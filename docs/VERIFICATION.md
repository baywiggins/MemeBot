# Verification and pilot evidence

## Completed checks

- Python 3.13 locked environment installed with uv; FFmpeg, ffprobe and Node found locally.
- Automated suite: **50 tests passed after final review**, covering DST, upload playlist pagination, staggered sources, legacy import, job idempotency/locking, revision invalidation, clip operations, exact/near matching, real FFmpeg rendering, private upload/retry/reconciliation, processing failures and public-state retry.
- Ruff checks/format passed. Strict frontend project audit reported zero findings. Official designmd lint reported zero errors/warnings; generated theme tokens are synchronized.
- Source research records 14 initial candidates and four additional candidates. No verified daily sources; three sampled less-frequent alternatives and two unreviewed backups. See SOURCES.md for evidence limits.

## Real media pilot (engineering test, not editorial approval)

Source: StreetCan, video `KFMIEIZkaSI`, published 2026-10-11T17:59:12Z, nominal duration 572 seconds. Downloaded through yt-dlp, validated, analyzed by PySceneDetect, fingerprinted, assembled and rendered through the actual pipeline.

- Detected 187 scene candidates; the eight-minute target selected 134 whole candidates.
- Output: 481.208 seconds, H.264 1920×1080 at 30 fps, AAC 48 kHz, 143,827,405 bytes.
- Video/audio stream durations: 481.184 / 481.208 seconds (difference ~24 ms).
- Export includes edit manifest, metadata and thumbnail. Approval remains unset, no upload attempted. Full FFmpeg output decode completed without errors. The source also passed strict packet/decode validation.
- Many detected scenes are internal cuts: a human must merge/trim for joke continuity. This run proves media plumbing, not final editorial quality or automatic understanding.

## Live rollout still required

The operator does not yet have a Google Cloud OAuth desktop client or YouTube Data API key. API discovery and publishing edge cases are tested with deterministic HTTP fixtures; no live private upload or connected destination has been claimed. Settings contains setup fields and instructions. No LaunchAgent has been installed.

Before installing daily scheduling: personally review/correct the pilot, render and approve, then verify one private upload and processing. Evaluate seven real daily episodes and record correction time, source yield (usable seconds), missed duplicates, render duration and disk consumption. Empty days and inadequate footage must remain visible. Full-channel overlap, semantic cut quality, creator permissions, monetization eligibility and real listening/sync review are not established by these software tests.

## Browser and review completion

The in-app browser verified daily-to-episode navigation, actual H.264 playback (481.208s, 1920×1080), source evidence charts/sample links, invalid trim feedback, keyboard focus from source notes to Save, and credential setup at 390×844 without horizontal overflow. AppTest covers empty states and navigation. The pilot is available in the default app data directory `~/.local/share/memebot`, episode 1, with media paths and render hash verified after transfer from the test workspace.

A fresh read-only reviewer found no Critical findings and seven Important recovery/editing issues; all were reproduced before repair. The thumbnail recovery finding was also fixed because a recovered upload should use the reviewed frame. Ten new regression tests cover: rejected initiation, expired/missing upload reconciliation, linking an existing upload, recovered thumbnail, worker handoff, foreground completion, concurrent trimming/fingerprints, repeated split/merge, duplicate ownership and corrupt-cache replacement. Final suite: **50 passed**; lint, formatter and package build pass. No review findings remain deferred.

This is not a screen-reader certification or exhaustive codec corpus test. Browser tests did not authorize a real episode or contact a destination account.
