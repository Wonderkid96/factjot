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
YT_LEDGER     = REPO_ROOT / "data" / "ledgers" / "youtube_uploads.jsonl"

# Resolve the reel output dir from src.core.paths so we stay in sync if
# it ever moves (currently REPO_ROOT/output/reel/{reel_id}/final.mp4).
import sys as _sys
_sys.path.insert(0, str(REPO_ROOT))
try:
    from src.core.paths import REELS_CACHE as _REELS_CACHE
except Exception:
    _REELS_CACHE = REPO_ROOT / "output" / "reel"
REEL_CACHE = _REELS_CACHE

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


def _already_uploaded(reel_id: str | None) -> bool:
    """True if reel_id is already in youtube_uploads.jsonl."""
    if not reel_id or not YT_LEDGER.exists():
        return False
    with YT_LEDGER.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                if json.loads(line).get("source_reel_id") == reel_id:
                    return True
            except json.JSONDecodeError:
                continue
    return False


def _is_fresh(reel_meta: dict | None, max_age_minutes: int = 30) -> bool:
    """True if reel was posted in the last `max_age_minutes`.

    Used as a guard so the YouTube cross-post step in the workflow
    doesn't re-upload an old reel when the agent just posted a
    carousel and reels.jsonl wasn't touched.
    """
    timestamp = (reel_meta or {}).get("published_at") or (reel_meta or {}).get("posted_at")
    if not timestamp:
        return False
    from datetime import datetime, timezone, timedelta
    try:
        posted = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    age = datetime.now(timezone.utc) - posted
    return age <= timedelta(minutes=max_age_minutes)


def _resolve_video_path(arg_path: str | None, reel_meta: dict | None) -> Path:
    if arg_path:
        p = Path(arg_path).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"Video not found: {p}")
        return p
    if reel_meta:
        # Prefer the out_dir recorded in reels.jsonl when present (most
        # reliable, survives path refactors). Fall back to constructing
        # from REELS_CACHE / reel_id / final.mp4.
        candidates: list[Path] = []
        out_dir = reel_meta.get("out_dir")
        if out_dir:
            p = Path(out_dir)
            if not p.is_absolute():
                p = REPO_ROOT / p
            candidates.append(p / "final.mp4")
        if reel_meta.get("reel_id"):
            candidates.append(REEL_CACHE / reel_meta["reel_id"] / "final.mp4")
        for c in candidates:
            if c.exists():
                return c
        tried = "\n  tried: " + "\n  tried: ".join(str(c) for c in candidates)
        raise FileNotFoundError(
            f"Latest reel ({reel_meta.get('reel_id')}) is in reels.jsonl "
            f"but final.mp4 was not on disk.{tried}"
        )
    raise FileNotFoundError("No video path provided and reels.jsonl is empty.")


def _ensure_shorts_tag(description: str) -> str:
    """Append #Shorts so YouTube treats the upload as a Short."""
    if "#shorts" in description.lower():
        return description
    return description.rstrip() + "\n\n#Shorts"


def _description_from_reel_meta(reel_meta: dict | None) -> str:
    """Build a Shorts description when --description is not passed.

    Prefer the caption stored on the reel ledger row (written since 2026-05);
    older rows only have claim + title.
    """
    if not reel_meta:
        return ""
    cap = (reel_meta.get("caption") or "").strip()
    if cap:
        return cap
    title = (reel_meta.get("reel_title") or "").strip()
    claim = (reel_meta.get("claim") or "").strip()
    parts = [p for p in (title, claim) if p]
    return "\n\n".join(parts) if parts else ""


def _prepare_thumbnail(video_path: Path) -> Path | None:
    """Return a JPEG version of the reel's thumbnail.png under 2 MB, or
    None if no thumbnail file is available next to the video.

    YouTube caps custom thumbnails at 2 MB; our PNG renders at ~2.3 MB.
    JPEG at quality 85 typically lands well under 1 MB.
    """
    src = video_path.parent / "thumbnail.png"
    if not src.exists():
        return None
    try:
        from PIL import Image
    except ImportError:
        print("[youtube] Pillow not installed, skipping thumbnail compression", flush=True)
        return None

    out = video_path.parent / "thumbnail_yt.jpg"
    with Image.open(src) as im:
        im = im.convert("RGB")
        im.save(out, format="JPEG", quality=85, optimize=True, progressive=True)
    size_kb = out.stat().st_size // 1024
    if out.stat().st_size > 2 * 1024 * 1024:
        # Re-encode at lower quality if still over 2MB.
        with Image.open(src) as im:
            im = im.convert("RGB")
            im.save(out, format="JPEG", quality=75, optimize=True, progressive=True)
        size_kb = out.stat().st_size // 1024
    print(f"[youtube] thumbnail prepared: {out.name} ({size_kb}KB)", flush=True)
    return out


def _set_thumbnail(youtube, video_id: str, thumbnail_path: Path) -> bool:
    """Upload custom thumbnail. Soft fail (returns False) if the channel
    is not verified or the API rejects the image — YouTube will fall
    back to an auto-generated frame from the video."""
    try:
        request = youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg"),
        )
        request.execute()
        print(f"[youtube] custom thumbnail set on {video_id}", flush=True)
        return True
    except HttpError as exc:
        print(f"[youtube] thumbnail set failed (non-fatal): {exc}", flush=True)
        return False
    except Exception as exc:
        print(f"[youtube] thumbnail set failed (non-fatal): {exc}", flush=True)
        return False


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
    video_id = response["id"]
    print(f"[youtube] done. video_id={video_id}", flush=True)

    # Custom thumbnail (soft - YouTube auto-picks a frame if this fails).
    thumb = _prepare_thumbnail(video_path)
    if thumb is not None:
        _set_thumbnail(youtube, video_id, thumb)

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
    parser.add_argument("--max-age-minutes", type=int, default=30,
                        help="With --auto-latest, skip if the latest reel is older than this (default: 30)")
    args = parser.parse_args(argv)

    reel_meta = _latest_reel_meta() if args.auto_latest else None

    if args.auto_latest:
        if not reel_meta:
            print("[youtube] no entries in reels.jsonl, nothing to upload. skipping.")
            return 0
        if not _is_fresh(reel_meta, args.max_age_minutes):
            ts = reel_meta.get("published_at") or reel_meta.get("posted_at")
            print(
                f"[youtube] latest reel {reel_meta.get('reel_id')!r} "
                f"published_at={ts!r} is older than {args.max_age_minutes} min - "
                "agent likely posted a carousel this run. skipping."
            )
            return 0
        if _already_uploaded(reel_meta.get("reel_id")):
            print(
                f"[youtube] reel {reel_meta.get('reel_id')!r} already in "
                "youtube_uploads.jsonl. skipping to avoid duplicate."
            )
            return 0

    try:
        video_path = _resolve_video_path(args.video_path, reel_meta)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    title = args.title or (reel_meta or {}).get("reel_title") or video_path.stem
    description = args.description or _description_from_reel_meta(reel_meta)
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
