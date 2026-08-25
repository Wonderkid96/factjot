"""Tests for src.core.claude_cli (local `claude` CLI wrapper, no API key).

Every infra failure -- binary missing, non-zero exit, timeout, malformed
JSON, an explicit is_error envelope -- must return None so callers can fail
open. `--bare` must never appear in the built command: it forces
API-key-only auth, which defeats the point of calling the local CLI.
"""
from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock

from src.core.claude_cli import call_claude_cli


def _mock_run_result(stdout: str, returncode: int = 0, stderr: str = "") -> MagicMock:
    res = MagicMock()
    res.returncode = returncode
    res.stdout = stdout
    res.stderr = stderr
    return res


def _envelope(result="OK", is_error=False, structured_output=None) -> str:
    payload = {"type": "result", "is_error": is_error, "result": result}
    if structured_output is not None:
        payload["structured_output"] = structured_output
    return json.dumps(payload)


# --------------------------------------------------------------------------- #
# 1. Happy path
# --------------------------------------------------------------------------- #


def test_returns_envelope_on_success(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/claude")
    fake_run = MagicMock(return_value=_mock_run_result(_envelope(result="OK")))
    monkeypatch.setattr("subprocess.run", fake_run)

    envelope = call_claude_cli("say ok")
    assert envelope is not None
    assert envelope["result"] == "OK"
    fake_run.assert_called_once()


def test_json_schema_produces_structured_output(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/claude")
    fake_run = MagicMock(
        return_value=_mock_run_result(
            _envelope(structured_output={"passes": True, "reason": ""})
        )
    )
    monkeypatch.setattr("subprocess.run", fake_run)

    envelope = call_claude_cli(
        "judge this", json_schema={"type": "object", "properties": {}}
    )
    assert envelope["structured_output"] == {"passes": True, "reason": ""}


def test_default_model_is_sonnet(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/claude")
    fake_run = MagicMock(return_value=_mock_run_result(_envelope()))
    monkeypatch.setattr("subprocess.run", fake_run)

    call_claude_cli("hello")
    cmd = fake_run.call_args.args[0]
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "sonnet"


def test_never_passes_bare_flag(monkeypatch):
    """--bare forces API-key-only auth; using it would defeat local CLI auth."""
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/claude")
    fake_run = MagicMock(return_value=_mock_run_result(_envelope()))
    monkeypatch.setattr("subprocess.run", fake_run)

    call_claude_cli("hello")
    cmd = fake_run.call_args.args[0]
    assert "--bare" not in cmd


def test_disables_tool_use(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/claude")
    fake_run = MagicMock(return_value=_mock_run_result(_envelope()))
    monkeypatch.setattr("subprocess.run", fake_run)

    call_claude_cli("hello")
    cmd = fake_run.call_args.args[0]
    assert "--tools" in cmd
    assert cmd[cmd.index("--tools") + 1] == ""


# --------------------------------------------------------------------------- #
# 2. Fail-open ladder
# --------------------------------------------------------------------------- #


def test_returns_none_when_binary_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    fake_run = MagicMock()
    monkeypatch.setattr("subprocess.run", fake_run)

    assert call_claude_cli("hello") is None
    fake_run.assert_not_called()


def test_returns_none_on_nonzero_exit(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/claude")
    monkeypatch.setattr(
        "subprocess.run",
        MagicMock(return_value=_mock_run_result("", returncode=1, stderr="auth error")),
    )

    assert call_claude_cli("hello") is None


def test_returns_none_on_timeout(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/claude")
    monkeypatch.setattr(
        "subprocess.run",
        MagicMock(side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=60)),
    )

    assert call_claude_cli("hello") is None


def test_returns_none_on_os_error(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/claude")
    monkeypatch.setattr("subprocess.run", MagicMock(side_effect=OSError("boom")))

    assert call_claude_cli("hello") is None


def test_returns_none_on_malformed_json(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/claude")
    monkeypatch.setattr(
        "subprocess.run", MagicMock(return_value=_mock_run_result("not json"))
    )

    assert call_claude_cli("hello") is None


def test_returns_none_on_is_error_envelope(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/claude")
    monkeypatch.setattr(
        "subprocess.run",
        MagicMock(return_value=_mock_run_result(_envelope(is_error=True, result="refused"))),
    )

    assert call_claude_cli("hello") is None
