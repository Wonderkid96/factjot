"""Regression tests for the IG-compliant thumbnail JPEG step.

Phase E.4 promised "one asset, two surfaces" but only the YouTube side
ever did the PNG -> JPEG conversion. The IG side uploaded the rendered
PNG (~3.3MB) as `cover_url`, which IG silently discards because Reels
cover_url accepts JPEG only and is hard-capped at ~0.5MB. The reel
posted with no custom cover; IG fell back to an auto-extracted frame.

`_shrink_thumbnail_to_ig_jpeg` is the structural fix: render the overlay
once as PNG, emit ONE IG-compliant JPEG (<= 450KB), feed that single
artefact to both surfaces. These tests pin the invariant so a future
"simplification" cannot quietly remove the size cap, drop the format
conversion, or swap the upload back to the PNG path.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from PIL import Image

from pipelines.reel.make_reel import (
    _IG_COVER_TARGET_BYTES,
    _shrink_thumbnail_to_ig_jpeg,
)


def _write_overlay_png(path: Path) -> None:
    """Write a 1080x1920 PNG sized comparably to a real reel overlay.

    Uses 8x8 random-block noise: structured enough that JPEG quantises
    it well, unstructured enough that PNG cannot trivially deflate it.
    The combination puts the input PNG in the multi-MB range that real
    overlays produce while keeping the JPEG output in the few-hundred-KB
    range that exercises the size cap meaningfully. Pure pixel-level
    random noise would be JPEG-incompressible; pure gradients would be
    PNG-trivial. This sits in between.
    """
    import os
    block = 8
    cols, rows = 1080 // block, 1920 // block
    block_bytes = os.urandom(cols * rows * 3)
    block_img = Image.frombytes("RGB", (cols, rows), block_bytes)
    base = block_img.resize((1080, 1920), Image.NEAREST)
    base.save(path, format="PNG", optimize=False)


def test_shrink_emits_jpeg_under_ig_cap() -> None:
    """Output must be a JPEG, <= the IG cap, and 1080x1920.

    The size cap is the load-bearing assertion: IG silently drops covers
    over ~0.5MB. Format matters too — IG accepts JPEG only and discards
    any other format without raising. Dimensions matter because the rest
    of the pipeline assumes 9:16 at 1080 wide.
    """
    with TemporaryDirectory() as td:
        td_path = Path(td)
        src = td_path / "thumbnail.png"
        dst = td_path / "thumbnail.jpg"
        _write_overlay_png(src)

        _shrink_thumbnail_to_ig_jpeg(src, dst)

        assert dst.exists(), "JPEG output missing"
        assert dst.stat().st_size <= _IG_COVER_TARGET_BYTES, (
            f"JPEG {dst.stat().st_size}B exceeds IG cap "
            f"{_IG_COVER_TARGET_BYTES}B; IG would silently drop the cover"
        )
        magic = dst.read_bytes()[:3]
        assert magic == b"\xff\xd8\xff", (
            f"output is not a JPEG; magic={magic!r}. IG cover_url accepts "
            "JPEG only and discards everything else."
        )
        with Image.open(dst) as im:
            assert im.size == (1080, 1920), (
                f"JPEG dimensions drifted to {im.size}; IG cover expects 9:16 "
                "and the rest of the pipeline assumes 1080x1920"
            )


def test_ig_cover_target_under_meta_hard_cap() -> None:
    """IG Reels cover_url hard cap is ~0.5MB. Pin our target below it.

    A future edit that raises `_IG_COVER_TARGET_BYTES` past the Meta cap
    would reintroduce the silent-drop behaviour. This test fails loudly
    rather than letting that change land.
    """
    META_HARD_CAP = 500 * 1024
    assert _IG_COVER_TARGET_BYTES < META_HARD_CAP, (
        f"_IG_COVER_TARGET_BYTES={_IG_COVER_TARGET_BYTES} is at or above "
        f"Meta's ~{META_HARD_CAP}B cover_url hard cap; IG will silently "
        "discard the cover and fall back to an auto-extracted frame"
    )


def test_shrink_raises_when_pillow_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Failure must be loud, not silent.

    The previous behaviour was: skip the PNG->JPEG conversion entirely
    when Pillow was missing, hand IG a 3.3MB PNG, watch IG drop the
    cover. The replacement is a hard error so the workflow surfaces the
    problem instead of publishing a coverless reel.
    """
    import builtins
    real_import = builtins.__import__

    def fake_import(name: str, *args, **kwargs):
        if name == "PIL":
            raise ImportError("simulated missing Pillow")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with TemporaryDirectory() as td:
        src = Path(td) / "thumbnail.png"
        dst = Path(td) / "thumbnail.jpg"
        src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        with pytest.raises(RuntimeError, match="Pillow"):
            _shrink_thumbnail_to_ig_jpeg(src, dst)
