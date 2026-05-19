# factjot Architecture Codemap

**Last Updated:** 2026-05-19  
**Repository:** /Users/Music/Developer/Insta-bot  
**Status:** Autonomous Instagram + YouTube publishing system  

This index maps the architectural structure of factjot. Each area has a dedicated codemap. Start with the area matching your task, then cross-reference related modules.

## Quick Navigation

| Area | Purpose | Entry Points |
|---|---|---|
| **[Pipelines & Publishing](./pipelines.md)** | Post-type workflows (reel, carousel, list) and GitHub Actions orchestration | `pipelines/{reel,carousel,list}/` + `.github/workflows/autonomous-reel.yml` |
| **[Content Generation](./content.md)** | Carousel writing, reel scripting, fact sourcing, copy generation | `src/content/` + `src/research/` (non-image modules) |
| **[Image Pipeline](./images.md)** | Image sourcing, validation, fetching, reuse tracking | `src/research/{image_*.py, sourcer.py}` + `data/ledgers/used_images.jsonl` |
| **[Rendering & Media](./rendering.md)** | PNG carousel slides, MP4 reel composition, thumbnail + story rendering | `src/render/` + `pipelines/reel/download_music.py` |
| **[Publishing & API](./publishing.md)** | Instagram Graph API, image hosting (imgbb), state commits, ledger management | `src/publish/` + `src/brain.py` |
| **[Core & Shared](./core.md)** | Configuration, models, paths, brand, JSON storage | `src/core/` |
| **[Data & State](./data.md)** | Ledgers (append-only), per-run output, state tracking | `data/ledgers/` + `output/` + `insta-brain/` |
| **[Testing & Verification](./testing.md)** | Unit + integration tests, fact verification, visual verification | `tests/` + `src/verification/` |

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│  insta-brain/    rules, ledgers, bank, log              │
├─────────────────────────────────────────────────────────┤
│  pipelines/      reel, carousel, list, manual           │
│  .github/        autonomous-reel.yml, manual-run.yml    │
├─────────────────────────────────────────────────────────┤
│  src/            research, content, render, publish     │
├─────────────────────────────────────────────────────────┤
│  data/ledgers/   used_images, used_footage, api_costs   │
│  output/         per-run rendered artefacts             │
└─────────────────────────────────────────────────────────┘
```

## Pipeline Lifecycle (all types)

```
SOURCE → VERIFY → GENERATE → ACQUIRE MEDIA → RENDER → [APPROVE] → PUBLISH → LEDGER → MEASURE
```

- **Autonomous mode:** reel_morning (08:00 UTC), list_midday (11:30 UTC). Agent chooses subject + angle, pipelines handle the rest. Skip-on-weak for quality gate.
- **Editorial mode:** Manual dispatch via `manual-run.yml`. Same pipeline, human-guided brief/script input.
- **Safety gates:** Fact verification ≥2 sources, image validation (licence, provider, match), dedupe (posted + images), reel duration/audio quality.

## Key Files (Always Read First)

1. **`CLAUDE.md`** — Project operating rules, hard constraints, environment specifics
2. **`SPEC_FACTJOT_SYSTEM.md`** — System constitution, lifecycle stages, two-mode model (autonomous vs editorial)
3. **`SPEC_IMAGE_PIPELINE.md`** — Image sourcing rules, provider order, fallback logic, reuse policy
4. **`insta-brain/gotchas.md`** — Incident log and failure patterns to avoid
5. **`docs/PIPELINE_OPERATIONS_REFERENCE.md`** — What actually runs in production

## Cross-Cutting Concerns

### Dedupe & Ledgers
- **Posted dedupe:** `src/brain.py` reads `insta-brain/data/posted.jsonl`; agent applies duplicate guard
- **Image reuse:** `src/research/used_images.py` tracks via `data/ledgers/used_images.jsonl` (URL + SHA256)
- **Footage reuse:** `data/ledgers/used_footage_urls.jsonl` for reel video sources

### Brand & Visual Identity
- **Source of truth:** `brand/brand_kit.json` (v2.1)
- **Rendered via:** `src/core/brand.py` → consumed by all renderers
- **Typography:** Archivo Black (900) for hooks/subtitles; Instrument Serif for titles; Space Grotesk for body (readable_list profile only)

### Voice & Tone Rules
- No em-dashes in YAML (breaks GitHub Actions dispatch)
- British English throughout
- Direct, specific language; no superlatives in list covers
- Shock through specificity, not hype

### Environment & Secrets
- `META_ACCESS_TOKEN`, `IMGBB_API_KEY`, `ELEVENLABS_API_KEY` via GitHub secrets
- Local: `.env` file (see `.env.example`)
- Canonical Python: `/Library/Frameworks/Python.framework/Versions/Current/bin/python3`

## Common Tasks & Where to Look

| Task | Look Here |
|---|---|
| Add new image provider | `SPEC_IMAGE_PIPELINE.md` + `src/research/source_registry.py` |
| Change carousel layout/fonts | `src/render/carousel_slides.py` + `brand/brand_kit.json` |
| Modify reel encoding settings | `src/render/reel_composer.py` (CRF, maxrate, codec) |
| Add new pipeline mode | `SPEC_FACTJOT_SYSTEM.md` + `CLAUDE.md` (plan mode required) |
| Debug image quality | `src/research/image_sourcer.py` (scores) + `src/research/entity_image_validator.py` |
| Check posting status | `insta-brain/data/posted.jsonl` (ledger) |
| View workflow logs | GitHub Actions → `Autonomous Post` → failed run |

## Related Documentation

- **README.md** — Setup, troubleshooting (partly legacy; prefer the SPEC)
- **ROADMAP.md** — Deferred work (Phase 8+)
- **docs/superpowers/plans/** — Historical implementation plans (quality recovery, transitions)
