#!/usr/bin/env bash
# Clear only discovery / list-prep caches so the next scout run sees fresh inventory.
#
# NEVER add insta-brain/data/posted.jsonl, reels.jsonl, list_posts.jsonl,
# data/ledgers/used_images.jsonl, or data/ledgers/used_footage_urls.jsonl to
# this script. Those record what was published and what assets were used;
# truncating them causes duplicate posts and reused media.
#
# Canonical lists: src/core/paths.py → PUBLISH_AND_DEDUP_LEDGERS,
# SCOUT_INVENTORY_CACHE_LEDGERS.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

truncate_empty() {
  local f="$1"
  mkdir -p "$(dirname "$f")"
  : >"$f"
}

truncate_empty "data/ledgers/discovery.log.jsonl"
truncate_empty "data/ledgers/list_pack_cache.jsonl"
truncate_empty "data/ledgers/generated_list_packs.jsonl"
truncate_empty "data/ledgers/used_list_themes.jsonl"
truncate_empty "data/ledgers/reel_discovery_staging.jsonl"

mkdir -p data/trends
find data/trends -mindepth 1 -maxdepth 1 -name "*.json" -delete 2>/dev/null || true

# Optional: regeneratable downloads only (not git-tracked).
for d in data/cache/images data/cache/list_assets data/cache/reels data/cache/renders; do
  if [[ -d "$d" ]]; then
    find "$d" -mindepth 1 -delete
  fi
done

echo "Scout inventory caches cleared under $ROOT"
echo "Publish and dedup ledgers were not modified."
