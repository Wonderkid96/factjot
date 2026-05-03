"""Autonomous fact discovery from multiple sources with multi-check truth gates.

Sources:
    - r/Damnthatsinteresting (upvotes >= 10,000) -- public Reddit JSON API
    - r/morbidreality (upvotes >= 3,000) -- requires Reddit OAuth (NSFW-gated)
    - Wikipedia "List of unusual deaths" (per-century children, 1800 onwards)

Pipeline per candidate:
    1. Parse the claim from the title (TIL prefix stripped for r/todayilearned;
       raw title used directly for all other subreddits).
    2. Reject if we have seen this source ID before (local dedupe).
    3. Reject if the claim hash is already in `insta-brain/data/posted.jsonl`.
    4. Reject unless upvotes >= per-source minimum (community-vetted).
    5. Reject unless post age >= MIN_AGE_DAYS (gives correction reflex
       time to surface in comments).
    6. Reject if any of the top correction signals appear near the top of
       the comment thread ("myth", "false", "actually", "debunked", "wrong").
    7. Reject unless the source link is on a Tier 1 or Tier 2 trusted host.
    8. Fetch the source URL, extract main text, and reject unless the claim's
       most distinctive tokens (numbers, capitalised names) actually appear
       in the source body. Catches "real link, fabricated claim" attacks.

Wikipedia entries skip the Reddit-specific gates (upvotes, age, comments) but
still pass the domain trust check, the source-content cross-check, the boring
filter, and the already-posted dedup.

Anything that survives all checks is appended to:
    data/discovered_facts.jsonl

`src/research/rare_fact_bank.py::load_all_facts()` merges this feed with the
curated bank, so every publish run automatically picks up fresh material.
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

# ---------------------------------------------------------------------------
# Source definitions
# ---------------------------------------------------------------------------

SOURCES = [
    # All public Reddit JSON (no auth required) except r/morbidreality which is
    # NSFW-gated and uses OAuth via _reddit_oauth_token() when REDDIT_* secrets
    # are present. r/todayilearned removed: too mainstream.
    {"subreddit": "Damnthatsinteresting", "title_format": "direct", "min_upvotes": 10_000},
    {"subreddit": "interestingasfuck",    "title_format": "direct", "min_upvotes": 10_000},
    {"subreddit": "UnresolvedMysteries",  "title_format": "direct", "min_upvotes":  2_000},
    {"subreddit": "AskHistorians",        "title_format": "direct", "min_upvotes":  2_000},
    {"subreddit": "history",              "title_format": "direct", "min_upvotes":  2_000},
    # r/MorbidReality requires Reddit OAuth (NSFW-gated). Not worth the setup
    # friction - Wikipedia unusual deaths covers the same dark-history angle.
]

USER_AGENT   = "factjot-discoverer/1.0 (educational, contact @factjot)"
MIN_AGE_DAYS = 3            # Time for corrections to surface
MAX_CANDIDATES = 100        # Per subreddit per run
COMMENT_SCAN_TOP = 5        # Top-N comments to scan for correction signals

CORRECTION_SIGNALS = (
    "myth", "false", "incorrect", "wrong", "debunked", "actually,",
    "this is misleading", "not true", "this is wrong", "untrue",
    "this isn't true", "actually it's", "common misconception",
)

# Tier 1 + Tier 2 trusted publishers. Anything else is rejected at the source.
TRUSTED_DOMAINS = {
    # Tier 1: government and primary scientific
    "nasa.gov", "noaa.gov", "who.int", "nih.gov", "cdc.gov", "nhs.uk",
    "europa.eu", "esa.int", "usgs.gov", "fisheries.noaa.gov",
    # Tier 1: peer-reviewed research
    "nature.com", "science.org", "sciencedirect.com", "cell.com",
    "thelancet.com", "nejm.org", "pnas.org", "royalsociety.org",
    # Tier 1: research universities
    "ox.ac.uk", "cam.ac.uk", "harvard.edu", "mit.edu", "stanford.edu",
    "berkeley.edu", "yale.edu", "princeton.edu", "imperial.ac.uk",
    "ucl.ac.uk", "csiro.au",
    # Tier 1: museums and institutional
    "britannica.com", "nhm.ac.uk", "smithsonianmag.com", "si.edu",
    "museumoflondon.org.uk", "amnh.org", "rmg.co.uk",
    # Tier 1: Wikipedia (frequently cited by morbidreality; rights-cleared)
    "en.wikipedia.org", "wikipedia.org",
    # Tier 2: established journalism with editorial standards
    "bbc.com", "bbc.co.uk", "reuters.com", "apnews.com",
    "nationalgeographic.com", "scientificamerican.com",
    "newscientist.com", "theatlantic.com", "economist.com",
    # Curated science-popular
    "atlasobscura.com", "computerhistory.org", "oceana.org",
    "earthobservatory.nasa.gov", "voyager.jpl.nasa.gov",
}

TIL_TITLE_RE   = re.compile(r"^TIL[ -:,]*\s*(?:that\s+)?(.+?)$", re.IGNORECASE)
NUMBER_TOKEN_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\b")
PROPER_NOUN_RE  = re.compile(r"\b[A-Z][A-Za-z\-']{3,}\b")

# Wikipedia wikitext patterns
_WIKI_BULLET_RE  = re.compile(r"^\*+\s*(.+)$", re.MULTILINE)
_WIKI_MARKUP_RE  = re.compile(
    r"\[\[(?:[^\]|]+\|)?([^\]]+)\]\]"  # [[Link|Display]] or [[Display]]
    r"|\{\{[^}]+\}\}"                   # {{template}}
    r"|<ref[^/]*/>"                     # <ref ... />
    r"|<ref[^>]*>.*?</ref>"             # <ref>...</ref>
    r"|'{2,3}",                         # '' or '''
    re.DOTALL,
)
# Year prefix in wikitext bullets, e.g. "1986 -- ..." or "1986: ..."
_WIKI_YEAR_RE    = re.compile(r"^(\d{4})\s*[-:]+\s*")

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT})


# ---------------------------------------------------------------------------
# Claim normalisation
# ---------------------------------------------------------------------------

def _normalise_claim(raw: str) -> str:
    text = raw.strip().rstrip(".") + "."
    text = re.sub(r"\s+", " ", text)
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text


def _parse_til_title(title: str) -> str | None:
    """Strip the 'TIL (that)...' prefix. Returns None if the title doesn't match."""
    m = TIL_TITLE_RE.match(title)
    return _normalise_claim(m.group(1)) if m else None


