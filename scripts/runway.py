"""Report how many fresh (unposted) facts remain per topic.

Run this any time before scheduling a week's worth of posts. If any topic
has fewer than `MIN_RUNWAY` fresh facts left, the script exits non-zero
so launchd / cron can alert.

Usage:
    python3 scripts/runway.py
    python3 scripts/runway.py --min 7      # alert threshold
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.brain import brain, claim_hash
from src.research.rare_fact_bank import RARE_FACT_BANK


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min", type=int, default=7,
                        help="Minimum fresh facts per topic before runway is considered low (default 7)")
    args = parser.parse_args()

    by_topic: dict[str, list[dict]] = defaultdict(list)
    for row in RARE_FACT_BANK:
        by_topic[row["topic"]].append(row)

    total_fresh = 0
    total_used = 0
    low_topics: list[str] = []

    print(f"{'topic':<14} {'total':>6} {'used':>6} {'fresh':>6}")
    print("-" * 38)
    for topic in sorted(by_topic.keys()):
        rows = by_topic[topic]
        used = sum(1 for r in rows if brain.is_fact_posted(r["claim"]))
        fresh = len(rows) - used
        total_fresh += fresh
        total_used += used
        flag = "  LOW" if fresh < args.min else ""
        print(f"{topic:<14} {len(rows):>6} {used:>6} {fresh:>6}{flag}")
        if fresh < args.min:
            low_topics.append(topic)

    print("-" * 38)
    print(f"{'TOTAL':<14} {sum(len(v) for v in by_topic.values()):>6} {total_used:>6} {total_fresh:>6}")
    print()

    days_runway = total_fresh // 6  # 6 facts per carousel
    print(f"Runway at 1 carousel/day: ~{days_runway} days")

    if low_topics:
        print()
        print(f"WARNING: low runway in topic(s): {', '.join(low_topics)}")
        print(f"Add fresh facts to bank/<topic>.md or src/research/rare_fact_bank.py")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
