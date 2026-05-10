"""Backfill the `slot` field on data/ledgers/reel_performance.jsonl.

Background
----------
The performance ledger records reach/views/likes per reel but until
this script ran, no `slot` field was attached. The deferred monthly
performance review needs `slot` to answer "which slot performs best".

Slot inference
--------------
The schedule (3 slots/day, set in 2026-05-10 audit Phase E.5) is:

    reel_morning   09:00 BST -> 08:00 UTC   (07:00-11:00 UTC window)
    list_midday    14:00 BST -> 13:00 UTC   (11:00-17:00 UTC window)
    reel_night     20:30 BST -> 19:30 UTC   (17:00-22:00 UTC window)

`posted_at` lives slightly after the cron fire (CI bootstrap + agent
turn time + Meta processing + media_publish), typically 5-30 min later
on GitHub Actions. The windows above absorb that tail comfortably.

Anything outside those windows (manual local runs, off-cycle backfills,
old test posts) is tagged `unknown`.

Idempotency
-----------
Re-running this script is a no-op for entries that already have a
`slot` field; only entries missing the field are touched. The ledger
is rewritten in full per CLAUDE.md hard rule 1.8 (this ledger is the
one named exception to append-only).

Usage
-----
    python3 scripts/backfill_reel_performance_slot.py [--dry-run]

`--dry-run` prints the planned slot for each entry without writing.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.core.paths import REEL_PERFORMANCE  # noqa: E402


# UTC hour windows per the 3-slot schedule (Phase E.5).
# Each window is half-open: [start, end). A timestamp at the end hour
# rolls into the next window. Anything outside any window is `unknown`.
SLOT_WINDOWS: list[tuple[int, int, str]] = [
    (7,  11, "reel_morning"),
    (11, 17, "list_midday"),
    (17, 22, "reel_night"),
]


def infer_slot(posted_at_iso: str) -> str:
    """Return the slot name for a given posted_at ISO-8601 timestamp.

    Returns `unknown` if the string can't be parsed or the time of day
    falls outside any scheduled window (manual runs, backfills, etc.).
    """
    if not posted_at_iso:
        return "unknown"
    try:
        # Accept both the canonical "...Z" suffix and explicit +00:00.
        clean = posted_at_iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
    except (ValueError, TypeError):
        return "unknown"
    if dt.tzinfo is None:
        # Naive timestamps are interpreted as UTC by convention here:
        # all production posts are written with timezone-aware UTC, so
        # naive entries are old / hand-edited and should still map by
        # hour.
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    hour = dt.hour
    for start, end, name in SLOT_WINDOWS:
        if start <= hour < end:
            return name
    return "unknown"


def backfill(ledger_path: Path, *, dry_run: bool = False) -> dict:
    """Read the ledger, attach slot to entries missing one, rewrite.

    Returns a small stats dict for the CLI summary.
    """
    if not ledger_path.exists():
        return {"updated": 0, "kept": 0, "total": 0, "missing_ledger": True}

    entries: list[dict] = []
    updated = 0
    kept    = 0
    for raw in ledger_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            # Preserve unparseable lines untouched. Better to keep
            # debug context than silently delete.
            entries.append({"__raw_unparsed__": line})
            continue
        if "slot" in d and d["slot"]:
            kept += 1
        else:
            d["slot"] = infer_slot(d.get("posted_at", ""))
            updated += 1
        entries.append(d)

    if dry_run:
        for e in entries:
            if "__raw_unparsed__" in e:
                print(f"  unparsed: {e['__raw_unparsed__'][:100]}")
                continue
            print(f"  {e.get('reel_id','?')[:14]} {e.get('posted_at','')[:19]} -> slot={e.get('slot','?')}")
        return {"updated": updated, "kept": kept, "total": len(entries), "dry_run": True}

    # Full rewrite: mutable per CLAUDE.md hard rule 1.8.
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("w", encoding="utf-8") as fh:
        for e in entries:
            if "__raw_unparsed__" in e:
                fh.write(e["__raw_unparsed__"] + "\n")
            else:
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    return {"updated": updated, "kept": kept, "total": len(entries)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--ledger",
        default=str(REEL_PERFORMANCE),
        help="Path to reel_performance.jsonl (default: canonical project path)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would change, do not write the ledger.",
    )
    args = parser.parse_args(argv)

    ledger_path = Path(args.ledger)
    stats = backfill(ledger_path, dry_run=args.dry_run)
    if stats.get("missing_ledger"):
        print(f"Ledger not found: {ledger_path}")
        return 1
    mode = "would update" if args.dry_run else "updated"
    print(
        f"slot backfill: {mode}={stats['updated']} kept={stats['kept']} "
        f"total={stats['total']} ledger={ledger_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
