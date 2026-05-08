"""Phase 2: structured list-mode handoff tests.

Protects the Stage 6b boundary identified in the routing audit. The
list pipeline must keep typed `items` separate from rendered `lines`,
so a future renderer redesign can read structured fields without
re-deriving them from prose.

Covered:

- The adapter `_items_to_render_slides` is deterministic, builds one
  slide per item with [r]name[/r] / rank_reason / concrete_fact, and
  appends one closing slide.
- The validator `_enforce_list_shape` rejects every malformed shape
  the writer could plausibly emit (missing fields, wrong rank order,
  oversized fields, missing closing block, missing cover image query).
"""
from __future__ import annotations

import pytest

from pipelines.manual.ship_manual_post import (
    LIST_ITEM_REQUIRED_FIELDS,
    _enforce_list_shape,
    _items_to_render_slides,
)
from src.content.carousel_diagnostics import CarouselShapeError


# ---------------------------------------------------------------- #
# Fixtures
# ---------------------------------------------------------------- #


def _good_item(rank: int) -> dict:
    return {
        "rank": rank,
        "name": f"Item {rank}",
        "rank_reason": f"reason {rank}",
        "concrete_fact": f"concrete fact {rank}",
        "image_query": f"query {rank}",
    }


def _good_payload(n_items: int = 5) -> dict:
    return {
        "cover_title": "Five most expensive product recalls in history",
        "label": "BUSINESS",
        "caption_body": "human, warm caption.",
        "cover_image_query": "industrial warehouse stacked goods",
        "items": [_good_item(i) for i in range(1, n_items + 1)],
        "closing": {
            "lines": ["one", "two", "three"],
            "image_query": "thoughtful closing visual",
        },
        # cover + items + closing = n_items + 2 fallback queries
        "visual_fallback_queries": [
            f"fallback {i}" for i in range(n_items + 2)
        ],
    }


# ---------------------------------------------------------------- #
# Adapter
# ---------------------------------------------------------------- #


def test_adapter_emits_one_slide_per_item_plus_closing():
    payload = _good_payload(n_items=3)
    slides = _items_to_render_slides(payload["items"], payload["closing"])
    assert len(slides) == 4  # 3 items + 1 closing


def test_adapter_lines_are_deterministic():
    item = {
        "rank": 1,
        "name": "Takata airbag recall",
        "rank_reason": "$24B in recall costs",
        "concrete_fact": "Over 100M vehicles recalled",
        "image_query": "car airbag deployment",
    }
    closing = {"lines": ["a", "b", "c"], "image_query": "x"}
    slides = _items_to_render_slides([item], closing)
    assert slides[0]["lines"] == [
        "[r]Takata airbag recall[/r]",
        "$24B in recall costs",
        "Over 100M vehicles recalled",
    ]
    # Closing slide carries the freeform lines straight through.
    assert slides[1]["lines"] == ["a", "b", "c"]


def test_adapter_assigns_slide_numbers_in_order():
    payload = _good_payload(n_items=5)
    slides = _items_to_render_slides(payload["items"], payload["closing"])
    # Items 1..5 -> slideNumber 2..6, closing -> slideNumber 7.
    assert [s["slideNumber"] for s in slides] == [2, 3, 4, 5, 6, 7]


def test_adapter_preserves_structured_item_per_slide():
    payload = _good_payload(n_items=2)
    slides = _items_to_render_slides(payload["items"], payload["closing"])
    # Item slides carry the source dict on slide["item"].
    assert slides[0]["item"] == payload["items"][0]
    assert slides[1]["item"] == payload["items"][1]
    # Closing slide has no `item` key (it isn't a ranked entry).
    assert "item" not in slides[2]


def test_adapter_does_not_mutate_input():
    payload = _good_payload(n_items=2)
    items_before = [dict(it) for it in payload["items"]]
    closing_before = dict(payload["closing"])
    closing_before["lines"] = list(payload["closing"]["lines"])
    _items_to_render_slides(payload["items"], payload["closing"])
    assert payload["items"] == items_before
    assert payload["closing"]["lines"] == closing_before["lines"]


