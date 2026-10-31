#!/usr/bin/env python3
"""Pick the patched ttsim build for an upstream ttsim pin.

Usage: fork-ttsim.py <fork repo> <ttsim version>

Prints Actions-style lines: result=ready and release=<version>-steps.N when the
fork repository has published a build, or result=waiting and a reason when the
build may still appear. Any other state exits with status 1 and a message that
names the fix. Only the stdlib and the gh CLI are used, so a local run needs
`gh auth login`.
"""

import datetime
import json
import re
import subprocess
import sys

UPSTREAM = "tenstorrent/ttsim"
VERSION = re.compile(r"v(\d+)\.(\d+)\.(\d+)")
# The x86 libraries that smoke tests and `just fetch-ttsim` download.
ASSETS = ("libttsim_wh.so", "libttsim_bh.so")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
# ttsim's daily release job builds a new upstream release within a day; past
# this window a missing build means that job failed or needs a manual run.
WAIT_HOURS = 48


class Fail(Exception):
    pass


def key(tag):
    return tuple(int(x) for x in VERSION.fullmatch(tag).groups())


def decide(fork, version, fork_releases, upstream_releases, now):
    """Return (result, detail): ("ready", tag) or ("waiting", reason). Raise Fail otherwise."""
    if not VERSION.fullmatch(version):
        raise Fail(f"tt_metal/ttsim-version holds {version!r}, not vX.Y.Z")
    steps = re.compile(rf"{re.escape(version)}-steps\.([1-9][0-9]*)")
    published = [
        (int(m[1]), r)
        for r in fork_releases
        if not r["draft"] and not r["prerelease"] and (m := steps.fullmatch(r["tag_name"]))
    ]
    if published:
        _, release = max(published, key=lambda pair: pair[0])
        tag = release["tag_name"]
        assets = {a["name"]: a for a in release["assets"]}
        for name in ASSETS:
            asset = assets.get(name)
            if not asset or asset["size"] <= 0 or not DIGEST.fullmatch(asset.get("digest") or ""):
                raise Fail(f"{fork} {tag} has no non-empty {name} with a sha256 digest; fix or replace that release")
        return "ready", tag
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


def main(argv):
    if len(argv) != 3:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    fork, version = argv[1], argv[2]
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        result, detail = decide(fork, version, releases(fork), releases(UPSTREAM), now)
    except Fail as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"result={result}")
    print(f"release={detail}" if result == "ready" else f"reason={detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
