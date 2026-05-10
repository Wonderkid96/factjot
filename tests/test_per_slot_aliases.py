"""Regression tests for `_build_per_slot_aliases` in ship_manual_post.

Documented production incident (`insta-brain/gotchas.md`): when
`cover_slot_aliases` is empty in the upstream JSON, the cover slot must
fall back to the global `source_aliases` via `None` in slot 0. This was
inlined inside `main()` for a long time, which made it untestable in
isolation — meaning every "fix wrong cover image" attempt was guesswork
against the live pipeline. Extracting the function and pinning the
contract here closes that failure mode.

These tests exercise the pure function directly. No image-pipeline
side effects, no Playwright, no HTTP.
"""
from __future__ import annotations

from pipelines.manual.ship_manual_post import _build_per_slot_aliases


def test_empty_cover_slot_aliases_falls_back_to_global() -> None:
    """The documented failure mode: empty `cover_slot_aliases` must
    produce `None` for slot 0 so ImageSourcer applies global aliases.

    If this assertion ever flips to expecting `[]` or to rejecting
    `None`, the cover slot will start gating with global aliases,
    reproducing the `POOL_REJECT no_alias_match` cover-failure incident
    on every scene-style cover query.
    """
    per_slot, _ = _build_per_slot_aliases(
        cover_slot_aliases=[],
        cover_title="Cover",
        slides=[{"lines": ["a"]}, {"lines": ["b"]}],
    )

    assert per_slot[0] is None, (
        f"Empty cover_slot_aliases should fall back to None (global "
        f"aliases) for slot 0, got {per_slot[0]!r}. See gotchas.md "
        "cover-alias incident for the production failure mode."
    )


def test_non_empty_cover_aliases_used_verbatim() -> None:
    per_slot, _ = _build_per_slot_aliases(
        cover_slot_aliases=["smartphone", "messaging"],
        cover_title="Cover",
        slides=[{"lines": ["a"]}],
    )
    assert per_slot[0] == ["smartphone", "messaging"]


def test_slot_aliases_independent_per_slide() -> None:
    per_slot, _ = _build_per_slot_aliases(
        cover_slot_aliases=[],
        cover_title="Cover",
        slides=[
            {"lines": ["a"], "slot_aliases": ["alpha"]},
            {"lines": ["b"]},  # missing slot_aliases
            {"lines": ["c"], "slot_aliases": []},  # explicitly empty
        ],
    )
    assert per_slot == [None, ["alpha"], None, None]


def test_malformed_aliases_are_dropped() -> None:
    """Non-string entries and whitespace-only strings must be filtered.

    Upstream JSON sometimes contains nulls or empty strings; the
    pipeline used to silently include them, then `ImageSourcer` would
    fail later with an opaque match error.
    """
    per_slot, _ = _build_per_slot_aliases(
        cover_slot_aliases=["valid", "", None, "  ", 42, "also_valid"],
        cover_title="Cover",
        slides=[],
    )
    assert per_slot[0] == ["valid", "also_valid"]


def test_non_list_cover_aliases_treated_as_empty() -> None:
    """A missing/None/string cover_slot_aliases must coerce to None at
    slot 0, not crash and not pass through a bad value."""
    for bad in (None, "smartphone", {"alias": "x"}, 42):
        per_slot, _ = _build_per_slot_aliases(
            cover_slot_aliases=bad,
            cover_title="Cover",
            slides=[],
        )
        assert per_slot[0] is None, (
            f"cover_slot_aliases={bad!r} should coerce to None for slot 0"
        )


def test_per_slot_text_alignment() -> None:
    """`per_slot_text` must align 1:1 with `per_slot_aliases` indices.

    ImageSourcer.source_images iterates these together; off-by-one
    breaks every image lookup downstream of the misalignment.
    """
    per_slot, per_slot_text = _build_per_slot_aliases(
        cover_slot_aliases=[],
        cover_title="My Cover Title",
        slides=[
            {"lines": ["first line"]},
            {"lines": ["second", "and another"]},
        ],
    )
    assert len(per_slot) == len(per_slot_text)
    assert per_slot_text[0] == "My Cover Title"
    assert per_slot_text[1] == "first line"
    assert per_slot_text[2] == "second and another"