def _parse_direct_title(title: str) -> str | None:
    """Use the raw title directly as the claim (no prefix to strip)."""
    clean = _normalise_claim(title)
    if len(clean) < 50 or len(clean) > 320:
        return None
    return clean


def _parse_title(title: str, title_format: str) -> str | None:
    """Dispatch to the correct title parser for the given source format."""
    if title_format == "til":
        return _parse_til_title(title)
    return _parse_direct_title(title)


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _hostname(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().lstrip(".")
    except Exception:
        return ""


def _is_trusted(url: str) -> bool:
    host = _hostname(url)
    return any(host == d or host.endswith("." + d) for d in TRUSTED_DOMAINS)


def _existing_source_ids() -> set[str]:
    """Return all reddit_id values already written to the output file."""
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


# ---------------------------------------------------------------------------
# Reddit fetchers (with optional OAuth for NSFW-gated subreddits)
# ---------------------------------------------------------------------------

import os

_REDDIT_TOKEN_CACHE: dict[str, str] = {}


def _reddit_oauth_token() -> str | None:
    """Return a cached Reddit OAuth bearer token, fetching if needed.

    Uses the script-app password grant. Required env vars:
        REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET,
        REDDIT_USERNAME,  REDDIT_PASSWORD

    Returns None if any credential is missing (caller should fall back
    to public JSON or skip the source). The token lives for ~1 hour and
    is cached in-process so a single discovery run only authenticates once.
    """
    if "token" in _REDDIT_TOKEN_CACHE:
        return _REDDIT_TOKEN_CACHE["token"]
    cid = os.getenv("REDDIT_CLIENT_ID")
    csec = os.getenv("REDDIT_CLIENT_SECRET")
    user = os.getenv("REDDIT_USERNAME")
    pw   = os.getenv("REDDIT_PASSWORD")
    if not all([cid, csec, user, pw]):
        return None
    try:
        resp = requests.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(cid, csec),
            data={"grant_type": "password", "username": user, "password": pw},
            headers={"User-Agent": USER_AGENT},
            timeout=15,
        )
    except requests.RequestException as exc:
        print(f"  Reddit OAuth request failed: {exc}")
        return None
    if not resp.ok:
        print(f"  Reddit OAuth failed: HTTP {resp.status_code}")
        return None
    token = resp.json().get("access_token")
    if token:
        _REDDIT_TOKEN_CACHE["token"] = token
    return token


