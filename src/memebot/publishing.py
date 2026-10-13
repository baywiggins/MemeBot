"""Resumable private uploads; uncertain outcomes never trigger a blind re-upload."""

import json
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests

from .episodes import Episodes
from .timeutil import utcnow

API = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3"
CHUNK = 8 * 1024 * 1024


class YouTubeHTTPError(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__(
            f"YouTube returned HTTP {status}. Check credentials, quota, and channel permissions."
        )


class Publisher:
    def __init__(self, store, session):
        self.store = store
        self.session = session
        self.episodes = Episodes(store)
        if not store.setting("installation_id"):
            store.set_setting("installation_id", uuid.uuid4().hex)

    def marker(self, eid, revision):
        return f"memebot-{self.store.setting('installation_id')}-{eid}-r{revision}"

    def request(self, method, url, **kwargs):
        try:
            response = self.session.request(method, url, timeout=90, **kwargs)
        except requests.RequestException:
            raise RuntimeError(
                "YouTube connection interrupted. Reconcile or resume the existing upload."
            ) from None
        if response.status_code not in (200, 201, 204, 308, 404, 410):
            raise YouTubeHTTPError(response.status_code)
        return response

    def destination(self):
        r = self.request(
            "GET", API + "/channels", params={"part": "snippet,contentDetails", "mine": "true"}
        )
        items = r.json().get("items", [])
        if not items:
            raise ValueError("The connected Google account has no YouTube channel")
        item = items[0]
        return {
            "id": item["id"],
            "name": item["snippet"]["title"],
            "uploads": item["contentDetails"]["relatedPlaylists"]["uploads"],
        }

    def _state(self, eid, state, error=None):
        self.store.execute(
            "UPDATE episodes SET upload_state=?,upload_error=? WHERE id=?", (state, error, eid)
        )

    def _complete(self, eid, video_id):
        self.store.execute(
            "UPDATE episodes SET upload_id=?,upload_state='private',upload_error=NULL WHERE id=?",
            (video_id, eid),
        )
        return video_id

    def _finalize(self, eid, video_id, path):
        self._complete(eid, video_id)
        self._thumbnail(eid, video_id, path.parent / "thumbnail.jpg")
        return video_id

    def upload_private(self, eid, progress=None):
        row = self.episodes.require_approved(eid)
        if row["upload_state"] in ("private", "published") and row["upload_id"]:
            if (
                row["upload_revision"] == row["revision"]
                and row["upload_hash"] == row["approved_hash"]
            ):
                return row["upload_id"]
            raise ValueError("The remote upload belongs to a different revision")
        if row["upload_state"] == "publishing":
            raise ValueError("Reconcile the publication result first")
        if row["upload_state"] in ("uncertain", "uploading") and not row["upload_session"]:
            raise ValueError(
                "Reconcile the uncertain upload in YouTube Studio before starting another"
            )
        path = Path(row["render_path"])
        size = path.stat().st_size
        session_url = row["upload_session"]
        if not session_url:
            confirmed = self.store.setting("destination")
            if not confirmed:
                raise ValueError("Connect and confirm the destination channel before uploading")
            destination = self.destination()
            # The UI/CLI must have explicitly confirmed this destination before upload.
            if confirmed["id"] != destination["id"]:
                raise ValueError(
                    "Connected destination changed. Reconnect and confirm the channel."
                )
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                current = db.execute("SELECT * FROM episodes WHERE id=?", (eid,)).fetchone()
                if (
                    current["revision"] != row["revision"]
                    or current["approved_hash"] != row["approved_hash"]
                ):
                    raise ValueError("Episode changed before upload; approve the new render")
                db.execute(
                    "UPDATE episodes SET upload_state='uploading',destination_id=?,upload_revision=?,upload_hash=? WHERE id=?",
                    (destination["id"], row["revision"], row["approved_hash"], eid),
                )
            body = {
                "snippet": {
                    "title": row["title"],
                    "description": row["description"],
                    "categoryId": "23",
                    "tags": [self.marker(eid, row["revision"])],
                },
                "status": {
                    "privacyStatus": "private",
                    "selfDeclaredMadeForKids": bool(row["made_for_kids"]),
                },
            }
            try:
                response = self.request(
                    "POST",
                    UPLOAD + "/videos",
                    params={"uploadType": "resumable", "part": "snippet,status"},
                    json=body,
                    headers={
                        "X-Upload-Content-Length": str(size),
                        "X-Upload-Content-Type": "video/mp4",
                    },
                )
                if response.status_code not in (200, 201):
                    raise YouTubeHTTPError(response.status_code)
                session_url = response.headers.get("Location")
                if not session_url:
                    raise RuntimeError(
                        "YouTube did not return an upload session. Reconcile before retrying."
                    )
                parsed = urlparse(session_url)
                if parsed.scheme != "https" or not (
                    parsed.hostname == "www.googleapis.com"
                    or (parsed.hostname or "").endswith(".googleapis.com")
                ):
                    raise RuntimeError("YouTube returned an unexpected upload endpoint")
                self.store.execute(
                    "UPDATE episodes SET upload_session=? WHERE id=?", (session_url, eid)
                )
                offset = 0
            except YouTubeHTTPError as exc:
                # A definite initiation rejection happened before any media transfer.
                state = "none" if 400 <= exc.status < 500 and exc.status != 408 else "uncertain"
                self._state(eid, state, str(exc))
                raise
            except Exception as exc:
                self._state(eid, "uncertain", str(exc))
                raise
        else:
            try:
                response = self.request(
                    "PUT",
                    session_url,
                    data=b"",
                    headers={"Content-Length": "0", "Content-Range": f"bytes */{size}"},
                )
                if response.status_code in (200, 201):
                    return self._finalize(eid, response.json()["id"], path)
                if response.status_code in (404, 410):
                    raise ValueError(
                        "Upload session expired. Reconcile the video from YouTube Studio before retrying."
                    )
                offset = self._offset(response)
            except Exception as exc:
                self._state(eid, "uncertain", str(exc))
                raise
        self._state(eid, "uploading")
        try:
            with path.open("rb") as stream:
                while offset < size:
                    stream.seek(offset)
                    chunk = stream.read(min(CHUNK, size - offset))
                    end = offset + len(chunk) - 1
                    response = self.request(
                        "PUT",
                        session_url,
                        data=chunk,
                        headers={
                            "Content-Type": "video/mp4",
                            "Content-Length": str(len(chunk)),
                            "Content-Range": f"bytes {offset}-{end}/{size}",
                        },
                    )
                    if response.status_code in (200, 201):
                        return self._finalize(eid, response.json()["id"], path)
                    if response.status_code != 308:
                        raise RuntimeError("Upload session unavailable; reconcile before retrying")
                    next_offset = self._offset(response)
                    if next_offset <= offset or next_offset > size:
                        raise RuntimeError("Upload made no progress; resume this session")
                    offset = next_offset
                    if progress:
                        progress(offset / size, "Uploading privately to YouTube")
            raise RuntimeError("Upload result is uncertain; reconcile this session")
        except Exception as exc:
            self._state(eid, "uncertain", str(exc))
            raise

    @staticmethod
    def _offset(response):
        value = response.headers.get("Range", "")
        return int(value.rsplit("-", 1)[-1]) + 1 if value else 0

    def _thumbnail(self, eid, video_id, path):
        if not path.exists():
            return
        try:
            with path.open("rb") as media:
                r = self.request(
                    "POST",
                    UPLOAD + "/thumbnails/set",
                    params={"videoId": video_id, "uploadType": "media"},
                    data=media,
                    headers={"Content-Type": "image/jpeg"},
                )
                if not r.ok:
                    raise RuntimeError("Custom thumbnail was not accepted")
        except Exception:
            self.store.execute(
                "UPDATE episodes SET upload_error=? WHERE id=?",
                (
                    "Video uploaded privately; custom thumbnail was not accepted. Set it in YouTube Studio.",
                    eid,
                ),
            )

    def _remote(self, row, video_id):
        r = self.request(
            "GET",
            API + "/videos",
            params={"id": video_id, "part": "snippet,status,processingDetails"},
        )
        items = r.json().get("items", [])
        if not items:
            raise ValueError("Video not found on the connected account")
        video = items[0]
        if video["snippet"]["channelId"] != row["destination_id"]:
            raise ValueError("Video belongs to a different destination channel")
        if self.marker(row["id"], row["upload_revision"]) not in video["snippet"].get("tags", []):
            raise ValueError("Video does not match this MemeBot episode revision")
        return video

    def reconcile(self, eid, video_id):
        row = self.episodes.require_approved(eid)
        video = self._remote(row, video_id)
        status = "published" if video["status"]["privacyStatus"] == "public" else "private"
        self.store.execute(
            "UPDATE episodes SET upload_id=?,upload_state=?,upload_error=NULL WHERE id=?",
            (video_id, status, eid),
        )
        if row["render_path"]:
            self._thumbnail(eid, video_id, Path(row["render_path"]).parent / "thumbnail.jpg")
        return video_id

    def recover_missing(self, eid, *, confirmed_absent):
        """Reconcile the owned upload inventory before an explicitly requested reset."""
        if not confirmed_absent:
            raise ValueError("First confirm in YouTube Studio that no matching upload exists")
        row = self.episodes.get(eid)
        if row["upload_state"] not in ("uncertain", "uploading") or row["upload_id"]:
            raise ValueError("Only an unresolved upload without a video ID can be recovered here")
        if row["upload_session"]:
            size = Path(row["render_path"]).stat().st_size
            response = self.request(
                "PUT",
                row["upload_session"],
                data=b"",
                headers={"Content-Length": "0", "Content-Range": f"bytes */{size}"},
            )
            if response.status_code in (200, 201):
                return self._finalize(eid, response.json()["id"], Path(row["render_path"]))
            if response.status_code not in (404, 410):
                raise ValueError(
                    "This upload session is still active. Use Upload / resume privately."
                )
        destination = self.destination()
        if destination["id"] != row["destination_id"]:
            raise ValueError("Reconnect the original destination channel before recovery")
        token = None
        seen = set()
        marker = self.marker(eid, row["upload_revision"])
        while True:
            params = {
                "playlistId": destination["uploads"],
                "part": "contentDetails",
                "maxResults": 50,
            }
            if token:
                params["pageToken"] = token
            response = self.request("GET", API + "/playlistItems", params=params)
            if not response.ok:
                raise ValueError("Upload inventory is unavailable; recovery was not reset")
            page = response.json()
            ids = [item.get("contentDetails", {}).get("videoId") for item in page.get("items", [])]
            ids = [v for v in ids if v]
            if ids:
                response = self.request(
                    "GET", API + "/videos", params={"id": ",".join(ids), "part": "snippet,status"}
                )
                if not response.ok:
                    raise ValueError("Upload inventory could not be verified")
                for video in response.json().get("items", []):
                    if video["snippet"]["channelId"] == row["destination_id"] and marker in video[
                        "snippet"
                    ].get("tags", []):
                        return self.reconcile(eid, video["id"])
            token = page.get("nextPageToken")
            if not token:
                break
            if token in seen:
                raise ValueError("Upload inventory pagination was incomplete; retry recovery")
            seen.add(token)
        # API visibility can lag. The explicit Studio confirmation is required in
        # addition to this scan; a network error or partial scan never reaches here.
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT * FROM episodes WHERE id=?", (eid,)).fetchone()
            if any(
                current[k] != row[k]
                for k in ("revision", "upload_state", "upload_session", "upload_id")
            ):
                raise ValueError("Upload state changed during recovery; refresh and retry")
            db.execute(
                "INSERT INTO settings VALUES(?,?)",
                (
                    f"upload_recovery:{eid}:{uuid.uuid4().hex}",
                    json.dumps(
                        {"at": utcnow(), "studio_absence_confirmed": True, "previous": dict(row)}
                    ),
                ),
            )
            db.execute(
                "UPDATE episodes SET upload_state='none',upload_session=NULL,upload_revision=NULL,upload_hash=NULL,destination_id=NULL,upload_error=NULL WHERE id=?",
                (eid,),
            )
        return None

    def publish(self, eid):
        row = self.episodes.require_approved(eid)
        if row["upload_state"] == "published":
            return row["upload_id"]
        if row["upload_state"] not in ("private", "publishing") or not row["upload_id"]:
            raise ValueError("Upload privately and reconcile any uncertainty before publishing")
        if row["upload_revision"] != row["revision"] or row["upload_hash"] != row["approved_hash"]:
            raise ValueError("The uploaded video is not the approved revision")
        video = self._remote(row, row["upload_id"])
        if video["status"]["privacyStatus"] == "public":
            self._state(eid, "published")
            return row["upload_id"]
        if video.get("processingDetails", {}).get("processingStatus") != "succeeded":
            raise ValueError(
                "YouTube is still processing this video or processing failed. Check YouTube Studio."
            )
        status = {
            k: v
            for k, v in video["status"].items()
            if k
            in (
                "embeddable",
                "license",
                "publicStatsViewable",
                "selfDeclaredMadeForKids",
                "containsSyntheticMedia",
            )
        }
        status["privacyStatus"] = "public"
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT * FROM episodes WHERE id=?", (eid,)).fetchone()
            if (
                current["revision"] != row["revision"]
                or current["approved_hash"] != row["approved_hash"]
            ):
                raise ValueError("Episode changed before publication")
            db.execute("UPDATE episodes SET upload_state='publishing' WHERE id=?", (eid,))
        try:
            r = self.request(
                "PUT",
                API + "/videos",
                params={"part": "status"},
                json={"id": row["upload_id"], "status": status},
            )
            if not r.ok or r.json().get("status", {}).get("privacyStatus") != "public":
                raise RuntimeError("Publication response was inconclusive; retry to reconcile")
            self._state(eid, "published")
            return row["upload_id"]
        except Exception as exc:
            self._state(eid, "publishing", str(exc))
            raise
