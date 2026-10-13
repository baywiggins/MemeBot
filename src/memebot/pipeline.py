"""Long-running pipeline stages, called by the worker rather than UI reruns."""

import json
import shutil
import uuid
from pathlib import Path

from .discovery import YouTubeCatalog, collect_catalog
from .episodes import Episodes
from .media import (
    detect_scenes,
    fingerprint,
    probe,
    render_segments,
    similar_fingerprints,
    thumbnail,
    validate_decode,
)
from .timeutil import yesterday


class QuietDownloadLog:
    def debug(self, *args):
        pass

    def warning(self, *args):
        pass

    def error(self, *args):
        pass


def download_video(store, config, vid, progress=None):
    from yt_dlp import YoutubeDL

    row = store.one("SELECT * FROM videos WHERE id=?", (vid,))
    if not row:
        raise ValueError("Source video not found")
    folder = config.home / "media" / vid
    folder.mkdir(parents=True, exist_ok=True)
    cached = (
        Path(row["path"])
        if row["path"]
        else next(
            (p for p in folder.glob("source.*") if p.suffix in (".mp4", ".mkv", ".webm", ".mov")),
            None,
        )
    )

    def validate(path):
        meta = probe(path)
        stamp = [path.stat().st_size, path.stat().st_mtime_ns]
        if store.setting(f"media_validated:{vid}") != stamp:
            validate_decode(path)
            store.set_setting(f"media_validated:{vid}", stamp)
        return meta

    if cached and cached.exists():
        try:
            meta = validate(cached)
        except (ValueError, RuntimeError, OSError):
            quarantine = folder / "quarantine" / uuid.uuid4().hex
            quarantine.mkdir(parents=True)
            for old in set([cached, *folder.glob("source.*")]):
                if old.is_file():
                    shutil.move(str(old), str(quarantine / old.name))
            store.execute("UPDATE videos SET path=NULL,status='discovered' WHERE id=?", (vid,))
            with store.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                for c in conn.execute("SELECT id FROM clips WHERE video_id=?", (vid,)).fetchall():
                    Episodes._clear_duplicate_dependents(conn, c["id"])
                conn.execute(
                    "UPDATE clips SET exact_hash=NULL,fingerprints='[]',duplicate_of=NULL,near_duplicate_of=NULL WHERE video_id=?",
                    (vid,),
                )
        else:
            store.execute(
                "UPDATE videos SET path=?,duration=?,error=NULL,status=? WHERE id=?",
                (
                    str(cached),
                    meta["duration"],
                    "analyzed" if row["status"] == "analyzed" else "downloaded",
                    vid,
                ),
            )
            return cached
    if shutil.disk_usage(config.home).free < 2 * 1024**3:
        raise RuntimeError("Less than 2 GB free disk space. Free space before downloading footage.")
    store.execute("UPDATE videos SET status='downloading',error=NULL WHERE id=?", (vid,))

    def hook(event):
        if progress and event["status"] == "downloading":
            total = event.get("total_bytes") or event.get("total_bytes_estimate") or 1
            progress(min(event.get("downloaded_bytes", 0) / total, 1), "Downloading source footage")

    runtime = "node" if shutil.which("node") else "deno"
    options = {
        "outtmpl": str(folder / "source.%(ext)s"),
        "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "continuedl": True,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 30,
        "quiet": True,
        "no_warnings": True,
        "logger": QuietDownloadLog(),
        "js_runtimes": {runtime: {}},
        "progress_hooks": [hook],
        "max_filesize": 2 * 1024**3,
    }
    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(row["url"], download=True)
        paths = list(folder.glob("source.*"))
        path = next((p for p in paths if p.suffix in (".mp4", ".mkv", ".webm", ".mov")), None)
        if not path:
            raise RuntimeError("No completed video was downloaded")
        meta = validate(path)
        provenance = {
            k: info.get(k)
            for k in ["uploader", "uploader_id", "channel_id", "license", "webpage_url"]
        }
        store.execute(
            "UPDATE videos SET status='downloaded',path=?,duration=?,provenance=?,error=NULL WHERE id=?",
            (str(path), meta["duration"], json.dumps(provenance), vid),
        )
        return path
    except Exception:
        message = "Source download failed. The video may be unavailable; check the source and retry. Update yt-dlp if extraction fails."
        store.execute("UPDATE videos SET status='failed',error=? WHERE id=?", (message, vid))
        raise RuntimeError(message) from None


def fingerprint_clip(store, cid):
    clip = store.one(
        "SELECT c.*,v.path,v.source_date FROM clips c JOIN videos v ON v.id=c.video_id WHERE c.id=?",
        (cid,),
    )
    if clip["exact_hash"]:
        exact, prints = clip["exact_hash"], json.loads(clip["fingerprints"])
    else:
        exact, prints = fingerprint(clip["path"], clip["start"], clip["end"])
    # Compute outside SQLite, but compare and save against one locked snapshot.
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        current = db.execute(
            "SELECT c.start,c.end,v.path FROM clips c JOIN videos v ON v.id=c.video_id WHERE c.id=?",
            (cid,),
        ).fetchone()
        if not current or any(current[k] != clip[k] for k in ("start", "end", "path")):
            raise ValueError("Clip changed during analysis. Retry to check the new boundaries.")
        candidates = db.execute(
            """SELECT c.id,c.exact_hash,c.fingerprints FROM clips c JOIN videos v ON v.id=c.video_id
            WHERE c.id!=? AND c.exact_hash IS NOT NULL AND c.decision!='excluded'
            AND ((v.source_date=? AND c.id<?) OR EXISTS
                (SELECT 1 FROM episode_clips ec JOIN episodes e ON e.id=ec.episode_id
                 WHERE ec.clip_id=c.id AND e.upload_state='published')) ORDER BY c.id""",
            (cid, clip["source_date"], cid),
        ).fetchall()
        duplicate = next((c["id"] for c in candidates if c["exact_hash"] == exact), None)
        near = next(
            (
                c["id"]
                for c in candidates
                if similar_fingerprints(prints, json.loads(c["fingerprints"]))
            ),
            None,
        )
        db.execute(
            "UPDATE clips SET exact_hash=?,fingerprints=?,duplicate_of=?,near_duplicate_of=? WHERE id=?",
            (exact, json.dumps(prints), duplicate, near, cid),
        )


