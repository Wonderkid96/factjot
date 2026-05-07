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
from datetime import datetime
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

# ------------------------------------------------------------------ #
# Brand constants (sourced from brand/brand_kit.json)
# ------------------------------------------------------------------ #

BRAND_VOICE = """\
Brand: factjot (@factjot)
Voice: curious, precise, dry. A smart friend explaining something remarkable.
Tone: confident, never sensational. Present tense where possible.
Reading level: general audience.

Slide format (strict):
- Each slide: exactly 3 lines
- Each line: 28 to 42 characters. Never exceed 48 characters.
- Lines must flow as connected sentences, NOT bullet points or fragments
- Each slide covers one coherent moment or idea
- Front-load the most interesting element on each slide
- No hedging, no filler, no attribution phrases ("sources say", "according to")
- No em-dashes. Use commas, full stops, or parentheses instead.
- Do not end a line with a weak connector word: a, the, and, or, of, in, to, with
- Do not leave the final line under 12 characters
- Do not split names, dates, numbers or key phrases across lines awkwardly
- Prefer clean visual rhythm over exact word count

Red keyword markup:
- Wrap 1-2 key words or short phrases per line in [r]...[/r] -- rendered in red
- Use for the most striking facts, names, numbers, turning points
- Example: "Iran sets up [r]new authority[/r] over the strait."
- Count [r]...[/r] tags in the character limit but they are short so it is fine

Cover title: 5 to 9 words. No full stop. Must contain a verb or a sting,
not a noun phrase. Sets up the story without spoiling it.
Banned shapes (chant-style, all rejected):
- "the X with no Y"
- "no X no Y"
- "X-free Y"
- "the Y that X" where Y is vague (the thing that, the one that, the X that)
The title should sound like a sentence in factjot's voice, not a tagline.
Good: "openai built a phone that refuses apps".
Good: "the software that jailed the post office workers".
Bad: "the phone with no apps".
Bad: "no apps no store".
Category label: 1-3 words in capitals. Any subject is valid — SPORT, POLITICS, CRIME, CULTURE, FOOD, DESIGN, MUSIC, INTERNET HISTORY, AVIATION, SCIENCE, or anything else that fits.

Final slide (CTA): a thought-provoking question or reflection the reader wants to debate.
Same format: 3 lines, 28-42 characters each. Do NOT reference the source or say "follow for more"."""


TYPE_GUIDANCE: dict[str, str] = {
    "fact": (
        "POST TYPE: FACT CAROUSEL.\n"
        "Single subject deep dive. The carousel must move forward across\n"
        "slides: setup, mechanism, consequence, contradiction, sting.\n"
        "No filler, no recap. One subject. Evergreen, not topical.\n"
    ),
    "news": (
        "POST TYPE: NEWS / CURRENT CAROUSEL.\n"
        "A current or recent story (last 30 days). Lead with the named\n"
        "entities and the specific weird angle the brief identifies.\n"
        "Do NOT explain the news in general terms. Assume the viewer\n"
        "knows roughly what is going on; you are pointing at the angle.\n"
        "Voice stays dry. Do not slip into newsreader register.\n"
    ),
    "list": (
        "POST TYPE: LIST CAROUSEL.\n"
        "Cover + 5 items + closing = 7 slides total. Each item slide\n"
        "names ONE specific item from the brief and gives one line of\n"
        "angle (why it belongs in this list). Item ordering is intentional.\n"
        "Closing slide should make the 5 items feel like a pattern, not\n"
        "a coincidence. Do not summarise the list in the closing line.\n"
    ),
}


def _type_guidance(format_type: str) -> str:
    return TYPE_GUIDANCE.get(format_type, TYPE_GUIDANCE["fact"])


