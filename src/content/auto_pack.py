"""Auto-generate a list pack from TMDB trending data.

Used by plan_week.py every Sunday to create a "Trending This Week"
list post without manual curation. The hook text comes from TMDB's
own overview, trimmed and made punchy. Not as polished as hand-crafted
hooks but always fresh and timely.

The generated pack is written to src/content/list_packs_auto.py (not the
hand-curated list_packs.py) so it never overwrites Toby's curated packs.
It is also saved as data/trends/auto_pack_YYYY-WW.json for inspection.

Usage:
    from src.content.auto_pack import build_trending_pack
    pack = build_trending_pack(movies, posted_tmdb_ids)
    if pack:
        # pass to ship_list_post.py or queue for this week
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path


# TMDB genre_id → short label for the slide pill
_GENRE_LABELS: dict[int, str] = {
    28: "ACTION", 12: "ADVENTURE", 16: "ANIMATION", 35: "COMEDY",
    80: "CRIME", 99: "DOCUMENTARY", 18: "DRAMA", 10751: "FAMILY",
    14: "FANTASY", 36: "HISTORY", 27: "HORROR", 10402: "MUSIC",
    9648: "MYSTERY", 10749: "ROMANCE", 878: "SCI-FI", 10770: "TV MOVIE",
    53: "THRILLER", 10752: "WAR", 37: "WESTERN",
}


def _make_hook(overview: str, title: str) -> str:
    """Convert TMDB overview into a punchy factjot-style hook.

    Takes the first 1-2 sentences, caps at 160 chars. Not hand-crafted
    but clean enough for an auto-generated trending pack.
    """
    if not overview:
        return f"One of this week's most-watched films. {title} is trending now."
    sentences = re.split(r"(?<=[.!?])\s+", overview.strip())
    hook = " ".join(sentences[:2])
    if len(hook) > 160:
        hook = hook[:157] + "..."
    return hook


def _genre_label(genre_ids: list[int]) -> str:
    for gid in genre_ids:
        if gid in _GENRE_LABELS:
            return _GENRE_LABELS[gid]
    return "FILM"


def build_trending_pack(
    movies: list[dict],
    posted_tmdb_ids: set[int] | None = None,
    count: int = 5,
) -> dict | None:
    """Build a list pack dict from TMDB trending movies.

    Args:
        movies:          List of TMDB movie dicts from trend_scout.
        posted_tmdb_ids: Set of TMDB IDs already used in published packs
                         (prevents reposting the same film).
        count:           Number of items to include (default 5).

    Returns:
        A list pack dict ready to pass to ship_list_post.py,
        or None if fewer than 4 usable films are available.
    """
    posted = posted_tmdb_ids or set()

    # Filter: needs backdrop, not already posted, has an overview
    candidates = [
        m for m in movies
        if m.get("backdrop_path")
        and m.get("tmdb_id") not in posted
        and m.get("overview")
        and m.get("title")
    ]

    if len(candidates) < 4:
        return None

    items = []
    for m in candidates[:count]:
        items.append({
            "kind":         "movie",
            "tmdb_id":      m["tmdb_id"],
            "hook":         _make_hook(m["overview"], m["title"]),
            "accent_word":  None,
            "genre":        _genre_label(m.get("genre_ids", [])),
        })

    now = datetime.now(timezone.utc)
    week_str = now.strftime("%Y-W%W")
    slug = f"trending_{week_str.replace('-', '_').lower()}"

    pack = {
        "slug":     slug,
        "title":    f"Five films everyone is watching right now",
        "subtitle": f"week of {now.strftime('%d %B %Y')}.",
        "category": "TRENDING",
        "series":   "factjot",
        "auto_generated": True,
        "items":    items,
        "closing": {
            "headline": "All streaming now.",
            "cta":      "Follow @factjot for more picks every week.",
        },
        "caption": (
            f"Five films trending this week — {now.strftime('%B %Y')}.\n\n"
            "Follow @factjot for weekly picks."
        ),
    }

    # Save for inspection + record-keeping
    out_dir = Path(__file__).resolve().parents[2] / "data" / "trends"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"auto_pack_{week_str}.json"
    out_path.write_text(json.dumps(pack, indent=2))
    print(f"  [auto_pack] saved to {out_path}")

    return pack


def get_posted_tmdb_ids() -> set[int]:
    """Return all TMDB IDs already published in list posts.

    Reads the brain's posted.jsonl and extracts tmdb_ids from any
    list-type entries so we never feature the same film twice.
    """
    posted: set[int] = set()
    ledger = Path(__file__).resolve().parents[2] / "insta-brain" / "data" / "posted.jsonl"
    if not ledger.exists():
        return posted
    try:
        with ledger.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    for item in row.get("items", []):
                        tid = item.get("tmdb_id")
                        if tid:
                            posted.add(int(tid))
                except Exception:
                    pass
    except Exception:
        pass
    return posted
