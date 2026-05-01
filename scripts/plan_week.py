"""Generate the next 7 days of carousels and queue them for autonomous publish.

Twice a day (10:00 and 18:00 local time) = 14 carousels per week.

Pipeline:
    1. Read all available facts via `load_all_facts()` (curated bank + auto-discovered).
    2. Filter out anything in `posted.jsonl` (rule 01).
    3. Group by topic, rotate so consecutive posts cover different categories.
    4. Build carousels (5-6 facts each).
    5. Render each via the HTML+Playwright pipeline.
    6. Append a row to `data/approval_queue.jsonl` and `insta-brain/data/queue.jsonl`
       with the scheduled publish time.

When the curated bank runs low, this script triggers `discover_facts.py`
in-process to top up before generation.

Run weekly via launchd (Sundays 04:00).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.brain import brain
from src.content.carousel_generator import CarouselDraftGenerator
from src.core.config import load_config
from src.core.models import SourceEvidence, VerifiedFact
from src.render.render_carousel import BrandKitRenderer
from src.research.rare_fact_bank import load_all_facts
from src.research.sensitivity_guide import CONTROVERSIAL
from src.review.approval_queue import ApprovalQueue
from src.utils.logging_utils import configure_logging

POSTS_PER_DAY = 2          # 10:00 and 18:00 local
WEEK_DAYS = 7
SLOT_HOURS = (10, 18)      # local time of day
MIN_FACTS_PER_POST = 4     # lower than ideal-of-6 so we can ship while bank grows
TARGET_FACTS_PER_POST = 5
LOW_RUNWAY_THRESHOLD = 3   # if any topic has fewer than 3 fresh, trigger discovery


def _fact_from_row(row: dict) -> VerifiedFact:
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
                url=u,
                publisher=u.split("/")[2] if "//" in u else u,
                snippet=row["claim"][:160],
                quality_score=0.9,
            )
            for u in row.get("sources", [])
        ],
        verified_at=row.get("discovered_at", datetime.utcnow().isoformat() + "Z"),
        image_hint=row.get("image_hint", ""),
    )


def _runway_by_topic() -> dict[str, list[dict]]:
    """Topic → list of fresh, publishable rows.

    Drops anything already posted (rule 01) and anything tagged
    `controversial` (rule 14). Edgy facts ARE allowed through the
    autonomous queue — they're typically the universally-loved ones
    (Phineas Gage, Aron Ralston, Cordyceps, etc) and gating them out
    made the feed bland. Controversial stays opt-in only via ship_first_post.
    """
    fresh: dict[str, list[dict]] = defaultdict(list)
    controversial_skipped = 0
    for row in load_all_facts():
        if brain.is_fact_posted(row["claim"]):
            continue
        if row.get("sensitivity") == CONTROVERSIAL:
            controversial_skipped += 1
            continue
        fresh[row["topic"]].append(row)
    if controversial_skipped:
        print(f"Sensitivity gate: skipped {controversial_skipped} controversial fact(s) from autonomous queue (edgy allowed).")
    return fresh


def _trigger_discovery() -> None:
    print("Bank runway low; triggering discover_facts.py...")
    subprocess.run([
        "/Library/Frameworks/Python.framework/Versions/Current/bin/python3",
        str(Path(__file__).parent / "discover_facts.py"),
    ], check=False)


def _next_slot_times(start_at: datetime, days: int, start_tomorrow: bool) -> list[datetime]:
    """Return slot timestamps: POSTS_PER_DAY per day for `days` days.

    If `start_tomorrow` is True, the first slot is the morning of (today + 1).
    Otherwise it's the next future slot from `start_at`.
    """
    out: list[datetime] = []
    if start_tomorrow:
        day0 = start_at.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    else:
        day0 = start_at.replace(hour=0, minute=0, second=0, microsecond=0)
    for d in range(days):
        for hour in SLOT_HOURS:
            slot = day0 + timedelta(days=d, hours=hour)
            if slot > start_at:
                out.append(slot)
    return out[: days * POSTS_PER_DAY]


def _build_carousel_inputs(fresh: dict[str, list[dict]], n_posts: int) -> list[list[dict]]:
    """Pick which facts go into which carousel.

    Round-robin through topics so consecutive posts cover different categories.
    Each carousel takes up to TARGET_FACTS_PER_POST facts from one topic.
    Keeps each topic's pool sorted by curated-first (curated rows have no
    `discovered_at` field), so curated facts ship before discovered ones.
    """
    pools: dict[str, list[dict]] = {}
    for topic, rows in fresh.items():
        # Sort: quirky_score descending (best facts first), curated before
        # auto-discovered, then stable alphabetical. This ensures the weekly
        # plan always leads with the most shocking facts and uses textbook-tier
        # (quirky_score 0-1) facts only when higher-scored ones are exhausted.
        pools[topic] = sorted(
            rows,
            key=lambda r: (
                -r.get("quirky_score", 1),        # higher score = earlier
                "discovered_at" in r,              # curated before auto-discovered
                r["claim"],                        # stable tiebreak
            ),
        )
    ordered_topics = sorted(pools.keys(), key=lambda t: -len(pools[t]))
    carousels: list[list[dict]] = []
    while len(carousels) < n_posts:
        progress = False
        for topic in list(ordered_topics):
            pool = pools.get(topic, [])
            if len(pool) < MIN_FACTS_PER_POST:
                continue
            chunk = pool[:TARGET_FACTS_PER_POST]
            pools[topic] = pool[TARGET_FACTS_PER_POST:]
            carousels.append(chunk)
            progress = True
            if len(carousels) >= n_posts:
                break
        if not progress:
            break
    return carousels


def _check_reel_runway(cfg, days_ahead: int) -> None:
    """Count unused quirky_score=3 facts and warn/trigger discovery if low.

    Reels need one q3 fact per day. If the unused stock falls below
    `reel_low_runway_threshold` (default 14 = 2 weeks), discovery runs
    so the bank is topped up before the queue runs dry.
    """
    from src.research.rare_fact_bank import RARE_FACT_BANK, _with_defaults
    from src.research.sensitivity_guide import CONTROVERSIAL

    threshold = cfg.pipeline.get("reel_low_runway_threshold", 14)

    q3_fresh = [
        _with_defaults(dict(r))
        for r in RARE_FACT_BANK
        if r.get("quirky_score", 0) == 3
        and not brain.is_fact_posted(r["claim"])
        and _with_defaults(dict(r)).get("sensitivity") != CONTROVERSIAL
    ]

    days_remaining = len(q3_fresh)
    weeks_remaining = days_remaining / 7

    print(f"\nReel runway: {days_remaining} unused quirky_score=3 facts "
          f"({weeks_remaining:.1f} weeks at 1/day)")

    if days_remaining < threshold:
        print(f"  WARNING: reel runway below {threshold}-fact threshold — triggering discovery")
        _trigger_discovery()
    elif days_remaining < days_ahead:
        print(f"  WARNING: only {days_remaining} reels available for {days_ahead}-day plan")
    else:
        print(f"  Reel bank healthy — next {min(days_remaining, days_ahead)} days covered")


def _run_trend_scout(dry_run: bool) -> None:
    """Fetch weekly trends, print a strategy report, generate auto list pack.

    Safe to fail — all errors are caught and logged so plan_week never
    aborts because of a trend fetch failure. The rest of the plan still runs.
    """
    try:
        from src.research.trend_scout import fetch_weekly_trends
        from src.content.auto_pack import build_trending_pack, get_posted_tmdb_ids

        print("\n── Weekly Trend Report ───────────────────────────────────")
        trends = fetch_weekly_trends()

        # Topic weights from Reddit TIL
        weights = trends.get("topic_weights", {})
        top_topic = trends.get("top_topic", "unknown")
        sorted_topics = sorted(weights.items(), key=lambda x: -x[1])
        print(f"  Reddit TIL signals this week:")
        for topic, score in sorted_topics:
            bar = "█" * score if score else "·"
            print(f"    {topic:<12} {bar} ({score})")
        print(f"  → Hot topic this week: {top_topic.upper()}")
        print(f"  → Reels and first carousel slot will favour {top_topic} facts")

        # Trending movies — auto list pack
        movies = trends.get("movies", [])
        print(f"\n  TMDB trending movies this week: {len(movies)} with backdrops")
        for m in movies[:5]:
            print(f"    {m['year']} {m['title'][:50]}")

        posted_ids = get_posted_tmdb_ids()
        pack = build_trending_pack(movies, posted_tmdb_ids=posted_ids)
        if pack:
            print(f"\n  Auto list pack generated: \"{pack['title']}\"")
            print(f"    Slug: {pack['slug']}")
            print(f"    Items: {', '.join(i.get('tmdb_id', '?') and str(i['tmdb_id']) for i in pack['items'])}")
            if dry_run:
                print(f"    DRY-RUN: pack saved to data/trends/ — ship manually with:")
                print(f"    python3 scripts/ship_list_post.py --pack {pack['slug']}")
            else:
                print(f"    Ready to ship: python3 scripts/ship_list_post.py --pack {pack['slug']}")
        else:
            print("\n  Not enough fresh trending movies for an auto list pack this week.")

        print("──────────────────────────────────────────────────────────\n")

    except Exception as exc:
        print(f"\n  [trends] Scout failed ({exc.__class__.__name__}: {exc}) — continuing without trend data")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="generate + render but skip enqueueing for publish")
    parser.add_argument("--days", type=int, default=WEEK_DAYS,
                        help="how many days ahead to schedule (default 7)")
    parser.add_argument("--start-tomorrow", action="store_true",
                        help="first slot is tomorrow morning (else the next future slot today)")
    args = parser.parse_args()

    configure_logging()
    cfg = load_config()
    brand = json.loads(Path("brand/brand_kit.json").read_text())
    queue = ApprovalQueue(cfg.review["queue_path"])

    n_posts = args.days * POSTS_PER_DAY
    fresh = _runway_by_topic()
    short = [t for t, r in fresh.items() if len(r) < LOW_RUNWAY_THRESHOLD]
    if short:
        _trigger_discovery()
        fresh = _runway_by_topic()  # reload after discovery

    print(f"Runway after discovery: " + ", ".join(f"{t}={len(r)}" for t, r in fresh.items()))

    # ------------------------------------------------------------------ #
    # Reel runway check — quirky_score=3 facts only
    # ------------------------------------------------------------------ #
    _check_reel_runway(cfg, args.days)

    # ------------------------------------------------------------------ #
    # Weekly trend scout
    # Fetches TMDB trending + Reddit TIL signals. Used for two things:
    #   1. Topic weighting — carousels and reels favour the hot topic
    #      this week (e.g. space if Starship launched).
    #   2. Auto list pack — generates a "Trending This Week" film list
    #      saved to data/trends/ and printed for Toby to review/ship.
    # ------------------------------------------------------------------ #
    _run_trend_scout(args.dry_run)

    carousels = _build_carousel_inputs(fresh, n_posts)
    if not carousels:
        print("No carousels could be built. Bank empty across all topics.")
        return 2

    slots = _next_slot_times(datetime.now(timezone.utc), args.days, args.start_tomorrow)
    if len(carousels) < n_posts:
        print(f"WARNING: only built {len(carousels)} of {n_posts} target carousels.")

    # Idempotency: skip post_ids AND timeslots already in the queue. Without
    # the timeslot check, a second plan_week run with a different fact pool
    # produces a different post_id but the same publish_at, double-booking.
    already_queued: set[str] = set()
    booked_slots: set[str] = set()
    for row in queue.list_all():
        if row.get("status") in {"scheduled", "approved", "published"}:
            already_queued.add(row.get("post_id", ""))
            pa = row.get("publish_at")
            if pa:
                booked_slots.add(pa)

    gen = CarouselDraftGenerator()
    renderer = BrandKitRenderer(
        brand=brand,
        width=brand["layout"]["canvas_width"],
        height=brand["layout"]["canvas_height"],
    )

    enqueued = 0
    skipped_dup = 0
    for carousel_rows, slot in zip(carousels, slots):
        slot_iso = slot.isoformat().replace("+00:00", "Z")
        # Idempotency: if this timeslot is already booked, skip BEFORE generating.
        if slot_iso in booked_slots:
            skipped_dup += 1
            continue

        facts = [_fact_from_row(r) for r in carousel_rows]
        posts = gen.generate(facts, default_series=["factjot"])
        if not posts:
            continue
        post = posts[0]

        # Belt-and-braces: skip if this exact post_id is already queued.
        if post.post_id in already_queued:
            skipped_dup += 1
            continue

        post.publish_at = slot_iso
        booked_slots.add(slot_iso)
        already_queued.add(post.post_id)

        paths = renderer.render_post(post)
        if not paths:
            print(f"  [skip] render failed for {post.post_id} ({post.status})")
            continue
        post.render_paths = paths

        if not args.dry_run:
            post.status = "scheduled"
            queue.enqueue(post)
            brain.append_queue({
                "post_id": post.post_id,
                "category": post.category,
                "scheduled_for": post.publish_at,
                "status": "scheduled",
                "render_paths": paths,
            })
        enqueued += 1
        print(f"  [{enqueued}] {slot.strftime('%a %d %b %H:%M')} UTC — {post.category} ({len(paths)} slides)")

    print()
    print(f"Plan complete: {enqueued} new carousels scheduled across {args.days} days "
          f"({skipped_dup} skipped as already queued).")
    print(f"Queue file: {cfg.review['queue_path']}")
    if args.dry_run:
        print("DRY-RUN: no posts were enqueued.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
