# Pipelines & Publishing Codemap

**Last Updated:** 2026-05-19  
**Entry Points:** `pipelines/{reel,carousel,list}/` + `.github/workflows/`  
**Architecture Phase:** Autonomous-only (2026-05-07), 2-slot cadence (2026-05-19)  

---

## Pipeline Directory Structure

```
pipelines/
├── reel/                    Reel (video) pipeline
│   ├── make_reel.py         Entry point: script + title -> MP4 + thumbnail + story
│   ├── fetch_reel_metrics.py Read Instagram insights, append to performance ledger
│   ├── download_music.py    Download royalty-free background music
│   └── setup_reel_assets.py Copy brand assets (intros, overlays)
├── carousel/                Carousel (image) pipeline
│   ├── ship_carousel_post.py Entry point: brief -> PNG slides + publish
│   └── score_performance.py  Analytics helper (unused in current flow)
├── list/                    List carousel pipeline (legacy entry point)
│   └── ship_curated_list.py  Deprecated; routed via ship_carousel_post.py --type list
├── manual/                  Manual carousel wrapper
│   └── ship_manual_post.py   Wraps carousel logic, imports news renderers
├── shared/                  Cross-pipeline ops
│   ├── check_meta_setup.py  Validate .env + token scopes
│   ├── refresh_token.py     Refresh long-lived Meta token (60-day)
│   ├── log_workflow_failure.py Log failures to insta-brain/log.md
│   ├── check_brain_fresh.py Check ledgers are in sync
│   ├── check_posted_today.py Query posted.jsonl for recent posts
│   ├── cleanup_caches.py    Clear per-run temps
│   ├── make_avatar.py       Generate profile avatar (unused)
│   ├── make_logo_asset.py   Generate wordmark PNG (unused)
│   ├── auto_schedule_weekly.py Legacy weekly planner (unused)
│   └── setup_token.py       GitHub secrets setup helper
└── __init__.py

# No news/ folder; see DELETED PIPELINES section below.
```

---

## Active Pipelines

### Reel Pipeline (`pipelines/reel/make_reel.py`)

**What it does:**
- Takes a script (4-6 items, 70-120 words) and a title
- Sources video footage from providers (Pexels, YouTube, generic stock)
- Generates voiceover audio (ElevenLabs, 48kHz enforced)
- Renders MP4 with motion, subtitles, branded intro/outro, hard thumbnail
- Publishes to Instagram + YouTube Shorts (same MP4)

**Entrypoint signature:**
```bash
python3 pipelines/reel/make_reel.py \
  --script "Hook. Item 1. Item 2. Item 3. Close." \
  --title "Example" \
  --topic earth \
  --dry-run
```

**Lifecycle stages used:**
- **Source:** Agent-provided script (no discovery)
- **Verify:** Fact claims in script checked at agent level; not re-verified in pipeline
- **Generate:** Voiceover TTS from ElevenLabs
- **Acquire media:** Video footage from `src/research/video_finder.py`
- **Render:** MP4 composition in `src/render/reel_composer.py`
- **Publish:** Graph API to Instagram (reel container) + YouTube Data API
- **Ledger:** Append to `data/ledgers/youtube_uploads.jsonl`, `data/ledgers/api_usage_costs.jsonl`
- **Measure:** `fetch_reel_metrics.py` reads IG insights, appends to `data/ledgers/reel_performance.jsonl` (mutable)

**Key modules:**
- `src/render/reel_composer.py` — FFmpeg script generation (hardwired to case_file_dynamic transitions)
- `src/render/reel_text_renderer.py` — Kinetic subtitle rendering (Archivo Bold 700)
- `src/render/tts_engine.py` — ElevenLabs voiceover engine
- `src/render/reel_story.py` — Story (vertical) tile rendering
- `src/render/thumbnail_picker.py` — Thumbnail frame selection from reel

**Quality gates:**
- Duration floor: 18s (enforced in `reel_composer.py`)
- Audio must be 48 kHz (enforced at ElevenLabs + mux stage)
- Footage confidence: confidence-gated TMDB seeding (optional, fallback to stock)
- Script length: 70-120 words (checked at agent prompt level)

---

### Carousel Pipeline (`pipelines/carousel/ship_carousel_post.py`)

**What it does:**
- Takes a brief (one-sentence to one paragraph) and a format type (fact, list, news, story, etc.)
- Generates carousel copy in two stages: Sonnet (editorial) + Haiku (fitter)
- Fetches images per slide according to visual intent (entity, action, concept)
- Renders PNG slides with carousel footer + branding
- Publishes to Instagram Graph API as a carousel

**Entrypoint signature:**
```bash
python3 pipelines/carousel/ship_carousel_post.py \
  --brief "A list of three major engineering disasters..." \
  --type list \
  --layout-mode readable_list \
  --dry-run
```

