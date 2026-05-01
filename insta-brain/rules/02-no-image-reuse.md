# Rule 02 — Never reuse an image

## The rule
An image that has been published once may never be published again.

## Why
- Visual reuse is the second most obvious sign of a "lazy" content account.
- We pull from many free sources (Pexels, Pixabay, Openverse, Wikipedia, Commons). Without dedupe, the same Wikipedia article keeps surfacing the same photo.

## How
1. The ledger is `data/used_images.jsonl`. One line per saved image, with both:
    - `url` (where we fetched it from)
    - `sha256` (hash of the raw image bytes)
2. `src/research/used_images.py::UsedImageLedger` is the single API. `is_used(url, sha256)` returns true if either matches.
3. `src/research/image_fetcher.py` checks the ledger before returning a candidate. If matched, the candidate is skipped and the next result tried.
4. After a successful save, `mark_used(...)` is called atomically to add both URL and SHA to the in-memory set and append a row to disk.

## Sources iterated, in order
1. Pexels API (free key)
2. Pixabay API (free key)
3. Openverse (no key, aggregates Flickr + Wikimedia + others)
4. Wikipedia opensearch + REST summary lead image
5. Wikimedia Commons file search

## Why both URL and content hash
Same image often shows up at multiple URLs (Wikipedia thumbnail, Commons original, Flickr resized). Pixel hash catches duplicates the URL would miss.

## Edge cases
- **Heavily compressed re-encodes**: a JPEG re-saved at a different quality has a different SHA. We accept this as a known limitation; near-duplicate detection at the pixel level is too costly. Live with rare visual repeats from re-encoded variants.
- **Cached file already on disk**: `data/images/<category>/<key>.jpg`. The cache is keyed by query, so a previously fetched image for the same query is reused (this is fine — it's the same post). The dedupe ledger only matters across posts.

## Source of truth
`data/used_images.jsonl`. Append-only.
