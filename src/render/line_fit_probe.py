"""Render-aware line-fit calibration.

The visual cap depends on the slide's font size, which depends on
whether the slide has an image (Archivo Black 48px) or is typography-only
(Archivo Black 42px). Char-counting alone is not enough because Archivo
Black is proportional and the actual cap drifts by ~3-4 chars between
the two slide kinds.

cap_for_slide_kind() returns a calibrated char cap. The Playwright
probe (measure_lines_overflow) gives the ground truth for cases where
the calibrated cap is too coarse.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

# Calibrated against the 1080x1350 news template:
# - Photo slide (.line at 48px, ~940px usable width).
# - Typography slide (.line at 42px, ~920px usable width).
# Both use Archivo Black 900 lowercase, letter-spacing -0.01em.
_SLIDE_KIND_CAPS: dict[str, int] = {
    "photo":      22,
    "typography": 26,
}

_DEFAULT_CAP = 22  # safest of the two


def cap_for_slide_kind(slide_kind: str) -> int:
    """Return the per-slide-kind calibrated char cap."""
    return _SLIDE_KIND_CAPS.get(slide_kind, _DEFAULT_CAP)
