# Rule 05 — Publishing

## The rule
We publish via Instagram Graph API only. Free tools, no paid services.

## API used
**Instagram Graph API (Meta)**, version `v21.0` (configurable via `META_GRAPH_VERSION`).

### Account requirements (one-time setup)
- Instagram Professional account (Business or Creator) at @factjot.
- Linked to a Facebook Page Toby controls.
- Meta Developer app with `instagram_content_publish`, `instagram_basic`, `pages_read_engagement` permissions.
- Long-lived access token (expires ~60 days, must refresh).

### Required env vars
```
INSTAGRAM_ACCOUNT_ID=<numeric IG user id>
FACEBOOK_PAGE_ID=<numeric FB page id>
META_ACCESS_TOKEN=<long-lived token>
META_GRAPH_VERSION=v21.0
IMGBB_API_KEY=<free key from api.imgbb.com>
TIMEZONE=Europe/London
```

### Carousel publish flow (in `scripts/publish_now.py`)
1. Read post bundle from `data/posts/<post_id>/post.yaml` and slides from `data/posts/<post_id>/slides/`.
2. Upload each slide PNG to imgbb (free, no quota for our scale). Returns a public URL.
3. POST to `/{ig-user-id}/media` for each public URL with `is_carousel_item=true` → child container IDs.
4. POST to `/{ig-user-id}/media` with `media_type=CAROUSEL`, `children=<comma-separated ids>`, `caption=<full caption>` → carousel container ID.
5. POST to `/{ig-user-id}/media_publish` with `creation_id=<carousel id>`.
6. On success: append to `insta-brain/data/posted.jsonl` (one row per slide claim), update `data/queue.jsonl` row status to `published`, append a one-line entry to `insta-brain/log.md`.
7. On failure: append to `data/publish_failures.jsonl` with the API error, retry with exponential backoff up to 3 times.

## Image hosting
**imgbb is the default.** Free, no expiry, simple POST upload. One env var: `IMGBB_API_KEY`.

Alternative free hosts the code can swap to if imgbb ever rate-limits us:
- GitHub Pages bucket (push PNG, get raw.githubusercontent.com URL)
- Cloudflare R2 (10 GB free)
- ImageKit free tier

We never pay for hosting. The image needs to live publicly only for the few minutes Meta fetches it. After publish, we could delete the imgbb upload, but imgbb's free quota is so generous we don't bother.

## Hard limits (Instagram)
- 10 slides per carousel
- 2,200 characters per caption
- 30 hashtags per caption
- 25 posts per IG user per 24h via API (more than enough for daily)
- Image: JPEG, ratio 4:5 to 1.91:1, min 320px wide, max 8 MB

## Cadence and rate limiting
- Default: 1 post/day at 10:00 local time (`TIMEZONE`).
- Never publish more than 2 posts in any 24h window via the bot.
- Manual publishes from the IG app don't count against API limit but should still be spaced.

## Token refresh
Long-lived tokens expire after ~60 days. Refresh weekly via `GET /oauth/access_token` with `grant_type=fb_exchange_token`. Schedule: `scripts/refresh_token.py` (cron / launchd, not yet wired).

## Never
- Use private/unofficial Instagram APIs.
- Use browser automation against instagram.com.
- Pay a third-party scheduler (Buffer, Later, Hootsuite, etc) for what Graph API does free.
- Skip the duplicate checks in rules 01 and 02 to "save time".