CONTENT_PROMPT = """\
{brand_voice}

---

{type_guidance}

You are writing a factjot carousel post. The brief is:

"{brief}"

Before writing the slides, resolve the visual subject. The brief may use a
colloquial or misspelled name. Identify the canonical proper name of the subject
(e.g. brief says "Concord plane" → visual_subject is "Concorde supersonic airliner").
This ensures image searches find the right thing.

BEAT-TO-SLIDE MAPPING -- HARD RULE.

The brief may contain numbered beats describing what each slide should
cover (e.g. "(1) cover hook ... (2) setup ... (3) mechanism ... (4) ...").
If the brief contains numbered beats, you MUST follow them exactly:
- Beat (1) -> the cover slide.
- Beat (2) -> content slide 1.
- Beat (3) -> content slide 2.
- ... and so on, in order, one beat per slide.

You may NOT:
- merge two beats into one slide
- split one beat across two slides
- skip a beat
- add a slide for content not in the brief
- reorder beats

If the brief specifies N beats and you produce M slides, M must equal N.
The carousel exists to deliver the brief's argument in the brief's order.

If the brief does NOT contain numbered beats, write {n_slides} content
slides plus a cover, derived from the brief, in the order the brief
introduces ideas. Do not improvise structure.

For image_queries (one per slide including cover):
- Queries search Wikimedia Commons and Wikipedia by file title.
- Write SHORT, SUBJECT-FIRST phrases matching how archive files are titled.
- Always start with the canonical proper name from visual_subject.
- Keep each query 2-5 words. Vary aspect across slides (takeoff, cockpit, interior, crash, retirement).
- Good: "Concorde takeoff", "Concorde cockpit", "Concorde crash 2000"
- Bad: "supersonic aircraft breaking sound barrier at altitude over ocean"

For source_aliases: list canonical name variants an image archive might use
to tag or title a photo of this subject. Include all required aliases. Aim for
4-12, but exceed 12 if needed to include every named entity from image_queries.
Do not drop named entities just to satisfy a count limit. Include THREE types:

1. At least 2 multi-word aliases (2+ words each, strongest for tag providers).
   Example: "British Airways Concorde", "Air France Concorde", "BAC Concorde"

2. The bare primary subject name as a single-word alias (e.g. "Concorde").
   REQUIRED -- Wikimedia Commons filenames are sparse: "File:Concorde G-BOAG.jpg"
   contains "Concorde" but not "aircraft", so multi-word aliases miss it entirely.
   Single-word aliases on tag providers (Pixabay) still require a context_word
   match before the image is accepted, so adding "Concorde" alone does NOT let in
   photos of Place de la Concorde -- those would fail the context_word gate.

3. The bare name of every named entity that appears as the subject of any
   image_queries entry -- even if that entity is not the primary visual subject.
   Named entities are: people, companies, organisations, products, places,
   and named technologies (e.g. "TSMC", "MediaTek Dimensity").
   Do NOT extract generic descriptive words. Never add as aliases: portrait,
   chip, processor, device, concept, phone, photo, factory, office, building,
   or any other non-specific noun. Terms like "semiconductor" or "wafer" must
   not be added as aliases unless they are part of a specific named product or
   named technology (e.g. "TSMC N2P" is acceptable, bare "wafer" is not).

   Examples of correct extraction:
   - image_queries entry "Sam Altman portrait" → add alias "Sam Altman"
   - image_queries entry "MediaTek chip processor" → add alias "MediaTek"
   - image_queries entry "TSMC semiconductor wafer" → add alias "TSMC"
   - image_queries entry "Luxshare manufacturing factory" → add alias "Luxshare"
   Do NOT extract: "portrait", "chip", "semiconductor", "factory".

   Why: per-slide queries target different named entities across the deck. A
   Wikipedia photo of Sam Altman has metadata "Sam Altman" -- it needs "Sam Altman"
   as a bare alias to pass the image gate. "Sam Altman phone" requires "phone" in
   the metadata, which a portrait image will never have.

Example for Concorde: ["British Airways Concorde", "Air France Concorde",
"BAC Concorde", "Concorde aircraft", "supersonic airliner", "Concorde"]

For cover_slot_aliases: bare named entity names that the cover image_query targets.
Same rules as slot_aliases. Omit or use [] if the cover targets the primary visual
subject already covered by source_aliases.

For each slide's slot_aliases: bare named entity names that the slide's image_query
specifically targets. These REPLACE the global source_aliases for that slot (global
aliases are not appended). Leave slot_aliases as [] if the slide targets the same
subject as the overall carousel.

Rules for slot_aliases and cover_slot_aliases:
- Include only: people, companies, organisations, products, places, named technologies.
- Do NOT include generic words: portrait, chip, processor, device, concept, phone,
  photo, factory, office, building, designer, original, comparison, or any other
  non-specific noun.
- Include at least the bare proper name. One multi-word variant is acceptable.

Examples:
- image_query "Sam Altman portrait" → slot_aliases: ["Sam Altman"]
- image_query "Jony Ive designer portrait" → slot_aliases: ["Jony Ive"]
- image_query "Apple iPhone original 2007" → slot_aliases: ["Apple", "Apple iPhone"]
- image_query "MediaTek chip processor" → slot_aliases: ["MediaTek"]
- image_query "OpenAI logo" → slot_aliases: [] (global source_aliases already covers this)
- image_query "Concorde takeoff" → slot_aliases: [] (global source_aliases already covers this)

For context_words: list 4-8 words that confirm the metadata is about the
RIGHT subject when only a single-word alias matched. These are not required
for multi-word alias matches. Describe what the subject IS, not what it looks like.
Example for Concorde aircraft: ["aircraft", "airliner", "aviation", "airline",
"supersonic", "jet", "airways", "flight"]

For negative_terms: list 8-16 words that would appear in metadata of WRONG images.
Think about every other meaning of the subject name, across ALL of these categories:
- Geographic/landmark: squares, plazas, obelisks, fountains, monuments, parks
- Transit infrastructure: metro stations, train stations, bus terminals, airports
  (IMPORTANT: if the subject name is shared with a metro or train station, include
  "station", "metro", "ligne", "platform", "terminal")
- Naval/military: ships, frigates, destroyers, HMS prefix, class names
  (if the subject name is shared with a vessel or ship class, include
  "frigate", "destroyer", "ship", "vessel", "HMS", "warship", "class")
- Unrelated proper nouns: people, places, brands, animals with the same name
IMPORTANT: scan all meanings of the subject name before writing this list.
Example for Concorde (aircraft, not the Paris square AND not the Paris metro AND not the warship class):
["place de la concorde", "paris", "obelisk", "luxor", "fountain",
"monument", "square", "plaza", "station", "metro", "platform",
"frigate", "warship", "HMS", "concord massachusetts", "concord grape"]

For subject_type: one short category string that describes what kind of subject
this is. Used to weight scoring. Choose from:
historical aircraft, living person, historical person, animal, place, building,
technology, invention, natural event, disaster, artwork, cultural object,
internet culture, science concept, organisation, vehicle, spacecraft, ship, other

For preferred_image_types: 4-8 short phrases describing ideal visual aspects for
this subject. Used to boost candidate scores. Be specific to the subject.
Example for Concorde: ["takeoff", "landing", "cockpit", "droop nose", "in flight",
"British Airways livery", "Air France livery", "museum display"]

For avoid_image_types: 4-8 short phrases describing visual types to penalise.
Example for Concorde: ["diagram", "map", "illustration", "airshow crowd",
"generic contrail", "generic sky", "model kit", "toy"]

For fallback_query: the canonical proper name alone, 1-4 words.
Used when a slot query finds nothing. Example: "Concorde aircraft".

For visual_fallback_queries: one short stock-photography search term per slot
(cover first, then content slides, in the same order as image_queries).
Used when both the slot query AND the global aliases find nothing.
These must be purely visual and descriptive -- never brand names, never the
subject's own name. Describe what kind of image would feel thematically right
for that slide even if it doesn't show the actual subject.
- Good: "smartphone screen apps icons", "computer chip circuit board",
  "tech factory assembly line", "artificial intelligence network nodes",
  "person using phone coffee shop", "silicon wafer semiconductor"
- Bad: "OpenAI logo", "Sam Altman", "MediaTek chip" (too subject-specific,
  will find nothing or find junk if the subject has no stock coverage)
Keep each query 3-6 words. Vary them across slides -- do not repeat the
same phrase. These are the last resort before a slide becomes typography-only.

Return JSON only:
{{
  "cover_title": "3-5 word punchy title",
  "label": "CATEGORY LABEL",
  "caption_body": "2-3 sentences. Human, warm. No hashtags.",
  "visual_subject": "canonical name and type of the main subject, max 12 words",
  "subject_type": "one category string from the list above",
  "fallback_query": "canonical proper name, 1-4 words",
  "source_aliases": ["multi-word alias 1", "multi-word alias 2", "single word ok"],
  "context_words": ["word1", "word2", ...],
  "negative_terms": ["wrong term 1", "wrong term 2", ...],
  "preferred_image_types": ["type1", "type2", ...],
  "avoid_image_types": ["type1", "type2", ...],
  "image_queries": ["query for cover", "query for slide 1", ...],
  "visual_fallback_queries": ["fallback for cover", "fallback for slide 1", ...],
  "cover_slot_aliases": ["NamedEntityForCover"],
  "slides": [
    {{"slideNumber": 1, "lines": ["...", "...", "..."], "slot_aliases": ["NamedEntity"]}}
  ]
}}

Exactly 3 lines per slide. One image_queries entry per slide including cover.
Return JSON only, no prose."""


