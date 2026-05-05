"""Validate that every reel-eligible fact has the curated content required
to produce a long, high-quality reel.

Born from the 2026-05-01 incident: a Switzerland fact lacking `reel_script`
fell through the auto-generator and produced a 22.7-second reel with the
nonsense title "The Story of Until Switzerland".

What this checks (each q3 fact, except those marked `sensitivity:
controversial` which are filtered out of autonomous publishing):
  1. has `reel_title`
  2. has `reel_script`
  3. reel_script word count >= MIN_REEL_SCRIPT_WORDS
  4. neither field contains an em-dash (brand voice rule)

Exit codes:
  0 = all facts pass
  1 = one or more failures (CI-friendly)

Run:
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
        pipelines/reel/validate_reel_facts.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.research.rare_fact_bank import RARE_FACT_BANK
from src.research.sensitivity_guide import CONTROVERSIAL


MIN_REEL_SCRIPT_WORDS = 70
MAX_REEL_SCRIPT_WORDS = 100  # above 100 words = 50s+ reel = CI timeout risk


def main() -> int:
    q3 = [f for f in RARE_FACT_BANK if f.get("quirky_score") == 3]
    eligible = [f for f in q3 if f.get("sensitivity") != CONTROVERSIAL]

    failures: list[tuple[str, str]] = []  # (claim_short, reason)

    for f in eligible:
        claim_short = f["claim"][:70]
        if not f.get("reel_title"):
            failures.append((claim_short, "missing reel_title"))
        elif "—" in f["reel_title"] or "–" in f["reel_title"]:
            failures.append((claim_short, "reel_title contains em-dash (brand rule)"))

        if not f.get("reel_script"):
            failures.append((claim_short, "missing reel_script"))
            continue

        wc = len(f["reel_script"].split())
        if wc < MIN_REEL_SCRIPT_WORDS:
            failures.append((claim_short, f"reel_script {wc} words < floor {MIN_REEL_SCRIPT_WORDS}"))
        elif wc > MAX_REEL_SCRIPT_WORDS:
            failures.append((claim_short, f"reel_script {wc} words > ceiling {MAX_REEL_SCRIPT_WORDS} (reel too long for CI)"))

        if "—" in f["reel_script"] or "–" in f["reel_script"]:
            failures.append((claim_short, "reel_script contains em-dash (brand rule)"))

    print(f"q3 total: {len(q3)} | eligible (non-controversial): {len(eligible)}")
    print(f"checks: reel_title, reel_script, word_count {MIN_REEL_SCRIPT_WORDS}-{MAX_REEL_SCRIPT_WORDS}, no em-dashes")
    print()

    if not failures:
        print("PASS — every reel-eligible fact has curated long-form content.")
        return 0

    print(f"FAIL — {len(failures)} issue(s):")
    for claim, reason in failures:
        print(f"  - {reason}")
        print(f"    {claim}")
    print()
    print("Add or extend the curated reel_title / reel_script in")
    print("src/research/rare_fact_bank.py for each fact above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
