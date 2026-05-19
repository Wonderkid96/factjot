# Testing & Verification Codemap

**Last Updated:** 2026-05-19  
**Test Directory:** `tests/`  
**Fact Verification:** `src/verification/fact_checker.py`  
**Visual Verification:** Manual inspection of rendered output  

---

## Testing Architecture

```
tests/
├── test_carousel_slides_byte_stable.py    # Typography + rendering
├── test_carousel_writer.py                # Content generation (Sonnet → Haiku)
├── test_fact_checker.py                   # Fact verification gates
├── test_image_sourcer.py                  # Image candidate scoring
├── test_image_fetcher.py                  # Image provider queries
├── test_json_store.py                     # Ledger I/O
├── test_line_fit_probe.py                 # Character width measurement
├── test_reel_composer.py                  # FFmpeg script generation
├── test_quote_picker.py                   # Quote dedup + selection
├── test_used_images.py                    # Image reuse ledger
└── conftest.py                            # Pytest fixtures + config
```

**Coverage target:** 80% (as of 2026-05-19: 34 tests passing).

---

## Unit Tests by Module

### Content Generation (`test_carousel_writer.py`)

**Purpose:** Verify two-stage carousel writing (Sonnet → Haiku).

**Test cases:**
- `test_stage_one_generates_valid_slides` — Sonnet produces slide objects
- `test_stage_two_fits_within_char_cap` — Haiku respects character limits
- `test_carousel_shape_valid_min_max_slides` — Between 3–7 slides (compact)
- `test_one_slide_one_idea_enforced` — No multi-idea slides
- `test_closing_slide_has_verified_quote` — Quote sourced from bank
- `test_visual_intents_present` — Each slide has visual_intent (entity, action, etc.)
- `test_error_shape_violation` — Raises CarouselShapeError on invalid shape

**Mocks:**
- Sonnet API calls (fixed responses)
- Image metadata (mock entities)
- Quote bank (test quotes only)

### Fact Verification (`test_fact_checker.py`)

**Purpose:** Verify fact checking gate (≥2 sources, confidence ≥0.65).

**Test cases:**
- `test_claim_with_two_sources_passes` — Verifiable claims accepted
- `test_claim_with_one_source_fails` — Single source rejected
- `test_confidence_below_floor_fails` — Low confidence (< 0.65) rejected
- `test_multiple_sources_aggregated` — Sources combined for confidence
- `test_well_known_facts_pass` — Famous facts verify easily
- `test_obscure_claims_fail_appropriately` — Unverifiable rejected

**Mocks:**
- Web search results (fixed mock data)
- Source ranking (confidence scoring)

### Image Sourcing (`test_image_sourcer.py`)

**Purpose:** Verify candidate ranking and provider routing.

**Test cases:**
- `test_rank_candidates_scores_correctly` — Scoring algorithm produces ranked list
- `test_entity_match_boosts_score` — Entity names increase score
- `test_keyword_relevance_scores_contextual_images` — Keyword match works
- `test_provider_priority_order_respected` — Wikimedia first, imgbb last
- `test_relax_mode_lowers_r3_floor` — Floor 6 in readable_list vs 8 in compact
- `test_news_mode_routes_differently` — News carousel routes to different providers
- `test_no_duplicate_providers_in_ranking` — Each provider once per tier

**Mocks:**
- Provider APIs (fixed mock responses)
- Entity database (mock Wikidata)

### Image Fetching (`test_image_fetcher.py`)

**Purpose:** Verify image download + validation.

**Test cases:**
- `test_fetch_returns_valid_urls` — Downloaded images have URLs
- `test_invalid_dimensions_rejected` — Too small or too large → rejected
- `test_broken_links_skipped` — 404 URLs marked as dead
- `test_licence_check_enforced` — Non-free images rejected
- `test_negative_terms_applied` — Cartoon/abstract filtered out
- `test_timeout_skips_to_next_provider` — 30s timeout moves on
- `test_query_variants_generated` — Search term variations tried

**Mocks:**
- HTTP requests (mock responses)
- Image validation (mock PIL)

### Line Fit Probe (`test_line_fit_probe.py`)

**Purpose:** Verify character width measurement on canvas.