def _fetch_top(subreddit: str, period: str = "month", limit: int = MAX_CANDIDATES,
               needs_oauth: bool = False) -> list[dict]:
    """Fetch top posts. Uses public JSON by default, OAuth for NSFW-gated subs."""
    if needs_oauth:
        token = _reddit_oauth_token()
        if not token:
            print(f"  Skipping r/{subreddit}: REDDIT_* OAuth credentials not set.")
            return []
        url = f"https://oauth.reddit.com/r/{subreddit}/top"
        try:
            resp = requests.get(
                url,
                params={"t": period, "limit": limit},
                headers={"Authorization": f"bearer {token}", "User-Agent": USER_AGENT},
                timeout=15,
            )
        except requests.RequestException:
            return []
    else:
        url = f"https://www.reddit.com/r/{subreddit}/top.json"
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


# ---------------------------------------------------------------------------
# Source content fetcher and cross-check
# ---------------------------------------------------------------------------

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
    html = re.sub(r"<style[^>]*>.*?</style>",  " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&\w+;",  " ", text)
    text = re.sub(r"\s+",    " ", text)
    return text.lower()


def _claim_supported_by_source(claim: str, source_text: str) -> bool:
    """Cheap source-content cross-check.

    Pull distinctive tokens from the claim (numbers + capitalised proper
    nouns >= 4 chars) and require that AT LEAST HALF appear in the source
    body. Catches "real link, fabricated content" attacks.
    """
    if not source_text:
        return False
    numbers = NUMBER_TOKEN_RE.findall(claim)
    propers = [w.lower() for w in PROPER_NOUN_RE.findall(claim) if len(w) >= 4]
    tokens  = list({*numbers, *propers})
    if not tokens:
        # No distinctive tokens to verify against; reject conservatively.
        return False
    hits = sum(1 for t in tokens if t.lower() in source_text)
    return hits >= max(1, len(tokens) // 2)


# ---------------------------------------------------------------------------
# Reject logger
# ---------------------------------------------------------------------------

def _record_reject(reason: str, post_id: str, claim: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "ts":       datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "reddit_id": post_id,
            "reason":   reason,
            "claim":    claim[:160],
        }, ensure_ascii=True) + "\n")


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

_VIRAL_SIGNALS = [
    "never", "no one", "nobody", "impossible", "always", "only",
    "first", "last", "largest", "smallest", "fastest", "oldest", "youngest",
    "killed", "survived", "destroyed", "discovered", "extinct", "banned",
    "illegal", "secret", "hidden", "forgotten", "accidental", "exploded",
    "radiation", "poison", "venom", "lethal", "deadly", "catastrophe",
    "billion", "trillion", "million years", "thousand years",
    "refused", "defied", "reversed", "collapsed", "betrayed", "executed",
    "escaped", "single-handedly", "never before", "never again",
]

# Specificity signals -- numbers and named persons make claims concrete and verifiable.
_NUMBER_RE = re.compile(r'\b\d[\d,]*(?:\.\d+)?(?:\s*(?:million|billion|trillion|thousand|percent|km|mph|years?|days?|metres?|meters?|tons?|kg|lbs?))?\b')
_PERSON_RE = re.compile(r'\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})+\b')

# Boring opener patterns -- generic "The X is a Y" structure with no specificity.
_BORING_OPENER_RE = re.compile(
    r'^(?:the |a |an )?[a-z]{2,30} (?:is|are|was|were) (?:a|an|the|one of the) [a-z]',
    re.IGNORECASE,
)


