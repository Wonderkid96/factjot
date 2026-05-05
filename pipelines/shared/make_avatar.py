"""Render a 1080x1080 factjot profile picture using the existing brand kit.

Outputs:
    data/avatars/factjot_avatar_mark.png    (single 'f.' mark, primary)
    data/avatars/factjot_avatar_wordmark.png (full wordmark variant)
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from playwright.sync_api import sync_playwright


SIZE = 1080
from src.core.paths import AVATARS as OUTPUT_DIR
FONT_REGULAR = Path("assets/fonts/InstrumentSerif-Regular.ttf")
FONT_ITALIC = Path("assets/fonts/InstrumentSerif-Italic.ttf")


def _data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = {".ttf": "font/ttf", ".otf": "font/otf"}.get(suffix, "application/octet-stream")
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _html(body: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"/>
<style>
  @font-face {{
    font-family: "Instrument Serif";
    src: url("{_data_url(FONT_REGULAR)}") format("truetype");
    font-style: normal; font-weight: 400;
  }}
  @font-face {{
    font-family: "Instrument Serif";
    src: url("{_data_url(FONT_ITALIC)}") format("truetype");
    font-style: italic; font-weight: 400;
  }}
  :root {{
    --paper: #F4F1E9;
    --near-black: #0B0B0C;
    --accent: #E6352A;
    --white: #FFFFFF;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{
    width: {SIZE}px; height: {SIZE}px;
    background: var(--near-black);
    color: var(--white);
    font-family: "Instrument Serif", Georgia, serif;
    -webkit-font-smoothing: antialiased;
    overflow: hidden;
  }}
  .stage {{
    width: {SIZE}px; height: {SIZE}px;
    display: flex; align-items: center; justify-content: center;
    position: relative;
  }}
  /* Subtle radial highlight, centred behind the mark */
  .stage::before {{
    content: "";
    position: absolute; inset: 0;
    background: radial-gradient(circle at 50% 45%, rgba(255,255,255,0.05), transparent 60%);
  }}
  .mark {{
    font-size: 720px;
    line-height: 1;
    letter-spacing: -0.04em;
    position: relative;
    z-index: 1;
  }}
  .mark .glyph {{ font-style: italic; }}
  .mark .dot {{ color: var(--accent); }}

  .wordmark {{
    font-size: 320px;
    line-height: 1;
    letter-spacing: -0.02em;
    position: relative;
    z-index: 1;
  }}
  .wordmark .reg {{ font-style: normal; }}
  .wordmark .ital {{ font-style: italic; }}
  .wordmark .dot {{ color: var(--accent); }}
</style></head>
<body><div class="stage">{body}</div></body></html>
"""


MARK_HTML = _html('<div class="mark"><span class="glyph">f</span><span class="dot">.</span></div>')
WORDMARK_HTML = _html(
    '<div class="wordmark">'
    '<span class="reg">fact</span>'
    '<span class="ital">jot</span>'
    '<span class="dot">.</span>'
    '</div>'
)


def render(html: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": SIZE, "height": SIZE},
                                   device_scale_factor=2)
        page = ctx.new_page()
        page.set_content(html, wait_until="networkidle")
        page.screenshot(path=str(out_path), omit_background=False, full_page=False,
                        clip={"x": 0, "y": 0, "width": SIZE, "height": SIZE})
        browser.close()


def main() -> None:
    render(MARK_HTML, OUTPUT_DIR / "factjot_avatar_mark.png")
    render(WORDMARK_HTML, OUTPUT_DIR / "factjot_avatar_wordmark.png")
    print("Wrote:")
    print(f"  {OUTPUT_DIR / 'factjot_avatar_mark.png'}")
    print(f"  {OUTPUT_DIR / 'factjot_avatar_wordmark.png'}")


if __name__ == "__main__":
    main()
