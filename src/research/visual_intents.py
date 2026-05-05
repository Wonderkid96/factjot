"""Generate visually grounded stock footage search queries per beat.

One Claude Haiku call per reel produces 8-10 queries for each of the 5 beats.
Queries describe what is literally visible on screen (subjects, actions,
environment, cinematic style) rather than abstract keywords or topic labels.

Falls back to regex expansion from narrative_beats when Claude is unavailable
so no reel is ever blocked by this layer.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


_BEAT_LABELS = ["ESTABLISHING", "SUBJECT", "DETAIL", "CONSEQUENCE", "ATMOSPHERE"]

_SYSTEM_PROMPT = """You generate stock footage search queries for a short documentary reel.

For each beat, produce 9 search queries. Queries must describe WHAT IS LITERALLY
VISIBLE on screen: subjects, actions, environment, lighting, camera style.

Rules:
- Each query is 4-8 words
- Describe visual content, not abstract concepts or emotions
- Include subject names where relevant (person, place, animal, object)
- Vary scale: include close-up, medium shot, wide shot, aerial
- Queries should get broader as the list progresses (specific → thematic → atmospheric)
- Later queries can relax to environmental or stylistic if specific footage is unlikely

Good: "octopus tentacles coral reef macro slow motion"
Bad: "marine intelligence biology underwater"

Good: "1940s scientist laboratory metal sphere glowing"
Bad: "nuclear weapons research danger"

Return ONLY a JSON object with exactly these 5 keys:
ESTABLISHING, SUBJECT, DETAIL, CONSEQUENCE, ATMOSPHERE
Each key maps to an array of 9 strings."""


def generate_all_beat_queries(
    claim: str,
    topic: str,
    image_hint: str,
    reel_script: str = "",
) -> list[list[str]]:
    """Generate 8-10 footage search queries for each of the 5 beats.

    Returns list[list[str]] indexed by beat (0=ESTABLISHING ... 4=ATMOSPHERE).
    Falls back to regex queries silently if Claude unavailable or fails.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if api_key:
        try:
            result = _claude_queries(api_key, claim, topic, image_hint, reel_script)
            if result and len(result) == 5:
                print(f"  [intents] Claude generated queries for {sum(len(q) for q in result)} slots")
                return result
        except Exception as exc:
            print(f"  [intents] Claude failed ({exc}), using regex fallback")

    return _regex_fallback(claim, topic, image_hint)


def _claude_queries(
    api_key: str,
    claim: str,
    topic: str,
    image_hint: str,
    reel_script: str,
) -> list[list[str]]:
    import anthropic

    script_excerpt = (reel_script[:600] + "...") if len(reel_script) > 600 else reel_script
    user_content = (
        f"Topic: {topic}\n"
        f"Claim: {claim}\n"
        f"Image hint: {image_hint}\n"
        f"Script:\n{script_excerpt}"
    )

    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )
    raw = resp.content[0].text.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    data = json.loads(raw)
    result = []
    for label in _BEAT_LABELS:
        queries = data.get(label, [])
        if isinstance(queries, list):
            # Coerce to strings, drop blanks, cap at 12
            clean = [str(q).strip() for q in queries if str(q).strip()][:12]
            result.append(clean)
        else:
            result.append([])
    return result


def _regex_fallback(claim: str, topic: str, image_hint: str) -> list[list[str]]:
    """Fallback: expand existing regex shot_list + hint + topic generics per beat."""
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
        result.append(unique[:10])

    return result
