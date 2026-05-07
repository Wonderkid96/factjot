# factjot - agent operating manual

Owner: **Toby Johnson (TJCreate)**, Lincoln UK. Instagram: @factjot.
Before anything else, read `/Users/Music/.claude/CLAUDE.md` for Toby's universal rules (no em dashes, British English, voice, etc).

**Context management:** Run `/compact` when context usage hits 60% to avoid hitting limits mid-task.

**Fix the tool, not the symptom.** When a value in a data file is wrong (wrong TMDB ID, wrong path, wrong ID in a ledger), do not just patch the value. Find the process that wrote it wrong and fix that process. Patching one bad value means the next one will be wrong too. Example: wrong TMDB IDs in list_packs.py were patched one-by-one until `verify_pack_ids.py` was written to fix them systematically and run weekly.

## Image pipeline rule -- read the spec first

Before touching manual carousel image sourcing, image candidate selection, image provider order, image fallbacks, or manual/news slide rendering, read:

`SPEC_IMAGE_PIPELINE.md`

If the file does not exist, create it in plan mode before making implementation changes.

The product goal is not just to avoid wrong images. The goal is a finished carousel that looks intentional, visually strong, factually accurate, legally usable, and safe to post.

A safe but ugly carousel is still a failed carousel.

Do not patch image sourcing symptoms without checking the spec.

**HISTORICAL HARD RULE (now superseded):** "Facts must come from Reddit only." This rule applied while the system used `discover_facts.py` to populate `rare_fact_bank.py` and `discovered_facts.jsonl` and the cron pipelines posted from that bank. The autonomous-only architecture (2026-05-07) deleted those crons. The autonomous agent now sources ideas directly from Sonnet 4.6's knowledge under the prompt's INTERESTINGNESS GATE / EVENT-VS-ANGLE / QUALITY GATE. The fact bank file (`rare_fact_bank.py`) still exists on disk but is **dormant**: the autonomous reel path provides a `--script` directly via the agent's `run_reel` tool and bypasses `_pick_fact()`. Do not re-add scheduled discovery cron without explicit approval.

**HARD RULE -- transitions are hardwired.** `case_file_dynamic` is the only reel transition mode. It is hardcoded in `src/render/reel_composer.py`. Do not add env var flags, feature toggles, or `--classic` fallbacks. The REEL_TRANSITIONS_MODE env var no longer exists. Every reel uses case_file_dynamic, always.

**HARD RULE -- never force-push to main.** Force-pushing rewrites history and silently deletes state commits (posted.jsonl, list_posts.jsonl, reels.jsonl updates) that running workflows have just written. This caused the horror film triple-post incident on 2026-05-05. If large files need removing from history, do it on a separate branch with workflows paused first.

**HARD RULE -- no empty image boxes.** If a carousel slide has no usable image, the renderer must use an intentional typography-only layout. Never render an empty photo rectangle, blank image slot, or near-invisible placeholder and call it success.

**HARD RULE -- image pipeline changes require plan mode.** Any change to `image_sourcer.py`, `image_fetcher.py`, manual carousel rendering, provider order, image fallback logic, or candidate scoring/selection must begin in plan mode. The plan must list files touched, functions touched, expected behaviour, acceptance tests, and rollback path.

**Image sourcing success means visual success.** Unit tests passing is not enough. The rendered output must be inspected. If the carousel has wrong images, repeated weak images, blank slots, or accidental empty boxes, the task is not complete.

---

## Known architecture risks (do not edit blindly)

**`pipelines/news/ship_news_post.py` has dual responsibility.** It is both:

1. The news pipeline's entry-point script (called by `news-carousel.yml`).
2. The renderer used by the manual / editorial carousel pipeline (`pipelines/manual/ship_manual_post.py` currently delegates rendering to it, and dry-run previews from the manual pipeline land in `output/news/...`).

This means an edit to `ship_news_post.py` for one purpose can silently affect the other. If you are asked to "fix manual carousel rendering" or "change manual slide layout", you will end up editing news-pipeline code. If you are asked to "change news layout", you will affect the manual pipeline.

This is a known mismatch flagged in `SPEC_FACTJOT_SYSTEM.md` section 10.1 and is to be untangled in a deliberate refactor (split renderer from news entry point, route manual through its own renderer, write to `output/manual/`). Until that refactor lands, treat any change here as cross-pipeline and inspect both manual and news rendered output before shipping.

---

## Open decisions (not for ad-hoc resolution)

Items below are deliberately undecided. Do not pick one in passing. They are owned by the relevant spec or by Toby and will be resolved in a focused decision.

- **INK black hex.** The system currently references INK as both `#0A0A0A` (CLAUDE.md typography section, brand colours line) and `#0B0B0C` (`SPEC_IMAGE_PIPELINE.md` section 12, typography-only fallback background). Final value belongs in `brand/brand_kit.json` once the style guide is migrated, and is owned by the future `SPEC_STYLE_GUIDE.md`. Do not unilaterally normalise either value in code or in templates.

---

## What this project is

Fully automated Instagram account posting via a single autonomous agent:

- **3 posts/day** at 10:00 / 13:00 / 18:00 BST (09:00 / 12:00 / 17:00 UTC)
- The agent (Sonnet 4.6) reads the post bank, picks the strongest non-duplicate idea, writes the brief or script, and chooses format (reel, carousel, list-style carousel)
- One workflow: `autonomous-reel.yml` with three scheduled crons + manual dispatch
- Modes: `morning`, `lunch`, `evening`. Lunch additionally has permission to use a current/breaking story if it passes the same quality bar; otherwise lunch falls back to evergreen
- Successful reel posts cross-post automatically to YouTube as Shorts (same MP4, same caption + `#Shorts`, same custom thumbnail)

