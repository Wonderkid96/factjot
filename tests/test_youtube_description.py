"""Tests for src.content.youtube_description (Phase F: YouTube divergence).

`build_shorts_description` returns a Shorts-shaped description: 1-2 line
hook, blank line, source URLs, blank line, exactly 5 hashtags ending in
`#Shorts`, via the local claude CLI. On any infra failure (CLI missing,
error, timeout, malformed output) it falls back to a deterministic template
so the YouTube upload never blocks on description generation.
"""
from __future__ import annotations

from unittest.mock import patch

from src.content.youtube_description import (
    _deterministic_fallback,
    _has_minimum_shape,
    _strip_clickbait,
    build_shorts_description,
)


_REEL_TITLE = "Antarctica was once a rainforest"
_CLAIM = (
    "Antarctica was once covered in temperate rainforest. "
    "Fossil pollen and roots from a 90-million-year-old core show the "
    "continent had a swampy, conifer-rich climate during the Cretaceous."
)
_SOURCES = [
    "https://www.bbc.com/news/science-environment-52213877",
    "https://www.nature.com/articles/s41586-020-2148-5",
    "https://www.nationalgeographic.com/science/article/antarctic-rainforest-discovery",
]
_TOPIC = "earth"


def _envelope(text: str) -> dict:
    return {"type": "result", "is_error": False, "result": text}


_GOOD_CLI_RESPONSE = (
    "Antarctica was once a temperate rainforest. Fossil cores from a "
    "90-million-year-old sample reveal a swampy Cretaceous climate.\n"
    "\n"
    "https://www.bbc.com/news/science-environment-52213877\n"
    "https://www.nature.com/articles/s41586-020-2148-5\n"
    "https://www.nationalgeographic.com/science/article/antarctic-rainforest-discovery\n"
    "\n"
    "#science #Antarctica #climate #fossils #Shorts"
)


# --------------------------------------------------------------------------- #
# 1. Happy path: CLI returns a properly shaped description
# --------------------------------------------------------------------------- #


def test_returns_cli_description_with_shorts_hashtag():
    """CLI response with proper shape -> normalised passthrough."""
    with patch("src.content.youtube_description.call_claude_cli") as fake_call:
        fake_call.return_value = _envelope(_GOOD_CLI_RESPONSE)
        result = build_shorts_description(_REEL_TITLE, _CLAIM, _SOURCES, _TOPIC)

    hashtag_lines = [
        line for line in result.splitlines() if line.strip().startswith("#")
    ]
    assert hashtag_lines, "expected at least one hashtag line"
    last_line = hashtag_lines[-1].strip()
    tags = last_line.split()
    assert len(tags) == 5
    assert tags[-1] == "#Shorts"
    fake_call.assert_called_once()


def test_calls_cli_with_sonnet():
    with patch("src.content.youtube_description.call_claude_cli") as fake_call:
        fake_call.return_value = _envelope(_GOOD_CLI_RESPONSE)
        build_shorts_description(_REEL_TITLE, _CLAIM, _SOURCES, _TOPIC)

    _, kwargs = fake_call.call_args
    assert kwargs["model"] == "sonnet"


def test_cli_output_is_normalised():
    """Em-dashes from a misbehaving model -> stripped via voice_normaliser."""
    bad_dash = chr(0x2014)  # U+2014 EM DASH
    response = (
        f"Antarctica {bad_dash} once a rainforest.\n"
        "\n"
        "https://www.bbc.com/news/science-environment-52213877\n"
        "https://www.nature.com/articles/s41586-020-2148-5\n"
        "https://www.nationalgeographic.com/science/article/antarctic-rainforest\n"
        "\n"
        "#science #Antarctica #climate #fossils #Shorts"
    )
    with patch("src.content.youtube_description.call_claude_cli") as fake_call:
        fake_call.return_value = _envelope(response)
        result = build_shorts_description(_REEL_TITLE, _CLAIM, _SOURCES, _TOPIC)

    assert bad_dash not in result


# --------------------------------------------------------------------------- #
# 2. Soft-fall to deterministic format
# --------------------------------------------------------------------------- #


def test_falls_back_to_deterministic_when_cli_unavailable():
    """CLI missing/errored -> deterministic fallback, upload still proceeds."""
    with patch("src.content.youtube_description.call_claude_cli") as fake_call:
        fake_call.return_value = None
        result = build_shorts_description(_REEL_TITLE, _CLAIM, _SOURCES, _TOPIC)

    assert _REEL_TITLE in result
    for url in _SOURCES:
        assert url in result
    last_line = result.strip().splitlines()[-1]
    tags = last_line.split()
    assert len(tags) == 5
    assert tags[-1] == "#Shorts"


