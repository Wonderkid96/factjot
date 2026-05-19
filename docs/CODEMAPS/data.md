# Data & State Codemap

**Last Updated:** 2026-05-19  
**Locations:** `data/ledgers/` (append-only), `insta-brain/data/` (git-tracked), `output/` (per-run, gitignored)  
**Authority:** `SPEC_FACTJOT_SYSTEM.md` § 11 (ledger discipline)  

---

## Data Layer Architecture

```
┌─────────────────────────────────────────────┐
│  Git-tracked state                          │
├─────────────────────────────────────────────┤
│  insta-brain/data/posted.jsonl              │ Every IG post ever published
│  data/ledgers/                              │ Append-only records
│    ├── used_images.jsonl                    │ Every image posted + metadata
│    ├── used_footage_urls.jsonl              │ Every reel video URL posted
│    ├── api_usage_costs.jsonl                │ API costs per run
│    ├── youtube_uploads.jsonl                │ IG reel → YT Short mappings
│    ├── reel_performance.jsonl               │ IG engagement (mutable!)
│    └── carousel_quality.jsonl               │ Carousel generation diagnostics
├─────────────────────────────────────────────┤
│  Per-run output (gitignored)                │
├─────────────────────────────────────────────┤
│  output/{pipeline}/YYYY-MM-DD_HH-MM_{}/    │ Rendered artefacts
│    ├── carousel.json                        │ Carousel metadata
│    ├── slides/                              │ PNG slides (carousel)
│    ├── reel.mp4                             │ MP4 video (reel)
│    ├── reel_thumbnail.png                   │ Thumbnail PNG (reel)
│    └── pipeline.log                         │ Debug log
└─────────────────────────────────────────────┘
```

---

## Ledgers (Git-tracked, Append-only)

### `insta-brain/data/posted.jsonl`

**Purpose:** Single source of truth for all published Instagram posts.

**Entry format (carousel):**
```json
{
  "post_id": "17975927492999999_456",
  "type": "carousel",
  "posted_at": "2026-05-19T08:30:00Z",
  "brief": "Three engineering disasters that killed more people...",
  "caption": "Three disasters killed more people than many wars, and each one followed ignored warnings...",
  "category": "history",
  "slide_count": 7,
  "layout_mode": "readable_list",
  "image_urls": [
    "https://commons.wikimedia.org/wiki/File:...",
    "https://commons.wikimedia.org/wiki/File:...",
    ...
  ],
  "entities": ["Banqiao Dam", "Chernobyl", "Bhopal"],
  "used_quotes": ["The pattern is not bad luck, it is systems choosing to ignore known risk."]
}
```

**Entry format (reel):**
```json
{
  "post_id": "17975927492999999_456",
  "type": "reel",
  "posted_at": "2026-05-19T09:00:00Z",
  "script": "Three engineering disasters...",
  "title": "Ignored Warnings",
  "caption": "Three disasters that killed more people than many wars...",
  "topic": "history",
  "duration_seconds": 25,
  "video_url": "https://tmpfiles.org/d/abc123.mp4",
  "thumbnail_url": "https://imgbb.com/...",
  "youtube_video_id": "dQw4w9WgXcQ",
  "entities": ["Banqiao Dam", "Chernobyl", "Bhopal"]
}
```

**Hard rules:**
- Append-only (never delete or edit past entries)
- Every published post recorded (no exceptions)
- Used by agent to detect duplicates (brief + angle fuzzy match)
- Used to track ledger.max_reuses (how many times an entity has appeared)

**Reading & Appending:**
```python
from src.brain import FactjotBrain

brain = FactjotBrain()
recent = brain.read_posted_posts(limit=30)  # Last 30 posts

# Check for duplicate before agent writes brief
for post in recent:
    if fuzzy_match(agent_brief, post["brief"]) > threshold:
        # Skip, likely duplicate
        pass

# After publish
brain.append_posted({
    "post_id": ig_media_id,
    "type": "carousel",
    "posted_at": datetime.now().isoformat(),
    ...
})
```

### `data/ledgers/used_images.jsonl`

**Purpose:** Prevent image reuse across posts (rule 02: "No image reuse").

**Entry format:**
```json
{
  "timestamp": "2026-05-19T08:30:00Z",
  "carousel_id": "17975927492999999_456",
  "slide_index": 2,
  "url": "https://commons.wikimedia.org/wiki/File:Marie_Curie_1903.jpg",
  "sha256": "abc123def456...",
  "entity": "Marie Curie",
  "entity_confidence": 0.92,
  "provider": "wikimedia",
  "category": "science"
}
```

**Hard rules:**
- Append-only ledger
- URL + SHA256 together uniquely identify an image
- `MAX_REUSES = 1` (never post same image twice, ever)
- Checked before carousel publish: `used_images.is_used(url, sha256)?`

**Reading & Appending:**
```python
from src.research.used_images import UsedImagesLedger

ledger = UsedImagesLedger()

# Check before using image
if ledger.is_used(image_url, image_sha256):
    # Skip, already posted
    pass

# After using image
ledger.add(image_url, image_sha256, carousel_id=carousel.id, entity=entity_name)
```

