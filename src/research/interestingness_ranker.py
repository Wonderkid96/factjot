"""Haiku re-rank of story candidates by genuine weird-bit density (Plan 1).

`story_scout.build_story_candidates` scores titles with cheap heuristics:
keyword hooks, a regex "shock" signal, novelty against the post bank, and
source bonuses. Those rank a title by how it *looks*, not by how interesting
the underlying story actually is, so a bland-but-novel title can sit near the
top of the pool the agent is shown.

This module re-scores the strongest heuristic candidates with a single Haiku
call that judges each on weird-bit strength (0-3), then reorders them. It is:

* Fail-open. Any infra problem (gate off, no key, SDK missing, API error,
  malformed output, no usable scores) returns the input order unchanged.
* Order-only. It never adds, drops, or mutates candidates; the agent's own
  gates and the per-topic diversity cap still run downstream.

It shares one definition of "weird bit" with ``verification.weird_bit_gate``,
so the candidate re-rank and the publish-time gate agree on what counts as
interesting.

Disable with ``STORY_RERANK=off``.
"""
from __future__ import annotations

import json
import os

_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 1024

_PROMPT = """\
You rank candidate story ideas for an Instagram account that posts
strange-but-true facts. A strong idea has a clear "weird bit": a contradiction,
an absurd mechanism, a stupid decision, a strange consequence, an overlooked
detail, a design failure, a system behaving in a way no normal person would
expect, a true detail that sounds fake, or a familiar thing made newly strange.

A weak idea is merely big, old, famous, sad, expensive, or dangerous; states
only that an event happened; or is a well-worn internet staple everyone knows.

Score each candidate title 0 to 3 on how strong its weird bit is:
- 3: sounds fake but is plainly true, an absurd mechanism, or a stupid decision
- 2: a real contradiction or strange consequence, specific
- 1: mildly interesting, but the weird bit is thin or generic
- 0: boring, well-worn, or just an event with no weird bit

CANDIDATES:
{block}

Return JSON only, no prose: a list of objects, one per candidate, in any order:
[{{"index": <int>, "score": <0-3>}}, ...]
"""


def _extract_json_array(raw: str) -> list:
    """Slice the first JSON array out of a model response. Raises on failure."""
    text = (raw or "").strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON array in response")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, list):
        raise ValueError("expected a JSON array")
    return data


def rerank_candidates(candidates: list, api_key: str | None = None) -> list:
    """Return ``candidates`` reordered by Haiku weird-bit score (descending).

    Candidates are duck-typed: each needs a ``.title`` attribute. Ties, and any
    candidate the model omits, keep their original relative order (Python's
    sort is stable and the input is already ``total_score`` descending), so an
    omitted candidate sinks but never drops out. Fails open to the input order
    on any problem.
    """
    if os.getenv("STORY_RERANK", "on").strip().lower() == "off":
        return candidates
    if len(candidates) <= 1:
        return candidates

    api_key = (api_key or os.getenv("ANTHROPIC_API_KEY", "")).strip()
    if not api_key:
        return candidates

    try:
        from anthropic import Anthropic
    except ImportError:
        return candidates

    block = "\n".join(
        f"{i}. {getattr(c, 'title', '')}" for i, c in enumerate(candidates)
    )
    try:
        client = Anthropic(api_key=api_key)
        res = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": _PROMPT.format(block=block)}],
        )
        scored = _extract_json_array(res.content[0].text)
    except Exception as exc:  # noqa: BLE001 - any failure must fail open
        print(
            f"  [rerank] unavailable, keeping heuristic order: {str(exc)[:80]}",
            flush=True,
        )
        return candidates

    score_by_index: dict[int, float] = {}
    for item in scored:
        try:
            idx = int(item["index"])
            score_by_index[idx] = float(item["score"])
        except (KeyError, TypeError, ValueError):
            continue

    if not score_by_index:
        return candidates

    # Stable sort: equal scores (and omitted candidates, which default to 0)
    # keep their incoming heuristic order. reverse=True preserves stability.
    order = sorted(
        range(len(candidates)),
        key=lambda i: score_by_index.get(i, 0.0),
        reverse=True,
    )
    reranked = [candidates[i] for i in order]
    print(
        f"  [rerank] reordered {len(candidates)} candidates "
        f"({len(score_by_index)} scored)",
        flush=True,
    )
    return reranked
