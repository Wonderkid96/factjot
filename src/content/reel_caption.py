"""Build Instagram caption for a Reel."""
from __future__ import annotations

import os
import random
import re
from urllib.parse import urlparse

from src.content.hashtag_builder import build_hashtags

_CTAS = [
    "Follow @factjot for more facts like this.",
    "Follow @factjot for a new fact every day.",
    "More where that came from. Follow @factjot.",
    "Follow @factjot for your daily fact.",
    "Want more? Follow @factjot.",
    "Daily facts at @factjot. Follow to keep learning.",
    "This one stopped me. Follow @factjot for more.",
]


# Hard rule: no em-dashes anywhere in caption output.
# Brand voice convention. Catch any em-dash that slips through string
# concatenation (sources, titles, music credits, etc).
# Sentinels are constructed at runtime via codepoint so the source itself
# stays clean for the targeted em-dash linter (scripts/check_em_dashes.py).
_EM_DASH = chr(0x2014)  # U+2014 EM DASH
_EN_DASH = chr(0x2013)  # U+2013 EN DASH


def _strip_em_dashes(text: str) -> str:
    return text.replace(_EM_DASH, ",").replace(_EN_DASH, ",")

# _BROAD removed 2026-05-09 per audit Q8 decision: hashtags now flow only
# through build_hashtags() which generates topic-specific tags via Haiku.
# The other dead constants below (_TOPIC_TAGS, _DEFAULT_TOPIC, _BRAND_TAGS,
# _STOP, _subject_hashtags) are unused but left for Phase B's ruff lint pass.

# Tier 2: topic-specific
_TOPIC_TAGS: dict[str, str] = {
    "space":      "#space #astronomy #universe #cosmos #nasa",
    "earth":      "#earth #geology #nature #earthscience #geography",
    "ocean":      "#ocean #marinelife #deepocean #oceanography #sealife",
    "biology":    "#biology #nature #wildlife #science #evolution",
    "nature":     "#nature #wildlife #animals #ecology #science",
    "history":    "#history #historyfacts #truecrime #historical #archive",
    "technology": "#technology #tech #innovation #engineering #science",
    "tech":       "#technology #tech #innovation #engineering #science",
    "science":    "#science #neuroscience #psychology #brain #learning",
}
_DEFAULT_TOPIC = "#science #nature #history #facts #learning"

# Always appended
_BRAND_TAGS = "#factjot #dailyfact"

# Words to ignore when extracting subject hashtags
_STOP = frozenset({
    "a", "an", "the", "in", "on", "at", "to", "for", "of", "and", "or",
    "but", "is", "was", "are", "were", "be", "been", "have", "had", "has",
    "do", "did", "does", "will", "would", "could", "should", "that", "this",
    "with", "from", "as", "by", "he", "she", "it", "they", "his", "her",
    "its", "their", "who", "which", "when", "where", "not", "no", "can",
    "so", "if", "about", "after", "before", "than", "also", "just", "only",
    "more", "may", "most", "some", "such", "even", "still", "then", "each",
    "every", "both", "all", "any", "many", "same", "own", "over", "between",
    "through", "during", "without", "however", "although", "while", "because",
    "since", "once", "until", "unless", "roughly", "nearly", "almost",
    "around", "early", "late", "first", "last", "next", "never", "always",
    "often", "used", "made", "said", "found", "came", "went", "took", "came",
    "began", "ended", "killed", "lived", "died", "went", "sent", "kept",
    "force", "years", "days", "time", "world", "people", "known", "human",
    "entire", "single", "whole", "large", "small", "long", "short", "high",
    # Common weak verbs that slip through
    "erupted", "reduced", "painted", "glowed", "called", "compels", "found",
    "created", "started", "ended", "become", "became", "happened", "appear",
    "appears", "remains", "remained", "believed", "thought", "estimated",
    "shows", "causes", "allows", "makes", "gives", "takes", "holds", "keeps",
    # Generic nouns too broad to be useful as niche tags
    "thing", "place", "story", "event", "moment", "record", "result", "point",
    "example", "reason", "matter", "system", "process", "effect", "impact",
})


