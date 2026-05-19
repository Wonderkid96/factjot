# Rendering & Media Codemap

**Last Updated:** 2026-05-19  
**Modules:** `src/render/`, `pipelines/reel/` (media-specific)  
**Output:** PNG slides (carousel), MP4 reels (video), PNG thumbnails + story tiles  

---

## Rendering Architecture

```
Carousel Pipeline
  ├─ Content generation (slides + visual intents)
  ├─ Image fetching (one image per slide)
  └─ Render to PNG
       └─ carousel_slides.py
            ├─ Cover slide (hook, no spoil)
            ├─ Content slides (entity + body + image)
            └─ Closing slide (verified quote)

Reel Pipeline
  ├─ Script + title from agent
  ├─ Fetch video footage (src/research/video_finder.py)
  ├─ Generate voiceover audio (tts_engine.py, 48kHz)
  ├─ Compose MP4 (reel_composer.py)
  ├─ Extract thumbnail frame (thumbnail_picker.py)
  ├─ Render story tile (reel_story.py, vertical 1080x1920)
  └─ Publish to IG + YouTube
```

---

## Carousel Rendering (`carousel_slides.py`)

**Purpose:** Render 7 PNG slides (1200x1500 each, 72 DPI) from content + images.

**Exports:**
- `CarouselRenderer` — Class to render PNG slides
  - `render_carousel(carousel_object) → List[PIL.Image]`
  - Returns: List of 7 PIL Image objects in RGB mode
- `render_cover_slide(headline, hook_text) → PIL.Image`
- `render_content_slide(headline, body, image, layout_profile) → PIL.Image`
- `render_closing_slide(quote_text, attribution) → PIL.Image`

**Canvas properties:**
- Dimensions: 1200 × 1500 px (Instagram carousel standard)
- DPI: 72 (screen-optimized)
- Background: `PAPER` from `brand/brand_kit.json` (`#F4F1E9`)
- Layout: Depends on profile (compact_legacy vs readable_list)

### Cover Slide

**Component structure:**
```
┌─────────────────────────┐
│                         │  Title area (Instrument Serif, centered)
│   [Headline/Hook]       │  20–40 chars, no spoil
│                         │
│  ┌───────────────────┐  │  Image area (optional, often skipped for typography-only cover)
│  │  Optional image   │  │
│  └───────────────────┘  │
│                         │
│  [Metadata pill]        │  Category label in pill (Archivo Black 900, 12px)
│                         │
└─────────────────────────┘
```

**Constraints:**
- Headline: ≤ 40 chars (verified at stage_two_fit)
- No spoilers (agent + Sonnet both enforce via prompt)
- Image optional (typography-only covers allowed)

### Content Slide

**Component structure (compact_legacy):**
```
┌─────────────────────────┐
│  ┌───────────────────┐  │
│  │  [Image, 80%]     │  │  Image: fills most of slide
│  │                   │  │
│  └───────────────────┘  │
│                         │
│  [Headline] (black bg)  │  Headline: Archivo Black 900, 24-char cap, bottom-left
│  [Body] (black bg)      │  Body: 6–8 lines max, 42–48px Archivo Black
│                         │
└─────────────────────────┘
```

**Component structure (readable_list):**
```
┌─────────────────────────┐
│  ┌───────────────────┐  │
│  │  [Image, 50%]     │  │  Image: top half, fills width
│  │                   │  │
│  └───────────────────┘  │
│                         │
│  ┌───────────────────┐  │  Body: bottom half, Space Grotesk SemiBold
│  │  [Headline]       │  │  Auto-fits 64px (large) → 28px (small) via CSS
│  │  [Body]           │  │
│  │  [Index]          │  │  Index: "Item 1 of 5" (Space Grotesk Bold 700)
│  └───────────────────┘  │
│                         │
└─────────────────────────┘
```

**Font constraints:**
- Headline: Instrument Serif (regular + italic for list titles)
- Body: Archivo Black 900 (compact_legacy) OR Space Grotesk SemiBold (readable_list)
- Metadata: Space Grotesk Bold 700, 11px (source attribution, index)

### Closing Slide

**Component structure:**
```
┌─────────────────────────┐
│                         │
│      [Quote text]       │  Quote: Instrument Serif Italic, 24–28px, centered
│                         │
│      — [Attribution]    │  Attribution: Source (magazine, author, etc.)
│                         │
│  [Wordmark]             │  Wordmark: fact [regular] jot [italic] . [red]
│                         │
└─────────────────────────┘
```

**Constraints:**
- Quote must be verified (sourced, deduplicated via `quotes.py`)
- Attribution mandatory (never anonymous)
- Wordmark: always included, positioned bottom center

---

## Reel Rendering (`reel_composer.py`)

**Purpose:** Compose MP4 reel from script, voiceover, footage, subtitles.

**Exports:**
- `ReelComposer` — Class to orchestrate reel rendering
  - `compose(reel_spec) → output_path.mp4`
  - Returns: Path to final MP4 file

**Pipeline:**
1. **Source video footage** (`src/research/video_finder.py`)
   - Query per-item (one video per reel item if possible)
   - Fallback: generic stock footage for concepts
   - Still images converted to MP4 via `_still_to_mp4` (5-second loop)

