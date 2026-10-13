"""SQLite persistence shared by the UI and one background worker."""

import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .timeutil import utcnow

CHANNEL_RE = re.compile(r"UC[A-Za-z0-9_-]{22}\Z")
VIDEO_RE = re.compile(r"[A-Za-z0-9_-]{11}\Z")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
 url TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '', research TEXT NOT NULL DEFAULT '{}',
 last_checked TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS videos (
 id TEXT PRIMARY KEY, source_id TEXT REFERENCES sources(id), title TEXT NOT NULL DEFAULT '',
 published_at TEXT, source_date TEXT, url TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'discovered',
 path TEXT, duration REAL, error TEXT, markers TEXT NOT NULL DEFAULT '[]',
 provenance TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS videos_day ON videos(source_date);
CREATE TABLE IF NOT EXISTS clips (
 id INTEGER PRIMARY KEY, video_id TEXT NOT NULL REFERENCES videos(id),
 start REAL NOT NULL, end REAL NOT NULL, decision TEXT NOT NULL DEFAULT 'candidate',
 exact_hash TEXT, fingerprints TEXT NOT NULL DEFAULT '[]', duplicate_of INTEGER REFERENCES clips(id),
 near_duplicate_of INTEGER REFERENCES clips(id), notes TEXT NOT NULL DEFAULT '',
 CHECK(start>=0 AND end>start), UNIQUE(video_id,start,end));
CREATE TABLE IF NOT EXISTS episodes (
 id INTEGER PRIMARY KEY, source_date TEXT NOT NULL UNIQUE, revision INTEGER NOT NULL DEFAULT 1,
 title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', made_for_kids INTEGER NOT NULL DEFAULT 0,
 thumbnail_clip INTEGER REFERENCES clips(id), thumbnail_time REAL,
 render_revision INTEGER, render_path TEXT, render_hash TEXT, duration REAL,
 approved_revision INTEGER, approved_hash TEXT, approved_at TEXT,
 upload_id TEXT, upload_revision INTEGER, upload_hash TEXT, upload_session TEXT,
 upload_state TEXT NOT NULL DEFAULT 'none', destination_id TEXT,
 upload_error TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS episode_clips (
 episode_id INTEGER NOT NULL REFERENCES episodes(id), clip_id INTEGER NOT NULL REFERENCES clips(id),
 position INTEGER NOT NULL, PRIMARY KEY(episode_id,clip_id), UNIQUE(episode_id,position));
CREATE TABLE IF NOT EXISTS jobs (
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, dedup_key TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0,
 progress REAL NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '', error TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS active_job ON jobs(dedup_key) WHERE status IN ('queued','running');
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise RuntimeError("This database requires a newer MemeBot version")
            db.executescript(SCHEMA)
            db.execute("PRAGMA user_version=1")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def all(self, sql, args=()):
        with self.connect() as db:
            return [dict(r) for r in db.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        rows = self.all(sql, args)
        return rows[0] if rows else None

    def execute(self, sql, args=()):
        with self.connect() as db:
            return db.execute(sql, args).lastrowid

    def add_source(self, channel_id, name, *, enabled=True, notes="", research=None):
        if not CHANNEL_RE.fullmatch(channel_id):
            raise ValueError("Use a YouTube channel ID beginning UC followed by 22 characters")
        if not name.strip():
            raise ValueError("Enter a channel name")
        self.execute(
            """INSERT INTO sources(id,name,enabled,url,notes,research) VALUES(?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET name=excluded.name,enabled=excluded.enabled,
            notes=excluded.notes,research=excluded.research""",
            (
                channel_id,
                name.strip(),
                int(enabled),
                f"https://www.youtube.com/channel/{channel_id}",
                notes,
                json.dumps(research or {}),
            ),
        )

    def save_video(self, video):
        if not VIDEO_RE.fullmatch(video["id"]):
            raise ValueError("Invalid YouTube video ID")
        self.execute(
            """INSERT INTO videos(id,source_id,title,published_at,source_date,url,created_at)
            VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET source_id=excluded.source_id,
            title=excluded.title,published_at=excluded.published_at,source_date=excluded.source_date""",
            (
                video["id"],
                video.get("source_id"),
                video.get("title", ""),
                video.get("published_at"),
                video.get("source_date"),
                f"https://www.youtube.com/watch?v={video['id']}",
                utcnow(),
            ),
        )

    def import_legacy(self, path):
        if not Path(path).exists():
            return 0
        count = 0
        for name, item in json.loads(Path(path).read_text()).items():
            vid = item.get("video_id", "")
            if VIDEO_RE.fullmatch(vid) and not self.one("SELECT id FROM videos WHERE id=?", (vid,)):
                self.save_video({"id": vid, "title": f"Legacy discovery: {name}"})
                count += 1
        return count

    def enqueue(self, kind, payload):
        packed = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        key = kind + ":" + packed
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            found = db.execute(
                "SELECT id FROM jobs WHERE dedup_key=? AND status IN ('queued','running')", (key,)
            ).fetchone()
            if found:
                return found["id"]
            return db.execute(
                "INSERT INTO jobs(kind,payload,dedup_key,created_at,updated_at) VALUES(?,?,?,?,?)",
                (kind, packed, key, utcnow(), utcnow()),
            ).lastrowid

    def claim_job(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM jobs WHERE status='queued' ORDER BY id LIMIT 1"
            ).fetchone()
            if not row:
                return None
            db.execute(
                "UPDATE jobs SET status='running',attempts=attempts+1,updated_at=? WHERE id=?",
                (utcnow(), row["id"]),
            )
            return dict(row)

    def recover_jobs(self):
        # Caller must own worker.lock, proving no other worker still owns these jobs.
        self.execute(
            "UPDATE jobs SET status='queued',message='Resuming interrupted work',updated_at=? WHERE status='running'",
            (utcnow(),),
        )

    def progress(self, job_id, value, message):
        self.execute(
            "UPDATE jobs SET progress=?,message=?,updated_at=? WHERE id=?",
            (max(0, min(1, value)), message, utcnow(), job_id),
        )

    def finish_job(self, job_id, error=None):
        self.execute(
            "UPDATE jobs SET status=?,error=?,progress=?,updated_at=? WHERE id=?",
            ("failed" if error else "done", error, 0 if error else 1, utcnow(), job_id),
        )

    def setting(self, key, default=None):
        row = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return json.loads(row["value"]) if row else default

    def set_setting(self, key, value):
        self.execute(
            "INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )
