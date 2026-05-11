"""Tests for the TTS voice resolution at the make_reel boundary.

Behavioural contract: when TTS_BACKEND=elevenlabs (the default), the
ELEVENLABS_VOICE env var is the authoritative source for which voice
narrates the reel. The `--voice` CLI flag is ignored on that path.
The hardcoded George default in `src/render/tts_engine.py::EL_VOICE_ID`
is NEVER reached from the autonomous path because make_reel always
goes through `_resolve_tts_voice` before calling `synthesise`.

This regression test exists because of the 2026-05-11 voice confusion
incident, where the model misread the production voice by inferring
it from a stale local `.env` that had drifted from the GitHub Secret.
A test that pins the resolution logic prevents a future refactor from
silently routing a different voice into production.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines.reel.make_reel import _resolve_tts_voice, _TtsConfigError  # noqa: E402


# ----- elevenlabs backend: env wins ---------------------------------

def test_elevenlabs_env_voice_overrides_cli(monkeypatch):
    monkeypatch.setenv("TTS_BACKEND", "elevenlabs")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "fake-key")
    monkeypatch.setenv("ELEVENLABS_VOICE", "MFZUKuGQUsGJPQjTS4wC")
    voice, backend = _resolve_tts_voice(cli_voice="en-GB-RyanNeural")
    assert voice == "MFZUKuGQUsGJPQjTS4wC"
    assert backend == "elevenlabs"


def test_elevenlabs_default_backend_used_when_unset(monkeypatch):
    # The codebase defaults TTS_BACKEND to "elevenlabs" when unset.
    monkeypatch.delenv("TTS_BACKEND", raising=False)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "fake-key")
    monkeypatch.setenv("ELEVENLABS_VOICE", "MFZUKuGQUsGJPQjTS4wC")
    voice, backend = _resolve_tts_voice(cli_voice="ignored")
    assert backend == "elevenlabs", "default backend must be elevenlabs"
    assert voice == "MFZUKuGQUsGJPQjTS4wC"


def test_elevenlabs_missing_api_key_raises(monkeypatch):
    monkeypatch.setenv("TTS_BACKEND", "elevenlabs")
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setenv("ELEVENLABS_VOICE", "MFZUKuGQUsGJPQjTS4wC")
    with pytest.raises(_TtsConfigError, match="ELEVENLABS_API_KEY missing"):
        _resolve_tts_voice(cli_voice="ignored")


def test_elevenlabs_missing_voice_raises(monkeypatch):
    monkeypatch.setenv("TTS_BACKEND", "elevenlabs")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "fake-key")
    monkeypatch.delenv("ELEVENLABS_VOICE", raising=False)
    with pytest.raises(_TtsConfigError, match="ELEVENLABS_VOICE missing"):
        _resolve_tts_voice(cli_voice="ignored")


def test_elevenlabs_blank_voice_treated_as_missing(monkeypatch):
    """A whitespace-only ELEVENLABS_VOICE must fail closed. Pre-fix,
    a `.env` with `ELEVENLABS_VOICE= ` could ship to the named-shortcut
    default silently. Now it raises."""
    monkeypatch.setenv("TTS_BACKEND", "elevenlabs")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "fake-key")
    monkeypatch.setenv("ELEVENLABS_VOICE", "   ")
    with pytest.raises(_TtsConfigError, match="ELEVENLABS_VOICE missing"):
        _resolve_tts_voice(cli_voice="ignored")


# ----- edge backend: cli_voice passes through -----------------------

def test_edge_backend_uses_cli_voice(monkeypatch):
    monkeypatch.setenv("TTS_BACKEND", "edge")
    # ELEVENLABS_* are irrelevant on this path; should not be consulted.
    monkeypatch.delenv("ELEVENLABS_VOICE", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    voice, backend = _resolve_tts_voice(cli_voice="en-GB-RyanNeural")
    assert voice == "en-GB-RyanNeural"
    assert backend == "edge"


def test_edge_backend_ignores_elevenlabs_env(monkeypatch):
    """An ELEVENLABS_VOICE set in env must NOT bleed into the edge path."""
    monkeypatch.setenv("TTS_BACKEND", "edge")
    monkeypatch.setenv("ELEVENLABS_VOICE", "MFZUKuGQUsGJPQjTS4wC")
    voice, _ = _resolve_tts_voice(cli_voice="en-US-AndrewNeural")
    assert voice == "en-US-AndrewNeural"


# ----- regression: George default never wins on elevenlabs path -----

def test_george_default_never_returned_from_elevenlabs_path(monkeypatch):
    """The hardcoded George voice in src/render/tts_engine.py::EL_VOICE_ID
    must never be returned by _resolve_tts_voice when backend=elevenlabs.
    Either the env voice wins or _TtsConfigError is raised.
    """
    monkeypatch.setenv("TTS_BACKEND", "elevenlabs")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "fake-key")
    monkeypatch.setenv("ELEVENLABS_VOICE", "any-custom-id")
    voice, _ = _resolve_tts_voice(cli_voice="JBFqnCBsd6RMkjVDRZzb")
    assert voice == "any-custom-id"
    assert voice != "JBFqnCBsd6RMkjVDRZzb", (
        "George CLI flag must never override an env-set ELEVENLABS_VOICE"
    )
