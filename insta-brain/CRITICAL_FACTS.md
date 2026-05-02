# CRITICAL FACTS — read first, every session

These are invariants. If anything you are about to do violates one, stop and ask.

## Terminology — NEVER confuse these

| Word | Meaning | Pipeline |
|---|---|---|
| **Reel** | A VIDEO post (~45-60s, voice-over, footage clips) | `scripts/make_reel.py` → GitHub Actions fires daily at 18:45 UTC |
| **Carousel** | A FACT CAROUSEL (5-6 image slides, curated facts) | `scripts/ship_first_post.py` → GitHub Actions fires at 09:45 + 17:45 UTC |
| **List** | A RECOMMENDATION LIST (films/TV/books, image slides) | `scripts/ship_list_post.py` → MANUAL only |

These are three completely separate pipelines with separate ledgers, separate dedup, and separate schedules.
- Reels use `quirky_score=3` facts only, deduped via `insta-brain/data/reels.jsonl` + `posted.jsonl`
- Carousels use any fact, deduped via `insta-brain/data/posted.jsonl`
- Lists use TMDB packs, each pack ships ONCE EVER, deduped via pack slug in `posted.jsonl`
Never call the wrong script for the wrong format. Never mix terminology in log entries.

## What this project is
- **Project name:** factjot
- **Instagram handle:** @factjot
- **Owner:** Toby Johnson (TJCreate)
- **Goal:** automated daily Instagram content — carousels + Reels + stories
- **Posting cadence (as of 2026-05-02, via GitHub Actions):**
  - 09:45 UTC — carousel (morning, GitHub Actions `carousel-morning.yml`)
  - 17:45 UTC — carousel (evening, GitHub Actions `carousel-evening.yml`)
  - 18:45 UTC — Reel (GitHub Actions `reel.yml`, story posted immediately after)
  - Sunday 04:00 UTC — weekly plan + token refresh + fact discovery
  - List posts: manual, shipped via `ship_list_post.py` when a pack is ready
- **Scheduler:** GitHub Actions (repo: Wonderkid96/factjot). Mac launchd ALL DISABLED.
- **Repo root:** `/Users/Music/Documents/Insta-bot`

## Hard rules (non-negotiable)
1. **Never repost a fact.** Hash check `data/posted.jsonl` before generation.
2. **Never reuse an image.** Hash check `data/used_images.jsonl` (URL + content SHA-256) before save.
3. **Every fact must be 100% true.** Verified against ≥2 independent reputable sources, with source URLs stored. Confidence ≥ 0.65. No fact ships without verification. No "loosely true", no folk-knowledge, no AI-paraphrased uncertainty.
4. **Never post a slide without a real image.** No procedural gradients, no solid colours, no placeholders. If the image fetcher can't find one, the slide does not ship — the post is held for review.
5. **Paid services allowed with approval.** ElevenLabs (voice synthesis, paid plan active since 2026-04-30) is used for Reels. All other services remain free: Pexels, Pixabay, Coverr, Wikimedia, imgbb, tmpfiles, Meta Graph API. No new paid services without Toby's explicit approval.
6. **No em dashes.** Anywhere. Ever.
7. **British English.** Colour, organise, centre, specialise.
8. **Append-only ledgers.** Never edit historical lines in any `.jsonl`.
9. **Read before write.** Always load posted + used_images ledgers before producing new content.
10. **Brand-locked visuals.** See `rules/04-visual-design.md`. No silent visual changes.

## What an agent MUST do at session start
1. Read `insta-brain/CLAUDE.md`
2. Read this file
3. Read `insta-brain/rules/index.md`
4. Read `insta-brain/MEMORY_INDEX.md` (for recent verified changes)
5. Read `insta-brain/data/posted.jsonl` (for repost check)
6. Read `insta-brain/inbox.md` (for any human-dropped notes)
7. Append one terse startup line to `insta-brain/log.md` before any edits or runs:
   `- YYYY-MM-DD HH:MM session start: read-order complete, working on <task>`

## What an agent MUST do at session end (if any non-trivial action ran)
1. Append a single terse line to `insta-brain/log.md` (newest at top)
2. If a post shipped: append a row to `data/posted.jsonl`
3. If metrics fetched: append rows to `data/stats.jsonl`
4. If behaviour/rules changed: append a block to `insta-brain/MEMORY_INDEX.md`
5. Never reorganise the brain folder structure unless Toby explicitly asks.

## Where things live
- **Code:** `src/` (research, content, render, publish, analytics, review)
- **Pipeline configuration:** `config/pipeline.yaml`
- **Brand kit:** `brand/brand_kit.json` (locked, see visual-design rule)
- **Renders:** `data/renders/<nnn>_<date>_<category>_<series>_<post_id>/slide_<nn>.png`
- **Per-post bundles (caption + slides + metadata):** `data/posts/<post_id>/`
- **Brain:** `insta-brain/` (this folder)

## Voice
Direct, dry, plain. No "did you know" preamble. No corporate fluff. No "I'm excited to share". British English. No em dashes.

## When in doubt
Ask Toby. Do not silently break a rule to make a task easier.

## Related
[[CLAUDE]] · [[PUBLISH_PLAN]] · [[rules/index]] · [[rules/01-no-repost]] · [[rules/02-no-image-reuse]] · [[rules/10-truth]] · [[rules/11-no-naked-slides]] · [[log]] · [[inbox]]
