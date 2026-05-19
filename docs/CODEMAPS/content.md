# Content Generation Codemap

**Last Updated:** 2026-05-19  
**Modules:** `src/content/`, `src/research/` (non-image), `src/verification/`  
**Architecture Pattern:** Two-stage carousel writing (Sonnet brief → Haiku fitter)  

---

## Content Pipeline Structure

```
src/
├── content/                    Copy generation, rules, carousel writing
│   ├── carousel_writer.py      Two-stage generation: Sonnet → Haiku
│   ├── carousel_rules.py       Shared rules (layout profiles, ONE SLIDE = ONE IDEA, caps)
│   ├── quotes.py               Closing quote selection + dedupe
│   └── __init__.py
├── research/                   (Non-image) content sourcing
│   ├── fact_topic_router.py    Route brief to fact category
│   ├── narrative_beats.py      Structure patterns (timeline, comparison, discovery)
│   ├── story_scout.py          Current-event story sourcing
│   ├── trend_scout.py          Trending topics for reels
│   ├── wikidata_resolver.py    Entity resolution (Wikidata IDs)
│   ├── omdb_client.py          Film/TV metadata (OMDB)
│   ├── tmdb_client.py          Film/TV poster/backdrop seeding
│   ├── entity_image_validator.py Entity metadata → image intent
│   ├── visual_intents.py       Intent types (entity, action, concept, chart)
│   ├── sensitivity_guide.py    Content safety checks
│   └── __init__.py
└── verification/               Fact checking
    ├── fact_checker.py         Source verification (≥2 sources, confidence ≥0.65)
    └── __init__.py
```

---

## Carousel Generation Flow

### Stage 1: Sonnet Editorial (`carousel_writer.py:stage_one`)

**Input:** Brief (one sentence to one paragraph) + format type (list, fact, timeline, etc.)

**Output:** List of slide objects with:
- `headline` — Slide title or entity name
- `body` — Carousel body copy
- `visual_intent` — What image to fetch (entity, action, concept, comparison, chart)
- `layout_kind` — Structural role (cover, content, closing)

**Process:**
1. Router: `fact_topic_router.py` → determine category (science, history, nature, etc.)
2. Brief analysis: Extract the angle, entities, narrative structure
3. Sonnet writes editorial content in two passes:
   - First: Generate 6-8 initial slides (cover + content + closing)
   - Second: Enrich with sources, context, visual intents
4. Validate shape (min 3, max 7 slides for compact_legacy; max 10 for readable_list)

**Constraints enforced:**
- ONE SLIDE = ONE IDEA (defined in `carousel_rules.py`)
- Cover slide must hook without spoiling
- Closing slide uses verified quote from `quotes.py`
- Each slide has a concrete visual intent
- No reused entities across slides (variety)

### Stage 2: Haiku Line Fitter (`carousel_writer.py:stage_two`)

**Input:** Slides from Stage 1 + layout profile (compact_legacy or readable_list)

**Output:** Final slides ready to render:
- `headline` — Fit to character cap
- `body` — Shortened to fit height + width in profile
- Same visual intents (unchanged)

**Process:**
1. Profile lookup: Get char caps, height, font size from `carousel_rules.py:LAYOUT_PROFILES`
2. Per-slide layout: `src/render/line_fit_probe.py` measures actual width on canvas
3. Haiku receives each slide with its measured constraints
4. Haiku rewrites to fit: shorten, restructure, preserve facts
5. Retry loop: If a rewrite still doesn't fit, abort with `OVERCAP_SLIDE_LINES` error

**Constraints enforced:**
- Character cap (24 for compact_legacy, 56 for readable_list)
- Height cap (slides must fit in carousel container)
- Font size per profile (Archivo Black 48px / 42px for compact; Space Grotesk auto 64→28px for list)
- No truncation or silent slicing

---

## Key Modules Explained

### `carousel_writer.py`

**Exports:**
- `generate_content(brief, format_type, layout_mode)` — End-to-end carousel generation
  - Returns: `(slides, diagnostics)` or raises `CarouselShapeError` with shape diagnostics
  - Uses: Sonnet 4.6 (brief → editorial) + Haiku 4.5 (fit copy)
- `_stage_one_editorial(brief, format_type)` — Sonnet editorial pass
- `_stage_two_fit(slides, layout_profile, layout_mode)` — Haiku line fitter
- `CarouselShapeError` — Exception with `diagnostics` field (used by agent to tag failures)

**Configuration:**
- `SONNET_MODEL = "claude-3-5-sonnet-20241022"`
- `HAIKU_MODEL = "claude-3-5-haiku-20241022"`
- Max retries per slide: 3

