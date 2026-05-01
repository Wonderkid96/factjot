"""Autonomous fact discovery from r/todayilearned with multi-check truth gates.

Pipeline per candidate post:
    1. Parse the claim out of the TIL title.
    2. Reject if we've seen this Reddit ID before (local dedupe).
    3. Reject if the claim hash is already in `insta-brain/data/posted.jsonl`.
    4. Reject unless upvotes >= MIN_UPVOTES (community-vetted).
    5. Reject unless post age >= MIN_AGE_DAYS (gives the correction reflex
       time to surface in comments).
    6. Reject if any of the top correction signals appear near the top of
       the comment thread ("myth", "false", "actually", "debunked", "wrong").
    7. Reject unless the source link is on a Tier 1 or Tier 2 trusted host.
    8. Fetch the source URL, extract main text, and reject unless the claim's
       most distinctive tokens (numbers, capitalised names) actually appear
       in the source body. Catches "real link, fabricated claim" attacks.

Anything that survives all eight checks is appended to:
    data/discovered_facts.jsonl

`src/research/rare_fact_bank.py::load_all_facts()` merges this feed with the
curated bank, so every publish run automatically picks up fresh material.

Run nightly via launchd (see launchd/com.tjcreate.factjot.discover.plist).
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.brain import brain, claim_hash
from src.research.fact_topic_router import route_to_topic, suggest_image_hint

from src.core.paths import DISCOVERED_FACTS as OUT_PATH, DISCOVERY_LOG as LOG_PATH
SUBREDDIT = "todayilearned"
USER_AGENT = "factjot-discoverer/1.0 (educational, contact @factjot)"

MIN_UPVOTES = 5000          # Community vetted
MIN_AGE_DAYS = 3            # Time for corrections to surface
MAX_CANDIDATES = 100        # Per run
COMMENT_SCAN_TOP = 5        # Top-N comments to scan for correction signals
CORRECTION_SIGNALS = (
    "myth", "false", "incorrect", "wrong", "debunked", "actually,",
    "this is misleading", "not true", "this is wrong", "untrue",
    "this isn't true", "actually it's", "common misconception",
)

# Tier 1 + Tier 2 trusted publishers. Anything else is rejected at the source.
TRUSTED_DOMAINS = {
    # Tier 1: government & primary scientific
    "nasa.gov", "noaa.gov", "who.int", "nih.gov", "cdc.gov", "nhs.uk",
    "europa.eu", "esa.int", "usgs.gov", "fisheries.noaa.gov",
    # Tier 1: peer-reviewed research
    "nature.com", "science.org", "sciencedirect.com", "cell.com",
    "thelancet.com", "nejm.org", "pnas.org", "royalsociety.org",
    # Tier 1: research universities
    "ox.ac.uk", "cam.ac.uk", "harvard.edu", "mit.edu", "stanford.edu",
    "berkeley.edu", "yale.edu", "princeton.edu", "imperial.ac.uk",
    "ucl.ac.uk", "csiro.au",
    # Tier 1: museums & institutional
    "britannica.com", "nhm.ac.uk", "smithsonianmag.com", "si.edu",
    "museumoflondon.org.uk", "amnh.org", "rmg.co.uk",
    # Tier 2: established journalism with editorial standards
    "bbc.com", "bbc.co.uk", "reuters.com", "apnews.com",
    "nationalgeographic.com", "scientificamerican.com",
    "newscientist.com", "theatlantic.com", "economist.com",
    # Curated science-popular
    "atlasobscura.com", "computerhistory.org", "oceana.org",
    "earthobservatory.nasa.gov", "voyager.jpl.nasa.gov",
}

TIL_TITLE_RE = re.compile(r"^TIL[ -:,]*\s*(?:that\s+)?(.+?)$", re.IGNORECASE)
NUMBER_TOKEN_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\b")
PROPER_NOUN_RE = re.compile(r"\b[A-Z][A-Za-z\-']{3,}\b")

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT})


def _normalise_claim(raw: str) -> str:
    text = raw.strip().rstrip(".") + "."
    text = re.sub(r"\s+", " ", text)
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text


def _hostname(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().lstrip(".")
    except Exception:
        return ""


def _is_trusted(url: str) -> bool:
    host = _hostname(url)
    return any(host == d or host.endswith("." + d) for d in TRUSTED_DOMAINS)


def _existing_reddit_ids() -> set[str]:
    if not OUT_PATH.exists():
        return set()
    out: set[str] = set()
    with OUT_PATH.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            rid = row.get("reddit_id")
            if rid:
                out.add(rid)
    return out


def _fetch_top(period: str = "month", limit: int = MAX_CANDIDATES) -> list[dict]:
    url = f"https://www.reddit.com/r/{SUBREDDIT}/top.json"
    resp = session.get(url, params={"t": period, "limit": limit}, timeout=15)
    if not resp.ok:
        return []
    return [c["data"] for c in resp.json().get("data", {}).get("children", [])]


def _fetch_top_comments(permalink: str) -> list[str]:
    """Return the bodies of the top N comments on a Reddit post."""
    url = f"https://www.reddit.com{permalink}.json?limit={COMMENT_SCAN_TOP}&depth=1"
    try:
        resp = session.get(url, timeout=15)
    except requests.RequestException:
        return []
    if not resp.ok:
        return []
    try:
        listing = resp.json()
    except Exception:
        return []
    if not isinstance(listing, list) or len(listing) < 2:
        return []
    children = listing[1].get("data", {}).get("children", [])
    bodies: list[str] = []
    for c in children[:COMMENT_SCAN_TOP]:
        body = c.get("data", {}).get("body", "")
        if body:
            bodies.append(body.lower())
    return bodies


def _has_correction_signal(comments: list[str]) -> bool:
    joined = "\n".join(comments).lower()
    return any(sig in joined for sig in CORRECTION_SIGNALS)


def _fetch_source_text(url: str, max_bytes: int = 200_000) -> str:
    """Return cleaned-up source HTML text. Best-effort, paywall-tolerant."""
    try:
        resp = session.get(url, timeout=12, allow_redirects=True)
    except requests.RequestException:
        return ""
    if not resp.ok:
        return ""
    html = resp.text[:max_bytes]
    # Strip script/style blocks then HTML tags. Crude but stable.
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&\w+;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.lower()


def _claim_supported_by_source(claim: str, source_text: str) -> bool:
    """Cheap source-content cross-check.

    Pull distinctive tokens from the claim (numbers + capitalised proper
    nouns ≥ 4 chars) and require that AT LEAST HALF of them appear in
    the source body. Catches "real link, fabricated content" attacks.
    """
    if not source_text:
        return False
    numbers = NUMBER_TOKEN_RE.findall(claim)
    propers = [w.lower() for w in PROPER_NOUN_RE.findall(claim) if len(w) >= 4]
    tokens = list({*numbers, *propers})
    if not tokens:
        # No distinctive tokens to verify against; reject conservatively.
        return False
    hits = sum(1 for t in tokens if t.lower() in source_text)
    # Require at least half the tokens to appear, minimum 1.
    return hits >= max(1, len(tokens) // 2)


def _record_reject(reason: str, post_id: str, claim: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "reddit_id": post_id, "reason": reason, "claim": claim[:160],
        }, ensure_ascii=True) + "\n")


def main() -> int:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    seen = _existing_reddit_ids()
    posted = brain.posted_hashes()

    posts = _fetch_top(period="month", limit=MAX_CANDIDATES)
    if not posts:
        print("No posts fetched (Reddit rate-limit or network).")
        return 1

    counters = {"appended": 0, "dup": 0, "low_upvotes": 0, "young": 0,
                "correction": 0, "untrusted": 0, "unsupported": 0,
                "malformed": 0, "already_posted": 0}

    now = datetime.now(timezone.utc).timestamp()
    age_threshold = MIN_AGE_DAYS * 86400

    with OUT_PATH.open("a", encoding="utf-8") as out_fh:
        for post in posts:
            rid = post.get("id", "")
            title = post.get("title", "")
            link = post.get("url", "")
            ups = int(post.get("ups", 0))
            created_utc = float(post.get("created_utc", 0))
            permalink = post.get("permalink", "")

            if not rid or rid in seen:
                counters["dup"] += 1
                continue

            m = TIL_TITLE_RE.match(title)
            if not m:
                counters["malformed"] += 1
                continue
            claim = _normalise_claim(m.group(1))
            if len(claim) < 50 or len(claim) > 320:
                counters["malformed"] += 1
                continue

            # Rule 01 — already posted under @factjot
            if claim_hash(claim) in posted:
                counters["already_posted"] += 1
                _record_reject("already_posted", rid, claim)
                continue

            # Quality gate 1: upvotes
            if ups < MIN_UPVOTES:
                counters["low_upvotes"] += 1
                _record_reject(f"low_upvotes({ups})", rid, claim)
                continue

            # Quality gate 2: age
            if (now - created_utc) < age_threshold:
                counters["young"] += 1
                _record_reject("young_post", rid, claim)
                continue

            # Quality gate 3: trusted source domain
            if not _is_trusted(link):
                counters["untrusted"] += 1
                _record_reject(f"untrusted({_hostname(link)})", rid, claim)
                continue

            # Quality gate 4: top-comment correction signals
            comments = _fetch_top_comments(permalink) if permalink else []
            if _has_correction_signal(comments):
                counters["correction"] += 1
                _record_reject("comment_correction", rid, claim)
                continue
            time.sleep(0.5)  # Be polite to Reddit's API

            # Quality gate 5: source-content cross-check
            source_text = _fetch_source_text(link)
            if not _claim_supported_by_source(claim, source_text):
                counters["unsupported"] += 1
                _record_reject("source_unsupported", rid, claim)
                continue

            topic = route_to_topic(claim)
            row = {
                "topic": topic,
                "claim": claim,
                "sources": [link],
                "image_hint": suggest_image_hint(claim, topic),
                "discovered_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "source_kind": f"r/{SUBREDDIT}",
                "reddit_id": rid,
                "upvotes": ups,
                "verified_by": "auto:multi_check",
            }
            out_fh.write(json.dumps(row, ensure_ascii=True) + "\n")
            counters["appended"] += 1

    print(f"r/{SUBREDDIT} discovery summary:")
    for k, v in counters.items():
        print(f"  {k:<18} {v}")
    print(f"  output:           {OUT_PATH}")
    print(f"  reject log:       {LOG_PATH}")
    if counters["appended"] > 0:
        brain.append_log(
            f"discovery: appended {counters['appended']} fresh facts from r/{SUBREDDIT} "
            f"(rejected {sum(v for k,v in counters.items() if k != 'appended')})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