**Lifecycle stages used:**
- **Source:** Agent-provided brief (no discovery)
- **Verify:** Fact verification in `src/verification/fact_checker.py` (≥2 sources, confidence ≥0.65)
- **Generate:** Copy via `src/content/carousel_writer.py` (two-stage: Sonnet → Haiku)
- **Acquire media:** Images via `src/research/image_sourcer.py` → `src/research/image_fetcher.py`
- **Render:** PNG slides via `src/render/carousel_slides.py`
- **Publish:** Graph API to Instagram (carousel container)
- **Ledger:** Append to `insta-brain/data/posted.jsonl`, `data/ledgers/used_images.jsonl`, `data/ledgers/carousel_quality.jsonl`
- **Measure:** Agent reads engagement later (not built into pipeline)

**Layout profiles** (from `src/content/carousel_rules.py:LAYOUT_PROFILES`):
- `compact_legacy` — Archivo Black 900, 24-char cap, bottom-left anchor (fact/news direct CLI)
- `readable_list` — Space Grotesk SemiBold, 56-char cap, half-box autofit (list_midday agent + optional news)

**Key modules:**
- `src/content/carousel_writer.py` — Two-stage generation (Sonnet brief → slides → Haiku fit)
- `src/content/carousel_rules.py` — Shared copy rules, layout profiles, ONE SLIDE = ONE IDEA
- `src/verification/fact_checker.py` — Fact sourcing + cross-check
- `src/research/image_sourcer.py` — Image candidate scoring, provider routing (R1/R2/R3)
- `src/render/carousel_slides.py` — PNG rendering (cover, content, story, closing)

**Quality gates:**
- Max 7 slides (compact), 10 slides (list)
- Line fit per slide (height/width) via `src/render/line_fit_probe.py`
- Carousel shape checked in `src/content/carousel_rules.py`
- Image provider validation (licence, provider, match confidence)
- No empty image boxes; all slides must have real media or intentional typography-only layout

---

## Autonomous Workflow (`autonomous-reel.yml`)

**Schedule (2-slot cadence, 2026-05-19):**

| Slot | UTC cron | BST | Mode | Tools exposed |
|---|---|---|---|---|
| `reel_morning` | `0 8 * * *` | 09:00 | Reel | `run_reel`, `skip`, `list_unposted_topics` |
| `list_midday` | `30 11 * * *` | 12:00 | List carousel | `run_carousel`, `skip`, `list_unposted_topics` |

Each slot:
1. Resolves mode from cron (or workflow_dispatch input)
2. Sets `DRY_RUN=false` for scheduled, `DRY_RUN=${{ inputs.dry_run }}` for manual
3. Installs deps (Python, FFmpeg, Playwright)
4. Runs agent with mode-filtered tool exposure
5. Agent reads `list_unposted_topics` (dedupe guard), sources content, calls `run_reel` or `run_carousel`
6. On success: publishes, commits state to git
7. On failure: calls `log_workflow_failure.py`, rolls back, does not commit

**Workflow architecture:**
- Single concurrency group (`factjot-publish`, `cancel-in-progress: false`) — queues overlapping triggers
- Step-level timeouts (3-4 min per critical step) — prevents silent hangs
- Live subprocess output (`live: true` on Python steps) — real-time monitoring
- Per-run cost logging to `data/ledgers/api_usage_costs.jsonl`
- State commit (git add + push) only on successful publish

**Soft steps (after main post):**
- `pipelines/shared/refresh_token.py` — Refresh Meta token if needed
- `scripts/upload_to_youtube.py` — Cross-post reel to YouTube (reel success only)
- `pipelines/reel/fetch_reel_metrics.py` — Fetch IG insights, append performance ledger
- `pipelines/shared/log_workflow_failure.py` — On failure, append to insta-brain/log.md

---

## Manual Workflow (`manual-run.yml`)

**Dispatch trigger:** GitHub Actions → Workflows → `Manual Run` → Run Workflow

**Inputs:**
- `pipeline` — choice: `carousel_fact`, `carousel_list`, `reel`
- `brief` / `script` — text input for the post
- `title` — title (reel only)
- `dry_run` — boolean, default true

**Routes:**
- `carousel_fact` → `ship_carousel_post.py --type fact --layout-mode compact_legacy`
- `carousel_list` → `ship_carousel_post.py --type list --layout-mode readable_list`
- `reel` → `make_reel.py --script ... --title ... --topic general`

---

## Deleted Pipelines

