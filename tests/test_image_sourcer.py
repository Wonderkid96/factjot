"""Unit tests for src/research/image_sourcer.py

All tests use mocks — no real HTTP calls.
Run: python -m pytest tests/test_image_sourcer.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.research.image_fetcher import _alias_matches
from src.research.image_sourcer import (
    ImageIntent,
    ImageSourcer,
    MAX_REUSES,
    MIN_SCORE,
    PROVIDER_TRUST,
    score_candidate,
)


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _make_candidate(
    provider="wikimedia_commons",
    url="http://example.com/img.jpg",
    meta="concorde aircraft supersonic british airways",
    allow_reason="alias='British Airways Concorde' (multi-word)",
    width=2048,
):
    cand = MagicMock()
    cand.provider     = provider
    cand.url          = url
    cand.meta         = meta
    cand.allow_reason = allow_reason
    cand.width        = width
    cand.content      = b"fake"
    cand.img          = MagicMock()
    cand.credit_name  = "Test"
    cand.credit_url   = url
    return cand


def _aviation_intent(**overrides):
    base = dict(
        visual_subject        = "Concorde supersonic passenger airliner",
        subject_type          = "historical aircraft",
        fallback_query        = "Concorde aircraft",
        source_aliases        = ["British Airways Concorde", "Air France Concorde", "Concorde aircraft"],
        context_words         = ["aircraft", "aviation", "supersonic"],
        negative_terms        = ["paris", "obelisk", "fountain"],
        preferred_image_types = ["takeoff", "cockpit", "landing"],
        avoid_image_types     = ["diagram", "map"],
    )
    base.update(overrides)
    return ImageIntent(**base)


def _make_sourcer(good_images=None, use_count=None, last_url="", last_meta=""):
    """Construct an ImageSourcer with pre-seeded internal state (no HTTP)."""
    with patch("src.research.image_fetcher.ImageFetcher"), \
         patch("src.research.image_fetcher.UsedImageLedger"):
        sourcer = ImageSourcer.__new__(ImageSourcer)
        sourcer.topic        = "editorial"
        sourcer.MAX_POOL     = 40
        sourcer._fetcher     = MagicMock()
    sourcer._use_count   = dict(use_count or {})
    sourcer._last_url    = last_url
    sourcer._last_meta   = last_meta
    sourcer._good_images = list(good_images or [])
    return sourcer


# ------------------------------------------------------------------ #
# Test 1: multi-word alias scores correctly
# ------------------------------------------------------------------ #

def test_score_multi_word_alias_commons_preferred_type():
    cand = _make_candidate(
        provider="wikimedia_commons",
        meta="concorde aircraft supersonic takeoff british airways",
        allow_reason="alias='British Airways Concorde' (multi-word)",
        width=2048,
    )
    intent = _aviation_intent()
    sc, reasons = score_candidate(cand, intent, {}, last_used_url="", last_used_meta="")

    # +30 (multi-word) +30 (commons) +15 (takeoff pref) +10 (res 2000+)
    assert sc == 85, f"expected 85, got {sc} reasons={reasons}"
    assert "alias:multi-word(+30)" in reasons
    assert "provider:wikimedia_commons(+30)" in reasons
    assert "preferred:'takeoff'(+15)" in reasons
    assert "res:2000+(+10)" in reasons


# ------------------------------------------------------------------ #
# Test 2: weak candidate below MIN_SCORE → source_images returns ""
# ------------------------------------------------------------------ #

def test_weak_candidate_returns_empty_string():
    cand = _make_candidate(
        provider="pexels",
        meta="concorde aviation",
        allow_reason="alias='Concorde' (single-word)",
        width=640,
    )
    intent = _aviation_intent()
    sc, _ = score_candidate(cand, intent, {}, last_used_url="", last_used_meta="")
    # +10 (single-word) +5 (pexels) = 15, below MIN_SCORE=20
    assert sc < MIN_SCORE

    sourcer = _make_sourcer()
    sourcer._fetcher.fetch_pool = MagicMock(return_value=[cand])
    sourcer._fetcher.commit_candidate = MagicMock()

    result = sourcer.source_images(["Concorde takeoff"], intent, "test-post")
    assert result == [""], f"expected [''], got {result}"
    sourcer._fetcher.commit_candidate.assert_not_called()


# ------------------------------------------------------------------ #
# Test 3: one good image cannot fill many slides - consecutive + reuse limits
# ------------------------------------------------------------------ #

def test_one_image_cannot_fill_many_slides():
    url_a = "http://example.com/a.jpg"
    intent = _aviation_intent()

    # High-scoring candidate, always returns URL A
    cand_a = _make_candidate(url=url_a)
    cand_a.allow_reason = "alias='Concorde aircraft' (multi-word)"

    saved_path = MagicMock()
    saved_path.read_bytes = MagicMock(return_value=b"\xff\xd8data")

    sourcer = _make_sourcer()
    sourcer._fetcher.fetch_pool = MagicMock(return_value=[cand_a])
    sourcer._fetcher.commit_candidate = MagicMock(
        return_value=(saved_path, {"provider": "wikimedia_commons", "reason": "test"})
    )

    result = sourcer.source_images(
        ["q0", "q1", "q2", "q3"], intent, "test-post"
    )

    # slot 0: commits URL A (use_count 1, last=A)
    # slot 1: URL A is last_used → hard reject → reuse. But no prior good_images except A,
    #         and A == last_used → _pick_reuse returns "" → typography
    # slot 2: URL A is not consecutive, use_count=1 < 2 → commits A (use_count 2, last=A)
    # slot 3: URL A is last_used → hard reject → _pick_reuse finds A but A==last_used → ""
    assert result[0] != "", "slot 0 should be an image"
    assert result[1] == "",  "slot 1 should be typography (consecutive with slot 0)"
    assert result[2] != "", "slot 2 should reuse URL A (not consecutive now)"
    assert result[3] == "",  "slot 3 should be typography (consecutive again)"

    # URL A used exactly twice
    assert sourcer._use_count.get(url_a, 0) == 2


# ------------------------------------------------------------------ #
# Test 4: no consecutive duplicate from pool
# ------------------------------------------------------------------ #

def test_no_consecutive_duplicate_from_pool():
    url_a = "http://example.com/a.jpg"
    cand_a = _make_candidate(url=url_a, allow_reason="alias='Concorde aircraft' (multi-word)")
    intent = _aviation_intent()

    sourcer = _make_sourcer(
        good_images=[("data:image/jpeg;base64,xxx", url_a)],
        use_count={url_a: 1},
        last_url=url_a,
    )
    sourcer._fetcher.fetch_pool = MagicMock(return_value=[cand_a])
    sourcer._fetcher.commit_candidate = MagicMock()

    result = sourcer.source_images(["Concorde takeoff"], intent, "test-post")
    # URL A is consecutive (last_url == url_a) — hard rejected from pool
    # Reuse: only image is A but A == last_url → typography
    assert result == [""], f"expected [''], got {result}"
    sourcer._fetcher.commit_candidate.assert_not_called()


# ------------------------------------------------------------------ #
# Test 5: lower-scored unused image beats already-used duplicate
# ------------------------------------------------------------------ #

def test_lower_scored_unused_beats_already_used():
    url_a = "http://example.com/a.jpg"
    url_b = "http://example.com/b.jpg"

    cand_a = _make_candidate(
        url=url_a,
        provider="wikimedia_commons",
        allow_reason="alias='British Airways Concorde' (multi-word)",
        width=2048,
    )
    cand_b = _make_candidate(
        url=url_b,
        provider="pixabay",
        allow_reason="alias='Concorde aircraft' (multi-word)",
        width=1280,
        meta="concorde aircraft aviation pixabay",
    )

    intent = _aviation_intent()

    # Baseline scores (no use_count penalty):
    sc_a_base, _ = score_candidate(cand_a, intent, {}, "", "")
    sc_b_base, _ = score_candidate(cand_b, intent, {}, "", "")
    assert sc_a_base > sc_b_base, "URL A should score higher fresh"

    # Now URL A has been used once — apply penalty
    sc_a_penalised, _ = score_candidate(cand_a, intent, {url_a: 1}, "", "")
    assert sc_a_penalised < sc_b_base, (
        f"URL A with -60 penalty ({sc_a_penalised}) should score below URL B ({sc_b_base})"
    )


# ------------------------------------------------------------------ #
# Test 6: use_count >= MAX_REUSES hard-rejected from pool
# ------------------------------------------------------------------ #

def test_overused_url_hard_rejected():
    url_a = "http://example.com/a.jpg"
    cand_a = _make_candidate(url=url_a, allow_reason="alias='Concorde aircraft' (multi-word)")
    intent = _aviation_intent()

    # URL A already used MAX_REUSES times
    sourcer = _make_sourcer(
        use_count={url_a: MAX_REUSES},
        last_url="",   # not last_used, so only the count blocks it
    )
    sourcer._fetcher.fetch_pool = MagicMock(return_value=[cand_a])
    sourcer._fetcher.commit_candidate = MagicMock()

    result = sourcer.source_images(["Concorde takeoff"], intent, "test-post")
    assert result == [""], "over-used URL should be hard rejected → typography"
    sourcer._fetcher.commit_candidate.assert_not_called()


# ------------------------------------------------------------------ #
# Test 7: near-duplicate meta penalty
# ------------------------------------------------------------------ #

def test_near_duplicate_meta_penalty():
    intent = _aviation_intent()
    last_meta = "concorde aircraft aviation supersonic british"

    cand = _make_candidate(
        provider="pixabay",
        meta="concorde aircraft aviation supersonic flying",  # 4 shared words
        allow_reason="alias='Concorde aircraft' (multi-word)",
        width=1280,
    )

    sc_without, _ = score_candidate(cand, intent, {}, last_used_url="", last_used_meta="")
    sc_with,    _ = score_candidate(cand, intent, {}, last_used_url="", last_used_meta=last_meta)

    assert sc_with == sc_without - 30, (
        f"near-dup penalty should be -30: {sc_without} → {sc_with}"
    )


# ------------------------------------------------------------------ #
# Test 8: news_intent passes with no aliases, no crash
# ------------------------------------------------------------------ #

def test_news_intent_no_alias_no_crash():
    intent = ImageIntent.news_intent()
    assert intent.source_aliases == []
    assert intent.negative_terms == []

    # Use width=0 so resolution bonus does not interfere with the assertion
    cand_commons = _make_candidate(
        provider="wikimedia_commons", url="http://ex.com/a.jpg",
        allow_reason="pass_intent_terms", width=0,
    )
    cand_pixabay = _make_candidate(
        provider="pixabay", url="http://ex.com/b.jpg",
        allow_reason="pass_intent_terms", width=0,
    )

    sc_commons, _ = score_candidate(cand_commons, intent, {}, "", "")
    sc_pixabay, _ = score_candidate(cand_pixabay, intent, {}, "", "")

    # No alias bonus — scored on provider trust only
    assert sc_commons == PROVIDER_TRUST["wikimedia_commons"]
    assert sc_pixabay  == PROVIDER_TRUST["pixabay"]
    assert sc_commons  > sc_pixabay


# ------------------------------------------------------------------ #
# Test 9: _alias_matches — token-boundary matching (Phase 7 fix)
# ------------------------------------------------------------------ #

def test_alias_matches_rejects_substring():
    """'Concord' must not match 'Concorde' via substring."""
    assert _alias_matches("Concord", "concorde") is False
    assert _alias_matches("Concord", "british airways concorde") is False
    assert _alias_matches("Concord", "place de la concorde") is False
    assert _alias_matches("Concord", "concordance") is False


def test_alias_matches_accepts_whole_token():
    """'Concord' must match when it appears as a complete token."""
    assert _alias_matches("Concord", "concord grape concordgrapes2.jpg") is True
    assert _alias_matches("Concord", "concord, massachusetts") is True
    assert _alias_matches("Concord", "concord-massachusetts") is True
    assert _alias_matches("Concord", "file:concord_ma.jpg") is True
    assert _alias_matches("Concord", "concord") is True


def test_alias_matches_multi_word_any_order():
    """Multi-word aliases match words in any order, still token-bounded."""
    assert _alias_matches("Concord Massachusetts", "concord, massachusetts central part") is True
    assert _alias_matches("Concord Massachusetts", "massachusetts concord town") is True
    assert _alias_matches("Concord Massachusetts", "concorde g-boag.jpg") is False
    assert _alias_matches("Concord grape", "concord grape concordgrapes2.jpg") is True


def test_r3_fallback_runs_after_non_empty_pool_selection_failure():
    intent = _aviation_intent()
    cand_r1 = _make_candidate(
        provider="wikimedia_commons",
        url="http://example.com/r1.jpg",
        meta="concorde aircraft archive shot",
        allow_reason="alias='Concorde aircraft' (multi-word)",
    )
    cand_r3 = _make_candidate(
        provider="pexels",
        url="http://example.com/r3.jpg",
        meta="aircraft cockpit controls close up",
        allow_reason="pass_intent_terms",
    )
    sourcer = _make_sourcer()
    sourcer._fetcher.fetch_pool = MagicMock(side_effect=[[cand_r1], [cand_r3]])
    sourcer._select_for_slot = MagicMock(side_effect=["", "data:image/jpeg;base64,recovered"])

    result = sourcer.source_images(
        queries=["Takata airbag recall"],
        intent=intent,
        post_id="test-post",
        visual_fallback_queries=["car airbag close up"],
    )

    assert result == ["data:image/jpeg;base64,recovered"]
    assert sourcer._fetcher.fetch_pool.call_count == 2
    assert sourcer._fetcher.fetch_pool.call_args_list[1].kwargs["query"] == "car airbag close up"
    assert sourcer._fetcher.fetch_pool.call_args_list[1].kwargs["provider_override"] == (
        "pexels", "pixabay", "smithsonian", "commons",
    )
    assert sourcer._select_for_slot.call_count == 2


def test_r3_fallback_still_allows_typography_when_no_candidate_commits():
    intent = _aviation_intent()
    cand_r1 = _make_candidate(
        provider="wikimedia_commons",
        url="http://example.com/r1.jpg",
        meta="concorde aircraft archive shot",
        allow_reason="alias='Concorde aircraft' (multi-word)",
    )
    cand_r3 = _make_candidate(
        provider="pexels",
        url="http://example.com/r3.jpg",
        meta="aircraft cockpit controls close up",
        allow_reason="pass_intent_terms",
    )
    sourcer = _make_sourcer()
    sourcer._fetcher.fetch_pool = MagicMock(side_effect=[[cand_r1], [cand_r3]])
    sourcer._select_for_slot = MagicMock(side_effect=["", ""])

    result = sourcer.source_images(
        queries=["Takata airbag recall"],
        intent=intent,
        post_id="test-post",
        visual_fallback_queries=["car airbag close up"],
    )

    assert result == [""]
    assert sourcer._fetcher.fetch_pool.call_count == 2
    assert sourcer._select_for_slot.call_count == 2


def test_scene_slot_drops_global_alias_gate():
    intent = _aviation_intent()
    sourcer = _make_sourcer()
    sourcer._fetcher.fetch_pool = MagicMock(return_value=[])
    sourcer._select_for_slot = MagicMock(return_value="")

    sourcer.source_images(
        queries=["smartphone chat app"],
        intent=intent,
        post_id="test-post",
        per_slot_aliases=[None],
        per_slot_text=["person looking at phone screen"],
        visual_fallback_queries=["phone chat screen close up"],
    )

    first_call = sourcer._fetcher.fetch_pool.call_args_list[0]
    assert first_call.kwargs["source_aliases"] is None


def test_rescue_list_cover_rebuilds_decision_row_for_slot_zero():
    intent = _aviation_intent()
    sourcer = _make_sourcer()
    sourcer.relax = True
    sourcer.last_run_decisions = [
        {"slot": 0, "outcome": "typography", "query": "old"},
        {"slot": 1, "outcome": "haiku_pick", "query": "slide1"},
    ]
    cand = _make_candidate()
    sourcer._fetcher.fetch_pool = MagicMock(return_value=[cand])

    def _fake_select(slot, query, raw_pool, intent, post_id, relaxation_round=1):
        sourcer.last_run_decisions.append(
            {
                "slot": 0,
                "outcome": "haiku_pick",
                "query": query,
                "chosen_meta": cand.meta,
            }
        )
        return "data:image/jpeg;base64,abc"

    sourcer._select_for_slot = MagicMock(side_effect=_fake_select)
    out = sourcer.rescue_list_cover(
        rescue_queries=["cinema audience silhouette"],
        intent=intent,
        post_id="test-rescue",
        total_slides=2,
        smoke_mode=False,
    )
    assert out.startswith("data:image")
    assert len(sourcer.last_run_decisions) == 2
    assert sourcer.last_run_decisions[0]["outcome"] == "haiku_pick"
    assert sourcer.last_run_decisions[0]["query"] == "cinema audience silhouette"
    assert sourcer.last_run_decisions[1]["slot"] == 1


def test_rescue_list_cover_rolls_back_after_failed_select():
    intent = _aviation_intent()
    sourcer = _make_sourcer()
    sourcer.relax = True
    sourcer.last_run_decisions = [
        {"slot": 0, "outcome": "typography"},
        {"slot": 1, "outcome": "haiku_pick"},
    ]
    cand = _make_candidate()
    sourcer._fetcher.fetch_pool = MagicMock(return_value=[cand])

    def _fake_select_fail(*_a, **_k):
        sourcer.last_run_decisions.append({"slot": 0, "outcome": "typography"})
        return ""

    sourcer._select_for_slot = MagicMock(side_effect=_fake_select_fail)
    out = sourcer.rescue_list_cover(
        rescue_queries=["one query"],
        intent=intent,
        post_id="pid",
        total_slides=2,
        smoke_mode=False,
    )
    assert out == ""
    assert sourcer.last_run_decisions == [
        {"slot": 0, "outcome": "typography"},
        {"slot": 1, "outcome": "haiku_pick"},
    ]
