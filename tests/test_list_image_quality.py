"""Phase 3 list-mode image-quality gate tests.

Covers:

- _hash_data_url: stable identity for dedup.
- _item_aliases_for_image: alias derivation from name + image_query.
- _image_meta_matches_item: case-insensitive substring match.
- _validate_list_images: per-item alias-mismatch rejection,
  carousel-wide dedup, cover/closing exempt from alias check but
  still subject to dedup.
"""
from __future__ import annotations

import pytest

from pipelines.manual.ship_manual_post import (
    _hash_data_url,
    _image_meta_matches_item,
    _item_aliases_for_image,
    _validate_list_images,
)


def _data_url(payload: str) -> str:
    """Build a fake data URL (the prefix is stripped before hashing)."""
    return f"data:image/jpeg;base64,{payload}"


# ---------------------------------------------------------------- #
# _hash_data_url
# ---------------------------------------------------------------- #


def test_hash_returns_empty_for_empty_input():
    assert _hash_data_url("") == ""


def test_hash_is_stable():
    a = _hash_data_url(_data_url("abc123"))
    b = _hash_data_url(_data_url("abc123"))
    assert a == b
    assert a != ""


def test_hash_distinguishes_payloads():
    assert _hash_data_url(_data_url("aaa")) != _hash_data_url(_data_url("bbb"))


def test_hash_strips_data_url_prefix_before_hashing():
    """Hash should depend on payload only, not the 'data:image/...' prefix."""
    a = _hash_data_url("data:image/jpeg;base64,xyz")
    b = _hash_data_url("data:image/png;base64,xyz")
    assert a == b


# ---------------------------------------------------------------- #
# _item_aliases_for_image
# ---------------------------------------------------------------- #


def test_aliases_include_full_name_and_significant_tokens():
    aliases = _item_aliases_for_image({
        "name": "Chernobyl disaster",
        "image_query": "Chernobyl reactor disaster",
    })
    assert "chernobyl disaster" in aliases  # full name
    assert "chernobyl" in aliases
    assert "disaster" in aliases
    assert "reactor" in aliases


def test_aliases_strip_short_tokens_and_stopwords():
    aliases = _item_aliases_for_image({
        "name": "The X-2",  # "the" is stopword, "X-2" splits to "x" + "2"
        "image_query": "of an A and B",
    })
    # No stopwords, no two-character tokens.
    assert "the" not in aliases
    assert "of" not in aliases
    assert "an" not in aliases
    assert "x" not in aliases
    assert "a" not in aliases


def test_aliases_lowercased_and_deduped():
    aliases = _item_aliases_for_image({
        "name": "Hubble Space Telescope",
        "image_query": "hubble space telescope NASA",
    })
    # Each significant token appears at most once.
    assert aliases.count("hubble") == 1
    assert aliases.count("telescope") == 1
    # Plus the full name.
    assert "hubble space telescope" in aliases


def test_aliases_handle_empty_inputs():
    assert _item_aliases_for_image({}) == []
    assert _item_aliases_for_image({"name": "", "image_query": ""}) == []


# ---------------------------------------------------------------- #
# _image_meta_matches_item
# ---------------------------------------------------------------- #


def test_match_finds_alias_substring_case_insensitively():
    item = {"name": "Chernobyl disaster", "image_query": "Chernobyl reactor"}
    matched, hits = _image_meta_matches_item(
        "Aerial photo of CHERNOBYL nuclear plant after explosion", item,
    )
    assert matched is True
    assert "chernobyl" in hits


def test_match_rejects_unrelated_meta():
    item = {"name": "Space Shuttle Challenger", "image_query": "Challenger explosion"}
    matched, hits = _image_meta_matches_item(
        "Cooling tower at a Soviet nuclear plant in the 1980s", item,
    )
    assert matched is False
    assert hits == []


def test_match_rejects_empty_meta():
    item = {"name": "Hubble", "image_query": "Hubble telescope"}
    matched, hits = _image_meta_matches_item("", item)
    assert matched is False
    assert hits == []


def test_match_empty_aliases_means_no_match():
    matched, hits = _image_meta_matches_item("anything", {})
    assert matched is False
    assert hits == []


# ---------------------------------------------------------------- #
# _validate_list_images
# ---------------------------------------------------------------- #