Stack: Python 3.11, Playwright + Chromium (HTML rendering), FFmpeg (Reels), ElevenLabs (voice, paid), Anthropic Sonnet 4.6 (agent + carousel writing), Anthropic Haiku 4.5 (image selection / repair / hashtags / search-query expansion), Instagram Graph API, YouTube Data API v3, imgbb + tmpfiles.org (image / video hosting).

**The Mac does not need to be on.** GitHub Actions handles all posting 24/7.

---

## Local output locations

All pipeline renders are written to `output/` (gitignored, local only). Named `YYYY-MM-DD_HH-MM_TOPIC` so they sort chronologically in Finder.

```
output/
  carousel/   fact carousel slides    (src/core/paths.py: RENDERS_CACHE)
  reel/       reel build artefacts    (src/core/paths.py: REELS_CACHE)
  list/       list carousel slides    (src/core/paths.py: LIST_RENDERS)
  news/       news carousel previews  (src/core/paths.py: NEWS_RENDERS)
  experiments/ prototype pipeline output
```

Dry-run previews: `pipelines/news/ship_news_post.py --dry-run` auto-saves to `output/news/YYYY-MM-DD_HH-MM_SECTION/`.

---

## Canonical Python path

For **local runs** on Toby's Mac:

```
/Library/Frameworks/Python.framework/Versions/Current/bin/python3
```

Never bare `python3` locally; packages will not be found.