### `data/ledgers/used_footage_urls.jsonl`

**Purpose:** Prevent video footage reuse across reels (parallel to used_images).

**Entry format:**
```json
{
  "timestamp": "2026-05-19T09:00:00Z",
  "reel_id": "17975927492999999_456",
  "url": "https://videos.pexels.com/video-files/123/456.mp4",
  "duration_seconds": 8,
  "source": "pexels",
  "title": "Banqiao Dam Spillway",
  "category": "engineering"
}
```

**Hard rule:** Same video URL never used in two reels. Prevents visual repetition.

### `data/ledgers/api_usage_costs.jsonl`

**Purpose:** Track API costs per run for budgeting.

**Entry format:**
```json
{
  "timestamp": "2026-05-19T08:30:00Z",
  "post_id": "17975927492999999_456",
  "run_mode": "carousel",
  "costs": {
    "anthropic": {
      "input_tokens": 3000,
      "output_tokens": 500,
      "cost_usd": 0.015
    },
    "elevenlabs": {
      "characters": 0,
      "cost_usd": 0.0
    },
    "meta_graph_api": {
      "calls": 15,
      "cost_usd": 0.0
    }
  },
  "total_usd": 0.015
}
```

**Usage:** Monthly cost audit (optional; not acted on in current pipeline).

### `data/ledgers/youtube_uploads.jsonl`

**Purpose:** Map IG reels to YouTube Shorts cross-posts.

**Entry format:**
```json
{
  "timestamp": "2026-05-19T09:05:00Z",
  "reel_ig_id": "17975927492999999_456",
  "youtube_video_id": "dQw4w9WgXcQ",
  "youtube_url": "https://www.youtube.com/shorts/dQw4w9WgXcQ",
  "channel": "UC_x5XG1OV2P6uZZ5FSM9Ttw"
}
```

**Hard rule:** One reel → one YouTube Short (deduplicated).

### `data/ledgers/carousel_quality.jsonl`

**Purpose:** Track carousel generation diagnostics (shape errors, line fits, etc.).

**Entry format:**
```json
{
  "timestamp": "2026-05-19T08:30:00Z",
  "carousel_id": "17975927492999999_456",
  "brief": "Three engineering disasters...",
  "stage_one_ok": true,
  "stage_two_ok": true,
  "slide_count": 7,
  "layout_profile": "readable_list",
  "errors": [],
  "fit_metrics": {
    "slide_0": {"char_cap": 56, "used": 42, "ok": true},
    "slide_1": {"char_cap": 56, "used": 48, "ok": true},
    ...
  }
}
```

**Usage:** Optional; helps debug carousel rendering issues.

### `data/ledgers/reel_performance.jsonl`

**Purpose:** Track reel engagement metrics (IG insights).

**Entry format (one per reel, updated nightly):**
```json
{
  "reel_ig_id": "17975927492999999_456",
  "posted_at": "2026-05-19T09:00:00Z",
  "fetched_at": "2026-05-19T22:00:00Z",
  "title": "Ignored Warnings",
  "engagement": {
    "plays": 1234,
    "comments": 45,
    "likes": 123,
    "shares": 12,
    "saves": 34
  },
  "reach": 2100,
  "impressions": 3000
}
```

**Hard rule:** This is the **only mutable ledger**. Fully rewritten on each `fetch_reel_metrics.py` run as metrics accumulate. All other ledgers are append-only.

---

## Per-Run Output (Gitignored)

### Directory structure

```
output/
├── carousel/
│   ├── 2026-05-19_08-30_engineering/
│   │   ├── carousel.json            # Metadata
│   │   ├── slides/
│   │   │   ├── 00_cover.png
│   │   │   ├── 01_content.png
│   │   │   ├── ...
│   │   │   └── 06_closing.png
│   │   ├── pipeline.log             # Debug log
│   │   └── ffmpeg_progress.txt      # (if relevant)
│   └── 2026-05-19_11-45_history/
│       ├── ...
├── reel/
│   ├── 2026-05-19_09-00_engineering/
│   │   ├── reel.mp4                 # Final video
│   │   ├── reel_thumbnail.png       # Thumbnail
│   │   ├── reel_story.png           # Story tile (optional)
│   │   ├── ffmpeg_filter_complex.txt
│   │   ├── ffmpeg_progress.txt
│   │   ├── ffmpeg_compose_stderr.log
│   │   └── pipeline.log
│   └── 2026-05-19_09-30_science/
│       ├── ...
└── test/
    └── (misc test outputs)
```

### `carousel.json` metadata

