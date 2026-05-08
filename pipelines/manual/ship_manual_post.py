"""Post a branded carousel from a plain-English brief.

Claude Sonnet writes the content. ImageFetcher sources photos across
Pexels, Pixabay, Openverse, Wikipedia and Wikimedia Commons in order,
so specific subjects (Concorde, Ask Jeeves, etc.) get real photographs
rather than generic stock. Renders in the standard news carousel template
and posts carousel + story.

Usage:
    python pipelines/manual/ship_manual_post.py --brief "Tribute to Ask Jeeves shutting down" --dry-run
    python pipelines/manual/ship_manual_post.py --brief "The history of Concorde, how it was built and why it ended"
    python pipelines/manual/ship_manual_post.py --brief "..." --label "AVIATION" --slides 5
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

import os
from anthropic import Anthropic
from playwright.sync_api import sync_playwright

from pipelines.news.ship_news_post import (
    render_cover_slide,
    render_news_slide,
    render_story_frame,
    _log,
)
from src.content.hashtag_builder import build_hashtags
from src.publish.image_host import make_image_host
from src.publish.instagram_publisher import InstagramGraphPublisher
from src.brain import brain, DuplicatePostError, claim_hash
from src.research.image_sourcer import CoverImageFailed, ImageIntent, ImageSourcer
from src.content.carousel_diagnostics import (
    CarouselShapeError,
    build_shape_diagnostics,
)
# Option C of the content quality recovery (2026-05-08): the writer/fitter
# split was reverted in favour of a single editorial-aware Sonnet call. The
# carousel_writer module stays on disk for future reuse (Option D work) but
# generate_content below no longer calls write_editorial_slides or
# fit_slide_lines. We keep LineFitError because the visual probe still
# raises it on wrap, and _parse_json_payload because its tolerance for
# trailing commentary / bare-comma JSON is equally useful on Sonnet output.
from src.content.carousel_writer import LineFitError, _parse_json_payload
from src.content.carousel_rules import (
    BEAT_DENSITY_RULES,
    COVER_TITLE_RULES,
    PHOTOGRAPHABLE_BEATS_RULES,
)

# ------------------------------------------------------------------ #
# Brand constants (sourced from brand/brand_kit.json)
# ------------------------------------------------------------------ #

BRAND_VOICE_EDITORIAL = f"""\
Brand: factjot (@factjot)
Voice: curious, precise, dry. A smart friend explaining something remarkable.
Tone: confident, never sensational. Present tense where possible.
Reading level: general audience.

Editorial rules:
{BEAT_DENSITY_RULES}
- No em dashes. Commas, full stops, or parentheses instead.
- British English. No hedging. No attribution phrases ("sources say",
  "according to").
- Preserve specific names, dates, numbers, places.
- If a beat is genuinely too dense for one slide, surface the dropped
  sub-fact in dropped_facts rather than welding fragments.

Red keyword markup:
- Wrap 1-2 key words or short phrases per line in [r]...[/r] for the
  accent colour.
- Use for the most striking facts, names, numbers, turning points.

{COVER_TITLE_RULES}
Category label: 1-3 words in capitals. Any subject is valid: SPORT,
POLITICS, CRIME, CULTURE, FOOD, DESIGN, MUSIC, INTERNET HISTORY,
AVIATION, SCIENCE, or anything else that fits.

{PHOTOGRAPHABLE_BEATS_RULES}
Final slide (CTA): a thought-provoking question or reflection the
reader wants to debate. Do NOT reference the source or say "follow
for more"."""

# Backwards-compat: some legacy imports still reach for BRAND_VOICE.
BRAND_VOICE = BRAND_VOICE_EDITORIAL


TYPE_GUIDANCE: dict[str, str] = {
    # Layout / render-shape only. The agent's MODE_PROMPTS carry editorial
    # angle, voice, and beat structure. The pipeline must NOT re-steer the
    # editorial direction or duplicate the agent prompt -- if it does, the
    # writer ends up with two slightly different sets of instructions and
    # drifts. Keep this dict to render-shape facts only.
    "fact": (
        "POST TYPE: FACT CAROUSEL.\n"
        "Render shape: cover + content slides matching the brief's beats.\n"
    ),
    "news": (
        "POST TYPE: NEWS / CURRENT CAROUSEL.\n"
        "Render shape: cover + content slides matching the brief's beats.\n"
    ),
    "list": (
        "POST TYPE: LIST CAROUSEL.\n"
        "Render shape: cover + one slide per list item + closing.\n"
        "Each item slide carries exactly ONE specific list item from the brief.\n"
    ),
}


