"""Aggregate reel performance by topic and tone for soft-weighted fact selection.

Returns weights in [0.1, 1.0] normalised against the best-performing bucket.
Topics/tones with no data default to 0.5 (neutral). Uniform weights are
returned when the ledger has fewer than MIN_RECORDS reels with reach > 0,
preventing early-data bias from a single lucky reel.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

MIN_RECORDS = 3


def get_topic_weights(perf_path: Path | None = None) -> dict[str, dict[str, float]]:
    """Return {"topic": {...}, "tone": {...}} weight dicts.

    Callers treat missing keys as 0.5 (neutral). Empty dicts are returned
    during the cold-start period (< MIN_RECORDS usable records).
    """
    from src.core.paths import REEL_PERFORMANCE
    path = perf_path or REEL_PERFORMANCE
    records = _load(path)
    usable = [r for r in records if r.get("reach", 0) > 0]
    if len(usable) < MIN_RECORDS:
        return {"topic": {}, "tone": {}}

    topic_scores: dict[str, list[float]] = defaultdict(list)
    tone_scores: dict[str, list[float]] = defaultdict(list)
    for r in usable:
        er = r.get("engagement_rate", 0.0)
        t = r.get("topic", "")
        n = r.get("tone", "")
        if t:
            topic_scores[t].append(er)
        if n:
            tone_scores[n].append(er)

    return {
        "topic": _normalise(topic_scores),
        "tone":  _normalise(tone_scores),
    }


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def _normalise(scores: dict[str, list[float]]) -> dict[str, float]:
    means = {k: sum(v) / len(v) for k, v in scores.items()}
    best = max(means.values(), default=1.0)
    if best == 0:
        return {k: 0.5 for k in means}
    return {k: max(0.1, v / best) for k, v in means.items()}
