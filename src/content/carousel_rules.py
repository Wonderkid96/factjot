"""Single source of truth for carousel content rules.

Phase 4 of the content quality recovery: removes the drift between
ship_manual_post.py BRAND_VOICE_EDITORIAL, autonomous_agent.py
MODE_PROMPTS, and src/content/carousel_writer.py prompt templates.
"""
from __future__ import annotations

from typing import Literal

# Visual line caps, by slide kind. Calibrated in src/render/line_fit_probe.py.
# Kept as module-level aliases of LAYOUT_PROFILES["compact_legacy"] so existing
# importers continue to work without change.
PHOTO_SLIDE_CAP = 22
TYPOGRAPHY_SLIDE_CAP = 26


# ------------------------------------------------------------------ #
# Layout profiles
# ------------------------------------------------------------------ #
# compact_legacy: the original Archivo Black 900 body layout. Tight
#   24-char hard cap, anchored bottom-left text. Existing fact / news
#   carousels render byte-identical with this profile.
# readable_list: brand-correct Space Grotesk SemiBold body in a
#   half-box flexbox container, with renderer-side font auto-fit.
#   Lines can be complete clauses (~30-50 chars). Currently the
#   default for format_type=list only.

LayoutMode = Literal["compact_legacy", "readable_list"]

LAYOUT_PROFILES: dict[str, dict] = {
    "compact_legacy": {
        "body_font":         "Archivo Black",
        "body_weight":       900,
        "body_size_photo":   48,
        "body_size_typo":    42,
        "line_height":       1.08,
        "photo_cap":         22,
        "typography_cap":    26,
        "hard_cap":          24,
        "auto_size":         False,
        "container":         "anchored_bottom_left",
        "writer_target_min": 12,
        "writer_target_max": 22,
    },
    "readable_list": {
        "body_font":         "Space Grotesk",
        "body_weight":       600,
        "body_size_max":     64,
        "body_size_min":     28,
        "line_height":       1.18,
        "photo_cap":         50,
        "typography_cap":    60,
        "hard_cap":          56,
        "auto_size":         True,
        "container":         "half_box_centered",
        "writer_target_min": 30,
        "writer_target_max": 50,
    },
}


def get_profile(mode: LayoutMode | str) -> dict:
    """Return the layout profile dict for `mode`. Defaults to compact_legacy
    if an unknown value is passed (defensive: keeps existing callers safe)."""
    if mode in LAYOUT_PROFILES:
        return LAYOUT_PROFILES[mode]
    return LAYOUT_PROFILES["compact_legacy"]

# Words a line must not end on (weak connectors).
WEAK_LINE_ENDINGS = frozenset({
    "a", "the", "and", "or", "of", "in", "to", "with", "an", "at", "by", "for",
})

# Maximum slides per carousel (cover + content).
MAX_SLIDES_TOTAL = 8
MIN_SLIDES_TOTAL = 3


BEAT_DENSITY_RULES = """\
ONE SLIDE = ONE IDEA. ONE BEAT = ONE FACT. HARD RULE.
- Semicolons inside a beat are FORBIDDEN.
- "and" welding two facts is FORBIDDEN. That second "and" starts a new beat.
- Multiple named people, multiple events, or multiple consequences in one
  slide are FORBIDDEN.
- Front-load the most interesting element on each slide.
"""


PHOTOGRAPHABLE_BEATS_RULES = """\
PHOTOGRAPHABLE BEATS - HARD RULE.
- Every beat's image_query must describe a visible object, person, or scene
  an archive could realistically have a photo of.
- Abstract concepts (a budget, a ruling, a classification, a regulation)
  must be reframed around a concrete photographable proxy: the people,
  the device, the workplace, the scene, the era.
- If you cannot think of a photographable proxy, repeat the cover query.
"""


COVER_TITLE_RULES = """\
Cover title: 5-9 words, no full stop. Must contain a verb or a sting.
Banned chant-style shapes:
- "the X with no Y"
- "no X no Y"
- "X-free Y"
- "the Y that X" where Y is vague
"""
