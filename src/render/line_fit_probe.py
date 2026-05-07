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
