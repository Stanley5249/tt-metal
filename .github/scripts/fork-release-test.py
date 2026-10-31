#!/usr/bin/env python3
"""Exercise fork release numbering, publication, and ttsim build selection
against an in-memory GitHub, with no network or builds."""

import copy
import datetime
import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = load("fork-release")
ttsim = load("fork-ttsim")
A, B = "a" * 40, "b" * 40


def published(tag, draft=False, target="stable"):
    return {
        "id": 0,
        "tag_name": tag,
        "draft": draft,
        "prerelease": "-dev" in tag,
        "target_commitish": target,
        "body": "",
        "assets": [],
    }


class FakeGitHub:
    """Answers the gh calls fork-release.py makes and records the writes."""

    def __init__(self, tags=None, releases=()):
        self.tags = dict(tags or {})
        self.releases = [copy.deepcopy(r) | {"id": i + 1} for i, r in enumerate(releases)]
        self.writes = []
        self.corrupt = False

    def find(self, tag):
        return next(r for r in self.releases if r["tag_name"] == tag)

    def assets(self, files):
        result = []
        for path in files:
            data = Path(path).read_bytes()
            digest = hashlib.sha256(b"corrupt" if self.corrupt else data).hexdigest()
            result.append({"id": hash(path), "name": Path(path).name, "size": len(data), "digest": f"sha256:{digest}"})
        return result

    def __call__(self, *args):
        args = [str(a) for a in args]
        if args[:2] == ["api", "repos/o/r/releases?per_page=100"]:
            return json.dumps([copy.deepcopy(self.releases)])
        if args[0] == "api" and args[1].startswith("repos/o/r/git/ref/tags/"):
            tag = args[1].rsplit("/", 1)[1]
            if tag not in self.tags:
                raise release.Fail("HTTP 404")
            return json.dumps({"object": {"type": "commit", "sha": self.tags[tag]}})
        self.writes.append(args)
        if args[:3] == ["api", "-X", "DELETE"]:
            asset = int(args[3].rsplit("/", 1)[1])
            for r in self.releases:
                r["assets"] = [a for a in r["assets"] if a["id"] != asset]
        elif args[:3] == ["api", "-X", "PATCH"]:
            target = next(r for r in self.releases if r["id"] == int(args[3].rsplit("/", 1)[1]))
            for flag, field in zip(args[4::2], args[5::2]):
                key, value = field.split("=", 1)
                if flag == "-F" and value in ("true", "false"):
                    value = value == "true"
                elif value.startswith("@"):
                    value = Path(value[1:]).read_text()
                target[key] = value
        elif args[:2] == ["release", "create"]:
            tag = args[2]
            assert "--verify-tag" in args and tag in self.tags, "the tag must exist before the draft"
            files = [a for a in args if a.endswith((".whl", ".tar.gz"))]
            notes = Path(args[args.index("--notes-file") + 1]).read_text()
            entry = published(tag, draft=True) | {"id": len(self.releases) + 1, "prerelease": "--prerelease" in args}
            self.releases.append(entry | {"body": notes, "assets": self.assets(files)})
        elif args[:2] == ["release", "upload"]:
            target = self.find(args[2])
            new = self.assets(args[4:])
            names = {a["name"] for a in new}
            target["assets"] = [a for a in target["assets"] if a["name"] not in names] + new
        else:
            raise AssertionError(f"unexpected gh call {args}")
        return ""


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dist = Path(temp.name)
        (self.dist / "ttnn-1.0.0+conda.1-cp312-cp312-linux_x86_64.whl").write_bytes(b"wheel")
        (self.dist / release.TRACY).write_bytes(b"tracy")
        self.notes = self.dist / "notes.md"
        self.notes.write_text("generated notes\n")
        self.manifest = release.manifest(self.dist, A)
        (self.dist / release.MANIFEST).write_text(json.dumps(self.manifest))
        os.environ["GH_REPO"] = "o/r"

    def use(self, fake):
        original = release.gh
        release.gh = fake
        self.addCleanup(setattr, release, "gh", original)
        return fake

    def remote(self, fake, tag):
        """The release's assets in the manifest's form, as GitHub reports them."""
        assets = fake.find(tag)["assets"]
        return {a["name"]: {"size": a["size"], "sha256": a["digest"].removeprefix("sha256:")} for a in assets}

    def test_manifest_ties_artifacts_to_one_commit(self):
        release.check(self.dist, A)
        with self.assertRaisesRegex(release.Fail, "built from"):
            release.check(self.dist, B)
        (self.dist / release.TRACY).write_bytes(b"changed")
        with self.assertRaisesRegex(release.Fail, "differ"):
            release.check(self.dist, A)
        (self.dist / "ttnn-other.whl").write_bytes(b"x")
        with self.assertRaisesRegex(release.Fail, "one ttnn wheel"):
            release.manifest(self.dist, A)

    def test_plan_numbers_after_every_tag_and_release(self):
        tags = {"v1.0.0-conda.1": B, "v1.0.0-conda.3": B, "v0.9.0-conda.7": B}
        releases = [
            published("v1.0.0-conda.1"),
            published("v1.0.0-conda.3"),
            published("v1.0.0-conda.4"),
            published("v1.1.0-dev1-conda.9"),
        ]
        self.assertEqual(release.plan("v1.0.0", A, tags, releases, False), {"action": "build", "tag": "v1.0.0-conda.5"})
        self.assertEqual(release.plan("v1.2.0", A, tags, releases, False)["tag"], "v1.2.0-conda.1")
        self.assertEqual(release.plan("v1.0.0", A, tags, releases, True), {"action": "none", "tag": ""})

    def test_plan_resumes_a_release_started_at_the_commit(self):
        cases = {
            "orphan tag": ({"v1.0.0-conda.2": A}, [], "build"),
            "tagged draft": ({"v1.0.0-conda.2": A}, [published("v1.0.0-conda.2", draft=True)], "build"),
            "tagless draft": ({}, [published("v1.0.0-conda.2", draft=True, target=A)], "build"),
            "published": ({"v1.0.0-conda.2": A}, [published("v1.0.0-conda.2")], "notify"),
        }
        for name, (tags, releases, action) in cases.items():
            for resume in (False, True):
                with self.subTest(name, resume=resume):
                    result = release.plan("v1.0.0", A, tags, releases, resume)
                    self.assertEqual(result, {"action": action, "tag": "v1.0.0-conda.2"})

    def test_plan_refuses_ambiguous_or_pending_releases(self):
        cases = {
            "several release tags": ({"v1.0.0-conda.1": A, "v1.0.0-conda.2": A}, []),
            "not on v1.0.0": ({"v0.9.0-conda.1": A}, []),
            "without a release": ({"v1.0.0-conda.1": B}, []),
            "publish or delete": ({"v1.0.0-conda.1": B}, [published("v1.0.0-conda.1", draft=True)]),
        }
        for message, (tags, releases) in cases.items():
            with self.subTest(message), self.assertRaisesRegex(release.Fail, message):
                release.plan("v1.0.0", A, tags, releases, False)

    def test_newest_compares_versions_within_a_channel(self):
        releases = [
            published("v1.0.1-conda.1"),
            published("v1.0.0-conda.5"),
            published("v1.3.0-dev2-conda.1"),
            published("v1.0.2-conda.1", draft=True),
        ]
        self.assertTrue(release.newest("v1.0.1-conda.2", releases))
        self.assertTrue(release.newest("v1.0.10-conda.1", releases))
        self.assertFalse(release.newest("v1.0.0-conda.6", releases))
        self.assertTrue(release.newest("v1.3.0-dev10-conda.1", releases))
        self.assertFalse(release.newest("v1.3.0-dev1-conda.4", releases))

    def test_publish_drafts_verifies_then_publishes(self):
        fake = self.use(FakeGitHub({"v1.0.0-conda.1": A}, [published("v0.9.0-conda.1")]))
        self.assertTrue(release.publish("v1.0.0-conda.1", A, self.dist, self.notes))
        entry = fake.find("v1.0.0-conda.1")
        self.assertFalse(entry["draft"])
        self.assertEqual(entry["make_latest"], "true")
        self.assertEqual(entry["body"], "generated notes\n")
        self.assertEqual(self.remote(fake, "v1.0.0-conda.1"), self.manifest["assets"])
        self.assertEqual([w[:2] for w in fake.writes], [["release", "create"], ["api", "-X"]])

    def test_publish_keeps_older_and_nightly_releases_off_latest(self):
        for tag in ["v0.9.0-conda.2", "v1.1.0-dev1-conda.1"]:
            with self.subTest(tag):
                fake = self.use(FakeGitHub({tag: A}, [published("v1.0.0-conda.1"), published("v1.1.0-dev2-conda.1")]))
                self.assertFalse(release.publish(tag, A, self.dist, self.notes))
                self.assertEqual(fake.find(tag)["make_latest"], "false")
                self.assertEqual(fake.find(tag)["prerelease"], "-dev" in tag)

    def test_publish_completes_a_partial_draft_and_keeps_its_notes(self):
        draft = published("v1.0.0-conda.1", draft=True, target=A) | {"body": "first notes"}
        draft["assets"] = [{"id": 7, "name": "stale.txt", "size": 1, "digest": None}]
        fake = self.use(FakeGitHub({"v1.0.0-conda.1": A}, [draft]))
        release.publish("v1.0.0-conda.1", A, self.dist, self.notes)
        entry = fake.find("v1.0.0-conda.1")
        self.assertEqual(entry["body"], "first notes")
        self.assertEqual(self.remote(fake, "v1.0.0-conda.1"), self.manifest["assets"])
        self.assertFalse(entry["draft"])

    def test_publish_stops_before_publishing_a_mismatch(self):
        cases = {
            "points to": ({"v1.0.0-conda.1": B}, [], False),
            "differ from the validated": ({"v1.0.0-conda.1": A}, [], True),
            "already published": ({"v1.0.0-conda.1": A}, [published("v1.0.0-conda.1")], False),
            "targets": ({"v1.0.0-conda.1": A}, [published("v1.0.0-conda.1", draft=True, target=B)], False),
        }
        for message, (tags, releases, corrupt) in cases.items():
            with self.subTest(message):
                fake = self.use(FakeGitHub(tags, releases))
                fake.corrupt = corrupt
                with self.assertRaisesRegex(release.Fail, message):
                    release.publish("v1.0.0-conda.1", A, self.dist, self.notes)
                self.assertNotIn("draft=false", [field for w in fake.writes for field in w])

    def test_published_release_is_checked_without_artifacts(self):
        fake = self.use(FakeGitHub({"v1.0.0-conda.1": A}))
        release.publish("v1.0.0-conda.1", A, self.dist, self.notes)
        writes = len(fake.writes)
        self.assertTrue(release.published("v1.0.0-conda.1", A))
        self.assertEqual(len(fake.writes), writes)
        fake.find("v1.0.0-conda.1")["assets"][0]["digest"] = None
        with self.assertRaisesRegex(release.Fail, "no sha256 digest"):
            release.published("v1.0.0-conda.1", A)
        with self.assertRaisesRegex(release.Fail, "has no release"):
            release.published("v1.0.0-conda.2", A)


