import pytest

from memebot.episodes import Conflict, Episodes
from memebot.store import Store


@pytest.fixture
def library(tmp_path):
    db = Store(tmp_path / "state.db")
    for letter in "ab":
        cid = "UC" + letter * 22
        db.add_source(cid, letter)
        vid = letter * 11
        db.save_video({"id": vid, "source_id": cid, "source_date": "2026-10-11"})
        db.execute(
            "UPDATE videos SET status='analyzed',duration=800,path=? WHERE id=?",
            (str(tmp_path / f"{vid}.mp4"), vid),
        )
        for n in range(4):
            db.execute(
                "INSERT INTO clips(video_id,start,end) VALUES(?,?,?)", (vid, n * 100, (n + 1) * 100)
            )
    return db, Episodes(db)


def test_draft_balances_sources_and_does_not_replace_user_edits(library):
    db, service = library
    eid = service.draft("2026-10-11")
    clips = service.clips(eid)
    assert [c["video_id"] for c in clips[:2]] == ["a" * 11, "b" * 11]
    assert sum(c["end"] - c["start"] for c in clips) == 500
    service.set_clips(eid, [c["id"] for c in clips[:3]], expected_revision=1)
    assert service.draft("2026-10-11") == eid
    assert len(service.clips(eid)) == 3


def test_clip_edits_invalidate_render_and_approval(library, tmp_path):
    db, s = library
    eid = s.draft("2026-10-11")
    artifact = tmp_path / "video.mp4"
    artifact.write_bytes(b"verified render")
    s.attach_render(eid, 1, artifact, 500)
    s.approve(eid, 1)
    c = s.clips(eid)[0]
    s.trim_clip(c["id"], 1, 99)
    row = s.get(eid)
    assert row["revision"] == 2 and row["approved_hash"] is None
    with pytest.raises(ValueError, match="Render"):
        s.approve(eid, 2)


def test_approval_rechecks_artifact_hash_and_minimum_duration(library, tmp_path):
    db, s = library
    eid = s.draft("2026-10-11")
    artifact = tmp_path / "video.mp4"
    artifact.write_bytes(b"render")
    s.attach_render(eid, 1, artifact, 500)
    s.approve(eid, 1)
    artifact.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        s.require_approved(eid)
    s.attach_render(eid, 1, artifact, 250)
    with pytest.raises(ValueError, match="5–10"):
        s.approve(eid, 1)


def test_stale_browser_revision_does_not_overwrite(library):
    db, s = library
    eid = s.draft("2026-10-11")
    s.metadata(
        eid,
        title="New title",
        description="My description",
        made_for_kids=False,
        expected_revision=1,
    )
    with pytest.raises(Conflict):
        s.metadata(
            eid, title="Stale title", description="", made_for_kids=False, expected_revision=1
        )
    assert s.get(eid)["title"] == "New title"


def test_merge_requires_same_video_adjacent_ranges_and_split_is_reversible(library):
    db, s = library
    eid = s.draft("2026-10-11")
    c = s.clips(eid)[0]
    second = s.split_clip(c["id"], 50)
    assert len(s.clips(eid)) == 6
    s.merge_clips(c["id"], second)
    assert len(s.clips(eid)) == 5
    assert s.clips(eid)[0]["end"] == 100
    with pytest.raises(ValueError):
        s.merge_clips(c["id"], 5)


def test_only_selected_date_and_available_nonduplicates_enter_episode(library):
    db, s = library
    db.execute("UPDATE clips SET duplicate_of=1 WHERE id=2")
    db.execute("UPDATE clips SET decision='excluded' WHERE id=3")
    db.execute("UPDATE videos SET source_date='2026-10-10' WHERE id=?", ("b" * 11,))
    eid = s.draft("2026-10-11")
    assert [c["id"] for c in s.clips(eid)] == [1, 4]


def test_published_episode_is_immutable(library):
    db, s = library
    eid = s.draft("2026-10-11")
    db.execute("UPDATE episodes SET upload_state='published' WHERE id=?", (eid,))
    with pytest.raises(ValueError, match="published"):
        s.trim_clip(s.clips(eid)[0]["id"], 1, 99)


def test_render_completing_after_edit_is_not_attached(library, tmp_path):
    db, s = library
    eid = s.draft("2026-10-11")
    s.metadata(eid, title="Changed", description="", made_for_kids=False, expected_revision=1)
    p = tmp_path / "out.mp4"
    p.write_bytes(b"old")
    with pytest.raises(Conflict):
        s.attach_render(eid, 1, p, 500)
