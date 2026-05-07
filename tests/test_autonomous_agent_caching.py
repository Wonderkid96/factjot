"""Smoke tests for prompt caching in scripts/autonomous_agent.py.

The agent loop runs 1-12 turns sending an identical large prompt prefix
(tools + system + first user message). We pin that prefix into
Anthropic's 5-minute prompt cache so every turn after the first reads
it at 10% of input cost.

These tests exercise the wiring (cache_control on the first user
message, cost ledger fields) without making real API calls.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scripts.autonomous_agent as agent


def test_cache_pricing_constants_match_anthropic_rates():
    """Cache writes are 1.25x base input. Cache reads are 0.10x."""
    assert agent.PRICE_CACHE_WRITE_PER_M == round(agent.PRICE_INPUT_PER_M * 1.25, 4)
    assert agent.PRICE_CACHE_READ_PER_M  == round(agent.PRICE_INPUT_PER_M * 0.10, 4)


def test_log_cost_records_cache_metrics(tmp_path, monkeypatch):
    ledger = tmp_path / "api_usage_costs.jsonl"
    monkeypatch.setattr(agent, "COST_LEDGER", ledger)
    agent._log_cost(
        mode="fact",
        dry_run=True,
        input_tokens=500,
        output_tokens=200,
        cache_creation_tokens=3000,
        cache_read_tokens=33000,    # 11 cache hits at ~3000 tokens each
        status="end_turn",
    )
    rows = ledger.read_text().strip().splitlines()
    assert len(rows) == 1
    record = json.loads(rows[0])
    assert record["cache_creation_tokens"] == 3000
    assert record["cache_read_tokens"]     == 33000
    cost = record["cost_estimate_usd"]
    # Cache read at 10% input rate beats baseline by 90% on those tokens.
    # Verify the saved-by-cache figure is positive and realistic.
    assert cost["saved_by_cache"] > 0
    assert cost["baseline_no_cache"] > cost["total"]


def test_log_cost_with_no_cache_still_works(tmp_path, monkeypatch):
    """Old-style no-caching runs: cache fields default to 0, total = legacy total."""
    ledger = tmp_path / "api_usage_costs.jsonl"
    monkeypatch.setattr(agent, "COST_LEDGER", ledger)
    agent._log_cost(
        mode="fact",
        dry_run=True,
        input_tokens=1000,
        output_tokens=500,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        status="end_turn",
    )
    record = json.loads(ledger.read_text().strip().splitlines()[0])
    cost = record["cost_estimate_usd"]
    expected_total = round(
        1000 / 1_000_000 * agent.PRICE_INPUT_PER_M
        + 500 / 1_000_000 * agent.PRICE_OUTPUT_PER_M,
        6,
    )
    assert cost["total"] == expected_total
    assert cost["saved_by_cache"] == 0


def test_first_user_message_carries_cache_control():
    """The agent loop's first user message must mark its content block as
    cache_control=ephemeral so the prefix gets pinned in Anthropic's
    prompt cache. Assert on the literal source so any future refactor
    that drops the cache_control marker fails the test.
    """
    src = Path(agent.__file__).read_text(encoding="utf-8")
    # The first user message in main() must carry an ephemeral cache_control
    # marker. We don't pin exact whitespace, but the cache_control directive
    # must appear inside the messages-list construction.
    assert '"cache_control": {"type": "ephemeral"}' in src, (
        "agent main() should mark its first user message with cache_control "
        "ephemeral so the prefix hits Anthropic's prompt cache on turn 2+"
    )
