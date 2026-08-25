"""Generate visually grounded stock footage search queries per script sentence.

One local `claude` CLI call per reel (Haiku, via `src.core.claude_cli` --
not the Anthropic API, no ANTHROPIC_API_KEY involved; see that module's
docstring for why) splits the reel script into sentences and generates 3-4
footage search queries per sentence. Queries describe what footage would
visually illustrate that specific line of the script -- not abstract beat
labels.

Falls back to regex expansion from narrative_beats when the CLI is
unavailable or fails. That fallback has no proper-noun anchoring, so a run
on the fallback path is materially more likely to match generic or
irrelevant stock footage -- this is not just a degraded-quality nicety.
"""
from __future__ import annotations

import re

from src.core.claude_cli import call_claude_cli

_MODEL = "haiku"


_SYSTEM_PROMPT = """Create stock footage search queries for a short documentary reel.

Input:
- Topic
- Subject hint
- Script sentences (numbered)

Task:
- For each sentence, return 3-4 search queries that show what that sentence looks like on screen.

Rules:
1. Keep queries visual and concrete (subject, action, place).
2. ALWAYS lead with the real proper noun — name, location, year — from the script sentence. A query with "Vasili Arkhipov 1962 submarine" will find better footage than "officer on submarine Cold War". Named entities are indexed by Wikimedia, NASA, and Archive.org; generic descriptions only match shallow stock libraries.
3. No abstract words (no "mystery", "destiny", "symbolic", "haunting", etc).
4. 4-8 words per query, proper noun first where possible.
5. If exact subject footage is unavailable, name the closest real alternative (specific ship class, specific location, specific era). Never fall back to generic B-roll.
6. First query per sentence = most specific (proper noun + action/place). Later queries in same sentence can widen to context (era, environment, related subject).
7. Include a year or decade when the script mentions one — it helps archive searches.

Return one entry per script sentence, in order, each carrying its sentence
index and its list of queries.

Example (reel about the Mariana Trench snailfish):
sentences: [
  {"index": 0, "queries": ["Mariana Trench snailfish Challenger Deep 2023", "hadal snailfish deep ocean floor footage"]},
  {"index": 1, "queries": ["Challenger Deep 11000 metres pressure zone", "Mariana Trench expedition underwater camera"]},
  {"index": 2, "queries": ["snailfish shoal deepest fish ever filmed", "deep sea fish close up low light footage"]}
]"""

_SCHEMA = {
    "type": "object",
    "properties": {
        "sentences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "queries": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["index", "queries"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["sentences"],
    "additionalProperties": False,
}


def generate_all_beat_queries(
    claim: str,
    topic: str,
    image_hint: str,
    reel_script: str = "",
) -> list[list[str]]:
    """Generate footage search queries driven by the reel script sentences.

    Returns list[list[str]] -- one list of queries per sentence (up to 8).
    Falls back to regex queries silently if the local CLI is unavailable or
    fails.
    """
    if reel_script:
        try:
            result = _claude_queries(claim, topic, image_hint, reel_script)
            if result and len(result) >= 3:
                total = sum(len(q) for q in result)
                print(f"  [intents] claude-cli: {len(result)} sentence slots, {total} queries")
                return result
        except Exception as exc:
            print(f"  [intents] claude-cli failed ({exc}), using regex fallback")

    return _regex_fallback(claim, topic, image_hint)


def _split_sentences(script: str, max_sentences: int = 8) -> list[str]:
    """Split script into sentences, capped at max_sentences."""
    # Split on sentence boundaries, keep non-empty sentences
    raw = re.split(r'(?<=[.!?])\s+', script.strip())
    sentences = [s.strip() for s in raw if s.strip() and len(s.split()) >= 3]
    return sentences[:max_sentences]


def _claude_queries(
    claim: str,
    topic: str,
    image_hint: str,
    reel_script: str,
) -> list[list[str]]:
    sentences = _split_sentences(reel_script, max_sentences=8)
    if not sentences:
        return []

    numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(sentences))
    user_content = (
        f"Topic: {topic}\n"
        f"Subject hint: {image_hint}\n\n"
        f"Script sentences:\n{numbered}"
    )
    prompt = f"{_SYSTEM_PROMPT}\n\n{user_content}"

    envelope = call_claude_cli(prompt, model=_MODEL, json_schema=_SCHEMA, timeout=60)
    if envelope is None:
        return []

    data = envelope.get("structured_output")
    if not isinstance(data, dict):
        return []

    by_index: dict[int, list[str]] = {}
    for entry in data.get("sentences", []):
        if not isinstance(entry, dict):
            continue
        idx = entry.get("index")
        queries = entry.get("queries")
        if not isinstance(idx, int) or not isinstance(queries, list):
            continue
        by_index[idx] = [str(q).strip() for q in queries if str(q).strip()][:6]

    return [by_index.get(i, []) for i in range(len(sentences))]


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
