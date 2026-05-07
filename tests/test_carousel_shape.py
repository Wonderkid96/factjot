from src.content.carousel_diagnostics import (
    CarouselShapeError,
    build_shape_diagnostics,
)


def test_shape_error_carries_structured_payload():
    diag = build_shape_diagnostics(
        requested_content_slides=5,
        returned_content_slides=8,
        slides=[{"lines": ["a", "b", "c"]} for _ in range(8)],
        dropped_facts=["nuclear test 1958"],
    )
    assert diag["requested_content_slides"] == 5
    assert diag["returned_content_slides"] == 8
    assert diag["dropped_facts"] == ["nuclear test 1958"]
    assert diag["overlong_lines"] == []
    err = CarouselShapeError("shape mismatch", diag)
    assert err.diagnostics["returned_content_slides"] == 8
    text = str(err)
    assert "requested_content_slides=5" in text
    assert "returned_content_slides=8" in text


def test_shape_error_flags_overlong_lines():
    diag = build_shape_diagnostics(
        requested_content_slides=5,
        returned_content_slides=5,
        slides=[
            {"lines": ["short", "this is way too long for the renderer", "ok"]},
        ] + [{"lines": ["a", "b", "c"]} for _ in range(4)],
    )
    assert any(o["chars"] > 24 for o in diag["overlong_lines"])
