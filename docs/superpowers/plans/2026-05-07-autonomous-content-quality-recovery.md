# Autonomous Content Quality Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate silent content trimming, decouple editorial writing from layout fitting, add render-aware line-fit validation, and tighten image-intent routing so autonomous carousels read coherent and look intentional.

**Architecture:** The current pipeline mixes editorial generation, layout fitting, and image-intent generation in one Sonnet call constrained by a 24-character hard cap. This plan splits those concerns into discrete stages with hard gates between them: a Stage A editorial writer that owns meaning, a Stage B fitter that owns line geometry without changing facts, a Stage C render-aware probe that measures actual text width, and a Stage D image-intent router that picks providers per slot intent. Phase 0 first removes silent trimming so the regressions become visible.

**Tech Stack:** Python 3.11, Anthropic SDK (Sonnet 4.6 + Haiku 4.5), Playwright + Chromium, Jinja templates, pytest.

**Approval gates:** Each phase below ends with a STOP block. The agent MUST stop and ask Toby for approval before starting the next phase. No skipping ahead.

---

## Pre-flight checklist (must pass before Task 0.1)

Do not write a line of code until every item below is confirmed. If any item fails, stop and ask Toby before proceeding.

- [ ] **PF-1.** This plan has been read end to end, including all four phases and all STOP gates.
- [ ] **PF-2.** The "Slide-count contract" section has been read. You can state, without scrolling back, what `total_slides` means, what `n_content_slides` means, and where conversion happens (`main()` only).
- [ ] **PF-3.** The "Dry-run contract" section has been read. You will use `--dry-run` for `pipelines/manual/ship_manual_post.py` and `DRY_RUN=true` env-var prefix for `scripts/autonomous_agent.py`. Never the other way round.
- [ ] **PF-4.** Verify the Anthropic model identifier `claude-haiku-4-5-20251001` is valid for this account before any code uses it. Run a one-message smoke call from the existing repo's `.env`. If the API rejects the ID, stop and ask Toby for the correct Haiku 4.5 identifier; do NOT silently fall back to Haiku 3.5 or guess a date suffix.
- [ ] **PF-5.** `git status` is clean or only contains files the user expects (PLAN.md, ROADMAP.md, memory/, scripts/_preview_new_story.py, the plan file itself). No accidental WIP from another task.
- [ ] **PF-6.** You are on `main` and have read CLAUDE.md's hard rules. In particular: no em dashes anywhere, no force-push to main, and `pipelines/news/ship_news_post.py` has a documented dual-role you must not break (renders both manual and news carousels).
- [ ] **PF-7.** The autonomous workflow is the only intentional poster. Do not re-add any deleted legacy workflow (carousel-morning, list-carousel, etc.). Phases 0-4 must not introduce new GitHub Actions cron triggers.
- [ ] **PF-8.** Tests are run via `/Library/Frameworks/Python.framework/Versions/Current/bin/python3 -m pytest`. Bare `python3` is NOT acceptable locally (CLAUDE.md "Canonical Python path" rule).
- [ ] **PF-9.** You will not edit `src/research/image_sourcer.py` or `src/research/image_fetcher.py` outside Phase 3, even if you spot a related bug. Image-pipeline edits require plan-mode discipline (CLAUDE.md hard rule).
- [ ] **PF-10.** Each task ends with: tests pass + the named smoke command runs cleanly + the named ledger row appears (where applicable) + a single commit. Do not batch multiple tasks into one commit.
- [ ] **PF-11.** STOP gates are literal. After Phase 0 acceptance, you stop and wait for Toby's "go" message in the conversation. You do not "just start Phase 1 since the tests passed". Phase boundaries are human-approval boundaries.
- [ ] **PF-12.** Cost & latency capture is part of the work, not an afterthought. Phase 0's first ledger writes already include `editorial_cost_usd`, `fitter_cost_usd`, `fitter_attempts`, `probe_attempts`, `total_runtime_ms` (defaulting to 0 in Phase 0). Do not skip these fields.
- [ ] **PF-13.** No new dependencies (pip packages, new MCP servers, new Anthropic features) without surfacing in the conversation first. Phase 1 uses the existing `anthropic` SDK; Phase 2 uses the existing `playwright` install.
- [ ] **PF-14.** If a step in this plan disagrees with what you discover in the actual codebase (e.g. line numbers shifted, a function was already renamed), stop and surface the discrepancy. Do not silently adapt - the discrepancy may be load-bearing.
- [ ] **PF-15.** When in doubt, ask. The human review at each STOP gate is a feature, not a delay.

Once all 15 items are checked, paste the checklist back to Toby with each box marked, then proceed to Task 0.1.

---

## Testing philosophy

Unit tests in this plan exercise specific helper functions to drive TDD. They should NOT become a load-bearing contract on internal shape: if a refactor moves logic between modules, tests that call internal helpers can be rewritten freely. The behaviour-level tests that DO need to keep passing across refactors are:

1. A malformed writer payload (wrong slide count, wrong line count, overlong lines, missing entities) causes the carousel run to exit non-zero with a `CONTENT_SHAPE_MISMATCH` line in stdout.
2. A clean dry-run produces exactly one row in `data/ledgers/carousel_quality.jsonl` with `result="dry_run"`.
3. The fitter never publishes a deck where any rendered line exceeds the per-slide-kind cap.
4. Every named entity, date, and integer present in the editorial-stage prose appears verbatim somewhere in the fitted lines for that slide.
5. A run with no usable cover image exits non-zero with `COVER_IMAGE_FAILED` and writes `result="cover_failed"` to the ledger. No partial deck is rendered.
6. The autonomous agent's tool result begins with a `FAILURE_KIND:` tag whose value matches the failure mode in the ledger row.

If a behaviour-level test above starts failing after a refactor, the plan is broken - not the test.

---

## Cost & latency baseline

Phase 1 adds one Haiku 4.5 fitter call per carousel run. Phase 2 adds one Playwright browser launch per fitter attempt (≤ 3 attempts). Both must be tracked so we know whether the recovery has made the pipeline meaningfully slower.

Track in `data/ledgers/carousel_quality.jsonl` for every run:

| Field | Source |
|---|---|
| `editorial_cost_usd` | Stage A usage record. |
| `fitter_cost_usd` | Sum across all fitter attempts (Stage B). |
| `fitter_attempts` | Number of fitter calls (1, 2, or 3). |
| `probe_attempts` | Number of Playwright probe launches (0, 1, 2, 3). |
| `total_runtime_ms` | Wall-clock from `generate_content` start to render-loop start. |

Acceptance baseline (capture from 5 dry-runs before Phase 1, from 5 dry-runs after each subsequent phase):

- Editorial + fitter cost ≤ $0.05 / run.
- Total `generate_content` wall-clock ≤ 25 seconds median, ≤ 45 seconds P95.
- Fitter attempts ≤ 1.5 mean. If above 2.0, the editorial prompt is letting through prose the fitter cannot fit; tighten the editorial prompt before Phase 4.

These targets are stop signals, not gates. If after Phase 2 we are at 60s P95 or $0.15/run, pause and reassess before Phase 3.

---

## Canonical contracts (read first)

These two contracts must hold across every task. Do not deviate without first updating this section.

### Slide-count contract

There are two scalars and they must never be mixed:

| Name | Meaning | Where it appears |
|---|---|---|
| `total_slides` | Cover + content. The IG carousel ships this many images. | CLI `--slides`, render loop, image-sourcer query list |
| `n_content_slides` | Content slides only (excludes cover). | Writer prompt, `EditorialSlide` list, `_enforce_carousel_shape` |

Conversion: `total_slides = n_content_slides + 1`.

Defaults: `fact` and `news` use `total_slides = 6` (so `n_content_slides = 5`). `list` uses `total_slides = 7`.

Diagnostic and shape-check functions use `n_content_slides` exclusively. Anything that talks to the render loop or the image sourcer uses `total_slides`. Conversion happens at the boundary in `main()`, never inside helpers.

### Dry-run contract

- `pipelines/manual/ship_manual_post.py` accepts `--dry-run` (CLI flag).
- `scripts/autonomous_agent.py` reads `DRY_RUN=true` from the environment (no CLI flag - see line 929 of that file).
- Smoke-test commands in this plan that run the agent must use `DRY_RUN=true` as a prefix, never `--dry-run`.

---

## File map

| File | Role | Phase |
|---|---|---|
| `src/content/carousel_diagnostics.py` | NEW. Structured shape-mismatch error + per-run quality block. | 0 |
| `src/content/carousel_rules.py` | NEW. Single source of truth for line caps, weak endings, anti-orphan rules. | 4 |
| `src/content/carousel_writer.py` | NEW. Two-stage writer: `write_editorial_slides()` + `fit_slide_lines()`. | 1 |
| `src/render/line_fit_probe.py` | NEW. Playwright width-measurement helper + per-slide-kind cap. | 2 |
| `pipelines/manual/ship_manual_post.py` | Replace silent slicing with hard fails; wire writer/fitter; wire probe; pass per-slot kind. | 0,1,2,3 |
| `pipelines/news/ship_news_post.py` | Make typography vs photo slide-kind explicit on render input. | 2 |
| `src/research/image_sourcer.py` | Add per-slot intent classifier; route providers by intent. | 3 |
| `src/research/image_fetcher.py` | Token-boundary negative-term matching. | 3 |
| `scripts/autonomous_agent.py` | Surface structured diagnostics in tool result; remove duplicate rule fragments. | 0,4 |
| `data/ledgers/carousel_quality.jsonl` | NEW append-only ledger written each run. | 0 |
| `tests/test_carousel_shape.py` | NEW. Phase 0 unit tests. | 0 |
| `tests/test_carousel_writer_fitter.py` | NEW. Phase 1 unit tests. | 1 |
| `tests/test_line_fit_probe.py` | NEW. Phase 2 unit tests. | 2 |
| `tests/test_image_intent_routing.py` | NEW. Phase 3 unit tests. | 3 |
| `.github/workflows/test.yml` | NEW. Pytest CI on PR + non-main pushes. | 0 |
| `src/research/image_sourcer.py` (`MAX_REUSES` constant) | Align value to SPEC_IMAGE_PIPELINE section 10 (2 uses per carousel). | 3 |

---

## Phase 0 - Observability and safety gates

**Goal:** Stop hiding degradation. Every silent slice becomes a hard fail with a diagnostics block. A new ledger captures per-run quality so we can compare before/after objectively.

### Task 0.1: Diagnostics module

**Files:**
- Create: `src/content/carousel_diagnostics.py`
- Test: `tests/test_carousel_shape.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_carousel_shape.py
from src.content.carousel_diagnostics import (
    CarouselShapeError,
    build_shape_diagnostics,
)


def test_shape_error_carries_structured_payload():
    # Contract: requested_content_slides means content-only (excludes cover).
    diag = build_shape_diagnostics(
        requested_content_slides=5,
        returned_content_slides=8,
        slides=[{"lines": ["a", "b", "c"]} for _ in range(8)],
        dropped_facts=["nuclear test 1958"],
    )
    assert diag["requested_content_slides"] == 5
    assert diag["returned_content_slides"] == 8
    assert diag["dropped_facts"] == ["nuclear test 1958"]
    assert diag["overlong_lines"] == []  # no lines >24 chars in this fixture
    err = CarouselShapeError("shape mismatch", diag)
    assert err.diagnostics["returned_content_slides"] == 8
    # str() must surface the payload so subprocess logs show it
    text = str(err)
    assert "requested_content_slides=5" in text
    assert "returned_content_slides=8" in text


def test_shape_error_flags_overlong_lines():
    diag = build_shape_diagnostics(
        requested_content_slides=5,
        returned_content_slides=5,
        slides=[
            {"lines": ["short", "this is way too long for the renderer", "ok"]},
        ] + [{"lines": ["a", "b", "c"]} for _ in range(4)],
    )
    assert any(o["chars"] > 24 for o in diag["overlong_lines"])
```

- [ ] **Step 2: Run test to verify it fails**

```bash
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 -m pytest tests/test_carousel_shape.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'src.content.carousel_diagnostics'`.

- [ ] **Step 3: Implement the module**

