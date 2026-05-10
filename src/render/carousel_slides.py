"""Carousel slide renderers (cover, content, story-frame).

Owned by `src/render/` because every active carousel renderer is
downstream of these primitives. Before Phase K.4 these lived in
`pipelines/news/ship_news_post.py` as a documented dual-role module
(CLAUDE.md §3): the news CLI was dead but the renderer primitives
were still imported by `pipelines/manual/ship_manual_post.py` and
`tests/test_typography_cover.py`. A renderer change for one path
silently affected the other; the import boundary did not signal that.

Extracting them here makes the boundary explicit:
- `pipelines/manual/ship_manual_post.py` imports from `src/render/`
  the same way every other pipeline does for shared render code.
- The dead news CLI and its news-only helpers are gone.
- Tests live alongside their target (`tests/test_typography_cover.py`).

Layout modes are owned by `src/content/carousel_rules.py`; this module
just renders what the caller chose.

Pure functions:
- `build_cover_html`
- `build_story_frame_html`
- `_render_cover_typography`
- `_render_news_slide_photo` / `_render_news_slide_typography`
- `_render_news_slide_photo_readable` /
  `_render_news_slide_typography_readable`
- `_font_faces` / `_font_faces_readable` / `_logo_tag`
- `_markup_lines` / `_is_empty_photo_url` / `escape_html`
- `_inline_asset` / `_inline_bytes`

Side-effecting (Playwright):
- `render_cover_slide`
- `render_news_slide`
- `render_story_frame`
- `_autosize_readable_text`
"""
from __future__ import annotations

import base64
import re
from pathlib import Path

from src.core.brand import LABEL_FONT_CANONICAL_PATH


# ------------------------------------------------------------------ #
# Module-level helpers
# ------------------------------------------------------------------ #

def _log(msg: str) -> None:
    print(msg, flush=True)


def escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;")
        .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")
    )


def _inline_asset(path: Path) -> str:
    if not path.exists():
        return ""
    mime = {
        ".ttf": "font/ttf", ".otf": "font/otf",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png",
    }.get(path.suffix.lower(), "application/octet-stream")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def _inline_bytes(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


# ------------------------------------------------------------------ #
# Render shared constants
# ------------------------------------------------------------------ #

_GRAIN_SVG = (
    "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='280' height='280'>"
    "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' "
    "stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 0.7 0'/>"
    "</filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>"
)


# ------------------------------------------------------------------ #
# Render helpers
# ------------------------------------------------------------------ #

def _markup_lines(lines: list[str]) -> str:
    """Convert [r]...[/r] markers to accent-red spans; HTML-escape everything else."""
    result = []
    for line in lines:
        parts = re.split(r"(\[r\].*?\[/r\])", line)
        html_parts = []
        for part in parts:
            m = re.match(r"\[r\](.*?)\[/r\]", part)
            if m:
                html_parts.append(f'<span class="red">{escape_html(m.group(1))}</span>')
            else:
                html_parts.append(escape_html(part))
        result.append(f'<div class="line">{"".join(html_parts)}</div>')
    return "\n".join(result)


def _font_faces(serif_url: str, label_url: str, archivo_url: str = "") -> str:
    """v2.1: label_url now points at SpaceGrotesk-Bold.ttf (label_font_canonical).
    The variable name is preserved so callsites stay stable; the @font-face
    declaration registers it as 'Space Grotesk' weight 700, matching the
    template-side rename. JetBrains Mono is no longer in this declaration."""
    archivo = ""
    if archivo_url:
        archivo = (
            f'@font-face{{font-family:"Archivo Black";src:url("{archivo_url}") '
            f'format("truetype");font-weight:900;font-style:normal;}}'
        )
    return f"""
    @font-face{{font-family:"Instrument Serif";src:url("{serif_url}") format("truetype");font-weight:400;font-style:normal;}}
    @font-face{{font-family:"Instrument Serif";src:url("{serif_url}") format("truetype");font-weight:400;font-style:italic;}}
    @font-face{{font-family:"Space Grotesk";src:url("{label_url}") format("truetype");font-weight:700;font-style:normal;}}
    {archivo}"""


def _logo_tag(logo_url: str, invert: bool = False) -> str:
    if logo_url:
        filt = "brightness(0) invert(1)" if invert else ""
        return f'<img class="wordmark-img" src="{logo_url}" alt="factjot" style="filter:{filt};"/>'
    return '<span class="wm-text">factjot.</span>'


# ------------------------------------------------------------------ #
# Cover slide -- matches production carousel style
# (full-bleed photo, gradient overlay, large title bottom)
# ------------------------------------------------------------------ #

def _is_empty_photo_url(photo_data_url: str) -> bool:
    """True when the photo data URL is missing or carries zero bytes.

    The cover renderer must branch on this rather than templating an
    empty string into a `background:url("")` declaration. Per
    `SPEC_IMAGE_PIPELINE.md` §13: an empty string for image data must
    not silently become an empty photo box.
    """
    s = (photo_data_url or "").strip()
    if not s:
        return True
    # data: URL with nothing after the comma (e.g. "data:image/png;base64,")
    if s.lower().startswith("data:"):
        comma = s.find(",")
        if comma < 0:
            return True
        if not s[comma + 1 :].strip():
            return True
    return False


def render_cover_slide(
    cover_title: str,
    source_label: str,
    photo_data_url: str,
    out_path: Path,
    index: int,
    total: int,
    repo_root: Path,
    browser,
    layout_mode: str = "compact_legacy",
) -> None:
    """Render the cover slide.

    layout_mode:
        compact_legacy (default) - existing photo-bearing cover, byte-
            identical to prior behaviour when ``photo_data_url`` is set.
        readable_list - same photo-bearing layout for list cover; the
            typography fallback uses a PAPER background to give visual
            contrast against dark photo covers in the same feed.

    When ``photo_data_url`` is empty (or carries zero bytes) the
    renderer branches to a typography-only variant per
    `SPEC_IMAGE_PIPELINE.md` §11/§12: a deliberate full-canvas
    typography layout with title, label pill, red accent rule and
    wordmark. Never an empty `background:url("")`.
    """
    html = build_cover_html(
        cover_title=cover_title,
        source_label=source_label,
        photo_data_url=photo_data_url,
        index=index,
        total=total,
        repo_root=repo_root,
        layout_mode=layout_mode,
    )
    page = browser.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=2)
    page.set_content(html, wait_until="networkidle")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out_path), full_page=False, clip={"x": 0, "y": 0, "width": 1080, "height": 1350})
    page.close()


