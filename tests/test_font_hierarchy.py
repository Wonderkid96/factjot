"""Regression tests for the carousel renderer's font hierarchy.

Phase B (2026-05-10) migrated the carousel label font from JetBrains Mono
Bold to Space Grotesk Bold 700. The rendered carousel HTML should reference
SpaceGrotesk-Bold and not JetBrainsMono. There was no test pinning this:
a brand_kit edit could revert every carousel post to the deprecated font
with no log line, no error, and no CI signal. These tests close that gap
by asserting the actual HTML string returned by `_build_html()` and
`_build_closing_html()` — pure functions, no Playwright, no browser.

Also pins `label_font_canonical` presence in `brand_kit.json` so a future
"clean up the typography block" refactor cannot delete the key and silently
fall back to JetBrains Mono via `.get()` defaults.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BRAND_KIT_PATH = REPO_ROOT / "brand" / "brand_kit.json"


@pytest.fixture(scope="module")
def brand_kit() -> dict:
    return json.loads(BRAND_KIT_PATH.read_text(encoding="utf-8"))


@pytest.fixture()
def carousel_renderer(brand_kit, tmp_path, monkeypatch):
    """A renderer whose `_asset_url` returns the input path verbatim instead
    of a base64 data URI.

    The production `_asset_url` embeds the font as a `data:font/ttf;base64,...`
    blob, so the original file path doesn't survive into the rendered HTML.
    For a structural test we want to see WHICH font path was wired to
    `font_sans_bold`, not the encoded bytes. Monkey-patching `_asset_url`
    to echo the path lets us assert against `assets/fonts/SpaceGrotesk-Bold.ttf`
    appearing (and `JetBrainsMono-Bold.ttf` not appearing) in the rendered
    HTML, which is the exact regression we're guarding against.
    """
    from src.render.render_carousel import BrandKitRenderer
    renderer = BrandKitRenderer(brand=brand_kit, output_dir=str(tmp_path))
    monkeypatch.setattr(renderer, "_asset_url", lambda p: f"file://{p}")
    return renderer


def test_build_html_uses_space_grotesk_not_jetbrains(carousel_renderer, tmp_path) -> None:
    """A standard fact-slide render must wire SpaceGrotesk-Bold and not JetBrainsMono.

    The slide.html.j2 template uses `font_sans_bold` for label / kicker / chip
    text, sourced from `label_font_canonical` in brand_kit.json. If the
    `.get()` fallback at `render_carousel.py:172` ever resolves to
    `label_font` instead, JetBrainsMono-Bold.ttf flows into every carousel
    slide. This assertion catches that drift before it reaches Instagram.
    """
    bg = tmp_path / "fake_bg.jpg"
    bg.write_bytes(b"\xff\xd8\xff")

    html = carousel_renderer._build_html(
        slide_text="A short test fact about hierarchies.",
        bg_path=bg,
        slide_index=1,
        total=3,
        category="science",
        is_closing=False,
    )

    assert "SpaceGrotesk-Bold" in html, (
        "Carousel slide HTML lost SpaceGrotesk-Bold reference. The label "
        "font canonical wiring at render_carousel.py:172 has reverted to a "
        "non-canonical font; check brand_kit.json['typography']"
        "['label_font_canonical'] is still set to assets/fonts/"
        "SpaceGrotesk-Bold.ttf."
    )
    assert "JetBrainsMono" not in html, (
        "Carousel slide HTML now references JetBrainsMono. The 2026-05-10 "
        "font hierarchy migration to Space Grotesk has been reverted. "
        "Check render_carousel.py:172 — the .get() fallback has fired "
        "because `label_font_canonical` is missing from brand_kit.json, "
        "OR template slide.html.j2 has had `font_mono_bold` re-wired into "
        "an active CSS rule."
    )


def test_build_closing_html_uses_space_grotesk_not_jetbrains(carousel_renderer, tmp_path) -> None:
    """Closing-quote slide has its own _build_closing_html path with the
    same .get() fallback at render_carousel.py:274. Test it independently.
    """
    bg = tmp_path / "fake_bg.jpg"
    bg.write_bytes(b"\xff\xd8\xff")

    html = carousel_renderer._build_closing_html(
        quote="A short closing quote.",
        attribution="Anon",
        bg_path=bg,
        slide_index=3,
        total=3,
    )

    assert "SpaceGrotesk-Bold" in html
    assert "JetBrainsMono" not in html


def test_brand_kit_label_font_canonical_present(brand_kit) -> None:
    """`label_font_canonical` must be present in the typography block.

    `render_carousel.py:172,274` do `ty.get("label_font_canonical", ty["label_font"])`.
    If `label_font_canonical` is ever removed during a brand_kit cleanup,
    the renderer silently falls back to `label_font` which still points at
    JetBrainsMono-Bold.ttf. Pin presence here so the deletion fails CI
    rather than reaching production.
    """
    typography = brand_kit.get("typography")
    assert typography is not None, "brand_kit.json missing 'typography' block"
    canonical = typography.get("label_font_canonical")
    assert canonical, (
        "brand_kit.json['typography']['label_font_canonical'] is missing or "
        "empty. Carousel renderers fall back to label_font (JetBrainsMono) "
        "when this key is absent. Restore it to assets/fonts/"
        "SpaceGrotesk-Bold.ttf."
    )
    assert "SpaceGrotesk" in canonical, (
        f"label_font_canonical resolves to {canonical!r}, which does not "
        "contain 'SpaceGrotesk'. The 2026-05-10 migration mandates "
        "Space Grotesk Bold for label / kicker / chip rendering."
    )
