"""Fetch Instagram performance metrics for all posted reels.

Reads insta-brain/data/reels.jsonl, resolves real media IDs by matching
caption content against /{account}/media (the stored ig_media_id from
media_publish is not always the canonical queryable ID), then fetches
per-media insights and writes to data/ledgers/reel_performance.jsonl.

Runs weekly via weekly-plan.yml. Safe to run manually at any time.
Re-fetches reels posted within the last REFETCH_DAYS so metrics stay
current as late engagement arrives.

Ledger schema (one JSON line per reel, keyed by reel_id):
  reel_id, ig_media_id, topic, tone, reel_title, claim,
  script_word_count, posted_at, metrics_fetched_at,
  reach, views, likes, saves, shares, comments,
  view_rate, viral_score, engagement_rate
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REELS_LOG  = ROOT / "insta-brain" / "data" / "reels.jsonl"
PERF_LOG   = ROOT / "data" / "ledgers" / "reel_performance.jsonl"

REFETCH_DAYS = 90   # re-fetch metrics for reels up to 90 days old
AUDIO_KBPS   = 128  # for future use


def _load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def _get(path: str, params: dict) -> dict:
    import urllib.request, urllib.parse
    params["access_token"] = os.environ["META_ACCESS_TOKEN"]
    host    = os.environ.get("META_GRAPH_HOST", "graph.facebook.com")
    version = os.environ.get("META_GRAPH_VERSION", "v21.0")
    url = f"https://{host}/{version}{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.loads(r.read())


def _first_words(text: str, n: int = 8) -> str:
    """Return first N words of text lowercased — used as a fuzzy match key."""
    return " ".join(text.lower().split()[:n])


def _build_media_index(account_id: str) -> dict[str, dict]:
    """Fetch all account media and index by first-words-of-caption."""
    try:
        data = _get(f"/{account_id}/media", {
            "fields": "id,media_type,media_product_type,timestamp,caption",
            "limit": 50,
        })
    except Exception as exc:
        print(f"  [media index] fetch error: {exc}")
        return {}
    index: dict[str, dict] = {}
    for m in data.get("data", []):
        cap = (m.get("caption") or "").strip()
        if cap:
            key = _first_words(cap)
            index[key] = m
            # Also index by stored id directly
            index[m["id"]] = m
    return index


def _resolve_media_id(reel: dict, media_index: dict) -> str | None:
    """Find the real queryable media ID for a reel.

    Tries:
    1. Stored ig_media_id (works if the publisher fix is in place).
    2. Caption match — first 8 words of claim vs first 8 words of caption.
    3. Reel title match — title appears somewhere in the caption.
    """
    stored = reel.get("ig_media_id", "")
    if stored in media_index:
        return stored

    claim_key = _first_words(reel.get("claim", ""))
    if claim_key in media_index:
        return media_index[claim_key]["id"]

    title = reel.get("reel_title", "").lower()
    if title:
        for key, m in media_index.items():
            if isinstance(key, str) and len(key) > 10 and title[:30] in key:
                return m["id"]

    return None


def _fetch_insights(media_id: str) -> dict:
    metrics = "reach,likes,comments,shares,saved,total_interactions,views"
    try:
        data = _get(f"/{media_id}/insights", {"metric": metrics})
        out: dict = {}
        for item in data.get("data", []):
            name = item.get("name", "")
            vals = item.get("values", [])
            out[name] = vals[0].get("value", 0) if vals else 0
        return out
    except Exception as exc:
        print(f"  [insights] error for {media_id}: {exc}")
        return {}


def _load_fact_meta(claim: str) -> dict:
    try:
        from src.research.rare_fact_bank import load_all_facts
        for f in load_all_facts():
            if f.get("claim", "").strip() == claim.strip():
                script = f.get("reel_script", "")
                return {
                    "tone":             f.get("tone", ""),
                    "reel_title":       f.get("reel_title", ""),
                    "script_word_count": len(script.split()) if script else 0,
                }
    except Exception:
        pass
    return {"tone": "", "reel_title": "", "script_word_count": 0}


def _derive(raw: dict, reach: int) -> dict:
    views    = raw.get("views", 0)
    saves    = raw.get("saved", 0)
    shares   = raw.get("shares", 0)
    comments = raw.get("comments", 0)
    likes    = raw.get("likes", 0)
    return {
        "reach":           reach,
        "views":           views,
        "likes":           likes,
        "saves":           saves,
        "shares":          shares,
        "comments":        comments,
        "view_rate":       round(views / reach, 3) if reach else 0.0,
        "viral_score":     saves * 3 + shares * 2 + comments,
        "engagement_rate": round((saves + shares + comments) / reach, 4) if reach else 0.0,
    }


def main() -> int:
    _load_env()

    if not REELS_LOG.exists():
        print("No reels.jsonl found.")
        return 0

    account_id = os.environ.get("INSTAGRAM_ACCOUNT_ID", "")
    if not account_id:
        print("INSTAGRAM_ACCOUNT_ID not set.")
        return 1

    print("Building media index from Instagram...")
    media_index = _build_media_index(account_id)
    print(f"  {len(media_index) // 2} media items indexed")

    # Load existing performance records
    existing: dict[str, dict] = {}
    if PERF_LOG.exists():
        for line in PERF_LOG.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    r = json.loads(line)
                    existing[r["reel_id"]] = r
                except Exception:
                    pass

    posted = [
        json.loads(l) for l in REELS_LOG.read_text().splitlines()
        if l.strip()
    ]

    cutoff  = datetime.now(timezone.utc) - timedelta(days=REFETCH_DAYS)
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    updated = 0
    skipped = 0

    for reel in posted:
        reel_id   = reel.get("reel_id", "")
        published = reel.get("published_at", "")
        if not reel_id:
            continue

        try:
            pub_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
            if pub_dt < cutoff:
                continue
        except Exception:
            pass

        real_id = _resolve_media_id(reel, media_index)
        if not real_id:
            print(f"  SKIP {reel_id} ({published[:10]}) — no matching media on account")
            skipped += 1
            continue

        print(f"Fetching: {reel_id} -> media_id={real_id} ({published[:10]})...")
        raw = _fetch_insights(real_id)
        if not raw:
            skipped += 1
            continue

        reach     = raw.get("reach", 0)
        fact_meta = _load_fact_meta(reel.get("claim", ""))

        record = {
            "reel_id":           reel_id,
            "ig_media_id":       real_id,
            "topic":             reel.get("topic", ""),
            "tone":              fact_meta["tone"],
            "reel_title":        fact_meta["reel_title"],
            "claim":             reel.get("claim", "")[:120],
            "script_word_count": fact_meta["script_word_count"],
            "posted_at":         published,
            "metrics_fetched_at": now_iso,
            **_derive(raw, reach),
        }
        existing[reel_id] = record
        updated += 1
        print(f"  reach={reach}  views={raw.get('views',0)}  saves={raw.get('saved',0)}  viral_score={record['viral_score']}")
        time.sleep(0.3)

    PERF_LOG.parent.mkdir(parents=True, exist_ok=True)
    with PERF_LOG.open("w", encoding="utf-8") as fh:
        for record in existing.values():
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"\nDone. {updated} updated, {skipped} skipped. Ledger: {PERF_LOG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
