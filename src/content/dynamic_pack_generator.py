"""Dynamic list-pack generator for the curated-list pipeline.

Produces a fresh list theme + items every day so the rotation does
not have to recycle the 8 hand-curated packs every 8 days. The
generator's contract:

- Theme must have a defensible criterion that survives "would a human
  who knows cinema recognise this list shape as coherent?". Banned
  shapes: circular ("german films that are german"), purely-superlative
  with no qualifier ("scariest films"), or boilerplate genre-only
  ("five action films").
- 5-7 items, each by title + release year. The resolver walks each
  title through TMDB.search_movie/search_tv; anything that does not
  resolve to a TMDB id is dropped. A pack with fewer than 4 resolved
  items is treated as a generation failure.
- Hooks are 1-2 sentences in factjot voice (curious, precise, dry).
  No em dashes. No "you won't believe". No flattery.

Items CAN reappear across different themes (Apocalypse Now showing up
in both a war-films list and a Coppola list is fine). Themes
themselves are deduplicated against `used_list_themes.jsonl` for the
last N entries so the model does not propose a near-duplicate of a
recent theme.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

from src.research.tmdb_client import TMDBClient

# Sonnet 4.6 - same model the autonomous agent uses. The list-theme
# generation budget is tiny (~600 tokens out per pack) so cost is low.
_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 1500
_TEMPERATURE = 0.85
_ITEM_TARGET = 5         # default item count
_ITEM_MIN_AFTER_RESOLVE = 4  # drop pack if fewer than this resolve on TMDB
_THEME_HISTORY_LIMIT = 20

# Titles that have appeared too many times and should never be included
# as list items again. Add to this list when a title keeps surfacing.
_TITLE_BLOCKLIST: frozenset[str] = frozenset({
    "fleabag",
})


def _theme_fingerprint(title: str, subtitle: str) -> str:
    """Return a short stable hash for a generated theme.

    Used by the rotation ledger to recognise "we already shipped this
    theme" without requiring identical title strings. The fingerprint
    is the sha1 of normalised lowercase content tokens.
    """
    text = f"{title}\n{subtitle}".lower()
    tokens = sorted(set(re.findall(r"[a-z0-9]{4,}", text)))
    return hashlib.sha1(" ".join(tokens).encode()).hexdigest()[:14]


def _build_prompt(recent_themes: list[str], allowed_categories: list[str]) -> str:
    """Sonnet prompt for one fresh list pack.

    `recent_themes` are short descriptors of recently-shipped themes
    that the model is told to avoid.
    """
    recent_block = ""
    if recent_themes:
        bullets = "\n".join(f"- {t}" for t in recent_themes)
        recent_block = (
            "RECENT THEMES (do not propose a near-duplicate of any of these "
            f"- vary the criterion and the angle):\n{bullets}\n\n"
        )
    blocked_block = ""
    if _TITLE_BLOCKLIST:
        titles = ", ".join(sorted(_TITLE_BLOCKLIST))
        blocked_block = (
            f"BANNED TITLES - never include these as list items under any "
            f"theme: {titles}.\n\n"
        )
    return (
        "You curate film and TV recommendation lists for factjot, an "
        "Instagram account whose audience cares about cinema and TV. "
        "Generate ONE list pack ready to ship.\n\n"
        "VOICE: curious, precise, dry. British English. No em dashes. "
        "No 'you won't believe'. No 'best of all time' inflation. "
        "Specific, defensible, occasionally opinionated.\n\n"
        "WHAT MAKES A GOOD LIST:\n"
        "1. The criterion is concrete and defensible. The viewer should "
        "be able to nod and say 'yes that fits' to each pick. Examples "
        "of good criteria: 'films shot in real wartime locations', "
        "'directors' debut features that scared the studio', 'TV shows "
        "that wrapped before they overstayed', 'films under 90 minutes "
        "that hit harder than 3-hour epics'.\n"
        "2. The criterion is NOT circular or boilerplate. Bad: 'german "
        "films that are german', 'five sci-fi films'. The criterion has "
        "to be a real angle, not a label restated.\n"
        "3. Items are real films/TV that exist on TMDB. Cite each by "
        "title and release year so the resolver can find them.\n"
        "4. The hook for each item is 1-2 sentences explaining why it "
        "fits the criterion. Specific over flattering.\n\n"
        f"{blocked_block}"
        f"{recent_block}"
        f"PICK ONE category from: {', '.join(allowed_categories)}.\n\n"
        "Return strict JSON only, no fenced block, no commentary. Shape:\n"
        "{\n"
        '  "title": "5-7 word cover title using the criterion",\n'
        '  "subtitle": "1 short line under the title (not the criterion '
        'repeated; an angle on it)",\n'
        '  "category": "FILM LIST" | "TV LIST" | "HORROR LIST" | "WORLD CINEMA",\n'
        '  "topic": "film" | "tv",\n'
        '  "kind": "movie" | "tv",\n'
        '  "items": [\n'
        '    {"expected_title": "...", "year": 1979, '
        '"hook": "1-2 sentences in factjot voice", '
        '"accent_word": "short phrase from the hook to italicise"},\n'
        "    ... 5 to 7 items total ...\n"
        '  ],\n'
        '  "closing_headline": "the recap slide title (3-6 words)",\n'
        '  "closing_cta": "1 line CTA on the recap slide",\n'
        '  "caption": "Instagram caption body, 1-3 sentences. No hashtags '
        '- the pipeline appends those. Ends with a question or statement, '
        'not flattery."\n'
        "}\n"
    )


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    return text


def _parse_payload(raw: str) -> dict[str, Any]:
    text = _strip_fence(raw)
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError(f"no JSON object in response: {text[:120]}")
    return json.loads(match.group(0))


def _generate_payload(
    api_key: str,
    recent_themes: list[str],
    allowed_categories: list[str],
) -> tuple[dict[str, Any], float]:
    """Call Sonnet once and return (parsed_payload, cost_usd)."""
    from anthropic import Anthropic

    client = Anthropic(api_key=api_key)
    prompt = _build_prompt(recent_themes, allowed_categories)
    res = client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        temperature=_TEMPERATURE,
        messages=[{"role": "user", "content": prompt}],
    )
    raw_text = ""
    try:
        raw_text = res.content[0].text or ""
    except (AttributeError, IndexError):
        raw_text = ""
    payload = _parse_payload(raw_text)

    # Sonnet 4.6 pricing: $3 in / $15 out per 1M tokens.
    try:
        cost = (
            res.usage.input_tokens / 1_000_000 * 3.00
            + res.usage.output_tokens / 1_000_000 * 15.00
        )
    except AttributeError:
        cost = 0.0
    return payload, cost


def _resolve_items(
    raw_items: list[dict],
    kind: str,
    tmdb: TMDBClient,
) -> list[dict]:
    """Walk the model-proposed items, attaching tmdb_id where TMDB has
    a match. Items with no match are dropped (logged).
    """
    out: list[dict] = []
    for item in raw_items:
        title = (item.get("expected_title") or "").strip()
        year = item.get("year")
        if not title:
            continue
        try:
            year_int = int(year) if year else None
        except (TypeError, ValueError):
            year_int = None
        tmdb_id: int | None = None
        if kind == "tv":
            tmdb_id = tmdb.search_tv(title, year_int)
        else:
            tmdb_id = tmdb.search_movie(title, year_int)
        if not tmdb_id:
            print(
                f"  [dynamic-pack] DROP no TMDB match for "
                f"{title!r} ({year_int})",
                flush=True,
            )
            continue
        out.append({
            "kind": kind,
            "tmdb_id": tmdb_id,
            "expected_title": title,
            "hook": (item.get("hook") or "").strip(),
            "accent_word": (item.get("accent_word") or "").strip(),
            "imdb_score": "",   # filled later by pack_resolver via OMDb
            "rotten_score": "",
            "genre": "",
        })
    return out


class DynamicPackError(RuntimeError):
    """Raised when generation fails in a way the caller should recover from."""


def generate_dynamic_pack(
    *,
    recent_themes: list[str] | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Generate one dynamic list pack ready for pack_resolver.

    Returns a dict matching the LIST_PACKS entry shape so it slots
    straight into ship_curated_list. Raises DynamicPackError on
    unrecoverable failure.
    """
    api_key = (api_key or os.getenv("ANTHROPIC_API_KEY", "")).strip()
    if not api_key:
        raise DynamicPackError("ANTHROPIC_API_KEY missing")

    recent_themes = (recent_themes or [])[-_THEME_HISTORY_LIMIT:]
    allowed_categories = ["FILM LIST", "TV LIST", "HORROR LIST", "WORLD CINEMA"]

    payload, cost = _generate_payload(api_key, recent_themes, allowed_categories)
    print(
        f"  [dynamic-pack] generated theme={payload.get('title')!r} "
        f"cost=${cost:.4f}",
        flush=True,
    )

    title = (payload.get("title") or "").strip()
    if not title:
        raise DynamicPackError("model returned no title")
    subtitle = (payload.get("subtitle") or "").strip()
    category = (payload.get("category") or "FILM LIST").upper()
    if category not in allowed_categories:
        category = "FILM LIST"
    topic = (payload.get("topic") or "film").lower()
    kind = (payload.get("kind") or "movie").lower()
    if kind not in ("movie", "tv"):
        kind = "movie"
    closing_headline = (payload.get("closing_headline") or "What did we miss?").strip()
    closing_cta = (payload.get("closing_cta") or "Comment with your picks.").strip()
    caption = (payload.get("caption") or "").strip()

    raw_items = payload.get("items") or []
    if not isinstance(raw_items, list) or len(raw_items) < _ITEM_MIN_AFTER_RESOLVE:
        raise DynamicPackError(
            f"model returned {len(raw_items)} items; need >= {_ITEM_MIN_AFTER_RESOLVE}"
        )

    tmdb = TMDBClient()
    resolved = _resolve_items(raw_items, kind, tmdb)
    if len(resolved) < _ITEM_MIN_AFTER_RESOLVE:
        raise DynamicPackError(
            f"only {len(resolved)} items resolved on TMDB; "
            f"need >= {_ITEM_MIN_AFTER_RESOLVE}"
        )

    fingerprint = _theme_fingerprint(title, subtitle)
    slug = f"dyn_{fingerprint}"

    pack = {
        "slug": slug,
        "title": title,
        "subtitle": subtitle,
        "category": category,
        "series": "factjot",
        "topic": topic,
        "items": resolved[:7],
        "closing": {
            "headline": closing_headline,
            "cta": closing_cta,
        },
        "caption": caption,
        # Diagnostics for the ledger:
        "_dynamic": True,
        "_theme_fingerprint": fingerprint,
        "_generation_cost_usd": cost,
    }
    return pack
