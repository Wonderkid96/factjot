# factjot brain — operating manual for any agent

You are working on **factjot**, an automated Instagram account posting daily reels and lists under @factjot. Last reviewed 2026-05-10 after the audit (Phases A–G).

If anything below contradicts a CLAUDE.md higher up the tree, the higher-level file wins for personal/voice rules; this file wins for factjot pipeline rules. The brain wins on conflicts with the project root `CLAUDE.md` per the read-order rule. For full technical docs and live invariants, read the project root `CLAUDE.md`, `SPEC_FACTJOT_SYSTEM.md`, and `SPEC_IMAGE_PIPELINE.md`.

---

## CRITICAL: read this before touching anything

1. `/Users/Music/.claude/CLAUDE.md` — universal voice rules (no em dashes in shipping copy, British English).
2. Project root `CLAUDE.md` — hard rules, plan-mode triggers, environment specifics.
3. `SPEC_FACTJOT_SYSTEM.md` — architecture, lifecycle, invariant principles.
4. The relevant sub-spec for the area being touched (`SPEC_IMAGE_PIPELINE.md` for image-pipeline change).
5. **[[gotchas]]** (`gotchas.md`) — incident log: everything that has broken or failed. Read before every change; append when you find a new failure mode.
6. **[[CRITICAL_FACTS]]** — invariants you must never break.
7. **[[MEMORY_INDEX]]** — recent verified context.

---

## What this project is

Fully automated Instagram account (@factjot). Scheduled slots run via `autonomous-reel.yml` on GitHub-hosted cron. **The Mac does not need to be on.**

The agent (Sonnet 4.6) writes the brief or script and calls one of `run_reel` / `run_carousel`, or `skip` if nothing clears the quality gate.

| Mode | BST | UTC cron | Format |
|---|---|---|---|
| `reel_morning` | 09:00 | `0 8 * * *` | Evergreen reel |
| `list_midday` | ~12:00 | `30 11 * * *` | List carousel |

Cut from 5 slots to 3 on 2026-05-10, then to 2 slots on 2026-05-19 (1 reel + 1 list per day).

The breaking-news pipeline was killed in audit Phase G.2 (decision B). `news-watcher.yml`, `pipelines/news/ship_news_breaking.py`, and `pipelines/news/check_guardian_rss.py` are gone. Phase K.4 (2026-05-11) deleted the dual-role `pipelines/news/ship_news_post.py` and the empty `pipelines/news/` package; renderer primitives now live in `src/render/carousel_slides.py`.

Crons are UTC, tracked to BST in summer. UK clocks fall back to GMT in October; UTC equals GMT then, so posts fire at the same UK clock time year-round.

---

## Stack

- **Python 3.11**, Playwright + Chromium, FFmpeg, ElevenLabs.
- **Anthropic Sonnet 4.6** — autonomous agent + carousel writer (lists).
- **Anthropic Haiku 4.5** — image selection, image repair, hashtags, search expansion, fact verification (Phase D), entity image validation (Phase E.3), thumbnail picker (Phase E.4).
- **Instagram Graph API** for publishing.
- **YouTube Data API v3** — successful reels cross-post as Shorts (own description + own title + sharper encode after Phase F divergence). Channel: `thefactjot@gmail.com`.
- **Image hosting:** imgbb (slides + thumbnails). **Video hosting:** tmpfiles.org (Cloudinary disabled — Meta's video fetcher 413'd it).

---

## Posting pipeline — how each format works

### Reels (`pipelines/reel/make_reel.py`)

