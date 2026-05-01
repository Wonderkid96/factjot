"""Alerting hook used across the publish/discover/refresh chain.

Every alert is appended to `data/alerts.jsonl` so `scripts/status.py` can
surface recent issues. Keeps the data centralised and easy to tail in a
dashboard or grep manually.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.core.paths import ALERTS as ALERTS_PATH


class AlertingService:
    def __init__(self) -> None:
        self.logger = logging.getLogger("alerting")

    def send_alert(self, title: str, details: dict) -> None:
        self.logger.error("ALERT | %s | %s", title, details)
        ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "kind": title,
            "detail": details,
        }
        try:
            with ALERTS_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=True) + "\n")
        except Exception as exc:
            # Alerting must never crash the caller. Worst case: log only.
            self.logger.error("alerting persist failed: %s", exc)
