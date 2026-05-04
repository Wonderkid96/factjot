"""Download the factjot background music bank from Pixabay Audio (free, CC0).

Run once to populate assets/music/ with mood-matched tracks.
Uses the same PIXABAY_API_KEY already in .env.

Usage:
    python3 scripts/download_music.py
    python3 scripts/download_music.py --list   # show what would be downloaded
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MUSIC_DIR = ROOT / "assets" / "music"

# Each entry: (output_stem, pixabay_search_query, mood_note)
# Output file: assets/music/{stem}.mp3
# Searches are tuned for documentary, atmospheric, minimal melodic.
TRACKS: list[tuple[str, str, str]] = [
    ("dark",          "dark cinematic ambient",        "tense/shocking — history crime space"),
    ("sober",         "solemn documentary piano",      "measured/serious — sober tone"),
    ("investigations","mystery investigation ambient", "curious — history technology biology"),
    ("ambient_space", "space ambient atmospheric",     "wide/floating — space facts"),
    ("ambient_ocean", "underwater ambient deep",       "deep/textural — ocean facts"),
    ("ambient_earth", "nature cinematic ambient",      "grand/geological — earth biology"),
]


def _fetch_pixabay_audio(query: str, api_key: str) -> dict | None:
    import urllib.request, urllib.parse, json as _json
    params = urllib.parse.urlencode({
        "key": api_key,
        "q": query,
        "media_type": "music",
        "per_page": 5,
    })
    url = f"https://pixabay.com/api/?{params}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = _json.loads(resp.read())
    except Exception as exc:
        print(f"  API error for {query!r}: {exc}")
        return None
    hits = data.get("hits", [])
    if not hits:
        return None
    return hits[0]


def _download(url: str, dest: Path) -> bool:
    import urllib.request
    try:
        urllib.request.urlretrieve(url, dest)
        return True
    except Exception as exc:
        print(f"  Download failed: {exc}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="Show plan without downloading")
    args = ap.parse_args()

    api_key = ""
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("PIXABAY_API_KEY="):
                api_key = line.split("=", 1)[1].strip().strip('"').strip("'")

    if not api_key:
        api_key = os.getenv("PIXABAY_API_KEY", "")
    if not api_key:
        print("ERROR: PIXABAY_API_KEY not found in .env or environment.")
        return 1

    MUSIC_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Music bank: {MUSIC_DIR}")
    print(f"Tracks to source: {len(TRACKS)}\n")

    for stem, query, note in TRACKS:
        dest = MUSIC_DIR / f"{stem}.mp3"
        exists = dest.exists()
        tag = "EXISTS" if exists else "MISSING"
        print(f"  [{tag}] {stem}.mp3  ({note})")
        print(f"           query: {query!r}")

        if args.list or exists:
            continue

        print(f"  Searching Pixabay for {query!r}...")
        hit = _fetch_pixabay_audio(query, api_key)
        if not hit:
            print(f"  No results — skipping. Add {stem}.mp3 manually.")
            continue

        audio_url = hit.get("audio", {}).get("url") or hit.get("previewURL", "")
        if not audio_url:
            print(f"  No audio URL in result — skipping.")
            continue

        print(f"  Found: {hit.get('tags','')[:60]}")
        print(f"  Downloading {audio_url[:80]}...")
        if _download(audio_url, dest):
            size_kb = dest.stat().st_size // 1024
            print(f"  Saved {dest.name} ({size_kb}KB)")
        time.sleep(0.5)

    print("\nDone.")
    missing = [s for s, _, _ in TRACKS if not (MUSIC_DIR / f"{s}.mp3").exists()]
    if missing:
        print(f"\nStill missing: {missing}")
        print("Add these manually from https://incompetech.com or https://pixabay.com/music/")
        print("Suggested Kevin MacLeod tracks (CC BY, free):")
        print("  dark           -> 'Cipher' or 'Ossuary 5 - Rest'")
        print("  sober          -> 'Constance' or 'Solemn'")
        print("  investigations -> 'Investigations' or 'Spy Glass'")
        print("  ambient_space  -> 'Long Note Four' or 'Ether Oar'")
        print("  ambient_ocean  -> 'Perspectives' or 'At Rest'")
        print("  ambient_earth  -> 'Epic Unease' or 'Healing'")
        print("  Download from: https://incompetech.com/music/royalty-free/music.html")
        print("  Licence: CC BY 4.0 - add credit to MUSIC_CREDIT env var")
    return 0


if __name__ == "__main__":
    sys.exit(main())
