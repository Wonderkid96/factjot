"""Multi-source portrait video finder for Reels composition.

Selection strategy (5 layers - tried in order, first hit wins):
  0. Entity sources      - Wikipedia lead image, Wikimedia Commons files,
                           Internet Archive exact-phrase search (entity-specific)
  1. Curated image_hint  - manually written, most specific
  2. Derived queries     - auto-extracted subjects from the fact claim
  3. Topic-generic       - atmospheric fallback for the topic category
  4. Safety pool         - pre-downloaded local clips in assets/video/{topic}/

Sources tried per query (in priority order):
  • Pexels Video          - portrait HD, already-keyed
  • NASA media API        - real footage for space facts (free, no key)
  • Internet Archive      - public-domain newsreels for history facts
  • Pixabay Video         - CC0 fallback (PIXABAY_API_KEY in .env)

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
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

_HTTP_TIMEOUT = 10   # was 20 - trimmed to cut Archive.org timeout loops on misses
_MAX_BYTES = 15 * 1024 * 1024   # 15 MB ceiling per clip
_MIN_BYTES_HD  = 2_000_000      # 2 MB floor - filters out sub-3s clips at typical bitrates
_MIN_BYTES_ARK = 50_000         # 50 KB floor for archival/historical content
_MIN_CLIP_DURATION_S = 5.0      # minimum: clips shorter than this may loop briefly but are usable

# Topics where Archive.org is a useful fallback even without allow_archival=True
_ARCHIVE_ELIGIBLE_TOPICS = {"history", "earth", "science"}


def _extract_hint_keywords(hint: str, max_words: int = 3) -> list[str]:
    """Extract the most meaningful individual words from an image hint.

    Prioritises proper nouns (capitalised, likely place/entity names), then
    long content words. Reuses the existing _STOP frozenset defined below.
    Used to generate targeted Wikimedia searches when compound phrase queries
    fail to find relevant footage.
    """
    words = hint.split()
    proper  = [w for w in words if w[0].isupper() and len(w) > 4 and w.lower() not in _STOP]
    content = [w for w in words if len(w) > 4 and w.lower() not in _STOP and w not in proper]
    return (proper + content)[:max_words]


def _topic_allows_archival(topic: str, allow_archival: bool) -> bool:
    """Return True if archival sources and their lower quality floor should apply."""
    return allow_archival or topic in _ARCHIVE_ELIGIBLE_TOPICS


_IMAGE_MAGIC = {
    b"\xff\xd8\xff":       "jpeg",  # JPEG
    b"\x89PNG\r\n\x1a\n":  "png",   # PNG
    b"RIFF":               "webp",  # WebP (followed by ....WEBP)
    b"GIF87a":             "gif",   # GIF87
    b"GIF89a":             "gif",   # GIF89
}


def _valid_image(path: Path) -> bool:
    """Return True if path starts with a known image magic-byte signature.

    Pure-Python, no external binary. Rejects DjVu-as-PNG (starts with
    'AT&T' or 'FORM'), truncated files, and any non-image content that
    has been given a .jpg/.png extension by Wikimedia/Wikipedia.
    """
    try:
        with open(path, "rb") as f:
            header = f.read(12)
        if not header:
            return False
        for magic, fmt in _IMAGE_MAGIC.items():
            if header.startswith(magic):
                if fmt == "webp":
                    return header[8:12] == b"WEBP"
                return True
        return False
    except Exception:
        return False

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
    "science":    ["laboratory experiment science", "microscope cells research", "scientific discovery visualization"],
    "earth":      ["aerial landscape drone nature", "mountain clouds time lapse", "volcano lava flowing"],
}

# Topic routing for specialist sources
# NASA: space only - earth observation footage is scientific visualisation, not cinematic b-roll
_NASA_TOPICS = {"space"}
# Archive.org: archival/historical content only (allow_archival=True facts)
# For most facts it returns old SD footage that fails the quality floor.

# Rights markers that indicate open/CC/public-domain content
_OPEN_LICENSE_MARKERS = (
    "cc0", "cc-by", "cc by", "public domain", "pd ", "pd-", "pdm",
    "creativecommons", "no known copyright",
)

# Filenames/descriptions containing any of these strings are skipped
_NSFW_BLOCK_TERMS = ("nsfw", "explicit", "nude", "nudity", "porn", "xxx", "adult", "erotic")

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
    blocked_filenames: set[str] | None = None,
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
    # Filename-level dedup: blocks clips whose content appeared in a previous
    # reel even if the download URL has changed (e.g. different resolution).
    _blocked_stems: set[str] = set(blocked_filenames or ())
    safety = _safety_pool_pick(topic) or []
    safety_idx = 0

    # Tier 0: entity-specific sources (Wikipedia, Wikimedia Commons, Archive.org)
    # Search using the named person/event extracted from the claim first --
    # this finds the actual photo of Phineas Gage, the portrait of Arkhipov,
    # the historical photo of the Radium Girls, etc. Fall back to image_hint
    # if the claim has no extractable named entity.
    from src.research.narrative_beats import extract_entities
    _claim_ents = extract_entities(claim)
    _entity_terms: list[str] = []
    if _claim_ents.proper_nouns:
        # Primary: first named person/place (e.g. "Phineas Gage")
        _entity_terms.append(" ".join(_claim_ents.proper_nouns[:2]))
    if image_hint and (not _entity_terms or image_hint != _entity_terms[0]):
        _entity_terms.append(image_hint)

    # Hard cap: max 2 entity images total across ALL search terms.
    # More than 2 consecutive stills = slideshow feel. B-roll fills the rest.
    _ENTITY_CAP = 2
    for _et in _entity_terms:
        if len(clips) >= _ENTITY_CAP:
            break
        _ec = _entity_sources(
            _et, out_dir,
            used_source_urls=used_source_urls,
            used_paths=used_paths,
            max_clips=_ENTITY_CAP - len(clips),
        )
        for ec in _ec:
            if len(clips) < count and str(ec) not in used_paths:
                clips.append(ec)
                used_paths.add(str(ec))
                print(f"  [video] ENTITY-0  ✓ {ec.name}")

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
            if _blocked_stems and path.stem in _blocked_stems:
                print(f"  [video] {label} SKIP {path.name} (filename used in a previous reel)")
                path.unlink(missing_ok=True)
                continue
            clips.append(path)
            used_paths.add(str(path))
            _blocked_stems.add(path.stem)   # block within this run too
            print(f"  [video] {label} ✓ {path.name}")

    # Last-resort keyword decomposition: if still short after all queries, try
    # individual meaningful words from image_hint against Wikimedia Commons only.
    # This is the final chance to find the actual subject (e.g. "Darvaza" alone)
    # before falling back to the generic safety pool.
    if len(clips) < count and image_hint:
        _lr_tried = set(e.lower() for e in (used_paths or set()))
        for _kw in _extract_hint_keywords(image_hint, max_words=3):
            if len(clips) >= count:
                break
            print(f"  [video] LAST-RESORT keyword: {_kw!r}")
            _lr = _wikimedia_entity_files(_kw, out_dir, used_source_urls=used_source_urls)
            if _lr and str(_lr) not in used_paths:
                if not (_blocked_stems and _lr.stem in _blocked_stems):
                    clips.append(_lr)
                    used_paths.add(str(_lr))
                    _blocked_stems.add(_lr.stem)
                    print(f"  [video] LAST-RESORT ✓ {_lr.name}")

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

    exclude_paths:    set of already-used local file paths - never return these.
    used_source_urls: set of already-downloaded remote URLs - sources skip these
                      so we never download the same content for different queries.
    """
    slug = hashlib.sha1(query.encode()).hexdigest()[:10]
    out_path = out_dir / f"footage_{slug}.mp4"

    _use_archival = _topic_allows_archival(topic, allow_archival)
    min_bytes = _MIN_BYTES_ARK if _use_archival else _MIN_BYTES_HD

    # Return from cache only if not already used elsewhere in this batch
    if out_path.exists() and out_path.stat().st_size >= min_bytes:
        if exclude_paths is None or str(out_path) not in exclude_paths:
            print(f"  [video] cached: {out_path.name}")
            return out_path

    sources = _build_source_list(topic, allow_archival=_use_archival)
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


