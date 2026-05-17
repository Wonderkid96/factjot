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
from playwright.sync_api import sync_playwright

# Renderer primitives live in src/render/carousel_slides.py (Phase K.4).
# Pre-Phase-K.4 these were imported from pipelines/news/ship_news_post.py
# as a documented dual-role module. The news CLI is now gone and the
# renderers are owned by src/render/ like every other shared render path.
from src.render.carousel_slides import (
    render_cover_slide,
    render_news_slide,
    render_story_frame,
    _log,
)
from src.content.hashtag_builder import build_hashtags
from src.content.voice_normaliser import normalise as normalise_caption
from src.publish.image_host import make_image_host
from src.publish.instagram_publisher import InstagramGraphPublisher
from src.brain import brain, DuplicatePostError, claim_hash
from src.research.image_sourcer import ImageIntent, ImageSourcer
from src.content.carousel_diagnostics import (
    CarouselShapeError,
    build_shape_diagnostics,
)
# D.1 fact verification gate (audit decision A: medium). Both checks fail
# OPEN on infrastructure issues (missing api_key, Wikipedia unreachable)
# and fail CLOSED on real quality issues (title contradicts claim, brief
# contains "fictional"/"absurdity", Wikipedia explicitly disagrees).
from src.verification.fact_checker import verify_anchors, verify_consistency
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
    LAYOUT_PROFILES,
    get_profile,
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
- British English. No hedging. No anonymous attribution phrases
  ("experts claim", "reports suggest", "scientists believe",
  "sources say", "according to unspecified sources"). Named primary
  sources are allowed and preferred (e.g. "The 1972 EPA report found...",
  "Surgeon General Steinfeld testified...", "The Warren Commission
  concluded..."). Naming the source increases credibility.
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
        "POST TYPE: RANKED / SUPERLATIVE LIST CAROUSEL.\n"
        "Render shape: cover + one slide per list item + closing.\n"
        "Each item slide carries exactly ONE named entry from the brief.\n"
        "The slide must read as a ranked entry, not a paragraph:\n"
        "  line 1 = the named entry (treated as the item title; the\n"
        "           writer should wrap the name in [r]...[/r]).\n"
        "  line 2 = the rank reason from the brief (one hard number\n"
        "           or fact that earns the spot).\n"
        "  line 3 = the concrete fact from the brief.\n"
        "Do not narrate setup -> mechanism -> consequence. Do not\n"
        "merge two items into one slide. The closing slide is a\n"
        "one-line takeaway, not a moral argument.\n"
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


def _build_per_slot_aliases(
    *,
    cover_slot_aliases: object,
    cover_title: str,
    slides: list[dict],
) -> tuple[list[list[str] | None], list[str]]:
    """Construct per-slot alias overrides for ImageSourcer.source_images().

    Returns a `(per_slot_aliases, per_slot_text)` pair indexed by slot
    (slot 0 = cover, then one entry per content slide).

    Each entry in `per_slot_aliases` is one of:
      - a non-empty list of strings (slot-specific aliases override globals);
      - `None` (slot falls back to the global `source_aliases`).

    The `None` fallback is the documented production failure mode tracked
    in `insta-brain/gotchas.md`: an empty `cover_slot_aliases` causes the
    cover slot to inherit globals, which for scene-style cover queries can
    gate out every candidate with `POOL_REJECT no_alias_match` even when
    content slots succeed. Extracting this construction out of `main()` is
    what makes that failure mode unit-testable; do not re-inline.

    Inputs are accepted as `object` (not `list[str]`) so a missing or
    malformed `cover_slot_aliases` field in the upstream JSON is handled
    here rather than crashing the caller.
    """
    def _clean_aliases(raw: object) -> list[str]:
        if not isinstance(raw, list):
            return []
        return [a for a in raw if isinstance(a, str) and a.strip()]

    cover_sa = _clean_aliases(cover_slot_aliases)
    slide_sa = [_clean_aliases(s.get("slot_aliases", [])) for s in slides]
    per_slot_aliases: list[list[str] | None] = (
        [cover_sa if cover_sa else None]
        + [sa if sa else None for sa in slide_sa]
    )
    per_slot_text: list[str] = (
        [cover_title]
        + [" ".join(s.get("lines", [])) for s in slides]
    )
    return per_slot_aliases, per_slot_text


def _validate_lines(slides: list[dict], hard_cap: int = HARD_LINE_CAP) -> list[str]:
    """Return warning strings for lines that violate soft character rules.

    Hard-cap violations are surfaced here AND raised by
    _assert_lines_within_render_cap. Soft warnings cover orphans and
    weak endings; they do not block publish.

    `hard_cap` defaults to compact_legacy's 24; readable_list callers
    pass the profile cap (56) so the line_warnings ledger does not spam
    false-positive overcap entries.
    """
    warnings: list[str] = []
    for i, slide in enumerate(slides, 1):
        lines = slide.get("lines", [])
        for j, raw_line in enumerate(lines):
            line  = _strip_markup(raw_line).strip()
            words = line.split()
            if len(line) > hard_cap:
                warnings.append(f"slide {i} line {j+1}: {len(line)} chars (max {hard_cap}): {line!r}")
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


def _assert_lines_within_render_cap(slides: list[dict], hard_cap: int = HARD_LINE_CAP) -> None:
    """Hard-fail if any slide line exceeds `hard_cap`.

    Lines over the cap visually wrap in the renderer and the carousel
    ships looking like garbage (e.g. 'leonard coatsworth crawled off on
    his hands and knees' breaking across four visual lines). Better to
    abort the run and skip the slot than ship a broken layout.

    The cap defaults to the compact_legacy value (24); readable_list
    callers pass the profile's wider cap (56). Autosize on readable_list
    handles within-cap overflow at render time.
    """
    # Permit a small textual overflow buffer and let the visual probe be the
    # final authority for compact_legacy fit. This avoids false hard-fails on
    # lines that are 1-2 chars over cap but still render on one visual line.
    overflow_buffer = 2
    bad: list[str] = []
    for i, slide in enumerate(slides, 1):
        for j, raw_line in enumerate(slide.get("lines", [])):
            line = _strip_markup(raw_line).strip()
            if len(line) > (hard_cap + overflow_buffer):
                bad.append(
                    f"slide {i} line {j+1}: {len(line)} chars > cap {hard_cap}+{overflow_buffer}: {line!r}"
                )
    if bad:
        raise RuntimeError(
            "OVERCAP_SLIDE_LINES (writer exceeded the layout's hard cap):\n"
            + "\n".join(bad)
        )


LIST_ITEM_REQUIRED_FIELDS = ("rank", "name", "rank_reason", "concrete_fact", "image_query")


def _items_to_render_slides(items: list[dict], closing: dict) -> list[dict]:
    """Convert structured list items into the renderer's flat-line shape.

    Each item becomes one content slide with deterministic 3-line output:
        line 1 = "[r]{name}[/r]"   (the renderer treats [r] as accent colour)
        line 2 = rank_reason
        line 3 = concrete_fact

    The closing slide stays freeform 3-line. The original structured item
    is preserved on the slide dict as `slide["item"]` so dry-run output
    and a future renderer redesign can read the typed fields directly.
    """
    rendered: list[dict] = []
    for item in items:
        rendered.append({
            "slideNumber": int(item["rank"]) + 1,
            "lines": [
                f"[r]{item['name']}[/r]",
                item["rank_reason"],
                item["concrete_fact"],
            ],
            "slot_aliases": [item["name"]],
            "item": dict(item),
        })
    rendered.append({
        "slideNumber": len(items) + 2,
        "lines": list(closing["lines"]),
        "slot_aliases": [],
    })
    return rendered


def _enforce_list_shape(data: dict, *, requested_items: int, hard_cap: int) -> None:
    """Hard-fail if list-mode writer output is malformed.

    Validates the structured list schema BEFORE the adapter runs, so a
    bad item never reaches the renderer. Each item must have all five
    required fields, ranks must be 1..N in order, and the three
    rendered fields (name, rank_reason, concrete_fact) must each fit
    `hard_cap` chars individually. The closing block and cover image
    query are also validated.
    """
    bad: list[str] = []

    items = data.get("items")
    if not isinstance(items, list):
        bad.append("items: missing or not a list")
        items = []
    elif len(items) != requested_items:
        bad.append(
            f"items: expected exactly {requested_items}, got {len(items)}"
        )

    for idx, item in enumerate(items, 1):
        if not isinstance(item, dict):
            bad.append(f"item {idx}: not an object")
            continue
        missing = [f for f in LIST_ITEM_REQUIRED_FIELDS if f not in item]
        if missing:
            bad.append(f"item {idx}: missing fields {missing}")
            continue
        rank = item["rank"]
        if not isinstance(rank, int) or isinstance(rank, bool):
            bad.append(f"item {idx}: rank is not an integer (got {rank!r})")
        elif rank != idx:
            bad.append(f"item {idx}: rank={rank} but expected {idx}")
        for field in ("name", "rank_reason", "concrete_fact", "image_query"):
            value = item.get(field)
            if not isinstance(value, str) or not value.strip():
                bad.append(f"item {idx}: {field} is empty or not a string")
                continue
            if field != "image_query" and len(_strip_markup(value)) > hard_cap:
                bad.append(
                    f"item {idx}: {field} is "
                    f"{len(_strip_markup(value))} chars > cap {hard_cap}: {value!r}"
                )

    closing = data.get("closing")
    if not isinstance(closing, dict):
        bad.append("closing: missing or not an object")
    else:
        cl_lines = closing.get("lines")
        if not isinstance(cl_lines, list) or len(cl_lines) != 3:
            bad.append(
                f"closing.lines: expected exactly 3 strings, got {cl_lines!r}"
            )
        else:
            for i, line in enumerate(cl_lines, 1):
                if not isinstance(line, str) or not line.strip():
                    bad.append(f"closing.lines[{i}]: empty or not a string")
                elif len(_strip_markup(line)) > hard_cap:
                    bad.append(
                        f"closing.lines[{i}]: "
                        f"{len(_strip_markup(line))} chars > cap {hard_cap}"
                    )
        cl_iq = closing.get("image_query")
        if not isinstance(cl_iq, str) or not cl_iq.strip():
            bad.append("closing.image_query: empty or not a string")

    cover_iq = data.get("cover_image_query")
    if not isinstance(cover_iq, str) or not cover_iq.strip():
        bad.append("cover_image_query: empty or not a string")

    # visual_fallback_queries: one stock-friendly query per slide,
    # in order [cover, item 1, ..., item N, closing]. The sourcer
    # uses these on R3 fallback when item-name searches return
    # nothing from archive providers.
    expected_n_fallbacks = requested_items + 2
    vfqs = data.get("visual_fallback_queries")
    if not isinstance(vfqs, list):
        bad.append("visual_fallback_queries: missing or not a list")
    elif len(vfqs) != expected_n_fallbacks:
        bad.append(
            f"visual_fallback_queries: expected exactly "
            f"{expected_n_fallbacks} (cover + {requested_items} items "
            f"+ closing), got {len(vfqs)}"
        )
    else:
        for i, q in enumerate(vfqs):
            if not isinstance(q, str) or not q.strip():
                bad.append(
                    f"visual_fallback_queries[{i}]: empty or not a string"
                )

    if bad:
        diag = {
            "requested_content_slides": requested_items + 1,
            "returned_content_slides": (len(items) if isinstance(items, list) else 0) + (1 if isinstance(closing, dict) else 0),
            "overlong_lines": [],
            "bad_line_count": [],
            "list_errors": bad,
            "items": items,
            "closing": closing,
        }
        raise CarouselShapeError(
            "list writer output failed shape validation:\n  "
            + "\n  ".join(bad),
            diag,
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
- Each line: target {target_min}-{target_max} characters. HARD CAP {hard_cap} characters.
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
- Use literal, search-friendly phrasing, not creative metaphors.
- Photographable proxies only: people, devices, rooms, scenes, eras.
  NOT abstract terms (no "ruling", "budget", "classification").
- 4-9 words per query, subject-first, concrete nouns included.
- For named entities, start with the canonical proper name and then add
  2-4 context words (place, object, action, era).

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


LIST_CONTENT_PROMPT = """\
{brand_voice_editorial}

---

POST TYPE: RANKED / SUPERLATIVE LIST CAROUSEL.

You are writing a factjot ranked list. The brief is:

"{brief}"

OUTPUT SHAPE: a STRUCTURED list with EXACTLY {n_items} items. Each item
is a standalone ranked entry. Items must NOT depend on each other.
The pipeline assembles the slide deterministically from your fields,
so you cannot turn an item into prose. Do not write a setup-mechanism-
consequence arc. Do not weld two items together with connective tissue.

ITEM FIELDS (all required):

- rank (integer 1..{n_items}): 1 is the headline entry. For
  "smallest"/"oldest"/"shortest" superlatives, rank 1 is still the
  most extreme entry that earns the slot.
- name (string): the proper-noun subject. Max {hard_cap} chars.
  Do NOT include any [r]...[/r] markup. The pipeline wraps the whole
  name in the accent colour automatically.
- rank_reason (string): one-line reason this entry earns its rank.
  Lead with the hard number or fact (e.g. "$24B in recall costs",
  "killed 1,134 workers", "0.49 km^2 land area"). Max {hard_cap}
  chars. No setup, no narrative, no semicolons, no "this is".
- concrete_fact (string): one extra hard fact (date, place, scale,
  outcome). Max {hard_cap} chars. Must add new information; do not
  restate name or rank_reason.
- image_query (string): 2-5 words. MUST start with the item name
-  verbatim (or its canonical short form). Add 3-6 visual context
  words after. Keep phrasing literal and search-friendly, not
  clever or metaphorical. The image is item-specific, not list-themed. No
  generic "engineering disaster", "factory fire", "warehouse"
  queries; those will be rejected and the slide will fall to
  typography. Examples:
    Chernobyl disaster -> "Chernobyl reactor disaster"
    Deepwater Horizon blowout -> "Deepwater Horizon oil rig fire"
    Space Shuttle Challenger -> "Space Shuttle Challenger explosion"
    Hubble Space Telescope mirror flaw -> "Hubble Space Telescope"
    Mars Climate Orbiter -> "Mars Climate Orbiter NASA"

CLOSING SLIDE (NOT a list item):

- closing.lines: EXACTLY 3 strings. Target 30-50 chars per line, max
  {hard_cap}. The closing slide MUST cite the criterion source
  explicitly. At least one of the three lines must read like
  "Source: USGS confirmed fatalities, 1900-present" or
  "Source: Box Office Mojo, domestic gross" or
  "Source: BFI Sight & Sound 2022 critics' poll". This is the closer's
  primary job: it tells the viewer where the ranking came from.
  The remaining lines may state a structural pattern about the items
  themselves; the closer is structural and source-backed, not moral.
  FORBIDDEN closer shapes:
    - rhetorical questions ("who chose...?", "what if...?")
    - moral imperatives ("we must...", "the world should...")
    - "the lesson is...", "the takeaway is..."
    - second person hectoring ("you have to...")
    - vague universals ("everyone knows...")
    - bare picks with no source ("just our picks", "wow")
- closing.image_query: 2-5 words, photographable proxy.

COVER (Phase D.2 list format rule):

- cover_title: 5-9 words. MUST follow EXACTLY one of these two shapes:
    a) "Five [items] by [criterion]"
       e.g. "Five engineering disasters by death toll"
            "Five films by domestic box office"
    b) "Five [items] that [verifiable condition]"
       e.g. "Five films that grossed under five million dollars"
            "Five companies that have traded since before 1700"
  No full stop. The criterion must be measurable from public records
  (a number, a record, a yes / no fact).
  Allowed superlatives (numeric / defensible only) when paired with a
  criterion: biggest, oldest, fastest, deadliest, longest, tallest,
  largest, richest, youngest, shortest, costliest, smallest, newest,
  slowest, most expensive, most profitable, least expensive,
  least profitable, most catastrophic.
  BANNED superlatives (opinion / aesthetic, never use):
    scariest, most underrated, strangest, most bizarre, best, worst,
    coolest, weirdest, most surprising, funniest, cutest, most iconic,
    most influential, most disturbing, safest, most dangerous,
    least survivable.
  Bare-superlative covers ("Five scariest films", "Five most iconic
  moments") are FORBIDDEN. If you cannot find a defensible criterion
  for the topic, do not ship the list; ask the brief for a different
  topic. The pipeline rejects bare-superlative covers post-write.
- cover_image_query: 2-5 words, photographable proxy.

VISUAL FALLBACK QUERIES (separate from image_query above):

The image_query above leads with the item name and is tried FIRST
against archive providers (Wikimedia Commons, Wikipedia,
Smithsonian). When that returns nothing, the sourcer falls back
to a generic, stock-friendly query for that slide. You must
provide one fallback per slide.

- visual_fallback_queries: ARRAY of EXACTLY {n_fallbacks} strings,
  in order: cover, item 1, item 2, ..., item N, closing.
- 2-4 words per fallback. Stock-photography vocabulary. Subject
  type, setting, era. Do NOT use the entity name; that's already
  the primary query and we need a different shape here.
- Examples (for a "worst product recalls" list):
    cover         -> "product recall warehouse shelves"
    Takata        -> "car airbag close up"
    Samsung Note 7-> "smartphone battery fire"
    Vioxx         -> "pill bottles pharmacy shelf"
    Firestone     -> "damaged car tyre close up"
    Peanut Corp   -> "peanut butter factory food safety"
    closing       -> "product safety inspection warehouse"

LAYOUT - HARD RULES (the pipeline rejects anything outside these):

- name, rank_reason, concrete_fact each must be <= {hard_cap}
  characters individually.
- Lowercase preferred (renderer text-transforms regardless).
- No em dashes. No semicolons inside fields. Commas, full stops,
  parentheses only.
- British English.

WORDING RULES (rendered fields only):

- Use "about" not "approximately". Drop "roughly", "reportedly",
  "generally" unless meaningfully load-bearing.
- Lead with the noun. Active verbs. Past tense for past events.
- No filler ("on that day", "as a result", "in the end",
  "ultimately", "essentially").
- Keep specifics: numbers, dates, places, currencies. Do NOT
  paraphrase a hard fact into a soft one.
- Each rendered field is one short clause, not a paragraph.

Return JSON only. No prose around it.

{{
  "cover_title": "5-9 word title with a superlative",
  "label": "CATEGORY LABEL",
  "caption_body": "2-3 sentences. Human, warm. No hashtags.",
  "visual_subject": "canonical name and type of the main subject",
  "subject_type": "one category string",
  "fallback_query": "1-4 words",
  "source_aliases": ["alias1", "..."],
  "context_words": ["word1", "..."],
  "negative_terms": ["wrong-meaning 1", "..."],
  "preferred_image_types": ["type1", "..."],
  "avoid_image_types": ["type1", "..."],
  "cover_image_query": "subject for cover",
  "items": [
    {{
      "rank": 1,
      "name": "Takata airbag recall",
      "rank_reason": "$24B in recall costs",
      "concrete_fact": "Over 100M vehicles recalled worldwide",
      "image_query": "car airbag deployment"
    }}
  ],
  "closing": {{
    "lines": ["one", "two", "three"],
    "image_query": "thoughtful closing visual"
  }},
  "visual_fallback_queries": [
    "cover fallback (stock-friendly)",
    "item 1 fallback (stock-friendly)",
    "...",
    "closing fallback (stock-friendly)"
  ],
  "dropped_facts": []
}}

Return EXACTLY {n_items} items in items[] AND EXACTLY {n_fallbacks}
strings in visual_fallback_queries[].
"""


LIST_POLISH_PROMPT = """\
Polish the wording in these structured list fields for a factjot
ranked-list carousel. The structure is FROZEN: do not change the
shape, the names, the ranks, or the count of items.

HARD RULES:

- Do NOT change item names. Names are immutable.
- Do NOT change ranks.
- Do NOT add new facts or numbers; only rewrite existing wording.
- Do NOT remove specifics (numbers, dates, places, currencies).
- Use "about" instead of "approximately".
- Drop stiff filler: "on that day", "in the end", "as a result",
  "reportedly", "generally", "ultimately", "essentially".
  Keep "roughly" only when it materially softens a number.
- Active voice. Lead with the noun. Past tense for past events.
- British English. No em dashes.
- Each rendered field stays under {hard_cap} characters
  (markup-stripped).
- Do NOT change image_query values. Pass them through unchanged.
- Do NOT touch visual_fallback_queries; they are not part of this
  polish payload at all.

CLOSING SLIDE (closing.lines):

- Summarise the ranking by stating a pattern about the five items
  themselves. The closer is structural, not moral.
- FORBIDDEN: rhetorical questions, moral imperatives, "the lesson
  is...", "the takeaway is...", second-person hectoring, vague
  universals ("everyone knows...").
- Exactly 3 lines, each <= {hard_cap} chars.

INPUT:
{payload_json}

Return JSON only, no prose around it. The shape:

{{
  "items": [
    {{ "rank": 1, "name": "...", "rank_reason": "polished",
       "concrete_fact": "polished", "image_query": "..." }}
  ],
  "closing": {{ "lines": ["polished line 1", "polished line 2", "polished line 3"],
               "image_query": "..." }}
}}
"""


LIST_SHAPE_REPAIR_PROMPT = """\
Repair this factjot list payload so it passes strict shape validation.

Hard rules:
- Keep the same number of items and same ranks.
- Do NOT change item names.
- Keep facts accurate; do not invent numbers or dates.
- Rewrite only wording where needed so each of these fields is <= {hard_cap} chars:
  - rank_reason
  - concrete_fact
  - closing.lines[1..3]
- Keep all image_query values unchanged.
- British English, no em dashes.

Validation failures you must fix:
{errors}

Input payload:
{payload_json}

Return JSON only with this exact shape:
{{
  "items": [
    {{ "rank": 1, "name": "...", "rank_reason": "...", "concrete_fact": "...", "image_query": "..." }}
  ],
  "closing": {{ "lines": ["...", "...", "..."], "image_query": "..." }}
}}
"""


def _repair_list_shape(data: dict, errors: list[str], api_key: str, hard_cap: int) -> tuple[dict, dict]:
    """Targeted repair pass for list shape failures (mainly over-cap fields)."""
    from anthropic import Anthropic

    payload = {"items": data.get("items", []), "closing": data.get("closing", {})}
    prompt = LIST_SHAPE_REPAIR_PROMPT.format(
        hard_cap=hard_cap,
        errors="\n".join(f"- {e}" for e in errors) if errors else "- shape mismatch",
        payload_json=json.dumps(payload, ensure_ascii=False, indent=2),
    )
    client = Anthropic(api_key=api_key)
    res = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        temperature=0.1,
        messages=[{"role": "user", "content": prompt}],
    )
    pricing = {"input": 3.00, "output": 15.00}
    cost = (
        res.usage.input_tokens / 1_000_000 * pricing["input"]
        + res.usage.output_tokens / 1_000_000 * pricing["output"]
    )
    usage = {
        "model": "claude-sonnet-4-6",
        "stage": "shape_repair",
        "input_tokens": res.usage.input_tokens,
        "output_tokens": res.usage.output_tokens,
        "cost_usd": round(cost, 5),
    }
    repaired = _parse_json_payload(res.content[0].text)
    return repaired, usage


def _ensure_list_visual_fields(data: dict, n_items: int) -> dict:
    """Backfill required visual query fields when the writer omits them."""
    items = data.get("items") if isinstance(data.get("items"), list) else []
    closing = data.get("closing") if isinstance(data.get("closing"), dict) else {}

    if not isinstance(data.get("cover_image_query"), str) or not data.get("cover_image_query", "").strip():
        if items and isinstance(items[0], dict) and isinstance(items[0].get("image_query"), str):
            data["cover_image_query"] = items[0]["image_query"]
        else:
            data["cover_image_query"] = "engineering disaster ruins"

    vfqs = data.get("visual_fallback_queries")
    expected = n_items + 2
    if not isinstance(vfqs, list) or len(vfqs) != expected:
        built: list[str] = []
        built.append("industrial disaster ruins")
        for item in items[:n_items]:
            iq = str(item.get("image_query", "")).strip().lower()
            parts = [p for p in re.split(r"\s+", iq) if p]
            built.append(" ".join(parts[:4]) if parts else "industrial accident site")
        while len(built) < expected - 1:
            built.append("industrial accident site")
        c_iq = str(closing.get("image_query", "")).strip().lower()
        built.append(" ".join(c_iq.split()[:4]) if c_iq else "safety inspection workers")
        data["visual_fallback_queries"] = built[:expected]
    return data


def _polish_list_wording(data: dict, api_key: str) -> tuple[dict, dict]:
    """Second-stage polish pass on rendered list fields only.

    Calls Haiku 4.5 with the structured items + closing and returns
    polished versions. Names, ranks, and image_query are forced back
    from the original payload to guarantee structural immutability,
    even if the model tries to drift.

    Returns (polished_data, usage_record). On parse failure or
    empty/malformed output the original `data` is returned unchanged
    along with the usage record (so cost is still accounted for).
    """
    from anthropic import Anthropic

    profile = get_profile("readable_list")
    payload = {"items": data["items"], "closing": data["closing"]}
    prompt = LIST_POLISH_PROMPT.format(
        hard_cap=profile["hard_cap"],
        payload_json=json.dumps(payload, ensure_ascii=False, indent=2),
    )
    client = Anthropic(api_key=api_key)
    res = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        temperature=0.2,
        messages=[{"role": "user", "content": prompt}],
    )
    pricing = {"input": 1.00, "output": 5.00}
    cost = (
        res.usage.input_tokens / 1_000_000 * pricing["input"]
        + res.usage.output_tokens / 1_000_000 * pricing["output"]
    )
    usage = {
        "model": "claude-haiku-4-5-20251001",
        "stage": "fitter",
        "input_tokens": res.usage.input_tokens,
        "output_tokens": res.usage.output_tokens,
        "cost_usd": round(cost, 5),
    }

    try:
        polished = _parse_json_payload(res.content[0].text)
    except Exception as exc:  # noqa: BLE001 - any parse error returns unchanged
        _log(f"     [polish-pass] JSON parse failed, keeping original wording: {exc}")
        return data, usage

    polished_items = polished.get("items") or []
    polished_closing = polished.get("closing") or {}

    if len(polished_items) == len(data["items"]):
        for orig, new in zip(data["items"], polished_items):
            new["rank"] = orig["rank"]
            new["name"] = orig["name"]
            new["image_query"] = orig.get("image_query") or new.get("image_query", "")
        data["items"] = polished_items

    cl_lines = polished_closing.get("lines")
    if isinstance(cl_lines, list) and len(cl_lines) == 3:
        polished_closing["image_query"] = (
            data["closing"].get("image_query")
            or polished_closing.get("image_query", "")
        )
        data["closing"] = polished_closing

    return data, usage


