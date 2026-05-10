# Publish plan — factjot

How content gets from idea to live on @factjot. Updated 2026-05-10 after the audit (Phases A–G).

---

## Scheduler: GitHub Actions (autonomous-reel.yml)

All posting runs on GitHub Actions (repo: Wonderkid96/factjot). The Mac is not required. Mac launchd jobs are ALL DISABLED. cron-job.org is gone — `CRON_TRIGGER_PAT` is no longer used by any active workflow. GitHub-native cron is the sole trigger.

| Slot | BST | UTC cron | Format | Tool the agent calls |
|---|---|---|---|---|
| `reel_morning` | 09:00 | `0 8 * * *` | Evergreen reel | `run_reel` |
| `list_midday` | 14:00 | `0 13 * * *` | List carousel | `run_carousel(format_type=list)` |
| `reel_night` | 20:30 | `30 19 * * *` | Evergreen reel | `run_reel` |

Cut from 5 slots to 3 on 2026-05-10 (audit Q4 quality bet, two-week distribution test before reassessment).

The breaking-news pipeline was killed in audit Phase G.2 (decision B). `news-watcher.yml` is deleted.

`autonomous-reel.yml` uses `concurrency.group: factjot-publish` with `cancel-in-progress: false`. Overlapping triggers queue, they do not cancel.

**Manual dispatch:** `workflow_dispatch` accepts `post_mode` (one of `reel_morning` / `list_midday` / `reel_night`) and `dry_run` (default `true`). `manual-run.yml` exists for prompt-driven manual reel/carousel runs.

---

## Reel flow

```
autonomous-reel.yml schedule fires
  → Resolve post mode from cron
  → Checkout, install Python 3.11 + FFmpeg + Playwright
  → Agent (Sonnet 4.6) reads recent posted.jsonl + reels.jsonl
    → Subject-fingerprint dedup (Phase C.3, Jaccard ≥ 0.6 against last 14 days)
    → Picks subject + writes script (≥70 words) + title
    → Calls run_reel(script=..., title=..., topic=...)
  → make_reel.py launches with --script and --title (mandatory; no auto-fallback)
    → Phase D.1 fact verification gate (Haiku consistency + Wikipedia anchors for numeric/named claims)
    → ElevenLabs TTS → 48 kHz audio (resampled before muxing)
    → Entity-first footage (Wikipedia / Wikimedia / Internet Archive) with Phase E.3 Haiku validation against the subject
    → Pexels / Coverr / Pixabay B-roll fills remaining slots
    → Playwright renders overlays (Archivo Black 900 hook + Archivo Bold 700 kinetic subtitles + Space Grotesk Bold 700 labels)
    → FFmpeg compose with hardcoded case_file_dynamic transitions
    → Phase E.4 Haiku-picks the best thumbnail frame, layers brand overlay
    → tmpfiles.org hosts MP4 (Cloudinary disabled — Meta's video fetcher 413'd it)
    → Instagram Graph API publishes Reel
    → Wait for IG story container status_code: FINISHED, then Story publishes
    → YouTube Data API uploads as Short with own description + own title (Phase F divergence) + sharper encode
  → Workflow stages each ledger separately (per-file `git add` with `if [ -e "$f" ]` guard so first cross-post does not abort)
  → git commit + git pull --rebase --autostash + git push
```

Key constraints:
- `--script` and `--title` are mandatory (Phase G.1 retired `rare_fact_bank.py` and the legacy `_pick_fact()` path).
- Audio must be 48 kHz (Meta rejects 44.1 kHz and 96 kHz).
- API polling at 15 s (not 3 s) to avoid rate limits.
- Final reel must be ≥35 s (hard abort otherwise).

---

## List carousel flow

```
autonomous-reel.yml list_midday slot fires
  → Agent (Sonnet 4.6) reads recent posted.jsonl
    → Subject-fingerprint dedup (Phase C.3)
    → Writes brief with declared criterion (Phase D.2 list format rule)
    → Calls run_carousel(format_type=list)
  → ship_carousel_post.py launches with --layout-mode readable_list
    → Phase D.1 fact verification gate (Haiku + Wikipedia)
    → Sonnet 4.6 carousel writer drafts items (Phase C.4 prompt cache, 5 min TTL)
    → Image sourcer (relax=True) finds candidate images per slot
    → Playwright renders slides (Space Grotesk SemiBold body in half-box auto-fit container)
    → Phase E.2 empty-cover variant uses typography-only layout if cover image fails
    → Voice normaliser (Phase C.1+C.2) cleans caption before publish
    → imgbb hosts each slide
    → Instagram Graph API publishes carousel
  → Workflow stages each ledger separately, commits, rebases, pushes
```

Key constraints:
- Lists need a defensible criterion. Briefs containing "fictional", "absurdity", "experiment" without justification fail at the format gate.
- Image fetcher must produce a real image or the renderer falls to typography-only — never a blank box.

---

## State persistence

After every Actions run, ledger files are committed back to `main` per the workflow's per-file guarded `git add`:

```
insta-brain/data/posted.jsonl
insta-brain/data/reels.jsonl
insta-brain/log.md
insta-brain/MEMORY_INDEX.md
data/ledgers/used_footage_urls.jsonl
data/ledgers/used_images.jsonl
data/ledgers/reel_performance.jsonl   (mutable — rewritten on each fetch)
data/ledgers/api_usage_costs.jsonl
data/ledgers/youtube_uploads.jsonl    (created on first cross-post)
data/ledgers/carousel_quality.jsonl   (created on first list post)
```

This is how the next run knows what's already been posted.

---

## Token refresh

Meta access token expires every ~60 days. Refresh manually via developers.facebook.com and update `META_ACCESS_TOKEN` in GitHub Secrets when needed. The previous Sunday weekly-plan auto-refresh was deleted with the rest of `weekly-plan.yml`. Meta System User permanent token is open work (manual setup in Meta Business Manager).

---

## What Toby does vs what the bot does

| Toby | Bot |
|---|---|
| Watch Actions tab for red runs | All generation, rendering, scheduling |
| Refresh Meta token every ~55 days | All publishing, dedup, metric pulling |
| Watch for over-saturated subjects in `posted.jsonl` if Phase C.3 dedup loosens | Subject-fingerprint dedup at Jaccard 0.6 against last 14 days |
| Check TikTok approval (pending) | Will dual-post once approved |

Toby never logs into Instagram to post.

---

## Related

[[CLAUDE]] · [[gotchas]] · [[CRITICAL_FACTS]] · [[MEMORY_INDEX]] · [[rules/index]] · [[log]]