def _build_source_list(topic: str, *, allow_archival: bool = False) -> list[tuple[str, Callable]]:
    """Build ordered source list.

    Non-archival (default): Pexels → Coverr → Pixabay → Wikimedia.
      For _ARCHIVE_ELIGIBLE_TOPICS (history, earth, science), Archive.org is
      appended last as a fallback — only reached when all stock sources fail.

    Archival mode: Archive.org → NASA (space only) → Wikimedia → Pexels → Coverr → Pixabay.
    """
    sources: list[tuple[str, Callable]] = []

    if allow_archival:
        sources.append(("archive.org", _archive_video_url))
        if topic in _NASA_TOPICS:
            sources.append(("nasa", _nasa_video_url))
        sources.append(("wikimedia", _wikimedia_video_url))
        sources.append(("pexels", _pexels_video_url))
        sources.append(("coverr", _coverr_video_url))
        sources.append(("pixabay", _pixabay_video_url))
    else:
        # HD-first path: stock sources first, Wikimedia as specific-subject backup.
        if topic in _NASA_TOPICS:
            sources.append(("nasa", _nasa_video_url))
        sources.append(("pexels", _pexels_video_url))
        sources.append(("coverr", _coverr_video_url))
        sources.append(("pixabay", _pixabay_video_url))
        sources.append(("wikimedia", _wikimedia_video_url))
        # Archive.org as last resort for topics with useful archival holdings,
        # even without an explicit allow_archival flag. Placed last so it only
        # fires after all stock sources fail — avoids slowing the common case.
        if topic in _ARCHIVE_ELIGIBLE_TOPICS:
            sources.append(("archive.org", _archive_video_url))

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
        # Block by video ID - prevents same video appearing twice at different resolutions
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
    print(f"  [pexels] best match score={best_score} from {len(candidates)} results")
    if best_score == 0:
        print(f"  [pexels] score=0 — skipping (no relevant match)")
        return None
    # Mark both the file URL and video ID so all quality variants are blocked
    if skip_urls is not None:
        skip_urls.add(f"pexels:{best_vid_id}")
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
# CC-licensed. Returns OGV/WebM - converted to MP4 via stream download.
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
    as a score - longer/rarer words count more than short common ones.
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
# Source 4: Coverr - cinematic CC0, non-stock aesthetic
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
            print(f"  [coverr] best match score={best_score} from {len(candidates)} results")
            if best_score == 0:
                print(f"  [coverr] score=0 — skipping (no relevant match)")
                return None
            if skip_urls is not None:
                skip_urls.add(f"coverr:{best_id}")
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
    print(f"  [pixabay] best match score={best_score} from {len(candidates)} results")
    if best_score == 0:
        print(f"  [pixabay] score=0 — skipping (no relevant match)")
        return None
    if skip_urls is not None:
        skip_urls.add(f"pixabay:{best_id}")
    return best_url


