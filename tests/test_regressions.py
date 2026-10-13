from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from memebot.episodes import Episodes
from memebot.publishing import Publisher
from memebot.store import Store


def episode_library(tmp_path):
    db = Store(tmp_path / "state.db")
    cid = "UC" + "x" * 22
    db.add_source(
        cid,
        "Example source",
        research={"uploads_per_day": {"2026-10-11": 1}, "as_of": "2026-10-12", "active_days_14": 1},
    )
    db.save_video(
        {"id": "x" * 11, "source_id": cid, "source_date": "2026-10-11", "title": "Sample"}
    )
    db.execute("UPDATE videos SET status='analyzed',duration=600,path='/missing/source.mp4'")
    c = db.execute("INSERT INTO clips(video_id,start,end) VALUES(?,0,400)", ("x" * 11,))
    s = Episodes(db)
    eid = s.draft("2026-10-11")
    return db, s, eid, c


def test_daily_review_button_navigates_to_existing_episode(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMEBOT_HOME", str(tmp_path))
    db, s, eid, c = episode_library(tmp_path)
    app = AppTest.from_file(
        str(Path(__file__).parents[1] / "src/memebot/ui.py"), default_timeout=15
    ).run()
    app.date_input[0].set_value(date(2026, 10, 11)).run()
    button = next(b for b in app.button if b.label == "Review this episode")
    button.click().run()
    assert not app.exception
    assert app.sidebar.radio[0].value == "Episodes"


def test_sources_chart_renders_nonempty_history(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMEBOT_HOME", str(tmp_path))
    episode_library(tmp_path)
    app = AppTest.from_file(
        str(Path(__file__).parents[1] / "src/memebot/ui.py"), default_timeout=15
    ).run()
    app.sidebar.radio[0].set_value("Sources").run()
    assert not app.exception


def test_split_preserves_selected_thumbnail_frame_in_second_half(tmp_path):
    db, s, eid, c = episode_library(tmp_path)
    s.thumbnail(eid, c, 300, 1)
    new = s.split_clip(c, 200)
    assert s.get(eid)["thumbnail_clip"] == new
    assert s.get(eid)["thumbnail_time"] == 300


def test_trimming_duplicate_original_clears_dependent_exact_exclusions(tmp_path):
    db, s, eid, c = episode_library(tmp_path)
    second = db.execute(
        "INSERT INTO clips(video_id,start,end,duplicate_of) VALUES(?,400,500,?)", ("x" * 11, c)
    )
    s.trim_clip(c, 10, 390)
    assert db.one("SELECT * FROM clips WHERE id=?", (second,))["duplicate_of"] is None


def test_uploader_requires_confirmed_destination_before_network(tmp_path):
    import requests

    db, s, eid, c = episode_library(tmp_path)
    path = tmp_path / "episode.mp4"
    path.write_bytes(b"media")
    s.attach_render(eid, 1, path, 400)
    s.approve(eid, 1)
    p = Publisher(db, requests.Session())
    with pytest.raises(ValueError, match="destination"):
        p.upload_private(eid)


def test_unused_previous_day_clip_does_not_block_current_day(monkeypatch, tmp_path):
    from memebot.pipeline import fingerprint_clip

    db, s, eid, c = episode_library(tmp_path)
    db.execute("UPDATE clips SET exact_hash='same',fingerprints='[]' WHERE id=?", (c,))
    db.save_video(
        {
            "id": "y" * 11,
            "source_id": "UC" + "x" * 22,
            "source_date": "2026-10-12",
            "title": "New sample",
        }
    )
    db.execute("UPDATE videos SET status='analyzed',duration=600,path='/missing/source.mp4'")
    new = db.execute("INSERT INTO clips(video_id,start,end) VALUES(?,0,400)", ("y" * 11,))
    monkeypatch.setattr("memebot.pipeline.fingerprint", lambda *a: ("same", []))
    fingerprint_clip(db, new)
    assert db.one("SELECT duplicate_of FROM clips WHERE id=?", (new,))["duplicate_of"] is None
    db.execute("UPDATE episodes SET upload_state='published' WHERE id=?", (eid,))
    fingerprint_clip(db, new)
    assert db.one("SELECT duplicate_of FROM clips WHERE id=?", (new,))["duplicate_of"] == c


def test_repeated_split_merge_split_reuses_retained_boundary(tmp_path):
    db, s, eid, cid = episode_library(tmp_path)
    second = s.split_clip(cid, 200)
    s.merge_clips(cid, second)
    recreated = s.split_clip(cid, 200)
    assert [c["id"] for c in s.clips(eid)] == [cid, recreated]
    assert db.one("SELECT decision FROM clips WHERE id=?", (recreated,))["decision"] != "excluded"


def test_exclude_restore_reassigns_duplicate_owner(tmp_path):
    db, s, eid, cid = episode_library(tmp_path)
    db.execute("UPDATE clips SET exact_hash='same' WHERE id=?", (cid,))
    second = db.execute(
        "INSERT INTO clips(video_id,start,end,exact_hash,duplicate_of) VALUES(?,400,500,'same',?)",
        ("x" * 11, cid),
    )
    s.decision(cid, "excluded")
    assert db.one("SELECT duplicate_of FROM clips WHERE id=?", (second,))["duplicate_of"] is None
    s.set_clips(eid, [second], s.get(eid)["revision"])
    s.decision(cid, "candidate")
    assert db.one("SELECT duplicate_of FROM clips WHERE id=?", (second,))["duplicate_of"] == cid


def test_fingerprint_does_not_restore_pre_trim_results(monkeypatch, tmp_path):
    from memebot.pipeline import fingerprint_clip

    db, s, eid, cid = episode_library(tmp_path)

    def concurrent_trim(*args):
        s.trim_clip(cid, 10, 390)
        return "old-range", []

    monkeypatch.setattr("memebot.pipeline.fingerprint", concurrent_trim)
    try:
        fingerprint_clip(db, cid)
    except ValueError:
        pass
    row = db.one("SELECT * FROM clips WHERE id=?", (cid,))
    assert row["start"] == 10 and row["exact_hash"] is None


def test_replacement_worker_waits_and_drains_after_incumbent_exit(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from memebot.config import Config
    from memebot.worker import run_worker, worker_lock

    db = Store(tmp_path / "state.db")
    started = Event()
    monkeypatch.setattr("memebot.worker.dispatch", lambda *a: "finished")

    def replacement():
        started.set()
        return run_worker(Config(tmp_path))

    with ThreadPoolExecutor(1) as pool:
        with worker_lock(tmp_path):
            jid = db.enqueue("test", {})
            result = pool.submit(replacement)
            assert started.wait(2)
            # A contender must remain available until the incumbent releases the lock.
            import time

            time.sleep(0.1)
        result.result(timeout=5)
    assert db.one("SELECT status FROM jobs WHERE id=?", (jid,))["status"] == "done"


def test_corrupt_cached_file_is_quarantined_and_downloaded_again(tmp_path, monkeypatch):
    from memebot.config import Config
    from memebot.pipeline import download_video

    db, s, eid, cid = episode_library(tmp_path)
    folder = tmp_path / "media" / ("x" * 11)
    folder.mkdir(parents=True)
    media = folder / "source.mp4"
    media.write_bytes(b"broken")
    db.execute("UPDATE videos SET path=?", (str(media),))

    def check(path):
        if Path(path).read_bytes() != b"good":
            raise ValueError("corrupt")
        return {"duration": 600, "has_audio": True}

    class Download:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, url, download):
            assert not media.exists()
            media.write_bytes(b"good")
            return {}

    monkeypatch.setattr("memebot.pipeline.probe", check)
    monkeypatch.setattr("memebot.pipeline.validate_decode", lambda p: None, raising=False)
    monkeypatch.setattr("yt_dlp.YoutubeDL", Download)
    assert download_video(db, Config(tmp_path), "x" * 11).read_bytes() == b"good"
    assert list((folder / "quarantine").rglob("source.mp4"))
    assert db.one("SELECT start,end FROM clips WHERE id=?", (cid,)) == {"start": 0, "end": 400}
