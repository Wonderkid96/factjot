"""Generate relevant, content-specific Instagram hashtags via the local claude CLI.

Falls back to static topic buckets on any infra failure.
"""
from __future__ import annotations

import os
import re

from src.core.claude_cli import call_claude_cli

# Single brand anchor only. Engagement-bait tags (#didyouknow, #mindblown,
# #interestingfacts, #learnontiktok, #fyp, #viral, #trending) stripped 2026-05-09
# per audit Q8 decision. The agent prompt bans these as voice antagonists; they
# can no longer ship via the hashtag builder either.
_BRAND = "#factjot"
_MODEL = "sonnet"

_FALLBACK: dict[str, str] = {
    "news":     "#worldnews #currentevents #journalism #media",
    "film":     "#filmrecs #moviestowatch #cinephile #filmtwitter #movienight #watchlist #filmcommunity",
    "reel":     "#todayilearned #knowledge #educational",
    "fact":     "#todayilearned #knowledge #educational",
    "history":  "#history #historyfacts #historical #archive #historynerds #ancienthistory",
    "science":  "#science #neuroscience #psychology #brain #learning #sciencefacts #stemfacts",
    "space":    "#space #astronomy #universe #cosmos #nasa #spacefacts #astrophysics",
    "ocean":    "#ocean #marinelife #deepocean #oceanography #sealife #marinebiology",
    "nature":   "#nature #wildlife #animals #ecology #biology #naturefacts",
    "tech":     "#technology #tech #innovation #engineering #techfacts #programming",
    "internet": "#internethistory #technews #tech #digitalculture",
}

_SCHEMA = {
    "type": "object",
    "properties": {
        "hashtags": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["hashtags"],
    "additionalProperties": False,
}


def build_hashtags(summary: str, topic: str = "", post_type: str = "fact") -> str:
    """Return a ready-to-append hashtag string for an Instagram post.

    Generates 15 content-specific tags, then appends the single #factjot
    brand anchor. Falls back to static topic buckets if the CLI call fails
    or returns garbage.
    """
    if not summary.strip():
        return _fallback(topic, post_type)

    prompt = (
        "Generate exactly 15 Instagram hashtags for this post. Rules:\n"
        "- Mix: 3-4 viral broad tags (>5M posts each), 5-6 topic-specific (500k-5M posts), 4-5 niche tags (<500k posts)\n"
        "- Specific to the content, not generic filler (#amazing, #love, #instagood etc)\n"
        "- The 4-5 niche tags MUST reference the specific subject, era, country, industry, or named entity in the post. Generic category tags (#militaryhistory, #animalfacts) do not count as niche unless they are the most specific level available for this content.\n"
        "- No spaces within a hashtag. Include the # symbol.\n"
        "- Do NOT include #factjot (added separately as the only brand anchor)\n"
        "- Do NOT use #didyouknow #mindblown #interestingfacts #learnontiktok #fyp #viral #trending or other engagement-bait tags\n\n"
        f"Post type: {post_type}\n"
        f"Topic: {topic or 'general'}\n"
        f"Content: {summary[:500]}"
    )

    envelope = call_claude_cli(prompt, model=_MODEL, json_schema=_SCHEMA)
    if envelope is not None:
        raw_tags = (envelope.get("structured_output") or {}).get("hashtags") or []
        tags = [
            t for t in raw_tags
            if isinstance(t, str) and re.match(r"^#[A-Za-z][A-Za-z0-9_]*$", t)
        ]
        if len(tags) >= 8:
            return " ".join(tags[:20]) + " " + _BRAND

    return _fallback(topic, post_type)


def _fallback(topic: str, post_type: str) -> str:
    key = topic.lower() if topic else post_type.lower()
    block = _FALLBACK.get(key) or _FALLBACK.get(post_type) or _FALLBACK["fact"]
    return f"{block} {_BRAND}"