**Deleted 2026-05-07 (architecture switch to autonomous-only):**
- `pipelines/carousel/ship_first_post.py` — Scheduled fact carousel (replaced by agent's `run_carousel` with format=fact)
- `pipelines/list/ship_list_post.py` — List carousel (replaced by agent's `run_carousel` with format=list)
- Workflows: all scheduled-cron pipelines except `autonomous-reel.yml` + `manual-run.yml`

**Deleted 2026-05-10 (audit Phase G.2, decision B — news pipeline kill):**
- `.github/workflows/news-watcher.yml` — Breaking-news Guardian RSS watcher
- `pipelines/news/ship_news_breaking.py` — Breaking-news wrapper
- `pipelines/news/check_guardian_rss.py` — RSS fetcher
- News carousel entry point deleted (renderer functions moved to `src/render/carousel_slides.py`)

**Retained (renderer-only dual role):**
- `pipelines/news/ship_news_post.py` — No CLI entry point; imported by `ship_carousel_post.py` for render functions. Marked for future untangling (SPEC §10.1). Do not delete without updating import in `ship_manual_post.py`.

---

## Cross-Pipeline Shared Ops (`pipelines/shared/`)

| Script | Purpose | Called by | When |
|---|---|---|---|
| `check_meta_setup.py` | Validate .env, token scopes | Manual or CI/CD | Setup verification |
| `refresh_token.py` | Refresh 60-day Meta token | autonomous-reel.yml | Soft step after post |
| `log_workflow_failure.py` | Append failure to insta-brain/log.md | autonomous-reel.yml on failure | Always on error |
| `check_brain_fresh.py` | Verify ledgers are in sync | (Optional) | Manual check |
| `check_posted_today.py` | Query recent posts | (Manual helper) | Status check |
| `cleanup_caches.py` | Remove temp files | (Legacy) | Not called |

---

## State & Ledgers Written by Pipelines

| Ledger | What | Pipeline | Append/Mutable |
|---|---|---|---|
| `insta-brain/data/posted.jsonl` | Every published post (IG ID, caption, timestamp) | carousel + reel | Append-only |
| `data/ledgers/used_images.jsonl` | Every image URL used (URL + SHA256) | carousel | Append-only |
| `data/ledgers/used_footage_urls.jsonl` | Every video URL used in reels | reel | Append-only |
| `data/ledgers/api_usage_costs.jsonl` | API costs per run (Anthropic, ElevenLabs, etc.) | Both | Append-only |
| `data/ledgers/youtube_uploads.jsonl` | YouTube Shorts cross-posts (IG reel ID + YT video ID) | reel | Append-only |
| `data/ledgers/reel_performance.jsonl` | IG engagement metrics (mutable, rewritten per fetch) | reel (fetch step) | Mutable |
| `data/ledgers/carousel_quality.jsonl` | Carousel generation diagnostics (shape errors, line fits) | carousel | Append-only |

---

## Typical Error Handling

| Error | Where caught | Action |
|---|---|---|
| Invalid Meta token | `check_meta_setup.py` or at publish time | Soft step: `refresh_token.py` retries |
| Image fetch timeout | `image_fetcher.py` | Fallback to next provider (R2/R3) or skip slide |
| Fact verification fails | `fact_checker.py` | Carousel aborts, agent receives error tag |
| Carousel too tall | `line_fit_probe.py` + `carousel_rules.py` | Retry with shorter copy or abort |
| Reel < 18s duration | `reel_composer.py` | Reject, agent re-scripts |
| FFmpeg encode fails | `reel_composer.py` | Auto-retry with fallback codec/settings |
| Audio not 48kHz | mux stage | Resample before mux (automatic) |

---

## Testing Pipelines Locally

```bash
# Reel (dry-run, no publish)
python3 /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
  pipelines/reel/make_reel.py \
  --script "Three engineering disasters..." \
  --title "Ignored Warnings" \
  --topic earth \
  --dry-run

# Carousel (dry-run, no publish)
python3 /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
  pipelines/carousel/ship_carousel_post.py \
  --brief "A timeline of..." \
  --type list \
  --layout-mode readable_list \
  --dry-run

# Smoke test (fast image-only, list)
python3 /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
  pipelines/carousel/ship_carousel_post.py \
  --brief "Test brief" \
  --type list \
  --dry-run \
  --smoke-mode
```

Output lands in `output/{reel,carousel}/YYYY-MM-DD_HH-MM_TOPIC/`.

---

## Related Documentation

- `SPEC_FACTJOT_SYSTEM.md` § 4-6 — Pipeline architecture, lifecycle, two-mode model
- `SPEC_IMAGE_PIPELINE.md` — Image sourcing rules, provider order, validation
- `docs/PIPELINE_OPERATIONS_REFERENCE.md` — Production wiring, entrypoint mapping
- `.github/workflows/autonomous-reel.yml` — Workflow definition (source of truth for cron + step order)