```python
# src/content/carousel_diagnostics.py
"""Structured diagnostics for carousel shape and layout failures.

Phase 0 of the content quality recovery: replaces silent slicing
(`slides[:8]`, `lines[:3]`) with hard fails that carry a payload an
operator can read in the autonomous agent's tool result and in the
quality ledger.
"""
from __future__ import annotations

from typing import Any

# Hard cap for a single slide line at the rendered template size. Mirrors
# HARD_LINE_CAP in pipelines/manual/ship_manual_post.py so diagnostics can
# be built before the pipeline-level assert runs. Phase 2 will replace this
# with a per-slide-kind cap from src/render/line_fit_probe.py.
HARD_LINE_CAP = 24


def build_shape_diagnostics(
    *,
    requested_content_slides: int,
    returned_content_slides: int,
    slides: list[dict[str, Any]],
    dropped_facts: list[str] | None = None,
) -> dict[str, Any]:
    """Return a structured payload describing a carousel shape mismatch.

    Both `requested_content_slides` and `returned_content_slides` count
    CONTENT slides only (cover excluded). See "Slide-count contract"
    at the top of the plan.

    The payload is intended to be both logged and embedded in
    CarouselShapeError so the autonomous agent's tool result surfaces it.
    """
    overlong: list[dict[str, Any]] = []
    bad_line_count: list[dict[str, Any]] = []
    for i, slide in enumerate(slides, 1):
        lines = slide.get("lines") or []
        if not isinstance(lines, list) or len(lines) != 3:
            bad_line_count.append({
                "slide": i,
                "line_count": len(lines) if isinstance(lines, list) else None,
            })
        for j, raw_line in enumerate(lines, 1):
            text = (raw_line or "").strip()
            if len(text) > HARD_LINE_CAP:
                overlong.append({
                    "slide": i,
                    "line": j,
                    "chars": len(text),
                    "text": text,
                })
    return {
        "requested_content_slides": requested_content_slides,
        "returned_content_slides": returned_content_slides,
        "overlong_lines": overlong,
        "bad_line_count": bad_line_count,
        "dropped_facts": list(dropped_facts or []),
    }


class CarouselShapeError(RuntimeError):
    """Hard-fails the pipeline when the writer's output cannot ship.

    Carries a structured diagnostics payload so the autonomous agent
    can surface it in its tool result and the operator can see exactly
    what was wrong without grepping logs.
    """

    def __init__(self, message: str, diagnostics: dict[str, Any]):
        self.diagnostics = diagnostics
        # str() includes a one-line summary so subprocess logs are readable.
        summary = (
            f"{message} "
            f"(requested_content_slides={diagnostics.get('requested_content_slides')}, "
            f"returned_content_slides={diagnostics.get('returned_content_slides')}, "
            f"overlong={len(diagnostics.get('overlong_lines') or [])}, "
            f"bad_line_count={len(diagnostics.get('bad_line_count') or [])})"
        )
        super().__init__(summary)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 -m pytest tests/test_carousel_shape.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/content/carousel_diagnostics.py tests/test_carousel_shape.py
git commit -m "$(cat <<'EOF'
feat(carousel): add CarouselShapeError + structured diagnostics

Phase 0 step 1 of the content quality recovery: a structured
diagnostics payload that the pipeline can attach to a hard fail when
the writer's output cannot ship. Replaces the silent slides[:8] and
lines[:3] slicing in ship_manual_post.py in the next step.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 0.2: Replace silent slicing in `ship_manual_post.py`

**Files:**
- Modify: `pipelines/manual/ship_manual_post.py:490-527`

- [ ] **Step 1: Add a failing integration test for the slide-count guard**

Append to `tests/test_carousel_shape.py`:

```python
import pytest
from pipelines.manual.ship_manual_post import _enforce_carousel_shape
from src.content.carousel_diagnostics import CarouselShapeError


def test_enforce_carousel_shape_rejects_too_many_slides():
    # 9 content slides returned when 5 were requested.
    data = {
        "slides": [{"lines": ["a", "b", "c"]} for _ in range(9)],
    }
    with pytest.raises(CarouselShapeError) as exc:
        _enforce_carousel_shape(data, requested_content_slides=5)
    assert exc.value.diagnostics["returned_content_slides"] == 9
    assert exc.value.diagnostics["requested_content_slides"] == 5


def test_enforce_carousel_shape_rejects_wrong_line_count():
    # Exactly 5 content slides requested, exactly 5 returned, but one has
    # only 2 lines instead of 3.
    data = {
        "slides": [
            {"lines": ["a", "b"]},  # only 2 lines
            {"lines": ["a", "b", "c"]},
            {"lines": ["a", "b", "c"]},
            {"lines": ["a", "b", "c"]},
            {"lines": ["a", "b", "c"]},
        ],
    }
    with pytest.raises(CarouselShapeError):
        _enforce_carousel_shape(data, requested_content_slides=5)


def test_enforce_carousel_shape_passes_clean_data():
    data = {
        "slides": [{"lines": ["one", "two", "three"]} for _ in range(5)],
    }
    # Must not raise.
    _enforce_carousel_shape(data, requested_content_slides=5)
```

- [ ] **Step 2: Run to verify it fails**

```bash
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 -m pytest tests/test_carousel_shape.py -v
```
Expected: 3 new tests fail with `AttributeError: module 'pipelines.manual.ship_manual_post' has no attribute '_enforce_carousel_shape'`.

- [ ] **Step 3: Implement `_enforce_carousel_shape` and remove silent slicing**

In `pipelines/manual/ship_manual_post.py`, replace lines 490-517 (the slice-and-warn block + the wrong-line-count slice) with the call below.

Add this near the other top-of-file imports (after the `from src.research.image_sourcer ...` line):

```python
from src.content.carousel_diagnostics import (
    CarouselShapeError,
    build_shape_diagnostics,
)
```

Add this helper above `generate_content`:

```python
def _enforce_carousel_shape(data: dict, *, requested_content_slides: int) -> None:
    """Hard-fail if the writer returned the wrong shape.

    Replaces the previous silent `slides[:8]` and `lines[:3]` slicing.
    The autonomous agent surfaces the diagnostics payload in its tool
    result so the operator can see what was lost.

    `requested_content_slides` is content-slides only (cover excluded).
    See "Slide-count contract" at the top of the plan. `data["slides"]`
    is also content-only.
    """
    slides = data.get("slides") or []
    diag = build_shape_diagnostics(
        requested_content_slides=requested_content_slides,
        returned_content_slides=len(slides),
        slides=slides,
        dropped_facts=data.get("dropped_facts") or [],
    )
    if len(slides) != requested_content_slides:
        raise CarouselShapeError(
            "writer returned wrong content-slide count", diag,
        )
    if diag["bad_line_count"]:
        raise CarouselShapeError(
            "one or more slides have wrong line count (must be exactly 3)", diag,
        )
```

Now in `generate_content` (around line 490), replace this existing block:

```python
    slides = data.get("slides", [])
    if len(slides) < 1:
        raise RuntimeError("No slides returned")
    if len(slides) > 8:
        dropped_n = len(slides) - 8
        dropped_preview = [
            (s.get("lines", [None])[0] if isinstance(s.get("lines"), list) else None)
            for s in slides[8:]
        ]
        _log(f"     [WARN] Sonnet returned {len(slides)} slides; pipeline cap is 8. "
             f"Dropping last {dropped_n}. First-line preview of dropped slides: {dropped_preview!r}")
        slides = slides[:8]
        data["slides"] = slides
```

with this:

```python
    slides = data.get("slides", [])
    if len(slides) < 1:
        raise CarouselShapeError(
            "writer returned no slides",
            build_shape_diagnostics(
                requested_content_slides=n_slides,
                returned_content_slides=0,
                slides=[],
            ),
        )
```

And replace this existing block:

```python
    for i, s in enumerate(slides, 1):
        lines = s.get("lines")
        if not isinstance(lines, list) or len(lines) < 2:
            raise RuntimeError(f"Slide {i} has too few lines: {lines}")
        if len(lines) > 3:
            s["lines"] = lines[:3]
```

with:

```python
    # n_slides is the content-only count (see Slide-count contract).
    _enforce_carousel_shape(data, requested_content_slides=n_slides)
    slides = data["slides"]
```

- [ ] **Step 4: Run all carousel-related tests**

```bash
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 -m pytest tests/test_carousel_shape.py tests/test_image_sourcer.py -v
```
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add pipelines/manual/ship_manual_post.py tests/test_carousel_shape.py
git commit -m "$(cat <<'EOF'
feat(carousel): replace silent slide/line slicing with CarouselShapeError

ship_manual_post.py was silently dropping extra slides and extra
lines after warn-only logging, hiding upstream writer regressions.
Wrong shape now hard-fails with structured diagnostics.

Phase 0 step 2 of the content quality recovery.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 0.3: Per-run quality ledger

**Files:**
- Create: `data/ledgers/carousel_quality.jsonl` (empty placeholder, gitignored only when in `output/`; this one is tracked because it is operator audit data)
- Modify: `pipelines/manual/ship_manual_post.py` (write a ledger entry at the end of every run, dry-run included)

- [ ] **Step 1: Add a failing test for ledger writes**

Append to `tests/test_carousel_shape.py`:

```python
import json
from pathlib import Path
from pipelines.manual.ship_manual_post import _write_quality_ledger_entry


def test_quality_ledger_entry_records_run(tmp_path):
    ledger = tmp_path / "carousel_quality.jsonl"
    _write_quality_ledger_entry(
        ledger_path=ledger,
        post_id="ask-jeeves-tribute",
        format_type="news",
        cover_title="ask jeeves quietly logs off",
        slide_count=6,
        line_warnings=["slide 4 line 3: ends with weak word 'and'"],
        dropped_facts=[],
        image_coverage={"image": 5, "typography": 1, "cover_failed": False},
        result="published",
    )
    rows = ledger.read_text().strip().splitlines()
    assert len(rows) == 1
    payload = json.loads(rows[0])
    assert payload["post_id"] == "ask-jeeves-tribute"
    assert payload["format_type"] == "news"
    assert payload["slide_count"] == 6
    assert payload["image_coverage"]["image"] == 5
    assert payload["result"] == "published"
    assert "ts" in payload
```

- [ ] **Step 2: Run, verify failure**

```bash
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 -m pytest tests/test_carousel_shape.py::test_quality_ledger_entry_records_run -v
```
Expected: FAIL.

- [ ] **Step 3: Implement `_write_quality_ledger_entry` and call it**

Add to top of `pipelines/manual/ship_manual_post.py`:

```python
from datetime import datetime, timezone
```

Add this helper above `main()`:

```python
def _write_quality_ledger_entry(
    *,
    ledger_path: Path,
    post_id: str,
    format_type: str,
    cover_title: str,
    slide_count: int,
    line_warnings: list[str],
    dropped_facts: list[str],
    image_coverage: dict,
    result: str,
    editorial_cost_usd: float = 0.0,
    fitter_cost_usd: float = 0.0,
    fitter_attempts: int = 0,
    probe_attempts: int = 0,
    total_runtime_ms: int = 0,
) -> None:
    """Append one structured row per run to data/ledgers/carousel_quality.jsonl.

    `result` is one of: "published", "dry_run", "shape_failed",
    "cover_failed", "publish_failed", "fitter_failed", "skipped".

    Cost/latency fields default to 0 in Phase 0 (writer is single-stage,
    no fitter, no probe) and are populated in Phase 1+2.
    """
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "post_id": post_id,
        "format_type": format_type,
        "cover_title": cover_title,
        "slide_count": slide_count,
        "line_warnings": list(line_warnings),
        "dropped_facts": list(dropped_facts),
        "image_coverage": dict(image_coverage),
        "result": result,
        "editorial_cost_usd": round(editorial_cost_usd, 5),
        "fitter_cost_usd": round(fitter_cost_usd, 5),
        "fitter_attempts": fitter_attempts,
        "probe_attempts": probe_attempts,
        "total_runtime_ms": total_runtime_ms,
    }
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
```

In `main()` after the `images = sourcer.source_images(...)` call, capture coverage:

```python
    image_coverage = {
        "image": sum(1 for u in images if u),
        "typography": sum(1 for u in images if not u),
        "cover_failed": not bool(images and images[0]),
    }
```

After the `_log(f"\n     Slides saved to: {save_dir.resolve()}")` line in the dry-run branch, write the ledger entry with `result="dry_run"`. After successful `publish_carousel` (where it logs `"Posted! Media ID: ..."`) write with `result="published"`. After publish failure, write with `result="publish_failed"`.

For the shape-fail and cover-fail paths, wrap them with try/except + ledger write before exiting.

Concretely, replace the early COVER_IMAGE_FAILED return:

```python
    if not images or not images[0]:
        _log("\nERROR: COVER_IMAGE_FAILED - no usable image found for the cover slide.")
        _log("       Run failed. Check image sourcer DEBUG logs for pool sizes and rejection reasons.")
        return 1
```

with:

```python
    if not images or not images[0]:
        _log("\nERROR: COVER_IMAGE_FAILED - no usable image found for the cover slide.")
        _log("       Run failed. Check image sourcer DEBUG logs for pool sizes and rejection reasons.")
        _write_quality_ledger_entry(
            ledger_path = repo_root / "data" / "ledgers" / "carousel_quality.jsonl",
            post_id     = post_id,
            format_type = args.type,
            cover_title = cover_title,
            slide_count = total_slides,
            line_warnings = data.get("_line_warnings", []),
            dropped_facts = data.get("dropped_facts") or [],
            image_coverage = {"image": 0, "typography": total_slides, "cover_failed": True},
            result = "cover_failed",
        )
        return 1
