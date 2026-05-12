"""Tests for beat-aware type-match scoring in _collect_beat_candidates."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

import src.research.video_finder as vf


def _make_file(tmp: Path, name: str, ext: str) -> Path:
    p = tmp / f"{name}{ext}"
    p.write_bytes(b"\x00" * 100)
    return p


def _run_collect(tmp: Path, media_path: Path, beat_idx: int) -> list[vf._Candidate]:
    """Run _collect_beat_candidates with mocked source and quality functions."""
    out_dir = tmp / f"out_{beat_idx}_{media_path.stem}"
    out_dir.mkdir(parents=True, exist_ok=True)
    with (
        patch.object(vf, "_try_all_sources", return_value=media_path),
        patch.object(vf, "_visual_quality_delta", return_value=0.0),
    ):
        return vf._collect_beat_candidates(
            queries=["war battle"],
            beat_idx=beat_idx,
            topic="history",
            out_dir=out_dir,
            used_source_urls=set(),
            used_paths=set(),
            blocked_stems=set(),
        )


@pytest.mark.parametrize("beat_idx,is_video,expected_bonus", [
    (0, False, 0.04),   # still on ESTABLISHING
    (0, True,  0.00),   # video on ESTABLISHING
    (1, True,  0.08),   # video on SUBJECT
    (1, False, 0.00),   # still on SUBJECT
    (2, True,  0.08),   # video on DETAIL
    (2, False, 0.00),   # still on DETAIL
    (3, True,  0.08),   # video on CONSEQUENCE
    (3, False, 0.00),   # still on CONSEQUENCE
    (4, True,  0.04),   # video on ATMOSPHERE
    (4, False, 0.00),   # still on ATMOSPHERE
])
def test_type_bonus_truth_table(beat_idx: int, is_video: bool, expected_bonus: float) -> None:
    with TemporaryDirectory() as td:
        tmp = Path(td)
        ext = ".mp4" if is_video else ".jpg"
        media = _make_file(tmp, "media", ext)
        results = _run_collect(tmp, media, beat_idx)
        assert results, f"expected a candidate for beat={beat_idx} {'video' if is_video else 'still'}"
        expected_score = min(1.0, 0.90 + expected_bonus)  # base 0.90 (query index 0) + type_bonus
        assert results[0].score == pytest.approx(expected_score, abs=1e-6), (
            f"beat {beat_idx} {'video' if is_video else 'still'}: "
            f"expected {expected_score:.3f}, got {results[0].score:.3f}"
        )


def test_video_beat1_outscores_still_beat1() -> None:
    with TemporaryDirectory() as td:
        tmp = Path(td)
        video = _make_file(tmp, "clip", ".mp4")
        still = _make_file(tmp, "img", ".jpg")
        video_results = _run_collect(tmp, video, 1)
        still_results = _run_collect(tmp, still, 1)
        assert video_results and still_results
        assert video_results[0].score > still_results[0].score


def test_still_beat0_outscores_video_beat0() -> None:
    with TemporaryDirectory() as td:
        tmp = Path(td)
        still = _make_file(tmp, "img", ".png")
        video = _make_file(tmp, "clip", ".mp4")
        still_results = _run_collect(tmp, still, 0)
        video_results = _run_collect(tmp, video, 0)
        assert still_results and video_results
        assert still_results[0].score > video_results[0].score
