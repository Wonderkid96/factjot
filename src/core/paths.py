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
# Staging file for reel discovery candidates (safe to truncate for fresh scout runs).
REEL_DISCOVERY_STAGING = LEDGERS / "reel_discovery_staging.jsonl"
USED_IMAGES     = LEDGERS / "used_images.jsonl"
USED_FOOTAGE    = LEDGERS / "used_footage_urls.jsonl"
ALERTS          = LEDGERS / "alerts.jsonl"
REEL_PERFORMANCE = LEDGERS / "reel_performance.jsonl"
PUBLISH_FAILURES = LEDGERS / "publish_failures.jsonl"

# ------------------------------------------------------------------ #
# output/  - all pipeline renders, local only, gitignored
# Each subfolder = one pipeline. Folders named YYYY-MM-DD_HH-MM_TOPIC
# so they sort chronologically and are easy to find in Finder.
# ------------------------------------------------------------------ #
OUTPUT          = ROOT / "output"
RENDERS_CACHE   = OUTPUT / "carousel"   # fact carousel slide PNGs
REELS_CACHE     = OUTPUT / "reel"       # reel build artefacts
LIST_RENDERS    = OUTPUT / "list"       # list carousel slide PNGs
NEWS_RENDERS    = OUTPUT / "news"       # news carousel slide PNGs

# ------------------------------------------------------------------ #
# data/cache/  - regeneratable downloads (images, etc.)
# ------------------------------------------------------------------ #
CACHE           = ROOT / "data" / "cache"
IMAGES_CACHE    = CACHE / "images"
LIST_ASSETS_CACHE = CACHE / "list_assets"

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
# Permanent subject-key dedup — one entry per reel/carousel subject ever posted.
# Hard-blocks exact and near-duplicate subjects across all time (no window).
SUBJECT_KEYS    = BRAIN_DATA / "subject_keys.jsonl"

# Publish history and asset dedup: never truncate or "reset" these when clearing
# scout caches. Workflows commit these after each post; losing them allows
# duplicate captions/topics and reused images or footage.
PUBLISH_AND_DEDUP_LEDGERS: tuple[Path, ...] = (
    POSTED,
    POSTED_QUOTES,
    REELS_LEDGER,
    LIST_POSTS,
    USED_IMAGES,
    USED_FOOTAGE,
    SUBJECT_KEYS,
)

# Discovery and list-prep caches only. Safe to empty for a fresh candidate
# inventory; does not affect duplicate guards.
SCOUT_INVENTORY_CACHE_LEDGERS: tuple[Path, ...] = (
    DISCOVERY_LOG,
    LIST_PACK_CACHE,
    GENERATED_LIST_PACKS,
    USED_LIST_THEMES,
    REEL_DISCOVERY_STAGING,
)


def ensure_dirs() -> None:
    """Create all required directories if they don't exist."""
    for d in (LEDGERS, CACHE, IMAGES_CACHE, LIST_ASSETS_CACHE,
              OUTPUT, RENDERS_CACHE, REELS_CACHE, LIST_RENDERS, NEWS_RENDERS,
              DB, LOGS, REEL_RUN_LOGS, AVATARS):
        d.mkdir(parents=True, exist_ok=True)
