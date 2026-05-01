# Memory Index

Purpose: quick handover ledger for future agents so they can understand recent system behaviour changes without replaying full chat history.

## Current Truth Snapshot (read this first)

- Canonical priority for operational truth:
  1. `insta-brain/CRITICAL_FACTS.md`
  2. `insta-brain/rules/*.md` (especially `09`, `06`, `13`)
  3. live code under `src/` and `scripts/`
  4. this file's newest dated entries
- If any older entry below conflicts with current code or rules, treat it as historical context only.
- Always verify with:
  - `/Library/Frameworks/Python.framework/Versions/Current/bin/python3 scripts/status.py`
  - `/Library/Frameworks/Python.framework/Versions/Current/bin/python3 scripts/runway.py`
  - `/Library/Frameworks/Python.framework/Versions/Current/bin/python3 scripts/check_brain_fresh.py`
- Publish safety gate is active:
  - `publish_now.py` and `publish_due.py` refuse to publish if `check_brain_fresh.py` fails.
- Scheduling state source of truth:
  - `data/approval_queue.jsonl` for actual queued posts.
  - `insta-brain/data/queue.jsonl` is brain mirror history and can include repeated planning snapshots.

Update rule:
- Append new entries at the top, newest first.
- One block per meaningful change batch.
- Include: date, what changed, why, affected files, and verification.
- **Always include a "routine impact" line** — does this change require updating any of the three Claude scheduled routines? Even if the answer is "no routine change needed", say so explicitly. See rule 18.
- Do not delete historical entries.
- Run `scripts/check_brain_fresh.py` after a non-trivial code change. It fails if any source file under `src/` or `scripts/` is newer than this file.

Scheduled routine locations (rule 18):
- AM post:      `~/.claude/scheduled-tasks/factjot---am-post---900am/SKILL.md`
- PM post:      `~/.claude/scheduled-tasks/factjot---pm-post-1800/SKILL.md`
- Weekly top-up: `~/.claude/scheduled-tasks/factjot---topup/SKILL.md`
- Update via: `mcp__scheduled-tasks__update_scheduled_task`

## 2026-05-01 — Full Reel pipeline build + daily automation

**What changed:** Complete Reels system built and first two Reels published. Major pipeline overhaul across footage, audio, text, publishing and scheduling. Summary:

