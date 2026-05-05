"""Render the factjot mark on a TRANSPARENT background for inline use on slides.

Outputs:
    assets/logo/factjot_mark.png   (256x256 retina, transparent bg)

The mark is the italic 'f' followed by a red accent period, in Instrument
Serif. Same identity as the IG profile picture but with no background, so
it can sit cleanly in the top-left corner of every slide.
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from playwright.sync_api import sync_playwright

# Full "factjot." wordmark for the top-left of every slide. Rendered tight
# so it scales cleanly down to ~36px tall in the slide top row.
WIDTH = 720
HEIGHT = 220
OUTPUT = Path("assets/logo/factjot_mark.png")
FONT_REGULAR = Path("assets/fonts/InstrumentSerif-Regular.ttf")
FONT_ITALIC = Path("assets/fonts/InstrumentSerif-Italic.ttf")


def _data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = {".ttf": "font/ttf", ".otf": "font/otf"}.get(suffix, "application/octet-stream")
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


HTML = f"""<!doctype html>
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
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{
    width: {WIDTH}px; height: {HEIGHT}px;
    background: transparent;
    color: #FFFFFF;
    font-family: "Instrument Serif", Georgia, serif;
    -webkit-font-smoothing: antialiased;
    overflow: hidden;
  }}
  .stage {{
    width: {WIDTH}px; height: {HEIGHT}px;
    display: flex; align-items: center; justify-content: center;
  }}
  /* Full "factjot." wordmark: 'fact' regular, 'jot' italic, '.' accent red */
  .mark {{
    font-size: 200px;
    line-height: 1;
    letter-spacing: -0.025em;
    white-space: nowrap;
  }}
  .mark .reg {{ font-style: normal; }}
  .mark .ital {{ font-style: italic; }}
  .mark .dot {{ color: #E6352A; font-style: italic; }}
</style></head>
<body><div class="stage"><div class="mark"><span class="reg">fact</span><span class="ital">jot</span><span class="dot">.</span></div></div></body></html>
"""


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": WIDTH, "height": HEIGHT},
                                   device_scale_factor=2)
        page = ctx.new_page()
        page.set_content(HTML, wait_until="networkidle")
        page.screenshot(path=str(OUTPUT), omit_background=True, full_page=False,
                        clip={"x": 0, "y": 0, "width": WIDTH, "height": HEIGHT})
        browser.close()
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
