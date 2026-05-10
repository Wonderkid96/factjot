"""Fetch a breaking Guardian article and publish a red-tinted news carousel to Instagram.

Flow:
  1. Pick the Guardian section for today (weekday rotation)
  2. Fetch the most recent article published within the last 24 hours
  3. Dedup check against data/ledgers/news_posts.jsonl
  4. Compress article to 8 slides with Claude (single-stage -- article is already prose)
  5. Render 1080x1350 PNGs with red brand overlay
  6. Host on imgbb, publish via Instagram Graph API
  7. Log to ledger and insta-brain

Usage (local):
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3 pipelines/news/ship_news_post.py --dry-run
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3 pipelines/news/ship_news_post.py --section technology
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3 pipelines/news/ship_news_post.py --article-url "https://www.theguardian.com/..."
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.append(str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

import os

from anthropic import Anthropic
from playwright.sync_api import sync_playwright

from src.content.hashtag_builder import build_hashtags
from src.publish.image_host import make_image_host
from src.publish.instagram_publisher import InstagramGraphPublisher
from src.research.image_sourcer import ImageIntent, ImageSourcer
from src.utils.logging_utils import configure_logging

# ------------------------------------------------------------------ #
# Constants
# ------------------------------------------------------------------ #

GUARDIAN_BASE = "https://content.guardianapis.com"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
SLIDES_COUNT  = 8
NEWS_LEDGER   = Path("data/ledgers/news_posts.jsonl")

# Weekday -> Guardian section (Mon=1 .. Sun=7)
# Intentionally varied -- not all conflict/politics. Science, tech, and society
# stories tend to be more positive and shareable.
SECTION_BY_DAY: dict[int, str] = {
    1: "world",
    2: "technology",
    3: "science",
    4: "society",
    5: "environment",
    6: "uk-news",
    7: "world",
}

_PRICING = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-6":         {"input": 3.00, "output": 15.00},
}

# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _log(msg: str) -> None:
    print(msg, flush=True)


def escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;")
        .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")
    )


def _inline_asset(path: Path) -> str:
    if not path.exists():
        return ""
    mime = {
        ".ttf": "font/ttf", ".otf": "font/otf",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png",
    }.get(path.suffix.lower(), "application/octet-stream")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def _inline_bytes(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


# ------------------------------------------------------------------ #
# News ledger (dedup by article URL)
# ------------------------------------------------------------------ #

def _load_posted_urls() -> set[str]:
    if not NEWS_LEDGER.exists():
        return set()
    urls: set[str] = set()
    for line in NEWS_LEDGER.read_text().splitlines():
        try:
            urls.add(json.loads(line)["url"])
        except Exception:
            pass
    return urls


def _log_posted(article: dict, caption: str, slide_count: int) -> None:
    NEWS_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "posted_at": datetime.now(timezone.utc).isoformat(),
        "url":       article["url"],
        "title":     article["title"],
        "section":   article["section"],
        "slides":    slide_count,
        "caption":   caption[:200],
    }
    with NEWS_LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# ------------------------------------------------------------------ #
# Guardian API
# ------------------------------------------------------------------ #

def fetch_breaking_article(
    section: str,
    guardian_key: str,
    max_age_hours: int = 24,
    query: str | None = None,
) -> dict | None:
    """Return the most recent fresh article with the full element list.

    Step 1: search for the newest article.
    Step 2: re-fetch that specific article by path to get ALL inline images
            (the search endpoint only returns a subset of elements).
    """
    params: dict = {
        "api-key":       guardian_key,
        "show-fields":   "bodyText,thumbnail,trailText,headline",
        "show-elements": "image",
        "order-by":      "newest",
        "page-size":     5,
    }
    if query:
        params["q"] = query
    else:
        params["section"] = section

    resp = requests.get(f"{GUARDIAN_BASE}/search", params=params, timeout=15)
    resp.raise_for_status()
    results = resp.json()["response"]["results"]

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    for item in results:
        pub = datetime.fromisoformat(item["webPublicationDate"].replace("Z", "+00:00"))
        if pub < cutoff:
            continue
        fields = item.get("fields", {})
        body = fields.get("bodyText", "")
        if len(body) < 400:
            continue

        # Step 2: fetch the full article to get all images
        article_path = re.search(r"theguardian\.com/(.+)", item["webUrl"])
        full_elements = item.get("elements", [])
        if article_path:
            try:
                full_resp = requests.get(
                    f"{GUARDIAN_BASE}/{article_path.group(1)}",
                    params={"api-key": guardian_key, "show-fields": "thumbnail", "show-elements": "image"},
                    timeout=15,
                )
                if full_resp.ok:
                    full_elements = full_resp.json()["response"]["content"].get("elements", full_elements)
            except Exception:
                pass

        return {
            "title":     item["webTitle"],
            "url":       item["webUrl"],
            "section":   item.get("sectionName", section),
            "pub_date":  item["webPublicationDate"],
            "body":      body,
            "trail":     fields.get("trailText", ""),
            "thumbnail": fields.get("thumbnail", ""),
            "elements":  full_elements,
        }
    return None


def fetch_article_by_url(article_url: str, guardian_key: str) -> dict | None:
    """Fetch a specific Guardian article by its full URL."""
    match = re.search(r"theguardian\.com/(.+?)(?:\?|$)", article_url)
    if not match:
        return None
    path = match.group(1).rstrip("/")
    try:
        resp = requests.get(
            f"{GUARDIAN_BASE}/{path}",
            params={
                "api-key":       guardian_key,
                "show-fields":   "bodyText,thumbnail,trailText,headline",
                "show-elements": "image",
            },
            timeout=15,
        )
        resp.raise_for_status()
        item = resp.json()["response"]["content"]
    except Exception as exc:
        _log(f"     fetch_article_by_url failed: {exc}")
        return None

    fields = item.get("fields", {})
    body   = fields.get("bodyText", "")
    if len(body) < 200:
        return None
    return {
        "title":     item["webTitle"],
        "url":       item["webUrl"],
        "section":   item.get("sectionName", "News"),
        "pub_date":  item["webPublicationDate"],
        "body":      body,
        "trail":     fields.get("trailText", ""),
        "thumbnail": fields.get("thumbnail", ""),
        "elements":  item.get("elements", []),
    }


def extract_image_urls(article: dict) -> list[str]:
    """Pull all unique image URLs from article elements, largest resolution first.

    Falls back to the thumbnail if no inline images are available.
    """
    seen: set[str] = set()
    urls: list[str] = []

    for element in article.get("elements", []):
        if element.get("type") != "image":
            continue
        assets = element.get("assets", [])
        # Pick the asset with the largest width
        best = max(
            (a for a in assets if a.get("file")),
            key=lambda a: int(a.get("typeData", {}).get("width", 0)),
            default=None,
        )
        if best and best["file"] not in seen:
            seen.add(best["file"])
            urls.append(best["file"])

    # Deduplicate by base filename -- the Guardian often returns the same photo
    # at multiple resolutions (e.g. /1000.jpg and /500.jpg). Keep only one per photo.
    deduped: list[str] = []
    base_seen: set[str] = set()
    for url in urls:
        # Strip resolution suffix to get the base photo path
        base = re.sub(r"/\d+\.jpg$", "", url)
        if base not in base_seen:
            base_seen.add(base)
            deduped.append(url)

    # Always include the thumbnail as a fallback if we have nothing else
    thumb = article.get("thumbnail", "")
    if thumb:
        thumb_base = re.sub(r"/\d+\.jpg$", "", thumb)
        if thumb_base not in base_seen:
            base_seen.add(thumb_base)
            deduped.append(thumb)

    return deduped


def download_image(url: str) -> bytes | None:
    if not url:
        return None
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return r.content
    except Exception:
        return None


def fetch_pexels_images(
    query: str, pexels_key: str, count: int = 8
) -> list[str]:
    """Search Pexels for relevant photos and return as base64 data URLs.

    Used to supplement when an article has fewer than MIN_ARTICLE_IMAGES.
    Portrait orientation preferred for 4:5 carousel format.
    """
    if not pexels_key:
        return []
    try:
        resp = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": pexels_key},
            params={"query": query, "per_page": count, "orientation": "portrait"},
            timeout=15,
        )
        resp.raise_for_status()
        photos = resp.json().get("photos", [])
        data_urls: list[str] = []
        for photo in photos:
            img_url = (
                photo.get("src", {}).get("large2x")
                or photo.get("src", {}).get("large")
                or photo.get("src", {}).get("medium")
            )
            if not img_url:
                continue
            data = download_image(img_url)
            if data:
                data_urls.append(_inline_bytes(data, "image/jpeg"))
            if len(data_urls) >= count:
                break
        return data_urls
    except Exception as exc:
        _log(f"     Pexels fallback error: {exc}")
        return []


def _pexels_query_for_article(article: dict) -> str:
    """Build a Pexels search query from the article headline and section."""
    # Strip punctuation, drop short/stop words, take the most meaningful terms
    stop = {"the", "that", "this", "with", "from", "have", "been", "says",
            "will", "were", "they", "their", "over", "into", "after", "live"}
    words = re.findall(r"[a-zA-Z]+", article.get("title", ""))
    keywords = [w for w in words if len(w) > 3 and w.lower() not in stop][:5]
    section = article.get("section", "").lower().replace(" news", "").strip()
    if section and section not in " ".join(keywords).lower():
        keywords.insert(0, section)
    return " ".join(keywords[:4])


# ------------------------------------------------------------------ #
# Claude compression
# ------------------------------------------------------------------ #

def compress_to_slides(
    article: dict, model: str, api_key: str,
) -> tuple[dict, dict]:
    body = article["body"]
    if len(body) > 5000:
        body = body[:5000].rsplit(" ", 1)[0] + "..."

    article_text = f"Headline: {article['title']}\n\n{body}"

    prompt = f"""
