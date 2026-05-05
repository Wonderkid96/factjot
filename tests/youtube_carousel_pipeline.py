#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright


DEFAULT_MODEL = "claude-haiku-4-5-20251001"

# Words per slide * slides = target narrative length.
# 4 lines * 6 words avg = 24 words/slide.
WORDS_PER_SLIDE = 24


@dataclass
class Cue:
    start: float
    end: float
    text: str


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def run_cmd(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print(">", " ".join(cmd))
    return subprocess.run(cmd, check=check, text=True, capture_output=True)


def sec_to_hhmmss(seconds: float) -> str:
    total = int(max(0, round(seconds)))
    hh = total // 3600
    mm = (total % 3600) // 60
    ss = total % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def to_seconds_with_ms(ts: str) -> float:
    hh, mm, sec_ms = ts.split(":")
    sec, ms = sec_ms.split(".")
    return int(hh) * 3600 + int(mm) * 60 + int(sec) + int(ms) / 1000


def clean_caption_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _inline_asset(path: Path) -> str:
    """Inline a file as a base64 data URI. Returns '' if the file doesn't exist."""
    if not path.exists():
        return ""
    suffix = path.suffix.lower()
    mime = {
        ".ttf": "font/ttf", ".otf": "font/otf",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp",
    }.get(suffix, "application/octet-stream")
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def parse_vtt(vtt_path: Path) -> list[Cue]:
    lines = vtt_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    cues: list[Cue] = []
    i = 0
    time_re = re.compile(r"(\d\d:\d\d:\d\d\.\d+)\s+-->\s+(\d\d:\d\d:\d\d\.\d+)")
    while i < len(lines):
        match = time_re.search(lines[i])
        if not match:
            i += 1
            continue
        start_s, end_s = match.groups()
        start = to_seconds_with_ms(start_s)
        end = to_seconds_with_ms(end_s)
        i += 1
        block_text: list[str] = []
        while i < len(lines) and lines[i].strip():
            block_text.append(lines[i])
            i += 1
        text = clean_caption_text(" ".join(block_text))
        if text:
            cues.append(Cue(start=start, end=end, text=text))
        i += 1
    if not cues:
        raise RuntimeError("No cues parsed from VTT file.")
    return cues


def parse_json_from_model_text(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    if not text:
        raise RuntimeError("Model returned empty text")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", text, flags=re.IGNORECASE)
    if fenced:
        return json.loads(fenced.group(1))
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start: end + 1])
    raise RuntimeError("Could not parse JSON from model output")


def get_video_duration(video_path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


# ------------------------------------------------------------------ #
# API pricing
# ------------------------------------------------------------------ #

_PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-6":         {"input": 3.00, "output": 15.00},
    "claude-opus-4-7":           {"input": 15.00, "output": 75.00},
}


def _usage_info(model: str, res: Any, stage: str) -> dict[str, Any]:
    input_tok = res.usage.input_tokens
    output_tok = res.usage.output_tokens
    rates = _PRICING.get(model, {"input": 0.0, "output": 0.0})
    cost = (input_tok / 1_000_000) * rates["input"] + (output_tok / 1_000_000) * rates["output"]
    return {
        "stage": stage, "model": model,
        "input_tokens": input_tok, "output_tokens": output_tok,
        "total_tokens": input_tok + output_tok,
        "cost_usd": round(cost, 6),
    }


# ------------------------------------------------------------------ #
# Stage 1: transcript -> clean narrative
# ------------------------------------------------------------------ #

