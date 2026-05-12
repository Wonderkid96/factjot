"""Tests for the shock scoring component of story_scout."""
from __future__ import annotations

from dataclasses import fields

import pytest

from src.research.story_scout import Candidate, _shock_score, _score_title


SHOCK_PAIRS = [
    (
        "47 soldiers survived despite orders to execute them",
        "A military event occurred last year",
        "number+survival+contradiction",
    ),
    (
        "World's only surviving Nazi submarine discovered in Norway",
        "A submarine was found in European waters",
        "scale superlative+outcome verb",
    ),
    (
        "In 1962 Vasili Arkhipov single-handedly prevented nuclear war",
        "A Soviet officer made an important decision",
        "year+proper noun+shocking outcome",
    ),
    (
        "Scientists executed the last known specimen of a species accidentally",
        "Researchers studied an endangered animal carefully",
        "outcome verb+scale superlative",
    ),
    (
        "Turns out no one told the pilot the runway had been closed",
        "A flight had an unusual landing event",
        "contradiction signal",
    ),
    (
        "The first time in history a country banned its own flag",
        "A government made a policy change about national symbols",
        "scale superlative+outcome verb",
    ),
    (
        "Only 3 men knew the truth and two of them were killed",
        "Several people were involved in a secret operation",
        "number+outcome verb",
    ),
    (
        "Woman survived 11 days trapped despite rescuers giving up",
        "A rescue operation took place in difficult conditions",
        "number+survival+contradiction",
    ),
    (
        "Never before seen creature discovered in the Mariana Trench",
        "Scientists found an unusual organism in deep water",
        "scale superlative",
    ),
    (
        "Exposed: how a single mistake killed 300 workers in 1970",
        "An industrial accident caused significant casualties",
        "outcome verb+number+year",
    ),
]


@pytest.mark.parametrize("high_title,bland_title,desc", SHOCK_PAIRS)
def test_shock_score_ranks_high_over_bland(high_title: str, bland_title: str, desc: str) -> None:
    high = _shock_score(high_title)
    bland = _shock_score(bland_title)
    assert high > bland, (
        f"[{desc}] expected shock({high_title!r})={high:.3f} "
        f"> shock({bland_title!r})={bland:.3f}"
    )


def test_shock_score_zero_for_neutral_title() -> None:
    assert _shock_score("A brief history of ancient trade routes") == 0.0


def test_shock_score_clamped_at_one() -> None:
    extreme = (
        "47 people survived despite only 3 known rescuers: world's only case "
        "where John Smith was executed first time"
    )
    assert _shock_score(extreme) <= 1.0


def test_score_title_returns_six_tuple() -> None:
    result = _score_title("Soviet submarine 1962 Cuba crisis", [])
    assert len(result) == 6, f"expected 6-tuple, got {len(result)}-tuple"


def test_candidate_has_shock_score_field() -> None:
    field_names = {f.name for f in fields(Candidate)}
    assert "shock_score" in field_names
