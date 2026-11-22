import datetime as dt
import subprocess
from pathlib import Path

import pytest
import sync
from conftest import release

NOW = dt.datetime(2026, 11, 10, tzinfo=dt.UTC)
DIGEST = "sha256:" + "a" * 64
PIN = f'ttsim = {{ url = "{sync.ttsim_url("v1.15.1-steps.3")}", sha256 = "{"b" * 64}" }}'
MANIFEST = f'[workspace]\nname = "tt-metal"\nversion = "0.83.0.dev20261121"\n\n[feature.runtime.dependencies]\n{PIN}\n'


def ttsim_release(tag: str, *, digest: str | None = DIGEST, size: int = 10, **fields: object) -> sync.Release:
    asset = {"id": 1, "name": sync.ttsim_package(tag), "size": size, "digest": digest}
    return release(tag, assets=[asset], **fields)


@pytest.mark.parametrize(
    ("channel", "tags", "expected"),
    [
        # Release candidates and -dev tags never reach stable.
        ("stable", ["v0.82.0", "v0.83.0-rc1", "v0.83.0-dev20261121", "v0.81.1"], "v0.82.0"),
        ("main", ["v0.82.0", "v0.83.0-dev20261108", "v0.83.0-dev20261121", "v0.83.0-rc1"], "v0.83.0-dev20261121"),
        # Versions compare as numbers, not as strings.
        ("stable", ["v0.9.0", "v0.10.0"], "v0.10.0"),
    ],
)
def test_latest_tag_takes_the_newest_of_the_channels_line(channel: str, tags: list[str], expected: str) -> None:
    upstream = [release(t) for t in tags] + [release("v9.0.0", draft=True)]
    assert sync.latest_tag(channel, upstream) == expected


@pytest.mark.parametrize(
    ("channel", "tag"), [("stable", "v0.83.0-dev20261121"), ("main", "v0.82.0"), ("stable", "v0.83.0-rc1")]
)
def test_check_tag_refuses_the_other_line(channel: str, tag: str) -> None:
    with pytest.raises(sync.ForkError, match="is not an upstream"):
        sync.check_tag(channel, tag)


def test_the_base_is_recorded_in_pixi_toml_in_pep_440_spelling() -> None:
    assert sync.recorded_base(MANIFEST) == "v0.83.0-dev20261121"
    updated = sync.record_base(MANIFEST, "v0.83.0-dev20261130")
    assert 'version = "0.83.0.dev20261130"' in updated
    assert sync.recorded_base(sync.record_base(MANIFEST, "v0.82.1")) == "v0.82.1"


def test_a_pin_round_trips_through_pixi_toml() -> None:
    build = sync.TtsimBuild("v1.16.0-steps.2", "c" * 64)
    pinned = sync.pin_ttsim(MANIFEST, build)
    assert sync.pinned_ttsim(pinned) == ("v1.16.0-steps.2", "c" * 64)
    sync.check_ttsim(pinned, "v1.16.0")
    with pytest.raises(sync.ForkError, match=r"not a v1\.15\.1-steps\.N build"):
        sync.check_ttsim(pinned, "v1.15.1")


UPSTREAM = [
    release("v1.15.1", published_at=NOW - dt.timedelta(days=30)),
    release("v1.16.0", published_at=NOW - dt.timedelta(hours=10)),
]
LATE = [release("v1.16.0", published_at=NOW - dt.timedelta(hours=49))]


