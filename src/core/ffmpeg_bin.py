"""Resolve the FFmpeg binary and validate features required for Reel compose.

Default Homebrew `ffmpeg` bottles often omit libass, so the `ass` filter is
missing and local `make_reel.py` fails while CI (static FFmpeg) succeeds.
Set FFMPEG_BIN to a full path (e.g. brew ffmpeg-full) when needed.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from shutil import which


def resolve_ffmpeg_bin() -> str:
    """Return path to ffmpeg: FFMPEG_BIN env, else first `ffmpeg` on PATH."""
    raw = os.environ.get("FFMPEG_BIN", "").strip()
    if raw:
        p = Path(raw).expanduser()
        if p.is_file() and os.access(p, os.X_OK):
            return str(p.resolve())
        w = which(raw)
        if w:
            return w
        raise RuntimeError(
            f"FFMPEG_BIN is set to {raw!r} but that is not an executable file "
            "and the name is not on PATH."
        )
    w = which("ffmpeg")
    if w:
        return w
    return "ffmpeg"


def assert_ffmpeg_has_ass(ffmpeg_bin: str) -> None:
    """Raise RuntimeError if this build cannot run the native subtitles filter."""
    try:
        proc = subprocess.run(
            [ffmpeg_bin, "-loglevel", "quiet", "-h", "filter=ass"],
            capture_output=True,
            timeout=20,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "ffmpeg not found. Install FFmpeg or set FFMPEG_BIN to the full path "
            "of an ffmpeg binary (see gotchas: Local macOS FFmpeg)."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"ffmpeg {ffmpeg_bin!r} timed out while probing filters."
        ) from exc

    if proc.returncode != 0:
        raise RuntimeError(
            f"The ffmpeg at {ffmpeg_bin!r} does not provide the `ass` filter "
            "(libass). Kinetic subtitles require it.\n\n"
            "Fix (Homebrew example):\n"
            "  brew install ffmpeg-full\n"
            "  export PATH=\"$(brew --prefix ffmpeg-full)/bin:$PATH\"\n"
            "or once per shell:\n"
            "  export FFMPEG_BIN=\"$(brew --prefix ffmpeg-full)/bin/ffmpeg\"\n"
            "Then re-run make_reel.py."
        )


def assert_reel_ffmpeg_ready() -> str:
    """Resolve ffmpeg and verify ASS works. Returns the path for subprocess calls."""
    fb = resolve_ffmpeg_bin()
    assert_ffmpeg_has_ass(fb)
    return fb
