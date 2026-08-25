"""Local-CLI re-rank of story candidates by genuine weird-bit density (Plan 1).

`story_scout.build_story_candidates` scores titles with cheap heuristics:
keyword hooks, a regex "shock" signal, novelty against the post bank, and
source bonuses. Those rank a title by how it *looks*, not by how interesting
the underlying story actually is, so a bland-but-novel title can sit near the
top of the pool the agent is shown.

This module re-scores the strongest heuristic candidates with a single call
that judges each on weird-bit strength (0-3), then reorders them. It calls
the local `claude` CLI (Sonnet, via `src.core.claude_cli`) -- not the
Anthropic API. No ANTHROPIC_API_KEY involved; see `claude_cli` module
docstring for why `--bare` is never used and what that costs.

* Fail-open. Any infra problem (gate off, CLI missing, CLI error, malformed
  output, no usable scores) returns the input order unchanged.
* Order-only. It never adds, drops, or mutates candidates; the agent's own
  gates and the per-topic diversity cap still run downstream.

It shares one definition of "weird bit" with ``verification.weird_bit_gate``,
so the candidate re-rank and the publish-time gate agree on what counts as
interesting.

Disable with ``STORY_RERANK=off``.
"""
from __future__ import annotations

import os

from src.core.claude_cli import call_claude_cli

_MODEL = "sonnet"

_PROMPT = """\
You rank candidate story ideas for an Instagram account that posts
controversial, shocking, or horrifying true facts. A strong idea has a clear
"weird bit" that is also genuinely shocking or disturbing, not just
technically odd: a contradiction, an absurd mechanism, a stupid decision, a
strange consequence, an overlooked detail, a design failure, a system
behaving in a way no normal person would expect, a true detail that sounds
fake, or a familiar thing made newly strange.

A weak idea is merely big, old, famous, sad, expensive, or dangerous; states
only that an event happened; is a well-worn internet staple everyone knows;
or has a technical weird bit that only lands as mildly interesting or quirky
rather than shocking.

Score each candidate title 0 to 3 on how strong AND how shocking its weird
bit is. A weird bit alone is not enough; it must also disturb, shock, or
horrify, not just mildly amuse:
- 3: genuinely shocking, disturbing, or horrifying, and plainly true
- 2: a real contradiction or strange consequence, specific, with genuine
  unease to it
- 1: has a technical weird bit but it only lands as mildly interesting or
  quirky, not shocking
- 0: boring, well-worn, merely an event with no weird bit, or a weird bit
  with no real shock value

CANDIDATES:
{block}

Score every candidate listed above, one entry per candidate, in any order.
"""

# --json-schema makes the CLI itself guarantee this shape -- no free-text
# JSON-extraction regex needed, unlike the old direct-API version.
_SCHEMA = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "score": {"type": "integer"},
                },
                "required": ["index", "score"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["scores"],
    "additionalProperties": False,
}


def rerank_candidates(candidates: list) -> list:
    """Return ``candidates`` reordered by weird-bit score (descending).

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

    block = "\n".join(
        f"{i}. {getattr(c, 'title', '')}" for i, c in enumerate(candidates)
    )
    envelope = call_claude_cli(
        _PROMPT.format(block=block),
        model=_MODEL,
        json_schema=_SCHEMA,
    )
    if envelope is None:
        return candidates

    scored = (envelope.get("structured_output") or {}).get("scores") or []

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