- The autonomous agent supplies `--script "<70+ words>"` and `--title "..."` via the `run_reel` tool. There is no auto-fallback path; the legacy `_pick_fact()` selection from `rare_fact_bank.py` was retired in Phase G.1. `--script` and `--title` are now mandatory on every invocation.
- Entity-first footage: Wikipedia lead image, Wikimedia Commons, Internet Archive (Tier 0). Phase E.3 added Haiku validation that rejects wrong-subject entity hits before they enter `footage_clips`.
- Fills remaining clips from Pexels / Coverr / Pixabay B-roll.
- ElevenLabs TTS (resampled to 48 kHz before muxing — Meta rejects 44.1 kHz and 96 kHz).
- FFmpeg composition with hardcoded `case_file_dynamic` transitions (no env flags, no classic fallback).
- Branded thumbnail (Phase E.4 Haiku-picks the best frame, then layers brand overlay) and story PNG.
- Posts reel to Instagram, then immediately posts the story (waiting for IG story container `status_code: FINISHED` before `media_publish` — see gotchas).
- Cross-posts to YouTube Shorts when feed reel publishes successfully.
- Commits `insta-brain/data/reels.jsonl` + `data/ledgers/used_footage_urls.jsonl` + `data/ledgers/youtube_uploads.jsonl` to git.
- **Local:** advisory lock on `data/cache/reels/.make_reel.lock` (second concurrent run exits **10**). `scripts/kill_local_reel_jobs.sh` stops this repo's compose jobs. Full encode on a Mac is slow; production posting runs on Linux via `autonomous-reel.yml`.
- Per-run logs: `output/reel/<id>/pipeline.log`, `logs/reel_runs/<UTC>_<id>.log`. Compose stderr: `ffmpeg_compose_stderr.log`. Filter graph: `ffmpeg_filter_complex.txt`.
- Performance ledger: `data/ledgers/reel_performance.jsonl` (mutable; rewritten on each `fetch_reel_metrics.py` run).
- Cost ledger: `data/ledgers/api_usage_costs.jsonl` (per-run API + TTS cost).

### List carousels (`pipelines/carousel/ship_carousel_post.py --type list`)

- The autonomous agent supplies a brief via `run_carousel(format_type=list)`, which appends `--layout-mode readable_list`.
- Phase D.2 list format rule: every list must declare a defensible criterion. Briefs that contain "fictional", "absurdity", "experiment" trigger fact verification rejection at $0 cost.
- Phase D.1 fact verification gate: Haiku consistency check, then numeric/named claims cross-checked against Wikipedia anchors. Catches inventions before they ship.
- `compact_legacy` and `readable_list` are the two layout profiles; `readable_list` uses Space Grotesk SemiBold body in a half-box auto-fit container, `compact_legacy` is byte-identical to pre-2026-05-08 output and stays default for `--type=fact`.
- Renders via Playwright, uploads to imgbb, posts to Instagram.
- Commits `insta-brain/data/posted.jsonl` + `data/ledgers/used_images.jsonl` to git.

### Other formats

There is no daily fact carousel slot. The fact format still exists in code (`compact_legacy` profile), but no scheduled slot calls it. `ship_first_post.py` was deleted in Phase G.3.

---

## Brain data ledgers — what lives where

| File | Written by | Read by | Committed to git |
|---|---|---|---|
| `insta-brain/data/posted.jsonl` | autonomous agent + carousel post | duplicate-guard prompt + visual layer | YES (every post workflow) |
| `insta-brain/data/reels.jsonl` | `make_reel.py` | duplicate-guard prompt + agent | YES (reel workflow) |
| `data/ledgers/used_images.jsonl` | `image_fetcher.py` (via paths.py) | `UsedImageLedger` | YES (every post workflow) |
| `data/ledgers/used_footage_urls.jsonl` | `make_reel.py` | global registry | YES (reel workflow) |
| `data/ledgers/api_usage_costs.jsonl` | every API caller | analytics | YES |
| `data/ledgers/youtube_uploads.jsonl` | YouTube cross-poster | analytics | YES (when present — first cross-post creates it; workflow `git add` is per-file guarded) |
| `data/ledgers/reel_performance.jsonl` | `fetch_reel_metrics.py` | analytics | YES (mutable; rewritten each run) |
| `data/ledgers/carousel_quality.jsonl` | carousel post | analytics | YES (when present) |
| `insta-brain/log.md` | all scripts | agents | YES |
| `data/cache/reels/<id>/pipeline.log` | `ReelRunLogger` | agents debugging | NO (local cache) |
| `logs/reel_runs/<UTC>_<id>.log` | same | agents | NO |
| `data/cache/reels/.make_reel.lock` | `make_reel.py` (fcntl) | second concurrent local process | NO (transient; delete if left after a crash) |

