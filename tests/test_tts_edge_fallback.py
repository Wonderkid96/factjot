"""Regression tests for the edge-tts fallback path in synthesise().

Behavioural contract: when the ElevenLabs path fails (quota
exceeded, network error, API outage), the fallback to edge-tts
must use a VALID edge-tts voice name, not the ElevenLabs voice_id
that the caller originally supplied. edge-tts ValueErrors on
unrecognised voice names; an unfixed fallback would crash the reel.

Live regression 2026-05-11: ElevenLabs quota exhausted mid-run,
fallback fired with voice='MFZUKuGQUsGJPQjTS4wC' (an ElevenLabs
voice_id), edge-tts raised ValueError, the entire reel pipeline
crashed instead of recovering.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.render.tts_engine import _looks_like_edge_voice, VOICE  # noqa: E402


# ----- edge voice name detection ------------------------------------

def test_canonical_edge_voices_pass():
    assert _looks_like_edge_voice("en-GB-RyanNeural")
    assert _looks_like_edge_voice("en-US-AndrewNeural")
    assert _looks_like_edge_voice("en-GB-SoniaNeural")
    assert _looks_like_edge_voice("en-US-BrianNeural")
    assert _looks_like_edge_voice("fr-FR-DeniseNeural")


def test_elevenlabs_voice_ids_fail():
    """ElevenLabs IDs are 20-char alphanumeric, no hyphens, no Neural suffix.
    They must NOT match the edge voice pattern.
    """
    assert not _looks_like_edge_voice("MFZUKuGQUsGJPQjTS4wC")  # the locked production voice
    assert not _looks_like_edge_voice("JBFqnCBsd6RMkjVDRZzb")  # George
    assert not _looks_like_edge_voice("onwK4e9ZLuTAKqWW03F9")  # Daniel
    assert not _looks_like_edge_voice("pNInz6obpgDQGcFmaJgB")  # Adam


def test_elevenlabs_shortcut_names_fail():
    """Named shortcuts like 'george', 'adam', 'factjot' are not edge voices."""
    assert not _looks_like_edge_voice("george")
    assert not _looks_like_edge_voice("adam")
    assert not _looks_like_edge_voice("factjot")


def test_empty_or_garbage_fails():
    assert not _looks_like_edge_voice("")
    assert not _looks_like_edge_voice("   ")
    assert not _looks_like_edge_voice("random-string")


def test_module_default_is_a_valid_edge_voice():
    """The fallback constant VOICE itself must pass the check.
    If a refactor changed VOICE to an ElevenLabs id by mistake, the
    fallback would loop forever or fail in a confusing way.
    """
    assert _looks_like_edge_voice(VOICE), (
        f"module default VOICE={VOICE!r} must be a valid edge voice"
    )


# ----- fallback uses a valid voice (integration shape) --------------

def test_synthesise_fallback_swaps_to_edge_voice(monkeypatch, tmp_path):
    """When ElevenLabs is the requested backend and the call fails,
    the fallback into edge-tts must use VOICE (a valid edge voice),
    not the ElevenLabs voice_id the caller passed.
    """
    import src.render.tts_engine as tts

    # Force the elevenlabs path to be attempted...
    monkeypatch.setenv("ELEVENLABS_API_KEY", "fake-key")
    # ...and to fail loudly so we hit the fallback.
    def _explode(*args, **kwargs):
        raise RuntimeError("ElevenLabs API error 401: quota_exceeded")
    monkeypatch.setattr(tts, "_synthesise_elevenlabs", _explode)

    # Intercept the edge-tts async call and capture the voice that was
    # actually passed to it. asyncio.run is called on the coroutine
    # returned by _synthesise_async, so we mock _synthesise_async.
    captured: dict = {}
    async def _fake_async(text, mp3_path, voice, rate, volume):
        captured["voice"] = voice
        return []  # empty beats - we only care about the voice arg
    monkeypatch.setattr(tts, "_synthesise_async", _fake_async)
    monkeypatch.setattr(tts, "_EDGE_TTS_AVAILABLE", True)

    # Call with an ElevenLabs voice_id as the caller would
    tts.synthesise(
        text="hello world",
        out_dir=tmp_path,
        voice="MFZUKuGQUsGJPQjTS4wC",
        backend="elevenlabs",
    )

    assert "voice" in captured, "_synthesise_async should have been called"
    edge_voice = captured["voice"]
    assert _looks_like_edge_voice(edge_voice), (
        f"fallback passed voice={edge_voice!r} to edge-tts; "
        f"must be a valid edge voice name"
    )
    assert edge_voice != "MFZUKuGQUsGJPQjTS4wC", (
        "fallback must NOT pass the ElevenLabs voice_id to edge-tts"
    )


def test_direct_edge_call_with_valid_voice_passes_through(monkeypatch, tmp_path):
    """When the caller requests backend=edge with a valid edge voice,
    the fallback-swap logic must NOT override it.
    """
    import src.render.tts_engine as tts

    captured: dict = {}
    async def _fake_async(text, mp3_path, voice, rate, volume):
        captured["voice"] = voice
        return []
    monkeypatch.setattr(tts, "_synthesise_async", _fake_async)
    monkeypatch.setattr(tts, "_EDGE_TTS_AVAILABLE", True)

    tts.synthesise(
        text="hi",
        out_dir=tmp_path,
        voice="en-US-AndrewNeural",
        backend="edge-tts",
    )
    assert captured.get("voice") == "en-US-AndrewNeural"
