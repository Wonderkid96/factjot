# Memory Index

Quick handover ledger. Newest entry first. Older entries summarised or removed once superseded.

Related: [[CLAUDE]] · [[CRITICAL_FACTS]] · [[PUBLISH_PLAN]] · [[log]] · [[rules/13-memory-index]]

---

## 2026-05-03 — Reel encode, Meta audio, CI observability

### Voice and Meta audio
- `make_reel.py`: padding concat now `aresample=48000` + mono `aformat` on both legs before `concat`, `anullsrc` mono 48 kHz, `-ar 48000` on lame output. Stops `voice_padded.mp3` staying at 44.1 kHz (Meta rejects 44.1 and 96 kHz; see gotchas).

### Reel video size (Meta ~5 MB URL fetch)
- `reel_composer.py` compose: libx264 **crf 30**, **maxrate 800k**, **bufsize 1600k**, preset **ultrafast** (replaces older crf 23 primary encode that ballooned files and caused 413).
- `make_reel.py` publish retries: first recompress after 413 **crf 33 / 600k**, second **crf 35 / 500k** (first attempt must differ from primary 30/800k).

### GitHub Actions logs during FFmpeg
- Plain `-stats` uses `\r`; line-based stderr readers never showed frame progress. compose uses **`-progress pipe:2`** and **`-stats_period 2`** (global options placed immediately after `-y`).
- Blocking `read(4096)` on a pipe: FFmpeg can go quiet for minutes during filter init, so the job looked frozen. **`_pump_ffmpeg_stderr`** in `reel_composer.py` uses **`select()` + 25 s heartbeat** on POSIX while FFmpeg is still alive.
- **`reel.yml` Post reel step**: `PYTHONUNBUFFERED=1` and **`python3 -u scripts/make_reel.py`**.

### ASS / libass fonts
- `make_reel.py` passes **`assets/fonts/subtitle_fonts`** as `fontsdir` only (e.g. Space Grotesk SemiBold for subs). Avoids loading the entire `assets/fonts` tree on every run.

---

## 2026-05-02 — GitHub Actions + full pipeline hardening

### Scheduler migrated to GitHub Actions
Mac launchd ALL DISABLED. GitHub Actions is sole scheduler (repo: Wonderkid96/factjot).
- Cron times and workflow names: see **[[PUBLISH_PLAN]]** (supersedes older notes here: morning carousel, reel midday, evening list carousel, Sunday weekly-plan).
- State persisted via git commit after every run (ledgers committed back to main)
- 19 secrets set in GitHub via `gh secret set`

### Reel quality hardening
- Wrote curated `reel_script` (≥70 words) + `reel_title` for all 43 eligible q3 facts
- `_pick_fact` requires both fields; no auto-fallback; hard abort if final reel < 35s
- `validate_reel_facts.py` added — run after every fact bank edit
- Root incident: 22.7s Switzerland reel titled "The Story of Until Switzerland" (2026-05-01)

### Audio/FFmpeg fixes
- `loudnorm` once produced 96000 Hz output → Meta rejected. **Canonical rule (see gotchas.md): Meta accepts 48 kHz only** (not 44.1, not 96). Output encoding must force 48 kHz; the old MEMORY_INDEX line about `-ar 44100` was wrong for Meta and contradicted gotchas.
- Voice padding (`voice_padded.mp3`): concat of 48 kHz silence + 44.1 kHz TTS without `aresample` kept 44.1 kHz on the padded file. Fixed in `make_reel.py`: `aresample=48000` + mono `aformat` before `concat`, plus `-ar 48000` on encode.
- `format=auto` on 26 chained overlay ops → non-standard pixel format. Fixed: `format=yuv420`
- `noise=alls=3:allf=t+u` temporal noise removed — slows Instagram transcoder
- ~~`crf 26`, `maxrate 2500k`~~ superseded 2026-05-03 by crf 30 / 800k primary + tighter 413 retries (see new entry above).

### Instagram API rate limit incident
- Created 30+ containers + polled every 3s = ~3000 API calls → hit code 4 / subcode 1349210
- All containers showed ERROR for ~2h regardless of video quality
- Fixed: `_wait_for_finished` polls every 15s (was 3s), initial 10s wait, code-4 backoff 30s
- Never create >5-6 containers per session. If reels fail, wait 2h before retrying.

### Video hosting (historical note)
- 2026-05-02: Cloudinary was still documented as primary here. **Current:** tmpfiles.org primary for Reel MP4 (Meta fetch window); Cloudinary disabled for video after 413 / timeout issues (see gotchas + root `CLAUDE.md`).

### Quote dedup
- `QuoteBank._session_hashes` tracks picks within a process lifetime
- Prevents same closing quote appearing in two carousels from one `plan_week` run
- Fixed 5 existing queue duplicates on 2026-05-02

### Failure auto-capture
- All 4 workflows: `Capture failure to brain log` step (`if: failure()`) → writes to `insta-brain/log.md`
- `make_reel.py`: `brain.append_log()` on every failure exit (footage, FFmpeg, upload, publish)

### TikTok setup (pending approval)
- App submitted for review 2026-05-02: Login Kit + Content Posting API (Direct Post)
- Domain verified: `https://wonderkid96.github.io/factjot/`
- GitHub Pages deployed for policy pages
- Integration NOT YET WIRED into pipeline — awaiting TikTok approval (1-3 business days)

---

## 2026-05-01 — Reel pipeline launched, fact bank expanded

- `make_reel.py` full pipeline live: ElevenLabs TTS, Pexels footage, Playwright overlays, FFmpeg, imgbb thumbnail, Instagram Reel + Story
- 45 q3 facts in `rare_fact_bank.py` (152 total)
- `discover_facts.py`: Reddit TIL auto-discovery with 8-gate quality filter
- `plan_week.py`: Sunday weekly planner, carousel + reel runway check
- First reels posted: Supervolcano, Radium Girls, Demon Core

---

## Operational status (as of 2026-05-03)

| Component | Status |
|---|---|
| Carousels | ✓ Live via GitHub Actions |
| Reels | ✓ Live via GitHub Actions |
| Stories | ✓ Auto-posted after each Reel |
| Token refresh | ✓ Weekly (Sunday workflow) |
| Fact discovery | ✓ Weekly (Sunday workflow) |
| Reel runway | See `scripts/check_reel_runway.py` (varies with bank + posts) |
| TikTok | Pending review approval |
| Carousel readability improvements | TODO when prioritised |
