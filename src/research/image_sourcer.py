"""Orchestrate image pool collection, scoring, and selection for carousel slides.

This module sits between the pipelines and ImageFetcher:
  - Pipelines construct an ImageIntent from Claude's JSON and call ImageSourcer.
  - ImageSourcer drives ImageFetcher.fetch_pool() and owns scoring + fallback.
  - ImageFetcher (HTTP, candidate validation) is not modified.

Fallback contract:
  1. Haiku selects from the pre-filtered, scored candidate pool (primary pick).
  2. Code enforces all hard rules before and after Haiku (safety layer).
  3. Deterministic fallback: top-scoring eligible candidate with score >= MIN_SCORE.
  4. Reuse a committed image: use_count < 2, URL != last_used_url.
  5. Typography-only slide (returns "").
  No wrong-subject image is ever selected over a typography slide.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from src.research.image_fetcher import ImageFetcher, NoImageFound, PoolCandidate
from src.research.used_images import UsedImageLedger

log = logging.getLogger(__name__)


class CoverImageFailed(RuntimeError):
    """Raised by the pipeline when no image can be sourced for the cover slide."""

# ------------------------------------------------------------------ #
# Provider trust tiers
# ------------------------------------------------------------------ #

PROVIDER_TRUST: dict[str, int] = {
    "wikimedia_commons": 30,
    "wikipedia":         30,
    "nasa":              25,
    "smithsonian":       20,
    "openverse":         15,
    "inaturalist":       12,
    "pixabay":           10,
    "pexels":             5,
}

MIN_SCORE: int = 20
MAX_REUSES:  int = 2   # same URL allowed at most this many times per carousel


# ------------------------------------------------------------------ #
# ImageIntent
# ------------------------------------------------------------------ #

@dataclass
class ImageIntent:
    """All Claude-resolved image fields in one place.

    Constructed via ImageIntent.from_dict(claude_json_data) in the pipeline.
    """
    visual_subject:        str
    subject_type:          str
    fallback_query:        str
    source_aliases:        list[str]
    context_words:         list[str]
    negative_terms:        list[str]
    preferred_image_types: list[str]
    avoid_image_types:     list[str]

    @classmethod
    def from_dict(cls, data: dict) -> "ImageIntent":
        return cls(
            visual_subject        = str(data.get("visual_subject", "")),
            subject_type          = str(data.get("subject_type", "")),
            fallback_query        = str(data.get("fallback_query", "")),
            source_aliases        = list(data.get("source_aliases", []))[:8],
            context_words         = list(data.get("context_words", []))[:8],
            negative_terms        = list(data.get("negative_terms", []))[:12],
            preferred_image_types = list(data.get("preferred_image_types", []))[:8],
            avoid_image_types     = list(data.get("avoid_image_types", []))[:8],
        )

    @classmethod
    def news_intent(cls) -> "ImageIntent":
        """Minimal intent for the news pipeline. No aliases, no scoring dimensions."""
        return cls(
            visual_subject="", subject_type="", fallback_query="",
            source_aliases=[], context_words=[], negative_terms=[],
            preferred_image_types=[], avoid_image_types=[],
        )


# ------------------------------------------------------------------ #
# Scoring
# ------------------------------------------------------------------ #

def score_candidate(
    cand: "PoolCandidate",
    intent: ImageIntent,
    use_count_by_url: dict[str, int],
    last_used_url: str,
    last_used_meta: str,
) -> tuple[int, list[str]]:
    """Score one pool candidate. Returns (score, reasons).

    Candidates with URL == last_used_url or use_count >= MAX_REUSES must be
    filtered out by the caller BEFORE calling this function.
    """
    score: int = 0
    reasons: list[str] = []
    meta   = cand.meta.lower()
    reason = cand.allow_reason

    # --- Alias match strength ---
    if "multi-word" in reason:
        score += 30
        reasons.append("alias:multi-word(+30)")
    elif "archive-trusted" in reason or "nasa_trusted_no_meta" in reason:
        score += 22
        reasons.append("alias:archive-trusted(+22)")
    elif "context=" in reason:
        score += 20
        reasons.append("alias:single+context(+20)")
    elif "alias=" in reason:
        score += 10
        reasons.append("alias:single-only(+10)")

    # --- Provider trust ---
    trust = PROVIDER_TRUST.get(cand.provider, 5)
    score += trust
    reasons.append(f"provider:{cand.provider}(+{trust})")

    # --- Preferred image type match (+15, once) ---
    for ptype in intent.preferred_image_types:
        if ptype.lower() in meta:
            score += 15
            reasons.append(f"preferred:{ptype!r}(+15)")
            break

    # --- Avoid image type penalty (−25, once) ---
    for atype in intent.avoid_image_types:
        if atype.lower() in meta:
            score -= 25
            reasons.append(f"avoid:{atype!r}(-25)")
            break

    # --- Resolution bonus ---
    if cand.width >= 2000:
        score += 10
        reasons.append("res:2000+(+10)")
    elif cand.width >= 1280:
        score += 5
        reasons.append("res:1280+(+5)")

    # --- Already-used-once penalty ---
    count = use_count_by_url.get(cand.url, 0)
    if count == 1:
        score -= 60
        reasons.append("already-used-once(-60)")

    # --- Near-duplicate meta penalty (≥4 shared words with last selected) ---
    if last_used_meta:
        last_words = set(last_used_meta.lower().split())
        cand_words = set(meta.split())
        shared = len(last_words & cand_words)
        if shared >= 4:
            score -= 30
            reasons.append(f"near-dup({shared}words)(-30)")

    return score, reasons


# ------------------------------------------------------------------ #
# ImageSourcer
# ------------------------------------------------------------------ #

class ImageSourcer:
    """Orchestrate per-slot pool collection, scoring, and selection.

    One instance per carousel run. Tracks which images have been used and
    prevents consecutive duplicates and over-reuse.
    """

    MAX_POOL: int = 40   # manual posts; override for news

    def __init__(
        self,
        topic: str = "editorial",
        use_fresh_ledger: bool = True,
    ) -> None:
        self.topic = topic
        if use_fresh_ledger:
            tmp = tempfile.mktemp(suffix="_sourcer_images.jsonl")
            ledger = UsedImageLedger(path=tmp)
        else:
            ledger = UsedImageLedger()
        self._fetcher = ImageFetcher(ledger=ledger)

        # Per-run tracking
        self._use_count:     dict[str, int]        = {}
        self._last_url:      str                   = ""
        self._last_meta:     str                   = ""
        self._good_images:   list[tuple[str, str]] = []  # (data_url, source_url)

    def source_images(
        self,
        queries:  list[str],
        intent:   ImageIntent,
        post_id:  str,
        max_pool: int | None = None,
    ) -> list[str]:
        """Return one base64 data URL per query slot.

        Empty string = typography-only slide.
        """

        pool_size = max_pool if max_pool is not None else self.MAX_POOL
        extra_fallbacks = [q for q in [intent.fallback_query, intent.visual_subject] if q]

        data_urls: list[str] = []

        for i, query in enumerate(queries):
            log.debug("IMAGE slot=%d query=%r", i, query)

            raw_pool = self._fetcher.fetch_pool(
                query          = query,
                topic          = self.topic,
                post_id        = post_id,
                slide_index    = i,
                intent_text    = intent.fallback_query or query,
                source_aliases = intent.source_aliases or None,
                negative_terms = intent.negative_terms or None,
                context_words  = intent.context_words  or None,
                extra_fallbacks= extra_fallbacks,
                max_pool       = pool_size,
            )

            log.debug("IMAGE slot=%d pool_size=%d", i, len(raw_pool))

            chosen = self._select_for_slot(i, query, raw_pool, intent, post_id)

            # Typography breaks the consecutive chain — the same image may
            # appear again on the next slot without being flagged consecutive.
            if not chosen:
                self._last_url = ""

            data_urls.append(chosen)

        return data_urls

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _select_for_slot(
        self,
        slot: int,
        query: str,
        raw_pool: list,
        intent: ImageIntent,
        post_id: str,
    ) -> str:
        """Run the full selection pipeline for one slot. Returns data URL or "".

        Flow:
          [A] Hard filter (code): drop overused / consecutive candidates.
          [B] Score all eligible candidates (deterministic).
          [C] Haiku picks from the scored pool (judgement layer).
          [D] Code enforces hard rules on each Haiku pick (safety layer).
          [E] Deterministic fallback if all Haiku picks fail.
          [F] _pick_reuse() or "" (typography-only).
        """
        if not raw_pool:
            chosen = self._pick_reuse()
            log.debug("IMAGE slot=%d EMPTY_POOL → %s", slot, "reuse" if chosen else "typography")
            return chosen

        # [A] Hard filter: overused or consecutive
        eligible = [
            c for c in raw_pool
            if self._use_count.get(c.url, 0) < MAX_REUSES and c.url != self._last_url
        ]
        log.debug("IMAGE slot=%d eligible_after_filter=%d", slot, len(eligible))

        if not eligible:
            chosen = self._pick_reuse()
            log.debug("IMAGE slot=%d all_hard_rejected → %s", slot, "reuse" if chosen else "typography")
            return chosen

        # [B] Score all eligible candidates, sorted best-first
        scored = sorted(
            [
                (score_candidate(c, intent, self._use_count, self._last_url, self._last_meta), c)
                for c in eligible
            ],
            key=lambda x: x[0][0],
            reverse=True,
        )

        for rank, ((sc, reasons), c) in enumerate(scored[:5], 1):
            log.debug(
                "IMAGE slot=%d #%d score=%3d [%s] %s | %s",
                slot, rank, sc, c.provider, " ".join(reasons), c.meta[:60],
            )
        if len(scored) > 5:
            log.debug("IMAGE slot=%d ... %d more not shown", slot, len(scored) - 5)

        # [C] Haiku selection
        cover_slot = (slot == 0)
        haiku_order: list[int] = []
        haiku_expressed_preference = False  # True when Haiku returned a valid pick list
        confidence = "low"

        if len(scored) >= 2:
            best_idx, backup_idxs, confidence = self._haiku_select(
                slot=slot,
                slide_query=query,
                visual_subject=intent.visual_subject,
                cover_slot=cover_slot,
                scored=scored,
            )
            if best_idx is not None:
                haiku_order = [best_idx] + [b for b in backup_idxs if b != best_idx]
                haiku_expressed_preference = True
        elif len(scored) == 1:
            haiku_order = [0]
            confidence = "medium"
            log.debug("IMAGE slot=%d single_candidate → using without Haiku call", slot)

        # Candidates Haiku did NOT pick: deterministic fallback should respect this.
        # If Haiku was called and expressed a preference, exclude everything it omitted.
        haiku_approved = set(haiku_order) if haiku_expressed_preference else set(range(len(scored)))

        # [D] Try each Haiku pick with safety re-checks
        for pick_idx in haiku_order:
            if pick_idx >= len(scored):
                log.warning("IMAGE slot=%d haiku_pick=%d out of range (pool=%d)", slot, pick_idx, len(scored))
                continue
            (sc, _), c = scored[pick_idx]

            # Safety re-check (guards against race conditions)
            if self._use_count.get(c.url, 0) >= MAX_REUSES:
                log.debug("IMAGE slot=%d haiku_pick=%d overused → skip", slot, pick_idx)
                continue
            if c.url == self._last_url:
                log.debug("IMAGE slot=%d haiku_pick=%d consecutive → skip", slot, pick_idx)
                continue

            # MIN_SCORE is a warning when Haiku is confident; a block otherwise
            if sc < MIN_SCORE and confidence != "high":
                log.debug(
                    "IMAGE slot=%d haiku_pick=%d score=%d < MIN_SCORE confidence=%s → skip",
                    slot, pick_idx, sc, confidence,
                )
                continue

            try:
                cached, credit = self._fetcher.commit_candidate(c, query, self.topic, post_id, slot)
                data_url = f"data:image/jpeg;base64,{base64.b64encode(cached.read_bytes()).decode()}"
                self._commit(c.url, c.meta, data_url)
                log.debug(
                    "IMAGE slot=%d HAIKU pick=%d [%s] score=%d confidence=%s %s",
                    slot, pick_idx, credit["provider"], sc, confidence, credit["reason"],
                )
                return data_url
            except Exception as exc:
                log.warning("IMAGE slot=%d haiku_pick=%d commit_failed: %s", slot, pick_idx, exc)
                continue

        # [E] Deterministic fallback: best eligible candidate at or above MIN_SCORE.
        # Respects Haiku's implicit rejections: if Haiku was called and didn't include
        # a candidate in its pick list, skip it here too. This prevents the fallback
        # from selecting an image Haiku deliberately avoided (e.g. a Paris metro station
        # when searching for a Concorde aircraft).
        log.debug("IMAGE slot=%d all_haiku_picks_failed → deterministic_fallback", slot)
        for i_det, ((sc, _), c) in enumerate(scored):
            if i_det not in haiku_approved:
                log.debug("IMAGE slot=%d det_skip=%d haiku_excluded", slot, i_det)
                continue
            if self._use_count.get(c.url, 0) >= MAX_REUSES or c.url == self._last_url:
                continue
            if sc < MIN_SCORE:
                break  # sorted descending; nothing below will qualify
            try:
                cached, credit = self._fetcher.commit_candidate(c, query, self.topic, post_id, slot)
                data_url = f"data:image/jpeg;base64,{base64.b64encode(cached.read_bytes()).decode()}"
                self._commit(c.url, c.meta, data_url)
                log.debug(
                    "IMAGE slot=%d DETERMINISTIC [%s] score=%d %s",
                    slot, credit["provider"], sc, credit["reason"],
                )
                return data_url
            except Exception as exc:
                log.warning("IMAGE slot=%d deterministic commit_failed: %s", slot, exc)

        # [F] Last resort: reuse an earlier committed image, or typography-only
        chosen = self._pick_reuse()
        log.debug("IMAGE slot=%d ALL_FAILED → %s", slot, "reuse" if chosen else "typography")
        return chosen

    def _commit(self, url: str, meta: str, data_url: str) -> None:
        self._use_count[url] = self._use_count.get(url, 0) + 1
        self._last_url  = url
        self._last_meta = meta
        self._good_images.append((data_url, url))

    # ------------------------------------------------------------------ #
    # Haiku selection
    # ------------------------------------------------------------------ #

    _HAIKU_MAX_CANDIDATES = 20  # send at most this many to Haiku

    def _haiku_select(
        self,
        slot: int,
        slide_query: str,
        visual_subject: str,
        cover_slot: bool,
        scored: "list[tuple[tuple[int, list[str]], PoolCandidate]]",
    ) -> "tuple[int | None, list[int], str]":
        """Call Haiku to pick the best candidate by metadata. Returns (best_idx, backup_idxs, confidence).

        Haiku receives integer IDs only -- no URLs, no image bytes.
        Returned IDs are indices into the scored list passed in.
        Falls back gracefully (returns None, [], "low") on any error.
        """
        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            log.debug("IMAGE haiku_select slot=%d: ANTHROPIC_API_KEY not set, skipping", slot)
            return None, [], "low"

        try:
            from anthropic import Anthropic
        except ImportError:
            log.debug("IMAGE haiku_select slot=%d: anthropic package not available", slot)
            return None, [], "low"

        # Cap candidate list to keep payload small. Already sorted desc by score.
        capped = scored[: self._HAIKU_MAX_CANDIDATES]
        candidates_payload = [
            {
                "id":       i,
                "provider": c.provider,
                "meta":     c.meta[:120],
                "score":    sc,
                "width":    c.width,
                "height":   c.height,
            }
            for i, ((sc, _), c) in enumerate(capped)
        ]

        system = (
            "You are selecting images for an Instagram carousel. "
            "Pick the most visually strong, relevant, and documentary candidates by metadata only. "
            "Prefer authentic photos over diagrams, maps, or crowd shots. Prefer higher resolution. "
            "Never invent IDs. Return only valid IDs from the provided list."
        )
        user = (
            f"Select images for this carousel slot.\n\n"
            f"Slide query: {slide_query}\n"
            f"Visual subject: {visual_subject}\n"
            f"Is cover slide: {cover_slot}\n\n"
            f"Candidates (id 0 to {len(candidates_payload) - 1}):\n"
            f"{json.dumps(candidates_payload, indent=2)}\n\n"
            f"Return JSON only: "
            f'{{\"best\": <id>, \"backups\": [<id>, <id>], \"confidence\": \"high|medium|low\"}}'
        )

        try:
            client = Anthropic(api_key=api_key)
            res = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=80,
                temperature=0.0,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            raw = res.content[0].text.strip()
            m = re.search(r"\{[\s\S]*\}", raw)
            if not m:
                log.warning("IMAGE haiku_select slot=%d: no JSON in response: %r", slot, raw[:80])
                return None, [], "low"
            data = json.loads(m.group(0))
            best = data.get("best")
            backups = data.get("backups", [])
            confidence = str(data.get("confidence", "low")).lower()
            if confidence not in ("high", "medium", "low"):
                confidence = "low"

            # Validate: all IDs must be integers in range
            valid = set(range(len(capped)))
            if not isinstance(best, int) or best not in valid:
                log.warning("IMAGE haiku_select slot=%d: invalid best=%r", slot, best)
                best = None
            backups = [b for b in backups if isinstance(b, int) and b in valid]

            log.debug(
                "IMAGE haiku_select slot=%d best=%s backups=%s confidence=%s",
                slot, best, backups, confidence,
            )
            return best, backups, confidence

        except Exception as exc:
            log.warning("IMAGE haiku_select slot=%d failed: %s", slot, exc)
            return None, [], "low"

    def _pick_reuse(self) -> str:
        """Return data URL of the best reusable image, or "" for typography slide.

        Rules:
        - use_count < MAX_REUSES
        - URL != last_used_url (no consecutive duplicate)
        - Prefer images used fewest times (most head-room remaining)
        """
        candidates = [
            (self._use_count.get(src_url, 0), data_url, src_url)
            for data_url, src_url in self._good_images
            if self._use_count.get(src_url, 0) < MAX_REUSES
            and src_url != self._last_url
        ]
        if not candidates:
            log.debug("IMAGE REUSE_FAILED → typography")
            return ""
        # Pick image with fewest existing uses (most capacity remaining)
        candidates.sort(key=lambda x: x[0])
        count, data_url, src_url = candidates[0]
        # Reuse does not call commit_candidate (no ledger mark) but we track counts
        self._use_count[src_url] = count + 1
        self._last_url  = src_url
        # Don't update _last_meta — reused image keeps the meta of its original commit
        log.debug("IMAGE REUSE url=%s use_count=%d", src_url[:60], count + 1)
        return data_url