def _subject_hashtags(claim: str, title: str | None, topic: str) -> str:
    """Extract 4-5 subject-specific hashtags from the claim and title.

    Uses individual proper nouns and key content words, not multi-word
    phrases which produce garbage like #EruptionEnded. Niche tags reach
    people who care specifically about this subject.
    """
    # Use claim only - title is already the hook and its words are redundant as tags
    sentences = re.split(r"(?<=[.!?])\s+", claim.strip())
    text = " ".join(sentences[:2])
    tokens = text.split()

    tags: list[str] = []
    seen: set[str] = set()

    # Pass 1: individual proper nouns - capitalised mid-sentence only.
    # Skip i=0 (first word of text) and skip words that follow sentence-final
    # punctuation (they're sentence-starters, not proper nouns).
    for i, tok in enumerate(tokens):
        clean = tok.strip(".,;:!?\"'()")
        prev_ends_sentence = i > 0 and tokens[i - 1].rstrip("\"'") [-1:] in ".!?"
        if (
            i > 0
            and not prev_ends_sentence
            and clean
            and clean[0].isupper()
            and len(clean) >= 4
            and clean.lower() not in _STOP
            and re.match(r"^[A-Za-z]+$", clean)
        ):
            tag = f"#{clean}"
            if tag.lower() not in seen:
                seen.add(tag.lower())
                tags.append(tag)
        if len(tags) >= 3:
            break

    # Pass 2: significant lowercase content words (6+ chars, not generic)
    for tok in tokens:
        clean = tok.strip(".,;:!?\"'()").lower()
        if (
            len(clean) >= 6
            and clean not in _STOP
            and re.match(r"^[a-z]+$", clean)
        ):
            tag = f"#{clean}"
            if tag.lower() not in seen:
                seen.add(tag.lower())
                tags.append(tag)
        if len(tags) >= 5:
            break

    return " ".join(tags[:5])


# Publisher name overrides for common domains
_PUBLISHER_NAMES: dict[str, str] = {
    "smithsonianmag.com":     "Smithsonian Magazine",
    "britannica.com":         "Encyclopaedia Britannica",
    "nationalgeographic.com": "National Geographic",
    "nasa.gov":               "NASA",
    "bbc.com":                "BBC",
    "bbc.co.uk":              "BBC",
    "nature.com":             "Nature Journal",
    "science.org":            "Science",
    "nhm.ac.uk":              "Natural History Museum",
    "noaa.gov":               "NOAA",
    "scientificamerican.com": "Scientific American",
    "atlasobscura.com":       "Atlas Obscura",
    "newscientist.com":       "New Scientist",
    "usgs.gov":               "USGS",
    "nps.gov":                "National Park Service",
    "mbari.org":              "MBARI",
    "seti.org":               "SETI Institute",
}


def _source_credit(sources: list[str]) -> str:
    publishers: list[str] = []
    seen: set[str] = set()
    for url in sources[:2]:
        try:
            host = urlparse(url).netloc.lower().lstrip("www.")
            name = next(
                (v for k, v in _PUBLISHER_NAMES.items() if host.endswith(k)),
                host.split(".")[0].capitalize(),
            )
            if name not in seen:
                seen.add(name)
                publishers.append(name)
        except Exception:
            pass
    return "📚 Source: " + " | ".join(publishers) if publishers else ""


def _punchline(claim: str, title: str | None) -> str:
    """Return the single most striking sentence from the claim.

    If a title is set, skip the first sentence (used as hook already)
    and return the second. Otherwise return a compressed version of
    the first sentence.
    """
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", claim.strip()) if s.strip()]
    if title and len(sentences) > 1:
        line = sentences[1]
    else:
        line = sentences[0]
    # Trim to 160 chars
    if len(line) > 160:
        line = line[:157] + "..."
    return line


def build_reel_caption(
    claim: str,
    topic: str,
    reel_title: str | None = None,
    sources: list[str] | None = None,
) -> str:
    """Return a complete, credit-bearing caption ready to post."""

    # Hook
    if reel_title:
        hook = reel_title.strip().rstrip(".")
        hook += "."
    else:
        hook = claim.split(".")[0].strip()
        if not hook.endswith((".", "!", "?")):
            hook += "."

    body = _punchline(claim, reel_title)
    cta  = random.choice(_CTAS)

    # Credits
    credit_lines: list[str] = []
    src = _source_credit(sources or [])
    if src:
        credit_lines.append(src)
    credit_lines.append("📹 Footage: Pexels.com")
    music = os.getenv("MUSIC_CREDIT", "").strip()
    if music:
        credit_lines.append(f"🎵 Music: {music}")

    hashtags = build_hashtags(
        summary=f"{reel_title or ''} {claim}".strip(),
        topic=topic,
        post_type="reel",
    )

    parts = [hook, body, "", cta, "", "\n".join(credit_lines), "", hashtags]
    caption = "\n".join(parts)
    caption = _strip_em_dashes(caption)
    return caption[:2200]
