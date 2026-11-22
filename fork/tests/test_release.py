import pytest
import release as rel
from conftest import release

HEAD = "h" * 40
OTHER = "o" * 40
BASE = "v0.82.0"


@pytest.mark.parametrize(
    ("tags", "known", "expected"),
    [
        # The first release on a base.
        ({}, [], rel.Plan("v0.82.0-conda.1", "build")),
        # The next number counts tags and drafts, and ignores other bases.
        (
            {"v0.82.0-conda.1": OTHER, "v0.81.1-conda.9": OTHER},
            [release("v0.82.0-conda.1"), release("v0.82.0-conda.2"), release("v0.81.1-conda.9")],
            rel.Plan("v0.82.0-conda.3", "build"),
        ),
        # A draft at HEAD resumes, and a published release at HEAD needs nothing.
        ({}, [release("v0.82.0-conda.2", draft=True, target_commitish=HEAD)], rel.Plan("v0.82.0-conda.2", "build")),
        ({"v0.82.0-conda.2": HEAD}, [release("v0.82.0-conda.2")], rel.Plan("v0.82.0-conda.2", "published")),
        # An unfinished release of another commit stops.
        ({}, [release("v0.82.0-conda.1", draft=True, target_commitish=OTHER)], "publish or delete it"),
        ({"v0.82.0-conda.1": OTHER}, [], "without a release"),
        # HEAD released on another base, or twice.
        ({"v0.81.1-conda.2": HEAD}, [release("v0.81.1-conda.2")], "not on v0.82.0"),
        (
            {"v0.82.0-conda.1": HEAD},
            [release("v0.82.0-conda.2", draft=True, target_commitish=HEAD)],
            "several releases",
        ),
    ],
)
def test_plan(tags: dict[str, str], known: list[rel.Release], expected: rel.Plan | str) -> None:
    if isinstance(expected, str):
        with pytest.raises(rel.ForkError, match=expected):
            rel.plan(BASE, HEAD, tags, known)
    else:
        assert rel.plan(BASE, HEAD, tags, known) == expected


@pytest.mark.parametrize(
    ("tag", "version"),
    [("v0.82.0-conda.3", "0.82.0+conda.3"), ("v0.83.0-dev20261121-conda.1", "0.83.0.dev20261121+conda.1")],
)
def test_wheel_version(tag: str, version: str) -> None:
    assert rel.wheel_version(tag) == version


MANIFEST = rel.Manifest(
    tag="v0.82.0-conda.1",
    sha=HEAD,
    assets={"a.whl": rel.AssetFile(size=5, sha256="1" * 64), "b.conda": rel.AssetFile(size=3, sha256="2" * 64)},
)


def asset(name: str, size: int, digest: str | None) -> rel.Asset:
    return rel.Asset(id=1, name=name, size=size, digest=digest)


GOOD = [asset("a.whl", 5, "sha256:" + "1" * 64), asset("b.conda", 3, "sha256:" + "2" * 64)]


@pytest.mark.parametrize(
    "assets",
    [
        GOOD[:1],
        [*GOOD, asset("extra.tar.gz", 1, "sha256:" + "3" * 64)],
        [asset("a.whl", 6, "sha256:" + "1" * 64), GOOD[1]],
        [asset("a.whl", 5, "sha256:" + "9" * 64), GOOD[1]],
        [asset("a.whl", 5, None), GOOD[1]],
    ],
)
def test_compare_refuses_any_difference_from_the_manifest(assets: list[rel.Asset]) -> None:
    rel.compare(MANIFEST, GOOD)
    with pytest.raises(rel.ForkError, match="differ from the prepared"):
        rel.compare(MANIFEST, assets)


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        # Drafts and the other channel's releases do not count.
        ("v0.82.0-conda.2", True),
        ("v0.83.0-dev20261121-conda.2", True),
        # A backfilled release is not the newest.
        ("v0.81.1-conda.9", False),
        ("v0.83.0-dev20261108-conda.5", False),
    ],
)
def test_newest_compares_published_releases_on_one_channel(tag: str, *, expected: bool) -> None:
    known = [
        release("v0.82.0-conda.1"),
        release("v0.82.0-conda.3", draft=True),
        release("v0.83.0-dev20261121-conda.1", prerelease=True),
        release("v0.83.0-dev20261125-conda.1", draft=True),
        release(tag),
    ]
    assert rel.newest(tag, known) is expected
