"""factjot status snapshot.

One-command readout of the bot's current state. Run any time to know:
- queue depth (scheduled / published / failed)
- next scheduled publish time + topic
- last publish (when, what, ig_media_id)
- runway per topic (fresh facts / total)
- token age estimate
- recent alerts
- recent log entries

Designed to be cron-friendly too — exit 1 if any red flag.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.brain import brain
from src.research.rare_fact_bank import RARE_FACT_BANK, load_all_facts


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def main() -> int:
    load_dotenv()

    print("=" * 64)
    print(f"factjot status — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 64)

    red_flags = 0

    # 1. Queue depth
    from src.core.paths import APPROVAL_QUEUE, ALERTS
    queue_rows = _read_jsonl(APPROVAL_QUEUE)
    by_status = Counter(r.get("status", "?") for r in queue_rows)
    print(f"\nQueue ({len(queue_rows)} rows):")
    for st, n in by_status.most_common():
        print(f"  {st:<14} {n}")

    # 2. Next scheduled publish
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    upcoming = sorted(
        [r for r in queue_rows if r.get("status") == "scheduled"
         and r.get("publish_at", "") > now_iso],
        key=lambda r: r.get("publish_at", ""),
    )
    if upcoming:
        nxt = upcoming[0]
        print(f"\nNext scheduled: {nxt.get('publish_at','')} — {nxt.get('category','?')} ({nxt.get('post_id','?')[:14]})")
    else:
        print("\nNext scheduled: NONE")
        red_flags += 1

    # 3. Last publish
    posted = _read_jsonl(Path("insta-brain/data/posted.jsonl"))
    if posted:
        last_post_id = posted[-1].get("post_id", "")
        last_when = posted[-1].get("published_at", "")
        last_cat = posted[-1].get("category", "")
        last_ig = posted[-1].get("ig_media_id", "")
        print(f"\nLast publish: {last_when} — {last_cat} ({last_post_id[:14]}, ig={last_ig})")
    else:
        print("\nLast publish: NEVER")

    # 4. Runway by topic
    fresh: dict[str, int] = {}
    used: dict[str, int] = {}
    for r in load_all_facts():
        if brain.is_fact_posted(r["claim"]):
            used[r["topic"]] = used.get(r["topic"], 0) + 1
        else:
            fresh[r["topic"]] = fresh.get(r["topic"], 0) + 1
    print(f"\nRunway (fresh / used per topic):")
    total_fresh = sum(fresh.values())
    for t in sorted(set(list(fresh.keys()) + list(used.keys()))):
        f = fresh.get(t, 0); u = used.get(t, 0)
        flag = "  LOW" if f < 7 else ""
        print(f"  {t:<14} {f:>3} fresh  /  {u:>3} used{flag}")
    days = total_fresh // 12  # 2 carousels/day, ~6 facts each
    print(f"  TOTAL          {total_fresh:>3} fresh  =>  ~{days} days at 2 posts/day")
    if days < 3:
        print(f"  RED FLAG: runway under 3 days")
        red_flags += 1

    # 5. Token age estimate
    token = os.getenv("META_ACCESS_TOKEN", "").strip()
    if token:
        try:
            r = requests.get(
                "https://graph.instagram.com/me",
                params={"fields": "id,username", "access_token": token},
                timeout=8,
            )
            if r.ok:
                print(f"\nIG token: VALID (username={r.json().get('username','')})")
            else:
                print(f"\nIG token: INVALID ({r.status_code})")
                red_flags += 1
        except Exception as exc:
            print(f"\nIG token: UNREACHABLE ({exc})")
            red_flags += 1
    else:
        print("\nIG token: NOT SET")
        red_flags += 1

    # 6. Recent alerts
    alerts = _read_jsonl(ALERTS)
    if alerts:
        recent = alerts[-3:]
        print(f"\nRecent alerts ({len(alerts)} total):")
        for a in recent:
            print(f"  {a.get('ts','')}  {a.get('kind','')}  {str(a.get('detail',''))[:80]}")
    else:
        print("\nRecent alerts: none")

    # 7. Recent comments on the latest post — reply window reminder
    try:
        posted_rows = _read_jsonl(Path("insta-brain/data/posted.jsonl"))
        if posted_rows:
            latest = posted_rows[-1]
            ig_id = latest.get("ig_media_id")
            comment_token = os.environ.get("META_ACCESS_TOKEN", "")
            if ig_id and comment_token:
                import requests as _req
                r = _req.get(
                    f"https://graph.instagram.com/v21.0/{ig_id}/comments",
                    params={
                        "fields": "text,timestamp,username",
                        "access_token": comment_token,
                    },
                    timeout=8,
                ).json()
                comments = r.get("data", [])
                if comments:
                    print(f"\nComments on latest post ({ig_id}) — reply to boost reach:")
                    for c in comments[:5]:
                        ts = c.get("timestamp", "")[:16]
                        user = c.get("username", "?")
                        text = (c.get("text") or "")[:80]
                        print(f"  {ts}  @{user}: {text}")
                    if len(comments) > 5:
                        print(f"  ... and {len(comments)-5} more")
                else:
                    print(f"\nComments on latest post: none yet")
    except Exception:
        pass

    # 8. Recent log
    log = Path("insta-brain/log.md")
    if log.exists():
        lines = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.startswith("- ")][:5]
        print(f"\nRecent log:")
        for ln in lines:
            print(f"  {ln[:120]}")

    print()
    if red_flags:
        print(f"STATUS: {red_flags} red flag(s) — see above.")
        return 1
    print("STATUS: green.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