def build_cover_html(
    cover_title: str,
    source_label: str,
    photo_data_url: str,
    index: int,
    total: int,
    repo_root: Path,
    layout_mode: str = "compact_legacy",
) -> str:
    """Build the cover slide HTML. Pure function, no browser side-effects.

    Branches:
      - photo_data_url empty/zero-bytes -> typography variant (per
        ``layout_mode``); INK background for ``compact_legacy``,
        PAPER for ``readable_list``.
      - photo_data_url present -> existing photo-bearing template.
    """
    logo_url    = _inline_asset(repo_root / "assets/logo/factjot_mark.png")
    serif_url   = _inline_asset(repo_root / "assets/fonts/InstrumentSerif-Regular.ttf")
    # v2.1: Space Grotesk Bold replaces JetBrains Mono Bold for labels.
    # Sourced from brand.py rather than a string literal so a font-file
    # rename in `assets/fonts/` (or a brand-kit migration) propagates here
    # without leaving this file pointing at a missing path. `_inline_asset`
    # accepts a Path, returns "" silently on missing file -- the import
    # makes the source of truth explicit.
    label_url   = _inline_asset(LABEL_FONT_CANONICAL_PATH)
    archivo_url = _inline_asset(repo_root / "assets/fonts/ArchivoBlack-Regular.ttf")

    # Default to "factjot" if the title is missing entirely so the
    # typography variant never renders as a blank pane.
    cover_title_in = (cover_title or "").strip().rstrip(".") or "factjot"
    pill = (source_label or "").upper()[:32] or "FACTJOT"

    if _is_empty_photo_url(photo_data_url):
        return _render_cover_typography(
            cover_title=cover_title_in,
            pill=pill,
            index=index,
            total=total,
            logo_url=logo_url,
            serif_url=serif_url,
            label_url=label_url,
            archivo_url=archivo_url,
            layout_mode=layout_mode,
        )

    index_label = f"{index}/{total}"
    logo = _logo_tag(logo_url, invert=True)

    # Size title dynamically. Archivo Black is heavier than Instrument Serif at
    # the same px, so the scale is shifted down to roughly match perceived size.
    chars = len(cover_title_in)
    if chars <= 20:
        title_size, title_lh = 100, 0.96
    elif chars <= 35:
        title_size, title_lh = 82, 0.98
    else:
        title_size, title_lh = 64, 1.04

    return f"""<!doctype html><html><head><meta charset="utf-8"/><style>
    {_font_faces(serif_url, label_url, archivo_url)}
    :root{{--near-black:#0B0B0C;--off-white:#EDE8DD;--accent:#E6352A;--white:#FFFFFF;--muted:#9A938A;}}
    *{{box-sizing:border-box;margin:0;padding:0;}}
    html,body{{width:1080px;height:1350px;overflow:hidden;background:var(--near-black);-webkit-font-smoothing:antialiased;}}
    .stage{{position:relative;width:1080px;height:1350px;overflow:hidden;isolation:isolate;}}
    .photo{{position:absolute;inset:0;background:url("{photo_data_url}") center/cover no-repeat;z-index:0;}}
    .top-darken{{position:absolute;inset:0 0 auto 0;height:22%;background:linear-gradient(to bottom,rgba(0,0,0,0.62),rgba(0,0,0,0));z-index:1;}}
    .bottom-darken{{position:absolute;inset:28% 0 0 0;background:linear-gradient(to bottom,rgba(11,11,12,0) 0%,rgba(11,11,12,0.55) 30%,rgba(11,11,12,0.95) 62%,rgba(11,11,12,0.99) 100%);z-index:1;}}
    .vignette{{position:absolute;inset:0;background:radial-gradient(ellipse at center,rgba(0,0,0,0) 68%,rgba(0,0,0,0.28) 100%);z-index:2;pointer-events:none;}}
    .grain{{position:absolute;inset:0;z-index:3;opacity:0.055;mix-blend-mode:overlay;background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='280' height='280'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 0.7 0'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>");pointer-events:none;}}
    .frame{{position:absolute;inset:0;z-index:10;padding:58px 72px 74px 72px;display:flex;flex-direction:column;justify-content:space-between;}}
    .top-row{{display:flex;align-items:center;gap:20px;font-family:"Space Grotesk",system-ui,sans-serif;font-size:20px;font-weight:700;letter-spacing:0.16em;color:var(--off-white);text-transform:uppercase;text-shadow:1px 1px 0 rgba(0,0,0,0.55);}}
    .wordmark-img{{height:36px;width:auto;display:block;opacity:0.95;filter:drop-shadow(1px 1px 0 rgba(0,0,0,0.45));}}
    .top-divider{{flex:1;height:1px;background:var(--off-white);opacity:0.32;}}
    .index{{opacity:0.72;}}
    .lower{{display:flex;flex-direction:column;gap:22px;}}
    .pill{{align-self:flex-start;background:var(--accent);color:var(--white);font-family:"Space Grotesk",system-ui,sans-serif;font-weight:700;font-size:17px;letter-spacing:0.26em;padding:7px 16px 9px;border-radius:999px;text-transform:uppercase;line-height:1;}}
    .title{{font-family:"Archivo Black","Inter",system-ui,sans-serif;font-weight:900;font-size:{title_size}px;line-height:{title_lh};letter-spacing:-0.01em;text-transform:lowercase;color:var(--off-white);text-shadow:2px 2px 0 rgba(0,0,0,0.55);text-wrap:balance;}}
    .title::after{{content:".";color:var(--accent);font-family:"Archivo Black","Inter",system-ui,sans-serif;text-transform:none;}}
    </style></head><body>
    <div class="stage">
      <div class="photo"></div>
      <div class="top-darken"></div><div class="bottom-darken"></div>
      <div class="vignette"></div><div class="grain"></div>
      <div class="frame">
        <div class="top-row">
          {logo}
          <span class="top-divider"></span>
          <span class="index">{index_label}</span>
        </div>
        <div class="lower">
          <span class="pill">{escape_html(pill)}</span>
          <div class="title">{escape_html(cover_title_in)}</div>
        </div>
      </div>
    </div></body></html>"""


