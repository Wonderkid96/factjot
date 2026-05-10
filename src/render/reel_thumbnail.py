"""Render a branded 1080x1920 thumbnail PNG for a Reel's feed cover.

The thumbnail is what appears on the profile grid and in the feed before
a viewer taps to play. A branded, legible title card is more compelling
than a random video frame and keeps the grid visually consistent.

Design: TJCreate Visual Style Guide v2.0 - Archivo Black 900 lowercase
headline anchored to the 4:5 grid window safe area (y=285..1635), wordmark
+ section counter at top, category pill + fact counter at bottom. Years
in the title are auto-accented red.
"""
from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

from src.core.brand import (
    FONT_SERIF_REGULAR, FONT_SERIF_ITALIC,
    FONT_SANS_SEMIBOLD,
    FONT_SANS_BOLD,
    FONT_MONO_BOLD,
    FONT_CAPTION_BLACK,
    REEL_W, REEL_H,
    assert_fonts_present,
)

_TEMPLATE_DIR = Path(__file__).parent / "templates"

_YEAR_RE = re.compile(r"\b(1[1-9]\d{2}|20\d{2})\b")


def _title_to_html(title: str) -> str:
    """Prepare title for the Archivo Black headline.

    - Strip trailing period (template adds an accent dot via CSS ::after).
    - If the title contains a 4-digit year (1100-2099), wrap it in <strong>
      so the template renders it in accent red. Matches the v2 spec
      "accent period on key words" rule for headline emphasis.
    """
    from html import escape
    cleaned = title.strip().rstrip(".")
    escaped = escape(cleaned)
    return _YEAR_RE.sub(lambda m: f"<strong>{m.group(0)}</strong>", escaped)


def render_thumbnail(
    title: str,
    topic: str,
    out_path: Path,
    *,
    frame_path: Path | None = None,
    title_size: int = 132,
    kicker: str | None = None,
    fact_number: str | None = None,
) -> Path:
    """Render a thumbnail PNG with optional footage frame as background.

    Anchored to Instagram's profile-grid 4:5 safe area (y=285..1635).
    Heavy gradient bands cover the cropped top and bottom 540px and double
    as legibility scrims. Headline is Archivo Black 900 lowercase per v2.

    Optional `kicker` (e.g. "DID YOU KNOW") sits above the headline as a
    red mono kicker. Optional `fact_number` sits in the bottom-right as
    `[ № 047 ]`.
    """
    assert_fonts_present()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=False)
    template = env.get_template("reel_thumbnail.html.j2")

    if frame_path and Path(frame_path).exists():
        import base64
        frame_bytes = Path(frame_path).read_bytes()
        ext = Path(frame_path).suffix.lower().lstrip(".")
        mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"
        frame_url = f"data:{mime};base64,{base64.b64encode(frame_bytes).decode()}"
    else:
        frame_url = None

    topic_label = topic.upper()
    html = template.render(
        width=REEL_W,
        height=REEL_H,
        topic=topic_label,
        category=topic_label,
        title_html=_title_to_html(title),
        headline_size=title_size,
        kicker=kicker,
        fact_number=fact_number,
        frame_url=frame_url,
        font_serif_regular=FONT_SERIF_REGULAR.as_uri(),
        font_serif_italic=FONT_SERIF_ITALIC.as_uri(),
        font_sans_semibold=FONT_SANS_SEMIBOLD.as_uri(),
        font_sans_bold=FONT_SANS_BOLD.as_uri(),
        font_mono_bold=FONT_MONO_BOLD.as_uri(),  # legacy alias, unused
        font_archivo_black=FONT_CAPTION_BLACK.as_uri(),
    )

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            context = browser.new_context(
                viewport={"width": REEL_W, "height": REEL_H},
                device_scale_factor=1,
            )
            page = context.new_page()
            page.set_content(html, wait_until="networkidle")
            page.evaluate("() => document.fonts.ready")
            page.screenshot(
                path=str(out_path),
                omit_background=False,
                full_page=False,
                clip={"x": 0, "y": 0, "width": REEL_W, "height": REEL_H},
            )
        finally:
            browser.close()

    print(f"  [thumbnail] rendered {out_path.name}")
    return out_path
