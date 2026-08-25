"""Tests for src.content.hashtag_builder (local claude CLI, not the API).

Falls back to static topic buckets on any infra failure or malformed output.
"""
from __future__ import annotations

from unittest.mock import patch

from src.content.hashtag_builder import build_hashtags, _BRAND


_SUMMARY = "In 1932 the Australian army lost a war to emus."


def _envelope(hashtags: list) -> dict:
    return {"type": "result", "is_error": False, "structured_output": {"hashtags": hashtags}}


def test_returns_generated_tags_plus_brand_anchor():
    tags = [f"#tag{i}" for i in range(15)]
    with patch("src.content.hashtag_builder.call_claude_cli") as fake_call:
        fake_call.return_value = _envelope(tags)
        result = build_hashtags(_SUMMARY, topic="history")

    assert result.endswith(_BRAND)
    for t in tags:
        assert t in result


def test_calls_cli_with_sonnet_and_a_schema():
    with patch("src.content.hashtag_builder.call_claude_cli") as fake_call:
        fake_call.return_value = _envelope([f"#tag{i}" for i in range(10)])
        build_hashtags(_SUMMARY)

    _, kwargs = fake_call.call_args
    assert kwargs["model"] == "sonnet"
    assert kwargs["json_schema"] is not None


def test_filters_malformed_tags():
    valid = [f"#good_tag{i}" for i in range(8)]  # clears the 8-tag floor
    invalid = ["no hash prefix", "#has space"]
    with patch("src.content.hashtag_builder.call_claude_cli") as fake_call:
        fake_call.return_value = _envelope(valid + invalid)
        result = build_hashtags(_SUMMARY)

    for t in valid:
        assert t in result
    assert "no hash prefix" not in result
    assert "#has space" not in result


def test_falls_back_when_too_few_valid_tags():
    with patch("src.content.hashtag_builder.call_claude_cli") as fake_call:
        fake_call.return_value = _envelope(["#one", "#two"])  # below the 8-tag floor
        result = build_hashtags(_SUMMARY, topic="science")

    assert "#science" in result
    assert result.endswith(_BRAND)


def test_falls_back_when_cli_unavailable():
    with patch("src.content.hashtag_builder.call_claude_cli") as fake_call:
        fake_call.return_value = None
        result = build_hashtags(_SUMMARY, topic="ocean")

    assert "#ocean" in result
    assert result.endswith(_BRAND)


def test_falls_back_on_empty_summary_without_calling_cli():
    with patch("src.content.hashtag_builder.call_claude_cli") as fake_call:
        result = build_hashtags("", topic="space")

    assert "#space" in result
    fake_call.assert_not_called()


def test_fallback_uses_post_type_when_topic_unknown():
    with patch("src.content.hashtag_builder.call_claude_cli") as fake_call:
        fake_call.return_value = None
        result = build_hashtags(_SUMMARY, topic="not-a-real-topic", post_type="film")

    assert "#filmrecs" in result
