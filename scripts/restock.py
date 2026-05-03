"""factjot restock — runway report + fact discovery.

Run automatically every Sunday via weekly-plan.yml (GitHub Actions).
Also run manually or via Claude Code routine for enrichment.

What it does:
  1. Reports reel and carousel runway per topic
  2. Runs discover_facts.py to pull fresh Reddit TIL facts
  3. Lists discovered facts that need reel enrichment (reel_script + reel_title)

When run inside a Claude Code session, Claude reads the enrichment list
and writes reel_script + reel_title directly into rare_fact_bank.py for
any qualifying facts, then commits. This closes the reel runway gap
without requiring Claude API credits.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.brain import brain
from src.research.rare_fact_bank import load_all_facts, RARE_FACT_BANK
from src.core.paths import DISCOVERED_FACTS

MIN_REEL_SCRIPT_WORDS  = 70
MIN_CAROUSEL_SCORE     = 2   # must match ship_first_post.py — never lower without updating both
REEL_RUNWAY_WARN       = 30
REEL_RUNWAY_CRITICAL   = 14
CAROUSEL_RUNWAY_WARN   = 14
TOPICS = ["space", "earth", "ocean", "biology", "history", "technology"]


def _reel_runway() -> int:
    facts = load_all_facts()
    return sum(
        1 for f in facts
        if f.get("quirky_score", 0) >= 3
        and f.get("reel_title")
        and f.get("reel_script")
        and len(f.get("reel_script", "").split()) >= MIN_REEL_SCRIPT_WORDS
        and not brain.is_fact_posted(f["claim"])
    )


def _carousel_runway() -> dict[str, int]:
    """Count unposted facts per topic at or above the carousel quality floor.

    Only facts with quirky_score >= MIN_CAROUSEL_SCORE are counted because
    ship_first_post.py will not post score=1 facts unless the bank is in
    emergency mode. Counting them would give a falsely optimistic runway.
    """
    facts = load_all_facts()
    counts: dict[str, int] = {t: 0 for t in TOPICS}
    for f in facts:
        topic = f.get("topic", "").lower()
        if (topic in counts
                and not brain.is_fact_posted(f["claim"])
                and f.get("quirky_score", 1) >= MIN_CAROUSEL_SCORE):
            counts[topic] += 1
    return counts


def _needs_enrichment() -> list[dict]:
    if not DISCOVERED_FACTS.exists():
        return []
    curated_claims = {f["claim"] for f in RARE_FACT_BANK}
    out = []
    for line in DISCOVERED_FACTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("quirky_score", 0) < 2:
            continue
        if row.get("claim") in curated_claims:
            continue
        if row.get("reel_script") and row.get("reel_title"):
            continue
        if brain.is_fact_posted(row.get("claim", "")):
            continue
        out.append(row)
    return out


def _status(value: int, warn: int, critical: int) -> str:
    if value >= warn:
        return "OK"
    if value >= critical:
        return "WARN"
    return "CRITICAL"


def main() -> int:
    print("=" * 62)
    print("  factjot RESTOCK REPORT")
    print("=" * 62)

    reel_count = _reel_runway()
    reel_st = _status(reel_count, REEL_RUNWAY_WARN, REEL_RUNWAY_CRITICAL)
    print(f"\nREEL RUNWAY:   {reel_count} days  [{reel_st}]")
    if reel_st != "OK":
        print(f"  Target >= {REEL_RUNWAY_WARN}. Add q3 facts with reel_script + reel_title.")

    print("\nCAROUSEL RUNWAY (unposted facts per topic):")
    for topic, count in sorted(_carousel_runway().items()):
        st = "OK" if count >= CAROUSEL_RUNWAY_WARN else ("WARN" if count >= 7 else "LOW")
        print(f"  {topic:<14} {count:>3} facts  [{st}]")

    print("\nRUNNING FACT DISCOVERY (r/todayilearned)...")
    result = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "discover_facts.py")],
    )
    if result.returncode != 0:
        print("  Discovery failed (network issue?). Continuing with existing bank.")

    enrichment = _needs_enrichment()
    print(f"\nFACTS NEEDING REEL ENRICHMENT: {len(enrichment)}")
    if enrichment:
        print("  Discovered facts with quirky_score >= 2, no reel_script / reel_title.")
        print("  Add to RARE_FACT_BANK with full reel fields to make them postable.\n")
        for i, f in enumerate(enrichment, 1):
            score = f.get("quirky_score", "?")
            topic = f.get("topic", "?")
            claim = f.get("claim", "")[:140]
            hint  = f.get("image_hint", "")
            src   = (f.get("sources") or ["?"])[0][:80]
            print(f"  [{i}] score={score}  topic={topic}")
            print(f"       claim: {claim}")
            print(f"       hint:  {hint}")
            print(f"       src:   {src}")
            print()
    else:
        print("  None. All eligible discovered facts are already enriched.")

    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
