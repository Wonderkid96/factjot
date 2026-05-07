"""Single source of truth for factjot brand constants.

Any module that renders visual content must import from here.
Never hardcode colours, fonts, or sizes. Read from brand_kit.json
via this module so the brand can't drift across carousel, list, Reel,
or story renderers.

Typography (TJCreate Visual Style Guide v2.0, 2026-05):
  Display / headlines  -> Instrument Serif  Regular + Italic
  Body / subtitles     -> Space Grotesk     SemiBold 600
  Labels / tags        -> JetBrains Mono    Bold 700
  Caption / burn-in    -> Archivo Black     900 (video subtitles only)

Wordmark rule (hardwired, never changes):
  fact[normal]  jot[italic]  .[accent-red]  colour=off-white
  letter-spacing: -0.02em  (matches make_avatar.py exactly)
"""
from __future__ import annotations

import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_KIT  = _ROOT / "brand" / "brand_kit.json"

# ------------------------------------------------------------------ #
# Load brand_kit once at import time
# ------------------------------------------------------------------ #
_kit: dict = {}

def _load() -> None:
    global _kit
    if _kit:
        return
    _kit = json.loads(_KIT.read_text(encoding="utf-8"))

_load()

# ------------------------------------------------------------------ #
# Colours
# ------------------------------------------------------------------ #
def _c(key: str) -> str:
    return _kit["colors"][key]

PAPER      = _c("paper")        # #F4F1E9
INK        = _c("ink")          # #0A0A0A
NEAR_BLACK = _c("near_black")   # #0B0B0C
MUTED      = _c("muted")        # #9A938A
OFF_WHITE  = _c("off_white")    # #EDE8DD
ACCENT     = _c("accent")       # #E6352A  - key words, dots, CTA
LIME       = _c("lime")         # #C8DB45
LILAC      = _c("lilac")        # #C4A9D0
WHITE      = _c("white")        # #FFFFFF

# v2 additions (TJCreate Visual Style Guide v2.0)
_v2 = _kit.get("colors_v2", {})
SKY              = _v2.get("sky")              # #C9D8E2
AVAILABLE        = _v2.get("available")        # #80EF80
MUTED_CANONICAL  = _v2.get("muted_canonical")  # #6B645A (v2 spec)

_surfaces = _kit.get("surfaces", {})
SURFACE_DARK_BG  = _surfaces.get("dark_bg")    # #0A0A0A
SURFACE          = _surfaces.get("surface")    # #161614
SURFACE_ELEVATED = _surfaces.get("elevated")   # #1E1E1B

BRAND_GRADIENT_CSS = (_kit.get("gradient") or {}).get(
    "brand_css",
    "linear-gradient(90deg, #E6352A 0%, #F4F1E9 33%, #C8DB45 66%, #C4A9D0 100%)",
)

# ------------------------------------------------------------------ #
# Font file paths (absolute)
# ------------------------------------------------------------------ #
_F = _ROOT / "assets" / "fonts"

FONT_SERIF_REGULAR  = _F / "InstrumentSerif-Regular.ttf"
FONT_SERIF_ITALIC   = _F / "InstrumentSerif-Italic.ttf"
FONT_SANS_SEMIBOLD  = _F / "SpaceGrotesk-SemiBold.ttf"
FONT_SANS_MEDIUM    = _F / "SpaceGrotesk-Medium.ttf"
FONT_MONO_BOLD      = _F / "JetBrainsMono-Bold.ttf"

# Caption / burn-in font (Archivo Black 900, single weight). v2.0 only —
# scope is short-form video subtitles and title cards. Existing
# carousel/reel-thumbnail/story renderers do NOT use it.
FONT_CAPTION_BLACK  = _F / "ArchivoBlack-Regular.ttf"

def font_url(path: Path) -> str:
    """Return a file:// URI for a font path (for HTML/CSS use)."""
    return path.absolute().as_uri()

# ------------------------------------------------------------------ #
# Font role constants - use these, never hardcode font names
# ------------------------------------------------------------------ #
ROLE_DISPLAY = "Instrument Serif"  # headlines, title cards, CTA wordmark
ROLE_BODY    = "Space Grotesk"     # subtitles, body copy
ROLE_LABEL   = "JetBrains Mono"   # category tags, metadata, counters
ROLE_CAPTION = "Archivo Black"     # short-form video burn-in subtitles only (v2)

# ------------------------------------------------------------------ #
# Wordmark spec (matches make_avatar.py - the canonical renderer)
# NEVER diverge from this. fact=normal, jot=italic, .=accent
# ------------------------------------------------------------------ #
WORDMARK_LETTER_SPACING = "-0.02em"
WORDMARK_COLOR          = OFF_WHITE

def wordmark_html(prefix: str = "") -> str:
    """Return the canonical wordmark as an HTML snippet.

    Args:
        prefix: Optional prefix before 'fact', e.g. '@'.

    Returns:
        '<span class="reg">{prefix}fact</span><span class="ital">jot</span>'
        '<span class="dot">.</span>'
    """
    return (
        f'<span class="reg">{prefix}fact</span>'
        f'<span class="ital">jot</span>'
        f'<span class="dot">.</span>'
    )

# ------------------------------------------------------------------ #
# Type scale (from style guide, adapted to 1080x1920 Reel canvas)
# ------------------------------------------------------------------ #
TYPE = {
    "hero":     160,   # Instrument Serif - CTA wordmark
    "h1":        90,   # Instrument Serif - title cards
    "subtitle":  72,   # Space Grotesk SemiBold - kinetic subtitles
    "label":     24,   # JetBrains Mono Bold - category pill
    "logo":      36,   # Instrument Serif - watermark (50% opacity)
}

# ------------------------------------------------------------------ #
# Layout constants (Reel canvas)
# ------------------------------------------------------------------ #
REEL_W = 1080
REEL_H = 1920

LABEL_TOP_PX     = 96     # Category label Y position
HOOK_TOP_PX      = 220    # Title card top - always below label
SUBTITLE_TOP_PX  = 1200   # Subtitle anchor - safe from IG UI chrome
LOGO_BOTTOM_PX   = 120    # Wordmark watermark from bottom
LOGO_RIGHT_PX    = 56     # Wordmark watermark from right

SIDE_MARGIN_PX   = 72     # Left/right margin for subtitle text box

# ------------------------------------------------------------------ #
# Validation helper
# ------------------------------------------------------------------ #
def assert_fonts_present() -> None:
    """Raise if any required font file is missing. Call at startup."""
    required = [
        FONT_SERIF_REGULAR, FONT_SERIF_ITALIC,
        FONT_SANS_SEMIBOLD, FONT_SANS_MEDIUM,
        FONT_MONO_BOLD,
    ]
    missing = [str(f) for f in required if not f.exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing brand fonts - run setup or check assets/fonts/:\n"
            + "\n".join(missing)
        )
