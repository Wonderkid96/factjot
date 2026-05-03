"""Decompose a fact into a narrative shot list for documentary-style Reels.

A Reel feels like a mini-documentary when each clip serves a different
narrative beat:

  ESTABLISHING → SUBJECT → DETAIL → CONSEQUENCE → ATMOSPHERE

Instead of running 6 variations of one query (which produces 6 visually
similar clips), we generate one search query per beat. Each beat is
deliberately distinct so the resulting clips cut between different
subjects, scales, and angles - the visual rhythm of a documentary.

Approach:
  1. Detect topic + extract entities from the claim (proper nouns,
     numbers/years, key verbs and nouns).
  2. Apply a topic-specific narrative template that maps entities into
     5 distinct visual queries.
  3. Return as an ordered list - clip 0 plays first, etc.

No LLM, no API. Pure regex + topic templates. Cheap, fast, deterministic.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


# ------------------------------------------------------------------ #
# Stop-word and POS heuristics
# ------------------------------------------------------------------ #

_STOP = frozenset({
    "a", "an", "the", "in", "on", "at", "to", "for", "of", "and", "or",
    "but", "is", "was", "are", "were", "be", "been", "being", "have",
    "had", "has", "do", "did", "does", "will", "would", "could", "should",
    "that", "this", "with", "from", "as", "by", "he", "she", "it", "they",
    "his", "her", "its", "their", "who", "which", "when", "where", "how",
    "not", "no", "can", "so", "if", "about", "after", "before", "than",
    "so", "more", "than", "also", "just", "only", "own", "same",
})

_NUMBER_RE = re.compile(r"^\$?[\d,]+(?:\.\d+)?(?:%|st|nd|rd|th|s)?$")
_YEAR_RE   = re.compile(r"^(?:1[0-9]|20)\d{2}s?$")


@dataclass
class Entities:
    proper_nouns: list[str]
    years: list[str]
    numbers: list[str]
    nouns: list[str]
    verbs_present: list[str]
    period_label: str  # e.g. "1920s", "Victorian", "ancient", or ""


def extract_entities(claim: str) -> Entities:
    cleaned = re.sub(r"\(.*?\)", "", claim)
    cleaned = re.sub(r"[^\w\s\-]", " ", cleaned)
    tokens = cleaned.split()

    proper: list[str] = []
    years:  list[str] = []
    numbers:list[str] = []
    nouns:  list[str] = []
    verbs:  list[str] = []

    for i, t in enumerate(tokens):
        low = t.lower()
        if _YEAR_RE.match(t):
            years.append(t)
            continue
        if _NUMBER_RE.match(t):
            numbers.append(t)
            continue
        if low in _STOP:
            continue
        if i > 0 and t[0].isupper() and len(t) > 2 and t.isalpha():
            proper.append(t)
            continue
        # Crude verb sniffer: -ed, -ing, -ate, common action words
        if (
            low.endswith(("ed", "ing", "ate"))
            or low in {"eats", "ate", "kills", "killed", "swallows", "swam", "flew", "burns", "burnt",
                       "exploded", "hatched", "hunts", "feeds", "lays", "builds", "punches", "shoots",
                       "broke", "broken", "dies", "died", "lived", "found", "hides", "carries"}
        ):
            verbs.append(low)
            continue
        if len(t) > 3:
            nouns.append(low)

    period = _detect_period(years, tokens)
    return Entities(
        proper_nouns=proper[:5],
        years=years[:2],
        numbers=numbers[:2],
        nouns=nouns[:8],
        verbs_present=verbs[:4],
        period_label=period,
    )


def _detect_period(years: list[str], tokens: list[str]) -> str:
    """Return a period label like '1920s', 'Victorian', 'ancient', or ''."""
    for y in years:
        decade = y[:3] + "0s"
        return decade
    lowered = " ".join(t.lower() for t in tokens)
    for needle, label in [
        ("victorian", "Victorian"),
        ("medieval", "medieval"),
        ("ancient", "ancient"),
        ("roman", "Roman"),
        ("egyptian", "Egyptian"),
        ("18th-century", "1800s"),
        ("19th-century", "1900s"),
        ("20th-century", "1900s"),
    ]:
        if needle in lowered:
            return label
    return ""


# ------------------------------------------------------------------ #
# Topic-specific narrative templates
# ------------------------------------------------------------------ #
# Each template returns a list of 5 search queries, one per beat:
# [ESTABLISHING, SUBJECT, DETAIL, CONSEQUENCE, ATMOSPHERE]
# ------------------------------------------------------------------ #

def _t_history(e: Entities, image_hint: str) -> list[str]:
    period = e.period_label or "vintage"
    subject = " ".join(e.proper_nouns[:2]) or " ".join(e.nouns[:2]) or "people"
    action  = e.verbs_present[0] if e.verbs_present else "working"
    detail  = e.nouns[0] if e.nouns else "hands"
    return [
        f"{period} {image_hint or 'archival footage'}",          # establishing
        f"{subject} {period} portrait",                          # subject
        f"{detail} close up vintage {action}",                   # detail
        f"{period} hospital medical archival",                   # consequence
        f"{period} empty room atmospheric dust light",           # atmosphere
    ]


def _t_space(e: Entities, image_hint: str) -> list[str]:
    subject = " ".join(e.proper_nouns[:2]) or e.nouns[0] if e.nouns else "planet"
    return [
        f"{image_hint or 'galaxy stars wide'}",                  # establishing
        f"{subject} space close up",                             # subject
        f"telescope detail close up",                            # detail
        f"earth orbit view from space",                          # consequence
        f"deep space stars time lapse atmospheric",              # atmosphere
    ]


def _t_nature(e: Entities, image_hint: str) -> list[str]:
    subject = e.nouns[0] if e.nouns else (e.proper_nouns[0] if e.proper_nouns else "wildlife")
    action  = e.verbs_present[0] if e.verbs_present else ""
    return [
        f"{image_hint or subject + ' natural habitat wide'}",    # establishing
        f"{subject} portrait close up",                          # subject
        f"{subject} {action} slow motion".strip(),               # detail
        f"forest sunlight wildlife green",                       # consequence
        f"nature atmospheric light dust mist",                   # atmosphere
    ]


def _t_ocean(e: Entities, image_hint: str) -> list[str]:
    # Pull the most specific noun - e.g. "anglerfish", "shark", "whale"
    subject = (e.nouns[0] if e.nouns else None) or (e.proper_nouns[0] if e.proper_nouns else "fish")
    return [
        f"{image_hint or subject + ' deep sea'}",               # establishing - use hint directly
        f"{subject} underwater footage close up",               # subject - force specific name
        f"{subject} bioluminescent dark ocean",                  # detail - species-specific
        f"deep sea fish creature dark",                          # consequence
        f"ocean underwater light rays atmospheric",              # atmosphere
    ]


def _t_tech(e: Entities, image_hint: str) -> list[str]:
    subject = e.nouns[0] if e.nouns else "computer"
    return [
        f"{image_hint or 'data center server room'}",            # establishing
        f"{subject} close up macro",                             # subject
        f"circuit board electronics detail",                     # detail
        f"code screen scrolling green",                          # consequence
        f"technology dark room lights atmospheric",              # atmosphere
    ]


def _t_earth(e: Entities, image_hint: str) -> list[str]:
    subject = e.nouns[0] if e.nouns else "landscape"
    return [
        f"{image_hint or 'aerial drone landscape wide'}",        # establishing
        f"{subject} close up nature",                            # subject
        f"geology rock formation detail",                        # detail
        f"weather clouds time lapse",                            # consequence
        f"earth atmospheric light fog mountains",                # atmosphere
    ]


_TEMPLATES = {
    "history":    _t_history,
    "space":      _t_space,
    "nature":     _t_nature,
    "biology":    _t_nature,
    "ocean":      _t_ocean,
    "tech":       _t_tech,
    "technology": _t_tech,
    "earth":      _t_earth,
}

# ------------------------------------------------------------------ #
# Hint-driven coverage suffixes (one per beat: ESTABLISHING → ATMOSPHERE)
# ------------------------------------------------------------------ #
# The ESTABLISHING beat uses the full hint verbatim (most specific).
# Beats 2-5 append a short coverage modifier to the core subject.
# All queries stay anchored to the same visual theme.
# ------------------------------------------------------------------ #

_BEAT_SUFFIXES: dict[str, list[str]] = {
    "earth":      ["close up detail", "dramatic slow motion", "atmospheric dark sky", "aerial wide"],
    "space":      ["close up surface", "detail texture", "atmospheric glow", "deep space stars wide"],
    "ocean":      ["underwater close up", "slow motion underwater", "deep dark abyss", "ocean surface light"],
    "biology":    ["portrait close up", "macro detail", "slow motion", "natural habitat wide"],
    "nature":     ["portrait close up", "macro detail", "slow motion", "habitat wide"],
    "history":    ["portrait close up", "detail texture", "archival atmospheric", "wide establishing scene"],
    "tech":       ["macro close up", "circuit board detail", "glowing dark room", "wide establishing"],
    "technology": ["macro close up", "circuit board detail", "glowing dark room", "wide establishing"],
}
_DEFAULT_SUFFIXES = ["close up", "detail", "atmospheric", "wide establishing"]


def _core_subject(hint: str) -> str:
    """Return the first 2-3 meaningful words from the hint for variation queries."""
    words = hint.split()
    meaningful = [w for w in words if len(w) > 3]
    # Use first 3 meaningful words, or first 3 words if all are short
    core_words = meaningful[:3] if meaningful else words[:3]
    return " ".join(core_words)


def _expand_hint(hint: str, topic: str) -> list[str]:
    """Expand image_hint into 5 coverage queries, all anchored to the same subject.

    Query 1 (ESTABLISHING) = full hint verbatim - most specific, best for keyword search.
    Queries 2-5 = core subject words + topic-appropriate coverage modifier.
    Every query is about the same thing. None drift to generic topic b-roll.
    """
    hint = hint.strip()
    core = _core_subject(hint)
    suffixes = _BEAT_SUFFIXES.get(topic, _DEFAULT_SUFFIXES)

    queries: list[str] = [hint]
    seen: set[str] = {hint.lower()}
    for suffix in suffixes:
        q = f"{core} {suffix}".strip()
        q = " ".join(q.split())
        if q.lower() not in seen:
            seen.add(q.lower())
            queries.append(q)

    return queries


# ------------------------------------------------------------------ #
# Public API
# ------------------------------------------------------------------ #

def shot_list(claim: str, topic: str, image_hint: str = "") -> list[str]:
    """Return an ordered list of 5 search queries - one per narrative beat.

    Primary path (image_hint present):
      All 5 queries are derived from the image_hint. The ESTABLISHING beat
      uses the full hint; the other 4 use the core subject + coverage
      modifiers. Every query targets the same visual theme.

    Fallback (no image_hint):
      Entity extraction from the claim + topic-specific templates.
      Less reliable - fact bank entries should always have an image_hint.
    """
    hint = image_hint.strip()

    if hint:
        return _expand_hint(hint, topic)

    # Fallback: entity extraction + templates
    e = extract_entities(claim)
    fn = _TEMPLATES.get(topic, _t_history)
    queries = fn(e, "")
    seen: set[str] = set()
    out: list[str] = []
    for q in queries:
        q = " ".join(q.split()).strip()
        if q and q.lower() not in seen:
            seen.add(q.lower())
            out.append(q)
    return out


def beat_label(index: int) -> str:
    """Human-readable label for the beat at this index."""
    labels = ["ESTABLISHING", "SUBJECT", "DETAIL", "CONSEQUENCE", "ATMOSPHERE"]
    return labels[index] if 0 <= index < len(labels) else f"BEAT {index}"
