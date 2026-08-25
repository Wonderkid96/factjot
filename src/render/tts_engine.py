"""TTS engine for Reels voice synthesis.

Supports two backends, selected via TTS_BACKEND env var or the `backend`
argument to synthesise():

  edge-tts (default, free):
    en-GB-RyanNeural  - British male, warm [DEFAULT]
    en-GB-ThomasNeural, en-GB-SoniaNeural, en-US-BrianNeural, etc.

  elevenlabs (paid, near-human quality):
    Requires ELEVENLABS_API_KEY in .env.
    Good voices: George (British, authoritative), Daniel (precise),
    Brian (conversational). Billed per character (~400 chars/Reel).
    Uses /v1/text-to-speech/{voice_id}/with-timestamps endpoint which
    returns character-level alignment - converted to WordBeat here.
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

try:
    import edge_tts as _edge_tts_mod
    _EDGE_TTS_AVAILABLE = True
except ImportError:
    _EDGE_TTS_AVAILABLE = False

VOICE = "en-GB-RyanNeural"  # edge-tts default

# Edge-tts voice names follow the Microsoft locale-prefixed pattern:
# `<lang>-<region>-<NameNeural>` (e.g. en-GB-RyanNeural, en-US-AndrewNeural).
# Used to distinguish edge voice names from ElevenLabs voice_ids when
# the ElevenLabs path falls back. ElevenLabs IDs are 20-char alphanumeric
# strings (e.g. onwK4e9ZLuTAKqWW03F9) which do not match this shape.
_EDGE_VOICE_RE = re.compile(r"^[a-z]{2,3}-[A-Z]{2}-[A-Za-z]+Neural$")


def _looks_like_edge_voice(voice: str) -> bool:
    """True when the string looks like an edge-tts voice name."""
    return bool(_EDGE_VOICE_RE.match((voice or "").strip()))


def _alert_tts_fallback(reason: str) -> None:
    """Surface ElevenLabs failures into the brain log so silent fallback
    to edge-tts can be detected after the fact (otherwise the wrong voice
    just ships and nobody notices). Best-effort - never raises."""
    try:
        from src.brain import brain
        brain.append_log(f"TTS FALLBACK to edge-tts: {reason}")
    except Exception:
        pass

# ElevenLabs defaults
EL_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"  # George - British male, authoritative (default)
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
# Number normalisation — convert digits to spoken words before TTS.
# TTS engines stumble on raw numerals: "2,150" → "two comma one fifty",
# "1,000" → garbled, "1908" → "one thousand nine hundred and eight".
# ------------------------------------------------------------------ #

_ORDINAL_MAP = {
    '1st': 'first', '2nd': 'second', '3rd': 'third', '4th': 'fourth',
    '5th': 'fifth', '6th': 'sixth', '7th': 'seventh', '8th': 'eighth',
    '9th': 'ninth', '10th': 'tenth', '11th': 'eleventh', '12th': 'twelfth',
    '13th': 'thirteenth', '14th': 'fourteenth', '15th': 'fifteenth',
    '16th': 'sixteenth', '17th': 'seventeenth', '18th': 'eighteenth',
    '19th': 'nineteenth', '20th': 'twentieth', '21st': 'twenty-first',
    '22nd': 'twenty-second', '23rd': 'twenty-third', '24th': 'twenty-fourth',
    '25th': 'twenty-fifth', '30th': 'thirtieth', '40th': 'fortieth',
    '50th': 'fiftieth', '100th': 'hundredth',
}

_ONES = [
    '', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine',
    'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen',
    'seventeen', 'eighteen', 'nineteen',
]
_TENS = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety']


def _int_to_words(n: int) -> str:
    if n < 0:
        return 'negative ' + _int_to_words(-n)
    if n == 0:
        return 'zero'
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + (('-' + _ONES[n % 10]) if n % 10 else '')
    if n < 1_000:
        rest = n % 100
        return _ONES[n // 100] + ' hundred' + (' and ' + _int_to_words(rest) if rest else '')
    if n < 1_000_000:
        rest = n % 1_000
        return _int_to_words(n // 1_000) + ' thousand' + (' ' + _int_to_words(rest) if rest else '')
    if n < 1_000_000_000:
        rest = n % 1_000_000
        return _int_to_words(n // 1_000_000) + ' million' + (' ' + _int_to_words(rest) if rest else '')
    rest = n % 1_000_000_000
    return _int_to_words(n // 1_000_000_000) + ' billion' + (' ' + _int_to_words(rest) if rest else '')


def _year_to_words(y: int) -> str:
    """Render a year as a native English year-reading (e.g. 1919 → 'nineteen nineteen').

    factjot voice avoids 'oh' in years (sounds American/casual). 1901 reads
    as 'nineteen hundred and one', not 'nineteen oh one'. Years where the
    last two digits are >=10 use the natural 'eighteen fifteen' form.
    """
    if 1100 <= y <= 1999:
        hi, lo = y // 100, y % 100
        hi_w = _int_to_words(hi)
        if lo == 0:
            return hi_w + ' hundred'
        if lo < 10:
            return hi_w + ' hundred and ' + _int_to_words(lo)
        return hi_w + ' ' + _int_to_words(lo)
    if 2000 <= y <= 2009:
        return 'two thousand' + (' and ' + _int_to_words(y % 100) if y % 100 else '')
    if 2010 <= y <= 2099:
        return 'twenty ' + _int_to_words(y % 100)
    return _int_to_words(y)


# Words that, when they immediately precede a 4-digit number, mean it is
# NOT a year (model number, room, version, code, etc). Match is anchored
# to end-of-prefix so only the directly preceding token counts.
_NOT_YEAR_PREFIX = re.compile(
    r'\b(?:model|room|version|chapter|page|figure|table|fig|code|serial|type|no|v)\.?\s*$',
    re.IGNORECASE,
)


def _year_or_integer(m: re.Match) -> str:
    n = int(m.group(1))
    prefix = m.string[max(0, m.start() - 24):m.start()]
    if _NOT_YEAR_PREFIX.search(prefix):
        return _int_to_words(n)
    return _year_to_words(n)


def normalise_for_tts(text: str) -> str:
    """Convert numerals and symbols to their spoken-word equivalents.

    Applied to every script before synthesis so the narrator reads
    '2,150 square kilometres' as 'two thousand one hundred and fifty
    square kilometres', not 'two comma one fifty square kilometres'.
    """
    # Ordinals first (before general number handling)
    text = re.sub(
        r'\b(\d+(?:st|nd|rd|th))\b',
        lambda m: _ORDINAL_MAP.get(m.group(0).lower(), m.group(0)),
        text, flags=re.IGNORECASE,
    )

    # Percentages: 80% → eighty percent
    text = re.sub(
        r'\b(\d+(?:\.\d+)?)\s*%',
        lambda m: _int_to_words(round(float(m.group(1)))) + ' percent',
        text,
    )

    # Decimal numbers NOT followed by a scale word (handle before integers)
    # e.g. 2.3 → two point three  (but leave "2.3 million" for scale handler)
    text = re.sub(
        r'\b(\d+)\.(\d+)\b(?!\s*(?:million|billion|trillion))',
        lambda m: _int_to_words(int(m.group(1))) + ' point ' + ' '.join(_ONES[int(d)] or 'zero' for d in m.group(2)),
        text,
    )

    # Numbers with scale words: 2.3 million → two point three million
    text = re.sub(
        r'\b(\d+(?:\.\d+)?)\s*(million|billion|trillion)\b',
        lambda m: (
            (_int_to_words(int(float(m.group(1)))) if float(m.group(1)) == int(float(m.group(1)))
             else _int_to_words(int(float(m.group(1)))) + ' point ' + ' '.join(
                 _ONES[int(d)] or 'zero' for d in str(m.group(1)).split('.')[-1]
             ))
            + ' ' + m.group(2)
        ),
        text, flags=re.IGNORECASE,
    )

    # 4-digit years (1000–2099) as standalone tokens → year reading,
    # unless preceded by a non-year context word (model, version, room…).
    text = re.sub(
        r'(?<!\d)([12]\d{3})(?!\d)',
        _year_or_integer,
        text,
    )

    # Integers with commas: 2,150 → two thousand one hundred and fifty
    text = re.sub(
        r'\b(\d{1,3}(?:,\d{3})+)\b',
        lambda m: _int_to_words(int(m.group(0).replace(',', ''))),
        text,
    )

    # Remaining plain integers ≥ 100 (skip single/double digits — narrator handles fine)
    text = re.sub(
        r'(?<!\d)(\d{3,})\b',
        lambda m: _int_to_words(int(m.group(1))),
        text,
    )

    return text


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
    tone: str = "curious",
) -> tuple[Path, list[WordBeat]]:
    """Synthesise `text` to MP3 and return (mp3_path, word_beats).

    backend: "elevenlabs" | "edge-tts" | None (auto: reads TTS_BACKEND env var,
             falls back to edge-tts).

    Both backends return identical output types. Swap freely.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    text = normalise_for_tts(text)

    resolved = (backend or os.getenv("TTS_BACKEND", "elevenlabs")).lower()

    elevenlabs_attempted = False
    if resolved == "elevenlabs":
        elevenlabs_attempted = True
        api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
        if not api_key:
            msg = "ELEVENLABS_API_KEY not set - falling back to edge-tts"
            print(f"  [tts] {msg}")
            _alert_tts_fallback(msg)
        else:
            try:
                result = _synthesise_elevenlabs(text, out_dir, voice, tone=tone)
                return result
            except Exception as exc:
                msg = f"ElevenLabs failed ({exc.__class__.__name__}: {exc}) - falling back to edge-tts"
                print(f"WARNING: ElevenLabs failed, using edge-tts fallback. Check ElevenLabs quota.")
                print(f"  [tts] {msg}")
                _alert_tts_fallback(msg)

    # Fallback: edge-tts (free, always available)
    if not _EDGE_TTS_AVAILABLE:
        raise RuntimeError("edge-tts is not installed. Run: pip install edge-tts")

    mp3_path = out_dir / "voice.mp3"

    # When falling back from ElevenLabs, `voice` is an ElevenLabs
    # voice_id (or one of the _EL_VOICES name shortcuts). edge-tts
    # expects a Microsoft Edge voice name like en-GB-RyanNeural and
    # ValueErrors on anything else. Swap to a known-good edge voice
    # so the fallback can actually render audio rather than crashing
    # the reel. (Live regression 2026-05-11: ElevenLabs quota
    # exhausted mid-run, fallback fired, then crashed in edge-tts
    # with `ValueError: Invalid voice 'onwK4e9ZLuTAKqWW03F9'`.)
    edge_voice = voice
    if elevenlabs_attempted or not _looks_like_edge_voice(voice):
        edge_voice = VOICE  # en-GB-RyanNeural default
        # Match ElevenLabs delivery pace so the fallback doesn't sound sluggish.
        rate = "+12%"
        print(
            f"  [tts] edge-tts fallback using voice={edge_voice} rate={rate} "
            f"(orig caller voice={voice!r} is not edge-compatible)",
            flush=True,
        )

    beats = asyncio.run(_synthesise_async(text, mp3_path, edge_voice, rate, volume))
    print(f"  [tts] {len(beats)} words, audio={mp3_path.name}, duration~{beats[-1].end_s:.1f}s" if beats else "  [tts] no beats returned")
    return mp3_path, beats


