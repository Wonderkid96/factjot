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
