import datetime as dt
import sys
from pathlib import Path

# The scripts run as files and import their siblings, so the tests do the same.
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from sync import Release


def release(tag: str, **fields: object) -> Release:
    """Build a release with defaults for the fields a test does not name."""
    defaults: dict[str, object] = {
        "id": 1,
        "tag_name": tag,
        "draft": False,
        "prerelease": False,
        "immutable": True,
        "target_commitish": "main",
        "published_at": dt.datetime(2026, 11, 1, tzinfo=dt.UTC),
        "body": "",
        "assets": [],
    }
    return Release.model_validate(defaults | fields)
