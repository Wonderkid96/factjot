"""Force-publish a single queued post to Instagram, end to end.

    python3 scripts/publish_now.py --post-id <id>
    python3 scripts/publish_now.py --post-id <id> --dry-run

What it does:
    1. Read the queue, find the matching post.
    2. Re-check rules 01 (no repost) and 11 (every slide has a real image).
    3. Upload all slide PNGs to imgbb to get public URLs.
    4. Build the carousel via Instagram Graph API (child containers → carousel
       container → publish).
    5. Append a row to insta-brain/data/posted.jsonl per slide claim.
    6. Mark the queue row as published.
    7. Append a one-liner to insta-brain/log.md.

Anything that fails appends a row to data/publish_failures.jsonl with the full
Meta error body and aborts.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.brain import brain, claim_hash
from src.content.description_builder import build_instagram_description
from src.core.config import load_config
from src.core.models import CarouselPost
from src.publish.image_host import ImgbbHost
from src.publish.instagram_publisher import InstagramGraphPublisher
from src.render.render_carousel import BrandKitRenderer
from src.review.approval_queue import ApprovalQueue
from src.utils.logging_utils import configure_logging

from src.core.paths import PUBLISH_FAILURES


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _record_failure(post_id: str, stage: str, error: str | dict) -> None:
    PUBLISH_FAILURES.parent.mkdir(parents=True, exist_ok=True)
    row = {"post_id": post_id, "stage": stage, "error": error, "ts": _now_iso()}
    with PUBLISH_FAILURES.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish a queued post to Instagram now.")
    parser.add_argument("--post-id", required=True, help="post_id from approval_queue.jsonl")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate + host images but skip the actual IG publish call.")
    args = parser.parse_args()

    configure_logging()

    # Rule 13: refuse to publish if brain is stale.
    import subprocess
    rc = subprocess.call([
        sys.executable,
        str(Path(__file__).parent / "check_brain_fresh.py"),
    ])
    if rc != 0:
        print("ABORT — brain is stale (rule 13). Update insta-brain/MEMORY_INDEX.md and log.md, then re-run.")
        return 11

    cfg = load_config()
    queue = ApprovalQueue(cfg.review["queue_path"])
    rows = queue.list_all()
    post = next((r for r in rows if r.get("post_id") == args.post_id), None)
    if post is None:
        print(f"No post {args.post_id} in queue.")
        return 2

    # ----- Rule 01: never repost a fact -----
    for slide_text in post.get("slides", []):
        # Strip our markup before hashing.
        plain = slide_text.replace("[i]", "").replace("[/i]", "").replace("[h]", "").replace("[/h]", "")
        if brain.is_fact_posted(plain):
            print(f"Refusing to publish: slide claim already in posted.jsonl: {plain[:80]}")
            return 3

    # ----- Rule 11: every slide must have a real image -----
    render_paths = [Path(p) for p in post.get("render_paths", [])]
    if not render_paths:
        print(f"No render_paths on post {args.post_id}. Re-run rendering.")
        return 4
    for p in render_paths:
        if not p.exists():
            print(f"Missing PNG: {p}")
            return 5

    # ----- Step 1: host images -----
    print(f"Uploading {len(render_paths)} PNGs to imgbb...")
    try:
        host = ImgbbHost()
    except RuntimeError as exc:
        print(f"Image host setup failed: {exc}")
        return 6
    try:
        hosted = host.upload_many([str(p) for p in render_paths])
    except Exception as exc:
        _record_failure(args.post_id, "imgbb_upload", str(exc))
        print(f"imgbb upload failed: {exc}")
        return 7
    public_urls = [h.public_url for h in hosted]
    print(f"  hosted at:")
    for u in public_urls:
        print(f"    {u}")

    if args.dry_run:
        print("DRY-RUN: skipping Instagram publish call.")
        return 0

    # ----- Step 2: Instagram Graph API publish -----
    publisher = InstagramGraphPublisher(
        account_id=cfg.env["INSTAGRAM_ACCOUNT_ID"],
        access_token=cfg.env["META_ACCESS_TOKEN"],
        graph_version=cfg.env["META_GRAPH_VERSION"],
        host=cfg.env["META_GRAPH_HOST"],
    )
    if not publisher.is_configured():
        print("Meta credentials missing. Set INSTAGRAM_ACCOUNT_ID and META_ACCESS_TOKEN in .env.")
        return 8

    full_caption = build_instagram_description(
        base_caption=post.get("caption", ""),
        hashtags=post.get("hashtags", []),
        image_credits=post.get("image_credits", []),
    )

    print("Publishing carousel to Instagram...")
    result = publisher.publish_carousel(image_urls=public_urls, caption=full_caption)
    if not result.get("ok"):
        _record_failure(args.post_id, "graph_api_publish", result.get("error", "unknown"))
        print(f"Publish failed: {result.get('error')}")
        return 9
    ig_media_id = result["ig_media_id"]
    print(f"  ig_media_id: {ig_media_id}")

    # Growth path: post slide 1 to Stories and link back to the new post.
    story_result = {"ok": False, "error": "missing image url"}
    if public_urls:
        story_image_url = public_urls[0]
        try:
            brand = json.loads(Path("brand/brand_kit.json").read_text())
            renderer = BrandKitRenderer(
                brand=brand,
                width=brand["layout"]["canvas_width"],
                height=brand["layout"]["canvas_height"],
            )
            story_post = CarouselPost(
                post_id=post.get("post_id", "story_now"),
                series=post.get("series", "factjot"),
                hook="",
                slides=[(post.get("slides") or [""])[0]],
                caption=post.get("caption", ""),
                hashtags=post.get("hashtags", []),
                sources=post.get("sources", []),
                confidence=0.9,
                category=post.get("category", "FACT"),
            )
            story_frame_path = renderer.render_stories_frame(
                story_post,
                bg_path=Path(render_paths[0]),
            )
            if story_frame_path:
                story_image_url = host.upload(story_frame_path).public_url
        except Exception as exc:
            print(f"  Story frame render skipped (non-fatal): {exc}")
        permalink = publisher.ig_permalink(ig_media_id)
        story_result = publisher.post_to_stories(
            image_url=story_image_url,
            link_url=permalink,
        )
    if story_result.get("ok"):
        print(f"  Story posted — ig_media_id: {story_result['ig_media_id']}")
        if story_result.get("warning"):
            print(f"  Story note: {story_result['warning']}")
    else:
        print(f"  Story skipped (non-fatal): {story_result.get('error')}")

    # ----- Step 3: brain writes -----
    slides_for_brain = []
    for slide_text in post.get("slides", []):
        plain = slide_text.replace("[i]", "").replace("[/i]", "").replace("[h]", "").replace("[/h]", "")
        slides_for_brain.append({
            "claim": plain,
            "topic": post.get("series", "").lower(),
            "category": post.get("category", ""),
            "sources": post.get("sources", []),
        })
    brain.record_publish(post_id=args.post_id, ig_media_id=ig_media_id, slides=slides_for_brain)
    brain.append_log(
        f"published {args.post_id} ({post.get('category', '?')}, {len(public_urls)} slides, ig_media={ig_media_id})"
    )
    queue.update_status(args.post_id, "published")
    print(f"DONE — recorded in posted.jsonl, queue marked published.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