# ------------------------------------------------------------------ #
# Per-list-item image validation
# ------------------------------------------------------------------ #

_LIST_IMAGE_STOPWORDS = frozenset({
    "the", "a", "an", "of", "and", "or", "in", "to", "with", "at",
    "by", "for", "from", "on", "that", "this", "these", "those",
    "are", "was", "were", "is", "be", "been",
})


def _hash_data_url(data_url: str) -> str:
    """Stable identity for a base64 data URL (used for dedup).

    Two slides that committed the SAME image (same provider, same
    fetched bytes) will hash identically. This is robust even when
    the upstream URL differs, because we hash the cached bytes.
    """
    if not data_url:
        return ""
    import hashlib
    payload = data_url.split(",", 1)[-1]
    return hashlib.sha1(payload.encode("ascii", errors="ignore")).hexdigest()


def _item_aliases_for_image(item: dict) -> list[str]:
    """Aliases the chosen image's metadata must contain to count as
    a match for this list item.

    Combines the item name (whole phrase, plus each significant
    token), and the item's image_query terms. Lowercased, stop-words
    dropped, single-character / two-character tokens dropped.
    """
    out: list[str] = []
    name = (item.get("name") or "").strip().lower()
    if name:
        out.append(name)
        for tok in re.split(r"[^a-z0-9]+", name):
            if len(tok) >= 3 and tok not in _LIST_IMAGE_STOPWORDS:
                out.append(tok)
    iq = (item.get("image_query") or "").strip().lower()
    for tok in re.split(r"[^a-z0-9]+", iq):
        if len(tok) >= 3 and tok not in _LIST_IMAGE_STOPWORDS:
            out.append(tok)
    seen: set[str] = set()
    deduped: list[str] = []
    for t in out:
        if t and t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped


def _image_meta_matches_item(meta: str, item: dict) -> tuple[bool, list[str]]:
    """Return (matched, hits) where hits are the aliases found in meta.

    Matching is case-insensitive substring across the metadata
    string the sourcer logs. A single token hit is enough; the
    pipeline already gates on subject-term presence at score time,
    so this is a final no-wrong-image safety net.
    """
    if not meta:
        return False, []
    meta_lc = meta.lower()
    aliases = _item_aliases_for_image(item)
    hits = [a for a in aliases if a in meta_lc]
    return bool(hits), hits


def _build_list_cover_rescue_queries(
    data: dict,
    intent: ImageIntent,
    primary_cover_query: str,
) -> list[str]:
    """Extra cover queries for list mode when the primary cover line fails.

    Order: first item (often a concrete film or place), intent fallbacks,
    then the writer's visual fallback for slot 0, then the broad subject.
    De-duplicates and skips the query that already failed for slot 0.
    """
    seen: set[str] = set()
    out: list[str] = []

    def add(q: object) -> None:
        if not isinstance(q, str):
            return
        s = q.strip()
        if len(s) < 3:
            return
        key = s.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(s)

    exhausted = (primary_cover_query or "").strip().lower()
    items = data.get("items") or []
    if items and isinstance(items[0], dict):
        add(items[0].get("image_query"))
        add(items[0].get("name"))
    add(intent.fallback_query)
    vfqs = data.get("visual_fallback_queries") or []
    if vfqs:
        add(vfqs[0] if len(vfqs) > 0 else "")
    add(intent.visual_subject)
    if exhausted:
        out = [q for q in out if q.strip().lower() != exhausted]
    return out