def _render_cover_typography(
    cover_title: str,
    pill: str,
    index: int,
    total: int,
    logo_url: str,
    serif_url: str,
    label_url: str,
    archivo_url: str,
    layout_mode: str,
) -> str:
    """Typography-only cover slide. No photo zone.

    Two palette variants chosen by ``layout_mode``:
      - compact_legacy: INK (#0A0A0A) ground, off-white type, white wordmark.
      - readable_list: PAPER (#F4F1E9) ground, INK type, dark wordmark.

    Common elements:
      - factjot wordmark + index pill on the top row.
      - Label pill (Space Grotesk Bold 700, uppercase, 0.08em tracking).
      - Instrument Serif Regular full-canvas title, balanced and centred,
        with bias toward the upper-third per the brief.
      - Red accent rule (4px x 120px in #E6352A) below the title.
      - Subtle grain overlay carried over from the typography content slide
        for visual continuity.

    Sized to read as deliberate, not as a broken render.
    """
    is_paper = layout_mode == "readable_list"
    bg          = "#F4F1E9" if is_paper else "#0A0A0A"
    ink         = "#0A0A0A" if is_paper else "#EDE8DD"
    pill_border = "rgba(10,10,10,0.85)" if is_paper else "rgba(237,232,221,0.85)"
    grain_blend = "multiply" if is_paper else "overlay"
    grain_op    = 0.045 if is_paper else 0.055

    # The factjot mark asset is white on transparent. On INK we keep it
    # white (no filter); on PAPER we flatten to black via brightness(0).
    if is_paper:
        logo_filter = "brightness(0)"
    else:
        logo_filter = ""
    if logo_url:
        logo = (
            f'<img class="wordmark-img" src="{logo_url}" alt="factjot" '
            f'style="filter:{logo_filter};"/>'
        )
    else:
        logo = '<span class="wm-text">factjot.</span>'

    chars = len(cover_title)
    # Slightly smaller scale for readable_list so the serif holds against
    # the lighter ground without going chunky.
    if is_paper:
        if chars <= 18:
            title_size, title_lh = 104, 1.00
        elif chars <= 32:
            title_size, title_lh = 92, 1.02
        elif chars <= 56:
            title_size, title_lh = 76, 1.06
        else:
            title_size, title_lh = 60, 1.10
    else:
        if chars <= 18:
            title_size, title_lh = 120, 1.00
        elif chars <= 32:
            title_size, title_lh = 104, 1.02
        elif chars <= 56:
            title_size, title_lh = 84, 1.06
        else:
            title_size, title_lh = 68, 1.10

    index_label = f"{index}/{total}"
    pill_html = escape_html(pill)
    title_html = escape_html(cover_title)

    return f"""<!doctype html><html><head><meta charset="utf-8"/><style>
    {_font_faces(serif_url, label_url, archivo_url)}
    :root{{--ink:{ink};--bg:{bg};--accent:#E6352A;--pill-border:{pill_border};}}
    *{{box-sizing:border-box;margin:0;padding:0;}}
    html,body{{width:1080px;height:1350px;overflow:hidden;background:var(--bg);color:var(--ink);-webkit-font-smoothing:antialiased;}}
    .stage{{position:relative;width:1080px;height:1350px;overflow:hidden;background:var(--bg);}}
    .grain{{position:absolute;inset:0;z-index:1;opacity:{grain_op};mix-blend-mode:{grain_blend};background-image:url("{_GRAIN_SVG}");pointer-events:none;}}
    .frame{{position:absolute;inset:0;z-index:10;padding:58px 84px 74px 84px;display:flex;flex-direction:column;}}
    .top-row{{display:flex;align-items:center;gap:20px;flex-shrink:0;}}
    .wordmark-img{{height:36px;width:auto;display:block;opacity:0.95;flex-shrink:0;}}
    .top-divider{{flex:1;height:1px;background:var(--ink);opacity:0.28;}}
    .index{{font-family:"Space Grotesk",system-ui,sans-serif;font-weight:700;font-size:22px;letter-spacing:0.04em;line-height:1;flex-shrink:0;color:var(--ink);opacity:0.78;}}
    .title-block{{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-start;padding-top:120px;gap:36px;text-align:center;}}
    .pill{{align-self:center;background:transparent;color:var(--ink);font-family:"Space Grotesk",system-ui,sans-serif;font-weight:700;font-size:17px;letter-spacing:0.08em;padding:9px 22px 11px;border:1.5px solid var(--pill-border);border-radius:999px;text-transform:uppercase;line-height:1;}}
    .title{{font-family:"Instrument Serif",Georgia,serif;font-weight:400;font-size:{title_size}px;line-height:{title_lh};letter-spacing:-0.005em;color:var(--ink);text-wrap:balance;max-width:920px;}}
    .title::after{{content:".";color:var(--accent);font-family:"Instrument Serif",Georgia,serif;}}
    .accent-rule{{width:120px;height:4px;background:var(--accent);margin-top:8px;}}
    </style></head><body>
    <div class="stage">
      <div class="grain"></div>
      <div class="frame">
        <div class="top-row">{logo}<span class="top-divider"></span><span class="index">{index_label}</span></div>
        <div class="title-block">
          <span class="pill">{pill_html}</span>
          <div class="title">{title_html}</div>
          <div class="accent-rule"></div>
        </div>
      </div>
    </div></body></html>"""