**Test cases:**
- `test_probe_measures_accurate_width` — Measured width close to actual
- `test_overflow_detected_correctly` — Detects text that doesn't fit
- `test_different_fonts_measured_separately` — Archivo vs Space Grotesk different widths
- `test_long_lines_split_and_measured` — Multi-line text handled
- `test_whitespace_normalized` — Trimmed correctly

**Mocks:**
- Playwright renderer (mock text measurements)

### Reel Composition (`test_reel_composer.py`)

**Purpose:** Verify FFmpeg script generation.

**Test cases:**
- `test_ffmpeg_filter_script_valid` — Generated filter graph is syntactically valid
- `test_audio_enforced_48khz` — Resample filter present
- `test_transitions_hardwired_case_file_dynamic` — Only this transition in use
- `test_duration_floor_enforced` — Duration ≥ 18s checked
- `test_subtitle_timing_aligned` — Subtitle timing matches audio
- `test_codec_h264_selected` — libx264 in script
- `test_max_bitrate_respected` — maxrate 800k in script

**Mocks:**
- FFmpeg binary (mock subprocess)
- Video/audio files (mock paths)

### Quote Picker (`test_quote_picker.py`)

**Purpose:** Verify quote selection + dedup.

**Test cases:**
- `test_closing_quote_selected_from_bank` — Quote from curated bank
- `test_quote_dedup_within_run` — Same quote not used twice in one agent run
- `test_quote_category_matched` — Science quotes for science carousel
- `test_quote_has_attribution` — Never anonymous
- `test_fallback_if_no_suitable_quote` — Generic quote if category match fails

**Mocks:**
- Quote bank (test data)
- Session hash dedup (in-memory)

### JSON Storage (`test_json_store.py`)

**Purpose:** Verify ledger I/O (atomic writes, append-only).

**Test cases:**
- `test_load_valid_json_file` — Reads correct JSON
- `test_save_writes_atomically` — Temp file → move pattern
- `test_append_jsonl_line_per_record` — One line per JSON object
- `test_append_never_truncates` — Ledger grows, never loses old records
- `test_corrupt_file_raises_error` — Malformed JSON fails gracefully
- `test_concurrent_appends_safe` — Multiple appends don't interleave

**Mocks:**
- File I/O (mock pathlib)

### Used Images Ledger (`test_used_images.py`)

**Purpose:** Verify image reuse tracking.

**Test cases:**
- `test_is_used_detects_reuse` — URL + SHA256 marked as used
- `test_add_appends_to_ledger` — New entries added
- `test_get_recent_by_entity` — Filter by entity name + days
- `test_max_reuses_enforced` — MAX_REUSES = 1 (never twice)
- `test_url_change_still_blocked` — Same image, new URL → still blocked
- `test_different_image_allowed` — Same URL, different content → allowed

**Mocks:**
- Ledger file (mock data)

### Typography & Rendering (`test_carousel_slides_byte_stable.py`)

**Purpose:** Ensure carousel PNG rendering is deterministic (byte-stable).

**Test cases:**
- `test_cover_slide_renders_without_image` — Typography-only covers OK
- `test_content_slide_with_image_renders` — Image composited correctly
- `test_closing_slide_renders_with_quote` — Quote + attribution renders
- `test_slide_dimensions_correct` — 1200×1500 px output
- `test_brand_colors_applied` — PAPER background, INK text
- `test_font_family_hierarchy_respected` — Correct font per element
- `test_byte_stable_output` — Same input → same PNG bytes (no re-encoding artifacts)

**Mocks:**
- PIL Image rendering (mock or real Playwright)
- Brand kit (test data)

---

## Integration Tests (Pipeline-level)

**Not separate files; run via `pytest tests/ -v`.**

| Test | What | How |
|---|---|---|
| **Carousel end-to-end (dry-run)** | Brief → carousel.json + PNGs | Call `ship_carousel_post.py --dry-run` |
| **Reel end-to-end (dry-run)** | Script → reel.mp4 + thumbnail | Call `make_reel.py --dry-run` |
| **Ledger write + read** | Published → ledger append → re-read | Actual file I/O |
| **Image provider fallback** | R1 fails → R2 → R3 | Mock API failures, verify fallback |

**Run locally:**
```bash
# Carousel integration test
python3 /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
  pipelines/carousel/ship_carousel_post.py \
  --brief "Three engineering disasters..." \
  --type list \
  --dry-run

# Reel integration test
python3 /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
  pipelines/reel/make_reel.py \
  --script "Hook. Item 1. Item 2. Item 3. Close." \
  --title "Example" \
  --topic earth \
  --dry-run
```