### `carousel_rules.py`

**Exports:**
- `LAYOUT_PROFILES` — Dict mapping profile name → (font, char_cap, height_px, autofit_range)
- `ONE_SLIDE_ONE_IDEA` — String constant (canonical reference for "one idea per slide" rule)
- `validate_carousel_shape(slides)` — Check min/max slide count, cover/closing structure
- `max_lines_for_layout(layout_profile)` — Height constraint in lines

**Profiles:**
```python
LAYOUT_PROFILES = {
    "compact_legacy": {
        "body_font": "Archivo Black 900",
        "char_cap": 24,
        "height_px": 320,
        "autofit": False,
    },
    "readable_list": {
        "body_font": "Space Grotesk SemiBold",
        "char_cap": 56,
        "height_px": 400,  # half-box autofit 64px → 28px
        "autofit": True,  # JavaScript auto-sizing
    },
}
```

### `quotes.py`

**Exports:**
- `pick_closing_quote(category, used_quotes_ledger)` → Quote text + attribution
- Maintains dedup via `QuoteBank._session_hashes` to prevent same quote across carousel runs

**Source:** Hand-curated bank in `insta-brain/bank/quotes.md` (verified, sourced)

### `fact_topic_router.py`

**Input:** Brief text  
**Output:** Category enum (science, history, nature, technology, culture, etc.)  

Used by Sonnet to pick narrative patterns and entity types.

### `narrative_beats.py`

**Exports:** Narrative patterns as templates
- `TIMELINE` — Historical progression (dates, events, consequences)
- `COMPARISON` — Side-by-side contrast (two entities, shared pattern)
- `DISCOVERY` — Journey from unknown to insight
- `COUNTDOWN` — Ranked list (top N)
- `CAUSE_EFFECT` — Why something happened, what happened next

Each pattern has: opening hook, data structure, entity roles, closing frame.

### `story_scout.py`

**Purpose:** Source current-event angles  
**Usage:** Optional; used by agent to find timely topics  
**Not used by core carousel pipeline.** The agent picks the brief; this is a helper.

### `fact_checker.py`

**Exports:**
- `verify_claim(claim_text) → (confidence: float, sources: List[SourceCite])`
- Confidence scale: 0.0–1.0; gate is ≥0.65
- Returns: At least 2 distinct sources (URL, title, author, publication)
- Raises: `UnverifiableClaimError` if sources < 2 or confidence < 0.65

**Process:**
1. Claim extraction: Identify factual assertions (dates, numbers, names)
2. Web search: Query each assertion independently
3. Source validation: Scan result text for confirmation
4. Confidence scoring: Based on source agreement + expertise signals
5. Correction signal: Look for contradiction keywords in results

**Configuration:**
- `MIN_SOURCES = 2`
- `MIN_CONFIDENCE = 0.65`
- `MAX_AGE_DAYS = 7` (prefer recent sources)
- Scoped search (no Reddit, no social media, prefer academic + news)

### `entity_image_validator.py`

**Purpose:** Map entity (person, place, thing) to visual intent  
**Input:** Entity type (NamedEntity from NER), category (science, history, etc.)  
**Output:** `visual_intent` (entity, action, concept, comparison, chart)  

Used by Sonnet to annotate slides with what image to fetch.

---

## Fact Sourcing & Verification

### Fact discovery (agent-sourced)

The autonomous agent does not use `fact_discovery.py` or `rare_fact_bank.py` (both deleted 2026-05-10). Instead:

1. Agent reads a prompt with INTERESTINGNESS / EVENT-VS-ANGLE / QUALITY gates
2. Agent sourced facts from its training data (Sonnet 4.6 knowledge cutoff)
3. Agent writes a brief or script directly
4. Pipeline verifies the brief's facts via `fact_checker.py`

### Fact verification gate

**Applied to:** Every carousel (all types: fact, list, timeline, etc.)

**Pipeline:**
1. `carousel_writer.py:stage_one` calls `fact_checker.py:verify_claim` for each factual statement
2. Fact checker returns confidence + sources
3. If confidence < 0.65: Reject, raise error, agent receives `FAILURE_KIND: fact_verification_failed`
4. If confidence ≥ 0.65: Pass, include sources in carousel metadata

**Hard rule:** Non-negotiable. Skip is better than publishing unverified content.

---

## Quote Selection

### `quotes.py:pick_closing_quote`

**Input:** Category (science, history, nature, etc.) + used quotes ledger  
**Output:** Quote text + attribution (verified source)  

