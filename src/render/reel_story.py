"""Render a branded 1080x1920 Story PNG teasing a new Reel.

Posted to Instagram Stories immediately after a Reel goes live. Drives
profile visits from viewers who see the Story but not the Reel in-feed.

Design: TJCreate Visual Style Guide v2.0 - stripped layout, central
Archivo Black 900 lowercase headline + small NEW REEL pill. The Reel
cover carries brand chrome; the story is the hook in its purest form.
Years in the title are auto-accented red.
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
    FONT_CAPTION_BLACK,
    REEL_W, REEL_H,
    assert_fonts_present,
)

_TEMPLATE_DIR = Path(__file__).parent / "templates"

_YEAR_RE = re.compile(r"\b(1[1-9]\d{2}|20\d{2})\b")


def _title_to_html(title: str) -> str:
    """Prepare title for the Archivo Black headline.

    Strips trailing period (template adds an accent dot via CSS) and wraps
    any 4-digit year in <strong> so it renders in accent red. Matches the
    reel thumbnail treatment so cover and story read as a pair.
    """
    from html import escape
    cleaned = title.strip().rstrip(".")
    escaped = escape(cleaned)
    return _YEAR_RE.sub(lambda m: f"<strong>{m.group(0)}</strong>", escaped)


def render_story(
    title: str,
    topic: str,
    out_path: Path,
    *,
    frame_path: Path | None = None,
    title_size: int = 132,
    kicker: str | None = None,
) -> Path:
    """Render a Story PNG with optional footage frame as background."""
    assert_fonts_present()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=False)
    template = env.get_template("reel_story.html.j2")

    if frame_path and Path(frame_path).exists():
        import base64
        frame_bytes = Path(frame_path).read_bytes()
        ext = Path(frame_path).suffix.lower().lstrip(".")
        mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"
        frame_url = f"data:{mime};base64,{base64.b64encode(frame_bytes).decode()}"
    else:
        frame_url = None

    html = template.render(
        width=REEL_W,
        height=REEL_H,
        topic=topic.upper(),
        title_html=_title_to_html(title),
        title_size=title_size,
        kicker=kicker,
        frame_url=frame_url,
        font_serif_regular=FONT_SERIF_REGULAR.as_uri(),
        font_serif_italic=FONT_SERIF_ITALIC.as_uri(),
        font_sans_semibold=FONT_SANS_SEMIBOLD.as_uri(),
        font_sans_bold=FONT_SANS_BOLD.as_uri(),
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

    print(f"  [story] rendered {out_path.name}")
    return out_path