# ------------------------------------------------------------------ #
# Entity-specific sources - run BEFORE generic B-roll queries
# These target the named entity directly (via image_hint) using free
# encyclopaedic APIs.  No API keys required.
# ------------------------------------------------------------------ #

def _nsfw_safe(name: str, description: str = "") -> bool:
    """Return True if the filename and description are free of NSFW markers."""
    combined = f"{name} {description}".lower()
    return not any(term in combined for term in _NSFW_BLOCK_TERMS)


def _wikipedia_lead_image(entity: str, out_dir: Path, *, used_source_urls: set[str] | None = None) -> Optional[Path]:
    """Fetch the Wikipedia article lead image for `entity` as a still frame.

    Returns the downloaded image path (PNG/JPG) on success, None otherwise.
    Still images work fine with FFmpeg's stream_loop -1 and require no duration
    check -- the compositor loops them to fill clip length.
    """
    # Normalise entity to title case for URL embedding
    title = entity.strip().replace(" ", "_")
    try:
        r = requests.get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}",
            headers={"User-Agent": "factjot-bot/1.0 (tobyjohnsonemail@gmail.com)"},
            timeout=_HTTP_TIMEOUT,
        )
        if not r.ok:
            return None
        data = r.json()
        img_info = data.get("originalimage") or data.get("thumbnail")
        if not img_info:
            return None
        img_url = img_info.get("source", "")
        if not img_url:
            return None
        if used_source_urls and img_url in used_source_urls:
            return None
        # Basic NSFW check on the URL itself
        if not _nsfw_safe(img_url):
            print(f"  [wikipedia] skipped NSFW-flagged URL")
            return None
        # Determine extension
        ext = "jpg"
        lower_url = img_url.lower().split("?")[0]
        if lower_url.endswith(".png"):
            ext = "png"
        elif lower_url.endswith(".gif"):
            ext = "gif"
        slug = hashlib.sha1(img_url.encode()).hexdigest()[:10]
        out_path = out_dir / f"wiki_lead_{slug}.{ext}"
        print(f"  [wikipedia] lead image: {img_url[:80]}")
        r2 = requests.get(
            img_url,
            headers={"User-Agent": "factjot-bot/1.0 (tobyjohnsonemail@gmail.com)"},
            stream=True, timeout=60,
        )
        r2.raise_for_status()
        total = 0
        with open(out_path, "wb") as f:
            for chunk in r2.iter_content(chunk_size=65536):
                f.write(chunk)
                total += len(chunk)
        size = out_path.stat().st_size if out_path.exists() else 0
        if size < _MIN_BYTES_ARK:
            out_path.unlink(missing_ok=True)
            print(f"  [wikipedia] image too small ({size//1024}KB), skipping")
            return None
        print(f"  [wikipedia] downloaded lead image {size//1024}KB -> {out_path.name}")
        if not _valid_image(out_path):
            out_path.unlink(missing_ok=True)
            print(f"  [wikipedia] image corrupt or 0x0 dimensions — skipping")
            return None
        if used_source_urls is not None:
            used_source_urls.add(img_url)
        return out_path
    except Exception as exc:
        print(f"  [wikipedia] error: {exc}")
        return None