In **GitHub Actions**, bare `python3` is correct (pip installs to the runner's system Python).

---

## Daily automation - GitHub Actions

**Single workflow handles all posting.** `autonomous-reel.yml` is the only intentional poster. All legacy multi-cron workflows (carousel-morning, reel, list-carousel, news-carousel, news-watcher, weekly-plan, daily-metrics, reset-and-relaunch) were deleted on 2026-05-07. No launchd, no cron-job.org dependency, no per-pipeline daily caps - the agent's prompt-level duplicate guard is the only dedup layer.

**The legacy queue is also disabled.** `pipelines/shared/publish_due.py`, `pipelines/shared/review_queue.py`, the `queue.jsonl` ledger, and the older "approve queued posts then publish" rhythm in README.md are legacy. The autonomous flow does not use them. They are kept on disk for reference and for the (rare) manual override case (`publish_now.py`).

**CRITICAL -- NEVER force-push to main.** Force-pushing rewrites history and silently deletes state commits (posted.jsonl, list_posts.jsonl, reels.jsonl updates) that running workflows have just written. This is what caused the triple-post incident on 2026-05-05. If large files need removing from history, do it on a separate branch, test, then merge -- never force-push to an active main branch.

### Posting schedule (BST = UTC+1)

All three fires use the same workflow with a different `post_mode` resolved from the cron schedule:

| Mode    | BST   | UTC   | Cron expression  | Behaviour                                                |
| ------- | ----- | ----- | ---------------- | -------------------------------------------------------- |
| morning | 10:00 | 09:00 | `0 9 * * *`      | Standard autonomous flow. No news permission.            |
| lunch   | 13:00 | 12:00 | `0 12 * * *`     | Standard flow + permission to use a current/breaking story if it clears the same quality bar; falls back to evergreen otherwise. |
| evening | 18:00 | 17:00 | `0 17 * * *`     | Standard autonomous flow. No news permission.            |

### All GitHub Actions workflows

Only two workflows exist after the 2026-05-07 cleanup:

| File | Role |
| ---- | ---- |
| `autonomous-reel.yml` | The agent. Three scheduled crons + manual dispatch. Drives the entire posting cadence. |
| `pages.yml`           | GitHub Pages build for `docs/` (privacy, terms). Never publishes to social. |

Everything else has been deleted. Do not re-add legacy posting workflows without explicitly removing the autonomous workflow first or double-posts will occur.

### How it fires

GitHub's built-in cron fires the autonomous workflow three times a day at 09:00 / 12:00 / 17:00 UTC. There is no longer a cron-job.org backup; the previous backup crons (`+45 min`) are also gone. The agent's prompt-level duplicate guard means a delayed or duplicate dispatch cannot accidentally produce a similar second post.

### Every autonomous run does

1. Resolve `post_mode` from the cron expression (or workflow_dispatch input)
2. Checkout (full history - needed for rebase)
3. Set up Python 3.11 + pip cache
4. Install FFmpeg via `FedericoCarboni/setup-ffmpeg@v3` (pre-built binary, not apt-get)
5. Install Python dependencies (4 min step timeout)
6. Cache / install Playwright Chromium (8 min step timeout, has restore-keys for partial cache hits across `requirements.txt` changes)
7. Install Playwright system deps via apt (6 min step timeout)
8. Write `.env` from GitHub secrets
9. Pull latest state
10. **Refresh Meta access token** (soft, `continue-on-error`) - folded in from the deleted `weekly-plan.yml`
11. **Run autonomous Claude agent** (40 min step timeout): Sonnet 4.6 reads `posted.jsonl`, picks an idea, writes a brief or script, calls exactly one of `run_reel` / `run_carousel` once
12. **Cross-post latest reel to YouTube as Short** (soft, only on success and when `dry_run!=true`): script picks the latest entry from `reels.jsonl`, checks freshness (last 30 min) + dedup (against `youtube_uploads.jsonl`), uploads `final.mp4` resumably, sets the same custom thumbnail
13. **Fetch IG reel performance metrics** (soft, `if: always()`) - folded in from the deleted `daily-metrics.yml`
14. Capture failure to brain log on any non-soft failure
15. Commit and push state (always runs). Each ledger file is staged individually so a missing file (e.g. `youtube_uploads.jsonl` on the first cross-post run) does not abort the whole `git add`.

### Concurrency

`concurrency.group: factjot-publish` with `cancel-in-progress: false` - if a manual dispatch overlaps a scheduled run, the second queues rather than cancelling. Job-level `timeout-minutes: 45`.

---

## Reel pipeline - full flow

The autonomous agent provides the script + title + topic + hint via the `run_reel` tool, which subprocesses `make_reel.py --script ... --title ... --topic ... --tone-override ... --hint ...`. The pipeline below describes that path. The legacy `_pick_fact()` selection from `rare_fact_bank.py` is still on disk but never called when `--script` is provided.

```
make_reel.py (autonomous path: --script provided)
  fact = autonomous dict   → script, title, topic, tone, image_hint from the agent
  build VO script  → uses --script directly (>=70 words; agent enforces this in its prompt)
  ElevenLabs TTS   → word-level beat timestamps (edge-tts fallback if key missing)
                     stability tuned per tone (shocking 0.38 / sober 0.65)
  find 8 clips     → Pexels → Coverr → Pixabay → Wikimedia (anchored to --hint)
                     score=0 clips rejected - never use footage with zero tag relevance
  pre-render stills→ JPEG/PNG/WebP footage pre-rendered to 30fps MP4 before main compose
  render overlays  → Playwright: label bar, hook title, kinetic subtitles, CTA card
  FFmpeg compose   → 8 clips, animated pan-crop, alpha intro, sidechain music, fade-to-black
  thumbnail        → footage frame + branded overlay (variant E, Archivo Black)
  story PNG        → stripped layout (Archivo Black headline + NEW REEL pill)
  caption          → title + body + CTA + source credits + 3-tier hashtags
  upload MP4       → tmpfiles.org (1-hr URL, Meta fetches within polling window)
  upload thumbnail → imgbb → passed as cover_url to Instagram
  publish_reel()   → Reel live on feed with branded thumbnail
  post_to_stories()→ Story fires immediately after
  ledger           → insta-brain/data/reels.jsonl + data/ledgers/used_footage_urls.jsonl
  YouTube cross-post (soft, in workflow): same final.mp4 → Shorts upload
```

**Video encoding:** Primary encode at **crf 23, preset medium, bicubic scale** (no maxrate). Pre-upload size check: if >4.7MB, two-pass VBR recompress at crf 30 / maxrate 800k. Adaptive retry on Meta 413: crf 33 / 600k, then crf 35 / 500k.

**Cloudinary is DISABLED as primary** (Meta 413'd it 2026-05-02 because URLs don't expire before Meta fetches). Could re-enable if needed for non-expiring URLs, but tmpfiles works fine within the polling window.

**Global footage dedup:** `data/ledgers/used_footage_urls.jsonl` tracks all video URLs ever used. Same video never appears in two different reels.

**Run commands (local, Mac):**

```bash
cd /Users/Music/Developer/Insta-bot
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 pipelines/reel/make_reel.py
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 pipelines/reel/make_reel.py --dry-run
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 pipelines/reel/make_reel.py --topic earth
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 pipelines/reel/make_reel.py --list-facts
```

**Local notes:** only one `make_reel.py` at a time (lock, exit **10** if contested). Per-run logs: `output/reel/<id>/pipeline.log` and `logs/reel_runs/`; compose stderr: `ffmpeg_compose_stderr.log`; FFmpeg live progress: `ffmpeg_progress.txt` (tail for `frame=/time=/speed=`) -- all in the reel output dir. If a run is killed, remove a stale `.make_reel.lock` if it remains.

FFmpeg graph template path: each reel compose writes `ffmpeg_filter_complex.txt` in the reel cache dir and runs FFmpeg with `-filter_complex_script`.

Reel visual toggles:

- `case_file_dynamic` is hardcoded. There is no `REEL_TRANSITIONS_MODE` toggle.
- `REEL_TEXTURE_FINISH=on|off` (default `on`)
- `REEL_TEXTURE_INTENSITY=low|medium` (default `low`)
- `REEL_GRIT_OVERLAY_PATH=/abs/path/to/animated_grit.mov` (optional override)
- `REEL_HOOK_OPTIMISER=off|on` (default `off`; generated hook/title selection)
- `REEL_PACING_PROFILE=classic|dynamic_lite` (default `classic`; subtitle pacing profile)
- `REEL_CLIP_MIN_CONF_SCORE=0.45` (default; low-confidence clip filter in beat selection)

API usage ledger:

- `data/ledgers/api_usage_costs.jsonl` records per-run usage and cost estimates
- ElevenLabs estimate uses `ELEVENLABS_COST_PER_1K_CHARS` (default `0.30`)
- `data/ledgers/hook_optimiser.jsonl` records generated hook candidates + winner
- `data/ledgers/reel_generation_features.jsonl` records per-reel generation features
  (hook mode, pacing mode, subtitle density, footage confidence summary, transitions/texture modes)

### Reel performance rollout checklist

Use this rollout order for new Reel performance features:

1. Baseline dry run (all defaults): verify reel exports and ledgers write cleanly.
2. Enable `REEL_HOOK_OPTIMISER=on` only: verify title quality + `hook_optimiser.jsonl`.
3. Enable `REEL_PACING_PROFILE=dynamic_lite`: verify subtitle readability and no CTA overlap.
4. Keep `REEL_CLIP_MIN_CONF_SCORE` at `0.45` initially; tune only after observing underfill rate.
5. For each phase, verify:
   - no FFmpeg graph/runtime regressions,
   - output duration/size constraints still pass,
   - publish path unchanged when features are off (classic fallback path intact).

**Project location:** `~/Developer/Insta-bot` (NOT ~/Documents - iCloud in Documents intercepts FFmpeg output writes, causing silent 14-min encode hangs). Do not move back into any iCloud-synced folder.

---

## Key source files


| File                                           | Purpose                                                                             |
| ---------------------------------------------- | ----------------------------------------------------------------------------------- |
| `pipelines/reel/make_reel.py`                  | Main Reel pipeline entry point                                                      |
| `scripts/kill_local_reel_jobs.sh`              | Stops this repo's `make_reel.py` + FFmpeg jobs using `factjot_intro.mov`            |
| `src/utils/reel_run_logger.py`                 | `ReelRunLogger`: `pipeline.log` + `logs/reel_runs/` copies                          |
| `pipelines/carousel/ship_first_post.py`        | Morning carousel (topic-based, quirky_score >= 2 floor)                             |
| `pipelines/list/ship_list_post.py`             | Evening list carousel (cache-first, then TMDB fallback)                             |
| `pipelines/list/prepare_packs.py`              | Sunday: pre-resolves all unposted list packs, writes cache                          |
| `pipelines/carousel/restock.py`                | Sunday: fact discovery + runway report across all content types                     |
| `pipelines/shared/refresh_token.py`            | Refreshes Meta 60-day access token                                                  |
| `pipelines/shared/check_posted_today.py`       | Idempotency guard, exits 1 if already posted today                                  |
| `pipelines/shared/check_token.py`              | Verifies Meta token; prints `ok` or `invalid`                                       |
| `pipelines/reel/check_reel_runway.py`          | Counts unposted q2+q3 facts with reel fields for runway                             |
| `pipelines/carousel/discover_facts.py`         | Discovers facts from Reddit TIL; scores 0-3; rejects boring                         |
| `pipelines/shared/log_workflow_failure.py`     | Writes failure entry to brain log on workflow error                                 |
| `pipelines/shared/log_token_alert.py`          | Writes token-expired alert to brain log                                             |
| `src/content/pack_resolver.py`                 | Shared TMDB resolution for list packs (used by both ship_list_post + prepare_packs) |
| `src/research/rare_fact_bank.py`               | Curated facts - source of truth                                                     |
| `src/research/narrative_beats.py`              | 5 footage queries derived from `image_hint`                                         |
| `src/research/video_finder.py`                 | Multi-source footage finder with relevance scoring                                  |
| `src/content/reel_script.py`                   | Formats claim into dramatic VO (narrative build + ellipses)                         |
| `src/content/reel_title.py`                    | Documentary-style title generator                                                   |
| `src/content/reel_caption.py`                  | Caption: title + body + CTA + source credits + 3-tier hashtags                      |
| `src/render/tts_engine.py`                     | ElevenLabs primary, edge-tts fallback - returns word beats                          |
| `src/render/reel_composer.py`                  | FFmpeg composition - constants, timing, filter graph builder                        |
| `src/render/reel_text_renderer.py`             | Playwright overlay renderer (all overlay PNGs)                                      |
| `src/render/reel_thumbnail.py`                 | Footage frame base64 + branded overlay composite                                    |
| `src/render/reel_story.py`                     | Story PNG renderer (same footage frame + story card)                                |
| `src/render/templates/reel_text_frame.html.j2` | Reel overlay template                                                               |
| `src/render/templates/reel_thumbnail.html.j2`  | Thumbnail template                                                                  |
| `src/render/templates/reel_story.html.j2`      | Story template                                                                      |
| `src/publish/instagram_publisher.py`           | `publish_reel()` + `post_to_stories()`                                              |
| `src/publish/image_host.py`                    | imgbb + tmpfiles with PNG salting for fresh URLs                                    |
| `src/core/brand.py`                            | Brand constants - fonts, colours, dimensions                                        |
| `src/core/paths.py`                            | All file paths - single source of truth                                             |
| `src/core/ffmpeg_bin.py`                       | `FFMPEG_BIN` + startup check; auto-falls-back to brew ffmpeg-full if default fails  |
| `pipelines/reel/download_music.py`             | Helper to populate assets/music/ from Pixabay or flag missing tracks                |
| `pipelines/manual/ship_manual_post.py`         | Manual carousel pipeline, content generation, image intent, rendering entry point   |
| `src/research/image_sourcer.py`                | Manual/news image orchestration, candidate pool, Haiku selector/scoring/fallback    |
| `src/research/image_fetcher.py`                | Low-level image provider search, candidate fetching, hard validation                |
| `src/research/used_images.py`                  | Image URL/SHA ledger                                                                |
| `pipelines/news/ship_news_post.py`             | News/manual slide renderer currently used by manual pipeline (DUAL ROLE, see warning below) |
| `SPEC_IMAGE_PIPELINE.md`                       | Required spec for image sourcing and fallback behaviour                             |
| `SPEC_FACTJOT_SYSTEM.md`                       | Top-level system constitution (read before any cross-cutting change)                |


---

## Fact bank

- **65 q3 facts** - shock tier only. All q1/q2 (boring internet trivia + Wikipedia unusual deaths) removed 2026-05-04.
- All q3 facts **must** have curated `reel_script` (>=70 words) and `reel_title` - hard gate enforced
- Sources: BBC, Smithsonian, NASA, National Geographic, NOAA. No Wikipedia-sourced facts.
- `allow_archival=True` set on facts where low-quality archival footage is appropriate (Voynich Manuscript, First Photograph)
- `discover_facts.py` is **Reddit-only**: r/Damnthatsinteresting, r/interestingasfuck, r/UnresolvedMysteries, r/AskHistorians, r/history. Wikipedia unusual deaths scraper removed. MIN_UPVOTES=10,000 for main subs. Scores: 1-3. score=0 = rejected.

**Runway rule:** keep at least 14 unused q3 facts (2 weeks buffer). Reel workflow checks runway before posting - if below 14, runs `discover_facts.py` automatically. Run `scripts/check_reel_runway.py` to see current count.

**To add a new reel-tier fact:**

```python
{
    "topic": "history",               # space/earth/ocean/biology/history/technology
    "claim": "...",                   # 2-3 sentences, self-contained, sourced
    "sources": ["url1", "url2"],      # minimum 2 reputable sources
    "image_hint": "...",              # 3-6 words describing the visual subject
    "quirky_score": 3,                # 3 = "wait, what?" tier
    "reel_title": "...",              # REQUIRED for q3 facts
    "reel_script": "...",             # REQUIRED for q3 facts, >=70 words, dramatic + ellipses
}
```

After editing `rare_fact_bank.py`, always run `scripts/validate_reel_facts.py`.

---

## Reel discovery and runway policy (LEGACY)

This section described the Reddit-discovery + enrichment pipeline used by the deleted `weekly-plan.yml` and `reel.yml` workflows. Both workflows have been removed in the autonomous-only architecture (2026-05-07). The autonomous agent now sources ideas directly from Sonnet 4.6 under the prompt's INTERESTINGNESS / EVENT-VS-ANGLE / QUALITY gates and verifies them at decision time.

The scripts (`pipelines/reel/discover_reel_facts.py`, `pipelines/carousel/restock.py`, `pipelines/reel/runway.py`, etc.) still exist on disk but no scheduled workflow calls them. They can still be run manually if Toby wants to repopulate the legacy fact bank for some reason.

The `data/ledgers/discovered_facts.jsonl` ledger is read-only as far as the autonomous flow is concerned - it is never queried during a posting run.

If you ever want to re-introduce a curated content source, do it as a tool the agent can opt into (e.g. `list_validated_facts(format="reel")`) rather than as an automatic substitute for the agent's own decision.

---

## Footage quality rules

**Source priority (Tier 0 runs first):**

1. **Named entity from claim** - proper nouns extracted from the claim text are used as the entity search term for Wikipedia/Wikimedia (e.g. "Phineas Gage" not "vintage skull diagram"). Falls back to `image_hint` if no named person/event found.
2. **Wikipedia lead image** - fetches the actual article image for the named entity (no auth)
3. **Wikimedia Commons** - entity-name search, video preferred over stills, rights-cleared only
4. **Internet Archive** - exact-phrase entity search, scored by relevance
5. **Pexels / Coverr / Pixabay** - B-roll fill from `image_hint`-derived narrative beats

Tier 0 fills the first 1-2 clip slots with the actual person/event. B-roll fills the rest.

**Narrative beats** - the 5 stock-footage queries come from claim entities, not just `image_hint`:

- ESTABLISHING: period + location + action from claim
- SUBJECT: named person + period (e.g. "Phineas Gage 1848 portrait close up")
- DETAIL: `image_hint` as B-roll anchor
- CONSEQUENCE: period + medical/aftermath
- ATMOSPHERE: period mood/setting

`image_hint` is a B-roll guide only. Named people and years are extracted from the claim and drive the specific beats. Facts without named entities (animals, phenomena) fall back to `image_hint`-expansion.

**Quality floors (do not lower):**

- Non-archival: 2MB minimum file size, 4s minimum duration (probed via ffprobe)
- Archival (`allow_archival=True`): 50KB minimum, all sources enabled
- NSFW block: filenames/descriptions containing "nsfw", "explicit", "nude", "porn", etc. are skipped
- **Relevance gate:** score=0 clips are rejected from all stock sources (Pexels, Coverr, Pixabay). A score=0 means zero query words matched the video tags - that's a random clip. Falls through to the next source or safety pool.

**Dedup:**

- `used_source_urls` set prevents same video appearing twice within a single Reel
- `data/ledgers/used_footage_urls.jsonl` (git-tracked) prevents same video across different Reels
- Pexels fetches 15 results per query to allow deduplication to find alternatives

---

## Reel timing constants


| Constant          | Value                    | Meaning                                                       |
| ----------------- | ------------------------ | ------------------------------------------------------------- |
| `INTRO_S`         | 1.5s                     | Silent window - hook title visible, voice starts after        |
| `MUSIC_VOLUME`    | 0.24                     | Background music (sidechain-ducked under voice)               |
| `FADE_TO_BLACK_S` | 1.5s                     | Final fade duration                                           |
| `KEN_BURNS_ZOOM`  | 0.20                     | 20% overscan - active pan on every clip                       |
| CTA timing        | dynamic                  | Card appears when narrator says "factjot" (word-beat sync)    |
| Total duration    | `voice_end + 0.8 + 1.5s` | Tight - no dead air after voice                               |
| FFmpeg crf        | 23                       | High quality - pre-upload size check handles the 5MB cap      |
| FFmpeg preset     | medium                   | Better motion estimation than ultrafast - sharper transitions |
| FFmpeg scale      | bicubic                  | Sharper upscale of 1080p source footage                       |
| FFmpeg audio      | 48kHz, 128k              | Meta requires 48kHz (not 44.1k, not 96k)                      |


---

## Reel thumbnail design (variant E, 2026-05-07)

The thumbnail is anchored to the 4:5 grid window safe area (y=285 to y=1635 on the 1080×1920 canvas) so all branding survives Instagram's profile-grid centre-crop.

- Single soft full-canvas darken overlay (heavier at top + bottom edges, lighter middle) so the footage is still visible behind the headline
- Focused radial gravity well behind the headline area only - keeps the central text legible without flattening the photo
- Header row inside the safe area: `factjot. ────── [ 01 / TOPIC ]`
- Centred Instrument Serif kicker (off-white, e.g. "DID YOU KNOW")
- **Big lowercase Archivo Black 900 headline (default 132px)** with auto-accent on any 4-digit year (regex-driven, renders in `--accent`)
- Bottom row: SCIENCE-style pill (left) + `[ № 047 ]` counter (right)
- Hard 3px shadows on chrome (no soft blur - radial focus does the legibility work)
- Template: `src/render/templates/reel_thumbnail.html.j2` (rendered via `src/render/reel_thumbnail.py`)

**Reel story** uses a stripped layout: full-canvas darken, central Archivo Black headline only, small red `NEW REEL` pill below. No masthead, no fact counter. The pair (cover + story) read as one design language. Template: `src/render/templates/reel_story.html.j2`.

**Carousel slides** mirror the reel cover's headline treatment: Archivo Black 900 lowercase, year auto-accent, accent-period via CSS `::after`. The full-width `factjot. ────── TOPIC/INDEX` header runs inside the same safe-area framing. Wordmark is now the canonical inline 3-part HTML across every template (`fact[normal] jot[italic] .[red]`); the legacy PNG fallback was removed on 2026-05-07. See `src/render/templates/slide.html.j2`, `closing.html.j2`, `list_hook.html.j2`, `list_item.html.j2`, `list_closing.html.j2`, `stories_frame.html.j2`.

---

## Typography - strict brand rule


Source of truth: `brand/brand_kit.json` (v2.0) and `brand/style-guide-v2.pdf` (gitignored, kept locally).

| Font                              | Use                                                | File                                     |
| --------------------------------- | -------------------------------------------------- | ---------------------------------------- |
| Instrument Serif Regular + Italic | Hook titles, wordmark, title cards                 | `assets/fonts/InstrumentSerif-*.ttf`     |
| Space Grotesk SemiBold 600        | Subtitles, body text                               | `assets/fonts/SpaceGrotesk-SemiBold.ttf` |
| JetBrains Mono Bold 700           | Labels, badges, tags                               | `assets/fonts/JetBrainsMono-Bold.ttf`    |
| Archivo Black 900 (v2, NEW)       | Short-form video burn-in subtitles only - never elsewhere | `assets/fonts/ArchivoBlack-Regular.ttf`  |

Archivo Black is scoped: lowercase preferred, tracking `-0.015em` to `-0.005em`, line-height `1.0`-`1.1`. Pairs against Instrument Serif. Do not use it for headlines, labels, or wordmark. Do not switch existing renderers to it without explicit approval.

Wordmark: `fact*jot*.` - "jot" italic, "." in `#E6352A`, base off-white `#EDE8DD`. Unchanged in v2.
Brand colours: PAPER `#F4F1E9` INK `#0A0A0A` ACCENT `#E6352A` LIME `#C8DB45` LILAC `#C4A9D0`.
v2 additions: SKY `#C9D8E2` AVAILABLE `#80EF80`, surface tokens `dark_bg #0A0A0A` / `surface #161614` / `elevated #1E1E1B`, brand gradient `accent → paper → lime → lilac` at 90°.
Shadow style: hard drop `2px 2px 0 rgba(0,0,0,0.5)` - matches carousels, no blur.

---

## API keys (all in `.env` locally; GitHub secrets in Actions)


| Key                    | Service                                    | Notes                                                               |
| ---------------------- | ------------------------------------------ | ------------------------------------------------------------------- |
| `META_ACCESS_TOKEN`    | Instagram Graph API                        | 60-day rolling. Refresh weekly via `refresh_token.py`.              |
| `META_APP_ID`          | Meta app identifier                        | factjot-publisher app. Used by token refresh flow.                  |
| `META_APP_SECRET`      | Meta app secret                            | Required to long-lived-token-exchange.                              |
| `META_GRAPH_VERSION`   | Graph API version                          | e.g. `v25.0`. Pinned in workflow secrets.                           |
| `META_GRAPH_HOST`      | Graph API host                             | `graph.facebook.com`                                                |
| `META_LOGIN_FLOW`      | Token refresh login flow                   | Used by Sunday weekly-plan token refresh.                           |
| `INSTAGRAM_ACCOUNT_ID` | IG business account id                     | The numeric id of @factjot.                                         |
| `FACEBOOK_PAGE_ID`     | Facebook page id                           | Linked page id for the IG account.                                  |
| `ANTHROPIC_API_KEY`    | Anthropic API                              | Used by autonomous agent (Sonnet 4.6) and carousel writer (Sonnet 4.6) + selectors (Haiku 4.5). |
| `ELEVENLABS_API_KEY`   | Voice                                      | Paid. ~500 chars/reel.                                              |
| `ELEVENLABS_VOICE`     | ElevenLabs voice id                        | Currently `MFZUKuGQUsGJPQjTS4wC`.                                   |
| `PEXELS_API_KEY`       | Primary footage + R3 stock B-roll          | Free, 200 req/hr                                                    |
| `COVERR_API_KEY`       | Secondary footage                          | Demo, 1,000 calls/month                                             |
| `PIXABAY_API_KEY`      | Tertiary footage + R3 stock B-roll         | Free                                                                |
| `IMGBB_API_KEY`        | Thumbnail + story + carousel image hosting | Free                                                                |
| `IMAGE_HOST`           | Image-host backend selector                | `imgbb` (default) or `cloudinary,imgbb,tmpfiles` for fallback chain |
| `CLOUDINARY_`*         | Video hosting (disabled)                   | cloud=dmzer6hgv, preset=factjot. Kept in secrets, not used.         |
| `TMDB_API_KEY`         | TMDB v3 API key                            | Used by list pack TMDB resolver (legacy script).                    |
| `TMDB_READ_TOKEN`      | TMDB v4 read token                         | Used by some TMDB endpoints (legacy).                               |
| `OMDB_API_KEY`         | OMDB fallback for film metadata            | Used by legacy list pipeline.                                       |
| `MUSIC_CREDIT`         | Caption credit line                        | Set to "Track · Artist" for background music                        |
| `YOUTUBE_CLIENT_ID`    | YouTube OAuth client id                    | From Google Cloud project FACTJOT-YT.                               |
| `YOUTUBE_CLIENT_SECRET`| YouTube OAuth client secret                | Pair with CLIENT_ID. Treat as sensitive.                            |
| `YOUTUBE_REFRESH_TOKEN`| YouTube refresh token                      | One-time auth via `scripts/setup_youtube_auth.py`. Bound to `thefactjot@gmail.com`. |

**The cron-job.org backup is gone.** `CRON_TRIGGER_PAT` (legacy) is no longer required by any active workflow.

**Token failure:** if `refresh_token.py` returns "API access blocked", the account was rate-limited by rapid API calls. Wait 30 min, then retry. If still blocked, regenerate via `setup_token.py` with a fresh short-lived token from developers.facebook.com → factjot app → Instagram → API Setup.

**YouTube auth refresh:** run `scripts/setup_youtube_auth.py /path/to/client_secret.json`. Authorise as `thefactjot@gmail.com`. The script prints the three secrets to set; pipe each into `gh secret set <NAME>`.

---

## Caption structure

Every Reel caption:

```
[Title or first sentence of claim]
[1 punchy sentence - the most striking detail]

[Randomised CTA - "Follow @factjot..."]

[Source credits]
[Footage credit]
[Music credit if set]

[3-tier hashtags: broad + topic + subject-specific]
```

Hashtags are 3-tier: 5 broad (`#facts #didyouknow`) + 5 topic (`#earthscience`) + 5 subject-specific extracted from the claim/title (`#supervolcano #humanevolution`).

---

## YAML rules for GitHub Actions workflows

GitHub uses a Go YAML parser (stricter than Python's PyYAML):

- **No em dashes** in comments or strings - Go parser rejects UTF-8 `-`. Use hyphens.
- **No multiline Python heredocs** inside `run: |` blocks - extract to dedicated scripts.
- If a workflow fails to dispatch with 422 "no workflow_dispatch trigger", the YAML is broken. Fix the YAML, push, then retry.

---

## Fix philosophy - mandatory for every agent

Every fix must be a long-term structural fix, not a temporary patch. A patch that suppresses a symptom without removing its root cause will reappear in a different form or a different part of the pipeline. Before shipping any fix, ask: does this eliminate the cause, or does it hide it? If it hides it, keep digging. No half-measures.

## Gotchas

`insta-brain/gotchas.md` - read this before touching anything. It documents everything that has broken, been tried, and failed. Keep it current. If you hit a new wall, add it before closing the session.

**Obsidian:** open the `insta-brain/` folder as a vault (or use the repo’s brain notes there). Hub notes use wikilinks so **[[gotchas]]** appears in the graph: start from **[[MEMORY_INDEX]]** in the same vault, or link **[[gotchas]]** from any note you edit. Plain paths alone do not create graph edges.

**Empty image string gotcha:** if a pipeline returns an empty string for an image slot, confirm how the renderer handles it. Empty string must not become a blank photo box. It must become a deliberate typography-only slide or the run must fail with a clear reason. Never assume the renderer handles this correctly without checking the template.

---

## Invariants - never break

1. Never repost a fact - check `insta-brain/data/posted.jsonl`.
2. Never reuse a carousel image across posts unless the relevant ledger/spec explicitly allows it. Within a single manual carousel, image reuse is only allowed by `SPEC_IMAGE_PIPELINE.md`: max 2 uses per URL, no consecutive duplicates, and only when reuse is better than a weak or misleading image.
3. Every fact must be 100% true - 2+ reputable sources, confidence >= 0.65.
4. No em dashes - anywhere, ever. Including YAML workflow comments.
5. British English throughout all copy.
6. Append-only ledgers - never edit historical lines. **Exception:** `data/ledgers/reel_performance.jsonl` is a mutable metrics store - it is fully rewritten on each `fetch_reel_metrics.py` run to update engagement numbers as they accumulate. Do not convert it to append-only.
7. Four fonts only - brand-locked. Three primaries (Instrument Serif, Space Grotesk, JetBrains Mono) plus Archivo Black scoped strictly to short-form video burn-in subtitles. No fifth font.
8. Reels use `quirky_score=3` facts only (fallback to q2 only when q3 exhausted).
9. All q3 facts must have curated `reel_script` (>=70 words) and `reel_title`.
10. Always use the full Python path for local runs. Bare `python3` only in GitHub Actions.
11. `--dry-run` first if you're unsure - it generates all assets without posting.
12. Audio must be 48kHz - Meta rejects 44.1kHz and 96kHz.

---

## Debugging workflow failures

1. Go to github.com/Wonderkid96/factjot → Actions tab
2. Find the failed run, read the step logs
3. Common causes: Meta token expired (`check_token.py` step fails), YAML parse error (422 on dispatch), git push conflict (rebase step fails), Meta 413 (video too large)
4. If token expired: run `refresh_token.py` locally, update `META_ACCESS_TOKEN` secret
5. Do not run scripts locally while Actions is active - race condition on ledger files

---

## What is NOT yet done

- TikTok integration - app submitted for review 2026-05-02; not yet wired into the autonomous workflow
- Meta System User token - current token is 60-day rolling; switching to System User would make it permanent (requires manual setup in Meta Business Manager)
- Per-run agent decision-note logging - the agent writes its decision note privately as part of its assistant message, but the workflow only logs subprocess output. Adding a print of the model's text content blocks would surface the decision note in run logs for audit.

## Recently completed (2026-05-07)

- Autonomous-only architecture: single workflow, three modes, all legacy crons deleted
- Sonnet 4.6 for agent + carousel slide writing; Haiku 4.5 for repair / image-pick / hashtags / search-query expansion
- YouTube cross-post: same MP4 → Shorts, same caption + `#Shorts`, custom thumbnail (channel: `thefactjot@gmail.com`)
- v2 brand: Archivo Black 900 added for caption / video burn-in; new colour tokens (SKY, AVAILABLE, surface set, brand gradient)
- Reel thumbnail variant E (radial focus, 4:5 safe area)
- Wordmark unified across every template (canonical inline `fact[normal] jot[italic] .[red]`)
- All carousel headlines (slide / closing / list_*) switched to Archivo Black 900
- R3 image fallback now routes through stock-friendly providers (`pexels, pixabay, smithsonian, commons`) so abstract editorial subjects get B-roll instead of typography-only
- Carousel story `NEW POST` text replaced with a small accent pill matching reel story
- Live-streamed pipeline output in autonomous_agent.py (no more silent hangs)
- Per-run cost capture in `data/ledgers/api_usage_costs.jsonl`

---

## Directory map

```
.github/workflows/  autonomous-reel.yml (the only poster), pages.yml (docs)
scripts/            autonomous_agent.py (Sonnet agent loop)
                    upload_to_youtube.py + setup_youtube_auth.py
                    legacy: check_*, log_*, ship_*, make_*
src/research/       image_sourcer.py + image_fetcher.py (carousel image pipeline,
                    R3 fallback uses stock-friendly provider order)
                    rare_fact_bank.py (DORMANT in autonomous flow; lazy-imported
                    by make_reel.py only on legacy CLI paths)
src/content/        Script, title, caption generators
src/render/         Playwright renderers, FFmpeg composer, thumbnail, story
                    Templates updated to v2 (Archivo Black headlines, unified
                    wordmark, variant E thumbnail, stripped reel story)
src/publish/        Instagram Graph API, image hosting
src/core/           Brand (v2.0), paths, config, models
assets/fonts/       Brand fonts. Four primaries:
                    InstrumentSerif-{Regular,Italic}.ttf
                    SpaceGrotesk-{SemiBold,Medium,Regular,Variable}.ttf
                    JetBrainsMono-{Bold,Regular}.ttf
                    ArchivoBlack-Regular.ttf (v2, video burn-in only)
assets/music/       default.mp3 + topic / mood stems for _pick_music(topic, tone)
assets/intros/      factjot_intro.mov - ProRes 4444 alpha intro overlay
assets/video/       Safety footage pool (fallback)
output/             Pipeline build artefacts (gitignored). Per-pipeline subdirs:
                      reel/      reel build outputs (final.mp4, thumbnail, story, footage)
                      carousel/  morning carousel slides (legacy)
                      list/      list carousel slides (legacy)
                      news/      news carousel previews (legacy)
                      manual/    autonomous editorial carousel slides (current)
data/ledgers/       Append-only records:
                      used_footage_urls.jsonl  reel footage dedup
                      used_images.jsonl        carousel image dedup
                      api_usage_costs.jsonl    per-run Anthropic + ElevenLabs cost
                      reel_performance.jsonl   IG insights (mutable)
                      youtube_uploads.jsonl    YouTube cross-post audit + dedup
                      discovered_facts.jsonl   legacy Reddit-discovered candidates
insta-brain/        Brain + dedup ledgers (posted.jsonl, reels.jsonl, list_posts.jsonl,
                    posted_quotes.jsonl, log.md, MEMORY_INDEX.md)
brand/              brand_kit.json (v2.0, locked) + style-guide-v2.pdf (gitignored)
docs/               Static pages built by pages.yml
```

