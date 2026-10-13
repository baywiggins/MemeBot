# Daily Compilation Workbench

Approved brief: the user's MemeBot plan, 2026-10-12. Build a local, single-user Python 3.13 / Streamlit / SQLite / yt-dlp / PySceneDetect / FFmpeg workbench. Collect the previous calendar day's YouTube compilations in America/New_York; assemble whole clips into an eight-minute target (5–10 minute publishable) landscape episode. Human review precedes private upload and a separate public Publish action. Edits invalidate approval. Never publish from a scheduler.

## Deliverables
1. Research 10–15 source channels; validate 14-day history and a seven-day daily streak; shortlist 3–5 plus backups, disclosing missing evidence.
2. Reuse main history, replace brittle legacy JSON state and downloader with locked dependencies and SQLite.
3. Paginated upload discovery with exact day boundaries; independent source failure and resumable downloads.
4. Suggested scene boundaries, silence/black markers, exact and near-duplicate screening; editable clips and reproducible balanced drafts.
5. 1080p30 H.264/AAC rendering with padding and loudness normalization; versioned review, thumbnail, title, source description, export manifest.
6. OAuth destination identity, resumable private upload and reconciliation; explicit Publish; LaunchAgent collection at 9 a.m. Eastern with wake catch-up.

## Acceptance
Test calendar/DST boundaries, staggered/multiple/paginated uploads, partial source errors, repeat runs, process locks and crashes, media boundaries/dedup, real FFmpeg render/probe/decode, approval invalidation, interrupted/ambiguous uploads, UI navigation and correction, and scheduler no-publication. A seven-real-day editorial pilot and a live private upload require available source media/credentials; never substitute fixture results for these claims.

## Progress
- Workspace populated from origin/main (1637c4e). No pre-existing tests. Working branch: feat/daily-workbench.
- Ruling: reuse the explicitly designated empty workspace on a feature branch; another worktree adds no isolation value here.
- Ruling: current yt-dlp can use the installed Node runtime, so a second JavaScript runtime is not required.
- Tasks 1–6 implemented: seeded dated source evidence, persistent modular pipeline, review UI, revision-bound rendering, resumable private upload/reconciliation and explicit publishing, collect-only LaunchAgent generator/installer.
- Tests written RED→GREEN per module; full pre-review suite: 40 passing. Real source pilot rendered 8:01; unapproved and not uploaded.
- Ruling: no researched channel met the seven-day daily criterion. Ship three clearly labeled less-frequent alternatives plus two disabled backups; cost: some calendar days cannot supply a publishable episode.
- Ruling: source research uses public YouTube RSS/full video metadata while no API key is available. Runtime discovery uses the requested paginated uploads playlist API; cost: public-feed failures leave some candidate cadence unknown.
- Ruling: no live upload or daily schedule activation until the operator supplies credentials and reviews the pilot. The user confirmed credentials do not yet exist; fixture tests do not substitute for live verification.
- Ruling: narrow sample inspection cannot establish full-channel overlap or audio quality. Label this limitation and measure overlap/yield during the pilot; cost: manual editorial work remains necessary.
- Regression fixes: daily-to-episode navigation, split-thumbnail continuity, duplicate ownership after trims, destination requirement before network, and unused prior-day footage exclusion; each reproduced before repair.

## Final review and repairs

One fresh-context read-only whole-branch review completed. No Critical findings. All seven Important findings accepted after concrete reproduction. The thumbnail recovery finding was regraded Important because the reviewed thumbnail is part of the requested output.

- Final: fixed rejected/expired upload dead ends — initiation rejection, confirmed missing-upload recovery and matching remote reconciliation tests RED→GREEN.
- Final: fixed worker shutdown handoff and foreground early success — replacement worker and foreground CLI tests RED→GREEN.
- Final: fixed fingerprints overwriting concurrent edits — concurrent trim regression RED→GREEN; comparison selection/save now uses one SQLite snapshot.
- Final: fixed repeated split→merge→split collision — retained boundary reuse test RED→GREEN.
- Final: fixed exclusion/restoration duplicate ownership — canonical exclusion/restoration regression RED→GREEN.
- Final: fixed corrupt cached footage retry — quarantine/replacement regression RED→GREEN; strict decode validation added, editorial cuts preserved.
- Final: fixed recovered upload skipping thumbnail — completion recovery regression RED→GREEN.
- Final suite: `uv run pytest -q` → 50/50 passing. Ruff check/format, `uv build`, strict frontend audit and designmd lint pass. Browser/pilot details recorded in VERIFICATION.md.
- Final: Ruling: live OAuth/upload acceptance, channel eligibility and seven-day yield remain external rollout checks — credentials do not exist and future observations cannot be fabricated — cost: these checks must precede routine operation.
- Final: Ruling: semantic joke boundaries and full audio/editorial review remain human tasks — scene detection only suggests cuts — cost: the automatic pilot needs correction before approval.
- Final: Ruling: remote/multi-user deployment and hostile local filesystem mutation are out of scope — localhost, one operator is the approved contract — cost: do not expose this server publicly.
- Final: Ruling: keep the implementation on the existing local feature branch with no merge or remote push — user requested implementation, not repository publication — cost: GitHub main remains unchanged until integration.
- No deferred review minors.
