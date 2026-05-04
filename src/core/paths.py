"""Canonical path constants for the factjot project.

Import from here instead of hardcoding strings. All paths are absolute
so scripts work regardless of cwd.

Structure:
  data/
    ledgers/   - append-only .jsonl truth stores
    cache/     - regeneratable downloads (images, renders, reels)
    db/        - .json databases

  logs/        - launchd + heartbeat logs

  assets/
    avatars/   - brand avatar images
    fonts/     - typography
    music/     - Reel music tracks
    video/     - safety-pool footage

  insta-brain/data/  - brain-owned ledgers (posted, quotes, reels, etc.)
"""
from pathlib import Path

# ------------------------------------------------------------------ #
# Root
# ------------------------------------------------------------------ #
ROOT = Path(__file__).resolve().parents[2]

# ------------------------------------------------------------------ #
# data/ledgers/  - append-only truth stores
# ------------------------------------------------------------------ #
LEDGERS         = ROOT / "data" / "ledgers"
APPROVAL_QUEUE  = LEDGERS / "approval_queue.jsonl"
DISCOVERED_FACTS = LEDGERS / "discovered_facts.jsonl"
LIST_PACK_CACHE      = LEDGERS / "list_pack_cache.jsonl"
GENERATED_LIST_PACKS = LEDGERS / "generated_list_packs.jsonl"
USED_LIST_THEMES     = LEDGERS / "used_list_themes.jsonl"
DISCOVERY_LOG   = LEDGERS / "discovery.log.jsonl"
USED_IMAGES     = LEDGERS / "used_images.jsonl"
USED_FOOTAGE    = LEDGERS / "used_footage_urls.jsonl"
ALERTS          = LEDGERS / "alerts.jsonl"
PUBLISH_FAILURES = LEDGERS / "publish_failures.jsonl"

# ------------------------------------------------------------------ #
# data/cache/  - regeneratable, safe to delete
# ------------------------------------------------------------------ #
CACHE           = ROOT / "data" / "cache"
IMAGES_CACHE    = CACHE / "images"
RENDERS_CACHE   = CACHE / "renders"
LIST_ASSETS_CACHE = CACHE / "list_assets"
REELS_CACHE     = CACHE / "reels"

# ------------------------------------------------------------------ #
# data/db/  - json databases
# ------------------------------------------------------------------ #
DB              = ROOT / "data" / "db"
METRICS_DB      = DB / "metrics_db.json"
# FACTS_DB, POSTS_DB, WEEKLY_STATE removed -- legacy of an older analytics design,
# never imported by any current consumer.

# ------------------------------------------------------------------ #
# logs/
# ------------------------------------------------------------------ #
LOGS            = ROOT / "logs"
HEARTBEAT_LOG   = LOGS / "heartbeat.log"
REEL_RUN_LOGS   = LOGS / "reel_runs"

# ------------------------------------------------------------------ #
# assets/
# ------------------------------------------------------------------ #
ASSETS          = ROOT / "assets"
AVATARS         = ASSETS / "avatars"

# ------------------------------------------------------------------ #
# insta-brain/  - brain root, ledgers, rules, bank, logs
# ------------------------------------------------------------------ #
REPO_ROOT       = ROOT
BRAIN_DIR       = ROOT / "insta-brain"
BRAIN_DATA      = BRAIN_DIR / "data"
BRAIN_RULES     = BRAIN_DIR / "rules"
BRAIN_BANK      = BRAIN_DIR / "bank"
BRAIN_LOG       = BRAIN_DIR / "log.md"
BRAIN_INBOX     = BRAIN_DIR / "inbox.md"
POSTED          = BRAIN_DATA / "posted.jsonl"
POSTED_QUOTES   = BRAIN_DATA / "posted_quotes.jsonl"
REELS_LEDGER    = BRAIN_DATA / "reels.jsonl"
# Permanent list-carousel ledger — never wiped by reset-and-relaunch.
# ship_list_post.py is the only writer. Dedup checks here first.
LIST_POSTS      = BRAIN_DATA / "list_posts.jsonl"
BRAIN_QUEUE     = BRAIN_DATA / "queue.jsonl"
STATS           = BRAIN_DATA / "stats.jsonl"
TRENDS          = BRAIN_DATA / "trends.jsonl"


def ensure_dirs() -> None:
    """Create all required directories if they don't exist."""
    for d in (LEDGERS, CACHE, IMAGES_CACHE, RENDERS_CACHE,
              LIST_ASSETS_CACHE, REELS_CACHE, DB, LOGS, REEL_RUN_LOGS, AVATARS):
        d.mkdir(parents=True, exist_ok=True)
