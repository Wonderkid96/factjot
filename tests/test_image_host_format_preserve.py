"""Regression tests for ImgbbHost format-preservation.

Behavioural contract: the bytes uploaded to imgbb must match the
source file's format. JPEG in -> JPEG bytes out. PNG in -> PNG bytes
out (with a salt chunk).

Pre-Phase-L-thumbnail-fix, `_salted_png_bytes` opened any input with
Pillow and re-saved as PNG, silently converting reel thumbnail JPEGs
to PNG. imgbb returned a `.png` URL, IG Reels rejected the cover
(JPEG only), and reels shipped with auto-picked frames instead of
the branded thumbnail. The bug was invisible because the upload
returned a valid URL - it just wasn't a valid IG cover URL.

These tests pin the format contract so the regression cannot recur
even if the salt logic is refactored.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.publish.image_host import ImgbbHost  # noqa: E402


# Magic-byte signatures for format detection.
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"


def _make_png(path: Path) -> None:
    from PIL import Image
    Image.new("RGB", (32, 32), color=(255, 0, 0)).save(path, "PNG")


def _make_jpeg(path: Path) -> None:
    from PIL import Image
    Image.new("RGB", (32, 32), color=(0, 255, 0)).save(path, "JPEG", quality=85)


# ----- format preservation ------------------------------------------

def test_jpeg_in_jpeg_out(tmp_path):
    """A `.jpg` file's bytes go to imgbb unmodified."""
    src = tmp_path / "thumbnail.jpg"
    _make_jpeg(src)
    out = ImgbbHost._bytes_for_upload(src)
    assert out.startswith(_JPEG_MAGIC), (
        f"expected JPEG bytes, got {out[:8]!r}"
    )
    # Raw passthrough: bytes must equal the source file.
    assert out == src.read_bytes()


def test_jpeg_with_jpeg_extension_in_jpeg_out(tmp_path):
    """`.jpeg` (long extension) is also routed as JPEG."""
    src = tmp_path / "thumbnail.jpeg"
    _make_jpeg(src)
    out = ImgbbHost._bytes_for_upload(src)
    assert out.startswith(_JPEG_MAGIC)
    assert out == src.read_bytes()


def test_png_in_png_out(tmp_path):
    """A `.png` file is re-encoded as PNG with a salt chunk."""
    src = tmp_path / "cover.png"
    _make_png(src)
    out = ImgbbHost._bytes_for_upload(src)
    assert out.startswith(_PNG_MAGIC), (
        f"expected PNG bytes, got {out[:8]!r}"
    )
    # The salt re-encode means bytes do NOT match the raw source.
    # That is by design: imgbb's dedupe needs a unique content hash.
    assert out != src.read_bytes()


def test_png_salt_is_unique_per_call(tmp_path):
    """Two calls on the same PNG yield different bytes (salt rotates)."""
    src = tmp_path / "cover.png"
    _make_png(src)
    a = ImgbbHost._bytes_for_upload(src)
    b = ImgbbHost._bytes_for_upload(src)
    assert a != b, "salt must rotate between calls so imgbb dedupe gives a fresh URL"


def test_unknown_extension_passes_through_raw(tmp_path):
    """A non-PNG, non-JPEG file uploads raw (no re-encoding attempt)."""
    src = tmp_path / "weird.bin"
    src.write_bytes(b"\x00\x01\x02\x03not-an-image")
    out = ImgbbHost._bytes_for_upload(src)
    assert out == src.read_bytes()


# ----- back-compat alias --------------------------------------------

def test_legacy_method_name_still_works(tmp_path):
    """`_salted_png_bytes` is kept as an alias for one cycle so any
    external caller that imported the old name does not break.
    """
    src = tmp_path / "cover.png"
    _make_png(src)
    out = ImgbbHost._salted_png_bytes(src)
    assert out.startswith(_PNG_MAGIC)


# ----- the bug we are pinning ---------------------------------------

def test_regression_jpeg_input_never_becomes_png_output(tmp_path):
    """The 2026-05-11 reel-cover bug: a JPEG was silently re-encoded
    as PNG, breaking IG Reels covers. This test pins that JPEG bytes
    in MUST produce JPEG bytes out, never PNG.
    """
    src = tmp_path / "ig_thumbnail.jpg"
    _make_jpeg(src)
    out = ImgbbHost._bytes_for_upload(src)
    # The hardest possible assertion: the output must NOT have the PNG
    # signature. A passing test means the conversion-to-PNG bug is
    # genuinely closed, not papered over.
    assert not out.startswith(_PNG_MAGIC), (
        "JPEG input must never produce PNG bytes - this is the regression"
    )
    assert out.startswith(_JPEG_MAGIC)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
