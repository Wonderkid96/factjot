"""Generate themed list carousel packs from the THEMES pool.

Runs every Sunday via weekly-plan.yml. Picks PACKS_PER_RUN random unused
themes, generates complete packs via TMDB Discover, and appends them to
data/ledgers/generated_list_packs.jsonl.

ship_list_post.py reads this file alongside the curated LIST_PACKS dict,
giving the evening list carousel an effectively infinite supply of unique,
themed content without any manual curation.

With 80+ themes, cycling takes 80+ weeks. Once exhausted, used_themes resets
automatically and the cycle begins again. Films never repeat across packs —
get_posted_tmdb_ids() ensures dedup.
"""
from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.brain import brain
from src.content.auto_pack import build_themed_pack, get_posted_tmdb_ids
from src.content.list_themes import THEMES
from src.content.pack_resolver import list_dedupe_claim
from src.core.paths import GENERATED_LIST_PACKS, USED_LIST_THEMES

PACKS_PER_RUN  = 3   # generate this many new packs each Sunday
TARGET_BUFFER  = 14  # if fewer than this many unposted packs exist, generate more


def _load_used_theme_slugs() -> set[str]:
    if not USED_LIST_THEMES.exists():
        return set()
    out: set[str] = set()
    for line in USED_LIST_THEMES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.add(json.loads(line)["slug"])
            except Exception:
                pass
    return out


def _mark_theme_used(slug: str) -> None:
    USED_LIST_THEMES.parent.mkdir(parents=True, exist_ok=True)
    with USED_LIST_THEMES.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"slug": slug, "used_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}) + "\n")


def _load_generated_packs() -> list[dict]:
    if not GENERATED_LIST_PACKS.exists():
        return []
    out = []
    for line in GENERATED_LIST_PACKS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def _append_generated_pack(pack: dict) -> None:
    GENERATED_LIST_PACKS.parent.mkdir(parents=True, exist_ok=True)
    with GENERATED_LIST_PACKS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(pack, ensure_ascii=True) + "\n")


def _count_unposted_generated(generated: list[dict]) -> int:
    return sum(1 for p in generated if not brain.is_fact_posted(list_dedupe_claim(p["slug"])))


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv()

    posted_ids = get_posted_tmdb_ids()
    used_slugs = _load_used_theme_slugs()
    generated = _load_generated_packs()

    unposted = _count_unposted_generated(generated)
    print(f"Generated pack buffer: {unposted} unposted packs")

    # Work out how many to generate
    n_to_generate = max(PACKS_PER_RUN, TARGET_BUFFER - unposted)

    # Available themes — unused first. If all used, reset and cycle.
    available = [t for t in THEMES if t["slug"] not in used_slugs]
    if not available:
        print("All themes used — resetting cycle.")
        used_slugs = set()
        USED_LIST_THEMES.write_text("", encoding="utf-8")
        available = list(THEMES)

    # Already-generated slugs (don't regenerate existing ones)
    existing_slugs = {p["slug"] for p in generated}
    available = [t for t in available if t["slug"] not in existing_slugs]

    if not available:
        print("All available themes already generated — nothing to do.")
        return 0

    random.shuffle(available)
    targets = available[:n_to_generate]

    generated_count = 0
    for theme in targets:
        print(f"\nGenerating: {theme['slug']!r} — {theme['title']!r}")
        pack = build_themed_pack(theme, posted_ids)
        if pack:
            _append_generated_pack(pack)
            _mark_theme_used(theme["slug"])
            generated_count += 1
            print(f"  OK — {len(pack['items'])} films")
        else:
            print(f"  SKIPPED — not enough films found")

    print(f"\nGeneration complete: {generated_count}/{len(targets)} packs written")
    print(f"Total generated pack buffer: {unposted + generated_count} unposted packs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
