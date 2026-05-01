# End-to-end publish plan

How a fact gets from "idea" to "live on @factjot". One-time setup at the top, weekly + daily flows below.

---

## ONE-TIME SETUP (≈ 30 min, all free)

### A. Free image hosts (improves photo quality, optional but recommended)
1. Sign up at https://www.pexels.com/api/ → get an API key (instant).
2. Sign up at https://pixabay.com/api/docs/ → get an API key (instant).
3. Sign up at https://api.imgbb.com/ → get an API key (instant). **This one is required for posting.**

### B. Meta / Instagram Graph API (the only sanctioned way to post)
1. Convert @factjot to an Instagram Professional account (Business or Creator). In the IG app: Settings → Account → Switch to Professional.
2. Link @factjot to a Facebook Page Toby controls. Meta Business Suite → Settings → Accounts → Instagram → Add.
3. Create a Meta Developer app at https://developers.facebook.com/apps/. App type: "Business".
4. In the app, add the **Instagram Graph API** product.
5. Generate a **long-lived access token** with these scopes: `instagram_content_publish`, `instagram_basic`, `pages_read_engagement`, `pages_show_list`. Use the Graph API Explorer or the OAuth flow.
6. Note the numeric Instagram User ID and Facebook Page ID (visible in Meta Business Suite or via `/me/accounts` API call).

### C. Drop credentials into `.env`
```
INSTAGRAM_ACCOUNT_ID=178...
FACEBOOK_PAGE_ID=104...
META_ACCESS_TOKEN=EAAG...
META_GRAPH_VERSION=v21.0
TIMEZONE=Europe/London
IMGBB_API_KEY=...
PEXELS_API_KEY=...
PIXABAY_API_KEY=...
```

### D. Verify setup
```
python3 scripts/check_meta_setup.py
```
Reports each var as OK or MISSING, confirms the token works.

---

## WEEKLY GENERATION (run Sunday or Monday morning)

```
python3 scripts/plan_week.py
```

What it does, in order:
1. Reads `insta-brain/data/posted.jsonl` and `data/used_images.jsonl` so it never repeats.
2. Picks 7 topics (rotating through a curated topic pool stored in `config/pipeline.yaml::weekly_topics`).
3. For each topic, runs the pipeline:
    - **Discover**: Wikipedia REST + curated `bank/<topic>.md`, dedupes against `posted.jsonl`.
    - **Verify**: ≥ 2 sources, confidence ≥ 0.65 (rule 10).
    - **Generate**: 5 fact slides + 1 closing wholesome-quote slide, ≤ 60 words each, with auto `[i]…[/i]` and `[h]…[/h]` highlights.
    - **Render**: HTML → Playwright → 7 PNGs (one per slide) at 1080×1350 retina. Each slide gets its own fresh, on-topic image. If any slide can't get one, the post is held for review (rule 11).
    - **Bundle**: write `data/posts/<post_id>/post.yaml` (caption, hashtags, schedule) and `data/posts/<post_id>/slides/01..07.png`.
4. Schedules each post for the next 7 days at the optimal slot:
    - Mon-Fri: 10:00 local time
    - Sat-Sun: 11:00 local time
    - (Both proven IG sweet spots for educational accounts in 2026.)
5. Appends every queued post to `insta-brain/data/queue.jsonl` with `status: "scheduled"`.
6. Prints a one-screen summary: 7 post titles, scheduled times, any QA failures.

Toby reviews the bundles in `data/posts/`, eyeballs the PNGs and captions, and either approves or kills any. Killed posts get `status: "killed"`.

---

## DAILY AUTO-PUBLISH (runs in background)

A macOS launchd job fires every 15 minutes:
```
~/Library/LaunchAgents/com.tjcreate.factjot.publish.plist
```
which calls:
```
python3 scripts/publish_due.py
```

What `publish_due.py` does:
1. Reads `queue.jsonl`, finds posts where `scheduled_for <= now` and `status == "scheduled"`.
2. For each due post:
    - Checks rules 01 + 02 + 10 + 11 again as a final guard.
    - Uploads each slide PNG to imgbb → public URL (no quota concerns at our scale).
    - Calls `POST /{ig-user-id}/media` for each PNG with `is_carousel_item=true` → child container IDs.
    - Calls `POST /{ig-user-id}/media` with `media_type=CAROUSEL`, `children=<ids>`, `caption=<full caption>` → carousel container ID.
    - Polls `GET /{carousel-id}?fields=status_code` until `FINISHED` (usually <30s).
    - Calls `POST /{ig-user-id}/media_publish` with `creation_id=<carousel id>` → `ig_media_id`.
3. On success:
    - Appends one row per slide claim to `insta-brain/data/posted.jsonl`.
    - Records the closing quote in `insta-brain/data/posted_quotes.jsonl`.
    - Updates the queue row to `status: "published"` with the `ig_media_id`.
    - Appends a single line to `insta-brain/log.md`.
4. On failure:
    - Appends to `data/publish_failures.jsonl` with the full Meta error body.
    - Retries with exponential backoff up to 3 times.
    - After 3 failures, marks the row `status: "publish_failed"` and stops; Toby sees it on next review.

---

## NIGHTLY METRICS (also via launchd)

22:00 daily:
```
python3 scripts/fetch_metrics.py
```
- For every `posted.jsonl` entry less than 7 days old, hits `GET /{ig-media-id}/insights`.
- Appends to `insta-brain/data/stats.jsonl` (impressions, reach, saves, shares, comments, likes, follows).

---

## WEEKLY REPORT (runs Sunday 23:00)

```
python3 scripts/weekly_report.py
```
- Aggregates the last 7 days of `stats.jsonl`.
- Writes `insta-brain/reports/weekly/<iso-week>.md`.
- Surfaces: best-performing post, worst-performing post, follower delta, cumulative reach.

---

## TOKEN REFRESH (every 50 days)

Long-lived tokens last ~60 days. A reminder fires from `scripts/refresh_token.py` (TBD) which calls `GET /oauth/access_token?grant_type=fb_exchange_token` and rewrites `.env`.

---

## WHAT TOBY DOES VS WHAT THE BOT DOES

| Toby | Bot |
|---|---|
| One-time Meta + image-host setup | All discovery, verification, generation |
| Weekly: skim `data/posts/<post_id>/` and approve | All rendering, scheduling |
| Add new ideas to `insta-brain/inbox.md` | All publishing, dedupe, metric pulling |
| Refresh access token every ~50 days | All weekly + nightly reports |
| Edit `bank/*.md` for gold-standard facts | Never invents a fact, never reposts |

That's the full loop. Toby never logs into Instagram to post. He approves, the bot ships.
