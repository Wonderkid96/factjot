"""Resolve the FFmpeg binary and validate it works for Reel compose.

Set FFMPEG_BIN to override the binary. On macOS the default Homebrew ffmpeg
periodically breaks after a libvpx upgrade (stale dyld references). When the
default ffmpeg fails its -version probe, this module auto-falls-back to brew
ffmpeg-full if it's installed, so a libvpx breakage doesn't block reel runs.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from shutil import which


_FALLBACK_PATHS = (
    "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",   # Apple Silicon
    "/usr/local/opt/ffmpeg-full/bin/ffmpeg",      # Intel Mac
)


def _probe(ffmpeg_bin: str) -> "tuple[bool, str]":
    """Run `ffmpeg -version`. Returns (ok, stderr_excerpt)."""
    try:
        proc = subprocess.run(
            [ffmpeg_bin, "-version"], capture_output=True, timeout=20
        )
    except FileNotFoundError:
        return False, "binary not found"
    except subprocess.TimeoutExpired:
        return False, "version probe timed out"
    if proc.returncode == 0:
        return True, ""
    return False, proc.stderr.decode("utf-8", errors="replace")[:500]


def _find_fallback() -> "str | None":
    """Return path to a working brew ffmpeg-full if one exists, else None."""
    for cand in _FALLBACK_PATHS:
        if Path(cand).is_file() and os.access(cand, os.X_OK):
            ok, _ = _probe(cand)
            if ok:
                return cand
    return None


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
    ok, stderr = _probe(ffmpeg_bin)
    if ok:
        return
    if stderr == "binary not found":
        raise RuntimeError(
            "ffmpeg not found. Install FFmpeg or set FFMPEG_BIN to the full path "
            "of a working ffmpeg binary.\n"
            "On macOS: brew install ffmpeg-full && "
            "export FFMPEG_BIN=\"$(brew --prefix ffmpeg-full)/bin/ffmpeg\""
        )
    if stderr == "version probe timed out":
        raise RuntimeError(f"ffmpeg {ffmpeg_bin!r} timed out on -version probe.")
    raise RuntimeError(
        f"ffmpeg at {ffmpeg_bin!r} failed to run.\nStderr: {stderr}\n"
        "On macOS this usually means a broken dynamic library (e.g. libvpx updated).\n"
        "Fix: brew install ffmpeg-full && "
        "export FFMPEG_BIN=\"$(brew --prefix ffmpeg-full)/bin/ffmpeg\""
    )


def assert_reel_ffmpeg_ready() -> str:
    """Resolve ffmpeg and verify it runs. Returns the path for subprocess calls.

    If the resolved binary fails (typical libvpx-after-brew-upgrade breakage on
    macOS) AND FFMPEG_BIN was not explicitly set, try brew ffmpeg-full as a
    fallback before raising. Keeps local Mac runs unblocked without requiring
    a manual env var; CI is unaffected because its PATH ffmpeg works fine.
    """
    fb = resolve_ffmpeg_bin()
    ok, stderr = _probe(fb)
    if ok:
        return fb

    user_pinned = bool(os.environ.get("FFMPEG_BIN", "").strip())
    if not user_pinned:
        fallback = _find_fallback()
        if fallback:
            print(
                f"[ffmpeg_bin] default ffmpeg at {fb!r} failed -version probe; "
                f"falling back to {fallback}"
            )
            return fallback

    assert_ffmpeg_runs(fb)  # raises with the original error message
    return fb  # unreachable
