"""Pillow-based overlay frame renderer for Reels.

Big, bold, kinetic-feeling typography on a 1080x1920 transparent canvas.
Each PNG is overlaid by FFmpeg at a precise time window.

Design rules:
  - Hook text: 3-4 words, takes up roughly half the frame.
  - Subtitles: large two-line max chunks, centred mid-frame.
  - Heavy black stroke + soft drop shadow so text reads on any footage.
  - Numbers/dates render in ACCENT red. Proper nouns in LIME. Body in WHITE.
  - No translucent panels — the stroke does the legibility work.
"""
from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ------------------------------------------------------------------ #
# Brand
# ------------------------------------------------------------------ #
_W, _H = 1080, 1920
_ACCENT = (230, 53, 42, 255)    # E6352A
_LIME   = (200, 219, 69, 255)   # C8DB45
_LILAC  = (196, 169, 208, 255)  # C4A9D0
_WHITE  = (255, 255, 255, 255)

_LABEL_BG = (11, 11, 12, 220)
_FONT_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"


def _font(filename: str, size: int) -> ImageFont.FreeTypeFont:
    path = _FONT_DIR / filename
    if path.exists():
        return ImageFont.truetype(str(path), size)
    for fallback in ("NeuePlak-CondensedBlack.ttf", "Roboto_Condensed-Black.ttf",
                     "HKGrotesk-Black.otf", "Anton-Regular.otf"):
        p = _FONT_DIR / fallback
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


# ------------------------------------------------------------------ #
# Word colour rules
# ------------------------------------------------------------------ #
_NUMBER_RE = re.compile(r"^\$?[\d,]+(?:\.\d+)?(?:%|st|nd|rd|th|s)?$")
_YEAR_RE   = re.compile(r"^(?:18|19|20)\d{2}s?$")

# Common sentence-initial verbs / adverbs that look like proper nouns
# but aren't. Prevents false-positive lime highlighting after a period.
_NOT_PROPER = frozenset({
    "Told", "Said", "Asked", "Called", "Used", "Found", "Made", "Built",
    "Created", "Born", "Died", "Lived", "Killed", "Saved", "Many", "Most",
    "Some", "Few", "When", "Where", "What", "Why", "How", "Then", "Later",
    "Today", "Now", "After", "Before", "Once", "First", "Last", "Soon",
    "Even", "Only", "Still", "Just", "Often", "Eventually",
})


def _word_colour(word: str, position: int) -> tuple:
    stripped = word.strip(".,;:!?\"'()[]")
    if _NUMBER_RE.match(stripped) or _YEAR_RE.match(stripped):
        return _ACCENT
    if (
        position > 0
        and len(stripped) > 2
        and stripped[0].isupper()
        and stripped.isalpha()
        and stripped not in _NOT_PROPER
    ):
        return _LIME
    return _WHITE


# ------------------------------------------------------------------ #
# Public renderers
# ------------------------------------------------------------------ #

def render_category_label(topic: str, out_path: Path) -> Path:
    img = _blank()
    draw = ImageDraw.Draw(img)
    label = topic.upper()
    font = _font("HKGrotesk-Black.otf", 44)
    bbox = draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 36, 18
    rx = (_W - tw) // 2 - pad_x - 14
    ry = 96
    rw, rh = rx + tw + pad_x * 2 + 14, ry + th + pad_y * 2
    _rounded_rect(draw, (rx, ry, rw, rh), _LABEL_BG, radius=12)
    dot_r = 7
    dot_x = rx + 24
    dot_y = ry + (rh - ry) // 2 + 2
    draw.ellipse((dot_x - dot_r, dot_y - dot_r, dot_x + dot_r, dot_y + dot_r), fill=_ACCENT)
    draw.text((rx + pad_x + 18, ry + pad_y - 4), label, font=font, fill=_WHITE)
    img.save(str(out_path), "PNG")
    return out_path