def _items_5() -> list[dict]:
    return [
        {"rank": 1, "name": "Chernobyl disaster",
         "rank_reason": "rr1", "concrete_fact": "cf1",
         "image_query": "Chernobyl reactor disaster"},
        {"rank": 2, "name": "Deepwater Horizon blowout",
         "rank_reason": "rr2", "concrete_fact": "cf2",
         "image_query": "Deepwater Horizon oil rig fire"},
        {"rank": 3, "name": "Space Shuttle Challenger",
         "rank_reason": "rr3", "concrete_fact": "cf3",
         "image_query": "Space Shuttle Challenger explosion"},
        {"rank": 4, "name": "Hubble Space Telescope",
         "rank_reason": "rr4", "concrete_fact": "cf4",
         "image_query": "Hubble Space Telescope"},
        {"rank": 5, "name": "Mars Climate Orbiter",
         "rank_reason": "rr5", "concrete_fact": "cf5",
         "image_query": "Mars Climate Orbiter NASA"},
    ]


def _decision(slot, query, meta="", url="ok"):
    return {
        "slot": slot, "query": query, "outcome": "haiku_pick",
        "chosen_url": url, "chosen_meta": meta,
        "chosen_provider": "pexels", "score": 9, "confidence": "medium",
        "relaxation_round": 1, "reason": "ok",
    }


def test_validator_keeps_well_matched_image():
    items = _items_5()
    images = [_data_url(f"slot{i}") for i in range(7)]
    decisions = [
        _decision(0, "list cover", meta="generic news collage"),                       # cover
        _decision(1, items[0]["image_query"], meta="Chernobyl reactor 4 explosion"),   # 1
        _decision(2, items[1]["image_query"], meta="Deepwater Horizon oil rig fire"),  # 2
        _decision(3, items[2]["image_query"], meta="Space Shuttle Challenger 1986"),   # 3
        _decision(4, items[3]["image_query"], meta="Hubble Space Telescope deployed"), # 4
        _decision(5, items[4]["image_query"], meta="Mars Climate Orbiter NASA art"),   # 5
        _decision(6, "closer", meta="empty boardroom"),                                 # closing
    ]
    filtered, audit = _validate_list_images(images, decisions, items)
    assert all(filtered), "every slide should keep its image"
    item_audits = [row for row in audit if 1 <= row["slot"] <= 5]
    assert all(row["match_status"] == "match" for row in item_audits)


def test_validator_rejects_mismatched_image_with_typography_fallback():
    """Chernobyl photo on a Challenger slide must be rejected even
    though the photo metadata is dramatic and visually plausible."""
    items = _items_5()
    images = [_data_url(f"slot{i}") for i in range(7)]
    decisions = [
        _decision(0, "list cover", meta="news collage 2020"),
        _decision(1, items[0]["image_query"], meta="Chernobyl reactor"),
        _decision(2, items[1]["image_query"], meta="Deepwater Horizon BP rig"),
        # Slot 3 is Challenger but the chosen image is a Chernobyl photo:
        _decision(3, items[2]["image_query"], meta="Cooling tower Chernobyl plant"),
        _decision(4, items[3]["image_query"], meta="Hubble Space Telescope"),
        _decision(5, items[4]["image_query"], meta="Mars Climate Orbiter NASA"),
        _decision(6, "closer", meta="empty boardroom"),
    ]
    filtered, audit = _validate_list_images(images, decisions, items)
    # Slot 3 must have been blanked.
    assert filtered[3] == ""
    challenger_audit = audit[3]
    assert challenger_audit["outcome"] == "rejected_alias_mismatch"
    assert challenger_audit["match_status"] == "mismatch"
    # Other item slides untouched.
    assert filtered[1] != ""
    assert filtered[2] != ""
    assert filtered[4] != ""


def test_validator_dedupes_duplicate_image_urls_first_wins():
    items = _items_5()
    # Slot 1 and slot 3 share the same image bytes.
    same = "AAAA"
    images = [
        _data_url("cover"), _data_url(same), _data_url("d2"),
        _data_url(same), _data_url("d4"), _data_url("d5"), _data_url("close"),
    ]
    decisions = [
        _decision(0, "cover", meta="news collage"),
        _decision(1, items[0]["image_query"], meta="Chernobyl reactor"),
        _decision(2, items[1]["image_query"], meta="Deepwater Horizon rig"),
        # Slot 3 alias also matches Challenger query so it passes alias check;
        # the dedup must catch the duplicate.
        _decision(3, items[2]["image_query"], meta="Space Shuttle Challenger explosion"),
        _decision(4, items[3]["image_query"], meta="Hubble Space Telescope"),
        _decision(5, items[4]["image_query"], meta="Mars Climate Orbiter NASA"),
        _decision(6, "closer", meta="empty boardroom"),
    ]
    filtered, audit = _validate_list_images(images, decisions, items)
    # Slot 1 keeps the image; slot 3 is blanked because it duplicates slot 1.
    assert filtered[1] != ""
    assert filtered[3] == ""
    assert audit[3]["outcome"] == "rejected_duplicate"
    assert audit[3]["dedupe_status"].startswith("duplicate_of_slot_1")