You are writing news carousels for Instagram. Your job is to make people stop, read, and feel informed.

First, decide how many content slides this story genuinely needs. Use as few as possible.
- Simple story with one key development: 2-3 content slides
- Story with several distinct developments: 4-6 content slides
- Complex multi-part story: up to 8 content slides
- Maximum 8 content slides

The final slide is always a thought-provoking call to action or reflection question
related to the story. It should make the reader think or want to discuss it.
Do NOT include a CTA on any other slide.

Writing rules:
- Present tense where possible ("Scientists discover", not "Scientists discovered")
- Write in full connected sentences, NOT bullet points or fragments
- Each slide tells one coherent moment -- lines must flow into each other naturally
- Each slide: exactly 3 lines, 5-8 words per line
- Front-load the most interesting element on each slide
- No hedging, no filler, no attribution phrases ("sources say", "according to")
- Do NOT repeat information across slides
- 100% factual -- only state what the article says

Key word markup:
- Wrap 1-2 key words or short phrases per line in [r]...[/r] -- rendered in red
- Use these for the most striking facts, names, numbers, turning points
- Example: "Iran sets up [r]new authority[/r] over the strait."

CTA slide (always the final slide):
- 3 lines, same format
- A thought-provoking question or reflection related to the story
- Something the reader would want to share or debate
- Do NOT reference the source or say "follow for more"

Tone: clear, confident, human. A smart friend explaining the news.

Output JSON only:
{{
  "cover_title": "3-5 word punchy title for the cover slide, no full stop",
  "title": "sharp headline, max 7 words, no full stop",
  "slides": [
    {{"slideNumber": 1, "lines": ["...", "...", "..."]}}
  ]
}}

Exactly 3 lines per slide. Return JSON only.