2. **Generate voiceover** (`tts_engine.py`)
   - Script → ElevenLabs API (voice ID from `ELEVENLABS_VOICE` secret)
   - Enforce 48 kHz, mono, WAV output
   - Resample if needed (44.1 kHz input → 48 kHz output)

3. **Render kinetic subtitles** (`reel_text_renderer.py`)
   - Generate subtitle PNG per-item (Archivo Bold 700)
   - Subtitle timing: aligned to audio timing (phrase-by-phrase)
   - Brand subtitle chunker (see CLAUDE.md §2) treats `—` as phrase break

4. **Compose via FFmpeg** (`reel_composer.py:_build_ffmpeg_script`)
   - Input: video stream, audio stream, subtitle stream (PNG overlays)
   - Hardwired transition: `case_file_dynamic` (see CLAUDE.md §7)
   - No fallback modes; if transitions requested, fail fast
   - Output codec: H.264 (libx264)
   - CRF: 30 (quality/file-size balance)
   - Max bitrate: 800 kbps video (strict, for tmpfiles/Cloudinary limits)

5. **Mux to MP4 container**
   - Audio: 48 kHz, 128 kbps
   - Video: 30 FPS, 1080×1920 (mobile format)
   - Duration: ≥ 18s, ≤ 60s (Instagram reel limits)

**Output constraints:**
- Duration floor: 18 seconds (non-negotiable, checked at end)
- Duration ceiling: 60 seconds (Instagram native limit)
- File size: target ≤ 5 MB (tmpfiles free limit; Cloudinary disabled per memo)
- Format: MP4 + H.264 (IG compatible)

**Error handling:**
- FFmpeg encode timeout: 5 min (after which FFmpeg killed, error raised)
- Fallback codec (if libx264 unavailable): libxvid (legacy, warns operator)
- Audio resample error: Fail fast (48 kHz required; do not attempt substitution)

---

## Key Rendering Modules

### `line_fit_probe.py`

**Purpose:** Measure actual character width on canvas + validate text fits.

**Exports:**
- `probe_line_width(text, font_name, font_size, canvas_width) → actual_width_px`
  - Uses Playwright to render text in real font
  - Accounts for kerning, ligatures, font rendering
- `validate_lines_for_layout(lines, layout_profile) → (fits: bool, overflow_px: int)`
  - Returns: Does text fit height? By how much does it overflow (if not)?

**Usage in carousel:**
```python
# During stage_two_fit (Haiku fitter)
layout_profile = LAYOUT_PROFILES["compact_legacy"]
for slide in slides:
    # Measure each line
    for i, line in enumerate(slide.body_lines):
        width = probe_line_width(line, "Archivo Black 900", 42, canvas_width=1000)
        if width > layout_profile["char_cap"]:
            # Does not fit; Haiku rewrites or aborts
            pass
```

### `tts_engine.py`

**Purpose:** Generate voiceover audio via ElevenLabs.

**Exports:**
- `TTSEngine` — Class wrapping ElevenLabs API
  - `synthesize(script, voice_id) → bytes (WAV audio)`
  - Returns: WAV audio, exactly 48 kHz, mono

**Configuration:**
- **Provider:** ElevenLabs (enforced)
- **Voice ID:** From `ELEVENLABS_VOICE` secret (updated 2026-05-18; matches "daniel" in API docs)
- **Sample rate:** Enforce 48 kHz request in API call (ElevenLabs defaults to 44.1 kHz)
- **Format:** WAV (PCM)
- **Mono:** Yes (no stereo)

**Error handling:**
- API rate limit (429): Retry with backoff
- Invalid voice ID: Fail fast with clear error
- Audio not 48 kHz: Resample before mux (critical; see CLAUDE.md §13)

### `reel_text_renderer.py`

**Purpose:** Render kinetic subtitles (overlays) for reel items.

**Exports:**
- `KineticSubtitleRenderer` — Class to render subtitle PNGs
  - `render_subtitle(text, start_frame, end_frame) → PIL.Image`
  - Returns: PNG image at 1080×1920 resolution

**Typography:**
- Font: Archivo Bold 700
- Size: 54–72 px (scales based on text length)
- Color: White (`#FFFFFF`) with hard drop shadow (2px 2px 0 rgba(0,0,0,0.5))
- Position: Centered horizontally, lower third vertically

**Phrase breaking:**
- Script chunked by sentence, comma, or `—` (em-dash, brand rule)
- Each phrase → one subtitle PNG
- Timing: Aligned to audio phrase timing (from voiceover generation)

### `reel_story.py`

**Purpose:** Render story tile (vertical 1080×1920 image) for Instagram Stories cross-post.

**Exports:**
- `StoryRenderer` — Class to render story PNG
  - `render(reel_spec) → PIL.Image`
  - Returns: 1080×1920 PNG

