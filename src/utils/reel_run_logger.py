"""Structured logging for local `make_reel.py` runs.

Writes timestamped lines to:
  - `output/reel/<reel_id>/pipeline.log` (next to FFmpeg artefacts)
  - `logs/reel_runs/<UTC>_<reel_id>.log` (central history)

Also mirrors each line to stdout with flush so terminals and CI see progress.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType


class ReelRunLogger:
    def __init__(self, *, reel_id: str, out_dir: Path, run_logs_dir: Path) -> None:
        self._handles: list[tuple[Path, object]] = []
        run_logs_dir.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        paths = (
            out_dir / "pipeline.log",
            run_logs_dir / f"{ts}_{reel_id}.log",
        )
        for p in paths:
            fh = p.open("w", encoding="utf-8")
            self._handles.append((p, fh))
        self.emit(f"reel_id={reel_id} pid={os.getpid()} python={sys.executable}")
        self.emit(f"cwd={os.getcwd()}")

    def emit(self, msg: str) -> None:
        line = f"{datetime.now(timezone.utc).isoformat()} | {msg}"
        for _p, fh in self._handles:
            fh.write(line + "\n")
            fh.flush()
        print(msg, flush=True)

    def close(self) -> None:
        for _p, fh in self._handles:
            try:
                fh.close()
            except OSError:
                pass
        self._handles.clear()


_LOCK_FILE: object | None = None


def acquire_local_make_reel_lock(reels_cache: Path) -> None:
    """Advisory exclusive lock: only one local make_reel at a time.

    Prevents stacked FFmpeg jobs when several agents or terminals run the script.
    No-op on Windows (fcntl unavailable).
    """
    global _LOCK_FILE
    if _LOCK_FILE is not None:
        return
    try:
        import fcntl  # type: ignore[attr-defined]
    except ImportError:
        return

    reels_cache.mkdir(parents=True, exist_ok=True)
    path = reels_cache / ".make_reel.lock"
    f = open(path, "a+", encoding="utf-8")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        raise RuntimeError(
            "Another `make_reel.py` is already running locally (lock: "
            f"{path}). Wait for it to finish, or run "
            "`scripts/kill_local_reel_jobs.sh` if it is a stale run."
        ) from None
    f.seek(0)
    f.truncate()
    f.write(f"{os.getpid()}\n{datetime.now(timezone.utc).isoformat()}\n")
    f.flush()
    _LOCK_FILE = f


def release_local_make_reel_lock() -> None:
    global _LOCK_FILE
    if _LOCK_FILE is None:
        return
    try:
        import fcntl

        fcntl.flock(_LOCK_FILE.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        _LOCK_FILE.close()
    except OSError:
        pass
    _LOCK_FILE = None


class local_make_reel_lock:
    """Context manager: exclusive local `make_reel` (see acquire_local_make_reel_lock)."""

    def __init__(self, reels_cache: Path) -> None:
        self._reels_cache = reels_cache

    def __enter__(self) -> None:
        acquire_local_make_reel_lock(self._reels_cache)

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        release_local_make_reel_lock()
