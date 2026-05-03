"""One-time setup: download music tracks and safety-pool video clips for Reels.

Run this once before using make_reel.py (local Mac):
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3 scripts/setup_reel_assets.py

What it does:
  1. Downloads 6 royalty-free Pixabay Music tracks (one per topic category)
     to assets/music/{topic}.mp3

  2. Downloads 3 safety-pool video clips per topic from Pexels
     to assets/video/{topic}/safety_{n}.mp4
     These are the last-resort fallback if the dynamic video search fails.

All content is royalty-free / CC0 or Pexels license (free for commercial use).
You only need to run this once; clips are cached and not re-downloaded.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.append(str(Path(__file__).resolve().parents[1]))
load_dotenv()

_ASSETS = Path(__file__).resolve().parents[1] / "assets"

# ------------------------------------------------------------------ #
# Music tracks — Pixabay Music
# Curated track IDs per topic (search at pixabay.com/music/)
# Format: {topic: [(title, pixabay_music_url), ...]}
#
# These are pre-selected ambient/atmospheric tracks that fit each category.
# Pixabay Music = royalty-free, no attribution required for all uses.
# ------------------------------------------------------------------ #
_MUSIC_TRACKS = {
    "space": [
        ("cosmic-ambient", "https://cdn.pixabay.com/download/audio/2022/01/18/audio_d0c6ff1bab.mp3"),
    ],
    "nature": [
        ("forest-ambient", "https://cdn.pixabay.com/download/audio/2022/02/22/audio_d1718ab41b.mp3"),
    ],
    "ocean": [
        ("ocean-waves", "https://cdn.pixabay.com/download/audio/2021/09/06/audio_c8d714ccaa.mp3"),
    ],
    "history": [
        ("cinematic-dark", "https://cdn.pixabay.com/download/audio/2022/03/15/audio_bf776aaa0d.mp3"),
    ],
    "tech": [
        ("electronic-ambient", "https://cdn.pixabay.com/download/audio/2022/01/20/audio_9e0f7e0b58.mp3"),
    ],
    "earth": [
        ("epic-nature", "https://cdn.pixabay.com/download/audio/2022/05/13/audio_a2b9b66990.mp3"),
    ],
}

# ------------------------------------------------------------------ #
# Safety video queries per topic
# Simple, reliable Pexels searches that almost always return results.
# ------------------------------------------------------------------ #
_SAFETY_QUERIES = {
    "space":   ["galaxy stars night", "milky way sky", "planets stars universe"],
    "nature":  ["forest sunlight slow", "wildlife close up", "trees wind"],
    "ocean":   ["ocean waves water", "underwater blue", "sea surf"],
    "history": ["old city streets", "vintage film grain", "smoke fog atmospheric"],
    "tech":    ["computer screen code", "circuit board macro", "data technology"],
    "earth":   ["mountain landscape aerial", "volcano lava", "desert sand wind"],
}

# ------------------------------------------------------------------ #
# Main
# ------------------------------------------------------------------ #

def setup_music() -> None:
    music_dir = _ASSETS / "music"
    music_dir.mkdir(parents=True, exist_ok=True)
    print("\n=== Downloading music tracks ===")
    for topic, tracks in _MUSIC_TRACKS.items():
        out = music_dir / f"{topic}.mp3"
        if out.exists() and out.stat().st_size > 10_000:
            print(f"  {topic}: already exists ({out.stat().st_size // 1024} KB)")
            continue
        title, url = tracks[0]
        print(f"  {topic}: downloading {title}...")
        try:
            r = requests.get(url, timeout=30, stream=True)
            r.raise_for_status()
            with open(out, "wb") as f:
                for chunk in r.iter_content(65536):
                    f.write(chunk)
            print(f"    -> {out.stat().st_size // 1024} KB")
        except Exception as exc:
            print(f"    FAILED: {exc}")
            print(f"    -> Manually download a royalty-free track from pixabay.com/music/")
            print(f"       and save it as {out}")


def setup_safety_pool() -> None:
    api_key = os.getenv("PEXELS_API_KEY", "").strip()
    if not api_key:
        print("\nPEXELS_API_KEY not set — skipping safety pool download.")
        return
    print("\n=== Downloading safety pool clips (Pexels) ===")
    for topic, queries in _SAFETY_QUERIES.items():
        video_dir = _ASSETS / "video" / topic
        video_dir.mkdir(parents=True, exist_ok=True)
        existing = list(video_dir.glob("safety_*.mp4"))
        if len(existing) >= 3:
            print(f"  {topic}: {len(existing)} clips already present")
            continue
        n = len(existing)
        for query in queries:
            if n >= 3:
                break
            out = video_dir / f"safety_{n:02d}.mp4"
            if out.exists() and out.stat().st_size > 50_000:
                n += 1
                continue
            print(f"  {topic}: searching '{query}'...")
            try:
                r = requests.get(
                    "https://api.pexels.com/videos/search",
                    headers={"Authorization": api_key},
                    params={"query": query, "orientation": "portrait", "size": "medium", "per_page": 3},
                    timeout=15,
                )
                r.raise_for_status()
                videos = r.json().get("videos", [])
                if not videos:
                    continue
                # Pick the file with the best portrait resolution
                chosen_url = None
                for vid in videos:
                    files = vid.get("video_files", [])
                    portrait = [f for f in files if f.get("height", 0) >= f.get("width", 1)]
                    if not portrait:
                        portrait = files
                    portrait.sort(key=lambda f: f.get("width", 0) * f.get("height", 0), reverse=True)
                    chosen_url = portrait[min(1, len(portrait)-1)].get("link")
                    if chosen_url:
                        break
                if not chosen_url:
                    continue
                resp = requests.get(chosen_url, stream=True, timeout=60)
                resp.raise_for_status()
                with open(out, "wb") as f:
                    for chunk in resp.iter_content(65536):
                        f.write(chunk)
                if out.stat().st_size < 50_000:
                    out.unlink(missing_ok=True)
                    continue
                print(f"    -> {out.name} ({out.stat().st_size // 1024} KB)")
                n += 1
                time.sleep(0.5)  # be polite to Pexels
            except Exception as exc:
                print(f"    FAILED: {exc}")


def main() -> None:
    setup_music()
    setup_safety_pool()
    print("\nDone. Run make_reel.py --dry-run to test.")


if __name__ == "__main__":
    main()
