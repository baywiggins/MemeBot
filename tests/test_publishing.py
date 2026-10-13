import json

import pytest
import requests
import responses

from memebot.episodes import Episodes
from memebot.publishing import API, UPLOAD, Publisher
from memebot.store import Store

CID = "UC" + "d" * 22
VID = "uploadvideo"


@pytest.fixture
def published_fixture(tmp_path):
    db = Store(tmp_path / "state.db")
    db.set_setting("destination", {"id": CID, "name": "My channel"})
    eid = db.execute(
        "INSERT INTO episodes(source_date,title,created_at) VALUES('2026-10-11','Daily memes','now')"
    )
    path = tmp_path / "video.mp4"
    path.write_bytes(b"x" * 1024)
    service = Episodes(db)
    service.attach_render(eid, 1, path, 480)
    service.approve(eid, 1)
    publisher = Publisher(db, requests.Session())
    return db, service, eid, publisher


def destination():
    return {
        "items": [
            {
                "id": CID,
                "snippet": {"title": "My channel"},
                "contentDetails": {"relatedPlaylists": {"uploads": "UUtest"}},
            }
        ]
    }


def remote(p, eid, privacy="private", processing="succeeded"):
    return {
        "items": [
            {
                "id": VID,
                "snippet": {"channelId": CID, "tags": [p.marker(eid, 1)]},
                "status": {
                    "privacyStatus": privacy,
                    "uploadStatus": "processed",
                    "selfDeclaredMadeForKids": False,
                },
                "processingDetails": {"processingStatus": processing},
            }
        ]
    }


@responses.activate
def test_private_upload_persists_remote_id_and_repeat_does_not_upload(published_fixture):
    db, s, eid, p = published_fixture
    responses.get(API + "/channels", json=destination())
    responses.post(
        UPLOAD + "/videos",
        status=200,
        headers={"Location": "https://www.googleapis.com/upload/session/one"},
    )
    responses.put("https://www.googleapis.com/upload/session/one", json={"id": VID})
    assert p.upload_private(eid) == VID
    assert p.upload_private(eid) == VID
    assert s.get(eid)["upload_state"] == "private"
    post = next(c for c in responses.calls if c.request.method == "POST")
    assert json.loads(post.request.body)["status"]["privacyStatus"] == "private"
    assert len([c for c in responses.calls if c.request.method == "POST"]) == 1


@responses.activate
def test_timeout_after_final_chunk_resumes_without_duplicate(published_fixture):
    db, s, eid, p = published_fixture
    responses.get(API + "/channels", json=destination())
    responses.post(
        UPLOAD + "/videos", headers={"Location": "https://www.googleapis.com/upload/session/one"}
    )
    responses.put(
        "https://www.googleapis.com/upload/session/one",
        body=requests.ConnectionError("lost response"),
    )
    with pytest.raises(RuntimeError):
        p.upload_private(eid)
    assert s.get(eid)["upload_state"] == "uncertain"
    responses.replace(
        responses.PUT, "https://www.googleapis.com/upload/session/one", json={"id": VID}
    )
    assert p.upload_private(eid) == VID
    assert len([c for c in responses.calls if c.request.method == "POST"]) == 1


@responses.activate
def test_ambiguous_without_session_cannot_start_a_fresh_upload(published_fixture):
    db, s, eid, p = published_fixture
    db.execute(
        "UPDATE episodes SET upload_state='uncertain',destination_id=? WHERE id=?", (CID, eid)
    )
    with pytest.raises(ValueError, match="Reconcile"):
        p.upload_private(eid)
    assert len(responses.calls) == 0


@responses.activate
def test_publish_requires_processing_and_approved_exact_revision(published_fixture):
    db, s, eid, p = published_fixture
    row = s.get(eid)
    db.execute(
        "UPDATE episodes SET upload_id=?,upload_revision=1,upload_hash=?,destination_id=?,upload_state='private' WHERE id=?",
        (VID, row["render_hash"], CID, eid),
    )
    responses.get(API + "/videos", json=remote(p, eid, processing="processing"))
    with pytest.raises(ValueError, match="processing"):
        p.publish(eid)
    responses.replace(responses.GET, API + "/videos", json=remote(p, eid))
    responses.put(API + "/videos", json={"id": VID, "status": {"privacyStatus": "public"}})
    assert p.publish(eid) == VID
    assert s.get(eid)["upload_state"] == "published"
    assert p.publish(eid) == VID