def _type_guidance(format_type: str) -> str:
    return TYPE_GUIDANCE.get(format_type, TYPE_GUIDANCE["fact"])




# ------------------------------------------------------------------ #
# Content generation via Claude Sonnet
# ------------------------------------------------------------------ #

_WEAK_ENDINGS = frozenset({"a", "the", "and", "or", "of", "in", "to", "with", "an", "at", "by", "for"})

# Hard cap for a single content-slide line at the rendered template size.
# Calibrated to Archivo Black 900 at 42px on the 1080-wide content slide:
# above 24 chars the renderer soft-wraps and the layout breaks (orphan
# words, 4-visual-line slides). Writer prompt asks for 16-22; cap is 24.
HARD_LINE_CAP = 24


def _strip_markup(text: str) -> str:
    return re.sub(r"\[/?r\]", "", text)


def _validate_lines(slides: list[dict]) -> list[str]:
    """Return warning strings for lines that violate soft character rules.

    Hard-cap violations are surfaced here AND raised by
    _assert_lines_within_render_cap. Soft warnings cover orphans and
    weak endings; they do not block publish.
    """
    warnings: list[str] = []
    for i, slide in enumerate(slides, 1):
        lines = slide.get("lines", [])
        for j, raw_line in enumerate(lines):
            line  = _strip_markup(raw_line).strip()
            words = line.split()
            if len(line) > HARD_LINE_CAP:
                warnings.append(f"slide {i} line {j+1}: {len(line)} chars (max {HARD_LINE_CAP}): {line!r}")
            if len(line) < 8 and j == len(lines) - 1:
                warnings.append(f"slide {i} final line too short ({len(line)} chars): {line!r}")
            # Anti-orphan: a line must have >= 3 words, OR be a single
            # named entity worth standing alone (heuristic: starts with a
            # capital in the original markup-stripped form, or a digit).
            if len(words) <= 2:
                stripped = line.rstrip(".,;:!?")
                first = stripped[:1] if stripped else ""
                looks_like_entity = first.isupper() or first.isdigit()
                if not looks_like_entity:
                    warnings.append(f"slide {i} line {j+1}: orphan ({len(words)} words): {line!r}")
            last_word = line.rstrip(".,;:!?").split()[-1].lower() if words else ""
            if last_word in _WEAK_ENDINGS:
                warnings.append(f"slide {i} line {j+1}: ends with weak word '{last_word}'")
    return warnings


def _assert_lines_within_render_cap(slides: list[dict]) -> None:
    """Hard-fail if any slide line exceeds HARD_LINE_CAP.

    Lines over the cap visually wrap in the renderer and the carousel
    ships looking like garbage (e.g. 'leonard coatsworth crawled off on
    his hands and knees' breaking across four visual lines). Better to
    abort the run and skip the slot than ship a broken layout.
    """
    bad: list[str] = []
    for i, slide in enumerate(slides, 1):
        for j, raw_line in enumerate(slide.get("lines", [])):
            line = _strip_markup(raw_line).strip()
            if len(line) > HARD_LINE_CAP:
                bad.append(f"slide {i} line {j+1}: {len(line)} chars > cap {HARD_LINE_CAP}: {line!r}")
    if bad:
        raise RuntimeError(
            "OVERCAP_SLIDE_LINES (Archivo Black wraps these and the layout breaks):\n"
            + "\n".join(bad)
        )


def _enforce_carousel_shape(data: dict, *, requested_content_slides: int) -> None:
    """Hard-fail if the writer returned the wrong shape.

    Replaces the previous silent slides[:8] and lines[:3] slicing.
    The autonomous agent surfaces the diagnostics payload in its tool
    result so the operator can see what was lost.

    `requested_content_slides` is content-slides only (cover excluded).
    See "Slide-count contract" in the implementation plan. `data["slides"]`
    is also content-only.
    """
    slides = data.get("slides") or []
    diag = build_shape_diagnostics(
        requested_content_slides=requested_content_slides,
        returned_content_slides=len(slides),
        slides=slides,
        dropped_facts=data.get("dropped_facts") or [],
    )
    if len(slides) != requested_content_slides:
        raise CarouselShapeError(
            "writer returned wrong content-slide count", diag,
        )
    if diag["bad_line_count"]:
        raise CarouselShapeError(
            "one or more slides have wrong line count (must be exactly 3)", diag,
        )


