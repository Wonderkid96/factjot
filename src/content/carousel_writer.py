"""Two-stage carousel content writer.

Stage A (write_editorial_slides): a Sonnet 4.6 call that produces
canonical, meaning-complete slide prose with NO line-break or char-cap
pressure. This is where editorial decisions happen.

Stage B (fit_slide_lines): a Haiku 4.5 call that converts each slide's
prose into exactly 3 lines that fit the visual cap. The fitter is
explicitly told NOT to change facts, names, dates, numbers, or
entities. A FactPreservationError is raised if entity identity drifts.

Phase 1 of the content quality recovery. Replaces the single-stage
generate_content() in pipelines/manual/ship_manual_post.py which
mixed editorial decisions with line geometry.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from anthropic import Anthropic


# ------------------------------------------------------------------ #
# Public types
# ------------------------------------------------------------------ #


@dataclass
class EditorialSlide:
    """One slide's prose, before line fitting."""
    slide_index: int          # 1-based, cover = 1
    prose: str                # 1-2 sentences, meaning-complete
    beat_id: str = ""         # writer-supplied beat identifier (optional)


@dataclass
class SlideFit:
    """One slide's fitted lines."""
    slide_index: int
    lines: list[str]          # exactly 3 strings


@dataclass
class WriterResult:
    """Output of stage A. The pipeline uses this then calls stage B."""
    cover_title: str
    label: str
    caption_body: str
    visual_subject: str
    subject_type: str
    fallback_query: str
    source_aliases: list[str]
    context_words: list[str]
    negative_terms: list[str]
    preferred_image_types: list[str]
    avoid_image_types: list[str]
    image_queries: list[str]
    visual_fallback_queries: list[str]
    cover_slot_aliases: list[str]
    slot_aliases: list[list[str]]
    slides: list[EditorialSlide]
    dropped_facts: list[str] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)


class FactPreservationError(RuntimeError):
    """Raised when the fitter changes a fact, name, date or number.

    Carries a `usage` dict (Haiku call that produced the bad output) so
    callers can ledger the cost honestly even though the run failed.
    """

    def __init__(self, message: str, *, usage: dict[str, Any] | None = None):
        super().__init__(message)
        self.usage = usage or {}


class LineFitError(RuntimeError):
    """Raised when the fitter cannot produce 3 lines under the cap.

    Carries a `usage` dict for the same reason as FactPreservationError.
    """

    def __init__(self, message: str, *, usage: dict[str, Any] | None = None):
        super().__init__(message)
        self.usage = usage or {}


# ------------------------------------------------------------------ #
# Stage A: editorial writer (Sonnet 4.6)
# ------------------------------------------------------------------ #

EDITORIAL_PROMPT_TEMPLATE = """\
{brand_voice_editorial}

---

{type_guidance}

You are writing a factjot carousel post. The brief is:

"{brief}"

Stage A: editorial writing only. Write meaning-complete slide prose.
You are NOT line-breaking. You are NOT trying to fit characters per
line. The next stage handles layout.

Rules:
- Cover title: 5-9 words, no full stop, must contain a verb or sting.
- Each content slide: 1-2 sentences of prose, complete, factual.
- Preserve specific names, dates, numbers, places.
- If a beat is too dense to fit one slide, surface the dropped sub-fact
  in `dropped_facts` rather than welding fragments.

(See the BEAT DENSITY block above for what counts as one beat.)
(See the PHOTOGRAPHABLE BEATS block above for image_query rules.)

Return JSON only:
{{
  "cover_title": "5-9 word title",
  "label": "CATEGORY",
  "caption_body": "2-3 sentences. Human, warm. No hashtags.",
  "visual_subject": "canonical name and type",
  "subject_type": "one category string",
  "fallback_query": "1-4 words",
  "source_aliases": ["..."],
  "context_words": ["..."],
  "negative_terms": ["..."],
  "preferred_image_types": ["..."],
  "avoid_image_types": ["..."],
  "image_queries": ["cover", "slide 1", ...],
  "visual_fallback_queries": ["cover fallback", "slide 1 fallback", ...],
  "cover_slot_aliases": ["..."],
  "dropped_facts": ["..."],
  "slides": [
    {{"slide_index": 2, "prose": "1-2 sentence factual statement", "beat_id": "2", "slot_aliases": ["..."]}}
  ]
}}

Slide indexing: cover is slide 1; the prose slides start at slide 2.
Return exactly {n_content_slides} prose slides. Do not include the
cover in `slides` (its text is in `cover_title`).
"""


