"""Streamlit entrypoint: local review desk, source library, and explicit publishing."""

import json
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

from memebot.config import Config
from memebot.episodes import Episodes
from memebot.research import seed_sources
from memebot.store import Store
from memebot.timeutil import yesterday
from memebot.ui_components import action, duration, header, jobs_panel, queue, theme

st.set_page_config(page_title="MemeBot · Daily desk", page_icon="🎞️", layout="wide")
config = Config.load()
db = Store(config.db_path)
episodes = Episodes(db)
seed_sources(db)
theme()


def date_picker(key):
    maximum = yesterday(config.timezone)
    try:
        initial = date.fromisoformat(st.query_params.get("date", maximum.isoformat()))
    except ValueError:
        initial = maximum
    value = st.date_input(
        "Source upload date",
        value=min(initial, maximum),
        max_value=maximum,
        format="YYYY-MM-DD",
        key=key,
    )
    st.query_params["date"] = value.isoformat()
    st.caption(
        f"Calendar day in {config.timezone}. Dates describe source uploads, not when the memes originated."
    )
    return value


def daily():
    header("Daily desk", "Yesterday’s footage. Your next episode.")
    left, right = st.columns([2, 1], gap="large")
    with left:
        day = date_picker("daily_date")
        if not config.api_key:
            st.info("Add a YouTube API key in Settings to start collecting source uploads.")
        if st.button(
            "Collect footage & prepare draft", type="primary", disabled=not config.api_key
        ):
            queue(config, "collect", {"date": day.isoformat()})
        videos = db.all(
            "SELECT v.*,s.name AS source FROM videos v LEFT JOIN sources s ON s.id=v.source_id WHERE source_date=? ORDER BY published_at",
            (day.isoformat(),),
        )
        st.subheader("Footage for this date")
        if videos:
            st.dataframe(
                [
                    {
                        "Source": v["source"],
                        "Video": v["title"],
                        "State": v["status"],
                        "Duration": duration(v["duration"]),
                        "Issue": v["error"] or "",
                    }
                    for v in videos
                ],
                hide_index=True,
                height=280,
            )
        else:
            st.info("No footage collected yet. Enable sources, then collect this date’s uploads.")
        ep = db.one("SELECT * FROM episodes WHERE source_date=?", (day.isoformat(),))
        if ep:
            with st.container(border=True):
                st.subheader(ep["title"])
                total = sum(c["end"] - c["start"] for c in episodes.clips(ep["id"]))
                st.write(
                    f"{len(episodes.clips(ep['id']))} clips · {duration(total)} · Revision {ep['revision']}"
                )

                def open_episode():
                    st.query_params["episode"] = str(ep["id"])
                    st.session_state["nav"] = "Episodes"

                st.button("Review this episode", on_click=open_episode)
        elif videos and st.button("Build draft from available clips"):
            queue(config, "draft", {"date": day.isoformat()})
    with right:
        with st.container(border=True):
            st.subheader("The daily flow")
            st.write(
                "1. Collect yesterday’s uploads\n2. Review cuts and remove repeats\n3. Render and approve\n4. Upload privately, then publish"
            )
            st.caption("Collection never publishes. You control the final cut.")
        with st.container(border=True):
            st.subheader("Source coverage")
            sources = db.all("SELECT * FROM sources WHERE enabled=1")
            st.write(f"{len(sources)} enabled channels")
            for source in sources:
                research = json.loads(source["research"])
                label = "daily verified" if research.get("daily_last_7") else "not verified daily"
                st.caption(f"{source['name']} · {label}")
    st.subheader("Recent work")
    jobs = db.all("SELECT * FROM jobs ORDER BY id DESC LIMIT 15")
    if not jobs:
        st.caption("Collection, rendering, and uploads will appear here.")
    for job in jobs:
        with st.expander(f"{job['kind'].capitalize()} · {job['status']} · #{job['id']}"):
            if job["error"]:
                st.error(job["error"])
            else:
                st.write(job["message"] or "Waiting for the worker")
            if job["status"] == "failed" and st.button("Retry job", key=f"retry-{job['id']}"):
                queue(config, job["kind"], json.loads(job["payload"]))