@pytest.mark.parametrize(
    ("pinned", "fork", "upstream", "expected"),
    [
        # An unchanged version keeps its build, even when a newer one exists.
        ("v1.16.0-steps.1", [ttsim_release("v1.16.0-steps.2")], UPSTREAM, None),
        # The highest steps.N wins; drafts, prereleases, and other versions do not count.
        (
            "v1.15.1-steps.3",
            [
                ttsim_release("v1.16.0-steps.2"),
                ttsim_release("v1.16.0-steps.10", digest="sha256:" + "d" * 64),
                ttsim_release("v1.16.0-steps.11", draft=True),
                ttsim_release("v1.16.0-steps.12", prerelease=True),
                ttsim_release("v1.17.0-steps.1"),
            ],
            UPSTREAM,
            sync.TtsimBuild("v1.16.0-steps.10", "d" * 64),
        ),
        # No build yet within 48 hours of upstream's release.
        ("v1.15.1-steps.3", [], UPSTREAM, sync.Waiting),
        # Overdue, missing digest, empty package, or an old upstream version all stop.
        ("v1.15.1-steps.3", [], LATE, "48 hours after"),
        ("v1.15.1-steps.3", [ttsim_release("v1.16.0-steps.1", digest=None)], UPSTREAM, "with a sha256 digest"),
        ("v1.15.1-steps.3", [ttsim_release("v1.16.0-steps.1", size=0)], UPSTREAM, "with a sha256 digest"),
        ("v1.15.1-steps.3", [], [*UPSTREAM, release("v1.17.0")], "older than v1.17.0"),
    ],
)
def test_choose_build(pinned: str, fork: list[sync.Release], upstream: list[sync.Release], expected: object) -> None:
    if isinstance(expected, str):
        with pytest.raises(sync.ForkError, match=expected):
            sync.choose_build("v1.16.0", pinned, fork, upstream, NOW)
    elif expected is sync.Waiting:
        assert isinstance(sync.choose_build("v1.16.0", pinned, fork, upstream, NOW), sync.Waiting)
    else:
        assert sync.choose_build("v1.16.0", pinned, fork, upstream, NOW) == expected


def test_exposed_workflows_lists_active_and_unregistered_inherited_ones() -> None:
    paths = [
        ".github/workflows/fork-checks.yaml",
        ".github/workflows/build.yaml",
        ".github/workflows/nightly.yaml",
        ".github/workflows/new.yaml",
    ]
    workflows = [
        sync.Workflow(path=".github/workflows/fork-checks.yaml", state="active"),
        sync.Workflow(path=".github/workflows/build.yaml", state="disabled_manually"),
        sync.Workflow(path=".github/workflows/nightly.yaml", state="active"),
    ]
    assert sync.exposed_workflows(paths, workflows) == [".github/workflows/nightly.yaml", ".github/workflows/new.yaml"]


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "protocol.file.allow=always", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repo with tags v0.1.0 and v0.2.0 and a submodule at an older commit."""
    for key, value in {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }.items():
        monkeypatch.setenv(key, value)
    sub = tmp_path / "sub"
    work = tmp_path / "work"
    for path in (sub, work):
        git(tmp_path, "init", "-q", "-b", "main", str(path))
        git(path, "commit", "-q", "--allow-empty", "-m", "first")
    git(sub, "commit", "-q", "--allow-empty", "-m", "second")
    git(work, "submodule", "add", "-q", str(sub), "sub")
    git(work, "commit", "-q", "-m", "add sub")
    git(work, "tag", "v0.1.0")
    git(work, "commit", "-q", "--allow-empty", "-m", "next")
    git(work, "tag", "v0.2.0")
    monkeypatch.chdir(work)
    return work


def test_require_clean_accepts_an_older_submodule_commit_but_not_edits(repo: Path) -> None:
    git(repo / "sub", "checkout", "-q", "HEAD~1")
    sync.require_clean()
    (repo / "sub/edit.txt").write_text("x")
    with pytest.raises(sync.ForkError, match="submodule changes"):
        sync.require_clean()
    (repo / "sub/edit.txt").unlink()
    (repo / "top.txt").write_text("x")
    with pytest.raises(sync.ForkError, match="your changes"):
        sync.require_clean()


@pytest.mark.usefixtures("repo")
def test_check_forward_refuses_an_older_tag() -> None:
    sync.check_forward("v0.1.0", "v0.2.0")
    with pytest.raises(sync.ForkError, match="not a forward upgrade"):
        sync.check_forward("v0.2.0", "v0.1.0")