---

## Fact Verification (Non-test verification)

**Module:** `src/verification/fact_checker.py`

**Gate location:** `carousel_writer.py:stage_one` (during content generation)

**Process:**
1. Sonnet generates slide copy with factual claims
2. `fact_checker.verify_claim(claim_text)` called for each claim
3. Returns: `(confidence: float, sources: List)`
4. If confidence < 0.65: Raise `UnverifiableClaimError`, abort carousel
5. If ≥ 0.65: Pass, include sources in metadata

**Example:**
```python
from src.verification.fact_checker import verify_claim

confidence, sources = verify_claim("Marie Curie discovered radium in 1898.")
# confidence: 0.92 (well-known fact)
# sources: [SourceCite(...), SourceCite(...)]

if confidence < 0.65:
    raise UnverifiableClaimError(claim="...", confidence=confidence)
```

---

## Visual Verification (Manual)

**Hard rule (SPEC § 13):** Output is the truth. Tests passing ≠ visual success. Always open rendered artefact and judge it.

**Checklist before publish:**

Carousel:
- [ ] All 7 slides render (no blank boxes)
- [ ] Images are correct (not abstract, not unrelated)
- [ ] Text is readable (not truncated, not overlapping)
- [ ] Wordmark visible (fact jot .)
- [ ] No typos in copy
- [ ] Closing quote is relevant + attributed

Reel:
- [ ] Video plays (not corrupted)
- [ ] Audio syncs with mouth shapes (if present) / voiceover is clear
- [ ] Subtitles present + timed correctly
- [ ] Thumbnail is visually compelling
- [ ] Duration 18–60 seconds
- [ ] Branding visible (intro, outro, thumbnail)

Story (if generated):
- [ ] Vertical aspect ratio (1080×1920)
- [ ] Thumbnail + call-to-action visible
- [ ] Wordmark in corner

---

## GitHub Actions CI/CD Tests

**Workflow:** `.github/workflows/test.yml`

**When:** Every PR and non-main push

**What:** `pytest tests/ -v`

**Pass criteria:**
- All 34 tests pass
- No import errors
- No missing dependencies

**Does NOT:** Execute pipeline entrypoints (no actual IG publishing in tests).

---

## Test Configuration (`conftest.py`)

**Fixtures provided:**

```python
@pytest.fixture
def sample_carousel():
    """Minimal valid carousel for testing"""
    return Carousel(
        id="test_carousel_1",
        slides=[
            Slide(layout_kind="cover", headline="Test", body="", visual_intent="concept"),
            Slide(layout_kind="content", headline="Entity", body="Fact", visual_intent="entity"),
            Slide(layout_kind="closing", headline="", body="Quote.", visual_intent="concept"),
        ],
    )

@pytest.fixture
def sample_reel():
    """Minimal valid reel for testing"""
    return Reel(
        id="test_reel_1",
        script="Hook. Item 1. Item 2. Item 3. Close.",
        title="Test",
        topic="science",
        items=[...],
    )

@pytest.fixture
def mock_config():
    """Config with test API keys (no actual calls)"""
    return PipelineConfig.load_from_env()
```

---

## Running Tests Locally

```bash
# All tests
pytest tests/ -v

# Single test file
pytest tests/test_carousel_writer.py -v

# Single test
pytest tests/test_carousel_writer.py::test_stage_one_generates_valid_slides -v

# With coverage
pytest tests/ --cov=src --cov-report=html

# Show print statements
pytest tests/ -v -s
```

---

## Debugging Test Failures

| Error | Likely cause | Debug step |
|---|---|---|
| `ModuleNotFoundError` | Dependency missing | `pip install -r requirements.txt` |
| Mock API call fails | Wrong fixture | Check `conftest.py` + mock setup |
| Image validation fails | PIL import issue | Verify Pillow installed |
| FFmpeg tests fail | ffmpeg not in PATH | Check `src/core/ffmpeg_bin.py` |
| Timeout in test | Playwright slow | Increase timeout in conftest.py |

---

## Related Documentation

- `SPEC_FACTJOT_SYSTEM.md` § 5 — Verify stage (fact checking)
- `.github/workflows/test.yml` — CI/CD test runner
- `pytest.ini` — Pytest configuration
- `tests/conftest.py` — Fixture + mock setup
