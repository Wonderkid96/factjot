# Publishing & API Codemap

**Last Updated:** 2026-05-19  
**Modules:** `src/publish/`, `src/brain.py`, GitHub Actions state commits  
**Authority:** Instagram Graph API v18+, Meta Business Account setup  

---

## Publishing Architecture

```
Pipeline generates final artefact
  ├─ Carousel: 7 PNG slides
  ├─ Reel: MP4 + thumbnail PNG
  └─ Story: 1080×1920 PNG (optional)
        ↓
Publish step (src/publish/instagram_publisher.py)
  ├─ Upload images/video to host
  ├─ POST to Graph API /media (item containers)
  ├─ POST to Graph API /media (carousel parent)
  └─ POST to Graph API /media_publish (go live)
        ↓
Ledger step (src/brain.py + pipeline)
  ├─ Append to insta-brain/data/posted.jsonl
  ├─ Append to data/ledgers/used_images.jsonl
  └─ Commit state to git
        ↓
YouTube cross-post (reels only, scripts/upload_to_youtube.py)
  └─ Upload same MP4 as YouTube Short
```

---

## Instagram Graph API Publishing

### `instagram_publisher.py`

**Purpose:** Orchestrate Graph API calls to publish carousel or reel.

**Exports:**
- `InstagramPublisher` — Class wrapping Meta Graph API
  - `publish_carousel(png_list, caption, config) → ig_media_id`
  - `publish_reel(mp4_path, thumbnail_path, caption, config) → ig_media_id`
  - Returns: Instagram media ID (for ledger tracking)

**API calls (standard Instagram Graph API v18 flow):**

#### Carousel workflow:

```
POST /ig_user_id/media
  media_type: CAROUSEL
  children: [child_id1, child_id2, ...]
  caption: "..."
  → Returns: carousel_container_id

# For each child:
POST /ig_user_id/media
  media_type: IMAGE
  image_url: "https://imgbb..."
  is_carousel_item: true
  → Returns: child_id

POST /carousel_container_id/media_publish
  → Returns: ig_media_id (live post)
```

#### Reel workflow:

```
POST /ig_user_id/media
  media_type: REELS
  video_url: "https://tmpfiles..."
  thumbnail_url: "https://imgbb..."
  caption: "..."
  → Returns: reel_container_id

POST /reel_container_id/media_publish
  → Returns: ig_media_id (live post)
```

**Image hosting (input):**
- Carousel: Upload each PNG to imgbb → get public URL
- Reel: Upload MP4 to tmpfiles.org → get URL (or fallback Cloudinary if tmpfiles unavailable)
- Reel thumbnail: Upload PNG to imgbb → get URL

### Image Host: `image_host.py`

**Purpose:** Upload PNG/MP4 to a free public host and return URL.

**Exports:**
- `ImageHost` — Class wrapping image hosting APIs
  - `upload_image(png_path) → url` (via imgbb)
  - `upload_video(mp4_path) → url` (via tmpfiles.org, fallback Cloudinary)

**Providers:**

| Provider | Use | Auth | Cost | Rate limit |
|---|---|---|---|---|
| **imgbb** | PNG carousel slides + reel thumbnail | API key | Free (5 MB/day included) | 30 requests/min |
| **tmpfiles.org** | Reel MP4 (primary) | None (anonymous) | Free (≤ 5 MB per file) | 20 uploads/day per IP |
| **Cloudinary** | Reel MP4 fallback (disabled 2026-05-18) | API key + preset | Free tier exhausted | N/A |