def _validate_list_images(
    images: list[str],
    decisions: list[dict],
    items: list[dict],
) -> tuple[list[str], list[dict]]:
    """Caller-side image validation for list mode.

    Two rules, in order:
      1. Item slides only: image metadata must contain the item
         name or a derived alias. If not, the slide goes typography
         (rejecting "visually dramatic but wrong" images, e.g. a
         Chernobyl photo on a Challenger slide).
      2. No duplicate images across the carousel. Slide hashes are
         compared on the committed bytes; first occurrence wins,
         later duplicates go typography.

    Cover (slot 0) and closing (last slot) are exempt from rule 1
    (they have no item) but participate in rule 2.

    Returns (filtered_images, audit_per_slot). The audit is suitable
    for logging and for inclusion in list_data.json.
    """
    audit: list[dict] = []
    filtered: list[str] = list(images)
    n = len(filtered)
    seen_hashes: dict[str, int] = {}

    for slot in range(n):
        url = filtered[slot]
        decision = decisions[slot] if slot < len(decisions) else {}
        slot_audit: dict = {
            "slot": slot,
            "image_query": decision.get("query", ""),
            "image_meta": decision.get("chosen_meta", "")[:140],
            "image_provider": decision.get("chosen_provider", ""),
            "selection_outcome": decision.get("outcome", ""),
            "selection_reason": decision.get("reason", ""),
            "match_status": "n/a",
            "dedupe_status": "n/a",
            "outcome": "kept",
        }

        if not url:
            slot_audit["outcome"] = "typography_input"
            audit.append(slot_audit)
            continue

        is_item_slide = 1 <= slot <= len(items)
        if is_item_slide:
            item = items[slot - 1]
            matched, hits = _image_meta_matches_item(
                decision.get("chosen_meta", ""), item,
            )
            slot_audit["item_name"] = item.get("name", "")
            slot_audit["aliases_checked"] = _item_aliases_for_image(item)[:5]
            slot_audit["aliases_matched"] = hits
            slot_audit["match_status"] = "match" if matched else "mismatch"
            if not matched:
                filtered[slot] = ""
                slot_audit["outcome"] = "rejected_alias_mismatch"
                slot_audit["dedupe_status"] = "skipped_after_reject"
                audit.append(slot_audit)
                continue

        h = _hash_data_url(url)
        if h and h in seen_hashes:
            filtered[slot] = ""
            slot_audit["outcome"] = "rejected_duplicate"
            slot_audit["dedupe_status"] = f"duplicate_of_slot_{seen_hashes[h]}"
        elif h:
            seen_hashes[h] = slot
            slot_audit["dedupe_status"] = "unique"

        audit.append(slot_audit)

    return filtered, audit


