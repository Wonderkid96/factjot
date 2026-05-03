# factjot — Gotchas

Things that have been tried, broken, or caused hard-to-trace problems. Every agent must read this before touching the pipeline. Keep it current. If you hit a new wall, add it here.

---

## YAML / GitHub Actions

**GitHub's Go YAML parser rejects UTF-8 em dashes (`—`) in comments.**
PyYAML accepts them. GitHub silently rejects the whole workflow, causing dispatch to return 422 "no workflow_dispatch trigger". The fix is to use plain hyphens everywhere. This has bitten us twice. Run `grep -r "—" .github/` before pushing any workflow change.

**Multiline Python heredocs inside `run: |` blocks break GitHub YAML parsing.**
Extract all Python logic to standalone scripts in `scripts/`. Never put more than a simple one-liner in a workflow `run:` block.

**GitHub's built-in cron scheduler is unreliable** on free-tier repos. It can be delayed 15-60 minutes or skipped entirely under load. Use cron-job.org to dispatch via the API at exact times. GitHub crons serve only as a backup.

---

## Meta / Instagram API

**Meta's video URL downloader rejects files over ~5MB.**
This limit appeared 2026-05-02 (previously 12MB worked). Encode reels at crf 30, maxrate 800k. Adaptive retry: if 413, recompress at crf 33 / maxrate 600k.

**Meta requires 48kHz audio. 44.1kHz and 96kHz are both rejected.**
ElevenLabs returns 44.1kHz by default. Always resample to 48kHz in FFmpeg before muxing. 96kHz was encountered once from an edge-tts path and also rejected.

**Meta access tokens expire every 60 days.** `refresh_token.py` extends them. If `refresh_token.py` returns "API access blocked", the app was rate-limited by too-rapid API calls. Wait 30 minutes, retry. If still blocked, regenerate from developers.facebook.com.

**Cloudinary URLs are rejected by Meta's video fetcher** even when the file is under 5MB. Meta's fetcher times out before Cloudinary's CDN responds in some regions. Use tmpfiles.org (1-hour expiry) — Meta fetches within the polling window.

---

## Word beat detection ("factjot" CTA sync)

**ElevenLabs often renders "factjot" as two tokens: "fact" and "jot".**
The CTA sync code checks for a word beat containing "factjot". If not found, it also checks for consecutive "fact" + "jot" beats. If neither matches, the fallback is time-based (voice_end - 3.5s). If the fallback is off, subtitles and CTA overlap. Always verify the printed "CTA locked to..." log line after a reel render.

---

## Footage

**Short clips loop visibly in FFmpeg, creating a hard jolt.**
`stream_loop -1` is needed so clips can fill their assigned window. If a clip is shorter than its window (e.g., 2s clip in a 7s hook window), FFmpeg loops it — the restart is a hard cut the viewer sees. Minimum accepted clip size is 2MB and minimum duration is 4s (probed with ffprobe). Do not lower these thresholds.

**The same clip can appear in both the intro section and the main content.**
footage_clips[0] plays under the factjot_intro.mov alpha overlay for the first 1.37s. It continues playing after the overlay ends. This is correct — the overlay is transparent and reveals the footage. Do not add a separate "intro clip" slot; the alpha overlay IS the intro.

**Global footage dedup (`data/ledgers/used_footage_urls.jsonl`) is git-tracked.**
This file must be committed after every reel or the same clip will appear in consecutive reels. It is included in `reel.yml`'s git-add step. Do not gitignore it.

---

## Image dedup

**`data/ledgers/used_images.jsonl` must be git-tracked** or image dedup resets to zero on every GitHub Actions run. It was gitignored until 2026-05-03. It is now tracked and committed in all three posting workflows.

**The brain and image_fetcher previously wrote to two different paths.**
`brain.py` used `data/used_images.jsonl`; `image_fetcher.py` used `data/ledgers/used_images.jsonl` (via paths.py). Neither checked the other's records. Fixed 2026-05-03: `brain.py` now uses `UsedImageLedger()` with no path argument, deferring to paths.py like everything else.

---

## Duplicate post prevention

**`assert_no_duplicate()` must be called immediately before every Instagram API publish call** — not earlier. It does a fresh disk read to catch posts made by concurrent runs that the in-memory cache doesn't know about. It was missing from `ship_list_post.py` until 2026-05-03.

**The queue (`insta-brain/data/queue.jsonl`) is a legacy artefact** from the old launchd system. GitHub Actions workflows do NOT read it — they generate posts on the fly with `ship_first_post.py` / `ship_list_post.py` / `make_reel.py`. The queue contains render paths pointing to `/home/runner/work/...` which evaporate after each run. Do not populate or read the queue.

---

## Reel quality gates

**q3 facts MUST have curated `reel_script` (>= 70 words) and `reel_title`.**
There is no auto-fallback path. If a discovered fact is missing either field, `make_reel.py` silently skips it. The runway check (`scripts/check_reel_runway.py`) only counts facts that pass ALL gates. Do not lower the 70-word minimum — it exists because 22-word scripts produced 22-second reels that felt broken (2026-05-01 incident).

---

## Fix philosophy (mandatory)

Every fix must be a long-term structural fix, not a temporary patch. A patch that suppresses a symptom without removing its root cause will reappear in a different form or a different part of the pipeline. Before shipping any fix, ask: does this eliminate the cause, or does it hide it? If it hides it, keep digging.
