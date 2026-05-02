"""TTS engine for Reels voice synthesis.

Supports two backends, selected via TTS_BACKEND env var or the `backend`
argument to synthesise():

  edge-tts (default, free):
    en-GB-RyanNeural  — British male, warm [DEFAULT]
    en-GB-ThomasNeural, en-GB-SoniaNeural, en-US-BrianNeural, etc.

  elevenlabs (paid, near-human quality):
    Requires ELEVENLABS_API_KEY in .env.
    Good voices: George (British, authoritative), Daniel (precise),
    Brian (conversational). Billed per character (~400 chars/Reel).
    Uses /v1/text-to-speech/{voice_id}/with-timestamps endpoint which
    returns character-level alignment — converted to WordBeat here.
    Model: eleven_turbo_v2_5 (fast + high quality, good for social).

Both backends return the same (mp3_path, list[WordBeat]) so the rest of
the pipeline (chunking, subtitle overlays, FFmpeg) is unchanged.

Usage:
    from src.render.tts_engine import synthesise
    mp3, words = synthesise("In the 1920s...", out_dir)                  # edge-tts
    mp3, words = synthesise("In the 1920s...", out_dir, backend="elevenlabs")
"""
from __future__ import annotations

import asyncio
import base64
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    import edge_tts as _edge_tts_mod
    _EDGE_TTS_AVAILABLE = True
except ImportError:
    _EDGE_TTS_AVAILABLE = False

VOICE = "en-GB-RyanNeural"  # edge-tts default


def _alert_tts_fallback(reason: str) -> None:
    """Surface ElevenLabs failures into the brain log so silent fallback
    to edge-tts can be detected after the fact (otherwise the wrong voice
    just ships and nobody notices). Best-effort — never raises."""
    try:
        from src.brain import brain
        brain.append_log(f"TTS FALLBACK to edge-tts: {reason}")
    except Exception:
        pass

# ElevenLabs defaults
EL_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"  # George — British male, authoritative (default)
EL_MODEL    = "eleven_turbo_v2_5"       # Fast + high quality, good for social

# ------------------------------------------------------------------ #
# Data types
# ------------------------------------------------------------------ #

@dataclass
class WordBeat:
    """One word with its start and end timestamps in seconds."""
    word: str
    start_s: float
    end_s: float

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


# ------------------------------------------------------------------ #
# Public API
# ------------------------------------------------------------------ #

def synthesise(
    text: str,
    out_dir: Path,
    voice: str = VOICE,
    rate: str = "+0%",
    volume: str = "+0%",
    backend: str | None = None,
) -> tuple[Path, list[WordBeat]]:
    """Synthesise `text` to MP3 and return (mp3_path, word_beats).

    backend: "elevenlabs" | "edge-tts" | None (auto: reads TTS_BACKEND env var,
             falls back to edge-tts).

    Both backends return identical output types. Swap freely.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    resolved = (backend or os.getenv("TTS_BACKEND", "elevenlabs")).lower()

    if resolved == "elevenlabs":
        api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
        if not api_key:
            msg = "ELEVENLABS_API_KEY not set — falling back to edge-tts"
            print(f"  [tts] {msg}")
            _alert_tts_fallback(msg)
        else:
            try:
                result = _synthesise_elevenlabs(text, out_dir, voice)
                return result
            except Exception as exc:
                msg = f"ElevenLabs failed ({exc.__class__.__name__}: {exc}) — falling back to edge-tts"
                print(f"  [tts] {msg}")
                _alert_tts_fallback(msg)

    # Fallback: edge-tts (free, always available)
    if not _EDGE_TTS_AVAILABLE:
        raise RuntimeError("edge-tts is not installed. Run: pip install edge-tts")

    mp3_path = out_dir / "voice.mp3"

    beats = asyncio.run(_synthesise_async(text, mp3_path, voice, rate, volume))
    print(f"  [tts] {len(beats)} words, audio={mp3_path.name}, duration~{beats[-1].end_s:.1f}s" if beats else "  [tts] no beats returned")
    return mp3_path, beats


def group_into_chunks(
    beats: list[WordBeat],
    words_per_line: int = 5,
    max_chars: int = 32,
    original_text: str | None = None,
) -> list[list[WordBeat]]:
    """Group word beats into chunks, preserving the constituent WordBeats.

    Returns a list of chunks, where each chunk is a list of WordBeats that
    belong together. Lets the caller render word-by-word reveal frames
    (kinetic subtitles) by walking through each chunk's beats in order.
    """
    if not beats:
        return []

    end_punct: dict[int, str] = {}
    if original_text:
        end_punct = _map_punctuation_to_beats(original_text, beats)

    chunks: list[list[WordBeat]] = []
    current: list[WordBeat] = []

    for i, beat in enumerate(beats):
        current.append(beat)
        tentative_text = " ".join(b.word for b in current)
        punct = end_punct.get(i, "")

        if punct in {".", "!", "?", ";"}:
            chunks.append(current)
            current = []
            continue
        if punct == "," and len(current) >= 3:
            chunks.append(current)
            current = []
            continue
        if len(current) >= words_per_line or len(tentative_text) > max_chars:
            chunks.append(current)
            current = []

    if current:
        chunks.append(current)
    return chunks


def group_into_lines(
    beats: list[WordBeat],
    words_per_line: int = 5,
    max_chars: int = 32,
    original_text: str | None = None,
) -> list[WordBeat]:
    """Merge word-level beats into display-line chunks.

    If `original_text` is provided, the chunker breaks at natural
    grammatical boundaries (periods, semicolons, commas) so subtitles
    read like complete clauses instead of arbitrary 4-word slices.

    Without `original_text`, falls back to fixed word-count chunks.

    Constraints:
      - max `words_per_line` words per chunk
      - max `max_chars` characters per chunk
      - never split mid-clause if the clause fits

    Each returned WordBeat spans the first word's start to the last word's end.
    """
    if not beats:
        return []

    # Build a punctuation map: beat_index -> trailing punctuation char (or '')
    end_punct: dict[int, str] = {}
    if original_text:
        end_punct = _map_punctuation_to_beats(original_text, beats)

    lines: list[WordBeat] = []
    current: list[WordBeat] = []

    def _flush() -> None:
        if not current:
            return
        text = " ".join(b.word for b in current)
        lines.append(WordBeat(
            word=text,
            start_s=current[0].start_s,
            end_s=current[-1].end_s,
        ))

    for i, beat in enumerate(beats):
        current.append(beat)
        tentative_text = " ".join(b.word for b in current)
        punct = end_punct.get(i, "")

        # Hard breaks: sentence end, semicolon — always flush
        if punct in {".", "!", "?", ";"}:
            _flush()
            current = []
            continue
        # Comma: flush only if current chunk is meaningfully long
        if punct == "," and len(current) >= 3:
            _flush()
            current = []
            continue
        # Length cap: flush if next word would overflow
        if len(current) >= words_per_line or len(tentative_text) > max_chars:
            _flush()
            current = []

    _flush()
    return lines


def _map_punctuation_to_beats(text: str, beats: list[WordBeat]) -> dict[int, str]:
    """For each beat index, return any trailing punctuation from the original text.

    Walks through the original text token-by-token in parallel with the
    beat list. When a token ends with punctuation, marks that beat index.
    """
    import re as _re
    tokens = text.split()
    end_punct: dict[int, str] = {}
    beat_idx = 0
    for tok in tokens:
        if beat_idx >= len(beats):
            break
        # Strip any leading symbols, then take the last char if it's punctuation
        trailing = ""
        if tok and tok[-1] in ".,;:!?":
            trailing = tok[-1]
        # Match — clean alphanumerics from token to compare with beat word
        clean = _re.sub(r"[^\w'-]", "", tok).lower()
        beat_word = beats[beat_idx].word.lower()
        if clean and beat_word and (clean == beat_word or clean.startswith(beat_word) or beat_word.startswith(clean)):
            if trailing:
                end_punct[beat_idx] = trailing
            beat_idx += 1
    return end_punct


def audio_duration(mp3_path: Path) -> float:
    """Return duration of an MP3 file in seconds using ffprobe."""
    import subprocess, json
    try:
        out = subprocess.check_output(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                str(mp3_path),
            ],
            stderr=subprocess.STDOUT,
        )
        return float(json.loads(out)["format"]["duration"])
    except Exception:
        # Estimate from beats if ffprobe unavailable
        return 0.0


# ------------------------------------------------------------------ #
# Async implementation
# ------------------------------------------------------------------ #

async def _synthesise_async(
    text: str,
    mp3_path: Path,
    voice: str,
    rate: str,
    volume: str,
) -> list[WordBeat]:
    # boundary='WordBoundary' required in edge-tts >= 7.x (default is SentenceBoundary)
    communicate = _edge_tts_mod.Communicate(
        text, voice, rate=rate, volume=volume, boundary="WordBoundary"
    )
    beats: list[WordBeat] = []
    audio_chunks: list[bytes] = []

    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_chunks.append(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            # offset and duration are in 100-nanosecond ticks
            start_s = chunk["offset"] / 10_000_000
            dur_s = chunk["duration"] / 10_000_000
            beats.append(WordBeat(
                word=chunk["text"],
                start_s=start_s,
                end_s=start_s + dur_s,
            ))

    # Write audio
    with open(mp3_path, "wb") as f:
        for chunk in audio_chunks:
            f.write(chunk)

    return beats


# ------------------------------------------------------------------ #
# ElevenLabs backend
# ------------------------------------------------------------------ #

def _synthesise_elevenlabs(
    text: str,
    out_dir: Path,
    voice: str,
) -> tuple[Path, list[WordBeat]]:
    """Call ElevenLabs /with-timestamps endpoint.

    Requires ELEVENLABS_API_KEY in env.
    `voice` can be a voice_id (e.g. "JBFqnCBsd6RMkjVDRZzb") or a voice
    name shorthand ("george", "daniel", "brian") which maps to the known id.
    """
    import requests as _req

    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "ELEVENLABS_API_KEY not set in .env. "
            "Get a free key at elevenlabs.io then add it."
        )

    voice_id = _el_resolve_voice(voice)
    mp3_path = out_dir / "voice.mp3"

    resp = _req.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps",
        json={
            "text": text,
            "model_id": EL_MODEL,
            "voice_settings": {
                "stability": 0.25,        # lower = more natural pitch variation
                "similarity_boost": 0.82,
                "style": 0.45,            # more energy and expression
                "use_speaker_boost": True,
            },
        },
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
        timeout=60,
    )
    if not resp.ok:
        raise RuntimeError(
            f"ElevenLabs API error {resp.status_code}: {resp.text[:400]}"
        )

    data = resp.json()
    audio_bytes = base64.b64decode(data["audio_base64"])
    mp3_path.write_bytes(audio_bytes)

    # Convert character-level alignment → WordBeat list
    alignment = data.get("alignment") or {}
    beats = _el_chars_to_words(
        chars=alignment.get("characters", []),
        starts=alignment.get("character_start_times_seconds", []),
        ends=alignment.get("character_end_times_seconds", []),
    )
    print(
        f"  [tts/elevenlabs] {len(beats)} words, "
        f"duration~{beats[-1].end_s:.1f}s" if beats else
        "  [tts/elevenlabs] no alignment data"
    )
    return mp3_path, beats


# Known voice name → ElevenLabs voice_id shortcuts
_EL_VOICES: dict[str, str] = {
    "george":  "JBFqnCBsd6RMkjVDRZzb",  # British male, warm, authoritative
    "daniel":  "onwK4e9ZLuTAKqWW03F9",  # British male, calm, precise
    "brian":   "nPczCjzI2devNBz1zQrb",  # British male, conversational
    "charlie": "IKne3meq5aSn9XLyUdCD",  # British male, natural
    "adam":    "pNInz6obpgDQGcFmaJgB",  # American male, deep
}


def _el_resolve_voice(voice: str) -> str:
    """Return a voice_id for a name shorthand or pass through a raw id."""
    low = voice.lower().strip()
    return _EL_VOICES.get(low, voice)


def _el_chars_to_words(
    chars: list[str],
    starts: list[float],
    ends: list[float],
) -> list[WordBeat]:
    """Aggregate ElevenLabs character-level alignment into WordBeat objects."""
    beats: list[WordBeat] = []
    current_chars: list[str] = []
    word_start: float = 0.0
    word_end: float = 0.0

    for ch, s, e in zip(chars, starts, ends):
        if ch in (" ", "\n", "\t"):
            if current_chars:
                beats.append(WordBeat(
                    word="".join(current_chars).strip(".,;:!?\"'"),
                    start_s=word_start,
                    end_s=word_end,
                ))
                current_chars = []
        else:
            if not current_chars:
                word_start = s
            current_chars.append(ch)
            word_end = e

    if current_chars:
        beats.append(WordBeat(
            word="".join(current_chars).strip(".,;:!?\"'"),
            start_s=word_start,
            end_s=word_end,
        ))

    return [b for b in beats if b.word]