def test_adapter_sets_slot_aliases_to_item_name():
    payload = _good_payload(n_items=1)
    slides = _items_to_render_slides(payload["items"], payload["closing"])
    assert slides[0]["slot_aliases"] == [payload["items"][0]["name"]]
    # Closing has no per-slot alias.
    assert slides[1]["slot_aliases"] == []


# ---------------------------------------------------------------- #
# Validator: required fields
# ---------------------------------------------------------------- #


def test_validator_required_fields_constant_matches_validator():
    # If a required field is renamed, both the constant and the
    # validator's per-field pass must move together.
    assert set(LIST_ITEM_REQUIRED_FIELDS) == {
        "rank", "name", "rank_reason", "concrete_fact", "image_query",
    }


def test_validator_passes_well_formed_payload():
    _enforce_list_shape(_good_payload(), requested_items=5, hard_cap=56)


def test_validator_rejects_missing_items_array():
    payload = _good_payload()
    payload.pop("items")
    with pytest.raises(CarouselShapeError) as exc:
        _enforce_list_shape(payload, requested_items=5, hard_cap=56)
    assert "items" in exc.value.diagnostics["list_errors"][0]


def test_validator_rejects_wrong_item_count():
    payload = _good_payload(n_items=4)
    with pytest.raises(CarouselShapeError) as exc:
        _enforce_list_shape(payload, requested_items=5, hard_cap=56)
    assert any("4" in e and "5" in e for e in exc.value.diagnostics["list_errors"])


@pytest.mark.parametrize("missing", ["rank", "name", "rank_reason", "concrete_fact", "image_query"])
def test_validator_rejects_missing_field(missing):
    payload = _good_payload(n_items=1)
    payload["items"][0].pop(missing)
    with pytest.raises(CarouselShapeError) as exc:
        _enforce_list_shape(payload, requested_items=1, hard_cap=56)
    assert any(missing in e for e in exc.value.diagnostics["list_errors"])


def test_validator_rejects_out_of_order_ranks():
    payload = _good_payload(n_items=3)
    # Swap ranks 1 and 2.
    payload["items"][0]["rank"] = 2
    payload["items"][1]["rank"] = 1
    with pytest.raises(CarouselShapeError) as exc:
        _enforce_list_shape(payload, requested_items=3, hard_cap=56)
    msg = "\n".join(exc.value.diagnostics["list_errors"])
    assert "rank" in msg


def test_validator_rejects_non_integer_rank():
    payload = _good_payload(n_items=1)
    payload["items"][0]["rank"] = "1"
    with pytest.raises(CarouselShapeError):
        _enforce_list_shape(payload, requested_items=1, hard_cap=56)


def test_validator_rejects_bool_rank_even_though_python_treats_bool_as_int():
    payload = _good_payload(n_items=1)
    payload["items"][0]["rank"] = True
    with pytest.raises(CarouselShapeError):
        _enforce_list_shape(payload, requested_items=1, hard_cap=56)


# ---------------------------------------------------------------- #
# Validator: hard-cap enforcement
# ---------------------------------------------------------------- #


@pytest.mark.parametrize("field", ["name", "rank_reason", "concrete_fact"])
def test_validator_rejects_field_over_hard_cap(field):
    payload = _good_payload(n_items=1)
    payload["items"][0][field] = "x" * 60  # cap is 56
    with pytest.raises(CarouselShapeError) as exc:
        _enforce_list_shape(payload, requested_items=1, hard_cap=56)
    assert any(field in e and "60" in e for e in exc.value.diagnostics["list_errors"])


def test_validator_ignores_red_markup_when_measuring_length():
    # The pipeline wraps name in [r]...[/r] AT ADAPTER TIME, but a
    # writer that includes the markup itself should still be measured
    # by visible chars, not raw bytes including the tags.
    payload = _good_payload(n_items=1)
    payload["items"][0]["name"] = "[r]" + ("x" * 50) + "[/r]"  # 50 visible
    # With hard_cap=56 this is fine on visible chars (50 <= 56).
    _enforce_list_shape(payload, requested_items=1, hard_cap=56)


def test_validator_rejects_image_query_when_blank():
    payload = _good_payload(n_items=1)
    payload["items"][0]["image_query"] = "   "
    with pytest.raises(CarouselShapeError) as exc:
        _enforce_list_shape(payload, requested_items=1, hard_cap=56)
    assert any("image_query" in e for e in exc.value.diagnostics["list_errors"])


