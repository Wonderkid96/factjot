"""Single source of truth for factjot brand constants.

Any module that renders visual content must import from here.
Never hardcode colours, fonts, or sizes. Read from brand_kit.json
via this module so the brand can't drift across carousel, list, Reel,
or story renderers.

Typography (TJCreate Visual Style Guide v2.1, 2026-05-10 font hierarchy):
  Display / headlines     -> Instrument Serif Regular + Italic
  Carousel body (list)    -> Space Grotesk    SemiBold 600
  Labels / kickers / chips -> Space Grotesk    Bold     700  (canonical)
  Reel subtitles          -> Archivo          Bold     700  (kinetic burn-in)
  Hooks / intro / story   -> Archivo Black    900           (Reel covers + thumbnails)

JetBrains Mono Bold is retained on disk for backwards compatibility but no
template references it after the 2026-05-10 hierarchy migration.

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

_REQUIRED_TYPOGRAPHY_KEYS = (
    # Removing any of these from brand_kit.json silently breaks a renderer.
    # Validate at import time so the failure is loud (KeyError on import)
    # rather than a downstream font reversion that ships with no log line.
    "headline_font",
    "headline_italic_font",
    "label_font_canonical",  # 2026-05-10 canonical label font; renderers
                              # MUST resolve to this, never fall back to
                              # legacy `label_font` (which still points at
                              # JetBrainsMono-Bold.ttf for backwards compat).
)


def _load() -> None:
    global _kit
    if _kit:
        return
    _kit = json.loads(_KIT.read_text(encoding="utf-8"))
    typography = _kit.get("typography") or {}
    missing = [k for k in _REQUIRED_TYPOGRAPHY_KEYS if not typography.get(k)]
    if missing:
        raise ValueError(
            f"brand_kit.json typography block is missing required keys: "
            f"{missing}. Renderers depend on these; missing values silently "
            f"fall back to deprecated fonts. Restore the keys before any "
            f"render path is invoked."
        )

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
FONT_MONO_BOLD      = _F / "JetBrainsMono-Bold.ttf"  # legacy, no template uses it

# v2.1 (2026-05-10) font hierarchy migration ------------------------------- #
# Space Grotesk Bold 700 replaces JetBrains Mono Bold for labels, kickers,
# chips, metadata, score badges, item indexes, source attributions.
# Archivo Bold 700 replaces Space Grotesk Medium 500 for kinetic reel
# subtitles. Both new files live alongside the legacy ones.
LABEL_FONT_CANONICAL_PATH = _F / "SpaceGrotesk-Bold.ttf"
SUBTITLE_FONT_PATH        = _F / "Archivo-Bold.ttf"
FONT_SANS_BOLD            = LABEL_FONT_CANONICAL_PATH  # alias for renderers
FONT_ARCHIVO_BOLD         = SUBTITLE_FONT_PATH          # alias for renderers

# Caption / burn-in font (Archivo Black 900, single weight). v2.0+ scope:
# Reel hooks, intro/title cards, thumbnails, story cards.
FONT_CAPTION_BLACK  = _F / "ArchivoBlack-Regular.ttf"

def font_url(path: Path) -> str:
    """Return a file:// URI for a font path (for HTML/CSS use)."""
    return path.absolute().as_uri()

# ------------------------------------------------------------------ #
# Font role constants - use these, never hardcode font names
# ------------------------------------------------------------------ #
ROLE_DISPLAY  = "Instrument Serif"  # headlines, title cards, CTA wordmark
ROLE_BODY     = "Space Grotesk"     # carousel body copy (readable_list)
ROLE_LABEL    = "Space Grotesk"     # v2.1 canonical labels/kickers/chips (Bold 700)
ROLE_LABEL_LEGACY = "JetBrains Mono"  # retained for any external consumer
ROLE_SUBTITLE = "Archivo"           # v2.1 kinetic reel subtitles (Bold 700)
ROLE_CAPTION  = "Archivo Black"     # hooks, intro/title cards, thumbnails, story cards

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
    "subtitle":  72,   # Archivo Bold 700 - kinetic subtitles (v2.1)
    "label":     24,   # Space Grotesk Bold 700 - category pill (v2.1)
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
        FONT_SANS_BOLD,             # v2.1 canonical label font
        FONT_ARCHIVO_BOLD,          # v2.1 kinetic subtitle font
        FONT_CAPTION_BLACK,
        FONT_MONO_BOLD,             # legacy, kept for backwards compatibility
    ]
    missing = [str(f) for f in required if not f.exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing brand fonts - run setup or check assets/fonts/:\n"
            + "\n".join(missing)
        )
