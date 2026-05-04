"""Resolve the FFmpeg binary and validate it works for Reel compose.

Set FFMPEG_BIN to override the binary (e.g. brew ffmpeg-full when system ffmpeg
has broken dependencies). On macOS the default Homebrew ffmpeg may have stale
dynamic library references after upgrades.
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


def assert_ffmpeg_runs(ffmpeg_bin: str) -> None:
    """Raise RuntimeError if the binary cannot execute at all."""
    try:
        proc = subprocess.run(
            [ffmpeg_bin, "-version"],
            capture_output=True,
            timeout=20,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "ffmpeg not found. Install FFmpeg or set FFMPEG_BIN to the full path "
            "of a working ffmpeg binary.\n"
            "On macOS: brew install ffmpeg-full && "
            "export FFMPEG_BIN=\"$(brew --prefix ffmpeg-full)/bin/ffmpeg\""
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"ffmpeg {ffmpeg_bin!r} timed out on -version probe."
        ) from exc

    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace")[:500]
        raise RuntimeError(
            f"ffmpeg at {ffmpeg_bin!r} failed to run (exit {proc.returncode}).\n"
            f"Stderr: {stderr}\n"
            "On macOS this usually means a broken dynamic library (e.g. libvpx updated).\n"
            "Fix: brew install ffmpeg-full && "
            "export FFMPEG_BIN=\"$(brew --prefix ffmpeg-full)/bin/ffmpeg\""
        )


def assert_reel_ffmpeg_ready() -> str:
    """Resolve ffmpeg and verify it runs. Returns the path for subprocess calls."""
    fb = resolve_ffmpeg_bin()
    assert_ffmpeg_runs(fb)
    return fb
