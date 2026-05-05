"""Prune old cache directories and ledger entries to keep disk usage in check.

What it touches (everything else is left alone):
    data/cache/reels/<reel_id>/        — per-reel render cache (footage, voice, overlays, final.mp4)
    data/cache/renders/<post_id>/      — per-carousel render PNGs
    insta-brain/log.md                 — rolling activity log

Safety:
    - Per-reel and per-carousel caches only get deleted if the post has already
      been published (recorded in reels.jsonl or posted.jsonl) AND is older than
      --keep-days days. We never touch a cache for an unpublished post.
    - Source-of-truth ledgers (posted.jsonl, reels.jsonl, posted_quotes.jsonl)
      are NEVER touched. They're the dedup gate; pruning them would risk
      duplicate posts.
    - --dry-run flag shows what would be deleted without touching anything.

Usage (local Mac):
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3 pipelines/shared/cleanup_caches.py --dry-run
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3 pipelines/shared/cleanup_caches.py --keep-days 7
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3 pipelines/shared/cleanup_caches.py --keep-days 14 --keep-log-lines 500

Schedule:
    Run weekly via the Sunday GitHub Actions workflow (weekly-plan.yml) or
    manually on the Mac when disk gets tight.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REELS_CACHE = REPO_ROOT / "data" / "cache" / "reels"
RENDERS_CACHE = REPO_ROOT / "data" / "cache" / "renders"
REELS_LEDGER = REPO_ROOT / "insta-brain" / "data" / "reels.jsonl"
POSTED_LEDGER = REPO_ROOT / "insta-brain" / "data" / "posted.jsonl"
LOG_PATH = REPO_ROOT / "insta-brain" / "log.md"


def _published_reel_ids() -> set[str]:
    """reel_id values that exist in reels.jsonl — safe to clean if old enough."""
    if not REELS_LEDGER.exists():
        return set()
    out: set[str] = set()
    with REELS_LEDGER.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                rid = row.get("reel_id")
                if rid:
                    out.add(rid)
            except json.JSONDecodeError:
                continue
    return out


def _published_post_ids() -> set[str]:
    """post_id values that exist in posted.jsonl — safe to clean if old enough."""
    if not POSTED_LEDGER.exists():
        return set()
    out: set[str] = set()
    with POSTED_LEDGER.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                pid = row.get("post_id")
                if pid:
                    out.add(pid)
            except json.JSONDecodeError:
                continue
    return out


def _dir_size(path: Path) -> int:
    """Total bytes in a directory tree."""
    if not path.exists():
        return 0
    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total


def _human(bytes_: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if bytes_ < 1024:
            return f"{bytes_:.1f}{unit}"
        bytes_ /= 1024
    return f"{bytes_:.1f}TB"


def _id_from_dirname(name: str) -> str:
    """Extract the post_id / reel_id from a cache directory name.

    Reel cache: directory name IS the reel_id (e.g. 'ee890ddbbfd464').
    Render cache: 'NNN_YYYYMMDD_CATEGORY_series_postid' — postid is the last
    underscore-separated chunk, always 14 hex chars.
    """
    parts = name.rsplit("_", 1)
    last = parts[-1]
    if len(last) == 14 and all(c in "0123456789abcdef" for c in last):
        return last
    return name  # fallback: try whole-name match


def prune_caches(cache_dir: Path, published_ids: set[str], keep_days: int, dry_run: bool) -> tuple[int, int]:
    """Delete subdirectories of cache_dir whose extracted id is in published_ids
    and whose mtime is older than keep_days. Returns (count_deleted, bytes_freed).
    """
    if not cache_dir.exists():
        return (0, 0)
    cutoff_ts = time.time() - keep_days * 86400
    deleted = 0
    freed = 0
    for child in sorted(cache_dir.iterdir()):
        if not child.is_dir():
            continue
        cid = _id_from_dirname(child.name)
        try:
            mtime = child.stat().st_mtime
        except OSError:
            continue
        published = cid in published_ids
        old_enough = mtime < cutoff_ts
        size = _dir_size(child)
        if published and old_enough:
            age_days = (time.time() - mtime) / 86400
            print(f"  [prune] {cid:20s} {_human(size):>9s}  age={age_days:.0f}d  {'(dry-run)' if dry_run else 'DELETING'}")
            if not dry_run:
                shutil.rmtree(child, ignore_errors=True)
            deleted += 1
            freed += size
        elif not published:
            print(f"  [keep ] {cid:20s} {_human(size):>9s}  unpublished — keeping")
        else:
            age_days = (time.time() - mtime) / 86400
            print(f"  [keep ] {cid:20s} {_human(size):>9s}  age={age_days:.0f}d (< {keep_days}d threshold)")
    return (deleted, freed)


def trim_log(log_path: Path, keep_lines: int, dry_run: bool) -> int:
    """Trim insta-brain/log.md to its last `keep_lines` lines.
    Returns the number of lines removed.
    """
    if not log_path.exists():
        return 0
    lines = log_path.read_text(encoding="utf-8").splitlines()
    if len(lines) <= keep_lines:
        return 0
    removed = len(lines) - keep_lines
    if dry_run:
        print(f"  [log  ] would trim {removed} lines (current {len(lines)} -> kept {keep_lines})")
    else:
        kept = lines[-keep_lines:]
        # Add a marker so we know it was trimmed
        header = f"<!-- log auto-trimmed {datetime.now(timezone.utc).isoformat()} - kept last {keep_lines} lines -->"
        log_path.write_text(header + "\n" + "\n".join(kept) + "\n", encoding="utf-8")
        print(f"  [log  ] trimmed {removed} lines (kept last {keep_lines})")
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report what would be deleted without touching anything")
    parser.add_argument("--keep-days", type=int, default=7, help="Keep cache dirs newer than this many days (default 7)")
    parser.add_argument("--keep-log-lines", type=int, default=500, help="Trim insta-brain/log.md to this many lines (default 500)")
    args = parser.parse_args()

    print(f"\n{'DRY RUN — no changes will be made' if args.dry_run else 'PRUNING'}\n")

    print(f"--- Reel caches (data/cache/reels/), keep_days={args.keep_days}")
    reel_ids = _published_reel_ids()
    print(f"  published reels in ledger: {len(reel_ids)}")
    rdel, rfreed = prune_caches(REELS_CACHE, reel_ids, args.keep_days, args.dry_run)

    print(f"\n--- Carousel renders (data/cache/renders/), keep_days={args.keep_days}")
    post_ids = _published_post_ids()
    print(f"  published posts in ledger: {len(post_ids)}")
    cdel, cfreed = prune_caches(RENDERS_CACHE, post_ids, args.keep_days, args.dry_run)

    print(f"\n--- Brain log (insta-brain/log.md), keep_lines={args.keep_log_lines}")
    ldel = trim_log(LOG_PATH, args.keep_log_lines, args.dry_run)

    total_freed = rfreed + cfreed
    print(f"\nSummary: {rdel + cdel} cache dirs {'would be ' if args.dry_run else ''}removed, "
          f"{_human(total_freed)} {'would be ' if args.dry_run else ''}freed, "
          f"{ldel} log lines {'would be ' if args.dry_run else ''}trimmed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