def request_narrative_from_claude(
    cues: list[Cue], slides_count: int, model: str, api_key: str,
) -> tuple[str, dict[str, Any]]:
    """Compress the transcript into N structured paragraphs, one per slide."""
    transcript_text = "\n".join(f"[{sec_to_hhmmss(c.start)}] {c.text}" for c in cues)
    prompt = f"""
You are summarizing a video transcript into structured slide sections.

Write exactly {slides_count} numbered paragraphs. Each paragraph will become one carousel slide.

Requirements:
- Each paragraph covers ONE clear idea or moment from the video — no mixing topics
- Paragraphs follow the video in strict chronological order
- Each paragraph: 3-5 sentences, ~25 words, written as clear connected prose
- Every sentence within a paragraph must connect to the next — cause, consequence, contrast, or elaboration
- Paragraphs must flow from one to the next — each builds on what came before
- Remove all filler, repetition, and false starts from the transcript
- Factually accurate — only include what the video actually states

Format:
1. [first idea]

2. [second idea]

...and so on to {slides_count}.

Output ONLY the numbered paragraphs. No headings, no extra commentary.

Transcript:
{transcript_text}
""".strip()

    client = Anthropic(api_key=api_key)
    res = client.messages.create(
        model=model, max_tokens=1400, temperature=0.3,
        messages=[{"role": "user", "content": prompt}],
    )
    return res.content[0].text.strip(), _usage_info(model, res, "narrative")


# ------------------------------------------------------------------ #
# Stage 2: narrative -> slide copy
# ------------------------------------------------------------------ #

