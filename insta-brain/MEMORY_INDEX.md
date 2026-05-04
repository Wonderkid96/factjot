# Memory Index

Quick handover ledger. Newest entry first. Older entries summarised or removed once superseded.

Related: [[CLAUDE]] · [[gotchas]] · [[CRITICAL_FACTS]] · [[PUBLISH_PLAN]] · [[log]] · [[rules/13-memory-index]]

---

## 2026-05-05 — Agent handover: commits, background tasks, Actions behaviour

### Repo state (answered "commit the rest?")
- **`main` at `origin`:** **`0eba2a4`** already includes **`rare_fact_bank.py`** ( **`science`** topic / blindsight fact), **`reel_caption.py`**, root **`CLAUDE.md`**, **`make_reel.py`**, **`paths.py`**, **`reel.yml`** / **`reset-and-relaunch.yml`**, brain Obsidian link pass, **`kill_local_reel_jobs.sh`**, **`src/utils/reel_run_logger.py`**. No extra unpushed edits were pending after that push.

### Background shell tasks (Cursor long jobs, all **`exit_code: 5`**)
- **`778842`:** `make_reel.py` (no `--topic`) reached FFmpeg compose for reel **`21f827c2754169`** (Harold Davidson / lions). **`FFmpeg failed (exit 255)`** before publish. Debug: **`data/cache/reels/21f827c2754169/ffmpeg_compose_stderr.log`** (if present) + **`ffmpeg_debug.txt`**.
- **`726712`:** `make_reel.py --topic science` ( **`1520bbd8d4e0a2`** ). Compose at **~0.017x** speed; then **`Exiting normally, received signal 15`** (SIGTERM). No Instagram publish.
- **`53633`:** Same science reel after **`kill_local_reel_jobs.sh`**; compose **~0.0046x**, long stall around **frame ~275 / ~9s** output time, then **signal 15**. No publish.
- **Interpretation:** **5** is the script failure path after FFmpeg error or interrupted compose. **255** = real FFmpeg failure; **15** = external kill / timeout, not "Meta broke".

### Hygiene after killed locals
- If Python or FFmpeg is killed hard, remove stale **`data/cache/reels/.make_reel.lock`** if it remains ( **`finally`** normally clears it).

### `reel.yml` manual dispatch (no `force`)
- **`workflow_dispatch`** without **`force: true`** runs **`check_posted_today.py reel`**; if a reel is already logged for that day, **Post reel** is **skipped** (green run, no second feed reel). Example triage: run **25293427059**. Use **`force`** only when Toby explicitly accepts a **second reel the same day** (bypasses idempotency).

---

## 2026-05-04 — Reel ops: logging, single-flight lock, brain graph, Actions

### Local `make_reel.py` (stacked encodes + observability)
- **`fcntl` advisory lock** on `data/cache/reels/.make_reel.lock`: second local run exits **10** with a clear message (prevents multiple FFmpeg composes pegging CPU). Released in **`finally`**.
- **`ReelRunLogger`**: `src/utils/reel_run_logger.py` writes **`data/cache/reels/<id>/pipeline.log`** and **`logs/reel_runs/<UTC>_<id>.log`**; milestones also **`print(..., flush=True)`**.
- **`scripts/kill_local_reel_jobs.sh`**: kills only this repo’s **`make_reel.py`** + FFmpeg jobs that reference **`assets/intros/factjot_intro.mov`**.
- **`src/core/paths.py`**: **`REEL_RUN_LOGS`**, **`ensure_dirs()`** creates **`logs/reel_runs/`**.

### FFmpeg compose (stderr)
- **`reel_composer.py`**: compose stderr goes to **`ffmpeg_compose_stderr.log`** in the reel cache dir (no pipe backpressure). **`ffmpeg_debug.txt`** keeps command + filter graph.

### Brain / Obsidian
- **`[[gotchas]]`** wikilink added to **[[MEMORY_INDEX]]**, **[[PUBLISH_PLAN]]**, **[[CRITICAL_FACTS]]**, **[[rules/index]]**, **[[rules/06-data-capture]]**, **[[rules/09-prompt-read-order]]** (gotchas is step 5), and **Related** header on **`gotchas.md`**. Root **`CLAUDE.md`** explains opening **`insta-brain/`** as the vault for graph edges.

