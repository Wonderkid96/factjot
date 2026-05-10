"""Weekly trend scout for factjot content planning.

Fetches two signals every Sunday:

1. TMDB trending movies + TV (this week)
   Used to auto-generate a "Trending This Week" list pack so there's
   always a fresh, timely list post without manual curation.

2. Reddit r/todayilearned hot posts
   Titles are parsed for factjot topic keywords to produce a topic
   weight map. plan_week.py uses this to prioritise which topic gets
   the first carousel slot and which q3 fact runs as that day's Reel.

No API keys beyond TMDB_READ_TOKEN (already in .env).
Reddit's JSON endpoint is public - no key needed.

Usage:
    from src.research.trend_scout import fetch_weekly_trends
    trends = fetch_weekly_trends()
    # trends['movies'], trends['tv'], trends['topic_weights']
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

_TIMEOUT = 12
_TMDB_BASE = "https://api.themoviedb.org/3"

# ------------------------------------------------------------------ #
# Topic keyword map - used to score Reddit TIL headlines
# ------------------------------------------------------------------ #
_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "space":      ["space", "galaxy", "universe", "planet", "star ", "asteroid",
                   "nasa", "orbit", "astronaut", "black hole", "comet", "solar",
                   "mars", "moon", "saturn", "jupiter", "telescope", "nebula"],
    "ocean":      ["ocean", "sea ", "marine", "shark", "whale", "deep sea",
                   "coral", "submarine", "underwater", "fish ", "dolphin",
                   "squid", "octopus", "jellyfish", "tide"],
    "biology":    ["animal", "species", "evolution", "dna", "bacteria", "virus",
                   "mammal", "bird ", "insect", "plant ", "fungi", "parasite",
                   "gene", "cell ", "brain ", "fossil", "creature", "migration"],
    "earth":      ["volcano", "earthquake", "geology", "climate", "glacier",
                   "continent", "cave", "desert", "mountain", "fossil",
                   "atmosphere", "tectonic", "erosion", "mineral"],
    "history":    ["history", "ancient", "medieval", "empire", "war ", "battle",
                   "century", "roman", "greek", "egypt", "viking", "napoleon",
                   "ww2", "wwii", "world war", "revolution", "slavery", "king ",
                   "queen ", "pharaoh", "civilisation", "civilization"],
    "technology": ["computer", "internet", "robot", "software", "code", "tech",
                   "invention", "engineer", "electricity", "telephone", "radio",
                   "algorithm", "silicon", "artificial intelligence", "ai "],
}


# ------------------------------------------------------------------ #
# TMDB trending
# ------------------------------------------------------------------ #

def _tmdb_headers() -> dict:
    token = os.environ.get("TMDB_READ_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TMDB_READ_TOKEN missing from .env")
    return {"Authorization": f"Bearer {token}", "accept": "application/json"}


def _fetch_tmdb_trending(kind: str = "movie") -> list[dict]:
    """Return top trending movies or TV shows this week from TMDB."""
    try:
        r = requests.get(
            f"{_TMDB_BASE}/trending/{kind}/week",
            headers=_tmdb_headers(),
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return r.json().get("results", [])
    except Exception as exc:
        print(f"  [trends] TMDB trending/{kind} failed: {exc}")
        return []


def _tmdb_movie_details(item: dict) -> dict:
    """Extract the fields we need for list pack generation."""
    release = item.get("release_date") or item.get("first_air_date") or ""
    year = release[:4] if release else ""
    return {
        "tmdb_id":      item.get("id"),
        "title":        item.get("title") or item.get("name", ""),
        "year":         year,
        "overview":     item.get("overview", ""),
        "backdrop_path": item.get("backdrop_path"),
        "poster_path":  item.get("poster_path"),
        "genre_ids":    item.get("genre_ids", []),
        "vote_average": item.get("vote_average", 0),
        "popularity":   item.get("popularity", 0),
    }


# ------------------------------------------------------------------ #
# Reddit topic signals
# ------------------------------------------------------------------ #

def _fetch_reddit_topic_weights() -> dict[str, int]:
    """Score factjot topics from r/todayilearned hot posts.

    Returns a dict like {'space': 4, 'history': 3, 'biology': 2, ...}
    Higher = more posts this week about that topic.
    """
    weights: dict[str, int] = {t: 0 for t in _TOPIC_KEYWORDS}
    try:
        r = requests.get(
            "https://www.reddit.com/r/todayilearned/hot.json",
            params={"limit": 25},
            headers={"User-Agent": "factjot-planner/1.0"},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        posts = r.json().get("data", {}).get("children", [])
        for post in posts:
            title = post.get("data", {}).get("title", "").lower()
            for topic, keywords in _TOPIC_KEYWORDS.items():
                if any(kw in title for kw in keywords):
                    weights[topic] += 1
    except Exception as exc:
        print(f"  [trends] Reddit fetch failed: {exc}")

    return weights


# ------------------------------------------------------------------ #
# Public API
# ------------------------------------------------------------------ #

def fetch_weekly_trends() -> dict:
    """Fetch this week's trending content and topic signals.

    Returns:
        {
            'movies':        list of TMDB movie dicts (top trending, with backdrop),
            'tv':            list of TMDB TV dicts (top trending, with backdrop),
            'topic_weights': dict[topic, int] - Reddit TIL signal scores,
            'top_topic':     str - highest-weighted factjot topic this week,
            'fetched_at':    ISO timestamp,
        }
    """
    print("  [trends] fetching TMDB trending movies...")
    raw_movies = _fetch_tmdb_trending("movie")
    movies = [
        _tmdb_movie_details(m) for m in raw_movies
        if m.get("backdrop_path")  # must have backdrop for list rendering
    ][:10]

    print(f"  [trends] fetching TMDB trending TV...")
    raw_tv = _fetch_tmdb_trending("tv")
    tv = [
        _tmdb_movie_details(m) for m in raw_tv
        if m.get("backdrop_path")
    ][:10]

    print("  [trends] scoring Reddit TIL topic signals...")
    topic_weights = _fetch_reddit_topic_weights()
    top_topic = max(topic_weights, key=lambda t: topic_weights[t]) if topic_weights else "history"

    result = {
        "movies":        movies,
        "tv":            tv,
        "topic_weights": topic_weights,
        "top_topic":     top_topic,
        "fetched_at":    datetime.now(timezone.utc).isoformat(),
    }

    # Cache to disk so plan_week can inspect it without re-fetching
    cache_dir = Path(__file__).resolve().parents[2] / "data" / "trends"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / "current.json"
    cache_path.write_text(json.dumps(result, indent=2))
    print(f"  [trends] saved to {cache_path}")

    return result


def load_cached_trends() -> dict | None:
    """Return the most recently fetched trend data, or None if not available."""
    cache_path = Path(__file__).resolve().parents[2] / "data" / "trends" / "current.json"
    if not cache_path.exists():
        return None
    try:
        return json.loads(cache_path.read_text())
    except Exception:
        return None