**Dedup logic:**
- `QuoteBank._session_hashes` tracks quote hashes in the current run
- Prevents same closing quote from appearing in two carousels from the same agent run
- Does not prevent reuse across days (ledger reset per run)

**Source:** Hand-curated `insta-brain/bank/quotes.md` (every quote is verified + attributed)

---

## Copy Rules & Constraints

### Carousel Copy Rules (all types)

| Rule | Enforced by | Action |
|---|---|---|
| **ONE SLIDE = ONE IDEA** | `carousel_rules.py`, Sonnet prompt | Sonnet avoids multi-idea slides; Haiku rejects them |
| **Entity variety** | Sonnet prompt | No entity appears in multiple slides |
| **Headline ≤ char_cap** | `carousel_writer.py:_stage_two_fit` | Haiku shortens to cap or aborts |
| **Body ≤ lines_for_profile** | `line_fit_probe.py` | Measure on canvas, retry or abort |
| **No truncation** | `carousel_rules.py:validate_shape` | Abort if any slide cannot fit without cutting |
| **Cover hooks without spoil** | Sonnet prompt | Cover teases angle, does not reveal answer |
| **Closing has verified quote** | `quotes.py` + `fact_checker.py` | Every quote is sourced, deduplicated |
| **Fact claims ≥ 2 sources** | `fact_checker.py` | Verify all factual statements at carousel level |

### Format-specific rules

**List format:**
- Cover must state ONE defensible criterion (e.g. "Engineering Disasters by Death Toll")
- No opinion superlatives (scariest, best, worst) — use objective criteria or skip the list
- Each item ranked by the criterion

**Timeline format:**
- Chronological order (mandatory)
- Each slide represents one event or milestone
- Opening slide: date range + overview

**Comparison format:**
- Two entities contrasted across shared dimensions
- Slides alternate (Entity A trait, Entity B trait, both summary)

---

## Integration with Pipelines

### From Agent to Carousel

```
autonomous-reel.yml (agent)
  → run_carousel(format_type="list", brief="...")
    → pipelines/carousel/ship_carousel_post.py --brief ... --type list
      → src/content/carousel_writer.py:generate_content()
        → Stage 1: Sonnet editorial + fact_checker
        → Stage 2: Haiku line fitter + shape validation
        → Output: Final slides ready to render
      → src/research/image_sourcer.py (next module, see images.md)
```

### From Agent to Reel

```
autonomous-reel.yml (agent)
  → run_reel(script="...", title="...")
    → pipelines/reel/make_reel.py --script ... --title ...
      → Reel pipeline does NOT use carousel_writer.py
      → Script is agent-provided; no two-stage generation
      → Voiceover generated directly from script (src/render/tts_engine.py)
      → Fact verification still applied at agent prompt level
```

---

## Error Handling & Debugging

| Error | Raised by | Caught by | Recovery |
|---|---|---|---|
| `CarouselShapeError` | `carousel_writer.py` | Agent tool wrapper | Tagged as `FAILURE_KIND: shape_error`; agent re-briefs |
| `UnverifiableClaimError` | `fact_checker.py` | `carousel_writer.py:stage_one` | Abort carousel; tagged as `fact_verification_failed` |
| `OVERCAP_SLIDE_LINES` | `line_fit_probe.py` | `_stage_two_fit` | Retry (max 3x) or abort |
| `CharacterCapExceeded` | `carousel_rules.py` | Haiku prompt | Shorten or restructure |
| Quote not found | `quotes.py` | Fallback quote | Use generic quote from bank |

---

## Testing Content Generation

```bash
# Test carousel writing (dry, no image fetch)
python3 << 'EOF'
from src.content.carousel_writer import generate_content

brief = "Three engineering disasters that killed more people than wars..."
slides, diag = generate_content(brief, format_type="list", layout_mode="readable_list")

for i, slide in enumerate(slides):
    print(f"Slide {i}: {slide.headline}")
    print(f"  Intent: {slide.visual_intent}")
    print(f"  Body: {slide.body[:50]}...")
EOF

# Test fact checker
python3 << 'EOF'
from src.verification.fact_checker import verify_claim

confidence, sources = verify_claim("The Banqiao Dam failed in 1975.")
print(f"Confidence: {confidence}, Sources: {len(sources)}")
EOF
```

---

## Related Documentation

- `SPEC_FACTJOT_SYSTEM.md` § 5 — Lifecycle stages (Generate stage detail)
- `SPEC_IMAGE_PIPELINE.md` — How visual intents are matched to images
- `src/render/line_fit_probe.py` — Character width measurement on canvas
- `docs/CODEMAPS/rendering.md` — How final slides are rendered to PNG
