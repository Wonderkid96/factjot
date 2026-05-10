"""Cover-slide typography variant: empty `photo_data_url` must branch to a
deliberate full-canvas typography layout, not a `background:url("")` declaration.

Covers Phase E.2 of the audit (P0 #3): the cover renderer previously templated
`background:url("{photo_data_url}")` with no branch on empty string, so the
list typography fallback rendered as a near-black canvas with no spec-mandated
typography. See `SPEC_IMAGE_PIPELINE.md` sections 11 and 12.

These tests exercise the pure HTML builders only; no browser/Playwright is
involved. The screenshot path is covered by the visual smoke check called out
in the implementation report.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from pipelines.news.ship_news_post import (
    _is_empty_photo_url,
    build_cover_html,
    build_story_frame_html,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------- #
# _is_empty_photo_url helper
# ---------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "value,expected",
    [
        ("", True),
        ("   ", True),
        (None, True),
        ("data:image/png;base64,", True),
        ("data:image/png;base64,   ", True),
        ("data:", True),
        ("data:image/png;base64,iVBORw0KGgoAAAA", False),
        ("https://example.com/cover.jpg", False),
    ],
)
def test_is_empty_photo_url(value, expected):
    assert _is_empty_photo_url(value) is expected


# ---------------------------------------------------------------------- #
# Typography variant: empty photo data URL
# ---------------------------------------------------------------------- #


def test_typography_variant_compact_legacy_no_empty_url():
    html = build_cover_html(
        cover_title="Five things",
        source_label="LIST",
        photo_data_url="",
        index=1,
        total=6,
        repo_root=REPO_ROOT,
        layout_mode="compact_legacy",
    )
    # Hard rule from CLAUDE.md sect 1.5: no empty image boxes ever.
    assert 'background:url("")' not in html
    assert "background:url('')" not in html
    # Typography variant must include the title and the accent rule.
    assert "Five things" in html
    assert "accent-rule" in html
    # And the label pill, with our spec tracking.
    assert "letter-spacing:0.08em" in html
    # INK ground for compact_legacy.
    assert "--bg:#0A0A0A" in html
    # The factjot mark is already white on transparent, so on INK we
    # render it without a filter (nothing to invert). The PAPER variant
    # is the one that needs `brightness(0)` to flatten white to black.
    assert "brightness(0)" not in html


def test_typography_variant_readable_list_uses_paper_ground():
    html = build_cover_html(
        cover_title="Five obscure 12th-century Latin manuscripts",
        source_label="LIST",
        photo_data_url="",
        index=1,
        total=6,
        repo_root=REPO_ROOT,
        layout_mode="readable_list",
    )
    assert 'background:url("")' not in html
    assert "background:url('')" not in html
    # PAPER ground for readable_list per spec section 12.
    assert "--bg:#F4F1E9" in html
    # INK type for readable_list.
    assert "--ink:#0A0A0A" in html
    # Wordmark goes dark on PAPER via `brightness(0)` (the asset is
    # white-on-transparent, so it would otherwise blend in).
    assert "filter:brightness(0);" in html
    # No invert filter on the PAPER variant.
    assert "brightness(0) invert(1)" not in html
    # Red accent rule still present.
    assert "background:var(--accent)" in html
    assert "Five obscure 12th-century Latin manuscripts" in html


def test_typography_variant_handles_zero_byte_data_url():
    """A `data:` URL with no payload must trigger the typography branch."""
    html = build_cover_html(
        cover_title="Edge case",
        source_label="TEST",
        photo_data_url="data:image/png;base64,",
        index=1,
        total=6,
        repo_root=REPO_ROOT,
        layout_mode="compact_legacy",
    )
    assert "data:image/png;base64," not in re.findall(
        r'background:url\("([^"]*)"\)', html
    )
    assert "Edge case" in html
    assert "accent-rule" in html


def test_typography_variant_handles_empty_title_and_label():
    html = build_cover_html(
        cover_title="",
        source_label="",
        photo_data_url="",
        index=1,
        total=6,
        repo_root=REPO_ROOT,
        layout_mode="compact_legacy",
    )
    # Sensible defaults rather than a blank pane.
    assert "factjot" in html
    assert "FACTJOT" in html
    # No empty url.
    assert 'background:url("")' not in html


# ---------------------------------------------------------------------- #
# Photo variant: existing behaviour preserved
# ---------------------------------------------------------------------- #


_TINY_PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


def test_photo_variant_unchanged_when_url_present_compact_legacy():
    html = build_cover_html(
        cover_title="With a real photo",
        source_label="NEWS",
        photo_data_url=_TINY_PNG_DATA_URL,
        index=1,
        total=8,
        repo_root=REPO_ROOT,
        layout_mode="compact_legacy",
    )
    # The existing photo template includes the `.photo` background-url and a
    # bottom-darken gradient. The typography variant has neither.
    assert ".photo{position:absolute;inset:0;background:url(" in html
    assert _TINY_PNG_DATA_URL in html
    assert "bottom-darken" in html
    # Typography-only marker absent (the typography variant has its own
    # `accent-rule` element class that the photo variant does not use).
    assert "accent-rule" not in html


def test_photo_variant_unchanged_when_url_present_readable_list():
    html = build_cover_html(
        cover_title="Five great photos",
        source_label="LIST",
        photo_data_url=_TINY_PNG_DATA_URL,
        index=1,
        total=6,
        repo_root=REPO_ROOT,
        layout_mode="readable_list",
    )
    # Today readable_list cover reuses the compact_legacy photo template
    # (the readable_list profile only changes content-slide layout). The
    # photo URL must still be present.
    assert _TINY_PNG_DATA_URL in html
    assert "bottom-darken" in html
    assert "accent-rule" not in html


# ---------------------------------------------------------------------- #
# Story frame: typography_cover flag avoids blurred flat ground
# ---------------------------------------------------------------------- #


def test_story_frame_photo_cover_uses_blurred_background():
    html = build_story_frame_html(
        cover_url=_TINY_PNG_DATA_URL,
        serif_url="",
        mono_url="",
        layout_mode="compact_legacy",
        typography_cover=False,
    )
    assert ".bg-blur" in html
    assert _TINY_PNG_DATA_URL in html


def test_story_frame_typography_cover_compact_legacy_uses_ink_flat():
    html = build_story_frame_html(
        cover_url=_TINY_PNG_DATA_URL,
        serif_url="",
        mono_url="",
        layout_mode="compact_legacy",
        typography_cover=True,
    )
    # No blurred background layer, just a flat INK ground behind the slide card.
    assert ".bg-blur" not in html
    assert ".bg-flat{position:absolute;inset:0;background:#0A0A0A" in html
    # The slide card itself still references the cover PNG.
    assert _TINY_PNG_DATA_URL in html


def test_story_frame_typography_cover_readable_list_uses_paper_flat():
    html = build_story_frame_html(
        cover_url=_TINY_PNG_DATA_URL,
        serif_url="",
        mono_url="",
        layout_mode="readable_list",
        typography_cover=True,
    )
    assert ".bg-blur" not in html
    assert ".bg-flat{position:absolute;inset:0;background:#F4F1E9" in html
    assert _TINY_PNG_DATA_URL in html