CONTENT_PROMPT = """\
{brand_voice_editorial}

---

{type_guidance}

You are writing a factjot carousel post. The brief is:

"{brief}"

LAYOUT - HARD RULES (the renderer measures pixel width with the
Playwright probe; lines that visually wrap are rejected on the spot
and the run hard-fails).

- Cover: a single line of 5-9 words goes in cover_title. No full stop.
- Each content slide has EXACTLY 3 lines.
- Each line: target 12-22 characters. HARD CAP {hard_cap} characters.
  Count characters including spaces, ignoring [r]...[/r] markup tags.
- Lines must read aloud as one phrase. Bullet-style fragments and
  stand-alone short words ("crews", "and", "in") are forbidden.
- The final line of each slide must be at least 8 characters.
- No line ends on a weak connector word: a, the, and, or, of, in, to,
  with, an, at, by, for.
- Lowercase preferred. The renderer text-transforms regardless, but
  writing in lowercase makes the cap accurate.
- No em dashes. Commas, full stops, or parentheses.

COMPRESSION when proper nouns won't fit:
- Long names get shortened or split across lines: "Tacoma Narrows
  Bridge" → "the bridge" or "Galloping Gertie" alone, with the
  full name carried by the cover.
- Years stand alone as fragments: "in 1879," / "1940."
- Drop softening words: just, very, really, simply, the, an, a where
  meaning survives.
- Pull the named entity onto its own line where it doesn't fit
  alongside a verb.

RED KEYWORD MARKUP:
- Wrap 1-2 key words or short phrases per line in [r]...[/r] for the
  accent colour. Pick the most striking word, name, or number.
- Example: "[r]galloping gertie[/r]," (one full line).

BEAT-TO-SLIDE MAPPING:
- The brief may include numbered beats. Slide 1 is cover. Beat 1 →
  cover_title. Beat 2 → slides[0]. Beat 3 → slides[1]. And so on.
- Do not merge beats. Do not skip beats. Do not reorder beats.
- If a beat is too dense to fit one slide cleanly, surface the dropped
  sub-fact in dropped_facts rather than welding fragments.

IMAGE QUERIES (one per slide including cover):
- Photographable proxies. People, devices, scenes, eras. NOT abstract
  concepts (no "ruling", "budget", "classification" - describe the
  people, the room, the era instead).
- 2-5 words per query, subject-first.
- For named entities, lead with the canonical proper name.

Return JSON only. No prose around it.

{{
  "cover_title": "5-9 word title in voice",
  "label": "CATEGORY LABEL",
  "caption_body": "2-3 sentences. Human, warm. No hashtags.",
  "visual_subject": "canonical name and type of the main subject",
  "subject_type": "one category string",
  "fallback_query": "canonical proper name, 1-4 words",
  "source_aliases": ["multi-word alias 1", "single-word alias", ...],
  "context_words": ["word1", "word2", ...],
  "negative_terms": ["compound wrong-meaning 1", ...],
  "preferred_image_types": ["type1", ...],
  "avoid_image_types": ["type1", ...],
  "image_queries": ["query for cover", "query for slide 2", ...],
  "visual_fallback_queries": ["fallback for cover", ...],
  "cover_slot_aliases": ["NamedEntityForCover"],
  "dropped_facts": ["sub-fact you dropped because beat was too dense"],
  "slides": [
    {{"slideNumber": 2, "lines": ["line one", "line two", "line three"], "slot_aliases": ["NamedEntity"]}}
  ]
}}

Return EXACTLY {n_slides} content slides (slideNumber 2 to {n_slides_plus_one}).
The cover text is in cover_title, NOT in slides. dropped_facts is
optional - omit or empty list if you didn't drop anything.
"""


