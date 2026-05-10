"""Phase D.2 list format rule tests.

The hybrid Q10 decision: every list MUST state ONE specific defensible
criterion on the cover ("Five engineering disasters by death toll"),
opinion superlatives ("scariest", "most iconic") are banned, and the
closing slide must cite the criterion source.

Covered:

- The story-scout pool no longer carries banned opinion superlatives
  (scariest / most underrated / strangest / etc.) but still carries the
  numeric / defensible ones (biggest / oldest / fastest / deadliest /
  longest).
- `build_list_reel_possibilities` always emits a non-empty `criterion`
  field on every candidate it returns.
- `_validate_list_criterion` accepts a "by [criterion]" or "that
  [verifiable condition]" cover paired with a closing that cites a
  source, and rejects bare-superlative covers, missing source citations,
  and missing / empty closing blocks.
"""
from __future__ import annotations

from unittest.mock import patch

from pipelines.manual.ship_manual_post import _validate_list_criterion
from src.research import story_scout
from src.research.story_scout import (
    BANNED_LIST_SUPERLATIVES,
    CRITERION_SHAPES,
    LIST_SUPERLATIVE_POOL,
    build_list_reel_possibilities,
)


# ---------------------------------------------------------------- #
# Pool composition: opinion superlatives stripped, numerics kept
# ---------------------------------------------------------------- #


def test_list_pool_drops_banned_opinion_superlatives():
    """Phase D.2 banned every opinion / aesthetic superlative."""
    banned = (
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
    )
    for term in banned:
        assert term not in LIST_SUPERLATIVE_POOL, (
            f"banned superlative {term!r} still present in pool"
        )
        assert term in BANNED_LIST_SUPERLATIVES, (
            f"banned superlative {term!r} missing from BANNED_LIST_SUPERLATIVES"
        )


def test_list_pool_keeps_numeric_defensible_superlatives():
    """The five anchor numeric superlatives must still be available."""
    for term in ("biggest", "oldest", "fastest", "deadliest", "longest"):
        assert term in LIST_SUPERLATIVE_POOL, (
            f"numeric superlative {term!r} missing from pool"
        )
        assert term in CRITERION_SHAPES, (
            f"numeric superlative {term!r} missing from CRITERION_SHAPES"
        )


# ---------------------------------------------------------------- #
# build_list_reel_possibilities: criterion field is mandatory
# ---------------------------------------------------------------- #


def test_build_list_reel_possibilities_emits_criterion_per_candidate():
    """Every candidate must carry a non-empty criterion string."""
    fake_candidates = [
        {
            "topic": "history",
            "title": (
                "1919 Boston had a giant molasses flood through city streets"
            ),
            "weird_bit": "molasses flood killed 21 people",
        },
        {
            "topic": "earth",
            "title": "Krakatoa eruption heard 3,000 miles away in 1883",
            "weird_bit": "loudest sound in recorded history",
        },
        {
            "topic": "technology",
            "title": "Mariner 1 lost to a missing hyphen in flight code",
            "weird_bit": "$80 million rocket destroyed by punctuation",
        },
    ]

    with patch.object(
        story_scout, "ranked_candidates_for_mode", return_value=fake_candidates,
    ):
        out = build_list_reel_possibilities("list_midday")

    assert out, "expected at least one candidate from the fake pool"
    for cand in out:
        criterion = cand.get("criterion", "")
        assert isinstance(criterion, str) and criterion.strip(), (
            f"candidate missing criterion: {cand!r}"
        )
        # The criterion should look like a real measurable axis.
        # All shipped CRITERION_SHAPES entries start with "by".
        assert criterion.startswith("by "), (
            f"candidate criterion looks malformed: {criterion!r}"
        )


# ---------------------------------------------------------------- #
# _validate_list_criterion: accept the good shape
# ---------------------------------------------------------------- #


