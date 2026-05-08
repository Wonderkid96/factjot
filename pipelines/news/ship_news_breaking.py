"""Canonical entrypoint for watcher-triggered breaking news posts.

This wrapper preserves current behaviour in ship_news_post while giving
workflows a dedicated, unambiguous executable for breaking news.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))
from pipelines.news.ship_news_post import main  # noqa: E402


if __name__ == "__main__":
    sys.exit(main())
