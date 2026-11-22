import pytest
import release as rel

HEAD = "h" * 40
OTHER = "o" * 40
BASE = "v0.82.0"


@pytest.mark.parametrize(
    ("tags", "drafts", "expected"),
    [
        # The first release on a base.
        ({}, [], "v0.82.0-conda.1"),
        # The next number follows every tag on the base, and ignores other bases.
        ({"v0.82.0-conda.2": OTHER, "v0.81.1-conda.9": OTHER}, [], "v0.82.0-conda.3"),
        # Drafts on other bases do not stop the release.
        ({}, ["v0.81.1-conda.3"], "v0.82.0-conda.1"),
        # HEAD released before, on any base, stops.
        ({"v0.81.1-conda.2": HEAD}, [], "already released as v0.81.1-conda.2"),
        # A draft that a failed publish left on the base stops.
        ({"v0.82.0-conda.1": OTHER}, ["v0.82.0-conda.2"], "gh release delete v0.82.0-conda.2"),
    ],
)
def test_next_tag(tags: dict[str, str], drafts: list[str], expected: str) -> None:
    if expected.startswith("v"):
        assert rel.next_tag(BASE, HEAD, tags, drafts) == expected
    else:
        with pytest.raises(rel.ForkError, match=expected):
            rel.next_tag(BASE, HEAD, tags, drafts)


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
        # The other channel's releases do not count.
        ("v0.82.0-conda.2", True),
        ("v0.83.0-dev20261125-conda.1", True),
        # A backfilled release is not the newest.
        ("v0.81.1-conda.9", False),
        ("v0.83.0-dev20261108-conda.5", False),
    ],
)
def test_newest_compares_release_tags_on_one_channel(tag: str, *, expected: bool) -> None:
    tags = ["v0.82.0-conda.1", "v0.83.0-dev20261121-conda.1"]
    assert rel.newest(tag, tags) is expected
