"""Revisioned editorial operations; all mutations invalidate approval atomically."""

import hashlib
import math
from pathlib import Path

from .timeutil import utcnow


class Conflict(ValueError):
    pass


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class Episodes:
    def __init__(self, store):
        self.store = store

    def get(self, eid):
        row = self.store.one("SELECT * FROM episodes WHERE id=?", (eid,))
        if not row:
            raise ValueError("Episode not found")
        return row

    def clips(self, eid):
        return self.store.all(
            """SELECT c.*,v.path,v.url,v.source_id,v.title AS source_title,
            v.duration AS source_duration,ec.position FROM episode_clips ec
            JOIN clips c ON c.id=ec.clip_id JOIN videos v ON v.id=c.video_id
            WHERE ec.episode_id=? ORDER BY ec.position""",
            (eid,),
        )

    @staticmethod
    def _editable(db, eid, expected=None):
        row = db.execute("SELECT * FROM episodes WHERE id=?", (eid,)).fetchone()
        if not row:
            raise ValueError("Episode not found")
        if row["upload_state"] in ("uploading", "uncertain", "publishing", "published"):
            raise ValueError(
                f"Episode is {row['upload_state']}; reconcile active uploads before editing"
            )
        if expected is not None and row["revision"] != expected:
            raise Conflict("This episode changed in another session. Refresh before saving.")
        return row

    @staticmethod
    def _bump(db, eid):
        row = db.execute("SELECT * FROM episodes WHERE id=?", (eid,)).fetchone()
        if row["upload_id"]:
            key = f"previous_upload:{eid}:{row['upload_id']}"
            import json

            db.execute("INSERT OR IGNORE INTO settings VALUES(?,?)", (key, json.dumps(dict(row))))
        db.execute(
            """UPDATE episodes SET revision=revision+1,render_revision=NULL,
            render_path=NULL,render_hash=NULL,duration=NULL,approved_revision=NULL,
            approved_hash=NULL,approved_at=NULL,upload_id=NULL,upload_revision=NULL,
            upload_hash=NULL,upload_session=NULL,upload_state='none',upload_error=NULL,
            destination_id=NULL WHERE id=?""",
            (eid,),
        )

    def _affected(self, db, cid):
        ids = [
            r[0] for r in db.execute("SELECT episode_id FROM episode_clips WHERE clip_id=?", (cid,))
        ]
        for eid in ids:
            self._editable(db, eid)
        return ids

    @staticmethod
    def _clear_duplicate_dependents(db, cid):
        db.execute("UPDATE clips SET duplicate_of=NULL WHERE duplicate_of=?", (cid,))
        db.execute("UPDATE clips SET near_duplicate_of=NULL WHERE near_duplicate_of=?", (cid,))

    @staticmethod
    def _refresh_exact_group(db, digest):
        if not digest:
            return
        rows = db.execute(
            """SELECT c.*,v.source_date,EXISTS(SELECT 1 FROM episode_clips ec
            JOIN episodes e ON e.id=ec.episode_id WHERE ec.clip_id=c.id
            AND e.upload_state='published') AS published
            FROM clips c JOIN videos v ON v.id=c.video_id WHERE c.exact_hash=? ORDER BY c.id""",
            (digest,),
        ).fetchall()
        for row in rows:
            if row["published"]:
                continue
            candidates = [r for r in rows if r["id"] != row["id"] and r["decision"] != "excluded"]
            owner = next((r for r in candidates if r["published"]), None)
            if owner is None:
                owner = next(
                    (
                        r
                        for r in candidates
                        if r["source_date"] == row["source_date"] and r["id"] < row["id"]
                    ),
                    None,
                )
            db.execute(
                "UPDATE clips SET duplicate_of=? WHERE id=?",
                (owner["id"] if owner else None, row["id"]),
            )

    @staticmethod
    def _order(db, eid, ids):
        db.execute("DELETE FROM episode_clips WHERE episode_id=?", (eid,))
        db.executemany(
            "INSERT INTO episode_clips VALUES(?,?,?)", [(eid, cid, i) for i, cid in enumerate(ids)]
        )

    def draft(self, day, brand="MemeBot"):
        from datetime import date

        date.fromisoformat(day)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id FROM episodes WHERE source_date=?", (day,)).fetchone()
            if row:
                return row["id"]
            rows = db.execute(
                """SELECT c.*,v.source_id,v.url FROM clips c JOIN videos v ON v.id=c.video_id
                WHERE v.source_date=? AND v.status='analyzed' AND v.path IS NOT NULL
                AND c.decision!='excluded' AND c.duplicate_of IS NULL
                AND NOT EXISTS (SELECT 1 FROM episode_clips ec JOIN episodes e ON e.id=ec.episode_id
                    WHERE ec.clip_id=c.id AND e.upload_state='published')
                ORDER BY v.source_id,v.published_at,v.id,c.start""",
                (day,),
            ).fetchall()
            groups = {}
            for c in rows:
                groups.setdefault(c["source_id"], []).append(c)
            chosen = []
            total = 0
            while groups and total < 480:
                for source in list(groups):
                    clip = groups[source].pop(0)
                    duration = clip["end"] - clip["start"]
                    if total + duration <= 600:
                        chosen.append(clip)
                        total += duration
                    if not groups[source]:
                        del groups[source]
                    if total >= 480:
                        break
            if not chosen:
                raise ValueError(
                    "No usable clips for this date. Collect and analyze footage first."
                )
            description = (
                "Sources (compilation uploaders; original creators may differ):\n"
                + "\n".join(dict.fromkeys(c["url"] for c in chosen))
            )
            eid = db.execute(
                "INSERT INTO episodes(source_date,title,description,created_at) VALUES(?,?,?,?)",
                (day, f"{brand} · Daily memes · {day}", description, utcnow()),
            ).lastrowid
            self._order(db, eid, [c["id"] for c in chosen])
            db.execute(
                "UPDATE episodes SET thumbnail_clip=?,thumbnail_time=? WHERE id=?",
                (chosen[0]["id"], chosen[0]["start"], eid),
            )
            return eid

    def set_clips(self, eid, ids, expected_revision):
        if len(ids) != len(set(ids)):
            raise ValueError("A clip cannot appear twice in an episode")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._editable(db, eid, expected_revision)
            for cid in ids:
                c = db.execute(
                    """SELECT c.*,v.source_date,v.path FROM clips c JOIN videos v ON v.id=c.video_id WHERE c.id=?""",
                    (cid,),
                ).fetchone()
                if (
                    not c
                    or c["source_date"] != row["source_date"]
                    or not c["path"]
                    or c["decision"] == "excluded"
                    or c["duplicate_of"]
                ):
                    raise ValueError(
                        "Select available, nonduplicate clips from this episode’s source date"
                    )
            self._order(db, eid, ids)
            if row["thumbnail_clip"] not in ids:
                first = (
                    db.execute("SELECT start FROM clips WHERE id=?", (ids[0],)).fetchone()
                    if ids
                    else None
                )
                db.execute(
                    "UPDATE episodes SET thumbnail_clip=?,thumbnail_time=? WHERE id=?",
                    (ids[0] if ids else None, first["start"] if first else None, eid),
                )
            self._bump(db, eid)

    def metadata(self, eid, *, title, description, made_for_kids, expected_revision):
        if not title.strip() or len(title) > 100 or "<" in title or ">" in title:
            raise ValueError("Use a title of 1–100 characters without angle brackets")
        if len(description.encode("utf-8")) > 5000:
            raise ValueError("Description must be at most 5,000 UTF-8 bytes")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._editable(db, eid, expected_revision)
            db.execute(
                "UPDATE episodes SET title=?,description=?,made_for_kids=? WHERE id=?",
                (title.strip(), description, int(made_for_kids), eid),
            )
            self._bump(db, eid)

    def thumbnail(self, eid, cid, at, expected_revision):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._editable(db, eid, expected_revision)
            c = db.execute(
                "SELECT c.* FROM clips c JOIN episode_clips ec ON ec.clip_id=c.id WHERE ec.episode_id=? AND c.id=?",
                (eid, cid),
            ).fetchone()
            if not c or not c["start"] <= at < c["end"]:
                raise ValueError("Choose a frame inside a selected clip")
            db.execute(
                "UPDATE episodes SET thumbnail_clip=?,thumbnail_time=? WHERE id=?", (cid, at, eid)
            )
            self._bump(db, eid)

    def trim_clip(self, cid, start, end):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            c = db.execute(
                "SELECT c.*,v.duration FROM clips c JOIN videos v ON v.id=c.video_id WHERE c.id=?",
                (cid,),
            ).fetchone()
            if (
                not c
                or not all(math.isfinite(v) for v in [start, end])
                or not 0 <= start < end <= c["duration"]
            ):
                raise ValueError("Clip bounds must be inside the source video")
            ids = self._affected(db, cid)
            self._clear_duplicate_dependents(db, cid)
            db.execute(
                "UPDATE clips SET start=?,end=?,exact_hash=NULL,fingerprints='[]',duplicate_of=NULL,near_duplicate_of=NULL WHERE id=?",
                (start, end, cid),
            )
            for eid in ids:
                ep = db.execute("SELECT * FROM episodes WHERE id=?", (eid,)).fetchone()
                if ep["thumbnail_clip"] == cid and not start <= (ep["thumbnail_time"] or 0) < end:
                    db.execute("UPDATE episodes SET thumbnail_time=? WHERE id=?", (start, eid))
                self._bump(db, eid)

    def split_clip(self, cid, at):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            c = db.execute("SELECT * FROM clips WHERE id=?", (cid,)).fetchone()
            if not c or not c["start"] < at < c["end"]:
                raise ValueError("Split point must be inside the clip")
            affected = self._affected(db, cid)
            self._clear_duplicate_dependents(db, cid)
            db.execute(
                "UPDATE clips SET end=?,exact_hash=NULL,fingerprints='[]',duplicate_of=NULL,near_duplicate_of=NULL WHERE id=?",
                (at, cid),
            )
            retained = db.execute(
                "SELECT id FROM clips WHERE video_id=? AND start=? AND end=?",
                (c["video_id"], at, c["end"]),
            ).fetchone()
            if retained:
                new = retained["id"]
                self._affected(db, new)
                self._clear_duplicate_dependents(db, new)
                db.execute(
                    "UPDATE clips SET decision=?,exact_hash=NULL,fingerprints='[]',duplicate_of=NULL,near_duplicate_of=NULL WHERE id=?",
                    (c["decision"], new),
                )
            else:
                new = db.execute(
                    "INSERT INTO clips(video_id,start,end,decision) VALUES(?,?,?,?)",
                    (c["video_id"], at, c["end"], c["decision"]),
                ).lastrowid
            for eid in affected:
                ids = [
                    r[0]
                    for r in db.execute(
                        "SELECT clip_id FROM episode_clips WHERE episode_id=? ORDER BY position",
                        (eid,),
                    )
                ]
                ids.insert(ids.index(cid) + 1, new)
                self._order(db, eid, list(dict.fromkeys(ids)))
                db.execute(
                    "UPDATE episodes SET thumbnail_clip=? WHERE id=? AND thumbnail_clip=? AND thumbnail_time>=?",
                    (new, eid, cid, at),
                )
                self._bump(db, eid)
            return new

    def merge_clips(self, first, second):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            a = db.execute("SELECT * FROM clips WHERE id=?", (first,)).fetchone()
            b = db.execute("SELECT * FROM clips WHERE id=?", (second,)).fetchone()
            if (
                not a
                or not b
                or a["video_id"] != b["video_id"]
                or abs(a["end"] - b["start"]) > 0.05
            ):
                raise ValueError("Merge only consecutive clips from the same source video")
            affected = set(self._affected(db, first) + self._affected(db, second))
            self._clear_duplicate_dependents(db, first)
            self._clear_duplicate_dependents(db, second)
            # Keep the second record excluded, retaining duplicate/history references.
            db.execute(
                "UPDATE clips SET end=?,exact_hash=NULL,fingerprints='[]',duplicate_of=NULL,near_duplicate_of=NULL WHERE id=?",
                (b["end"], first),
            )
            db.execute("UPDATE clips SET decision='excluded' WHERE id=?", (second,))
            for eid in affected:
                ids = [
                    r[0]
                    for r in db.execute(
                        "SELECT clip_id FROM episode_clips WHERE episode_id=? ORDER BY position",
                        (eid,),
                    )
                ]
                ids = [first if i == second else i for i in ids]
                self._order(db, eid, list(dict.fromkeys(ids)))
                db.execute(
                    "UPDATE episodes SET thumbnail_clip=? WHERE id=? AND thumbnail_clip=?",
                    (first, eid, second),
                )
                self._bump(db, eid)

    def decision(self, cid, decision):
        if decision not in ("candidate", "included", "excluded"):
            raise ValueError("Invalid review decision")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            ids = self._affected(db, cid)
            clip = db.execute("SELECT exact_hash FROM clips WHERE id=?", (cid,)).fetchone()
            if not clip:
                raise ValueError("Clip not found")
            self._clear_duplicate_dependents(db, cid)
            db.execute("UPDATE clips SET decision=? WHERE id=?", (decision, cid))
            self._refresh_exact_group(db, clip["exact_hash"])
            if decision == "excluded":
                for eid in ids:
                    keep = [
                        r[0]
                        for r in db.execute(
                            "SELECT clip_id FROM episode_clips WHERE episode_id=? AND clip_id!=? ORDER BY position",
                            (eid, cid),
                        )
                    ]
                    self._order(db, eid, keep)
                    db.execute(
                        "UPDATE episodes SET thumbnail_clip=NULL,thumbnail_time=NULL WHERE id=? AND thumbnail_clip=?",
                        (eid, cid),
                    )
                    self._bump(db, eid)

    def attach_render(self, eid, revision, path, duration):
        digest = file_hash(path)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._editable(db, eid, revision)
            db.execute(
                """UPDATE episodes SET render_revision=?,render_path=?,render_hash=?,duration=?,
                approved_revision=NULL,approved_hash=NULL,approved_at=NULL WHERE id=?""",
                (revision, str(Path(path).resolve()), digest, duration, eid),
            )

    def approve(self, eid, revision):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._editable(db, eid, revision)
            if row["render_revision"] != revision or not row["render_path"]:
                raise ValueError("Render the current episode before approval")
            if not row["duration"] or not 300 <= row["duration"] <= 600.2:
                raise ValueError("Publishing requires a finished 5–10 minute episode")
            if file_hash(row["render_path"]) != row["render_hash"]:
                raise ValueError("The rendered file changed. Render again before approval.")
            db.execute(
                "UPDATE episodes SET approved_revision=?,approved_hash=?,approved_at=? WHERE id=?",
                (revision, row["render_hash"], utcnow(), eid),
            )

    def require_approved(self, eid):
        row = self.get(eid)
        if (
            row["approved_revision"] != row["revision"]
            or row["approved_hash"] != row["render_hash"]
            or not row["approved_hash"]
        ):
            raise ValueError("Approve the current rendered episode before uploading or publishing")
        if not row["render_path"] or file_hash(row["render_path"]) != row["approved_hash"]:
            raise ValueError("The approved video file changed; render and approve it again")
        if not 300 <= row["duration"] <= 600.2:
            raise ValueError("Publishing requires a 5–10 minute episode")
        return row
