"""Generate visually grounded stock footage search queries per script sentence.

One Claude Haiku call per reel splits the reel script into sentences and
generates 3-4 footage search queries per sentence. Queries describe what
footage would visually illustrate that specific line of the script --
not abstract beat labels.

Falls back to regex expansion from narrative_beats when Claude is unavailable.
"""
from __future__ import annotations

import json
import os
import re

_ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001").strip()


_SYSTEM_PROMPT = """Create stock footage search queries for a short documentary reel.

Input:
- Topic
- Subject hint
- Script sentences (numbered)

Task:
- For each sentence, return 3-4 search queries that show what that sentence looks like on screen.

Rules:
1. Keep queries visual and concrete (subject, action, place).
2. Include the real subject or its true environment.
3. No abstract words (no "mystery", "destiny", "symbolic", etc).
4. 4-8 words per query.
5. If exact footage is rare, use the closest correct alternative, never random B-roll.
6. Early sentences should be subject-first, later ones can widen to context.

Output format:
- Return JSON only.
- Keys must be "0", "1", "2", ... (sentence index).
- Values must be arrays of query strings.

Example:
{
  "0": ["snailfish deep ocean floor footage", "deep sea fish trench dark water"],
  "1": ["underwater pressure deep sea environment", "deep ocean abyss fish habitat"],
  "2": ["marine biology fish close up", "deep sea life low light footage"]
}"""


def generate_all_beat_queries(
    claim: str,
    topic: str,
    image_hint: str,
    reel_script: str = "",
) -> list[list[str]]:
    """Generate footage search queries driven by the reel script sentences.

    Returns list[list[str]] -- one list of queries per sentence (up to 8).
    Falls back to regex queries silently if Claude unavailable or fails.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if api_key and reel_script:
        try:
            result = _claude_queries(api_key, claim, topic, image_hint, reel_script)
            if result and len(result) >= 3:
                total = sum(len(q) for q in result)
                print(f"  [intents] Claude: {len(result)} sentence slots, {total} queries")
                return result
        except Exception as exc:
            print(f"  [intents] Claude failed ({exc}), using regex fallback")

    return _regex_fallback(claim, topic, image_hint)


def _split_sentences(script: str, max_sentences: int = 8) -> list[str]:
    """Split script into sentences, capped at max_sentences."""
    # Split on sentence boundaries, keep non-empty sentences
    raw = re.split(r'(?<=[.!?])\s+', script.strip())
    sentences = [s.strip() for s in raw if s.strip() and len(s.split()) >= 3]
    return sentences[:max_sentences]


def _claude_queries(
    api_key: str,
    claim: str,
    topic: str,
    image_hint: str,
    reel_script: str,
) -> list[list[str]]:
    import anthropic

    sentences = _split_sentences(reel_script, max_sentences=8)
    if not sentences:
        return []

    numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(sentences))
    user_content = (
        f"Topic: {topic}\n"
        f"Subject hint: {image_hint}\n\n"
        f"Script sentences:\n{numbered}"
    )

    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=_ANTHROPIC_MODEL,
        max_tokens=900,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )
    raw = resp.content[0].text.strip()

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    data = json.loads(raw)
    result: list[list[str]] = []
    for i in range(len(sentences)):
        queries = data.get(str(i), [])
        if isinstance(queries, list):
            clean = [str(q).strip() for q in queries if str(q).strip()][:6]
            result.append(clean)
        else:
            result.append([])
    return result


def _regex_fallback(claim: str, topic: str, image_hint: str) -> list[list[str]]:
    """Fallback: expand existing regex shot_list + hint + topic generics."""
    from src.research.narrative_beats import shot_list, _expand_hint
    from src.research.video_finder import _TOPIC_GENERIC

    shot_queries = shot_list(claim=claim, topic=topic, image_hint=image_hint)
    hint_expansions = _expand_hint(image_hint, topic) if image_hint else []
    topic_fallbacks = _TOPIC_GENERIC.get(topic, [])

    result: list[list[str]] = []
    for beat_idx in range(5):
        pool: list[str] = []
        if beat_idx < len(shot_queries):
            pool.append(shot_queries[beat_idx])
        pool.extend(hint_expansions)
        pool.extend(topic_fallbacks)

        seen: set[str] = set()
        unique: list[str] = []
        for q in pool:
            if q.lower() not in seen:
                seen.add(q.lower())
                unique.append(q)
        result.append(unique[:8])

    return result
