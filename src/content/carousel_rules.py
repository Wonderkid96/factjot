"""Single source of truth for carousel content rules.

Phase 4 of the content quality recovery: removes the drift between
ship_manual_post.py BRAND_VOICE_EDITORIAL, autonomous_agent.py
MODE_PROMPTS, and src/content/carousel_writer.py prompt templates.
"""
from __future__ import annotations

# Visual line caps, by slide kind. Calibrated in src/render/line_fit_probe.py.
PHOTO_SLIDE_CAP = 22
TYPOGRAPHY_SLIDE_CAP = 26

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