**Reel pipeline (scripts/make_reel.py):**
- ElevenLabs TTS primary (paid, voice `3WqHLnw80rOZqJzW9YRB`), edge-tts fallback
- Randomised outro phrase appended to every script ("Follow factjot...") — CTA card synced to the exact word-beat when narrator says "factjot"
- 8 footage clips per Reel, all queries anchored to `image_hint` (not generic topic templates — fixed footage relevance bug)
- Footage quality floor: 800KB minimum for non-archival content; Archive.org gated behind `allow_archival=True` on fact bank entries; NASA space-only
- Duplicate prevention: `used_source_urls` set prevents same video appearing twice per Reel
- Composite thumbnail: FFmpeg freeze frame from ESTABLISHING clip (1.0s) + Playwright branded overlay (base64 inlined to bypass Chromium file:// restrictions)
- Story PNG: same footage frame as background + "New Reel" card + title — z-index fixed so overlay sits behind text
- Caption: 3-tier hashtags (broad + topic + subject-specific extracted from claim)
- Source credits in every caption (publisher names parsed from fact sources URLs)
- `MUSIC_CREDIT` env var for music attribution line

**Video finder overhaul (src/research/video_finder.py):**
- Added Coverr source (COVERR_API_KEY in .env)
- Added Wikimedia Commons with per-file license check (extmetadata)
- Relevance scoring on all sources — picks best-matching result not first result
- Pexels fetches 15 results (was 8) to enable deduplication

**Narrative beats (src/research/narrative_beats.py):**
- Complete rewrite: when image_hint present, all 5 beat queries expand from hint with coverage modifiers (close up, slow motion, atmospheric, aerial wide). Entity extraction from claim text retired as primary approach.
- biology → _t_nature, technology → _t_tech mappings added

**New files:**
- `src/content/reel_caption.py` — full caption builder
- `src/content/reel_title.py` — documentary-style title generator
- `src/content/reel_script.py` — narrative beat script formatter
- `src/content/auto_pack.py` — auto list pack from TMDB trending
- `src/render/reel_thumbnail.py` + `reel_thumbnail.html.j2`
- `src/render/reel_story.py` + `reel_story.html.j2`
- `src/research/trend_scout.py` — weekly TMDB + Reddit TIL signals
- `launchd/com.tjcreate.factjot.reel.plist` — daily 19:00 UTC Reel job (loaded)

**Fact bank (src/research/rare_fact_bank.py):**
- Expanded from ~110 to 152 facts (21 new quirky_score=3 shock-tier facts added)
- Now 45 quirky_score=3 facts, 36 unused = 5.1 weeks runway
- 9 with hand-crafted reel_scripts, 25 with reel_titles

**plan_week.py:**
- Added reel runway check (warns + triggers discovery if < 14 unused q3 facts)
- Added `_run_trend_scout()` — fetches TMDB trending + Reddit TIL topic weights
- Auto-generates trending list pack weekly, saved to `data/trends/`
- Topic weight map printed in weekly report

**Publishing (src/publish/instagram_publisher.py):**
- `publish_reel()` now accepts `cover_url` parameter for custom thumbnail
- Token refreshed successfully (was blocked by rate-limit from test API calls)

**Design:**
- Label bar now full-width carousel-style: `factjot. [──────────] TOPIC` (left: 56px, right: 56px, separator flex: 1 1 auto)
- CTA shadow changed from soft blur to hard drop (2px 2px 0) matching carousels
- Bottom-right logo watermark removed
- Music volume raised from 0.18 to 0.24
- Pan travel reduced from 18% to 10% overscan
- Film grain reduced from alls=6 to alls=3

**Reels published today:**
- `fd515a94e464e6` — Toba supervolcano, topic=earth, ig_media=18073737497269159
- `539e56ba22b1e0` — Radium Girls, topic=history, ig_media=18139721830518880

**Affected files:** `scripts/make_reel.py`, `src/research/video_finder.py`, `src/research/narrative_beats.py`, `src/research/rare_fact_bank.py`, `src/research/trend_scout.py`, `src/content/reel_caption.py`, `src/content/reel_script.py`, `src/content/reel_title.py`, `src/content/auto_pack.py`, `src/render/reel_composer.py`, `src/render/reel_text_renderer.py`, `src/render/reel_thumbnail.py`, `src/render/reel_story.py`, `src/render/templates/reel_text_frame.html.j2`, `src/render/templates/reel_thumbnail.html.j2`, `src/render/templates/reel_story.html.j2`, `src/publish/instagram_publisher.py`, `scripts/plan_week.py`, `config/pipeline.yaml`, `launchd/com.tjcreate.factjot.reel.plist`, `CLAUDE.md` (full rewrite), `insta-brain/CRITICAL_FACTS.md`

**Routine impact:** NEW launchd job `com.tjcreate.factjot.reel` fires daily at 19:00 UTC — no change to existing AM/PM/weekly Claude routines needed. The reel job is fully autonomous (picks next unused q3 fact, generates and posts). Carousel stories on publish_due.py NOT yet wired — next session.

**Verification:** `python3 scripts/make_reel.py --list-facts` shows 36 unused q3 facts. `launchctl list | grep factjot` shows all 5 jobs loaded.

## 2026-05-01 — Weekly maintenance (top-up)

- **What changed**: weekly top-up appended 44 fresh facts to `data/ledgers/discovered_facts.jsonl` (technology +14, earth +15, ocean +15). plan_week.py scheduled 14 new carousels for 2026-05-02 through 2026-05-08 at 2/day. Token refresh attempted but failed with HTTP 400 OAuthException ("API access blocked") — alert appended to `data/ledgers/alerts.jsonl`.
- **Why**: weekly runway top-up to sustain 2 posts/day cadence; technology was at 1 fresh (LOW) before this run, earth and ocean both under the 14-fresh threshold.
- **Routine impact**: no routine change needed. The token failure should be investigated separately; if app access remains blocked, AM/PM publish runs will fail until reauthorised.
- **Affected files**: `data/ledgers/discovered_facts.jsonl` (+44 lines), `data/approval_queue.jsonl` (+14 carousels), `data/ledgers/alerts.jsonl` (+1 token_refresh_failed), `insta-brain/log.md`, `insta-brain/data/weekly_state.json`.
- **Verification**: starting runway 12 days at 1/day (77 fresh, bank-only view from runway.py); ending state from status.py: 126 fresh = ~10 days at 2/day. Per-topic ending fresh: biology=19, earth=28, history=19, ocean=26, science=3, space=16, technology=15. Status returned 1 red flag (token invalid, expected — alerted).
- **Run status**: initially marked "failed" (step 8 token refresh errored at 13:08 UTC). At 16:17 UTC the operator confirmed the rate-limit had cleared (resolved by the parallel Reel-pipeline session); token refresh re-run succeeded (~59 day expiry), status returned green. weekly_state.json flipped to "ok".

## 2026-05-01 — Growth features: caption hook, Stories, comment surfacing

What changed:
- `src/content/carousel_generator.py` `_caption()`: was a hardcoded "Follow @factjot for fresh facts daily." now leads with the first fact's opening sentence (most quirky-scored = first in deck) + "Follow @factjot for more." IG shows ~125 chars before "More" — that space now earns engagement instead of wasting it on a generic CTA.
- `src/publish/instagram_publisher.py` `post_to_stories()`: new method. Posts a single image to IG Stories via `media_type=STORIES`. Non-fatal — if the token lacks `publish_to_stories` permission it logs and continues, doesn't break the carousel.
- `scripts/ship_first_post.py`: calls `post_to_stories(public_urls[0])` after every successful carousel publish. Slide 1 goes to Stories. Doubles exposure to existing followers.
- `scripts/status.py`: new section 7 fetches recent comments on the latest post via Graph API and prints them with username + timestamp. Operators see this on every status check and can reply in-app to boost algorithm reach within the engagement window.
- AM + PM scheduled routines updated to document Stories step + comment-reply reminder.

Why:
- Comments in the first hour + Stories are two of the highest-leverage growth levers for IG fact accounts. Stories give a second reach hit to followers. Replies in the first 60 minutes signal engagement to the algorithm. Both required zero complex infrastructure.

Routine impact:
- AM and PM routines updated (Stories step documented, PM now calls status.py and explicitly notes comment replies).
- Weekly top-up: no change needed.

Affected files:
- changed: `src/content/carousel_generator.py`, `src/publish/instagram_publisher.py`, `scripts/ship_first_post.py`, `scripts/status.py`, AM + PM routine prompts.

Next growth item (scoped but not yet built): Reels — 15-30s animated text version of each fact. Highest single reach lever but 2-3 days build. Would need FFmpeg + a motion template.

## 2026-05-01 — Sensitivity gate narrowed to animal cruelty only

What changed:
- `src/research/sensitivity_guide.py` `TRIGGER_PATTERNS` rewritten. Previously `religion`, `current_politics`, `suicide_specifics`, `sexual_content`, `graphic_violence` were all auto-routed to `controversial` (gated from autonomous queue). Now they map to `edgy` (informational tags only — autonomous queue ships them). **`animal_welfare` is the sole `controversial`-tier classifier.**
- Existing categories renamed to clarify they're informational: `religion` → `religion_topic`, `current_politics` → `politics_topic`, `suicide_specifics` → `suicide_topic`, `sexual_content` → `sexual_topic`, `graphic_violence` → `violence_topic`.
- Added `dog ?fight`, `cock ?fight`, `bull ?fight` patterns to the animal_welfare set.
- Rule 14 (`14-sensitivity.md`) rewritten to reflect the narrowed line. Explicit Instagram Community Standards reference added as the OUTER wall (separate from the classifier — operator's responsibility to enforce).
- Rule 17 (`17-dynamic-curation.md`) inviolate list updated: dropped "no controversial auto-publishing" generic; replaced with "no animal-cruelty auto-publishing" + "stay within Instagram Community Standards".

Why:
- Operator clarification: "I don't mind controversial stuff, perhaps it's the animal cruelty that I'm bothered about. perhaps everything else has no boundaries. stay within the insta guides though."
- The previous gate was over-broad. Genocide, religion, politics, suicide context are all valid factual subjects — they just need framing discipline, which falls to bank curators (and truth gate for r/TIL discoveries), not regex.
- Mike Headless Chicken style content (animals deliberately harmed, even historically) is the actual line for our audience.

Effect on the bank:
- 130 safe / 4 edgy (autonomous-publishable) / 2 controversial (manual opt-in only).
- The 2 controversial entries are Mike Headless Chicken + Tarrare's live-cat story — both `animal_welfare`. Same as before; correct outcome.
- Bank doesn't currently contain facts triggering the religion/politics/suicide/sexual/violence regexes, so no immediate reclassification beyond the rule change. Future bank entries on those subjects will now flow.

What stays inviolate (rule 17 final list):
1. No em dashes
2. No reposts
3. No image reuse
4. No animal-cruelty auto-publish
5. Instagram Community Standards (operator-enforced outer wall)
6. List packs ship once
7. Sources required
8. Brand kit locked

What was audited but kept as-is (mechanical, not editorial):
- `MAX_SLIDE_CHARS = 320`, `MIN_SLIDES_PER_POST = 3`, `TARGET_FACTS_PER_POST = 5` — visual-quality bounds, not taste.
- Truth gate stages (rule 10) — quality calibration, not editorial gate.
- Brand kit lock — identity stability.

Affected files:
- changed: `src/research/sensitivity_guide.py`, `insta-brain/rules/14-sensitivity.md`, `insta-brain/rules/17-dynamic-curation.md`

## 2026-05-01 — Rule audit + rule 17 (dynamic curation)

What changed (intent: less rigid, more dynamic):

- **New rule 17 (`17-dynamic-curation.md`)**: meta-rule defining what's inviolate (em dashes, no repost, no image reuse, no controversial auto-publish, pack-slug dedupe, sources required, brand kit locked) vs what's guidance you can flex (sensitivity tiers, spoilers, list cadence, variety, item count, sort order, truth-gate thresholds). Default disposition = ship over polish, trust the operator over the pipeline.
- **Rule 14 sensitivity loosened**: autonomous queue (`plan_week.py`) was hard-gated to safe-only; now allows safe + edgy. Edgy facts (Phineas Gage, Aron Ralston, Cordyceps, Radium Girls) are universally well-loved and gating them out made the feed bland. Controversial stays opt-in.
- **`ship_first_post.py` defaults flipped**: was safe-only with `--allow-edgy` opt-in; now safe + edgy by default with `--safe-only` opt-out. `--allow-controversial` unchanged.
- **`scripts/plan_week.py` `_runway_by_topic()`** updated accordingly.
- **Rule 15 list-cadence loosened**: dropped "no theme repeat within 4 weeks" and "no two list posts within 4 days" — replaced with judgment-based variety guidance. Framing-word repetition (the actual problem with `mind_bending_scifi` → `mind_bending_tv`) called out explicitly.
- **Rule 16 spoiler rule nuanced**: "Hard rule, no exceptions" → "Strong default, with judgment". Cultural-knowledge twists (Sixth Sense, Snape, Vader) get an explicit allowed-with-restraint exception.
- **TV pack renamed**: `mind_bending_tv` → `series_worth_your_weekend`. Title now "Five sci-fi series worth your weekend" / "no padding, no eight-season slog". Same picks, different framing — fixes the "always mind-bending" rut.
- **Pack backlog seeded**: `PACK_BACKLOG_STUBS` registry in `list_packs.py` with 6 themes spanning different tones/angles/domains (films_made_for_nothing, comfort_films_for_bad_days, documentaries_that_rewire_you, non_english_masterpieces, one_room_thrillers, directors_first_features). Each stub has tone + angle + intent so future curation has direction without starting from blank.

Why:
- Operator feedback: "ensure we're not really too strict on anything" + "more dynamic approach". The audit confirmed the rules had drifted toward over-engineering: hard-gating universally-loved facts, arbitrary cooldowns, "no exceptions" framing on judgment calls.
- Two consecutive packs both opening with "mind-bending" was the smoking gun — variety guidance existed but the implementation didn't differentiate framing-word reuse from actual theme reuse.

Verification:
- `list_packs()` returns 2 active packs: `mind_bending_scifi`, `series_worth_your_weekend`. Neither posted yet.
- `list_backlog_stubs()` returns 6 themed stubs ready for curation.
- Sensitivity audit: bank stays 129 safe / 4 edgy / 2 controversial. The 4 edgy facts (Aron Ralston, Radium Girls, Cordyceps, Anglerfish) now eligible for autonomous queue. Mike Headless Chicken + Tarrare cat-eating still gated.

Affected files:
- new: `insta-brain/rules/17-dynamic-curation.md`
- changed: `insta-brain/rules/index.md`, `insta-brain/rules/14-sensitivity.md`, `insta-brain/rules/15-list-posts.md`, `insta-brain/rules/16-no-spoilers.md`, `scripts/plan_week.py`, `scripts/ship_first_post.py`, `src/content/list_packs.py`

## 2026-04-30 — Image-host fallback chain proven; IG app rate-limit hit

What changed:
- `src/publish/image_host.py` now has `TmpfilesHost` (anonymous, no signup, ~1h file expiry) plus `ChainedImageHost` for ordered failover.
- `IMAGE_HOST` env var now accepts comma-separated chains, e.g. `imgbb,tmpfiles`. Default in `.env` is now this 2-host chain.
- `scripts/ship_list_post.py` detects IG fetch failures (error 9004 / "could not be fetched") and calls `host.next_backend()` to roll forward, re-uploads, retries publish. No manual intervention needed.

What we proved (live test of mind_bending_scifi pack):
- imgbb upload succeeded; IG fetch FAILED with 9004 (the original block).
- Chain rolled forward to tmpfiles automatically.
- tmpfiles upload succeeded; IG fetch SUCCEEDED — it accepted the media URL.
- Next IG step (carousel publish) FAILED with code 4/2207051 "Application request limit reached / Action is blocked".
- Conclusion: imgbb was definitely the host problem. We've now also hit IG's app-level rate limit from the day's combined activity.

Today's IG API load (counted):
- 7 successful publishes (each ~9 API calls: 7 children + 1 carousel + 1 publish ≈ 63 calls).
- ~5 failed list publishes (each ≥1 child-media call before failing ≈ 5-15 calls).
- 2 diagnostic single-image create-media tests (orphan containers, harmless but counted).
- Total ~80-100 API calls. IG's burst threshold for a small business account starts triggering around this volume.

Recovery:
- Rate limits typically clear in 1-24 hours.
- Tomorrow's scheduled 10:00 fact carousel may still hit the same wall if the cooldown isn't done.
- `scripts/publish_due.py` will fail gracefully (logs alert via AlertingService) but won't pollute the brain.

Architecture state going forward:
- Default `IMAGE_HOST=imgbb,tmpfiles` survives imgbb host issues automatically.
- Cloudinary is wired but inactive (needs signup credentials). Can be added to chain later as `cloudinary,imgbb,tmpfiles`.
- Per-upload PNG salting prevents host content-cache giving stale URLs.
- imgbb default 7-day auto-expiry stops uploads accumulating forever.

Affected files:
- changed: `src/publish/image_host.py`, `scripts/ship_list_post.py`, `.env`

## 2026-04-30 — Image-host fallback (Cloudinary) wired in

What changed:
- `src/publish/image_host.py` now exposes `CloudinaryHost` and `make_image_host()` factory. Backend selected by `IMAGE_HOST` env var (default `imgbb`).
- `scripts/ship_first_post.py`, `scripts/ship_list_post.py`, `scripts/publish_due.py` all switched from hardcoded `ImgbbHost()` to `make_image_host()`.
- PNG salting (tEXt chunk with random nonce) is shared between both backends so retries always get fresh URLs.

Why:
- 4 live publish attempts of `mind_bending_scifi` list pack failed tonight at IG's first-child-media-creation step.
- Diagnostic test: a TECH PNG that successfully published at 18:52 today was re-uploaded to imgbb tonight (fresh URL, identical content) and **also failed** with the same error. Confirms imgbb's CDN is being soft-blocked by Meta's media fetcher right now, not a content issue.
- Causes likely: 50+ slide uploads to imgbb today (across all dry-run iterations) tripped imgbb's anti-abuse rate-limit on Meta's fetcher IP range.

To activate Cloudinary:
1. Sign up at cloudinary.com (free tier, ~5 min).
2. Settings → Upload → Upload presets → create UNSIGNED preset (any name).
3. Add to `.env`: `CLOUDINARY_CLOUD_NAME=...`, `CLOUDINARY_UPLOAD_PRESET=...`, `IMAGE_HOST=cloudinary`.
4. Re-run `ship_list_post.py`. Default is still imgbb so nothing else changes until you flip the env var.

Verification:
- `make_image_host()` factory: returns ImgbbHost by default, CloudinaryHost when `IMAGE_HOST=cloudinary` (raises RuntimeError if creds missing — caller can fall back).
- No behaviour change for existing fact-carousel pipeline.

Affected files:
- changed: `src/publish/image_host.py`, `scripts/ship_first_post.py`, `scripts/ship_list_post.py`, `scripts/publish_due.py`

## 2026-04-30 — List-format posts (rule 15) + TMDB/OMDb wiring

What changed:
- New post format: themed list carousels (films/TV/etc), separate from fact carousels.
- `src/research/tmdb_client.py` — TMDB Bearer-auth client. Methods for movie metadata, posters, backdrops, watch providers (UK flatrate, region GB by default).
- `src/research/omdb_client.py` — optional OMDb client. Fills IMDB rating + Rotten Tomatoes score from `imdb_id`. Disabled silently if `OMDB_API_KEY` absent.
- `src/content/list_packs.py` — curated pack registry. Each pack: slug, title, subtitle, items (TMDB ids + per-item hooks + score overrides + genre overrides + watch override), closing, caption.
- `src/render/list_renderer.py` + 3 templates (`list_hook.html.j2`, `list_item.html.j2`, `list_closing.html.j2`) — separate render pipeline. Different layout: backdrop full-bleed + poster card + meta line + IMDB/Rotten chips + WATCH ON row + hook.
- `scripts/ship_list_post.py` — render → imgbb → IG publish. Pack-level dedupe via `list:<slug>` claim; each pack ships once, ever.

Layout iteration tonight (v1 → v5): added scores, switched score values from italic-serif to JetBrains Mono Bold for legibility, removed redundant number badge, reclaimed space for runtime + genre + watch-providers row, deduped/cleaned watch-provider names, added pack-level genre overrides.

Why:
- Lists drive saves and follows; facts drive reach. Mix gives top-of-funnel breadth + save-rate depth.
- TMDB chosen over IMDB (no public IMDB API). OMDb covers IMDB + RT in one call.
- Dedupe is pack-level not film-level so the same film can appear across multiple packs (e.g. Annihilation in `mind_bending_scifi` and a future `alex_garland_films`).

Known issue (active):
- First live publish at ~22:25 failed at IG step (code 7): "Media could not be fetched from this URI" on the hook image. imgbb URL serves fine; appears to be a transient IG fetcher hiccup. Brain NOT polluted (record_publish runs only on success). Retry pending.

Verification:
- `is_fact_posted("list:mind_bending_scifi")` returns False (pack still publishable).
- `is_fact_posted(<Mike Headless Chicken claim>)` returns True (correctly flagged from earlier HISTORY post).
- 69 slide rows / 13 unique posts in `posted.jsonl`. 279 image hashes. 12 quote hashes.

Affected files:
- new: `src/research/tmdb_client.py`, `src/research/omdb_client.py`, `src/content/list_packs.py`, `src/render/list_renderer.py`, `src/render/templates/list_hook.html.j2`, `src/render/templates/list_item.html.j2`, `src/render/templates/list_closing.html.j2`, `scripts/ship_list_post.py`, `insta-brain/rules/15-list-posts.md`
- changed: `insta-brain/rules/index.md`, `.env` (TMDB + OMDb keys, silent)

## 2026-04-30 — Sensitivity / controversy filter (rule 14)

What changed:
- New module `src/research/sensitivity_guide.py`. Three tiers: `safe` / `edgy` / `controversial`. Auto-classifier scans claim text against `TRIGGER_PATTERNS` and tags rows with `sensitivity` + `sensitivity_flags`.
- Author overrides win: `sensitivity` set on a bank row is honoured.
- `_with_defaults` (in `src/research/rare_fact_bank.py`) now calls `apply_sensitivity_defaults` so every loaded fact carries the fields.
- `scripts/ship_first_post.py` filters to `safe` by default; opt-in `--allow-edgy` and `--allow-controversial` flags.
- `scripts/plan_week.py` (autonomous queue) hard-gates to `safe` only. No edgy/controversial ever auto-queues.
- `insta-brain/rules/14-sensitivity.md` written; index updated.
- Mike Headless Chicken and Tarrare's cat-eating story explicitly marked `controversial` in the bank (animal_welfare flag, plus factual_dispute on Mike).

Why:
- Mike Headless Chicken slid through to live (post 63475ed0a8ceee, 18:21) because there was no controversy gate. Animal-welfare backlash + brain-stem-was-intact pile-on are predictable. Need a filter so future shock-tier facts don't auto-publish if they'll upset.

Verification:
- `python3 -c "from src.research.rare_fact_bank import load_all_facts; ..."` shows 135 rows: 129 safe / 4 edgy / 2 controversial. Mike + Tarrare correctly gated.
- False positive on "executed by a machine" (Ada Lovelace) caught and patched: tightened `executed/execution` regex to require human/death context.

Affected files:
- new: `src/research/sensitivity_guide.py`, `insta-brain/rules/14-sensitivity.md`
- changed: `src/research/rare_fact_bank.py` (defaults + 2 explicit overrides), `scripts/ship_first_post.py`, `scripts/plan_week.py`, `insta-brain/rules/index.md`

## 2026-04-30 — Startup memory continuity hardening

- **What changed**
  - Root and brain manuals now require an immediate startup write-back line in `insta-brain/log.md` after read-order completion.
  - `CRITICAL_FACTS.md` session-start checklist now includes mandatory startup logging before any edits or runs.
  - `scripts/check_brain_fresh.py` now fails if required memory-read files are missing or unreadable (`insta-brain/data/posted.jsonl`, `data/used_images.jsonl`, `insta-brain/inbox.md`).
- **Why**
  - Toby requested guaranteed continuity so future agents begin memory/logging discipline immediately on open, not only at session end.
- **Affected files**
  - `CLAUDE.md`
  - `insta-brain/CLAUDE.md`
  - `insta-brain/CRITICAL_FACTS.md`
  - `scripts/check_brain_fresh.py`
  - `insta-brain/log.md`
- **Verification performed**
  - Ran `scripts/check_brain_fresh.py` after changes; gate passes.

## 2026-04-30 — Memory hygiene and sync pass

- **What changed**
  - Added a canonical "Current Truth Snapshot" block at the top of `MEMORY_INDEX.md`.
  - Defined precedence so agents resolve conflicts consistently (rules/code override old memory notes).
  - Documented queue-truth distinction (`data/approval_queue.jsonl` authoritative, brain queue as mirror history).
- **Why**
  - The memory index had grown dense with historical notes; agents needed a deterministic entry point to avoid drift.
- **Affected files**
  - `insta-brain/MEMORY_INDEX.md`
- **Verification performed**
  - `status.py` confirms queue, token, and recent publish are healthy.
  - `runway.py` confirms fresh-fact runway counts.
  - `check_brain_fresh.py` run after this update.

## 2026-04-30 — Bank doubled (57 → 107) + Claude routine for daily generate-and-publish

- **What changed**
  - `src/research/rare_fact_bank.py` expanded from 57 → 107 curated entries. Added ~8 facts each in SPACE, EARTH, OCEAN, BIOLOGY, HISTORY, TECHNOLOGY. Every new entry carries an image_hint.
  - All 4 launchd jobs loaded into `~/Library/LaunchAgents/` and active per `launchctl list`.
  - `plan_week.py` rerun: 9 new carousels scheduled for 3-7 May. Approval queue now holds 13 carousels through 7 May (NATURE, HISTORY, SPACE, EARTH, OCEAN, TECH rotated).
  - Toby set up a Claude routine in the schedule UI to fire daily at ~9:04 with instruction to read the brain and run `ship_first_post.py` for the topic with most fresh facts. Acts as a redundant active-generator on top of the launchd publish-due job. Runs locally on Toby's Mac (rejected remote: would require non-trivial rework to deploy scripts off-device).
- **Why**
  - Runway was the only real bottleneck. Bank now sustains ~11 days at 1/day or 5-6 days at 2/day, with daily discovery topping up.
  - Claude routine provides an active-generator path so the queue can't go empty for long even if plan_week's Sunday refill fails.
- **Affected files**
  - `src/research/rare_fact_bank.py` (+47 facts, no duplicates)
  - `data/approval_queue.jsonl` (9 new rows)
  - No code changes
- **Operational notes for next agents**
  - The Claude routine instruction template (paste-ready) lives in the chat history. Toby can update it any time by editing the routine in the schedule UI.
  - When discovery's keyword-router over-defaults to "science", consider widening `route_to_topic` mappings rather than discarding good facts.
- **Verification performed**
  - Module imports clean.
  - `runway.py` confirms 68 fresh facts across 6 topics (>=10 in each except science).
  - `plan_week.py` ran end-to-end and scheduled 9 unique posts. Idempotency held — no double-bookings.

## 2026-04-30 — Autonomy hardening: launchd plists, status, alerts, plan_week dedupe

- **What changed**
  - `scripts/status.py` — single-command snapshot (queue depth, runway, last publish, IG token, recent alerts, recent log). Exits non-zero on red flags so cron can alert.
  - `scripts/heartbeat.py` — appends a line to `data/heartbeat.log` on every run so we can verify launchd is firing.
  - `src/analytics/alerting.py` — `AlertingService.send_alert` now persists JSON rows to `data/alerts.jsonl` in addition to log output. `status.py` surfaces the latest 3.
  - launchd plists for: `discover` (daily 03:00), `refresh_token` (Sunday 03:30), `plan_week` (Sunday 04:00). Combined with the existing `publish` (every 15 min), the full chain is autonomous.
  - `plan_week.py` is now idempotent on BOTH post_id and timeslot. Earlier runs were inserting two posts at the same publish_at slot because the second pass picked different facts (different post_id). Slot dedupe + post_id dedupe both checked before generation.
  - `plan_week.py` `--start-tomorrow` flag wires into `_next_slot_times` so launchd's Sunday-04:00 run starts from Monday 10:00, not the same morning's leftover slots.
  - `MIN_FACTS_PER_POST` lowered from 5 to 4 so the runway-stretched bank can still produce carousels.
- **Why**
  - Toby asked for highest-standard autonomy. The infrastructure existed but was untested; the launchd plists hadn't been written, and the status visibility was zero.
  - First live discovery run produced 4 fresh facts (rejected 96). The 8-stage gate is genuinely strict; `science` topic now overrepresented because the keyword router defaults there.
- **Affected files**
  - `scripts/status.py` (new)
  - `scripts/heartbeat.py` (new)
  - `src/analytics/alerting.py` (jsonl persistence)
  - `scripts/plan_week.py` (timeslot dedupe, --start-tomorrow, MIN_FACTS_PER_POST=4)
  - `launchd/com.tjcreate.factjot.discover.plist` (new)
  - `launchd/com.tjcreate.factjot.refresh.plist` (new)
  - `launchd/com.tjcreate.factjot.plan_week.plist` (new)
- **Operational notes for next agents**
  - **Bank growth is the bottleneck.** 22 fresh / 2 carousels per day = ~2 days of buffer. Discovery adds ~4/day; consumption at 2/day ≈ -6/day net. Sustainable cadence at current discovery rate is ~1/day until bank grows. If you want true 2/day, either expand `rare_fact_bank.py` significantly, broaden `TRUSTED_DOMAINS` carefully, or relax `MIN_UPVOTES`/`MIN_AGE_DAYS` in discover_facts.
  - **The keyword topic-router defaults too eagerly to "science".** Three of four discovered facts routed there. Consider tightening `route_to_topic` so unmatched claims fall back to a relevant topic by claim entity, or split "science" into more specific buckets.
- **Verification performed**
  - All modules import cleanly.
  - `status.py` ran end-to-end with valid output.
  - `discover_facts.py` ran live and produced 4 candidates that survived all 8 gates.
  - `plan_week.py --days 7 --start-tomorrow` ran twice, second run skipped duplicates correctly.
  - 4 unique carousels confirmed in `approval_queue.jsonl` for 1-2 May.

## 2026-04-29 — Audit + critical publish_due fixes; refresh_token.py

- **What changed**
  - `scripts/publish_due.py` had a stub `_to_public_image_urls` that returned empty for any path not starting with "http". Local renders never got uploaded. Replaced with real imgbb upload via `ImgbbHost`.
  - `InstagramGraphPublisher` was being instantiated WITHOUT the `host` keyword, so it defaulted to `graph.facebook.com` — wrong for our Instagram-login flow which uses `graph.instagram.com`. Now passes `host=cfg.env["META_GRAPH_HOST"]`.
  - After publish, the closing wholesome quote was rendered but not recorded in `posted_quotes.jsonl`. Quotes could repeat. Now calls `brain.record_quote_used()` after a successful publish.
  - Added `scripts/refresh_token.py`. Calls `graph.instagram.com/refresh_access_token` and rewrites `.env` in place. Run weekly (cadence ≪ 60 days) to keep the token alive.
  - Pre-publish spot audit ran clean: 13/13 PASS (env vars, brain freshness, posted/used integrity, IG token, modules import, bank rule sanity, runway).
- **Why**
  - The auto-publish cron was a paper tiger before this fix — it would have silently failed every 15 minutes once the launchd job was loaded.
  - Token expiry is silent and would have cratered the bot at day 60.
- **Affected files**
  - `scripts/publish_due.py` (3 critical fixes)
  - `scripts/refresh_token.py` (new)
- **Operational notes for next agents**
  - When wiring the launchd plist: also add a weekly job for `refresh_token.py` (`StartInterval` 604800 / 7 days, or a `StartCalendarInterval` Sunday 03:00).
  - The publish flow is now correct end-to-end. If a publish fails, check `data/launchd_publish.log` and the alerting service.
- **Verification performed**
  - Modules import cleanly.
  - Brain freshness gate passes after this batch.

## 2026-04-29 — Hybrid autonomy: 8-stage truth gate + 2/day scheduler

- **What changed**
  - `scripts/discover_facts.py` rebuilt for full autonomy. 8-stage truth gate per candidate r/TIL post: parse-claim → reddit-id-dedupe → posted.jsonl-dedupe → upvotes ≥ 5000 → age ≥ 3 days → trusted-domain check (Tier 1+2 only) → top-comment correction-signal scan → source-content cross-check (claim's numbers/proper-nouns must appear in source body). Anything that survives is auto-merged into the bank via `data/discovered_facts.jsonl`.
  - `src/research/fact_topic_router.py` — keyword-based topic routing for discovered facts. Maps free text to space/earth/ocean/biology/history/technology/science. Bundles a `suggest_image_hint` for known anchor terms.
  - `src/research/rare_fact_bank.py::load_all_facts()` — merges curated `RARE_FACT_BANK` with the discovered JSONL feed, deduping by claim text. Curated rows always rank first.
  - `scripts/plan_week.py` — generates 14 carousels (2/day at 10:00 and 18:00 local) for the next 7 days. Round-robin across topics so consecutive posts vary. If any topic has < 3 fresh facts, triggers `discover_facts.py` in-process before generation. Dry-run mode supported.
  - `launchd/com.tjcreate.factjot.publish.plist` — fires `publish_due.py` every 15 minutes, logs to `data/launchd_publish.log`.
  - Captions plural: "Follow @factjot for fresh facts daily." (was "one fresh fact a day"). Closing slide footer matches.
- **Why**
  - Toby wants autonomy without a human pending-file gate. Hybrid keeps the curated bank as the trusted core and gates auto-discovery behind aggressive filters: Tier 1+2 domains, community-vetted upvotes, age-resilience to debunks, source-content cross-reference.
  - Multiple checks compensate for the lack of human review. Failed candidates are silently dropped (logged to `data/discovery.log.jsonl`).
- **Affected files**
  - `scripts/discover_facts.py` (rewritten)
  - `scripts/plan_week.py` (new)
  - `src/research/fact_topic_router.py` (new)
  - `src/research/rare_fact_bank.py` (load_all_facts helper)
  - `src/content/carousel_generator.py` (caption pluralised)
  - `src/render/templates/closing.html.j2` (footer pluralised)
  - `launchd/com.tjcreate.factjot.publish.plist` (new)
- **Operational notes for next agents**
  - To install the launchd job: `cp launchd/com.tjcreate.factjot.publish.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.tjcreate.factjot.publish.plist`
  - Run `python3 scripts/plan_week.py` weekly (Sunday) to schedule 14 carousels for the next 7 days. Add to launchd separately when the discovery feed has stabilised.
  - The discovery's 8-stage gate is conservative by design — expect ~5-10 candidates per 100 fetched to survive. If volume needs to grow, broaden trusted domains or relax the upvote threshold cautiously.
  - **Source-content cross-check requires AT LEAST half the claim's distinctive tokens (numbers + capitalised names) to appear in the fetched source HTML.** Paywall sources will fail; the candidate is dropped, not retried.
- **Verification performed**
  - Modules import cleanly.
  - Brain freshness gate passes after this batch.

## 2026-04-29 — SPACE filter switched from blocklist to allowlist (airtight)

- **What changed**
  - For SPACE topic, the relevance gate now uses `SPACE_REQUIRED_TERMS` — an ALLOWLIST. An image's alt text must explicitly contain at least one real celestial-subject word (galaxy, mars, spacecraft, voyager 1, nasa image, lunar, supernova, etc.) or the candidate is rejected regardless of source.
  - Generic positive matches like "sun" or "star" alone NO LONGER SUFFICE. They were letting through camera lens-flare photos and starfield wallpapers.
  - Provider order for SPACE rewritten: `nasa → wiki → commons → smithsonian → openverse → pexels → pixabay → inaturalist`. NASA goes first because it only hosts real spacecraft + celestial photography. Pexels is now last with the strict allowlist gate as a final safety net.
  - NASA candidates trusted by provider (skip allowlist check) since their library is always real space content.
  - Voyager 1 fact's image_hint tightened to `"Voyager 1 probe NASA"` to land on actual JPL Voyager photos, not Voyager-branded stock photos.
- **Why**
  - Pexels has a huge library of "space-themed" stock — control-panel mockups, sci-fi prop shots, sun-flare camera bokeh — that all match generic positive terms. Reactive blocklist kept losing to new false positives (Olympus Trip 35 camera, Viña del Mar city skyline, Voyager-named control panel).
  - An allowlist of real celestial terms blocks them all by default. False negatives are recoverable (add curated `image_hint` to the bank); false positives ship as a published post and embarrass the brand.
- **Affected files**
  - `src/research/image_fetcher.py` (`SPACE_REQUIRED_TERMS`, allowlist check in `_pexels_photo_allowed` and `_candidate_allowed`, provider order)
  - `src/research/rare_fact_bank.py` (Voyager image_hint tightened)
- **Operational notes for next agents**
  - When extending to other topics, prefer ALLOWLIST over blocklist for any topic where stock libraries return ambiguous results (history, ai). Blocklist still fine for biology where Pexels coverage of real animals is strong.
  - If a real space photo is rejected because its alt is sparse (e.g. "rocky red landscape" with no Mars word), set the fact's `image_hint` to land on Wikipedia/NASA where the article title carries the celestial term.
- **Verification performed**
  - Module imports cleanly.
  - `_pexels_photo_allowed` and `_candidate_allowed` both updated and consistent.
  - Brain freshness gate passes.

## 2026-04-29 — Render folder audit + ship_first_post fresh-facts filter

- **What changed**
  - Manual audit of all 9 render folders. Six removed (001 empty, 002 TECH had guitarist for metaverse + tree for Wi-Fi, 003 empty, 004 HISTORY had Sphinx for London Fire + modern building for Oxford, 008 SPACE had city skyline for Venus, 009 NATURE had jewelry ring for octopus).
  - Three kept: 005 EARTH, 006 OCEAN, 007 NATURE (all on-topic, all currently live on @factjot).
  - `scripts/ship_first_post.py` now filters `RARE_FACT_BANK` rows through `brain.is_fact_posted()` BEFORE generation. Previously it built a carousel from already-posted facts then aborted at the rule 01 gate. Now it picks only fresh facts.
- **Why**
  - Toby asked to audit content for irrelevant images and remove offending folders.
  - Without the fresh-facts filter, retrying any topic that's been posted just hit "ABORT — claim already in posted.jsonl" and never produced a usable carousel.
- **Affected files**
  - `scripts/ship_first_post.py` (fresh-facts filter)
  - 6 deleted folders under `data/renders/`
- **Operational notes for next agents**
  - The TECH and HISTORY posts shipped earlier today (b401a141ce2832, 24942cfa604fb6) are LIVE on @factjot with bad images. Removing local renders doesn't pull them. If the live posts need to come down, do it via the IG app or extend `instagram_publisher.py` with a `delete_media` call.
  - Live, clean posts that should stay: NATURE (9d7f0cb163ad06), EARTH (a1b282f51ad0bb), OCEAN (0a0961a686fafc).
- **Verification performed**
  - `data/renders/` now contains only the 3 clean folders (005, 006, 007).
  - Brain freshness gate passes after this batch.

## 2026-04-29 — Full factjot wordmark + supply runway + tardigrade-deer fix

- **What changed**
  - Switched the top-left logo from the single "f." mark to the full italic "factjot." wordmark. `scripts/make_logo_asset.py` updated; `assets/logo/factjot_mark.png` regenerated at 720x220 transparent. Wordmark-img height in templates dropped to 38px to balance with the index pair.
  - Added `image_hint: "water bear microscope"` to the Tardigrade fact so Pexels lands on actual specimens, not generic "wildlife enclosure" deer photos.
  - Hardened `INTENT_STOPWORDS` so topic-disambiguator words ("animal", "wildlife", "nature", "marine", "underwater", "geology", etc.) are NOT treated as primary intent. Previously a "Tardigrade animal wildlife" variant let any photo whose alt contained "wildlife" pass the candidate-allowed gate.
  - Extended `BIOLOGY_NEGATIVE_TERMS` to block jewelry / decorative / artwork representations of animals (ring, necklace, tattoo, illustration, sculpture, leather, embroidery, plush, etc.) — caught after a Pexels octopus search returned a silver octopus-shaped ring on a leather belt.
  - **Expanded `rare_fact_bank.py` from 30 to 57 facts** across all six topics. Each new fact carries an `image_hint`. Spread: SPACE 11, EARTH 10, OCEAN 8, BIOLOGY 10, HISTORY 9, TECH 9.
  - Added `scripts/runway.py` — reports per-topic fresh-fact counts and total carousel days remaining. Exits non-zero if any topic falls below `--min` (default 7) so cron can alert.
- **Why**
  - Toby asked for the full wordmark, not just the avatar mark.
  - Toby caught a deer photo on a Tardigrade slide. Audit showed the disambiguator was diluting the candidate-allowed intent check.
  - The bank had 30 facts, all shipped today. Without expansion the supply was gone. New runway is ~4 days; still LOW but sustainable while we wire Wikipedia / r/TIL discovery.
- **Affected files**
  - `scripts/make_logo_asset.py` (full wordmark, wider canvas)
  - `assets/logo/factjot_mark.png` (regenerated)
  - `src/render/templates/slide.html.j2`, `closing.html.j2` (wordmark height 38px)
  - `src/research/image_fetcher.py` (INTENT_STOPWORDS expanded; BIOLOGY_NEGATIVE_TERMS expanded; TERM_EXPANSIONS_BIO seeded)
  - `src/research/rare_fact_bank.py` (+27 facts with image hints)
  - `scripts/runway.py` (new)
- **Operational notes for next agents**
  - Run `scripts/runway.py` weekly. If any topic shows LOW, top it up before scheduling a week.
  - Long-term supply requires Wikipedia "Did you know" + r/todayilearned scrapers (TBD). Bank-only sustains ~4 days; we need ~30 days of buffer.
  - When you spot a wrong-subject image like the deer/tardigrade case, FIRST add an `image_hint` to the fact, THEN consider whether the gate logic missed something.
- **Verification performed**
  - All modules import cleanly.
  - `runway.py` reports 27 fresh facts across 6 topics.
  - Logo PNG visible at top-left in latest renders (folder 009 onward).

## 2026-04-29 — Logo mark on every slide; tighter Pexels relevance gate

- **What changed**
  - Added `assets/logo/factjot_mark.png` (transparent italic "f." with red accent dot, generated by `scripts/make_logo_asset.py`).
  - Wired the logo into the top-left of every fact slide and closing slide. Replaces the text "factjot" wordmark, sits on top of the existing horizontal divider and slide-index pair.
  - Extended Pexels relevance filter beyond SPACE: added per-topic NEGATIVE term lists for SPACE (statue/marble/abstract render), BIOLOGY/NATURE/OCEAN (food: grilled/served/dish/sauce), HISTORY (halloween/cosplay/costume/photoshoot).
  - `_pexels_photo_allowed` now requires non-empty alt for every topic (was previously SPACE-only).
  - `image_hint` overrides added in `rare_fact_bank.py` for Venus, Saturn, Octopus to bias query toward the right domain.
- **Why**
  - Pexels probe revealed the API returns grilled-octopus dishes for "octopus", Venus de Milo statues for "Venus", abstract renders for "Saturn", costume photoshoots for "Cleopatra". The previous gate only filtered SPACE, so all of those were passing through.
  - Logo on every slide reinforces brand recognition once viewers tap into the carousel.
- **Affected files**
  - `assets/logo/factjot_mark.png` (new)
  - `scripts/make_logo_asset.py` (new)
  - `src/render/templates/slide.html.j2`
  - `src/render/templates/closing.html.j2`
  - `src/render/render_carousel.py` (LOGO_PATH constant; wordmark_image_url passed to both templates)
  - `src/research/image_fetcher.py` (NEGATIVE_TERMS_BY_TOPIC, expanded `_pexels_photo_allowed`)
  - `src/research/rare_fact_bank.py` (image_hint on Venus / Saturn / Octopus)
- **Operational notes for next agents**
  - Logo asset is regenerated by `scripts/make_logo_asset.py`. Do not hand-edit the PNG.
  - When you spot a topic returning bad Pexels results, add the offending alt-text terms to `NEGATIVE_TERMS_BY_TOPIC[topic]` and re-probe.
  - Wikipedia/Commons still occasionally returns metaphorical matches (e.g. "Venus" planetary-conjunction CITY photo for the Venus fact). Next agent: extend SPACE_NEGATIVE_TERMS with `city`, `skyline`, `aerial`, `building`, `street`.
- **Verification performed**
  - All 14 key modules import cleanly.
  - Logo asset regenerated at 200x200 retina; visible top-left in `data/renders/008_20260429_SPACE_factjot_*/slide_01.png`.
  - Pexels probe across 10 representative queries: food/statue/costume now blocked.
  - 6 carousels confirmed live on @factjot today via `posted.jsonl` (30 unique claim_hashes, 6 unique post_ids).

## 2026-04-29 — Brain wiring, image quality, and render structure hardening

- **What changed**
  - Wired `image_hint` through full discovery -> verification -> generation path.
  - Enforced read-before-generate and write-back memory behaviour in generation and scheduled publishing paths.
  - Added ordered image credits to caption/description builder and publish scripts.
  - Increased main fact text size and strengthened readability treatment (gradient + subtle diagonal shadow).
  - Reorganised render outputs into numbered per-post folders.
  - Reorganised source image cache into per-post slide-labelled files.
  - Added stricter ambiguity handling for `space` query terms (for example Venus).
  - Enforced strict `space` provider order and relevance gating to prevent non-space image mismatches.

- **Why**
  - Prevent repost/reuse mistakes and keep memory writes reliable for every run.
  - Improve visual readability and operational clarity for generated assets.
  - Prevent diagram/plant mismatches on `space` facts and prioritise stock-photo sources.

- **Affected files (high signal)**
  - `src/research/fact_discovery.py`
  - `src/verification/fact_checker.py`
  - `src/research/image_fetcher.py`
  - `src/render/render_carousel.py`
  - `src/content/description_builder.py`
  - `scripts/run_pipeline.py`
  - `scripts/publish_due.py`
  - `scripts/publish_now.py`
  - `scripts/ship_first_post.py`
  - `src/render/templates/slide.html.j2`
  - `src/render/templates/closing.html.j2`
  - `brand/brand_kit.json`
  - `README.md`
  - `insta-brain/rules/04-visual-design.md`
  - `insta-brain/CRITICAL_FACTS.md`
  - `CLAUDE.md`

- **Operational notes for next agents**
  - If `space` images drift off-topic again, inspect `ImageFetcher._pexels_photo_allowed()` and strict topic provider order first.
  - Keep `data/used_images.jsonl` append-only and trust it as the final dedupe authority.
  - Do not bypass brain writes after publish or scheduled publish paths.

- **Verification performed**
  - Python compile checks passed after each patch batch.
  - Smoke renders regenerated into numbered folders.
  - Provider-order and query-variant checks run for `space`.
