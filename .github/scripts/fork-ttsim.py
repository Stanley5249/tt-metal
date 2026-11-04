#!/usr/bin/env python3
"""Pick, pin, and check the patched ttsim build for an upstream ttsim pin.

Usage:
  fork-ttsim.py pick <ttsim version>
  fork-ttsim.py pin <release> <sha256>
  fork-ttsim.py check <ttsim version>

pick prints Actions-style lines: result=ready, release=<version>-steps.N, and
the sha256 of its conda package when the build is published, or result=waiting
and a reason when the build may still appear. pin rewrites the ttsim pin in
pixi.toml. check verifies that the pin is a build of the given version. Any
other state exits with status 1 and a message that names the fix. Only the
stdlib and the gh CLI are used, so a local pick needs `gh auth login`.
"""

import datetime
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from urllib.parse import quote

UPSTREAM = "tenstorrent/ttsim"
FORK = "Stanley5249/ttsim"
MANIFEST = Path("pixi.toml")
VERSION = re.compile(r"v(\d+)\.(\d+)\.(\d+)")
# The x86 libraries that every build must carry; the conda package holds the same files.
ASSETS = ("libttsim_wh.so", "libttsim_bh.so")
PIN_LINE = re.compile(r'^ttsim = \{ url = "[^"]*", sha256 = "[^"]*" \}$', re.MULTILINE)
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
SHA256 = re.compile(r"[0-9a-f]{64}")
# ttsim's daily release job builds a new upstream release within a day; past
# this window a missing build means that job failed or needs a manual run.
WAIT_HOURS = 48


class Fail(Exception):
    pass


def key(tag):
    return tuple(int(x) for x in VERSION.fullmatch(tag).groups())


def steps_pattern(version):
    return re.compile(rf"{re.escape(version)}-steps\.([1-9][0-9]*)")


def package(tag):
    # Conda versions cannot contain -, so the package spells -steps.N as +steps.N.
    version, _, steps = tag.partition("-steps.")
    return f"ttsim-{version.removeprefix('v')}+steps.{steps}-0.conda"


def package_url(tag):
    return f"https://github.com/{FORK}/releases/download/{tag}/{quote(package(tag), safe='')}"


def decide(fork, version, fork_releases, upstream_releases, now):
    """Return ("ready", tag, sha256) or ("waiting", reason). Raise Fail otherwise."""
    if not VERSION.fullmatch(version):
        raise Fail(f"tt_metal/ttsim-version holds {version!r}, not vX.Y.Z")
    steps = steps_pattern(version)
    published = [
        (int(m[1]), r)
        for r in fork_releases
        if not r["draft"] and not r["prerelease"] and (m := steps.fullmatch(r["tag_name"]))
    ]
    if published:
        _, release = max(published, key=lambda pair: pair[0])
        tag = release["tag_name"]
        assets = {a["name"]: a for a in release["assets"]}
        for name in (*ASSETS, package(tag)):
            asset = assets.get(name)
            if not asset or asset["size"] <= 0 or not DIGEST.fullmatch(asset.get("digest") or ""):
                raise Fail(f"{fork} {tag} has no non-empty {name} with a sha256 digest; fix or replace that release")
        return "ready", tag, assets[package(tag)]["digest"].removeprefix("sha256:")
    formal = {
        r["tag_name"]: r
        for r in upstream_releases
        if not r["draft"] and not r["prerelease"] and VERSION.fullmatch(r["tag_name"])
    }
    if version not in formal:
        raise Fail(f"{version} is not a published, non-prerelease {UPSTREAM} release, so {fork} cannot build it")
    highest = max(formal, key=key)
    dispatch = f"run {fork}'s release workflow with tag {version}"
    if version != highest:
        raise Fail(f"{fork} has no published {version}-steps.N, and {version} is older than {highest}; {dispatch}")
    published_at = datetime.datetime.fromisoformat(formal[version]["published_at"].replace("Z", "+00:00"))
    if now - published_at > datetime.timedelta(hours=WAIT_HOURS):
        raise Fail(
            f"{fork} has no published {version}-steps.N {WAIT_HOURS} hours after {UPSTREAM} published it; {dispatch}"
        )
    return (
        "waiting",
        f"{fork} has not released {version}-steps.N yet; {UPSTREAM} published {version} at {published_at:%Y-%m-%d %H:%M} UTC",
    )


def releases(repo):
    result = subprocess.run(
        ["gh", "api", f"repos/{repo}/releases?per_page=100", "--paginate", "--slurp"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise Fail(f"cannot list {repo} releases: {result.stderr.strip()}")
    return [r for page in json.loads(result.stdout) for r in page]


def pin(release, sha256):
    version = release.partition("-steps.")[0]
    if not VERSION.fullmatch(version) or not steps_pattern(version).fullmatch(release):
        raise Fail(f"{release} is not a vX.Y.Z-steps.N build")
    if not SHA256.fullmatch(sha256):
        raise Fail(f"{sha256!r} is not 64 hex digits")
    source = MANIFEST.read_text()
    new = f'ttsim = {{ url = "{package_url(release)}", sha256 = "{sha256}" }}'
    updated, count = PIN_LINE.subn(new, source)
    if count != 1:
        raise Fail(f"{MANIFEST} needs exactly one ttsim pin line, found {count}")
    MANIFEST.write_text(updated)


def check(version):
    pinned = tomllib.loads(MANIFEST.read_text())["feature"]["runtime"]["dependencies"].get("ttsim")
    if not isinstance(pinned, dict) or "url" not in pinned or "sha256" not in pinned:
        raise Fail(f"{MANIFEST} has no ttsim pin with a url and sha256 in feature.runtime.dependencies")
    parts = pinned["url"].rsplit("/", 2)
    tag = parts[-2] if len(parts) == 3 else ""
    if not steps_pattern(version).fullmatch(tag) or pinned["url"] != package_url(tag):
        raise Fail(f"{MANIFEST} pins {pinned['url']}, not a {version}-steps.N build of ttsim {version} from {FORK}")
    if not SHA256.fullmatch(pinned["sha256"]):
        raise Fail(f"{MANIFEST} pins ttsim with sha256 {pinned['sha256']!r}, not 64 hex digits")


def run(command, args):
    if command == "pick":
        now = datetime.datetime.now(datetime.timezone.utc)
        decision = decide(FORK, args[0], releases(FORK), releases(UPSTREAM), now)
        print(f"result={decision[0]}")
        if decision[0] == "ready":
            print(f"release={decision[1]}\nsha256={decision[2]}")
        else:
            print(f"reason={decision[1]}")
    elif command == "pin":
        pin(*args)
    else:
        check(*args)


def main(argv):
    arity = {"pick": 1, "pin": 2, "check": 1}
    if len(argv) < 2 or arity.get(argv[1]) != len(argv) - 2:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    try:
        run(argv[1], argv[2:])
    except Fail as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