# ------------------------------------------------------------------ #
# Story frame -- 1080x1920 9:16 wrapper around the cover slide.
# Blurred cover as full-bleed bg, cover slide itself as a centred card.
# ------------------------------------------------------------------ #

def render_story_frame(
    cover_path: Path,
    out_path: Path,
    repo_root: Path,
    browser,
    layout_mode: str = "compact_legacy",
    typography_cover: bool = False,
) -> None:
    """Render a 1080x1920 story frame wrapping the carousel cover slide.

    Story image = the cover slide composited inside a 9:16 frame with the
    factjot wordmark + NEW POST pill above it, and the same cover blurred
    behind. Matches the reel story's design language.

    layout_mode and typography_cover only affect the background palette
    when the cover is the typography variant (no photo). In that case
    blurring an INK or PAPER ground produces a flat scrim with no detail,
    so we replace the blurred photo with the brand ground for the
    matching layout. The slide card itself is always the cover PNG.
    """
    cover_url   = _inline_asset(cover_path)
    serif_url   = _inline_asset(repo_root / "assets/fonts/InstrumentSerif-Regular.ttf")
    # v2.1: Space Grotesk Bold replaces JetBrains Mono Bold for labels.
    # Sourced from brand.py rather than a string literal so a font-file
    # rename in `assets/fonts/` (or a brand-kit migration) propagates here
    # without leaving this file pointing at a missing path. `_inline_asset`
    # accepts a Path, returns "" silently on missing file -- the import
    # makes the source of truth explicit.
    label_url   = _inline_asset(LABEL_FONT_CANONICAL_PATH)

    html = build_story_frame_html(
        cover_url=cover_url,
        serif_url=serif_url,
        label_url=label_url,
        layout_mode=layout_mode,
        typography_cover=typography_cover,
    )

    page = browser.new_page(viewport={"width": 1080, "height": 1920}, device_scale_factor=2)
    page.set_content(html, wait_until="networkidle")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out_path), full_page=False, clip={"x": 0, "y": 0, "width": 1080, "height": 1920})
    page.close()


