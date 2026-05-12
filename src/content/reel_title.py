"""Generate a compelling story title for a Reel from the fact claim.

The title appears as a brief opening card (during the 3.5s intro) - like a documentary
episode title. It is NOT a subtitle and NOT the first line of the VO.
It names the story. "The Demon Core." "The Man Who Saved the World."
"The Sphere That Killed Twice."

Strategy:
  1. If the fact bank entry has a `reel_title` field, use it (manual override,
     always best quality).
  2. Otherwise auto-generate using entity extraction + signal detection.
  3. Fall back to None (no title card) if generation produces something weak.

The auto-generator classifies the claim by subject type (person / institution /
animal / object) and story signal (reversal / default), then picks from a pool
of templates tuned to the factjot voice: dry, specific, slightly contemptuous
of easy answers. Templates like "The X Nobody Talks About" are banned.
"""
from __future__ import annotations

import random
import re
from typing import Optional

# ------------------------------------------------------------------ #
# Known titles for specific facts (keyed by claim substring).
# Add entries here as we build Reels so quality is guaranteed.
# ------------------------------------------------------------------ #
_KNOWN_TITLES: list[tuple[str, str]] = [
    ("plutonium sphere",     "The Demon Core"),
    ("Vasili Arkhipov",      "The Man Who Saved the World"),
    ("Phineas Gage",         "The Man With a Spike Through His Head"),
    ("Sarah Winchester",     "The House That Never Stopped"),
    ("Tarrare",              "The Soldier Who Could Eat Anything"),
    ("Radium",               "The Girls Who Glowed"),
    ("Carrington",           "The Day the Sun Struck Earth"),
    ("Toba",                 "The Eruption That Nearly Ended Us"),
    ("mantis shrimp",        "The Deadliest Punch in Nature"),
    ("Cordyceps",            "The Fungus That Controls Minds"),
    ("anglerfish",           "The Strangest Love Story in the Ocean"),
    ("Eternal Flame",        "The Fire That Never Goes Out"),
    ("Denmark Strait",       "The World's Tallest Waterfall"),
    ("Tunguska",             "The Explosion With No Crater"),
    ("Antikythera",          "The Ancient Computer"),
    ("octopus",              "Nine Brains, Eight Decisions"),
    ("emu",                  "The Army That Surrendered to Emus"),
    ("Perimeter",            "The Machine That Declares War Itself"),
    ("B.F. Skinner",         "The Weapon That Actually Worked"),
    ("Winchester rifle",     "The House That Never Stopped"),
    ("Chernobyl",            "The Reactor They Couldn't Admit"),
    ("Dyatlov",              "The Nine Who Didn't Come Back"),
    ("Dancing Plague",       "They Hired a Band to Stop the Dancing"),
    ("dancing",              "They Hired a Band to Stop the Dancing"),
]

# ------------------------------------------------------------------ #
# Signal detection
# ------------------------------------------------------------------ #
_STOP = frozenset({
    "a", "an", "the", "in", "on", "at", "to", "for", "of", "and", "or",
    "but", "is", "was", "are", "were", "be", "been", "being", "have",
    "had", "has", "do", "did", "does", "will", "would", "could", "should",
    "that", "this", "with", "from", "as", "by", "he", "she", "it", "they",
    "his", "her", "its", "their", "who", "which", "when", "where", "not",
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "each", "every", "both", "all", "some", "any", "many", "most",
})

_YEAR_RE   = re.compile(r"^(?:18|19|20)\d{2}s?$")
_NUMBER_RE = re.compile(r"^\d")

_REVERSAL_SIGNALS = frozenset({
    "but", "despite", "however", "failed", "failure", "lost", "refused",
    "rejected", "wrong", "mistake", "denied", "ignored", "banned",
    "cancelled", "fired", "arrested", "collapsed", "backfired", "instead",
    "turned out", "never worked", "gave up", "surrendered", "defeated",
    "nobody", "no one", "nobody wanted", "nobody used", "nobody believed",
    "nobody listened", "no one believed", "no one listened",
})

