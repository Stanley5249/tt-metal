# /// script
# requires-python = ">=3.12"
# dependencies = ["pydantic>=2"]
# ///
"""Merge upstream and the fork branch into the checked-out channel.

merge takes the channel's latest upstream tag, or --tag, then pins the ttsim
build for upstream's ttsim version, records the upstream base in pixi.toml, and
merges the fork branch. It builds nothing and pushes nothing. Exit status 2
means a merge conflict: resolve it, commit the merge, and run merge again.

check-infra fails when a fork-owned path differs from the fork commit that the
channel merged last. link-ttsim puts this tree's SOC descriptors beside the
ttsim libraries of the default environment.
"""

import argparse
import datetime as dt
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlparse

from pydantic import BaseModel, TypeAdapter

FORK_REPO = "Stanley5249/tt-metal"
UPSTREAM_REPO = "tenstorrent/tt-metal"
TTSIM_FORK = "Stanley5249/ttsim"
TTSIM_UPSTREAM = "tenstorrent/ttsim"
MANIFEST = Path("pixi.toml")
# Each channel merges the upstream line of the same name. Release candidates
# match neither pattern.
CHANNEL_TAGS = {
    "stable": re.compile(r"v\d+\.\d+\.\d+"),
    "main": re.compile(r"v\d+\.\d+\.\d+-dev\d+"),
}
VERSION = re.compile(r"v(\d+)\.(\d+)\.(\d+)(?:-dev(\d+))?")
FORK_WORKFLOWS = ".github/workflows/fork-"
# Upstream's version pins. A channel must build what its upstream tag names.
UPSTREAM_PINS = ("tt_metal/sfpi-version", "tt_metal/ttsim-version")
PIN_LINE = re.compile(r'^ttsim = \{ url = "[^"]*", sha256 = "[^"]*" \}$', re.MULTILINE)
SHA256 = re.compile(r"[0-9a-f]{64}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
# ttsim's daily release job builds a new upstream release within a day; past
# this window a missing build means that job failed or needs a manual run.
TTSIM_WAIT_HOURS = 48
# UMD reads soc_descriptor.yaml beside the ttsim library, and the package ships
# none. This tree owns the descriptors, because real hardware reads them too.
SOC_DESCRIPTORS = {"wh": "wormhole_b0_80_arch.yaml", "bh": "blackhole_140_arch.yaml"}
CONFLICT = 2


class ForkError(Exception):
    """A state that needs the maintainer, named with its fix."""


class ConflictError(Exception):
    """A merge stopped on conflicts and is still in progress."""


class Asset(BaseModel):
    """The release asset fields that the scripts check."""

    id: int
    name: str
    size: int
    digest: str | None


class Release(BaseModel):
    """A GitHub release from the REST API."""

    id: int
    tag_name: str
    draft: bool
    prerelease: bool
    immutable: bool
    target_commitish: str
    published_at: dt.datetime | None
    body: str | None
    assets: list[Asset]


class Activation(BaseModel):
    """The variables from pixi shell-hook --json."""

    environment_variables: dict[str, str]


class Workflow(BaseModel):
    """A registered workflow from gh workflow list."""

    path: str
    state: str


RELEASE_PAGES = TypeAdapter(list[list[Release]])
WORKFLOWS = TypeAdapter(list[Workflow])


@dataclass(frozen=True)
class TtsimBuild:
    """A published Stanley5249/ttsim build and its conda package digest."""

    tag: str
    sha256: str


@dataclass(frozen=True)
class Waiting:
    """The ttsim build for a new upstream version may still appear."""

    reason: str


# Every command goes through run or output. Their arguments are fixed tool
# names and values from git, GitHub, and the repository, never a shell, and the
# tools come from PATH, where pixi global installs them.


def run(*args: str | Path, env: dict[str, str] | None = None, cwd: Path | None = None, check: bool = True) -> int:
    """Run a command with its output on the terminal and return its exit status."""
    return subprocess.run(args, env=env, cwd=cwd, check=check).returncode  # noqa: S603 -- see above


def output(*args: str | Path, env: dict[str, str] | None = None) -> str:
    """Run a command and return its output without the trailing newline."""
    return subprocess.run(args, env=env, check=True, capture_output=True, text=True).stdout.strip()  # noqa: S603 -- see above


def activated(environment: str, **variables: str) -> dict[str, str]:
    """Return the variables that pixi run would set for environment, with variables applied first.

    Callers start the environment's binaries directly with these, instead of
    nesting pixi run, so they own the process they start.
    """
    base = os.environ | variables
    hook = output("pixi", "shell-hook", "--locked", "-e", environment, "--json", env=base)
    return base | Activation.model_validate_json(hook).environment_variables


def git(*args: str) -> str:
    """Run git and return its output."""
    return output("git", *args)


def is_ancestor(commit: str, descendant: str) -> bool:
    """Whether commit is in descendant's history."""
    return run("git", "merge-base", "--is-ancestor", commit, descendant, check=False) == 0


def differs(old: str, new: str, *paths: str) -> bool:
    """Whether paths differ between two commits."""
    return run("git", "diff", "--quiet", old, new, "--", *paths, check=False) != 0


def gh(*args: str) -> str:
    """Run gh and return its output, naming gh's error on failure."""
    try:
        return output("gh", *args)
    except subprocess.CalledProcessError as error:
        raise ForkError(f"gh {' '.join(args)} failed: {error.stderr.strip()}") from error


def releases(repo: str) -> list[Release]:
    """List every release of repo; drafts need push access."""
    pages = gh("api", f"repos/{repo}/releases?per_page=100", "--paginate", "--slurp")
    return [release for page in RELEASE_PAGES.validate_json(pages) for release in page]


def version_key(tag: str) -> tuple[int, int, int, float]:
    """Order upstream tags; a release sorts after its -dev tags."""
    match = VERSION.fullmatch(tag)
    if match is None:
        raise ForkError(f"{tag} is not an upstream version tag")
    major, minor, patch, dev = match.groups()
    return int(major), int(minor), int(patch), int(dev) if dev else float("inf")


def check_tag(channel: str, tag: str) -> None:
    """Refuse a tag from the other upstream line."""
    if not CHANNEL_TAGS[channel].fullmatch(tag):
        raise ForkError(f"{tag} is not an upstream {channel} tag")


def latest_tag(channel: str, upstream: list[Release]) -> str:
    """Pick the newest published upstream tag of the channel's line."""
    tags = [r.tag_name for r in upstream if not r.draft and CHANNEL_TAGS[channel].fullmatch(r.tag_name)]
    if not tags:
        raise ForkError(f"{UPSTREAM_REPO} has no published {channel} release in its latest 100")
    return max(tags, key=version_key)


def recorded_base(manifest: str) -> str:
    """Read the upstream tag that pixi.toml records as the base.

    git describe cannot name it: upstream's commit dates are out of order, so it
    can prefer an older tag over the one that was merged.
    """
    version = tomllib.loads(manifest)["workspace"]["version"]
    return "v" + version.replace(".dev", "-dev")


def record_base(manifest: str, tag: str) -> str:
    """Return pixi.toml with tag as its recorded base, in PEP 440 spelling."""
    version = tag.removeprefix("v").replace("-dev", ".dev")
    return re.sub(r'^version = ".*"$', f'version = "{version}"', manifest, count=1, flags=re.MULTILINE)


def ttsim_package(tag: str) -> str:
    """Name a build's conda package; conda spells -steps.N as +steps.N."""
    version, _, steps = tag.partition("-steps.")
    return f"ttsim-{version.removeprefix('v')}+steps.{steps}-0.conda"


def ttsim_url(tag: str) -> str:
    """Return the download URL of a build's conda package."""
    return f"https://github.com/{TTSIM_FORK}/releases/download/{tag}/{quote(ttsim_package(tag), safe='')}"


def steps_pattern(version: str) -> re.Pattern[str]:
    """Match the fork's patched builds of one upstream ttsim version."""
    return re.compile(rf"{re.escape(version)}-steps\.([1-9][0-9]*)")


def pinned_ttsim(manifest: str) -> tuple[str, str]:
    """Return the pinned ttsim build tag and sha256 in pixi.toml."""
    pin = tomllib.loads(manifest)["feature"]["runtime"]["dependencies"].get("ttsim")
    if not isinstance(pin, dict) or "url" not in pin or "sha256" not in pin:
        raise ForkError(f"{MANIFEST} has no ttsim pin with a url and sha256 in feature.runtime.dependencies")
    # The release tag is the URL's folder: .../releases/download/<tag>/<package>.
    tag = PurePosixPath(urlparse(pin["url"]).path).parent.name
    if pin["url"] != ttsim_url(tag):
        raise ForkError(f"{MANIFEST} pins {pin['url']}, not a {TTSIM_FORK} build")
    return tag, pin["sha256"]


def check_ttsim(manifest: str, version: str) -> None:
    """Require the pin to be a patched build of upstream's ttsim version."""
    tag, sha256 = pinned_ttsim(manifest)
    if not steps_pattern(version).fullmatch(tag):
        raise ForkError(f"{MANIFEST} pins ttsim {tag}, not a {version}-steps.N build")
    if not SHA256.fullmatch(sha256):
        raise ForkError(f"{MANIFEST} pins ttsim with sha256 {sha256!r}, not 64 hex digits")


def pin_ttsim(manifest: str, build: TtsimBuild) -> str:
    """Return pixi.toml pinned to build."""
    line = f'ttsim = {{ url = "{ttsim_url(build.tag)}", sha256 = "{build.sha256}" }}'
    updated, count = PIN_LINE.subn(line, manifest)
    if count != 1:
        raise ForkError(f"{MANIFEST} needs exactly one ttsim pin line, found {count}")
    return updated


def choose_build(
    version: str,
    pinned: str,
    fork: list[Release],
    upstream: list[Release],
    now: dt.datetime,
) -> TtsimBuild | Waiting | None:
    """Pick the patched ttsim build for upstream's ttsim version.

    None keeps the pinned build, which already builds version, even when a newer
    steps.N exists. Otherwise take the highest published steps.N, whose conda
    package must be non-empty with a digest, or wait for it within TTSIM_WAIT_HOURS.
    """
    if not VERSION.fullmatch(version):
        raise ForkError(f"tt_metal/ttsim-version holds {version!r}, not vX.Y.Z")
    steps = steps_pattern(version)
    if steps.fullmatch(pinned):
        return None
    published = [
        (int(m[1]), r) for r in fork if not r.draft and not r.prerelease and (m := steps.fullmatch(r.tag_name))
    ]
    if published:
        _, release = max(published, key=lambda pair: pair[0])
        asset = next((a for a in release.assets if a.name == ttsim_package(release.tag_name)), None)
        if asset is None or asset.size <= 0 or not DIGEST.fullmatch(asset.digest or ""):
            raise ForkError(
                f"{TTSIM_FORK} {release.tag_name} has no non-empty {ttsim_package(release.tag_name)} "
                "with a sha256 digest; fix or replace that release"
            )
        return TtsimBuild(release.tag_name, (asset.digest or "").removeprefix("sha256:"))
    formal = {r.tag_name: r for r in upstream if not r.draft and not r.prerelease and VERSION.fullmatch(r.tag_name)}
    if version not in formal:
        raise ForkError(f"{version} is not a published {TTSIM_UPSTREAM} release, so {TTSIM_FORK} cannot build it")
    highest = max(formal, key=version_key)
    dispatch = f"run {TTSIM_FORK}'s release workflow with tag {version}"
    if version != highest:
        raise ForkError(f"{TTSIM_FORK} has no {version}-steps.N, and {version} is older than {highest}; {dispatch}")
    published_at = formal[version].published_at
    if published_at is None or now - published_at > dt.timedelta(hours=TTSIM_WAIT_HOURS):
        raise ForkError(
            f"{TTSIM_FORK} has no {version}-steps.N {TTSIM_WAIT_HOURS} hours after "
            f"{TTSIM_UPSTREAM} published it; {dispatch}"
        )
    return Waiting(
        f"{TTSIM_FORK} has not released {version}-steps.N yet; {TTSIM_UPSTREAM} published it at {published_at}"
    )


def exposed_workflows(paths: list[str], workflows: list[Workflow]) -> list[str]:
    """Return the inherited workflow paths that GitHub has not disabled.

    A path that GitHub never registered is exposed too: it starts active once a
    push makes GitHub evaluate it.
    """
    disabled = {w.path for w in workflows if w.state != "active"}
    return [p for p in paths if not p.startswith(FORK_WORKFLOWS) and p not in disabled]


def check_workflows(commit: str) -> None:
    """Stop when a push or a new tag could run an inherited workflow."""
    paths = [
        p
        for p in git("ls-tree", "-r", "--name-only", commit, ".github/workflows").splitlines()
        if p.endswith((".yml", ".yaml"))
    ]
    listed = gh("workflow", "list", "-R", FORK_REPO, "--all", "-L", "1000", "--json", "path,state")
    exposed = exposed_workflows(paths, WORKFLOWS.validate_json(listed))
    if exposed:
        raise ForkError(
            "inherited workflows are not disabled on GitHub; fork/README.md says how to disable them "
            "before you push:\n  " + "\n  ".join(exposed)
        )


def require_clean() -> None:
    """Refuse uncommitted changes, but accept a submodule at an older recorded commit.

    The merge aligns such a submodule; its own edits would be lost.
    """
    if git("status", "--porcelain", "--ignore-submodules=all"):
        raise ForkError("commit or stash your changes first")
    if git("submodule", "foreach", "--quiet", "--recursive", "git status --porcelain --ignore-submodules=all"):
        raise ForkError("commit or stash your submodule changes first")


def check_forward(base: str, upstream: str) -> None:
    """Refuse an upstream tag that does not contain the recorded base."""
    if not is_ancestor(base, upstream):
        raise ForkError(f"{upstream} is not a forward upgrade from {base}")


def merge(rev: str, message: str) -> None:
    """Merge rev, telling a conflict, which leaves the merge in progress, from an error."""
    if run("git", "merge", "--no-stat", "-m", message, rev, check=False) == 0:
        return
    conflicts = git("diff", "--name-only", "--diff-filter=U")
    if not conflicts:
        raise ForkError(f"merging {rev} failed without conflicts; see the error above")
    raise ConflictError(conflicts)


def commit_file(text: str, message: str, *extra: str) -> None:
    """Write pixi.toml and commit it with extra paths, when it changed."""
    if text == MANIFEST.read_text():
        return
    MANIFEST.write_text(text, newline="\n")
    git("commit", "-q", "-m", message, "--", str(MANIFEST), *extra)


def sync(tag: str | None, fork: str) -> None:
    """Merge an upstream tag and the fork branch into the checked-out channel."""
    channel = git("branch", "--show-current")
    if channel not in CHANNEL_TAGS:
        raise ForkError(f"check out stable or main, not {channel or 'a detached HEAD'}")
    require_clean()
    tag = tag or latest_tag(channel, releases(UPSTREAM_REPO))
    check_tag(channel, tag)
    git("fetch", "-q", "--no-tags", "upstream", "tag", tag)
    upstream = git("rev-parse", f"{tag}^{{commit}}")
    base = recorded_base(MANIFEST.read_text())
    check_forward(base, tag)
    # Decide before merging, so a build that is still coming leaves no merge.
    ttsim_version = git("show", f"{upstream}:tt_metal/ttsim-version").strip()
    pinned, _ = pinned_ttsim(MANIFEST.read_text())
    build = None
    if not steps_pattern(ttsim_version).fullmatch(pinned):
        build = choose_build(
            ttsim_version, pinned, releases(TTSIM_FORK), releases(TTSIM_UPSTREAM), dt.datetime.now(dt.UTC)
        )
    if isinstance(build, Waiting):
        print(f"waiting: {build.reason}; run sync again later")
        return
    if not is_ancestor(upstream, "HEAD"):
        merge(upstream, f"Merge upstream {tag} into {channel}")
    if differs(upstream, "HEAD", *UPSTREAM_PINS):
        raise ForkError(f"{' and '.join(UPSTREAM_PINS)} must match {tag}; revert the fork's edits to them")
    git("submodule", "sync", "--quiet", "--recursive")
    run("git", "submodule", "update", "--init", "--recursive")
    if build is not None:
        MANIFEST.write_text(pin_ttsim(MANIFEST.read_text(), build), newline="\n")
        # Resolving editable ttnn runs setup.py, which needs a version;
        # pixi.lock records none, so any version works.
        run("pixi", "lock", env=os.environ | {"SETUPTOOLS_SCM_PRETEND_VERSION": "0.0.0"})
        git("commit", "-q", "-m", f"build: use ttsim {build.tag}", "--", str(MANIFEST), "pixi.lock")
    commit_file(record_base(MANIFEST.read_text(), tag), f"build: record upstream {tag}")
    check_ttsim(MANIFEST.read_text(), ttsim_version)
    if not is_ancestor(fork, "HEAD"):
        merge(fork, f"Merge fork into {channel}")
    check_workflows("HEAD")
    print(f"{channel} now holds upstream {tag} and fork; review, run just ci, then push:")
    print(f"  fork patches:   git diff {tag} HEAD -- . ':!tt_metal/sfpi-licenses' ':!fork' ':!pixi.*'")
    print(f"  upstream:       git diff {base} {tag}")
    print(f"  resolutions:    git show --cc $(git log --merges -1 --format=%H --grep='^Merge upstream {tag}')")


def check_infra(fork: str) -> None:
    """ForkError when HEAD's fork-owned paths differ from the fork commit it merged last."""
    try:
        base = git("merge-base", "HEAD", fork)
    except subprocess.CalledProcessError as error:
        raise ForkError(f"HEAD has not merged {fork}; run git merge {fork}") from error
    owned = git("ls-tree", "-r", "--name-only", base).splitlines()
    # New files under fork-owned paths count too, not only the files fork has.
    changed = git("diff", "--name-status", base, "HEAD", "--", *owned, "fork", f"{FORK_WORKFLOWS}*")
    if changed:
        raise ForkError(
            f"fork-owned paths differ from {fork} at {base[:11]}; commit the change on the fork branch "
            f"and merge it instead:\n{changed}"
        )


def link_ttsim(environment: str) -> None:
    """Link this tree's SOC descriptors beside the environment's ttsim libraries.

    A rename replaces the link in one step, so a running test never sees it
    missing, and it never writes through a package file, which can be a hard link
    into pixi's cache.
    """
    prefix = activated(environment)["CONDA_PREFIX"]
    for arch, name in SOC_DESCRIPTORS.items():
        target = Path.cwd() / "tt_metal/soc_descriptors" / name
        library = Path(prefix) / "lib/ttsim" / arch
        if not library.is_dir():
            raise ForkError(f"{library} is missing; the ttsim package changed its layout")
        link = library / "soc_descriptor.yaml"
        if link.is_symlink() and link.readlink() == target:
            continue
        staged = library / ".soc_descriptor.yaml.new"
        staged.unlink(missing_ok=True)
        staged.symlink_to(target)
        staged.replace(link)


def main() -> None:
    """Run one sync command."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    merging = commands.add_parser("merge", help="merge upstream and the fork branch")
    merging.add_argument("--tag", help="exact upstream tag instead of the latest")
    checking = commands.add_parser("check-infra", help="check fork-owned paths against the fork branch")
    for sub in (merging, checking):
        sub.add_argument("--fork", default="fork", help="the fork branch ref, such as origin/fork in CI")
    commands.add_parser("link-ttsim", help="link the SOC descriptors beside ttsim")
    args = parser.parse_args()
    try:
        if args.command == "merge":
            sync(args.tag, args.fork)
        elif args.command == "check-infra":
            check_infra(args.fork)
        else:
            link_ttsim("default")
    except ConflictError as conflict:
        print(f"Resolve these conflicts, commit the merge, then rerun:\n{conflict}", file=sys.stderr)
        sys.exit(CONFLICT)
    except ForkError as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as error:
        print(f"error: {' '.join(map(str, error.cmd))} failed: {(error.stderr or '').strip()}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
