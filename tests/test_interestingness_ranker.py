"""Tests for src.research.interestingness_ranker (Plan 1: candidate re-rank).

The re-rank reorders heuristically-scored candidates by weird-bit score,
scored via the local `claude` CLI (src.core.claude_cli), not the Anthropic
API. It is order-only (never adds/drops/mutates) and fail-open (any infra
problem returns the input order unchanged).

`call_claude_cli` itself is covered by tests/test_claude_cli.py; here it is
mocked so these tests exercise only the ranker's own reordering logic.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from src.research.interestingness_ranker import rerank_candidates


def _cand(title: str) -> SimpleNamespace:
    """A duck-typed stand-in for story_scout.Candidate (needs only .title)."""
    return SimpleNamespace(title=title)


def _envelope(scores: list) -> dict:
    return {"type": "result", "is_error": False, "structured_output": {"scores": scores}}


# --------------------------------------------------------------------------- #
# 1. Reordering
# --------------------------------------------------------------------------- #


def test_reorders_by_score():
    cands = [_cand("alpha"), _cand("bravo"), _cand("charlie")]
    with patch("src.research.interestingness_ranker.call_claude_cli") as fake_call:
        fake_call.return_value = _envelope(
            [{"index": 0, "score": 0}, {"index": 1, "score": 3}, {"index": 2, "score": 1}]
        )
        out = rerank_candidates(cands)

    assert [c.title for c in out] == ["bravo", "charlie", "alpha"]


def test_calls_cli_with_sonnet_and_a_schema():
    cands = [_cand("alpha"), _cand("bravo")]
    with patch("src.research.interestingness_ranker.call_claude_cli") as fake_call:
        fake_call.return_value = _envelope([])
        rerank_candidates(cands)

    _, kwargs = fake_call.call_args
    assert kwargs["model"] == "sonnet"
    assert kwargs["json_schema"] is not None


def test_ties_keep_heuristic_order():
    cands = [_cand("alpha"), _cand("bravo"), _cand("charlie")]
    with patch("src.research.interestingness_ranker.call_claude_cli") as fake_call:
        fake_call.return_value = _envelope(
            [{"index": 0, "score": 2}, {"index": 1, "score": 2}, {"index": 2, "score": 3}]
        )
        out = rerank_candidates(cands)

    # charlie (3) leads; alpha and bravo tie at 2 and keep their input order.
    assert [c.title for c in out] == ["charlie", "alpha", "bravo"]


def test_omitted_candidate_sinks_but_survives():
    cands = [_cand("alpha"), _cand("bravo"), _cand("charlie")]
    with patch("src.research.interestingness_ranker.call_claude_cli") as fake_call:
        fake_call.return_value = _envelope([{"index": 1, "score": 3}])
        out = rerank_candidates(cands)

    assert out[0].title == "bravo"
    assert {c.title for c in out} == {"alpha", "bravo", "charlie"}  # none dropped
    assert len(out) == 3


def test_returns_the_same_objects():
    cands = [_cand("alpha"), _cand("bravo")]
    with patch("src.research.interestingness_ranker.call_claude_cli") as fake_call:
        fake_call.return_value = _envelope(
            [{"index": 0, "score": 1}, {"index": 1, "score": 2}]
        )
        out = rerank_candidates(cands)

    assert out[0] is cands[1]
    assert out[1] is cands[0]


# --------------------------------------------------------------------------- #
# 2. Fail-open ladder
# --------------------------------------------------------------------------- #


def test_fails_open_when_cli_unavailable():
    """call_claude_cli returns None on any infra problem (see its own tests)."""
    cands = [_cand("alpha"), _cand("bravo")]
    with patch("src.research.interestingness_ranker.call_claude_cli") as fake_call:
        fake_call.return_value = None
        out = rerank_candidates(cands)

    assert out == cands


def test_fails_open_when_structured_output_missing_scores():
    cands = [_cand("alpha"), _cand("bravo")]
    with patch("src.research.interestingness_ranker.call_claude_cli") as fake_call:
        fake_call.return_value = {"type": "result", "is_error": False, "structured_output": {}}
        out = rerank_candidates(cands)

    assert out == cands


def test_gate_disabled_by_env(monkeypatch):
    monkeypatch.setenv("STORY_RERANK", "off")
    cands = [_cand("alpha"), _cand("bravo")]
    with patch("src.research.interestingness_ranker.call_claude_cli") as fake_call:
        out = rerank_candidates(cands)

    assert out == cands
    fake_call.assert_not_called()


def test_single_candidate_returned_as_is():
    cands = [_cand("alpha")]
    with patch("src.research.interestingness_ranker.call_claude_cli") as fake_call:
        out = rerank_candidates(cands)

    assert out == cands
    fake_call.assert_not_called()


def test_empty_list_returned_as_is():
    with patch("src.research.interestingness_ranker.call_claude_cli") as fake_call:
        out = rerank_candidates([])

    assert out == []
    fake_call.assert_not_called()
