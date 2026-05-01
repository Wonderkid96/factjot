"""Render a branded 1080x1920 thumbnail PNG for a Reel's feed cover.

The thumbnail is what appears on the profile grid and in the feed before
a viewer taps to play. A branded, legible title card is more compelling
than a random video frame and keeps the grid visually consistent.

Design: dark background, accent gradient line (left edge), carousel-style
header (factjot. ─── TOPIC), large centred title, subtle play icon.
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
    # Keep all but last word plain; italicise the last word
    plain = escape(" ".join(words[:-1]))
    last = escape(words[-1])
    return f"{plain} <em>{last}</em>"


def render_thumbnail(
    title: str,
    topic: str,
    out_path: Path,
    *,
    frame_path: Path | None = None,
    title_size: int = 108,
) -> Path:
    """Render a thumbnail PNG with optional footage frame as background.

    When `frame_path` is provided the footage still is used as the CSS
    background-image behind the branded overlay (header, title, play icon).
    This gives the thumbnail real visual context while keeping factjot.
    branding legible on top.
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
            omit_background=False,   # solid background — no transparency
            full_page=False,
            clip={"x": 0, "y": 0, "width": REEL_W, "height": REEL_H},
        )
        browser.close()

    print(f"  [thumbnail] rendered {out_path.name}")
    return out_path
