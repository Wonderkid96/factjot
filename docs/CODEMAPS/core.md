# Core & Shared Modules Codemap

**Last Updated:** 2026-05-19  
**Modules:** `src/core/`  
**Purpose:** Configuration, models, paths, brand, JSON storage (shared across all pipelines)  

---

## Core Module Structure

```
src/core/
├── config.py              Pipeline configuration (knobs, thresholds)
├── models.py              Data models (Carousel, Reel, Slide, etc.)
├── paths.py               Output paths + directory management
├── brand.py               Brand asset loader (fonts, colors, logos)
├── json_store.py          JSON file I/O with write safety
├── ffmpeg_bin.py          FFmpeg binary auto-detection
└── __init__.py
```

---

## Configuration (`config.py`)

**Purpose:** Single source of truth for pipeline knobs and thresholds.

**Exports:**
- `PipelineConfig` — Class wrapping all config
  - `load_from_env()` → Config from environment + `.env` file
  - `validate()` → Check required keys, raise if missing

**Config categories:**

### API Keys & Secrets

```python
INSTAGRAM_ACCOUNT_ID: str          # Numeric IG account ID
META_ACCESS_TOKEN: str              # 60-day Meta Graph API token
IMGBB_API_KEY: str                  # imgbb image hosting API key
ELEVENLABS_API_KEY: str             # ElevenLabs voiceover API key
ELEVENLABS_VOICE: str               # Voice ID (e.g., "onwK4e9ZLuTAKqWW03F9")
ANTHROPIC_API_KEY: str              # Anthropic Claude API key
PEXELS_API_KEY: str (optional)      # Pexels image search (optional)
PIXABAY_API_KEY: str (optional)     # Pixabay image search (optional)
YOUTUBE_API_KEY: str (optional)     # YouTube Data API token (for Shorts cross-post)
```

### Quality Thresholds

```python
MIN_UPVOTES: int = 10000            # Minimum Reddit upvotes for fact sourcing (retired)
MIN_CAROUSEL_SCORE: int = 2         # Minimum image relevance score to use
MIN_CONFIDENCE: float = 0.65        # Fact verification confidence floor
SCRIPT_LENGTH_MIN: int = 70         # Minimum reel script length (words)
SCRIPT_LENGTH_MAX: int = 120        # Maximum reel script length
REEL_DURATION_MIN: int = 18         # Minimum reel duration (seconds)
REEL_DURATION_MAX: int = 60         # Maximum reel duration (Instagram limit)
CAROUSEL_MIN_SLIDES: int = 3        # Minimum slides per carousel
CAROUSEL_MAX_SLIDES_COMPACT: int = 7  # Max for compact_legacy
CAROUSEL_MAX_SLIDES_LIST: int = 10  # Max for readable_list
```

### Feature Flags

```python
DRY_RUN: bool = True                # Compose content but skip publish
SMOKE_MODE: bool = False            # Fast mode: skip image fetch, use placeholders
DEBUG_MODE: bool = False            # Verbose logging
PUBLISH_TO_IG: bool = True          # Actually post to Instagram (if not dry-run)
PUBLISH_TO_YOUTUBE: bool = True     # Cross-post reels to YouTube
```

### Paths & Storage

```python
PROJECT_ROOT: Path                  # Repo root
OUTPUT_DIR: Path                    # Per-run output folder
DATA_DIR: Path                      # Ledgers + cache
CACHE_DIR: Path                     # Temporary files
BRAND_KIT_PATH: Path                # brand/brand_kit.json
ASSETS_DIR: Path                    # Fonts, music, intros
```

**Loading order:**
1. Environment variables (`.env` file)
2. Default values in `config.py`
3. Runtime overrides via CLI flags

---

## Data Models (`models.py`)

**Purpose:** Type-safe data structures for pipeline objects.

**Exports:**

### Carousel models

```python
class Slide:
    """Single carousel slide"""
    layout_kind: str                # cover, content, closing
    headline: str                   # Slide title / entity
    body: str                        # Body copy
    visual_intent: str              # entity, action, concept, comparison, chart
    image_url: str (optional)       # Final image URL (after fetch)
    image_sha256: str (optional)    # Image hash (for dedupe)
    sources: List[SourceCite]       # Fact sources

class Carousel:
    """Complete carousel post"""
    id: str                         # Unique ID (timestamp-based)
    brief: str                      # User brief / agent input
    slides: List[Slide]             # 3–7 slides (compact) or 3–10 (list)
    caption: str                    # IG post caption
    category: str                   # Topic category (science, history, etc.)
    layout_mode: str                # compact_legacy or readable_list
    posted_at: Optional[datetime]   # When published (if published)
    ig_media_id: Optional[str]      # IG media ID (after publish)
```

