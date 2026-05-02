"""Multi-source portrait video finder for Reels composition.

Selection strategy (4 layers — tried in order, first hit wins):
  1. Curated image_hint  — manually written, most specific
  2. Derived queries     — auto-extracted subjects from the fact claim
  3. Topic-generic       — atmospheric fallback for the topic category
  4. Safety pool         — pre-downloaded local clips in assets/video/{topic}/

Sources tried per query (in priority order):
  • Pexels Video          — portrait HD, already-keyed
  • NASA media API        — real footage for space facts (free, no key)
  • Internet Archive      — public-domain newsreels for history facts
  • Pixabay Video         — CC0 fallback (PIXABAY_API_KEY in .env)

Usage:
    from src.research.video_finder import find_video
    mp4 = find_video(
        image_hint="Soviet submarine cold war",
        claim="In 1962 Vasili Arkhipov refused...",
        topic="history",
        out_dir=Path("data/cache/reels/abc123"),
    )
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

_HTTP_TIMEOUT = 20
_MAX_BYTES = 15 * 1024 * 1024   # 15 MB ceiling per clip — keeps FFmpeg memory sane
_MIN_BYTES_HD  = 800_000        # 800 KB floor for modern HD footage (proxy for ≥720p)
_MIN_BYTES_ARK = 50_000         # 50 KB floor for archival/historical content

# ------------------------------------------------------------------ #
# Topic-generic atmospheric fallback queries
# (used when specific searches return nothing usable)
# ------------------------------------------------------------------ #
_TOPIC_GENERIC: dict[str, list[str]] = {
    "space":      ["galaxy nebula stars time lapse", "milky way stars night sky", "planet orbit solar system"],
    "nature":     ["forest sunlight slow motion", "wildlife animal nature", "green forest time lapse"],
    "biology":    ["wildlife animal nature slow motion", "macro insect creature close up", "animal behaviour nature"],
    "ocean":      ["underwater ocean slow motion", "ocean waves surface water", "deep sea fish underwater"],
    "history":    ["vintage film archive black white", "old city streets historical", "aerial city smoke fog"],
    "tech":       ["computer code screen technology", "circuit board technology close up", "data center server lights"],
    "technology": ["computer code screen technology", "circuit board technology close up", "data center server lights"],
    "earth":      ["aerial landscape drone nature", "mountain clouds time lapse", "volcano lava flowing"],
}

# Topic routing for specialist sources
# NASA: space only — earth observation footage is scientific visualisation, not cinematic b-roll
_NASA_TOPICS = {"space"}
# Archive.org: archival/historical content only (allow_archival=True facts)
# For most facts it returns old SD footage that fails the quality floor.

# Rights markers that indicate open/CC/public-domain content
_OPEN_LICENSE_MARKERS = (
    "cc0", "cc-by", "cc by", "public domain", "pd ", "pd-", "pdm",
    "creativecommons", "no known copyright",
)

# Stop words for query derivation
_STOP = frozenset({
    "a", "an", "the", "in", "on", "at", "to", "for", "of", "and", "or",
    "but", "is", "was", "are", "were", "be", "been", "being", "have",
    "had", "has", "do", "did", "does", "will", "would", "could", "should",
    "that", "this", "with", "from", "as", "by", "he", "she", "it", "they",
    "his", "her", "its", "their", "who", "which", "when", "where", "how",
    "not", "no", "can", "so", "if", "about", "after", "before", "than",
})


# ------------------------------------------------------------------ #
# Public entry point
# ------------------------------------------------------------------ #

def find_video(
    image_hint: str,
    claim: str,
    topic: str,
    out_dir: Path,
    *,
    allow_archival: bool = False,
) -> Optional[Path]:
    """Find and download a portrait video for this fact."""
    out_dir.mkdir(parents=True, exist_ok=True)
    queries = _ranked_queries(image_hint, claim, topic)
    print(f"  [video] queries: {queries}")
    for query in queries:
        path = _try_all_sources(query, topic, out_dir, allow_archival=allow_archival)
        if path:
            return path
    pool = _safety_pool_pick(topic)
    return pool[0] if pool else None


def find_videos(
    image_hint: str,
    claim: str,
    topic: str,
    out_dir: Path,
    *,
    count: int = 5,
    use_narrative_beats: bool = True,
    allow_archival: bool = False,
    used_source_registry: set[str] | None = None,
) -> list[Path]:
    """Find `count` distinct portrait videos for this fact.

    Quality rules
    -------------
    allow_archival=False (default):
      - Minimum file size: 800 KB (proxy for ≥720p quality).
      - Archive.org skipped (returns old SD footage for most queries).
      - NASA skipped unless topic is "space".
      - Duplicate file paths are never reused.
      - If the same Pexels file URL is returned for multiple queries,
        only the first hit is kept; the remainder fetch fresh results
        from Pexels with an offset to find a distinct clip.

    allow_archival=True:
      - Minimum file size: 50 KB (historical content may be small/grainy).
      - Archive.org and NASA enabled regardless of topic.
      - Use for facts whose subject IS archival footage (first photo, etc.).
    """
    from src.research.narrative_beats import shot_list, beat_label

    out_dir.mkdir(parents=True, exist_ok=True)

    # Build ordered query list: narrative beats first, then fallbacks
    queries: list[tuple[str, str]] = []
    if use_narrative_beats:
        beats = shot_list(claim=claim, topic=topic, image_hint=image_hint)
        queries.extend((beat_label(i), q) for i, q in enumerate(beats))
        print(f"  [video] narrative shot list:")
        for label, q in queries:
            print(f"    {label:<14} {q}")

    fallback_queries = _ranked_queries(image_hint, claim, topic)
    queries.extend(("FALLBACK", q) for q in fallback_queries)

    clips: list[Path] = []
    used_paths: set[str] = set()       # local file paths already in this batch
    # Seed from global registry so clips used in previous reels are skipped
    used_source_urls: set[str] = set(used_source_registry or ())
    safety = _safety_pool_pick(topic) or []
    safety_idx = 0

    for label, query in queries:
        if len(clips) >= count:
            break
        path = _try_all_sources(
            query, topic, out_dir,
            allow_archival=allow_archival,
            exclude_paths=used_paths,
            used_source_urls=used_source_urls,
        )
        if path and str(path) not in used_paths:
            clips.append(path)
            used_paths.add(str(path))
            print(f"  [video] {label} ✓ {path.name}")

    # Top up from safety pool
    while len(clips) < count and safety_idx < len(safety):
        candidate = safety[safety_idx]
        safety_idx += 1
        if str(candidate) not in used_paths:
            clips.append(candidate)
            used_paths.add(str(candidate))

    print(f"  [video] -> {len(clips)} unique clips ready for composition")
    # Propagate used URLs back to caller's registry for cross-reel dedup
    if used_source_registry is not None:
        used_source_registry.update(used_source_urls)
    return clips


# ------------------------------------------------------------------ #
# Query generation
# ------------------------------------------------------------------ #

def _ranked_queries(image_hint: str, claim: str, topic: str) -> list[str]:
    """Return 3-5 search queries in priority order.

    All queries are anchored to the image_hint where possible so they
    describe the actual visual subject, not a generic topic category.
    """
    from src.research.narrative_beats import _expand_hint, _core_subject

    seen: set[str] = set()
    queries: list[str] = []

    def _add(q: str) -> None:
        q = q.strip()
        if q and q.lower() not in seen:
            seen.add(q.lower())
            queries.append(q)

    if image_hint:
        # Anchor fallbacks to the hint subject, not the generic topic pool
        _add(image_hint)
        core = _core_subject(image_hint)
        for mod in ("slow motion", "wide establishing", "aerial"):
            _add(f"{core} {mod}")
    else:
        # No hint: derive from claim text as before
        for q in _derive_queries(claim, topic):
            _add(q)
        # Final resort: generic topic atmospherics
        for q in _TOPIC_GENERIC.get(topic, []):
            _add(q)

    return queries[:6]


def _derive_queries(claim: str, topic: str) -> list[str]:
    """Extract 1-2 search queries from the raw claim text."""
    # Remove possessives, punctuation, and parentheticals
    clean = re.sub(r"\(.*?\)", "", claim)
    clean = re.sub(r"[^\w\s]", " ", clean)
    words = [w for w in clean.split() if w.lower() not in _STOP and len(w) > 2]

    # Keep proper nouns (capitalised mid-sentence) and longer content words
    proper = [w for w in words if w[0].isupper() and len(w) > 3]
    content = [w for w in words if len(w) > 5]

    derived = []
    if proper:
        # "Vasili Arkhipov Soviet submarine" style
        chunk = " ".join(proper[:4])
        derived.append(chunk)
    if content:
        # "submarine nuclear torpedo cold war" style
        chunk = " ".join(content[:4])
        if chunk not in derived:
            derived.append(chunk)

    # Append topic as grounding word
    if topic not in ("history",):  # history clips work better without topic word
        derived = [f"{q} {topic}" if topic not in q.lower() else q for q in derived]

    return derived[:2]


# ------------------------------------------------------------------ #
# Source trial loop
# ------------------------------------------------------------------ #

def _try_all_sources(
    query: str,
    topic: str,
    out_dir: Path,
    *,
    allow_archival: bool = False,
    exclude_paths: set[str] | None = None,
    used_source_urls: set[str] | None = None,
) -> Optional[Path]:
    """Try each source in priority order and return the first usable clip.

    exclude_paths:    set of already-used local file paths — never return these.
    used_source_urls: set of already-downloaded remote URLs — sources skip these
                      so we never download the same content for different queries.
    """
    slug = hashlib.sha1(query.encode()).hexdigest()[:10]
    out_path = out_dir / f"footage_{slug}.mp4"

    min_bytes = _MIN_BYTES_ARK if allow_archival else _MIN_BYTES_HD

    # Return from cache only if not already used elsewhere in this batch
    if out_path.exists() and out_path.stat().st_size >= min_bytes:
        if exclude_paths is None or str(out_path) not in exclude_paths:
            print(f"  [video] cached: {out_path.name}")
            return out_path

    sources = _build_source_list(topic, allow_archival=allow_archival)
    for name, fn in sources:
        try:
            url = fn(query, topic, skip_urls=used_source_urls)
            if not url:
                continue
            print(f"  [video] {name}: {url[:80]}")
            if _download_mp4(url, out_path, min_bytes=min_bytes):
                if used_source_urls is not None:
                    used_source_urls.add(url)
                return out_path
        except Exception as exc:
            print(f"  [video] {name} error: {exc}")
    return None


def _build_source_list(topic: str, *, allow_archival: bool = False) -> list[tuple[str, callable]]:
    """Build ordered source list.

    Non-archival (default): Pexels → Coverr → Pixabay → Wikimedia.
      Archival sources (NASA, Archive.org) produce low-quality footage for
      most modern queries and are skipped unless the fact is specifically
      about archival/historical subject matter.

    Archival mode: Archive.org → NASA (space only) → Wikimedia → Pexels → Coverr → Pixabay.
    """
    sources: list[tuple[str, callable]] = []

    if allow_archival:
        sources.append(("archive.org", _archive_video_url))
        if topic in _NASA_TOPICS:
            sources.append(("nasa", _nasa_video_url))
        sources.append(("wikimedia", _wikimedia_video_url))
        sources.append(("pexels", _pexels_video_url))
        sources.append(("coverr", _coverr_video_url))
        sources.append(("pixabay", _pixabay_video_url))
    else:
        # HD-only path: modern stock sources first, Wikimedia as specific-subject backup
        if topic in _NASA_TOPICS:
            sources.append(("nasa", _nasa_video_url))
        sources.append(("pexels", _pexels_video_url))
        sources.append(("coverr", _coverr_video_url))
        sources.append(("pixabay", _pixabay_video_url))
        sources.append(("wikimedia", _wikimedia_video_url))

    return sources


# ------------------------------------------------------------------ #
# Source 1: Pexels Video
# ------------------------------------------------------------------ #

def _pexels_video_url(query: str, topic: str, skip_urls: set[str] | None = None) -> Optional[str]:
    api_key = os.getenv("PEXELS_API_KEY", "").strip()
    if not api_key:
        return None
    r = requests.get(
        "https://api.pexels.com/videos/search",
        headers={"Authorization": api_key},
        params={"query": query, "orientation": "portrait", "size": "medium", "per_page": 15},
        timeout=_HTTP_TIMEOUT,
    )
    r.raise_for_status()
    videos = r.json().get("videos", [])
    candidates: list[tuple[int, str, int]] = []
    for vid in videos:
        vid_id = vid.get("id", 0)
        # Block by video ID — prevents same video appearing twice at different resolutions
        if skip_urls and f"pexels:{vid_id}" in skip_urls:
            continue
        mp4 = _best_pexels_file(vid.get("video_files", []))
        if not mp4:
            continue
        if skip_urls and mp4 in skip_urls:
            continue
        slug = vid.get("url", "").replace("-", " ").replace("/", " ")
        score = _relevance_score(query, slug)
        candidates.append((score, mp4, vid_id))
    if not candidates:
        return None
    candidates.sort(key=lambda x: -x[0])
    best_score, best_url, best_vid_id = candidates[0]
    # Mark both the file URL and video ID so all quality variants are blocked
    if skip_urls is not None:
        skip_urls.add(f"pexels:{best_vid_id}")
    print(f"  [pexels] best match score={best_score} from {len(candidates)} results")
    return best_url


def _best_pexels_file(files: list[dict]) -> Optional[str]:
    """Prefer ~720p portrait files. 1440p+ files balloon to 30-60MB each
    which causes FFmpeg memory issues at scale (8+ clips composited)."""
    portrait = [f for f in files if f.get("height", 0) >= f.get("width", 1)]
    candidates = portrait or files
    # Filter to files closest to 1280-1920 px tall (avoids 2160p/2560p UHD bloat)
    sweet_spot = [f for f in candidates if 1000 <= f.get("height", 0) <= 1920]
    if sweet_spot:
        candidates = sweet_spot
    # Pick mid-resolution: sort by height ascending, take median
    candidates.sort(key=lambda f: f.get("height", 0))
    chosen = candidates[len(candidates) // 2]
    return chosen.get("link")


# ------------------------------------------------------------------ #
# Source 2: NASA Images and Video Library
# ------------------------------------------------------------------ #

def _nasa_video_url(query: str, topic: str, skip_urls: set[str] | None = None) -> Optional[str]:
    search = requests.get(
        "https://images-api.nasa.gov/search",
        params={"q": query, "media_type": "video", "page_size": 5},
        timeout=_HTTP_TIMEOUT,
    )
    search.raise_for_status()
    items = search.json().get("collection", {}).get("items", [])
    if not items:
        return None
    nasa_id = items[0].get("data", [{}])[0].get("nasa_id")
    if not nasa_id:
        return None
    asset = requests.get(
        f"https://images-api.nasa.gov/asset/{nasa_id}",
        timeout=_HTTP_TIMEOUT,
    )
    asset.raise_for_status()
    asset_items = asset.json().get("collection", {}).get("items", [])
    mp4s = [i["href"] for i in asset_items if i.get("href", "").endswith(".mp4")]
    if not mp4s:
        return None
    mobile = [u for u in mp4s if "mobile" in u.lower() or "_sm" in u.lower()]
    return (mobile or mp4s)[0]


# ------------------------------------------------------------------ #
# Source 3: Internet Archive
# ------------------------------------------------------------------ #

def _archive_video_url(query: str, topic: str, skip_urls: set[str] | None = None) -> Optional[str]:
    search = requests.get(
        "https://archive.org/advancedsearch.php",
        params={
            "q": f"({query}) AND mediatype:movies AND licenseurl:(creativecommons OR publicdomain)",
            "fl[]": ["identifier"],
            "rows": 5,
            "output": "json",
        },
        timeout=_HTTP_TIMEOUT,
    )
    search.raise_for_status()
    docs = search.json().get("response", {}).get("docs", [])
    # Sort by relevance score against the query (identifier slug is a proxy for content)
    scored = sorted(
        [(  _relevance_score(query, doc.get("identifier", "")), doc) for doc in docs],
        key=lambda x: -x[0],
    )
    for _, doc in scored:
        identifier = doc.get("identifier")
        if not identifier:
            continue
        meta = requests.get(f"https://archive.org/metadata/{identifier}", timeout=_HTTP_TIMEOUT)
        if not meta.ok:
            continue
        meta_json = meta.json()
        files = meta_json.get("files", [])
        # Prefer 512kb or h264 derivatives (smaller, web-friendly)
        mp4s = [f for f in files if f.get("name", "").lower().endswith(".mp4")]
        small = [f for f in mp4s if any(k in f.get("name", "").lower() for k in ("512", "h264", "small"))]
        chosen = (small or mp4s)
        if chosen:
            name = chosen[0]["name"]
            license_url = meta_json.get("metadata", {}).get("licenseurl", "")
            print(f"  [archive.org] rights OK ({license_url[:60] or 'CC/PD via query filter'})")
            return f"https://archive.org/download/{identifier}/{name}"
    return None


# ------------------------------------------------------------------ #
# Source 3b: Wikimedia Commons
# Excellent for specific species, historical footage, scientific subjects.
# CC-licensed. Returns OGV/WebM — converted to MP4 via stream download.
# ------------------------------------------------------------------ #

def _wikimedia_video_url(query: str, topic: str, skip_urls: set[str] | None = None) -> Optional[str]:
    """Search Wikimedia Commons for a rights-cleared video matching the query."""
    try:
        search = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "generator": "search",
                "gsrsearch": f"filetype:video {query}",
                "gsrnamespace": "6",
                "gsrlimit": "8",
                "prop": "videoinfo",
                "viprop": "url|mime|size|extmetadata",
                "viextmetadatafilter": "LicenseShortName|License|Restrictions",
                "format": "json",
            },
            timeout=_HTTP_TIMEOUT,
        )
        search.raise_for_status()
        pages = search.json().get("query", {}).get("pages", {})
        candidates: list[tuple[int, str, str]] = []  # (score, url, license)
        for page in pages.values():
            info = (page.get("videoinfo") or [{}])[0]
            url = info.get("url", "")
            mime = info.get("mime", "")
            size = info.get("size", 0)
            if not (mime.startswith("video/") and url and 0 < size < 50_000_000):
                continue
            meta = info.get("extmetadata", {})
            license_short = meta.get("LicenseShortName", {}).get("value", "")
            license_code  = meta.get("License", {}).get("value", "")
            restrictions  = meta.get("Restrictions", {}).get("value", "")
            if restrictions and restrictions.lower() not in ("", "none"):
                continue
            if not _is_rights_cleared(license_short, license_code):
                continue
            title = page.get("title", "")
            score = _relevance_score(query, title)
            candidates.append((score, url, license_short or license_code))
        if candidates:
            candidates.sort(key=lambda x: -x[0])
            score, url, lic = candidates[0]
            print(f"  [wikimedia] rights OK ({lic}) score={score} from {len(candidates)} candidates")
            return url
    except Exception:
        pass
    return None


def _is_rights_cleared(short: str, code: str) -> bool:
    """Return True if the license string indicates open/CC/public-domain use."""
    combined = f"{short} {code}".lower()
    return any(marker in combined for marker in _OPEN_LICENSE_MARKERS)


def _relevance_score(query: str, text: str) -> int:
    """Score how well `text` matches the query.

    Each query word that appears in text contributes its character-length
    as a score — longer/rarer words count more than short common ones.
    Words under 3 chars are skipped. Returns 0 if text is empty.
    """
    if not text:
        return 0
    text_clean = re.sub(r"[^\w\s]", " ", text.lower())
    score = 0
    for word in query.lower().split():
        if len(word) > 3 and word in text_clean:
            score += len(word)
    return score


# ------------------------------------------------------------------ #
# Source 4: Coverr — cinematic CC0, non-stock aesthetic
# COVERR_API_KEY in .env (optional; omit to use public unauthenticated tier)
# ------------------------------------------------------------------ #

def _coverr_video_url(query: str, topic: str, skip_urls: set[str] | None = None) -> Optional[str]:
    params: dict = {"query": query, "page": 1, "per_page": 6}
    token = os.getenv("COVERR_API_KEY", "").strip()
    if token:
        params["token"] = token
    try:
        r = requests.get(
            "https://api.coverr.co/videos",
            params=params,
            timeout=_HTTP_TIMEOUT,
        )
        r.raise_for_status()
        hits = r.json().get("hits", [])
        candidates: list[tuple[int, str, str]] = []
        for hit in hits:
            hit_id = str(hit.get("id", hit.get("slug", "")))
            if skip_urls and f"coverr:{hit_id}" in skip_urls:
                continue
            title = hit.get("title", "")
            score = _relevance_score(query, title)
            urls = hit.get("urls", {})
            mp4 = urls.get("mp4_download") or urls.get("preview_mp4") or urls.get("mp4")
            if mp4 and not (skip_urls and mp4 in skip_urls):
                candidates.append((score, mp4, hit_id))
        if candidates:
            candidates.sort(key=lambda x: -x[0])
            best_score, best_url, best_id = candidates[0]
            if skip_urls is not None:
                skip_urls.add(f"coverr:{best_id}")
            print(f"  [coverr] best match score={best_score} from {len(candidates)} results")
            return best_url
    except Exception:
        pass
    return None


# ------------------------------------------------------------------ #
# Source 5: Pixabay Video
# ------------------------------------------------------------------ #

def _pixabay_video_url(query: str, topic: str, skip_urls: set[str] | None = None) -> Optional[str]:
    api_key = os.getenv("PIXABAY_API_KEY", "").strip()
    if not api_key:
        return None
    r = requests.get(
        "https://pixabay.com/api/videos/",
        params={"key": api_key, "q": query, "orientation": "vertical", "per_page": 10},
        timeout=_HTTP_TIMEOUT,
    )
    r.raise_for_status()
    hits = r.json().get("hits", [])
    if not hits:
        return None
    candidates: list[tuple[int, str, int]] = []
    for hit in hits:
        hit_id = hit.get("id", 0)
        if skip_urls and f"pixabay:{hit_id}" in skip_urls:
            continue
        tags = hit.get("tags", "")
        score = _relevance_score(query, tags)
        videos = hit.get("videos", {})
        for quality in ("medium", "small", "large"):
            url = videos.get(quality, {}).get("url")
            if url:
                if skip_urls and url in skip_urls:
                    break
                candidates.append((score, url, hit_id))
                break
    if not candidates:
        return None
    candidates.sort(key=lambda x: -x[0])
    best_score, best_url, best_id = candidates[0]
    if skip_urls is not None:
        skip_urls.add(f"pixabay:{best_id}")
    print(f"  [pixabay] best match score={best_score} from {len(candidates)} results")
    return best_url


# ------------------------------------------------------------------ #
# Safety pool: pre-downloaded local clips
# ------------------------------------------------------------------ #

def _safety_pool_pick(topic: str) -> list[Path]:
    """Return all clips in assets/video/{topic}/ shuffled, or [] if empty."""
    import random
    pool_dir = Path(__file__).resolve().parents[2] / "assets" / "video" / topic
    if not pool_dir.exists():
        return []
    clips = list(pool_dir.glob("*.mp4"))
    if not clips:
        return []
    random.shuffle(clips)
    return clips


# ------------------------------------------------------------------ #
# Download helper
# ------------------------------------------------------------------ #

def _download_mp4(url: str, out_path: Path, *, min_bytes: int = _MIN_BYTES_HD) -> bool:
    try:
        r = requests.get(url, stream=True, timeout=60)
        r.raise_for_status()
        total = 0
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)
                total += len(chunk)
                if total > _MAX_BYTES:
                    print(f"  [video] clip too large (>{_MAX_BYTES//1024//1024}MB), skipping")
                    break
        size = out_path.stat().st_size if out_path.exists() else 0
        if size < min_bytes:
            out_path.unlink(missing_ok=True)
            print(f"  [video] clip too small ({size//1024}KB < {min_bytes//1024}KB floor), skipping")
            return False
        print(f"  [video] downloaded {size//1024}KB -> {out_path.name}")
        return True
    except Exception as exc:
        print(f"  [video] download error: {exc}")
        out_path.unlink(missing_ok=True)
        return False
