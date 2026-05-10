"""Fail-loudly check that the brain is up to date.

Rule 13 says every non-trivial code change must be paired with a MEMORY_INDEX
entry. This script enforces it by failing if any source file under `src/`,
`scripts/`, or `brand/` has been modified more recently than the brain's
`MEMORY_INDEX.md` and `log.md`.

Run before shipping or as a launchd/CI gate.

Exit codes:
    0 — brain is fresh
    1 — brain is stale, manual update required
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BRAIN_FILES = [
    REPO_ROOT / "insta-brain" / "MEMORY_INDEX.md",
    REPO_ROOT / "insta-brain" / "log.md",
]
REQUIRED_MEMORY_READ_FILES = [
    REPO_ROOT / "insta-brain" / "data" / "posted.jsonl",
    # 2026-05-03: used_images.jsonl moved from data/ to data/ledgers/ when
    # paths.py unified the dedup ledger. Keeping the old path here would
    # hard-fail this check on every run because the file no longer exists.
    REPO_ROOT / "data" / "ledgers" / "used_images.jsonl",
    REPO_ROOT / "insta-brain" / "inbox.md",
]
WATCH_DIRS = ["src", "scripts", "brand", "src/render/templates"]
EXCLUDE_NAMES = {"__pycache__", ".pyc"}


def _newest_mtime(paths: list[Path]) -> tuple[float, Path | None]:
    newest_mtime = 0.0
    newest_path: Path | None = None
    for p in paths:
        if not p.exists():
            continue
        m = p.stat().st_mtime
        if m > newest_mtime:
            newest_mtime = m
            newest_path = p
    return newest_mtime, newest_path


def _walk_sources() -> list[Path]:
    out: list[Path] = []
    for d in WATCH_DIRS:
        root = REPO_ROOT / d
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if any(part in EXCLUDE_NAMES for part in p.parts):
                continue
            if p.suffix in {".pyc", ".pyo"}:
                continue
            out.append(p)
    return out


def main() -> int:
    missing = [p for p in REQUIRED_MEMORY_READ_FILES if not p.exists()]
    if missing:
        print("FAIL — required memory files are missing:")
        for p in missing:
            print(f"  - {p}")
        print("Create them before continuing.")
        return 1

    unreadable: list[Path] = []
    for p in REQUIRED_MEMORY_READ_FILES:
        try:
            p.read_text(encoding="utf-8")
        except Exception:
            unreadable.append(p)
    if unreadable:
        print("FAIL — required memory files are not readable:")
        for p in unreadable:
            print(f"  - {p}")
        return 1

    brain_mtime, brain_path = _newest_mtime(BRAIN_FILES)
    if brain_path is None:
        print("FAIL — neither MEMORY_INDEX.md nor log.md exists.")
        return 1

    sources = _walk_sources()
    src_mtime, src_path = _newest_mtime(sources)
    src_dt = datetime.fromtimestamp(src_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    brain_dt = datetime.fromtimestamp(brain_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    print(f"Newest source: {src_path}")
    print(f"  mtime:       {src_dt}")
    print(f"Newest brain:  {brain_path}")
    print(f"  mtime:       {brain_dt}")

    if src_mtime > brain_mtime + 60:  # 60s grace for clock skew
        print()
        print("STALE — source files have been modified more recently than the brain.")
        print("Append a MEMORY_INDEX entry (rule 13) and a log.md line, then re-run.")
        return 1

    print()
    print("OK — brain is up to date with source.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
