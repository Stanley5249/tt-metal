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
        self.git(self.upstream, "tag", "v1.1.0-dev20260101")
        self.git(self.root, "init", "-q", "--bare", str(self.origin))
        self.git(self.root, "clone", "-q", str(self.upstream), str(self.work))
        self.git(self.work, "remote", "rename", "origin", "upstream")
        self.git(self.work, "remote", "add", "origin", str(self.origin))
        self.git(self.work, "switch", "-q", "-c", "stable")
        self.write(self.work, ".github/fork-infra", "fork.txt\n")
        self.write(self.work, ".github/scripts/fork-infra.sh", (SCRIPTS / "fork-infra.sh").read_text())
        self.write(self.work, ".github/scripts/fork-upstream-tags.sh", (SCRIPTS / "fork-upstream-tags.sh").read_text())
        self.write(self.work, "fork.txt", "infrastructure\n")
        self.commit(self.work, "fork infrastructure")
        self.git(self.work, "branch", "nightly")
        self.git(self.work, "push", "-q", "origin", "stable", "nightly")

    def git(self, cwd, *args, check=True):
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=check,
        )

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

    def sync(self, track="stable", tag="v1.0.1", success=True):
        (self.root / "output").write_text("")
        result = subprocess.run(
            ["bash", str(SCRIPTS / "fork-sync.sh"), track, tag],
            cwd=self.work,
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(result.returncode == 0, success, result.stdout)
        return result.stdout

    def test_forward_update_and_local_retry(self):
        self.advance()
        self.sync()
        sha = self.git(self.work, "rev-parse", "HEAD").stdout
        self.assertEqual((self.work / "tt_metal/ttsim-version").read_text(), "new-upstream-ttsim\n")
        self.sync()
        self.assertEqual(self.git(self.work, "rev-parse", "HEAD").stdout, sha)
        self.assertIn("changed=true", (self.root / "output").read_text())
        self.assertEqual(
            self.git(self.work, "rev-parse", "origin/stable").stdout, self.git(self.work, "rev-parse", "stable").stdout
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
        sha = self.git(self.work, "rev-parse", "HEAD").stdout
        self.git(self.work, "push", "-q", "origin", candidate)
        self.git(self.work, "switch", "-q", "stable")
        self.git(self.work, "branch", "-D", candidate)
        self.sync()
        self.assertEqual(self.git(self.work, "rev-parse", "HEAD").stdout, sha)

    def test_already_integrated(self):
        self.advance()
        self.sync()
        self.git(self.work, "push", "-q", "origin", "HEAD:stable")
        self.sync()
        self.assertEqual((self.root / "output").read_text(), "changed=false\n")

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
        self.assertIn("Resolve conflicts", self.sync(success=False))
        self.git(self.work, "rev-parse", "--verify", "MERGE_HEAD")
        self.assertIn("source.txt", self.git(self.work, "diff", "--name-only", "--diff-filter=U").stdout)
        self.write(self.work, "source.txt", "resolved patch\n")
        self.commit(self.work, "resolve merge")
        self.sync()
        self.assertEqual((self.work / "source.txt").read_text(), "resolved patch\n")

    def test_reject_older_tag(self):
        self.advance()
        self.sync()
        self.git(self.work, "push", "-q", "origin", "HEAD:stable")
        self.assertIn("not a forward upgrade", self.sync(tag="v1.0.0", success=False))

    def test_reject_stale_candidate(self):
        self.advance()
        self.sync()
        self.git(self.work, "switch", "-q", "stable")
        self.write(self.work, "new-fork.txt", "new fork change\n")
        self.commit(self.work, "new fork change")
        self.git(self.work, "push", "-q", "origin", "stable")
        self.assertIn("behind stable", self.sync(success=False))

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
                result = subprocess.run(
                    ["bash", str(SCRIPTS / "fork-select-tag.sh"), track],
                    env=env,
                    text=True,
                    capture_output=True,
                    check=True,
                )
                self.assertEqual(result.stdout.strip(), expected)

    def test_upstream_dependency_pins_are_required(self):
        self.write(self.work, "tt_metal/sfpi-version", "fork override\n")
        self.commit(self.work, "override dependency")
        self.git(self.work, "push", "-q", "origin", "stable")
        self.advance()
        self.sync(success=False)
        self.assertEqual((self.root / "output").read_text(), "")

    def test_nightly_copies_stable_infrastructure(self):
        self.write(self.work, "fork.txt", "new stable infrastructure\n")
        self.commit(self.work, "infrastructure update")
        self.git(self.work, "push", "-q", "origin", "stable")
        self.advance("v1.1.0-dev20260102")
        self.sync("nightly", "v1.1.0-dev20260102")
        self.assertEqual((self.work / "fork.txt").read_text(), "new stable infrastructure\n")

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