```

For the shape-failed branch, add a top-level try/except in `main()` around the `generate_content` call:

```python
    try:
        data, usage = generate_content(args.brief, n_slides, api_key, format_type=args.type)
    except CarouselShapeError as shape_err:
        _log(f"\nERROR: CONTENT_SHAPE_MISMATCH - {shape_err}")
        _log(f"       Diagnostics: {json.dumps(shape_err.diagnostics, ensure_ascii=False)}")
        _write_quality_ledger_entry(
            ledger_path = repo_root / "data" / "ledgers" / "carousel_quality.jsonl",
            post_id     = "shape-failed",
            format_type = args.type,
            cover_title = "(shape failed)",
            slide_count = 0,
            line_warnings = [],
            dropped_facts = shape_err.diagnostics.get("dropped_facts") or [],
            image_coverage = {"image": 0, "typography": 0, "cover_failed": False},
            result = "shape_failed",
        )
        return 1
```

`warnings` from `_validate_lines` was previously local to `generate_content`. Promote it: have `generate_content` return it as a third tuple element (or attach to `data["_line_warnings"] = warnings`). Use the second option to avoid signature churn:

In `generate_content`, replace:

```python
    warnings = _validate_lines(slides)
    for w in warnings:
        _log(f"     [line warn] {w}")
```

with:

```python
    warnings = _validate_lines(slides)
    for w in warnings:
        _log(f"     [line warn] {w}")
    data["_line_warnings"] = warnings
```

Then in `main()` use `data.get("_line_warnings", [])` when calling `_write_quality_ledger_entry`.

- [ ] **Step 4: Run tests + a manual dry-run**

```bash
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 -m pytest tests/test_carousel_shape.py -v
```
Expected: all green.

```bash
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 pipelines/manual/ship_manual_post.py \
  --brief "Tribute to Ask Jeeves shutting down for good" \
  --label "INTERNET HISTORY" \
  --type fact --dry-run
```
Expected: a row appears in `data/ledgers/carousel_quality.jsonl` with `result="dry_run"`.

- [ ] **Step 5: Commit**

```bash
git add pipelines/manual/ship_manual_post.py tests/test_carousel_shape.py
git commit -m "$(cat <<'EOF'
feat(carousel): write per-run quality ledger entry

data/ledgers/carousel_quality.jsonl now records one structured row
per run (dry-run included) capturing slide count, line warnings,
dropped facts, image coverage, and outcome. Replaces ad-hoc grep of
stdout for diagnostics.

Phase 0 step 3 of the content quality recovery.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 0.4: Surface diagnostics in autonomous agent tool result

**Files:**
- Modify: `scripts/autonomous_agent.py:152-187` (`_run_pipeline` already streams; nothing changes there).
- Modify: `scripts/autonomous_agent.py:190-201` (`run_reel`) to tag reel failure modes.
- Modify: `scripts/autonomous_agent.py:204-214` (`run_carousel`) to tag carousel failure modes.

Both tools must return a tool result whose first line is `FAILURE_KIND: <kind>` so the Phase 0 acceptance check applies uniformly across all five modes.

- [ ] **Step 1: Add a small shared tagger helper**

Above `run_reel` and `run_carousel`, add:

```python
def _tag_failure_kind(raw: str, kind_map: list[tuple[str, str]]) -> str:
    """Prefix a `FAILURE_KIND: <kind>` line to the subprocess output.

    `kind_map` is a list of (sentinel_substring, kind_name) pairs,
    checked in order. The first matching sentinel wins. If none match
    and `exit_code=0` is in the output, the result is tagged as `none`.
    Otherwise the kind is `unknown`.

    The tag lets the autonomous agent surface the failure mode in its
    own log line without parsing 7k of streamed subprocess tail.
    """
    for sentinel, kind in kind_map:
        if sentinel in raw:
            return f"FAILURE_KIND: {kind}\n\n{raw}"
    if "exit_code=0" in raw:
        return f"FAILURE_KIND: none\n\n{raw}"
    return f"FAILURE_KIND: unknown\n\n{raw}"
```

- [ ] **Step 2: Tag carousel runs**

Replace the existing `run_carousel` with:

```python
def run_carousel(args: dict, dry_run: bool, format_type: str = "fact") -> str:
    cmd = [
        "python3", "-u", "pipelines/manual/ship_manual_post.py",
        "--brief",  args["brief"],
        "--label",  args["label"],
        "--slides", str(args.get("slides", 6)),
        "--type",   format_type,
    ]
    if dry_run:
        cmd.append("--dry-run")
    raw = _run_pipeline(cmd)
    return _tag_failure_kind(raw, [
        ("CONTENT_SHAPE_MISMATCH", "content_shape_mismatch"),
        ("COVER_IMAGE_FAILED",     "cover_image_failed"),
        ("PUBLISH FAILED",         "publish_failed"),
    ])
```

- [ ] **Step 3: Tag reel runs**

Replace the existing `run_reel` with:

```python
def run_reel(args: dict, dry_run: bool) -> str:
    cmd = [
        "python3", "-u", "pipelines/reel/make_reel.py",
        "--script",        args["script"],
        "--title",         args["title"],
        "--topic",         args["topic"],
        "--tone-override", args["tone_override"],
        "--hint",          args["hint"],
    ]
    if dry_run:
        cmd.append("--dry-run")
    raw = _run_pipeline(cmd)
    # Sentinels mirror the literal strings make_reel.py prints / logs.
    # Order matters: lock_contention must be checked before exit_code=0
    # because a fast lock-contention exit is also exit_code=10, not 0.
    return _tag_failure_kind(raw, [
        ("ERROR: TTS returned no word timing", "tts_failed"),
        ("ERROR: could not find any footage",  "no_footage"),
        ("reel FAILED ffmpeg",                 "ffmpeg_failed"),
        ("reel FAILED video upload",           "video_upload_failed"),
        ("reel FAILED publish",                "publish_failed"),
        ("exit_code=10",                       "lock_contention"),
    ])
```

The `lock_contention` sentinel is `exit_code=10` because `make_reel.py` exits 10 when a stale `.make_reel.lock` is held (CLAUDE.md "Run commands" section). Listing it explicitly in the kind_map keeps it from falling into the `unknown` bucket on the helper's catch-all branch.

- [ ] **Step 4: Smoke-test all five modes**

```bash
for mode in fact news list reel_morning reel_evening; do
  echo "=== $mode ==="
  DRY_RUN=true /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
    scripts/autonomous_agent.py --post-mode "$mode" 2>&1 | grep -E "^FAILURE_KIND:" | head -1
done
```
Expected: five lines of output, each beginning with `FAILURE_KIND:`. Clean dry-runs report `FAILURE_KIND: none`. The reel modes will tag `FAILURE_KIND: none` if the dry-run renders a final.mp4 without uploading; if footage cannot be sourced (likely on a cold environment with no API keys), the tag will be `FAILURE_KIND: no_footage`. Both are acceptable for Phase 0 acceptance; the point is that every mode emits a tag.

- [ ] **Step 5: Commit**

```bash
git add scripts/autonomous_agent.py
git commit -m "$(cat <<'EOF'
feat(autonomous): tag every tool result with FAILURE_KIND

run_reel and run_carousel now share a _tag_failure_kind helper that
prefixes FAILURE_KIND: <kind> to the subprocess output.
Carousel kinds: content_shape_mismatch, cover_image_failed,
publish_failed. Reel kinds: tts_failed, no_footage, ffmpeg_failed,
video_upload_failed, publish_failed, lock_contention. Clean exits
become "none"; unrecognised non-zero exits become "unknown".

Phase 0 step 4 of the content quality recovery.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 0.5: CI test workflow

**Files:**
- Create: `.github/workflows/test.yml`

The repo currently has only two workflows: `autonomous-reel.yml` (cron-driven poster) and `pages.yml` (docs). Neither runs pytest. Without a CI gate, the test files added in Phase 0/1/2/3 will rot the moment a PR lands without running them. Phase 0 fixes this with a minimal pytest workflow that runs on PRs and non-main pushes only. It does NOT post to social, does NOT deploy, does NOT touch any ledger - it is a test-only gate.

CLAUDE.md hard rules apply: no em dashes in the YAML, no multiline Python heredocs inside `run: |` blocks.

- [ ] **Step 1: Write the workflow**

```yaml
# .github/workflows/test.yml
name: tests

on:
  pull_request:
    branches: [main]
  push:
    branches-ignore: [main]

permissions:
  contents: read

concurrency:
  group: tests-${{ github.ref }}
  cancel-in-progress: true

jobs:
  pytest:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pytest

      - name: Run pytest
        run: pytest tests/ -v
```

Notes:
- `branches-ignore: [main]` on push means commits straight to main do NOT re-run tests; PR-merge events still trigger via the `pull_request` event before merge. This avoids duplicate runs from the autonomous workflow's own state-commit pushes.
- `cancel-in-progress: true` on the concurrency group means a force-pushed PR cancels the previous run. Safe here because tests have no external side effects.
- No `secrets:` block: tests run with no API keys, so they must mock or skip anything that needs network. Existing `tests/test_image_sourcer.py` already follows this pattern.

- [ ] **Step 2: Sanity-check the YAML parses**

```bash
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 -c "import yaml; yaml.safe_load(open('.github/workflows/test.yml'))"
```
Expected: no output (clean parse). If it errors, the YAML is broken; fix before continuing.

- [ ] **Step 3: Verify pytest still runs locally with no surprises**

```bash
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 -m pytest tests/ -v
```
Expected: all green (the tests added in Tasks 0.1-0.3 plus the pre-existing `tests/test_image_sourcer.py` and `tests/test_reel_hook.py`).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/test.yml
git commit -m "$(cat <<'EOF'
ci: add pytest workflow for PRs and non-main pushes

Runs pytest tests/ on every PR targeting main and on every push to a
non-main branch. Uses Python 3.11 and the existing requirements.txt.
No secrets, no posting, no deploys. The autonomous-reel workflow
remains the only intentional poster.

Without this gate, the test files added across Phase 0-3 of the
content quality recovery would rot on the first PR that landed
without local pytest.

Phase 0 step 5 of the content quality recovery.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Phase 0 acceptance

Run all five autonomous modes in dry-run. The three carousel modes (`fact`, `news`, `list`) must each append one structured row to `data/ledgers/carousel_quality.jsonl` with `result="dry_run"`. The two reel modes (`reel_morning`, `reel_evening`) do NOT write to the carousel ledger by design - they exercise a different pipeline (`make_reel.py`). All five modes must produce a tool result that begins with a `FAILURE_KIND:` tag.

The new `.github/workflows/test.yml` must parse cleanly (`python -c "import yaml; yaml.safe_load(...)"`) and pytest must be green locally (`pytest tests/ -v`).

```bash
for mode in fact news list reel_morning reel_evening; do
  DRY_RUN=true /Library/Frameworks/Python.framework/Versions/Current/bin/python3 scripts/autonomous_agent.py --post-mode "$mode"
done
# Expect exactly 3 new rows from the carousel modes:
tail -n 5 data/ledgers/carousel_quality.jsonl
```

Acceptance: 3 carousel-ledger rows added, all with `result="dry_run"`. 5 tool results visible in stdout, each beginning with `FAILURE_KIND:`.

### **STOP - request approval before Phase 1.**

This is a hard gate. Phase 1 introduces architectural change (a second model call) and is reversible only with effort. Do not start Phase 1 until Toby has signed off on the items below.

> Toby, before I move to Phase 1 (writer/fitter split):
> - Confirm Phase 0 dry-runs look right (5 modes, 3 ledger rows, no silent slicing).
> - Confirm baseline cost/latency numbers from 5 single-stage dry-runs are captured (these become the comparison set for Phase 1).
> - Confirm you want me to proceed with the full two-stage writer architecture rather than the lighter "tighten existing prompt" alternative.

---

## Phase 1 - Split editorial writing from layout fitting

**Goal:** A Sonnet call writes meaning-complete slide prose without char-cap pressure. A separate Haiku call fits that prose to 3 lines that respect the visual cap, without changing facts. A diff check confirms factual identity is preserved.

### Task 1.1: New writer module

**Files:**
- Create: `src/content/carousel_writer.py`
- Test: `tests/test_carousel_writer_fitter.py`

- [ ] **Step 1: Write the failing test for editorial writer signature**

```python
# tests/test_carousel_writer_fitter.py
import pytest
from src.content.carousel_writer import (
    EditorialSlide,
    SlideFit,
    write_editorial_slides,
    fit_slide_lines,
    FactPreservationError,
    LineFitError,
)


def test_editorial_slide_dataclass_round_trip():
    slide = EditorialSlide(
        slide_index=2,
        prose="Phineas Gage survived an iron rod through his skull in 1848.",
        beat_id="2",
    )
    assert slide.slide_index == 2
    assert "1848" in slide.prose
    assert slide.beat_id == "2"


def test_slide_fit_dataclass():
    fit = SlideFit(
        slide_index=2,
        lines=["phineas gage", "took an iron rod", "to the head, 1848"],
    )
    assert len(fit.lines) == 3