_WIKI_IMAGE_SKIP = frozenset({
    "flag", "icon", "logo", "banner", "symbol", "map", "button",
    "blank", "arrow", "stub", "signature", "badge", "seal", "coat",
    "emblem", "edit", "question", "portal", "commons", "wikimedia",
})


def _wikipedia_article_images(
    entity: str,
    out_dir: Path,
    *,
    used_source_urls: set[str] | None = None,
    max_images: int = 3,
) -> list[Path]:
    """Fetch up to max_images images from a Wikipedia article (beyond the lead).

    Uses MediaWiki `prop=images` to list all image titles in the article,
    then resolves their download URLs via `prop=imageinfo`. Skips icons,
    flags, logos, SVGs, and images smaller than 300px on either side.
    Returns validated paths (non-zero dimensions, non-corrupt).
    """
    title = entity.strip().replace(" ", "_")
    results: list[Path] = []
    try:
        # Step 1: list all image titles referenced in the article
        r = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query", "titles": title,
                "prop": "images", "imlimit": "15",
                "format": "json",
            },
            headers={"User-Agent": "factjot-bot/1.0 (tobyjohnsonemail@gmail.com)"},
            timeout=_HTTP_TIMEOUT,
        )
        if not r.ok:
            return results
        pages = r.json().get("query", {}).get("pages", {})
        img_titles: list[str] = []
        for page in pages.values():
            for img in page.get("images", []):
                t = img.get("title", "")
                lower = t.lower()
                # Keep only jpg/png, skip utility images
                if not any(lower.endswith(ext) for ext in (".jpg", ".jpeg", ".png")):
                    continue
                if any(skip in lower for skip in _WIKI_IMAGE_SKIP):
                    continue
                img_titles.append(t)

        # Step 2: resolve actual download URLs and download each
        for img_title in img_titles:
            if len(results) >= max_images:
                break
            try:
                r2 = requests.get(
                    "https://en.wikipedia.org/w/api.php",
                    params={
                        "action": "query", "titles": img_title,
                        "prop": "imageinfo", "iiprop": "url|size|mime",
                        "format": "json",
                    },
                    headers={"User-Agent": "factjot-bot/1.0 (tobyjohnsonemail@gmail.com)"},
                    timeout=_HTTP_TIMEOUT,
                )
                if not r2.ok:
                    continue
                for pg in r2.json().get("query", {}).get("pages", {}).values():
                    info = pg.get("imageinfo", [{}])[0]
                    url  = info.get("url", "")
                    if not url:
                        continue
                    if info.get("width", 0) < 300 or info.get("height", 0) < 300:
                        continue
                    if used_source_urls and url in used_source_urls:
                        continue
                    if not _nsfw_safe(url):
                        continue
                    ext  = "png" if url.lower().split("?")[0].endswith(".png") else "jpg"
                    slug = hashlib.sha1(url.encode()).hexdigest()[:10]
                    out_path = out_dir / f"wiki_article_{slug}.{ext}"
                    if out_path.exists() and out_path.stat().st_size > _MIN_BYTES_ARK:
                        if _valid_image(out_path):
                            print(f"  [wikipedia] cached article image -> {out_path.name}")
                            if used_source_urls is not None:
                                used_source_urls.add(url)
                            results.append(out_path)
                            break
                    r3 = requests.get(
                        url,
                        headers={"User-Agent": "factjot-bot/1.0 (tobyjohnsonemail@gmail.com)"},
                        stream=True, timeout=60,
                    )
                    r3.raise_for_status()
                    with open(out_path, "wb") as f:
                        for chunk in r3.iter_content(65536):
                            f.write(chunk)
                    size = out_path.stat().st_size if out_path.exists() else 0
                    if size < _MIN_BYTES_ARK:
                        out_path.unlink(missing_ok=True)
                        continue
                    if not _valid_image(out_path):
                        out_path.unlink(missing_ok=True)
                        continue
                    print(f"  [wikipedia] article image {size//1024}KB -> {out_path.name}")
                    if used_source_urls is not None:
                        used_source_urls.add(url)
                    results.append(out_path)
                    break
            except Exception:
                continue
        time.sleep(0.3)
    except Exception as exc:
        print(f"  [wikipedia-article] error: {exc}")
    return results


