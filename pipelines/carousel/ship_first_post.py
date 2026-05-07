"""Render one carousel from the curated bank and publish it to Instagram.

End to end:
    1. Pull a topic's facts from the rare fact bank.
    2. Generate the carousel (slides + caption + hashtags).
    3. Render slides via HTML+Playwright.
    4. Host PNGs on imgbb.
    5. Publish carousel via Instagram Graph API.
    6. Record in insta-brain/data/posted.jsonl + log.md.

Usage (local Mac):
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3 pipelines/carousel/ship_first_post.py --topic space
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3 pipelines/carousel/ship_first_post.py --topic nature --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.brain import brain
from src.content.carousel_generator import CarouselDraftGenerator
from src.content.description_builder import build_instagram_description
from src.core.config import load_config
from src.core.models import SourceEvidence, VerifiedFact
from src.publish.image_host import make_image_host
from src.publish.instagram_publisher import InstagramGraphPublisher
from src.render.render_carousel import BrandKitRenderer
from src.research.rare_fact_bank import load_all_facts, _with_defaults
from src.research.sensitivity_guide import filter_for_publish
from src.utils.logging_utils import configure_logging


def _fact_from_bank(row: dict) -> VerifiedFact:
    fact_id = hashlib.sha1(f"{row['topic']}:{row['claim']}".encode()).hexdigest()[:12]
    return VerifiedFact(
        fact_id=fact_id,
        topic=row["topic"],
        claim=row["claim"],
        verified=True,
        confidence=0.92,
        contradiction_flags=[],
        sources=[
            SourceEvidence(
                url=u, publisher=u.split("/")[2], snippet=row["claim"][:160], quality_score=0.9
            )
            for u in row["sources"]
        ],
        verified_at=datetime.utcnow().isoformat() + "Z",
        image_hint=row.get("image_hint", ""),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default=None, help="Optional topic filter. Omit for a random fact from any topic.")
    parser.add_argument("--dry-run", action="store_true",
                        help="render + host on imgbb but skip the final IG publish call")
    parser.add_argument("--safe-only", action="store_true",
                        help="restrict to safe-tier facts only (no graphic medical, death events, body horror)")
    parser.add_argument("--allow-controversial", action="store_true",
                        help="permit controversial-tier facts (animal welfare, religion, politics, etc).")
    args = parser.parse_args()

    configure_logging()
    cfg = load_config()
    brand = json.loads(Path("brand/brand_kit.json").read_text())

    # Per-day carousel cap removed: the autonomous agent is now the
    # single poster and runs its own duplicate guard via the post bank
    # summary. The old daily cap blocked legitimate same-day choices.

    # ----- Pick facts from the full bank (or filtered by topic if specified) -----
    # Apply schema defaults so every row carries sensitivity fields before filtering.
    all_rows = [_with_defaults(dict(row)) for row in load_all_facts()]
    if args.topic:
        all_rows = [r for r in all_rows if r["topic"] == args.topic]
    posted_filtered = [row for row in all_rows if not brain.is_fact_posted(row["claim"])]
    posted_skipped = len(all_rows) - len(posted_filtered)

    # Sensitivity gate: default = safe + edgy (the well-loved dark stuff).
    # --safe-only narrows to safe-tier only.
    # --allow-controversial widens to include the opt-in tier.
    fresh_rows = filter_for_publish(
        posted_filtered,
        allow_edgy=not args.safe_only,
        allow_controversial=args.allow_controversial,
    )
    sensitivity_skipped = len(posted_filtered) - len(fresh_rows)
    if sensitivity_skipped:
        skipped_examples = [
            f"  - [{r['sensitivity']}] {r['claim'][:70]}... flags={r.get('sensitivity_flags') or []}"
            for r in posted_filtered if r not in fresh_rows
        ][:3]
        print(f"Sensitivity gate dropped {sensitivity_skipped} fact(s). Sample:")
        for line in skipped_examples:
            print(line)

    # Quality floor — never post score=1 (mildly interesting) facts while
    # better ones exist anywhere in the bank.
    MIN_CAROUSEL_SCORE = 2
    # Reserve reel-eligible facts (reel_script + reel_title) for the reel pipeline.
    # Using them as carousels wastes the curated video script and reduces reel runway.
    # Only use reel-eligible facts as carousel if NO other facts remain (bank empty).
    # Prefer facts that don't have reel scripts (those are better saved for reels)
    non_reel = [r for r in fresh_rows if not (r.get("reel_script") and r.get("reel_title"))]
    if non_reel:
        fresh_rows = non_reel

    # Quality floor -- prefer quirky_score >= MIN_CAROUSEL_SCORE, fall back to any if needed
    quality_rows = [r for r in fresh_rows if r.get("quirky_score", 1) >= MIN_CAROUSEL_SCORE]
    if quality_rows:
        fresh_rows = quality_rows
    elif fresh_rows:
        print(f"Quality bank low -- using score<{MIN_CAROUSEL_SCORE} facts as emergency fallback.")
        brain.append_log(f"carousel WARNING -- quality bank low, used score<{MIN_CAROUSEL_SCORE} facts")

    # Hard floor: need at least 3 facts for a carousel
    MIN_FRESH_FACTS = 3
    if len(fresh_rows) < MIN_FRESH_FACTS:
        topic_label = args.topic or "any"
        print(f"\nABORT: only {len(fresh_rows)} fresh fact(s) available (topic={topic_label!r}), need >={MIN_FRESH_FACTS}.")
        print("Top up src/research/rare_fact_bank.py with new facts.")
        brain.append_log(f"carousel ABORTED -- runway too low ({len(fresh_rows)} fresh, need {MIN_FRESH_FACTS}+)")
        return 2

    # Sort best facts first; stable so ties keep bank order
    fresh_rows.sort(key=lambda r: r.get("quirky_score", 1), reverse=True)

    topic_label = args.topic or "mixed"
    facts = [_fact_from_bank(row) for row in fresh_rows]
    quirky_picked = sum(1 for r in fresh_rows[:6] if r.get("quirky_score", 1) >= 2)
    print(f"Found {len(fresh_rows)} fresh facts (topic={topic_label!r}, {posted_skipped} already-posted, {sensitivity_skipped} sensitivity-gated, top-6 has {quirky_picked} quirky_score≥2)")

    # ----- Generate the carousel -----
    gen = CarouselDraftGenerator()
    posts = gen.generate(facts, default_series=["factjot"])
    if not posts:
        print("Generator returned no posts.")
        return 3
    post = posts[0]
    print(f"\nPost {post.post_id} | category={post.category} | {len(post.slides)} slides")
    for i, slide in enumerate(post.slides, start=1):
        plain = slide.replace("[i]", "").replace("[/i]", "").replace("[h]", "").replace("[/h]", "")
        print(f"  {i}. {plain}")

    # ----- Rule 01 final check -----
    for s in post.slides:
        plain = s.replace("[i]", "").replace("[/i]", "").replace("[h]", "").replace("[/h]", "")
        if brain.is_fact_posted(plain):
            print(f"\nABORT: claim already in posted.jsonl: {plain[:80]}")
            return 4

    # ----- Render -----
    print("\nRendering slides (Playwright + Chromium)...")
    renderer = BrandKitRenderer(
        brand=brand,
        width=brand["layout"]["canvas_width"],
        height=brand["layout"]["canvas_height"],
    )
    paths = renderer.render_post(post)
    if not paths:
        print(f"Render produced no PNGs. status={post.status}")
        return 5
    from src.core.paths import RENDERS_CACHE
    render_folder = Path(paths[0]).parent if paths else RENDERS_CACHE
    print(f"  {len(paths)} PNGs at {render_folder}/")

    # ----- Host slides via the configured image host (imgbb / cloudinary) -----
    try:
        host = make_image_host()
    except RuntimeError as exc:
        print(f"Image host setup failed: {exc}")
        return 6
    print(f"\nUploading via {type(host).__name__}...")
    hosted = host.upload_many(paths)
    public_urls = [h.public_url for h in hosted]
    for u in public_urls:
        print(f"  {u}")

    if args.dry_run:
        print("\nDRY-RUN — skipping Instagram publish call.")
        print("Inspect any of the imgbb URLs above to verify the slide looks right.")
        return 0

    # Hard duplicate gate — fresh disk read, catches facts posted in other processes.
    # This fires even for spontaneous manual requests. Not catchable/bypassable.
    from src.brain import DuplicatePostError
    all_claims = []
    for s in post.slides:
        plain = s.replace("[i]","").replace("[/i]","").replace("[h]","").replace("[/h]","").strip()
        if plain:
            all_claims.append(plain)
    try:
        brain.assert_no_duplicate(all_claims)
    except DuplicatePostError as e:
        print(f"\nABORTED — duplicate block:\n{e}")
        brain.append_log(f"carousel BLOCKED — duplicate claim(s) in {post.post_id}")
        return 8

    # ----- Publish -----
    print("\nPublishing carousel to Instagram...")
    publisher = InstagramGraphPublisher(
        account_id=cfg.env["INSTAGRAM_ACCOUNT_ID"],
        access_token=cfg.env["META_ACCESS_TOKEN"],
        graph_version=cfg.env["META_GRAPH_VERSION"],
        host=cfg.env["META_GRAPH_HOST"],
    )
    full_caption = build_instagram_description(
        base_caption=post.caption,
        hashtags=post.hashtags,
        image_credits=post.image_credits,
    )
    result = publisher.publish_carousel(image_urls=public_urls, caption=full_caption)
    if not result.get("ok"):
        print(f"\nPublish failed: {result.get('error')}")
        return 7
    ig_media_id = result["ig_media_id"]
    print(f"PUBLISHED — ig_media_id: {ig_media_id}")

    # ----- Render + post Stories frame -----
    # Renders a 9:16 (1080x1920) framed version of slide 1 — properly fitted
    # for Stories. Includes a link sticker pointing to the carousel so
    # followers can tap straight through to the post.
    print("\nRendering Stories frame (9:16)...")
    try:
        # Use rendered slide 1 so story references the exact live carousel
        # design without stretching or re-typesetting copy.
        bg_path = Path(paths[0])
        stories_path = renderer.render_stories_frame(post, bg_path=bg_path)
        if stories_path:
            stories_hosted = host.upload(stories_path)
            permalink = publisher.ig_permalink(ig_media_id)
            print(f"  Uploading Stories frame...")
            story_result = publisher.post_to_stories(
                stories_hosted.public_url,
                link_url=permalink,
            )
            if story_result.get("ok"):
                print(f"  Story posted — ig_media_id: {story_result['ig_media_id']}")
                if permalink and story_result.get("link_requested"):
                    if story_result.get("warning"):
                        print(f"  Link sticker fallback: {story_result['warning']}")
                    elif story_result.get("link_applied"):
                        print(f"  Link sticker requested → {permalink}")
                    else:
                        print("  Link sticker status uncertain (IG may silently ignore it).")
            else:
                print(f"  Story skipped (non-fatal): {story_result.get('error')}")
        else:
            print("  Stories frame render failed (non-fatal).")
    except Exception as exc:
        print(f"  Stories skipped (non-fatal): {exc}")

    # ----- Record in brain -----
    slides_for_brain = []
    for s in post.slides:
        plain = s.replace("[i]", "").replace("[/i]", "").replace("[h]", "").replace("[/h]", "")
        slides_for_brain.append({
            "claim": plain,
            "topic": post.series.lower(),
            "category": post.category,
            "sources": post.sources,
        })
    brain.record_publish(post_id=post.post_id, ig_media_id=ig_media_id, slides=slides_for_brain)
    if post.closing_quote:
        brain.record_quote_used(
            post.closing_quote,
            attribution=post.closing_attribution,
            post_id=post.post_id,
            ig_media_id=ig_media_id,
        )
    brain.append_log(
        f"published {post.post_id} ({post.category}, {len(public_urls)} slides, ig_media={ig_media_id})"
    )
    print("Recorded in insta-brain/data/posted.jsonl, posted_quotes.jsonl, and log.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
