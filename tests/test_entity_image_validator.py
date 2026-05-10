"""Tests for src.research.entity_image_validator (Phase E.3).

The validator runs every entity-tier image past Haiku 4.5 vision before
the candidate enters footage_clips. Two real production failures that
this gate prevents:

- Hillary Clinton 2016 campaign poster behind a deep-ocean topic
  (output/reel/0e429c48dde78e/thumbnail.png).
- Engineering officers memorial inscription behind the same script
  (output/reel/65e54938a1494e/thumbnail.png).

Soft-fail policy: missing api_key, anthropic infra error, malformed JSON
all return ok=True so the existing fallback chain in find_videos still
works on a developer machine without credentials. Only an explicit
matches=false from the model rejects.
"""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from src.research.entity_image_validator import (
    _detect_media_type,
    _parse_response,
    validate_entity_image,
)


# ---------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------- #


_PNG_HEADER = b"\x89PNG\r\n\x1a\n"
_JPEG_HEADER = b"\xff\xd8\xff\xe0\x00\x10JFIF"


def _write_fake_image(dir_path: Path, *, name: str = "test.png", header: bytes = _PNG_HEADER) -> Path:
    """Write a small file with a real image magic-byte header.

    The validator reads the first few bytes to detect media type; the rest
    of the file body is irrelevant for the unit tests because the
    Anthropic call is mocked.
    """
    p = dir_path / name
    p.write_bytes(header + b"\x00" * 256)
    return p


def _mock_haiku_response(payload: dict, *, in_tokens: int = 120, out_tokens: int = 40) -> MagicMock:
    """Fake Anthropic SDK messages.create response carrying JSON.

    Mirrors the shape used by tests/test_fact_checker_verification.py for
    parity. The validator extracts JSON from the first text block.
    """
    res = MagicMock()
    res.content = [MagicMock()]
    res.content[0].text = json.dumps(payload)
    res.usage.input_tokens = in_tokens
    res.usage.output_tokens = out_tokens
    return res


# ---------------------------------------------------------------------- #
# Positive / negative core paths
# ---------------------------------------------------------------------- #


def test_validate_returns_ok_true_on_positive_haiku_response(monkeypatch):
    """Haiku says matches=true with high confidence -> ok=True, accepted."""
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_haiku_response({
        "matches": True,
        "confidence": 0.92,
        "reason": "image clearly shows a deep-ocean submarine",
    })
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    with TemporaryDirectory() as td:
        p = _write_fake_image(Path(td))
        result = validate_entity_image(
            image_url=str(p),
            claim_text="Deep-ocean pressure crushes submarines.",
            image_hint="deep ocean submarine",
            api_key="dummy",
        )

    assert result["ok"] is True
    assert result["confidence"] >= 0.9
    assert "submarine" in result["reason"].lower()
    assert result["cost_usd"] > 0.0


def test_validate_returns_ok_false_on_negative_haiku_response(monkeypatch):
    """Hillary Clinton poster on a deep-ocean topic: matches=false rejected."""
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_haiku_response({
        "matches": False,
        "confidence": 0.97,
        "reason": "image shows a Hillary Clinton 2016 campaign poster, not a submarine",
    })
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    with TemporaryDirectory() as td:
        p = _write_fake_image(Path(td), name="bad.jpg", header=_JPEG_HEADER)
        result = validate_entity_image(
            image_url=str(p),
            claim_text="Deep-ocean pressure crushes submarines.",
            image_hint="deep ocean submarine",
            api_key="dummy",
        )

    assert result["ok"] is False
    assert "clinton" in result["reason"].lower() or "poster" in result["reason"].lower()
    assert result["cost_usd"] > 0.0


# ---------------------------------------------------------------------- #
# Soft-fail conditions: every infra failure must keep the pipeline alive
# ---------------------------------------------------------------------- #


def test_validate_soft_passes_when_api_key_empty(monkeypatch):
    """No API key -> ok=True, no Anthropic call made.

    The pipeline must keep working on a developer machine without
    credentials; validation is additive only.
    """
    fake_client = MagicMock()
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    with TemporaryDirectory() as td:
        p = _write_fake_image(Path(td))
        result = validate_entity_image(
            image_url=str(p),
            claim_text="anything",
            image_hint="whatever",
            api_key="",
        )

    assert result["ok"] is True
    assert result["reason"] == "api_key_missing"
    assert result["cost_usd"] == 0.0
    fake_client.messages.create.assert_not_called()


def test_validate_soft_passes_on_anthropic_connection_error(monkeypatch):
    """Network / 5xx / timeout -> ok=True (soft-fail) with reason captured."""
    fake_client = MagicMock()
    fake_client.messages.create.side_effect = ConnectionError("upstream 503")
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    with TemporaryDirectory() as td:
        p = _write_fake_image(Path(td))
        result = validate_entity_image(
            image_url=str(p),
            claim_text="claim",
            image_hint="hint",
            api_key="dummy",
        )

    assert result["ok"] is True
    assert result["reason"].startswith("api_error:")
    assert "503" in result["reason"] or "upstream" in result["reason"]