# Phase D.2 list format rule. Banned superlatives must never appear on
# the cover, even softened. Allowed superlatives must be paired with a
# stated criterion (the "by" or "that" clause). The validator runs after
# the writer returns, before render starts, so a bare-superlative cover
# is killed before any image / Playwright cost is paid.
_BANNED_LIST_SUPERLATIVES_LC: tuple[str, ...] = (
    "scariest",
    "most underrated",
    "strangest",
    "most bizarre",
    "best",
    "worst",
    "coolest",
    "weirdest",
    "most surprising",
    "funniest",
    "cutest",
    "most iconic",
    "most influential",
    "most disturbing",
    "safest",
    "most dangerous",
    "least survivable",
)

# Phrases that look like a criterion clause but carry no actual axis
# ("Five films that are amazing" -> "that are" is empty). The validator
# rejects covers whose "that ..." clause matches one of these.
_EMPTY_THAT_CLAUSES: tuple[str, ...] = (
    "that are",
    "that were",
    "that is",
    "that was",
    "that you",
    "that we",
    "that everyone",
    "that nobody",
)

# Phrases that look like a criterion clause but carry no actual axis
# ("Five disasters by far the worst" -> "by far" is filler). The
# validator rejects covers whose "by ..." clause matches one of these.
_EMPTY_BY_CLAUSES: tuple[str, ...] = (
    "by far",
    "by accident",
    "by mistake",
    "by chance",
    "by no means",
    "by any measure",
)


def _validate_list_criterion(data: dict) -> tuple[bool, str]:
    """Phase D.2 list format rule check.

    Hard rules:
      1. The cover title must follow either
         "Five [items] by [criterion]" or
         "Five [items] that [verifiable condition]". The "by" or
         "that" clause must carry an actual axis, not filler ("by
         far", "that are").
      2. The cover title must not contain a banned opinion superlative
         (scariest, most iconic, etc.), even when softened.
      3. The closing slide must cite a source. Heuristic: the joined
         closing copy must contain "source", "sources", "data:",
         "ranked by", "according to", or "per ", followed by a
         non-trivial token.

    Returns (True, "") on pass, (False, reason) on fail. Reason is a
    one-line human-readable explanation suitable for surfacing to the
    autonomous agent's failure-kind tag.
    """
    cover_title_raw = data.get("cover_title")
    if not isinstance(cover_title_raw, str) or not cover_title_raw.strip():
        return False, "cover_title is missing or empty"
    cover_title = cover_title_raw.strip()
    cover_lc = cover_title.lower()

    # Rule 2 first: banned superlatives kill the cover unconditionally.
    # Match on whole-word boundaries so "best" does not match "biggest".
    for banned in _BANNED_LIST_SUPERLATIVES_LC:
        pattern = r"\b" + re.escape(banned) + r"\b"
        if re.search(pattern, cover_lc):
            return False, (
                f"cover_title uses banned opinion superlative '{banned}': "
                f"{cover_title!r}. Use 'Five [items] by [criterion]' or "
                f"'Five [items] that [verifiable condition]' instead."
            )

    # Rule 1: cover must contain a "by" or "that" clause with content.
    # Find the first " by " or " that " token and inspect what follows.
    by_idx = cover_lc.find(" by ")
    that_idx = cover_lc.find(" that ")
    clause_kind = ""
    clause = ""
    if by_idx != -1 and (that_idx == -1 or by_idx < that_idx):
        clause_kind = "by"
        clause = cover_lc[by_idx + 1 :].strip()  # includes "by ..."
    elif that_idx != -1:
        clause_kind = "that"
        clause = cover_lc[that_idx + 1 :].strip()  # includes "that ..."
    else:
        return False, (
            f"cover_title missing 'by [criterion]' or 'that "
            f"[verifiable condition]' clause: {cover_title!r}. The "
            f"Phase D.2 list format rule requires an explicit measurable "
            f"axis on the cover."
        )

    # Reject empty filler clauses that masquerade as criteria.
    if clause_kind == "by":
        for empty in _EMPTY_BY_CLAUSES:
            if clause.startswith(empty):
                rest = clause[len(empty) :].strip()
                if not rest:
                    return False, (
                        f"cover_title 'by' clause is filler "
                        f"('{empty}'), no actual criterion: "
                        f"{cover_title!r}."
                    )
        # The clause should have a noun-like token after "by".
        after_by = clause[3:].strip()  # strip "by "
        if len(after_by) < 3:
            return False, (
                f"cover_title 'by' clause is too short to be a real "
                f"criterion: {cover_title!r}."
            )
    else:  # clause_kind == "that"
        for empty in _EMPTY_THAT_CLAUSES:
            if clause == empty or clause.startswith(empty + " "):
                rest = clause[len(empty) :].strip()
                # "that are amazing" / "that were great" -> empty axis.
                if not rest or rest in {
                    "amazing", "great", "incredible", "iconic",
                    "interesting", "weird", "strange", "cool",
                    "fascinating",
                }:
                    return False, (
                        f"cover_title 'that' clause is filler "
                        f"('{empty} {rest}'), no verifiable condition: "
                        f"{cover_title!r}."
                    )
        after_that = clause[5:].strip()  # strip "that "
        if len(after_that) < 3:
            return False, (
                f"cover_title 'that' clause is too short to be a real "
                f"verifiable condition: {cover_title!r}."
            )

    # Rule 3: closing slide must cite a source. Pull text from the
    # closing block (preferred) or closing_headline (legacy field used
    # by the news pipeline). Either has to mention a source.
    closing_text_parts: list[str] = []
    closing_block = data.get("closing")
    if isinstance(closing_block, dict):
        lines = closing_block.get("lines")
        if isinstance(lines, list):
            for line in lines:
                if isinstance(line, str) and line.strip():
                    closing_text_parts.append(line.strip())
    closing_headline = data.get("closing_headline")
    if isinstance(closing_headline, str) and closing_headline.strip():
        closing_text_parts.append(closing_headline.strip())

    if not closing_text_parts:
        return False, (
            "closing slide is missing or empty: Phase D.2 list format "
            "rule requires the closing to cite the criterion source."
        )

    closing_lc = " ".join(closing_text_parts).lower()
    source_markers = (
        "source:", "sources:", "data:", "ranked by",
        "according to", "per the ", "per a ", "per data",
        "from the ", "official ", "records:",
    )
    if not any(marker in closing_lc for marker in source_markers):
        return False, (
            f"closing does not cite the criterion source. Phase D.2 "
            f"list format rule requires an explicit source citation "
            f"(e.g. 'Source: USGS confirmed fatalities, 1900-present'). "
            f"Got: {' / '.join(closing_text_parts)[:120]!r}"
        )

    return True, ""