def analyze_video(store, vid, progress=None):
    row = store.one("SELECT * FROM videos WHERE id=?", (vid,))
    if not row["path"]:
        raise ValueError("Download the source before analyzing clips")
    existing = store.one("SELECT count(*) AS n FROM clips WHERE video_id=?", (vid,))["n"]
    if not existing:
        bounds, markers = detect_scenes(row["path"])
        # Commit all suggestions together; retries never resurrect discarded cuts.
        with store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE videos SET status='analyzing',markers=? WHERE id=?",
                (json.dumps(markers), vid),
            )
            conn.executemany(
                "INSERT OR IGNORE INTO clips(video_id,start,end) VALUES(?,?,?)",
                [
                    (vid, start, min(end, row["duration"]))
                    for start, end in bounds
                    if end - start >= 0.1
                ],
            )
    else:
        store.execute("UPDATE videos SET status='analyzing' WHERE id=?", (vid,))
    clips = store.all("SELECT id FROM clips WHERE video_id=? ORDER BY start", (vid,))
    for i, c in enumerate(clips):
        if progress:
            progress(i / max(1, len(clips)), f"Checking clip {i + 1} of {len(clips)}")
        fingerprint_clip(store, c["id"])
    store.execute("UPDATE videos SET status='analyzed',error=NULL WHERE id=?", (vid,))


def collect(store, config, day, progress=None):
    if day > yesterday(config.timezone):
        raise ValueError("Choose a completed source date, yesterday or earlier")
    result = collect_catalog(
        store,
        YouTubeCatalog(config.api_key),
        day,
        config.timezone,
        lambda p, m: progress(p * 0.15, m) if progress else None,
    )
    videos = store.all("SELECT * FROM videos WHERE source_date=? ORDER BY id", (day.isoformat(),))
    errors = [f"{e['source']}: {e['error']}" for e in result["errors"]]
    for i, video in enumerate(videos):

        def report(p, message):
            if progress:
                progress(0.15 + 0.8 * (i + p) / max(1, len(videos)), message)

        try:
            download_video(store, config, video["id"], report)
            analyze_video(store, video["id"], report)
        except Exception as exc:
            errors.append(f"{video['id']}: {exc}")
            store.execute("UPDATE videos SET error=? WHERE id=?", (str(exc), video["id"]))
    available = store.one(
        "SELECT count(*) AS n FROM videos WHERE source_date=? AND status='analyzed'",
        (day.isoformat(),),
    )["n"]
    if available:
        try:
            result["episode_id"] = Episodes(store).draft(day.isoformat(), config.brand)
        except ValueError as exc:
            errors.append(str(exc))
    result["errors"] = errors
    if progress:
        progress(1, f"Collected {len(videos)} videos; {available} ready for review")
    if errors:
        raise RuntimeError(
            "Some sources failed; successful footage is available. " + "; ".join(errors)
        )
    if not videos:
        result["message"] = "No source uploads were published on this date."
    return result


def render_episode(store, config, eid, progress=None):
    service = Episodes(store)
    row = service.get(eid)
    clips = service.clips(eid)
    if not clips:
        raise ValueError("Select clips before rendering")
    if row["upload_state"] in ("uploading", "uncertain", "publishing", "published"):
        raise ValueError("Cannot render while upload is active, uncertain, or published")
    for clip in clips:
        fingerprint_clip(store, clip["id"])
    clips = service.clips(eid)
    if any(c["duplicate_of"] for c in clips):
        raise ValueError(
            "Exact duplicates are selected. Remove them in the episode editor before rendering."
        )
    folder = config.home / "episodes" / str(eid) / f"r{row['revision']}"
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / "episode.mp4"
    metadata = render_segments(clips, output, progress)
    thumb = next((c for c in clips if c["id"] == row["thumbnail_clip"]), clips[0])
    at = (
        row["thumbnail_time"]
        if thumb["id"] == row["thumbnail_clip"] and row["thumbnail_time"] is not None
        else thumb["start"]
    )
    thumbnail(
        thumb["path"], max(thumb["start"], min(at, thumb["end"] - 0.01)), folder / "thumbnail.jpg"
    )
    manifest = {
        "episode_id": eid,
        "revision": row["revision"],
        "source_date": row["source_date"],
        "title": row["title"],
        "description": row["description"],
        "clips": [
            {k: c[k] for k in ["id", "video_id", "url", "start", "end", "source_id"]} for c in clips
        ],
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (folder / "metadata.json").write_text(
        json.dumps({k: row[k] for k in ["title", "description", "made_for_kids"]}, indent=2)
    )
    service.attach_render(eid, row["revision"], output, metadata["duration"])
    return str(output)
