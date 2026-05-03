# factjot brain — operating manual for any agent

You are working on **factjot**, an automated Instagram account posting daily carousels, Reels, and stories under @factjot.

If anything below contradicts a CLAUDE.md higher up the tree, the higher-level file wins for personal/voice rules; this file wins for factjot pipeline rules. For full technical docs, read `CLAUDE.md` at the project root.

---

## CRITICAL: read this before touching anything

1. `CLAUDE.md` (project root) — full technical docs, pipeline, timing, file map
2. **[[gotchas]]** (`gotchas.md`) — incident log: everything that has broken or failed. Read before every change; append when you find a new failure mode.
3. **[[CRITICAL_FACTS]]** — invariants you must never break
4. **[[MEMORY_INDEX]]** — latest handover context

---

## What this project is

Fully automated Instagram account. **The Mac does not need to be on.**

- **Morning carousel** — 10:00 BST (09:00 UTC) via `carousel-morning.yml`
- **Reel** — 12:00 BST (11:00 UTC) via `reel.yml`
- **Evening list carousel** — 18:00 BST (17:00 UTC) via `list-carousel.yml`
- **Weekly prep** — Sunday 04:00 BST (03:00 UTC) via `weekly-plan.yml`

All posts fire via **cron-job.org** (primary, reliable) dispatching GitHub Actions. GitHub's own crons are backup only. All launchd jobs are DISABLED.

---

## Daily automation at a glance

| Time (UTC) | Workflow | Script | Content type |
|---|---|---|---|
| 09:00 | carousel-morning.yml | ship_first_post.py --topic X | Fact carousel, topic rotates by weekday |
| 11:00 | reel.yml | make_reel.py | Reel + thumbnail + story |
| 17:00 | list-carousel.yml | ship_list_post.py --next | Film/TV list carousel |
| 03:00 Sun | weekly-plan.yml | restock.py + prepare_packs.py | Discovery, prep, token refresh |

Backup crons fire at +45 min. Idempotency check (git pull then check_posted_today.py) prevents double-posting if both trigger.

---

## Posting pipeline — how each type works

### Morning carousel (`ship_first_post.py`)
- Picks an unposted fact for the day's topic with `quirky_score >= 2`
- Falls back to other topics if primary is exhausted (quality floor maintained)
- Emergency fallback to score=1 only if ALL topics are exhausted (logs warning)
- Renders via Playwright, uploads to imgbb, posts to Instagram
- Commits `posted.jsonl` + `used_images.jsonl` to git

### Reel (`make_reel.py`)
- Picks unposted q3 fact with curated `reel_script` (>=70 words) + `reel_title`
- Entity-first footage: Wikipedia lead image, Wikimedia Commons, Internet Archive (Tier 0)
- Fills remaining clips from Pexels / Coverr / Pixabay B-roll
- ElevenLabs TTS, FFmpeg composition, branded thumbnail + story PNG
- Posts reel to Instagram, then immediately posts story
- Commits `reels.jsonl` + `used_footage_urls.jsonl` to git

### Evening list carousel (`ship_list_post.py --next`)
- Picks next unposted pack from `src/content/list_packs.py`
- **Cache-first:** if `data/ledgers/list_pack_cache.jsonl` has pre-built imgbb URLs for
  this pack (prepared by Sunday's `prepare_packs.py`), skips TMDB + render + imgbb
  entirely and posts directly. Reduces post time from ~5 min to ~30 sec.
- On cache miss: resolves TMDB, renders via Playwright, uploads to imgbb, posts
- Commits `posted.jsonl` + `list_pack_cache.jsonl` to git

### Sunday weekly prep (`weekly-plan.yml`)
- Refresh Meta access token (`refresh_token.py`)
- Discover new facts from Reddit TIL (`restock.py` — includes discovery + runway report)
- **Pre-build list packs** (`prepare_packs.py`) — resolves all unposted packs via TMDB
  (parallelised), renders slides, uploads to imgbb, writes to `list_pack_cache.jsonl`
- Validate reel fact bank (`validate_reel_facts.py`)
- Prune old caches (`cleanup_caches.py`)
- Commits everything to git

---

## Brain data ledgers — what lives where

| File | Written by | Read by | Committed to git |
|---|---|---|---|
| `insta-brain/data/posted.jsonl` | ship_first_post, ship_list_post | brain.is_fact_posted(), check_posted_today.py | YES — every post workflow |
| `insta-brain/data/reels.jsonl` | make_reel.py | brain.list_reel_claims(), check_posted_today.py | YES — reel workflow |
| `insta-brain/data/posted_quotes.jsonl` | ship_first_post.py | QuoteBank | YES — carousel workflows |
| `data/ledgers/used_images.jsonl` | image_fetcher.py (via paths.py) | brain.images (UsedImageLedger) | YES — all posting workflows |
| `data/ledgers/used_footage_urls.jsonl` | make_reel.py | make_reel.py (global registry) | YES — reel workflow |
| `data/ledgers/discovered_facts.jsonl` | discover_facts.py | load_all_facts() | YES — weekly-plan workflow |
| `data/ledgers/list_pack_cache.jsonl` | prepare_packs.py | ship_list_post.py | YES — weekly-plan + list-carousel |
| `insta-brain/log.md` | all scripts | agents | YES — all workflows |

**Git is the database.** Every important state file is committed to git after every workflow run. The runner is destroyed after each run — nothing persists except what's in git and on imgbb/tmpfiles servers.

---

## Strict invariants — never break these

1. Never repost a fact — `brain.assert_no_duplicate()` called immediately before every Instagram API call in all three posting scripts.
2. Never reuse a carousel image — `data/ledgers/used_images.jsonl` (git-tracked, committed after each post).
3. Every fact must be 100% true — 2+ reputable sources, confidence >= 0.65.
4. No em dashes anywhere — in copy, code comments, or YAML. GitHub's Go parser rejects them in YAML. Use hyphens.
5. British English throughout all copy.
6. Append-only ledgers — never edit historical lines in any `.jsonl`.
7. Three fonts only — Instrument Serif, Space Grotesk SemiBold, JetBrains Mono Bold.
8. Reels use `quirky_score=3` facts only (fallback to q2 only when q3 exhausted).
9. All q3 facts must have curated `reel_script` (>=70 words) and `reel_title`. No auto-fallback.
10. Carousels require `quirky_score >= 2` (MIN_CAROUSEL_SCORE). Score=1 facts never post unless all topics exhausted.
11. `MIN_UPVOTES = 10_000` in discover_facts.py. Do not lower.
12. Minimum footage clip size: 2MB. Minimum duration: 4s. Do not lower.

---

## Voice and brand

Direct, dry, factual. No "did you know" preamble. No corporate fluff. No em dashes. British English. Captions: title hook + punchline body + CTA + source credits + hashtags.

Wordmark: `fact`*`jot*`.` — "jot" italic, "." in `#E6352A`, base off-white `#EDE8DD`.

---

## When brain disagrees with code

Fix the code. Do not weaken the rule. Add to **[[gotchas]]** if a new failure mode is discovered.

## When uncertain

Stop and ask Toby. Do not silently work around a rule.
