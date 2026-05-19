# Image Pipeline Codemap

**Last Updated:** 2026-05-19  
**Modules:** `src/research/image_*.py`, `src/research/sourcer.py`  
**Authority:** `SPEC_IMAGE_PIPELINE.md` (all non-negotiable rules live there)  
**State:** `data/ledgers/used_images.jsonl` (append-only)  

---

## Image Pipeline Overview

```
Generate carousel slides (src/content/carousel_writer.py)
  ↓ Each slide has visual_intent (entity, action, concept, etc.)
  ↓
Image sourcer (src/research/image_sourcer.py)
  ↓ Scores candidates, picks provider order
  ↓
Image fetcher (src/research/image_fetcher.py)
  ↓ Queries providers, validates licence + metadata
  ↓
Entity validator (src/research/entity_image_validator.py)
  ↓ Confirms image matches entity (Wikidata, named entities)
  ↓
Dedupe (src/research/used_images.py)
  ↓ Check URL + SHA256 against ledger
  ↓
Final image ready for render
```

---

## Core Modules

### `image_sourcer.py`

**Purpose:** Score candidate images per slide, route to provider sequence.

**Exports:**
- `ImageSourcer(relax=False)` — Class constructor
  - `relax=False` — Strict: R3 score floor 8 (compact_legacy, tight confidence)
  - `relax=True` — Relaxed: R3 score floor 6 (readable_list, allow moderately-confident candidates)
- `sourcer.rank_candidates(query, entity, category, is_news=False)` — Returns sorted list of candidates

**Scoring tiers (R1, R2, R3):**
- **R1 (High confidence)** — Wikipedia image, Wikimedia Commons, direct entity match from named source
- **R2 (Medium confidence)** — Stock photo (Pexels, Pixabay, Unsplash) with keyword match + human review
- **R3 (Fallback)** — Generic concept search (NASA, iNaturalist, generic stock) with score floor

**Provider order** (source of truth in `SPEC_IMAGE_PIPELINE.md` §6):
1. Wikimedia Commons (public domain, verified)
2. Wikipedia (linked images, curated)
3. iNaturalist (species + nature, scientific)
4. Smithsonian (verified public domain, DEMO_KEY tier)
5. NASA Images (space + earth science)
6. Openverse (aggregates Flickr, Europeana, etc.)
7. Pexels (stock photo, human-reviewed)
8. Pixabay (large stock, human-reviewed)
9. imgbb search fallback (web image search, lowest confidence)

**Scoring algorithm:**
```python
score = (
    entity_match_weight * entity_score +        # Is this THE entity? (0–10)
    keyword_relevance_weight * relevance_score +  # Does it match the headline? (0–10)
    source_credibility_weight * credibility +    # How trusted is the provider? (0–10)
    license_quality_weight * license_score       # Is it freely usable? (0–10)
)
# Floor: R1 ≥ 9, R2 ≥ 7, R3 ≥ 6 (or 8 if not relaxed)
```

### `image_fetcher.py`

**Purpose:** Query image providers, download, validate.

**Exports:**
- `ImageFetcher` — Class that queries one provider at a time
  - `fetch(query, provider, timeout=15s)` — Returns list of image URLs
- `_query_variants(entity, headline, category)` → List of search term variations
  - Removes token boundaries (dates like "1975" become wildcard match)
  - Adds negative terms (exclude abstract, cartoon, diagram if not appropriate)

**Negative terms:**
- Abstract, cartoon, diagram, graph, chart, screenshot (for entity/action slides)
- Portrait, selfie, mugshot (for location/concept slides)
- Logo, icon, infographic (all types)

**Provider-specific logic:**
- **Wikimedia:** API query, check licence field (must be CC0, CC-BY, or equivalent)
- **Wikipedia:** Parse `File:` page, extract licence from infobox
- **iNaturalist:** API query, check observer count (higher = more verified)
- **NASA:** API query, download from CDN, check public domain flag
- **Pexels/Pixabay:** API query, filter by license (all are free)
- **Openverse:** API query, cross-check licence field
- **imgbb:** Web search fallback, minimal validation (last resort)

**Validation:**
- URL must be HTTPS (security)
- Image dimensions: min 400x400, max 4000x4000 (carousel fit)
- Aspect ratio: 0.5–2.0 (not extreme)
- File size: max 5 MB (for Cloudinary upload)
- Licence: must be freely reusable (CC0, CC-BY, CC-BY-SA, public domain, or platform ToS allows)

### `used_images.py`

**Purpose:** Track image reuse (ledger-based dedupe).

**Exports:**
- `UsedImagesLedger` — Class to query and update `data/ledgers/used_images.jsonl`
- `ledger.is_used(url, sha256)` → bool (has this URL + image hash been posted before?)
- `ledger.add(url, sha256, timestamp)` → Append to ledger
- `ledger.get_recent_by_entity(entity_name, days=7)` → Images posted in last N days for that entity

