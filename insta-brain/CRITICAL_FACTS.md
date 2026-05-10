# CRITICAL FACTS — read first, every session

These are invariants. If anything you are about to do violates one, stop and ask. Updated 2026-05-10 after the audit (Phases A–G).

## Terminology — NEVER confuse these

| Word | Meaning | Pipeline |
|---|---|---|
| **Reel** | A VIDEO post (~45-60s, voice-over, footage clips) | `pipelines/reel/make_reel.py` (called by autonomous agent's `run_reel` tool, fires at 09:00 + 20:30 BST) |
| **Carousel** | A LIST CAROUSEL (image slides with declared criterion, e.g. films/TV/books) | `pipelines/carousel/ship_carousel_post.py --type list` (called by autonomous agent's `run_carousel` tool, fires at 14:00 BST) |
| **Story** | A 9:16 frame published immediately after a reel publishes | Built inside `make_reel.py`; needs IG story container `status_code: FINISHED` before `media_publish` |

These are separate code paths with separate ledgers, separate dedup, and separate cadence.

- **Reels** dedup via `insta-brain/data/reels.jsonl` + `posted.jsonl`. Footage dedup via `data/ledgers/used_footage_urls.jsonl`.
- **Carousels** dedup via `insta-brain/data/posted.jsonl`. Image dedup via `data/ledgers/used_images.jsonl`.
- **Subject-fingerprint dedup (Phase C.3):** rejects subjects whose Jaccard similarity to anything in the last 14 days hits 0.6 or above. Prevents same-subject framing across formats.
- The fact-only carousel slot was retired in audit Phase E.5 cadence cut. The fact format still exists in code (`compact_legacy` profile) but no scheduled slot calls it.

Never call the wrong script for the wrong format. Never mix terminology in log entries.

## What this project is

- **Project name:** factjot
- **Instagram handle:** @factjot
- **Owner:** Toby Johnson (TJCreate), Lincoln, UK
- **Goal:** automated daily Instagram content (reels + lists, plus auto-stories on every reel)
- **Posting cadence (as of 2026-05-10):**

  | Slot | BST | UTC cron |
  |---|---|---|
  | `reel_morning` | 09:00 | `0 8 * * *` |
  | `list_midday` | 14:00 | `0 13 * * *` |
  | `reel_night` | 20:30 | `30 19 * * *` |

- **Scheduler:** GitHub Actions workflow `autonomous-reel.yml` (repo: Wonderkid96/factjot). Mac launchd ALL DISABLED. cron-job.org gone.
- **Repo root:** `/Users/Music/Developer/Insta-bot`. Never `~/Documents/` (iCloud intercepts FFmpeg writes — see gotchas).

## Hard rules (non-negotiable)

1. **Never force-push to main.** Force-push silently deletes state commits being written by running workflows (caused the 2026-05-05 triple-post incident).
2. **Never repost.** Agent reads the last 30 entries of `posted.jsonl` and rejects topic / angle / "same subject framed differently" overlaps. Phase C.3 subject-fingerprint dedup adds Jaccard ≥ 0.6 against last 14 days.
3. **Never reuse an image.** Hash-checked against `data/ledgers/used_images.jsonl` (git-tracked).
4. **Never reuse footage across reels.** Hash-checked against `data/ledgers/used_footage_urls.jsonl`.
5. **Every fact must be defensible.** Phase D.1 fact verification gate: Haiku consistency + Wikipedia anchors for numeric/named claims. The previous "≥ 2 reputable sources, confidence ≥ 0.65" code gate was tied to the deleted Reddit-discovery pipeline; Phase D restored a code-level path for the autonomous flow. No "loosely true", no folk-knowledge, no AI-paraphrased uncertainty.
6. **Lists need a defensible criterion** (Phase D.2). Bare "things" without a criterion fail the format gate. Briefs containing "fictional", "absurdity", "experiment" without justification fail at $0 cost.
7. **Never post a slide without a real image.** No procedural gradients, no solid colours, no placeholders. The Phase E.2 empty-cover variant uses an intentional typography-only layout when the image fetcher cannot find a real image — never a blank rectangle.
8. **Reel `--script` and `--title` are mandatory.** No auto-fallback. Phase G.1 retired `rare_fact_bank.py` and the legacy `_pick_fact()` selection path. The autonomous reel path supplies both via `run_reel`.
9. **Audio must be 48 kHz.** Meta rejects 44.1 kHz and 96 kHz. ElevenLabs returns 44.1 kHz; always resample before muxing.
10. **Wait for IG story container `status_code: FINISHED` before `media_publish`** (commit `3a366e1`). Stories were sometimes published before cover image upload completed, producing partial-render stories.
11. **Voice normaliser before publish.** Phase C.1+C.2: every caption builder routes through `voice_normaliser` before commit. No corporate fluff, no "did you know", no "I'm excited to share" leaks past it.
12. **Paid services allowed with approval.** ElevenLabs (voice synthesis, paid plan active since 2026-04-30), Anthropic API (Sonnet 4.6 + Haiku 4.5). All other services remain free: Pexels, Pixabay, Coverr, Wikimedia, imgbb, tmpfiles, Meta Graph API, YouTube Data API. No new paid services without Toby's explicit approval.
13. **No em dashes in shipping copy or YAML.** Code comments, docstrings, internal logs, and `.md` technical docs are out of scope. GitHub's Go YAML parser silently rejects em dashes and breaks `workflow_dispatch` with 422.
14. **British English.** Colour, organise, centre, specialise.
15. **Append-only ledgers** with one named exception: `data/ledgers/reel_performance.jsonl` is mutable, rewritten on each `fetch_reel_metrics.py` run.
16. **Read before write.** Always load `posted.jsonl` + `reels.jsonl` + `used_images.jsonl` + `used_footage_urls.jsonl` before producing new content.
17. **Brand-locked visuals.** See `rules/04-visual-design.md` and `brand/brand_kit.json` v2.1. Font hierarchy: Archivo Black 900 (hooks/thumbnails/stories), Archivo Bold 700 (kinetic subtitles), Instrument Serif Regular + Italic (headlines/wordmark), Space Grotesk SemiBold (carousel body), Space Grotesk Bold 700 (labels/kickers/chips, replaces JetBrains Mono Bold). JetBrains Mono Bold is removed from active brand.
18. **Image-pipeline changes require plan mode.** See `SPEC_IMAGE_PIPELINE.md`.

## What an agent MUST do at session start

1. Read `/Users/Music/.claude/CLAUDE.md` (universal voice rules).
2. Read project root `CLAUDE.md`.
3. Read `SPEC_FACTJOT_SYSTEM.md`.
4. Read `SPEC_IMAGE_PIPELINE.md` (only if touching image-pipeline code).
5. Read `insta-brain/gotchas.md` before any pipeline / render / publish change.
6. Read this file.
7. Read `insta-brain/MEMORY_INDEX.md` (recent verified changes).
8. Read `insta-brain/data/posted.jsonl` and `insta-brain/data/reels.jsonl` (for repost check).
9. Read `insta-brain/inbox.md` (for any human-dropped notes).
10. Append one terse startup line to `insta-brain/log.md` before any edits or runs:
    `- YYYY-MM-DD HH:MM session start: read-order complete, working on <task>`

## What an agent MUST do at session end (if any non-trivial action ran)

1. Append a single terse line to `insta-brain/log.md` (newest at top).
2. If a post shipped: workflow handles ledger commits via per-file guarded `git add`.
3. If metrics fetched: `data/ledgers/reel_performance.jsonl` is rewritten in place.
4. If behaviour/rules changed: append a block to `insta-brain/MEMORY_INDEX.md`.
5. If a new failure mode was discovered: append to `insta-brain/gotchas.md`.
6. Never reorganise the brain folder structure unless Toby explicitly asks.

## Where things live

- **Pipelines:** `pipelines/{reel,manual,news,carousel,list,shared}/`. Production entry points: `pipelines/reel/make_reel.py` and `pipelines/carousel/ship_carousel_post.py`.
- **Shared modules:** `src/{core,research,content,verification,render,publish,utils}/`.
- **Workflows:** `.github/workflows/`. Active: `autonomous-reel.yml`, `manual-run.yml`, `test.yml`, `pages.yml`.
- **Brand kit:** `brand/brand_kit.json` v2.1 (locked, accessed via `src/core/brand.py`).
- **Output (gitignored):** `output/{reel,carousel,list,news,manual,experiments}/YYYY-MM-DD_HH-MM_TOPIC/`.
- **Brain:** `insta-brain/` (this folder).

## Voice

Direct, dry, plain. No "did you know" preamble. No corporate fluff. No "I'm excited to share". British English. No em dashes in shipping copy. Phase C.1+C.2 voice normaliser enforces this on every caption builder.

## When in doubt

Ask Toby. Do not silently break a rule to make a task easier.

## Related

[[CLAUDE]] · [[gotchas]] · [[MEMORY_INDEX]] · [[PUBLISH_PLAN]] · [[rules/index]] · [[rules/01-no-repost]] · [[rules/02-no-image-reuse]] · [[rules/10-truth]] · [[rules/11-no-naked-slides]] · [[log]] · [[inbox]]