def build_story_frame_html(
    cover_url: str,
    serif_url: str,
    label_url: str,
    layout_mode: str = "compact_legacy",
    typography_cover: bool = False,
) -> str:
    """Build the story frame HTML. Pure function.

    For photo covers the background is the cover blurred and dimmed.
    For typography covers the background is the brand ground for the
    matching ``layout_mode`` (PAPER for readable_list, INK otherwise),
    so the story does not show a flat blurred swatch.
    """
    paper_typography = typography_cover and layout_mode == "readable_list"
    if paper_typography:
        bg_layer = (
            ".bg-flat{position:absolute;inset:0;background:#F4F1E9;z-index:0;}"
            ".bg-overlay{position:absolute;inset:0;background:rgba(244,241,233,0.0);z-index:1;}"
        )
        bg_dom = '<div class="bg-flat"></div><div class="bg-overlay"></div>'
        wordmark_color = "var(--ink)"
        body_bg = "#F4F1E9"
    elif typography_cover:
        bg_layer = (
            ".bg-flat{position:absolute;inset:0;background:#0A0A0A;z-index:0;}"
            ".bg-overlay{position:absolute;inset:0;background:rgba(11,11,12,0.0);z-index:1;}"
        )
        bg_dom = '<div class="bg-flat"></div><div class="bg-overlay"></div>'
        wordmark_color = "var(--off-white)"
        body_bg = "#0B0B0C"
    else:
        bg_layer = (
            f'.bg-blur{{position:absolute;inset:0;background:url("{cover_url}") center/cover no-repeat;'
            "filter:blur(28px) saturate(0.7) brightness(0.45);transform:scale(1.12);z-index:0;}"
            ".bg-overlay{position:absolute;inset:0;background:rgba(11,11,12,0.62);z-index:1;}"
        )
        bg_dom = '<div class="bg-blur"></div><div class="bg-overlay"></div>'
        wordmark_color = "var(--off-white)"
        body_bg = "#0B0B0C"

    return f"""<!doctype html><html><head><meta charset="utf-8"/><style>
    {_font_faces(serif_url, label_url, "")}
    :root{{--near-black:#0B0B0C;--off-white:#EDE8DD;--accent:#E6352A;--white:#FFFFFF;--ink:#0A0A0A;}}
    *{{box-sizing:border-box;margin:0;padding:0;}}
    html,body{{width:1080px;height:1920px;overflow:hidden;background:{body_bg};color:var(--white);font-family:"Instrument Serif",Georgia,serif;-webkit-font-smoothing:antialiased;}}
    {bg_layer}
    .grain{{position:absolute;inset:0;z-index:5;opacity:0.06;mix-blend-mode:overlay;background-image:url("{_GRAIN_SVG}");pointer-events:none;}}
    .frame{{position:absolute;inset:0;z-index:10;padding:280px 60px 280px 60px;display:flex;flex-direction:column;justify-content:flex-start;align-items:center;gap:32px;}}
    .header{{width:880px;align-self:center;display:flex;align-items:center;justify-content:space-between;flex:0 0 auto;}}
    .wordmark{{font-family:"Instrument Serif",Georgia,serif;font-weight:400;font-size:52px;letter-spacing:-0.01em;line-height:1;color:{wordmark_color};text-shadow:1px 1px 0 rgba(0,0,0,0.45);}}
    .wordmark .ital{{font-style:italic;}}
    .wordmark .dot{{color:var(--accent);}}
    .new-post-badge{{background:var(--accent);color:var(--off-white);font-family:"Space Grotesk",system-ui,sans-serif;font-weight:700;font-size:22px;letter-spacing:0.24em;padding:12px 22px 14px;border-radius:9999px;text-transform:uppercase;line-height:1;}}
    .card-wrapper{{width:100%;display:flex;justify-content:center;align-items:flex-start;flex:1 1 auto;}}
    .slide-card{{width:880px;aspect-ratio:4 / 5;border-radius:24px;overflow:hidden;box-shadow:0 32px 80px rgba(0,0,0,0.65),0 6px 20px rgba(0,0,0,0.45);border:1px solid rgba(255,255,255,0.10);position:relative;}}
    .slide-card img{{width:100%;height:100%;object-fit:cover;display:block;}}
    </style></head><body>
    {bg_dom}
    <div class="grain"></div>
    <div class="frame">
      <div class="header">
        <span class="wordmark">fact<span class="ital">jot</span><span class="dot">.</span></span>
        <div class="new-post-badge">NEW POST</div>
      </div>
      <div class="card-wrapper">
        <div class="slide-card">
          <img src="{cover_url}" alt=""/>
        </div>
      </div>
    </div>
    </body></html>"""


# ------------------------------------------------------------------ #
# Content slides -- black background, white text, red key words
# ------------------------------------------------------------------ #

def render_news_slide(
    lines: list[str],
    photo_data_url: str,
    out_path: Path,
    index: int,
    total: int,
    source_label: str,
    repo_root: Path,
    browser,
    layout_mode: str = "compact_legacy",
) -> None:
    """Render a content slide.

    layout_mode:
        compact_legacy (default) - existing Archivo Black 900 anchored
            bottom-left layout. Byte-identical to prior behaviour.
        readable_list - Space Grotesk SemiBold body inside a half-box
            flexbox container at the bottom 50% of the canvas, with
            renderer-side font auto-fit (64 -> 28 px walk).
    """
    logo_url    = _inline_asset(repo_root / "assets/logo/factjot_mark.png")
    serif_url   = _inline_asset(repo_root / "assets/fonts/InstrumentSerif-Regular.ttf")
    # v2.1: Space Grotesk Bold replaces JetBrains Mono Bold for labels.
    # Sourced from brand.py rather than a string literal so a font-file
    # rename in `assets/fonts/` (or a brand-kit migration) propagates here
    # without leaving this file pointing at a missing path. `_inline_asset`
    # accepts a Path, returns "" silently on missing file -- the import
    # makes the source of truth explicit.
    label_url   = _inline_asset(LABEL_FONT_CANONICAL_PATH)
    archivo_url = _inline_asset(repo_root / "assets/fonts/ArchivoBlack-Regular.ttf")

    index_label = f"{index}/{total}"
    logo = _logo_tag(logo_url, invert=True)
    lines_html = _markup_lines(lines)

    if layout_mode == "readable_list":
        grotesk_url = _inline_asset(repo_root / "assets/fonts/SpaceGrotesk-SemiBold.ttf")
        if photo_data_url:
            html = _render_news_slide_photo_readable(
                serif_url, label_url, grotesk_url, logo, index_label, lines_html, photo_data_url,
            )
        else:
            html = _render_news_slide_typography_readable(
                serif_url, label_url, grotesk_url, logo, index_label, lines_html,
            )
    else:
        if photo_data_url:
            html = _render_news_slide_photo(
                serif_url, label_url, archivo_url, logo, index_label, lines_html, photo_data_url,
            )
        else:
            html = _render_news_slide_typography(
                serif_url, label_url, archivo_url, logo, index_label, lines_html,
            )

    page = browser.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=2)
    page.set_content(html, wait_until="networkidle")

    # readable_list: walk font-size 64 -> 28 px and pick the largest
    # that fits the half-box container. compact_legacy uses fixed sizes.
    if layout_mode == "readable_list":
        _autosize_readable_text(page)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out_path), full_page=False, clip={"x": 0, "y": 0, "width": 1080, "height": 1350})
    page.close()