def _verify_facts_or_raise(
    *,
    brief: str,
    data: dict,
    slides: list,
    format_type: str,
    api_key: str,
    editorial_cost_usd: float,
) -> None:
    """Run the D.1 fact verification gate. Raise CarouselShapeError on fail.

    Two independent checks:
    1. verify_consistency: Haiku consistency check (title vs claim
       contradiction; red-flag words like "fictional"/"absurdity").
    2. verify_anchors: heuristic Wikipedia cross-check on each slide claim.

    Both checks fail-OPEN on infrastructure issues (the message ships rather
    than blocks on a Wikipedia outage or missing api_key). They fail-CLOSED
    only on real quality issues.

    Raises CarouselShapeError(message="ERROR: fact verification failed ...")
    so the autonomous agent's _tag_failure_kind matches the
    `fact_verification_failed` sentinel and the caller's existing
    CarouselShapeError handler logs it and writes a quality-ledger row.
    """
    consistency_brief = {
        "title": data.get("cover_title", ""),
        "claim": brief,
        "caption_body": data.get("caption_body", ""),
        "format_type": format_type,
    }
    consistency = verify_consistency(consistency_brief, api_key)
    consistency_cost = float(consistency.get("cost_usd", 0.0) or 0.0)
    if not consistency["ok"]:
        raise CarouselShapeError(
            f"ERROR: fact verification failed (consistency): {consistency['reason']}",
            diagnostics={
                "verification_stage": "consistency",
                "reason": consistency["reason"],
            },
            usage={
                "editorial_cost_usd": editorial_cost_usd,
                "fitter_cost_usd":    0.0,
                "fitter_attempts":    1,
                "probe_attempts":     0,
                "verification_cost_usd": consistency_cost,
            },
        )

    # Extract one claim string per slide for the Wikipedia anchor check.
    # Slide shapes: lines list (compact_legacy/non-list) or item dict
    # (readable_list with structured items). Prefer the item's
    # concrete_fact / name when present; fall back to joined lines.
    claims_to_verify: list[str] = []
    for s in slides or []:
        if not s:
            continue
        if isinstance(s, dict):
            item = s.get("item") if isinstance(s.get("item"), dict) else None
            if item:
                concrete = (item.get("concrete_fact") or "").strip()
                name = (item.get("name") or "").strip()
                joined = " ".join(p for p in (name, concrete) if p)
                if joined:
                    claims_to_verify.append(joined)
                    continue
            # Non-item slide: join the lines for the anchor check.
            lines = s.get("lines") or []
            joined = " ".join(str(line) for line in lines if line)
            if joined.strip():
                claims_to_verify.append(joined.strip())
        elif isinstance(s, str):
            if s.strip():
                claims_to_verify.append(s.strip())

    if not claims_to_verify:
        return

    anchors = verify_anchors(claims_to_verify, api_key=api_key)
    if not anchors["ok"]:
        flagged_summary = "; ".join(
            f"{f['claim'][:80]} ({f['reason']})" for f in anchors["flagged"][:3]
        )
        raise CarouselShapeError(
            f"ERROR: fact verification failed (anchors): {flagged_summary}",
            diagnostics={
                "verification_stage": "anchors",
                "flagged": anchors["flagged"][:3],
            },
            usage={
                "editorial_cost_usd": editorial_cost_usd,
                "fitter_cost_usd":    0.0,
                "fitter_attempts":    1,
                "probe_attempts":     0,
                "verification_cost_usd": consistency_cost,
            },
        )


def _generate_list_content(
    brief: str, n_items: int, api_key: str, layout_mode: str,
) -> tuple[dict, list[dict]]:
    """List-mode writer: returns structured items, not prose lines.

    Sonnet emits the item fields directly; the adapter
    `_items_to_render_slides()` then maps them onto the renderer's
    existing 3-line slide shape. The original structured items
    survive on `data["items"]` and on `slide["item"]` for inspection.
    """
    from anthropic import Anthropic

    profile = get_profile(layout_mode)
    client = Anthropic(api_key=api_key)
    prompt = LIST_CONTENT_PROMPT.format(
        brand_voice_editorial=BRAND_VOICE_EDITORIAL,
        brief=brief,
        n_items=n_items,
        n_fallbacks=n_items + 2,  # cover + items + closing
        hard_cap=profile["hard_cap"],
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
        "stage": "editorial",
        "input_tokens": res.usage.input_tokens,
        "output_tokens": res.usage.output_tokens,
        "cost_usd": round(cost, 5),
    }

    data = _parse_json_payload(res.content[0].text)
    usage_records = [usage]
    already_polished = False

    try:
        _enforce_list_shape(
            data, requested_items=n_items, hard_cap=profile["hard_cap"],
        )
    except CarouselShapeError as shape_err_first:
        data = _ensure_list_visual_fields(data, n_items)
        # First repair pass: compact wording while preserving item names/ranks.
        data, polish_usage = _polish_list_wording(data, api_key)
        usage_records.append(polish_usage)
        already_polished = True
        try:
            _enforce_list_shape(
                data, requested_items=n_items, hard_cap=profile["hard_cap"],
            )
        except CarouselShapeError as shape_err_2:
            # Second repair pass: explicit fix guided by validator errors.
            repaired, repair_usage = _repair_list_shape(
                data,
                shape_err_2.diagnostics.get("list_errors")
                or shape_err_first.diagnostics.get("list_errors")
                or [],
                api_key,
                profile["hard_cap"],
            )
            usage_records.append(repair_usage)
            try:
                _enforce_list_shape(
                    repaired, requested_items=n_items, hard_cap=profile["hard_cap"],
                )
            except CarouselShapeError as shape_err_3:
                shape_err_3.usage = {
                    "editorial_cost_usd": float(usage["cost_usd"]),
                    "fitter_cost_usd": float(
                        sum(u["cost_usd"] for u in usage_records[1:])
                    ),
                    "fitter_attempts": 1,
                    "probe_attempts": 0,
                }
                raise shape_err_3
            data = repaired

    # Wording polish pass: Haiku 4.5 rewrites rendered fields and the
    # closer. Names, ranks, and image_query are forced back to the
    # originals inside _polish_list_wording, so structural drift is
    # impossible. Re-validate after the pass and surface any failure
    # the same way the first call would.
    if not already_polished:
        data, polish_usage = _polish_list_wording(data, api_key)
        usage_records.append(polish_usage)
        try:
            _enforce_list_shape(
                data, requested_items=n_items, hard_cap=profile["hard_cap"],
            )
        except CarouselShapeError as shape_err:
            shape_err.usage = {
                "editorial_cost_usd": float(usage["cost_usd"]),
                "fitter_cost_usd":    float(polish_usage["cost_usd"]),
                "fitter_attempts":    1,
                "probe_attempts":     0,
            }
            raise

    items   = data["items"]
    closing = data["closing"]

    rendered_slides = _items_to_render_slides(items, closing)
    data["slides"] = rendered_slides
    data["image_queries"] = (
        [data["cover_image_query"]]
        + [item["image_query"] for item in items]
        + [closing["image_query"]]
    )

    warnings = _validate_lines(rendered_slides, hard_cap=profile["hard_cap"])
    for w in warnings:
        _log(f"     [line warn] {w}")
    data["_line_warnings"] = warnings
    data["_fitter_attempts"] = 1
    data["_probe_attempts"] = 0

    # D.2 list format rule. Cover must follow "Five [items] by
    # [criterion]" or "Five [items] that [verifiable condition]"; banned
    # opinion superlatives ("scariest", "most iconic", etc.) are
    # rejected; closing must cite the criterion source. Runs before fact
    # verification so the Wikipedia-anchor cost is not paid on a
    # bare-superlative cover.
    list_ok, list_reason = _validate_list_criterion(data)
    if not list_ok:
        raise CarouselShapeError(
            f"ERROR: list format rule failed: {list_reason}",
            diagnostics={
                "list_format_rule": "phase_d2",
                "reason": list_reason,
                "cover_title": data.get("cover_title", ""),
            },
            usage={
                "editorial_cost_usd": float(usage["cost_usd"]),
                "fitter_cost_usd": float(
                    sum(u["cost_usd"] for u in usage_records[1:])
                ),
                "fitter_attempts": 1,
                "probe_attempts":  0,
            },
        )

    # D.1 fact verification gate (list path). Same gate as the non-list
    # branch in generate_content; runs after shape repairs so verification
    # only sees the final, ship-ready content.
    _verify_facts_or_raise(
        brief=brief,
        data=data,
        slides=rendered_slides,
        format_type="list",
        api_key=api_key,
        editorial_cost_usd=float(sum(u["cost_usd"] for u in usage_records)),
    )

    return data, usage_records


