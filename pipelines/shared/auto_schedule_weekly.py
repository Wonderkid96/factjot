from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.core.config import load_config
from src.review.approval_queue import ApprovalQueue
from src.review.weekly_scheduler import next_weekday_slot


def main() -> None:
    cfg = load_config()
    queue = ApprovalQueue(cfg.review["queue_path"])
    approved = [p for p in queue.list_all() if p.get("status") == "approved" and not p.get("publish_at")]
    days = cfg.pipeline["weekly_days"]
    hour = cfg.pipeline["weekly_post_hour_utc"]
    for i, post in enumerate(approved):
        day = days[i % len(days)]
        slot = next_weekday_slot(day, hour)
        queue.update_status(post["post_id"], "scheduled", publish_at=slot)
        print(f"Scheduled {post['post_id']} for {slot}")


if __name__ == "__main__":
    main()
