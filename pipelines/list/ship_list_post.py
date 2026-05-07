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

Usage (local Mac):
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3 pipelines/list/ship_list_post.py --pack mind_bending_scifi --dry-run
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3 pipelines/list/ship_list_post.py --pack mind_bending_scifi

The --dry-run path is the same as a real publish up to the IG call. That
means imgbb hosts the PNGs publicly so you can preview the layout in a
browser before authorising a live ship.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.brain import brain
from src.content.description_builder import build_instagram_description
from src.content.hashtag_builder import build_hashtags
from src.content.list_packs import LIST_PACKS, get_pack, list_packs
from src.content.pack_resolver import resolve_pack, slug_post_id, list_dedupe_claim
from src.core.paths import GENERATED_LIST_PACKS, LIST_POSTS
from src.core.config import load_config
from src.core.models import CarouselPost
from src.core.paths import LIST_PACK_CACHE
from src.publish.image_host import make_image_host
from src.publish.instagram_publisher import InstagramGraphPublisher
from src.render.list_renderer import ListCarouselRenderer, ListSlideSpec
from src.render.render_carousel import BrandKitRenderer
from src.utils.logging_utils import configure_logging



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


def _load_generated_packs_into_runtime() -> None:
    """Load generated_list_packs.jsonl into the runtime LIST_PACKS dict."""
    if not GENERATED_LIST_PACKS.exists():
        return
    import json as _json
    for line in GENERATED_LIST_PACKS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            pack = _json.loads(line)
            slug = pack.get("slug")
            if slug and slug not in LIST_PACKS:
                LIST_PACKS[slug] = pack
        except Exception:
            pass


# Load generated packs at import time so get_pack() finds them.
_load_generated_packs_into_runtime()


def _is_list_posted(slug: str) -> bool:
    """Hard check against list_posts.jsonl — survives resets of posted.jsonl."""
    if not LIST_POSTS.exists():
        return False
    target = list_dedupe_claim(slug)
    for line in LIST_POSTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            if json.loads(line).get("claim") == target:
                return True
        except json.JSONDecodeError:
            pass
    return False


def _recent_posted_categories(n: int = 3) -> list[str]:
    """Return categories of the last N real list posts (skips sentinel entries)."""
    if not LIST_POSTS.exists():
        return []
    rows = []
    for line in LIST_POSTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            if row.get("ig_media_id") != "skip":
                rows.append(row)
        except json.JSONDecodeError:
            pass
    return [r.get("category", "") for r in rows[-n:]]


def _record_list_post(slug: str, post_id: str, ig_media_id: str,
                      category: str, sources: list) -> None:
    """Append to list_posts.jsonl — permanent, never wiped by reset."""
    from src.brain import claim_hash as _claim_hash
    from datetime import timezone
    claim = list_dedupe_claim(slug)
    row = {
        "claim_hash": _claim_hash(claim),
        "claim": claim,
        "topic": "film",
        "category": category,
        "post_id": post_id,
        "ig_media_id": ig_media_id,
        "published_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sources": sources,
    }
    LIST_POSTS.parent.mkdir(parents=True, exist_ok=True)
    with LIST_POSTS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=True) + "\n")


