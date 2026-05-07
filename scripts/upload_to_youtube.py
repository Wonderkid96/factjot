"""Upload a vertical 1080x1920 MP4 to YouTube as a Short.

Reads YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN
from env (set via GitHub Actions secrets locally via gh secret set).

Usage:
    python3 scripts/upload_to_youtube.py path/to/final.mp4 \\
        --title "..." --description "..." [--tags science,history] \\
        [--privacy public|unlisted|private]

If --title / --description are omitted, the script can also auto-pick
the most recent reel by passing --auto-latest. That looks up
insta-brain/data/reels.jsonl, finds the newest entry, and uses its
reel_title and the start of its caption.

Adds #Shorts to the description so YouTube treats the upload as a
Short. Existing #Shorts is not duplicated.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

REPO_ROOT     = Path(__file__).resolve().parent.parent
REELS_LEDGER  = REPO_ROOT / "insta-brain" / "data" / "reels.jsonl"
REEL_CACHE    = REPO_ROOT / "data" / "cache" / "reels"
YT_LEDGER     = REPO_ROOT / "data" / "ledgers" / "youtube_uploads.jsonl"

TOKEN_URI     = "https://oauth2.googleapis.com/token"
SCOPES        = ["https://www.googleapis.com/auth/youtube.upload"]
DEFAULT_PRIVACY = "public"

# YouTube category IDs: 27=Education, 28=Science & Technology, 22=People & Blogs.
# 27 (Education) is the safest bet for factjot's content profile.
CATEGORY_ID = "27"


def _credentials_from_env() -> Credentials:
    cid     = os.environ.get("YOUTUBE_CLIENT_ID", "").strip()
    secret  = os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip()
    refresh = os.environ.get("YOUTUBE_REFRESH_TOKEN", "").strip()
    missing = [k for k, v in [
        ("YOUTUBE_CLIENT_ID", cid),
        ("YOUTUBE_CLIENT_SECRET", secret),
        ("YOUTUBE_REFRESH_TOKEN", refresh),
    ] if not v]
    if missing:
        raise RuntimeError(f"Missing env vars: {', '.join(missing)}")

    creds = Credentials(
        token=None,
        refresh_token=refresh,
        client_id=cid,
        client_secret=secret,
        token_uri=TOKEN_URI,
        scopes=SCOPES,
    )
    creds.refresh(google.auth.transport.requests.Request())
    return creds


def _latest_reel_meta() -> dict | None:
    """Return the most recent entry from reels.jsonl, or None."""
    if not REELS_LEDGER.exists():
        return None
    last: dict | None = None
    with REELS_LEDGER.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                last = json.loads(line)
            except json.JSONDecodeError:
                continue
    return last


def _resolve_video_path(arg_path: str | None, reel_meta: dict | None) -> Path:
    if arg_path:
        p = Path(arg_path).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"Video not found: {p}")
        return p
    if reel_meta and reel_meta.get("reel_id"):
        candidate = REEL_CACHE / reel_meta["reel_id"] / "final.mp4"
        if candidate.exists():
            return candidate
    raise FileNotFoundError("No video path provided and could not auto-resolve from reels.jsonl")


def _ensure_shorts_tag(description: str) -> str:
    """Append #Shorts so YouTube treats the upload as a Short."""
    if "#shorts" in description.lower():
        return description
    return description.rstrip() + "\n\n#Shorts"


def upload(video_path: Path, title: str, description: str,
           tags: list[str], privacy: str) -> dict:
    creds   = _credentials_from_env()
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

    body = {
        "snippet": {
            "title":       title[:100],   # YouTube hard cap at 100 chars
            "description": _ensure_shorts_tag(description)[:5000],
            "tags":        tags[:30],
            "categoryId":  CATEGORY_ID,
        },
        "status": {
            "privacyStatus":          privacy,
            "selfDeclaredMadeForKids": False,
            "madeForKids":             False,
        },
    }

    media = MediaFileUpload(str(video_path), mimetype="video/mp4",
                            resumable=True, chunksize=4 * 1024 * 1024)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    print(f"[youtube] uploading {video_path.name} ({video_path.stat().st_size // 1024}KB)...", flush=True)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"[youtube] {int(status.progress() * 100)}% uploaded", flush=True)
    print(f"[youtube] done. video_id={response['id']}", flush=True)
    return response


def _log_upload(video_id: str, title: str, video_path: Path,
                reel_meta: dict | None, privacy: str) -> None:
    from datetime import datetime, timezone
    record = {
        "timestamp":  datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "video_id":   video_id,
        "url":        f"https://youtube.com/shorts/{video_id}",
        "title":      title,
        "video_file": str(video_path),
        "privacy":    privacy,
        "source_reel_id": (reel_meta or {}).get("reel_id"),
        "ig_media_id":    (reel_meta or {}).get("ig_media_id"),
    }
    YT_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with YT_LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Upload a video to YouTube as a Short")
    parser.add_argument("video_path", nargs="?", help="Path to the MP4 (omit if --auto-latest)")
    parser.add_argument("--title")
    parser.add_argument("--description", default="")
    parser.add_argument("--tags", default="", help="Comma-separated tags")
    parser.add_argument("--privacy", choices=["public", "unlisted", "private"],
                        default=DEFAULT_PRIVACY)
    parser.add_argument("--auto-latest", action="store_true",
                        help="Resolve video + title from the most recent reels.jsonl entry")
    args = parser.parse_args(argv)

    reel_meta = _latest_reel_meta() if args.auto_latest else None

    try:
        video_path = _resolve_video_path(args.video_path, reel_meta)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    title = args.title or (reel_meta or {}).get("reel_title") or video_path.stem
    description = args.description or (reel_meta or {}).get("caption") or ""
    tags_list = [t.strip() for t in args.tags.split(",") if t.strip()]
    if not tags_list and reel_meta and reel_meta.get("topic"):
        tags_list = [reel_meta["topic"], "facts", "factjot"]

    try:
        response = upload(video_path, title, description, tags_list, args.privacy)
    except HttpError as exc:
        print(f"ERROR: YouTube API: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    video_id = response["id"]
    _log_upload(video_id, title, video_path, reel_meta, args.privacy)
    print(f"https://youtube.com/shorts/{video_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