def group_into_chunks(
    beats: list[WordBeat],
    words_per_line: int = 5,
    max_chars: int = 32,
    original_text: str | None = None,
    pause_gap_s: float = 0.15,
) -> list[list[WordBeat]]:
    """Group word beats into chunks, preserving the constituent WordBeats.

    Returns a list of chunks, where each chunk is a list of WordBeats that
    belong together. Lets the caller render word-by-word reveal frames
    (kinetic subtitles) by walking through each chunk's beats in order.

    Break priority (highest to lowest):
      1. Timing gap — gap between consecutive words >= pause_gap_s always
         breaks, because the speaker has already paused. This is the most
         reliable signal: it fires on sentence ends, breath pauses, and
         em-dash pauses without needing any text heuristic.
      2. Hard punctuation — ., !, ?, ; always break.
      3. Comma — breaks when current chunk already has >= 2 words.
      4. Word/char cap — fallback when speech is uninterrupted and long.
    """
    if not beats:
        return []

    end_punct: dict[int, str] = {}
    if original_text:
        end_punct = _map_punctuation_to_beats(original_text, beats)

    chunks: list[list[WordBeat]] = []
    current: list[WordBeat] = []

    for i, beat in enumerate(beats):
        # 1. Gap break: speaker has paused — start a fresh chunk now.
        if current and i > 0:
            gap = beat.start_s - beats[i - 1].end_s
            if gap >= pause_gap_s:
                chunks.append(current)
                current = []

        current.append(beat)
        tentative_text = " ".join(b.word for b in current)
        punct = end_punct.get(i, "")

        # 2. Hard punctuation break.
        if punct in {".", "!", "?", ";"}:
            chunks.append(current)
            current = []
            continue
        # 3. Comma break (only after >= 2 words so "In 1991," splits cleanly).
        if punct == "," and len(current) >= 2:
            chunks.append(current)
            current = []
            continue
        # 4. Word/char cap fallback.
        if len(current) >= words_per_line or len(tentative_text) > max_chars:
            chunks.append(current)
            current = []

    if current:
        chunks.append(current)
    return chunks