```

- [ ] **Step 2: Run, verify failure**

```bash
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 -m pytest tests/test_carousel_writer_fitter.py -v
```
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement dataclasses + writer skeleton**

```python
# src/content/carousel_writer.py
"""Two-stage carousel content writer.

Stage A (write_editorial_slides): a Sonnet 4.6 call that produces
canonical, meaning-complete slide prose with NO line-break or char-cap
pressure. This is where editorial decisions happen.

Stage B (fit_slide_lines): a Haiku 4.5 call that converts each slide's
prose into exactly 3 lines that fit the visual cap. The fitter is
explicitly told NOT to change facts, names, dates, numbers, or
entities. A FactPreservationError is raised if entity identity drifts.

Phase 1 of the content quality recovery. Replaces the single-stage
generate_content() in pipelines/manual/ship_manual_post.py which
mixed editorial decisions with line geometry.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from anthropic import Anthropic


# ------------------------------------------------------------------ #
# Public types
# ------------------------------------------------------------------ #


@dataclass
class EditorialSlide:
    """One slide's prose, before line fitting."""
    slide_index: int          # 1-based, cover = 1
    prose: str                # 1-2 sentences, meaning-complete
    beat_id: str = ""         # writer-supplied beat identifier (optional)


@dataclass
class SlideFit:
    """One slide's fitted lines."""
    slide_index: int
    lines: list[str]          # exactly 3 strings


@dataclass
class WriterResult:
    """Output of stage A. The pipeline uses this then calls stage B."""
    cover_title: str
    label: str
    caption_body: str
    visual_subject: str
    subject_type: str
    fallback_query: str
    source_aliases: list[str]
    context_words: list[str]
    negative_terms: list[str]
    preferred_image_types: list[str]
    avoid_image_types: list[str]
    image_queries: list[str]
    visual_fallback_queries: list[str]
    cover_slot_aliases: list[str]
    slot_aliases: list[list[str]]    # per-slide aliases, len == slides
    slides: list[EditorialSlide]
    dropped_facts: list[str] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)


class FactPreservationError(RuntimeError):
    """Raised when the fitter changes a fact, name, date or number."""


class LineFitError(RuntimeError):
    """Raised when the fitter cannot produce 3 lines under the cap."""


# ------------------------------------------------------------------ #
# Stage A: editorial writer (Sonnet 4.6)
# ------------------------------------------------------------------ #

EDITORIAL_PROMPT_TEMPLATE = """\
{brand_voice_editorial}

---

{type_guidance}

You are writing a factjot carousel post. The brief is:

"{brief}"

Stage A: editorial writing only. Write meaning-complete slide prose.
You are NOT line-breaking. You are NOT trying to fit characters per
line. The next stage handles layout.

Rules:
- Cover title: 5-9 words, no full stop, must contain a verb or sting.
- Each content slide: 1-2 sentences of prose, complete, factual.
- ONE SLIDE = ONE IDEA. Do not weld two beats with "and" or semicolons.
- Preserve specific names, dates, numbers, places.
- If a beat is too dense to fit one slide, surface the dropped sub-fact
  in `dropped_facts` rather than welding fragments.
- Image queries must be photographable proxies (people, devices,
  scenes, eras), not abstract concepts.

Return JSON only:
{{
  "cover_title": "5-9 word title",
  "label": "CATEGORY",
  "caption_body": "2-3 sentences. Human, warm. No hashtags.",
  "visual_subject": "canonical name and type",
  "subject_type": "one category string",
  "fallback_query": "1-4 words",
  "source_aliases": ["..."],
  "context_words": ["..."],
  "negative_terms": ["..."],
  "preferred_image_types": ["..."],
  "avoid_image_types": ["..."],
  "image_queries": ["cover", "slide 1", ...],
  "visual_fallback_queries": ["cover fallback", "slide 1 fallback", ...],
  "cover_slot_aliases": ["..."],
  "dropped_facts": ["..."],
  "slides": [
    {{"slide_index": 2, "prose": "1-2 sentence factual statement", "beat_id": "2"}}
  ]
}}

Slide indexing: cover is slide 1; the prose slides start at slide 2.
Return exactly {n_content_slides} prose slides. Do not include the
cover in `slides` (its text is in `cover_title`).
"""


def write_editorial_slides(
    *,
    brief: str,
    n_content_slides: int,
    format_type: str,
    api_key: str,
    brand_voice_editorial: str,
    type_guidance: str,
) -> tuple[WriterResult, dict]:
    """Call Sonnet 4.6 with the editorial prompt. Returns parsed result + usage."""
    client = Anthropic(api_key=api_key)
    prompt = EDITORIAL_PROMPT_TEMPLATE.format(
        brand_voice_editorial=brand_voice_editorial,
        type_guidance=type_guidance,
        brief=brief,
        n_content_slides=n_content_slides,
    )
    res = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        temperature=0.5,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = res.content[0].text.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", raw, re.IGNORECASE)
        if fenced:
            data = json.loads(fenced.group(1))
        else:
            s, e = raw.find("{"), raw.rfind("}")
            data = json.loads(raw[s : e + 1])

    slides_raw = data.get("slides") or []
    slides = [
        EditorialSlide(
            slide_index=int(s.get("slide_index", i + 2)),
            prose=str(s.get("prose", "")).strip(),
            beat_id=str(s.get("beat_id", "")),
        )
        for i, s in enumerate(slides_raw)
    ]

    result = WriterResult(
        cover_title=data.get("cover_title", ""),
        label=str(data.get("label", "FACTJOT")).upper(),
        caption_body=data.get("caption_body", ""),
        visual_subject=data.get("visual_subject", ""),
        subject_type=data.get("subject_type", ""),
        fallback_query=data.get("fallback_query", ""),
        source_aliases=list(data.get("source_aliases") or []),
        context_words=list(data.get("context_words") or []),
        negative_terms=list(data.get("negative_terms") or []),
        preferred_image_types=list(data.get("preferred_image_types") or []),
        avoid_image_types=list(data.get("avoid_image_types") or []),
        image_queries=list(data.get("image_queries") or []),
        visual_fallback_queries=list(data.get("visual_fallback_queries") or []),
        cover_slot_aliases=list(data.get("cover_slot_aliases") or []),
        slot_aliases=[list(s.get("slot_aliases") or []) for s in slides_raw],
        slides=slides,
        dropped_facts=list(data.get("dropped_facts") or []),
        raw_payload=data,
    )

    pricing = {"input": 3.00, "output": 15.00}
    cost = (
        res.usage.input_tokens / 1_000_000 * pricing["input"]
        + res.usage.output_tokens / 1_000_000 * pricing["output"]
    )
    usage = {
        "model": "claude-sonnet-4-6",
        "stage": "editorial",
        "input_tokens": res.usage.input_tokens,
        "output_tokens": res.usage.output_tokens,
        "cost_usd": round(cost, 5),
    }
    return result, usage


# ------------------------------------------------------------------ #
# Stage B: fitter (Haiku 4.5)
# ------------------------------------------------------------------ #

FITTER_PROMPT_TEMPLATE = """\
You are the layout fitter. The editorial writer above has produced
meaning-complete slide prose. Your only job is to break that prose
into exactly 3 short lines per slide that fit the renderer's hard
character cap.

HARD RULES:
1. Output exactly 3 lines per slide. No more, no fewer.
2. No line may exceed {hard_cap} characters (counting [r]...[/r] markup).
3. You MUST NOT change any factual content. Names, dates, numbers,
   place names, organisation names, and entities must appear with the
   same spelling and the same numeric value as in the input prose.
4. You MAY rephrase for compactness ONLY where meaning is preserved.
   You MAY drop softening words (just, very, really, simply).
5. Lowercase only. The renderer text-transforms anyway, but write it
   lowercase to make the cap accurate.
6. No em dashes. Use commas, full stops, parentheses.
7. Wrap 1-2 key words or short phrases per line in [r]...[/r] for the
   accent colour. Pick the most striking word, name, or number.
8. Anti-orphan: a line must have at least 3 words OR be a single
   capitalised entity standing alone (e.g. "carl norden,").
9. Last line must be at least 8 characters.
10. No line may end on a weak connector: a, the, and, or, of, in, to,
    with, an, at, by, for.

Input slides (one per line, JSON):
{slides_json}

Return JSON only:
{{
  "slides": [
    {{"slide_index": 1, "lines": ["line one", "line two", "line three"]}}
  ]
}}

Return exactly {n_slides} entries, one per input slide, in the same order.
"""


def fit_slide_lines(
    *,
    editorial_slides: list[EditorialSlide],
    hard_cap: int,
    api_key: str,
) -> tuple[list[SlideFit], dict]:
    """Call Haiku 4.5 to fit each slide's prose to 3 lines under the cap.

    Raises FactPreservationError if entity identity drifts vs input.
    Raises LineFitError if any line still exceeds the cap.
    """
    client = Anthropic(api_key=api_key)
    slides_json = json.dumps(
        [
            {"slide_index": s.slide_index, "prose": s.prose}
            for s in editorial_slides
        ],
        ensure_ascii=False,
    )
    prompt = FITTER_PROMPT_TEMPLATE.format(
        hard_cap=hard_cap,
        slides_json=slides_json,
        n_slides=len(editorial_slides),
    )
    res = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        temperature=0.1,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = res.content[0].text.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", raw, re.IGNORECASE)
        if fenced:
            data = json.loads(fenced.group(1))
        else:
            s, e = raw.find("{"), raw.rfind("}")
            data = json.loads(raw[s : e + 1])

    fits_raw = data.get("slides") or []
    if len(fits_raw) != len(editorial_slides):
        raise LineFitError(
            f"fitter returned {len(fits_raw)} slides, expected {len(editorial_slides)}"
        )

    fits: list[SlideFit] = []
    for inp, out in zip(editorial_slides, fits_raw):
        lines = list(out.get("lines") or [])
        if len(lines) != 3:
            raise LineFitError(
                f"slide {inp.slide_index}: fitter returned {len(lines)} lines"
            )
        # Cap check (accounting for [r]...[/r] markup that the renderer
        # treats as zero-width style spans).
        for line in lines:
            stripped = re.sub(r"\[/?r\]", "", line).strip()
            if len(stripped) > hard_cap:
                raise LineFitError(
                    f"slide {inp.slide_index}: line {len(stripped)} > cap {hard_cap}: {stripped!r}"
                )
        # Fact preservation check: every digit-run and every Capitalised
        # word in the input must appear in the joined output (case-insensitive
        # for words; exact for digit-runs).
        joined_in = inp.prose
        joined_out = " ".join(lines)
        in_numbers = set(re.findall(r"\d+(?:[.,]\d+)*", joined_in))
        out_numbers = set(re.findall(r"\d+(?:[.,]\d+)*", joined_out))
        missing_numbers = in_numbers - out_numbers
        if missing_numbers:
            raise FactPreservationError(
                f"slide {inp.slide_index}: fitter dropped numbers {sorted(missing_numbers)}"
            )
        # Capitalised proper nouns: simple heuristic, splits on whitespace.
        in_propers = {
            w.rstrip(".,;:!?")
            for w in joined_in.split()
            if w[:1].isupper()
        }
        out_lower = joined_out.lower()
        missing_propers = {
            w for w in in_propers
            if w.lower() not in out_lower and len(w) > 2
        }
        if missing_propers:
            raise FactPreservationError(
                f"slide {inp.slide_index}: fitter dropped proper nouns "
                f"{sorted(missing_propers)}"
            )
        fits.append(SlideFit(slide_index=inp.slide_index, lines=lines))

    pricing = {"input": 1.00, "output": 5.00}  # Haiku 4.5 placeholder; verify before commit
    cost = (
        res.usage.input_tokens / 1_000_000 * pricing["input"]
        + res.usage.output_tokens / 1_000_000 * pricing["output"]
    )
    usage = {
        "model": "claude-haiku-4-5",
        "stage": "fitter",
        "input_tokens": res.usage.input_tokens,
        "output_tokens": res.usage.output_tokens,
        "cost_usd": round(cost, 5),
    }
    return fits, usage
```

- [ ] **Step 4: Run tests**

```bash
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 -m pytest tests/test_carousel_writer_fitter.py -v
```
Expected: 2 passed (the dataclass round-trip tests).

- [ ] **Step 5: Commit**

```bash
git add src/content/carousel_writer.py tests/test_carousel_writer_fitter.py
git commit -m "$(cat <<'EOF'
feat(carousel): add two-stage writer (editorial + fitter)

src/content/carousel_writer.py introduces:
- write_editorial_slides() (Sonnet 4.6, owns meaning, no char cap).
- fit_slide_lines() (Haiku 4.5, breaks prose to 3 lines under the cap).
- FactPreservationError raised if numbers / proper nouns drift.
- LineFitError raised if cap is still exceeded after fitting.