**Ledger entry format:**
```json
{
  "url": "https://...",
  "sha256": "abc123...",
  "posted_at": "2026-05-19T08:30:00Z",
  "carousel_id": "123456789_456",
  "slide_index": 2,
  "entity": "Marie Curie",
  "category": "science"
}
```

**Dedup rule:** URL + SHA256 together uniquely identify an image. If either changed, it's not a reuse.
- URL changed (rehosted) + same image (same SHA) = **blocked** (rule 02)
- URL same + image modified (different SHA) = **allowed** (different image content)

### `entity_image_validator.py`

**Purpose:** Confirm image matches the intended entity (Wikidata resolution).

**Exports:**
- `validate_entity_match(image_metadata, entity_name, wikidata_id)` → confidence: float
- `get_entity_from_image(image_url, image_metadata)` → (entity_name, wikidata_id, confidence)

**Process:**
1. Extract text/metadata from image (OCR, filename, provider tags)
2. Resolve entity: Wikidata lookup by ID or name
3. Compare: Does image metadata mention the entity? (name, alternate names, related entities)
4. Score: Based on text coverage, metadata confidence, provider expertise

**Confidence scale:**
- 0.9–1.0 — Direct entity (e.g. Wikipedia Curie article image)
- 0.7–0.9 — Strong match (Wikidata image, same entity named in alt text)
- 0.5–0.7 — Contextual match (person in relevant photo, correct era)
- <0.5 — Rejected (generic or irrelevant)

**Hard rule:** Entity confidence ≥ 0.65 required to use image on content slide (not cover or closing).

### `source_registry.py`

**Purpose:** Central registry of all image sources.

**Exports:**
- `SOURCES` — Dict of provider name → (API endpoint, keys required, rate limit, licence scope)
- `PRIORITY_ORDER` — Ordered list of provider names (source of truth alongside `SPEC_IMAGE_PIPELINE.md`)

**Entry structure:**
```python
{
    "wikimedia": {
        "endpoint": "https://commons.wikimedia.org/w/api.php",
        "auth": "none",
        "rate_limit": "unlimited",
        "licence_scope": "CC0, CC-BY, CC-BY-SA",
    },
    "pexels": {
        "endpoint": "https://api.pexels.com/v1/search",
        "auth": "API_KEY",
        "rate_limit": "200/hour",
        "licence_scope": "CC0 (platform ToS)",
    },
    # ... etc
}
```

### `visual_intents.py`

**Purpose:** Define image intent types + query templates.

**Exports:**
- `VisualIntent` — Enum: ENTITY, ACTION, CONCEPT, COMPARISON, CHART
- `intent_to_search_query(intent, entity, context)` → Search string for fetcher

**Query templates:**
```python
ENTITY:      "{entity_name}"
ACTION:      "{entity_name} {verb}" (e.g. "Marie Curie discovering radium")
CONCEPT:     "{concept} {domain}" (e.g. "radioactivity physics")
COMPARISON:  "{entity1} vs {entity2}" or just "{entity1} {entity2}"
CHART:       "{concept} chart", "{entity} timeline" (rarely used; usually generic)
```

---

## Workflow: Carousel Image Sourcing

### When: Carousel pipeline calls image sourcer

```
ship_carousel_post.py
  for each slide in carousel.slides:
    visual_intent = slide.visual_intent  # ENTITY, ACTION, CONCEPT
    headline = slide.headline
    
    # 1. Score candidates per provider
    sourcer = ImageSourcer(relax=profile.relax_images)
    candidates = sourcer.rank_candidates(
        query=headline,
        entity=extract_entity(slide),
        category=carousel.category,
        is_news=carousel.is_news
    )
    
    # 2. Try providers in order (R1 → R2 → R3)
    for provider in R1_PROVIDERS:
        images = fetcher.fetch(candidates[provider], provider)
        if images:
            image = images[0]  # Top-ranked
            break
    else:
        # R1 failed, try R2
        for provider in R2_PROVIDERS:
            ...
    else:
        # R2 failed, try R3
        for provider in R3_PROVIDERS:
            ...
    else:
        # All failed; use placeholder or skip
        image = None  # Will trigger "No empty image boxes" error
    
    # 3. Validate match + dedup
    confidence = entity_validator.validate_entity_match(
        image.metadata,
        entity=extract_entity(slide),
        wikidata_id=...
    )
    if confidence < 0.65:
        # Not a match; try next candidate
        continue
    
    if used_images.is_used(image.url, image.sha256):
        # Already posted; try next candidate
        continue
    
    # 4. Add to ledger
    used_images.add(image.url, image.sha256, carousel.id)
    slide.image = image
```

### Fallback routes (R1 → R2 → R3)

