"""Tests for src.content.youtube_title (Phase F: YouTube divergence).

`build_shorts_title` returns a 60-100 char keyword-leading Shorts title.
On any infra failure (no api_key, Anthropic exception, malformed Haiku
output) it falls back to the IG `reel_title` truncated to 100 chars so
the YouTube upload never blocks on title generation.
"""
from __future__ import annotations

from unittest.mock import MagicMock

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


def _mock_haiku_text(text: str) -> MagicMock:
    """Fake Anthropic SDK response carrying a plain-text string."""
    res = MagicMock()
    res.content = [MagicMock()]
    res.content[0].text = text
    res.usage.input_tokens = 100
    res.usage.output_tokens = 30
    return res


# --------------------------------------------------------------------------- #
# 1. Happy path: Haiku returns a 60-100 char keyword-leading title
# --------------------------------------------------------------------------- #


def test_returns_haiku_title_within_target_band(monkeypatch):
    """Haiku returns a 60-100 char title -> passthrough (normalised)."""
    target = (
        "Antarctica Rainforest: 90-Million-Year Cretaceous Cores Reveal Swampy Climate"
    )
    assert 60 <= len(target) <= 100
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_haiku_text(target)
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    result = build_shorts_title(_REEL_TITLE, _CLAIM, api_key="dummy")
    assert result == target
    assert 60 <= len(result) <= 100
    fake_client.messages.create.assert_called_once()


def test_haiku_title_strips_wrapping_quotes(monkeypatch):
    """Models sometimes wrap output in quotes despite instruction."""
    response = (
        '"Antarctica Rainforest: 90-Million-Year Cretaceous Cores Reveal Swampy Climate"'
    )
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_haiku_text(response)
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    result = build_shorts_title(_REEL_TITLE, _CLAIM, api_key="dummy")
    assert not result.startswith('"')
    assert not result.endswith('"')


def test_haiku_title_normalises_em_dash(monkeypatch):
    """Em-dash from Haiku -> normalised away by voice_normaliser."""
    bad_dash = chr(0x2014)
    response = (
        f"Antarctica Rainforest {bad_dash} 90-Million-Year-Old Cretaceous Cores Reveal Climate"
    )
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_haiku_text(response)
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    result = build_shorts_title(_REEL_TITLE, _CLAIM, api_key="dummy")
    assert bad_dash not in result


def test_haiku_title_capped_at_youtube_hard_limit(monkeypatch):
    """Haiku gave > 100 chars -> trimmed to 100."""
    too_long = "A" * 150
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_haiku_text(too_long)
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    result = build_shorts_title(_REEL_TITLE, _CLAIM, api_key="dummy")
    assert len(result) <= _YT_TITLE_HARD_CAP


# --------------------------------------------------------------------------- #
# 2. Soft-fall ladder: empty key, missing SDK, exception, empty response
# --------------------------------------------------------------------------- #


def test_falls_back_to_reel_title_when_api_key_empty(monkeypatch):
    """No api_key + no env var -> truncated reel_title fallback."""
    fake_client = MagicMock()
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = build_shorts_title(_REEL_TITLE, _CLAIM, api_key="")
    fake_client.messages.create.assert_not_called()
    assert result == _REEL_TITLE


def test_falls_back_to_truncated_when_anthropic_raises(monkeypatch):
    """Anthropic exception -> reel_title fallback (truncated to 100)."""
    fake_client = MagicMock()
    fake_client.messages.create.side_effect = ConnectionError("upstream 503")
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    long_title = "How Antarctica was once a rainforest, " * 5
    result = build_shorts_title(long_title, _CLAIM, api_key="dummy")
    assert len(result) <= _YT_TITLE_HARD_CAP
    assert result.startswith("How Antarctica")


def test_falls_back_when_haiku_returns_too_short(monkeypatch):
    """Haiku gave < 20 chars -> truncated reel_title fallback."""
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_haiku_text("Antarctica.")
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    result = build_shorts_title(_REEL_TITLE, _CLAIM, api_key="dummy")
    assert result == _REEL_TITLE


def test_falls_back_when_haiku_returns_only_clickbait(monkeypatch):
    """Haiku returned 'You won't believe' only -> stripper empties it -> fallback."""
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_haiku_text("You won't believe")
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    result = build_shorts_title(_REEL_TITLE, _CLAIM, api_key="dummy")
    assert result == _REEL_TITLE


def test_empty_reel_title_returns_empty(monkeypatch):
    """Empty input -> empty output, no Anthropic call."""
    fake_client = MagicMock()
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)
    assert build_shorts_title("", _CLAIM, api_key="dummy") == ""
    assert build_shorts_title("   ", _CLAIM, api_key="dummy") == ""
    fake_client.messages.create.assert_not_called()


# --------------------------------------------------------------------------- #
# 3. Clickbait phrases are stripped or rejected
# --------------------------------------------------------------------------- #


def test_haiku_title_strips_did_you_know(monkeypatch):
    """Haiku slipped in 'Did you know' -> stripper removes it."""
    response = (
        "Did you know Antarctica was once a temperate rainforest 90 million years ago?"
    )
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_haiku_text(response)
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    result = build_shorts_title(_REEL_TITLE, _CLAIM, api_key="dummy")
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