```json
{
  "carousel_id": "17975927492999999_456",
  "brief": "Three engineering disasters...",
  "layout_mode": "readable_list",
  "category": "history",
  "slides": [
    {
      "index": 0,
      "kind": "cover",
      "headline": "Three Disasters",
      "body": "",
      "image_file": null,
      "visual_intent": "concept"
    },
    {
      "index": 1,
      "kind": "content",
      "headline": "Banqiao Dam (1975)",
      "body": "Up to 170,000 people died in floods...",
      "image_file": "slides/01_content.png",
      "visual_intent": "entity",
      "image_url": "https://commons.wikimedia.org/wiki/File:...",
      "image_sha256": "abc123..."
    },
    ...
  ],
  "posted_at": null,
  "ig_media_id": null
}
```

---

## Ledger Reading & Writing

### Using `src.brain.FactjotBrain`

```python
from src.brain import FactjotBrain

brain = FactjotBrain()

# Read posts
recent_posts = brain.read_posted_posts(limit=30)
for post in recent_posts:
    print(f"{post['posted_at']}: {post['type']}")

# Check for duplicate
if brain.check_duplicate(agent_brief, agent_angle):
    # Similar post already made
    pass

# Append after publish
brain.append_posted({
    "post_id": ig_media_id,
    "type": "carousel",
    "posted_at": datetime.now().isoformat(),
    "brief": brief,
    "caption": caption,
    ...
})
```

### Using `src.research.used_images.UsedImagesLedger`

```python
from src.research.used_images import UsedImagesLedger

ledger = UsedImagesLedger()

# Check
if ledger.is_used(image_url, image_sha256):
    # Skip, already used
    pass

# Add
ledger.add(
    url=image_url,
    sha256=image_sha256,
    carousel_id=carousel.id,
    entity=entity_name,
    category=category
)

# Query
recent_images = ledger.get_recent_by_entity("Marie Curie", days=7)
print(f"Marie Curie images in last 7 days: {len(recent_images)}")
```

### Manual ledger operations

```python
from src.core.json_store import append_jsonl, load_jsonl

# Append one record
append_jsonl(
    Path("data/ledgers/used_images.jsonl"),
    {
        "url": "https://...",
        "sha256": "abc123...",
        "entity": "Marie Curie",
        ...
    }
)

# Read all records
records = load_jsonl(Path("data/ledgers/used_images.jsonl"))
for record in records:
    print(record)
```

---

## Ledger Invariants (Non-negotiable)

| Ledger | Invariant | Enforced by |
|---|---|---|
| `posted.jsonl` | Every IG post captured (never missed) | `ship_carousel_post.py`, `make_reel.py` |
| `used_images.jsonl` | URL + SHA256 never duplicated | `image_sourcer.py` + `used_images.py` check |
| `used_footage_urls.jsonl` | Video URL never reused in reels | `video_finder.py` check |
| `api_usage_costs.jsonl` | One record per run (append-only) | Pipeline's cost tracker |
| `youtube_uploads.jsonl` | One entry per reel → YT cross-post | `scripts/upload_to_youtube.py` |
| `reel_performance.jsonl` | Fully rewritten per fetch (mutable) | `fetch_reel_metrics.py` |
| `carousel_quality.jsonl` | Diagnostic record per carousel (append) | `ship_carousel_post.py` |

---

## Debugging with Ledgers

### Find recent posts

```bash
tail -5 insta-brain/data/posted.jsonl
```

### Check image reuse

```bash
grep -c "Marie Curie" data/ledgers/used_images.jsonl  # How many MC images?
```

### Find failed carousels

```bash
cat data/ledgers/carousel_quality.jsonl | jq 'select(.errors | length > 0)'
```

### Verify reel engagement

```bash
cat data/ledgers/reel_performance.jsonl | jq '.[-1] | {title, engagement}'
```

---

## Storage Location Rules (from SPEC § 11.2)

- **Git-tracked state:** `insta-brain/data/` + `data/ledgers/` (committed on publish)
- **Per-run output:** `output/` (gitignored, local only)
- **Temporary caches:** `.cache/`, `data/cache/` (gitignored, auto-cleanup)
- **Ledger discipline:** Append-only except `reel_performance.jsonl` (fully rewritten)
- **Write safety:** Atomic writes (temp file → move, never in-place truncation)

---

## Cleanup & Maintenance

### Temporary file cleanup

```bash
# Clear old outputs (optional, not auto-run)
rm -rf output/carousel/* output/reel/*

# Clear Playwright cache
rm -rf ~/.cache/ms-playwright/

# Clear FFmpeg progress logs
rm ffmpeg_progress.txt ffmpeg_compose_stderr.log
```

### Ledger inspection (safe, read-only)

```bash
# Count all posts
wc -l insta-brain/data/posted.jsonl

# Find posts by category
cat insta-brain/data/posted.jsonl | jq 'select(.category == "science")'

# Latest 10 posts (jq)
tail -10 insta-brain/data/posted.jsonl | jq '.title // .brief'
```

---

## Related Documentation

- `SPEC_FACTJOT_SYSTEM.md` § 11 — Ledger discipline + invariants
- `src/brain.py` — Ledger reading API
- `src/research/used_images.py` — Image dedup checking
- `docs/CODEMAPS/publishing.md` — When ledgers are written
