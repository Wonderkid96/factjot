from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class PerformanceTracker:
    def __init__(self, metrics_path: str | None = None) -> None:
        from src.core.paths import METRICS_DB
        self.metrics_path = Path(metrics_path) if metrics_path else METRICS_DB
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.metrics_path.exists():
            self.metrics_path.write_text("[]", encoding="utf-8")

    def track_event(self, event_type: str, payload: dict) -> None:
        rows = json.loads(self.metrics_path.read_text(encoding="utf-8"))
        rows.append(
            {
                "event_type": event_type,
                "payload": payload,
                "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        )
        self.metrics_path.write_text(json.dumps(rows, indent=2, ensure_ascii=True), encoding="utf-8")