Phase 1 step 1 of the content quality recovery. Not yet wired into
the pipeline.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 1.2: Fact-preservation tests

**Files:**
- Modify: `tests/test_carousel_writer_fitter.py`

- [ ] **Step 1: Add unit tests that exercise the preservation logic in isolation**

Append to `tests/test_carousel_writer_fitter.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from src.content.carousel_writer import (
    EditorialSlide,
    fit_slide_lines,
    FactPreservationError,
    LineFitError,
)


def _mock_anthropic_response(payload: dict):
    """Helper: build a fake Anthropic SDK response with the given JSON payload."""
    res = MagicMock()
    res.content = [MagicMock()]
    res.content[0].text = '```json\n' + str(payload).replace("'", '"') + '\n```'
    res.usage.input_tokens = 100
    res.usage.output_tokens = 200
    return res


def test_fitter_rejects_dropped_numbers(monkeypatch):
    fake = MagicMock()
    fake.messages.create.return_value = _mock_anthropic_response({
        "slides": [
            {"slide_index": 2, "lines": ["phineas gage", "took a rod", "to the head"]}
        ]
    })
    monkeypatch.setattr("src.content.carousel_writer.Anthropic", lambda api_key: fake)
    with pytest.raises(FactPreservationError) as exc:
        fit_slide_lines(
            editorial_slides=[EditorialSlide(
                slide_index=2,
                prose="Phineas Gage survived an iron rod through his skull in 1848.",
            )],
            hard_cap=24,
            api_key="dummy",
        )
    assert "1848" in str(exc.value)


def test_fitter_rejects_dropped_proper_noun(monkeypatch):
    fake = MagicMock()
    fake.messages.create.return_value = _mock_anthropic_response({
        "slides": [
            {"slide_index": 2, "lines": ["a man survived", "an iron rod", "through his head"]}
        ]
    })
    monkeypatch.setattr("src.content.carousel_writer.Anthropic", lambda api_key: fake)
    with pytest.raises(FactPreservationError) as exc:
        fit_slide_lines(
            editorial_slides=[EditorialSlide(
                slide_index=2,
                prose="Phineas Gage survived an iron rod through his skull.",
            )],
            hard_cap=24,
            api_key="dummy",
        )
    assert "Gage" in str(exc.value) or "Phineas" in str(exc.value)


def test_fitter_rejects_overcap_line(monkeypatch):
    fake = MagicMock()
    fake.messages.create.return_value = _mock_anthropic_response({
        "slides": [
            {"slide_index": 2, "lines": [
                "phineas gage took an iron rod to his head",
                "in 1848",
                "and survived the injury.",
            ]}
        ]
    })
    monkeypatch.setattr("src.content.carousel_writer.Anthropic", lambda api_key: fake)
    with pytest.raises(LineFitError):
        fit_slide_lines(
            editorial_slides=[EditorialSlide(
                slide_index=2,
                prose="Phineas Gage survived an iron rod through his skull in 1848.",
            )],
            hard_cap=24,
            api_key="dummy",
        )


def test_fitter_accepts_clean_output(monkeypatch):
    fake = MagicMock()
    fake.messages.create.return_value = _mock_anthropic_response({
        "slides": [
            {"slide_index": 2, "lines": ["phineas gage,", "took a rod", "in 1848"]}
        ]
    })
    monkeypatch.setattr("src.content.carousel_writer.Anthropic", lambda api_key: fake)
    fits, _ = fit_slide_lines(
        editorial_slides=[EditorialSlide(
            slide_index=2,
            prose="Phineas Gage took a rod through his skull in 1848.",
        )],
        hard_cap=24,
        api_key="dummy",
    )
    assert len(fits) == 1
    assert fits[0].lines == ["phineas gage,", "took a rod", "in 1848"]
```

- [ ] **Step 2: Run, verify all four pass**

```bash
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 -m pytest tests/test_carousel_writer_fitter.py -v
```
Expected: all green.

- [ ] **Step 3: Commit**

```bash
git add tests/test_carousel_writer_fitter.py
git commit -m "$(cat <<'EOF'
test(carousel): exercise fact-preservation guards in fit_slide_lines

Covers number drop, proper-noun drop, overcap line, and clean accept.
The mocked Anthropic client lets us assert pipeline behaviour without
burning real API tokens.

Phase 1 step 2 of the content quality recovery.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 1.3: Wire the two-stage writer into the pipeline

**Files:**
- Modify: `pipelines/manual/ship_manual_post.py:450-538` (`generate_content`)

- [ ] **Step 1: Refactor `generate_content` to call both stages**

Add at top of `pipelines/manual/ship_manual_post.py`:

```python
from src.content.carousel_writer import (
    EditorialSlide,
    FactPreservationError,
    LineFitError,
    SlideFit,
    fit_slide_lines,
    write_editorial_slides,
)
```

Split the giant `BRAND_VOICE` constant into two:
- `BRAND_VOICE_EDITORIAL`: rules that survive into Stage A - voice, beat density, anti-em-dash, anti-orphan, weak endings.
- Remove the char-cap rules from BRAND_VOICE; those move into the fitter prompt (already inlined in `carousel_writer.FITTER_PROMPT_TEMPLATE`).

In practice, replace the existing `BRAND_VOICE` literal in `ship_manual_post.py` with:

```python
BRAND_VOICE_EDITORIAL = """\
Brand: factjot (@factjot)
Voice: curious, precise, dry. A smart friend explaining something remarkable.
Tone: confident, never sensational. Present tense where possible.
Reading level: general audience.

Editorial rules (Stage A - meaning only, layout handled separately):
- ONE SLIDE = ONE IDEA. ONE BEAT = ONE FACT.
- No semicolons inside a beat. No "and" welding two facts.
- No em dashes. Commas, full stops, or parentheses instead.
- British English. No hedging. No attribution phrases.
- Front-load the most interesting element on each slide.
- Preserve specific names, dates, numbers, places.
- If a beat is genuinely too dense for one slide, surface the dropped
  sub-fact in dropped_facts rather than welding fragments.
"""

# Backwards-compat: some legacy imports still reach for BRAND_VOICE.
BRAND_VOICE = BRAND_VOICE_EDITORIAL
```

Then replace the body of `generate_content` (the whole function) with:

```python
def generate_content(
    brief: str, n_slides: int, api_key: str, format_type: str = "fact",
) -> tuple[dict, list[dict]]:
    """Two-stage carousel writer.

    Stage A (Sonnet 4.6) writes editorial slide prose without char-cap
    pressure. Stage B (Haiku 4.5) fits each slide's prose to 3 lines
    under the renderer's hard cap. A FactPreservationError is raised
    if entity identity drifts.

    Returns the same `data` shape the rest of the pipeline expects
    (with `slides` populated as `[{slideNumber, lines, slot_aliases}]`)
    plus a list of usage records, one per stage.

    `n_slides` is content-only (cover added on top in main()).
    """
    type_guidance = _type_guidance(format_type)

    # Stage A: editorial writer.
    writer_result, usage_a = write_editorial_slides(
        brief                  = brief,
        n_content_slides       = n_slides,
        format_type            = format_type,
        api_key                = api_key,
        brand_voice_editorial  = BRAND_VOICE_EDITORIAL,
        type_guidance          = type_guidance,
    )

    # Stage B: fitter.
    fits, usage_b = fit_slide_lines(
        editorial_slides = writer_result.slides,
        hard_cap         = HARD_LINE_CAP,
        api_key          = api_key,
    )

    # Reshape into the dict form the rest of the pipeline already speaks.
    fitted_by_index = {f.slide_index: f for f in fits}
    slide_dicts: list[dict] = []
    for ed in writer_result.slides:
        f = fitted_by_index.get(ed.slide_index)
        if f is None:
            raise LineFitError(f"fitter dropped slide_index={ed.slide_index}")
        slide_dicts.append({
            "slideNumber":  ed.slide_index,
            "lines":        f.lines,
            "slot_aliases": writer_result.slot_aliases[ed.slide_index - 2]
                             if ed.slide_index - 2 < len(writer_result.slot_aliases) else [],
            "_editorial_prose": ed.prose,
        })

    data = {
        "cover_title":              writer_result.cover_title,
        "label":                    writer_result.label,
        "caption_body":             writer_result.caption_body,
        "visual_subject":           writer_result.visual_subject,
        "subject_type":             writer_result.subject_type,
        "fallback_query":           writer_result.fallback_query,
        "source_aliases":           writer_result.source_aliases,
        "context_words":            writer_result.context_words,
        "negative_terms":           writer_result.negative_terms,
        "preferred_image_types":    writer_result.preferred_image_types,
        "avoid_image_types":        writer_result.avoid_image_types,
        "image_queries":            writer_result.image_queries,
        "visual_fallback_queries":  writer_result.visual_fallback_queries,
        "cover_slot_aliases":       writer_result.cover_slot_aliases,
        "slides":                   slide_dicts,
        "dropped_facts":            writer_result.dropped_facts,
    }

    # n_slides is content-only (see Slide-count contract).
    _enforce_carousel_shape(data, requested_content_slides=n_slides)

    warnings = _validate_lines(slide_dicts)
    for w in warnings:
        _log(f"     [line warn] {w}")
    data["_line_warnings"] = warnings

    _assert_lines_within_render_cap(slide_dicts)

    if writer_result.dropped_facts:
        _log("     [INFO] Writer reported dropped_facts (beat too dense for one slide):")
        for df in writer_result.dropped_facts:
            _log(f"            - {df}")

    return data, [usage_a, usage_b]
```

The caller in `main()` currently does `data, usage = generate_content(...)` and accesses `usage['cost_usd']` etc. Update the caller to:

```python
    data, usage_records = generate_content(args.brief, n_slides, api_key, format_type=args.type)
    total_cost = sum(u["cost_usd"] for u in usage_records)
    in_tokens  = sum(u["input_tokens"]  for u in usage_records)
    out_tokens = sum(u["output_tokens"] for u in usage_records)
    _log(f"     {in_tokens:,} in / {out_tokens:,} out  ~${total_cost:.4f}  ({len(usage_records)} stages)")
```

Wrap the `generate_content` call in `main()` to also catch `FactPreservationError` and `LineFitError`, writing a `result="fitter_failed"` ledger row and returning 1.

- [ ] **Step 2: Smoke-test on a real brief, dry-run**

```bash
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 pipelines/manual/ship_manual_post.py \
  --brief "Phineas Gage survived a 13-pound iron rod through his skull in 1848 and lived another 12 years" \
  --label "HISTORY" --type fact --dry-run
```
Expected:
- Both Stage A and Stage B usage logged.
- No line over 24 chars.
- Visible numbers `1848`, `13`, `12` preserved on the rendered slides.
- A `result="dry_run"` row in `data/ledgers/carousel_quality.jsonl`.

- [ ] **Step 3: Commit**

```bash
git add pipelines/manual/ship_manual_post.py
git commit -m "$(cat <<'EOF'
feat(carousel): wire two-stage writer/fitter into manual pipeline

generate_content() now calls write_editorial_slides() (Sonnet 4.6,
meaning) then fit_slide_lines() (Haiku 4.5, layout). Fact preservation
is enforced before render. The legacy single-stage prompt is replaced
by BRAND_VOICE_EDITORIAL (no char-cap rules) and the fitter's own
prompt template.

Phase 1 step 3 of the content quality recovery.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Phase 1 acceptance

Run 5 dry-run briefs covering the SPEC_IMAGE_PIPELINE acceptance list (Concorde aircraft, Concord Massachusetts, Concord grape, niche science topic, historical person). For each, open the rendered PDFs and check:
- Every named entity from the brief survives onto a slide.
- Every numeric fact from the brief survives onto a slide.
- Every line ≤ 24 chars.
- No "and" welding, no semicolons inside a beat.
- No silent slide drops (compare slide count to brief beat count).

```bash
for brief in \
  "The history of Concorde, how it was built and why it ended" \
  "Concord Massachusetts in the 1700s" \
  "How the Concord grape became America's juice grape" \
  "Why CRISPR base-editing differs from regular CRISPR" \
  "Phineas Gage and the iron rod, 1848"
do
  /Library/Frameworks/Python.framework/Versions/Current/bin/python3 pipelines/manual/ship_manual_post.py \
    --brief "$brief" --type fact --dry-run
done

# Also exercise news + list types so format_type guidance is covered:
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 pipelines/manual/ship_manual_post.py \
  --brief "Why the UK weather forecast got 12 hours warmer this week" --label WEATHER --type news --dry-run
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 pipelines/manual/ship_manual_post.py \
  --brief "Five inventions nobody asked for: smell-o-vision, sgraffito jeans, gum-flavoured toothpaste, electric forks, smart napkins" \
  --label CULTURE --type list --slides 7 --dry-run
```

### **STOP - request approval before Phase 2.**

This is the second hard gate. Phase 2 adds Playwright probe latency (one browser launch per fitter attempt). Do not start Phase 2 until the items below are signed off.

