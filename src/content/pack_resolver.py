"""ORPHAN — DO NOT IMPORT. Both named callers were deleted Phase G.3.

`ship_list_post.py` and `prepare_packs.py` were removed in Phase G.3 (see
`CLAUDE.md §12`). This module has no live callers and forms a mutual-import
cluster with `src/render/list_renderer.py` (which is also orphaned). The
"single source of truth" claim below is stale archaeology — preserved only
so a future agent reading the file understands what it WAS rather than
trying to wire it back in. Do not import this module to "fix list rendering"
— the active list path is `pipelines/carousel/ship_carousel_post.py
--type list` via `pipelines/manual/ship_manual_post.py`.

(Original docstring follows.)

Shared TMDB resolution logic for list carousel packs.

Used by both ship_list_post.py (post time) and prepare_packs.py (prep time).
Single source of truth — change here, both scripts benefit.
"""
from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from src.render.list_renderer import ListSlideSpec
from src.research.omdb_client import OMDbClient
from src.research.tmdb_client import TMDBClient


def slug_post_id(slug: str) -> str:
    return hashlib.sha1(f"list:{slug}".encode()).hexdigest()[:14]


def list_dedupe_claim(slug: str) -> str:
    return f"list:{slug}"


def download_asset(url: str, dest: Path) -> Path:
    if dest.exists() and dest.stat().st_size > 1024:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return dest


def _fetch_item_data(raw: dict, tmdb: TMDBClient, omdb: OMDbClient,
                     asset_root: Path, idx: int) -> dict:
    """Fetch all TMDB data for a single pack item. Called in parallel."""
    kind = raw.get("kind", "movie")
    tmdb_id = int(raw["tmdb_id"])

    if kind == "movie":
        entity = tmdb.get_movie(tmdb_id)
        credits = tmdb.get_movie_credits(tmdb_id)
        title = entity.get("title") or entity.get("original_title") or "Untitled"
        # Hard guard: if the pack item declares an expected_title, verify TMDB
        # returns a matching title. A mismatch means the ID is wrong - abort
        # immediately rather than silently posting the wrong film.
        expected = raw.get("expected_title")
        if expected and expected.lower() not in title.lower() and title.lower() not in expected.lower():
            raise RuntimeError(
                f"TMDB ID {tmdb_id} returned {title!r} but pack expects {expected!r}. "
                f"Wrong ID - fix list_packs.py before posting."
            )
        year = (entity.get("release_date") or "")[:4] or ""
        credit_name = tmdb.director_name(credits) or ""
        director = f"dir. {credit_name}" if credit_name else ""
        imdb_id = entity.get("imdb_id") or ""
        duration_min = raw.get("runtime") or entity.get("runtime") or 0
        duration_str = f"{duration_min} MIN" if duration_min else ""
        source_path = "movie"
    else:
        entity = tmdb.get_tv_show(tmdb_id)
        credits = tmdb.get_tv_credits(tmdb_id)
        title = entity.get("name") or entity.get("original_name") or "Untitled"
        expected = raw.get("expected_title")
        if expected and expected.lower() not in title.lower() and title.lower() not in expected.lower():
            raise RuntimeError(
                f"TMDB ID {tmdb_id} returned {title!r} but pack expects {expected!r}. "
                f"Wrong ID - fix list_packs.py before posting."
            )
        year = (entity.get("first_air_date") or "")[:4] or ""
        credit_name = tmdb.first_creator_name(entity, credits) or ""
        director = f"by {credit_name}" if credit_name else ""
        try:
            ext = tmdb.get_tv_external_ids(tmdb_id)
            imdb_id = ext.get("imdb_id") or ""
        except Exception:
            imdb_id = ""
        seasons = entity.get("number_of_seasons") or 0
        episodes = entity.get("number_of_episodes") or 0
        if raw.get("runtime"):
            duration_str = str(raw["runtime"]).upper()
        elif seasons and episodes:
            duration_str = f"{seasons} S · {episodes} EPS"
        elif episodes:
            duration_str = f"{episodes} EPS"
        else:
            duration_str = ""
        source_path = "tv"

    backdrop_url = TMDBClient.best_backdrop(entity)
    poster_url = TMDBClient.best_poster(entity)
    if not backdrop_url or not poster_url:
        raise RuntimeError(f"TMDB id {tmdb_id} ({title}) missing backdrop or poster")

    bd_path = download_asset(backdrop_url, asset_root / f"{idx:02d}_backdrop.jpg")
    po_path = download_asset(poster_url, asset_root / f"{idx:02d}_poster.jpg")

    imdb_score = raw.get("imdb_score", "") or ""
    rotten_score = raw.get("rotten_score", "") or ""
    if (not imdb_score or not rotten_score) and omdb.enabled and imdb_id:
        fetched = omdb.scores_by_imdb_id(imdb_id)
        imdb_score = imdb_score or fetched.get("imdb", "")
        rotten_score = rotten_score or fetched.get("rotten", "")

    genre = raw.get("genre", "") or ""
    if not genre and entity.get("genres"):
        genre = (entity["genres"][0].get("name") or "").upper()

    leading_cast = list(raw.get("leading_cast") or [])
    if not leading_cast:
        cast = sorted(credits.get("cast", []) or [], key=lambda c: c.get("order", 999))
        leading_cast = [c["name"].upper() for c in cast[:2] if c.get("name")]

    return {
        "idx": idx,
        "title": title,
        "year": year,
        "director": director,
        "hook": raw.get("hook", ""),
        "accent_word": raw.get("accent_word", ""),
        "backdrop_local_path": str(bd_path),
        "poster_local_path": str(po_path),
        "imdb_score": imdb_score,
        "rotten_score": rotten_score,
        "runtime": duration_str,
        "genre": genre,
        "leading_cast": leading_cast,
        "watch_providers": list(raw.get("watch_providers") or []),
        "source_url": f"https://www.themoviedb.org/{source_path}/{tmdb_id}",
    }


