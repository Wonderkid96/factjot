#!/usr/bin/env python3
"""Automated reel fact discovery from shock/morbid Reddit sources.

Pulls from NSFW-gated and public subreddits focused on morbid curiosity,
shocking history, and genuinely startling facts. For each qualifying post,
Claude generates a reel_script (70-120 words) and reel_title (3-7 words)
and writes the result to a staging file for human review before it enters
rare_fact_bank.py.

Sources (all require NSFW setting or high engagement threshold):
  r/morbidreality      -- NSFW, requires Reddit OAuth
  r/Glitch_in_the_Matrix
  r/UnresolvedMysteries
  r/interestingasfuck
  r/Damnthatsinteresting
  r/history
  r/todayilearned

Output: data/ledgers/reel_discovery_staging.jsonl
  Each entry is a candidate reel fact -- review, then copy into rare_fact_bank.py.

Usage:
    python3 pipelines/reel/discover_reel_facts.py
    python3 pipelines/reel/discover_reel_facts.py --limit 20
    python3 pipelines/reel/discover_reel_facts.py --dry-run   # preview, no file writes
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from anthropic import Anthropic

# ------------------------------------------------------------------ #
# Config
# ------------------------------------------------------------------ #

USER_AGENT   = "factjot-reel-discoverer/1.0 (educational, contact @factjot)"
STAGING_FILE = Path("data/ledgers/reel_discovery_staging.jsonl")
MIN_AGE_DAYS = 2       # Allow corrections to surface before we use a fact
MAX_PER_SUB  = 50      # Posts to scan per subreddit
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

# Subreddits in priority order. nsfw=True requires Reddit OAuth credentials.
SOURCES = [
    {"subreddit": "morbidreality",         "nsfw": True,  "min_upvotes": 1_000},
    {"subreddit": "interestingasfuck",     "nsfw": False, "min_upvotes": 15_000},
    {"subreddit": "Damnthatsinteresting",  "nsfw": False, "min_upvotes": 15_000},
    {"subreddit": "UnresolvedMysteries",   "nsfw": False, "min_upvotes": 2_000},
    {"subreddit": "Glitch_in_the_Matrix",  "nsfw": False, "min_upvotes": 3_000},
    {"subreddit": "todayilearned",         "nsfw": False, "min_upvotes": 20_000},
    {"subreddit": "history",               "nsfw": False, "min_upvotes": 5_000},
]

# Topics to map posts into (for image_hint and video search)
TOPIC_KEYWORDS = {
    "history":   {"war", "battle", "century", "ancient", "empire", "soldier", "king", "queen", "dynasty", "revolution"},
    "science":   {"discovery", "research", "experiment", "laboratory", "physicist", "biologist", "chemical"},
    "space":     {"nasa", "planet", "orbit", "asteroid", "galaxy", "cosmos", "astronaut", "telescope"},
    "ocean":     {"ocean", "deep sea", "shark", "whale", "submarine", "coral", "fish", "marine"},
    "biology":   {"animal", "creature", "species", "evolution", "dna", "cell", "parasite", "insect"},
    "earth":     {"earthquake", "volcano", "climate", "geology", "mineral", "fossil", "erosion"},
    "technology":{"computer", "algorithm", "internet", "silicon", "engineer", "code", "robot"},
}

# Hard blocklist -- posts containing these are rejected outright
BLOCK_TERMS = {
    "suicide", "self-harm", "child abuse", "paedophile", "rape", "sexual assault",
    "gore", "beheading", "execution video", "nsfw image",
}

_REDDIT_TOKEN_CACHE: dict[str, str] = {}


# ------------------------------------------------------------------ #
# Reddit auth
# ------------------------------------------------------------------ #

def _oauth_token() -> str | None:
    if "token" in _REDDIT_TOKEN_CACHE:
        return _REDDIT_TOKEN_CACHE["token"]
    cid  = os.getenv("REDDIT_CLIENT_ID", "").strip()
    csec = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
    user = os.getenv("REDDIT_USERNAME", "").strip()
    pw   = os.getenv("REDDIT_PASSWORD", "").strip()
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
        resp.raise_for_status()
        token = resp.json().get("access_token")
        if token:
            _REDDIT_TOKEN_CACHE["token"] = token
        return token
    except Exception as exc:
        print(f"  Reddit OAuth failed: {exc}")
        return None


def _fetch_posts(subreddit: str, nsfw: bool, limit: int) -> list[dict]:
    if nsfw:
        token = _oauth_token()
        if not token:
            print(f"  Skipping r/{subreddit}: no Reddit OAuth credentials (REDDIT_CLIENT_ID etc.)")
            return []
        url     = f"https://oauth.reddit.com/r/{subreddit}/top"
        headers = {"Authorization": f"bearer {token}", "User-Agent": USER_AGENT}
    else:
        url     = f"https://www.reddit.com/r/{subreddit}/top.json"
        headers = {"User-Agent": USER_AGENT}

    try:
        resp = requests.get(url, params={"t": "month", "limit": limit},
                            headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()["data"]["children"]
    except Exception as exc:
        print(f"  r/{subreddit} fetch failed: {exc}")
        return []


# ------------------------------------------------------------------ #
# Filtering
# ------------------------------------------------------------------ #

def _already_staged(title: str) -> bool:
    if not STAGING_FILE.exists():
        return False
    t = title.lower().strip()
    for line in STAGING_FILE.read_text().splitlines():
        try:
            if json.loads(line).get("reddit_title", "").lower().strip() == t:
                return True
        except Exception:
            pass
    return False


def _already_in_bank(title: str) -> bool:
    bank = Path("src/research/rare_fact_bank.py").read_text()
    return title.lower()[:40] in bank.lower()


def _classify_topic(text: str) -> str:
    text_lower = text.lower()
    scores: dict[str, int] = {}
    for topic, keywords in TOPIC_KEYWORDS.items():
        scores[topic] = sum(1 for kw in keywords if kw in text_lower)
    return max(scores, key=lambda t: scores[t]) if any(scores.values()) else "history"


def _is_blocked(text: str) -> bool:
    text_lower = text.lower()
    return any(term in text_lower for term in BLOCK_TERMS)


def _age_days(created_utc: float) -> float:
    return (time.time() - created_utc) / 86400


# ------------------------------------------------------------------ #
# Claude script generation
# ------------------------------------------------------------------ #

def _generate_reel(title: str, body: str, topic: str, api_key: str, model: str) -> dict | None:
    """Ask Claude to write a reel_script and reel_title for this fact."""
    context = f"Title: {title}"
    if body and len(body) > 20:
        context += f"\n\nContext: {body[:800]}"

    prompt = f"""