def test_validate_list_criterion_accepts_by_criterion_with_source():
    data = {
        "cover_title": "Five engineering disasters by death toll",
        "closing_headline": "Source: USGS",
    }
    ok, reason = _validate_list_criterion(data)
    assert ok is True, f"expected pass, got reason={reason!r}"
    assert reason == ""


def test_validate_list_criterion_accepts_year_criterion_with_source():
    """Cover with a 'by year' criterion plus a real source cite."""
    data = {
        "cover_title": "Five films by year of release",
        "closing": {
            "lines": [
                "Spanning over a century of cinema",
                "From silent films to digital",
                "Source: Box Office Mojo, domestic gross",
            ],
            "image_query": "vintage film reels archive",
        },
    }
    ok, reason = _validate_list_criterion(data)
    assert ok is True, f"expected pass, got reason={reason!r}"
    assert reason == ""


# ---------------------------------------------------------------- #
# _validate_list_criterion: reject bare superlatives + no source
# ---------------------------------------------------------------- #


def test_validate_list_criterion_rejects_bare_superlative_no_source():
    data = {
        "cover_title": "Five scariest films ever",
        "closing_headline": "Wow.",
    }
    ok, reason = _validate_list_criterion(data)
    assert ok is False
    assert "scariest" in reason.lower(), (
        f"expected reason to mention banned superlative, got {reason!r}"
    )


def test_validate_list_criterion_rejects_missing_source_citation():
    """Criterion present but closing has no source -> fail."""
    data = {
        "cover_title": "Five films by year of release",
        "closing": {
            "lines": [
                "Just our picks.",
                "Pure cinematic taste.",
                "Hope you enjoyed.",
            ],
            "image_query": "film reel",
        },
    }
    ok, reason = _validate_list_criterion(data)
    assert ok is False
    assert "source" in reason.lower(), (
        f"expected reason to mention source citation, got {reason!r}"
    )


# ---------------------------------------------------------------- #
# _validate_list_criterion: robustness to missing closing fields
# ---------------------------------------------------------------- #


def test_validate_list_criterion_handles_missing_closing_headline():
    """closing_headline absent AND closing block absent -> clear fail."""
    data = {
        "cover_title": "Five engineering disasters by death toll",
        # no closing or closing_headline at all
    }
    ok, reason = _validate_list_criterion(data)
    assert ok is False
    assert reason, "expected a non-empty reason"
    # The fail must cite the missing closing, not crash with a KeyError.
    assert "closing" in reason.lower(), (
        f"expected reason to mention closing, got {reason!r}"
    )


def test_validate_list_criterion_handles_empty_closing_headline():
    """closing_headline present but empty string -> clear fail."""
    data = {
        "cover_title": "Five engineering disasters by death toll",
        "closing_headline": "",
        "closing": {
            "lines": ["", "", ""],
            "image_query": "",
        },
    }
    ok, reason = _validate_list_criterion(data)
    assert ok is False
    assert reason, "expected a non-empty reason"


# ---------------------------------------------------------------- #
# Extra coverage: empty filler clauses
# ---------------------------------------------------------------- #


def test_validate_list_criterion_rejects_filler_by_clause():
    """'by far' is filler, not a real criterion."""
    data = {
        "cover_title": "Five disasters by far",
        "closing_headline": "Source: USGS",
    }
    ok, reason = _validate_list_criterion(data)
    assert ok is False
    assert reason


def test_validate_list_criterion_rejects_filler_that_clause():
    """'that are amazing' is filler, not a verifiable condition."""
    data = {
        "cover_title": "Five films that are amazing",
        "closing_headline": "Source: BFI",
    }
    ok, reason = _validate_list_criterion(data)
    assert ok is False
    assert reason


def test_validate_list_criterion_rejects_missing_clause_entirely():
    """No 'by' or 'that' clause -> fail."""
    data = {
        "cover_title": "Five amazing things",
        "closing_headline": "Source: nowhere",
    }
    ok, reason = _validate_list_criterion(data)
    assert ok is False
    assert "by" in reason.lower() or "that" in reason.lower()
