import json
from datetime import date

import pytest

from memebot.store import Store
from memebot.timeutil import day_window


def test_calendar_window_handles_dst():
    a, b = day_window(date(2026, 3, 8))
    assert a.isoformat() == "2026-03-08T05:00:00+00:00"
    assert b.isoformat() == "2026-03-09T04:00:00+00:00"
    a, b = day_window(date(2026, 11, 1))
    assert (b - a).total_seconds() == 25 * 3600


def test_import_legacy_never_claims_processed(tmp_path):
    db = Store(tmp_path / "state.db")
    legacy = tmp_path / "curVids.json"
    legacy.write_text(json.dumps({"Heno": {"video_id": "5wHPCleT0FM", "is_new": True}}))
    assert db.import_legacy(legacy) == 1
    assert db.import_legacy(legacy) == 0
    assert db.one("SELECT * FROM videos")["status"] == "discovered"


def test_jobs_deduplicate_and_recover_after_lock_owner_dies(tmp_path):
    db = Store(tmp_path / "state.db")
    job = db.enqueue("collect", {"date": "2026-10-11"})
    assert db.enqueue("collect", {"date": "2026-10-11"}) == job
    assert db.claim_job()["id"] == job
    assert db.claim_job() is None
    db.recover_jobs()  # Only called while holding the exclusive OS worker lock.
    assert db.claim_job()["id"] == job
    db.finish_job(job, error="Source unavailable")
    assert db.one("SELECT * FROM jobs WHERE id=?", (job,))["status"] == "failed"
    assert db.enqueue("collect", {"date": "2026-10-11"}) != job


def test_source_identity_not_display_name(tmp_path):
    db = Store(tmp_path / "state.db")
    db.add_source("UC" + "a" * 22, "First")
    db.add_source("UC" + "a" * 22, "Renamed")
    assert len(db.all("SELECT * FROM sources")) == 1
    assert db.one("SELECT * FROM sources")["name"] == "Renamed"
    with pytest.raises(ValueError):
        db.add_source("../oops", "Bad")