def _score_fact(claim: str, upvotes: int) -> int:
    """Assign quirky_score 0-3.  0 = reject (drop entirely), 1-3 = postable.

    Upvote base:
      10k-15k  -> 1  (carousel only when score >= 2 floor is met via bonus)
      15k-30k  -> 2  (carousel)
      30k+     -> 3  (reel-eligible)

    For Wikipedia entries, upvotes is passed as 0 so base lands at 1;
    viral signals can still push the score up to 2.

    Bonuses and penalties applied after base:
      +1  viral signal word present (capped at 3)
      -1  boring generic opener ("The X is a Y") with no specificity signals

    A score of 0 means the claim is textbook-level and will be rejected at
    discovery time -- it never enters discovered_facts.jsonl.
    """
    if upvotes >= 30_000:
        base = 3
    elif upvotes >= 15_000:
        base = 2
    else:
        base = 1

    claim_lower     = claim.lower()
    has_viral       = any(sig in claim_lower for sig in _VIRAL_SIGNALS)
    has_number      = bool(_NUMBER_RE.search(claim))
    has_person      = bool(_PERSON_RE.search(claim))
    has_specificity = has_number or has_person
    is_generic      = bool(_BORING_OPENER_RE.match(claim)) and not has_specificity

    score = base
    if has_viral:
        score = min(3, score + 1)
    if is_generic:
        score -= 1  # demote -- score can reach 0 (reject tier)

    return score


# ---------------------------------------------------------------------------
# Wikipedia unusual deaths scraper
# ---------------------------------------------------------------------------

# Wikipedia split the "List of unusual deaths" page into per-century children.
# The original combined page is now a stub redirect, so we fetch each child.
_WIKI_API_BASE = "https://en.wikipedia.org/w/api.php"
_WIKI_PAGES = [
    "List_of_unusual_deaths_in_the_19th_century",
    "List_of_unusual_deaths_in_the_20th_century",
    "List_of_unusual_deaths_in_the_21st_century",
    "List_of_unusual_deaths_(1800-1849)",
    "List_of_unusual_deaths_(1850-1899)",
    # Spontaneous combustion, unidentified sounds, etc.
    "List_of_unidentified_sounds",
    "List_of_reportedly_haunted_locations",
    # Mass-event lists rich with shock detail
    "List_of_industrial_disasters",
    "List_of_explosion_disasters",
]
_WIKI_SOURCE_URL_BASE = "https://en.wikipedia.org/wiki/"


def _strip_wiki_markup(text: str) -> str:
    """Remove wikitext markup, leaving plain readable text."""
    # Resolve [[Link|Display]] -> Display, [[Display]] -> Display
    text = re.sub(r"\[\[(?:[^\]|]+\|)?([^\]]+)\]\]", r"\1", text)
    # Remove {{templates}}
    text = re.sub(r"\{\{[^}]*\}\}", "", text)
    # Remove <ref> tags and their content
    text = re.sub(r"<ref[^/]*/?>", "", text)
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.DOTALL)
    # Remove bold/italic markers
    text = re.sub(r"'{2,3}", "", text)
    # Remove any leftover HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Tidy whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_wiki_death_table(wikitext: str, page_url: str) -> list[dict]:
    """Extract death-row Details cells from Wikipedia's table-formatted lists.

    Each row in these tables looks like:
        |-
        !Name of person
        |[[File:image.jpg|...]]
        |{{dts|3 January 1804}}
        |The actual details about the death go here...

    We split on `|-` row separators and extract the last cell of each row
    (which is consistently the Details column). Header rows are skipped
    because their cells are introduced with `!` instead of `|`.
    """
    out: list[dict] = []
    rows = re.split(r"\n\|-\s*\n", wikitext)
    for row in rows:
        # Each row has cells separated by `\n|`. Take the last `|`-prefixed cell.
        cells = re.split(r"\n\|", row)
        if len(cells) < 2:
            continue
        details_raw = cells[-1].strip()
        # Skip image-only or date-only cells that lack prose.
        if details_raw.startswith("[[File:") or details_raw.startswith("{{dts"):
            continue
        # Drop trailing pipes / closing braces.
        details_raw = details_raw.rstrip("|}").strip()
        claim = _strip_wiki_markup(details_raw)
        # Drop leading date if it survived markup removal.
        claim = re.sub(r"^\d{1,2}\s+\w+\s+\d{4}\s*", "", claim).strip()
        claim = _normalise_claim(claim)
        if len(claim) < 60 or len(claim) > 320:
            continue
        out.append({"claim": claim, "source_url": page_url})
    return out


