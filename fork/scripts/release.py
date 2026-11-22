# /// script
# requires-python = ">=3.12"
# dependencies = ["pydantic>=2"]
# ///
"""Prepare and publish a fork release of HEAD.

prepare numbers the release, builds and packages HEAD, smoke-tests the wheel on
the Wormhole and Blackhole simulators, and writes dist/<tag>/ with the assets,
their manifest, the smoke logs, and notes.md for review. publish sends that
folder's assets and notes to GitHub. GitHub releases and the fork's tags are
the only state: a draft or tag at HEAD resumes its release, and a published
release never changes.
"""

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, TypeAdapter
from sync import (
    FORK_REPO,
    MANIFEST,
    UPSTREAM_PINS,
    Asset,
    ForkError,
    Release,
    activated,
    check_ttsim,
    check_workflows,
    differs,
    gh,
    git,
    is_ancestor,
    link_ttsim,
    recorded_base,
    releases,
    require_clean,
    run,
)

UPSTREAM_URL = "https://github.com/tenstorrent/tt-metal.git"
CONDA = re.compile(r"(v(\d+)\.(\d+)\.(\d+)(?:-dev(\d+))?)-conda\.([1-9][0-9]*)")
DIST = Path("dist")
ASSET_GLOBS = ("ttnn-*.whl", "tt-metal-*.conda")
SCRIPTS = Path(__file__).resolve().parent
CLIFF = SCRIPTS.parent / "cliff.toml"
RECIPE = SCRIPTS.parent / "conda/recipe.yaml"
# What a release must ship beside ttnn: the Tracy tools and viewer, the SFPI
# compiler, and the license texts of both.
WHEEL_FILES = (
    "ttnn/build/tools/profiler/bin/tracy-capture",
    "ttnn/build/tools/profiler/bin/tracy-csvexport",
    "ttnn/build/profiler/build_wasm/index.html",
    "ttnn/build/profiler/build_wasm/favicon.svg",
    "ttnn/build/profiler/build_wasm/tracy-profiler.js",
    "ttnn/build/profiler/build_wasm/tracy-profiler.wasm",
    "ttnn/build/profiler/licenses/tracy/LICENSE",
    "ttnn/build/profiler/licenses/tracy/public/libbacktrace/LICENSE",
    "ttnn/runtime/sfpi/compiler/bin/riscv-tt-elf-g++",
    "ttnn/runtime/sfpi/compiler/bin/riscv-tt-elf-as",
    "ttnn/runtime/sfpi/compiler/bin/riscv-tt-elf-ld",
    "ttnn/runtime/sfpi/LICENSE",
    "ttnn/runtime/sfpi/COPYING3",
    "ttnn/runtime/sfpi/COPYING3.LIB",
    "ttnn/runtime/sfpi/COPYING.NEWLIB",
    "ttnn/runtime/sfpi/COPYING.RUNTIME",
)


class AssetFile(BaseModel):
    """One built asset's size and digest."""

    size: int
    sha256: str


class Manifest(BaseModel):
    """Ties a prepared release's assets to its tag and commit."""

    tag: str
    sha: str
    assets: dict[str, AssetFile]


class TagRef(BaseModel):
    """One ref from the git matching-refs API."""

    class Target(BaseModel):
        """The object a ref names."""

        sha: str
        type: str

    ref: str
    object: Target


TAG_REFS = TypeAdapter(list[list[TagRef]])


@dataclass(frozen=True)
class Plan:
    """What a release of HEAD needs: build and publish tag, or nothing."""

    tag: str
    action: Literal["build", "published"]


def channel(tag: str) -> Literal["stable", "main"]:
    """Name the channel that a fork or upstream tag belongs to."""
    return "main" if "-dev" in tag else "stable"


def wheel_version(tag: str) -> str:
    """Return the wheel's PEP 440 version: -devN as .devN, and +conda.N."""
    match = CONDA.fullmatch(tag)
    if match is None:
        raise ForkError(f"{tag} is not a fork release tag")
    return f"{match[1].removeprefix('v').replace('-dev', '.dev')}+conda.{match[6]}"