Article:
{article_text}
""".strip()

    client = Anthropic(api_key=api_key)
    res = client.messages.create(
        model=model, max_tokens=3000, temperature=0.5,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = res.content[0].text.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", raw, re.IGNORECASE)
        if fenced:
            data = json.loads(fenced.group(1))
        else:
            s, e = raw.find("{"), raw.rfind("}")
            data = json.loads(raw[s: e + 1])

    slides = data.get("slides", [])
    # Claude decides the count -- clamp to 2-8 content slides
    if len(slides) < 2:
        raise RuntimeError(f"Too few slides returned: {len(slides)}")
    if len(slides) > 8:
        slides = slides[:8]
        data["slides"] = slides
    for i, s in enumerate(slides, 1):
        if not isinstance(s.get("lines"), list) or len(s["lines"]) != 3:
            raise RuntimeError(f"Slide {i} must have 3 lines")

    input_tok  = res.usage.input_tokens
    output_tok = res.usage.output_tokens
    rates = _PRICING.get(model, {"input": 0.0, "output": 0.0})
    cost  = (input_tok / 1_000_000) * rates["input"] + (output_tok / 1_000_000) * rates["output"]
    usage = {"model": model, "input_tokens": input_tok, "output_tokens": output_tok, "cost_usd": round(cost, 6)}
    return data, usage


# ------------------------------------------------------------------ #
# Caption
# ------------------------------------------------------------------ #

def build_caption(article: dict, carousel_title: str, trail: str) -> str:
    pub     = article["pub_date"][:10]
    section = article.get("section", "world").lower().replace(" ", "-")

    intro = trail.strip() if trail else carousel_title
    intro = re.sub(r"<[^>]+>", "", intro).strip()

    hashtags = build_hashtags(
        summary=article.get("title", carousel_title),
        topic=section,
        post_type="news",
    )

    return (
        f"{intro}\n\n"
        f"Source: The Guardian ({pub})\n"
        f"Read more: {article['url']}\n\n"
        f"{hashtags}"
    )


# ------------------------------------------------------------------ #
# Render helpers
# ------------------------------------------------------------------ #

def _markup_lines(lines: list[str]) -> str:
    """Convert [r]...[/r] markers to accent-red spans; HTML-escape everything else."""
    result = []
    for line in lines:
        parts = re.split(r"(\[r\].*?\[/r\])", line)
        html_parts = []
        for part in parts:
            m = re.match(r"\[r\](.*?)\[/r\]", part)
            if m:
                html_parts.append(f'<span class="red">{escape_html(m.group(1))}</span>')
            else:
                html_parts.append(escape_html(part))
        result.append(f'<div class="line">{"".join(html_parts)}</div>')
    return "\n".join(result)


def _font_faces(serif_url: str, mono_url: str, archivo_url: str = "") -> str:
    """v2.1: mono_url now points at SpaceGrotesk-Bold.ttf (label_font_canonical).
    The variable name is preserved so callsites stay stable; the @font-face
    declaration registers it as 'Space Grotesk' weight 700, matching the
    template-side rename. JetBrains Mono is no longer in this declaration."""
    archivo = ""
    if archivo_url:
        archivo = (
            f'@font-face{{font-family:"Archivo Black";src:url("{archivo_url}") '
            f'format("truetype");font-weight:900;font-style:normal;}}'
        )
    return f"""
    @font-face{{font-family:"Instrument Serif";src:url("{serif_url}") format("truetype");font-weight:400;font-style:normal;}}
    @font-face{{font-family:"Instrument Serif";src:url("{serif_url}") format("truetype");font-weight:400;font-style:italic;}}
    @font-face{{font-family:"Space Grotesk";src:url("{mono_url}") format("truetype");font-weight:700;font-style:normal;}}
    {archivo}"""


def _logo_tag(logo_url: str, invert: bool = False) -> str:
    if logo_url:
        filt = "brightness(0) invert(1)" if invert else ""
        return f'<img class="wordmark-img" src="{logo_url}" alt="factjot" style="filter:{filt};"/>'
    return '<span class="wm-text">factjot.</span>'


# ------------------------------------------------------------------ #
# Cover slide -- matches production carousel style
# (full-bleed photo, gradient overlay, large title bottom)
# ------------------------------------------------------------------ #

def render_cover_slide(
    cover_title: str,
    source_label: str,
    photo_data_url: str,
    out_path: Path,
    index: int,
    total: int,
    repo_root: Path,
    browser,
) -> None:
    logo_url    = _inline_asset(repo_root / "assets/logo/factjot_mark.png")
    serif_url   = _inline_asset(repo_root / "assets/fonts/InstrumentSerif-Regular.ttf")
    # v2.1: Space Grotesk Bold replaces JetBrains Mono Bold for labels.
    mono_url    = _inline_asset(repo_root / "assets/fonts/SpaceGrotesk-Bold.ttf")
    archivo_url = _inline_asset(repo_root / "assets/fonts/ArchivoBlack-Regular.ttf")

    index_label = f"{index}/{total}"
    pill = source_label.upper()[:32]
    logo = _logo_tag(logo_url, invert=True)

    # Size title dynamically. Archivo Black is heavier than Instrument Serif at
    # the same px, so the scale is shifted down to roughly match perceived size.
    chars = len(cover_title.strip())
    if chars <= 20:
        title_size, title_lh = 100, 0.96
    elif chars <= 35:
        title_size, title_lh = 82, 0.98
    else:
        title_size, title_lh = 64, 1.04

    cover_title_clean = cover_title.strip().rstrip(".")

    html = f"""<!doctype html><html><head><meta charset="utf-8"/><style>
    {_font_faces(serif_url, mono_url, archivo_url)}
    :root{{--near-black:#0B0B0C;--off-white:#EDE8DD;--accent:#E6352A;--white:#FFFFFF;--muted:#9A938A;}}
    *{{box-sizing:border-box;margin:0;padding:0;}}
    html,body{{width:1080px;height:1350px;overflow:hidden;background:var(--near-black);-webkit-font-smoothing:antialiased;}}
    .stage{{position:relative;width:1080px;height:1350px;overflow:hidden;isolation:isolate;}}
    .photo{{position:absolute;inset:0;background:url("{photo_data_url}") center/cover no-repeat;z-index:0;}}
    .top-darken{{position:absolute;inset:0 0 auto 0;height:22%;background:linear-gradient(to bottom,rgba(0,0,0,0.62),rgba(0,0,0,0));z-index:1;}}
    .bottom-darken{{position:absolute;inset:28% 0 0 0;background:linear-gradient(to bottom,rgba(11,11,12,0) 0%,rgba(11,11,12,0.55) 30%,rgba(11,11,12,0.95) 62%,rgba(11,11,12,0.99) 100%);z-index:1;}}
    .vignette{{position:absolute;inset:0;background:radial-gradient(ellipse at center,rgba(0,0,0,0) 68%,rgba(0,0,0,0.28) 100%);z-index:2;pointer-events:none;}}
    .grain{{position:absolute;inset:0;z-index:3;opacity:0.055;mix-blend-mode:overlay;background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='280' height='280'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 0.7 0'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>");pointer-events:none;}}
    .frame{{position:absolute;inset:0;z-index:10;padding:58px 72px 74px 72px;display:flex;flex-direction:column;justify-content:space-between;}}
    .top-row{{display:flex;align-items:center;gap:20px;font-family:"Space Grotesk",system-ui,sans-serif;font-size:20px;font-weight:700;letter-spacing:0.16em;color:var(--off-white);text-transform:uppercase;text-shadow:1px 1px 0 rgba(0,0,0,0.55);}}
    .wordmark-img{{height:36px;width:auto;display:block;opacity:0.95;filter:drop-shadow(1px 1px 0 rgba(0,0,0,0.45));}}
    .top-divider{{flex:1;height:1px;background:var(--off-white);opacity:0.32;}}
    .index{{opacity:0.72;}}
    .lower{{display:flex;flex-direction:column;gap:22px;}}
    .pill{{align-self:flex-start;background:var(--accent);color:var(--white);font-family:"Space Grotesk",system-ui,sans-serif;font-weight:700;font-size:17px;letter-spacing:0.26em;padding:7px 16px 9px;border-radius:999px;text-transform:uppercase;line-height:1;}}
    .title{{font-family:"Archivo Black","Inter",system-ui,sans-serif;font-weight:900;font-size:{title_size}px;line-height:{title_lh};letter-spacing:-0.01em;text-transform:lowercase;color:var(--off-white);text-shadow:2px 2px 0 rgba(0,0,0,0.55);text-wrap:balance;}}
    .title::after{{content:".";color:var(--accent);font-family:"Archivo Black","Inter",system-ui,sans-serif;text-transform:none;}}
    </style></head><body>
    <div class="stage">
      <div class="photo"></div>
      <div class="top-darken"></div><div class="bottom-darken"></div>
      <div class="vignette"></div><div class="grain"></div>
      <div class="frame">
        <div class="top-row">
          {logo}
          <span class="top-divider"></span>
          <span class="index">{index_label}</span>
        </div>
        <div class="lower">
          <span class="pill">{escape_html(pill)}</span>
          <div class="title">{escape_html(cover_title_clean)}</div>
        </div>
      </div>
    </div></body></html>"""

    page = browser.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=2)
    page.set_content(html, wait_until="networkidle")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out_path), full_page=False, clip={"x": 0, "y": 0, "width": 1080, "height": 1350})
    page.close()


# ------------------------------------------------------------------ #
# Story frame -- 1080x1920 9:16 wrapper around the cover slide.
# Blurred cover as full-bleed bg, cover slide itself as a centred card.
# ------------------------------------------------------------------ #

def render_story_frame(
    cover_path: Path,
    out_path: Path,
    repo_root: Path,
    browser,
) -> None:
    """Render a 1080x1920 story frame wrapping the carousel cover slide.

    Story image = the cover slide composited inside a 9:16 frame with the
    factjot wordmark + NEW POST pill above it, and the same cover blurred
    behind. Matches the reel story's design language.
    """
    cover_url   = _inline_asset(cover_path)
    serif_url   = _inline_asset(repo_root / "assets/fonts/InstrumentSerif-Regular.ttf")
    # v2.1: Space Grotesk Bold replaces JetBrains Mono Bold for labels.
    mono_url    = _inline_asset(repo_root / "assets/fonts/SpaceGrotesk-Bold.ttf")

    html = f"""<!doctype html><html><head><meta charset="utf-8"/><style>
    {_font_faces(serif_url, mono_url, "")}
    :root{{--near-black:#0B0B0C;--off-white:#EDE8DD;--accent:#E6352A;--white:#FFFFFF;}}
    *{{box-sizing:border-box;margin:0;padding:0;}}
    html,body{{width:1080px;height:1920px;overflow:hidden;background:var(--near-black);color:var(--white);font-family:"Instrument Serif",Georgia,serif;-webkit-font-smoothing:antialiased;}}
    .bg-blur{{position:absolute;inset:0;background:url("{cover_url}") center/cover no-repeat;filter:blur(28px) saturate(0.7) brightness(0.45);transform:scale(1.12);z-index:0;}}
    .bg-overlay{{position:absolute;inset:0;background:rgba(11,11,12,0.62);z-index:1;}}
    .grain{{position:absolute;inset:0;z-index:5;opacity:0.06;mix-blend-mode:overlay;background-image:url("{_GRAIN_SVG}");pointer-events:none;}}
    .frame{{position:absolute;inset:0;z-index:10;padding:280px 60px 280px 60px;display:flex;flex-direction:column;justify-content:flex-start;align-items:center;gap:32px;}}
    .header{{width:880px;align-self:center;display:flex;align-items:center;justify-content:space-between;flex:0 0 auto;}}
    .wordmark{{font-family:"Instrument Serif",Georgia,serif;font-weight:400;font-size:52px;letter-spacing:-0.01em;line-height:1;color:var(--off-white);text-shadow:1px 1px 0 rgba(0,0,0,0.45);}}
    .wordmark .ital{{font-style:italic;}}
    .wordmark .dot{{color:var(--accent);}}
    .new-post-badge{{background:var(--accent);color:var(--off-white);font-family:"Space Grotesk",system-ui,sans-serif;font-weight:700;font-size:22px;letter-spacing:0.24em;padding:12px 22px 14px;border-radius:9999px;text-transform:uppercase;line-height:1;}}
    .card-wrapper{{width:100%;display:flex;justify-content:center;align-items:flex-start;flex:1 1 auto;}}
    .slide-card{{width:880px;aspect-ratio:4 / 5;border-radius:24px;overflow:hidden;box-shadow:0 32px 80px rgba(0,0,0,0.65),0 6px 20px rgba(0,0,0,0.45);border:1px solid rgba(255,255,255,0.10);position:relative;}}
    .slide-card img{{width:100%;height:100%;object-fit:cover;display:block;}}
    </style></head><body>
    <div class="bg-blur"></div>
    <div class="bg-overlay"></div>
    <div class="grain"></div>
    <div class="frame">
      <div class="header">
        <span class="wordmark">fact<span class="ital">jot</span><span class="dot">.</span></span>
        <div class="new-post-badge">NEW POST</div>
      </div>
      <div class="card-wrapper">
        <div class="slide-card">
          <img src="{cover_url}" alt=""/>
        </div>
      </div>
    </div>
    </body></html>"""

    page = browser.new_page(viewport={"width": 1080, "height": 1920}, device_scale_factor=2)
    page.set_content(html, wait_until="networkidle")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out_path), full_page=False, clip={"x": 0, "y": 0, "width": 1080, "height": 1920})
    page.close()


# ------------------------------------------------------------------ #
# Content slides -- black background, white text, red key words
# ------------------------------------------------------------------ #

_GRAIN_SVG = (
    "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='280' height='280'>"
    "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' "
    "stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 0.7 0'/>"
    "</filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>"
)


def render_news_slide(
    lines: list[str],
    photo_data_url: str,
    out_path: Path,
    index: int,
    total: int,
    source_label: str,
    repo_root: Path,
    browser,
    layout_mode: str = "compact_legacy",
) -> None:
    """Render a content slide.

    layout_mode:
        compact_legacy (default) - existing Archivo Black 900 anchored
            bottom-left layout. Byte-identical to prior behaviour.
        readable_list - Space Grotesk SemiBold body inside a half-box
            flexbox container at the bottom 50% of the canvas, with
            renderer-side font auto-fit (64 -> 28 px walk).
    """
    logo_url    = _inline_asset(repo_root / "assets/logo/factjot_mark.png")
    serif_url   = _inline_asset(repo_root / "assets/fonts/InstrumentSerif-Regular.ttf")
    # v2.1: Space Grotesk Bold replaces JetBrains Mono Bold for labels.
    mono_url    = _inline_asset(repo_root / "assets/fonts/SpaceGrotesk-Bold.ttf")
    archivo_url = _inline_asset(repo_root / "assets/fonts/ArchivoBlack-Regular.ttf")

    index_label = f"{index}/{total}"
    logo = _logo_tag(logo_url, invert=True)
    lines_html = _markup_lines(lines)

    if layout_mode == "readable_list":
        grotesk_url = _inline_asset(repo_root / "assets/fonts/SpaceGrotesk-SemiBold.ttf")
        if photo_data_url:
            html = _render_news_slide_photo_readable(
                serif_url, mono_url, grotesk_url, logo, index_label, lines_html, photo_data_url,
            )
        else:
            html = _render_news_slide_typography_readable(
                serif_url, mono_url, grotesk_url, logo, index_label, lines_html,
            )
    else:
        if photo_data_url:
            html = _render_news_slide_photo(
                serif_url, mono_url, archivo_url, logo, index_label, lines_html, photo_data_url,
            )
        else:
            html = _render_news_slide_typography(
                serif_url, mono_url, archivo_url, logo, index_label, lines_html,
            )

    page = browser.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=2)
    page.set_content(html, wait_until="networkidle")

    # readable_list: walk font-size 64 -> 28 px and pick the largest
    # that fits the half-box container. compact_legacy uses fixed sizes.
    if layout_mode == "readable_list":
        _autosize_readable_text(page)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out_path), full_page=False, clip={"x": 0, "y": 0, "width": 1080, "height": 1350})
    page.close()


def _render_news_slide_photo(
    serif_url: str, mono_url: str, archivo_url: str, logo: str, index_label: str,
    lines_html: str, photo_data_url: str,
) -> str:
    """Full-bleed content slide. Photo fills the canvas; text sits over a bottom gradient.

    Body lines are Archivo Black 900 lowercase (v2 brand). Sizes and line-height
    are tuned for AB's heavier weight: ~17% smaller px and 14% tighter leading
    than the previous Instrument Serif setup.
    """
    return f"""<!doctype html><html><head><meta charset="utf-8"/><style>
    {_font_faces(serif_url, mono_url, archivo_url)}
    :root{{--near-black:#0B0B0C;--off-white:#EDE8DD;--accent:#E6352A;--white:#FFFFFF;}}
    *{{box-sizing:border-box;margin:0;padding:0;}}
    html,body{{width:1080px;height:1350px;overflow:hidden;background:var(--near-black);-webkit-font-smoothing:antialiased;}}
    .stage{{position:relative;width:1080px;height:1350px;overflow:hidden;isolation:isolate;}}
    .photo{{position:absolute;inset:0;background:url("{photo_data_url}") center/cover no-repeat;z-index:0;}}
    .top-darken{{position:absolute;inset:0 0 auto 0;height:28%;background:linear-gradient(to bottom,rgba(0,0,0,0.72),rgba(0,0,0,0));z-index:1;}}
    .bottom-darken{{position:absolute;inset:30% 0 0 0;background:linear-gradient(to bottom,rgba(11,11,12,0) 0%,rgba(11,11,12,0.60) 35%,rgba(11,11,12,0.95) 62%,rgba(11,11,12,0.99) 100%);z-index:1;}}
    .vignette{{position:absolute;inset:0;background:radial-gradient(ellipse at center,rgba(0,0,0,0) 65%,rgba(0,0,0,0.30) 100%);z-index:2;pointer-events:none;}}
    .grain{{position:absolute;inset:0;z-index:3;opacity:0.055;mix-blend-mode:overlay;background-image:url("{_GRAIN_SVG}");pointer-events:none;}}
    .frame{{position:absolute;inset:0;z-index:10;padding:62px 70px 74px 70px;display:flex;flex-direction:column;justify-content:space-between;}}
    .top-row{{display:flex;align-items:center;gap:20px;}}
    .wordmark-img{{height:28px;width:auto;display:block;opacity:0.95;flex-shrink:0;filter:drop-shadow(1px 1px 0 rgba(0,0,0,0.45));}}
    .top-divider{{flex:1;height:1px;background:var(--off-white);opacity:0.32;}}
    .index{{background:rgba(255,255,255,0.12);color:var(--off-white);font-family:"Space Grotesk",system-ui,sans-serif;font-weight:700;font-size:24px;letter-spacing:0.04em;padding:8px 18px 10px;border-radius:999px;line-height:1;flex-shrink:0;}}
    .lines{{display:flex;flex-direction:column;gap:8px;}}
    .line{{font-family:"Archivo Black","Inter",system-ui,sans-serif;font-weight:900;font-size:48px;line-height:1.08;letter-spacing:-0.01em;text-transform:lowercase;color:var(--off-white);text-shadow:2px 2px 0 rgba(0,0,0,0.55);}}
    .line .red{{color:var(--accent);font-weight:900;}}
    </style></head><body>
    <div class="stage">
      <div class="photo"></div>
      <div class="top-darken"></div>
      <div class="bottom-darken"></div>
      <div class="vignette"></div>
      <div class="grain"></div>
      <div class="frame">
        <div class="top-row">{logo}<span class="top-divider"></span><div class="index">{index_label}</div></div>
        <div class="lines">{lines_html}</div>
      </div>
    </div></body></html>"""


def _render_news_slide_typography(
    serif_url: str, mono_url: str, archivo_url: str, logo: str, index_label: str, lines_html: str,
) -> str:
    """Intentional full-height typography-only slide. No photo zone. Looks deliberate.

    Lines are Archivo Black 900 lowercase, sized down for AB's heavier weight
    and tightened leading.
    """
    return f"""<!doctype html><html><head><meta charset="utf-8"/><style>
    {_font_faces(serif_url, mono_url, archivo_url)}
    :root{{--near-black:#0B0B0C;--off-white:#EDE8DD;--accent:#E6352A;--white:#FFFFFF;}}
    *{{box-sizing:border-box;margin:0;padding:0;}}
    html,body{{width:1080px;height:1350px;overflow:hidden;background:var(--near-black);-webkit-font-smoothing:antialiased;}}
    .stage{{position:relative;width:1080px;height:1350px;overflow:hidden;background:var(--near-black);}}
    .accent-line{{position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--accent);z-index:2;}}
    .grain{{position:absolute;inset:0;z-index:1;opacity:0.055;mix-blend-mode:overlay;
            background-image:url("{_GRAIN_SVG}");pointer-events:none;}}
    .frame{{position:absolute;inset:0;z-index:10;padding:62px 70px 62px 86px;
            display:flex;flex-direction:column;}}
    .top-row{{display:flex;align-items:center;gap:20px;flex-shrink:0;margin-bottom:0;}}
    .wordmark-img{{height:28px;width:auto;display:block;opacity:0.88;flex-shrink:0;}}
    .top-divider{{flex:1;height:1px;background:var(--off-white);opacity:0.32;}}
    .index{{background:rgba(255,255,255,0.1);color:var(--off-white);font-family:"Space Grotesk",system-ui,sans-serif;
            font-weight:700;font-size:24px;letter-spacing:0.04em;padding:8px 18px 10px;border-radius:999px;line-height:1;flex-shrink:0;}}
    .lines-wrap{{flex:1;display:flex;flex-direction:column;justify-content:center;padding-right:20px;}}
    .lines{{display:flex;flex-direction:column;gap:10px;}}
    .line{{font-family:"Archivo Black","Inter",system-ui,sans-serif;font-weight:900;font-size:42px;line-height:1.10;
           letter-spacing:-0.01em;text-transform:lowercase;color:var(--off-white);}}
    .line .red{{color:var(--accent);font-weight:900;}}
    </style></head><body>
    <div class="stage">
      <div class="accent-line"></div>
      <div class="grain"></div>
      <div class="frame">
        <div class="top-row">{logo}<span class="top-divider"></span><div class="index">{index_label}</div></div>
        <div class="lines-wrap">
          <div class="lines">{lines_html}</div>
        </div>
      </div>
    </div></body></html>"""


# ------------------------------------------------------------------ #
# readable_list layout (Space Grotesk SemiBold + half-box + autosize)
# ------------------------------------------------------------------ #
# Opt-in via layout_mode="readable_list" on render_news_slide. Only the
# list slot picks this by default today; fact and news continue to use
# the compact_legacy templates above unchanged.

def _font_faces_readable(serif_url: str, mono_url: str, grotesk_url: str) -> str:
    """v2.1: mono_url points at SpaceGrotesk-Bold.ttf; both label-bold (700)
    and body-semibold (600) Space Grotesk weights are registered so the
    readable_list layout has access to both in the same family."""
    return f"""
    @font-face{{font-family:"Instrument Serif";src:url("{serif_url}") format("truetype");font-weight:400;font-style:normal;}}
    @font-face{{font-family:"Space Grotesk";src:url("{mono_url}") format("truetype");font-weight:700;font-style:normal;}}
    @font-face{{font-family:"Space Grotesk";src:url("{grotesk_url}") format("truetype");font-weight:600;font-style:normal;}}"""


def _render_news_slide_photo_readable(
    serif_url: str, mono_url: str, grotesk_url: str, logo: str, index_label: str,
    lines_html: str, photo_data_url: str,
) -> str:
    """Photo slide, readable_list layout. Body text in Space Grotesk
    SemiBold, sized by JS auto-fit to occupy the bottom 50% of the
    canvas. Top half is the photo (full bleed) with a gradient scrim
    that protects legibility at the text baseline."""
    return f"""<!doctype html><html><head><meta charset="utf-8"/><style>
    {_font_faces_readable(serif_url, mono_url, grotesk_url)}
    :root{{--near-black:#0B0B0C;--off-white:#EDE8DD;--accent:#E6352A;--white:#FFFFFF;--body-size:64px;}}
    *{{box-sizing:border-box;margin:0;padding:0;}}
    html,body{{width:1080px;height:1350px;overflow:hidden;background:var(--near-black);-webkit-font-smoothing:antialiased;}}
    .stage{{position:relative;width:1080px;height:1350px;overflow:hidden;isolation:isolate;}}
    .photo{{position:absolute;inset:0;background:url("{photo_data_url}") center/cover no-repeat;z-index:0;}}
    .top-darken{{position:absolute;inset:0 0 auto 0;height:24%;background:linear-gradient(to bottom,rgba(0,0,0,0.65),rgba(0,0,0,0));z-index:1;}}
    .bottom-darken{{position:absolute;inset:42% 0 0 0;background:linear-gradient(to bottom,rgba(11,11,12,0) 0%,rgba(11,11,12,0.65) 35%,rgba(11,11,12,0.95) 60%,rgba(11,11,12,0.99) 100%);z-index:1;}}
    .vignette{{position:absolute;inset:0;background:radial-gradient(ellipse at center,rgba(0,0,0,0) 65%,rgba(0,0,0,0.30) 100%);z-index:2;pointer-events:none;}}
    .grain{{position:absolute;inset:0;z-index:3;opacity:0.055;mix-blend-mode:overlay;background-image:url("{_GRAIN_SVG}");pointer-events:none;}}
    .top-row{{position:absolute;top:0;left:0;right:0;z-index:10;display:flex;align-items:center;gap:20px;padding:62px 70px 0 70px;}}
    .wordmark-img{{height:28px;width:auto;display:block;opacity:0.95;flex-shrink:0;filter:drop-shadow(1px 1px 0 rgba(0,0,0,0.45));}}
    .top-divider{{flex:1;height:1px;background:var(--off-white);opacity:0.32;}}
    .index{{background:rgba(255,255,255,0.12);color:var(--off-white);font-family:"Space Grotesk",system-ui,sans-serif;font-weight:700;font-size:24px;letter-spacing:0.04em;padding:8px 18px 10px;border-radius:999px;line-height:1;flex-shrink:0;}}
    .lines-wrap{{position:absolute;left:0;right:0;bottom:0;height:50%;z-index:10;padding:0 70px 78px 70px;display:flex;flex-direction:column;justify-content:flex-end;}}
    .lines{{display:flex;flex-direction:column;gap:0.16em;font-size:var(--body-size);}}
    .line{{font-family:"Space Grotesk","Inter",system-ui,sans-serif;font-weight:600;font-size:1em;line-height:1.18;letter-spacing:-0.01em;color:var(--off-white);text-shadow:2px 2px 0 rgba(0,0,0,0.55);text-wrap:balance;}}
    .line .red{{color:var(--accent);font-weight:700;}}
    </style></head><body>
    <div class="stage">
      <div class="photo"></div>
      <div class="top-darken"></div>
      <div class="bottom-darken"></div>
      <div class="vignette"></div>
      <div class="grain"></div>
      <div class="top-row">{logo}<span class="top-divider"></span><div class="index">{index_label}</div></div>
      <div class="lines-wrap"><div class="lines">{lines_html}</div></div>
    </div></body></html>"""


def _render_news_slide_typography_readable(
    serif_url: str, mono_url: str, grotesk_url: str, logo: str, index_label: str,
    lines_html: str,
) -> str:
    """Typography-only slide, readable_list layout. Same half-box as
    the photo variant but on the dark brand background, with the red
    accent rule running down the left edge (kept from compact_legacy
    for visual continuity)."""
    return f"""<!doctype html><html><head><meta charset="utf-8"/><style>
    {_font_faces_readable(serif_url, mono_url, grotesk_url)}
    :root{{--near-black:#0B0B0C;--off-white:#EDE8DD;--accent:#E6352A;--white:#FFFFFF;--body-size:64px;}}
    *{{box-sizing:border-box;margin:0;padding:0;}}
    html,body{{width:1080px;height:1350px;overflow:hidden;background:var(--near-black);-webkit-font-smoothing:antialiased;}}
    .stage{{position:relative;width:1080px;height:1350px;overflow:hidden;background:var(--near-black);}}
    .accent-line{{position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--accent);z-index:2;}}
    .grain{{position:absolute;inset:0;z-index:1;opacity:0.055;mix-blend-mode:overlay;background-image:url("{_GRAIN_SVG}");pointer-events:none;}}
    .top-row{{position:absolute;top:0;left:0;right:0;z-index:10;display:flex;align-items:center;gap:20px;padding:62px 70px 0 86px;}}
    .wordmark-img{{height:28px;width:auto;display:block;opacity:0.88;flex-shrink:0;}}
    .top-divider{{flex:1;height:1px;background:var(--off-white);opacity:0.32;}}
    .index{{background:rgba(255,255,255,0.10);color:var(--off-white);font-family:"Space Grotesk",system-ui,sans-serif;font-weight:700;font-size:24px;letter-spacing:0.04em;padding:8px 18px 10px;border-radius:999px;line-height:1;flex-shrink:0;}}
    .lines-wrap{{position:absolute;left:0;right:0;bottom:0;height:50%;z-index:10;padding:0 70px 78px 86px;display:flex;flex-direction:column;justify-content:center;}}
    .lines{{display:flex;flex-direction:column;gap:0.16em;font-size:var(--body-size);}}
    .line{{font-family:"Space Grotesk","Inter",system-ui,sans-serif;font-weight:600;font-size:1em;line-height:1.18;letter-spacing:-0.01em;color:var(--off-white);text-wrap:balance;}}
    .line .red{{color:var(--accent);font-weight:700;}}
    </style></head><body>
    <div class="stage">
      <div class="accent-line"></div>
      <div class="grain"></div>
      <div class="top-row">{logo}<span class="top-divider"></span><div class="index">{index_label}</div></div>
      <div class="lines-wrap"><div class="lines">{lines_html}</div></div>
    </div></body></html>"""


_AUTOSIZE_JS = """
(() => {
  const wrap  = document.querySelector('.lines-wrap');
  const lines = document.querySelector('.lines');
  if (!wrap || !lines) return;
  const sizes = [64, 58, 52, 46, 40, 34, 28];
  for (const s of sizes) {
    lines.style.setProperty('font-size', s + 'px');
    // Allow the layout to reflow before measuring.
    void lines.offsetHeight;
    if (lines.scrollHeight <= wrap.clientHeight && lines.scrollWidth <= wrap.clientWidth) {
      lines.dataset.fitted = String(s);
      return;
    }
  }
  lines.style.setProperty('font-size', '28px');
  lines.dataset.fitted = '28';
})();
"""


def _autosize_readable_text(page) -> None:
    """Walk font-size from 64 -> 28 px and apply the largest size that
    keeps `.lines` within the `.lines-wrap` half-box bounds. No-op for
    layouts without `.lines-wrap` (compact_legacy)."""
    try:
        page.evaluate(_AUTOSIZE_JS)
    except Exception:
        # Defensive: never let the autosize fail a render. Worst case
        # the slide ships with the CSS default body-size.
        pass


# ------------------------------------------------------------------ #
# Main
# ------------------------------------------------------------------ #

def main() -> int:
    parser = argparse.ArgumentParser(description="Post a breaking Guardian news carousel to Instagram")
    parser.add_argument("--section",     default=None, help="Guardian section override")
    parser.add_argument("--query",       default=None, help="Free-text search query override")
    parser.add_argument("--article-url", default=None, help="Fetch a specific Guardian article by URL (used by watcher)")
    parser.add_argument("--dry-run",     action="store_true", help="Render + host but skip IG publish")
    parser.add_argument("--model",       default=DEFAULT_MODEL)
    parser.add_argument("--max-age",     type=int, default=24, help="Max article age in hours (default 24)")
    parser.add_argument("--out-dir",     default=None, help="Override output dir (dry-run)")
    args = parser.parse_args()

    configure_logging()
    repo_root = Path(__file__).resolve().parents[2]

    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    guardian_key  = os.getenv("GUARDIAN_API_KEY", "test").strip()

    if not anthropic_key:
        _log("ERROR: ANTHROPIC_API_KEY not set")
        return 1

    # Section rotation by weekday
    section = args.section or SECTION_BY_DAY.get(datetime.now().isoweekday(), "world")

    # ---- 1. Fetch article ----
    if args.article_url:
        # Watcher-triggered: fetch a specific article directly
        _log(f"\n[1/6] Fetching specific article (watcher-triggered)...")
        article = fetch_article_by_url(args.article_url, guardian_key)
        if not article:
            _log(f"     Could not fetch article: {args.article_url}")
            return 1
    else:
        # Scheduled: search for newest article in today's section
        _log(f"\n[1/6] Checking Guardian for breaking news (section={section}, max_age={args.max_age}h)...")
        article = fetch_breaking_article(section, guardian_key, max_age_hours=args.max_age, query=args.query)
        if not article:
            _log("     No breaking story found within the time window. Nothing to post.")
            return 0

    _log(f"     Found: \"{article['title']}\"")
    _log(f"     Published: {article['pub_date']}")
    _log(f"     URL: {article['url']}")

    # ---- 2. Dedup check ----
    posted_urls = _load_posted_urls()
    if article["url"] in posted_urls:
        _log("[2/6] Already posted this article -- skipping.")
        return 0
    _log("[2/6] Article is new -- proceeding.")

    # ---- 3. Download article images, with Pexels fallback ----
    _log("[3/6] Downloading article images...")
    image_urls_from_api = extract_image_urls(article)
    _log(f"     Found {len(image_urls_from_api)} unique image(s) in article")

    image_data_urls: list[str] = []
    for img_url in image_urls_from_api:
        data = download_image(img_url)
        if data:
            mime = "image/jpeg" if img_url.lower().endswith((".jpg", ".jpeg")) else "image/png"
            image_data_urls.append(_inline_bytes(data, mime))
            _log(f"     article image {len(image_data_urls)}: {len(data):,}b")
        if len(image_data_urls) >= SLIDES_COUNT:
            break

    # Supplement via editorial sources (Commons, Wikipedia, Openverse, Smithsonian)
    # if the article has fewer than 4 unique photos. Pexels is not used here:
    # news articles cover specific named subjects and Pexels cannot be trusted
    # to return relevant images for proper nouns.
    MIN_ARTICLE_IMAGES = 4
    if len(image_data_urls) < MIN_ARTICLE_IMAGES:
        needed    = SLIDES_COUNT - len(image_data_urls)
        query     = _pexels_query_for_article(article)
        post_slug = re.sub(r"[^a-z0-9]+", "-", article["title"].lower())[:40]
        _log(f"     < {MIN_ARTICLE_IMAGES} article images -- editorial fallback (query: \"{query}\", need {needed})")
        sourcer = ImageSourcer(topic="editorial", use_fresh_ledger=False)
        extras  = sourcer.source_images([query] * needed, ImageIntent.news_intent(), post_slug)
        for url in extras:
            if url:
                image_data_urls.append(url)
        filled = sum(1 for u in extras if u)
        _log(f"     editorial fallback: {filled}/{needed} slots filled")

    if not image_data_urls:
        _log("     No images available -- photo zone will be empty.")

    # ---- 4. Compress to slides ----
    _log(f"[4/6] Compressing article to slides with Claude (count decided by Claude)...")
    slides_payload, usage = compress_to_slides(article, args.model, anthropic_key)
    carousel_title = slides_payload.get("title", article["title"])
    cover_title    = slides_payload.get("cover_title", carousel_title)
    _log(f"     Cover title: \"{cover_title}\"")
    _log(f"     {usage['input_tokens']:,} in / {usage['output_tokens']:,} out  ~${usage['cost_usd']:.4f}")

    # ---- 5. Render slides ----
    # Slide 1 = cover (full-bleed photo + title, production carousel style)
    # Slides 2-N = content (black bg, white text, red key words)
    # Total = SLIDES_COUNT + 1
    _log("[5/6] Rendering carousel slides...")
    # Cover pill shows the section category (no Guardian attribution on slides --
    # Guardian is credited in the caption/description only)
    source_label = article.get("section", "News").upper()
    slides = slides_payload["slides"]
    total_slides = len(slides) + 1  # +1 for cover

    # Cover uses the first (most editorial) image available
    cover_photo = image_data_urls[0] if image_data_urls else ""
    # Content slides cycle through remaining images
    content_images = image_data_urls[1:] if len(image_data_urls) > 1 else image_data_urls

    slide_paths: list[Path] = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()

            # Cover slide
            cover_path = tmp_dir / "slide_01.png"
            render_cover_slide(
                cover_title=cover_title,
                source_label=source_label,
                photo_data_url=cover_photo,
                out_path=cover_path,
                index=1,
                total=total_slides,
                repo_root=repo_root,
                browser=browser,
            )
            slide_paths.append(cover_path)
            _log("     cover done")

            # Content slides
            for idx, slide in enumerate(slides, start=2):
                img_idx = (idx - 2) % max(len(content_images), 1)
                photo_data_url = content_images[img_idx] if content_images else ""
                out_path = tmp_dir / f"slide_{idx:02d}.png"
                render_news_slide(
                    lines=slide["lines"],
                    photo_data_url=photo_data_url,
                    out_path=out_path,
                    index=idx,
                    total=total_slides,
                    source_label=source_label,
                    repo_root=repo_root,
                    browser=browser,
                )
                slide_paths.append(out_path)
                _log(f"     slide {idx} done")
            browser.close()

        # ---- 6. Host images ----
        _log("[6/6] Hosting slides and publishing...")
        image_host = make_image_host()
        image_urls: list[str] = []
        for path in slide_paths:
            hosted = image_host.upload(path)
            image_urls.append(hosted.public_url)
            _log(f"     uploaded: {hosted.public_url[:60]}...")

        caption = build_caption(article, carousel_title, article.get("trail", ""))

        if args.dry_run:
            _log("\n[DRY RUN] Skipping Instagram publish.")
            _log(f"Caption preview:\n{caption[:300]}...")
            # Save slides to output/news/YYYY-MM-DD_HH-MM_SECTION (or --out-dir override)
            from datetime import datetime as _dt
            ts = _dt.now().strftime("%Y-%m-%d_%H-%M")
            safe_section = re.sub(r"[^A-Za-z0-9]+", "-", section.lower())
            default_save = repo_root / "output" / "news" / f"{ts}_{safe_section}"
            save_dir = Path(args.out_dir) if args.out_dir else default_save
            save_dir.mkdir(parents=True, exist_ok=True)
            for p in slide_paths:
                shutil.copy(p, save_dir / p.name)
            _log(f"Slides saved to: {save_dir.resolve()}")
            _log_posted(article, caption, len(slides))
            _log("Ledger updated (dry-run).")
            return 0

        publisher = InstagramGraphPublisher(
            account_id=os.getenv("INSTAGRAM_ACCOUNT_ID", ""),
            access_token=os.getenv("META_ACCESS_TOKEN", ""),
            graph_host=os.getenv("META_GRAPH_HOST", "graph.instagram.com"),
            graph_version=os.getenv("META_GRAPH_VERSION", "v21.0"),
        )
        result = publisher.publish_carousel(image_urls, caption)
        _log(f"\nPosted! Media ID: {result.get('id', 'unknown')}")

    _log_posted(article, caption, len(slides))
    _log(f"Ledger updated: {NEWS_LEDGER}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