**Git is the database.** Every important state file is committed to git after every workflow run. The runner is destroyed after each run; nothing persists except git, imgbb, and tmpfiles.

---

## Strict invariants — never break these

The principles live in `SPEC_FACTJOT_SYSTEM.md` §12. Implementation rules also live in project-root `CLAUDE.md` §1. The brain restates the ones that affect any agent decision here.

1. **Never force-push to main.** Force-push silently deletes state commits being written by running workflows (caused the 2026-05-05 triple-post incident).
2. **Never repost.** Agent reads the last 30 entries of `posted.jsonl` and rejects topic, angle, and "same subject framed differently" overlaps. Subject-fingerprint dedup added in Phase C.3 rejects briefs whose Jaccard similarity to anything in the last 14 days hits 0.6 or above.
3. **Never reuse an image.** Hash-checked against `data/ledgers/used_images.jsonl` (git-tracked).
4. **Never reuse footage across reels.** Hash-checked against `data/ledgers/used_footage_urls.jsonl`.
5. **Every fact must be defensible.** Phase D.1 fact verification gate: Haiku consistency check + Wikipedia anchors for numeric/named claims. The previous "≥ 2 reputable sources, confidence ≥ 0.65" code gate was tied to the deleted Reddit-discovery pipeline; Phase D restored a code-level path for the autonomous flow.
6. **Lists need a defensible criterion.** Phase D.2 rule: every list must declare why the items belong together. Bare "things" without a criterion fail the format gate.
7. **No empty image boxes.** A slide either shows a real image or uses the intentional typography-only layout (Phase E.2 empty-cover variant). Never a blank rectangle, near-invisible placeholder, or trust-the-renderer empty string.
8. **No em dashes in shipping copy or YAML.** Code comments, docstrings, internal logs, and `.md` technical docs are out of scope. GitHub's Go YAML parser silently rejects em dashes and breaks `workflow_dispatch` with 422 "no workflow_dispatch trigger".
9. **British English** throughout copy, captions, comments.
10. **Append-only ledgers**, with one named exception: `data/ledgers/reel_performance.jsonl` is mutable, rewritten on each metrics fetch.
11. **Audio must be 48 kHz.** Meta rejects 44.1 kHz and 96 kHz. ElevenLabs returns 44.1 kHz by default; always resample before muxing.
12. **Reel transitions are hardwired.** `case_file_dynamic` is the only transition mode (hardcoded in `src/render/reel_composer.py`). No env flags, no classic fallback. The legacy `REEL_TRANSITIONS_MODE` env var is gone.
13. **Voice normaliser before publish.** Phase C.1+C.2: every caption builder routes through `voice_normaliser` before commit. No corporate fluff, no "did you know", no "I'm excited to share" leaks past it.
14. **Reel `--script` and `--title` are mandatory.** No auto-fallback. Phase G.1 retired `rare_fact_bank.py` and the legacy `_pick_fact()` selection path. The autonomous reel path supplies both via `run_reel`.
15. **TMDB artwork is confidence-gated** (reels). If title match confidence is weak (or year check fails when provided), reject the TMDB match and continue with normal footage fallback. Carousel-side gating is deferred (audit P2).
16. **Image-pipeline changes require plan mode.** Any change to `image_sourcer.py`, `image_fetcher.py`, manual carousel rendering, provider order, or candidate scoring begins in plan mode. See `SPEC_IMAGE_PIPELINE.md`.

---

## Voice and brand

Direct, dry, factual. No "did you know" preamble. No corporate fluff. No em dashes in shipping copy. British English. Captions: hook + body + CTA + source credits + hashtags. Phase C.1+C.2 voice normaliser enforces this on every caption builder.

Wordmark: `fact[regular] jot[italic] .[red]`. Canonical inline 3-part HTML across every template; the legacy PNG fallback was removed 2026-05-07.

### Font hierarchy (post 2026-05-10 rationalisation)