def plan(base: str, head: str, tags: dict[str, str], known: list[Release]) -> Plan:
    """Choose the release tag for head on base.

    tags maps the fork's tag names to their commits. A tag or a draft at head
    resumes that release. Any other unfinished release on base stops, so none is
    left behind silently. A new release takes the next number on base after
    every tag and release, drafts included.
    """
    by_tag = {r.tag_name: r for r in known}
    at_head = {t for t, commit in tags.items() if commit == head and CONDA.fullmatch(t)}
    at_head |= {r.tag_name for r in known if r.draft and r.target_commitish == head and CONDA.fullmatch(r.tag_name)}
    if len(at_head) > 1:
        raise ForkError(f"{head} carries several releases: {', '.join(sorted(at_head))}; investigate them")
    if at_head:
        tag = at_head.pop()
        if not tag.startswith(f"{base}-conda."):
            raise ForkError(f"{head} is released as {tag}, not on {base}")
        release = by_tag.get(tag)
        return Plan(tag, "published" if release and not release.draft else "build")
    on_base = [m for t in [*tags, *by_tag] if (m := CONDA.fullmatch(t)) and m[1] == base]
    for m in on_base:
        release = by_tag.get(m[0])
        if release is None:
            raise ForkError(f"{m[0]} is tagged at {tags[m[0]]} without a release; investigate before releasing again")
        if release.draft:
            raise ForkError(f"draft {m[0]} releases {release.target_commitish}; publish or delete it first")
    number = max((int(m[6]) for m in on_base), default=0) + 1
    return Plan(f"{base}-conda.{number}", "build")


def compare(manifest: Manifest, assets: list[Asset]) -> None:
    """Require GitHub's assets to be exactly the manifest's names, sizes, and digests."""
    found = {a.name: (a.size, a.digest) for a in assets}
    wanted = {name: (a.size, f"sha256:{a.sha256}") for name, a in manifest.assets.items()}
    if found != wanted:
        raise ForkError(f"{manifest.tag} assets {found} differ from the prepared {wanted}")


def newest(tag: str, known: list[Release]) -> bool:
    """Whether tag is newer than every other published release on its channel."""

    def key(t: str) -> tuple[int, ...]:
        match = CONDA.fullmatch(t)
        if match is None:
            raise ForkError(f"{t} is not a fork release tag")
        return tuple(int(x or 0) for x in match.group(2, 3, 4, 5, 6))

    others = [
        r.tag_name
        for r in known
        if not r.draft and r.tag_name != tag and CONDA.fullmatch(r.tag_name) and channel(r.tag_name) == channel(tag)
    ]
    return all(key(tag) > key(t) for t in others)


def sha256(path: Path) -> str:
    """Hash a file in blocks."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def manifest_of(folder: Path, tag: str, head: str) -> Manifest:
    """Record the one wheel and one conda package in folder."""
    assets = {}
    for pattern in ASSET_GLOBS:
        found = sorted(folder.glob(pattern))
        if len(found) != 1 or found[0].stat().st_size == 0:
            raise ForkError(f"expected one non-empty {pattern} in {folder}, found {[p.name for p in found]}")
        assets[found[0].name] = AssetFile(size=found[0].stat().st_size, sha256=sha256(found[0]))
    return Manifest(tag=tag, sha=head, assets=assets)


def remote_tags() -> dict[str, str]:
    """Map the fork's release tags on GitHub to their commits."""
    pages = gh("api", f"repos/{FORK_REPO}/git/matching-refs/tags/v", "--paginate", "--slurp")
    tags = {}
    for ref in (ref for page in TAG_REFS.validate_json(pages) for ref in page):
        name = ref.ref.removeprefix("refs/tags/")
        if CONDA.fullmatch(name):
            sha = ref.object.sha
            if ref.object.type == "tag":
                sha = gh("api", f"repos/{FORK_REPO}/git/tags/{sha}", "--jq", ".object.sha").strip()
            tags[name] = sha
    return tags


