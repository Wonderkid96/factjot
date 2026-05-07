import pytest
from src.render.line_fit_probe import cap_for_slide_kind


def test_cap_for_photo_slide_is_tighter_than_typography():
    photo_cap = cap_for_slide_kind("photo")
    typo_cap = cap_for_slide_kind("typography")
    assert photo_cap < typo_cap
    assert 18 <= photo_cap <= 26
    assert 22 <= typo_cap <= 30


def test_cap_for_unknown_kind_returns_safe_default():
    assert cap_for_slide_kind("nonsense") == cap_for_slide_kind("photo")


from unittest.mock import MagicMock
from src.render.line_fit_probe import measure_lines_overflow


def test_measure_lines_overflow_flags_visual_wrap():
    """The probe must call into Playwright with the same template as
    the real renderer and report which lines overflowed.

    We mock the browser/page so this test runs with no Chromium needed.
    """
    fake_page = MagicMock()
    fake_page.evaluate.return_value = [
        {"text": "fits fine",                  "rendered_width_px": 480, "wraps": False},
        {"text": "this line is way too long",  "rendered_width_px": 1020, "wraps": True},
        {"text": "ok",                         "rendered_width_px": 80,   "wraps": False},
    ]
    fake_browser = MagicMock()
    fake_browser.new_page.return_value = fake_page

    overflow = measure_lines_overflow(
        lines=["fits fine", "this line is way too long", "ok"],
        slide_kind="photo",
        browser=fake_browser,
    )
    assert overflow == [False, True, False]
