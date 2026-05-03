"""Render and (optionally) publish a list-format carousel.

Different pipeline from ship_first_post.py:
    1. Load curated pack from `src/content/list_packs.py`.
    2. Resolve each item via TMDB (title, year, director, poster, backdrop).
    3. Download backdrops + posters to a per-post asset folder.
    4. Build hook + N item + closing slide specs.
    5. Render via ListCarouselRenderer (HTML + Playwright).
    6. Upload PNGs to imgbb.
    7. Optional Instagram publish (default: dry-run, prints imgbb URLs).
    8. Record in brain on real publish.

Usage:
    python3 scripts/ship_list_post.py --pack mind_bending_scifi --dry-run
    python3 scripts/ship_list_post.py --pack mind_bending_scifi          # live

The --dry-run path is the same as a real publish up to the IG call. That
means imgbb hosts the PNGs publicly so you can preview the layout in a
browser before authorising a live ship.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import requests

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.brain import brain
from src.content.description_builder import build_instagram_description
from src.content.list_packs import LIST_PACKS, get_pack, list_packs
from src.content.pack_resolver import resolve_pack, slug_post_id, list_dedupe_claim
from src.core.config import load_config
from src.core.models import CarouselPost
from src.core.paths import LIST_PACK_CACHE
from src.publish.image_host import make_image_host
from src.publish.instagram_publisher import InstagramGraphPublisher
from src.render.render_carousel import BrandKitRenderer
from src.render.list_renderer import ListCarouselRenderer, ListSlideSpec
from src.utils.logging_utils import configure_logging


HASHTAGS_FILM = [
    "factjot", "filmrecs", "moviestowatch", "scifi", "filmtwitter",
    "movienight", "cinephile", "indiefilm", "filmlovers", "filmlist",
    "underratedfilms", "filmcommunity", "movierecommendations",
    "filmsofinstagram", "watchlist",
]


def _slug_post_id(slug: str) -> str:
    return slug_post_id(slug)


def _list_dedupe_claim(slug: str) -> str:
    return list_dedupe_claim(slug)


def _load_pack_cache(slug: str) -> dict | None:
    """Return cached prep data for this slug if it exists and is still valid."""
    if not LIST_PACK_CACHE.exists():
        return None
    for line in LIST_PACK_CACHE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("slug") != slug:
            continue
        from datetime import timezone
        valid_until = row.get("valid_until", "")
        if valid_until:
            from datetime import datetime as dt
            try:
                if dt.fromisoformat(valid_until.replace("Z", "+00:00")) < dt.now(timezone.utc):
                    return None   # expired
            except ValueError:
                pass
        return row
    return None


def _resolve_pack(pack: dict, post_id: str) -> tuple[list[ListSlideSpec], list[dict], list[str]]:
    """Returns (slide_specs, recap_items, source_urls).

    Walks the pack's items, hits TMDB for each, downloads backdrop + poster,
    and assembles the slide specs. The first item's backdrop is reused on
    the hook slide (most visually striking is positioned first per pack rules).
    """
    tmdb = TMDBClient()
    omdb = OMDbClient()  # disabled if OMDB_API_KEY missing — that's fine
    from src.core.paths import LIST_ASSETS_CACHE
    asset_root = LIST_ASSETS_CACHE / post_id
    asset_root.mkdir(parents=True, exist_ok=True)

    item_specs: list[ListSlideSpec] = []
    recap_items: list[dict] = []
    sources: list[str] = []

    for idx, raw in enumerate(pack["items"], start=1):
        kind = raw.get("kind", "movie")
        if kind not in ("movie", "tv"):
            raise NotImplementedError(f"list item kind {kind!r} not supported yet")
        tmdb_id = int(raw["tmdb_id"])

        # ---- Fetch domain-specific TMDB data ----
        if kind == "movie":
            entity = tmdb.get_movie(tmdb_id)
            credits = tmdb.get_movie_credits(tmdb_id)
            title = entity.get("title") or entity.get("original_title") or "Untitled"
            year = (entity.get("release_date") or "")[:4] or ""
            credit_name = tmdb.director_name(credits) or ""
            director = f"dir. {credit_name}" if credit_name else ""
            imdb_id = entity.get("imdb_id") or ""
            # Runtime in minutes for movies
            duration_min = raw.get("runtime") or entity.get("runtime") or 0
            duration_str = f"{duration_min} MIN" if duration_min else ""
        else:  # tv
            entity = tmdb.get_tv_show(tmdb_id)
            credits = tmdb.get_tv_credits(tmdb_id)
            title = entity.get("name") or entity.get("original_name") or "Untitled"
            year = (entity.get("first_air_date") or "")[:4] or ""
            credit_name = tmdb.first_creator_name(entity, credits) or ""
            director = f"by {credit_name}" if credit_name else ""
            # External IDs request for IMDB tt-id (used by OMDb)
            try:
                ext = tmdb.get_tv_external_ids(tmdb_id)
                imdb_id = ext.get("imdb_id") or ""
            except Exception:
                imdb_id = ""
            # Duration: TV uses seasons + episodes instead of runtime
            seasons = entity.get("number_of_seasons") or 0
            episodes = entity.get("number_of_episodes") or 0
            if raw.get("runtime"):
                # Pack can override with whatever string makes sense
                duration_str = str(raw["runtime"]).upper()
            elif seasons and episodes:
                duration_str = f"{seasons} S · {episodes} EPS"
            elif episodes:
                duration_str = f"{episodes} EPS"
            else:
                duration_str = ""

        backdrop_url = TMDBClient.best_backdrop(entity)
        poster_url = TMDBClient.best_poster(entity)
        if not backdrop_url or not poster_url:
            raise RuntimeError(f"TMDB id {tmdb_id} ({title}) is missing backdrop or poster")

        bd_path = _download(backdrop_url, asset_root / f"{idx:02d}_backdrop.jpg")
        po_path = _download(poster_url, asset_root / f"{idx:02d}_poster.jpg")

        # Pack-level scores win. OMDb fallback fills the gap from imdb_id.
        imdb_score = raw.get("imdb_score", "") or ""
        rotten_score = raw.get("rotten_score", "") or ""
        if (not imdb_score or not rotten_score) and omdb.enabled and imdb_id:
            fetched = omdb.scores_by_imdb_id(imdb_id)
            imdb_score = imdb_score or fetched.get("imdb", "")
            rotten_score = rotten_score or fetched.get("rotten", "")

        # First listed genre, pack override beats API.
        genre = raw.get("genre", "") or ""
        if not genre and entity.get("genres"):
            genre = (entity["genres"][0].get("name") or "").upper()

        # Leading cast — top 2 from credits, ordered by `order`.
        leading_cast = list(raw.get("leading_cast") or [])
        if not leading_cast:
            cast = sorted(credits.get("cast", []) or [], key=lambda c: c.get("order", 999))
            leading_cast = [c["name"].upper() for c in cast[:2] if c.get("name")]

        watch_providers = list(raw["watch_providers"]) if raw.get("watch_providers") else []

        item_specs.append(ListSlideSpec(
            kind="item",
            title=title,
            year=year,
            director=director,
            hook=raw.get("hook", ""),
            accent_word=raw.get("accent_word", ""),
            backdrop_local_path=str(bd_path),
            poster_local_path=str(po_path),
            imdb_score=imdb_score,
            rotten_score=rotten_score,
            runtime=duration_str,
            genre=genre,
            leading_cast=leading_cast,
            watch_providers=watch_providers,
        ))
        recap_items.append({"title": title, "year": year})
        source_path = "movie" if kind == "movie" else "tv"
        sources.append(f"https://www.themoviedb.org/{source_path}/{tmdb_id}")

    # Hook: reuse item-1 backdrop.
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


def _print_preview(pack: dict, specs: list[ListSlideSpec]) -> None:
    print(f"\nPack: {pack['slug']}")
    print(f"  Title:    {pack['title']}")
    print(f"  Subtitle: {pack['subtitle']}")
    print(f"  Slides:   {len(specs)} (1 hook + {len(specs)-2} items + 1 closing)")
    for s in specs:
        if s.kind == "hook":
            print(f"  [hook]    {s.title} | {s.subtitle}")
        elif s.kind == "item":
            credit = s.director or ""
            print(f"  [item]    {s.title} ({s.year}) — {credit}")
            extras = " · ".join(filter(None, [s.runtime, s.genre]))
            if extras:
                print(f"            {extras}")
            if s.leading_cast:
                print(f"            Starring: {' · '.join(s.leading_cast)}")
            print(f"            {s.hook}")
        else:
            print(f"  [closing] {s.headline} | recap × {len(s.recap_items)}")


def _pick_next_unposted_pack() -> str | None:
    """Return the slug of the next unposted pack. Curated first, then TMDB auto-generated."""
    for slug in LIST_PACKS:
        if not brain.is_fact_posted(_list_dedupe_claim(slug)):
            return slug
    # All curated packs posted — generate a trending pack from TMDB
    print("All curated packs posted. Generating auto pack from TMDB trending...")
    try:
        from src.content.auto_pack import build_trending_pack, get_posted_tmdb_ids
        from src.research.trend_scout import fetch_weekly_trends
        trends = fetch_weekly_trends()
        movies = trends.get("movies", [])
        posted_ids = get_posted_tmdb_ids()
        pack = build_trending_pack(movies, posted_tmdb_ids=posted_ids)
        if pack:
            slug = pack["slug"]
            # Register it in a runtime dict so get_pack() can find it
            from src.content.list_packs import LIST_PACKS as _lp
            _lp[slug] = pack
            print(f"  Auto pack generated: {slug!r}")
            return slug
    except Exception as exc:
        print(f"  Auto pack generation failed: {exc}")
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ship a list-format carousel to Instagram.",
    )
    pack_group = parser.add_mutually_exclusive_group(required=True)
    pack_group.add_argument("--pack",
                            help=f"list pack slug. Known: {', '.join(list_packs())}")
    pack_group.add_argument("--next", action="store_true",
                            help="auto-pick the next unposted pack in order")
    parser.add_argument("--dry-run", action="store_true",
                        help="render + host on imgbb but skip the IG publish call")
    args = parser.parse_args()

    configure_logging()
    cfg = load_config()
    brand = json.loads(Path("brand/brand_kit.json").read_text())

    if args.next:
        chosen_slug = _pick_next_unposted_pack()
        if chosen_slug is None:
            print("WARNING: all list packs have been posted. Add new packs to list_packs.py.")
            return 1
        print(f"--next selected pack: {chosen_slug!r}")
        args.pack = chosen_slug

    pack = get_pack(args.pack)
    post_id = _slug_post_id(args.pack)

    # Rule 01 spirit: each list pack ships ONCE, ever. New packs, not re-runs.
    if brain.is_fact_posted(_list_dedupe_claim(args.pack)):
        print(f"List pack {args.pack!r} has already been shipped. Add a new pack rather than reposting.")
        return 2

    # Cache-first: if Sunday's prepare_packs.py already resolved and uploaded
    # this pack, skip TMDB + render + imgbb entirely and post directly.
    cached = _load_pack_cache(args.pack)
    if cached:
        print(f"Cache hit for {args.pack!r} — skipping TMDB, render, and imgbb.")
        public_urls = cached["imgbb_urls"]
        full_caption = cached["caption"]
        sources = cached.get("sources", [])
        post_id = cached.get("post_id", post_id)
        # Jump straight to publish
        from src.brain import DuplicatePostError
        try:
            brain.assert_no_duplicate([_list_dedupe_claim(args.pack)])
        except DuplicatePostError as e:
            print(f"\nABORTED — duplicate blocked:\n{e}")
            brain.append_log(f"list carousel BLOCKED — duplicate: {args.pack}")
            return 3
        if args.dry_run:
            print("\nDRY-RUN — cached URLs:")
            for u in public_urls:
                print(f"  {u}")
            return 0
        # Skip to publish block below
        _use_cache = True
    else:
        _use_cache = False
        print(f"Resolving pack via TMDB...")
        specs, recap, sources = resolve_pack(pack, post_id)
    if _use_cache:
        # Already have public_urls and full_caption from cache — skip to publish.
        pass
    else:
        _print_preview(pack, specs)

    if not _use_cache:
        print("\nRendering slides (Playwright + Chromium)...")
        renderer = ListCarouselRenderer(
        brand=brand,
        width=brand["layout"]["canvas_width"],
        height=brand["layout"]["canvas_height"],
    )
        paths = renderer.render(post_id=post_id, category=pack["category"],
                                series=pack["series"], slides=specs)
        if not paths:
            print("Render produced no PNGs.")
            return 5
        print(f"  {len(paths)} PNGs at {Path(paths[0]).parent}/")

        try:
            host = make_image_host()
        except RuntimeError as exc:
            print(f"Image host setup failed: {exc}")
            return 6

        def _host_label(h) -> str:
            return getattr(h, "active_name", type(h).__name__)

        def _upload_via(h):
            print(f"\nUploading via {_host_label(h)}...")
            hosted = h.upload_many(paths)
            urls = [x.public_url for x in hosted]
            for u in urls:
                print(f"  {u}")
            return urls

        public_urls = _upload_via(host)

        if args.dry_run:
            print("\nDRY-RUN — skipping Instagram publish call.")
            print("Open the URLs above to preview the layout.")
            return 0

        from src.brain import DuplicatePostError
        try:
            brain.assert_no_duplicate([_list_dedupe_claim(args.pack)])
        except DuplicatePostError as e:
            print(f"\nABORTED — duplicate blocked:\n{e}")
            brain.append_log(f"list carousel BLOCKED — duplicate: {args.pack}")
            return 3

        full_caption = build_instagram_description(
            base_caption=pack["caption"],
            hashtags=HASHTAGS_FILM,
            image_credits=[{"source": "TMDB", "url": s} for s in sources],
        )

    print("\nPublishing carousel to Instagram...")
    publisher = InstagramGraphPublisher(
        account_id=cfg.env["INSTAGRAM_ACCOUNT_ID"],
        access_token=cfg.env["META_ACCESS_TOKEN"],
        graph_version=cfg.env["META_GRAPH_VERSION"],
        host=cfg.env["META_GRAPH_HOST"],
    )

    def _looks_like_fetch_failure(err) -> bool:
        # Meta returns "Media could not be fetched from this URI" /
        # error code 9004 when the URL host is unreachable to its fetcher.
        # That's the case where rolling forward to the next backend helps.
        s = str(err or "").lower()
        return ("could not be fetched" in s
                or "doesn't meet our requirements" in s
                or "9004" in s)

    result = publisher.publish_carousel(image_urls=public_urls, caption=full_caption)
    while not result.get("ok") and _looks_like_fetch_failure(result.get("error")) and hasattr(host, "next_backend"):
        try:
            new_name = host.next_backend()
        except RuntimeError as exc:
            print(f"\nAll image-host backends exhausted. Last error: {exc}")
            break
        print(f"\nIG fetch failure on {_host_label(host)}'s previous host. "
              f"Re-hosting via {new_name} and retrying...")
        public_urls = _upload_via(host)
        result = publisher.publish_carousel(image_urls=public_urls, caption=full_caption)

    if not result.get("ok"):
        print(f"\nPublish failed: {result.get('error')}")
        return 7
    ig_media_id = result["ig_media_id"]
    print(f"PUBLISHED via {_host_label(host)} — ig_media_id: {ig_media_id}")

    # Growth path: push hook slide to Stories with a backlink to the carousel.
    story_result = {"ok": False, "error": "missing image url"}
    if public_urls:
        story_image_url = public_urls[0]
        try:
            story_renderer = BrandKitRenderer(
                brand=brand,
                width=brand["layout"]["canvas_width"],
                height=brand["layout"]["canvas_height"],
            )
            story_post = CarouselPost(
                post_id=post_id,
                series=pack["series"],
                hook="",
                slides=[pack["title"]],
                caption=pack["caption"],
                hashtags=HASHTAGS_FILM,
                sources=sources,
                confidence=0.9,
                category=pack["category"],
            )
            story_frame_path = story_renderer.render_stories_frame(
                story_post,
                bg_path=Path(paths[0]),
            )
            if story_frame_path:
                story_image_url = host.upload(story_frame_path).public_url
        except Exception as exc:
            print(f"Story frame render skipped (non-fatal): {exc}")
        permalink = publisher.ig_permalink(ig_media_id)
        story_result = publisher.post_to_stories(
            image_url=story_image_url,
            link_url=permalink,
        )
    if story_result.get("ok"):
        print(f"Story posted — ig_media_id: {story_result['ig_media_id']}")
        if story_result.get("warning"):
            print(f"Story note: {story_result['warning']}")
    else:
        print(f"Story skipped (non-fatal): {story_result.get('error')}")

    # Record in brain. Slides for posted.jsonl carry list metadata so the
    # autonomous queue / weekly planner can see this is a list, not a fact.
    slides_for_brain = [{
        "claim": _list_dedupe_claim(args.pack),
        "topic": "film",
        "category": pack["category"],
        "kind": "list",
        "list_pack": args.pack,
        "tmdb_ids": [it["tmdb_id"] for it in pack["items"]],
        "sources": sources,
    }]
    brain.record_publish(post_id=post_id, ig_media_id=ig_media_id, slides=slides_for_brain)
    brain.append_log(
        f"published {post_id} (LIST {pack['category']}, {len(public_urls)} slides, "
        f"pack={args.pack}, ig_media={ig_media_id})"
    )
    print("Recorded in insta-brain/data/posted.jsonl and log.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
