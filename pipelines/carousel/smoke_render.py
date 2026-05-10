"""ORPHANED — DO NOT RUN. rare_fact_bank.py was deleted in Phase G.1.

This module imports `from src.research.rare_fact_bank import RARE_FACT_BANK`
which raises `ImportError` immediately. The `Usage` line below is preserved
for archaeology only — running it crashes before any render happens. The
file is kept on disk because it's outside the Phase G deletion list, not
because it works. Do not import this module. Do not resuscitate
`rare_fact_bank.py`. See `CLAUDE.md §12` for Phase G rationale.

(Original docstring follows.)

Render sample posts end-to-end so we can eyeball the new style.

Pulls multiple facts from the rare fact bank for two topics, builds two
carousels, and writes them as PNGs via the HTML+Playwright renderer.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.content.carousel_generator import CarouselDraftGenerator
from src.core.models import SourceEvidence, VerifiedFact
from src.render.render_carousel import BrandKitRenderer
# BROKEN IMPORT: rare_fact_bank.py was deleted Phase G.1. The line below
# raises ImportError on module load. Do not "fix" by recreating
# rare_fact_bank.py — the deletion is deliberate.
from src.research.rare_fact_bank import RARE_FACT_BANK
from src.utils.logging_utils import configure_logging


def _fact_from_bank(row: dict) -> VerifiedFact:
    fact_id = hashlib.sha1(f"{row['topic']}:{row['claim']}".encode("utf-8")).hexdigest()[:12]
    return VerifiedFact(
        fact_id=fact_id,
        topic=row["topic"],
        claim=row["claim"],
        verified=True,
        confidence=0.92,
        contradiction_flags=[],
        sources=[
            SourceEvidence(
                url=url,
                publisher=url.replace("https://", "").split("/")[0].replace("www.", ""),
                snippet=row["claim"][:160],
                quality_score=0.9,
            )
            for url in row["sources"]
        ],
        verified_at=datetime.utcnow().isoformat() + "Z",
        image_hint=row.get("image_hint", ""),
    )


def main() -> None:
    configure_logging()
    brand = json.loads(Path("brand/brand_kit.json").read_text(encoding="utf-8"))

    # Two topics, multiple facts each.
    sample_topics = ["space", "biology"]
    facts: list[VerifiedFact] = []
    for topic in sample_topics:
        for row in RARE_FACT_BANK:
            if row["topic"] == topic:
                facts.append(_fact_from_bank(row))

    generator = CarouselDraftGenerator()
    posts = generator.generate(facts, default_series=["factjot"])

    renderer = BrandKitRenderer(
        brand=brand,
        width=brand["layout"]["canvas_width"],
        height=brand["layout"]["canvas_height"],
        output_dir=None,
    )

    for post in posts:
        print(f"\n=== Post {post.post_id} | category={post.category} | slides={len(post.slides)} ===")
        for i, slide in enumerate(post.slides, start=1):
            print(f"  slide {i}: {slide}")
        paths = renderer.render_post(post)
        print(f"  rendered {len(paths)} slide(s):")
        for p in paths:
            print(f"    {p}")


if __name__ == "__main__":
    main()
