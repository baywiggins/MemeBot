from datetime import datetime, timezone

import pytest

from memebot.config import Config
from memebot.scheduler import launchagent, schedule_due
from memebot.store import Store
from memebot.worker import run_worker, worker_lock


def test_worker_lock_prevents_double_claim_and_job_failure_is_visible(tmp_path):
    config = Config(tmp_path)
    db = Store(config.db_path)
    jid = db.enqueue("bad-job", {})
    with worker_lock(tmp_path):
        with pytest.raises(BlockingIOError):
            with worker_lock(tmp_path):
                pass
    assert run_worker(config) == 1
    job = db.one("SELECT * FROM jobs WHERE id=?", (jid,))
    assert job["status"] == "failed" and "Unknown job" in job["error"]


def test_scheduler_only_collects_yesterday_after_nine_and_catches_up(tmp_path):
    config = Config(tmp_path)
    db = Store(config.db_path)
    assert schedule_due(config, datetime(2026, 10, 12, 12, 59, tzinfo=timezone.utc)) is None
    jid = schedule_due(config, datetime(2026, 10, 12, 16, 0, tzinfo=timezone.utc))
    assert jid
    assert schedule_due(config, datetime(2026, 10, 12, 17, 0, tzinfo=timezone.utc)) is None
    job = db.one("SELECT * FROM jobs WHERE id=?", (jid,))
    assert job["kind"] == "collect" and "2026-10-11" in job["payload"]
    assert "publish" not in job["payload"]


def test_launchagent_quotes_paths_through_plist_argument_array(tmp_path):
    import plistlib

    plist = launchagent(Config(tmp_path / "with spaces"))
    data = plistlib.loads(plist)
    assert data["ProgramArguments"][-1] == "tick"
    assert data["StartInterval"] == 900
    assert data["EnvironmentVariables"]["MEMEBOT_HOME"] == str(tmp_path / "with spaces")
