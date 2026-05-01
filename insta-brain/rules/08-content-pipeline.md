# Rule 08 — The content pipeline

## The five stages

```
1. DISCOVER  →  2. VERIFY  →  3. GENERATE  →  4. APPROVE  →  5. PUBLISH
```

A post does not skip stages. Every transition writes to the brain.

## 1. Discover
- **Code:** `src/research/fact_discovery.py`
- **Inputs:** topic list (cli arg), `bank/*.md`, Wikipedia REST summaries, `posted.jsonl` (for repost dedupe).
- **Output:** list of `FactCandidate` objects — claim text, sources, rarity score.
- **Brain reads:** `posted.jsonl` (skip already-shipped claims by hash).

## 2. Verify
- **Code:** `src/verification/fact_checker.py`
- **Gate:** ≥ 2 sources, confidence ≥ 0.65, no contradiction flags, has concrete anchor.
- **Output:** `VerifiedFact` objects only (unverified ones are dropped silently).
- **Brain reads:** none (verification is stateless).

## 3. Generate
- **Code:** `src/content/carousel_generator.py`
- **Builds:** `CarouselPost` with slides (`[i]…[/i]` and `[h]…[/h]` markup), caption, hashtags, image queries per slide.
- **Brain reads:** `bank/*.md` for voice/style examples (future), `rules/03-voice.md` for banned phrases.
- **Brain writes:** `data/queue.jsonl` row with `status: "draft"`.

## 4. Approve
- **Code:** `src/review/approval_queue.py`, `scripts/review_queue.py`
- **Human gate.** Toby reads each post bundle (caption + each slide PNG) and either approves or kills it.
- **Approved posts** get a `scheduled_for` timestamp.
- **Brain writes:** updates the same `queue.jsonl` row to `status: "approved"` (then `"scheduled"`).

## 5. Publish
- **Code:** `scripts/publish_now.py` (manual) or `scripts/publish_due.py` (cron).
- **Steps:** upload PNGs to imgbb → create child media containers → create carousel container → publish.
- **Brain writes:**
  - `posted.jsonl`: one row per slide claim, with the IG `media_id`.
  - `queue.jsonl`: row updated to `status: "published"`.
  - `log.md`: `2026-04-29 10:00 published abc123 (SPACE, 6 slides, ig_media=178…)`.

## After publish
- A nightly job (`scripts/fetch_metrics.py`, TBD) hits the IG insights endpoint per post and appends to `stats.jsonl`.
- A weekly summary in `reports/weekly/<iso-week>.md` aggregates stats and surfaces the top 3 posts and any flat performers.

## Failure modes and where they go
- **Image fetcher gave up** → `queue.jsonl.status = qa_failed: missing_image_<n>`. Held for human review.
- **API publish failed** → row in `data/publish_failures.jsonl` with the full Meta error body. Retried up to 3 times with exponential backoff. After that, escalated to Toby.
- **Token expired** → publish stops, `log.md` gets a single line, Toby refreshes via `scripts/refresh_token.py` (TBD).
