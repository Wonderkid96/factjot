#!/usr/bin/env python3
"""Guardian news article -> branded Instagram carousel.

Fetches a real news article from The Guardian API, compresses it into
8 slides via Claude, and renders 1080x1350 PNGs using the factjot brand
with an accent-red background instead of the standard near-black.

Usage:
    python tests/guardian_news_carousel.py --query "climate change"
    python tests/guardian_news_carousel.py --query "artificial intelligence" --slides 8
    python tests/guardian_news_carousel.py --article-url "https://www.theguardian.com/..."

Guardian API key:
    Register free at https://open-platform.theguardian.com/
    Set GUARDIAN_API_KEY in .env — falls back to the public 'test' key for development.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
from pathlib import Path
from typing import Any

import requests
from anthropic import Anthropic
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright


GUARDIAN_BASE  = "https://content.guardianapis.com"
DEFAULT_MODEL  = "claude-haiku-4-5-20251001"
DEFAULT_SLIDES = 8

_PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-6":         {"input": 3.00, "output": 15.00},
    "claude-opus-4-7":           {"input": 15.00, "output": 75.00},
}


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

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
        ".png": "image/png", ".webp": "image/webp",
    }.get(path.suffix.lower(), "application/octet-stream")
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _inline_bytes(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _usage_info(model: str, res: Any) -> dict[str, Any]:
    input_tok  = res.usage.input_tokens
    output_tok = res.usage.output_tokens
    rates = _PRICING.get(model, {"input": 0.0, "output": 0.0})
    cost  = (input_tok / 1_000_000) * rates["input"] + (output_tok / 1_000_000) * rates["output"]
    return {
        "model": model,
        "input_tokens": input_tok, "output_tokens": output_tok,
        "total_tokens": input_tok + output_tok,
        "cost_usd": round(cost, 6),
    }


def parse_json_from_model_text(raw: str) -> dict[str, Any]:
    text = raw.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", text, re.IGNORECASE)
    if fenced:
        return json.loads(fenced.group(1))
    s, e = text.find("{"), text.rfind("}")
    if s != -1 and e > s:
        return json.loads(text[s: e + 1])
    raise RuntimeError("Could not parse JSON from model output")


# ------------------------------------------------------------------ #
# Guardian API
# ------------------------------------------------------------------ #

def fetch_guardian_by_query(query: str, api_key: str) -> dict[str, Any]:
    """Fetch the most relevant article for a search query."""
    resp = requests.get(
        f"{GUARDIAN_BASE}/search",
        params={
            "q": query,
            "api-key": api_key,
            "show-fields": "bodyText,thumbnail,trailText,headline",
            "order-by": "relevance",
            "page-size": 1,
        },
        timeout=15,
    )
    resp.raise_for_status()
    results = resp.json()["response"]["results"]
    if not results:
        raise RuntimeError(f"No Guardian articles found for: {query!r}")
    return _parse_guardian_result(results[0])


def fetch_guardian_by_url(article_url: str, api_key: str) -> dict[str, Any]:
    """Fetch a specific Guardian article by its URL."""
    # Extract the path after theguardian.com
    match = re.search(r"theguardian\.com(/[^\s?#]+)", article_url)
    if not match:
        raise ValueError(f"Not a Guardian URL: {article_url}")
    path = match.group(1).lstrip("/")
    resp = requests.get(
        f"{GUARDIAN_BASE}/{path}",
        params={
            "api-key": api_key,
            "show-fields": "bodyText,thumbnail,trailText,headline",
        },
        timeout=15,
    )
    resp.raise_for_status()
    content = resp.json()["response"]["content"]
    return _parse_guardian_result(content)


def _parse_guardian_result(item: dict) -> dict[str, Any]:
    fields = item.get("fields", {})
    return {
        "title":     item.get("webTitle", ""),
        "url":       item.get("webUrl", ""),
        "section":   item.get("sectionName", ""),
        "date":      item.get("webPublicationDate", "")[:10],
        "body":      fields.get("bodyText", ""),
        "trail":     fields.get("trailText", ""),
        "thumbnail": fields.get("thumbnail", ""),
    }


def download_thumbnail(url: str, out_path: Path) -> bool:
    """Download the article thumbnail. Returns True on success."""
    if not url:
        return False
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(resp.content)
        return True
    except Exception:
        return False


# ------------------------------------------------------------------ #
# Claude compression
# ------------------------------------------------------------------ #

def compress_article_to_slides(
    article: dict[str, Any],
    slides_count: int,
    model: str,
    api_key: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Single-stage: article text -> slide JSON.

    News articles are already structured prose, so no Stage 1 narrative
    compression is needed -- we go straight to slide formatting.
    """
    body = article["body"]
    # Guardian bodyText can be very long -- cap at ~5000 chars to stay within
    # a reasonable token budget while keeping the most important content.
    if len(body) > 5000:
        body = body[:5000].rsplit(" ", 1)[0] + "..."

    article_text = f"Headline: {article['title']}\n\n{body}"

    prompt = f"""
You are turning a news article into an Instagram carousel for a factual editorial account.

Create exactly {slides_count} slides that:
- Tell the story from start to finish in logical, chronological order
- Each slide covers ONE clear idea or development in the story
- Each slide: exactly 4 lines, 6-9 words per line
- Lines within each slide must connect — cause, consequence, or contrast
- Read as editorial journalism: clear, confident, factual, direct
- No filler, no padding, no repetition
- Do not begin multiple consecutive lines with the same word
- The full set of slides must give a reader the complete picture of the story

Output JSON only:
{{
  "title": "short punchy headline (max 7 words)",
  "slides": [
    {{"slideNumber": 1, "lines": ["...", "...", "...", "..."]}}
  ]
}}

Exactly {slides_count} slides. Exactly 4 lines each. Return JSON only.

Article:
{article_text}
""".strip()

    client = Anthropic(api_key=api_key)
    res = client.messages.create(
        model=model, max_tokens=2500, temperature=0.2,
        messages=[{"role": "user", "content": prompt}],
    )
    data = parse_json_from_model_text(res.content[0].text)

    slides = data.get("slides", [])
    if len(slides) != slides_count:
        raise RuntimeError(f"Expected {slides_count} slides, got {len(slides)}")
    for i, s in enumerate(slides, 1):
        if not isinstance(s.get("lines"), list) or len(s["lines"]) != 4:
            raise RuntimeError(f"Slide {i} must have 4 lines")

    return data, _usage_info(model, res)


