"""Aggregate reel performance metrics into topic/tone scores.

Reads data/ledgers/reel_performance.jsonl and groups by (topic, tone).
Computes mean viral_score and engagement_rate per combination and writes:
  - data/ledgers/topic_tone_scores.json  — machine-readable, used by _pick_fact()
  - insta-brain/PERFORMANCE.md           — human-readable summary

Runs after fetch_reel_metrics.py in weekly-plan.yml and fetch-metrics.yml.
Safe to run manually at any time. Graceful no-op if ledger is empty.

Minimum sample size: 3 reels per topic/tone combo before a score is trusted.
Minimum total reels: 10 before weighting is applied at all in _pick_fact().
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PERF_LOG   = ROOT / "data" / "ledgers" / "reel_performance.jsonl"
SCORES_OUT = ROOT / "data" / "ledgers" / "topic_tone_scores.json"
PERF_MD    = ROOT / "insta-brain" / "PERFORMANCE.md"

MIN_SAMPLE = 3   # minimum reels per topic/tone before score is trusted


def load_performance() -> list[dict]:
    if not PERF_LOG.exists() or PERF_LOG.stat().st_size == 0:
        return []
    rows = []
    for line in PERF_LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return rows


def aggregate(rows: list[dict]) -> dict:
    """Group by topic/tone and compute mean scores."""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        topic = row.get("topic", "unknown")
        tone  = row.get("tone", "curious")
        key   = f"{topic}/{tone}"
        buckets[key].append(row)

    scores: dict[str, dict] = {}
    for key, items in buckets.items():
        if len(items) < MIN_SAMPLE:
            continue
        viral = [r["viral_score"] for r in items if "viral_score" in r]
        eng   = [r["engagement_rate"] for r in items if "engagement_rate" in r]
        view  = [r["view_rate"] for r in items if "view_rate" in r]
        if not viral:
            continue
        scores[key] = {
            "viral_score":     round(mean(viral), 1),
            "engagement_rate": round(mean(eng), 4) if eng else 0.0,
            "view_rate":       round(mean(view), 3) if view else 0.0,
            "n":               len(items),
        }
    return scores


def write_scores(scores: dict, total_reels: int) -> None:
    SCORES_OUT.parent.mkdir(parents=True, exist_ok=True)
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "total_reels":  total_reels,
        "min_sample":   MIN_SAMPLE,
        "scores":       scores,
    }
    SCORES_OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"  [score] wrote {len(scores)} topic/tone scores -> {SCORES_OUT.name}")


def write_markdown(scores: dict, rows: list[dict]) -> None:
    PERF_MD.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# factjot Performance Report",
        f"\n_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_",
        f"\n**{len(rows)} reels tracked** | **{len(scores)} topic/tone combos with ≥{MIN_SAMPLE} samples**\n",
    ]

    if scores:
        # Sort by viral_score descending
        ranked = sorted(scores.items(), key=lambda x: -x[1]["viral_score"])
        lines.append("## Topic/Tone Performance (ranked by viral score)\n")
        lines.append("| Topic/Tone | Viral Score | Engagement Rate | View Rate | Reels |")
        lines.append("|------------|-------------|-----------------|-----------|-------|")
        for key, s in ranked:
            lines.append(
                f"| {key} | {s['viral_score']} | {s['engagement_rate']:.1%} "
                f"| {s['view_rate']:.0%} | {s['n']} |"
            )
    else:
        lines.append("_Not enough data yet — need at least 3 reels per topic/tone combo._\n")

    # Recent reels table
    if rows:
        recent = sorted(rows, key=lambda r: r.get("posted_at", ""), reverse=True)[:10]
        lines.append("\n## Recent Reels\n")
        lines.append("| Title | Topic | Tone | Viral | Reach | Saves |")
        lines.append("|-------|-------|------|-------|-------|-------|")
        for r in recent:
            title = (r.get("reel_title") or r.get("claim", "")[:40]).replace("|", "/")
            lines.append(
                f"| {title[:40]} | {r.get('topic','')} | {r.get('tone','')} "
                f"| {r.get('viral_score', 0)} | {r.get('reach', 0):,} | {r.get('saves', 0)} |"
            )

    PERF_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  [score] wrote performance report -> {PERF_MD.name}")


def main() -> int:
    rows = load_performance()
    if not rows:
        print("  [score] reel_performance.jsonl is empty — nothing to score (no-op)")
        # Write empty scores file so _pick_fact() doesn't error on missing file
        write_scores({}, 0)
        return 0

    print(f"  [score] {len(rows)} reel records found")
    scores = aggregate(rows)
    write_scores(scores, len(rows))
    write_markdown(scores, rows)

    if scores:
        best = max(scores.items(), key=lambda x: x[1]["viral_score"])
        print(f"  [score] top performer: {best[0]} (viral={best[1]['viral_score']})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
