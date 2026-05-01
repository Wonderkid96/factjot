"""Render a branded 1080x1920 Story PNG teasing a new Reel.

Posted to Instagram Stories immediately after a Reel goes live. Drives
profile visits from viewers who see the Story but not the Reel in-feed.

Design: dark background, accent gradient line, carousel header (factjot. ─── New Reel),
red NEW REEL pill, large fact title, "↑ Watch on our profile" CTA, topic pill at bottom.
"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

from src.core.brand import (
    FONT_SERIF_REGULAR, FONT_SERIF_ITALIC,
    FONT_SANS_SEMIBOLD,
    FONT_MONO_BOLD,
    REEL_W, REEL_H,
    assert_fonts_present,
)

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _title_to_html(title: str) -> str:
    """Light emphasis: italicise the last word for Instrument Serif flair."""
    from html import escape
    words = title.split()
    if len(words) <= 2:
        return escape(title)
    plain = escape(" ".join(words[:-1]))
    last = escape(words[-1])
    return f"{plain} <em>{last}</em>"


def render_story(
    title: str,
    topic: str,
    out_path: Path,
    *,
    frame_path: Path | None = None,
    title_size: int = 96,
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
        frame_url=frame_url,
        font_serif_regular=FONT_SERIF_REGULAR.as_uri(),
        font_serif_italic=FONT_SERIF_ITALIC.as_uri(),
        font_sans_semibold=FONT_SANS_SEMIBOLD.as_uri(),
        font_mono_bold=FONT_MONO_BOLD.as_uri(),
    )

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(
            viewport={"width": REEL_W, "height": REEL_H},
            device_scale_factor=1,
        )
        page = context.new_page()
        page.set_content(html, wait_until="networkidle")
        page.screenshot(
            path=str(out_path),
            omit_background=False,
            full_page=False,
            clip={"x": 0, "y": 0, "width": REEL_W, "height": REEL_H},
        )
        browser.close()

    print(f"  [story] rendered {out_path.name}")
    return out_path
