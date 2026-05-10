"""Shorten a reel title into a 4-6 word thumbnail overlay (Phase E.4).

The reel cover overlay (`reel_thumbnail_overlay.html.j2`) carries an
Archivo Black 900 headline in a lower-third PAPER scrim. At ~80px font
size and 60px side padding the line cap is roughly 6 words; longer
titles wrap awkwardly or shrink to unreadable sizes.

This module asks Haiku 4.5 to compress the curated reel title down to
4-6 words while keeping the punchline. Anything <=6 words passes through
unchanged. Soft-fall: on any infra failure we return the first 6 words
of the input so the pipeline never blocks on overlay copy.

Voice rules from `/Users/Music/.claude/CLAUDE.md` and `CLAUDE.md` apply:
no em-dashes, British English, no clickbait shapes ("you won't believe",
"mind-blown", "this changed everything"). The prompt explicitly bans
those shapes; a regex post-check strips obvious leftovers and warns.
"""
from __future__ import annotations

import os
import re


_HAIKU_MODEL = "claude-haiku-4-5-20251001"
_TARGET_WORDS_MIN = 4
_TARGET_WORDS_MAX = 6
_MAX_TOKENS = 60          # tiny: 4-6 words plus a couple of stop tokens
_TEMPERATURE = 0.2

# Clickbait shapes that the prompt bans. Post-check stripper logs a
# warning but does not crash; the soft-fall is "first 6 words of input".
_CLICKBAIT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\byou\s+won'?t\s+believe\b", re.IGNORECASE),
    re.compile(r"\bmind[\s-]?blown\b", re.IGNORECASE),
    re.compile(r"\bmind[\s-]?blowing\b", re.IGNORECASE),
    re.compile(r"\bthis\s+changed\s+everything\b", re.IGNORECASE),
    re.compile(r"\bunbelievable\b", re.IGNORECASE),
    re.compile(r"\bshocking\s+truth\b", re.IGNORECASE),
    re.compile(r"\bwait\s+until\s+you\s+see\b", re.IGNORECASE),
)


def _word_count(text: str) -> int:
    """Count whitespace-separated tokens. Empty -> 0."""
    return len([w for w in text.strip().split() if w])


def _strip_clickbait(text: str) -> tuple[str, list[str]]:
    """Remove clickbait phrases, return (cleaned, list_of_hits).

    Hits are returned so the caller can log a warning that Haiku ignored
    the rule. We do not abort on a hit — the soft-fall covers that case
    when the resulting string is empty.
    """
    cleaned = text
    hits: list[str] = []
    for pat in _CLICKBAIT_PATTERNS:
        m = pat.search(cleaned)
        if m:
            hits.append(m.group(0))
            cleaned = pat.sub("", cleaned)
    # Collapse double-spaces that the substitution may have left behind.
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,;:")
    return cleaned, hits


def _soft_fallback(reel_title: str) -> str:
    """Return the first 6 words of the input, lower-case if input was lower-case.

    Used when api_key is empty, when Haiku raises, or when Haiku returns
    an empty / clickbait-only string. Mirrors the case of the input so a
    lower-case title stays lower-case.
    """
    words = (reel_title or "").strip().split()
    if not words:
        return ""
    short = " ".join(words[:_TARGET_WORDS_MAX])
    # Strip a stray trailing period; the overlay template adds its own
    # accent dot via CSS where appropriate.
    return short.rstrip(".")


def _build_prompt(reel_title: str) -> str:
    """Compose the headline-shortener prompt sent to Haiku.

    The wording mirrors the spec in
    `docs/superpowers/plans/2026-05-10-factjot-audit-implementation.md`
    §6 Phase E.4 — do not rewrite without a paired spec change.
    """
    return (
        "Shorten this reel title to 4-6 words for a thumbnail overlay. "
        "Preserve the specific noun/verb that makes it interesting. "
        "No clickbait shapes. No \"you won't believe\" or \"mind-blown\". "
        "No em-dashes (use commas or rewrite). British English. "
        "Lower-case if the input is lower-case. "
        "Return ONLY the shortened title, no quotation marks, no commentary.\n\n"
        f"Original: \"{reel_title.strip()}\""
    )


def build_thumbnail_headline(
    reel_title: str,
    api_key: str = "",
) -> str:
    """Return a 4-6 word version of `reel_title` suited to the cover overlay.

    Parameters
    ----------
    reel_title
        The curated reel title from `fact["reel_title"]` or the auto-built
        title from `make_title(...)`. Empty string is returned as-is.
    api_key
        Anthropic API key. Empty string -> soft-fall to first 6 words of
        the input. Falling back is normal on a developer machine without
        credentials; production CI always has the key.

    Returns
    -------
    str
        A short headline suitable for the Archivo Black overlay. May be
        identical to the input when the input is already <=6 words.
    """
    text = (reel_title or "").strip()
    if not text:
        return ""

    # Already short enough — pass through. Saves a Haiku call on every
    # short curated title.
    if _word_count(text) <= _TARGET_WORDS_MAX:
        return text.rstrip(".")

    # Resolve API key from env if not supplied.
    api_key = (api_key or os.getenv("ANTHROPIC_API_KEY", "")).strip()
    if not api_key:
        return _soft_fallback(text)

    try:
        from anthropic import Anthropic
    except ImportError:
        return _soft_fallback(text)

    prompt = _build_prompt(text)

    try:
        client = Anthropic(api_key=api_key)
        res = client.messages.create(
            model=_HAIKU_MODEL,
            max_tokens=_MAX_TOKENS,
            temperature=_TEMPERATURE,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        print(f"  [thumb-headline] Haiku error, soft-falling: {str(exc)[:80]}")
        return _soft_fallback(text)

    raw = ""
    try:
        raw = (res.content[0].text or "").strip()
    except (AttributeError, IndexError):
        raw = ""

    # Strip wrapping quotes that models sometimes add despite "no quotation
    # marks" instruction.
    raw = raw.strip("\"'`")
    # Drop trailing period (overlay adds its own).
    raw = raw.rstrip(".")

    # Clickbait check: strip phrases the prompt banned, log if any hit.
    cleaned, hits = _strip_clickbait(raw)
    if hits:
        print(
            f"  [thumb-headline] WARNING: Haiku returned banned clickbait phrase(s): "
            f"{hits}; stripped and continuing"
        )

    if not cleaned or _word_count(cleaned) == 0:
        return _soft_fallback(text)

    # Cap at 6 words even if Haiku ignored the upper bound. Floor of 4
    # is aspirational, not enforced (Haiku occasionally returns 3 strong
    # words; that beats a forced 4-word version).
    words = cleaned.split()
    if len(words) > _TARGET_WORDS_MAX:
        cleaned = " ".join(words[:_TARGET_WORDS_MAX])

    # Mirror input case: if the original was all lower-case (no upper-case
    # alpha chars at all), keep the result lower-case too.
    if not any(c.isupper() for c in text):
        cleaned = cleaned.lower()

    return cleaned
