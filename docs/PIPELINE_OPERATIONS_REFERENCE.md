# Pipeline operations reference

**Purpose:** Single place for what actually runs in production after the 2026 content quality recovery, how it was verified, and where to look for cleanup candidates.  
**Last updated:** 2026-05-08

For **files that may be archived or removed** (with evidence and caveats), use the repo root **`CLEANUP_AUDIT.md`**. This document does not duplicate that inventory line-by-line.

---

## 1. Active GitHub Actions workflows

| Workflow | Role |
|----------|------|
| `.github/workflows/autonomous-reel.yml` | Scheduled evergreen poster: `reel_morning`, `list`, `reel_evening`, `fact` via autonomous agent. |
| `.github/workflows/manual-run.yml` | `workflow_dispatch` prompt-driven manual reel/carousel runs. |
| `.github/workflows/test.yml` | PR and non-main pushes: `pytest tests/ -v` only. Does not execute pipeline entrypoints. |
| `.github/workflows/pages.yml` | Builds `docs/` for GitHub Pages. No Instagram or pipeline posting. |

The breaking-news watcher (`.github/workflows/news-watcher.yml`) was deleted in audit Phase G.2. See section 2 below for the impact on `pipelines/news/`.

---

## 2. Production path (autonomous agent)

**Entrypoint:** `scripts/autonomous_agent.py` (`POST_MODE` from schedule or dispatch).

**Subprocess entrypoints:**

| Slot | Pipeline | Layout profile |
|------|----------|----------------|
| `reel_morning`, `reel_evening` | `pipelines/reel/make_reel.py` | n/a (reel) |
| `list` | `pipelines/carousel/ship_carousel_post.py` | `readable_list` (since 2026-05-08) |
| `fact` | `pipelines/carousel/ship_carousel_post.py` | `compact_legacy` |

Routing lives in `scripts/autonomous_agent.py:run_carousel`: the agent appends `--layout-mode readable_list` for `format_type == "list"`. Direct CLI invocations of `ship_carousel_post.py` without `--layout-mode` default to `compact_legacy` for any sub-type, including news. See CLAUDE.md §10 and `src/content/carousel_rules.py:LAYOUT_PROFILES` for the per-profile font / cap / autosize details.

**Breaking-news path:** killed in audit Phase G.2 (decision B). The watcher (`check_guardian_rss.py`), the wrapper (`ship_news_breaking.py`), and the workflow (`news-watcher.yml`) were all deleted on 2026-05-10. Only `pipelines/news/ship_news_post.py` survives because the manual carousel pipeline imports its renderer functions; do not invoke its CLI.

**Other steps in `autonomous-reel.yml` (direct `python3` calls):**

- `pipelines/shared/refresh_token.py` (soft)
- `scripts/upload_to_youtube.py` (soft, reel success path only)
- `pipelines/reel/fetch_reel_metrics.py` (soft, `if: always()`)
- `pipelines/shared/log_workflow_failure.py` (on failure)

**Indirect but required on the carousel path:**  
`pipelines/carousel/ship_carousel_post.py` wraps `pipelines/manual/ship_manual_post.py`, which imports render helpers from **`pipelines/news/ship_news_post.py`** (dual role: news CLI + shared renderer). Do not delete `ship_news_post.py` without replacing that import path.

---

## 3. Content quality recovery (summary)

Work tracked in **`docs/superpowers/plans/2026-05-07-autonomous-content-quality-recovery.md`**. Implemented areas (high level):

- **Phase 0:** Structured shape errors (`CarouselShapeError` / `build_shape_diagnostics`), no silent slide or line slicing, `data/ledgers/carousel_quality.jsonl`, `FAILURE_KIND:` prefixes on agent tool output (carousel and reel maps differ but both use `_tag_failure_kind`).
- **Phase 1:** Two-stage carousel generation in `src/content/carousel_writer.py` (Sonnet editorial + Haiku fitter), fact-preservation errors where applicable.
- **Phase 2:** `src/render/line_fit_probe.py` (per-slide-kind caps, Playwright width probe, retry loop in `generate_content`).
- **Phase 3:** `src/research/image_sourcer.py` (slot intent, provider routing), `src/research/image_fetcher.py` (token-boundary negative terms), `MAX_REUSES` aligned with `SPEC_IMAGE_PIPELINE.md`.
- **Phase 4:** `src/content/carousel_rules.py` as shared rules source; duplication reduced in agent + manual pipeline.

**Canonical rule string in Python:** a repo-wide search for the literal `ONE SLIDE = ONE IDEA` under `*.py` should resolve to **`src/content/carousel_rules.py`** (plan and brain docs may still mention the phrase for narrative reasons).

---

## 4. Verification performed (static + local tests)

- **Tests:** `pytest tests/` reports **34 passed** (as of the post-recovery tree).
- **Workflow YAML:** confirmed `autonomous-reel.yml` and `test.yml` contents match the roles above.
- **Agent tagging:** `run_reel` and `run_carousel` both wrap subprocess output with `FAILURE_KIND` via `_tag_failure_kind`.

**Not re-verified in this document:** individual GitHub Actions run history (green/red). Check the Actions tab on the repo for live status.

---

## 5. Operational gaps to be aware of

- **`carousel_quality.jsonl`:** written by `ship_carousel_post.py` (via the manual module) and staged in the `autonomous-reel.yml` state-commit `git add` loop.
- **Dry-run contracts:** `ship_carousel_post.py` uses `--dry-run`; the agent respects **`DRY_RUN=true`** in the environment (`scripts/autonomous_agent.py`), not a `--dry-run` flag for the agent process.
- **Docs drift:** `insta-brain/` and parts of `README.md` may still describe old `scripts/*.py` paths, deleted workflows, or queue-based publishing. Treat **`SPEC_FACTJOT_SYSTEM.md`**, root **`CLAUDE.md`**, and this file** as the architecture prompts to reconcile against; brain notes are not always migrated.

---

## 6. Reel media (faq)

Reels are **not** image-only. `make_reel.py` builds from **video footage** where possible; still images from entity tiers can be converted to MP4 in **`src/render/reel_composer.py`** (`_still_to_mp4`) before final composition.

---

## 7. Related documents

| Document | Use |
|----------|-----|
| `CLEANUP_AUDIT.md` | Removal and archive candidates, per-file classification, evidence method. |
| `SPEC_IMAGE_PIPELINE.md` | Image sourcing, reuse, fallbacks (non-negotiables). |
| `SPEC_FACTJOT_SYSTEM.md` | System constitution and known mismatches (e.g. manual vs news renderer). |
| `docs/superpowers/plans/2026-05-07-autonomous-content-quality-recovery.md` | Original phased implementation plan. |