You are writing a script for a 30-45 second Instagram Reel for @factjot.

The reel is based on this Reddit post:
{context}

Write:
1. A reel_title: 3-7 words. Mysterious, intriguing, withholds the punchline.
   Like a documentary episode name. NOT a full sentence. NOT the fact itself.
   Examples: "The Man Who Couldn't Die", "The Sound That Kills", "Nine Brains, One Body"

2. A reel_script: 75-110 words of spoken narration. Rules:
   - Start with the most shocking or surprising element
   - Build tension or mystery through the script
   - Present tense where possible
   - No filler, no "today we're looking at", no intro waffle
   - End with a line that lands the emotional punch
   - Factually accurate -- only what the source confirms
   - British spelling

Output JSON only:
{{"reel_title": "...", "reel_script": "..."}}
""".strip()

    try:
        client = Anthropic(api_key=api_key)
        res = client.messages.create(
            model=model, max_tokens=600, temperature=0.6,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = res.content[0].text.strip()
        # Parse JSON
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\{[\s\S]+\}", raw)
            data = json.loads(m.group()) if m else {}

        title_out  = (data.get("reel_title") or "").strip()
        script_out = (data.get("reel_script") or "").strip()

        if not title_out or not script_out or len(script_out.split()) < 60:
            return None

        return {
            "reel_title":  title_out,
            "reel_script": script_out,
            "tokens": res.usage.input_tokens + res.usage.output_tokens,
        }
    except Exception as exc:
        print(f"    Claude error: {exc}")
        return None


# ------------------------------------------------------------------ #
# Main
# ------------------------------------------------------------------ #

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit",   type=int, default=10,  help="Max new facts to stage per run")
    parser.add_argument("--model",   default=DEFAULT_MODEL)
    parser.add_argument("--dry-run", action="store_true",   help="Preview without writing")
    args = parser.parse_args()

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set")
        return 1

    STAGING_FILE.parent.mkdir(parents=True, exist_ok=True)

    staged   = 0
    total_tokens = 0
    has_oauth = bool(os.getenv("REDDIT_CLIENT_ID"))

    print(f"Reel fact discovery  (limit={args.limit}, oauth={'yes' if has_oauth else 'no -- skipping NSFW subs'})")
    print()

    for source in SOURCES:
        sub   = source["subreddit"]
        nsfw  = source["nsfw"]
        min_u = source["min_upvotes"]

        if staged >= args.limit:
            break

        print(f"r/{sub} ({'NSFW/OAuth' if nsfw else 'public'}, min_upvotes={min_u:,})")
        posts = _fetch_posts(sub, nsfw, MAX_PER_SUB)
        found = 0

        for child in posts:
            if staged >= args.limit:
                break

            post = child["data"]
            title      = (post.get("title") or "").strip()
            selftext   = (post.get("selftext") or "").strip()
            upvotes    = post.get("ups", 0)
            created    = post.get("created_utc", 0)
            reddit_id  = post.get("id", "")
            url        = post.get("url", "")

            if upvotes < min_u:
                continue
            if _age_days(created) < MIN_AGE_DAYS:
                continue
            if not title or len(title) < 20:
                continue
            if _is_blocked(title) or _is_blocked(selftext):
                continue
            if _already_staged(title):
                continue
            if _already_in_bank(title):
                continue

            topic = _classify_topic(title + " " + selftext)

            print(f"  [{upvotes:,} upvotes] {title[:80]}")

            if args.dry_run:
                staged += 1
                found  += 1
                continue

            result = _generate_reel(title, selftext, topic, api_key, args.model)
            if not result:
                print(f"    skipped (Claude returned weak script)")
                continue

            total_tokens += result["tokens"]
            entry = {
                "reddit_id":    reddit_id,
                "reddit_title": title,
                "subreddit":    sub,
                "upvotes":      upvotes,
                "source_url":   url,
                "topic":        topic,
                "reel_title":   result["reel_title"],
                "reel_script":  result["reel_script"],
                "status":       "staged",
            }

            with STAGING_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

            print(f"    -> \"{result['reel_title']}\"")
            print(f"       {len(result['reel_script'].split())} words")
            staged += 1
            found  += 1
            time.sleep(0.3)

        if found:
            print(f"  Staged {found} from r/{sub}")
        print()

    rates = {"claude-haiku-4-5-20251001": 0.80, "claude-sonnet-4-6": 3.00}
    cost = (total_tokens / 1_000_000) * rates.get(args.model, 0.80) * 2
    print(f"Done. {staged} facts staged.  Claude: ~${cost:.4f}")
    if not args.dry_run and staged:
        print(f"Review: {STAGING_FILE}")
        print("When happy with entries, copy claim+reel_script+reel_title into src/research/rare_fact_bank.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
