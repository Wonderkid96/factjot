"""Pre-resolve, render, and upload all unposted list carousel packs.

Runs every Sunday via weekly-plan.yml BEFORE the first post of the week.
At post time (17:00 UTC daily), ship_list_post.py reads from the cache
and skips TMDB, Playwright, and imgbb entirely — reducing post time from
~5 min to ~30 sec and eliminating all three as failure points.

Cache lives in: data/ledgers/list_pack_cache.jsonl (committed to git).
imgbb URLs are permanent and survive between runs.

Safe to re-run: skips packs already cached and still valid (< 7 days old).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.brain import brain
from src.content.list_packs import LIST_PACKS
from src.content.pack_resolver import resolve_pack, slug_post_id, list_dedupe_claim
from src.core.config import load_config
from src.core.paths import LIST_PACK_CACHE
from src.publish.image_host import make_image_host
from src.render.list_renderer import ListCarouselRenderer

CACHE_TTL_DAYS = 7   # re-prep after this many days even if not yet posted


def _load_cache() -> dict[str, dict]:
    """Return existing cache keyed by slug."""
    out: dict[str, dict] = {}
    if not LIST_PACK_CACHE.exists():
        return out
    for line in LIST_PACK_CACHE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        out[row["slug"]] = row
    return out


def _is_fresh(row: dict) -> bool:
    valid_until = row.get("valid_until", "")
    if not valid_until:
        return False
    try:
        return datetime.fromisoformat(
            valid_until.replace("Z", "+00:00")
        ) > datetime.now(timezone.utc)
    except ValueError:
        return False


def _write_cache(cache: dict[str, dict]) -> None:
    LIST_PACK_CACHE.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(row, ensure_ascii=True) for row in cache.values()]
    LIST_PACK_CACHE.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")


def prepare_pack(slug: str, pack: dict, cfg, brand: dict) -> dict | None:
    """Resolve, render, upload one pack. Returns cache row or None on failure."""
    post_id = slug_post_id(slug)
    print(f"\n[prepare] {slug} (post_id={post_id})")

    try:
        # Parallel TMDB fetch — faster than sequential on 10-film packs
        specs, recap, sources = resolve_pack(pack, post_id, parallel=True)
        print(f"  resolved {len(specs)} slides")
    except Exception as exc:
        print(f"  TMDB resolution failed: {exc}")
        return None

    renderer = ListCarouselRenderer(
        brand=brand,
        width=brand["layout"]["canvas_width"],
        height=brand["layout"]["canvas_height"],
    )
    paths = renderer.render(
        post_id=post_id,
        category=pack["category"],
        series=pack["series"],
        slides=specs,
    )
    if not paths:
        print("  render produced no PNGs")
        return None
    print(f"  rendered {len(paths)} PNGs")

    try:
        host = make_image_host()
        hosted = host.upload_many(paths)
        imgbb_urls = [x.public_url for x in hosted]
    except Exception as exc:
        print(f"  imgbb upload failed: {exc}")
        return None
    print(f"  uploaded {len(imgbb_urls)} images to imgbb")

    _HASHTAGS_FILM = [
        "factjot", "filmrecs", "moviestowatch", "scifi", "filmtwitter",
        "movienight", "cinephile", "indiefilm", "filmlovers", "filmlist",
        "underratedfilms", "filmcommunity", "movierecommendations",
        "filmsofinstagram", "watchlist",
    ]
    titles = [item["title"] for item in recap if item.get("title")]
    credits_line = "Credits:\n" + "\n".join(f"• {t}" for t in titles) if titles else ""
    hashtag_block = " ".join(_HASHTAGS_FILM)
    caption = "\n\n".join(p for p in [
        pack["caption"].strip(), credits_line, hashtag_block
    ] if p).strip()

    now = datetime.now(timezone.utc)
    return {
        "slug": slug,
        "prepared_at": now.isoformat().replace("+00:00", "Z"),
        "valid_until": (now + timedelta(days=CACHE_TTL_DAYS)).isoformat().replace("+00:00", "Z"),
        "post_id": post_id,
        "imgbb_urls": imgbb_urls,
        "caption": caption,
        "sources": sources,
    }


def main() -> int:
    cfg = load_config()
    brand = json.loads(Path("brand/brand_kit.json").read_text())
    cache = _load_cache()

    prepared = 0
    skipped_posted = 0
    skipped_fresh = 0
    failed = 0

    for slug, pack in LIST_PACKS.items():
        claim = list_dedupe_claim(slug)

        if brain.is_fact_posted(claim):
            skipped_posted += 1
            continue

        existing = cache.get(slug)
        if existing and _is_fresh(existing):
            print(f"[prepare] {slug} — cache fresh, skipping")
            skipped_fresh += 1
            continue

        row = prepare_pack(slug, pack, cfg, brand)
        if row:
            cache[slug] = row
            prepared += 1
        else:
            failed += 1

    _write_cache(cache)

    print(f"\nPack preparation complete:")
    print(f"  prepared  {prepared}")
    print(f"  fresh     {skipped_fresh} (already cached)")
    print(f"  posted    {skipped_posted} (already published)")
    print(f"  failed    {failed}")
    print(f"  cache:    {LIST_PACK_CACHE}")

    return 1 if failed and prepared == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