def _pick_next_unposted_pack() -> str | None:
    """Return the slug of the next unposted pack.

    Priority: curated packs → generated themed packs → TMDB trending fallback.
    Checks list_posts.jsonl (permanent) AND posted.jsonl (resets periodically).

    Category cooldown: prefers packs whose category has not appeared in the
    last 3 posts. If all remaining packs share a recent category, falls back
    to any available pack — this keeps variety without hard-blocking topics.
    """
    recent_cats = _recent_posted_categories(3)

    def _is_available(slug: str) -> bool:
        return not _is_list_posted(slug) and not brain.is_fact_posted(list_dedupe_claim(slug))

    # First pass: packs whose category is not in the recent 3
    for slug in LIST_PACKS:
        if _is_available(slug):
            pack_cat = LIST_PACKS[slug].get("category", "")
            if pack_cat not in recent_cats:
                return slug

    # Second pass: any available pack (all remaining are recent-category repeats)
    for slug in LIST_PACKS:
        if _is_available(slug):
            return slug
    # All known packs posted — generate a trending pack from TMDB as last resort
    print("All packs posted. Generating auto pack from TMDB trending...")
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
    post_id = slug_post_id(args.pack)

    # Per-day list cap removed: the autonomous agent is now the single
    # poster and runs its own duplicate guard via the post bank summary.
    # The pack-uniqueness check below still applies (a list pack ships
    # only once, ever).

    # Rule 01 spirit: each list pack ships ONCE, ever. New packs, not re-runs.
    # Check list_posts.jsonl first — it survives resets of posted.jsonl.
    if _is_list_posted(args.pack):
        print(f"List pack {args.pack!r} has already been shipped (list_posts.jsonl). Add a new pack rather than reposting.")
        return 2
    if brain.is_fact_posted(list_dedupe_claim(args.pack)):
        print(f"List pack {args.pack!r} has already been shipped (posted.jsonl). Add a new pack rather than reposting.")
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
            brain.assert_no_duplicate([list_dedupe_claim(args.pack)])
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
            brain.assert_no_duplicate([list_dedupe_claim(args.pack)])
        except DuplicatePostError as e:
            print(f"\nABORTED — duplicate blocked:\n{e}")
            brain.append_log(f"list carousel BLOCKED — duplicate: {args.pack}")
            return 3

        titles = [item["title"] for item in recap if item.get("title")]
        credits_line = "Credits:\n" + "\n".join(f"• {t}" for t in titles) if titles else ""
        hashtag_block = build_hashtags(
            summary=pack.get("caption", pack.get("title", "")),
            topic=pack.get("category", "film").lower(),
            post_type="film",
        )
        full_caption = "\n\n".join(p for p in [
            pack["caption"].strip(), credits_line, hashtag_block
        ] if p).strip()

    print("\nPublishing carousel to Instagram...")
    publisher = InstagramGraphPublisher(
        account_id=cfg.env["INSTAGRAM_ACCOUNT_ID"],
        access_token=cfg.env["META_ACCESS_TOKEN"],
        graph_version=cfg.env["META_GRAPH_VERSION"],
        host=cfg.env["META_GRAPH_HOST"],
    )

    def _looks_like_fetch_failure(err) -> bool:
        s = str(err or "").lower()
        return ("could not be fetched" in s
                or "doesn't meet our requirements" in s
                or "9004" in s)

    result = publisher.publish_carousel(image_urls=public_urls, caption=full_caption)

    # Retry with next image-host backend only when we have a live host object
    # (non-cache path). On cache path host is not defined so we skip retries.
    if not _use_cache:
        while not result.get("ok") and _looks_like_fetch_failure(result.get("error")) and hasattr(host, "next_backend"):
            try:
                new_name = host.next_backend()
            except RuntimeError as exc:
                print(f"\nAll image-host backends exhausted. Last error: {exc}")
                break
            print(f"\nIG fetch failure — re-hosting via {new_name} and retrying...")
            public_urls = _upload_via(host)
            result = publisher.publish_carousel(image_urls=public_urls, caption=full_caption)

    if not result.get("ok"):
        print(f"\nPublish failed: {result.get('error')}")
        return 7
    ig_media_id = result["ig_media_id"]
    src = "cache" if _use_cache else "live"
    print(f"PUBLISHED ({src}) — ig_media_id: {ig_media_id}")

    # Growth path: push hook slide to Stories with a backlink to the carousel.
    story_result = {"ok": False, "error": "missing image url"}
    if public_urls:
        story_image_url = public_urls[0]
        # Custom story frame requires rendered paths and a live host object.
        # On the cache path neither is available, so we skip frame rendering
        # and fall back to story_image_url = public_urls[0] set above.
        if not _use_cache:
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
                    hashtags=hashtag_block.split(),
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
        "claim": list_dedupe_claim(args.pack),
        "topic": "film",
        "category": pack["category"],
        "kind": "list",
        "list_pack": args.pack,
        "tmdb_ids": [it["tmdb_id"] for it in pack["items"]],
        "sources": sources,
    }]
    brain.record_publish(post_id=post_id, ig_media_id=ig_media_id, slides=slides_for_brain)
    # Permanent record — survives any future reset of posted.jsonl.
    _record_list_post(args.pack, post_id, ig_media_id, pack["category"], sources)
    brain.append_log(
        f"published {post_id} (LIST {pack['category']}, {len(public_urls)} slides, "
        f"pack={args.pack}, ig_media={ig_media_id})"
    )
    print("Recorded in insta-brain/data/posted.jsonl, list_posts.jsonl, and log.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