def request_slides_from_claude(
    narrative: str, slides_count: int, model: str, api_key: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Format each narrative paragraph into 4 punchy, connected slide lines."""
    prompt = f"""
You are formatting pre-written narrative paragraphs into visual slide copy for an Instagram carousel.

The input below contains exactly {slides_count} numbered paragraphs. Each paragraph becomes one slide.
Rewrite each paragraph as exactly 4 punchy lines for visual display.

Rules per slide:
- Exactly 4 lines
- Each line: 5-9 words, clear and readable
- Lines must connect and build on each other — cause, contrast, or consequence
- Do NOT mix topics from different paragraphs into one slide
- Keep factual accuracy — do not invent, exaggerate, or drop key facts
- Avoid starting multiple lines with the same word

Rules across slides:
- The story must read cohesively from slide 1 through to slide {slides_count}
- A reader following slide by slide must understand the full picture

Output JSON only:
{{
  "title": "short punchy carousel title (max 6 words)",
  "slides": [
    {{
      "slideNumber": 1,
      "lines": ["line one", "line two", "line three", "line four"]
    }}
  ]
}}

Exactly {slides_count} slides. Exactly 4 lines each. Return JSON only.

Narrative paragraphs:
{narrative}
""".strip()

    client = Anthropic(api_key=api_key)
    res = client.messages.create(
        model=model, max_tokens=3000, temperature=0.2,
        messages=[{"role": "user", "content": prompt}],
    )
    data = parse_json_from_model_text(res.content[0].text)

    slides = data.get("slides", [])
    if len(slides) != slides_count:
        raise RuntimeError(f"Expected {slides_count} slides, got {len(slides)}")
    for i, s in enumerate(slides, 1):
        if not isinstance(s.get("lines"), list) or len(s["lines"]) != 4:
            raise RuntimeError(f"Slide {i} must have exactly 4 lines, got {s.get('lines')}")

    return data, _usage_info(model, res, "slides")


# ------------------------------------------------------------------ #
# Caption + video download
# ------------------------------------------------------------------ #

def download_captions(url: str, out_dir: Path) -> Path:
    base = out_dir / "captions_raw"
    run_cmd(["yt-dlp", "--skip-download", "--write-subs", "--sub-langs", "en.*",
             "--sub-format", "vtt", "-o", str(base), url], check=False)
    found = list(out_dir.glob("captions_raw*.vtt"))
    if found:
        return found[0]
    run_cmd(["yt-dlp", "--skip-download", "--write-auto-subs", "--sub-langs", "en.*",
             "--sub-format", "vtt", "-o", str(base), url], check=False)
    found = list(out_dir.glob("captions_raw*.vtt"))
    if not found:
        raise RuntimeError("No subtitle track found")
    return found[0]


def download_video(url: str, out_dir: Path) -> Path:
    out_path = out_dir / "video.mp4"
    run_cmd(["yt-dlp", "-f", "mp4/best", "-o", str(out_path), url])
    if not out_path.exists():
        raise RuntimeError("Video download failed")
    return out_path


# ------------------------------------------------------------------ #
# Frame selection
# ------------------------------------------------------------------ #

_FRAME_STOP = frozenset({
    "a", "an", "the", "in", "on", "at", "to", "for", "of", "and", "or",
    "but", "is", "was", "are", "were", "be", "been", "this", "that", "it",
    "its", "as", "by", "with", "from", "not", "have", "has", "had", "so",
    "we", "they", "he", "she", "you", "i", "our", "their",
})


def pick_frame_time_from_cues(
    cues: list[Cue],
    start: float,
    end: float,
    slide_lines: list[str] | None = None,
) -> float:
    """Find the transcript cue most relevant to the slide text within [start, end]."""
    window_cues = [c for c in cues if c.end >= start and c.start <= end]
    if not window_cues:
        return start + max(0.0, (end - start) / 2.0)

    slide_keywords: set[str] = set()
    if slide_lines:
        for line in slide_lines:
            for word in re.findall(r"[a-z]+", line.lower()):
                if len(word) > 3 and word not in _FRAME_STOP:
                    slide_keywords.add(word)

    midpoint = start + max(0.0, (end - start) / 2.0)

    def cue_score(c: Cue) -> tuple[float, float, float]:
        cue_words = set(re.findall(r"[a-z]+", c.text.lower()))
        keyword_overlap = len(cue_words & slide_keywords) / max(len(slide_keywords), 1)
        text_weight = min(len(c.text), 120) / 120.0
        punct_bonus = 0.2 if any(ch in c.text for ch in ".?!:;") else 0.0
        distance_penalty = abs(((c.start + c.end) / 2.0) - midpoint)
        return (keyword_overlap, text_weight + punct_bonus, -distance_penalty)

    chosen = max(window_cues, key=cue_score)
    return chosen.start + max(0.05, (chosen.end - chosen.start) / 2.0)


def extract_frame_ffmpeg(video_path: Path, timestamp: float, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{timestamp:.3f}", "-i", str(video_path),
         "-vframes", "1", "-q:v", "2", str(out_path)],
        check=True, capture_output=True,
    )


# ------------------------------------------------------------------ #
# Slide rendering
# ------------------------------------------------------------------ #

def render_slide_with_playwright(
    lines: list[str],
    frame_path: Path,
    out_path: Path,
    index: int,
    total: int,
    carousel_title: str,
    browser: Any,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]

    photo_url = _inline_asset(frame_path)
    logo_url  = _inline_asset(repo_root / "assets/logo/factjot_mark.png")
    serif_url = _inline_asset(repo_root / "assets/fonts/InstrumentSerif-Regular.ttf")
    mono_url  = _inline_asset(repo_root / "assets/fonts/JetBrainsMono-Bold.ttf")

    index_label = f"{index}/{total}"

    logo_tag = (
        f'<img class="wordmark-img" src="{logo_url}" alt="factjot" />'
        if logo_url else
        '<span class="wordmark-text">fact<span class="ital">jot</span><span class="dot">.</span></span>'
    )
    lines_html = "\n".join(
        f'<div class="line">{escape_html(line)}</div>' for line in lines
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
      font-family: "Instrument Serif";
      src: url("{serif_url}") format("truetype");
      font-weight: 400; font-style: italic;
    }}
    @font-face {{
      font-family: "JetBrains Mono";
      src: url("{mono_url}") format("truetype");
      font-weight: 700; font-style: normal;
    }}

    :root {{
      --near-black: #0A0A0A;
      --off-white:  #EDE8DD;
      --muted:      #9A938A;
      --accent:     #E6352A;
      --white:      #FFFFFF;
    }}

    * {{ box-sizing: border-box; margin: 0; padding: 0; }}

    html, body {{
      width: 1080px; height: 1350px;
      overflow: hidden;
      background: var(--near-black);
      -webkit-font-smoothing: antialiased;
    }}

    .stage {{
      position: relative;
      width: 1080px; height: 1350px;
      overflow: hidden;
      display: flex;
      flex-direction: column;
    }}

    /* ---- TOP ZONE: solid dark bg + text ---- */
    .text-zone {{
      flex: 0 0 auto;
      padding: 64px 70px 0 70px;
      display: flex;
      flex-direction: column;
      gap: 0;
    }}

    .counter {{
      align-self: flex-end;
      background: rgba(255,255,255,0.12);
      color: var(--white);
      font-family: "JetBrains Mono", monospace;
      font-weight: 700;
      font-size: 28px;
      letter-spacing: 0.04em;
      padding: 10px 22px 12px;
      border-radius: 999px;
      line-height: 1;
      margin-bottom: 36px;
    }}

    .lines {{
      display: flex;
      flex-direction: column;
      gap: 0;
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

    /* ---- BOTTOM ZONE: photo box ---- */
    .photo-zone {{
      flex: 1 1 0;
      margin: 32px 50px 50px 50px;
      overflow: hidden;
      border-radius: 6px;
      background: #111;
    }}

    .photo-zone img {{
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }}

    /* factjot wordmark, bottom-right corner */
    .corner-mark {{
      position: absolute;
      right: 62px;
      bottom: 62px;
      z-index: 20;
      font-family: "Instrument Serif", Georgia, serif;
      font-size: 28px;
      line-height: 1;
      letter-spacing: -0.01em;
      color: var(--off-white);
      opacity: 0.65;
      pointer-events: none;
    }}
    .corner-mark .ital {{ font-style: italic; }}
    .corner-mark .dot  {{ color: var(--accent); }}

    /* small wordmark top-left */
    .top-logo {{
      position: absolute;
      left: 70px;
      top: 66px;
      z-index: 20;
      opacity: 0.55;
    }}
    .wordmark-img  {{ height: 28px; width: auto; display: block; }}
    .wordmark-text {{
      font-family: "Instrument Serif", serif;
      font-size: 26px; line-height: 1;
      color: var(--off-white);
    }}
    .wordmark-text .ital {{ font-style: italic; }}
    .wordmark-text .dot  {{ color: var(--accent); }}
  </style>
</head>
<body>
  <div class="stage">

    <div class="top-logo">{logo_tag}</div>

    <div class="text-zone">
      <div class="counter">{index_label}</div>
      <div class="lines">
{lines_html}
      </div>
    </div>

    <div class="photo-zone">
      <img src="{photo_url}" alt="" />
    </div>

    <div class="corner-mark">fact<span class="ital">jot</span><span class="dot">.</span></div>

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
    parser = argparse.ArgumentParser(description="YouTube -> branded Instagram carousel")
    parser.add_argument("--url", required=True)
    parser.add_argument("--slides", type=int, default=8, choices=[8, 9, 10])
    parser.add_argument("--project-name", default="yt-carousel-test")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--force", action="store_true", help="Re-run Claude even if cached")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    load_dotenv(repo_root / ".env")
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing ANTHROPIC_API_KEY in environment or .env")
    if shutil.which("yt-dlp") is None:
        raise RuntimeError("yt-dlp not found on PATH")

    out_dir = repo_root / "tests" / "output" / args.project_name
    frames_dir = out_dir / "frames"
    slides_dir = out_dir / "slides"
    for d in [out_dir, frames_dir, slides_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # ---- Step 1: captions ----
    final_vtt = out_dir / "captions_raw.vtt"
    if final_vtt.exists():
        print("\n[1/6] Captions cached -- skipping download.")
    else:
        print("\n[1/6] Downloading captions...")
        vtt_path = download_captions(args.url, out_dir)
        shutil.copy(vtt_path, final_vtt)

    # ---- Step 2: parse transcript ----
    print("[2/6] Parsing transcript...")
    cues = parse_vtt(final_vtt)
    (out_dir / "transcript.json").write_text(
        json.dumps(
            [{"start": sec_to_hhmmss(c.start), "end": sec_to_hhmmss(c.end), "text": c.text} for c in cues],
            indent=2,
        ),
        encoding="utf-8",
    )

    # ---- Step 3: two-stage Claude compression ----
    slides_json_path = out_dir / "slides.json"
    narrative_path   = out_dir / "narrative.txt"
    usage_path       = out_dir / "api_usage.json"
    all_usage: list[dict] = []

    if slides_json_path.exists() and narrative_path.exists() and not args.force:
        print("[3/6] Slide copy cached -- skipping Claude calls.")
        slides_payload = json.loads(slides_json_path.read_text())
        if usage_path.exists():
            all_usage = json.loads(usage_path.read_text())
    else:
        print(f"[3a/6] Stage 1 -- structuring transcript into {args.slides} paragraphs...")
        narrative, u1 = request_narrative_from_claude(cues, args.slides, args.model, api_key)
        narrative_path.write_text(narrative, encoding="utf-8")
        print(f"       {u1['input_tokens']:,} in / {u1['output_tokens']:,} out  ~${u1['cost_usd']:.4f}")
        all_usage.append(u1)

        print(f"[3b/6] Stage 2 -- dividing narrative into {args.slides} slides...")
        slides_payload, u2 = request_slides_from_claude(narrative, args.slides, args.model, api_key)
        slides_json_path.write_text(json.dumps(slides_payload, indent=2), encoding="utf-8")
        print(f"       {u2['input_tokens']:,} in / {u2['output_tokens']:,} out  ~${u2['cost_usd']:.4f}")
        all_usage.append(u2)

        usage_path.write_text(json.dumps(all_usage, indent=2), encoding="utf-8")

    # ---- Step 4: video ----
    video_path = out_dir / "video.mp4"
    if video_path.exists():
        print("[4/6] Video cached -- skipping download.")
    else:
        print("[4/6] Downloading source video...")
        video_path = download_video(args.url, out_dir)

    # ---- Step 5: extract frames (equal-time segments) ----
    print("[5/6] Extracting frames with FFmpeg...")
    duration = get_video_duration(video_path)
    slides = slides_payload["slides"]
    segment = duration / len(slides)

    for idx, slide in enumerate(slides, start=1):
        frame_path = frames_dir / f"slide_{idx:02d}.jpg"
        if frame_path.exists():
            print(f"  slide {idx}: cached")
            continue
        seg_start = (idx - 1) * segment
        seg_end = idx * segment
        frame_ts = pick_frame_time_from_cues(cues, seg_start, seg_end, slide["lines"])
        print(f"  slide {idx}: t={frame_ts:.1f}s")
        extract_frame_ffmpeg(video_path, frame_ts, frame_path)

    # ---- Step 6: render branded slides ----
    carousel_title = slides_payload.get("title", "")
    print("[6/6] Rendering branded carousel slides...")

    # Always re-render slides (visual changes should not require --force)
    for f in slides_dir.glob("slide_*.png"):
        f.unlink()

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for idx, slide in enumerate(slides, start=1):
            out_path = slides_dir / f"slide_{idx:02d}.png"
            frame_path = frames_dir / f"slide_{idx:02d}.jpg"
            print(f"  rendering slide {idx}...")
            render_slide_with_playwright(
                slide["lines"], frame_path, out_path,
                idx, len(slides), carousel_title, browser,
            )
        browser.close()

    # ---- Summary ----
    print(f"\nDone.  Output: {out_dir}")
    if all_usage:
        total_in  = sum(u["input_tokens"] for u in all_usage)
        total_out = sum(u["output_tokens"] for u in all_usage)
        total_cost = sum(u["cost_usd"] for u in all_usage)
        print(f"API cost: {total_in:,} in / {total_out:,} out  ->  ~${total_cost:.4f} USD  ({args.model})")


if __name__ == "__main__":
    main()
