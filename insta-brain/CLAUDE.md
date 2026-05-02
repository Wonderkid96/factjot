# factjot brain — operating manual for any agent

You are working on **factjot**, an automated Instagram account posting daily carousels, Reels, and stories under @factjot.

If anything below contradicts a CLAUDE.md higher up the tree, the higher-level file wins for personal/voice rules; this file wins for factjot pipeline rules. For full technical docs, read `CLAUDE.md` at the project root.

---

## CRITICAL: brain must stay fresh

The freshness gate runs before every publish:
```
python3 scripts/check_brain_fresh.py
```

**This check blocks publishing if any source file is newer than `insta-brain/MEMORY_INDEX.md` or `insta-brain/log.md`.** It fails with exit 1. `publish_due.py` and `publish_now.py` refuse to post if it fails. On GitHub Actions all files have the same checkout mtime so the gate always passes — it is most relevant for local Mac development.

**You must update the brain immediately after any non-trivial code or pipeline change — not at session end, but the moment the change lands.** If you edit a src/ file and don't update MEMORY_INDEX.md and log.md, the next scheduled post will be blocked. This is intentional.

---

## Read order at session start

ALWAYS in this order before any code change or content generation:

1. `CLAUDE.md` (project root) — full technical documentation, pipeline, files, timing constants
2. `insta-brain/CLAUDE.md` (this file) — brain rules
3. `insta-brain/CRITICAL_FACTS.md` — invariants you must never break
4. `insta-brain/rules/index.md` — all rules with one-line summaries
5. `insta-brain/MEMORY_INDEX.md` — latest verified handover context (newest entry first)
6. `insta-brain/data/posted.jsonl` — every published fact (build in-memory set for dedup)
7. `data/ledgers/used_images.jsonl` — every image hash shipped (for image dedup)
8. `insta-brain/inbox.md` — Toby's drop-ins, process and clear

If a file does not exist, create it empty and continue. Do not skip the read.

## Startup continuity step (mandatory)

Immediately after the read order, append one line to `insta-brain/log.md`:
```
- YYYY-MM-DD HH:MM session start: read-order complete, working on <task>
```
Do this before any code edits, generation, scheduling, or publishing.

---

## Brain update rules — non-negotiable

### After every non-trivial code change (during session, not just at end):
1. Append to `insta-brain/log.md` — one terse line describing what changed
2. Append to `insta-brain/MEMORY_INDEX.md` — dated block: what, why, affected files, verification, routine impact
3. Run `check_brain_fresh.py` and confirm it exits 0 before continuing

### After every publish action:
- Reels: `insta-brain/data/reels.jsonl` is written automatically by `make_reel.py`
- Carousels: `insta-brain/data/posted.jsonl` is written automatically by `publish_due.py`
- Both write a line to `insta-brain/log.md` automatically

### At session end:
- Confirm `check_brain_fresh.py` passes
- Confirm log.md has a session-end summary line

### Never:
- Leave source files newer than MEMORY_INDEX.md or log.md
- Edit historical lines in any `.jsonl`
- Skip the freshness check before a publish

---

## What this project is

- **Instagram handle:** @factjot
- **Owner:** Toby Johnson (TJCreate), Lincoln UK
- **Daily schedule (GitHub Actions — laptop not required):**
  - 09:45 UTC: carousel morning (`carousel-morning.yml`)
  - 17:45 UTC: carousel evening (`carousel-evening.yml`)
  - 18:45 UTC: Reel + story (`reel.yml`)
  - Sunday 04:00 UTC: weekly plan + token refresh + discovery (`weekly-plan.yml`)
  - List posts: manual, whenever a pack is ready (`ship_list_post.py`)

---

## Strict invariants (never bend these)

1. **Never repost a fact.** Hash check `data/posted.jsonl` before generating.
2. **Never reuse a carousel image.** Hash check `data/ledgers/used_images.jsonl`.
3. **Every fact must be 100% true.** 2+ reputable sources, confidence ≥ 0.65.
4. **Never post a carousel slide without a real image.** No placeholders.
5. **ElevenLabs is the only paid service approved.** All others are free tiers. No new paid services without Toby's explicit approval.
6. **No em dashes.** Anywhere. Commas, full stops, parentheses, or rewrite.
7. **British English.** Colour, organise, centre, specialise.
8. **Append-only ledgers.** Never edit historical lines in any `.jsonl`.
9. **Read before write.** Load posted + used_images ledgers before generating.
10. **Reels use quirky_score=3 facts only.** Never use lower-scored facts for Reels.
11. **Brain must be fresh before any publish.** `check_brain_fresh.py` must exit 0.

---

## What the brain files are for

| File | Purpose |
|---|---|
| `CRITICAL_FACTS.md` | Top-level invariants and cadence |
| `rules/` | Full rule set (01-19) |
| `MEMORY_INDEX.md` | Handover ledger — what changed, when, why |
| `log.md` | Rolling activity log, newest at top |
| `inbox.md` | Toby's drop-ins — process and clear |
| `data/posted.jsonl` | All carousel facts published |
| `data/reels.jsonl` | All Reels published (reel_id, ig_media_id, claim, topic) |
| `data/queue.jsonl` | Brain mirror of the carousel approval queue |
| `data/stats.jsonl` | Per-post Instagram metrics over time |
| `data/trends.jsonl` | Weekly trending topic snapshots |
| `bank/<topic>.md` | Hand-curated gold-standard facts |
| `reports/weekly/` | Weekly performance reports |

---

## Codebase entry points the brain protects

| Concern | Code path | Brain interaction |
|---|---|---|
| Carousel discovery | `src/research/fact_discovery.py` | Reads `posted.jsonl` to filter already-shared claims |
| Image fetch | `src/research/image_fetcher.py` | Writes `data/ledgers/used_images.jsonl` |
| Carousel generation | `src/content/carousel_generator.py` | Voice rules from `rules/03-voice.md` |
| Reel script | `src/content/reel_script.py` | Narrative beat formatting |
| Reel title | `src/content/reel_title.py` | Documentary-style title generator |
| Reel caption | `src/content/reel_caption.py` | 3-tier hashtags + source credits |
| Footage | `src/research/video_finder.py` | Quality floor, dedup, relevance scoring |
| Reel composition | `src/render/reel_composer.py` | FFmpeg constants, timing |
| Carousel publish | `scripts/publish_due.py` | Writes `posted.jsonl` + `log.md` after publish |
| Reel publish | `scripts/make_reel.py` | Writes `reels.jsonl` + `log.md` after publish |
| Weekly planning | `scripts/plan_week.py` | Checks carousel + reel runway, trend scout, schedules 14 carousels |
| Metrics | `src/analytics/performance_tracker.py` | Writes `data/stats.jsonl` |

---

## Voice

Direct, dry, factual. No "did you know" preamble. No corporate fluff. No em dashes. British English. Captions: title hook + punchline body + CTA + source credits + hashtags.

---

## When brain disagrees with code

Fix the code. Do not weaken the rule. Update `rules/index.md` if a new rule emerges.

## When uncertain

Stop and ask Toby. Do not silently work around a rule.

---

## Related

[[CRITICAL_FACTS]] · [[MEMORY_INDEX]] · [[PUBLISH_PLAN]] · [[rules/index]] · [[log]] · [[inbox]]
