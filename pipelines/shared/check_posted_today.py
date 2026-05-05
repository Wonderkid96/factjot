"""Check if a post of the given type was already published today.

Usage (GitHub Actions uses bare python3; local Mac uses full path):
    python3 pipelines/shared/check_posted_today.py carousel
    python3 pipelines/shared/check_posted_today.py reel
    python3 pipelines/shared/check_posted_today.py list

Exit codes:
    0 = not posted yet today (workflow should proceed)
    1 = already posted today (workflow should skip)
    2 = error (caller should treat as not posted to be safe)

Used by GitHub Actions workflows for idempotency. Avoids inline Python
in workflow YAML (GitHub's YAML parser doesn't like multiline Python
inside bash heredocs).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: check_posted_today.py {carousel|reel|list}", file=sys.stderr)
        return 2

    kind = sys.argv[1].lower()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if kind == "reel":
        ledger = Path("insta-brain/data/reels.jsonl")
        match = lambda row: row.get("published_at", "").startswith(today)
    elif kind == "carousel":
        ledger = Path("insta-brain/data/posted.jsonl")
        match = lambda row: (
            row.get("published_at", "").startswith(today)
            and row.get("category", "CAROUSEL") == "CAROUSEL"
            and not str(row.get("claim", "")).startswith("list:")
        )
    elif kind == "list":
        # Check list_posts.jsonl (permanent) AND posted.jsonl.
        # list_posts.jsonl is more reliable — never wiped, always current.
        list_posts = Path("insta-brain/data/list_posts.jsonl")
        if list_posts.exists():
            try:
                for line in list_posts.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if (
                        row.get("published_at", "").startswith(today)
                        and row.get("ig_media_id") != "skip"
                    ):
                        print("already_posted")
                        return 1
            except Exception:
                pass
        ledger = Path("insta-brain/data/posted.jsonl")
        match = lambda row: (
            row.get("published_at", "").startswith(today)
            and str(row.get("claim", "")).startswith("list:")
        )
    else:
        print(f"unknown kind: {kind}", file=sys.stderr)
        return 2

    if not ledger.exists():
        print("not_posted")
        return 0

    try:
        for line in ledger.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if match(row):
                print("already_posted")
                return 1
    except Exception as exc:
        print(f"check failed: {exc}", file=sys.stderr)
        print("not_posted")
        return 0

    print("not_posted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
