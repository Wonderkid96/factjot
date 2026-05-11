"""Tests for the entity_image_validator soft-pass logging.

Behavioural contract: every soft-pass (api_key_missing, fetch_failed,
anthropic_sdk_missing, api_error:*) must emit a [entity-validate]
SOFT-PASS log line so the caller in video_finder (which discards the
returned dict to a bool) cannot accidentally hide quota / key /
infra failures from the workflow log.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.research.entity_image_validator import _soft_pass  # noqa: E402


def test_soft_pass_logs_to_stdout(capsys):
    result = _soft_pass("api_key_missing")
    captured = capsys.readouterr()
    assert "[entity-validate] SOFT-PASS" in captured.out
    assert "api_key_missing" in captured.out


def test_soft_pass_returns_canonical_shape():
    result = _soft_pass("fetch_failed")
    assert result == {
        "ok": True,
        "confidence": 0.0,
        "reason": "fetch_failed",
        "cost_usd": 0.0,
    }


def test_soft_pass_preserves_cost(capsys):
    result = _soft_pass("api_error:quota_exceeded", cost_usd=0.005)
    assert result["cost_usd"] == 0.005
    captured = capsys.readouterr()
    assert "api_error:quota_exceeded" in captured.out


def test_soft_pass_log_includes_all_reason_types(capsys):
    """All four soft-pass reasons must surface visibly."""
    for reason in ("api_key_missing", "fetch_failed",
                   "anthropic_sdk_missing", "api_error:Timeout"):
        capsys.readouterr()  # clear previous
        _soft_pass(reason)
        captured = capsys.readouterr()
        assert "SOFT-PASS" in captured.out
        assert reason in captured.out