def render_hook_text(text: str, out_path: Path) -> Path:
    """3-5 words, MASSIVE.

    The hook is the first thing the viewer sees. Unbreakable hyphenated
    compounds (like '20th-century') are softened to spaces so the wrapper
    can still find break points.
    """
    text = _soften_hyphens(text)
    img = _blank()
    draw = ImageDraw.Draw(img)
    font_path = "NeuePlak-CondensedBlack.ttf"
    target_max_w = _W - 100
    target_max_h = int(_H * 0.50)

    font, wrapped, block_h = _autofit(
        text, draw, font_path,
        max_w=target_max_w, max_h=target_max_h,
        max_size=240, min_size=110, step=10,
    )
    y = int(_H * 0.32) - block_h // 2
    _draw_lines_with_word_colour(
        draw, wrapped, font, y=y,
        line_gap=int(font.size * 0.08),
        stroke_width=max(6, font.size // 22),
        shadow_offset=(0, 6),
        shadow_blur=14,
        shadow_alpha=210,
    )
    img.save(str(out_path), "PNG")
    return out_path


def render_fact_chunk(text: str, out_path: Path) -> Path:
    """One subtitle chunk — big, central, brand-coloured words."""
    text = _soften_hyphens(text)
    img = _blank()
    draw = ImageDraw.Draw(img)
    font_path = "NeuePlak-CondensedBlack.ttf"
    target_max_w = _W - 120
    target_max_h = int(_H * 0.40)

    font, wrapped, block_h = _autofit(
        text, draw, font_path,
        max_w=target_max_w, max_h=target_max_h,
        max_size=170, min_size=85, step=8,
    )
    y = int(_H * 0.50) - block_h // 2
    _draw_lines_with_word_colour(
        draw, wrapped, font, y=y,
        line_gap=int(font.size * 0.10),
        stroke_width=max(5, font.size // 22),
        shadow_offset=(0, 5),
        shadow_blur=12,
        shadow_alpha=200,
    )
    img.save(str(out_path), "PNG")
    return out_path


def render_cta_frame(out_path: Path) -> Path:
    img = _blank()
    draw = ImageDraw.Draw(img)
    handle_font = _font("NeuePlak-CondensedBlack.ttf", 200)
    sub_font = _font("HKGrotesk-Black.otf", 56)

    handle = "@factjot"
    sub = "follow for more"

    hbbox = draw.textbbox((0, 0), handle, font=handle_font)
    hw, hh = hbbox[2] - hbbox[0], hbbox[3] - hbbox[1]
    sbbox = draw.textbbox((0, 0), sub, font=sub_font)
    sw, sh = sbbox[2] - sbbox[0], sbbox[3] - sbbox[1]

    gap = 36
    block_h = hh + gap + sh
    y_start = _H // 2 - block_h // 2 - 40

    hx = (_W - hw) // 2
    _text_with_shadow(img, draw, hx, y_start, handle, handle_font,
                       fill=_ACCENT, stroke_width=8,
                       shadow_offset=(0, 10), shadow_blur=18)
    sy = y_start + hh + gap
    sx = (_W - sw) // 2
    _text_with_shadow(img, draw, sx, sy, sub, sub_font,
                       fill=_LIME, stroke_width=4,
                       shadow_offset=(0, 5), shadow_blur=10)
    img.save(str(out_path), "PNG")
    return out_path


def render_logo_frame(logo_path: Path, out_path: Path) -> Path:
    img = _blank()
    if logo_path.exists():
        try:
            logo = Image.open(str(logo_path)).convert("RGBA")
            target_w = 200
            ratio = target_w / logo.width
            logo = logo.resize((target_w, int(logo.height * ratio)), Image.LANCZOS)
            r, g, b, a = logo.split()
            a = a.point(lambda x: int(x * 0.32))
            logo = Image.merge("RGBA", (r, g, b, a))
            x = _W - logo.width - 56
            y = _H - logo.height - 130
            img.paste(logo, (x, y), logo)
        except Exception:
            pass
    img.save(str(out_path), "PNG")
    return out_path


# ------------------------------------------------------------------ #
# Hook word picker
# ------------------------------------------------------------------ #

def pick_hook_words(claim: str, max_words: int = 4) -> str:
    cleaned = re.sub(r"\[/?[ih]\]", "", claim).strip()
    cleaned = _soften_hyphens(cleaned)
    words = cleaned.split()
    # Year-anchored opener: "In 1962 Soviet officer..." → "In 1962"
    for i in range(min(5, len(words))):
        if _YEAR_RE.match(words[i].strip(".,")):
            return " ".join(words[max(0, i-1):i+2]).rstrip(",.;:")
    return " ".join(words[:max_words]).rstrip(",.;:")


def _soften_hyphens(text: str) -> str:
    """Replace in-word hyphens with spaces so the wrapper can break."""
    return re.sub(r"(?<=\w)-(?=\w)", " ", text)


# ------------------------------------------------------------------ #
# Auto-fitting font sizer
# ------------------------------------------------------------------ #

def _autofit(
    text: str,
    draw: ImageDraw.ImageDraw,
    font_path: str,
    *,
    max_w: int,
    max_h: int,
    max_size: int,
    min_size: int,
    step: int = 10,
) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    """Pick the biggest font size that fits within max_w x max_h.

    Returns (font, wrapped_lines, block_height).
    Floors at min_size and accepts overflow rather than going smaller.
    """
    size = max_size
    best = None
    while size >= min_size:
        font = _font(font_path, size)
        wrapped = _wrap_smart(text, font, draw, max_w)
        max_line_w = max(int(font.getlength(line)) for line in wrapped)
        block_h = _block_h(wrapped, font, draw, line_gap=int(size * 0.10))
        if max_line_w <= max_w and block_h <= max_h:
            return font, wrapped, block_h
        best = (font, wrapped, block_h)
        size -= step
    # Floor reached — use min_size and let it overflow
    return best if best else (_font(font_path, min_size), [text], 0)


def _wrap_smart(text: str, font: ImageFont.FreeTypeFont, draw, max_w: int) -> list[str]:
    """Word-wrap. If a single word is wider than max_w, accept it on its own line."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        test = (current + " " + word).strip()
        if int(font.getlength(test)) <= max_w:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [text]


def _block_h(lines: list[str], font: ImageFont.FreeTypeFont, draw, line_gap: int) -> int:
    if not lines:
        return 0
    line_h = int(font.size * 1.05)
    return line_h * len(lines) + line_gap * max(0, len(lines) - 1)


# ------------------------------------------------------------------ #
# Coloured-word text rendering (using Pillow's native spacing)
# ------------------------------------------------------------------ #

def _draw_lines_with_word_colour(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    y: int,
    line_gap: int,
    stroke_width: int,
    shadow_offset: tuple,
    shadow_blur: int,
    shadow_alpha: int,
) -> None:
    """Draw lines centred, each word in its brand colour.

    Approach: for each line, compute the centred starting X using Pillow's
    real text length, then walk word-by-word using `font.getlength(word + ' ')`
    to advance. This matches Pillow's own spacing exactly (no clipping).

    Shadow is drawn first as a separate blurred RGBA layer so the colour
    stays clean.
    """
    img = draw._image  # underlying PIL image
    line_h = int(font.size * 1.05)

    # Pre-compute centred x positions per line
    layouts = []
    for line in lines:
        full_w = int(font.getlength(line))
        x_start = (_W - full_w) // 2
        layouts.append((line, x_start))

    # Pass 1: soft drop shadow under entire text block
    if shadow_blur > 0 and shadow_alpha > 0:
        shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        cy = y
        for line, x in layouts:
            sd.text(
                (x + shadow_offset[0], cy + shadow_offset[1]),
                line, font=font, fill=(0, 0, 0, shadow_alpha),
            )
            cy += line_h + line_gap
        shadow = shadow.filter(ImageFilter.GaussianBlur(shadow_blur))
        img.alpha_composite(shadow)

    # Pass 2: word-by-word coloured text with stroke
    cy = y
    for line, x_start in layouts:
        words = line.split()
        cx = x_start
        for i, word in enumerate(words):
            colour = _word_colour(word, i)
            draw.text(
                (cx, cy), word, font=font,
                fill=colour,
                stroke_width=stroke_width,
                stroke_fill=(0, 0, 0, 255),
            )
            # Advance by exact Pillow spacing for "word "
            cx += int(font.getlength(word + " "))
        cy += line_h + line_gap


def _text_with_shadow(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    x: int, y: int, text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple, stroke_width: int,
    shadow_offset: tuple, shadow_blur: int,
) -> None:
    if shadow_blur > 0:
        shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.text((x + shadow_offset[0], y + shadow_offset[1]), text,
                font=font, fill=(0, 0, 0, 220))
        shadow = shadow.filter(ImageFilter.GaussianBlur(shadow_blur))
        img.alpha_composite(shadow)
    draw.text((x, y), text, font=font, fill=fill,
              stroke_width=stroke_width, stroke_fill=(0, 0, 0, 255))


# ------------------------------------------------------------------ #
# Generic helpers
# ------------------------------------------------------------------ #

def _blank() -> Image.Image:
    return Image.new("RGBA", (_W, _H), (0, 0, 0, 0))


def _rounded_rect(draw: ImageDraw.ImageDraw, bbox: tuple, fill: tuple, radius: int = 12) -> None:
    draw.rounded_rectangle(bbox, radius=radius, fill=fill)