### Reel models

```python
class ReelItem:
    """One item in a reel script"""
    text: str                       # Voiceover text
    duration_seconds: float         # Intended duration
    video_url: Optional[str]        # Video source URL
    entities: List[str]             # Named entities in item

class Reel:
    """Complete reel post"""
    id: str                         # Unique ID
    script: str                     # Full voiceover script
    title: str                      # Reel title / hook
    items: List[ReelItem]           # Parsed items
    topic: str                      # Category / topic
    posted_at: Optional[datetime]   # When published
    ig_media_id: Optional[str]      # IG media ID
    youtube_video_id: Optional[str] # YouTube Short ID (if cross-posted)
    duration_seconds: Optional[float]  # Final reel duration
    video_url: Optional[str]        # Uploaded MP4 URL
    thumbnail_url: Optional[str]    # Uploaded thumbnail URL
```

### Error models

```python
class CarouselShapeError(Exception):
    """Carousel structure is invalid"""
    diagnostics: dict               # Details: min/max, actual count, missing cover, etc.

class UnverifiableClaimError(Exception):
    """Fact claim failed verification"""
    claim: str
    sources_found: int
    confidence: float
```

---

## Paths (`paths.py`)

**Purpose:** Centralized path management for output, caches, ledgers.

**Exports:**
- `get_output_dir(pipeline_name, topic) → Path`
  - Returns: `output/{pipeline}/YYYY-MM-DD_HH-MM_TOPIC/`
  - Auto-creates directory
  
- `get_carousel_render_dir(carousel_id) → Path`
  - Returns: `output/carousel/{carousel_id}/`
  
- `get_reel_render_dir(reel_id) → Path`
  - Returns: `output/reel/{reel_id}/`

- `LEDGER_PATHS` — Dict of all ledger paths
  ```python
  {
      "posted": Path("insta-brain/data/posted.jsonl"),
      "used_images": Path("data/ledgers/used_images.jsonl"),
      "used_footage": Path("data/ledgers/used_footage_urls.jsonl"),
      "api_costs": Path("data/ledgers/api_usage_costs.jsonl"),
      "carousel_quality": Path("data/ledgers/carousel_quality.jsonl"),
      "reel_performance": Path("data/ledgers/reel_performance.jsonl"),
      "youtube_uploads": Path("data/ledgers/youtube_uploads.jsonl"),
  }
  ```

**Hard rule:** All output must be under `output/` (gitignored). Ledgers go in `data/ledgers/` or `insta-brain/data/` (git-tracked).

---

## Brand (`brand.py`)

**Purpose:** Load + expose brand visual identity from `brand/brand_kit.json`.

**Exports:**
- `Brand` — Class wrapping brand assets
  - `load()` → Load from `brand/brand_kit.json` v2.1
  - `get_color(name) → Hex string` (e.g., `"#E6352A"` for ACCENT)
  - `get_font(name, weight) → Font object`

**Brand properties (from `brand/brand_kit.json`):**

```json
{
  "version": "2.1",
  "colours": {
    "PAPER": "#F4F1E9",           // Background
    "INK": "#0A0A0A",             // Text / shadows (open: vs #0B0B0C)
    "ACCENT": "#E6352A",          // Red highlight
    "LIME": "#C8DB45",            // Secondary (reserved)
    "LILAC": "#C4A9D0",           // Secondary (reserved)
    "SKY": "#C9D8E2",             // Tertiary (reserved)
    "AVAILABLE": "#80EF80"        // Status color (reserved)
  },
  "typography": {
    "archivo": {
      "path": "assets/fonts/Archivo-Black.ttf",
      "weights": [900, 700]
    },
    "instrument_serif": {
      "path": "assets/fonts/InstrumentSerif-Regular.ttf",
      "weights": [400, 700]  // 400 = Regular, 700 = Bold
    },
    "space_grotesk": {
      "path": "assets/fonts/SpaceGrotesk-SemiBold.ttf",
      "weights": [500, 700]  // 500 = SemiBold, 700 = Bold
    }
  },
  "shadows": {
    "hard_drop": "2px 2px 0 rgba(0,0,0,0.5)"
  },
  "wordmark": {
    "format": "html",
    "content": "fact<i>jot</i>."  // fact (reg) jot (italic) . (red ACCENT)
  }
}
```