### New reel content
- **`rare_fact_bank.py`**: new topic **`science`** (blindsight / visual cortex). **`reel_caption.py`**: **`science`** hashtag tier. **`make_reel.py`**: **`--topic`** help lists **`science`**.

### GitHub Actions
- **`reel.yml`**: job **`timeout-minutes: 45`** (was 20); job-level **`PYTHONUNBUFFERED: "1"`**; Post reel still **`python3 -u scripts/make_reel.py`**.
- **`reset-and-relaunch.yml`**: Post reel uses **`PYTHONUNBUFFERED=1`** and **`python3 -u scripts/make_reel.py`**.

### Local full publish attempt (science reel, 2026-05-04)
- **`make_reel.py --topic science`** completed TTS + footage + overlays, then entered **`compose()`**. **`ffmpeg_compose_stderr.log`** showed **speed ~0.005x** with **output time frozen ~9s / frame ~275** while wall clock passed **30+ min** (not the old stderr pipe stall: the log file grew). Run was **stopped** to avoid burning the Mac for hours. **Treat as open local performance investigation** (filter cost, `loudnorm`, or single-thread FFmpeg on Apple Silicon). **Canonical full encode + publish:** let **`reel.yml`** on **ubuntu-latest** ship until this is profiled.

---

## 2026-05-03 — Reel encode, Meta audio, CI observability

### Voice and Meta audio
- `make_reel.py`: padding concat now `aresample=48000` + mono `aformat` on both legs before `concat`, `anullsrc` mono 48 kHz, `-ar 48000` on lame output. Stops `voice_padded.mp3` staying at 44.1 kHz (Meta rejects 44.1 and 96 kHz; see gotchas).

### Reel video size (Meta ~5 MB URL fetch)
- `reel_composer.py` compose: libx264 **crf 30**, **maxrate 800k**, **bufsize 1600k**, preset **ultrafast** (replaces older crf 23 primary encode that ballooned files and caused 413).
- `make_reel.py` publish retries: first recompress after 413 **crf 33 / 600k**, second **crf 35 / 500k** (first attempt must differ from primary 30/800k).

### GitHub Actions logs during FFmpeg
- **Removed `-progress pipe:2`** (2026-05-03 follow-up): it flooded stderr; with **`stderr=None`** FFmpeg inherited a **narrow pipe** in Cursor/agent and some CI wrappers, the buffer filled, and **FFmpeg blocked on stderr writes** (fake “stuck on frame 0”). Compose stderr now goes to **`ffmpeg_compose_stderr.log`** in the reel cache dir; failures include a tail in the raised error.
- Blocking `read(4096)` on a pipe without draining: can deadlock the child. **`_pump_ffmpeg_stderr`** in `reel_composer.py` uses **`select()` + 25 s heartbeat** on POSIX when that pattern is used.
- **`reel.yml` Post reel step**: `PYTHONUNBUFFERED=1` and **`python3 -u scripts/make_reel.py`**.

### ASS / libass fonts
- `make_reel.py` passes **`assets/fonts/subtitle_fonts`** as `fontsdir` only (e.g. Space Grotesk SemiBold for subs). Avoids loading the entire `assets/fonts` tree on every run.

### Local FFmpeg (`FFMPEG_BIN`)
- `src/core/ffmpeg_bin.py`: **`assert_reel_ffmpeg_ready()`** at start of `make_reel.py` (requires **`ass`** / libass). Default Homebrew **`ffmpeg`** often lacks it; use **`ffmpeg-full`** or set **`FFMPEG_BIN`** to a full path. All `make_reel` FFmpeg subprocesses and `compose(ffmpeg_bin=...)` use that binary.

### Reel compose "stuck on frame 0" for hours (2026-05-03)
- **Symptom:** **`frame=0`** for a long time, or **no forward progress**; runs looked hung for **hours**.
- **Cause A (graph cost):** **`image2` + `stream_loop -1`** defaulted to **25 fps** on stills; huge JPEGs multiplied decodes before **`concat`**. **Fix:** **`-framerate 1`** before still **`-i`**, **`,fps=30`** after each clip leg (see `_build_filter_graph`).
- **Cause B (silent stall):** **`-progress pipe:2`** + inherited stderr **pipe backpressure** once the buffer filled. **Fix:** drop **`-progress`**, log compose stderr to **`ffmpeg_compose_stderr.log`**.
- **Not corruption:** Tier-0 JPEGs and H.264 clips were valid; failures were **scheduling + IO**, not bad media.

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