def test_validator_does_not_apply_hard_cap_to_image_query():
    # image_query is metadata for the sourcer, not a rendered field.
    # It can be longer than the line cap.
    payload = _good_payload(n_items=1)
    payload["items"][0]["image_query"] = "a " * 50  # ~100 chars
    _enforce_list_shape(payload, requested_items=1, hard_cap=56)


# ---------------------------------------------------------------- #
# Validator: closing block + cover query
# ---------------------------------------------------------------- #


def test_validator_rejects_missing_closing_block():
    payload = _good_payload()
    payload.pop("closing")
    with pytest.raises(CarouselShapeError) as exc:
        _enforce_list_shape(payload, requested_items=5, hard_cap=56)
    assert any("closing" in e for e in exc.value.diagnostics["list_errors"])


def test_validator_rejects_wrong_closing_line_count():
    payload = _good_payload()
    payload["closing"]["lines"] = ["only", "two"]
    with pytest.raises(CarouselShapeError) as exc:
        _enforce_list_shape(payload, requested_items=5, hard_cap=56)
    assert any("closing.lines" in e for e in exc.value.diagnostics["list_errors"])


def test_validator_rejects_overlong_closing_line():
    payload = _good_payload()
    payload["closing"]["lines"][0] = "x" * 60
    with pytest.raises(CarouselShapeError) as exc:
        _enforce_list_shape(payload, requested_items=5, hard_cap=56)
    assert any("closing.lines[1]" in e for e in exc.value.diagnostics["list_errors"])


def test_validator_rejects_missing_cover_image_query():
    payload = _good_payload()
    payload["cover_image_query"] = ""
    with pytest.raises(CarouselShapeError) as exc:
        _enforce_list_shape(payload, requested_items=5, hard_cap=56)
    assert any("cover_image_query" in e for e in exc.value.diagnostics["list_errors"])


def test_validator_rejects_missing_closing_image_query():
    payload = _good_payload()
    payload["closing"]["image_query"] = ""
    with pytest.raises(CarouselShapeError) as exc:
        _enforce_list_shape(payload, requested_items=5, hard_cap=56)
    assert any("closing.image_query" in e for e in exc.value.diagnostics["list_errors"])


def test_validator_rejects_missing_visual_fallback_queries():
    payload = _good_payload()
    payload.pop("visual_fallback_queries")
    with pytest.raises(CarouselShapeError) as exc:
        _enforce_list_shape(payload, requested_items=5, hard_cap=56)
    assert any("visual_fallback_queries" in e for e in exc.value.diagnostics["list_errors"])


def test_validator_rejects_wrong_number_of_visual_fallback_queries():
    # Expect cover + 5 items + closing = 7 fallback queries.
    payload = _good_payload()
    payload["visual_fallback_queries"] = ["only", "five", "of", "the", "seven"]
    with pytest.raises(CarouselShapeError) as exc:
        _enforce_list_shape(payload, requested_items=5, hard_cap=56)
    msg = "\n".join(exc.value.diagnostics["list_errors"])
    assert "visual_fallback_queries" in msg
    assert "7" in msg  # expected count


def test_validator_rejects_blank_visual_fallback_query_entry():
    payload = _good_payload()
    payload["visual_fallback_queries"][2] = "   "
    with pytest.raises(CarouselShapeError) as exc:
        _enforce_list_shape(payload, requested_items=5, hard_cap=56)
    msg = "\n".join(exc.value.diagnostics["list_errors"])
    assert "visual_fallback_queries[2]" in msg


def test_validator_collects_multiple_errors_in_one_payload():
    # Several distinct violations should all be reported, not just the first.
    payload = _good_payload(n_items=2)
    payload["items"][0]["name"] = "y" * 80
    payload["items"][1].pop("concrete_fact")
    payload["closing"]["lines"] = ["only one"]
    with pytest.raises(CarouselShapeError) as exc:
        _enforce_list_shape(payload, requested_items=2, hard_cap=56)
    errors = exc.value.diagnostics["list_errors"]
    assert any("name" in e for e in errors)
    assert any("concrete_fact" in e for e in errors)
    assert any("closing.lines" in e for e in errors)