> Toby, before I move to Phase 2 (render-aware fit probe):
> - Walk through the 7 rendered decks from Phase 1 acceptance (5 facts + 1 news + 1 list) and confirm fact preservation is solid.
> - Confirm cost/latency vs Phase 0 baseline: editorial+fitter cost ≤ $0.05/run, P95 wall-clock ≤ 45s. If either is breached, we tighten the editorial prompt or revert to single-stage before Phase 2.
> - Confirm fitter_attempts mean is ≤ 1.5 across the 7 decks. If it's higher, the editorial prompt is generating prose the fitter cannot fit cleanly; address that first.

---

## Phase 2 - Render-aware line-fit probe

**Goal:** Replace the char-based `HARD_LINE_CAP=24` with a per-slide-kind cap that reflects actual rendered width. Add an iterative fit loop: if the probe reports a soft-wrap, ask the fitter to retry up to N=2 times before hard failing.

### Scope constraint: news-pipeline dual-role import safety

`pipelines/news/ship_news_post.py` is dual-role per CLAUDE.md and SPEC_FACTJOT_SYSTEM section 10.1: it is both the news-pipeline entry point AND the renderer module that `pipelines/manual/ship_manual_post.py` imports (`render_cover_slide`, `render_news_slide`, `render_story_frame`). A full split of those concerns is a separate refactor outside the scope of this plan.

For Phase 2, that means:

- Any new parameter added to `render_news_slide`, `render_cover_slide`, or `render_story_frame` MUST have a default that preserves current behaviour for existing callers.
- The standalone news-pipeline path (`pipelines/news/ship_news_post.py main()`) must continue to render correctly after every Phase 2 commit.
- After Task 2.3, run a smoke check of the news standalone path before marking the phase done:

  ```bash
  /Library/Frameworks/Python.framework/Versions/Current/bin/python3 pipelines/news/ship_news_post.py --dry-run
  ```

  Expected: a deck renders to `output/news/` and exits 0. If this regresses after a Phase 2 edit, you have broken the dual-role contract; revert the parameter or the rename.

### Task 2.1: Calibrated per-slide-kind cap

**Files:**
- Create: `src/render/line_fit_probe.py`
- Test: `tests/test_line_fit_probe.py`

- [ ] **Step 1: Write a failing test for the cap function**

```python
# tests/test_line_fit_probe.py
import pytest
from src.render.line_fit_probe import cap_for_slide_kind


def test_cap_for_photo_slide_is_tighter_than_typography():
    # Photo slide is Archivo Black 48px, typography is 42px.
    # The 48px slide must accept fewer characters per line.
    photo_cap = cap_for_slide_kind("photo")
    typo_cap = cap_for_slide_kind("typography")
    assert photo_cap < typo_cap
    # Sanity floor: caps must be in a sensible range.
    assert 18 <= photo_cap <= 26
    assert 22 <= typo_cap <= 30


def test_cap_for_unknown_kind_returns_safe_default():
    assert cap_for_slide_kind("nonsense") == cap_for_slide_kind("photo")
```

- [ ] **Step 2: Run, verify failure**

```bash
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 -m pytest tests/test_line_fit_probe.py -v
```
Expected: FAIL.

- [ ] **Step 3: Implement `cap_for_slide_kind`**

```python
# src/render/line_fit_probe.py
"""Render-aware line-fit calibration.

The visual cap depends on the slide's font size, which depends on
whether the slide has an image (Archivo Black 48px) or is typography-only
(Archivo Black 42px). Char-counting alone is not enough because Archivo
Black is proportional and the actual cap drifts by ~3-4 chars between
the two slide kinds.

cap_for_slide_kind() returns a calibrated char cap. Phase 2.2 adds a
Playwright probe that measures actual rendered width for the cases
where the calibrated cap is too coarse.
"""
from __future__ import annotations

# Calibrated against the 1080x1350 news template:
# - Photo slide (.line at 48px, ~940px usable width).
# - Typography slide (.line at 42px, ~920px usable width).
# Both use Archivo Black 900 lowercase, letter-spacing -0.01em.
# Numbers below come from a one-off measurement pass: we rendered
# strings of repeated lowercase letters at each font size and recorded
# the cap at which the line wrapped. Photos hit ~22 chars before wrap;
# typography hits ~26 chars.
_SLIDE_KIND_CAPS: dict[str, int] = {
    "photo":      22,
    "typography": 26,
}

_DEFAULT_CAP = 22  # safest of the two


def cap_for_slide_kind(slide_kind: str) -> int:
    """Return the per-slide-kind calibrated char cap."""
    return _SLIDE_KIND_CAPS.get(slide_kind, _DEFAULT_CAP)
```

- [ ] **Step 4: Run, verify pass**

```bash
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 -m pytest tests/test_line_fit_probe.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/render/line_fit_probe.py tests/test_line_fit_probe.py
git commit -m "$(cat <<'EOF'
feat(render): per-slide-kind char cap (photo 22, typography 26)

Replaces the single HARD_LINE_CAP=24 with a calibrated cap that
reflects whether the slide's body font is 48px (photo slide) or
42px (typography slide). Phase 2 step 1.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2.2: Playwright width-measurement probe

**Files:**
- Modify: `src/render/line_fit_probe.py`
- Modify: `tests/test_line_fit_probe.py`

- [ ] **Step 1: Test for `measure_lines_overflow` (Playwright invocation mocked)**

Append to `tests/test_line_fit_probe.py`:

```python
from unittest.mock import MagicMock
from src.render.line_fit_probe import measure_lines_overflow


def test_measure_lines_overflow_flags_visual_wrap():
    """The probe must call into Playwright with the same template as
    the real renderer and report which lines overflowed.

    We mock the browser/page so this test runs with no Chromium needed.
    """
    fake_page = MagicMock()
    # Simulated layout: line 1 fits, line 2 overflows (rendered at 980px > 940px window).
    fake_page.evaluate.return_value = [
        {"text": "fits fine",                  "rendered_width_px": 480, "wraps": False},
        {"text": "this line is way too long",  "rendered_width_px": 1020, "wraps": True},
        {"text": "ok",                         "rendered_width_px": 80,   "wraps": False},
    ]
    fake_browser = MagicMock()
    fake_browser.new_page.return_value = fake_page

    overflow = measure_lines_overflow(
        lines=["fits fine", "this line is way too long", "ok"],
        slide_kind="photo",
        browser=fake_browser,
    )
    assert overflow == [False, True, False]
```

- [ ] **Step 2: Run, verify failure**

```bash
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 -m pytest tests/test_line_fit_probe.py -v
```
Expected: FAIL.

- [ ] **Step 3: Implement `measure_lines_overflow`**

Append to `src/render/line_fit_probe.py`:

```python
from pathlib import Path
from typing import Any