def _parse_json_payload(raw: str) -> dict:
    """Tolerantly extract the first JSON object from a model response.

    Models occasionally append commentary or explanatory text after the
    JSON. The previous fallback (raw[first_{ : last_}+1]) spans across
    that commentary and re-fails with `Extra data`. raw_decode skips
    leading whitespace, parses the first JSON object, and returns it
    regardless of what follows.
    """
    raw = raw.strip()
    decoder = json.JSONDecoder()
    # Try a fenced ```json block first - it's the most reliable signal.
    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", raw, re.IGNORECASE)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass  # fall through to raw_decode
    # Locate the first '{' and parse just the JSON object that starts there.
    start = raw.find("{")
    if start == -1:
        raise json.JSONDecodeError("no JSON object found", raw, 0)
    obj, _end = decoder.raw_decode(raw[start:])
    if not isinstance(obj, dict):
        raise json.JSONDecodeError("expected JSON object", raw, start)
    return obj


def write_editorial_slides(
    *,
    brief: str,
    n_content_slides: int,
    format_type: str,
    api_key: str,
    brand_voice_editorial: str,
    type_guidance: str,
) -> tuple[WriterResult, dict]:
    """Call Sonnet 4.6 with the editorial prompt. Returns parsed result + usage."""
    client = Anthropic(api_key=api_key)
    prompt = EDITORIAL_PROMPT_TEMPLATE.format(
        brand_voice_editorial=brand_voice_editorial,
        type_guidance=type_guidance,
        brief=brief,
        n_content_slides=n_content_slides,
    )
    res = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        temperature=0.5,
        messages=[{"role": "user", "content": prompt}],
    )
    data = _parse_json_payload(res.content[0].text)

    slides_raw = data.get("slides") or []
    slides = [
        EditorialSlide(
            slide_index=int(s.get("slide_index", i + 2)),
            prose=str(s.get("prose", "")).strip(),
            beat_id=str(s.get("beat_id", "")),
        )
        for i, s in enumerate(slides_raw)
    ]

    result = WriterResult(
        cover_title=data.get("cover_title", ""),
        label=str(data.get("label", "FACTJOT")).upper(),
        caption_body=data.get("caption_body", ""),
        visual_subject=data.get("visual_subject", ""),
        subject_type=data.get("subject_type", ""),
        fallback_query=data.get("fallback_query", ""),
        source_aliases=list(data.get("source_aliases") or []),
        context_words=list(data.get("context_words") or []),
        negative_terms=list(data.get("negative_terms") or []),
        preferred_image_types=list(data.get("preferred_image_types") or []),
        avoid_image_types=list(data.get("avoid_image_types") or []),
        image_queries=list(data.get("image_queries") or []),
        visual_fallback_queries=list(data.get("visual_fallback_queries") or []),
        cover_slot_aliases=list(data.get("cover_slot_aliases") or []),
        slot_aliases=[list(s.get("slot_aliases") or []) for s in slides_raw],
        slides=slides,
        dropped_facts=list(data.get("dropped_facts") or []),
        raw_payload=data,
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
    return result, usage


# ------------------------------------------------------------------ #
# Stage B: fitter (Haiku 4.5)
# ------------------------------------------------------------------ #

FITTER_PROMPT_TEMPLATE = """\
You are the layout fitter. The editorial writer above has produced
meaning-complete slide prose. Your only job is to break that prose
into exactly 3 short lines per slide that fit the renderer's hard
character cap.

HARD RULES:
1. Output exactly 3 lines per slide. No more, no fewer.
2. No line may exceed {hard_cap} characters (counting [r]...[/r] markup
   as zero-width style spans, i.e. only the inner text counts).
3. You MUST NOT change any factual content. Names, dates, numbers,
   place names, organisation names, and entities must appear with the
   same spelling and the same numeric value as in the input prose.
4. You MAY rephrase for compactness ONLY where meaning is preserved.
   You MAY drop softening words (just, very, really, simply).
5. Lowercase only. The renderer text-transforms anyway, but write it
   lowercase to make the cap accurate.
6. No em dashes. Use commas, full stops, parentheses.
7. Wrap 1-2 key words or short phrases per line in [r]...[/r] for the
   accent colour. Pick the most striking word, name, or number.
8. Anti-orphan: a line must have at least 3 words OR be a single
   capitalised entity standing alone (e.g. "carl norden,").
9. Last line must be at least 8 characters.
10. No line may end on a weak connector: a, the, and, or, of, in, to,
    with, an, at, by, for.

Input slides (one per line, JSON):
{slides_json}

Return JSON only:
{{
  "slides": [
    {{"slide_index": 1, "lines": ["line one", "line two", "line three"]}}
  ]
}}

Return exactly {n_slides} entries, one per input slide, in the same order.
"""


def fit_slide_lines(
    *,
    editorial_slides: list[EditorialSlide],
    hard_cap: int,
    api_key: str,
    prior_attempt_feedback: str = "",
) -> tuple[list[SlideFit], dict]:
    """Call Haiku 4.5 to fit each slide's prose to 3 lines under the cap.

    Raises FactPreservationError if entity identity drifts vs input.
    Raises LineFitError if any line still exceeds the cap.
    """
    client = Anthropic(api_key=api_key)
    slides_json = json.dumps(
        [
            {"slide_index": s.slide_index, "prose": s.prose}
            for s in editorial_slides
        ],
        ensure_ascii=False,
    )
    feedback_block = ""
    if prior_attempt_feedback:
        feedback_block = (
            "\n\nThe previous attempt failed. Specific issues:\n"
            f"{prior_attempt_feedback}\n"
            "Fix only those specific lines. Keep the rest unchanged.\n"
        )
    prompt = FITTER_PROMPT_TEMPLATE.format(
        hard_cap=hard_cap,
        slides_json=slides_json,
        n_slides=len(editorial_slides),
    ) + feedback_block
    res = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        temperature=0.1,
        messages=[{"role": "user", "content": prompt}],
    )

    # Compute usage upfront so we can attach it to any raised exception
    # (callers ledger the partial cost on failed runs).
    pricing = {"input": 0.80, "output": 4.00}
    cost = (
        res.usage.input_tokens / 1_000_000 * pricing["input"]
        + res.usage.output_tokens / 1_000_000 * pricing["output"]
    )
    _usage_so_far = {
        "model": "claude-haiku-4-5-20251001",
        "stage": "fitter",
        "input_tokens": res.usage.input_tokens,
        "output_tokens": res.usage.output_tokens,
        "cost_usd": round(cost, 5),
    }

    data = _parse_json_payload(res.content[0].text)

    fits_raw = data.get("slides") or []
    if len(fits_raw) != len(editorial_slides):
        raise LineFitError(
            f"fitter returned {len(fits_raw)} slides, expected {len(editorial_slides)}",
            usage=_usage_so_far,
        )

    fits: list[SlideFit] = []
    for inp, out in zip(editorial_slides, fits_raw):
        lines = list(out.get("lines") or [])
        if len(lines) != 3:
            raise LineFitError(
                f"slide {inp.slide_index}: fitter returned {len(lines)} lines",
                usage=_usage_so_far,
            )
        for line in lines:
            stripped = re.sub(r"\[/?r\]", "", line).strip()
            if len(stripped) > hard_cap:
                raise LineFitError(
                    f"slide {inp.slide_index}: line {len(stripped)} > cap {hard_cap}: {stripped!r}",
                    usage=_usage_so_far,
                )
        joined_in = inp.prose
        joined_out = " ".join(lines)
        in_numbers = set(re.findall(r"\d+(?:[.,]\d+)*", joined_in))
        out_numbers = set(re.findall(r"\d+(?:[.,]\d+)*", joined_out))
        missing_numbers = in_numbers - out_numbers
        if missing_numbers:
            raise FactPreservationError(
                f"slide {inp.slide_index}: fitter dropped numbers {sorted(missing_numbers)}",
                usage=_usage_so_far,
            )
        in_propers = {
            w.rstrip(".,;:!?")
            for w in joined_in.split()
            if w[:1].isupper()
        }
        out_lower = joined_out.lower()
        missing_propers = {
            w for w in in_propers
            if w.lower() not in out_lower and len(w) > 2
        }
        if missing_propers:
            raise FactPreservationError(
                f"slide {inp.slide_index}: fitter dropped proper nouns "
                f"{sorted(missing_propers)}",
                usage=_usage_so_far,
            )
        fits.append(SlideFit(slide_index=inp.slide_index, lines=lines))

    usage = {
        "model": "claude-haiku-4-5-20251001",
        "stage": "fitter",
        "input_tokens": res.usage.input_tokens,
        "output_tokens": res.usage.output_tokens,
        "cost_usd": round(cost, 5),
    }
    return fits, usage