def checked_base(head: str) -> str:
    """Return the upstream base recorded at head, after checking upstream's pins."""
    base = recorded_base(git("show", f"{head}:{MANIFEST}"))
    if not git("tag", "--list", base):
        # A fork clone carries only fork tags.
        git("fetch", "-q", "--no-tags", UPSTREAM_URL, "tag", base)
    if not is_ancestor(base, head):
        raise ForkError(f"pixi.toml names {base}, which {head} does not contain")
    if differs(base, head, *UPSTREAM_PINS):
        raise ForkError(f"{' and '.join(UPSTREAM_PINS)} must match {base}")
    check_ttsim(git("show", f"{head}:{MANIFEST}"), git("show", f"{head}:tt_metal/ttsim-version").strip())
    return base


def build_wheel(folder: Path, version: str) -> None:
    """Package the current build as a ttnn wheel without compiling it again."""
    work = Path("build_wheel").resolve()
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    # setuptools writes into build/, which links to build_Release.
    config = work / "setup.cfg"
    config.write_text(f"[build]\nbuild_base = {work / 'build'}\n[egg_info]\negg_base = {work}\n", newline="\n")
    # uv installs tt-metal's build requirements in isolation and builds for the
    # default environment's Python, which ttnn was compiled against.
    python = Path(activated("default")["CONDA_PREFIX"]) / "bin/python"
    env = os.environ | {
        "TT_FROM_PRECOMPILED_DIR": str(Path.cwd()),
        "SETUPTOOLS_SCM_PRETEND_VERSION": version,
        "DIST_EXTRA_CONFIG": str(config),
    }
    run("uv", "build", "--wheel", "--python", python, "--out-dir", folder, ".", env=env)


def build_conda(folder: Path, version: str) -> None:
    """Build the tt-metal metapackage with the wheel's version."""
    work = Path("build_conda").resolve()
    shutil.rmtree(work, ignore_errors=True)
    env = os.environ | {"TT_METAL_VERSION": version}
    run("rattler-build", "build", "--recipe", RECIPE, "--output-dir", work, env=env)
    for package in (work / "noarch").glob("tt-metal-*.conda"):
        shutil.copy2(package, folder)


def missing_files(names: list[str]) -> list[str]:
    """Return the WHEEL_FILES that a wheel listing lacks."""
    return [name for name in WHEEL_FILES if name not in names]


def smoke(folder: Path, wheel: Path) -> None:
    """Check the wheel's files, then install it and run smoke.py on the Wormhole simulator.

    tt-scope owns profiler capture tests, so this checks only that the
    packages install and work. rattler-build has already installed the conda
    package in a fresh environment and run the recipe's tests.
    """
    with zipfile.ZipFile(wheel) as archive:
        missing = missing_files(archive.namelist())
    if missing:
        raise ForkError(f"{wheel.name} lacks: {', '.join(missing)}")
    run("pixi", "install", "--locked", "-e", "wheel")
    link_ttsim("wheel")
    env = activated("wheel", TTSIM_ARCH="wh")
    python = Path(env["CONDA_PREFIX"]) / "bin/python"
    # Reinstall, because a resumed release keeps the same version.
    run("uv", "pip", "install", "--python", python, "--reinstall-package", "ttnn", wheel)
    # conda links lib/python3.1 to lib/python3.12, so one folder appears twice.
    (home,) = {path.resolve() for path in python.parent.parent.glob("lib/python3.*/site-packages/ttnn/")}
    # Point tt-metal at the wheel, as a consumer does, and run outside the
    # checkout, whose models/ and ttnn/ folders would shadow the wheel's. A
    # process of its own, because it opens a device in another environment.
    env |= {"TT_METAL_HOME": str(home), "TT_METAL_RUNTIME_ROOT": f"{home}/"}
    run(python, SCRIPTS / "smoke.py", env=env, cwd=folder.resolve())


