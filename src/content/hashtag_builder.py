"""Generate relevant, content-specific Instagram hashtags via Claude Haiku.

~$0.001 per call. Falls back to static topic buckets on API failure.
"""
from __future__ import annotations

import os
import re

# Single brand anchor only. Engagement-bait tags (#didyouknow, #mindblown,
# #interestingfacts, #learnontiktok, #fyp, #viral, #trending) stripped 2026-05-09
# per audit Q8 decision. The agent prompt bans these as voice antagonists; they
# can no longer ship via the hashtag builder either.
_BRAND = "#factjot"

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


def build_hashtags(
    summary: str,
    topic: str = "",
    post_type: str = "fact",
    api_key: str = "",
) -> str:
    """Return a ready-to-append hashtag string for an Instagram post.

    Generates 15 content-specific tags via Claude Haiku, then appends the
    single #factjot brand anchor. Falls back to static topic buckets if the
    API call fails or returns garbage.
    """
    api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key or not summary.strip():
        return _fallback(topic, post_type)

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        prompt = (
            "Generate exactly 15 Instagram hashtags for this post. Rules:\n"
            "- Mix: 3-4 viral broad tags (>5M posts each), 5-6 topic-specific (500k-5M posts), 4-5 niche tags (<500k posts)\n"
            "- Specific to the content, not generic filler (#amazing, #love, #instagood etc)\n"
            "- No spaces within a hashtag. Include the # symbol.\n"
            "- Do NOT include #factjot (added separately as the only brand anchor)\n"
            "- Do NOT use #didyouknow #mindblown #interestingfacts #learnontiktok #fyp #viral #trending or other engagement-bait tags\n"
            "- Return ONLY the space-separated hashtag string, nothing else\n\n"
            f"Post type: {post_type}\n"
            f"Topic: {topic or 'general'}\n"
            f"Content: {summary[:500]}"
        )
        res = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            temperature=0.4,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = res.content[0].text.strip()
        tags = [
            t for t in raw.split()
            if t.startswith("#") and re.match(r"^#[A-Za-z][A-Za-z0-9_]*$", t)
        ]
        if len(tags) >= 8:
            return " ".join(tags[:20]) + " " + _BRAND
    except Exception:
        pass

    return _fallback(topic, post_type)


def _fallback(topic: str, post_type: str) -> str:
    key = topic.lower() if topic else post_type.lower()
    block = _FALLBACK.get(key) or _FALLBACK.get(post_type) or _FALLBACK["fact"]
    return f"{block} {_BRAND}"