def sources_page():
    header("Sources", "A small rotation of channels. Evidence before assumptions.")
    if st.button("Refresh 14-day upload history", disabled=not config.api_key):
        queue(
            config,
            "research",
            {"as_of": (yesterday(config.timezone) + timedelta(days=1)).isoformat()},
        )
    st.caption(
        "Daily means a matching upload on each of the last seven completed days. Missing evidence is shown as unknown."
    )
    for source in db.all("SELECT * FROM sources ORDER BY enabled DESC,name"):
        with st.expander(source["name"], expanded=False):
            st.link_button("Open channel", source["url"])
            st.write(source["notes"])
            report = json.loads(source["research"])
            if report.get("evidence_missing"):
                st.warning("Upload history could not be fully verified.")
            elif report.get("uploads_per_day"):
                st.write(
                    f"Observed activity: {report.get('active_days_14', 0)}/14 days · checked {report.get('as_of', 'unknown')}"
                )
                st.bar_chart(report["uploads_per_day"], height=140)
                st.caption("Missing days: " + ", ".join(report.get("missing_days", [])))
                if report.get("median_duration"):
                    st.caption(f"Typical duration: {duration(report['median_duration'])}")
            for i, url in enumerate(report.get("sample_urls", []), 1):
                st.link_button(f"Sample upload {i}", url)
            if source["error"]:
                st.error(source["error"])
            with st.form(f"source-{source['id']}"):
                enabled = st.checkbox("Use this source", value=bool(source["enabled"]))
                notes = st.text_area("Source notes", value=source["notes"])
                if st.form_submit_button("Save source"):
                    action(
                        lambda: db.add_source(
                            source["id"],
                            source["name"],
                            enabled=enabled,
                            notes=notes,
                            research=report,
                        )
                    )
            stats = db.one(
                """SELECT count(c.id) AS clips,sum(c.duplicate_of IS NOT NULL) AS duplicates FROM clips c
                JOIN videos v ON v.id=c.video_id WHERE v.source_id=?""",
                (source["id"],),
            )
            st.caption(
                f"Library yield: {stats['clips']} clips · {stats['duplicates'] or 0} exact duplicates"
            )
    with st.expander("Add a source", expanded=True):
        with st.form("new_source"):
            name = st.text_input("Channel name", key="source_name")
            identifier = st.text_input(
                "YouTube channel ID",
                key="source_id",
                help="A UC… ID from the channel URL. You can resolve @handles below.",
            )
            if st.form_submit_button("Add source", key="add_source"):
                action(lambda: db.add_source(identifier.strip(), name), "Source added")
        with st.form("resolve_handle"):
            handle = st.text_input("Resolve an @handle or channel URL")
            if st.form_submit_button("Look up channel", disabled=not config.api_key):
                try:
                    from memebot.discovery import YouTubeCatalog

                    c = YouTubeCatalog(config.api_key).channel(handle)
                    st.info(
                        f"{c['snippet']['title']} — {c['id']}. Paste this ID above to add the source."
                    )
                except (ValueError, RuntimeError) as exc:
                    st.error(str(exc))


