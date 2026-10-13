# MemeBot — Daily Compilation Workbench

A local browser app for collecting YouTube compilations from a selected calendar day, reviewing suggested cuts, and making an eight-minute landscape episode. SQLite stores progress, edits and upload recovery state. A separate worker handles downloads, analysis, rendering and uploads while the browser is closed.

**Source finding:** none of the inspected channels met the strict daily criterion. Three active, less-frequent alternatives are preconfigured, with two disabled backups. See [dated research and gaps](docs/SOURCES.md). Empty days remain empty; MemeBot never fills them with another date’s footage.

## Install and open (macOS)

```bash
brew install uv ffmpeg node
git clone https://github.com/baywiggins/MemeBot.git
cd MemeBot
uv sync --locked
uv run memebot doctor
uv run memebot ui
```

Open **http://127.0.0.1:8501**. Python 3.13 is selected by `.python-version` and provisioned by uv. Node supplies yt-dlp’s JavaScript runtime. No paid AI services are used. Bind the app to localhost: it is a single-operator tool without remote authentication.

App data defaults to `~/.local/share/memebot`. Override it with `MEMEBOT_HOME=/absolute/path`; `.env.example` documents optional settings. The database is `state.db`, footage lives in `media/<video-id>`, exports in `episodes/<id>/r<revision>`, and jobs log to `worker.log`. Credentials are stored locally with owner-only file permissions. Back up the data directory while the worker is stopped. Removing it loses deduplication, approvals and upload recovery history.

## Set up source access and your destination

You do not need credentials to inspect the UI or edit/render already collected footage. Collection needs a YouTube Data API key. Uploading additionally needs OAuth:

1. Create a Google Cloud project and enable **YouTube Data API v3**.
2. Create an API key and restrict its API access to YouTube Data API v3.
3. Configure the Google Auth Platform consent screen. For personal testing, add your Google account as a test user.
4. Create an OAuth client with type **Desktop app** and download its client JSON.
5. In **Settings → Set up Google credentials**, enter the key, choose that JSON, and save locally. Then **Connect YouTube channel**, complete Google’s browser consent, and verify the displayed channel name/ID.

Do not paste credentials into chat or commit them. [Google’s installed-app authorization guide](https://developers.google.com/youtube/v3/guides/auth/installed-apps) explains the browser/loopback flow. The app requests `youtube.force-ssl` to inspect the destination, upload, set a thumbnail and update privacy. OAuth testing status can require periodic reconnection. The API may restrict uploads from unverified projects to private; API project audit/verification and channel feature eligibility are external prerequisites for public publication/custom thumbnails. See [YouTube upload requirements](https://developers.google.com/youtube/v3/docs/videos/insert).

## Daily workflow

1. **Sources:** inspect the dated evidence, enable/disable sources, and refresh the 14-day history after adding a key.
2. **Daily desk:** choose yesterday (or an earlier completed day) and collect. The day is midnight-to-midnight in America/New_York, including daylight-saving transitions. Discovery paginates uploads and each source can succeed independently.
3. **Clip library:** preview and adjust suggested scene cuts; split, merge or exclude intros, ads and incomplete jokes. Silence/black-frame intervals are cues. Camera cuts are not necessarily joke boundaries. Original audio is retained.
4. **Episodes:** order clips, edit metadata and choose a thumbnail timestamp. Drafts aim for eight minutes and alternate sources; whole candidates are preserved. Exact normalized audiovisual duplicates are excluded, visual similarity is only a warning. Review warnings and source references yourself.
5. **Render:** outputs 1920×1080 H.264/AAC at 30 fps, fits without cropping captions, pads portrait video, and normalizes loudness. Clips without audio get a silent track. The export folder includes MP4, thumbnail JPEG, metadata JSON and a source/cut manifest. Drafts outside 5–10 minutes can be rendered/exported but cannot be approved for daily publication.
6. **Review and approve:** watch the render, then approve its exact revision/file hash. Edits invalidate approval; an uploaded older revision remains private in YouTube Studio.
7. **Upload privately:** verify the destination shown beside the control. The resumable session and resulting video ID are saved. Wait for YouTube processing, then explicitly choose **Publish** to make that approved upload public. Published episodes are locked.

Metadata dates describe compilation publication, not the age of the memes inside. Source descriptions identify compilation uploaders; they do not establish original creator permission. Rearrangement alone does not establish monetization eligibility. [YouTube’s reused-content policy](https://support.google.com/youtube/answer/1311392?hl=en) is separate from copyright permission.

## CLI

```bash
uv run memebot collect --date 2026-10-11
uv run memebot draft --date 2026-10-11
uv run memebot render --episode 1
uv run memebot approve --episode 1       # after personally reviewing the render
uv run memebot upload --episode 1        # private
uv run memebot publish --episode 1 --public
uv run memebot status --json
uv run memebot research --as-of 2026-10-12
uv run memebot import-legacy curVids.json
uv run memebot worker
```

`collect`, `draft`, `render`, `upload`, and `publish` accept `--background`. Foreground commands use the same queue and show the final job result. A second worker cannot claim concurrently. `worker` drains pending jobs and exits. `draft` never replaces an existing edited episode; add newly arrived clips in the episode editor. Legacy JSON IDs are imported only as discovered records, never processed/published successes.

## Recovery and scheduling

Failed jobs are visible on the Daily desk and can be retried. Downloads resume in their own video-ID directories. Invalid cached files are quarantined and replaced; saved clip edits remain. Completed files pass header and full decode checks, cached against file size/modification time. Renders use temporary output files; repeating a failed render does not approve it. Starting a worker recovers interrupted queue records under the process lock. Use **Settings → Resume queued work** if a process was killed.

A timed-out upload is never blindly replaced with another video. Retry its saved session. If the session is missing/expired, inspect YouTube Studio and use **Reconcile existing video** (or `memebot reconcile --episode 1 --video-id ID`); ownership and the episode tag must match. If no upload exists in Studio, use **Recover missing upload** (or `memebot recover-upload --episode 1 --confirm-no-upload`). This checks the saved session and paginates your channel’s upload inventory before recording an explicit reset. An active session is resumed, and a matching existing video is linked instead of replaced. Never erase SQLite state to force a retry. Publish network failures retain recovery state; retry verifies whether the remote video is already public. A rejection before the visibility change leaves the video private.

After completing your first reviewed pilot episode, install collection scheduling:

```bash
uv run memebot schedule --install
# Later:
uv run memebot schedule --remove
```

The macOS LaunchAgent checks every 15 minutes, collecting the previous completed day once the clock reaches 9 a.m. Eastern. It catches up for the current due date after wake; it does not automatically backfill all days during a multi-day absence. Failed collections need a manual retry. Keep this checkout/venv in place while the LaunchAgent is installed. Save the discovery key in Settings (a `.env` in your terminal directory is not available to launchd). Scheduling never approves or publishes.

## Development and evidence

```bash
uv sync --locked
uv run pytest -q
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run python scripts/sync_theme.py
uv build
```

[Design tokens](DESIGN.md) own the theme; [UX contract](UX-CONTRACT.md) records shared controls and flows. Modules separate discovery, media analysis, editorial state, rendering, OAuth/publishing and the worker. [Implementation ledger](docs/IMPLEMENTATION.md) and [verification/pilot notes](docs/VERIFICATION.md) record tested behavior and limitations.

Live private-upload verification needs your Google credentials. The seven-day editorial pilot remains a rollout step: record correction time, usable seconds per source, missed duplicates, render time and disk use before relying on daily operation.
