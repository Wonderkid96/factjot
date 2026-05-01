from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.review.approval_queue import ApprovalQueue


def main() -> None:
    parser = argparse.ArgumentParser(description="Review and schedule queue items.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list")
    approve = sub.add_parser("approve")
    approve.add_argument("--post-id", required=True)

    reject = sub.add_parser("reject")
    reject.add_argument("--post-id", required=True)

    schedule = sub.add_parser("schedule")
    schedule.add_argument("--post-id", required=True)
    schedule.add_argument("--publish-at", required=True, help="ISO UTC time, ex: 2026-05-06T10:00:00Z")

    args = parser.parse_args()
    queue = ApprovalQueue()

    if args.command == "list":
        print(json.dumps(queue.list_all(), indent=2))
        return
    if args.command == "approve":
        print("approved" if queue.update_status(args.post_id, "approved") else "post not found")
        return
    if args.command == "reject":
        print("rejected" if queue.update_status(args.post_id, "rejected") else "post not found")
        return
    if args.command == "schedule":
        ok = queue.update_status(args.post_id, "scheduled", publish_at=args.publish_at)
        print("scheduled" if ok else "post not found")


if __name__ == "__main__":
    main()