def _wikimedia_entity_files(
    entity: str, out_dir: Path, *, used_source_urls: set[str] | None = None
) -> Optional[Path]:
    """Search Wikimedia Commons for files (video preferred, image fallback) matching `entity`.

    Uses the MediaWiki search API then resolves actual file URLs via imageinfo.
    Prefers video files; falls back to still images.  CC/PD licensed only.
    50 KB minimum (archival threshold).
    """
    try:
        # Step 1: search for files in File namespace (ns=6)
        search_r = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": entity,
                "srnamespace": "6",
                "srlimit": "12",
                "format": "json",
            },
            headers={"User-Agent": "factjot-bot/1.0 (tobyjohnsonemail@gmail.com)"},
            timeout=_HTTP_TIMEOUT,
        )
        search_r.raise_for_status()
        results = search_r.json().get("query", {}).get("search", [])
        if not results:
            return None

        # Step 2: resolve file URLs in one batch query (up to 12 titles)
        titles_pipe = "|".join(r["title"] for r in results)
        info_r = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "titles": titles_pipe,
                "prop": "imageinfo",
                "iiprop": "url|size|mime|extmetadata",
                "iiextmetadatafilter": "LicenseShortName|License|Restrictions",
                "format": "json",
            },
            headers={"User-Agent": "factjot-bot/1.0 (tobyjohnsonemail@gmail.com)"},
            timeout=_HTTP_TIMEOUT,
        )
        info_r.raise_for_status()
        pages = info_r.json().get("query", {}).get("pages", {})

        video_candidates: list[tuple[int, str, str]] = []
        image_candidates: list[tuple[int, str, str]] = []

        for page in pages.values():
            info = (page.get("imageinfo") or [{}])[0]
            url = info.get("url", "")
            mime = info.get("mime", "")
            size = info.get("size", 0)
            title = page.get("title", "")

            if not url or size < _MIN_BYTES_ARK:
                continue
            if size > _MAX_BYTES:
                continue
            if not _nsfw_safe(title):
                continue
            if used_source_urls and url in used_source_urls:
                continue

            meta = info.get("extmetadata", {})
            license_short = meta.get("LicenseShortName", {}).get("value", "")
            license_code  = meta.get("License", {}).get("value", "")
            restrictions  = meta.get("Restrictions", {}).get("value", "")
            if restrictions and restrictions.lower() not in ("", "none"):
                continue
            if not _is_rights_cleared(license_short, license_code):
                continue

            score = _relevance_score(entity, title)
            lic = license_short or license_code

            if mime.startswith("video/"):
                video_candidates.append((score, url, lic))
            elif mime.startswith("image/"):
                image_candidates.append((score, url, lic))

        # Prefer video over image; fall back to image still
        for candidates, kind in ((video_candidates, "video"), (image_candidates, "image")):
            if not candidates:
                continue
            candidates.sort(key=lambda x: -x[0])
            score, url, lic = candidates[0]
            print(f"  [wikimedia-entity] {kind} rights OK ({lic}) score={score} from {len(candidates)} candidates")

            ext = "mp4"
            lower = url.lower().split("?")[0]
            if kind == "image":
                ext = "jpg" if lower.endswith(".jpg") or lower.endswith(".jpeg") else "png"
            elif ".webm" in lower:
                ext = "webm"
            elif ".ogv" in lower or ".ogg" in lower:
                ext = "ogv"

            slug = hashlib.sha1(url.encode()).hexdigest()[:10]
            out_path = out_dir / f"wm_entity_{slug}.{ext}"

            r3 = requests.get(
                url,
                headers={"User-Agent": "factjot-bot/1.0 (tobyjohnsonemail@gmail.com)"},
                stream=True, timeout=60,
            )
            r3.raise_for_status()
            total = 0
            with open(out_path, "wb") as f:
                for chunk in r3.iter_content(chunk_size=65536):
                    f.write(chunk)
                    total += len(chunk)

            size_dl = out_path.stat().st_size if out_path.exists() else 0
            if size_dl < _MIN_BYTES_ARK:
                out_path.unlink(missing_ok=True)
                continue

            # Duration check only for actual video files
            if kind == "video":
                dur = _probe_duration(out_path)
                if dur is not None and dur < _MIN_CLIP_DURATION_S:
                    out_path.unlink(missing_ok=True)
                    print(f"  [wikimedia-entity] clip too short ({dur:.1f}s), skipping")
                    continue

            # For still images, validate dimensions before accepting
            if kind != "video" and not _valid_image(out_path):
                out_path.unlink(missing_ok=True)
                print(f"  [wikimedia-entity] image corrupt or 0x0 — skipping")
                continue
            print(f"  [wikimedia-entity] downloaded {size_dl//1024}KB -> {out_path.name}")
            if used_source_urls is not None:
                used_source_urls.add(url)
            return out_path

    except Exception as exc:
        print(f"  [wikimedia-entity] error: {exc}")
    return None