def generate_content(
    brief: str, n_slides: int, api_key: str, format_type: str = "fact",
) -> tuple[dict, list[dict]]:
    """Single-stage editorial writer (Option C of content quality recovery).

    One Sonnet 4.6 call writes the carousel content with all editorial,
    layout, and image constraints in a unified prompt. The Playwright
    probe runs once after the call to verify visual fit; if any line
    visually wraps, the call hard-fails via LineFitError (which the
    autonomous agent surfaces as content_shape_mismatch in its
    FAILURE_KIND tag).

    Replaces the two-stage Sonnet-then-Haiku pipeline that produced
    render-safe prose only after Haiku-side retries the model could not
    consistently satisfy.

    Returns `(data, [single_usage_record])`. `n_slides` is content-only
    (cover is on top in main()).
    """
    from anthropic import Anthropic

    type_guidance = _type_guidance(format_type)

    client = Anthropic(api_key=api_key)
    prompt = CONTENT_PROMPT.format(
        brand_voice_editorial=BRAND_VOICE_EDITORIAL,
        type_guidance=type_guidance,
        brief=brief,
        n_slides=n_slides,
        n_slides_plus_one=n_slides + 1,
        hard_cap=HARD_LINE_CAP,
    )
    res = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        temperature=0.5,
        messages=[{"role": "user", "content": prompt}],
    )

    pricing = {"input": 3.00, "output": 15.00}
    cost = (
        res.usage.input_tokens / 1_000_000 * pricing["input"]
        + res.usage.output_tokens / 1_000_000 * pricing["output"]
    )
    usage = {
        "model": "claude-sonnet-4-6",
        "stage": "single_writer",
        "input_tokens": res.usage.input_tokens,
        "output_tokens": res.usage.output_tokens,
        "cost_usd": round(cost, 5),
    }

    # Tolerant JSON parser (handles fenced blocks, trailing commentary,
    # and bare-comma quirks - all observed Sonnet/Haiku output failures).
    data = _parse_json_payload(res.content[0].text)

    # Hard-fail if the writer returned the wrong shape (slide count or
    # per-slide line count). Attaches the cost so the ledger is honest.
    try:
        _enforce_carousel_shape(data, requested_content_slides=n_slides)
    except CarouselShapeError as shape_err:
        shape_err.usage = {
            "editorial_cost_usd": float(usage["cost_usd"]),
            "fitter_cost_usd":    0.0,
            "fitter_attempts":    1,
            "probe_attempts":     0,
        }
        raise

    slides = data["slides"]

    # Soft warnings (orphans, weak endings, final-line-too-short).
    warnings = _validate_lines(slides)
    for w in warnings:
        _log(f"     [line warn] {w}")
    data["_line_warnings"] = warnings

    # Hard char cap on lines (HARD_LINE_CAP=24). Catches obvious overruns.
    _assert_lines_within_render_cap(slides)

    # Visual probe: run Playwright on the actual rendered template
    # (Archivo Black at 48px, 940px usable width) to catch font-specific
    # wraps that char-counting misses. This is visual truth.
    from playwright.sync_api import sync_playwright as _sync_pw_for_probe
    from src.render.line_fit_probe import measure_lines_overflow

    probe_attempts = 1
    with _sync_pw_for_probe() as pw:
        browser = pw.chromium.launch()
        try:
            wraps_per_slide: list[list[bool]] = []
            for s in slides:
                wraps_per_slide.append(measure_lines_overflow(
                    lines      = s["lines"],
                    slide_kind = "photo",
                    browser    = browser,
                ))
        finally:
            browser.close()

    bad: list[str] = []
    for s, wraps in zip(slides, wraps_per_slide):
        for j, wraps_j in enumerate(wraps, 1):
            if wraps_j:
                bad.append(
                    f"slide {s.get('slideNumber', '?')} line {j} visually wraps: "
                    f"{s['lines'][j-1]!r}"
                )
    if bad:
        raise LineFitError(
            "writer produced render-unsafe lines (probe detected visual wrap):\n"
            + "\n".join(bad),
            usage={
                "editorial_cost_usd": float(usage["cost_usd"]),
                "fitter_cost_usd":    0.0,
                "fitter_attempts":    1,
                "probe_attempts":     probe_attempts,
            },
        )

    if data.get("dropped_facts"):
        _log("     [INFO] Writer reported dropped_facts (beat too dense for one slide):")
        for df in data["dropped_facts"]:
            _log(f"            - {df}")

    data["_fitter_attempts"] = 1
    data["_probe_attempts"] = probe_attempts

    return data, [usage]


# ------------------------------------------------------------------ #
# Quality ledger
# ------------------------------------------------------------------ #

