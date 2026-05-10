"""Tests for src.content.thumbnail_headline (Phase E.4).

`build_thumbnail_headline` shortens the curated reel title to 4-6 words
for the cover overlay. <=6 words pass through unchanged. On any infra
failure the soft-fall returns the first 6 words of the input so the
overlay still ships something.

Tests mock the Anthropic SDK and verify each branch of the soft-fall
ladder, plus the clickbait stripper that scrubs phrases the prompt
banned but the model occasionally produces anyway.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from src.content.thumbnail_headline import (
    _strip_clickbait,
    _word_count,
    build_thumbnail_headline,
)


def _mock_haiku_text(text: str) -> MagicMock:
    """Fake Anthropic SDK response carrying a plain-text string."""
    res = MagicMock()
    res.content = [MagicMock()]
    res.content[0].text = text
    res.usage.input_tokens = 50
    res.usage.output_tokens = 8
    return res


# --------------------------------------------------------------------------- #
# 1. Pass-through when input is already short enough
# --------------------------------------------------------------------------- #


def test_short_title_passes_through_unchanged(monkeypatch):
    """6 words or fewer -> no Haiku call, return as-is."""
    fake_client = MagicMock()
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    result = build_thumbnail_headline(
        "deep ocean pressure crushes submarines.", api_key="dummy",
    )
    # Trailing period is stripped.
    assert result == "deep ocean pressure crushes submarines"
    fake_client.messages.create.assert_not_called()


def test_exact_six_words_passes_through(monkeypatch):
    """Exactly 6 words -> no Haiku call."""
    fake_client = MagicMock()
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)
    txt = "one two three four five six"
    assert build_thumbnail_headline(txt, api_key="dummy") == txt
    fake_client.messages.create.assert_not_called()


# --------------------------------------------------------------------------- #
# 2. Long title goes through Haiku, returns the shortened version
# --------------------------------------------------------------------------- #


def test_long_title_is_shortened_via_haiku(monkeypatch):
    """>6 words -> Haiku is called, response is returned (no period, no quotes)."""
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_haiku_text(
        "ocean pressure crushes submarines"
    )
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    long_title = (
        "How Deep Ocean Pressure Crushes Submarines at One Thousand Metres "
        "Below the Surface"
    )
    result = build_thumbnail_headline(long_title, api_key="dummy")

    assert result == "ocean pressure crushes submarines"
    fake_client.messages.create.assert_called_once()


def test_long_title_strips_wrapping_quotes_from_haiku(monkeypatch):
    """Models sometimes wrap output in quotes despite instruction; strip them."""
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_haiku_text(
        '"ocean pressure crushes submarines"'
    )
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    result = build_thumbnail_headline(
        "How Deep Ocean Pressure Crushes Submarines at Thousand Metres",
        api_key="dummy",
    )
    assert result == "ocean pressure crushes submarines"


def test_long_title_caps_at_six_words_when_haiku_overshoots(monkeypatch):
    """Haiku ignored the cap -> we trim to 6 words."""
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_haiku_text(
        "deep ocean pressure crushes the silent submarines below"
    )
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    result = build_thumbnail_headline(
        "How Deep Ocean Pressure Crushes Submarines at Thousand Metres",
        api_key="dummy",
    )
    assert _word_count(result) == 6


# --------------------------------------------------------------------------- #
# 3. Soft-fall on Anthropic error -> first 6 words of input
# --------------------------------------------------------------------------- #


def test_soft_falls_to_first_six_words_on_anthropic_error(monkeypatch):
    """Network / 5xx / timeout -> first 6 words of the original title."""
    fake_client = MagicMock()
    fake_client.messages.create.side_effect = ConnectionError("upstream 503")
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    long_title = "How Deep Ocean Pressure Crushes Submarines at Thousand Metres"
    result = build_thumbnail_headline(long_title, api_key="dummy")

    assert result == "How Deep Ocean Pressure Crushes Submarines"
    assert _word_count(result) == 6


def test_soft_falls_when_api_key_empty(monkeypatch):
    """No API key -> first 6 words of input, no Anthropic call."""
    fake_client = MagicMock()
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    long_title = "How Deep Ocean Pressure Crushes Submarines at Thousand Metres"
    result = build_thumbnail_headline(long_title, api_key="")
    assert result == "How Deep Ocean Pressure Crushes Submarines"
    fake_client.messages.create.assert_not_called()


def test_soft_falls_when_haiku_returns_only_clickbait(monkeypatch):
    """Haiku returned 'You won't believe' only -> stripper empties it -> soft-fall."""
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_haiku_text(
        "You won't believe"
    )
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    long_title = "How Deep Ocean Pressure Crushes Submarines at Thousand Metres"
    result = build_thumbnail_headline(long_title, api_key="dummy")
    assert result == "How Deep Ocean Pressure Crushes Submarines"


# --------------------------------------------------------------------------- #
# 4. Clickbait stripper: strips phrases the prompt banned, keeps the rest
# --------------------------------------------------------------------------- #


def test_strip_clickbait_removes_you_wont_believe():
    """'you won't believe X' -> 'X'. Logged warning, output still usable."""
    cleaned, hits = _strip_clickbait("you won't believe deep ocean pressure")
    assert "believe" not in cleaned.lower()
    assert "deep ocean pressure" in cleaned.lower()
    assert len(hits) == 1


def test_strip_clickbait_removes_mind_blown():
    cleaned, hits = _strip_clickbait("mind-blown by submarine depths")
    assert "blown" not in cleaned.lower()
    assert "submarine" in cleaned.lower()
    assert len(hits) == 1


def test_strip_clickbait_removes_multiple_phrases():
    cleaned, hits = _strip_clickbait(
        "you won't believe this changed everything for submarines"
    )
    assert "believe" not in cleaned.lower()
    assert "everything" not in cleaned.lower()
    assert "submarines" in cleaned.lower()
    assert len(hits) == 2


def test_strip_clickbait_passes_through_clean_text():
    cleaned, hits = _strip_clickbait("ocean pressure crushes submarines")
    assert cleaned == "ocean pressure crushes submarines"
    assert hits == []


# --------------------------------------------------------------------------- #
# 5. Edge cases: empty / whitespace / case mirror
# --------------------------------------------------------------------------- #


def test_empty_input_returns_empty():
    assert build_thumbnail_headline("", api_key="dummy") == ""
    assert build_thumbnail_headline("   ", api_key="dummy") == ""


def test_lowercase_input_keeps_haiku_response_lowercase(monkeypatch):
    """Lower-case input -> mirror to lower-case even if Haiku used title case."""
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_haiku_text(
        "Ocean Pressure Crushes Submarines"  # title case from model
    )
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    long_lower = "how deep ocean pressure crushes submarines at thousand metres"
    result = build_thumbnail_headline(long_lower, api_key="dummy")
    # Lower-case input -> output mirrored to lower-case.
    assert result == "ocean pressure crushes submarines"


def test_mixed_case_input_keeps_haiku_response_mixed(monkeypatch):
    """Mixed-case input -> do NOT force lower-case."""
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_haiku_text(
        "Ocean Pressure Crushes Submarines"
    )
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    long_mixed = "How Deep Ocean Pressure Crushes Submarines at Thousand Metres"
    result = build_thumbnail_headline(long_mixed, api_key="dummy")
    assert result == "Ocean Pressure Crushes Submarines"


def test_word_count_helper():
    assert _word_count("") == 0
    assert _word_count("one") == 1
    assert _word_count("one two three") == 3
    assert _word_count("   spaced   words   ") == 2
