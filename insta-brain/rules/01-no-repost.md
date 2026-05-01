# Rule 01 — Never repost a fact

## The rule
A claim that has been published once on @factjot may never be published again.

## Why
- The whole brand promise is "one fresh fact a day". Reposts kill that.
- Instagram's algorithm punishes repeat content.
- Toby would rather drop a day than ship a duplicate.

## How
1. Before generation, load `data/posted.jsonl` into a set of `claim_hash` values.
2. For each candidate fact, compute `sha256(normalise(claim))` where normalise = lowercase + collapse whitespace + strip leading/trailing punctuation.
3. If the hash exists in the set, skip the fact silently. Do not warn, do not retry. Move to the next.
4. After publish (in `scripts/publish_now.py`), append a new row to `posted.jsonl` for every slide's claim, including:
    - `claim_hash`
    - `claim` (full text, for human inspection)
    - `topic`, `category`
    - `post_id`, `ig_media_id`
    - `published_at` (ISO 8601 UTC)
    - `sources` (urls)

## Edge cases
- **Near-duplicate claims** (same fact, slightly different wording): the rarity-deduper in `src/research/fact_discovery.py::_too_similar` already drops claims with Jaccard ≥ 0.62 against accepted candidates within a single discovery batch. For across-session dedup, add a similarity check against the last 200 entries of `posted.jsonl` before accepting a new claim. (TODO: not yet implemented; for now, hash-only.)
- **Claim-text-changed-but-same-fact**: human responsibility. If you spot a near-duplicate, add the original `claim_hash` to a `aliases` field on the new row when shipping, so future similarity checks catch it.

## Source of truth
`data/posted.jsonl`. Append-only. Every line is one published fact. Never edit historical lines.