@responses.activate
def test_reconciliation_checks_marker_and_destination(published_fixture):
    db, s, eid, p = published_fixture
    db.execute(
        "UPDATE episodes SET upload_state='uncertain',upload_revision=1,upload_hash=render_hash,destination_id=? WHERE id=?",
        (CID, eid),
    )
    wrong = remote(p, eid)
    wrong["items"][0]["snippet"]["channelId"] = "UC" + "e" * 22
    responses.get(API + "/videos", json=wrong)
    with pytest.raises(ValueError, match="destination"):
        p.reconcile(eid, VID)
    assert s.get(eid)["upload_id"] is None


@responses.activate
def test_publish_retry_reconciles_public_state(published_fixture):
    db, s, eid, p = published_fixture
    db.execute(
        "UPDATE episodes SET upload_id=?,upload_revision=1,upload_hash=render_hash,destination_id=?,upload_state='publishing' WHERE id=?",
        (VID, CID, eid),
    )
    responses.get(API + "/videos", json=remote(p, eid, privacy="public"))
    assert p.publish(eid) == VID
    assert s.get(eid)["upload_state"] == "published"
    assert not [c for c in responses.calls if c.request.method == "PUT"]


@responses.activate
def test_definite_initiation_rejection_does_not_lock_episode(published_fixture):
    db, s, eid, p = published_fixture
    responses.get(API + "/channels", json=destination())
    responses.post(UPLOAD + "/videos", status=403)
    with pytest.raises(RuntimeError):
        p.upload_private(eid)
    assert s.get(eid)["upload_state"] == "none"
    s.metadata(eid, title="Corrected", description="", made_for_kids=False, expected_revision=1)


@responses.activate
def test_recovered_completed_upload_also_sets_thumbnail(published_fixture, tmp_path):
    db, s, eid, p = published_fixture
    (tmp_path / "thumbnail.jpg").write_bytes(b"jpeg")
    db.execute(
        "UPDATE episodes SET upload_state='uncertain',upload_session='https://www.googleapis.com/upload/session/one',upload_revision=1,upload_hash=render_hash,destination_id=? WHERE id=?",
        (CID, eid),
    )
    responses.put("https://www.googleapis.com/upload/session/one", json={"id": VID})
    responses.post(UPLOAD + "/thumbnails/set", json={"items": []})
    assert p.upload_private(eid) == VID
    assert any("/thumbnails/set" in c.request.url for c in responses.calls)


@responses.activate
def test_expired_upload_recovery_requires_confirmation_and_scans_existing(published_fixture):
    db, s, eid, p = published_fixture
    db.execute(
        "UPDATE episodes SET upload_state='uncertain',upload_session='https://www.googleapis.com/upload/session/one',upload_revision=1,upload_hash=render_hash,destination_id=? WHERE id=?",
        (CID, eid),
    )
    with pytest.raises(ValueError, match="confirm"):
        p.recover_missing(eid, confirmed_absent=False)
    responses.put("https://www.googleapis.com/upload/session/one", status=410)
    responses.get(API + "/channels", json=destination())
    responses.get(API + "/playlistItems", json={"items": []})
    assert p.recover_missing(eid, confirmed_absent=True) is None
    assert s.get(eid)["upload_state"] == "none" and s.get(eid)["upload_session"] is None
    assert db.all("SELECT * FROM settings WHERE key LIKE 'upload_recovery:%'")


@responses.activate
def test_recovery_links_existing_upload_instead_of_resetting(published_fixture):
    db, s, eid, p = published_fixture
    db.execute(
        "UPDATE episodes SET upload_state='uncertain',upload_revision=1,upload_hash=render_hash,destination_id=? WHERE id=?",
        (CID, eid),
    )
    responses.get(API + "/channels", json=destination())
    responses.get(API + "/playlistItems", json={"items": [{"contentDetails": {"videoId": VID}}]})
    responses.get(API + "/videos", json=remote(p, eid))
    assert p.recover_missing(eid, confirmed_absent=True) == VID
    assert s.get(eid)["upload_state"] == "private"
    assert not [c for c in responses.calls if c.request.method == "POST"]