def test_validator_cover_exempt_from_alias_but_subject_to_dedup():
    """Cover is exempt from item alias matching but still must not
    duplicate any later slide. Identical image on cover and slot 4
    means the LATER slot (slot 4) loses, not the cover."""
    items = _items_5()
    same = "SAME"
    images = [
        _data_url(same), _data_url("d1"), _data_url("d2"),
        _data_url("d3"), _data_url(same), _data_url("d5"), _data_url("close"),
    ]
    decisions = [
        # Cover meta intentionally wouldn't match any item alias.
        _decision(0, "cover", meta="generic news photo collage"),
        _decision(1, items[0]["image_query"], meta="Chernobyl reactor"),
        _decision(2, items[1]["image_query"], meta="Deepwater Horizon rig"),
        _decision(3, items[2]["image_query"], meta="Space Shuttle Challenger explosion"),
        # Slot 4 alias passes, but image is the same as cover.
        _decision(4, items[3]["image_query"], meta="Hubble Space Telescope deployed"),
        _decision(5, items[4]["image_query"], meta="Mars Climate Orbiter NASA"),
        _decision(6, "closer", meta="empty boardroom"),
    ]
    filtered, audit = _validate_list_images(images, decisions, items)
    # Cover keeps its image (first wins, no item-alias gate).
    assert filtered[0] != ""
    # Slot 4 was blanked as a duplicate of cover.
    assert filtered[4] == ""
    assert audit[4]["dedupe_status"].startswith("duplicate_of_slot_0")


def test_validator_typography_input_is_not_rejected_again():
    """A slot that came in already blank stays blank with a clear
    label rather than being treated as a rejection."""
    items = _items_5()
    images = [
        _data_url("cover"), "", _data_url("d2"),
        _data_url("d3"), _data_url("d4"), _data_url("d5"), _data_url("close"),
    ]
    decisions = [
        _decision(0, "cover", meta="news collage"),
        {"slot": 1, "query": items[0]["image_query"], "outcome": "typography",
         "chosen_url": "", "chosen_meta": "", "chosen_provider": "",
         "score": None, "confidence": "low", "relaxation_round": 3,
         "reason": "r3_exhausted"},
        _decision(2, items[1]["image_query"], meta="Deepwater Horizon rig"),
        _decision(3, items[2]["image_query"], meta="Space Shuttle Challenger"),
        _decision(4, items[3]["image_query"], meta="Hubble Space Telescope"),
        _decision(5, items[4]["image_query"], meta="Mars Climate Orbiter NASA"),
        _decision(6, "closer", meta="boardroom"),
    ]
    filtered, audit = _validate_list_images(images, decisions, items)
    assert filtered[1] == ""
    assert audit[1]["outcome"] == "typography_input"
    # No false "rejected_alias_mismatch" on a slot that never had an image.
    assert audit[1]["match_status"] == "n/a"


def test_validator_audit_exposes_query_meta_provider_outcome():
    """The audit row must contain the fields the human inspector
    needs: image_query, image_meta, image_provider, outcome,
    selection_reason, match_status, dedupe_status."""
    items = _items_5()
    images = [_data_url(f"x{i}") for i in range(7)]
    decisions = [
        _decision(i, f"q{i}", meta=f"m{i} {items[i-1]['name']}" if 1 <= i <= 5 else f"m{i}")
        for i in range(7)
    ]
    _, audit = _validate_list_images(images, decisions, items)
    required_keys = {
        "slot", "image_query", "image_meta", "image_provider",
        "selection_outcome", "selection_reason",
        "match_status", "dedupe_status", "outcome",
    }
    for row in audit:
        assert required_keys.issubset(row.keys()), f"missing keys in {row}"
