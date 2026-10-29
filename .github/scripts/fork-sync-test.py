#!/usr/bin/env python3
"""Exercise fork sync with tiny local Git repositories and no builds."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent


class ForkSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = os.environ | {
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_ALLOW_PROTOCOL": "file",
            "GITHUB_OUTPUT": str(self.root / "output"),
        }
        self.upstream = self.root / "upstream"
        self.origin = self.root / "origin.git"
        self.work = self.root / "work"
        self.git(self.root, "init", "-q", "--initial-branch=main", str(self.upstream))
        self.write(self.upstream, "source.txt", "base\n")
        self.write(self.upstream, "tt_metal/sfpi-version", "upstream-sfpi\n")
        self.write(self.upstream, "tt_metal/ttsim-version", "upstream-ttsim\n")
        self.commit(self.upstream, "base")
        self.git(self.upstream, "tag", "v1.0.0")
        self.write(self.upstream, "nightly.txt", "nightly base\n")
        self.commit(self.upstream, "nightly base")
        self.git(self.upstream, "tag", "v1.1.0-dev20260101")
        self.git(self.root, "init", "-q", "--bare", str(self.origin))
        self.git(self.root, "clone", "-q", str(self.upstream), str(self.work))
        self.git(self.work, "remote", "rename", "origin", "upstream")
        self.git(self.work, "remote", "add", "origin", str(self.origin))
        self.git(self.work, "switch", "-q", "-c", "stable", "v1.0.0")
        for script in ["fork-select-tag.sh", "fork-upstream-tags.sh", "fork-version.sh"]:
            self.write(self.work, f".github/scripts/{script}", (SCRIPTS / script).read_text())
        self.write(self.work, "fork.txt", "fork change\n")
        self.commit(self.work, "fork change")
        infrastructure = self.head()
        self.git(self.work, "switch", "-q", "-c", "nightly", "v1.1.0-dev20260101")
        self.git(self.work, "cherry-pick", infrastructure)
        self.git(self.work, "switch", "-q", "stable")
        self.git(self.work, "push", "-q", "origin", "stable", "nightly")

    def call(self, cmd, cwd=None, env=None, success=True):
        result = subprocess.run(
            cmd, cwd=cwd or self.work, env=env or self.env, text=True, capture_output=True, check=False
        )
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def git(self, cwd, *args):
        return self.call(["git", *args], cwd=cwd).stdout

    def head(self):
        return self.git(self.work, "rev-parse", "HEAD").strip()

    def write(self, repo, path, content):
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def commit(self, repo, message):
        self.git(repo, "add", ".")
        self.git(repo, "commit", "-qm", message)

    def advance(self, tag="v1.0.1"):
        self.write(self.upstream, "source.txt", "updated\n")
        self.write(self.upstream, "tt_metal/ttsim-version", "new-upstream-ttsim\n")
        self.commit(self.upstream, "upstream update")
        self.git(self.upstream, "tag", tag)

    def sync(self, track="stable", tag="v1.0.1", success=True, status=None):
        (self.root / "output").write_text("")
        result = self.call(["bash", str(SCRIPTS / "fork-sync.sh"), track, tag], success=success)
        if status is not None:
            self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def outputs(self):
        return dict(line.split("=", 1) for line in (self.root / "output").read_text().splitlines())

    def version(self, track="stable", ref="HEAD", label=""):
        output = self.call(["bash", str(SCRIPTS / "fork-version.sh"), track, ref, label]).stdout
        return dict(line.split("=", 1) for line in output.splitlines())

    def version_error(self, track="stable", ref="HEAD", label=""):
        result = self.call(["bash", str(SCRIPTS / "fork-version.sh"), track, ref, label], success=False)
        # A failed run must not leave Actions outputs behind.
        self.assertEqual(result.stdout, "")
        return result.stderr

    def test_stable_version_excludes_fork_and_rc_tags(self):
        self.git(self.work, "tag", "v1.0.0-conda.9")
        self.git(self.work, "tag", "v1.0.1-rc1")
        metadata = self.version(label="conda.test")
        self.assertEqual(metadata["base"], "v1.0.0")
        self.assertEqual(metadata["track"], "stable")
        self.assertEqual(metadata["version"], "1.0.0+conda.test")
        self.assertEqual(metadata["base-commit"], self.git(self.work, "rev-parse", "v1.0.0^{commit}").strip())
        self.assertEqual(self.version("auto")["version"], "1.0.0")
        self.assertEqual(self.version(label="Conda_RC-1")["version"], "1.0.0+Conda_RC-1")

    def test_nightly_version_and_track_guard(self):
        metadata = self.version("nightly", "origin/nightly", "conda.2")
        self.assertEqual(metadata["base"], "v1.1.0-dev20260101")
        self.assertEqual(metadata["track"], "nightly")
        self.assertEqual(metadata["version"], "1.1.0.dev20260101+conda.2")
        self.assertEqual(self.version("auto", "origin/nightly")["version"], "1.1.0.dev20260101")
        self.assertIn("cannot build", self.version_error("stable", "origin/nightly"))
        self.assertIn("cannot build", self.version_error("nightly"))

    def test_invalid_version_inputs(self):
        self.version_error("invalid")
        self.version_error(ref="missing-ref")
        for label in ["../bad", "conda.1\nbase=injected", "conda.", "conda..1"]:
            with self.subTest(label=label):
                self.version_error(label=label)

    def test_forward_update_and_local_retry(self):
        self.advance()
        self.sync()
        sha = self.head()
        self.assertEqual((self.work / "tt_metal/ttsim-version").read_text(), "new-upstream-ttsim\n")
        self.sync()
        self.assertEqual(self.head(), sha)
        outputs = self.outputs()
        self.assertEqual(outputs["changed"], "true")
        self.assertEqual(outputs["sha"], sha)
        self.assertEqual(outputs["candidate"], "chore/sync-stable-v1.0.1")
        self.assertIn(self.git(self.upstream, "rev-parse", "v1.0.1").strip(), self.git(self.work, "log", "--format=%P", "-1"))
        self.assertEqual(
            self.git(self.work, "rev-parse", "origin/stable"), self.git(self.work, "rev-parse", "stable")
        )

    def test_clone_without_upstream_tags(self):
        self.advance()
        self.git(self.work, "tag", "-d", "v1.0.0", "v1.1.0-dev20260101")
        self.sync()
        self.git(self.work, "rev-parse", "--verify", "v1.0.0")

    def test_remote_candidate_retry(self):
        self.advance()
        self.sync()
        candidate = "chore/sync-stable-v1.0.1"
        sha = self.head()
        self.git(self.work, "push", "-q", "origin", candidate)
        self.git(self.work, "switch", "-q", "stable")
        self.git(self.work, "branch", "-D", candidate)
        self.sync()
        self.assertEqual(self.head(), sha)

    def test_already_integrated(self):
        self.advance()
        self.sync()
        self.git(self.work, "push", "-q", "origin", "HEAD:stable")
        self.sync()
        self.assertEqual(self.outputs()["changed"], "false")

    def test_invalid_tag_and_dirty_tree(self):
        self.assertIn("not an upstream", self.sync(tag="v1.0.1-rc1", success=False))
        self.write(self.work, "source.txt", "local work\n")
        self.assertIn("commit or stash", self.sync(success=False))
        self.assertEqual((self.work / "source.txt").read_text(), "local work\n")

    def test_conflict_preserves_resolution_state(self):
        self.write(self.work, "source.txt", "fork patch\n")
        self.commit(self.work, "source patch")
        self.git(self.work, "push", "-q", "origin", "stable")
        self.advance()
        self.assertIn("Resolve conflicts", self.sync(success=False, status=2))
        self.git(self.work, "rev-parse", "--verify", "MERGE_HEAD")
        self.assertIn("source.txt", self.git(self.work, "diff", "--name-only", "--diff-filter=U"))
        self.write(self.work, "source.txt", "resolved patch\n")
        self.commit(self.work, "resolve merge")
        self.sync()
        self.assertEqual((self.work / "source.txt").read_text(), "resolved patch\n")

    def test_reject_older_tag(self):
        self.advance()
        self.sync()
        self.git(self.work, "push", "-q", "origin", "HEAD:stable")
        self.assertIn("not a forward upgrade", self.sync(tag="v1.0.0", success=False))

    def test_moved_track_merges_into_update_branch(self):
        self.advance()
        self.sync()
        merge = self.head()
        self.git(self.work, "push", "-q", "origin", "HEAD")
        self.git(self.work, "switch", "-q", "stable")
        self.write(self.work, "new-fork.txt", "new fork change\n")
        self.commit(self.work, "new fork change")
        self.git(self.work, "push", "-q", "origin", "stable")
        self.sync()
        self.git(self.work, "merge-base", "--is-ancestor", merge, "HEAD")
        self.git(self.work, "merge-base", "--is-ancestor", "origin/stable", "HEAD")
        self.assertEqual(self.outputs()["sha"], self.head())

    def test_select_tags(self):
        binary = self.root / "bin"
        binary.mkdir()
        gh = binary / "gh"
        gh.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$TEST_RELEASES"\n')
        gh.chmod(0o755)
        for track, releases, expected in [
            ("stable", "v1.2.0", "v1.2.0"),
            ("nightly", "v1.2.0-rc1\nv1.2.0-dev20260102\nv1.2.0\nv1.2.0-dev20260101", "v1.2.0-dev20260102"),
        ]:
            with self.subTest(track=track):
                env = self.env | {"PATH": f"{binary}:{self.env['PATH']}", "TEST_RELEASES": releases}
                output = self.call(["bash", str(SCRIPTS / "fork-select-tag.sh"), track], env=env).stdout
                self.assertEqual(output.strip(), expected)

    def test_upstream_dependency_pins_are_required(self):
        self.write(self.work, "tt_metal/sfpi-version", "fork override\n")
        self.commit(self.work, "override dependency")
        self.git(self.work, "push", "-q", "origin", "stable")
        self.advance()
        self.sync(success=False, status=1)
        self.assertNotIn("changed", self.outputs())

    def test_fetch_failure_is_not_a_conflict(self):
        self.advance()
        self.git(self.work, "remote", "set-url", "upstream", str(self.root / "missing"))
        output = self.sync(success=False, status=128)
        self.assertIn("missing", output)
        self.assertNotIn("Resolve conflicts", output)
        self.assertNotIn("changed", self.outputs())

    def test_nightly_ignores_stable(self):
        self.write(self.work, "fork.txt", "stable-only change\n")
        self.commit(self.work, "stable-only change")
        self.git(self.work, "push", "-q", "origin", "stable")
        self.advance("v1.1.0-dev20260102")
        self.sync("nightly", "v1.1.0-dev20260102")
        self.assertEqual((self.work / "fork.txt").read_text(), "fork change\n")
        self.assertEqual(self.outputs()["candidate"], "chore/sync-nightly-v1.1.0-dev20260102")

    def test_submodule_alignment_and_dirty_guard(self):
        module = self.root / "module"
        self.git(self.root, "init", "-q", "--initial-branch=main", str(module))
        self.write(module, "data", "old\n")
        self.commit(module, "old module")
        nested = self.root / "nested"
        self.git(self.root, "init", "-q", "--initial-branch=main", str(nested))
        self.write(nested, "data", "old nested\n")
        self.commit(nested, "old nested")
        self.write(nested, "data", "new nested\n")
        self.commit(nested, "new nested")
        self.git(module, "submodule", "add", "-q", str(nested), "nested")
        self.commit(module, "add nested")
        self.git(self.upstream, "submodule", "add", "-q", str(module), "dep")
        self.commit(self.upstream, "add module")
        self.git(self.upstream, "tag", "v1.0.1")
        self.sync()
        self.git(self.work, "push", "-q", "origin", "HEAD:stable")
        self.write(module, "data", "new\n")
        self.commit(module, "new module")
        self.git(self.upstream / "dep", "fetch", "-q", "origin")
        self.git(self.upstream / "dep", "checkout", "-q", "origin/main")
        self.commit(self.upstream, "update module")
        self.git(self.upstream, "tag", "v1.0.2")
        self.sync(tag="v1.0.2")
        self.assertEqual((self.work / "dep/data").read_text(), "new\n")
        self.git(self.work / "dep", "checkout", "-q", "HEAD~1")
        self.sync(tag="v1.0.2")
        self.assertEqual((self.work / "dep/data").read_text(), "new\n")
        self.git(self.work / "dep/nested", "checkout", "-q", "HEAD~1")
        self.sync(tag="v1.0.2")
        self.assertEqual((self.work / "dep/nested/data").read_text(), "new nested\n")
        self.write(self.work, "dep/data", "user edit\n")
        self.assertIn("submodule changes", self.sync(tag="v1.0.2", success=False))
        self.assertEqual((self.work / "dep/data").read_text(), "user edit\n")


if __name__ == "__main__":
    unittest.main()
