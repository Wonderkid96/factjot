#!/usr/bin/env python3
"""Ship a curated film/TV list carousel.

Revived 2026-05-11 as part of Phase N - rebuilds the curated list
post path the user remembered fondly. Replaces the agent's inline
list generation for the daily list_midday slot.

Source of truth for content: src/content/list_packs.py (8 curated
packs as of 2026-05-11). Source of truth for film metadata: TMDB,
with OMDb confidence-gated fallback. Poster + backdrop assets are
downloaded to data/cache/list_assets/<post_id>/ at render time.

Rotation: tracks used packs in data/ledgers/used_list_themes.jsonl
and prefers unused ones. When all packs have been used, the oldest
is recycled.

CLI:
    python3 -m pipelines.list.ship_curated_list                  # auto-pick
    python3 -m pipelines.list.ship_curated_list --pack <slug>    # force
    python3 -m pipelines.list.ship_curated_list --dry-run        # local only
    python3 -m pipelines.list.ship_curated_list --list           # show packs
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.brain import brain, DuplicatePostError                       # noqa: E402
from src.content.list_packs import LIST_PACKS                         # noqa: E402
from src.content.pack_resolver import (                               # noqa: E402
    resolve_pack, slug_post_id, list_dedupe_claim,
)
from src.content.hashtag_builder import build_hashtags                # noqa: E402
from src.content.voice_normaliser import normalise as normalise_voice  # noqa: E402
from src.core.paths import (                                          # noqa: E402
    LIST_RENDERS, USED_LIST_THEMES,
)
from src.publish.image_host import make_image_host                    # noqa: E402
from src.publish.instagram_publisher import InstagramGraphPublisher   # noqa: E402
from src.render.list_renderer import ListCarouselRenderer             # noqa: E402


def _log(msg: str) -> None:
    print(msg, flush=True)


# ------------------------------------------------------------------ #
# Rotation
# ------------------------------------------------------------------ #

def _load_used_slugs() -> dict[str, str]:
    """Return {slug: iso_timestamp_of_last_use}.

    Reads from two sources, merging by latest timestamp:
    1. data/ledgers/used_list_themes.jsonl - written by this script.
    2. insta-brain/data/posted.jsonl - historical truth. Pre-Phase-N
       posts (May 1-6) only landed in posted.jsonl because the old
       prepare_packs.py wrote to a different ledger. Without merging,
       rotation would pick already-shipped packs, get blocked by the
       brain dedup, and spin.
    """
    used: dict[str, str] = {}

    # Source 1: the per-script ledger.
    if USED_LIST_THEMES.exists():
        for line in USED_LIST_THEMES.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                slug = row.get("slug")
                ts = row.get("posted_at") or row.get("used_at") or ""
                if slug and (slug not in used or ts > used[slug]):
                    used[slug] = ts
            except json.JSONDecodeError:
                continue

    # Source 2: the brain's authoritative posted ledger. Pulls slugs
    # out of "list:<slug>" claims for any historical pack we ever
    # shipped. Strict prefix match.
    from src.core.paths import POSTED
    if POSTED.exists():
        for line in POSTED.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                claim = row.get("claim", "")
                if not isinstance(claim, str) or not claim.startswith("list:"):
                    continue
                slug = claim[len("list:"):].strip()
                ts = row.get("published_at") or ""
                if slug and (slug not in used or ts > used[slug]):
                    used[slug] = ts
            except json.JSONDecodeError:
                continue
    return used


def _record_used(slug: str) -> None:
    """Append a row to the used-themes ledger. Append-only invariant
    (per SPEC §11.2)."""
    USED_LIST_THEMES.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "slug": slug,
        "posted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    with USED_LIST_THEMES.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def _pick_pack(force_slug: str | None = None) -> tuple[str, dict]:
    """Return (slug, pack) for the next pack to ship.

    Order of preference:
    1. The explicitly forced slug if provided and valid.
    2. The least-recently-used pack from LIST_PACKS that has never shipped.
    3. The least-recently-used pack overall (recycle when all have shipped).
    """
    if force_slug:
        if force_slug not in LIST_PACKS:
            raise SystemExit(
                f"unknown pack slug {force_slug!r}; "
                f"known: {sorted(LIST_PACKS.keys())}"
            )
        return force_slug, LIST_PACKS[force_slug]

    used = _load_used_slugs()
    candidates = list(LIST_PACKS.keys())
    # Never-used first, then oldest-used.
    candidates.sort(key=lambda slug: used.get(slug, ""))
    chosen = candidates[0]
    return chosen, LIST_PACKS[chosen]


# ------------------------------------------------------------------ #
# Render + publish
# ------------------------------------------------------------------ #

def _load_brand() -> dict:
    brand_path = ROOT / "brand" / "brand_kit.json"
    with brand_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _build_caption(pack: dict, sources: list[str]) -> str:
    """Pack caption + factjot CTA + Haiku-generated hashtags."""
    body = (pack.get("caption") or "").strip()
    cta = "Follow @factjot for more lists like this."
    src_block = ""
    if sources:
        # Source list shows just two TMDB links to keep the caption short.
        seen: list[str] = []
        for url in sources:
            if url and url not in seen:
                seen.append(url)
            if len(seen) >= 2:
                break
        if seen:
            src_block = "Sources: " + " | ".join(seen)
    hashtags = build_hashtags(
        summary=f"{pack.get('title','')} {body}".strip(),
        topic=pack.get("topic", "film"),
        post_type="list",
    )
    parts = [body, "", cta]
    if src_block:
        parts.extend(["", src_block])
    parts.extend(["", hashtags])
    raw = "\n".join(p for p in parts if p is not None)
    return normalise_voice(raw)


def ship(pack_slug: str, pack: dict, *, dry_run: bool) -> int:
    post_id = slug_post_id(pack_slug)
    dedupe_claim = list_dedupe_claim(pack_slug)

    _log(f"\n=== ship_curated_list: pack={pack_slug!r} post_id={post_id} ===")
    _log(f"     title:    {pack.get('title')!r}")
    _log(f"     category: {pack.get('category')!r}")
    _log(f"     items:    {len(pack.get('items', []))}")

    # Pre-publish dedup. brain.assert_no_duplicate reads posted.jsonl from
    # disk; defence-in-depth at the publisher boundary fires in addition.
    try:
        brain.assert_no_duplicate([dedupe_claim])
    except DuplicatePostError:
        _log(f"\nABORTED: pack {pack_slug!r} already posted (claim={dedupe_claim}).")
        return 1

    _log("\nResolving TMDB metadata + downloading posters...")
    slides, recap_items, sources = resolve_pack(pack, post_id, parallel=True)
    _log(f"     resolved {len(slides)} slides ({len(recap_items)} items)")

    _log("\nRendering carousel slides...")
    brand = _load_brand()
    out_dir = LIST_RENDERS / f"{datetime.now().strftime('%Y-%m-%d_%H-%M')}_{pack_slug}"
    renderer = ListCarouselRenderer(
        brand=brand, output_dir=str(out_dir),
    )
    slide_paths = renderer.render(
        post_id=post_id,
        category=pack.get("category", "FILM LIST"),
        series=pack.get("series", "factjot"),
        slides=slides,
    )
    if not slide_paths:
        _log("\nERROR: renderer returned no slides")
        return 9
    _log(f"     rendered {len(slide_paths)} slides to {slide_paths[0].rsplit('/', 1)[0]}")

    caption = _build_caption(pack, sources)
    _log(f"\nCaption ({len(caption)} chars):")
    _log("---\n" + caption + "\n---")

    if dry_run:
        _log("\nDRY-RUN - skipping upload + publish")
        for p in slide_paths:
            _log(f"  open {p}")
        return 0

    _log("\nUploading slides to imgbb...")
    host = make_image_host()
    image_urls: list[str] = []
    for i, path in enumerate(slide_paths, 1):
        hosted = host.upload(Path(path))
        image_urls.append(hosted.public_url)
        _log(f"     slide {i:02d}: {hosted.public_url[:70]}...")

    _log("\nPublishing carousel to Instagram...")
    publisher = InstagramGraphPublisher(
        account_id=os.getenv("INSTAGRAM_ACCOUNT_ID", ""),
        access_token=os.getenv("META_ACCESS_TOKEN", ""),
        host=os.getenv("META_GRAPH_HOST", "graph.instagram.com"),
        graph_version=os.getenv("META_GRAPH_VERSION", "v21.0"),
        dedup_check=brain.assert_no_duplicate,
    )
    result = publisher.publish_carousel(
        image_urls, caption,
        dedup_subjects=[dedupe_claim],
    )
    if not result.get("ok"):
        _log(f"\nERROR: publish failed: {result.get('error')}")
        return 7
    ig_media_id = result.get("ig_media_id", "")
    _log(f"\nPosted! Media ID: {ig_media_id}")

    # Record to brain (shared dedup pool) + used-themes ledger.
    brain.record_publish(
        post_id=post_id,
        ig_media_id=ig_media_id,
        slides=[{
            "claim":    dedupe_claim,
            "topic":    pack.get("topic", "film"),
            "category": pack.get("category", "FILM LIST"),
            "sources":  sources,
        }],
    )
    _record_used(pack_slug)
    brain.append_log(
        f"curated list {pack_slug!r} published ({pack.get('category')}, "
        f"ig_media={ig_media_id})"
    )

    return 0


# ------------------------------------------------------------------ #
# CLI
# ------------------------------------------------------------------ #

def main() -> int:
    parser = argparse.ArgumentParser(description="Ship a curated film/TV list carousel")
    parser.add_argument("--pack", default=None,
                        help="Pack slug (omit for auto-rotation)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Render locally, skip upload + publish")
    parser.add_argument("--list", action="store_true",
                        help="List available packs and exit")
    args = parser.parse_args()

    if args.list:
        used = _load_used_slugs()
        for slug, pack in LIST_PACKS.items():
            last = used.get(slug, "never")
            n = len(pack.get("items", []))
            cat = pack.get("category", "?")
            _log(f"  {slug:35s} [{cat:15s}] {n} items  last_used={last}")
        return 0

    slug, pack = _pick_pack(force_slug=args.pack)
    _log(f"Picked pack: {slug}")
    return ship(slug, pack, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
