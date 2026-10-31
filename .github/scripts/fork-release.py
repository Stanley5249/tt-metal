#!/usr/bin/env python3
"""Number, check, and publish fork releases for fork-release.yaml.

  manifest <dist> <sha>          record the built wheel and Tracy tools for sha
  check <dist> <sha>             require dist to match its manifest for sha
  plan <base> <sha> [--resume]   choose the release tag and what to do
  publish <tag> <sha> <dist> <notes>
                                 draft, verify, publish, and verify again
  published <tag> <sha>          verify a release published earlier

Each command prints Actions outputs. GitHub releases and the fork's tags are
the only state: a tag at sha is the intent to release sha, and a published
release is never changed. Only the stdlib, git, and the gh CLI are used.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

MANIFEST = "fork-manifest.json"
TRACY = "tracy-tools-linux_x86_64.tar.gz"
CONDA = re.compile(r"(v(\d+)\.(\d+)\.(\d+)(?:-dev(\d+))?)-conda\.([1-9][0-9]*)")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


class Fail(Exception):
    pass


def gh(*args):
    result = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise Fail(f"gh {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def repo():
    return os.environ["GH_REPO"]


def releases():
    """All releases, drafts included, which needs push access."""
    return [
        r
        for page in json.loads(gh("api", f"repos/{repo()}/releases?per_page=100", "--paginate", "--slurp"))
        for r in page
    ]


def tag_commit(tag):
    """The commit a remote tag points to, peeling an annotated tag."""
    obj = json.loads(gh("api", f"repos/{repo()}/git/ref/tags/{tag}"))["object"]
    if obj["type"] == "tag":
        obj = json.loads(gh("api", f"repos/{repo()}/git/tags/{obj['sha']}"))["object"]
    return obj["sha"]


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def manifest(dist, sha):
    wheels = sorted(p.name for p in Path(dist).glob("ttnn-*.whl"))
    if len(wheels) != 1:
        raise Fail(f"expected one ttnn wheel in {dist}, found {wheels}")
    assets = {}
    for name in [wheels[0], TRACY]:
        path = Path(dist) / name
        if not path.is_file() or path.stat().st_size == 0:
            raise Fail(f"{path} is missing or empty")
        assets[name] = {"size": path.stat().st_size, "sha256": sha256(path)}
    return {"sha": sha, "assets": assets}


def check(dist, sha):
    """Return the manifest after checking that it names sha and dist's files match it."""
    recorded = json.loads((Path(dist) / MANIFEST).read_text())
    if recorded.get("sha") != sha:
        raise Fail(f"artifacts were built from {recorded.get('sha')}, not {sha}")
    if manifest(dist, sha) != recorded:
        raise Fail(f"artifacts in {dist} differ from {MANIFEST}")
    return recorded


def plan(base, sha, tags, all_releases, resume):
    """Return {"action", "tag"}; action is build, notify, or none.

    tags maps the fork's conda tag names to their commits. A tag or a tagless
    draft at sha means a release of sha was started, so it is finished rather
    than numbered again. Without one, resume does nothing, and a new release
    takes the next number on base after every tag and release, drafts included.
    """
    by_tag = {r["tag_name"]: r for r in all_releases}
    at_sha = {t for t, commit in tags.items() if commit == sha and CONDA.fullmatch(t)}
    at_sha |= {
        r["tag_name"]
        for r in all_releases
        if r["draft"] and r["tag_name"] not in tags and r["target_commitish"] == sha and CONDA.fullmatch(r["tag_name"])
    }
    if len(at_sha) > 1:
        raise Fail(f"{sha} carries several release tags: {', '.join(sorted(at_sha))}; delete the unpublished extras")
    if at_sha:
        tag = at_sha.pop()
        if CONDA.fullmatch(tag)[1] != base:
            raise Fail(f"{sha} is released as {tag}, not on {base}")
        release = by_tag.get(tag)
        return {"action": "notify" if release and not release["draft"] else "build", "tag": tag}
    if resume:
        return {"action": "none", "tag": ""}
    # An unfinished release of another commit on this base would otherwise be
    # passed over and left behind by every new run.
    for t in sorted(tags):
        m = CONDA.fullmatch(t)
        if m and m[1] == base and t not in by_tag:
            raise Fail(f"{t} is tagged at {tags[t]} without a release; finish it there or delete the tag")
    for r in all_releases:
        m = CONDA.fullmatch(r["tag_name"])
        if m and m[1] == base and r["draft"]:
            raise Fail(f"draft {r['tag_name']} releases another commit; publish or delete it first")
    numbers = [int(m[6]) for t in [*tags, *by_tag] if (m := CONDA.fullmatch(t)) and m[1] == base]
    return {"action": "build", "tag": f"{base}-conda.{max(numbers, default=0) + 1}"}


def channel(tag):
    return "nightly" if CONDA.fullmatch(tag)[5] else "stable"


def newest(tag, all_releases):
    """Whether tag is newer than every other published release on its channel."""

    def key(t):
        m = CONDA.fullmatch(t)
        return tuple(int(x or 0) for x in m.group(2, 3, 4, 5, 6))

    others = [
        r["tag_name"]
        for r in all_releases
        if not r["draft"]
        and r["tag_name"] != tag
        and CONDA.fullmatch(r["tag_name"])
        and channel(r["tag_name"]) == channel(tag)
    ]
    return all(key(tag) > key(t) for t in others)


