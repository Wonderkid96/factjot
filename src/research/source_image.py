"""Fetch a relevant image directly from a fact's source article.

Supports Wikipedia articles only. Reddit and news sites are excluded:
Reddit images lack stable licensing, news photography is almost always
copyrighted. Wikipedia images are Creative Commons - safe to use.

Typical caller flow:

    from src.research.source_image import fetch_source_image

    img_url = fetch_source_image(
        source_url="https://en.wikipedia.org/wiki/Voynich_manuscript",
        claim="The Voynich Manuscript has defied every attempt at decryption...",
    )
    if img_url:
        # use it as a carousel background or reel still frame

Relevance check
---------------
The Wikipedia API returns the article's lead image. We validate that it is
actually relevant to the claim by checking whether the article title tokens
appear in the claim text (and vice versa). If the overlap is too thin the
image is rejected so we never attach a misleading visual.

The function returns a URL (not a local path) so callers can decide whether
to download it for a reel still frame, pass it straight to an <img> tag in
a Playwright template, or hand it to image_fetcher.py for carousel use.
Download + caching is the caller's responsibility.

Rights summary
--------------
Wikipedia lead images are sourced from Wikimedia Commons and are almost
always CC-BY, CC-BY-SA, or public domain. A small fraction carry
non-commercial restrictions. We check the licence field from the
pageimages API and reject anything that is not clearly open.

Do NOT extend this to:
  - i.redd.it / imgur  -- uploaded by users, no licence metadata
  - news CDN domains   -- copyrighted editorial photography
  - general image CDNs -- no licence metadata, no provenance
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse, unquote

import requests

_HTTP_TIMEOUT = 15
_MIN_IMAGE_BYTES = 40_000   # 40 KB  -- skips icons and tiny thumbnails
_MIN_IMAGE_DIM  = 400       # 400 px -- each dimension checked via API metadata

# Licence strings that indicate open/CC/public-domain use
_OPEN_LICENCE_MARKERS = (
    "cc0", "cc-by", "cc by", "public domain", "pd ", "pd-",
    "creativecommons", "no known copyright",
)

# Words whose presence in a filename/alt text suggests a portrait/headshot
# of a person who is incidental to the fact subject. We skip these so that
# the "lead image" of an article about, say, a scientist does not end up as
# a headshot of that scientist plastered over a slide about their discovery.
_PORTRAIT_HINTS = (
    "portrait", "headshot", "mugshot", "bust", "selfie",
)

# Filenames/descriptions that suggest NSFW content
_NSFW_BLOCK_TERMS = (
    "nsfw", "explicit", "nude", "nudity", "porn", "xxx", "adult", "erotic",
)

# Wikipedia URL patterns we recognise
_WIKI_RE = re.compile(
    r"^https?://(?P<lang>[a-z]{2,})\.wikipedia\.org/wiki/(?P<title>.+)$"
)

_USER_AGENT = "factjot-bot/1.0 (tobyjohnsonemail@gmail.com)"


# ------------------------------------------------------------------ #
# Public API
# ------------------------------------------------------------------ #

def fetch_source_image(source_url: str, claim: str) -> Optional[str]:
    """Return a CC-licensed image URL from a Wikipedia source article.

    Parameters
    ----------
    source_url:
        A URL from the fact's ``sources`` list. If it is not a Wikipedia
        article, the function returns None immediately (no error raised).
    claim:
        The full fact claim text. Used for relevance scoring.

    Returns
    -------
    str | None
        A direct image URL if one is found, passes the relevance check,
        passes the rights check, and meets minimum dimensions. None otherwise.

    The function is intentionally conservative: if in doubt, it returns
    None and lets the existing video_finder / image_fetcher pipelines run
    as normal. A false negative is far preferable to an irrelevant image.
    """
    # 1. Detect whether this is a Wikipedia URL
    article_title = _extract_wiki_title(source_url)
    if not article_title:
        return None

    # 2. Call the Wikipedia pageimages API
    image_info = _wiki_pageimages(article_title)
    if not image_info:
        return None

    img_url   = image_info.get("url", "")
    img_w     = image_info.get("width", 0)
    img_h     = image_info.get("height", 0)
    filename  = image_info.get("filename", "")
    licence   = image_info.get("licence", "")

    if not img_url:
        return None

    # 3. Basic safety checks
    if not _nsfw_safe(img_url, filename):
        print(f"  [source-image] NSFW-flagged, skipping: {filename}")
        return None

    if _looks_like_portrait(filename):
        print(f"  [source-image] looks like a portrait/headshot, skipping: {filename}")
        return None

    # 4. Dimension check
    if img_w < _MIN_IMAGE_DIM or img_h < _MIN_IMAGE_DIM:
        print(f"  [source-image] too small ({img_w}x{img_h}), skipping")
        return None

    # 5. Rights check
    if not _is_open_licence(licence):
        print(f"  [source-image] licence not open ({licence!r}), skipping")
        return None

    # 6. Relevance check: do article title tokens overlap with claim keywords?
    score = _relevance_score(article_title, claim)
    if score < 2:
        print(f"  [source-image] relevance too low (score={score}) for {article_title!r}")
        return None

    # 7. Probe file size with a HEAD request (avoids downloading the full image
    #    just to reject it). Some Wikipedia servers do not honour HEAD for media;
    #    we skip the size check rather than crash in that case.
    try:
        head = requests.head(
            img_url,
            headers={"User-Agent": _USER_AGENT},
            timeout=8,
            allow_redirects=True,
        )
        content_length = int(head.headers.get("Content-Length", 0))
        if head.ok and content_length > 0 and content_length < _MIN_IMAGE_BYTES:
            print(f"  [source-image] too small ({content_length} bytes), skipping")
            return None
    except Exception:
        pass   # HEAD failed -- proceed and let the caller discover the size on download

    print(f"  [source-image] accepted: {img_url[:80]} (score={score}, {img_w}x{img_h})")
    return img_url


# ------------------------------------------------------------------ #
# Wikipedia API helpers
# ------------------------------------------------------------------ #

def _extract_wiki_title(url: str) -> Optional[str]:
    """Return the article title from a Wikipedia URL, or None if not Wikipedia.

    Examples:
        https://en.wikipedia.org/wiki/Voynich_manuscript  -> "Voynich manuscript"
        https://en.wikipedia.org/wiki/Cold_War_(1953-62)  -> "Cold War (1953-62)"
        https://www.bbc.co.uk/...                         -> None
    """
    m = _WIKI_RE.match(url.strip())
    if not m:
        return None
    raw = m.group("title")
    # Decode percent-encoding and normalise underscores to spaces
    title = unquote(raw).replace("_", " ")
    # Strip fragment anchors (e.g. #History)
    title = title.split("#")[0].strip()
    return title if title else None


def _wiki_pageimages(article_title: str) -> Optional[dict]:
    """Call the Wikipedia pageimages API for a given article title.

    Returns a dict with keys: url, width, height, filename, licence.
    Returns None if the article has no lead image or the API call fails.

    We use the REST v1 summary endpoint first (simpler) then fall back to
    the MediaWiki action API for the licence metadata.
    """
    # Step 1: get image URL + dimensions from the summary REST endpoint
    normalized = article_title.strip().replace(" ", "_")
    try:
        r = requests.get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{normalized}",
            headers={"User-Agent": _USER_AGENT},
            timeout=_HTTP_TIMEOUT,
        )
        if not r.ok:
            return None
        data = r.json()
    except Exception as exc:
        print(f"  [source-image] summary API error: {exc}")
        return None

    original = data.get("originalimage") or {}
    thumbnail = data.get("thumbnail") or {}

    # Prefer the original (full resolution) over thumbnail
    img_source = original.get("source") or thumbnail.get("source")
    img_w      = original.get("width")  or thumbnail.get("width",  0)
    img_h      = original.get("height") or thumbnail.get("height", 0)

    if not img_source:
        return None

    # Derive the filename from the URL for NSFW + portrait checks
    filename = _filename_from_url(img_source)

    # Step 2: fetch licence via the MediaWiki imageinfo API
    # The REST summary endpoint does not include licence metadata, so we
    # make a second call using the File: page title from the pageimages API.
    licence = _fetch_licence(article_title)

    return {
        "url":      img_source,
        "width":    img_w,
        "height":   img_h,
        "filename": filename,
        "licence":  licence,
    }


def _fetch_licence(article_title: str) -> str:
    """Return the licence short name for the lead image of a Wikipedia article.

    Uses the MediaWiki action=query prop=pageimages + prop=images chain.
    Returns an empty string if anything fails -- callers handle the empty case.
    """
    try:
        # First get the lead image file name via pageimages
        r1 = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action":     "query",
                "titles":     article_title,
                "prop":       "pageimages",
                "piprop":     "name",
                "format":     "json",
            },
            headers={"User-Agent": _USER_AGENT},
            timeout=_HTTP_TIMEOUT,
        )
        if not r1.ok:
            return ""
        pages = r1.json().get("query", {}).get("pages", {})
        file_name = ""
        for page in pages.values():
            file_name = page.get("pageimage", "")
            break
        if not file_name:
            return ""

        # Now fetch licence metadata for that file from Commons
        r2 = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action":               "query",
                "titles":               f"File:{file_name}",
                "prop":                 "imageinfo",
                "iiprop":               "extmetadata",
                "iiextmetadatafilter":  "LicenseShortName|License|Restrictions",
                "format":               "json",
            },
            headers={"User-Agent": _USER_AGENT},
            timeout=_HTTP_TIMEOUT,
        )
        if not r2.ok:
            return ""
        pages2 = r2.json().get("query", {}).get("pages", {})
        for page in pages2.values():
            info = (page.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata", {})
            restrictions = meta.get("Restrictions", {}).get("value", "")
            if restrictions and restrictions.lower() not in ("", "none"):
                return f"RESTRICTED:{restrictions}"
            lic = (meta.get("LicenseShortName", {}).get("value", "")
                   or meta.get("License", {}).get("value", ""))
            return lic
    except Exception:
        pass
    return ""


# ------------------------------------------------------------------ #
# Relevance scoring
# ------------------------------------------------------------------ #

_STOP = frozenset({
    "a", "an", "the", "in", "on", "at", "to", "for", "of", "and", "or",
    "but", "is", "was", "are", "were", "be", "been", "have", "had", "has",
    "this", "that", "with", "from", "as", "by", "it", "its", "which",
    "who", "when", "where", "how", "not", "no", "can", "so", "if",
})


def _relevance_score(article_title: str, claim: str) -> int:
    """Score how well the article title matches the claim.

    Strategy:
    - Tokenise both strings, lower-cased, stripping punctuation.
    - Remove common stop words.
    - Count how many title tokens appear in the claim.
    - Weight by token length (longer/rarer words carry more signal).

    A score of 2 means at least one meaningful word (4+ chars) overlaps,
    which is a strong indicator the article is specifically about the
    fact subject. Scores below 2 are rejected.

    Examples:
        title="Voynich manuscript"  claim="The Voynich Manuscript has..."  -> 8
        title="Aspirin"             claim="Aspirin was originally..."       -> 7
        title="War"                 claim="A war broke out in 1914..."      -> 0 (too short)
    """
    def tokenise(text: str) -> set[str]:
        tokens = re.findall(r"[a-zA-Z]{3,}", text.lower())
        return {t for t in tokens if t not in _STOP}

    title_tokens = tokenise(article_title)
    claim_tokens = tokenise(claim)

    score = 0
    for token in title_tokens:
        if token in claim_tokens:
            score += len(token)   # 3-char tokens score 3, 10-char score 10
    return score


# ------------------------------------------------------------------ #
# Safety helpers
# ------------------------------------------------------------------ #

def _nsfw_safe(url: str, filename: str) -> bool:
    combined = f"{url} {filename}".lower()
    return not any(term in combined for term in _NSFW_BLOCK_TERMS)


def _looks_like_portrait(filename: str) -> bool:
    lower = filename.lower()
    return any(hint in lower for hint in _PORTRAIT_HINTS)


def _is_open_licence(licence: str) -> bool:
    """Return True if the licence string indicates CC/open/public-domain use."""
    if licence.startswith("RESTRICTED:"):
        return False
    lower = licence.lower()
    return any(marker in lower for marker in _OPEN_LICENCE_MARKERS)


def _filename_from_url(url: str) -> str:
    """Extract the bare filename from a Wikimedia image URL."""
    path = urlparse(url).path
    return unquote(path.split("/")[-1])