def _render_news_slide_photo(
    serif_url: str, label_url: str, archivo_url: str, logo: str, index_label: str,
    lines_html: str, photo_data_url: str,
) -> str:
    """Full-bleed content slide. Photo fills the canvas; text sits over a bottom gradient.

    Body lines are Archivo Black 900 lowercase (v2 brand). Sizes and line-height
    are tuned for AB's heavier weight: ~17% smaller px and 14% tighter leading
    than the previous Instrument Serif setup.
    """
    return f"""<!doctype html><html><head><meta charset="utf-8"/><style>
    {_font_faces(serif_url, label_url, archivo_url)}
    :root{{--near-black:#0B0B0C;--off-white:#EDE8DD;--accent:#E6352A;--white:#FFFFFF;}}
    *{{box-sizing:border-box;margin:0;padding:0;}}
    html,body{{width:1080px;height:1350px;overflow:hidden;background:var(--near-black);-webkit-font-smoothing:antialiased;}}
    .stage{{position:relative;width:1080px;height:1350px;overflow:hidden;isolation:isolate;}}
    .photo{{position:absolute;inset:0;background:url("{photo_data_url}") center/cover no-repeat;z-index:0;}}
    .top-darken{{position:absolute;inset:0 0 auto 0;height:28%;background:linear-gradient(to bottom,rgba(0,0,0,0.72),rgba(0,0,0,0));z-index:1;}}
    .bottom-darken{{position:absolute;inset:30% 0 0 0;background:linear-gradient(to bottom,rgba(11,11,12,0) 0%,rgba(11,11,12,0.60) 35%,rgba(11,11,12,0.95) 62%,rgba(11,11,12,0.99) 100%);z-index:1;}}
    .vignette{{position:absolute;inset:0;background:radial-gradient(ellipse at center,rgba(0,0,0,0) 65%,rgba(0,0,0,0.30) 100%);z-index:2;pointer-events:none;}}
    .grain{{position:absolute;inset:0;z-index:3;opacity:0.055;mix-blend-mode:overlay;background-image:url("{_GRAIN_SVG}");pointer-events:none;}}
    .frame{{position:absolute;inset:0;z-index:10;padding:62px 70px 74px 70px;display:flex;flex-direction:column;justify-content:space-between;}}
    .top-row{{display:flex;align-items:center;gap:20px;}}
    .wordmark-img{{height:28px;width:auto;display:block;opacity:0.95;flex-shrink:0;filter:drop-shadow(1px 1px 0 rgba(0,0,0,0.45));}}
    .top-divider{{flex:1;height:1px;background:var(--off-white);opacity:0.32;}}
    .index{{background:rgba(255,255,255,0.12);color:var(--off-white);font-family:"Space Grotesk",system-ui,sans-serif;font-weight:700;font-size:24px;letter-spacing:0.04em;padding:8px 18px 10px;border-radius:999px;line-height:1;flex-shrink:0;}}
    .lines{{display:flex;flex-direction:column;gap:8px;}}
    .line{{font-family:"Archivo Black","Inter",system-ui,sans-serif;font-weight:900;font-size:48px;line-height:1.08;letter-spacing:-0.01em;text-transform:lowercase;color:var(--off-white);text-shadow:2px 2px 0 rgba(0,0,0,0.55);}}
    .line .red{{color:var(--accent);font-weight:900;}}
    </style></head><body>
    <div class="stage">
      <div class="photo"></div>
      <div class="top-darken"></div>
      <div class="bottom-darken"></div>
      <div class="vignette"></div>
      <div class="grain"></div>
      <div class="frame">
        <div class="top-row">{logo}<span class="top-divider"></span><div class="index">{index_label}</div></div>
        <div class="lines">{lines_html}</div>
      </div>
    </div></body></html>"""


