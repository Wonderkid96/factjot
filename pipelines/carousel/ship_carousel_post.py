"""Canonical carousel entrypoint for autonomous and manual runs.

This wraps the legacy manual pipeline module so callers can use a
format-agnostic path that reflects current production usage.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))
from pipelines.manual.ship_manual_post import main


if __name__ == "__main__":
    sys.exit(main())