# ------------------------------------------------------------------ #
# Rendering -- red-tinted brand style
# ------------------------------------------------------------------ #

def render_news_slide(
    lines: list[str],
    image_path: Path | None,
    out_path: Path,
    index: int,
    total: int,
    carousel_title: str,
    source_label: str,
    browser: Any,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]

    photo_url = _inline_asset(image_path) if image_path and image_path.exists() else ""
    logo_url  = _inline_asset(repo_root / "assets/logo/factjot_mark.png")
    serif_url = _inline_asset(repo_root / "assets/fonts/InstrumentSerif-Regular.ttf")
    mono_url  = _inline_asset(repo_root / "assets/fonts/JetBrainsMono-Bold.ttf")

    index_label = f"{index}/{total}"

    # Source label -- e.g. "THE GUARDIAN" or section name, capped to fit
    pill = source_label.upper()[:28]

    logo_tag = (
        f'<img class="wordmark-img" src="{logo_url}" alt="factjot" />'
        if logo_url else
        '<span class="wordmark-text">fact<span class="ital">jot</span><span class="dot">.</span></span>'
    )

    lines_html = "\n".join(
        f'<div class="line">{escape_html(line)}</div>' for line in lines
    )

    photo_zone_html = (
        f'<div class="photo-zone"><img src="{photo_url}" alt="" /></div>'
        if photo_url else
        '<div class="photo-zone photo-empty"></div>'
    )

    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    @font-face {{
      font-family: "Instrument Serif";
      src: url("{serif_url}") format("truetype");
      font-weight: 400; font-style: normal;
    }}
    @font-face {{
      font-family: "JetBrains Mono";
      src: url("{mono_url}") format("truetype");
      font-weight: 700; font-style: normal;
    }}

    :root {{
      --red:       #E6352A;
      --red-dark:  #C42B22;
      --off-white: #EDE8DD;
      --white:     #FFFFFF;
    }}

    * {{ box-sizing: border-box; margin: 0; padding: 0; }}

    html, body {{
      width: 1080px; height: 1350px;
      overflow: hidden;
      background: var(--red);
      -webkit-font-smoothing: antialiased;
    }}

    .stage {{
      position: relative;
      width: 1080px; height: 1350px;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      background: var(--red);
    }}

    /* ---- TEXT ZONE ---- */
    .text-zone {{
      flex: 0 0 auto;
      padding: 64px 70px 0 70px;
      display: flex;
      flex-direction: column;
    }}

    .top-row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 38px;
    }}

    .wordmark-img {{
      height: 28px; width: auto; display: block;
      opacity: 0.88;
      filter: brightness(0) invert(1);
    }}
    .wordmark-text {{
      font-family: "Instrument Serif", serif;
      font-size: 26px; color: var(--white); opacity: 0.88;
    }}
    .wordmark-text .ital {{ font-style: italic; }}

    .counter {{
      background: rgba(0,0,0,0.22);
      color: var(--white);
      font-family: "JetBrains Mono", monospace;
      font-weight: 700;
      font-size: 26px;
      letter-spacing: 0.04em;
      padding: 9px 20px 11px;
      border-radius: 999px;
      line-height: 1;
    }}

    /* Source pill */
    .source-pill {{
      align-self: flex-start;
      background: rgba(0,0,0,0.22);
      color: var(--white);
      font-family: "JetBrains Mono", monospace;
      font-weight: 700;
      font-size: 17px;
      letter-spacing: 0.24em;
      padding: 7px 16px 9px;
      border-radius: 999px;
      text-transform: uppercase;
      line-height: 1;
      margin-bottom: 28px;
    }}

    .lines {{
      display: flex;
      flex-direction: column;
    }}

    .line {{
      font-family: "Instrument Serif", Georgia, serif;
      font-weight: 400;
      font-size: 52px;
      line-height: 1.18;
      color: var(--white);
      letter-spacing: -0.01em;
      margin-bottom: 18px;
    }}

    /* ---- PHOTO ZONE ---- */
    .photo-zone {{
      flex: 1 1 0;
      margin: 32px 50px 50px 50px;
      overflow: hidden;
      border-radius: 6px;
      background: rgba(0,0,0,0.25);
    }}

    .photo-zone img {{
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }}

    .photo-empty {{
      background: rgba(0,0,0,0.18);
    }}

    /* factjot. watermark */
    .corner-mark {{
      position: absolute;
      right: 62px; bottom: 62px; z-index: 20;
      font-family: "Instrument Serif", serif;
      font-size: 28px; line-height: 1;
      letter-spacing: -0.01em;
      color: var(--white); opacity: 0.55;
      pointer-events: none;
    }}
    .corner-mark .ital {{ font-style: italic; }}
  </style>