**R1 (High confidence):**
- Wikimedia Commons → Wikipedia article images
- Direct Wikidata images
- Provider: Wikimedia, Wikipedia, iNaturalist (for species)

**R2 (Stock photos):**
- Human-reviewed stock: Pexels, Pixabay, Unsplash, Openverse
- Used when entity is well-known but Wikidata image not available

**R3 (Concept/fallback):**
- Generic concept search (NASA, Smithsonian, generic stock)
- Relaxed scoring (floor 6 instead of 8)
- Used when entity-specific image fails

---

## Layout-Specific Scoring

### compact_legacy (fact carousel)

- **Relax:** False (strict scoring, R3 floor 8)
- **Rationale:** Limited space, high visual density; must be confident images
- **Negative terms applied:** Abstract, cartoon, diagram, etc.

### readable_list (list carousel)

- **Relax:** True (lenient scoring, R3 floor 6)
- **Rationale:** Half-page images, more space; moderately-confident OK
- **Negative terms:** Still applied, but floor is lower

---

## Ledger Discipline

### `data/ledgers/used_images.jsonl`

**Append-only ledger of every image posted.**

Entry:
```json
{
  "timestamp": "2026-05-19T08:30:00Z",
  "carousel_id": "123456789_456",
  "slide_index": 2,
  "url": "https://commons.wikimedia.org/wiki/File:...",
  "sha256": "abc123def456...",
  "entity": "Marie Curie",
  "entity_confidence": 0.92,
  "provider": "wikimedia",
  "category": "science"
}
```

**Why SHA256 + URL?**
- URL alone is fragile (CDN redirects, hotlinks)
- SHA256 alone is fragile (image may be rehosted)
- Together: URL + SHA uniquely identify a specific image posted at a specific time

**Reuse policy (from SPEC_IMAGE_PIPELINE.md §11):**
- **No image reuse across posts.** `MAX_REUSES = 1` (never post same image twice)
- **No entity reuse (strict).** Entity "Marie Curie" never appears across two carousel slides in the same post
- **No entity reuse (soft, inter-post).** Prefer new entities within a week; reuse after 7 days is acceptable

---

## Error Handling & Fallbacks

| Problem | Trigger | Fallback |
|---|---|---|
| Provider API timeout | No response in 15s | Skip to next provider |
| No images found (all R1–R3 empty) | All providers failed | Abort carousel with `image_fetch_failed` |
| Image doesn't match entity | Entity confidence < 0.65 | Try next candidate from same provider |
| Image already used | SHA256 in ledger | Try next candidate from same provider |
| Image licence unknown | Provider doesn't specify | Reject (safer) |
| Image dimensions invalid | < 400x400 or > 4000x4000 | Reject |
| Broken URL | HTTP 404/403 after download | Mark as dead, skip |

---

## Testing Image Sourcing

```bash
# Test image sourcer
python3 << 'EOF'
from src.research.image_sourcer import ImageSourcer

sourcer = ImageSourcer(relax=False)
candidates = sourcer.rank_candidates(
    query="Marie Curie discovered radium",
    entity="Marie Curie",
    category="science",
    is_news=False
)

print(f"Top candidates:")
for provider, score in candidates[:5]:
    print(f"  {provider}: {score}")
EOF

# Test fetcher
python3 << 'EOF'
from src.research.image_fetcher import ImageFetcher

fetcher = ImageFetcher()
images = fetcher.fetch(
    query="Marie Curie",
    provider="wikimedia"
)

for img in images[:3]:
    print(f"  {img.url} (confidence: {img.confidence})")
EOF

# Check used images
python3 << 'EOF'
from src.research.used_images import UsedImagesLedger

ledger = UsedImagesLedger()
recent = ledger.get_recent_by_entity("Marie Curie", days=7)
print(f"Marie Curie images posted in last 7 days: {len(recent)}")
EOF
```

---

## Known Issues & Mitigations

| Issue | Cause | Mitigation |
|---|---|---|
| Pexels often returns same "popular" images | Limited pool, high download counts | Exclude Pexels in R2 (SPEC directive); use R1 first |
| Wikidata images outdated | Curated once, not refreshed | Fallback to Wikipedia if Wikidata fails |
| iNaturalist species misidentified | Crowd-sourced; lower confidence | Require observer_count ≥ 10 + manual review on renders |
| TMDB poster/backdrop seeding weak | Year + title not unique | Confidence gate: token overlap ≥ 0.8, year check if present |
| Generic search returns unrelated results | Keyword pollution | Use negative terms + entity name + category + provider credibility |

---

## Related Documentation

- `SPEC_IMAGE_PIPELINE.md` — Authoritative rules, provider order, licence policy, fallback algorithm
- `docs/CODEMAPS/content.md` — How visual intents are generated (carousel_writer.py)
- `docs/CODEMAPS/rendering.md` — How images are composited into PNG slides
- `src/research/source_registry.py` — Full provider registry