**Component structure:**
```
┌──────────────────────────┐
│  [Brand hook text]       │  Top: Call-to-action or title (Archivo Black 900)
│                          │
│  ┌────────────────────┐  │
│  │  [Reel preview]    │  │  Middle: Thumbnail from reel composition
│  │                    │  │
│  └────────────────────┘  │
│                          │
│  [Wordmark]              │  Bottom: fact jot wordmark + link sticker
│  [Link: "See full reel"]  │
│                          │
└──────────────────────────┘
```

**Use:** Cross-post to IG Stories (optional); currently unused in live flow.

### `thumbnail_picker.py`

**Purpose:** Select a visually strong frame from reel to use as thumbnail.

**Exports:**
- `ThumbnailPicker` — Class to score frames
  - `pick_best_frame(video_frames) → best_frame_index`
  - Returns: Index of highest-scoring frame

**Scoring criteria:**
- Face detection (human faces score high)
- Scene cut detection (avoid motion blur, extreme motion)
- Text readability (subtitle overlay clear)
- Brightness distribution (not too dark, not blown out)
- Entity visibility (branded elements visible)

**Output:**
- PNG 1200×600 (IG reel thumbnail dimensions)
- Branded overlay: `fact.` logo in corner, wordmark at bottom

---

## Brand Kit Integration

**Source:** `brand/brand_kit.json` (v2.1)

**Consumed by all renderers via `src/core/brand.py`:**

| Property | Value | Used by |
|---|---|---|
| `PAPER` | `#F4F1E9` | Carousel background, story background |
| `INK` | `#0A0A0A` (or `#0B0B0C`, open decision) | Text, shadows, strokes |
| `ACCENT` | `#E6352A` (red) | Wordmark dot, pill highlights, emphasis |
| `LIME` | `#C8DB45` | Secondary accent (reserved for future use) |
| `LILAC` | `#C4A9D0` | Secondary accent (reserved for future use) |
| Shadow | `2px 2px 0 rgba(0,0,0,0.5)` (hard drop, no blur) | All text overlays |
| Font: Archivo | Black 900 | Hook cards, subtitles, metadata labels |
| Font: Instrument Serif | Regular + Italic | Titles, headlines, wordmark |
| Font: Space Grotesk | SemiBold (body), Bold 700 (labels) | Readable_list profile, metadata |

---

## Output Structure

### Carousel render output

```
output/carousel/YYYY-MM-DD_HH-MM_TOPIC/
├── carousel.json              Metadata (id, caption, slide count)
├── slides/
│   ├── 00_cover.png           Cover slide
│   ├── 01_content.png         Content slide 1
│   ├── 02_content.png         Content slide 2
│   ...
│   ├── 06_closing.png         Closing slide
└── pipeline.log               Debug log
```

### Reel render output

```
output/reel/YYYY-MM-DD_HH-MM_TOPIC/
├── reel.mp4                   Final reel video
├── reel_thumbnail.png         Thumbnail image
├── reel_story.png             Story tile (if generated)
├── ffmpeg_filter_complex.txt  FFmpeg filter graph (debug)
├── ffmpeg_progress.txt        FFmpeg progress log
├── ffmpeg_compose_stderr.log  FFmpeg error log (if any)
└── pipeline.log               Debug log
```

---

## Quality Gates (Rendering)

| Gate | Enforced by | Action |
|---|---|---|
| **Carousel shape valid** | `carousel_rules.py:validate_shape` | Reject if min/max slides violated |
| **Slides not truncated** | `line_fit_probe.py` | Reject if text overflow > 0 |
| **Images not broken** | PNG write check | Reject if PIL fails to save |
| **Reel duration ≥ 18s** | `reel_composer.py` | Reject if under floor |
| **Audio is 48 kHz** | tts_engine + mux verification | Reject or resample |
| **MP4 is valid** | ffprobe check (implicit in publish) | Reject if meta invalid |
| **Thumbnail extracted** | `thumbnail_picker.py` | Fail soft; use frame 0 if picker fails |

---

## Testing Rendering Locally

```bash
# Test carousel rendering
python3 << 'EOF'
from src.render.carousel_slides import CarouselRenderer
from src.content.carousel_writer import generate_content

brief = "Three engineering disasters..."
slides, _ = generate_content(brief, format_type="list", layout_mode="readable_list")

renderer = CarouselRenderer(layout_mode="readable_list")
pngs = renderer.render_carousel(carousel_spec)

for i, png in enumerate(pngs):
    png.save(f"output/test_slide_{i}.png")
EOF

# Test line fit
python3 << 'EOF'
from src.render.line_fit_probe import probe_line_width

width = probe_line_width(
    text="Marie Curie discovered radium in 1898",
    font_name="Archivo Black 900",
    font_size=42,
    canvas_width=1000
)
print(f"Rendered width: {width}px")
EOF

# Test reel composition (dry-run)
python3 /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
  pipelines/reel/make_reel.py \
  --script "Three disasters. Item 1. Item 2. Item 3. Pattern." \
  --title "Example" \
  --topic earth \
  --dry-run
```

---

## Related Documentation

- `brand/brand_kit.json` — Visual identity (single source of truth)
- `src/core/brand.py` — Brand asset loader
- `SPEC_IMAGE_PIPELINE.md` — Image rendering requirements
- `docs/CODEMAPS/content.md` — How slides are generated before rendering
