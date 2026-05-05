"""Generate a compelling story title for a Reel from the fact claim.

The title appears as a brief opening card (during the 3.5s intro) - like a documentary
episode title. It is NOT a subtitle and NOT the first line of the VO.
It names the story. "The Demon Core." "The Man Who Saved the World."
"The Sphere That Killed Twice."

Strategy:
  1. If the fact bank entry has a `reel_title` field, use it (manual override,
     always best quality).
  2. Otherwise auto-generate using entity extraction + narrative templates.
  3. Fall back to None (no title card) if generation produces something weak.

The auto-generator pulls the central subject from the claim and wraps it in
one of several proven documentary title patterns, chosen by topic and claim
structure.
"""
from __future__ import annotations

import re
from typing import Optional

# ------------------------------------------------------------------ #
# Known titles for specific facts (keyed by claim substring)
# Add entries here as we build Reels so quality is guaranteed.
# ------------------------------------------------------------------ #
_KNOWN_TITLES: list[tuple[str, str]] = [
    ("plutonium sphere", "The Demon Core"),
    ("Vasili Arkhipov", "The Man Who Saved the World"),
    ("Phineas Gage", "The Man With a Spike Through His Head"),
    ("Sarah Winchester", "The House That Never Stopped"),
    ("Tarrare", "The Soldier Who Could Eat Anything"),
    ("Radium", "The Girls Who Glowed"),
    ("Carrington", "The Day the Sun Struck Earth"),
    ("Toba", "The Eruption That Nearly Ended Us"),
    ("mantis shrimp", "The Deadliest Punch in Nature"),
    ("Cordyceps", "The Fungus That Controls Minds"),
    ("anglerfish", "The Strangest Love Story in the Ocean"),
    ("Eternal Flame", "The Fire That Never Goes Out"),
    ("Denmark Strait", "The World's Tallest Waterfall"),
    ("Tunguska", "The Explosion With No Crater"),
    ("Antikythera", "The Ancient Computer"),
    ("octopus",     "Nine Brains, Eight Decisions"),
]

# ------------------------------------------------------------------ #
# Stop words and entity heuristics (reused from narrative_beats)
# ------------------------------------------------------------------ #
_STOP = frozenset({
    "a", "an", "the", "in", "on", "at", "to", "for", "of", "and", "or",
    "but", "is", "was", "are", "were", "be", "been", "being", "have",
    "had", "has", "do", "did", "does", "will", "would", "could", "should",
    "that", "this", "with", "from", "as", "by", "he", "she", "it", "they",
    "his", "her", "its", "their", "who", "which", "when", "where", "not",
    # Number words - prevent "One", "Two", "Each" being picked as proper nouns
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "each", "every", "both", "all", "some", "any", "many", "most",
})

_YEAR_RE   = re.compile(r"^(?:18|19|20)\d{2}s?$")
_NUMBER_RE = re.compile(r"^\d")


def make_title(
    claim: str,
    topic: str,
    reel_title: Optional[str] = None,
) -> Optional[str]:
    """Return a story title string, or None if nothing compelling can be derived.

    Args:
        claim:       Raw fact claim text.
        topic:       Fact topic (history, space, nature, ocean, tech, earth).
        reel_title:  Manual override from the fact bank. Always wins if set.

    Returns:
        A short title string (3-7 words) or None.
    """
    if reel_title:
        return reel_title.strip()

    # Check known titles
    lower = claim.lower()
    for fragment, title in _KNOWN_TITLES:
        if fragment.lower() in lower:
            return title

    # Auto-generate
    return _auto_title(claim, topic)


def _auto_title(claim: str, topic: str) -> Optional[str]:
    """Derive a title from the claim using entity extraction + templates."""
    tokens = re.sub(r"[^\w\s]", " ", claim).split()
    proper_nouns = [
        t for t in tokens
        if t[0].isupper()
        and t.lower() not in _STOP
        and not _YEAR_RE.match(t)
        and not _NUMBER_RE.match(t)
        and len(t) > 2
    ]
    content_nouns = [
        t.lower() for t in tokens
        if t.lower() not in _STOP
        and not _YEAR_RE.match(t)
        and not _NUMBER_RE.match(t)
        and len(t) > 4
    ]

    years = [t for t in tokens if _YEAR_RE.match(t)]
    year  = years[0] if years else None

    # Template selection -- lead with intrigue, not the answer.
    # Good hooks withhold the punchline so viewers stay to find out.
    if proper_nouns and year:
        subject = proper_nouns[0]
        return f"What {subject} Did in {year}"

    if proper_nouns:
        subject = " ".join(proper_nouns[:2])
        templates_by_topic = {
            "history": f"The {subject} Nobody Talks About",
            "space":   f"What {subject} Actually Found",
            "nature":  f"How {subject} Survived This",
            "biology": f"How {subject} Survived This",
            "ocean":   f"What Lives Beneath {subject}",
            "tech":    f"What {subject} Changed Forever",
            "earth":   f"The Secret Under {subject}",
            "science": f"What {subject} Discovered",
        }
        return templates_by_topic.get(topic, f"The {subject} Nobody Talks About")

    if year and content_nouns:
        noun = content_nouns[0].capitalize()
        return f"In {year}, Nobody Believed This"

    if content_nouns:
        noun = content_nouns[0].capitalize()
        templates_by_topic = {
            "history": f"The {noun} They Buried",
            "space":   f"The {noun} at the Edge of Everything",
            "nature":  f"The {noun} That Should Not Exist",
            "biology": f"The {noun} That Should Not Exist",
            "ocean":   f"The {noun} Hiding in the Deep",
            "tech":    f"The {noun} That Changed Everything",
            "earth":   f"The {noun} Beneath Our Feet",
            "science": f"The {noun} Nobody Expected",
        }
        return templates_by_topic.get(topic, f"The {noun} Nobody Talks About")

    if year:
        return f"Nobody Believed What Happened in {year}"

    return None