def _write_quality_ledger_entry(
    *,
    ledger_path: Path,
    post_id: str,
    format_type: str,
    cover_title: str,
    slide_count: int,
    line_warnings: list[str],
    dropped_facts: list[str],
    image_coverage: dict,
    result: str,
    editorial_cost_usd: float = 0.0,
    fitter_cost_usd: float = 0.0,
    fitter_attempts: int = 0,
    probe_attempts: int = 0,
    total_runtime_ms: int = 0,
) -> None:
    """Append one structured row per run to data/ledgers/carousel_quality.jsonl.

    `result` is one of: "published", "dry_run", "shape_failed",
    "cover_failed", "publish_failed", "fitter_failed", "skipped".

    Cost/latency fields default to 0 in Phase 0 (writer is single-stage,
    no fitter, no probe) and are populated in Phase 1+2.
    """
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "post_id": post_id,
        "format_type": format_type,
        "cover_title": cover_title,
        "slide_count": slide_count,
        "line_warnings": list(line_warnings),
        "dropped_facts": list(dropped_facts),
        "image_coverage": dict(image_coverage),
        "result": result,
        "editorial_cost_usd": round(editorial_cost_usd, 5),
        "fitter_cost_usd": round(fitter_cost_usd, 5),
        "fitter_attempts": fitter_attempts,
        "probe_attempts": probe_attempts,
        "total_runtime_ms": total_runtime_ms,
    }
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


# ------------------------------------------------------------------ #
# Main
# ------------------------------------------------------------------ #

