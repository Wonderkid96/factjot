"""Structured diagnostics for carousel shape and layout failures.

Phase 0 of the content quality recovery: replaces silent slicing
(slides[:8], lines[:3]) with hard fails that carry a payload an
operator can read in the autonomous agent's tool result and in the
quality ledger.
"""
from __future__ import annotations

from typing import Any

# Hard cap for a single slide line at the rendered template size. Mirrors
# HARD_LINE_CAP in pipelines/manual/ship_manual_post.py so diagnostics can
# be built before the pipeline-level assert runs. Phase 2 replaces this
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
    at the top of the implementation plan.
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
    can surface it in its tool result.

    `usage` is a dict of any partial cost incurred before the shape
    check ran, so the quality ledger can record honest spend even on
    failed runs.
    """

    def __init__(
        self,
        message: str,
        diagnostics: dict[str, Any],
        *,
        usage: dict[str, Any] | None = None,
    ):
        self.diagnostics = diagnostics
        self.usage = usage or {}
        summary = (
            f"{message} "
            f"(requested_content_slides={diagnostics.get('requested_content_slides')}, "
            f"returned_content_slides={diagnostics.get('returned_content_slides')}, "
            f"overlong={len(diagnostics.get('overlong_lines') or [])}, "
            f"bad_line_count={len(diagnostics.get('bad_line_count') or [])})"
        )
        super().__init__(summary)
