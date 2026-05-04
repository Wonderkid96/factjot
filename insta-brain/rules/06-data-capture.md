# Rule 06 — Data capture

## The rule
After every meaningful action, the brain gets updated. No action is "done" until its trace is in the brain.

## What writes where

| Action | File appended | Schema |
|---|---|---|
| A fact is generated into a draft post | `insta-brain/data/queue.jsonl` | `{post_id, category, slides, caption, hashtags, render_paths, status: "draft"}` |
| A draft is approved | update existing `queue.jsonl` row → `status: "approved"`, add `scheduled_for` | (rewrite that row only) |
| An image is downloaded and saved | `data/used_images.jsonl` (root) | `{url, sha256, provider, post_id, slide_index, query, ts}` |
| A post is published to Instagram | `insta-brain/data/posted.jsonl` (one row per slide claim) | `{claim_hash, claim, topic, category, post_id, ig_media_id, published_at, sources}` |
| Per-post Instagram metrics fetched | `insta-brain/data/stats.jsonl` | `{post_id, ig_media_id, checked_at, impressions, reach, saves, shares, comments, likes, follows}` |
| A weekly trends scrape runs | `insta-brain/data/trends.jsonl` | `{snapshot_at, source, topic, score}` |
| Any non-trivial agent action | `insta-brain/log.md` | one line, prefixed with date+time, newest at top |
| Any non-trivial behaviour/rules/schema change | `insta-brain/MEMORY_INDEX.md` | dated block with what, why, affected files, verification |
| Local or CI **`make_reel.py`** run (milestones) | `data/cache/reels/<reel_id>/pipeline.log` | human-readable trace; also **`logs/reel_runs/<UTC>_<id>.log`** (copy via `ReelRunLogger`) |
| FFmpeg compose diagnostics | `data/cache/reels/<reel_id>/ffmpeg_compose_stderr.log` + `ffmpeg_debug.txt` | stderr tail on failure; full command + filter graph in debug file |

## Append-only invariant
None of the `.jsonl` files is rewritten in place. New row, every time. The only exception: `queue.jsonl` rows are mutable in status only (draft → approved → scheduled → published / failed). Even then, we don't delete; we mark.

## When to mirror
- `data/used_images.jsonl` lives at the project root because the image fetcher writes it during render.
- `insta-brain/data/used_images.jsonl` is a symlink (or rsync-on-publish) so agents reading the brain can see image history without traversing the codebase.

## Read order at the start of every run
1. `insta-brain/CLAUDE.md`
2. `insta-brain/CRITICAL_FACTS.md`
3. **[[gotchas]]** (`gotchas.md`) — incident log; same content as rule 09 step 5
4. `insta-brain/rules/index.md`
5. `insta-brain/MEMORY_INDEX.md`
6. `insta-brain/data/posted.jsonl` → in-memory set of `claim_hash`
7. `data/used_images.jsonl` → in-memory sets of `url` and `sha256`
8. `insta-brain/inbox.md`

## When the data file is missing
Create empty. Do not skip the read. An empty file means "we have not posted anything yet" — that is fine.

## When a row fails to write
Treat it as a critical error. Do not consider the action complete. Retry the write. If it still fails, the brain is in an inconsistent state — alert Toby and stop publishing until resolved.
