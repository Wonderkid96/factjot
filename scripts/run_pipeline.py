from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.core.json_store import JsonStore
from src.analytics.performance_tracker import PerformanceTracker
from src.brain import brain
from src.content.carousel_generator import CarouselDraftGenerator
from src.core.config import load_config
from src.render.render_carousel import BrandKitRenderer
from src.research.fact_discovery import FactDiscoveryService
from src.review.approval_queue import ApprovalQueue
from src.utils.logging_utils import configure_logging
from src.verification.fact_checker import FactVerificationLayer


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate verified Instagram carousel drafts.")
    parser.add_argument("--topics", nargs="+", required=True, help="Topics to research")
    parser.add_argument("--count", type=int, default=10, help="Number of draft posts")
    args = parser.parse_args()

    configure_logging()
    cfg = load_config()
    tracker = PerformanceTracker(cfg.storage["metrics_db_path"])
    queue = ApprovalQueue(cfg.review["queue_path"])
    facts_store = JsonStore(cfg.storage["facts_db_path"], default=[])
    posts_store = JsonStore(cfg.storage["posts_db_path"], default=[])
    existing_claims = {row.get("claim", "") for row in facts_store.read()}

    discovery = FactDiscoveryService(cfg.discovery["max_candidates_per_topic"], existing_claims=existing_claims)
    verifier = FactVerificationLayer(cfg.pipeline["min_sources"], cfg.pipeline["min_confidence"])
    generator = CarouselDraftGenerator(cfg.pipeline["max_slide_words"])
    renderer = BrandKitRenderer(
        cfg.brand,
        width=cfg.render["width"],
        height=cfg.render["height"],
        output_dir=cfg.render["output_dir"],
    )

    candidates = discovery.discover(args.topics, count=args.count * 2)
    verified = verifier.verify(candidates)
    posts = generator.generate(verified[: args.count], cfg.pipeline["default_series"])

    for post in posts:
        min_rel = cfg.images.get("min_relevance_score", 0.55)
        if post.image_relevance_score < min_rel:
            post.status = "qa_failed"
            tracker.track_event(
                "image_relevance_failed",
                {"post_id": post.post_id, "score": post.image_relevance_score, "threshold": min_rel},
            )
        else:
            post.render_paths = renderer.render_post(post)
            post.status = "needs_approval" if post.render_paths else post.status
        queue.enqueue(post)
        brain.append_queue(
            {
                "post_id": post.post_id,
                "category": post.category,
                "slides": post.slides,
                "caption": post.caption,
                "hashtags": post.hashtags,
                "image_credits": post.image_credits,
                "render_paths": post.render_paths,
                "status": post.status,
            }
        )
        tracker.track_event("post_drafted", {"post_id": post.post_id, "status": post.status})

    facts_rows = facts_store.read()
    for fact in verified[: args.count]:
        facts_rows.append(
            {
                "fact_id": fact.fact_id,
                "topic": fact.topic,
                "claim": fact.claim,
                "confidence": fact.confidence,
                "sources": [s.url for s in fact.sources],
                "verified_at": fact.verified_at,
            }
        )
    facts_store.write(facts_rows)

    posts_rows = posts_store.read()
    posts_rows.extend([p.to_dict() for p in posts])
    posts_store.write(posts_rows)
    brain.append_log(
        f"generated {len(posts)} posts for topics={','.join(args.topics)}"
    )
    print(f"Created {len(posts)} posts. Review queue: {cfg.review['queue_path']}")


if __name__ == "__main__":
    main()
