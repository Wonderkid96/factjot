"""Publish all carousel posts that are due right now from the approval queue.

Called by GitHub Actions (carousel-morning.yml and list-carousel.yml are NOT
this script -- this is for the older queue-based pipeline). Reads approval_queue.jsonl,
finds posts whose publish_at is in the past and status is "scheduled", then
uploads images and publishes via the Instagram Graph API.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.analytics.alerting import AlertingService
from src.analytics.performance_tracker import PerformanceTracker
from src.brain import brain
from src.content.description_builder import build_instagram_description
from src.core.config import load_config
from src.core.models import CarouselPost
from src.publish.image_host import make_image_host
from src.publish.instagram_publisher import InstagramGraphPublisher
from src.render.render_carousel import BrandKitRenderer
from src.review.approval_queue import ApprovalQueue
from src.utils.retry_utils import io_retry


def _host_local_paths(local_paths: list[str], host) -> list[str]:
    """Upload local PNGs via the configured image host, return public URLs.

    If a path is already an http URL (manual override), pass it through.
    """
    public: list[str] = []
    for p in local_paths:
        if p.startswith("http://") or p.startswith("https://"):
            public.append(p)
            continue
        hosted = host.upload(p)
        public.append(hosted.public_url)
    return public


def main() -> None:
    # Rule 13: refuse to publish if brain is stale.
    rc = subprocess.call([
        sys.executable,
        str(Path(__file__).parent / "check_brain_fresh.py"),
    ])
    if rc != 0:
        print("ABORT — brain is stale (rule 13). Update insta-brain/MEMORY_INDEX.md and log.md, then re-run.")
        return

    cfg = load_config()
    queue = ApprovalQueue(cfg.review["queue_path"])
    tracker = PerformanceTracker(cfg.storage["metrics_db_path"])
    alerting = AlertingService()
    publisher = InstagramGraphPublisher(
        account_id=cfg.env["INSTAGRAM_ACCOUNT_ID"],
        access_token=cfg.env["META_ACCESS_TOKEN"],
        graph_version=cfg.env["META_GRAPH_VERSION"],
        host=cfg.env["META_GRAPH_HOST"],
    )
    try:
        image_host = make_image_host()
    except RuntimeError as exc:
        print(f"ABORT — image host setup failed: {exc}")
        return

    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    from src.brain import DuplicatePostError
    due = queue.due_scheduled_posts(now_iso)
    for post in due:
        # Hard duplicate gate — fresh disk read on every post, catches cross-process duplicates.
        all_claims = []
        for slide_text in post.get("slides", []):
            plain = slide_text.replace("[i]","").replace("[/i]","").replace("[h]","").replace("[/h]","").strip()
            if plain:
                all_claims.append(plain)
        try:
            brain.assert_no_duplicate(all_claims)
        except DuplicatePostError as e:
            queue.update_status(post["post_id"], "cancelled")
            tracker.track_event("publish_failed", {"post_id": post["post_id"], "error": "duplicate blocked"})
            alerting.send_alert("publish_failed", {"post_id": post["post_id"], "error": str(e)[:200]})
            brain.append_log(f"carousel BLOCKED (duplicate) post_id={post['post_id']}")
            print(f"BLOCKED {post['post_id']}: duplicate — {str(e)[:120]}")
            continue

        try:
            image_urls = _host_local_paths(post.get("render_paths", []), image_host)
        except Exception as exc:
            queue.update_status(post["post_id"], "failed")
            tracker.track_event("publish_failed", {"post_id": post["post_id"], "error": f"imgbb upload: {exc}"})
            alerting.send_alert("publish_failed", {"post_id": post["post_id"], "error": f"imgbb upload failed: {exc}"})
            print(f"Failed {post['post_id']}: imgbb upload — {exc}")
            continue
        if not image_urls:
            queue.update_status(post["post_id"], "failed")
            tracker.track_event("publish_failed", {"post_id": post["post_id"], "error": "no render_paths"})
            print(f"Failed {post['post_id']}: render_paths empty")
            continue
        description = build_instagram_description(
            base_caption=post.get("caption", ""),
            hashtags=post.get("hashtags", []),
            image_credits=post.get("image_credits", []),
        )
        result = _publish_with_retry(publisher, image_urls=image_urls, caption=description)
        if result.get("ok"):
            # Growth path: also push slide 1 to Stories with a backlink.
            story_result = {"ok": False, "error": "missing image url"}
            if image_urls:
                story_image_url = image_urls[0]
                try:
                    render_paths = post.get("render_paths", [])
                    if render_paths:
                        brand = json.loads(Path("brand/brand_kit.json").read_text())
                        renderer = BrandKitRenderer(
                            brand=brand,
                            width=brand["layout"]["canvas_width"],
                            height=brand["layout"]["canvas_height"],
                        )
                        story_post = CarouselPost(
                            post_id=post.get("post_id", "story_due"),
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
                            story_image_url = image_host.upload(story_frame_path).public_url
                except Exception as exc:
                    print(f"Story frame render skipped (non-fatal): {exc}")
                permalink = publisher.ig_permalink(result["ig_media_id"])
                story_result = publisher.post_to_stories(
                    image_url=story_image_url,
                    link_url=permalink,
                )
            if story_result.get("ok"):
                print(f"Story posted for {post['post_id']}")
                if story_result.get("warning"):
                    print(f"Story note for {post['post_id']}: {story_result['warning']}")
            else:
                print(f"Story skipped for {post['post_id']} (non-fatal): {story_result.get('error')}")

            queue.update_status(post["post_id"], "published")
            slides_for_brain = []
            for slide_text in post.get("slides", []):
                plain = slide_text.replace("[i]", "").replace("[/i]", "").replace("[h]", "").replace("[/h]", "")
                slides_for_brain.append(
                    {
                        "claim": plain,
                        "topic": post.get("series", "").lower(),
                        "category": post.get("category", ""),
                        "sources": post.get("sources", []),
                    }
                )
            brain.record_publish(
                post_id=post["post_id"],
                ig_media_id=result["ig_media_id"],
                slides=slides_for_brain,
            )
            # Record the closing wholesome quote so we never reuse it.
            closing_quote = post.get("closing_quote", "")
            if closing_quote:
                brain.record_quote_used(
                    closing_quote,
                    attribution=post.get("closing_attribution", ""),
                    post_id=post["post_id"],
                    ig_media_id=result["ig_media_id"],
                )
            brain.append_log(
                f"published {post['post_id']} ({post.get('category', '?')}, {len(image_urls)} slides, ig_media={result['ig_media_id']})"
            )
            tracker.track_event("post_published", {"post_id": post["post_id"], "ig_media_id": result["ig_media_id"]})
            print(f"Published {post['post_id']}")
        else:
            tracker.track_event("publish_failed", {"post_id": post["post_id"], "error": result.get("error")})
            alerting.send_alert("publish_failed", {"post_id": post["post_id"], "error": result.get("error")})
            print(f"Failed {post['post_id']}: {result.get('error')}")


@io_retry()
def _publish_with_retry(publisher: InstagramGraphPublisher, image_urls: list[str], caption: str) -> dict:
    return publisher.publish_carousel(image_urls=image_urls, caption=caption)


if __name__ == "__main__":
    main()