def generate_content(
    brief: str, n_slides: int, api_key: str, format_type: str = "fact",
    layout_mode: str = "compact_legacy",
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

    `layout_mode` selects the writer-prompt cap shape and the renderer
    constraints downstream:
      - compact_legacy (default) preserves the original 12-22 char
        target / 24 hard cap and runs the strict line-fit probe.
      - readable_list uses the wider 30-50 / hard-cap-56 shape; the
        renderer auto-fits the largest body size that fits the
        half-box, so the line-fit probe is skipped.

    For format_type == "list" the writer emits a structured items
    array (rank/name/rank_reason/concrete_fact/image_query) instead
    of freeform lines. See `_generate_list_content` and
    `_items_to_render_slides`. The structured items survive on
    `data["items"]` and on each `slide["item"]` for inspection.
    """
    if format_type == "list":
        # n_slides here is content-slide count = items + closing.
        # The structured list shape requires that count to be exactly
        # items + 1 (the closing slide).
        return _generate_list_content(
            brief=brief,
            n_items=max(1, n_slides - 1),
            api_key=api_key,
            layout_mode=layout_mode,
        )

    from anthropic import Anthropic

    profile = get_profile(layout_mode)
    type_guidance = _type_guidance(format_type)

    client = Anthropic(api_key=api_key)
    prompt = CONTENT_PROMPT.format(
        brand_voice_editorial=BRAND_VOICE_EDITORIAL,
        type_guidance=type_guidance,
        brief=brief,
        n_slides=n_slides,
        n_slides_plus_one=n_slides + 1,
        hard_cap=profile["hard_cap"],
        target_min=profile["writer_target_min"],
        target_max=profile["writer_target_max"],
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

    # D.1 fact verification gate. Both checks run before render so the
    # shipping cost (image sourcing, Playwright render, Meta upload) is
    # never paid on a post that contradicts itself or contains "fictional"
    # framing. CarouselShapeError so the same handler in main() logs it
    # and writes a quality-ledger row; the autonomous agent matches the
    # "ERROR: fact verification failed" sentinel ahead of the more generic
    # CONTENT_SHAPE_MISMATCH sentinel.
    _verify_facts_or_raise(
        brief=brief,
        data=data,
        slides=slides,
        format_type=format_type,
        api_key=api_key,
        editorial_cost_usd=float(usage["cost_usd"]),
    )

    # Soft warnings (orphans, weak endings, final-line-too-short).
    # hard_cap is profile-driven so readable_list does not raise false
    # warnings against the legacy 24-char limit.
    warnings = _validate_lines(slides, hard_cap=profile["hard_cap"])
    for w in warnings:
        _log(f"     [line warn] {w}")
    data["_line_warnings"] = warnings

    # Hard char cap on lines (profile-driven; 24 for compact_legacy, 56
    # for readable_list). Catches obvious overruns before render.
    _assert_lines_within_render_cap(slides, hard_cap=profile["hard_cap"])

    # Visual probe: only meaningful for compact_legacy, where the
    # Archivo-Black-at-48px-wraps-at-24-chars rule is enforced. For
    # readable_list the renderer auto-sizes body text down to fit the
    # half-box, so a strict no-wrap probe would block legitimate output.
    probe_attempts = 0
    if not profile.get("auto_size"):
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
    parser.add_argument("--layout-mode", default=None, choices=list(LAYOUT_PROFILES.keys()),
                        help="Renderer layout profile. Defaults: list -> readable_list, "
                             "fact/news -> compact_legacy.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--smoke-mode",
        action="store_true",
        help="Fast validation mode for dry-runs: reduce image pool work and skip R3 fallback.",
    )
    parser.add_argument("--subject-key", default="",
                        help="Canonical subject key for permanent dedup (e.g. 'biggest-dam-failures').")
    args = parser.parse_args()

    # Layout-profile routing lives in src/content/carousel_rules.py
    # (single source of truth). Pre-Phase-K.3 the default was an inline
    # `if args.type == "list"` check that could drift from the agent
    # shim's parallel check. Now both call the same helper.
    from src.content.carousel_rules import profile_for_format
    if args.layout_mode is None:
        layout_mode = profile_for_format(args.type)
    else:
        layout_mode = args.layout_mode

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
    _log(f"     Layout: {layout_mode}")
    if args.smoke_mode:
        if not args.dry_run:
            _log("ERROR: --smoke-mode is dry-run only.")
            return 1
        _log("     Smoke:  enabled (bounded image sourcing effort)")
    try:
        data, usage_records = generate_content(
            args.brief, n_slides, api_key, format_type=args.type,
            layout_mode=layout_mode,
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

    per_slot_aliases, per_slot_text = _build_per_slot_aliases(
        cover_slot_aliases=data.get("cover_slot_aliases", []),
        cover_title=cover_title,
        slides=slides,
    )
    _log(f"     SlotAliases: {per_slot_aliases}")

    # post_id / save_dir are defined up here (rather than just before the
    # image-fetch step) so the structured-list payload can be persisted
    # BEFORE the cover image hardgate runs. That keeps Phase 2 inspectable
    # even when image sourcing aborts the run.
    post_id = re.sub(r"[^a-z0-9]+", "-", cover_title.lower())[:30]
    ts       = datetime.now().strftime("%Y-%m-%d_%H-%M")
    slug     = re.sub(r"[^a-z0-9]+", "-", cover_title.lower())[:40]
    save_dir = repo_root / "output" / "manual" / f"{ts}_{slug}"
    save_dir.mkdir(parents=True, exist_ok=True)

    if args.type == "list" and isinstance(data.get("items"), list):
        list_payload = {
            "cover_title": cover_title,
            "label": label,
            "cover_image_query": data.get("cover_image_query"),
            "items": data["items"],
            "closing": data.get("closing"),
            "rendered_slides": [
                {"slideNumber": s.get("slideNumber"),
                 "lines": s.get("lines"),
                 "item": s.get("item")}
                for s in slides
            ],
            # _image_audit is populated AFTER content generation,
            # right after the sourcer runs. On runs that abort before
            # the sourcer completes (cover gate aborts in the
            # validation block, etc.) this key may be absent. The
            # writer updates list_data.json once more in the live
            # publish path so the audit lands eventually.
            "image_audit": data.get("_image_audit", []),
            "cover_image_status": data.get("_cover_image_status", "pending"),
            "cover_image_query": data.get("_cover_image_query", data.get("cover_image_query", "")),
            "cover_fallback_reason": data.get("_cover_fallback_reason", ""),
        }
        (save_dir / "list_data.json").write_text(
            json.dumps(list_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _log(f"     Structured list data: {(save_dir / 'list_data.json').resolve()}")
        _log(f"     Items ({len(data['items'])}):")
        for it in data["items"]:
            _log(f"       {it.get('rank')}. {it.get('name')}")
            _log(f"          rank_reason:   {it.get('rank_reason')}")
            _log(f"          concrete_fact: {it.get('concrete_fact')}")
            _log(f"          image_query:   {it.get('image_query')}")
        _log(f"     Adapted slide lines:")
        for s in slides:
            n = s.get("slideNumber")
            for j, ln in enumerate(s.get("lines", []), 1):
                _log(f"       slide {n} line {j}: {ln}")

    # ---- 2. Fetch images (ImageSourcer: pool + Haiku selection + scoring + reuse limits) ----
    _log(f"\n[2/4] Fetching images (pool mode, max 40 candidates/slot, Haiku selector)...")
    while len(queries) < total_slides:
        queries.append(intent.fallback_query or label.lower())
    while len(per_slot_aliases) < total_slides:
        per_slot_aliases.append(None)
    visual_fallbacks = data.get("visual_fallback_queries", [])
    while len(visual_fallbacks) < total_slides:
        visual_fallbacks.append("")
    # relax_image_floor is a property of the layout profile, not the
    # layout-mode string. Pre-Phase-K.3 this was an inline string match
    # that conflated layout choice with image-floor relaxation; a
    # future profile that wants readable typography with a STRICT
    # image floor would need a new branch. Read from the profile.
    sourcer = ImageSourcer(
        topic="editorial",
        use_fresh_ledger=args.dry_run,
        relax=get_profile(layout_mode)["relax_image_floor"],
    )
    smoke_pool = 12 if args.smoke_mode else None
    images  = sourcer.source_images(
        queries[:total_slides], intent, post_id,
        max_pool=smoke_pool,
        per_slot_aliases=per_slot_aliases[:total_slides],
        per_slot_text=per_slot_text[:total_slides],
        visual_fallback_queries=visual_fallbacks[:total_slides],
        smoke_mode=args.smoke_mode,
    )

    if (
        args.type == "list"
        and isinstance(data.get("items"), list)
        and not args.smoke_mode
        and (not images or not images[0])
    ):
        rescue_qs = _build_list_cover_rescue_queries(
            data,
            intent,
            queries[0] if queries else "",
        )
        if rescue_qs:
            _log(
                f"\n[cover] list cover empty after primary fetch; "
                f"trying {len(rescue_qs)} rescue quer"
                f"{'y' if len(rescue_qs) == 1 else 'ies'}..."
            )
            rescued = sourcer.rescue_list_cover(
                rescue_queries=rescue_qs,
                intent=intent,
                post_id=post_id,
                total_slides=total_slides,
                smoke_mode=args.smoke_mode,
            )
            if rescued:
                images = list(images)
                if len(images) < total_slides:
                    images.extend([""] * (total_slides - len(images)))
                images[0] = rescued
                _log("     [cover] LIST_COVER_RESCUE succeeded")

    # List-mode image quality gate: per-item alias match + carousel-wide
    # de-duplication. Wrong-but-dramatic images (Chernobyl photo on a
    # Challenger slide) and reused images (one fire photo across two
    # slides) are forced to typography. The cover and closing are
    # exempt from alias check but still subject to dedup.
    image_audit: list[dict] = []
    if args.type == "list" and isinstance(data.get("items"), list):
        images, image_audit = _validate_list_images(
            images=images,
            decisions=getattr(sourcer, "last_run_decisions", []),
            items=data["items"],
        )
        _log(f"\n     Image validation (list mode):")
        for row in image_audit:
            tag = row.get("outcome", "?")
            slot = row.get("slot", "?")
            meta = (row.get("image_meta") or "")[:80]
            extra = ""
            if row.get("match_status") == "mismatch":
                extra = (
                    f" item={row.get('item_name','')!r}"
                    f" aliases_checked={row.get('aliases_checked', [])}"
                )
            elif row.get("match_status") == "match":
                extra = f" matched={row.get('aliases_matched', [])}"
            if row.get("dedupe_status", "").startswith("duplicate_of_slot_"):
                extra += f" {row['dedupe_status']}"
            _log(
                f"       slot {slot}: {tag} | {row.get('image_provider','')} "
                f"q={row.get('image_query','')!r}{extra}"
            )
            if meta:
                _log(f"         meta: {meta}")
        data["_image_audit"] = image_audit
        # Re-save list_data.json with the image audit so cover-gate
        # aborts still leave a fully-populated payload behind for
        # inspection. The early-save (before sourcing) is a safety
        # net; this overwrite is the canonical version.
        list_path = save_dir / "list_data.json"
        try:
            existing = json.loads(list_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            existing = {}
        existing["image_audit"] = image_audit
        existing["items"] = data.get("items", existing.get("items"))
        existing["closing"] = data.get("closing", existing.get("closing"))
        # cover_image_status is set later (in the cover-policy block);
        # if the audit re-save fires AFTER that block, this picks up
        # the latest. If it fires before, the field stays "pending"
        # and gets overwritten on the live-publish save.
        existing["cover_image_status"] = data.get("_cover_image_status", existing.get("cover_image_status", "pending"))
        existing["cover_image_query"] = data.get("_cover_image_query", existing.get("cover_image_query", ""))
        existing["cover_fallback_reason"] = data.get("_cover_fallback_reason", existing.get("cover_fallback_reason", ""))
        list_path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    image_coverage = {
        "image": sum(1 for u in images if u),
        "typography": sum(1 for u in images if not u),
        "cover_failed": not bool(images and images[0]),
    }

    # Cover-image policy:
    #   list mode -> typography-only cover fallback (the item slides are
    #     what carry the value; do not abort the whole run for a missing
    #     cover photo).
    #   fact / news -> existing hard-fail behaviour, unchanged.
    cover_image_query = (queries[0] if queries else "")
    cover_decision = (
        getattr(sourcer, "last_run_decisions", [{}])[0]
        if getattr(sourcer, "last_run_decisions", None)
        else {}
    )
    cover_fallback_reason = ""
    if not images or not images[0]:
        if args.type == "list":
            cover_image_status = "typography_fallback"
            cover_fallback_reason = (
                cover_decision.get("selection_reason")
                or cover_decision.get("reason")
                or "no_cover_image_pool"
            )
            _log(
                "\n[cover] LIST_MODE_TYPOGRAPHY_FALLBACK"
                f" status=typography_fallback"
                f" cover_image_query={cover_image_query!r}"
                f" reason={cover_fallback_reason!r}"
            )
            # Ensure images[0] exists and is empty so render_cover_slide
            # gets the empty url; the cover renderer's dark base layer +
            # gradients render cleanly without a photo.
            if not images:
                images = [""] * total_slides
            else:
                images[0] = ""
            image_coverage["cover_failed"] = False  # not a failure for list
            image_coverage["cover_typography_fallback"] = True
        else:
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
    else:
        cover_image_status = "selected"
        _log(
            f"\n[cover] status=selected"
            f" cover_image_query={cover_image_query!r}"
            f" provider={cover_decision.get('chosen_provider', '')!r}"
        )
    data["_cover_image_status"] = cover_image_status
    data["_cover_image_query"] = cover_image_query
    data["_cover_fallback_reason"] = cover_fallback_reason

    # Re-save list_data.json with the resolved cover status so dry-run
    # inspection sees the final policy outcome (selected /
    # typography_fallback) rather than the "pending" placeholder
    # written by the audit-aware re-save above.
    if args.type == "list" and isinstance(data.get("items"), list):
        list_path = save_dir / "list_data.json"
        try:
            existing = json.loads(list_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            existing = {}
        existing["cover_image_status"] = cover_image_status
        existing["cover_image_query"] = cover_image_query
        existing["cover_fallback_reason"] = cover_fallback_reason
        list_path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

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
                layout_mode=layout_mode,
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
                    layout_mode=layout_mode,
                )
                slide_paths.append(out_path)
                _log(f"     slide {idx} done")

            # 9:16 story frame wrapping the cover slide. Without this the
            # story falls back to the raw 4:5 cover slide stretched into 9:16.
            # When the cover is the typography variant (no usable photo),
            # tell the story frame so it does not blur a flat brand swatch.
            story_path = tmp_dir / "story.png"
            render_story_frame(
                cover_path=cover_path,
                out_path=story_path,
                repo_root=repo_root,
                browser=browser,
                layout_mode=layout_mode,
                typography_cover=(cover_image_status == "typography_fallback"),
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
        # Phase C runtime guarantee: every caption that ships goes through
        # the shared voice normaliser. Em / en dashes resolved, smart
        # quotes straightened, spacing tidied. Applied to the final
        # assembled string so both dry-run preview and live publish see
        # exactly what Instagram will render.
        caption = normalise_caption(caption)

        # Save locally regardless of dry-run. save_dir was already
        # created up-front (right after content generation) so the
        # structured-list payload is available for inspection even when
        # the cover image gate fails. Re-mkdir is a no-op.
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
            # Defence-in-depth: same boundary check as the reel path.
            # The publisher re-reads the dedup ledger from disk just
            # before the Graph API call. (Audit R6.)
            dedup_check=brain.assert_no_duplicate,
        )

        try:
            brain.assert_no_duplicate([editorial_claim])
        except DuplicatePostError:
            _log(f"\nABORTED: this brief has already been posted (id={post_id}).")
            return 1

        publish_result = publisher.publish_carousel(
            image_urls,
            caption,
            dedup_subjects=[editorial_claim],
        )
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
                subject_key=args.subject_key or "",
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