def _archive_entity_search(
    entity: str, out_dir: Path, *, used_source_urls: set[str] | None = None
) -> Optional[Path]:
    """Search Internet Archive for the specific entity using exact-phrase matching.

    Uses quoted query for precision.  Falls back to unquoted if no results.
    50 KB minimum.  Prefers h264/512kb web derivatives.
    """
    for q_form in (f'"{entity}"', entity):
        try:
            search_r = requests.get(
                "https://archive.org/advancedsearch.php",
                params={
                    "q": f"({q_form}) AND mediatype:movies AND licenseurl:(creativecommons OR publicdomain)",
                    "fl[]": ["identifier", "title", "description"],
                    "rows": "8",
                    "output": "json",
                },
                timeout=_HTTP_TIMEOUT,
            )
            search_r.raise_for_status()
            docs = search_r.json().get("response", {}).get("docs", [])
            if not docs:
                continue

            scored = sorted(
                [(_relevance_score(entity, f"{doc.get('title', '')} {doc.get('description', '')} {doc.get('identifier', '')}"), doc)
                 for doc in docs],
                key=lambda x: -x[0],
            )

            for score, doc in scored:
                identifier = doc.get("identifier")
                if not identifier:
                    continue
                if not _nsfw_safe(identifier, doc.get("description", "") or ""):
                    print(f"  [archive-entity] skipped NSFW item: {identifier}")
                    continue

                meta_r = requests.get(
                    f"https://archive.org/metadata/{identifier}",
                    timeout=_HTTP_TIMEOUT,
                )
                if not meta_r.ok:
                    continue
                meta_json = meta_r.json()
                files = meta_json.get("files", [])
                mp4s = [f for f in files if f.get("name", "").lower().endswith(".mp4")]
                if not mp4s:
                    continue

                # Prefer small/web-friendly derivatives
                small = [f for f in mp4s if any(k in f.get("name", "").lower() for k in ("512", "h264", "small", "mobile"))]
                chosen_files = small or mp4s

                for chosen in chosen_files:
                    name = chosen.get("name", "")
                    if not _nsfw_safe(name):
                        continue
                    url = f"https://archive.org/download/{identifier}/{name}"
                    if used_source_urls and url in used_source_urls:
                        continue

                    slug = hashlib.sha1(url.encode()).hexdigest()[:10]
                    out_path = out_dir / f"archive_entity_{slug}.mp4"

                    license_url = meta_json.get("metadata", {}).get("licenseurl", "")
                    print(f"  [archive-entity] score={score} rights OK ({license_url[:60] or 'CC/PD via query filter'}): {url[:80]}")

                    if _download_mp4(url, out_path, min_bytes=_MIN_BYTES_ARK):
                        if used_source_urls is not None:
                            used_source_urls.add(url)
                        return out_path
        except Exception as exc:
            print(f"  [archive-entity] error ({q_form!r}): {exc}")
    return None


