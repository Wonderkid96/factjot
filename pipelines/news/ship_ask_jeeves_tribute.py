"""One-off tribute carousel: Goodbye, Jeeves (Ask.com shutdown May 2026).

Usage:
    python pipelines/news/ship_ask_jeeves_tribute.py --dry-run
    python pipelines/news/ship_ask_jeeves_tribute.py
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

import os
import re
import requests
import base64
from playwright.sync_api import sync_playwright

from pipelines.news.ship_news_post import (
    render_cover_slide,
    render_news_slide,
    _log,
)
from src.content.hashtag_builder import build_hashtags
from src.publish.image_host import make_image_host
from src.publish.instagram_publisher import InstagramGraphPublisher

# ------------------------------------------------------------------ #
# Slide content -- fully factual, sourced from Ask.com shutdown news
# ------------------------------------------------------------------ #

COVER_TITLE   = "Goodbye, Jeeves."
SOURCE_LABEL  = "INTERNET HISTORY"

SLIDES = [
    {
        "lines": [
            "In [r]1996[/r], a search engine launched",
            "where you could ask in plain English.",
            "No keywords, no syntax.",
            "Just a [r]butler[/r] waiting for your question.",
        ]
    },
    {
        "lines": [
            "His name was [r]Jeeves[/r],",
            "borrowed from P.G. Wodehouse fiction.",
            "He promised to fetch any answer",
            "with the grace of a [r]gentleman's servant.[/r]",
        ]
    },
    {
        "lines": [
            "By the early [r]2000s,[/r] Ask Jeeves",
            "drew over [r]8 million users[/r] a day.",
            "A top-ten US website, built",
            "before Google was even a verb.",
        ]
    },
    {
        "lines": [
            "In [r]2005[/r], IAC paid [r]$1.85 billion[/r]",
            "believing natural language search",
            "was the inevitable future of the web.",
            "It was. Just not Jeeves doing it.",
        ]
    },
    {
        "lines": [
            "In [r]2006[/r], the butler was quietly retired.",
            "The site became simply [r]Ask.com.[/r]",
            "A name. Nothing more.",
            "The soul walked out with the three-piece suit.",
        ]
    },
    {
        "lines": [
            "On [r]1 May 2026,[/r] Ask.com shut down.",
            "After 30 years, the search was over.",
            "Queries now redirect to [r]Google.[/r]",
            "The butler finally stepped aside.",
        ]
    },
    {
        "lines": [
            "Ask Jeeves tried to do [r]what AI does now.[/r]",
            "It just arrived [r]30 years too early.[/r]",
            "Was it ahead of its time,",
            "or simply the wrong kind of smart?",
        ]
    },
]

CAPTION_BODY = """\
Ask.com shut down on 1 May 2026, closing the book on one of the internet's most beloved pioneers. Ask Jeeves launched in 1996 with a radical idea: what if you could ask a search engine a question, in plain English, like you would a friend?

It didn't survive the Google era. But for a generation of early internet users, Jeeves was the internet.