def verify(release, tag, sha, draft, expected=None):
    """Check one release against the tag, commit, state, and assets it must have."""
    if release["tag_name"] != tag or release["draft"] != draft:
        raise Fail(
            f"{release['tag_name']} is {'a draft' if release['draft'] else 'published'}, expected {tag} {'draft' if draft else 'published'}"
        )
    if release["prerelease"] != (channel(tag) == "nightly"):
        raise Fail(f"{tag} has prerelease={release['prerelease']} on the {channel(tag)} channel")
    target = release.get("target_commitish", "")
    if re.fullmatch(r"[0-9a-f]{40}", target) and target != sha:
        raise Fail(f"{tag} targets {target}, not {sha}")
    commit = tag_commit(tag)
    if commit != sha:
        raise Fail(f"tag {tag} points to {commit}, not {sha}")
    assets = {a["name"]: (a["size"], a.get("digest")) for a in release["assets"]}
    if expected is not None:
        wanted = {name: (a["size"], f"sha256:{a['sha256']}") for name, a in expected["assets"].items()}
        if assets != wanted:
            raise Fail(f"{tag} assets {assets} differ from the validated {wanted}")
        return
    wheels = [n for n in assets if n.startswith("ttnn-") and n.endswith(".whl")]
    if sorted(assets) != sorted([*wheels, TRACY]) or len(wheels) != 1:
        raise Fail(f"{tag} should carry one ttnn wheel and {TRACY}, not {sorted(assets)}")
    for name, (size, digest) in assets.items():
        if size <= 0 or not DIGEST.fullmatch(digest or ""):
            raise Fail(f"{tag} asset {name} is empty or has no sha256 digest")


def find(tag):
    return next((r for r in releases() if r["tag_name"] == tag), None)


def require(tag):
    release = find(tag)
    if release is None:
        raise Fail(f"{tag} has no release")
    return release


def publish(tag, sha, dist, notes):
    """Publish tag at sha with the validated assets in dist; return whether it is the channel's newest."""
    expected = check(dist, sha)
    files = [str(Path(dist) / name) for name in expected["assets"]]
    nightly = channel(tag) == "nightly"
    release = find(tag)
    if release and not release["draft"]:
        raise Fail(f"{tag} is already published; it never changes")
    if release:
        # A draft is not public yet, so a partial upload may be replaced, but
        # its notes stay: git-cliff cannot regenerate them once the tag exists.
        for asset in release["assets"]:
            if asset["name"] not in expected["assets"]:
                gh("api", "-X", "DELETE", f"repos/{repo()}/releases/assets/{asset['id']}")
        gh("release", "upload", tag, "--clobber", *files)
        fields = ["-F", f"prerelease={str(nightly).lower()}"]
        if not release["body"]:
            fields += ["-F", f"body=@{notes}"]
        gh("api", "-X", "PATCH", f"repos/{repo()}/releases/{release['id']}", *fields)
    else:
        flags = ["--prerelease"] if nightly else []
        gh("release", "create", tag, "--verify-tag", "--draft", "--title", tag, "--notes-file", notes, *flags, *files)
    release = require(tag)
    verify(release, tag, sha, draft=True, expected=expected)
    latest = newest(tag, releases())
    # A backfilled stable release must not take GitHub's latest label from a
    # newer one; nightly releases never take it.
    make_latest = "true" if latest and not nightly else "false"
    gh(
        "api",
        "-X",
        "PATCH",
        f"repos/{repo()}/releases/{release['id']}",
        "-F",
        "draft=false",
        "-f",
        f"make_latest={make_latest}",
    )
    # Read the release again, so the summary reports what GitHub serves.
    verify(require(tag), tag, sha, draft=False, expected=expected)
    return latest


def published(tag, sha):
    verify(require(tag), tag, sha, draft=False)
    return newest(tag, releases())


def local_tags():
    out = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname:strip=2) %(objectname) %(*objectname)", "refs/tags/v*-conda.*"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    tags = {}
    for line in out.splitlines():
        name, obj, *peeled = line.split()
        tags[name] = peeled[0] if peeled else obj
    return tags


def main(argv):
    command, args = argv[1] if len(argv) > 1 else "", argv[2:]
    try:
        if command == "manifest" and len(args) == 2:
            data = manifest(*args)
            (Path(args[0]) / MANIFEST).write_text(json.dumps(data, indent=2) + "\n")
            for name, asset in data["assets"].items():
                print(f"{asset['sha256']}  {name}")
        elif command == "check" and len(args) == 2:
            check(*args)
        elif command == "plan" and len(args) in (2, 3) and args[2:] in ([], ["--resume"]):
            result = plan(args[0], args[1], local_tags(), releases(), resume=bool(args[2:]))
            print(f"action={result['action']}\ntag={result['tag']}")
        elif command == "publish" and len(args) == 4:
            print(f"latest={str(publish(*args)).lower()}")
        elif command == "published" and len(args) == 2:
            print(f"latest={str(published(*args)).lower()}")
        else:
            print(__doc__.split("\n\n")[1], file=sys.stderr)
            return 2
    except Fail as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
