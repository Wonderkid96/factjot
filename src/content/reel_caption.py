"""Build Instagram caption for a Reel."""
from __future__ import annotations

import os
import random
import re
from urllib.parse import urlparse

from src.content.hashtag_builder import build_hashtags
from src.content.voice_normaliser import normalise

_CTAS = [
    "Follow @factjot for more facts like this.",
    "Follow @factjot for a new fact every day.",
    "More where that came from. Follow @factjot.",
    "Follow @factjot for your daily fact.",
    "Want more? Follow @factjot.",
    "Daily facts at @factjot. Follow to keep learning.",
    "This one stopped me. Follow @factjot for more.",
]

# Dialogue hooks: comments and saves outrank follows in distribution.
# Dry, factjot-voice invitations only; no begging, no "smash that".
_ENGAGEMENT_LINES = [
    "If you already knew this, say so in the comments. We will be impressed and suspicious.",
    "Know a stranger fact? Comments are open.",
    "Save this for the next quiet dinner party.",
    "Send this to someone who thinks they know things.",
    "Argue about it in the comments. Politely.",
    "Save it. You will want this one later.",
]


# Brand-voice normalisation (em / en dashes, smart quotes, spacing) lives
# in src.content.voice_normaliser.normalise(). The local _strip_em_dashes
# helper was removed 2026-05-10 (Phase C of the audit) when the
# normaliser became the single shared entrypoint for every caption
# builder. Apply normalise() to the assembled caption right before we
# return it from build_reel_caption.

# Hashtag generation moved entirely to src.content.hashtag_builder.build_hashtags()
# (Haiku-generated, topic-specific) on 2026-05-09 per audit Q8. The previous
# static _TOPIC_TAGS / _DEFAULT_TOPIC / _BRAND_TAGS / _STOP / _subject_hashtags
# helpers were deferred for cleanup in Phase B; deleted now since no caller
# references them and ruff's F841 selection set does not catch module-level
# dead names.

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


_WORD_RE = re.compile(r"[a-z0-9]+")


def _content_words(text: str) -> set[str]:
    """Return content words (4+ chars, lowercased) for overlap detection."""
    return {w for w in _WORD_RE.findall(text.lower()) if len(w) >= 4}


def _punchline(claim: str, title: str | None) -> str:
    """Return the single most striking sentence from the claim, distinct
    from the title.

    If a title is set, skip the first sentence (used as hook already)
    and return the next sentence that does NOT repeat the title's
    content words. The IG caption first line is what shows before the
    "more" cut, so a sentence that paraphrases the title wastes that
    real estate. Falls back to the second sentence if no later sentence
    is sufficiently distinct.
    """
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", claim.strip()) if s.strip()]
    if title and len(sentences) > 1:
        title_words = _content_words(title)
        line = sentences[1]
        if title_words:
            # Try sentences 1..N in order; pick the first whose content
            # words are <50% overlap with the title.
            for cand in sentences[1:]:
                cand_words = _content_words(cand)
                if not cand_words:
                    continue
                overlap = len(title_words & cand_words) / max(len(cand_words), 1)
                if overlap < 0.5:
                    line = cand
                    break
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
    share_hook: str | None = None,
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

    body   = _punchline(claim, reel_title)
    # Agent-supplied share hook ("Send this to someone who...") takes priority
    # over the generic engagement pool. Falls back when the agent omits it.
    engage = share_hook.strip() if share_hook and share_hook.strip() else random.choice(_ENGAGEMENT_LINES)
    cta    = random.choice(_CTAS)

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

    parts = [hook, body, "", engage, "", cta, "", "\n".join(credit_lines), "", hashtags]
    caption = "\n".join(parts)
    caption = normalise(caption)
    return caption[:2200]
