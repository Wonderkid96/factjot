#!/usr/bin/env python3
"""Lightweight Guardian RSS watcher -- pure Python stdlib, no dependencies.

Checks multiple Guardian RSS feeds for significant new stories.
Prints the article URL if something post-worthy is found, exits 0.
Prints nothing and exits 1 if nothing significant is found.

Significance criteria (no AI needed):
  - Published within the last MAX_AGE_HOURS
  - Not already in data/ledgers/news_posts.jsonl
  - Headline contains at least one urgency signal OR a notable number
  - Not from a comment/opinion/lifestyle section

Called by news-watcher.yml which then triggers news-carousel.yml.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

# ---- Config ----

MAX_AGE_HOURS = 3

# Feeds to monitor, in priority order
FEEDS = [
    ("world",       "https://www.theguardian.com/world/rss"),
    ("technology",  "https://www.theguardian.com/technology/rss"),
    ("science",     "https://www.theguardian.com/science/rss"),
    ("environment", "https://www.theguardian.com/environment/rss"),
    ("uk-news",     "https://www.theguardian.com/uk-news/rss"),
    ("society",     "https://www.theguardian.com/society/rss"),
]

# Words in a headline that suggest something newsworthy happened
URGENCY_WORDS = frozenset({
    "breaks", "breaking", "kills", "killed", "dead", "deaths", "crash",
    "explosion", "explodes", "launches", "announces", "collapses", "resigns",
    "arrested", "banned", "record", "historic", "first", "breakthrough",
    "crisis", "emergency", "attack", "fire", "flood", "earthquake",
    "warns", "threatens", "condemns", "sanctions", "cuts", "raises",
    "discovers", "discovery", "finds", "confirms", "reveals", "shock",
})

# URL fragments that indicate opinion/lifestyle -- skip these
SKIP_SECTIONS = (
    "/commentisfree/", "/lifeandstyle/", "/sport/", "/fashion/",
    "/culture/", "/food/", "/travel/", "/books/", "/music/",
    "/television/", "/games/", "/crosswords/",
)


def _load_posted_urls() -> set[str]:
    ledger = Path("data/ledgers/news_posts.jsonl")
    if not ledger.exists():
        return set()
    urls: set[str] = set()
    for line in ledger.read_text(encoding="utf-8").splitlines():
        try:
            urls.add(json.loads(line)["url"])
        except Exception:
            pass
    return urls


def _is_significant(title: str, url: str) -> bool:
    """Return True if this headline is likely post-worthy."""
    # Skip opinion / lifestyle
    for skip in SKIP_SECTIONS:
        if skip in url:
            return False

    # Check for urgency signals in headline words
    words = set(re.findall(r"[a-z]+", title.lower()))
    has_urgency = bool(words & URGENCY_WORDS)

    # A number in the headline (statistics, death tolls, financial figures)
    has_number = bool(re.search(r"\b\d{2,}\b", title))

    # Proper nouns suggest a named event/person (multiple capitalised words)
    proper_nouns = re.findall(r"\b[A-Z][a-z]{2,}\b", title)
    has_named_subject = len(proper_nouns) >= 2

    return (has_urgency or has_number) and has_named_subject


def main() -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)
    posted = _load_posted_urls()

    for section_name, feed_url in FEEDS:
        try:
            req = urllib.request.Request(
                feed_url,
                headers={"User-Agent": "factjot-news-watcher/1.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                root = ET.fromstring(r.read())
        except Exception as exc:
            print(f"[watcher] RSS fetch failed ({section_name}): {exc}", file=sys.stderr)
            continue

        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link  = (item.findtext("link") or "").strip()
            pub   = item.findtext("pubDate") or ""

            if not link or not title:
                continue
            if link in posted:
                continue

            # Freshness check
            try:
                pub_dt = parsedate_to_datetime(pub).astimezone(timezone.utc)
                if pub_dt < cutoff:
                    continue
            except Exception:
                continue

            # Significance check
            if _is_significant(title, link):
                print(link)   # sole stdout output -- caller reads this
                return 0

    return 1   # nothing found


if __name__ == "__main__":
    sys.exit(main())