def resolve_pack(pack: dict, post_id: str,
                 parallel: bool = False) -> tuple[list[ListSlideSpec], list[dict], list[str]]:
    """Resolve a pack to slide specs, recap items, and source URLs.

    parallel=True uses ThreadPoolExecutor to fetch all items concurrently.
    Use for prepare_packs.py (Sunday prep). Keep False for post-time (safer).
    """
    from src.core.paths import LIST_ASSETS_CACHE
    asset_root = LIST_ASSETS_CACHE / post_id
    asset_root.mkdir(parents=True, exist_ok=True)

    # Instagram Graph API carousel hard cap: 10 images.
    # (The "20 frames" figure applies to Stories, not feed carousels.)
    # Hook + items + closing = total slides, so items max = 8.
    INSTAGRAM_MAX_CAROUSEL = 10
    MAX_ITEMS = INSTAGRAM_MAX_CAROUSEL - 2  # 8
    raw_items = pack["items"]
    if len(raw_items) > MAX_ITEMS:
        print(f"  [pack] trimming {len(raw_items)} items to {MAX_ITEMS} (Instagram {INSTAGRAM_MAX_CAROUSEL}-slide cap)")
        raw_items = raw_items[:MAX_ITEMS]

    tmdb = TMDBClient()
    omdb = OMDbClient()
    items = list(enumerate(raw_items, start=1))

    if parallel and len(items) > 1:
        results: dict[int, dict] = {}
        with ThreadPoolExecutor(max_workers=min(len(items), 6)) as pool:
            futures = {
                pool.submit(_fetch_item_data, raw, tmdb, omdb, asset_root, idx): idx
                for idx, raw in items
            }
            for future in as_completed(futures):
                data = future.result()   # raises on error - intentional
                results[data["idx"]] = data
        ordered = [results[i] for i, _ in items]
    else:
        ordered = [_fetch_item_data(raw, tmdb, omdb, asset_root, idx) for idx, raw in items]

    item_specs: list[ListSlideSpec] = []
    recap_items: list[dict] = []
    sources: list[str] = []

    for data in ordered:
        item_specs.append(ListSlideSpec(
            kind="item",
            title=data["title"],
            year=data["year"],
            director=data["director"],
            hook=data["hook"],
            accent_word=data["accent_word"],
            backdrop_local_path=data["backdrop_local_path"],
            poster_local_path=data["poster_local_path"],
            imdb_score=data["imdb_score"],
            rotten_score=data["rotten_score"],
            runtime=data["runtime"],
            genre=data["genre"],
            leading_cast=data["leading_cast"],
            watch_providers=data["watch_providers"],
        ))
        recap_items.append({"title": data["title"], "year": data["year"]})
        sources.append(data["source_url"])

    hook_spec = ListSlideSpec(
        kind="hook",
        title=pack["title"],
        subtitle=pack["subtitle"],
        kicker=pack["category"],
        backdrop_local_path=item_specs[0].backdrop_local_path,
    )
    closing_spec = ListSlideSpec(
        kind="closing",
        headline=pack["closing"]["headline"],
        cta=pack["closing"]["cta"],
        backdrop_local_path=item_specs[0].backdrop_local_path,
        recap_items=recap_items,
    )
    return [hook_spec, *item_specs, closing_spec], recap_items, sources