Source of truth: `brand/brand_kit.json` v2.1 (consumed via `src/core/brand.py`). Saved memory: `project_font_hierarchy.md`.

| Family / weight | Use |
|---|---|
| Archivo Black 900 | Hook cards, intro/title cards, thumbnails, story cards |
| Archivo Bold 700 | Kinetic reel subtitles (replaces Space Grotesk SemiBold for `.subtitle`) |
| Instrument Serif Regular + Italic | Serif headlines, wordmark, carousel hook titles |
| Space Grotesk SemiBold | Carousel body copy in `readable_list` profile |
| Space Grotesk Bold 700 | Labels, kickers, chips, metadata, score badges, item indexes, source attributions (replaces JetBrains Mono Bold across every template) |

JetBrains Mono Bold is **removed** from the active brand system. Files are retained on disk for backwards compatibility but no template imports them. The earlier "3 fonts only" / "4 brand fonts only with Archivo Black scoped to short-form video burn-in" carve-out is gone.

When applying Space Grotesk Bold 700 to label/kicker/chip rules, add `text-transform: uppercase` + `letter-spacing: 0.06em-0.1em` to preserve the data-tag affordance lost when JetBrains Mono dropped out.

### Brand colours

PAPER `#F4F1E9`, INK `#0A0A0A` (open decision: project root `CLAUDE.md` references `#0A0A0A`, `SPEC_IMAGE_PIPELINE.md` §12 references `#0B0B0C` — final value lands in `brand/brand_kit.json` once the style guide migrates), ACCENT `#E6352A`, LIME `#C8DB45`, LILAC `#C4A9D0`. v2 additions: SKY `#C9D8E2`, AVAILABLE `#80EF80`, surface tokens `dark_bg`, `surface`, `elevated`, brand gradient at 90°.

Shadow: hard drop `2px 2px 0 rgba(0,0,0,0.5)`, no blur.

### Carousel layout profiles

Source of truth: `src/content/carousel_rules.py` -> `LAYOUT_PROFILES`. Two profiles, picked by `--layout-mode` on `pipelines/carousel/ship_carousel_post.py` or derived from `format_type` by the agent's `run_carousel`.

| Profile | Body font | Container | Char cap | Used by |
|---|---|---|---|---|
| `compact_legacy` | Archivo Black 900 (48px / 42px) | anchored bottom-left | 24 hard | fact slot; default for `--type=fact|news` direct CLI |
| `readable_list` | Space Grotesk SemiBold | half-box bottom 50%, JS auto-fit (64 → 28 px) | 56 hard | list slot; optional for news when explicitly selected |

Image scoring under `readable_list` runs `ImageSourcer(relax=True)`: R3 score floor drops 8 → 6 to admit moderately-confident candidates on item slides where named-subject metadata is weak. compact_legacy callers leave `relax=False`.

---

## When brain disagrees with code

Fix the code. Do not weaken the rule. Add to **[[gotchas]]** if a new failure mode is discovered.

## When uncertain

Stop and ask Toby. Do not silently work around a rule.

## ECC harness rules

The machine runs the `everything-claude-code` plugin. Standard rules apply:

- **Use ECC tools when the task fits.** Python review → `python-reviewer` or `/ecc:code-review`. Planning → `planner` or `/ecc:plan`. TDD → `tdd-guide`. Build/test fails → relevant `*-build-resolver` agent. Voice/brand writing → `brand-voice` with `/Users/Music/Developer/Mind/Brain/wiki/freelance/voice.md` and `brand.md` as the source. Name the tool in chat before invoking.
- **Brain authority wins over ECC stores.** Do not write Toby-specific facts (clients, rates, voice rules, project history) to ECC's MCP memory graph or via `/ecc:promote`. Generic factjot pipeline patterns are fine. Identity, voice, finances live in the Brain only.
- Brain path: `/Users/Music/Developer/Mind/Brain/`. Any other path is legacy.

## Related

[[gotchas]] · [[CRITICAL_FACTS]] · [[MEMORY_INDEX]] · [[PUBLISH_PLAN]] · [[rules/index]] · [[log]]
