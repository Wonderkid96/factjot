"""Tests for src.verification.weird_bit_gate (Plan 2: interestingness backstop).

The judge applies the SHARED_CORE QUALITY GATE to a finished reel script via
the local `claude` CLI (src.core.claude_cli), not the Anthropic API.

* Fail-open: any infra problem (gate off, CLI unavailable, malformed output)
  returns ``(True, "")`` so the account keeps posting on the structural gate
  alone.
* Lenient: it rejects only when the model explicitly returns ``passes=false``.

`call_claude_cli` itself is covered by tests/test_claude_cli.py; here it is
mocked so these tests exercise only the gate's own decision logic.
"""
from __future__ import annotations

from unittest.mock import patch

from src.verification.weird_bit_gate import judge_weird_bit


_WEIRD_SCRIPT = (
    "In 1932, the Australian army declared war on the emu population of "
    "Western Australia. They deployed two Lewis machine guns and 10,000 "
    "rounds. The emus scattered and outpaced the soldiers. After six days "
    "the army had killed roughly fifty birds and given up."
)
_BORING_SCRIPT = (
    "In 1850, about 200 people lived in a small town. The winters were cold "
    "and the houses were small. People farmed the land and kept animals. "
    "Life carried on this way for many years without much changing at all."
)


def _envelope(structured_output: dict) -> dict:
    return {"type": "result", "is_error": False, "structured_output": structured_output}


# --------------------------------------------------------------------------- #
# 1. Pass: a genuine weird bit ships
# --------------------------------------------------------------------------- #


def test_passes_when_weird_bit_present():
    with patch("src.verification.weird_bit_gate.call_claude_cli") as fake_call:
        fake_call.return_value = _envelope(
            {
                "weird_bit": "a sovereign army lost a war to flightless birds",
                "type": "a strange consequence",
                "passes": True,
                "reason": "",
            }
        )
        ok, reason = judge_weird_bit(_WEIRD_SCRIPT)

    assert ok is True
    assert reason == ""
    fake_call.assert_called_once()


def test_calls_cli_with_sonnet_and_a_schema():
    with patch("src.verification.weird_bit_gate.call_claude_cli") as fake_call:
        fake_call.return_value = _envelope({"passes": True})
        judge_weird_bit(_WEIRD_SCRIPT)

    _, kwargs = fake_call.call_args
    assert kwargs["model"] == "sonnet"
    assert kwargs["json_schema"] is not None


# --------------------------------------------------------------------------- #
# 2. Reject: a well-formed but boring script is caught
# --------------------------------------------------------------------------- #


def test_rejects_when_no_weird_bit():
    with patch("src.verification.weird_bit_gate.call_claude_cli") as fake_call:
        fake_call.return_value = _envelope(
            {
                "weird_bit": "",
                "type": "none",
                "passes": False,
                "reason": "the script only describes an ordinary town with no weird bit.",
            }
        )
        ok, reason = judge_weird_bit(_BORING_SCRIPT)

    assert ok is False
    assert "weird bit" in reason.lower()


def test_reject_uses_default_reason_when_model_omits_it():
    with patch("src.verification.weird_bit_gate.call_claude_cli") as fake_call:
        fake_call.return_value = _envelope({"passes": False})
        ok, reason = judge_weird_bit(_BORING_SCRIPT)

    assert ok is False
    assert reason  # non-empty default reason supplied


# --------------------------------------------------------------------------- #
# 3. Lenient bias: anything but explicit passes=false ships
# --------------------------------------------------------------------------- #


def test_passes_when_passes_field_missing():
    with patch("src.verification.weird_bit_gate.call_claude_cli") as fake_call:
        fake_call.return_value = _envelope(
            {"weird_bit": "something", "type": "an overlooked detail"}
        )
        ok, reason = judge_weird_bit(_WEIRD_SCRIPT)

    assert ok is True
    assert reason == ""


def test_passes_when_structured_output_missing_entirely():
    with patch("src.verification.weird_bit_gate.call_claude_cli") as fake_call:
        fake_call.return_value = {"type": "result", "is_error": False}
        ok, reason = judge_weird_bit(_WEIRD_SCRIPT)

    assert ok is True


# --------------------------------------------------------------------------- #
# 4. Fail-open ladder
# --------------------------------------------------------------------------- #


def test_fails_open_when_cli_unavailable():
    """call_claude_cli returns None on any infra problem (see its own tests)."""
    with patch("src.verification.weird_bit_gate.call_claude_cli") as fake_call:
        fake_call.return_value = None
        ok, reason = judge_weird_bit(_BORING_SCRIPT)

    assert ok is True
    assert reason == ""


def test_gate_disabled_by_env(monkeypatch):
    monkeypatch.setenv("WEIRD_BIT_GATE", "off")
    with patch("src.verification.weird_bit_gate.call_claude_cli") as fake_call:
        ok, reason = judge_weird_bit(_BORING_SCRIPT)

    assert ok is True
    fake_call.assert_not_called()


def test_empty_script_passes_without_call():
    with patch("src.verification.weird_bit_gate.call_claude_cli") as fake_call:
        ok, reason = judge_weird_bit("")

    assert ok is True
    fake_call.assert_not_called()