**Error handling:**
- imgbb key missing: Fail fast (non-negotiable)
- tmpfiles.org full: Fallback to Cloudinary if enabled, else fail
- Cloudinary fallback disabled per CLAUDE.md (Meta 413'd videos even under 5 MB)
- Upload timeout (30s): Retry once, then fail

**Hard rule (from CLAUDE.md §18):** Raise Cloudinary fallback threshold to 5120 KB if re-enabled (true 5 MB vs 5000 KB).

### Configuration (`config`)

**Config keys expected:**
```python
{
    "INSTAGRAM_ACCOUNT_ID": "...",  # Numeric IG Account ID
    "META_ACCESS_TOKEN": "...",     # 60-day long-lived token
    "IMGBB_API_KEY": "...",         # imgbb API key
    # Optional:
    "CLOUDINARY_API_KEY": "...",    # Cloudinary key (if fallback enabled)
    "CLOUDINARY_UPLOAD_PRESET": "factjot",  # Preset name
}
```

---

## State Management (`src/brain.py`)

**Purpose:** Single API for reading + writing ledgers (posted, quotes, images).

**Exports:**
- `FactjotBrain` — Class wrapping all ledger operations
  - `read_posted_posts(limit=50)` → List of recent posts from `posted.jsonl`
  - `append_posted(post_data)` → Write to ledger
  - `check_duplicate(brief, angle)` → Has similar post been made? (fuzzy match)
  - `get_used_quotes()` → All quotes from `posted_quotes.jsonl`
  - `add_used_quote(quote_text)` → Append to ledger
  - `get_used_images()` → All images from `used_images.jsonl`
  - `is_image_used(url, sha256)` → Check image reuse

**Ledger files read:**
- `insta-brain/data/posted.jsonl` — Every published post
- `data/ledgers/used_images.jsonl` — Every image URL + SHA256
- `data/ledgers/used_footage_urls.jsonl` — Every video URL (reel)

---

## Ledger Discipline

### `insta-brain/data/posted.jsonl`

**Append-only ledger of every published post to Instagram.**

Entry (carousel):
```json
{
  "post_id": "123456789_456",
  "type": "carousel",
  "brief": "Three engineering disasters...",
  "slide_count": 7,
  "posted_at": "2026-05-19T08:30:00Z",
  "caption": "Three disasters killed more...",
  "category": "history",
  "image_urls": ["https://imgbb.com/...", ...],
  "used_quotes": ["The pattern..."],
  "entities": ["Banqiao Dam", "Chernobyl", "Bhopal"]
}
```

Entry (reel):
```json
{
  "post_id": "123456789_456",
  "type": "reel",
  "script": "Hook. Item 1...",
  "title": "Ignored Warnings",
  "posted_at": "2026-05-19T09:00:00Z",
  "caption": "Three disasters...",
  "duration_seconds": 25,
  "video_url": "https://tmpfiles...",
  "thumbnail_url": "https://imgbb...",
  "youtube_video_id": "dQw4w9WgXcQ"
}
```

**Hard rules:**
- Append-only (never delete or edit)
- Every published post captured (no exceptions)
- Used for agent's duplicate guard (prompt-level check before write)

### `data/ledgers/used_images.jsonl`

See images.md — Track URL + SHA256 to prevent image reuse.

### `data/ledgers/used_footage_urls.jsonl`

**Track every video URL used in reels (prevent footage reuse).**

Entry:
```json
{
  "url": "https://pexels.com/video/...",
  "posted_in_reel_id": "123456789_456",
  "posted_at": "2026-05-19T09:00:00Z",
  "duration_seconds": 8,
  "source": "pexels",
  "title": "Example Title"
}
```

---

## GitHub Actions State Commits

**When:** After successful publish (carousel or reel).

**What:** Git add + commit + push of ledger changes.

**Flow (in `autonomous-reel.yml`):**

```yaml
- name: Commit state
  if: success()
  run: |
    git config user.name "factjot-bot"
    git config user.email "noreply@github.com"
    git add -A  # Stage all changes (ledgers, cache)
    git commit -m "state: autonomous post $(date -u +%Y-%m-%dT%H:%M:%S)Z"
    git push
```

**Example commit message:**
```
state: autonomous post 2026-05-19T08:30:00Z

- carousel: 7 slides, 3 entities
- used_images: +1 entry
- posted.jsonl: +1 entry
```

**Ledger files included:**
- `insta-brain/data/posted.jsonl`
- `data/ledgers/used_images.jsonl`
- `data/ledgers/used_footage_urls.jsonl`
- `data/ledgers/api_usage_costs.jsonl`
- `data/ledgers/carousel_quality.jsonl`

**Hard rule (CLAUDE.md §1):** Never force-push to main. Force-push silently deletes state commits. Use a feature branch for large rewrites, pause workflows, then merge.

---

## YouTube Cross-Post (`scripts/upload_to_youtube.py`)

**When:** After reel publish to Instagram (soft step, does not block if fails).

**What:** Upload same MP4 as YouTube Short to @factjot YouTube account.

**Configuration:**
- **Account:** thefactjot@gmail.com (factjot's own Google account, separate from Toby's personal email)
- **Channel:** factjot YouTube (for revenue + long-form discoverability)
- **Auth:** OAuth 2.0 token stored in GitHub secret `YOUTUBE_API_KEY`
- **API:** YouTube Data API v3

**Workflow:**

```python
# After reel.mp4 published to IG:
yt_uploader = YouTubeUploader(api_key=YOUTUBE_API_KEY)
response = yt_uploader.upload_short(
    video_path="reel.mp4",
    title="Ignored Warnings",  # Same as IG caption
    description="Three disasters...\n\nWatch full reel: https://instagram.com/factjot",
    tags=["#shorts", "factjot", ...],  # Include #Shorts hashtag
    made_for_kids=False,
)
youtube_video_id = response["video_id"]

# Log to ledger
data/ledgers/youtube_uploads.jsonl.append({
    "reel_ig_id": "123456789_456",
    "youtube_video_id": youtube_video_id,
    "uploaded_at": datetime.now().isoformat(),
})
```

**Dedupe:** One reel → one YouTube Short (no duplication).

---

## API Error Handling

| Error | Cause | Recovery |
|---|---|---|
| 401 Unauthorized | Token expired | Soft step `refresh_token.py` retries before publish |
| 403 Forbidden | Token scopes missing | Fail; operator must re-authorize |
| 429 Rate Limited | Too many API calls | Exponential backoff (1s, 2s, 4s, give up) |
| 413 Payload Too Large | Video > 5 MB | Reject; reel already encoded at CRF 30, maxrate 800k |
| 400 Bad Request | Invalid carousel structure | Abort; surface shape error to agent |

**Idempotency:** Same image uploaded twice (same SHA) within 60 seconds returns cached URL (imgbb feature). This is safe; used for retries.

---

## Testing Publishing Locally

```bash
# Test Instagram publisher (dry-run, no upload)
python3 << 'EOF'
from src.publish.instagram_publisher import InstagramPublisher
from pathlib import Path

publisher = InstagramPublisher(
    account_id=os.getenv("INSTAGRAM_ACCOUNT_ID"),
    access_token=os.getenv("META_ACCESS_TOKEN"),
)

# Dry-run: print what would be uploaded, don't POST
carousel_pngs = [Path(f"output/test_slide_{i}.png") for i in range(7)]
caption = "Test carousel"

print("Would publish:")
for png in carousel_pngs:
    print(f"  - {png.name}")
EOF

# Test image host upload
python3 << 'EOF'
from src.publish.image_host import ImageHost
from pathlib import Path

host = ImageHost(imgbb_key=os.getenv("IMGBB_API_KEY"))

# Upload test image
test_png = Path("output/test_slide_0.png")
url = host.upload_image(test_png)
print(f"Uploaded to: {url}")
EOF

# Check ledger
python3 << 'EOF'
from src.brain import FactjotBrain

brain = FactjotBrain()
recent_posts = brain.read_posted_posts(limit=5)

for post in recent_posts:
    print(f"{post['posted_at']}: {post['type']} - {post.get('title', post.get('brief', ''))[:50]}")
EOF
```

---

## Related Documentation

- `CLAUDE.md` § 6 — Hard rules on auth, tokens, secrets
- `SPEC_FACTJOT_SYSTEM.md` § 5 — Lifecycle stages (Publish stage detail)
- `.github/workflows/autonomous-reel.yml` — Actual publish step commands
- `scripts/upload_to_youtube.py` — YouTube Short cross-post implementation
