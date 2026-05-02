# Memory Index

Quick handover ledger. Newest entry first. Older entries summarised or removed once superseded.

---

## 2026-05-02 — GitHub Actions + full pipeline hardening

### Scheduler migrated to GitHub Actions
Mac launchd ALL DISABLED. GitHub Actions is sole scheduler (repo: Wonderkid96/factjot).
- `carousel-morning.yml` 09:45 UTC, `carousel-evening.yml` 17:45 UTC, `reel.yml` 18:45 UTC, `weekly-plan.yml` Sunday 04:00 UTC
- State persisted via git commit after every run (ledgers committed back to main)
- 19 secrets set in GitHub via `gh secret set`

### Reel quality hardening
- Wrote curated `reel_script` (≥70 words) + `reel_title` for all 43 eligible q3 facts
- `_pick_fact` requires both fields; no auto-fallback; hard abort if final reel < 35s
- `validate_reel_facts.py` added — run after every fact bank edit
- Root incident: 22.7s Switzerland reel titled "The Story of Until Switzerland" (2026-05-01)

### Audio/FFmpeg fixes
- `loudnorm` upsampled voice+music to 96000 Hz → Instagram rejects. Fixed: `-ar 44100 -ac 2`
- `format=auto` on 26 chained overlay ops → non-standard pixel format. Fixed: `format=yuv420`
- `noise=alls=3:allf=t+u` temporal noise removed — slows Instagram transcoder
- `crf 26`, `maxrate 2500k`, `profile:v main` added

### Instagram API rate limit incident
- Created 30+ containers + polled every 3s = ~3000 API calls → hit code 4 / subcode 1349210
- All containers showed ERROR for ~2h regardless of video quality
- Fixed: `_wait_for_finished` polls every 15s (was 3s), initial 10s wait, code-4 backoff 30s
- Never create >5-6 containers per session. If reels fail, wait 2h before retrying.

### Cloudinary video hosting
- Primary video host: `CloudinaryVideoHost` in `src/publish/image_host.py`
- cloud=dmzer6hgv, preset=factjot (unsigned), API key set in .env + GitHub Secrets
- tmpfiles.org retained as fallback only (unreliable 1h expiry URLs from cloud IPs)

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

## Operational status (as of 2026-05-02)

| Component | Status |
|---|---|
| Carousels | ✓ Live via GitHub Actions |
| Reels | ✓ Live via GitHub Actions (one-off 21:00 UTC trigger tonight for rate limit recovery) |
| Stories | ✓ Auto-posted after each Reel |
| Token refresh | ✓ Weekly (Sunday workflow) |
| Fact discovery | ✓ Weekly (Sunday workflow) |
| Reel runway | 28 facts unused (~4 weeks) |
| TikTok | Pending review approval |
| Carousel readability improvements | TODO next session |