_ANIMAL_SIGNALS = frozenset({
    "emu", "bird", "birds", "fish", "shark", "octopus", "whale", "bear",
    "lion", "tiger", "wolf", "eagle", "pigeon", "rat", "cat", "dog",
    "spider", "jellyfish", "snake", "crocodile", "elephant", "dolphin",
    "squid", "crab", "beetle", "wasp", "moth", "bat", "crow", "raven",
    "mantis", "shrimp", "starfish", "eel", "platypus", "sloth", "fungus",
    "parasite", "bacteria", "virus",
})

_INSTITUTION_SIGNALS = frozenset({
    "army", "military", "nasa", "government", "congress", "parliament",
    "company", "corporation", "bank", "hospital", "university", "police",
    "navy", "air force", "committee", "department", "ministry", "soviet",
    "pentagon", "cia", "fbi", "kgb", "fda", "cdc", "who ", "un ", "eu ",
    "white house", "kremlin", "pentagon", "senate", "court",
})


def _word_in(word: str, text: str) -> bool:
    """True if `word` appears as a whole word in `text`."""
    return bool(re.search(r"\b" + re.escape(word) + r"\b", text))


def _has_reversal(claim: str) -> bool:
    lower = claim.lower()
    return any(_word_in(s.strip(), lower) for s in _REVERSAL_SIGNALS)


def _classify_subject(proper_nouns: list[str], claim: str) -> str:
    """Return 'animal', 'institution', 'person', or 'thing'."""
    lower = claim.lower()

    if any(_word_in(a, lower) for a in _ANIMAL_SIGNALS):
        return "animal"

    if any(_word_in(i, lower) for i in _INSTITUTION_SIGNALS):
        return "institution"

    # Person heuristic: biographical markers, or 2+ consecutive proper nouns
    bio_markers = ("born", "died", " his ", " her ", " he ", " she ")
    if proper_nouns and any(m in lower for m in bio_markers):
        return "person"
    if len(proper_nouns) >= 2:
        return "person"

    return "thing"


# ------------------------------------------------------------------ #
# Template pools — indexed by (subject_type, reversal, topic).
# Pick randomly from the matching pool so titles stay varied.
# Pools are ordered best-first; the first entry is the strongest.
# ------------------------------------------------------------------ #

def _pick(pool: list[str]) -> str:
    return random.choice(pool)


def _templates_person_reversal(subject: str, topic: str) -> str:
    pool = [
        f"The {subject} Nobody Listened To",
        f"The {subject} They Ignored",
        f"Why Nobody Stopped {subject}",
        f"The {subject} Who Was Wrong About Everything",
        f"What {subject} Got Completely Wrong",
    ]
    return _pick(pool)


def _templates_person(subject: str, topic: str) -> str:
    topic_pools: dict[str, list[str]] = {
        "history": [
            f"The {subject} They Forgot",
            f"What {subject} Left Behind",
            f"The Last Thing {subject} Did",
            f"The {subject} Who Wasn't Supposed to Be There",
        ],
        "space": [
            f"What {subject} Actually Found",
            f"The {subject} at the Edge",
            f"How {subject} Got Stuck",
        ],
    }
    pool = topic_pools.get(topic, [
        f"The {subject} They Forgot",
        f"What {subject} Left Behind",
        f"The {subject} Nobody Expected",
    ])
    return _pick(pool)


def _templates_institution_reversal(subject: str, topic: str) -> str:
    pool = [
        f"The {subject} That Defeated Itself",
        f"How {subject} Got It Completely Wrong",
        f"{subject}'s Most Expensive Mistake",
        f"The {subject} That Couldn't Stop Itself",
        f"Why {subject} Lost",
    ]
    return _pick(pool)


def _templates_institution(subject: str, topic: str) -> str:
    pool = [
        f"The {subject} Nobody Questioned",
        f"What {subject} Actually Decided",
        f"The {subject} That Knew Too Much",
        f"The {subject} With One Job",
    ]
    return _pick(pool)


def _templates_animal_reversal(subject: str, topic: str) -> str:
    pool = [
        f"The {subject} That Won",
        f"The {subject} Nobody Could Stop",
        f"How {subject} Beat Everything",
        f"The {subject}'s Unlikely Victory",
    ]
    return _pick(pool)


def _templates_animal(subject: str, topic: str) -> str:
    pool = [
        f"The {subject} That Shouldn't Exist",
        f"What {subject} Actually Does",
        f"The {subject} With a Problem",
        f"The {subject} at the Edge of Everything",
    ]
    return _pick(pool)


