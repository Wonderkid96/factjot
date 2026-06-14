"""Tests for src.verification.weird_bit_gate (Plan 2: interestingness backstop).

The judge applies the SHARED_CORE QUALITY GATE to a finished reel script.

* Fail-open: any infra problem (gate off, no key, SDK missing, API error,
  malformed output) returns ``(True, "")`` so the account keeps posting on the
  structural gate alone.
* Lenient: it rejects only when the model explicitly returns ``passes=false``.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.verification.weird_bit_gate import judge_weird_bit, _extract_json


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


def _mock_json_response(payload: dict) -> MagicMock:
    res = MagicMock()
    res.content = [MagicMock()]
    res.content[0].text = json.dumps(payload)
    res.usage.input_tokens = 100
    res.usage.output_tokens = 30
    return res


def _mock_text_response(text: str) -> MagicMock:
    res = MagicMock()
    res.content = [MagicMock()]
    res.content[0].text = text
    res.usage.input_tokens = 100
    res.usage.output_tokens = 30
    return res


# --------------------------------------------------------------------------- #
# 1. Pass: a genuine weird bit ships
# --------------------------------------------------------------------------- #


def test_passes_when_weird_bit_present(monkeypatch):
    fake = MagicMock()
    fake.messages.create.return_value = _mock_json_response(
        {
            "weird_bit": "a sovereign army lost a war to flightless birds",
            "type": "a strange consequence",
            "passes": True,
            "reason": "",
        }
    )
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake)

    ok, reason = judge_weird_bit(_WEIRD_SCRIPT, api_key="dummy")
    assert ok is True
    assert reason == ""
    fake.messages.create.assert_called_once()


# --------------------------------------------------------------------------- #
# 2. Reject: a well-formed but boring script is caught
# --------------------------------------------------------------------------- #


def test_rejects_when_no_weird_bit(monkeypatch):
    fake = MagicMock()
    fake.messages.create.return_value = _mock_json_response(
        {
            "weird_bit": "",
            "type": "none",
            "passes": False,
            "reason": "the script only describes an ordinary town with no weird bit.",
        }
    )
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake)

    ok, reason = judge_weird_bit(_BORING_SCRIPT, api_key="dummy")
    assert ok is False
    assert "weird bit" in reason.lower()


def test_reject_uses_default_reason_when_model_omits_it(monkeypatch):
    fake = MagicMock()
    fake.messages.create.return_value = _mock_json_response({"passes": False})
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake)

    ok, reason = judge_weird_bit(_BORING_SCRIPT, api_key="dummy")
    assert ok is False
    assert reason  # non-empty default reason supplied


# --------------------------------------------------------------------------- #
# 3. Lenient bias: anything but explicit passes=false ships
# --------------------------------------------------------------------------- #


def test_passes_when_passes_field_missing(monkeypatch):
    fake = MagicMock()
    fake.messages.create.return_value = _mock_json_response(
        {"weird_bit": "something", "type": "an overlooked detail"}
    )
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake)

    ok, reason = judge_weird_bit(_WEIRD_SCRIPT, api_key="dummy")
    assert ok is True
    assert reason == ""


def test_parses_json_wrapped_in_code_fence(monkeypatch):
    fenced = "```json\n" + json.dumps({"passes": False, "reason": "boring."}) + "\n```"
    fake = MagicMock()
    fake.messages.create.return_value = _mock_text_response(fenced)
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake)

    ok, reason = judge_weird_bit(_BORING_SCRIPT, api_key="dummy")
    assert ok is False
    assert reason == "boring."


# --------------------------------------------------------------------------- #
# 4. Fail-open ladder
# --------------------------------------------------------------------------- #


def test_fails_open_without_api_key(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    ok, reason = judge_weird_bit(_BORING_SCRIPT, api_key="")
    assert ok is True
    assert reason == ""
    fake.messages.create.assert_not_called()


def test_fails_open_when_anthropic_raises(monkeypatch):
    fake = MagicMock()
    fake.messages.create.side_effect = ConnectionError("upstream 503")
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake)

    ok, reason = judge_weird_bit(_BORING_SCRIPT, api_key="dummy")
    assert ok is True
    assert reason == ""


def test_fails_open_on_malformed_json(monkeypatch):
    fake = MagicMock()
    fake.messages.create.return_value = _mock_text_response("not json at all")
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake)

    ok, reason = judge_weird_bit(_BORING_SCRIPT, api_key="dummy")
    assert ok is True


def test_gate_disabled_by_env(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake)
    monkeypatch.setenv("WEIRD_BIT_GATE", "off")

    ok, reason = judge_weird_bit(_BORING_SCRIPT, api_key="dummy")
    assert ok is True
    fake.messages.create.assert_not_called()


def test_empty_script_passes_without_call(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake)

    ok, reason = judge_weird_bit("", api_key="dummy")
    assert ok is True
    fake.messages.create.assert_not_called()


# --------------------------------------------------------------------------- #
# 5. _extract_json unit
# --------------------------------------------------------------------------- #


def test_extract_json_handles_surrounding_prose():
    raw = 'Here is the result: {"passes": true} hope that helps'
    assert _extract_json(raw) == {"passes": True}


def test_extract_json_raises_on_no_object():
    with pytest.raises(ValueError):
        _extract_json("no braces here")