Rest easy, old friend."""

# Pexels queries per slide (cover first, then one per content slide).
# Each query is deliberately distinct to avoid duplicate photos.
PEXELS_QUERIES = [
    "english butler formal vintage portrait",
    "vintage desktop computer 1990s retro monitor",
    "old library research books study reading",
    "nineties office computer keyboard work",
    "business deal handshake corporate 2000s",
    "internet web browser laptop screen coffee",
    "google search engine results typing",
    "artificial intelligence robot future digital",
]


def _fetch_unique_pexels_images(queries: list[str], pexels_key: str) -> list[str]:
    """Fetch one unique image per query slot, deduplicating by photo ID."""
    used_ids: set[int] = set()
    data_urls: list[str] = []

    for query in queries:
        chosen: str = ""
        try:
            resp = requests.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": pexels_key},
                params={"query": query, "per_page": 6, "orientation": "portrait"},
                timeout=15,
            )
            resp.raise_for_status()
            for photo in resp.json().get("photos", []):
                pid = photo.get("id")
                if pid in used_ids:
                    continue
                img_url = (
                    photo.get("src", {}).get("large2x")
                    or photo.get("src", {}).get("large")
                    or photo.get("src", {}).get("medium")
                )
                if not img_url:
                    continue
                r = requests.get(img_url, timeout=15)
                r.raise_for_status()
                mime = "image/jpeg"
                chosen = f"data:{mime};base64,{base64.b64encode(r.content).decode()}"
                used_ids.add(pid)
                break
        except Exception as exc:
            _log(f"     Pexels error for '{query}': {exc}")
        data_urls.append(chosen)
        _log(f"     '{query[:40]}': {'OK' if chosen else 'MISS'}")

    return data_urls


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    repo_root  = Path(__file__).resolve().parents[2]
    pexels_key = os.getenv("PEXELS_API_KEY", "").strip()

    if not pexels_key:
        _log("ERROR: PEXELS_API_KEY not set")
        return 1

    total_slides = len(SLIDES) + 1  # +1 for cover

    # Fetch unique images (one per slot, no repeats)
    _log("\n[1/3] Fetching images from Pexels (dedup enabled)...")
    images = _fetch_unique_pexels_images(PEXELS_QUERIES[:total_slides], pexels_key)

    cover_photo   = images[0] if images else ""
    content_imgs  = images[1:] if len(images) > 1 else images

    _log(f"\n[2/3] Rendering {total_slides} slides...")
    slide_paths: list[Path] = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()

            cover_path = tmp_dir / "slide_01.png"
            render_cover_slide(
                cover_title=COVER_TITLE,
                source_label=SOURCE_LABEL,
                photo_data_url=cover_photo,
                out_path=cover_path,
                index=1,
                total=total_slides,
                repo_root=repo_root,
                browser=browser,
            )
            slide_paths.append(cover_path)
            _log("     cover done")

            for idx, slide in enumerate(SLIDES, start=2):
                img_idx = (idx - 2) % max(len(content_imgs), 1)
                out_path = tmp_dir / f"slide_{idx:02d}.png"
                render_news_slide(
                    lines=slide["lines"],
                    photo_data_url=content_imgs[img_idx] if content_imgs else "",
                    out_path=out_path,
                    index=idx,
                    total=total_slides,
                    source_label=SOURCE_LABEL,
                    repo_root=repo_root,
                    browser=browser,
                )
                slide_paths.append(out_path)
                _log(f"     slide {idx} done")

            browser.close()

        _log(f"\n[3/3] {'DRY RUN -- saving locally' if args.dry_run else 'Hosting and publishing'}...")

        hashtags = build_hashtags(
            summary="Ask Jeeves Ask.com shutdown 1996 internet history search engine butler nostalgia Google",
            topic="internet",
            post_type="news",
        )
        caption = f"{CAPTION_BODY}\n\n{hashtags}"

        from datetime import datetime as _dt
        ts       = _dt.now().strftime("%Y-%m-%d_%H-%M")
        save_dir = repo_root / "output" / "news" / f"{ts}_ask-jeeves-tribute"
        save_dir.mkdir(parents=True, exist_ok=True)
        for p in slide_paths:
            shutil.copy(p, save_dir / p.name)
        _log(f"     Slides saved to: {save_dir.resolve()}")

        if args.dry_run:
            _log("\n[DRY RUN] Caption preview:")
            _log(caption[:400] + "...")
            return 0

        image_host = make_image_host()
        image_urls: list[str] = []
        for path in slide_paths:
            hosted = image_host.upload(path)
            image_urls.append(hosted.public_url)
            _log(f"     uploaded: {hosted.public_url[:60]}...")

        publisher = InstagramGraphPublisher(
            account_id=os.getenv("INSTAGRAM_ACCOUNT_ID", ""),
            access_token=os.getenv("META_ACCESS_TOKEN", ""),
            host=os.getenv("META_GRAPH_HOST", "graph.instagram.com"),
            graph_version=os.getenv("META_GRAPH_VERSION", "v21.0"),
        )
        result = publisher.publish_carousel(image_urls, caption)
        ig_media_id = result.get("id") or result.get("ig_media_id", "")
        _log(f"\nPosted! Media ID: {ig_media_id}")

        # Story: cover slide + link to carousel
        story_result = {"ok": False, "error": "no media id"}
        if ig_media_id and image_urls:
            permalink = publisher.ig_permalink(ig_media_id)
            story_result = publisher.post_to_stories(
                image_url=image_urls[0],
                link_url=permalink,
            )
        if story_result.get("ok"):
            _log(f"Story posted — ig_media_id: {story_result['ig_media_id']}")
        else:
            _log(f"Story skipped (non-fatal): {story_result.get('error')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