def main() -> int:
    import logging as _logging
    parser = argparse.ArgumentParser(description="Post a branded carousel from a brief")
    parser.add_argument("--brief",   required=True, help="Plain-English description of what to post")
    parser.add_argument("--label",   default=None,  help="Override category label on cover (e.g. 'AVIATION')")
    parser.add_argument("--slides",  type=int, default=0,
                        help="Number of slides total (cover + content). 0 = default per --type "
                             "(fact/news=6, list=7).")
    parser.add_argument("--type",    default="fact", choices=["fact", "news", "list"],
                        help="Carousel sub-type. Switches writer guidance + default slide count.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Route image sourcer + fetcher DEBUG logs to stdout so pool scoring and
    # POOL_REJECT reasons are visible.
    _h = _logging.StreamHandler()
    _h.setFormatter(_logging.Formatter("%(message)s"))
    for _logger_name in ("src.research.image_sourcer", "src.research.image_fetcher"):
        _lg = _logging.getLogger(_logger_name)
        _lg.setLevel(_logging.DEBUG)
        _lg.addHandler(_h)

    # Slide count: cover + content. The writer prompt expects n_slides
    # CONTENT slides (cover added on top in the render loop). Default
    # depends on the carousel sub-type.
    if args.slides > 0:
        total_slides_arg = max(3, min(8, args.slides))
    else:
        total_slides_arg = 7 if args.type == "list" else 6
    n_slides = total_slides_arg - 1   # CONTENT slides only

    repo_root = Path(__file__).resolve().parents[2]
    api_key   = os.getenv("ANTHROPIC_API_KEY", "").strip()

    if not api_key:
        _log("ERROR: ANTHROPIC_API_KEY not set")
        return 1

    quality_ledger_path = repo_root / "data" / "ledgers" / "carousel_quality.jsonl"

    # ---- 1. Generate content ----
    _log(f"\n[1/4] Generating content from brief...")
    _log(f"     Brief:  \"{args.brief}\"")
    _log(f"     Type:   {args.type}  (target {total_slides_arg} slides total)")
    try:
        data, usage_records = generate_content(
            args.brief, n_slides, api_key, format_type=args.type,
        )
    except CarouselShapeError as shape_err:
        _log(f"\nERROR: CONTENT_SHAPE_MISMATCH - {shape_err}")
        _log(f"       Diagnostics: {json.dumps(shape_err.diagnostics, ensure_ascii=False)}")
        partial = shape_err.usage or {}
        _write_quality_ledger_entry(
            ledger_path=quality_ledger_path,
            post_id="shape-failed",
            format_type=args.type,
            cover_title="(shape failed)",
            slide_count=0,
            line_warnings=[],
            dropped_facts=shape_err.diagnostics.get("dropped_facts") or [],
            image_coverage={"image": 0, "typography": 0, "cover_failed": False},
            result="shape_failed",
            editorial_cost_usd=float(partial.get("editorial_cost_usd", 0.0) or 0.0),
            fitter_cost_usd=float(partial.get("fitter_cost_usd", 0.0) or 0.0),
            fitter_attempts=int(partial.get("fitter_attempts", 0) or 0),
            probe_attempts=int(partial.get("probe_attempts", 0) or 0),
        )
        return 1
    except LineFitError as fit_err:
        _log(f"\nERROR: CONTENT_SHAPE_MISMATCH - fitter failed: {fit_err}")
        partial = getattr(fit_err, "usage", {}) or {}
        # The single-call writer (Option C) attaches usage with the
        # editorial_cost_usd / fitter_cost_usd / fitter_attempts shape.
        # FactPreservationError no longer applies (no two-stage diff to
        # check), so it's not in this except clause.
        if "editorial_cost_usd" in partial:
            ed_cost = float(partial.get("editorial_cost_usd", 0.0) or 0.0)
            fit_cost = float(partial.get("fitter_cost_usd", 0.0) or 0.0)
            fit_n = int(partial.get("fitter_attempts", 0) or 0)
        else:
            # Single-attempt failure (the retry loop didn't even start).
            # Stage A by definition succeeded since fit was called.
            ed_cost = 0.0
            fit_cost = float(partial.get("cost_usd", 0.0) or 0.0)
            fit_n = 1
        _write_quality_ledger_entry(
            ledger_path=quality_ledger_path,
            post_id="fitter-failed",
            format_type=args.type,
            cover_title="(fitter failed)",
            slide_count=0,
            line_warnings=[],
            dropped_facts=[],
            image_coverage={"image": 0, "typography": 0, "cover_failed": False},
            result="fitter_failed",
            editorial_cost_usd=ed_cost,
            fitter_cost_usd=fit_cost,
            fitter_attempts=fit_n,
        )
        return 1

    total_cost = sum(u["cost_usd"]      for u in usage_records)
    in_tokens  = sum(u["input_tokens"]  for u in usage_records)
    out_tokens = sum(u["output_tokens"] for u in usage_records)
    _log(
        f"     {in_tokens:,} in / {out_tokens:,} out  ~${total_cost:.4f}  "
        f"({len(usage_records)} stages)"
    )

    # Per-stage cost split for the ledger.
    editorial_cost = next(
        (u["cost_usd"] for u in usage_records if u.get("stage") == "editorial"),
        0.0,
    )
    fitter_cost = next(
        (u["cost_usd"] for u in usage_records if u.get("stage") == "fitter"),
        0.0,
    )

    cover_title  = data["cover_title"]
    label        = args.label.upper() if args.label else data.get("label", "FACTJOT").upper()
    caption_body = data.get("caption_body", "").strip()
    slides       = data["slides"]
    queries      = data.get("image_queries", [])
    total_slides = len(slides) + 1  # +1 for cover

    intent = ImageIntent.from_dict(data)
    _log(f"     Cover: \"{cover_title}\"  |  Label: {label}")
    _log(f"     Subject:   {intent.subject_type} — \"{intent.visual_subject}\"")
    _log(f"     Aliases:   {intent.source_aliases}")
    _log(f"     Context:   {intent.context_words}")
    _log(f"     Negative:  {intent.negative_terms}")
    _log(f"     Preferred: {intent.preferred_image_types}")
    _log(f"     Avoid:     {intent.avoid_image_types}")
    _log(f"     Fallback:  \"{intent.fallback_query}\"")

    # Build per-slot alias overrides. Cover uses cover_slot_aliases; each content
    # slide uses its own slot_aliases if present. A non-empty list replaces the
    # global source_aliases for that slot. None means fall back to global.
    def _clean_aliases(raw: object) -> list[str]:
        if not isinstance(raw, list):
            return []
        return [a for a in raw if isinstance(a, str) and a.strip()]

    cover_sa = _clean_aliases(data.get("cover_slot_aliases", []))
    slide_sa  = [_clean_aliases(s.get("slot_aliases", [])) for s in slides]
    per_slot_aliases: list[list[str] | None] = (
        [cover_sa if cover_sa else None]
        + [sa if sa else None for sa in slide_sa]
    )
    _log(f"     SlotAliases: {per_slot_aliases}")

    # ---- 2. Fetch images (ImageSourcer: pool + Haiku selection + scoring + reuse limits) ----
    _log(f"\n[2/4] Fetching images (pool mode, max 40 candidates/slot, Haiku selector)...")
    while len(queries) < total_slides:
        queries.append(intent.fallback_query or label.lower())
    while len(per_slot_aliases) < total_slides:
        per_slot_aliases.append(None)
    post_id = re.sub(r"[^a-z0-9]+", "-", cover_title.lower())[:30]
    visual_fallbacks = data.get("visual_fallback_queries", [])
    while len(visual_fallbacks) < total_slides:
        visual_fallbacks.append("")
    sourcer = ImageSourcer(topic="editorial", use_fresh_ledger=args.dry_run)
    images  = sourcer.source_images(
        queries[:total_slides], intent, post_id,
        per_slot_aliases=per_slot_aliases[:total_slides],
        visual_fallback_queries=visual_fallbacks[:total_slides],
    )

    image_coverage = {
        "image": sum(1 for u in images if u),
        "typography": sum(1 for u in images if not u),
        "cover_failed": not bool(images and images[0]),
    }

    if not images or not images[0]:
        _log("\nERROR: COVER_IMAGE_FAILED - no usable image found for the cover slide.")
        _log("       Run failed. Check image sourcer DEBUG logs for pool sizes and rejection reasons.")
        _write_quality_ledger_entry(
            ledger_path=quality_ledger_path,
            post_id=post_id,
            format_type=args.type,
            cover_title=cover_title,
            slide_count=total_slides,
            line_warnings=data.get("_line_warnings", []),
            dropped_facts=data.get("dropped_facts") or [],
            image_coverage={"image": 0, "typography": total_slides, "cover_failed": True},
            result="cover_failed",
            editorial_cost_usd=editorial_cost,
            fitter_cost_usd=fitter_cost,
            fitter_attempts=data.get("_fitter_attempts", 1),
            probe_attempts=data.get("_probe_attempts", 0),
        )
        return 1

    cover_photo  = images[0]
    content_imgs = images[1:] if len(images) > 1 else images

    # ---- 3. Render ----
    _log(f"\n[3/4] Rendering {total_slides} slides...")
    slide_paths: list[Path] = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()

            cover_path = tmp_dir / "slide_01.png"
            render_cover_slide(
                cover_title=cover_title,
                source_label=label,
                photo_data_url=cover_photo,
                out_path=cover_path,
                index=1,
                total=total_slides,
                repo_root=repo_root,
                browser=browser,
            )
            slide_paths.append(cover_path)
            _log("     cover done")

            for idx, slide in enumerate(slides, start=2):
                img_idx  = (idx - 2) % max(len(content_imgs), 1)
                out_path = tmp_dir / f"slide_{idx:02d}.png"
                render_news_slide(
                    lines=slide["lines"],
                    photo_data_url=content_imgs[img_idx] if content_imgs else "",
                    out_path=out_path,
                    index=idx,
                    total=total_slides,
                    source_label=label,
                    repo_root=repo_root,
                    browser=browser,
                )
                slide_paths.append(out_path)
                _log(f"     slide {idx} done")

            # 9:16 story frame wrapping the cover slide. Without this the
            # story falls back to the raw 4:5 cover slide stretched into 9:16.
            story_path = tmp_dir / "story.png"
            render_story_frame(
                cover_path=cover_path,
                out_path=story_path,
                repo_root=repo_root,
                browser=browser,
            )
            _log("     story frame done")

            browser.close()

        # Build caption + hashtags
        hashtags = build_hashtags(
            summary=f"{cover_title} {caption_body}",
            topic=label.lower().split()[0] if label else "",
            post_type="fact",
        )
        caption = f"{caption_body}\n\n{hashtags}" if caption_body else hashtags

        # Save locally regardless of dry-run
        ts       = datetime.now().strftime("%Y-%m-%d_%H-%M")
        slug     = re.sub(r"[^a-z0-9]+", "-", cover_title.lower())[:40]
        save_dir = repo_root / "output" / "manual" / f"{ts}_{slug}"
        save_dir.mkdir(parents=True, exist_ok=True)
        for p in slide_paths:
            shutil.copy(p, save_dir / p.name)
        shutil.copy(story_path, save_dir / story_path.name)
        _log(f"\n     Slides saved to: {save_dir.resolve()}")

        if args.dry_run:
            _log("\n[DRY RUN] Caption preview:")
            _log(caption[:500])
            _log(f"\n     Total slides: {total_slides}  |  Cost: ${total_cost:.4f}")
            _write_quality_ledger_entry(
                ledger_path=quality_ledger_path,
                post_id=post_id,
                format_type=args.type,
                cover_title=cover_title,
                slide_count=total_slides,
                line_warnings=data.get("_line_warnings", []),
                dropped_facts=data.get("dropped_facts") or [],
                image_coverage=image_coverage,
                result="dry_run",
                editorial_cost_usd=editorial_cost,
                fitter_cost_usd=fitter_cost,
                fitter_attempts=data.get("_fitter_attempts", 1),
                probe_attempts=data.get("_probe_attempts", 0),
            )
            return 0

        # ---- 4. Host + publish ----
        _log(f"\n[4/4] Hosting and publishing...")
        image_host = make_image_host()
        image_urls: list[str] = []
        for path in slide_paths:
            hosted = image_host.upload(path)
            image_urls.append(hosted.public_url)
            _log(f"     uploaded: {hosted.public_url[:60]}...")

        brief_hash      = claim_hash(args.brief)[:12]
        editorial_claim = f"manual:{brief_hash}:{post_id}"

        publisher = InstagramGraphPublisher(
            account_id=os.getenv("INSTAGRAM_ACCOUNT_ID", ""),
            access_token=os.getenv("META_ACCESS_TOKEN", ""),
            host=os.getenv("META_GRAPH_HOST", "graph.instagram.com"),
            graph_version=os.getenv("META_GRAPH_VERSION", "v21.0"),
        )

        try:
            brain.assert_no_duplicate([editorial_claim])
        except DuplicatePostError:
            _log(f"\nABORTED: this brief has already been posted (id={post_id}).")
            return 1

        publish_result = publisher.publish_carousel(image_urls, caption)
        ig_media_id    = publish_result.get("id") or publish_result.get("ig_media_id", "")
        if ig_media_id:
            _log(f"\nPosted! Media ID: {ig_media_id}")
            brain.record_publish(
                post_id=post_id,
                ig_media_id=ig_media_id,
                slides=[{
                    "claim":    editorial_claim,
                    "topic":    "editorial",
                    "category": label,
                    "sources":  [],
                }],
            )
            _write_quality_ledger_entry(
                ledger_path=quality_ledger_path,
                post_id=post_id,
                format_type=args.type,
                cover_title=cover_title,
                slide_count=total_slides,
                line_warnings=data.get("_line_warnings", []),
                dropped_facts=data.get("dropped_facts") or [],
                image_coverage=image_coverage,
                result="published",
                editorial_cost_usd=editorial_cost,
                fitter_cost_usd=fitter_cost,
                fitter_attempts=data.get("_fitter_attempts", 1),
                probe_attempts=data.get("_probe_attempts", 0),
            )
        else:
            err = publish_result.get("error", "(no error key in result)")
            _log(f"\nPUBLISH FAILED: {err}")
            _log(f"     full result: {publish_result}")
            _log(f"     {len(image_urls)} image URLs were uploaded to host successfully.")
            _log(f"     IG Graph API rejected the carousel. Common causes: image-fetch")
            _log(f"     timeout from Meta side, container ERROR/EXPIRED status, token issue,")
            _log(f"     or aspect-ratio mismatch on one of the slides.")
            _write_quality_ledger_entry(
                ledger_path=quality_ledger_path,
                post_id=post_id,
                format_type=args.type,
                cover_title=cover_title,
                slide_count=total_slides,
                line_warnings=data.get("_line_warnings", []),
                dropped_facts=data.get("dropped_facts") or [],
                image_coverage=image_coverage,
                result="publish_failed",
                editorial_cost_usd=editorial_cost,
                fitter_cost_usd=fitter_cost,
                fitter_attempts=data.get("_fitter_attempts", 1),
                probe_attempts=data.get("_probe_attempts", 0),
            )
            return 1

        # Story: 9:16 story frame + link back to carousel
        story_result = {"ok": False, "error": "no media id"}
        if ig_media_id and image_urls:
            try:
                story_hosted = image_host.upload(story_path)
                story_url    = story_hosted.public_url
                permalink    = publisher.ig_permalink(ig_media_id)
                story_result = publisher.post_to_stories(
                    image_url=story_url,
                    link_url=permalink,
                )
            except Exception as exc:
                story_result = {"ok": False, "error": f"story upload failed: {exc}"}
        if story_result.get("ok"):
            _log(f"Story posted — ig_media_id: {story_result['ig_media_id']}")
        else:
            _log(f"Story skipped (non-fatal): {story_result.get('error')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