def _fetch_wikipedia_unusual_deaths() -> list[dict]:
    """Fetch and parse Wikipedia's per-century "List of unusual deaths" pages.

    Wikipedia split the original combined article into per-century children
    that use wikitext tables, not bullet lists. Each row maps a person to
    a Details cell containing the unusual circumstances of death.

    Returns a list of dicts with keys:
        claim       -- cleaned plain-text Details cell
        source_url  -- canonical Wikipedia URL for the page it came from
    Entries shorter than 60 chars or longer than 320 chars are skipped.
    """
    results: list[dict] = []
    for page in _WIKI_PAGES:
        page_url = _WIKI_SOURCE_URL_BASE + page
        try:
            resp = session.get(
                _WIKI_API_BASE,
                params={
                    "action":   "parse",
                    "page":     page,
                    "prop":     "wikitext",
                    "format":   "json",
                },
                timeout=20,
            )
        except requests.RequestException:
            print(f"  Wikipedia fetch failed for {page} (network error).")
            continue
        if not resp.ok:
            print(f"  Wikipedia fetch failed for {page}: HTTP {resp.status_code}.")
            continue

        try:
            data = resp.json()
        except Exception:
            continue

        wikitext = data.get("parse", {}).get("wikitext", {}).get("*", "")
        if not wikitext:
            continue

        page_results = _parse_wiki_death_table(wikitext, page_url)
        results.extend(page_results)
        print(f"  {page}: {len(page_results)} entries")
        time.sleep(0.5)  # Polite to Wikipedia API

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    seen   = _existing_source_ids()
    posted = brain.posted_hashes()

    now           = datetime.now(timezone.utc).timestamp()
    age_threshold = MIN_AGE_DAYS * 86400

    # Shared counters across all sources.
    counters = {
        "appended": 0, "dup": 0, "low_upvotes": 0, "young": 0,
        "correction": 0, "untrusted": 0, "unsupported": 0,
        "malformed": 0, "already_posted": 0, "boring": 0,
    }

    with OUT_PATH.open("a", encoding="utf-8") as out_fh:

        # ------------------------------------------------------------------
        # Reddit sources
        # ------------------------------------------------------------------
        for source in SOURCES:
            subreddit    = source["subreddit"]
            title_format = source["title_format"]
            min_upvotes  = source["min_upvotes"]
            needs_oauth  = source.get("needs_oauth", False)
            source_kind  = f"r/{subreddit}"

            auth_label = " [OAuth]" if needs_oauth else ""
            print(f"\nFetching {source_kind}{auth_label} (min upvotes: {min_upvotes:,}) ...")
            posts = _fetch_top(subreddit, period="month", limit=MAX_CANDIDATES,
                               needs_oauth=needs_oauth)
            if not posts:
                print(f"  No posts fetched for {source_kind} (rate-limit or network issue).")
                continue

            for post in posts:
                rid           = post.get("id", "")
                title         = post.get("title", "")
                link          = post.get("url", "")
                ups           = int(post.get("ups", 0))
                created_utc   = float(post.get("created_utc", 0))
                permalink     = post.get("permalink", "")

                if not rid or rid in seen:
                    counters["dup"] += 1
                    continue

                claim = _parse_title(title, title_format)
                if not claim or len(claim) < 50 or len(claim) > 320:
                    counters["malformed"] += 1
                    continue

                # Gate 0: already posted under @factjot
                if claim_hash(claim) in posted:
                    counters["already_posted"] += 1
                    _record_reject("already_posted", rid, claim)
                    continue

                # Gate 1: minimum upvotes (per-source threshold)
                if ups < min_upvotes:
                    counters["low_upvotes"] += 1
                    _record_reject(f"low_upvotes({ups})", rid, claim)
                    continue

                # Gate 2: post age
                if (now - created_utc) < age_threshold:
                    counters["young"] += 1
                    _record_reject("young_post", rid, claim)
                    continue

                # Gate 3: trusted source domain
                if not _is_trusted(link):
                    counters["untrusted"] += 1
                    _record_reject(f"untrusted({_hostname(link)})", rid, claim)
                    continue

                # Gate 4: top-comment correction signals
                comments = _fetch_top_comments(permalink) if permalink else []
                if _has_correction_signal(comments):
                    counters["correction"] += 1
                    _record_reject("comment_correction", rid, claim)
                    continue
                time.sleep(0.5)  # Be polite to Reddit's API

                # Gate 5: source-content cross-check
                source_text = _fetch_source_text(link)
                if not _claim_supported_by_source(claim, source_text):
                    counters["unsupported"] += 1
                    _record_reject("source_unsupported", rid, claim)
                    continue

                topic = route_to_topic(claim)
                score = _score_fact(claim, ups)
                if score == 0:
                    counters["boring"] += 1
                    _record_reject("boring_generic", rid, claim)
                    continue

                seen.add(rid)  # Mark as seen so dedup works within this run
                row = {
                    "topic":        topic,
                    "claim":        claim,
                    "sources":      [link],
                    "image_hint":   suggest_image_hint(claim, topic),
                    "quirky_score": score,
                    "discovered_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "source_kind":  source_kind,
                    "reddit_id":    rid,
                    "upvotes":      ups,
                    "verified_by":  "auto:multi_check",
                }
                out_fh.write(json.dumps(row, ensure_ascii=True) + "\n")
                counters["appended"] += 1

        # ------------------------------------------------------------------
        # Wikipedia unusual deaths
        # ------------------------------------------------------------------
        print("\nFetching Wikipedia: List of unusual deaths ...")
        wiki_entries = _fetch_wikipedia_unusual_deaths()
        print(f"  Parsed {len(wiki_entries)} candidate entries.")

        # The Wikipedia article itself is the source; it is trusted by domain.
        # Skip upvotes, age, and comment gates -- none apply to Wikipedia.
        for entry in wiki_entries:
            claim      = entry["claim"]
            source_url = entry["source_url"]

            # Synthetic ID so we can dedup across runs.
            synthetic_id = "wiki:ud:" + str(abs(hash(claim)) % (10 ** 12))

            if synthetic_id in seen:
                counters["dup"] += 1
                continue

            # Gate 0: already posted under @factjot
            if claim_hash(claim) in posted:
                counters["already_posted"] += 1
                _record_reject("already_posted", synthetic_id, claim)
                continue

            # Gate 1 (adapted): domain trust check (Wikipedia is already in TRUSTED_DOMAINS)
            if not _is_trusted(source_url):
                counters["untrusted"] += 1
                _record_reject(f"untrusted({_hostname(source_url)})", synthetic_id, claim)
                continue

            # Gate 2: source-content cross-check against the full Wikipedia article.
            source_text = _fetch_source_text(source_url)
            if not _claim_supported_by_source(claim, source_text):
                counters["unsupported"] += 1
                _record_reject("source_unsupported", synthetic_id, claim)
                continue

            topic = route_to_topic(claim)
            # Wikipedia entries have no upvote signal; pass 0 so base=1,
            # viral signals can still push to 2.
            score = _score_fact(claim, upvotes=0)
            if score == 0:
                counters["boring"] += 1
                _record_reject("boring_generic", synthetic_id, claim)
                continue

            seen.add(synthetic_id)
            row = {
                "topic":        topic,
                "claim":        claim,
                "sources":      [source_url],
                "image_hint":   suggest_image_hint(claim, topic),
                "quirky_score": score,
                "discovered_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "source_kind":  "wikipedia:unusual_deaths",
                "reddit_id":    synthetic_id,  # kept for dedup compatibility with existing schema
                "upvotes":      0,
                "verified_by":  "auto:multi_check",
            }
            out_fh.write(json.dumps(row, ensure_ascii=True) + "\n")
            counters["appended"] += 1

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\nDiscovery summary (all sources):")
    for k, v in counters.items():
        print(f"  {k:<18} {v}")
    print(f"  output:           {OUT_PATH}")
    print(f"  reject log:       {LOG_PATH}")

    if counters["appended"] > 0:
        source_labels = [f"r/{s['subreddit']}" for s in SOURCES] + ["wikipedia:unusual_deaths"]
        brain.append_log(
            f"discovery: appended {counters['appended']} fresh facts from "
            f"{', '.join(source_labels)} "
            f"(rejected {sum(v for k, v in counters.items() if k != 'appended')})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
