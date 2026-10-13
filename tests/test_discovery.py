from datetime import date

import pytest

from memebot.discovery import YouTubeCatalog, cadence_report, collect_catalog
from memebot.store import Store

CID = "UC" + "a" * 22


class Catalog(YouTubeCatalog):
    def __init__(self):
        self.calls = []

    def get(self, resource, **params):
        self.calls.append((resource, params))
        if resource == "channels":
            return {
                "items": [
                    {
                        "id": CID,
                        "snippet": {"title": "Demo"},
                        "contentDetails": {"relatedPlaylists": {"uploads": "UUtest"}},
                    }
                ]
            }
        if not params.get("pageToken"):
            return {
                "items": [
                    {
                        "snippet": {"title": "A"},
                        "contentDetails": {
                            "videoId": "aaaaaaaaaaa",
                            "videoPublishedAt": "2026-10-11T04:00:00Z",
                        },
                    }
                ],
                "nextPageToken": "page2",
            }
        return {
            "items": [
                {
                    "snippet": {"title": "B"},
                    "contentDetails": {
                        "videoId": "bbbbbbbbbbb",
                        "videoPublishedAt": "2026-10-12T03:59:59Z",
                    },
                },
                {
                    "snippet": {"title": "Outside"},
                    "contentDetails": {
                        "videoId": "ccccccccccc",
                        "videoPublishedAt": "2026-10-12T04:00:00Z",
                    },
                },
                {"snippet": {"title": "Private video"}, "contentDetails": {}},
            ]
        }


def test_upload_playlist_pagination_exact_date_boundaries():
    rows = Catalog().uploads(CID, date(2026, 10, 11), date(2026, 10, 12))
    assert [v["id"] for v in rows] == ["aaaaaaaaaaa", "bbbbbbbbbbb"]
    assert rows[0]["source_date"] == "2026-10-11"


def test_partial_source_failure_and_reruns_preserve_download_state(tmp_path):
    db = Store(tmp_path / "state.db")
    db.add_source(CID, "Good")
    db.add_source("UC" + "b" * 22, "Bad")

    class Partial(Catalog):
        def uploads(self, channel, *args, **kwargs):
            if channel != CID:
                raise RuntimeError("Unavailable channel")
            return super().uploads(channel, *args, **kwargs)

    result = collect_catalog(db, Partial(), date(2026, 10, 11))
    assert result["videos"] == 2 and len(result["errors"]) == 1
    db.execute(
        "UPDATE videos SET status='downloaded',path='/local/video.mp4' WHERE id='aaaaaaaaaaa'"
    )
    collect_catalog(db, Partial(), date(2026, 10, 11))
    assert len(db.all("SELECT * FROM videos")) == 2
    assert db.one("SELECT * FROM videos WHERE id='aaaaaaaaaaa'")["status"] == "downloaded"


def test_cadence_needs_seven_distinct_days_and_reports_gaps():
    rows = [
        {"published_at": f"2026-10-{d:02d}T18:00:00Z", "duration": 480, "id": str(d)}
        for d in range(5, 12)
    ]
    report = cadence_report(rows, date(2026, 10, 12))
    assert report["daily_last_7"] is True
    assert report["active_days_14"] == 7
    assert report["missing_days"] == [f"2026-09-{d:02d}" for d in range(28, 31)] + [
        f"2026-10-{d:02d}" for d in range(1, 5)
    ]
    report = cadence_report([rows[-1]] * 7, date(2026, 10, 12))
    assert report["daily_last_7"] is False


def test_catalog_requires_key():
    with pytest.raises(ValueError, match="YOUTUBE_API_KEY"):
        YouTubeCatalog("")