_PROBE_HTML_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"/>
<style>
  @font-face {{
    font-family: "Archivo Black";
    src: url("file://{archivo_path}") format("truetype");
    font-weight: 900;
  }}
  *{{box-sizing:border-box;margin:0;padding:0;}}
  html,body{{width:1080px;height:1350px;background:#0B0B0C;}}
  .frame{{padding:62px 70px;}}
  .lines{{display:flex;flex-direction:column;gap:8px;width:940px;}}
  .line{{
    font-family:"Archivo Black",sans-serif;
    font-weight:900;
    font-size:{font_size}px;
    line-height:{line_height};
    letter-spacing:-0.01em;
    text-transform:lowercase;
    color:#EDE8DD;
    white-space:nowrap;
    overflow:visible;
  }}
</style></head><body>
<div class="frame">
  <div class="lines" id="lines">
{line_divs}
  </div>
</div></body></html>
"""


def _slide_kind_metrics(slide_kind: str) -> tuple[int, float, int]:
    """Return (font_size_px, line_height, wrap_width_px) for the slide kind."""
    if slide_kind == "typography":
        return 42, 1.10, 920
    # photo (default)
    return 48, 1.08, 940


def measure_lines_overflow(
    *,
    lines: list[str],
    slide_kind: str,
    browser: Any,
    archivo_path: str | None = None,
) -> list[bool]:
    """Return one bool per line: True if the line would visually wrap.

    The probe renders each line on its own white-space:nowrap div, then
    measures `scrollWidth` against the parent's `clientWidth`. Anything
    where rendered_width > wrap_width is flagged as overflowing.
    """
    font_size, line_height, wrap_width = _slide_kind_metrics(slide_kind)
    if archivo_path is None:
        archivo_path = str(
            Path(__file__).resolve().parents[2] / "assets/fonts/ArchivoBlack-Regular.ttf"
        )
    line_divs = "\n".join(
        f'    <div class="line" data-i="{i}">{line}</div>'
        for i, line in enumerate(lines)
    )
    html = _PROBE_HTML_TEMPLATE.format(
        archivo_path=archivo_path,
        font_size=font_size,
        line_height=line_height,
        line_divs=line_divs,
    )
    page = browser.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=1)
    page.set_content(html, wait_until="networkidle")
    probe_js = (
        "Array.from(document.querySelectorAll('.line')).map(el => ({"
        "text: el.textContent, "
        f"rendered_width_px: el.scrollWidth, wraps: el.scrollWidth > {wrap_width}"
        "}))"
    )
    measurements: list[dict] = page.evaluate(probe_js)
    page.close()
    return [bool(m["wraps"]) for m in measurements]
```

Note: this works with the existing tests because the test passes a mocked `browser.new_page` → `page.evaluate` chain that returns the precomputed list.

- [ ] **Step 4: Run, verify pass**

```bash
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 -m pytest tests/test_line_fit_probe.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/render/line_fit_probe.py tests/test_line_fit_probe.py
git commit -m "$(cat <<'EOF'
feat(render): Playwright probe for actual line overflow

measure_lines_overflow() renders each line on a white-space:nowrap
div in the actual carousel template (Archivo Black, photo or
typography font size) and reports which lines exceed the wrap width.
Char-counting drifts by 3-4 chars on Archivo Black; the probe is the
ground truth.

Phase 2 step 2 of the content quality recovery.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2.3: Iterative fit retry in the pipeline

**Files:**
- Modify: `pipelines/manual/ship_manual_post.py:generate_content`
- Modify: `src/content/carousel_writer.py:fit_slide_lines` to accept a `prior_attempt_feedback` arg

- [ ] **Step 1: Add `prior_attempt_feedback` to fit_slide_lines**

In `src/content/carousel_writer.py`, change `fit_slide_lines` signature:

```python
def fit_slide_lines(
    *,
    editorial_slides: list[EditorialSlide],
    hard_cap: int,
    api_key: str,
    prior_attempt_feedback: str = "",
) -> tuple[list[SlideFit], dict]:
```

And in the prompt template, append (only when feedback is non-empty):

```python
    feedback_block = ""
    if prior_attempt_feedback:
        feedback_block = (
            "\n\nThe previous attempt failed. Specific issues:\n"
            f"{prior_attempt_feedback}\n"
            "Fix only those specific lines. Keep the rest unchanged.\n"
        )
    prompt = FITTER_PROMPT_TEMPLATE.format(
        hard_cap=hard_cap,
        slides_json=slides_json,
        n_slides=len(editorial_slides),
    ) + feedback_block
```

- [ ] **Step 2: Add the retry loop in the pipeline**

In `pipelines/manual/ship_manual_post.py`, replace the single `fit_slide_lines(...)` call inside `generate_content` with a retry loop:

```python
    from playwright.sync_api import sync_playwright as _sync_pw_for_probe
    from src.render.line_fit_probe import (
        cap_for_slide_kind,
        measure_lines_overflow,
    )

    # We do not yet know the per-slot slide kind (photo vs typography);
    # that depends on image-source results, which only run later. Use
    # photo cap (the tighter of the two) as the conservative default for
    # the fitter; the probe will catch anything that still overflows on
    # typography slides too.
    fitter_cap = cap_for_slide_kind("photo")

    feedback = ""
    fits: list[SlideFit] = []
    usage_b: dict = {}
    last_err: Exception | None = None
    for attempt in range(1, 4):  # max 3 attempts
        try:
            fits, usage_b = fit_slide_lines(
                editorial_slides       = writer_result.slides,
                hard_cap               = fitter_cap,
                api_key                = api_key,
                prior_attempt_feedback = feedback,
            )
        except (FactPreservationError, LineFitError) as exc:
            last_err = exc
            feedback = str(exc)
            _log(f"     [fitter retry {attempt}] {exc}")
            continue

        # Probe each slide for visual wrap.
        with _sync_pw_for_probe() as pw:
            browser = pw.chromium.launch()
            wraps_per_slide: list[list[bool]] = []
            for f in fits:
                wraps_per_slide.append(measure_lines_overflow(
                    lines      = f.lines,
                    slide_kind = "photo",  # conservative; refined in 2.4
                    browser    = browser,
                ))
            browser.close()
        bad: list[str] = []
        for f, wraps in zip(fits, wraps_per_slide):
            for j, wraps_j in enumerate(wraps, 1):
                if wraps_j:
                    bad.append(
                        f"slide {f.slide_index} line {j} visually wraps: "
                        f"{f.lines[j-1]!r} (Archivo Black photo cap)"
                    )
        if not bad:
            break
        feedback = "\n".join(bad)
        _log(f"     [fitter retry {attempt}] visual wrap detected:\n{feedback}")
    else:
        # Fell off the loop without breaking - exhausted retries.
        raise LineFitError(
            f"fitter could not produce a non-wrapping deck after 3 attempts: {last_err}"
        )
```

- [ ] **Step 3: Smoke-test**

```bash
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 pipelines/manual/ship_manual_post.py \
  --brief "Phineas Gage survived a 13-pound iron rod through his skull in 1848" \
  --type fact --dry-run
```
Expected: at most 1-2 retries, then a clean deck. Probe log lines visible.

- [ ] **Step 4: Commit**

```bash
git add src/content/carousel_writer.py pipelines/manual/ship_manual_post.py
git commit -m "$(cat <<'EOF'
feat(carousel): iterative fit-with-probe retry loop (max 3)

The pipeline now runs the Playwright probe after each fitter call
and feeds visual-wrap diagnostics back to Haiku for a targeted retry.
Hard fails after 3 attempts.

Phase 2 step 3 of the content quality recovery.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Phase 2 acceptance

Render 10 dry-run briefs across all five carousel modes. For each, open the rendered PDFs and verify:
- No line breaks into a 4th visual row.
- No orphan single-word terminal lines.
- No Archivo Black soft wrap (all lines fit on one row).
- Probe retries log meaningfully (operator can see when the fitter retried and why).

### **STOP - request approval before Phase 3.**

> Toby:
> - 10-deck visual review of Phase 2 output.
> - Confirm probe latency is acceptable (one Playwright launch per fitter call).

---

## Phase 3 - Image-intent routing and filter corrections

**Goal:** A per-slot intent classifier picks the right provider order based on whether the slide is about a named entity, a photographable scene, or an abstract proxy. Token-boundary negative-term matching replaces the current substring match.

### Task 3.1: Per-slot intent classifier

**Files:**
- Modify: `src/research/image_sourcer.py`
- Test: `tests/test_image_intent_routing.py`

- [ ] **Step 1: Failing test for `_classify_slot_intent`**

```python
# tests/test_image_intent_routing.py
import pytest
from src.research.image_sourcer import _classify_slot_intent


def test_classifies_named_entity_query_as_entity():
    intent = _classify_slot_intent(
        slide_text="phineas gage survived a rod",
        query="phineas gage portrait",
        slot_aliases=["Phineas Gage"],
    )
    assert intent == "entity"


def test_classifies_descriptive_b_roll_as_scene():
    intent = _classify_slot_intent(
        slide_text="crews lifted the wreckage",
        query="bridge collapse rescue crew",
        slot_aliases=[],
    )
    assert intent == "scene"


def test_classifies_abstract_concept_as_abstract():
    intent = _classify_slot_intent(
        slide_text="the budget was approved",
        query="federal budget approval",
        slot_aliases=[],
    )
    assert intent == "abstract"
```

- [ ] **Step 2: Run, verify failure**

```bash
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 -m pytest tests/test_image_intent_routing.py -v
```
Expected: FAIL.

- [ ] **Step 3: Implement `_classify_slot_intent`**

In `src/research/image_sourcer.py`, add:

```python
_ABSTRACT_TOKENS = frozenset({
    "budget", "funding", "approval", "policy", "ruling", "verdict",
    "decision", "regulation", "classification", "guidelines",
    "agreement", "negotiation", "investigation", "analysis",
    "inflation", "interest", "tariff", "quota",
})

_SCENE_TOKENS = frozenset({
    "rescue", "crowd", "protest", "march", "factory", "office",
    "courtroom", "warehouse", "lab", "hospital", "stadium",
    "street", "harbour", "port", "cockpit", "deck", "platform",
    "site", "scene", "queue", "bridge", "tunnel",
})


def _classify_slot_intent(
    *,
    slide_text: str,
    query: str,
    slot_aliases: list[str] | None,
) -> str:
    """Return 'entity' | 'scene' | 'abstract' for one slot.

    'entity' = the slot is about a specific named subject. Archive
              providers (Wikipedia, Commons, Smithsonian) should run
              first; their files are titled by subject identity.
    'scene' = the slot describes a photographable scene without a
              specific named subject. Stock providers (Pexels, Pixabay)
              are better; they tag by visual content.
    'abstract' = the slot describes an abstract concept (budget,
                 ruling, policy). The fitter should already have
                 reframed this around a concrete proxy, but if it
                 didn't, route to stock providers and rely on the
                 visual_fallback_query.
    """
    has_alias = bool(slot_aliases)
    text = f"{slide_text} {query}".lower()
    tokens = set(re.findall(r"[a-z]{3,}", text))
    has_scene = bool(tokens & _SCENE_TOKENS)
    has_abstract = bool(tokens & _ABSTRACT_TOKENS)

    if has_alias:
        return "entity"
    if has_abstract and not has_scene:
        return "abstract"
    if has_scene:
        return "scene"
    # Fallback: capitalised proper-noun heuristic on the original
    # (non-lowered) slide text.
    if any(w[:1].isupper() and len(w) > 2 for w in slide_text.split()):
        return "entity"
    return "scene"
```

(Add `import re` at top of `image_sourcer.py` if not already present.)

- [ ] **Step 4: Run, verify pass**

```bash
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 -m pytest tests/test_image_intent_routing.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/research/image_sourcer.py tests/test_image_intent_routing.py
git commit -m "$(cat <<'EOF'
feat(image): _classify_slot_intent (entity/scene/abstract)

Per-slot classifier that drives provider routing in source_images().
Phase 3 step 1 of the content quality recovery.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3.2: Route providers per slot intent

**Files:**
- Modify: `src/research/image_sourcer.py:source_images` (around lines 230-330)

- [ ] **Step 1: Wire the classifier into the R1 fetch loop**

Replace the existing R1 fetch call with a per-slot provider override:

```python
        slot_intent = _classify_slot_intent(
            slide_text   = "",  # not yet plumbed; left blank for now (improved in 3.3)
            query        = query,
            slot_aliases = slot_override,
        )
        log.debug("IMAGE slot=%d intent=%s", i, slot_intent)

        if slot_intent == "entity":
            slot_provider_order: tuple[str, ...] | None = None  # use topic order (archive-first)
        elif slot_intent == "scene":
            slot_provider_order = ("pexels", "pixabay", "smithsonian", "commons", "wiki", "wiki_article")
        else:  # abstract
            slot_provider_order = ("pexels", "pixabay", "smithsonian", "commons")

        relaxation_round = 1
        raw_pool = self._fetcher.fetch_pool(
            query             = query,
            topic             = self.topic,
            post_id           = post_id,
            slide_index       = i,
            intent_text       = intent.fallback_query or query,
            source_aliases    = effective_aliases,
            negative_terms    = intent.negative_terms or None,
            context_words     = intent.context_words  or None,
            extra_fallbacks   = extra_fallbacks,
            max_pool          = pool_size,
            provider_override = slot_provider_order,
        )
```

- [ ] **Step 2: Smoke-test against the SPEC acceptance set**

```bash
for brief in \
  "The history of Concorde, how it was built and why it ended" \
  "Phineas Gage and the iron rod, 1848" \
  "How rescue crews lifted Galloping Gertie's collapsed deck"
do
  /Library/Frameworks/Python.framework/Versions/Current/bin/python3 pipelines/manual/ship_manual_post.py \
    --brief "$brief" --type fact --dry-run
done
```
Expected: each deck logs `IMAGE slot=N intent=...` lines; entity briefs route archive-first, scene briefs route stock-first.

- [ ] **Step 3: Commit**

```bash
git add src/research/image_sourcer.py
git commit -m "$(cat <<'EOF'
feat(image): route providers per slot intent (entity/scene/abstract)

Each slot's provider order is now decided by its intent, not just
its round. Entity slots stay archive-first; scene and abstract slots
go stock-first to match how those providers tag content.

Phase 3 step 2 of the content quality recovery.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3.3: Token-boundary negative-term matching

**Files:**
- Modify: `src/research/image_fetcher.py:_candidate_allowed` (around lines 880-908)

- [ ] **Step 1: Failing test**

Append to `tests/test_image_intent_routing.py`:

```python
from src.research.image_fetcher import _negative_term_hits


def test_negative_term_hits_token_boundary():
    """A negative 'station' must not reject 'naval station mare island'
    when 'naval' is part of a multi-word valid alias context, but it
    should reject 'metro station entrance' on a tag provider."""
    # Substring-matching wrongly hits 'station' inside 'destination'.
    # Token matching must NOT.
    hits = _negative_term_hits(
        meta="travel destination paris",
        negative_terms=["station"],
    )
    assert hits == []  # 'station' not a token in 'destination'

    hits = _negative_term_hits(
        meta="metro station entrance",
        negative_terms=["station"],
    )
    assert hits == ["station"]


def test_negative_term_hits_compound_phrase():
    hits = _negative_term_hits(
        meta="place de la concorde paris square",
        negative_terms=["place de la concorde", "obelisk"],
    )
    assert "place de la concorde" in hits
```

- [ ] **Step 2: Run, verify failure**

```bash
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 -m pytest tests/test_image_intent_routing.py -v
```
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `_negative_term_hits` and use it**

In `src/research/image_fetcher.py`, add a helper near `_alias_matches`:

```python
def _negative_term_hits(*, meta: str, negative_terms: list[str]) -> list[str]:
    """Return negative terms that match meta on token / phrase boundaries.

    Single-word negatives must match a whole token in meta. Multi-word
    phrases match a contiguous token sequence anywhere in meta.

    Avoids the substring trap where 'station' fires on 'destination'.
    """
    if not negative_terms or not meta:
        return []
    meta_lower = meta.lower()
    meta_tokens = re.findall(r"[a-z0-9]+", meta_lower)
    meta_token_string = " ".join(meta_tokens)
    hits: list[str] = []
    for term in negative_terms:
        t = term.strip().lower()
        if not t:
            continue
        if " " in t:
            # Multi-word: match a contiguous token-sequence on word
            # boundaries. Build a regex over the token string.
            pattern = r"(?:^|\s)" + r"\s+".join(re.escape(w) for w in t.split()) + r"(?:\s|$)"
            if re.search(pattern, meta_token_string):
                hits.append(term)
        else:
            if t in meta_tokens:
                hits.append(term)
    return hits
```

(Ensure `import re` is present in `image_fetcher.py`.)

Replace the existing negative-term block in `_candidate_allowed`:

```python
        if negative_terms and meta:
            neg_hit = next((t for t in negative_terms if t.lower() in meta), None)
            if neg_hit:
                ...
```

with:

```python
        if negative_terms and meta:
            hits = _negative_term_hits(meta=meta, negative_terms=negative_terms)
            neg_hit = hits[0] if hits else None
            if neg_hit:
                is_weak_neg = (len(neg_hit.split()) == 1)
                has_strong_alias = bool(source_aliases) and any(
                    len(a.split()) > 1 and _alias_matches(a, meta)
                    for a in source_aliases
                )
                is_archive = cand.provider in _ARCHIVE_PROVIDERS
                if is_weak_neg and (has_strong_alias or is_archive):
                    log.debug(
                        "NEGATIVE_OVERRIDE neg=%r overridden (strong_alias=%s, archive=%s) | %s | meta=%r",
                        neg_hit, has_strong_alias, is_archive, cand.provider,
                        (cand.meta_text or "")[:80],
                    )
                    # Fall through to alias gate.
                else:
                    return False, f"negative_term={neg_hit!r}"
```

- [ ] **Step 4: Run all image tests**

```bash
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 -m pytest tests/ -v
```
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/research/image_fetcher.py tests/test_image_intent_routing.py
git commit -m "$(cat <<'EOF'
fix(image): token-boundary negative term matching

Previously _candidate_allowed used `term.lower() in meta`, which fired
'station' on 'destination'. Now uses _negative_term_hits which
matches whole tokens for single-word negatives and contiguous
token-sequences for multi-word phrases.

Phase 3 step 3 of the content quality recovery.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3.4: Align `MAX_REUSES` with SPEC_IMAGE_PIPELINE section 10

**Files:**
- Modify: `src/research/image_sourcer.py` (the `MAX_REUSES` module-level constant near line 50)
- Test: `tests/test_image_intent_routing.py`

`SPEC_IMAGE_PIPELINE.md` section 10 says: "The same URL is capped at 2 uses per carousel." The deterministic-fallback eligibility filter in `source_images()` is `self._use_count.get(c.url, 0) < MAX_REUSES`. Currently `MAX_REUSES = 1`, which means a URL is only eligible when `_use_count == 0`, i.e. never reused. That makes `_pick_reuse()` unreachable for the spec's intended "low-quality reuse beats no image at all" path on duplicate-only pools. Aligning to `MAX_REUSES = 2` brings code into spec compliance: a URL can appear in the deck once normally, and once more as a reuse fallback if the alternative is typography-only.

This is a small, contained alignment. No spec change. No behaviour change for slots that have other candidates. The only path that lights up is the `_pick_reuse()` branch when the eligible pool is empty.

- [ ] **Step 1: Failing test for second-use eligibility**

Append to `tests/test_image_intent_routing.py`:

```python
from unittest.mock import MagicMock
from src.research.image_sourcer import ImageSourcer, MAX_REUSES


def test_max_reuses_allows_second_use_per_carousel():
    """SPEC section 10: 'same URL is capped at 2 uses per carousel'.

    Implementation contract: a URL with _use_count == 1 must remain
    eligible (so _pick_reuse can return it). With MAX_REUSES == 1 the
    URL would already be ineligible at count 1; with MAX_REUSES == 2
    it stays eligible for the second use.
    """
    assert MAX_REUSES >= 2, (
        f"MAX_REUSES={MAX_REUSES} blocks second use; "
        "SPEC_IMAGE_PIPELINE.md section 10 requires up to 2 uses per carousel."
    )

    sourcer = ImageSourcer(topic="editorial", use_fresh_ledger=True)
    # Simulate: URL was used once already.
    sourcer._use_count["data:image/jpeg;base64,fake"] = 1
    # The eligibility predicate used inside source_images:
    eligible_at_count_1 = (
        sourcer._use_count.get("data:image/jpeg;base64,fake", 0) < MAX_REUSES
    )
    assert eligible_at_count_1 is True
    # Simulate: URL has now been used twice.
    sourcer._use_count["data:image/jpeg;base64,fake"] = 2
    eligible_at_count_2 = (
        sourcer._use_count.get("data:image/jpeg;base64,fake", 0) < MAX_REUSES
    )
    assert eligible_at_count_2 is False
```

- [ ] **Step 2: Run, verify failure on the assert about MAX_REUSES**

```bash
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 -m pytest tests/test_image_intent_routing.py::test_max_reuses_allows_second_use_per_carousel -v
```
Expected: FAIL with `AssertionError: MAX_REUSES=1 blocks second use`.

- [ ] **Step 3: Update the constant**

In `src/research/image_sourcer.py`, find the `MAX_REUSES` constant (around line 50, near `MIN_SCORE` and `MIN_SCORE_R3`). Change:

```python
MAX_REUSES = 1
```

to:

```python
# Cap matches SPEC_IMAGE_PIPELINE.md section 10: same URL up to 2 uses
# per carousel. Eligibility is `_use_count[url] < MAX_REUSES`, so a value
# of 2 lets a URL be used once normally then once more as a reuse
# fallback when the alternative is typography-only.
MAX_REUSES = 2
```

If the docstring at the top of `image_sourcer.py` mentions `<2` or `2 uses`, leave it; if it mentions `1 use` or `no reuse`, update to match the new constant.

- [ ] **Step 4: Run, verify pass**

```bash
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 -m pytest tests/ -v
```
Expected: all green. The pre-existing `tests/test_image_sourcer.py::test_overused_url_hard_rejected` still passes because it asserts behaviour at `_use_count >= MAX_REUSES`, which is still correctly enforced.

- [ ] **Step 5: Commit**

```bash
git add src/research/image_sourcer.py tests/test_image_intent_routing.py
git commit -m "$(cat <<'EOF'
fix(image): align MAX_REUSES with SPEC section 10 (2 uses per carousel)

MAX_REUSES was 1, which made the eligibility predicate
(_use_count < MAX_REUSES) reject any URL on its second appearance and
left _pick_reuse() unreachable for the spec's intended fallback path.
SPEC_IMAGE_PIPELINE.md section 10 says "the same URL is capped at 2
uses per carousel"; setting MAX_REUSES = 2 brings code into spec.

Phase 3 step 4 of the content quality recovery.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Phase 3 acceptance

Run the SPEC_IMAGE_PIPELINE acceptance set:
1. Concorde aircraft (no Place de la Concorde, no obelisks).
2. Concord, Massachusetts (no Concorde aircraft).
3. Concord grape (no aircraft, no town).
4. Niche science topic (typography or diagrams allowed).
5. Historical person (portraits preferred).
6. Topic with no good images (cover fails honestly).

For each, open the rendered PDF and inspect. No wrong-subject covers.

```bash
for brief in \
  "The history of Concorde supersonic airliner" \
  "The town of Concord Massachusetts" \
  "How the Concord grape became America's juice grape" \
  "Why CRISPR base editing is different from regular CRISPR" \
  "Phineas Gage iron rod 1848" \
  "Federal Reserve open market operations 1990s"
do
  /Library/Frameworks/Python.framework/Versions/Current/bin/python3 pipelines/manual/ship_manual_post.py \
    --brief "$brief" --type fact --dry-run
done
```

### **STOP - request approval before Phase 4.**

> Toby:
> - Walk through the 6 acceptance decks visually.
> - Confirm no wrong-subject covers, no broken negative gates.

---

## Phase 4 - Rule unification

**Goal:** One source of truth for line caps, anti-orphan, weak endings, beat density, and photographable rules. Remove duplicate or conflicting fragments across the autonomous agent prompt, the writer prompt, and the validator.

### Task 4.1: Carousel rules module

**Files:**
- Create: `src/content/carousel_rules.py`

- [ ] **Step 1: Define the module**

```python
# src/content/carousel_rules.py
"""Single source of truth for carousel content rules.

Phase 4 of the content quality recovery: removes the drift between
ship_manual_post.py BRAND_VOICE_EDITORIAL, autonomous_agent.py
MODE_PROMPTS, and src/content/carousel_writer.py prompt templates.
"""
from __future__ import annotations

# Visual line caps, by slide kind. Calibrated in src/render/line_fit_probe.py.
PHOTO_SLIDE_CAP = 22
TYPOGRAPHY_SLIDE_CAP = 26

# Words a line must not end on (weak connectors).
WEAK_LINE_ENDINGS = frozenset({
    "a", "the", "and", "or", "of", "in", "to", "with", "an", "at", "by", "for",
})

# Maximum slides per carousel (cover + content).
MAX_SLIDES_TOTAL = 8
MIN_SLIDES_TOTAL = 3


BEAT_DENSITY_RULES = """\
ONE SLIDE = ONE IDEA. ONE BEAT = ONE FACT. HARD RULE.
- Semicolons inside a beat are FORBIDDEN.
- "and" welding two facts is FORBIDDEN. That second "and" starts a new beat.
- Multiple named people, multiple events, or multiple consequences in one
  slide are FORBIDDEN.
- Front-load the most interesting element on each slide.
"""


PHOTOGRAPHABLE_BEATS_RULES = """\
PHOTOGRAPHABLE BEATS - HARD RULE.
- Every beat's image_query must describe a visible object, person, or scene
  an archive could realistically have a photo of.
- Abstract concepts (a budget, a ruling, a classification, a regulation)
  must be reframed around a concrete photographable proxy: the people,
  the device, the workplace, the scene, the era.
- If you cannot think of a photographable proxy, repeat the cover query.
"""


COVER_TITLE_RULES = """\
Cover title: 5-9 words, no full stop. Must contain a verb or a sting.
Banned chant-style shapes:
- "the X with no Y"
- "no X no Y"
- "X-free Y"
- "the Y that X" where Y is vague
"""
```

- [ ] **Step 2: Replace the inline rules**

In `pipelines/manual/ship_manual_post.py`:

```python
from src.content.carousel_rules import (
    BEAT_DENSITY_RULES,
    PHOTOGRAPHABLE_BEATS_RULES,
    COVER_TITLE_RULES,
)
```

Rebuild `BRAND_VOICE_EDITORIAL` as:

```python
BRAND_VOICE_EDITORIAL = f"""\
Brand: factjot (@factjot)
Voice: curious, precise, dry. A smart friend explaining something remarkable.
Tone: confident, never sensational. Present tense where possible.
Reading level: general audience.

Editorial rules (Stage A - meaning only, layout handled separately):
{BEAT_DENSITY_RULES}
- No em dashes. Commas, full stops, or parentheses instead.
- British English. No hedging. No attribution phrases.
- Preserve specific names, dates, numbers, places.
- If a beat is genuinely too dense for one slide, surface the dropped
  sub-fact in dropped_facts rather than welding fragments.

{COVER_TITLE_RULES}
{PHOTOGRAPHABLE_BEATS_RULES}
"""

BRAND_VOICE = BRAND_VOICE_EDITORIAL
```

In `scripts/autonomous_agent.py`, add the import alongside the other top-of-file imports:

```python
from src.content.carousel_rules import BEAT_DENSITY_RULES, PHOTOGRAPHABLE_BEATS_RULES
```

The `MODE_PROMPTS` dict assembles each prompt from a `textwrap.dedent("""...""")` literal. Inside each carousel-mode literal (NEWS, LIST, FACT - three places), replace the hand-written paragraph that begins `BEAT DENSITY -- HARD RULE` and ends before `DECISION PROCESS` with a single placeholder line:

```
{beat_density_rules}
{photographable_beats_rules}
```

Then at the end of `autonomous_agent.py`, change the dict assembly so each mode-prompt string is a Python f-string that interpolates the imported blocks:

```python
MODE_PROMPTS: dict[str, str] = {
    "reel_morning": SHARED_CORE + REEL_MORNING_BODY,
    "reel_evening": SHARED_CORE + REEL_EVENING_BODY,
    "news":         SHARED_CORE + NEWS_BODY.format(
        beat_density_rules        = BEAT_DENSITY_RULES,
        photographable_beats_rules= PHOTOGRAPHABLE_BEATS_RULES,
    ),
    "list":         SHARED_CORE + LIST_BODY.format(
        beat_density_rules        = BEAT_DENSITY_RULES,
        photographable_beats_rules= PHOTOGRAPHABLE_BEATS_RULES,
    ),
    "fact":         SHARED_CORE + FACT_BODY.format(
        beat_density_rules        = BEAT_DENSITY_RULES,
        photographable_beats_rules= PHOTOGRAPHABLE_BEATS_RULES,
    ),
}
```

The existing inline `MODE_PROMPTS` dict is constructed with simple string concatenation; this change introduces named `*_BODY` constants. Concretely, lift each mode's `textwrap.dedent` literal into a module-level `NEWS_BODY = textwrap.dedent("""...""")` (etc.), with `{beat_density_rules}` and `{photographable_beats_rules}` placeholder fields where the duplicated paragraphs used to be. Reels do not use these blocks (they are carousel-specific).

- [ ] **Step 3: Smoke-test all five modes**

```bash
for mode in fact news list reel_morning reel_evening; do
  DRY_RUN=true /Library/Frameworks/Python.framework/Versions/Current/bin/python3 scripts/autonomous_agent.py --post-mode "$mode"
done
```
Expected: same output quality as before; no regression. Carousel modes should still produce 6 / 7 / 6 slides as appropriate.

- [ ] **Step 4: Commit**

```bash
git add src/content/carousel_rules.py pipelines/manual/ship_manual_post.py scripts/autonomous_agent.py
git commit -m "$(cat <<'EOF'
refactor(carousel): single source of truth for content rules

src/content/carousel_rules.py centralises BEAT_DENSITY_RULES,
PHOTOGRAPHABLE_BEATS_RULES, COVER_TITLE_RULES, line caps, and weak-ending
words. ship_manual_post.py and autonomous_agent.py now import from there
instead of duplicating the rules inline.

Phase 4 of the content quality recovery.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Phase 4 acceptance

- All five autonomous modes still post a valid dry-run.
- A `grep -r "ONE SLIDE = ONE IDEA" .` returns the rule defined in `src/content/carousel_rules.py` and nowhere else (the imports surface at usage sites but the literal source is single).
- A `grep -r "HARD_LINE_CAP" .` returns the legacy alias only as a re-export from `carousel_rules.py`.

### **STOP - request approval before declaring done.**

> Toby:
> - Final visual review across all five modes.
> - Confirm the carousel quality ledger now shows clean rows for the last week of dry-runs.
> - Confirm we are ready to enable autonomous posting again.

---

## Definition of done

The recovery is complete only when ALL of these hold:

1. No silent content trimming anywhere in the carousel path. Every shape mismatch raises `CarouselShapeError` with a structured payload.
2. Every line on every rendered slide fits the visual cap; no Archivo Black soft wraps.
3. Every named entity, date, and number from the brief survives onto a slide.
4. Image coverage is high (≥ 80% photo, ≤ 20% intentional typography per deck) without wrong-subject regressions on the SPEC acceptance set.
5. `data/ledgers/carousel_quality.jsonl` shows clean rows for at least 5 consecutive dry-runs across all five modes.
6. Failures are explicit, tagged in `FAILURE_KIND:` lines in the autonomous agent's tool result, and logged in the quality ledger.

If any of the above is unverified, the recovery is not done.