def write_notes(path: Path, tag: str, base: str, head: str) -> None:
    """Write notes for head's commits since base that no earlier fork release listed.

    After a sync, earlier releases sit on the old base inside the range, so
    git-cliff skips their tags by name.
    """
    released = [t for t in git("tag", "--merged", head, "--list", "v*-conda.*").split() if t != tag]
    try:
        previous = git("describe", "--tags", "--abbrev=0", "--match", "v*-conda.*", "--exclude", tag, head)
    except subprocess.CalledProcessError:
        previous = ""  # The channel's first fork release on any base.
    env = os.environ | {
        "GIT_CLIFF_SKIP_TAGS": "^(" + "|".join(map(re.escape, released)) + ")$",
        "UPSTREAM_BASE": base,
        "PREVIOUS_RELEASE": previous,
    }
    base_commit = git("rev-parse", f"{base}^{{commit}}")
    run("git-cliff", "--config", CLIFF, "--offline", "--tag", tag, "--output", path, f"{base_commit}..{head}", env=env)
    # An upstream-only merge may leave no conventional commits, so git-cliff
    # can write nothing even with render_always.
    if not path.read_text().strip():
        lines = [
            (
                f"Built from tt-metal [{base}](https://github.com/tenstorrent/tt-metal/releases/tag/{base}). "
                f"[fork/README.md](https://github.com/{FORK_REPO}/blob/{tag}/fork/README.md) lists the patches."
            ),
        ]
        if previous:
            compare_url = f"https://github.com/{FORK_REPO}/compare/{previous}...{tag}"
            lines += ["", f"**Full Changelog**: [{previous}...{tag}]({compare_url})"]
        path.write_text("\n".join(lines) + "\n", newline="\n")


def prepare() -> None:
    """Package and smoke-test the build of HEAD into dist/<tag>/.

    `just release` builds first, so this script starts no build.
    """
    require_clean()
    head = git("rev-parse", "HEAD")
    base = checked_base(head)
    tags = remote_tags()
    # git-cliff and the notes range read the fork's tags locally.
    missing = [f"refs/tags/{t}:refs/tags/{t}" for t in tags if not git("tag", "--list", t)]
    if missing:
        git("fetch", "-q", "--no-tags", "origin", *missing)
    step = plan(base, head, tags, releases(FORK_REPO))
    if step.action == "published":
        print(f"{step.tag} already publishes {head}; nothing to prepare")
        return
    folder = DIST / step.tag
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    version = wheel_version(step.tag)
    build_wheel(folder, version)
    build_conda(folder, version)
    manifest = manifest_of(folder, step.tag, head)
    wheel = folder / next(name for name in manifest.assets if name.endswith(".whl"))
    smoke(folder, wheel)
    write_notes(folder / "notes.md", step.tag, base, head)
    (folder / "fork-manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n", newline="\n")
    print(f"Prepared {step.tag} at {head} in {folder}:")
    for name, asset in manifest.assets.items():
        print(f"  {asset.sha256}  {name}")
    print(f"Review and edit {folder / 'notes.md'}, push HEAD, then run just publish")


def prepared(head: str) -> tuple[Path, Manifest]:
    """Find the dist/<tag>/ folder prepared for head and check its files."""
    found = [
        (path.parent, manifest)
        for path in DIST.glob("*/fork-manifest.json")
        if (manifest := Manifest.model_validate_json(path.read_text())).sha == head
    ]
    if len(found) != 1:
        raise ForkError(f"expected one dist/<tag>/ prepared for {head}, found {[str(f) for f, _ in found]}")
    folder, manifest = found[0]
    if manifest_of(folder, manifest.tag, head) != manifest:
        raise ForkError(f"the assets in {folder} differ from its fork-manifest.json")
    return folder, manifest