def _templates_thing_reversal(noun: str, topic: str) -> str:
    topic_pools: dict[str, list[str]] = {
        "history": [
            f"The {noun} That Backfired",
            f"The {noun} That Should Have Stopped",
            f"The {noun} Nobody Survived Twice",
        ],
        "space": [
            f"The {noun} That Disappeared",
            f"The {noun} at the Edge of Everything",
        ],
        "tech": [
            f"The {noun} That Broke Everything",
            f"The {noun} Nobody Tested",
            f"The {noun} That Worked Once",
        ],
        "science": [
            f"The {noun} That Worked Once",
            f"The {noun} Nobody Expected",
        ],
    }
    pool = topic_pools.get(topic, [
        f"The {noun} That Backfired",
        f"The {noun} That Should Have Stopped",
        f"The {noun} Nobody Survived Twice",
    ])
    return _pick(pool)


def _templates_thing(noun: str, topic: str) -> str:
    topic_pools: dict[str, list[str]] = {
        "history": [
            f"The {noun} They Buried",
            f"The {noun} That Outlasted Everything",
            f"The Last Known {noun}",
        ],
        "space": [
            f"The {noun} at the Edge of Everything",
            f"The {noun} That Shouldn't Be There",
            f"The Signal Inside the {noun}",
        ],
        "nature":  [
            f"The {noun} That Shouldn't Work",
            f"The {noun} at the Bottom of Everything",
        ],
        "biology": [
            f"The {noun} That Shouldn't Work",
            f"The {noun} Running the Show",
        ],
        "ocean":   [
            f"The {noun} Hiding in the Deep",
            f"The {noun} at the Bottom",
        ],
        "tech":    [
            f"The {noun} That Changed One Thing",
            f"The {noun} Nobody Finished",
        ],
        "earth":   [
            f"The {noun} Beneath Our Feet",
            f"The {noun} Nobody Mapped",
        ],
        "science": [
            f"The {noun} That Shouldn't Work",
            f"The {noun} Nobody Expected",
        ],
    }
    pool = topic_pools.get(topic, [
        f"The {noun} Nobody Expected",
        f"The Last Known {noun}",
    ])
    return _pick(pool)


def _year_templates(year: str, noun: str, topic: str) -> str:
    pool = [
        f"In {year}, Nobody Stopped This",
        f"What Happened in {year}",
        f"The {noun.capitalize()} of {year}",
        f"In {year}, Nobody Believed It",
    ]
    return _pick(pool)


# ------------------------------------------------------------------ #
# Public API
# ------------------------------------------------------------------ #

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

    lower = claim.lower()
    for fragment, title in _KNOWN_TITLES:
        if fragment.lower() in lower:
            return title

    return _auto_title(claim, topic)


def _auto_title(claim: str, topic: str) -> Optional[str]:
    """Derive a title from the claim using entity extraction + signal-based templates."""
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

    reversal     = _has_reversal(claim)
    subject_type = _classify_subject(proper_nouns, claim)

    if proper_nouns:
        # Animals and institutions: use the first noun only to avoid
        # awkward compounds like "NASA Apollo" or "Soviet Engineers".
        # Persons and things: join up to two for specificity.
        if subject_type in ("animal", "institution"):
            subject = proper_nouns[0]
        else:
            subject = " ".join(proper_nouns[:2])

        if subject_type == "animal":
            return (
                _templates_animal_reversal(subject, topic) if reversal
                else _templates_animal(subject, topic)
            )
        if subject_type == "institution":
            return (
                _templates_institution_reversal(subject, topic) if reversal
                else _templates_institution(subject, topic)
            )
        if subject_type == "person":
            return (
                _templates_person_reversal(subject, topic) if reversal
                else _templates_person(subject, topic)
            )
        # thing with a proper noun
        return (
            _templates_thing_reversal(subject, topic) if reversal
            else _templates_thing(subject, topic)
        )

    if year and content_nouns:
        return _year_templates(year, content_nouns[0], topic)

    if content_nouns:
        noun = content_nouns[0].capitalize()
        return (
            _templates_thing_reversal(noun, topic) if reversal
            else _templates_thing(noun, topic)
        )

    if year:
        return f"What Happened in {year}"

    return None
