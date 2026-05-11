"""Tests for the ThumbnailUnavailable sentinel exception.

Behavioural contract: the thumbnail picker raises a class-specific
exception (ThumbnailUnavailable) instead of a generic RuntimeError
when it cannot produce any frame. Back-compat is preserved because
ThumbnailUnavailable subclasses RuntimeError - existing `except
RuntimeError` catches still fire. New callers can match the sentinel
specifically and recover (ship reel without custom cover).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.render.thumbnail_picker import (  # noqa: E402
    ThumbnailUnavailable,
    pick_best_thumbnail,
)


def test_sentinel_subclasses_runtimeerror():
    """Existing `except RuntimeError` in make_reel must still catch it."""
    assert issubclass(ThumbnailUnavailable, RuntimeError)


def test_empty_footage_clips_raises_sentinel(tmp_path):
    """The fast path: empty clip list -> ThumbnailUnavailable, not generic RuntimeError."""
    with pytest.raises(ThumbnailUnavailable, match="empty footage_clips"):
        pick_best_thumbnail(
            footage_clips=[],
            claim="anything",
            reel_title="anything",
            api_key="",
            candidate_dir=tmp_path,
            ffmpeg_bin="/usr/bin/ffmpeg",
        )


def test_empty_footage_clips_still_catchable_as_runtimeerror(tmp_path):
    """A caller using `except RuntimeError` (the existing pattern in
    make_reel.py) still catches the sentinel.
    """
    try:
        pick_best_thumbnail(
            footage_clips=[],
            claim="x",
            reel_title="x",
            api_key="",
            candidate_dir=tmp_path,
            ffmpeg_bin="/usr/bin/ffmpeg",
        )
    except RuntimeError:
        pass  # expected
    else:
        pytest.fail("expected RuntimeError (via ThumbnailUnavailable subclass)")


def test_sentinel_message_carries_through():
    """The sentinel must carry a useful message for the workflow log."""
    exc = ThumbnailUnavailable("some specific reason")
    assert "some specific reason" in str(exc)
