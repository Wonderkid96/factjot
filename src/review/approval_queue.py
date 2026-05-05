from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.core.models import CarouselPost


class ApprovalQueue:
    def __init__(self, queue_path: str | None = None) -> None:
        from src.core.paths import APPROVAL_QUEUE
        self.queue_path = Path(queue_path) if queue_path else APPROVAL_QUEUE
        self.queue_path.parent.mkdir(parents=True, exist_ok=True)
        self.queue_path.touch(exist_ok=True)

    def enqueue(self, post: CarouselPost) -> None:
        with self.queue_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(post.to_dict(), ensure_ascii=True) + "\n")

    def list_all(self) -> list[dict]:
        rows: list[dict] = []
        with self.queue_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows

    def update_status(self, post_id: str, status: str, publish_at: str | None = None) -> bool:
        rows = self.list_all()
        changed = False
        for row in rows:
            if row["post_id"] == post_id:
                row["status"] = status
                if publish_at:
                    row["publish_at"] = publish_at
                row["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                changed = True
        if changed:
            with self.queue_path.open("w", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(json.dumps(row, ensure_ascii=True) + "\n")
        return changed

    def due_scheduled_posts(self, now_iso: str) -> list[dict]:
        due = []
        for row in self.list_all():
            publish_at = row.get("publish_at")
            if row.get("status") == "scheduled" and publish_at and publish_at <= now_iso:
                due.append(row)
        return due