class TtsimTests(unittest.TestCase):
    NOW = datetime.datetime(2026, 10, 31, tzinfo=datetime.timezone.utc)

    def build(self, tag, **changes):
        assets = [{"name": n, "size": 1, "digest": "sha256:" + "0" * 64} for n in ttsim.ASSETS]
        return {"tag_name": tag, "draft": False, "prerelease": False, "assets": assets} | changes

    def upstream(self, tag, hours=1, **changes):
        published_at = (self.NOW - datetime.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {"tag_name": tag, "draft": False, "prerelease": False, "published_at": published_at} | changes

    def decide(self, fork, upstream, version="v1.1.0"):
        return ttsim.decide("f/ttsim", version, fork, upstream, self.NOW)

    def test_highest_published_build_is_ready(self):
        fork = [
            self.build("v1.1.0-steps.9"),
            self.build("v1.1.0-steps.10"),
            self.build("v1.1.0-steps.11", prerelease=True),
        ]
        fork += [
            self.build("v1.1.0-steps.12", draft=True),
            self.build("v1.1.0-steps.012"),
            self.build("v1.2.0-steps.1"),
        ]
        self.assertEqual(self.decide(fork, []), ("ready", "v1.1.0-steps.10"))

    def test_broken_highest_build_fails(self):
        for asset in [{"size": 0}, {"digest": None}, {"digest": "sha1:00"}]:
            with self.subTest(asset):
                fork = [self.build("v1.1.0-steps.1")]
                fork[0]["assets"][0] |= asset
                with self.assertRaisesRegex(ttsim.Fail, "libttsim_wh.so"):
                    self.decide(fork, [])
        fork = [self.build("v1.1.0-steps.1")]
        fork[0]["assets"].pop()
        with self.assertRaisesRegex(ttsim.Fail, "libttsim_bh.so"):
            self.decide(fork, [])

    def test_missing_build_waits_only_for_a_new_highest_release(self):
        self.assertEqual(self.decide([], [self.upstream("v1.0.0", 900), self.upstream("v1.1.0", 47.9)])[0], "waiting")
        cases = {
            "older than v1.2.0": [self.upstream("v1.1.0"), self.upstream("v1.2.0")],
            "48 hours": [self.upstream("v1.1.0", 48.1)],
            "not a published": [self.upstream("v1.1.0", prerelease=True), self.upstream("v1.0.0")],
            "not a published, ": [self.upstream("v1.1.0", draft=True)],
        }
        for message, upstream in cases.items():
            with self.subTest(message), self.assertRaisesRegex(ttsim.Fail, message):
                self.decide([], upstream)
        # A higher prerelease does not make the formal release a backfill.
        self.assertEqual(
            self.decide([], [self.upstream("v1.1.0"), self.upstream("v1.2.0", prerelease=True)])[0], "waiting"
        )

    def test_version_must_be_formal(self):
        with self.assertRaisesRegex(ttsim.Fail, "not vX.Y.Z"):
            self.decide([], [], version="v1.1.0-rc1")


if __name__ == "__main__":
    unittest.main()