def test_falls_back_when_cli_returns_malformed_no_hashtags():
    """Model ignored the format spec (no hashtags) -> deterministic fallback."""
    with patch("src.content.youtube_description.call_claude_cli") as fake_call:
        fake_call.return_value = _envelope(
            "Just a plain paragraph with no hashtags or sources at all."
        )
        result = build_shorts_description(_REEL_TITLE, _CLAIM, _SOURCES, _TOPIC)

    assert _REEL_TITLE in result
    last_line = result.strip().splitlines()[-1]
    assert last_line.split()[-1] == "#Shorts"


# --------------------------------------------------------------------------- #
# 3. Banned clickbait phrases are rejected from the final output
# --------------------------------------------------------------------------- #


def test_clickbait_phrases_stripped_from_cli_output():
    """Model slipped in a banned phrase -> stripper removes it, output ships."""
    response = (
        "You won't believe Antarctica was once a rainforest. Fossil cores "
        "show a Cretaceous swampy climate.\n"
        "\n"
        "https://www.bbc.com/news/science-environment-52213877\n"
        "https://www.nature.com/articles/s41586-020-2148-5\n"
        "https://www.nationalgeographic.com/science/article/antarctic-rainforest\n"
        "\n"
        "#science #Antarctica #climate #fossils #Shorts"
    )
    with patch("src.content.youtube_description.call_claude_cli") as fake_call:
        fake_call.return_value = _envelope(response)
        result = build_shorts_description(_REEL_TITLE, _CLAIM, _SOURCES, _TOPIC)

    lower = result.lower()
    assert "you won't believe" not in lower
    assert "you wont believe" not in lower
    assert "mind-blowing" not in lower
    assert "did you know" not in lower
    assert "this changed everything" not in lower


def test_deterministic_fallback_has_no_banned_phrases():
    """The deterministic template never contains banned phrases."""
    result = _deterministic_fallback(_REEL_TITLE, _CLAIM, _SOURCES, _TOPIC)
    lower = result.lower()
    assert "you won't believe" not in lower
    assert "you wont believe" not in lower
    assert "mind-blowing" not in lower
    assert "did you know" not in lower
    assert "this changed everything" not in lower


# --------------------------------------------------------------------------- #
# 4. Helper coverage
# --------------------------------------------------------------------------- #


def test_strip_clickbait_returns_hits():
    cleaned, hits = _strip_clickbait("you won't believe this fact about pyramids")
    assert "believe" not in cleaned.lower()
    assert "pyramids" in cleaned.lower()
    assert len(hits) == 1


def test_strip_clickbait_passes_clean_text_through():
    cleaned, hits = _strip_clickbait("Pyramids are older than mammoths.")
    assert cleaned == "Pyramids are older than mammoths."
    assert hits == []


def test_has_minimum_shape_requires_shorts_hashtag():
    """Sanity gate: missing #Shorts -> not a valid description."""
    assert not _has_minimum_shape("")
    assert not _has_minimum_shape("hello world")
    assert not _has_minimum_shape("hello #science #facts")
    assert _has_minimum_shape("hello #science #Shorts")


# --------------------------------------------------------------------------- #
# 5. Deterministic fallback edge cases
# --------------------------------------------------------------------------- #


def test_deterministic_fallback_drops_non_url_sources():
    """Garbage in `sources` shouldn't poison the description."""
    result = _deterministic_fallback(
        _REEL_TITLE, _CLAIM,
        ["not a url", "https://valid.example.com/article", ""],
        _TOPIC,
    )
    assert "not a url" not in result
    assert "https://valid.example.com/article" in result


def test_deterministic_fallback_handles_empty_sources():
    """No sources -> still returns a viable description with hashtags."""
    result = _deterministic_fallback(_REEL_TITLE, _CLAIM, [], _TOPIC)
    assert _REEL_TITLE in result
    last_line = result.strip().splitlines()[-1]
    assert last_line.split()[-1] == "#Shorts"


def test_deterministic_fallback_normalises_topic_for_hashtag():
    """Topic with spaces / non-alpha -> safe hashtag."""
    result = _deterministic_fallback(_REEL_TITLE, _CLAIM, [], "Earth Science!")
    last_line = result.strip().splitlines()[-1]
    # Topic punctuation stripped.
    assert "Science!" not in last_line
