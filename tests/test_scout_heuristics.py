"""Tests for the heuristic scoring upgrades added 2026-05-16.

Covers _punchline_in_title, _question_mode, _familiarity_penalty,
and their integration into _score_title.
"""
from __future__ import annotations

from src.research import story_scout


# ---- _punchline_in_title -----------------------------------------------


def test_punchline_detected_when_explanation_follows_connector() -> None:
    spoiled = "TIL the Hindenburg crashed because hydrogen ignited near the tail fin"
    assert story_scout._punchline_in_title(spoiled) is True


def test_punchline_detected_with_actually_resolution() -> None:
    spoiled = "Bananas are actually berries from the same family as tomatoes"
    assert story_scout._punchline_in_title(spoiled) is True


def test_punchline_not_detected_when_no_connector() -> None:
    mystery = "An island appeared off Iceland in 1963 and nobody can visit"
    assert story_scout._punchline_in_title(mystery) is False


def test_punchline_not_detected_when_tail_too_short() -> None:
    title = "Ship sank in 1912 because of fog"
    assert story_scout._punchline_in_title(title) is False


# ---- _question_mode ----------------------------------------------------


def test_question_mode_question_mark() -> None:
    assert story_scout._question_mode("Why did the Soviet Navy lose 8 submarines?") is True


def test_question_mode_mystery_opener() -> None:
    assert story_scout._question_mode("The mystery of the Dyatlov Pass deaths") is True


def test_question_mode_unknown_phrase() -> None:
    assert story_scout._question_mode("No one knows what happened on flight MH370") is True


def test_question_mode_plain_assertion() -> None:
    assert story_scout._question_mode("The Soviet submarine K-19 leaked radiation in 1961") is False


# ---- _familiarity_penalty ----------------------------------------------


def test_familiarity_penalty_well_worn() -> None:
    penalty = story_scout._familiarity_penalty("TIL the mantis shrimp has 16 colour receptors")
    assert penalty >= 0.2


def test_familiarity_penalty_clean() -> None:
    penalty = story_scout._familiarity_penalty("The 1908 Tunguska event flattened Siberian forest")
    assert penalty == 0.0


def test_familiarity_penalty_caps_at_04() -> None:
    penalty = story_scout._familiarity_penalty(
        "Mantis shrimp swim through the Mariana Trench past Cleopatra near pyramids"
    )
    assert penalty <= 0.4


def test_familiarity_penalty_fresh_cleopatra_angle_passes() -> None:
    """Fresh archaeology angle on a famous subject must not trigger."""
    assert story_scout._familiarity_penalty(
        "Cleopatra's tomb finally located by sonar survey in 2024"
    ) == 0.0


def test_familiarity_penalty_fresh_pyramids_angle_passes() -> None:
    """Fresh discovery about pyramids must not trigger the broad-subject penalty."""
    assert story_scout._familiarity_penalty(
        "Mayan pyramids were aligned with Venus transits, new study finds"
    ) == 0.0


def test_familiarity_penalty_fresh_great_wall_angle_passes() -> None:
    assert story_scout._familiarity_penalty(
        "Great Wall section in Inner Mongolia was a smuggling route"
    ) == 0.0


def test_familiarity_penalty_cleopatra_timeline_meme_still_caught() -> None:
    """The actual cliché phrasing must still trigger."""
    assert story_scout._familiarity_penalty(
        "Cleopatra lived closer to the moon landing than to the pyramids"
    ) > 0.0


# ---- _score_title integration ------------------------------------------


def test_score_title_punchline_lowers_hook() -> None:
    spoiled = story_scout._score_title(
        "Ship sank because the captain ignored hidden iceberg warnings", []
    )
    mystery = story_scout._score_title(
        "Ship sank in 1912 with a hidden warning that nobody read", []
    )
    assert spoiled[0] < mystery[0]


def test_score_title_well_worn_hits_novelty() -> None:
    well_worn = story_scout._score_title("The mantis shrimp has 16 photoreceptors", [])
    fresh = story_scout._score_title("The fangtooth has translucent body armour", [])
    assert well_worn[1] < fresh[1]


def test_score_title_question_mode_lifts_hook() -> None:
    base = story_scout._score_title("Soviet submarine K-19 leaked radiation", [])
    question = story_scout._score_title(
        "Why did Soviet submarine K-19 vanish for a year?", []
    )
    assert question[0] >= base[0]


def test_score_title_still_returns_six_tuple() -> None:
    result = story_scout._score_title("Anything title here at all", [])
    assert len(result) == 6
