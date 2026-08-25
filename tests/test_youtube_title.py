"""Tests for src.content.youtube_title (Phase F: YouTube divergence).

`build_shorts_title` returns a 60-100 char keyword-leading Shorts title via
the local claude CLI. On any infra failure (CLI missing, error, timeout,
malformed output) it falls back to the IG `reel_title` truncated to 100
chars so the YouTube upload never blocks on title generation.
"""
from __future__ import annotations

from unittest.mock import patch

from src.content.youtube_title import (
    _strip_clickbait,
    _truncated_fallback,
    build_shorts_title,
    _YT_TITLE_HARD_CAP,
)


_REEL_TITLE = "How Antarctica was once a rainforest"
_CLAIM = (
    "Antarctica was once covered in temperate rainforest. "
    "Fossil pollen and roots from a 90-million-year-old core show the "
    "continent had a swampy, conifer-rich climate during the Cretaceous."
)


def _envelope(text: str) -> dict:
    return {"type": "result", "is_error": False, "result": text}


# --------------------------------------------------------------------------- #
# 1. Happy path: CLI returns a 60-100 char keyword-leading title
# --------------------------------------------------------------------------- #


def test_returns_cli_title_within_target_band():
    target = (
        "Antarctica Rainforest: 90-Million-Year Cretaceous Cores Reveal Swampy Climate"
    )
    assert 60 <= len(target) <= 100
    with patch("src.content.youtube_title.call_claude_cli") as fake_call:
        fake_call.return_value = _envelope(target)
        result = build_shorts_title(_REEL_TITLE, _CLAIM)

    assert result == target
    assert 60 <= len(result) <= 100
    fake_call.assert_called_once()


def test_calls_cli_with_sonnet():
    with patch("src.content.youtube_title.call_claude_cli") as fake_call:
        fake_call.return_value = _envelope(
            "Antarctica Rainforest 90 Million Year Old Cretaceous Cores Reveal Climate"
        )
        build_shorts_title(_REEL_TITLE, _CLAIM)

    _, kwargs = fake_call.call_args
    assert kwargs["model"] == "sonnet"


def test_cli_title_strips_wrapping_quotes():
    response = (
        '"Antarctica Rainforest: 90-Million-Year Cretaceous Cores Reveal Swampy Climate"'
    )
    with patch("src.content.youtube_title.call_claude_cli") as fake_call:
        fake_call.return_value = _envelope(response)
        result = build_shorts_title(_REEL_TITLE, _CLAIM)

    assert not result.startswith('"')
    assert not result.endswith('"')


def test_cli_title_normalises_em_dash():
    bad_dash = chr(0x2014)
    response = (
        f"Antarctica Rainforest {bad_dash} 90-Million-Year-Old Cretaceous Cores Reveal Climate"
    )
    with patch("src.content.youtube_title.call_claude_cli") as fake_call:
        fake_call.return_value = _envelope(response)
        result = build_shorts_title(_REEL_TITLE, _CLAIM)

    assert bad_dash not in result


def test_cli_title_capped_at_youtube_hard_limit():
    too_long = "A" * 150
    with patch("src.content.youtube_title.call_claude_cli") as fake_call:
        fake_call.return_value = _envelope(too_long)
        result = build_shorts_title(_REEL_TITLE, _CLAIM)

    assert len(result) <= _YT_TITLE_HARD_CAP


# --------------------------------------------------------------------------- #
# 2. Soft-fall ladder: CLI unavailable, too short, clickbait-emptied
# --------------------------------------------------------------------------- #


def test_falls_back_to_truncated_when_cli_unavailable():
    long_title = "How Antarctica was once a rainforest, " * 5
    with patch("src.content.youtube_title.call_claude_cli") as fake_call:
        fake_call.return_value = None
        result = build_shorts_title(long_title, _CLAIM)

    assert len(result) <= _YT_TITLE_HARD_CAP
    assert result.startswith("How Antarctica")


def test_falls_back_when_cli_returns_too_short():
    with patch("src.content.youtube_title.call_claude_cli") as fake_call:
        fake_call.return_value = _envelope("Antarctica.")
        result = build_shorts_title(_REEL_TITLE, _CLAIM)

    assert result == _REEL_TITLE


def test_falls_back_when_cli_returns_only_clickbait():
    with patch("src.content.youtube_title.call_claude_cli") as fake_call:
        fake_call.return_value = _envelope("You won't believe")
        result = build_shorts_title(_REEL_TITLE, _CLAIM)

    assert result == _REEL_TITLE


def test_empty_reel_title_returns_empty_without_calling_cli():
    with patch("src.content.youtube_title.call_claude_cli") as fake_call:
        assert build_shorts_title("", _CLAIM) == ""
        assert build_shorts_title("   ", _CLAIM) == ""
    fake_call.assert_not_called()


# --------------------------------------------------------------------------- #
# 3. Clickbait phrases are stripped or rejected
# --------------------------------------------------------------------------- #


def test_cli_title_strips_did_you_know():
    response = (
        "Did you know Antarctica was once a temperate rainforest 90 million years ago?"
    )
    with patch("src.content.youtube_title.call_claude_cli") as fake_call:
        fake_call.return_value = _envelope(response)
        result = build_shorts_title(_REEL_TITLE, _CLAIM)

    assert "did you know" not in result.lower()


def test_truncated_fallback_does_not_introduce_clickbait():
    """The deterministic truncation must not insert any banned phrase."""
    long_title = "How Antarctica was once a rainforest, fossil cores reveal climate "
    result = _truncated_fallback(long_title)
    lower = result.lower()
    assert "you won't believe" not in lower
    assert "did you know" not in lower
    assert "mind-blowing" not in lower
    assert "this changed everything" not in lower


def test_strip_clickbait_helper_removes_phrase():
    cleaned, hits = _strip_clickbait("you won't believe this fact about Antarctica")
    assert "believe" not in cleaned.lower()
    assert "Antarctica" in cleaned
    assert len(hits) == 1


def test_strip_clickbait_helper_passes_clean_text():
    cleaned, hits = _strip_clickbait("Antarctica Rainforest: Cretaceous Cores")
    assert cleaned == "Antarctica Rainforest: Cretaceous Cores"
    assert hits == []


# --------------------------------------------------------------------------- #
# 4. Truncation fallback edge cases
# --------------------------------------------------------------------------- #


def test_truncated_fallback_keeps_short_title_unchanged():
    short = "Antarctica rainforest fossils"
    assert _truncated_fallback(short) == short


def test_truncated_fallback_caps_at_hard_limit():
    long_title = "A" * 150
    result = _truncated_fallback(long_title)
    assert len(result) == _YT_TITLE_HARD_CAP


def test_truncated_fallback_handles_empty():
    assert _truncated_fallback("") == ""
    assert _truncated_fallback("   ") == ""