def _render_news_slide_typography(
    serif_url: str, label_url: str, archivo_url: str, logo: str, index_label: str, lines_html: str,
) -> str:
    """Intentional full-height typography-only slide. No photo zone. Looks deliberate.

    Lines are Archivo Black 900 lowercase, sized down for AB's heavier weight
    and tightened leading.
    """
    return f"""<!doctype html><html><head><meta charset="utf-8"/><style>
    {_font_faces(serif_url, label_url, archivo_url)}
    :root{{--near-black:#0B0B0C;--off-white:#EDE8DD;--accent:#E6352A;--white:#FFFFFF;}}
    *{{box-sizing:border-box;margin:0;padding:0;}}
    html,body{{width:1080px;height:1350px;overflow:hidden;background:var(--near-black);-webkit-font-smoothing:antialiased;}}
    .stage{{position:relative;width:1080px;height:1350px;overflow:hidden;background:var(--near-black);}}
    .accent-line{{position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--accent);z-index:2;}}
    .grain{{position:absolute;inset:0;z-index:1;opacity:0.055;mix-blend-mode:overlay;
            background-image:url("{_GRAIN_SVG}");pointer-events:none;}}
    .frame{{position:absolute;inset:0;z-index:10;padding:62px 70px 62px 86px;
            display:flex;flex-direction:column;}}
    .top-row{{display:flex;align-items:center;gap:20px;flex-shrink:0;margin-bottom:0;}}
    .wordmark-img{{height:28px;width:auto;display:block;opacity:0.88;flex-shrink:0;}}
    .top-divider{{flex:1;height:1px;background:var(--off-white);opacity:0.32;}}
    .index{{background:rgba(255,255,255,0.1);color:var(--off-white);font-family:"Space Grotesk",system-ui,sans-serif;
            font-weight:700;font-size:24px;letter-spacing:0.04em;padding:8px 18px 10px;border-radius:999px;line-height:1;flex-shrink:0;}}
    .lines-wrap{{flex:1;display:flex;flex-direction:column;justify-content:center;padding-right:20px;}}
    .lines{{display:flex;flex-direction:column;gap:10px;}}
    .line{{font-family:"Archivo Black","Inter",system-ui,sans-serif;font-weight:900;font-size:42px;line-height:1.10;
           letter-spacing:-0.01em;text-transform:lowercase;color:var(--off-white);}}
    .line .red{{color:var(--accent);font-weight:900;}}
    </style></head><body>
    <div class="stage">
      <div class="accent-line"></div>
      <div class="grain"></div>
      <div class="frame">
        <div class="top-row">{logo}<span class="top-divider"></span><div class="index">{index_label}</div></div>
        <div class="lines-wrap">
          <div class="lines">{lines_html}</div>
        </div>
      </div>
    </div></body></html>"""


# ------------------------------------------------------------------ #
# readable_list layout (Space Grotesk SemiBold + half-box + autosize)
# ------------------------------------------------------------------ #
# Opt-in via layout_mode="readable_list" on render_news_slide. Only the
# list slot picks this by default today; fact and news continue to use
# the compact_legacy templates above unchanged.

def _font_faces_readable(serif_url: str, label_url: str, grotesk_url: str) -> str:
    """v2.1: label_url points at SpaceGrotesk-Bold.ttf; both label-bold (700)
    and body-semibold (600) Space Grotesk weights are registered so the
    readable_list layout has access to both in the same family."""
    return f"""
    @font-face{{font-family:"Instrument Serif";src:url("{serif_url}") format("truetype");font-weight:400;font-style:normal;}}
    @font-face{{font-family:"Space Grotesk";src:url("{label_url}") format("truetype");font-weight:700;font-style:normal;}}
    @font-face{{font-family:"Space Grotesk";src:url("{grotesk_url}") format("truetype");font-weight:600;font-style:normal;}}"""


def _render_news_slide_photo_readable(
    serif_url: str, label_url: str, grotesk_url: str, logo: str, index_label: str,
    lines_html: str, photo_data_url: str,
) -> str:
    """Photo slide, readable_list layout. Body text in Space Grotesk
    SemiBold, sized by JS auto-fit to occupy the bottom 50% of the
    canvas. Top half is the photo (full bleed) with a gradient scrim
    that protects legibility at the text baseline."""
    return f"""<!doctype html><html><head><meta charset="utf-8"/><style>
    {_font_faces_readable(serif_url, label_url, grotesk_url)}
    :root{{--near-black:#0B0B0C;--off-white:#EDE8DD;--accent:#E6352A;--white:#FFFFFF;--body-size:64px;}}
    *{{box-sizing:border-box;margin:0;padding:0;}}
    html,body{{width:1080px;height:1350px;overflow:hidden;background:var(--near-black);-webkit-font-smoothing:antialiased;}}
    .stage{{position:relative;width:1080px;height:1350px;overflow:hidden;isolation:isolate;}}
    .photo{{position:absolute;inset:0;background:url("{photo_data_url}") center/cover no-repeat;z-index:0;}}
    .top-darken{{position:absolute;inset:0 0 auto 0;height:24%;background:linear-gradient(to bottom,rgba(0,0,0,0.65),rgba(0,0,0,0));z-index:1;}}
    .bottom-darken{{position:absolute;inset:42% 0 0 0;background:linear-gradient(to bottom,rgba(11,11,12,0) 0%,rgba(11,11,12,0.65) 35%,rgba(11,11,12,0.95) 60%,rgba(11,11,12,0.99) 100%);z-index:1;}}
    .vignette{{position:absolute;inset:0;background:radial-gradient(ellipse at center,rgba(0,0,0,0) 65%,rgba(0,0,0,0.30) 100%);z-index:2;pointer-events:none;}}
    .grain{{position:absolute;inset:0;z-index:3;opacity:0.055;mix-blend-mode:overlay;background-image:url("{_GRAIN_SVG}");pointer-events:none;}}
    .top-row{{position:absolute;top:0;left:0;right:0;z-index:10;display:flex;align-items:center;gap:20px;padding:62px 70px 0 70px;}}
    .wordmark-img{{height:28px;width:auto;display:block;opacity:0.95;flex-shrink:0;filter:drop-shadow(1px 1px 0 rgba(0,0,0,0.45));}}
    .top-divider{{flex:1;height:1px;background:var(--off-white);opacity:0.32;}}
    .index{{background:rgba(255,255,255,0.12);color:var(--off-white);font-family:"Space Grotesk",system-ui,sans-serif;font-weight:700;font-size:24px;letter-spacing:0.04em;padding:8px 18px 10px;border-radius:999px;line-height:1;flex-shrink:0;}}
    .lines-wrap{{position:absolute;left:0;right:0;bottom:0;height:50%;z-index:10;padding:0 70px 78px 70px;display:flex;flex-direction:column;justify-content:flex-end;}}
    .lines{{display:flex;flex-direction:column;gap:0.16em;font-size:var(--body-size);}}
    .line{{font-family:"Space Grotesk","Inter",system-ui,sans-serif;font-weight:600;font-size:1em;line-height:1.18;letter-spacing:-0.01em;color:var(--off-white);text-shadow:2px 2px 0 rgba(0,0,0,0.55);text-wrap:balance;}}
    .line .red{{color:var(--accent);font-weight:700;}}
    </style></head><body>
    <div class="stage">
      <div class="photo"></div>
      <div class="top-darken"></div>
      <div class="bottom-darken"></div>
      <div class="vignette"></div>
      <div class="grain"></div>
      <div class="top-row">{logo}<span class="top-divider"></span><div class="index">{index_label}</div></div>
      <div class="lines-wrap"><div class="lines">{lines_html}</div></div>
    </div></body></html>"""