def test_validate_soft_passes_on_malformed_json(monkeypatch):
    """Model returns nonsense -> ok=True (resilient parse failure)."""
    res = MagicMock()
    res.content = [MagicMock()]
    res.content[0].text = "this is not JSON at all"
    res.usage.input_tokens = 50
    res.usage.output_tokens = 20

    fake_client = MagicMock()
    fake_client.messages.create.return_value = res
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    with TemporaryDirectory() as td:
        p = _write_fake_image(Path(td))
        result = validate_entity_image(
            image_url=str(p),
            claim_text="claim",
            image_hint="hint",
            api_key="dummy",
        )

    assert result["ok"] is True
    assert result["reason"].startswith("parse_failed:")
    # Cost was still incurred because the API call did happen.
    assert result["cost_usd"] > 0.0


# ---------------------------------------------------------------------- #
# Cache: same URL twice in one session reuses the result
# ---------------------------------------------------------------------- #


def test_validate_cache_reuses_result_for_same_url(monkeypatch):
    """Cache hit -> no second Anthropic call for same image URL."""
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_haiku_response({
        "matches": True,
        "confidence": 0.8,
        "reason": "ok",
    })
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    cache: dict[str, dict] = {}
    with TemporaryDirectory() as td:
        p = _write_fake_image(Path(td))
        url = str(p)
        first = validate_entity_image(
            image_url=url, claim_text="x", image_hint="y",
            api_key="dummy", cache=cache,
        )
        second = validate_entity_image(
            image_url=url, claim_text="x", image_hint="y",
            api_key="dummy", cache=cache,
        )

    assert first == second
    assert fake_client.messages.create.call_count == 1
    assert url in cache


# ---------------------------------------------------------------------- #
# Cost reporting: matches Haiku 4.5 pricing ($1 in / $5 out per 1M tokens)
# ---------------------------------------------------------------------- #


def test_validate_reports_cost_at_haiku_4_5_pricing(monkeypatch):
    """1000 input / 100 output tokens -> 0.001 + 0.0005 = $0.0015."""
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_haiku_response(
        {"matches": True, "confidence": 0.7, "reason": "ok"},
        in_tokens=1000,
        out_tokens=100,
    )
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    with TemporaryDirectory() as td:
        p = _write_fake_image(Path(td))
        result = validate_entity_image(
            image_url=str(p),
            claim_text="x",
            image_hint="y",
            api_key="dummy",
        )

    expected = 1000 / 1_000_000 * 1.00 + 100 / 1_000_000 * 5.00
    assert abs(result["cost_usd"] - expected) < 1e-9


# ---------------------------------------------------------------------- #
# Auxiliary unit checks
# ---------------------------------------------------------------------- #


def test_detect_media_type_recognises_png_jpeg_webp():
    """Magic-byte detection covers the formats Wikimedia returns."""
    assert _detect_media_type(_PNG_HEADER + b"\x00") == "image/png"
    assert _detect_media_type(_JPEG_HEADER + b"\x00") == "image/jpeg"
    # WebP requires 'WEBP' at offset 8 after RIFF prefix.
    webp = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00"
    assert _detect_media_type(webp) == "image/webp"
    # Unknown bytes default to JPEG (Anthropic will reject if invalid).
    assert _detect_media_type(b"random") == "image/jpeg"


def test_parse_response_handles_low_confidence_negative():
    """Low confidence on a negative still parses correctly."""
    raw = json.dumps({
        "matches": False, "confidence": 0.42, "reason": "uncertain",
    })
    matches, conf, reason = _parse_response(raw)
    assert matches is False
    assert conf == 0.42
    assert reason == "uncertain"


def test_parse_response_clamps_confidence_into_range():
    """Confidence >1.0 is clamped to 1.0; <0.0 to 0.0."""
    raw_high = json.dumps({
        "matches": True, "confidence": 5.0, "reason": "way too high",
    })
    _, conf_high, _ = _parse_response(raw_high)
    assert conf_high == 1.0

    raw_low = json.dumps({
        "matches": False, "confidence": -1.0, "reason": "negative",
    })
    _, conf_low, _ = _parse_response(raw_low)
    assert conf_low == 0.0


def test_validate_handles_remote_url_fetch(monkeypatch):
    """HTTP URL path: bytes fetched via requests, then validated."""
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_haiku_response({
        "matches": True, "confidence": 0.85, "reason": "match",
    })
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    class _FakeResp:
        def raise_for_status(self): pass
        def iter_content(self, chunk_size):
            yield _PNG_HEADER + b"\x00" * 200

    with patch("src.research.entity_image_validator.requests.get", return_value=_FakeResp()):
        result = validate_entity_image(
            image_url="https://upload.wikimedia.org/test.png",
            claim_text="claim",
            image_hint="hint",
            api_key="dummy",
        )

    assert result["ok"] is True
    assert result["confidence"] >= 0.8


def test_validate_soft_passes_when_remote_fetch_fails(monkeypatch):
    """Network failure on image fetch -> soft-pass, no Anthropic call."""
    fake_client = MagicMock()
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    with patch(
        "src.research.entity_image_validator.requests.get",
        side_effect=ConnectionError("dns failure"),
    ):
        result = validate_entity_image(
            image_url="https://example.invalid/missing.png",
            claim_text="claim",
            image_hint="hint",
            api_key="dummy",
        )

    assert result["ok"] is True
    assert result["reason"] == "fetch_failed"
    fake_client.messages.create.assert_not_called()
