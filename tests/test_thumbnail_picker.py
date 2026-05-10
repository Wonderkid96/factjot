"""Tests for src.render.thumbnail_picker (Phase E.4).

The picker extracts up to 3 candidate frames from the footage list, scores
each one with Haiku 4.5 vision, and returns the strongest. Soft-fall path
covers the developer-without-credentials case and any Anthropic infra
failure: the pipeline must never fail just because the picker cannot reach
the API.

Tests mock both subprocess.run (FFmpeg) and the Anthropic client. Frame
files are created with a real PNG magic-byte header so the media-type
detector picks the right MIME and the soft-fall path triggers based on
the right signal (rather than a fake bytes-too-small error).

NOTE: every assertion that touches a file lives INSIDE the
TemporaryDirectory context manager. The chosen path is on a temp dir that
gets removed when the `with` block exits; assertions outside the block
fail with "no such file or directory" through no fault of the picker.
"""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

import pytest

from src.render.thumbnail_picker import (
    _detect_media_type,
    _parse_score_response,
    _plan_candidates,
    pick_best_thumbnail,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


_PNG_HEADER = b"\x89PNG\r\n\x1a\n"
_JPEG_HEADER = b"\xff\xd8\xff\xe0\x00\x10JFIF"


def _write_fake_frame(dir_path: Path, *, name: str = "frame.png") -> Path:
    """Write a fake but valid-looking PNG. Big enough to clear the size floor."""
    p = dir_path / name
    p.write_bytes(_PNG_HEADER + b"\x00" * 4096)
    return p


def _write_fake_clip(dir_path: Path, *, name: str = "clip.mp4") -> Path:
    """Write a fake video file. Contents do not matter; the FFmpeg call is mocked."""
    p = dir_path / name
    p.write_bytes(b"\x00" * 1024)
    return p


def _mock_haiku_score(score: int, reason: str = "ok",
                      in_tokens: int = 200, out_tokens: int = 30) -> MagicMock:
    """Fake Anthropic SDK response carrying a score JSON payload."""
    res = MagicMock()
    res.content = [MagicMock()]
    res.content[0].text = json.dumps({"score": score, "reason": reason})
    res.usage.input_tokens = in_tokens
    res.usage.output_tokens = out_tokens
    return res


def _patch_extract_writes_png(monkeypatch):
    """Replace _extract_frame so calls write a real-looking PNG and return True.

    The picker's own frame-extraction code shells out to FFmpeg, which is
    not available in the test runner. We side-step that with a stub that
    materialises a small PNG at the requested out_path.
    """
    def _fake_extract(ffmpeg_bin, clip, seek_seconds, out_path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(_PNG_HEADER + b"\x00" * 4096)
        return True
    monkeypatch.setattr(
        "src.render.thumbnail_picker._extract_frame", _fake_extract,
    )


def _patch_probe_duration(monkeypatch, seconds: float = 10.0):
    """Stub the FFmpeg duration probe to return a fixed value."""
    monkeypatch.setattr(
        "src.render.thumbnail_picker._probe_duration_s",
        lambda ffmpeg_bin, clip: seconds,
    )


# --------------------------------------------------------------------------- #
# 1. Three candidates extracted from three clips
# --------------------------------------------------------------------------- #


def test_pick_extracts_three_candidates_from_three_clips(monkeypatch):
    """With 3 clips the picker spreads candidates across first/middle/last."""
    _patch_probe_duration(monkeypatch, 10.0)
    _patch_extract_writes_png(monkeypatch)

    fake_client = MagicMock()
    fake_client.messages.create.side_effect = [
        _mock_haiku_score(6),
        _mock_haiku_score(8),
        _mock_haiku_score(7),
    ]
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    with TemporaryDirectory() as td:
        td_path = Path(td)
        clips = [
            _write_fake_clip(td_path, name=f"clip_{i}.mp4")
            for i in range(3)
        ]
        cand_dir = td_path / "thumb_candidates"
        chosen, meta = pick_best_thumbnail(
            footage_clips=clips,
            claim="x",
            reel_title="y",
            api_key="dummy",
            candidate_dir=cand_dir,
            ffmpeg_bin="ffmpeg",
        )

        assert len(meta["candidates"]) == 3
        assert fake_client.messages.create.call_count == 3
        # Highest score = 8; chosen frame is the c1@50% candidate.
        assert chosen.exists()
        assert "c1@50" in chosen.name


# --------------------------------------------------------------------------- #
# 2. Returns the highest-scored candidate
# --------------------------------------------------------------------------- #


def test_pick_returns_highest_scored_candidate(monkeypatch):
    """Of three candidates the highest-scored one wins."""
    _patch_probe_duration(monkeypatch, 8.0)
    _patch_extract_writes_png(monkeypatch)

    # Order: 5, 9, 4 -> the middle one (c1@50%) wins.
    fake_client = MagicMock()
    fake_client.messages.create.side_effect = [
        _mock_haiku_score(5, reason="ok mid"),
        _mock_haiku_score(9, reason="strong subject"),
        _mock_haiku_score(4, reason="dull"),
    ]
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    with TemporaryDirectory() as td:
        td_path = Path(td)
        clips = [
            _write_fake_clip(td_path, name="a.mp4"),
            _write_fake_clip(td_path, name="b.mp4"),
            _write_fake_clip(td_path, name="c.mp4"),
        ]
        chosen, meta = pick_best_thumbnail(
            footage_clips=clips,
            claim="claim",
            reel_title="title",
            api_key="dummy",
            candidate_dir=td_path / "cands",
            ffmpeg_bin="ffmpeg",
        )

        assert chosen.exists()
        # The chosen candidate's score field is 9.
        chosen_meta = next(c for c in meta["candidates"] if Path(c["frame"]) == chosen)
        assert chosen_meta["score"] == 9
        assert "strong" in chosen_meta["reason"].lower()


# --------------------------------------------------------------------------- #
# 3. Soft-fall to footage_clips[0] first frame when api_key is empty
# --------------------------------------------------------------------------- #


def test_pick_soft_falls_when_api_key_empty(monkeypatch):
    """No API key -> first extracted candidate, no Anthropic call made."""
    _patch_probe_duration(monkeypatch, 10.0)
    _patch_extract_writes_png(monkeypatch)

    fake_client = MagicMock()
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    with TemporaryDirectory() as td:
        td_path = Path(td)
        clips = [
            _write_fake_clip(td_path, name=f"c{i}.mp4") for i in range(3)
        ]
        chosen, meta = pick_best_thumbnail(
            footage_clips=clips,
            claim="x",
            reel_title="y",
            api_key="",
            candidate_dir=td_path / "cands",
            ffmpeg_bin="ffmpeg",
        )

        assert chosen.exists()
        fake_client.messages.create.assert_not_called()
        assert meta["fallback_reason"] == "api_key_missing"
        assert meta["total_cost_usd"] == 0.0


# --------------------------------------------------------------------------- #
# 4. Soft-fall when Anthropic raises a connection error on every call
# --------------------------------------------------------------------------- #


def test_pick_soft_falls_when_anthropic_errors_everywhere(monkeypatch):
    """Every Haiku call fails -> picker still returns a candidate."""
    _patch_probe_duration(monkeypatch, 10.0)
    _patch_extract_writes_png(monkeypatch)

    fake_client = MagicMock()
    fake_client.messages.create.side_effect = ConnectionError("upstream 503")
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    with TemporaryDirectory() as td:
        td_path = Path(td)
        clips = [
            _write_fake_clip(td_path, name=f"c{i}.mp4") for i in range(3)
        ]
        chosen, meta = pick_best_thumbnail(
            footage_clips=clips,
            claim="x",
            reel_title="y",
            api_key="dummy",
            candidate_dir=td_path / "cands",
            ffmpeg_bin="ffmpeg",
        )

        assert chosen.exists()
        assert meta["fallback_reason"] == "all_haiku_calls_failed"
        # All three Haiku calls were attempted, all failed -> all scores None.
        assert all(c["score"] is None for c in meta["candidates"])
        assert all("api_error" in c["reason"] for c in meta["candidates"])


# --------------------------------------------------------------------------- #
# 5. Fewer than 3 clips: handle gracefully (planner duplicates or splits time)
# --------------------------------------------------------------------------- #


def test_pick_handles_two_clips_gracefully(monkeypatch):
    """With 2 clips the planner returns 3 plans (clip0/clip1/clip0) at varied seeks."""
    _patch_probe_duration(monkeypatch, 10.0)
    _patch_extract_writes_png(monkeypatch)

    fake_client = MagicMock()
    fake_client.messages.create.side_effect = [
        _mock_haiku_score(5),
        _mock_haiku_score(9),
        _mock_haiku_score(6),
    ]
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    with TemporaryDirectory() as td:
        td_path = Path(td)
        clips = [
            _write_fake_clip(td_path, name="a.mp4"),
            _write_fake_clip(td_path, name="b.mp4"),
        ]
        chosen, meta = pick_best_thumbnail(
            footage_clips=clips,
            claim="x",
            reel_title="y",
            api_key="dummy",
            candidate_dir=td_path / "cands",
            ffmpeg_bin="ffmpeg",
        )

        assert chosen.exists()
        assert len(meta["candidates"]) == 3
        # Best is c1@50% (score=9) -> clip b.mp4.
        chosen_meta = next(c for c in meta["candidates"] if Path(c["frame"]) == chosen)
        assert chosen_meta["score"] == 9


def test_pick_handles_single_clip(monkeypatch):
    """With 1 clip the planner extracts 3 different moments from it."""
    _patch_probe_duration(monkeypatch, 12.0)
    _patch_extract_writes_png(monkeypatch)

    fake_client = MagicMock()
    fake_client.messages.create.side_effect = [
        _mock_haiku_score(7),
        _mock_haiku_score(5),
        _mock_haiku_score(8),
    ]
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    with TemporaryDirectory() as td:
        td_path = Path(td)
        clips = [_write_fake_clip(td_path, name="solo.mp4")]
        chosen, meta = pick_best_thumbnail(
            footage_clips=clips,
            claim="x",
            reel_title="y",
            api_key="dummy",
            candidate_dir=td_path / "cands",
            ffmpeg_bin="ffmpeg",
        )

        assert chosen.exists()
        assert len(meta["candidates"]) == 3
        # All three candidates extracted from clip0.
        assert all(c["label"].startswith("c0@") for c in meta["candidates"])


# --------------------------------------------------------------------------- #
# 6. Cost reported at Haiku 4.5 vision pricing across 3 calls
# --------------------------------------------------------------------------- #


def test_pick_reports_cost_at_haiku_4_5_pricing(monkeypatch):
    """Cost = sum of per-call (input_tokens*$1/M + output_tokens*$5/M).

    Three calls at 1000 input + 100 output tokens each:
      per call = 1000/1M*1.00 + 100/1M*5.00 = 0.001 + 0.0005 = 0.0015
      total    = 0.0045 USD (< 0.5p per reel).
    """
    _patch_probe_duration(monkeypatch, 10.0)
    _patch_extract_writes_png(monkeypatch)

    fake_client = MagicMock()
    fake_client.messages.create.side_effect = [
        _mock_haiku_score(7, in_tokens=1000, out_tokens=100),
        _mock_haiku_score(8, in_tokens=1000, out_tokens=100),
        _mock_haiku_score(6, in_tokens=1000, out_tokens=100),
    ]
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    with TemporaryDirectory() as td:
        td_path = Path(td)
        clips = [_write_fake_clip(td_path, name=f"c{i}.mp4") for i in range(3)]
        _, meta = pick_best_thumbnail(
            footage_clips=clips,
            claim="x",
            reel_title="y",
            api_key="dummy",
            candidate_dir=td_path / "cands",
            ffmpeg_bin="ffmpeg",
        )

        expected_per_call = 1000 / 1_000_000 * 1.00 + 100 / 1_000_000 * 5.00
        assert abs(meta["total_cost_usd"] - 3 * expected_per_call) < 1e-6


# --------------------------------------------------------------------------- #
# 7. Vision call is capped at 3 calls per reel (cost control)
# --------------------------------------------------------------------------- #


def test_pick_caps_vision_calls_at_three(monkeypatch):
    """Even with 5 clips the picker calls Haiku at most 3 times (CLAUDE.md cap)."""
    _patch_probe_duration(monkeypatch, 10.0)
    _patch_extract_writes_png(monkeypatch)

    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_haiku_score(7)
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    with TemporaryDirectory() as td:
        td_path = Path(td)
        clips = [_write_fake_clip(td_path, name=f"c{i}.mp4") for i in range(5)]
        _, meta = pick_best_thumbnail(
            footage_clips=clips,
            claim="x",
            reel_title="y",
            api_key="dummy",
            candidate_dir=td_path / "cands",
            ffmpeg_bin="ffmpeg",
        )

        assert fake_client.messages.create.call_count == 3
        assert len(meta["candidates"]) == 3


# --------------------------------------------------------------------------- #
# 8. Empty footage_clips raises (cannot ship without a thumbnail)
# --------------------------------------------------------------------------- #


def test_pick_raises_on_empty_footage(monkeypatch):
    """No clips -> hard fail. The pipeline cannot ship a Reel without a cover."""
    with TemporaryDirectory() as td:
        td_path = Path(td)
        with pytest.raises(RuntimeError):
            pick_best_thumbnail(
                footage_clips=[],
                claim="x",
                reel_title="y",
                api_key="dummy",
                candidate_dir=td_path / "cands",
                ffmpeg_bin="ffmpeg",
            )


# --------------------------------------------------------------------------- #
# 9. Aux: planner builds plans for the right indexes
# --------------------------------------------------------------------------- #


def test_plan_candidates_three_clips_picks_first_middle_last(monkeypatch):
    """With 3 clips the planner targets indexes [0, 1, 2]."""
    monkeypatch.setattr(
        "src.render.thumbnail_picker._probe_duration_s",
        lambda ff, c: 10.0,
    )
    with TemporaryDirectory() as td:
        td_path = Path(td)
        clips = [_write_fake_clip(td_path, name=f"c{i}.mp4") for i in range(3)]
        plans = _plan_candidates(clips, ffmpeg_bin="ffmpeg")

        assert [p.clip.name for p in plans] == ["c0.mp4", "c1.mp4", "c2.mp4"]
        # Seek positions: 25%, 50%, 75% of 10s.
        assert plans[0].seek_seconds == pytest.approx(2.5, abs=0.01)
        assert plans[1].seek_seconds == pytest.approx(5.0, abs=0.01)
        assert plans[2].seek_seconds == pytest.approx(7.5, abs=0.01)


def test_plan_candidates_handles_still_images(monkeypatch):
    """Stills get seek=0 regardless of the chosen fraction."""
    monkeypatch.setattr(
        "src.render.thumbnail_picker._probe_duration_s",
        lambda ff, c: 0.0,  # still
    )
    with TemporaryDirectory() as td:
        td_path = Path(td)
        clips = [
            (td_path / f"img_{i}.jpg")
            for i in range(3)
        ]
        for c in clips:
            c.write_bytes(_JPEG_HEADER + b"\x00" * 200)
        plans = _plan_candidates(clips, ffmpeg_bin="ffmpeg")

        assert all(p.seek_seconds == 0.0 for p in plans)


# --------------------------------------------------------------------------- #
# 10. Aux: response parsing
# --------------------------------------------------------------------------- #


def test_parse_score_response_handles_valid_json():
    score, reason = _parse_score_response(json.dumps({"score": 7, "reason": "good"}))
    assert score == 7
    assert reason == "good"


def test_parse_score_response_clamps_score_into_range():
    high, _ = _parse_score_response(json.dumps({"score": 99, "reason": "x"}))
    low, _ = _parse_score_response(json.dumps({"score": -3, "reason": "x"}))
    assert high == 10
    assert low == 1


def test_parse_score_response_returns_none_on_invalid():
    assert _parse_score_response("nonsense")[0] is None
    assert _parse_score_response("")[0] is None
    assert _parse_score_response(json.dumps({"score": "abc"}))[0] is None


def test_detect_media_type_recognises_common_formats():
    assert _detect_media_type(_PNG_HEADER + b"\x00") == "image/png"
    assert _detect_media_type(_JPEG_HEADER + b"\x00") == "image/jpeg"
    webp = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00"
    assert _detect_media_type(webp) == "image/webp"
    # Default for unknown bytes -> PNG (renderer writes PNG).
    assert _detect_media_type(b"random") == "image/png"
