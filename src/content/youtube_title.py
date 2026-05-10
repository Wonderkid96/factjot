"""Build a Shorts-shaped, keyword-leading YouTube title (Phase F).

Per the YouTube-as-revenue principle and Q7's full-divergence decision,
the YouTube Short gets its own title rather than reusing the IG hook
verbatim. The Shorts title is search-tuned: the most-searchable noun
leads the line, length is 60-100 characters, and clickbait shapes are
banned.

Soft-fall ladder (every infra issue is non-fatal -- worst case the
upload uses the IG `reel_title`, capped at 100 chars to satisfy YouTube
API limits):

    api_key empty                         -> truncated reel_title
    Anthropic SDK import failure          -> truncated reel_title
    Anthropic API exception               -> truncated reel_title
    Haiku returned only banned phrases    -> truncated reel_title
    Haiku returned empty / malformed      -> truncated reel_title

Voice rules from `/Users/Music/.claude/CLAUDE.md` and `CLAUDE.md` apply:
no em-dashes, British English, no clickbait shapes.
"""
from __future__ import annotations

import os
import re

from src.content.voice_normaliser import normalise


_HAIKU_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 80
_TEMPERATURE = 0.3

# YouTube hard cap. We aim for the 60-100 band; the API will accept up
# to 100 chars regardless.
_YT_TITLE_HARD_CAP = 100
_TARGET_MIN_CHARS = 60

# Clickbait shapes the prompt bans. Same set as the description module
# plus a stronger guard against question-shaped openers ("did you know").
_CLICKBAIT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\byou\s+won'?t\s+believe\b", re.IGNORECASE),
    re.compile(r"\bmind[\s-]?blown\b", re.IGNORECASE),
    re.compile(r"\bmind[\s-]?blowing\b", re.IGNORECASE),
    re.compile(r"\bthis\s+changed\s+everything\b", re.IGNORECASE),
    re.compile(r"\bdid\s+you\s+know\b", re.IGNORECASE),
    re.compile(r"\bunbelievable\b", re.IGNORECASE),
    re.compile(r"\bshocking\s+truth\b", re.IGNORECASE),
    re.compile(r"\bwait\s+until\s+you\s+see\b", re.IGNORECASE),
)


def _strip_clickbait(text: str) -> tuple[str, list[str]]:
    """Remove clickbait phrases. Returns (cleaned, hits).

    Hits are returned so the caller can warn that Haiku ignored the
    rule. The fallback path activates if the cleaned title is empty.
    """
    cleaned = text
    hits: list[str] = []
    for pat in _CLICKBAIT_PATTERNS:
        m = pat.search(cleaned)
        if m:
            hits.append(m.group(0))
            cleaned = pat.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,;:")
    return cleaned, hits


def _truncated_fallback(reel_title: str) -> str:
    """Return the IG title trimmed to YouTube's 100-char cap.

    Used whenever Haiku cannot run. Mirrors the previous behaviour, so
    the upload never blocks just because the description/title pipeline
    is degraded.
    """
    text = (reel_title or "").strip()
    if not text:
        return ""
    if len(text) <= _YT_TITLE_HARD_CAP:
        return normalise(text)
    return normalise(text[:_YT_TITLE_HARD_CAP].rstrip())


def _build_prompt(reel_title: str, claim: str) -> str:
    """Compose the title-writer prompt sent to Haiku."""
    return (
        "Write a YouTube Shorts title for a factjot reel. "
        "60-100 characters max. Keyword-leading (start with the most "
        "searchable noun).\n\n"
        f"Reel title (the IG version): \"{reel_title.strip()}\"\n"
        f"Claim: \"{claim.strip()}\"\n\n"
        "Rules:\n"
        "- Lead with the noun/subject, not \"How\" / \"Why\" / "
        "\"The story of\".\n"
        "- Be specific. Use proper nouns and dates if they exist in the claim.\n"
        "- No clickbait. No \"you won't believe\", \"mind-blowing\", "
        "\"this changed everything\".\n"
        "- British English. No em-dashes.\n"
        "- 60-100 characters total.\n\n"
        "Return only the title."
    )


def build_shorts_title(
    reel_title: str,
    claim: str,
    api_key: str = "",
) -> str:
    """Return a 60-100 char keyword-leading Shorts title.

    Parameters
    ----------
    reel_title
        The IG-shaped reel title (curated or auto). Used as input
        context for Haiku and as the truncation source for soft-fall.
    claim
        The full fact claim. Used by Haiku to lift proper nouns and
        dates into the title.
    api_key
        Anthropic API key. Empty falls through to the truncated-title
        fallback.

    Returns
    -------
    str
        A YouTube-ready title. Always non-empty when `reel_title` is
        non-empty. May exceed 100 chars only on the deterministic
        fallback path when the IG title itself is shorter than the cap.
    """
    text = (reel_title or "").strip()
    if not text:
        return ""

    api_key = (api_key or os.getenv("ANTHROPIC_API_KEY", "")).strip()
    if not api_key:
        return _truncated_fallback(text)

    try:
        from anthropic import Anthropic
    except ImportError:
        return _truncated_fallback(text)

    prompt = _build_prompt(text, claim or "")

    try:
        client = Anthropic(api_key=api_key)
        res = client.messages.create(
            model=_HAIKU_MODEL,
            max_tokens=_MAX_TOKENS,
            temperature=_TEMPERATURE,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        print(f"  [yt-title] Haiku error, soft-falling: {str(exc)[:80]}")
        return _truncated_fallback(text)

    raw = ""
    try:
        raw = (res.content[0].text or "").strip()
    except (AttributeError, IndexError):
        raw = ""

    raw = raw.strip("\"'`").rstrip(".")

    cleaned, hits = _strip_clickbait(raw)
    if hits:
        print(
            f"  [yt-title] WARNING: Haiku returned banned clickbait phrase(s): "
            f"{hits}; stripped and continuing"
        )

    if not cleaned:
        return _truncated_fallback(text)

    # Length sanity. If Haiku gave us something far too short (< 20 chars)
    # or far too long (> hard cap), prefer the deterministic fallback or
    # truncate respectively.
    if len(cleaned) < 20:
        return _truncated_fallback(text)
    if len(cleaned) > _YT_TITLE_HARD_CAP:
        cleaned = cleaned[:_YT_TITLE_HARD_CAP].rstrip()

    return normalise(cleaned)


__all__ = ["build_shorts_title", "_TARGET_MIN_CHARS", "_YT_TITLE_HARD_CAP"]
