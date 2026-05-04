# Publish plan — factjot

How content gets from idea to live on @factjot. Updated 2026-05-05.

---

## Scheduler: GitHub Actions

All posting runs on GitHub Actions (repo: Wonderkid96/factjot). The Mac is not required. Mac launchd jobs are ALL DISABLED as of 2026-05-02. **cron-job.org** remains the primary fire-at-wall-clock trigger; GitHub crons are backup (see root `CLAUDE.md`).

| Workflow | Cron (UTC) | Script | What it posts |
|---|---|---|---|
| `carousel-morning.yml` | 09:00 (+ 09:45 backup) | `ship_first_post.py --topic X` | Morning carousel |
| `reel.yml` | 11:00 (+ 11:45 backup) | `make_reel.py` | Reel + story |
| `list-carousel.yml` | 17:00 (+ 17:45 backup) | `ship_list_post.py --next` | Evening list carousel |
| `weekly-plan.yml` | 03:00 Sunday | `refresh_token.py`, `restock.py`, `generate_list_packs.py`, `prepare_packs.py`, `validate_reel_facts.py`, `cleanup_caches.py` | Weekly prep |

Topics rotate by weekday (morning and evening use offset sets so the same category never posts twice in one day).

**Manual `reel.yml` dispatch:** **`workflow_dispatch`** accepts **`force`** (boolean). Default **`false`**: `check_posted_today.py reel` still runs; if a reel is already logged for that calendar day, the **Post reel** step is **skipped** (expected, green workflow). **`force: true`** bypasses that check for emergencies only (can ship a **second** reel the same day if the rest of the pipeline succeeds).

---

## Carousel flow

```
ship_first_post.py --topic X
  ← picks next unused fact from curated bank + discovered feed
  ← renders 5-6 slides via Playwright (HTML → PNG)
  ← uploads each slide to imgbb
  ← creates carousel container via Instagram Graph API
  ← polls until FINISHED, then publishes
  → writes to insta-brain/data/posted.jsonl
  → writes to insta-brain/log.md
```

Dedup: `brain.is_fact_posted()` + `assert_no_duplicate()` hard gate before every publish.

---

## Reel flow

```
make_reel.py
  ← picks q3 fact (quirky_score=3, has curated reel_script ≥70 words + reel_title)
  ← ElevenLabs TTS → voice MP3 + word timestamps
  ← Pexels/Coverr/Pixabay → 8 footage clips
  ← Playwright → overlay PNGs (label, title, subtitles, CTA)
  ← FFmpeg → final.mp4 (48 kHz AAC, libx264 crf 30 + maxrate 800k for Meta ~5 MB cap)
  ← tmpfiles.org → short-lived public MP4 URL (Meta fetches within publish poll window)
  ← imgbb → thumbnail + story PNG URLs
  ← Instagram Graph API → publish Reel
  ← Instagram Graph API → publish Story
  → writes to insta-brain/data/reels.jsonl + posted.jsonl
  → writes to insta-brain/log.md
```

Key constraints:
- Only `quirky_score=3` facts used
- `reel_script` ≥70 words required (hard abort otherwise)
- Final reel must be ≥35s (hard abort otherwise)
- API polling: 15s intervals (not 3s) to avoid rate limits
- Run `scripts/validate_reel_facts.py` after any fact bank edit

---

## State persistence

After every Actions run, ledger files are committed back to `main`:
```
insta-brain/data/posted.jsonl
insta-brain/data/reels.jsonl
insta-brain/data/posted_quotes.jsonl
insta-brain/log.md
data/approval_queue.jsonl
```
This is how the next run knows what's already been posted.

---

## Token refresh

Meta access token expires every ~60 days. Sunday workflow runs `refresh_token.py` automatically. If it expires before Sunday, update `META_ACCESS_TOKEN` in GitHub Secrets manually via developers.facebook.com.

---

## What Toby does vs what the bot does

| Toby | Bot |
|---|---|
| Watch Actions tab for red runs | All generation, rendering, scheduling |
| Refresh Meta token every ~55 days | All publishing, dedup, metric pulling |
| Add new q3 facts when runway low | Weekly fact discovery from Reddit TIL |
| Add facts with reel_script + reel_title | Validate via `validate_reel_facts.py` |
| Check TikTok approval (pending) | Will dual-post once approved |

Toby never logs into Instagram to post.

---

## Related
[[CLAUDE]] · [[gotchas]] · [[CRITICAL_FACTS]] · [[MEMORY_INDEX]] · [[rules/index]] · [[log]]