def clip_library():
    header("Clip library", "Keep the whole joke. Split, merge, trim, or leave it out.")
    day = date_picker("library_date")
    rows = db.all(
        """SELECT c.*,v.path,v.title,v.duration,v.markers,s.name AS source FROM clips c
        JOIN videos v ON v.id=c.video_id LEFT JOIN sources s ON s.id=v.source_id
        WHERE v.source_date=? AND v.status='analyzed' ORDER BY v.source_id,v.id,c.start""",
        (day.isoformat(),),
    )
    if not rows:
        st.info("Collect footage first. Detected clip boundaries will appear here for review.")
        return
    sources = list(dict.fromkeys(c["source"] or "Unknown" for c in rows))
    selected = st.selectbox("Filter by source", ["All sources", *sources])
    if selected != "All sources":
        rows = [c for c in rows if c["source"] == selected]
    page = st.number_input(
        "Page", min_value=1, max_value=max(1, (len(rows) + 11) // 12), value=1, step=1
    )
    st.caption(
        f"{len(rows)} clips · 12 per page. Cuts are suggestions; check setup and punchline before keeping a clip."
    )
    for c in rows[(page - 1) * 12 : page * 12]:
        with st.container(border=True):
            left, right = st.columns([3, 2], gap="large")
            with left:
                st.subheader(f"Clip {c['id']} · {c['source']}")
                if c["path"] and Path(c["path"]).exists():
                    st.video(c["path"], start_time=c["start"], end_time=c["end"])
                else:
                    st.warning("Source file is missing. Collect this date again to restore it.")
                st.caption(f"{c['title']} · {duration(c['start'])} → {duration(c['end'])}")
                markers = [
                    m
                    for m in json.loads(c["markers"])
                    if m["end"] >= c["start"] and m["start"] <= c["end"]
                ]
                for m in markers:
                    st.caption(
                        f"{m['kind'].capitalize()} marker: {m['start']:.2f}s–{m['end']:.2f}s"
                    )
            with right:
                if c["duplicate_of"]:
                    st.warning(
                        f"Exact duplicate of clip {c['duplicate_of']}; excluded from new drafts."
                    )
                elif c["near_duplicate_of"]:
                    st.warning(
                        f"Looks similar to clip {c['near_duplicate_of']}. Check both before using."
                    )
                match_id = c["duplicate_of"] or c["near_duplicate_of"]
                if match_id:
                    match = db.one(
                        "SELECT c.*,v.path,v.source_date,v.title FROM clips c JOIN videos v ON v.id=c.video_id WHERE c.id=?",
                        (match_id,),
                    )
                    if match:
                        with st.expander(f"Compare with clip {match_id}"):
                            st.caption(f"{match['source_date']} · {match['title']}")
                            if match["path"] and Path(match["path"]).exists():
                                st.video(
                                    match["path"], start_time=match["start"], end_time=match["end"]
                                )
                            else:
                                st.info("Comparison footage is unavailable locally.")
                with st.form(f"trim-{c['id']}"):
                    start = st.number_input(
                        "Start (seconds)",
                        value=float(c["start"]),
                        min_value=0.0,
                        max_value=float(c["duration"]),
                        step=0.1,
                    )
                    end = st.number_input(
                        "End (seconds)",
                        value=float(c["end"]),
                        min_value=0.0,
                        max_value=float(c["duration"]),
                        step=0.1,
                    )
                    st.caption(
                        "Unsaved trims stay in this form until you save. Save before changing pages."
                    )
                    if st.form_submit_button("Save trim"):
                        action(
                            lambda: episodes.trim_clip(c["id"], start, end),
                            "Trim saved; affected episodes need a new render.",
                        )
                cols = st.columns(2)
                with cols[0]:
                    if st.button(
                        "Exclude clip" if c["decision"] != "excluded" else "Restore clip",
                        key=f"decision-{c['id']}",
                    ):
                        action(
                            lambda: episodes.decision(
                                c["id"], "excluded" if c["decision"] != "excluded" else "candidate"
                            )
                        )
                with cols[1]:
                    next_clip = next(
                        (
                            r
                            for r in rows
                            if r["video_id"] == c["video_id"]
                            and abs(r["start"] - c["end"]) < 0.05
                            and r["id"] != c["id"]
                            and r["decision"] != "excluded"
                        ),
                        None,
                    )
                    if st.button("Merge with next", key=f"merge-{c['id']}", disabled=not next_clip):
                        action(lambda: episodes.merge_clips(c["id"], next_clip["id"]))
                with st.form(f"split-{c['id']}"):
                    at = st.number_input(
                        "Split at (seconds)",
                        value=float((c["start"] + c["end"]) / 2),
                        min_value=float(c["start"]),
                        max_value=float(c["end"]),
                        step=0.1,
                    )
                    if st.form_submit_button("Split clip"):
                        action(lambda: episodes.split_clip(c["id"], at))


def episode_page():
    header("Episodes", "Arrange the rundown, check the render, then approve your final cut.")
    rows = db.all("SELECT * FROM episodes ORDER BY source_date DESC")
    if not rows:
        st.info("No episodes yet. Collect a date’s footage from the Daily desk to prepare a draft.")
        return
    ids = [r["id"] for r in rows]
    try:
        current = int(st.query_params.get("episode", ids[0]))
    except ValueError:
        current = ids[0]
    eid = st.selectbox(
        "Episode",
        ids,
        index=ids.index(current) if current in ids else 0,
        format_func=lambda v: next(
            f"{r['source_date']} · {r['title']}" for r in rows if r["id"] == v
        ),
    )
    st.query_params["episode"] = str(eid)
    row = episodes.get(eid)
    clips = episodes.clips(eid)
    total = sum(c["end"] - c["start"] for c in clips)
    locked = row["upload_state"] in ("uploading", "uncertain", "publishing", "published")
    st.caption(
        f"{len(clips)} clips · {duration(total)} · Revision {row['revision']} · Upload: {row['upload_state']}"
    )
    if total < 300:
        st.warning(
            "This draft is under five minutes. Add more footage from the same date before approval. You can still render and export it."
        )
    if total > 600:
        st.warning("This draft is over ten minutes. Remove clips or trim them before approval.")
    left, right = st.columns([3, 2], gap="large")
    with left:
        if row["render_path"] and Path(row["render_path"]).exists():
            st.video(row["render_path"])
            st.caption(f"Rendered revision {row['render_revision']} · {duration(row['duration'])}")
            if st.button("Show export folder"):
                import subprocess

                subprocess.run(["open", str(Path(row["render_path"]).parent)], check=False)
            st.code(str(Path(row["render_path"]).parent), language=None)
        else:
            st.info("Your episode preview will appear here after rendering.")
        controls = st.columns(2)
        with controls[0]:
            if st.button("Render episode", type="primary", disabled=locked or not clips):
                queue(config, "render", {"episode_id": eid})
        with controls[1]:
            reviewed = st.checkbox(
                "I reviewed this render",
                key=f"reviewed-{eid}-{row['revision']}",
                disabled=not row["render_path"],
            )
            if st.button(
                "Approve this render", disabled=locked or not reviewed or not row["render_path"]
            ):
                action(
                    lambda: episodes.approve(eid, row["revision"]),
                    "Render approved. You can upload it privately.",
                )
        with st.expander("Title, description & audience"):
            with st.form(f"metadata-{eid}-{row['revision']}"):
                title = st.text_input("Video title", value=row["title"], max_chars=100)
                description = st.text_area("Description", value=row["description"], height=180)
                kids = st.checkbox(
                    "Made for kids",
                    value=bool(row["made_for_kids"]),
                    help="Select according to your intended audience, not whether children might watch.",
                )
                st.caption(
                    "Save before changing pages. Changes require rendering and approval again."
                )
                if st.form_submit_button("Save metadata", disabled=locked):
                    action(
                        lambda: episodes.metadata(
                            eid,
                            title=title,
                            description=description,
                            made_for_kids=kids,
                            expected_revision=row["revision"],
                        )
                    )
        if clips:
            with st.expander("Thumbnail frame"):
                if row["render_path"]:
                    preview = Path(row["render_path"]).parent / "thumbnail.jpg"
                    if preview.exists():
                        st.image(str(preview), caption="Thumbnail from the current render")
                with st.form(f"thumbnail-{eid}"):
                    tcid = st.selectbox(
                        "Frame source", [c["id"] for c in clips], format_func=lambda v: f"Clip {v}"
                    )
                    tc = next(c for c in clips if c["id"] == tcid)
                    at = st.number_input(
                        "Source timestamp (seconds)",
                        value=float(tc["start"]),
                        min_value=0.0,
                        step=0.1,
                    )
                    if st.form_submit_button("Set thumbnail frame", disabled=locked):
                        action(lambda: episodes.thumbnail(eid, tcid, at, row["revision"]))
        publishing_controls(row, locked)
    with right:
        st.subheader("Episode rundown")
        page = st.selectbox(
            "Rundown page",
            range(max(1, (len(clips) + 11) // 12)),
            format_func=lambda p: f"Clips {p * 12 + 1}–{min((p + 1) * 12, len(clips))}",
            key=f"rundown-page-{eid}",
        )
        for i in range(page * 12, min((page + 1) * 12, len(clips))):
            c = clips[i]
            with st.container(border=True):
                st.write(f"**{i + 1:02} · Clip {c['id']}** — {duration(c['end'] - c['start'])}")
                st.caption(c["source_title"])
                if c["near_duplicate_of"]:
                    st.warning(f"Similar to clip {c['near_duplicate_of']}")
                cols = st.columns(3)
                ids_now = [x["id"] for x in clips]
                if cols[0].button("↑ Up", key=f"up-{c['id']}", disabled=locked or i == 0):
                    ids_now[i - 1], ids_now[i] = ids_now[i], ids_now[i - 1]
                    action(lambda: episodes.set_clips(eid, ids_now, row["revision"]))
                if cols[1].button(
                    "↓ Down", key=f"down-{c['id']}", disabled=locked or i == len(clips) - 1
                ):
                    ids_now[i + 1], ids_now[i] = ids_now[i], ids_now[i + 1]
                    action(lambda: episodes.set_clips(eid, ids_now, row["revision"]))
                if cols[2].button("Remove", key=f"remove-{c['id']}", disabled=locked):
                    action(
                        lambda: episodes.set_clips(
                            eid, [v for v in ids_now if v != c["id"]], row["revision"]
                        )
                    )
        available = db.all(
            """SELECT c.* FROM clips c JOIN videos v ON v.id=c.video_id WHERE v.source_date=?
            AND v.status='analyzed' AND c.decision!='excluded' AND c.duplicate_of IS NULL
            AND c.id NOT IN (SELECT clip_id FROM episode_clips WHERE episode_id=?) ORDER BY c.id""",
            (row["source_date"], eid),
        )
        if available:
            add = st.selectbox(
                "Add an available clip",
                [c["id"] for c in available],
                format_func=lambda v: f"Clip {v}",
            )
            if st.button("Add to rundown", disabled=locked):
                action(
                    lambda: episodes.set_clips(
                        eid, [c["id"] for c in clips] + [add], row["revision"]
                    )
                )


def publishing_controls(row, locked):
    st.subheader("Publish when ready")
    destination = db.setting("destination")
    approved = row["approved_revision"] == row["revision"] and bool(row["approved_hash"])
    if not destination:
        st.info(
            "Connect your YouTube channel in Settings. Exporting does not require a connection."
        )
    else:
        st.write(f"Destination: **{destination['name']}**")
    if row["upload_error"]:
        st.warning(row["upload_error"])
    if row["upload_id"]:
        st.link_button(
            "Open video in YouTube Studio",
            f"https://studio.youtube.com/video/{row['upload_id']}/edit",
        )
    if row["upload_state"] in ("none", "uploading", "uncertain"):
        label = "Resume private upload" if row["upload_session"] else "Upload privately"
        if st.button(
            label,
            disabled=not approved
            or not destination
            or (row["upload_state"] == "uncertain" and not row["upload_session"]),
        ):
            queue(config, "upload", {"episode_id": row["id"]})
    if row["upload_state"] in ("private", "publishing"):
        confirmation = st.checkbox(
            f"Publish this approved episode publicly to {destination['name'] if destination else 'the connected channel'}",
            key=f"publish-confirm-{row['id']}-{row['revision']}",
        )
        if st.button("Publish", type="primary", disabled=not approved or not confirmation):
            queue(config, "publish", {"episode_id": row["id"]})
    if row["upload_state"] in ("uncertain", "publishing", "uploading"):
        with st.expander("Reconcile an interrupted upload"):
            st.caption(
                "Check YouTube Studio, then supply the existing video ID. MemeBot verifies its destination and episode tag before linking it."
            )
            with st.form("reconcile"):
                video_id = st.text_input("Existing YouTube video ID", value=row["upload_id"] or "")
                if st.form_submit_button("Reconcile existing video"):
                    queue(config, "reconcile", {"episode_id": row["id"], "video_id": video_id})
            if row["upload_state"] in ("uncertain", "uploading") and not row["upload_id"]:
                st.caption(
                    "If there is no video to link, check the destination’s YouTube Studio first. Recovery checks the upload session and channel history before enabling a fresh attempt."
                )
                absent = st.checkbox(
                    "I checked YouTube Studio and found no upload for this episode",
                    key=f"absent-{row['id']}-{row['revision']}",
                )
                if st.button("Recover missing upload", disabled=not absent):
                    queue(
                        config,
                        "recover-upload",
                        {"episode_id": row["id"], "confirmed_absent": absent},
                    )
    if row["upload_state"] == "published":
        st.success("Published. This episode is locked to preserve its history.")


def settings():
    header("Settings", "Local files, source access, and your publishing destination.")
    st.subheader("Connection checklist")
    for label, ready in config.health().items():
        st.write(f"{'✓' if ready else '○'} {label}")
    st.caption(f"Private app data: {config.home}")
    with st.expander("Set up Google credentials", expanded=not config.api_key):
        st.markdown(
            "1. Create a Google Cloud project and enable **YouTube Data API v3**.\n2. Create an **API key** restricted to YouTube Data API v3.\n3. Configure Google Auth Platform consent for your account; add yourself as a test user if the app is in Testing.\n4. Create an OAuth client with application type **Desktop app**, then download its JSON.\n5. Save both below and connect your channel. Testing-mode authorizations may need periodic reconnection."
        )
        st.link_button(
            "Open Google Cloud APIs",
            "https://console.cloud.google.com/apis/library/youtube.googleapis.com",
        )
        with st.form("credentials"):
            key = st.text_input(
                "YouTube API key", type="password", help="Leave blank to keep your saved key."
            )
            client = st.file_uploader("OAuth desktop client JSON", type=["json"])
            brand = st.text_input("Channel / episode brand", value=config.brand)
            if st.form_submit_button("Save local settings"):

                def save():
                    from memebot.auth import private_json

                    path = config.home / "config.json"
                    saved = json.loads(path.read_text()) if path.exists() else {}
                    if key.strip():
                        saved["api_key"] = key.strip()
                    saved["brand"] = brand.strip() or "MemeBot"
                    if client:
                        document = json.loads(client.getvalue())
                        if not all(
                            document.get("installed", {}).get(k)
                            for k in ("client_id", "client_secret", "auth_uri", "token_uri")
                        ):
                            raise ValueError(
                                "Choose a Google OAuth Desktop app client JSON with an installed section"
                            )
                        # Client files are configuration, not arbitrary authorization destinations.
                        installed = document["installed"]
                        if (
                            installed["auth_uri"] != "https://accounts.google.com/o/oauth2/auth"
                            or installed["token_uri"] != "https://oauth2.googleapis.com/token"
                        ):
                            raise ValueError("OAuth client must use Google authorization endpoints")
                        private_json(config.home / "client_secret.json", document)
                    private_json(path, saved)

                action(save, "Settings saved locally")
    if st.button(
        "Connect YouTube channel", disabled=not (config.home / "client_secret.json").exists()
    ):
        queue(config, "connect", {})
    destination = db.setting("destination")
    if destination:
        st.success(f"Connected: {destination['name']} ({destination['id']})")
    st.subheader("Daily collection")
    st.write(
        "Collect yesterday’s uploads after 9:00 a.m. Eastern. If your Mac is asleep, collection catches up when it wakes. Publishing always requires review."
    )
    st.caption(
        "Enable scheduling after your first reviewed episode. It is not installed automatically."
    )
    from memebot.scheduler import launchagent

    st.download_button(
        "Download collection LaunchAgent",
        data=launchagent(config),
        file_name="local.memebot.collect.plist",
        mime="application/xml",
    )
    st.code("uv run memebot schedule --install", language="bash")
    st.subheader("Recovery")
    st.caption(
        "Failed work is retained in Daily desk. Retry a job after fixing the reported problem. Interrupted uploads use the saved session; never delete app state to retry an upload."
    )
    if st.button("Resume queued work"):
        from memebot.worker import spawn_worker

        action(lambda: spawn_worker(config), "Worker started")


with st.sidebar:
    st.markdown("## MemeBot")
    st.caption("DAILY COMPILATION WORKBENCH")
    view = st.radio(
        "Workspace",
        ["Daily desk", "Sources", "Clip library", "Episodes", "Settings"],
        key="nav",
        label_visibility="collapsed",
    )
    st.divider()
    jobs_panel(config)
    if st.button("Refresh workbench"):
        st.rerun()
    st.caption("Local workspace · review before publishing")

{
    "Daily desk": daily,
    "Sources": sources_page,
    "Clip library": clip_library,
    "Episodes": episode_page,
    "Settings": settings,
}[view]()