def verify(release: Release, manifest: Manifest, *, draft: bool) -> None:
    """Check a release's tag, state, target, and assets."""
    tag = manifest.tag
    if release.tag_name != tag or release.draft != draft:
        raise ForkError(f"{release.tag_name} has draft={release.draft}, expected {tag} with draft={draft}")
    if release.prerelease != (channel(tag) == "main"):
        raise ForkError(f"{tag} has prerelease={release.prerelease} on the {channel(tag)} channel")
    if release.target_commitish != manifest.sha:
        raise ForkError(f"{tag} targets {release.target_commitish}, not {manifest.sha}")
    compare(manifest, release.assets)
    if not draft:
        commit = remote_tags().get(tag)
        if commit != manifest.sha:
            raise ForkError(f"tag {tag} points to {commit}, not {manifest.sha}")
        if not release.immutable:
            raise ForkError(f"{tag} is not immutable; enable immutable releases for {FORK_REPO}")


def find(tag: str) -> Release:
    """Read one release, drafts included."""
    release = next((r for r in releases(FORK_REPO) if r.tag_name == tag), None)
    if release is None:
        raise ForkError(f"{tag} has no release")
    return release


def publish() -> None:
    """Publish the release prepared for HEAD with its reviewed notes."""
    head = git("rev-parse", "HEAD")
    folder, manifest = prepared(head)
    tag = manifest.tag
    notes = folder / "notes.md"
    if not notes.is_file() or not notes.read_text().strip():
        raise ForkError(f"{notes} is missing or empty")
    # The tag goes on a commit that the channel already holds.
    status = gh("api", f"repos/{FORK_REPO}/compare/{channel(tag)}...{head}", "--jq", ".status").strip()
    if status not in {"identical", "behind"}:
        raise ForkError(f"origin/{channel(tag)} does not contain {head}; push it first")
    # A new tag can trigger inherited tag workflows.
    check_workflows(head)
    known = releases(FORK_REPO)
    step = plan(recorded_base(git("show", f"{head}:{MANIFEST}")), head, remote_tags(), known)
    if step.tag != tag:
        raise ForkError(f"{folder} holds {tag}, but GitHub now needs {step.tag}; run just release again")
    if step.action == "published":
        verify(find(tag), manifest, draft=False)
        print(f"{tag} already publishes {head} with the prepared assets")
        return
    files = [str(folder / name) for name in manifest.assets]
    prerelease = channel(tag) == "main"
    draft = next((r for r in known if r.tag_name == tag), None)
    if draft is None:
        flags = ["--prerelease"] if prerelease else []
        gh(
            "release",
            "create",
            tag,
            "-R",
            FORK_REPO,
            "--target",
            head,
            "--draft",
            "--title",
            tag,
            "--notes-file",
            str(notes),
            *flags,
            *files,
        )
    else:
        # A draft is not public yet, so a partial upload may be replaced.
        for asset in draft.assets:
            if asset.name not in manifest.assets:
                gh("api", "-X", "DELETE", f"repos/{FORK_REPO}/releases/assets/{asset.id}")
        gh("release", "upload", tag, "-R", FORK_REPO, "--clobber", *files)
        gh(
            "release",
            "edit",
            tag,
            "-R",
            FORK_REPO,
            f"--prerelease={str(prerelease).lower()}",
            "--notes-file",
            str(notes),
        )
    release = find(tag)
    verify(release, manifest, draft=True)
    # A backfilled stable release must not take GitHub's latest label from a
    # newer one; main's releases never take it.
    latest = newest(tag, releases(FORK_REPO)) and not prerelease
    path = f"repos/{FORK_REPO}/releases/{release.id}"
    gh("api", "-X", "PATCH", path, "-F", "draft=false", "-f", f"make_latest={str(latest).lower()}")
    verify(find(tag), manifest, draft=False)
    print(f"Published {tag} at {head}: https://github.com/{FORK_REPO}/releases/tag/{tag}")


def main() -> None:
    """Run one release step."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("prepare", "publish"))
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            prepare()
        else:
            publish()
    except ForkError as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as error:
        print(f"error: {' '.join(map(str, error.cmd))} exited with {error.returncode}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