def generate_ass_file(
    chunks: list[list[WordBeat]],
    out_path: "Path",
    *,
    play_res_x: int = 1080,
    play_res_y: int = 1920,
    font_name: str = "Archivo Bold",
    font_size: int = 72,
    margin_v: int = 140,
    voice_delay_s: float = 3.5,
    cta_start_s: float = 9999.0,
    subtitle_start_gate: float = 3.5,
) -> "Path":
    """Generate an .ass subtitle file from word-beat chunks.

    Replaces 20+ sequential PNG overlay stages with a single FFmpeg
    'ass' filter -- one filter pass regardless of subtitle count.

    libass (--enable-libass) is compiled into the static FFmpeg used
    on GitHub Actions, so no extra install is needed.

    Returns the path to the written .ass file.
    """
    from pathlib import Path as _Path

    def _ts(seconds: float) -> str:
        """Convert float seconds to ASS timestamp H:MM:SS.cc"""
        seconds = max(0.0, seconds)
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = seconds % 60
        cs = int(round((s - int(s)) * 100))
        return f"{h}:{m:02d}:{int(s):02d}.{cs:02d}"

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {play_res_x}\n"
        f"PlayResY: {play_res_y}\n"
        "WrapStyle: 1\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour,"
        " OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut,"
        " ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow,"
        " Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font_name},{font_size},"
        "&H00FFFFFF,&H000000FF,&H00000000,&HAA000000,"  # white text, dark bg
        "-1,0,0,0,100,100,0,0,1,2.5,1.5,"              # bold, no italic, border+shadow
        f"2,40,40,{margin_v},1\n"                       # bottom-centre alignment
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    dialogue_lines: list[str] = []
    for chunk_idx, chunk in enumerate(chunks):
        raw_start = chunk[0].start_s + voice_delay_s
        if chunk_idx + 1 < len(chunks):
            raw_end = chunks[chunk_idx + 1][0].start_s + voice_delay_s
        else:
            raw_end = chunk[-1].end_s + voice_delay_s + 0.35

        start = max(raw_start, subtitle_start_gate)
        end = min(raw_end, cta_start_s - 0.05)
        if start >= end:
            continue

        text = " ".join(b.word for b in chunk)
        # Escape backslashes and braces (ASS override tag delimiters)
        text = text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")

        dialogue_lines.append(
            f"Dialogue: 0,{_ts(start)},{_ts(end)},Default,,0,0,0,,{text}"
        )

    _Path(out_path).write_text(
        header + "\n".join(dialogue_lines) + "\n", encoding="utf-8"
    )
    return _Path(out_path)


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

        # Hard breaks: sentence end, semicolon - always flush
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
        # Em dash is a standalone token in text but maps to no beat word.
        # Mark the preceding beat (if any) as a hard break and move on.
        if tok in {"—", "--"}:
            if beat_idx > 0:
                end_punct[beat_idx - 1] = "."
            continue
        # Strip any leading symbols, then take the last char if it's punctuation
        trailing = ""
        if tok and tok[-1] in ".,;:!?":
            trailing = tok[-1]
        # Match - clean alphanumerics from token to compare with beat word
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
    for ffprobe in ("ffprobe", "/opt/homebrew/opt/ffmpeg-full/bin/ffprobe"):
        try:
            out = subprocess.check_output(
                [ffprobe, "-v", "quiet", "-print_format", "json", "-show_format", str(mp3_path)],
                stderr=subprocess.STDOUT,
            )
            return float(json.loads(out)["format"]["duration"])
        except Exception:
            continue
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
    tone: str = "curious",
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

    # Check quota before burning characters
    try:
        quota_resp = _req.get(
            "https://api.elevenlabs.io/v1/user/subscription",
            headers={"xi-api-key": api_key},
            timeout=10,
        )
        if quota_resp.ok:
            sub = quota_resp.json()
            used = sub.get("character_count", 0)
            limit = sub.get("character_limit", 1)
            pct_used = used / limit * 100
            if pct_used > 80:
                print(f"WARNING: ElevenLabs {pct_used:.0f}% quota used ({used}/{limit} chars)")
    except Exception as exc:
        # Quota check is best-effort. Surface failure so we know when
        # the check itself is broken (vs the quota being fine).
        print(f"[tts] ElevenLabs quota check failed: {exc}", flush=True)

    resp = _req.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps",
        json={
            "text": text,
            "model_id": EL_MODEL,
            "voice_settings": {
                # Tune by tone: shocking facts need more drama, sober facts stay measured.
                "stability":       {"shocking": 0.38, "sober": 0.65, "wholesome": 0.55}.get(tone, 0.52),
                "similarity_boost": 0.82,
                "style":           {"shocking": 0.42, "sober": 0.10, "wholesome": 0.20}.get(tone, 0.22),
                "use_speaker_boost": True,
                # daniel at default 1.0 sounds sluggish on short-form; bump delivery pace.
                "speed":           {"shocking": 1.15, "sober": 1.05, "wholesome": 1.08}.get(tone, 1.12),
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
    if beats:
        print(f"  [tts/elevenlabs] {len(beats)} words, duration~{beats[-1].end_s:.1f}s")
    else:
        print("  [tts/elevenlabs] no alignment data")
        raise RuntimeError(
            "ElevenLabs returned empty alignment data - cannot build word beats. "
            "Check the API response or fall back to edge-tts."
        )
    return mp3_path, beats


# Known voice name → ElevenLabs voice_id shortcuts. The autonomous
# production path does NOT use these - it reads ELEVENLABS_VOICE
# straight from env (see pipelines/reel/make_reel.py::_resolve_tts_voice).
# These are convenience aliases for local CLI runs and documentation.
_EL_VOICES: dict[str, str] = {
    "george":  "JBFqnCBsd6RMkjVDRZzb",  # British male, warm, authoritative
    "daniel":  "onwK4e9ZLuTAKqWW03F9",  # British male, calm, precise
    "brian":   "nPczCjzI2devNBz1zQrb",  # British male, conversational
    "charlie": "IKne3meq5aSn9XLyUdCD",  # British male, natural
    "adam":    "pNInz6obpgDQGcFmaJgB",  # American male, deep
    # factjot brand voice. Updated 2026-05-18. The production GitHub
    # Secret ELEVENLABS_VOICE points here; this alias is for local
    # CLI use and to self-document the choice.
    "factjot": "onwK4e9ZLuTAKqWW03F9",  # brand voice (daniel)
}


def _el_resolve_voice(voice: str) -> str:
    """Return a voice_id for a name shorthand or pass through a raw id."""
    low = voice.lower().strip()
    resolved = _EL_VOICES.get(low, voice)
    print(f"  [tts/elevenlabs] voice={voice} resolved={resolved}")
    return resolved


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