# ------------------------------------------------------------------ #
# Content generation via Claude Sonnet
# ------------------------------------------------------------------ #

_WEAK_ENDINGS = frozenset({"a", "the", "and", "or", "of", "in", "to", "with", "an", "at", "by", "for"})


def _strip_markup(text: str) -> str:
    return re.sub(r"\[/?r\]", "", text)


def _validate_lines(slides: list[dict]) -> list[str]:
    """Return warning strings for lines that violate character rules."""
    warnings: list[str] = []
    for i, slide in enumerate(slides, 1):
        lines = slide.get("lines", [])
        for j, raw_line in enumerate(lines):
            line = _strip_markup(raw_line).strip()
            if len(line) > 48:
                warnings.append(f"slide {i} line {j+1}: {len(line)} chars (max 48): {line!r}")
            if len(line) < 12 and j == len(lines) - 1:
                warnings.append(f"slide {i} final line too short ({len(line)} chars): {line!r}")
            last_word = line.rstrip(".,;:!?").split()[-1].lower() if line.split() else ""
            if last_word in _WEAK_ENDINGS:
                warnings.append(f"slide {i} line {j+1}: ends with weak word '{last_word}'")
    return warnings


def generate_content(
    brief: str, n_slides: int, api_key: str, format_type: str = "fact",
) -> tuple[dict, dict]:
    """Write the carousel slides + cover + caption + image metadata.

    Uses Sonnet 4.6 because this is the final reader-facing copy; editorial
    voice, mechanism precision, and conceptual sting matter here. Haiku
    flattened the language at the 28-42 char constraint. The repair pass
    below stays on Haiku because that is a constrained-fit task, not an
    editorial one.

    `format_type` selects the writer guidance (fact / news / list).
    Structural rules (lines per slide, char limits, image queries) are
    shared across all three.
    """
    client  = Anthropic(api_key=api_key)
    prompt  = CONTENT_PROMPT.format(
        brand_voice=BRAND_VOICE,
        type_guidance=_type_guidance(format_type),
        brief=brief,
        n_slides=n_slides,
    )
    res = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        temperature=0.5,
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
    if len(slides) < 1:
        raise RuntimeError("No slides returned")
    if len(slides) > 8:
        slides = slides[:8]
        data["slides"] = slides
    for i, s in enumerate(slides, 1):
        lines = s.get("lines")
        if not isinstance(lines, list) or len(lines) < 2:
            raise RuntimeError(f"Slide {i} has too few lines: {lines}")
        if len(lines) > 3:
            s["lines"] = lines[:3]

    # Validate line character rules. Warn-only -- never silently rewrite.
    # Sonnet's output is the truth; if a line is awkward, that is a brief
    # or render concern, not something a second model should "fix".
    warnings = _validate_lines(slides)
    for w in warnings:
        _log(f"     [line warn] {w}")

    pricing = {"input": 3.00, "output": 15.00}
    cost = (res.usage.input_tokens / 1_000_000) * pricing["input"] + \
           (res.usage.output_tokens / 1_000_000) * pricing["output"]
    usage = {
        "model": "claude-sonnet-4-6",
        "input_tokens": res.usage.input_tokens,
        "output_tokens": res.usage.output_tokens,
        "cost_usd": round(cost, 5),
    }
    return data, usage


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

    # ---- 1. Generate content ----
    _log(f"\n[1/4] Generating content from brief...")
    _log(f"     Brief:  \"{args.brief}\"")
    _log(f"     Type:   {args.type}  (target {total_slides_arg} slides total)")
    data, usage = generate_content(args.brief, n_slides, api_key, format_type=args.type)
    _log(f"     {usage['input_tokens']:,} in / {usage['output_tokens']:,} out  ~${usage['cost_usd']:.4f}")

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

    if not images or not images[0]:
        _log("\nERROR: COVER_IMAGE_FAILED — no usable image found for the cover slide.")
        _log("       Run failed. Check image sourcer DEBUG logs for pool sizes and rejection reasons.")
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
            _log(f"\n     Total slides: {total_slides}  |  Cost: ${usage['cost_usd']:.4f}")
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

        result      = publisher.publish_carousel(image_urls, caption)
        ig_media_id = result.get("id") or result.get("ig_media_id", "")
        _log(f"\nPosted! Media ID: {ig_media_id}")
        if ig_media_id:
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