</head>
<body>
  <div class="stage">

    <div class="text-zone">
      <div class="top-row">
        {logo_tag}
        <div class="counter">{index_label}</div>
      </div>
      <div class="source-pill">{escape_html(pill)}</div>
      <div class="lines">
{lines_html}
      </div>
    </div>

    {photo_zone_html}

    <div class="corner-mark">fact<span class="ital">jot</span>.</div>

  </div>
</body>
</html>"""

    page = browser.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=2)
    page.set_content(html, wait_until="networkidle")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(
        path=str(out_path), full_page=False,
        clip={"x": 0, "y": 0, "width": 1080, "height": 1350},
    )
    page.close()


# ------------------------------------------------------------------ #
# Main
# ------------------------------------------------------------------ #

def main() -> None:
    parser = argparse.ArgumentParser(description="Guardian article -> branded red news carousel")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--query", help="Search query, e.g. 'climate change'")
    group.add_argument("--article-url", help="Direct Guardian article URL")
    parser.add_argument("--slides",        type=int, default=DEFAULT_SLIDES, choices=[6, 7, 8, 9, 10])
    parser.add_argument("--project-name",  default="guardian-news")
    parser.add_argument("--model",         default=DEFAULT_MODEL)
    parser.add_argument("--force",         action="store_true", help="Re-run Claude even if cached")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    load_dotenv(repo_root / ".env")
    anthropic_key  = os.getenv("ANTHROPIC_API_KEY", "").strip()
    guardian_key   = os.getenv("GUARDIAN_API_KEY", "test").strip()

    if not anthropic_key:
        raise RuntimeError("Missing ANTHROPIC_API_KEY in .env")

    out_dir    = repo_root / "output" / "experiments" / args.project_name
    slides_dir = out_dir / "slides"
    for d in [out_dir, slides_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # ---- Fetch article ----
    article_path = out_dir / "article.json"
    if article_path.exists() and not args.force:
        print("\n[1/4] Article cached -- skipping Guardian fetch.")
        article = json.loads(article_path.read_text())
    else:
        print("\n[1/4] Fetching article from The Guardian...")
        if args.query:
            article = fetch_guardian_by_query(args.query, guardian_key)
        else:
            article = fetch_guardian_by_url(args.article_url, guardian_key)
        article_path.write_text(json.dumps(article, indent=2), encoding="utf-8")
        print(f"       \"{article['title']}\"")
        print(f"       {article['url']}")

    # ---- Download thumbnail ----
    thumb_path = out_dir / "thumbnail.jpg"
    if not thumb_path.exists():
        ok = download_thumbnail(article.get("thumbnail", ""), thumb_path)
        print(f"[1b/4] Thumbnail: {'downloaded' if ok else 'not available'}")

    # ---- Claude compression ----
    slides_json_path = out_dir / "slides.json"
    usage_path       = out_dir / "api_usage.json"

    if slides_json_path.exists() and not args.force:
        print("[2/4] Slides cached -- skipping Claude call.")
        slides_payload = json.loads(slides_json_path.read_text())
        usage = json.loads(usage_path.read_text()) if usage_path.exists() else {}
    else:
        print(f"[2/4] Compressing article into {args.slides} slides with Claude...")
        slides_payload, usage = compress_article_to_slides(
            article, args.slides, args.model, anthropic_key,
        )
        slides_json_path.write_text(json.dumps(slides_payload, indent=2), encoding="utf-8")
        usage_path.write_text(json.dumps(usage, indent=2), encoding="utf-8")
        print(f"       {usage['input_tokens']:,} in / {usage['output_tokens']:,} out  ~${usage['cost_usd']:.4f}")

    # ---- Render ----
    source_label = f"The Guardian  •  {article.get('section', 'News')}"
    carousel_title = slides_payload.get("title", article["title"])
    slides = slides_payload["slides"]

    print(f"[3/4] Rendering {len(slides)} slides...")

    # Clear previous renders so visual changes take effect
    for f in slides_dir.glob("slide_*.png"):
        f.unlink()

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for idx, slide in enumerate(slides, start=1):
            out_path = slides_dir / f"slide_{idx:02d}.png"
            print(f"  slide {idx}...")
            render_news_slide(
                lines=slide["lines"],
                image_path=thumb_path if thumb_path.exists() else None,
                out_path=out_path,
                index=idx,
                total=len(slides),
                carousel_title=carousel_title,
                source_label=source_label,
                browser=browser,
            )
        browser.close()

    print(f"\n[4/4] Done.")
    print(f"Title:  {carousel_title}")
    print(f"Source: {article['url']}")
    print(f"Output: {out_dir}/slides/")
    if usage:
        print(f"Cost:   ~${usage.get('cost_usd', 0):.4f} USD  ({args.model})")


if __name__ == "__main__":
    main()
