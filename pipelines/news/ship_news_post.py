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
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3 scripts/ship_news_post.py
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3 scripts/ship_news_post.py --dry-run
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3 scripts/ship_news_post.py --section technology
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3 scripts/ship_news_post.py --query "AI regulation EU"
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

from src.publish.image_host import make_image_host
from src.publish.instagram_publisher import InstagramGraphPublisher
from src.utils.logging_utils import configure_logging

# ------------------------------------------------------------------ #
# Constants
# ------------------------------------------------------------------ #

GUARDIAN_BASE = "https://content.guardianapis.com"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
SLIDES_COUNT  = 8
NEWS_LEDGER   = Path("data/ledgers/news_posts.jsonl")

# Weekday -> Guardian section (Mon=1 .. Sun=7)
SECTION_BY_DAY: dict[int, str] = {
    1: "world",
    2: "technology",
    3: "science",
    4: "environment",
    5: "world",
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
    """Return the most recent fresh article, including all inline image elements."""
    params: dict = {
        "api-key":      guardian_key,
        "show-fields":  "bodyText,thumbnail,trailText,headline",
        "show-elements": "image",
        "order-by":     "newest",
        "page-size":    5,
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
        return {
            "title":      item["webTitle"],
            "url":        item["webUrl"],
            "section":    item.get("sectionName", section),
            "pub_date":   item["webPublicationDate"],
            "body":       body,
            "trail":      fields.get("trailText", ""),
            "thumbnail":  fields.get("thumbnail", ""),
            "elements":   item.get("elements", []),
        }
    return None


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

    # Always include the thumbnail as a fallback if we have nothing else
    thumb = article.get("thumbnail", "")
    if thumb and thumb not in seen:
        urls.append(thumb)

    return urls


def download_image(url: str) -> bytes | None:
    if not url:
        return None
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return r.content
    except Exception:
        return None


# ------------------------------------------------------------------ #
# Claude compression
# ------------------------------------------------------------------ #

def compress_to_slides(
    article: dict, slides_count: int, model: str, api_key: str,
) -> tuple[dict, dict]:
    body = article["body"]
    if len(body) > 5000:
        body = body[:5000].rsplit(" ", 1)[0] + "..."

    article_text = f"Headline: {article['title']}\n\n{body}"

    prompt = f"""
You are turning a news article into an Instagram carousel for a factual editorial account.

Create exactly {slides_count} slides that:
- Tell the story from start to finish in logical order
- Each slide covers ONE clear idea or development in the story
- Each slide: exactly 4 lines, 6-9 words per line
- Lines within each slide must connect — cause, consequence, or contrast
- Read as editorial journalism: clear, confident, factual, direct
- No filler, no padding, no repetition across slides
- Do not begin multiple consecutive lines with the same word
- A reader following all slides in order gets the full picture

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
    if len(slides) != slides_count:
        raise RuntimeError(f"Expected {slides_count} slides, got {len(slides)}")
    for i, s in enumerate(slides, 1):
        if not isinstance(s.get("lines"), list) or len(s["lines"]) != 4:
            raise RuntimeError(f"Slide {i} must have 4 lines")

    input_tok  = res.usage.input_tokens
    output_tok = res.usage.output_tokens
    rates = _PRICING.get(model, {"input": 0.0, "output": 0.0})
    cost  = (input_tok / 1_000_000) * rates["input"] + (output_tok / 1_000_000) * rates["output"]
    usage = {"model": model, "input_tokens": input_tok, "output_tokens": output_tok, "cost_usd": round(cost, 6)}
    return data, usage


# ------------------------------------------------------------------ #
# Caption
# ------------------------------------------------------------------ #

SECTION_HASHTAGS: dict[str, str] = {
    "world":       "#WorldNews #BreakingNews #GlobalNews",
    "technology":  "#Tech #Technology #TechNews",
    "science":     "#Science #ScienceNews #Discovery",
    "environment": "#Climate #Environment #ClimateNews",
    "uk-news":     "#UKNews #Britain #PoliticsUK",
}

NEWS_HASHTAGS = "#News #FactJot #LearnOnInstagram #DidYouKnow #Interesting #Viral #Facts"


def build_caption(article: dict, carousel_title: str, trail: str) -> str:
    pub = article["pub_date"][:10]
    section = article.get("section", "world").lower().replace(" ", "-")
    section_tags = SECTION_HASHTAGS.get(section, "#News #WorldNews")

    intro = trail.strip() if trail else carousel_title
    # Strip HTML tags from trail text if any
    intro = re.sub(r"<[^>]+>", "", intro).strip()

    return (
        f"{intro}\n\n"
        f"Source: The Guardian ({pub})\n"
        f"Read more: {article['url']}\n\n"
        f"{section_tags} {NEWS_HASHTAGS}"
    )


# ------------------------------------------------------------------ #
# Render -- red brand style
# ------------------------------------------------------------------ #

def render_news_slide(
    lines: list[str],
    photo_data_url: str,
    out_path: Path,
    index: int,
    total: int,
    source_label: str,
    repo_root: Path,
    browser,
) -> None:
    logo_url  = _inline_asset(repo_root / "assets/logo/factjot_mark.png")
    serif_url = _inline_asset(repo_root / "assets/fonts/InstrumentSerif-Regular.ttf")
    mono_url  = _inline_asset(repo_root / "assets/fonts/JetBrainsMono-Bold.ttf")

    index_label = f"{index}/{total}"
    pill = source_label.upper()[:32]

    logo_tag = (
        f'<img class="wordmark-img" src="{logo_url}" alt="factjot" />'
        if logo_url else
        '<span class="wm">factjot.</span>'
    )

    lines_html = "\n".join(f'<div class="line">{escape_html(ln)}</div>' for ln in lines)

    photo_zone = (
        f'<div class="photo-zone"><img src="{photo_data_url}" alt="" /></div>'
        if photo_data_url else
        '<div class="photo-zone photo-empty"></div>'
    )

    html = f"""<!doctype html><html><head><meta charset="utf-8"/><style>
    @font-face{{font-family:"Instrument Serif";src:url("{serif_url}") format("truetype");font-weight:400;font-style:normal;}}
    @font-face{{font-family:"JetBrains Mono";src:url("{mono_url}") format("truetype");font-weight:700;font-style:normal;}}
    :root{{--red:#E6352A;--white:#FFFFFF;--off-white:#EDE8DD;}}
    *{{box-sizing:border-box;margin:0;padding:0;}}
    html,body{{width:1080px;height:1350px;overflow:hidden;background:var(--red);-webkit-font-smoothing:antialiased;}}
    .stage{{position:relative;width:1080px;height:1350px;overflow:hidden;display:flex;flex-direction:column;background:var(--red);}}
    .text-zone{{flex:0 0 auto;padding:64px 70px 0 70px;display:flex;flex-direction:column;}}
    .top-row{{display:flex;align-items:center;justify-content:space-between;margin-bottom:36px;}}
    .wordmark-img{{height:28px;width:auto;display:block;opacity:0.88;filter:brightness(0) invert(1);}}
    .wm{{font-family:"Instrument Serif",serif;font-size:26px;color:var(--white);opacity:0.88;}}
    .counter{{background:rgba(0,0,0,0.22);color:var(--white);font-family:"JetBrains Mono",monospace;font-weight:700;font-size:26px;letter-spacing:0.04em;padding:9px 20px 11px;border-radius:999px;line-height:1;}}
    .source-pill{{align-self:flex-start;background:rgba(0,0,0,0.22);color:var(--white);font-family:"JetBrains Mono",monospace;font-weight:700;font-size:16px;letter-spacing:0.22em;padding:7px 16px 9px;border-radius:999px;text-transform:uppercase;line-height:1;margin-bottom:26px;}}
    .lines{{display:flex;flex-direction:column;}}
    .line{{font-family:"Instrument Serif",Georgia,serif;font-weight:400;font-size:52px;line-height:1.18;color:var(--white);letter-spacing:-0.01em;margin-bottom:18px;}}
    .photo-zone{{flex:1 1 0;margin:28px 50px 50px 50px;overflow:hidden;border-radius:6px;background:rgba(0,0,0,0.22);}}
    .photo-zone img{{width:100%;height:100%;object-fit:cover;display:block;}}
    .photo-empty{{background:rgba(0,0,0,0.18);}}
    .corner-mark{{position:absolute;right:62px;bottom:62px;z-index:20;font-family:"Instrument Serif",serif;font-size:28px;line-height:1;letter-spacing:-0.01em;color:var(--white);opacity:0.55;pointer-events:none;}}
    .corner-mark .ital{{font-style:italic;}}
    </style></head><body>
    <div class="stage">
      <div class="text-zone">
        <div class="top-row">{logo_tag}<div class="counter">{index_label}</div></div>
        <div class="source-pill">{escape_html(pill)}</div>
        <div class="lines">{lines_html}</div>
      </div>
      {photo_zone}
      <div class="corner-mark">fact<span class="ital">jot</span>.</div>
    </div></body></html>"""

    page = browser.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=2)
    page.set_content(html, wait_until="networkidle")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out_path), full_page=False, clip={"x": 0, "y": 0, "width": 1080, "height": 1350})
    page.close()


# ------------------------------------------------------------------ #
# Main
# ------------------------------------------------------------------ #

def main() -> int:
    parser = argparse.ArgumentParser(description="Post a breaking Guardian news carousel to Instagram")
    parser.add_argument("--section",  default=None, help="Guardian section override")
    parser.add_argument("--query",    default=None, help="Search query override")
    parser.add_argument("--dry-run",  action="store_true", help="Render + host but skip IG publish")
    parser.add_argument("--model",    default=DEFAULT_MODEL)
    parser.add_argument("--max-age",  type=int, default=24, help="Max article age in hours (default 24)")
    parser.add_argument("--out-dir",  default=None, help="Override output dir (dry-run); defaults to output/news/YYYY-MM-DD_HH-MM_SECTION")
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

    # ---- 1. Fetch breaking article ----
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

    # ---- 3. Download all article images ----
    _log("[3/6] Downloading article images...")
    image_urls_from_api = extract_image_urls(article)
    _log(f"     Found {len(image_urls_from_api)} image(s) in article")

    # Download each unique image; skip any that fail
    image_data_urls: list[str] = []
    for img_url in image_urls_from_api:
        data = download_image(img_url)
        if data:
            mime = "image/jpeg" if img_url.lower().endswith((".jpg", ".jpeg")) else "image/png"
            image_data_urls.append(_inline_bytes(data, mime))
            _log(f"     downloaded {len(data):,}b  {img_url[-50:]}")
        if len(image_data_urls) >= SLIDES_COUNT:
            break  # no point fetching more than we can use

    if not image_data_urls:
        _log("     No images available -- photo zone will be empty.")

    # ---- 4. Compress to slides ----
    _log(f"[4/6] Compressing article to {SLIDES_COUNT} slides with Claude...")
    slides_payload, usage = compress_to_slides(article, SLIDES_COUNT, args.model, anthropic_key)
    carousel_title = slides_payload.get("title", article["title"])
    _log(f"     Title: \"{carousel_title}\"")
    _log(f"     {usage['input_tokens']:,} in / {usage['output_tokens']:,} out  ~${usage['cost_usd']:.4f}")

    # ---- 5. Render slides ----
    _log("[5/6] Rendering carousel slides...")
    source_label = f"The Guardian  •  {article['section']}"
    slides = slides_payload["slides"]

    slide_paths: list[Path] = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for idx, slide in enumerate(slides, start=1):
                # Cycle through available images; each slide gets its own where possible
                if image_data_urls:
                    photo_data_url = image_data_urls[(idx - 1) % len(image_data_urls)]
                else:
                    photo_data_url = ""
                out_path = tmp_dir / f"slide_{idx:02d}.png"
                render_news_slide(
                    lines=slide["lines"],
                    photo_data_url=photo_data_url,
                    out_path=out_path,
                    index=idx,
                    total=len(slides),
                    source_label=source_label,
                    repo_root=repo_root,
                    browser=browser,
                )
                slide_paths.append(out_path)
                _log(f"     slide {idx} done  [image {((idx-1) % max(len(image_data_urls),1)) + 1}/{max(len(image_data_urls),1)}]")
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
