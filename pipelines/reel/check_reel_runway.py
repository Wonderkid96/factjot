"""Print the count of reel-eligible facts remaining (q3 + q2, unposted).

Used by the reel workflow runway check. Output is a single integer.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.brain import brain
from src.research.rare_fact_bank import load_all_facts


def main() -> int:
    facts = load_all_facts()
    eligible = [
        f for f in facts
        if f.get("quirky_score", 0) >= 2
        and not brain.is_fact_posted(f["claim"])
    ]
    print(len(eligible))
    return 0


if __name__ == "__main__":
    sys.exit(main())
