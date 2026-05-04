# factjot — agent operating manual

Owner: **Toby Johnson (TJCreate)**, Lincoln UK. Instagram: @factjot.
Before anything else, read `/Users/Music/.claude/CLAUDE.md` for Toby's universal rules (no em dashes, British English, voice, etc).

---

## What this project is

Fully automated Instagram account posting:
- **2 carousel posts/day** — morning (10:00 BST) + evening (18:00 BST)
- **1 Reel/day** — midday (12:00 BST), with composite thumbnail + story posted automatically after

Stack: Python 3.11, Playwright + Chromium (HTML rendering), FFmpeg (Reels), ElevenLabs (voice, paid), Instagram Graph API, imgbb + tmpfiles.org (video hosting).

**The Mac does not need to be on.** GitHub Actions handles all posting 24/7.

---

## Canonical Python path

For **local runs** on Toby's Mac:
```
/Library/Frameworks/Python.framework/Versions/Current/bin/python3
```
Never bare `python3` locally — packages will not be found.

In **GitHub Actions**, bare `python3` is correct (pip installs to the runner's system Python).

---

## Daily automation — GitHub Actions + cron-job.org

**All launchd jobs are DISABLED.** GitHub Actions is the sole scheduler. Do not re-enable launchd without disabling the workflows first or double-posts will occur.

### Posting schedule (BST = UTC+1)

| Workflow | BST | UTC | Triggers |
|---|---|---|---|
| `carousel-morning.yml` | 10:00 | 09:00 | `ship_first_post.py --topic X` |
| `reel.yml` | 12:00 | 11:00 | `make_reel.py` |
| `list-carousel.yml` | 18:00 | 17:00 | `ship_list_post.py --next` |

### How it fires

1. **cron-job.org** (primary, reliable) hits GitHub dispatch API at exactly 09:00/11:00/17:00 UTC
2. **GitHub's built-in crons** fire at the same times as backups (unreliable, often delayed)
3. **Backup crons** at +45 min (09:45/11:45/17:45 UTC) catch any GitHub cron delay
4. Idempotency check with `git pull` before posting prevents duplicates even if both trigger simultaneously

### cron-job.org job IDs

| Job ID | Time (UTC) | Workflow |
|---|---|---|
| 7555728 | 09:00 | carousel-morning.yml |
| 7555730 | 11:00 | reel.yml |
| 7555733 | 17:00 | list-carousel.yml |

API key stored in cron-job.org account. GitHub PAT stored as `CRON_TRIGGER_PAT` secret in the repo.

### Every workflow run does

1. Checkout (full history — needed for rebase)
2. Set up Python 3.11 + pip cache
3. Install FFmpeg (reel.yml only, via `FedericoCarboni/setup-ffmpeg@v3`)
4. Cache/install Playwright + Chromium
5. Write `.env` from GitHub secrets
6. Verify Meta token (`scripts/check_token.py` — exits 1 and logs alert if invalid)
7. `git pull --rebase --autostash` then idempotency check (`scripts/check_posted_today.py`)
8. Post content (skipped if already posted today)
9. Capture failure to brain log if any step failed (`scripts/log_workflow_failure.py`)
10. Commit and push state (`insta-brain/data/`, `data/ledgers/`) — always runs

### Concurrency

All 3 posting workflows share `concurrency.group: factjot-publish`. If two triggers overlap, the second queues (never cancels). This prevents git push conflicts and stale ledger reads.

---

## Reel pipeline — full flow

```
make_reel.py
  pick fact        → quirky_score=3 (fallback q2 when q3 exhausted), unused, sensitivity-safe
  build VO script  → curated reel_script field REQUIRED (>=70 words); no auto-fallback
  ElevenLabs TTS   → word-level beat timestamps (edge-tts fallback if key missing)
  find 8 clips     → Pexels → Coverr → Pixabay → Wikimedia (all anchored to image_hint)
  render overlays  → Playwright: label bar, hook title, kinetic subtitles, CTA card
  FFmpeg compose   → 8 clips, animated pan-crop, alpha intro, sidechain music, fade-to-black
  thumbnail        → FFmpeg freeze frame at 1.0s + Playwright branded overlay (base64 composited)
  story PNG        → Playwright: "NEW REEL" card with same footage frame behind
  caption          → title + body + CTA + source credits + 3-tier hashtags
  upload MP4       → tmpfiles.org (1-hr URL, Meta fetches within polling window) [PRIMARY]
  upload thumbnail → imgbb → passed as cover_url to Instagram
  publish_reel()   → Reel live on feed with branded thumbnail
  post_to_stories()→ Story fires immediately after
  ledger           → insta-brain/data/reels.jsonl + data/ledgers/used_footage_urls.jsonl
```

**Video size limit:** Meta's URL downloader rejects files over ~5MB. Encode at crf 30, maxrate 800k. Adaptive retry: if 413, recompress at crf 33 + maxrate 600k and retry once.

**Cloudinary is DISABLED as primary** (Meta 413'd it 2026-05-02 because URLs don't expire before Meta fetches). Could re-enable if needed for non-expiring URLs, but tmpfiles works fine within the polling window.

**Global footage dedup:** `data/ledgers/used_footage_urls.jsonl` tracks all video URLs ever used. Same video never appears in two different reels.

**Run commands (local, Mac):**
```bash
cd /Users/Music/Developer/Insta-bot
# If `ffmpeg -h filter=ass` fails, install libass-capable FFmpeg (e.g. brew ffmpeg-full) then:
# export FFMPEG_BIN="$(brew --prefix ffmpeg-full)/bin/ffmpeg"
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 scripts/make_reel.py
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 scripts/make_reel.py --dry-run
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 scripts/make_reel.py --topic earth
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 scripts/make_reel.py --list-facts
```

**Local notes:** only one **`make_reel.py`** at a time (lock, exit **10** if contested). Per-run logs: **`data/cache/reels/<id>/pipeline.log`** and **`logs/reel_runs/`**; compose stderr: **`ffmpeg_compose_stderr.log`** in the same cache dir. If a run is killed, remove a stale **`.make_reel.lock`** if it remains. Prefer **`reel.yml`** on GitHub for a full encode when the Mac graph runs at fractional real-time speed.

---

## Key source files

| File | Purpose |
|---|---|
| `scripts/make_reel.py` | Main Reel pipeline entry point |
| `scripts/kill_local_reel_jobs.sh` | Stops this repo's `make_reel.py` + FFmpeg jobs using `factjot_intro.mov` |
| `src/utils/reel_run_logger.py` | `ReelRunLogger`: `pipeline.log` + `logs/reel_runs/` copies |
| `scripts/ship_first_post.py` | Morning carousel (topic-based, quirky_score >= 2 floor) |
| `scripts/ship_list_post.py` | Evening list carousel (cache-first, then TMDB fallback) |
| `scripts/prepare_packs.py` | Sunday: pre-resolves all unposted list packs, writes cache |
| `scripts/restock.py` | Sunday: fact discovery + runway report across all content types |
| `scripts/refresh_token.py` | Refreshes Meta 60-day access token |
| `scripts/check_posted_today.py` | Idempotency guard — exits 1 if already posted today |
| `scripts/check_token.py` | Verifies Meta token; prints `ok` or `invalid` |
| `scripts/check_reel_runway.py` | Counts unposted q2+q3 facts with reel fields for runway |
| `scripts/discover_facts.py` | Discovers facts from Reddit TIL; scores 0-3; rejects boring |
| `scripts/log_workflow_failure.py` | Writes failure entry to brain log on workflow error |
| `scripts/log_token_alert.py` | Writes token-expired alert to brain log |
| `src/content/pack_resolver.py` | Shared TMDB resolution for list packs (used by both ship_list_post + prepare_packs) |
| `src/research/rare_fact_bank.py` | Curated facts — source of truth |
| `src/research/narrative_beats.py` | 5 footage queries derived from `image_hint` |
| `src/research/video_finder.py` | Multi-source footage finder with relevance scoring |
| `src/content/reel_script.py` | Formats claim into dramatic VO (narrative build + ellipses) |
| `src/content/reel_title.py` | Documentary-style title generator |
| `src/content/reel_caption.py` | Caption: title + body + CTA + source credits + 3-tier hashtags |
| `src/render/tts_engine.py` | ElevenLabs primary, edge-tts fallback — returns word beats |
| `src/render/reel_composer.py` | FFmpeg composition — constants, timing, filter graph builder |
| `src/render/reel_text_renderer.py` | Playwright overlay renderer (all overlay PNGs) |
| `src/render/reel_thumbnail.py` | Footage frame base64 + branded overlay composite |
| `src/render/reel_story.py` | Story PNG renderer (same footage frame + story card) |
| `src/render/templates/reel_text_frame.html.j2` | Reel overlay template |
| `src/render/templates/reel_thumbnail.html.j2` | Thumbnail template |
| `src/render/templates/reel_story.html.j2` | Story template |
| `src/publish/instagram_publisher.py` | `publish_reel()` + `post_to_stories()` |
| `src/publish/image_host.py` | imgbb + tmpfiles with PNG salting for fresh URLs |
| `src/core/brand.py` | Brand constants — fonts, colours, dimensions |
| `src/core/paths.py` | All file paths — single source of truth |
| `src/core/ffmpeg_bin.py` | `FFMPEG_BIN` + startup check that `ass` filter exists (local Mac vs CI) |

---

## Fact bank

- **152 total facts** across space, earth, ocean, biology, history, technology
- **~43 quirky_score=3** (shock/viral tier — the only ones used for Reels by default)
- All q3 facts **must** have curated `reel_script` (>=70 words) and `reel_title` — hard gate enforced
- `allow_archival=True` set on facts where low-quality archival footage is appropriate (Voynich Manuscript, First Photograph)
- `discover_facts.py` requires MIN_UPVOTES=10,000. Scores: 10k-15k=1, 15k-30k=2, 30k+=3. Viral signal words give +1 bonus. Generic openers with no specificity signals score 0 (rejected, never written to bank).

**Runway rule:** keep at least 14 unused q3 facts (2 weeks buffer). Reel workflow checks runway before posting — if below 14, runs `discover_facts.py` automatically. Run `scripts/check_reel_runway.py` to see current count.

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

## Footage quality rules

**Source priority (Tier 0 runs first):**
1. **Wikipedia lead image** — fetches the actual article image for the named entity (no auth)
2. **Wikimedia Commons** — entity-name search, video preferred over stills, rights-cleared only
3. **Internet Archive** — exact-phrase entity search, scored by relevance
4. **Pexels / Coverr / Pixabay** — B-roll fill from `image_hint`-derived queries

Tier 0 fills the first 1-2 clip slots with fact-specific content. B-roll fills the rest.

**Quality floors (do not lower):**
- Non-archival: 2MB minimum file size, 4s minimum duration (probed via ffprobe)
- Archival (`allow_archival=True`): 50KB minimum, all sources enabled
- NSFW block: filenames/descriptions containing "nsfw", "explicit", "nude", "porn", etc. are skipped

**Dedup:**
- `used_source_urls` set prevents same video appearing twice within a single Reel
- `data/ledgers/used_footage_urls.jsonl` (git-tracked) prevents same video across different Reels
- Pexels fetches 15 results per query to allow deduplication to find alternatives

---

## Reel timing constants

| Constant | Value | Meaning |
|---|---|---|
| `INTRO_S` | 3.5s | Silent window — hook title visible, voice starts after |
| `MUSIC_VOLUME` | 0.24 | Background music (sidechain-ducked under voice) |
| `FADE_TO_BLACK_S` | 1.5s | Final fade duration |
| `KEN_BURNS_ZOOM` | 0.10 | 10% overscan — subtle pan, not shaky |
| CTA timing | dynamic | Card appears when narrator says "factjot" (word-beat sync) |
| Total duration | `voice_end + 0.8 + 1.5s` | Tight — no dead air after voice |
| FFmpeg crf | 30 | Quality/size balance — keeps output under ~5MB for Meta |
| FFmpeg audio | 48kHz, 128k | Meta requires 48kHz (not 44.1k, not 96k) |

---

## Reel thumbnail design

`factjot.` top-left (Instrument Serif 30px) · `TOPIC` top-right (JetBrains Mono 22px)

- No separator line in header — wordmark and topic sit directly at top edges
- Title centred vertically (Instrument Serif, ~108px, last word italicised)
- Corner brackets: L-shaped viewfinder lines at all 4 corners, 56px arms, off-white 65% opacity
- Left accent line: full height, red → lime gradient, 4px, 80% opacity
- Title scrim: radial dark ellipse behind title area so footage never fights the text
- Template: `src/render/templates/reel_thumbnail.html.j2`

**Carousel slides** use a full-width header bar:
`factjot. [────────────────────] TOPIC/INDEX`

Position: `top: 56px; left: 72px; right: 72px` (see `src/render/templates/slide.html.j2`)

---

## Typography — strict brand rule

| Font | Use | File |
|---|---|---|
| Instrument Serif Regular + Italic | Hook titles, wordmark, title cards | `assets/fonts/InstrumentSerif-*.ttf` |
| Space Grotesk SemiBold 600 | Subtitles, body text | `assets/fonts/SpaceGrotesk-SemiBold.ttf` |
| JetBrains Mono Bold 700 | Labels, badges, tags | `assets/fonts/JetBrainsMono-Bold.ttf` |

Wordmark: `fact`*`jot`*`.` — "jot" italic, "." in `#E6352A`, base off-white `#EDE8DD`.
Brand colours: PAPER `#F4F1E9` INK `#0A0A0A` ACCENT `#E6352A` LIME `#C8DB45` LILAC `#C4A9D0`.
Shadow style: hard drop `2px 2px 0 rgba(0,0,0,0.5)` — matches carousels, no blur.

---

## API keys (all in `.env` locally; GitHub secrets in Actions)

| Key | Service | Notes |
|---|---|---|
| `META_ACCESS_TOKEN` | Instagram Graph API | 60-day rolling. Refresh weekly via `refresh_token.py`. |
| `META_APP_ID` | Meta app identifier | factjot-publisher app. Used by token refresh flow. |
| `META_APP_SECRET` | Meta app secret | Required to long-lived-token-exchange. |
| `META_GRAPH_VERSION` | Graph API version | e.g. `v25.0`. Pinned in workflow secrets. |
| `META_GRAPH_HOST` | Graph API host | `graph.facebook.com` |
| `META_LOGIN_FLOW` | Token refresh login flow | Used by Sunday weekly-plan token refresh. |
| `INSTAGRAM_ACCOUNT_ID` | IG business account id | The numeric id of @factjot. |
| `FACEBOOK_PAGE_ID` | Facebook page id | Linked page id for the IG account. |
| `ELEVENLABS_API_KEY` | Voice | Paid. ~500 chars/reel. |
| `ELEVENLABS_VOICE` | ElevenLabs voice id | Default `3WqHLnw80rOZqJzW9YRB`. |
| `PEXELS_API_KEY` | Primary footage | Free, 200 req/hr |
| `COVERR_API_KEY` | Secondary footage | Demo, 1,000 calls/month |
| `PIXABAY_API_KEY` | Tertiary footage | Free |
| `IMGBB_API_KEY` | Thumbnail + story + carousel image hosting | Free |
| `IMAGE_HOST` | Image-host backend selector | `imgbb` (default) or `cloudinary,imgbb,tmpfiles` for fallback chain |
| `CLOUDINARY_*` | Video hosting (disabled) | cloud=dmzer6hgv, preset=factjot. Kept in secrets, not used. |
| `TMDB_API_KEY` | TMDB v3 API key | Used by list pack TMDB resolver. |
| `TMDB_READ_TOKEN` | TMDB v4 read token | Used by some TMDB endpoints. |
| `OMDB_API_KEY` | OMDB fallback for film metadata | Used when TMDB lacks a field. |
| `CRON_TRIGGER_PAT` | GitHub fine-grained PAT | cron-job.org uses this to dispatch workflows via GitHub API |
| `MUSIC_CREDIT` | Caption credit line | Set to "Track · Artist" for background music |

**Token failure:** if `refresh_token.py` returns "API access blocked", the account was rate-limited by rapid API calls. Wait 30 min, then retry. If still blocked, regenerate via `setup_token.py` with a fresh short-lived token from developers.facebook.com → factjot app → Instagram → API Setup.

**If cron-job.org jobs stop firing:** log in at cron-job.org, check job status. If PAT expired, create a new fine-grained PAT (repo scope, Actions read/write), update `CRON_TRIGGER_PAT` secret, and PATCH the cron-job.org jobs with the new token in their `extendedData.headers`.

---

## Caption structure

Every Reel caption:
```
[Title or first sentence of claim]
[1 punchy sentence — the most striking detail]

[Randomised CTA — "Follow @factjot..."]

[Source credits]
[Footage credit]
[Music credit if set]

[3-tier hashtags: broad + topic + subject-specific]
```

Hashtags are 3-tier: 5 broad (`#facts #didyouknow`) + 5 topic (`#earthscience`) + 5 subject-specific extracted from the claim/title (`#supervolcano #humanevolution`).

---

## YAML rules for GitHub Actions workflows

GitHub uses a Go YAML parser (stricter than Python's PyYAML):
- **No em dashes** in comments or strings — Go parser rejects UTF-8 `—`. Use hyphens.
- **No multiline Python heredocs** inside `run: |` blocks — extract to dedicated scripts.
- If a workflow fails to dispatch with 422 "no workflow_dispatch trigger", the YAML is broken. Fix the YAML, push, then retry.

---

## Fix philosophy — mandatory for every agent

Every fix must be a long-term structural fix, not a temporary patch. A patch that suppresses a symptom without removing its root cause will reappear in a different form or a different part of the pipeline. Before shipping any fix, ask: does this eliminate the cause, or does it hide it? If it hides it, keep digging. No half-measures.

## Gotchas

`insta-brain/gotchas.md` — read this before touching anything. It documents everything that has broken, been tried, and failed. Keep it current. If you hit a new wall, add it before closing the session.

**Obsidian:** open the `insta-brain/` folder as a vault (or use the repo’s brain notes there). Hub notes use wikilinks so **[[gotchas]]** appears in the graph: start from **[[MEMORY_INDEX]]** in the same vault, or link **[[gotchas]]** from any note you edit. Plain paths alone do not create graph edges.

---

## Invariants — never break

1. Never repost a fact — check `insta-brain/data/posted.jsonl`.
2. Never reuse a carousel image — check `data/ledgers/used_images.jsonl`.
3. Every fact must be 100% true — 2+ reputable sources, confidence >= 0.65.
4. No em dashes — anywhere, ever. Including YAML workflow comments.
5. British English throughout all copy.
6. Append-only ledgers — never edit historical lines.
7. Three fonts only — brand-locked.
8. Reels use `quirky_score=3` facts only (fallback to q2 only when q3 exhausted).
9. All q3 facts must have curated `reel_script` (>=70 words) and `reel_title`.
10. Always use the full Python path for local runs. Bare `python3` only in GitHub Actions.
11. `--dry-run` first if you're unsure — it generates all assets without posting.
12. Audio must be 48kHz — Meta rejects 44.1kHz and 96kHz.

---

## Debugging workflow failures

1. Go to github.com/Wonderkid96/factjot → Actions tab
2. Find the failed run, read the step logs
3. Common causes: Meta token expired (`check_token.py` step fails), YAML parse error (422 on dispatch), git push conflict (rebase step fails), Meta 413 (video too large)
4. If token expired: run `refresh_token.py` locally, update `META_ACCESS_TOKEN` secret
5. Do not run scripts locally while Actions is active — race condition on ledger files

---

## What is NOT yet done

- Stories on carousel posts — carousels don't post a story after publishing; only reels do
- Carousel story images — no template exists for carousel story cards
- TikTok integration — app submitted for review 2026-05-02; not yet wired into pipeline
- Meta System User token — current token is 60-day rolling; switching to System User would make it permanent (requires manual setup in Meta Business Manager)

---

## Directory map

```
.github/workflows/  carousel-morning.yml, reel.yml, list-carousel.yml
scripts/            Entry points + utility scripts (check_*, log_*, ship_*, make_*)
src/research/       Fact bank, video finder, narrative beats, sensitivity guide
src/content/        Script, title, caption generators
src/render/         Playwright renderers, FFmpeg composer, thumbnail, story
src/publish/        Instagram Graph API, image hosting
src/core/           Brand, paths, config, models
assets/fonts/       Brand fonts
assets/music/       default.mp3 — Reel background music
assets/intros/      factjot_intro.mov — ProRes 4444 alpha intro overlay
assets/video/       Safety footage pool (fallback)
data/cache/reels/   Per-reel output — final.mp4, thumbnail.png, story.png, footage
data/ledgers/       Append-only records (used_footage_urls.jsonl, used_images.jsonl, etc.)
insta-brain/        Brain + ledgers (posted.jsonl, reels.jsonl, queue.jsonl)
logs/               Job stdout/stderr (GitHub Actions logs are in the GitHub UI, not stored locally)
config/             pipeline.yaml — schedule, thresholds, settings
brand/              brand_kit.json (locked)
```
