#!/usr/bin/env bash
# Emergency stop: stacked local `make_reel.py` + FFmpeg compose jobs (same machine).
# Safe to run any time; does not touch GitHub Actions or cron-job.org.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "Stopping FFmpeg jobs using factjot intro from: $ROOT"
pkill -f "${ROOT}/assets/intros/factjot_intro.mov" 2>/dev/null || true
echo "Stopping make_reel.py under: $ROOT"
pkill -f "${ROOT}/scripts/make_reel.py" 2>/dev/null || true
sleep 1
echo "Remaining matches (should be empty):"
pgrep -fl make_reel 2>/dev/null | grep -F "$ROOT" || echo "  (none)"
pgrep -fl factjot_intro 2>/dev/null | grep -F "$ROOT" || echo "  (none)"
echo "Done."
