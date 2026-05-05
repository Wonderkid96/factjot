"""Lightweight heartbeat. Writes a single line to `data/heartbeat.log` every
time it runs so we can verify the scheduler is actually firing the chain.

Can be triggered manually or added as a step in a GitHub Actions workflow.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from src.core.paths import HEARTBEAT_LOG as HEARTBEAT_PATH


def main() -> int:
    HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}  alive\n"
    with HEARTBEAT_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line)
    print(line.strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
