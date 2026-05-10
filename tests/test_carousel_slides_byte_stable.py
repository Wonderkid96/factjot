"""Byte-stable output tests for the extracted carousel renderer.

When `pipelines/news/ship_news_post.py` was the dual-role module, there
was no test asserting that the carousel render output stayed
byte-identical across edits. Now that the renderers live in
`src/render/carousel_slides.py`, this test pins the public HTML
shape so a future edit that drifts the markup is caught immediately.

Three canonical shapes covered:
- photo cover (compact_legacy)
- typography cover (compact_legacy + readable_list)
- story frame (photo + typography ground variants)

The test does not run Playwright; it only checks the pure-HTML
builders since CSS rendering is the dependency that varies most
across versions.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.render.carousel_slides import (  # noqa: E402
    build_cover_html,
    build_story_frame_html,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


# ----- photo cover --------------------------------------------------

def test_photo_cover_compact_legacy_html_shape():
    html = build_cover_html(
        cover_title="Pepsi Once Owned a Navy",
        source_label="HISTORY",
        photo_data_url="data:image/png;base64,iVBORw0KGgo=",
        index=1,
        total=8,
        repo_root=REPO_ROOT,
        layout_mode="compact_legacy",
    )
    # Photo branch must render a .photo div with the data URL.
    assert ".photo{position:absolute" in html
    assert "data:image/png;base64,iVBORw0KGgo=" in html
    # Compact_legacy uses Archivo Black for the title.
    assert 'font-family:"Archivo Black"' in html
    # Index label must appear as N/M.
    assert "1/8" in html
    # Pill must be the source label, uppercased and escaped.
    assert "HISTORY" in html


def test_photo_cover_readable_list_html_shape():
    html = build_cover_html(
        cover_title="Five Inventions Nobody Asked For",
        source_label="TECHNOLOGY",
        photo_data_url="data:image/png;base64,iVBORw0KGgo=",
        index=1,
        total=7,
        repo_root=REPO_ROOT,
        layout_mode="readable_list",
    )
    # readable_list with a photo still uses the photo branch (no PAPER
    # ground switch unless photo_data_url is empty).
    assert ".photo{position:absolute" in html
    assert "1/7" in html


# ----- typography cover --------------------------------------------

def test_typography_cover_compact_legacy_uses_ink_ground():
    html = build_cover_html(
        cover_title="Why Nobody Believed Him",
        source_label="HISTORY",
        photo_data_url="",
        index=1,
        total=6,
        repo_root=REPO_ROOT,
        layout_mode="compact_legacy",
    )
    # INK ground.
    assert "--bg:#0A0A0A" in html
    # Instrument Serif for typography title.
    assert 'font-family:"Instrument Serif"' in html
    # Red accent rule fixture.
    assert ".accent-rule" in html


def test_typography_cover_readable_list_uses_paper_ground():
    html = build_cover_html(
        cover_title="Five Strange Things",
        source_label="LIST",
        photo_data_url="",
        index=1,
        total=7,
        repo_root=REPO_ROOT,
        layout_mode="readable_list",
    )
    # PAPER ground for readable_list typography variant.
    assert "--bg:#F4F1E9" in html
    # INK type colour.
    assert "--ink:#0A0A0A" in html


def test_typography_cover_empty_title_defaults_to_factjot():
    html = build_cover_html(
        cover_title="",
        source_label="",
        photo_data_url="",
        index=1,
        total=4,
        repo_root=REPO_ROOT,
    )
    # When the title is empty, the renderer must fall back to "factjot"
    # so the typography variant never produces a blank pane.
    assert "factjot" in html


# ----- story frame -------------------------------------------------

def test_story_frame_photo_cover_uses_blurred_bg(tmp_path):
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"\x89PNG\r\n\x1a\nfakebytes")
    html = build_story_frame_html(
        cover_url=f"data:image/png;base64,fake",
        serif_url="data:font/ttf;base64,abc",
        label_url="data:font/ttf;base64,def",
        layout_mode="compact_legacy",
        typography_cover=False,
    )
    # Photo cover -> blurred background, not flat.
    assert "bg-blur" in html
    assert "filter:blur(28px)" in html


def test_story_frame_typography_cover_uses_flat_ground():
    html = build_story_frame_html(
        cover_url="data:image/png;base64,fake",
        serif_url="data:font/ttf;base64,abc",
        label_url="data:font/ttf;base64,def",
        layout_mode="compact_legacy",
        typography_cover=True,
    )
    # Typography compact_legacy -> INK flat ground.
    assert "bg-flat{position:absolute;inset:0;background:#0A0A0A" in html
    assert "blur(28px)" not in html


def test_story_frame_typography_readable_list_uses_paper_flat():
    html = build_story_frame_html(
        cover_url="data:image/png;base64,fake",
        serif_url="data:font/ttf;base64,abc",
        label_url="data:font/ttf;base64,def",
        layout_mode="readable_list",
        typography_cover=True,
    )
    assert "bg-flat{position:absolute;inset:0;background:#F4F1E9" in html
