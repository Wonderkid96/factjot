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


_SYSTEM_PROMPT = """You generate stock footage search queries for a short documentary reel.

The reel script is provided sentence by sentence. For each sentence, produce
3-4 search queries that describe footage which would visually illustrate
THAT SPECIFIC SENTENCE.

CRITICAL RULES:
1. Every query MUST include the specific subject (animal, person, place, object)
   OR its specific environment. Never describe a property alone.
   BAD:  "translucent macro close-up"
   GOOD: "translucent snailfish deep ocean macro"
   BAD:  "pressure extreme environment"
   GOOD: "deep sea fish extreme pressure ocean floor"

2. Queries describe what is LITERALLY VISIBLE: subjects, actions, environments.
   Not emotions, concepts, or abstractions.

3. Each query is 4-8 words.

4. Vary across sentences: use the specific subject for early sentences,
   broaden to environment/atmosphere for later sentences.

5. If the specific footage is unlikely to exist in stock libraries, use the
   closest thematically correct alternative (e.g. "deep sea fish" if no
   snailfish footage exists, NOT a random macro clip).

Return ONLY a JSON object where keys are "0", "1", "2", ... (sentence index)
and values are arrays of 3-4 query strings. Example:
{
  "0": ["snailfish deep ocean floor footage", "deep sea fish trench dark water"],
  "1": ["extreme ocean depth darkness abyss", "underwater pressure deep sea environment"],
  "2": ["deep sea fish translucent body anatomy", "marine biology fish deep water"]
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
        model="claude-haiku-4-5-20251001",
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
