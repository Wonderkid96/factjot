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


import pytest
from pipelines.manual.ship_manual_post import _enforce_carousel_shape


def test_enforce_carousel_shape_rejects_too_many_slides():
    data = {
        "slides": [{"lines": ["a", "b", "c"]} for _ in range(9)],
    }
    with pytest.raises(CarouselShapeError) as exc:
        _enforce_carousel_shape(data, requested_content_slides=5)
    assert exc.value.diagnostics["returned_content_slides"] == 9
    assert exc.value.diagnostics["requested_content_slides"] == 5


def test_enforce_carousel_shape_rejects_wrong_line_count():
    data = {
        "slides": [
            {"lines": ["a", "b"]},
            {"lines": ["a", "b", "c"]},
            {"lines": ["a", "b", "c"]},
            {"lines": ["a", "b", "c"]},
            {"lines": ["a", "b", "c"]},
        ],
    }
    with pytest.raises(CarouselShapeError):
        _enforce_carousel_shape(data, requested_content_slides=5)


def test_enforce_carousel_shape_passes_clean_data():
    data = {
        "slides": [{"lines": ["one", "two", "three"]} for _ in range(5)],
    }
    _enforce_carousel_shape(data, requested_content_slides=5)


import json
from pipelines.manual.ship_manual_post import _write_quality_ledger_entry


def test_quality_ledger_entry_records_run(tmp_path):
    ledger = tmp_path / "carousel_quality.jsonl"
    _write_quality_ledger_entry(
        ledger_path=ledger,
        post_id="ask-jeeves-tribute",
        format_type="news",
        cover_title="ask jeeves quietly logs off",
        slide_count=6,
        line_warnings=["slide 4 line 3: ends with weak word 'and'"],
        dropped_facts=[],
        image_coverage={"image": 5, "typography": 1, "cover_failed": False},
        result="published",
    )
    rows = ledger.read_text().strip().splitlines()
    assert len(rows) == 1
    payload = json.loads(rows[0])
    assert payload["post_id"] == "ask-jeeves-tribute"
    assert payload["format_type"] == "news"
    assert payload["slide_count"] == 6
    assert payload["image_coverage"]["image"] == 5
    assert payload["result"] == "published"
    assert "ts" in payload