def _render_news_slide_typography_readable(
    serif_url: str, label_url: str, grotesk_url: str, logo: str, index_label: str,
    lines_html: str,
) -> str:
    """Typography-only slide, readable_list layout. Same half-box as
    the photo variant but on the dark brand background, with the red
    accent rule running down the left edge (kept from compact_legacy
    for visual continuity)."""
    return f"""<!doctype html><html><head><meta charset="utf-8"/><style>
    {_font_faces_readable(serif_url, label_url, grotesk_url)}
    :root{{--near-black:#0B0B0C;--off-white:#EDE8DD;--accent:#E6352A;--white:#FFFFFF;--body-size:64px;}}
    *{{box-sizing:border-box;margin:0;padding:0;}}
    html,body{{width:1080px;height:1350px;overflow:hidden;background:var(--near-black);-webkit-font-smoothing:antialiased;}}
    .stage{{position:relative;width:1080px;height:1350px;overflow:hidden;background:var(--near-black);}}
    .accent-line{{position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--accent);z-index:2;}}
    .grain{{position:absolute;inset:0;z-index:1;opacity:0.055;mix-blend-mode:overlay;background-image:url("{_GRAIN_SVG}");pointer-events:none;}}
    .top-row{{position:absolute;top:0;left:0;right:0;z-index:10;display:flex;align-items:center;gap:20px;padding:62px 70px 0 86px;}}
    .wordmark-img{{height:28px;width:auto;display:block;opacity:0.88;flex-shrink:0;}}
    .top-divider{{flex:1;height:1px;background:var(--off-white);opacity:0.32;}}
    .index{{background:rgba(255,255,255,0.10);color:var(--off-white);font-family:"Space Grotesk",system-ui,sans-serif;font-weight:700;font-size:24px;letter-spacing:0.04em;padding:8px 18px 10px;border-radius:999px;line-height:1;flex-shrink:0;}}
    .lines-wrap{{position:absolute;left:0;right:0;bottom:0;height:50%;z-index:10;padding:0 70px 78px 86px;display:flex;flex-direction:column;justify-content:center;}}
    .lines{{display:flex;flex-direction:column;gap:0.16em;font-size:var(--body-size);}}
    .line{{font-family:"Space Grotesk","Inter",system-ui,sans-serif;font-weight:600;font-size:1em;line-height:1.18;letter-spacing:-0.01em;color:var(--off-white);text-wrap:balance;}}
    .line .red{{color:var(--accent);font-weight:700;}}
    </style></head><body>
    <div class="stage">
      <div class="accent-line"></div>
      <div class="grain"></div>
      <div class="top-row">{logo}<span class="top-divider"></span><div class="index">{index_label}</div></div>
      <div class="lines-wrap"><div class="lines">{lines_html}</div></div>
    </div></body></html>"""


_AUTOSIZE_JS = """
(() => {
  const wrap  = document.querySelector('.lines-wrap');
  const lines = document.querySelector('.lines');
  if (!wrap || !lines) return;
  const sizes = [64, 58, 52, 46, 40, 34, 28];
  for (const s of sizes) {
    lines.style.setProperty('font-size', s + 'px');
    // Allow the layout to reflow before measuring.
    void lines.offsetHeight;
    if (lines.scrollHeight <= wrap.clientHeight && lines.scrollWidth <= wrap.clientWidth) {
      lines.dataset.fitted = String(s);
      return;
    }
  }
  lines.style.setProperty('font-size', '28px');
  lines.dataset.fitted = '28';
})();
"""


def _autosize_readable_text(page) -> None:
    """Walk font-size from 64 -> 28 px and apply the largest size that
    keeps `.lines` within the `.lines-wrap` half-box bounds. No-op for
    layouts without `.lines-wrap` (compact_legacy)."""
    try:
        page.evaluate(_AUTOSIZE_JS)
    except Exception as exc:
        # Defensive: never let the autosize fail a render. Surface the
        # exception so a broken Playwright eval is visible in workflow
        # logs (Phase J.2 surface-silent-failures pattern).
        print(f"[carousel_slides] autosize failed: {exc}", flush=True)
