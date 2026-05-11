"""Regression tests for the consistency-check calibration.

The 2026-05-11 09:00 BST scheduled reel slot skipped because Haiku
rejected the Mechanical Turk story (a real 1770 chess-automaton
hoax) with reason 'framing this as an absurdity or fabrication
story rather than a factual account, making it inappropriate for
a fact account despite being historically accurate about the Turk.'

The verifier was over-rejecting: stories about real hoaxes, failed
experiments, and counter-intuitive events are exactly what @factjot
ships. The fix:
1. Narrowed _RED_FLAG_WORDS from 6 to 3 - removed `experiment`,
   `invented`, `fabricated` which catch legitimate content.
2. Rewrote the Haiku prompt to make rule #2 literal (only the exact
   listed words, not the model's interpretation of 'sounds like
   fiction') and add positive examples of valid hoax/failed-experiment
   stories.

These tests pin the deterministic local-scan path. The Haiku
prompt itself is tested for shape and content but not for output
(would require a real Anthropic call); the prompt changes are
verified by running the calibration check against the actual
slot.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.verification.fact_checker import (  # noqa: E402
    _RED_FLAG_WORDS,
    _consistency_prompt,
    verify_consistency,
)


# ----- red-flag word list calibration -------------------------------

def test_red_flag_list_is_narrow():
    """Three words only. Each must signal the POST is fictional, not
    that the subject involves anything experimental / inventive."""
    assert set(_RED_FLAG_WORDS) == {"fictional", "imaginary", "absurdity"}


def test_experiment_no_longer_red_flag():
    """A real failed experiment is valid fact content."""
    assert "experiment" not in _RED_FLAG_WORDS


def test_invented_no_longer_red_flag():
    """'X invented Y' is a legitimate fact pattern."""
    assert "invented" not in _RED_FLAG_WORDS


def test_fabricated_no_longer_red_flag():
    """Real stories about document forgery use the word 'fabricated'."""
    assert "fabricated" not in _RED_FLAG_WORDS


# ----- deterministic local scan: real hoax / failed experiment stories pass ---

def test_acoustic_kitty_passes_local_scan():
    """The CIA Acoustic Kitty reel (shipped 2026-05-11 00:02Z)
    uses 'experiment' legitimately. Must not be locally blocked.
    """
    result = verify_consistency({
        "title": "What the CIA Spent $20 Million On",
        "claim": "In the 1960s the CIA spent $20 million on a program "
                 "called Acoustic Kitty. The experiment implanted a "
                 "microphone in a live cat. It did not work.",
        "format_type": "fact",
    }, api_key="")  # empty api_key -> fails open after local scan
    assert result["ok"], f"unexpected block: {result['reason']}"


def test_skinner_pigeon_passes_local_scan():
    """The Project Pigeon reel (shipped 2026-05-11 00:29Z) describes
    a real WW2 experiment. Must not be locally blocked.
    """
    result = verify_consistency({
        "title": "The Weapon That Actually Worked",
        "claim": "During WW2, psychologist B.F. Skinner built a guided "
                 "missile steered by pigeons. The experiment succeeded "
                 "in tests. The military funded it and then cancelled it.",
        "format_type": "fact",
    }, api_key="")
    assert result["ok"], f"unexpected block: {result['reason']}"


def test_mechanical_turk_passes_local_scan():
    """The Mechanical Turk story that triggered the 09:00 BST skip
    on 2026-05-11. Real 1770 hoax. Must pass the local scan.
    """
    result = verify_consistency({
        "title": "The Chess Machine That Wasn't",
        "claim": "In 1770 Wolfgang von Kempelen unveiled a chess-playing "
                 "automaton called The Turk. It toured Europe for 80 "
                 "years, defeating Napoleon. Inside the cabinet sat a "
                 "hidden human chess master.",
        "format_type": "fact",
    }, api_key="")
    assert result["ok"], f"unexpected block: {result['reason']}"


def test_wright_brothers_passes_local_scan():
    """The word 'invented' must not block a real history of invention."""
    result = verify_consistency({
        "title": "The Day Powered Flight Began",
        "claim": "On 17 December 1903 the Wright brothers invented "
                 "powered flight at Kitty Hawk.",
        "format_type": "fact",
    }, api_key="")
    assert result["ok"], f"unexpected block: {result['reason']}"


def test_document_forgery_passes_local_scan():
    """The word 'fabricated' must not block real stories about forgery."""
    result = verify_consistency({
        "title": "The Forger Who Saved Lives",
        "claim": "Adolfo Kaminsky fabricated identity documents that "
                 "rescued thousands during the Holocaust.",
        "format_type": "fact",
    }, api_key="")
    assert result["ok"], f"unexpected block: {result['reason']}"


# ----- the bad-shape inputs that triggered the original gate --------

def test_fictional_films_still_blocks():
    """The original incident: 'Five fictional films ranked by absurdity'.
    Both red-flag words appear. Must still hard-fail.
    """
    result = verify_consistency({
        "title": "Five fictional films ranked by absurdity",
        "claim": "These five made-up films illustrate the absurdity of...",
        "format_type": "list",
    }, api_key="")
    assert not result["ok"]
    assert "red_flag_word" in result["reason"]


def test_imaginary_word_blocks():
    """An 'imaginary' framing must still trigger the gate."""
    result = verify_consistency({
        "title": "Five imaginary historical figures",
        "claim": "These imaginary people never existed but...",
        "format_type": "list",
    }, api_key="")
    assert not result["ok"]
    assert "red_flag_word" in result["reason"]


# ----- Haiku prompt shape -------------------------------------------

def test_prompt_includes_positive_hoax_examples():
    """The prompt must call out real hoaxes / failed experiments as
    valid content so the model doesn't extend rule #2 to framing.
    """
    prompt = _consistency_prompt(
        title="t", claim="c", caption_body="", format_type="fact",
    )
    # Specific real-world subjects mentioned by name as 'valid content'.
    assert "Mechanical Turk" in prompt
    assert "Acoustic Kitty" in prompt
    assert "Project Pigeon" in prompt


def test_prompt_makes_rule_2_literal():
    """The prompt must tell the model rule #2 is keyword-only,
    not its own interpretation of 'sounds like fiction'.
    """
    prompt = _consistency_prompt(
        title="t", claim="c", caption_body="", format_type="fact",
    )
    assert "ONLY on the exact words" in prompt or "exact words" in prompt
    assert "Do not extend this rule" in prompt or "do not extend" in prompt.lower()


def test_prompt_does_not_describe_hoax_framing_as_a_flag():
    """The prompt must not give the model any signal that 'deception/
    hoax framing' is itself a red flag - that's the over-extension
    that caused the Mechanical Turk skip.
    """
    prompt = _consistency_prompt(
        title="t", claim="c", caption_body="", format_type="fact",
    )
    # Positive: real hoaxes are explicitly valid content.
    assert "hoaxes" in prompt.lower()
    # And the model is told to be permissive on tone.
    assert "permissive on tone" in prompt.lower()
