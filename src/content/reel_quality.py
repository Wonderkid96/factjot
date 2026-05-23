"""Code-level quality gates for autonomous reel copy.

Prompts ask for these behaviours, but production needs a hard stop when a
model returns a thin script or awkward title. Keep these checks mechanical:
they should catch obvious failures without trying to replace editorial taste.
"""
from __future__ import annotations

import re

MIN_REEL_WORDS = 70
MAX_REEL_WORDS = 120
MAX_TITLE_CHARS = 70

_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z0-9]+)?")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_YEAR_OR_NUMBER_RE = re.compile(r"\b(?:\d{1,3}(?:,\d{3})+|\d{2,4}|[A-Z]{2,})\b")
_PROPER_NOUN_RE = re.compile(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})*\b")
_TURN_SIGNALS = (
    "but", "because", "despite", "without", "refused", "failed", "lost",
    "accidentally", "burst", "killed", "died", "sank", "collapsed", "exploded", "poisoned",
    "invented", "discovered", "nothing", "nobody", "no one", "never",
    "still", "already", "twice",
)
_BANNED_TITLE_PHRASES = (
    "did you know",
    "you won't believe",
    "mind blowing",
    "mind-blowing",
    "this changed everything",
    "what happened next",
    "little did they know",
)
_AWKWARD_TITLE_PATTERNS = (
    re.compile(r"\bfor\s+\d+\s+(?:man|woman|person|people)\b", re.I),
    re.compile(r"\bthe\s+story\s+of\b", re.I),
    re.compile(r"\bthe\s+history\s+of\b", re.I),
)
_TITLE_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "over",
    "under", "after", "before", "when", "where", "while", "about", "than",
    "then", "they", "them", "their", "his", "her", "its", "your", "our",
    "was", "were", "are", "is", "been", "being", "have", "has", "had",
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "who", "what", "why", "how", "a", "an", "to", "of", "in", "on",
}


def word_count(text: str) -> int:
    return len(_WORD_RE.findall(text or ""))


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_RE.split((text or "").strip()) if s.strip()]


def _content_tokens(text: str) -> set[str]:
    return {
        w.lower()
        for w in _WORD_RE.findall(text or "")
        if len(w) >= 4 and w.lower() not in _TITLE_STOPWORDS
    }


def validate_reel_script(script: str) -> tuple[bool, str]:
    """Return (ok, reason) for an autonomous reel script."""
    script = (script or "").strip()
    wc = word_count(script)
    if wc < MIN_REEL_WORDS:
        return False, f"script too short: {wc} words, minimum {MIN_REEL_WORDS}"
    if wc > MAX_REEL_WORDS:
        return False, f"script too long: {wc} words, maximum {MAX_REEL_WORDS}"

    sentences = _sentences(script)
    if not sentences:
        return False, "script has no complete sentence"
    first = sentences[0]
    first_wc = word_count(first)
    if first_wc < 6:
        return False, "first sentence is too short to carry the hook"
    if first_wc > 32:
        return False, "first sentence is too long; hook must land immediately"

    first_l = first.lower()
    has_concrete_anchor = bool(_YEAR_OR_NUMBER_RE.search(first) or _PROPER_NOUN_RE.search(first))
    has_turn_signal = any(sig in first_l for sig in _TURN_SIGNALS)
    if not (has_concrete_anchor and has_turn_signal):
        return (
            False,
            "first sentence must contain a concrete anchor and the weird bit",
        )
    return True, "ok"


def validate_reel_title(title: str, script: str) -> tuple[bool, str]:
    """Return (ok, reason) for a reel hook-card title."""
    title = (title or "").strip()
    if not title:
        return False, "title is missing"
    if len(title) > MAX_TITLE_CHARS:
        return False, f"title too long: {len(title)} chars, maximum {MAX_TITLE_CHARS}"

    words = _WORD_RE.findall(title)
    if len(words) < 2:
        return False, "title must be at least two words"
    if len(words) > 12:
        return False, "title is too wordy for a hook card"

    lower = title.lower()
    for phrase in _BANNED_TITLE_PHRASES:
        if phrase in lower:
            return False, f"title uses banned phrase: {phrase}"
    for pattern in _AWKWARD_TITLE_PATTERNS:
        if pattern.search(title):
            return False, "title uses an awkward documentary-style shape"

    title_tokens = _content_tokens(title)
    script_tokens = _content_tokens(" ".join(_sentences(script)[:2]) or script)
    if title_tokens and script_tokens and not (title_tokens & script_tokens):
        return False, "title does not connect to the opening subject or weird bit"

    return True, "ok"


def validate_reel_copy(script: str, title: str) -> tuple[bool, str]:
    ok, reason = validate_reel_script(script)
    if not ok:
        return ok, reason
    ok, reason = validate_reel_title(title, script)
    if not ok:
        return ok, reason
    return True, "ok"
