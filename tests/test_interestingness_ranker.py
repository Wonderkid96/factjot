"""Tests for src.research.interestingness_ranker (Plan 1: candidate re-rank).

The re-rank reorders heuristically-scored candidates by Haiku weird-bit score.
It is order-only (never adds/drops/mutates) and fail-open (any infra problem
returns the input order unchanged).
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.research.interestingness_ranker import (
    rerank_candidates,
    _extract_json_array,
)


def _cand(title: str) -> SimpleNamespace:
    """A duck-typed stand-in for story_scout.Candidate (needs only .title)."""
    return SimpleNamespace(title=title)


def _mock_array_response(payload: list) -> MagicMock:
    res = MagicMock()
    res.content = [MagicMock()]
    res.content[0].text = json.dumps(payload)
    return res


def _mock_text_response(text: str) -> MagicMock:
    res = MagicMock()
    res.content = [MagicMock()]
    res.content[0].text = text
    return res


# --------------------------------------------------------------------------- #
# 1. Reordering
# --------------------------------------------------------------------------- #


def test_reorders_by_haiku_score(monkeypatch):
    cands = [_cand("alpha"), _cand("bravo"), _cand("charlie")]
    fake = MagicMock()
    fake.messages.create.return_value = _mock_array_response(
        [{"index": 0, "score": 0}, {"index": 1, "score": 3}, {"index": 2, "score": 1}]
    )
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake)

    out = rerank_candidates(cands, api_key="dummy")
    assert [c.title for c in out] == ["bravo", "charlie", "alpha"]


def test_ties_keep_heuristic_order(monkeypatch):
    cands = [_cand("alpha"), _cand("bravo"), _cand("charlie")]
    fake = MagicMock()
    fake.messages.create.return_value = _mock_array_response(
        [{"index": 0, "score": 2}, {"index": 1, "score": 2}, {"index": 2, "score": 3}]
    )
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake)

    out = rerank_candidates(cands, api_key="dummy")
    # charlie (3) leads; alpha and bravo tie at 2 and keep their input order.
    assert [c.title for c in out] == ["charlie", "alpha", "bravo"]


def test_omitted_candidate_sinks_but_survives(monkeypatch):
    cands = [_cand("alpha"), _cand("bravo"), _cand("charlie")]
    fake = MagicMock()
    fake.messages.create.return_value = _mock_array_response([{"index": 1, "score": 3}])
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake)

    out = rerank_candidates(cands, api_key="dummy")
    assert out[0].title == "bravo"
    assert {c.title for c in out} == {"alpha", "bravo", "charlie"}  # none dropped
    assert len(out) == 3


def test_returns_the_same_objects(monkeypatch):
    cands = [_cand("alpha"), _cand("bravo")]
    fake = MagicMock()
    fake.messages.create.return_value = _mock_array_response(
        [{"index": 0, "score": 1}, {"index": 1, "score": 2}]
    )
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake)

    out = rerank_candidates(cands, api_key="dummy")
    assert out[0] is cands[1]
    assert out[1] is cands[0]


# --------------------------------------------------------------------------- #
# 2. Fail-open ladder
# --------------------------------------------------------------------------- #


def test_fails_open_without_api_key(monkeypatch):
    cands = [_cand("alpha"), _cand("bravo")]
    fake = MagicMock()
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    out = rerank_candidates(cands, api_key="")
    assert out == cands
    fake.messages.create.assert_not_called()


def test_fails_open_when_anthropic_raises(monkeypatch):
    cands = [_cand("alpha"), _cand("bravo")]
    fake = MagicMock()
    fake.messages.create.side_effect = ConnectionError("503")
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake)

    out = rerank_candidates(cands, api_key="dummy")
    assert out == cands


def test_fails_open_on_malformed_json(monkeypatch):
    cands = [_cand("alpha"), _cand("bravo")]
    fake = MagicMock()
    fake.messages.create.return_value = _mock_text_response("not json at all")
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake)

    out = rerank_candidates(cands, api_key="dummy")
    assert out == cands


def test_gate_disabled_by_env(monkeypatch):
    cands = [_cand("alpha"), _cand("bravo")]
    fake = MagicMock()
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake)
    monkeypatch.setenv("STORY_RERANK", "off")

    out = rerank_candidates(cands, api_key="dummy")
    assert out == cands
    fake.messages.create.assert_not_called()


def test_single_candidate_returned_as_is(monkeypatch):
    cands = [_cand("alpha")]
    fake = MagicMock()
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake)

    out = rerank_candidates(cands, api_key="dummy")
    assert out == cands
    fake.messages.create.assert_not_called()


def test_empty_list_returned_as_is(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake)

    out = rerank_candidates([], api_key="dummy")
    assert out == []
    fake.messages.create.assert_not_called()


# --------------------------------------------------------------------------- #
# 3. _extract_json_array unit
# --------------------------------------------------------------------------- #


def test_extract_json_array_handles_surrounding_prose():
    assert _extract_json_array('noise [{"index": 0, "score": 2}] tail') == [
        {"index": 0, "score": 2}
    ]


def test_extract_json_array_raises_on_no_array():
    with pytest.raises(ValueError):
        _extract_json_array("no array here")