**Usage in renderers:**
```python
brand = Brand.load()
paper_color = brand.get_color("PAPER")      # "#F4F1E9"
ink_color = brand.get_color("INK")          # "#0A0A0A"
archivo_font = brand.get_font("archivo", 900)  # Font object
```

---

## JSON Storage (`json_store.py`)

**Purpose:** Safe JSON file I/O with write safety + append-only ledger support.

**Exports:**
- `JSONStore` — Class for JSON file operations
  - `load(path) → dict or list`
  - `save(path, data)` → Write to file (atomic: write temp, then move)
  - `append(path, record)` → Append JSON line to ledger file

- `append_jsonl(path, record)` → Helper to append one line to JSONL

**Ledger format (JSONL):** One JSON object per line (no commas, no array wrapper).

```
{"post_id": "123", "type": "carousel", ...}
{"post_id": "124", "type": "reel", ...}
```

**Write safety:**
- All writes are atomic: write to temp file, then rename
- Ledger appends are always at end of file (never overwrites)
- Exception on failure: never silent truncation

---

## FFmpeg Binary Detection (`ffmpeg_bin.py`)

**Purpose:** Auto-detect FFmpeg installation, fallback to `ffmpeg-full` if needed.

**Exports:**
- `get_ffmpeg_bin() → str` — Path to ffmpeg binary
  - Returns: `/usr/local/bin/ffmpeg` or `/opt/homebrew/bin/ffmpeg-full`
  - Checks: Default Homebrew ffmpeg first, falls back to ffmpeg-full if broken

**Error handling:**
- If FFmpeg not found: Raise clear error (operator must install)
- If ffmpeg-full needed: Log a note (auto-detection works, but mentions fallback)

**Hard rule (CLAUDE.md §6):** No manual `FFMPEG_BIN` env var needed. Auto-detection is transparent.

---

## Environment Setup

### `.env` file (local only, gitignored)

```bash
# Required
INSTAGRAM_ACCOUNT_ID=123456789
META_ACCESS_TOKEN=...
IMGBB_API_KEY=...
ANTHROPIC_API_KEY=...
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE=onwK4e9ZLuTAKqWW03F9

# Optional
PEXELS_API_KEY=...
PIXABAY_API_KEY=...
YOUTUBE_API_KEY=...
```

### GitHub secrets (for `autonomous-reel.yml`)

- `META_ACCESS_TOKEN` — Meta Graph API token (60-day, must refresh every ~50 days)
- `INSTAGRAM_ACCOUNT_ID` — Numeric account ID
- `IMGBB_API_KEY` — imgbb API key
- `ANTHROPIC_API_KEY` — Anthropic API key
- `ELEVENLABS_API_KEY` — ElevenLabs API key
- `ELEVENLABS_VOICE` — Voice ID (updated 2026-05-18)
- `YOUTUBE_API_KEY` — YouTube API token (optional, for Shorts cross-post)

---

## Testing Core Modules

```bash
# Test config loading
python3 << 'EOF'
from src.core.config import PipelineConfig

config = PipelineConfig.load_from_env()
config.validate()
print(f"Account ID: {config.INSTAGRAM_ACCOUNT_ID}")
print(f"Output dir: {config.OUTPUT_DIR}")
EOF

# Test brand loading
python3 << 'EOF'
from src.core.brand import Brand

brand = Brand.load()
paper = brand.get_color("PAPER")
archivo = brand.get_font("archivo", 900)
print(f"Paper color: {paper}")
print(f"Archivo font: {archivo}")
EOF

# Test paths
python3 << 'EOF'
from src.core.paths import get_output_dir, LEDGER_PATHS

carousel_dir = get_output_dir("carousel", "engineering")
print(f"Carousel output: {carousel_dir}")

for name, path in LEDGER_PATHS.items():
    print(f"  {name}: {path}")
EOF

# Test JSON storage
python3 << 'EOF'
from src.core.json_store import append_jsonl
from pathlib import Path

test_ledger = Path("output/test_ledger.jsonl")
append_jsonl(test_ledger, {"id": 1, "text": "test"})
append_jsonl(test_ledger, {"id": 2, "text": "test2"})
EOF
```

---

## Related Documentation

- `brand/brand_kit.json` — Visual identity (source of truth)
- `.env.example` — Template for local environment variables
- `SPEC_FACTJOT_SYSTEM.md` § 9 — Configuration rules + ledger discipline
- `CLAUDE.md` § 6 — Environment specifics (canonical Python path, secrets management)