def _entity_sources(
    entity_term: str,
    out_dir: Path,
    *,
    used_source_urls: set[str] | None = None,
    used_paths: set[str] | None = None,
    max_clips: int = 2,
) -> list[Path]:
    """Try entity-specific sources for a named entity or image_hint term.

    Attempts the full term first, then shortened variants if the full
    term yields nothing.  Returns up to `max_clips` paths.

    Order:
      1. Wikipedia lead image
      2. Wikimedia Commons (video preferred, image fallback)
      3. Internet Archive (exact phrase search)
    """
    clips: list[Path] = []
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build entity strings to try: full term, then shortened variants
    hint = entity_term.strip()
    words = hint.split()
    entities = [hint]
    if len(words) > 2:
        entities.append(" ".join(words[:3]))
    if len(words) > 3:
        entities.append(" ".join(words[:2]))

    for entity in entities:
        if len(clips) >= max_clips:
            break
        print(f"  [entity-sources] trying entity: {entity!r}")

        # 1a. Wikipedia lead image (fastest, most relevant single image)
        path = _wikipedia_lead_image(entity, out_dir, used_source_urls=used_source_urls)
        if path and (used_paths is None or str(path) not in used_paths):
            clips.append(path)
            if used_paths is not None:
                used_paths.add(str(path))
            if len(clips) >= max_clips:
                break

        # 1b. Additional Wikipedia article images (daguerreotypes, artefact photos,
        # medical illustrations etc. that live in the article body, not just the lead).
        # Fetched sparingly (max 2 extra) so the reel isn't a slideshow.
        if len(clips) < max_clips:
            extra = _wikipedia_article_images(
                entity, out_dir,
                used_source_urls=used_source_urls,
                max_images=min(2, max_clips - len(clips)),
            )
            for ep in extra:
                if len(clips) >= max_clips:
                    break
                if used_paths is None or str(ep) not in used_paths:
                    clips.append(ep)
                    if used_paths is not None:
                        used_paths.add(str(ep))

        # 2. Wikimedia Commons entity search
        path = _wikimedia_entity_files(entity, out_dir, used_source_urls=used_source_urls)
        if path and (used_paths is None or str(path) not in used_paths):
            clips.append(path)
            if used_paths is not None:
                used_paths.add(str(path))
            if len(clips) >= max_clips:
                break

        # 3. Internet Archive entity search
        path = _archive_entity_search(entity, out_dir, used_source_urls=used_source_urls)
        if path and (used_paths is None or str(path) not in used_paths):
            clips.append(path)
            if used_paths is not None:
                used_paths.add(str(path))

    # Keyword fallback: if still below cap, extract individual meaningful words
    # from the entity_term (which may be the full image_hint) and search
    # Wikimedia Commons with each one. Catches cases like "Darvaza gas crater"
    # where the compound phrase fails but "Darvaza" alone finds the real footage.
    if len(clips) < max_clips:
        _tried = set(e.lower() for e in entities)
        for _kw in _extract_hint_keywords(entity_term, max_words=3):
            if len(clips) >= max_clips:
                break
            if _kw.lower() in _tried:
                continue
            _tried.add(_kw.lower())
            print(f"  [entity-sources] wikimedia hint keyword: {_kw!r}")
            path = _wikimedia_entity_files(_kw, out_dir, used_source_urls=used_source_urls)
            if path and (used_paths is None or str(path) not in used_paths):
                clips.append(path)
                if used_paths is not None:
                    used_paths.add(str(path))

    if clips:
        print(f"  [entity-sources] found {len(clips)} entity clip(s)")
    return clips


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
# Duration probe + download helper
# ------------------------------------------------------------------ #

def _probe_duration(path: Path) -> Optional[float]:
    """Return the duration of a video file in seconds, or None if ffprobe unavailable."""
    for ffprobe in ("ffprobe", "/opt/homebrew/opt/ffmpeg-full/bin/ffprobe"):
        try:
            result = subprocess.run(
                [ffprobe, "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                capture_output=True, text=True, timeout=10,
            )
            return float(result.stdout.strip())
        except Exception:
            continue
    return None


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
        dur = _probe_duration(out_path)
        if dur is not None and dur < _MIN_CLIP_DURATION_S:
            out_path.unlink(missing_ok=True)
            print(f"  [video] clip too short ({dur:.1f}s < {_MIN_CLIP_DURATION_S}s), skipping")
            return False
        print(f"  [video] downloaded {size//1024}KB {f'({dur:.1f}s) ' if dur else ''}-> {out_path.name}")
        return True
    except Exception as exc:
        print(f"  [video] download error: {exc}")
        out_path.unlink(missing_ok=True)
        return False
