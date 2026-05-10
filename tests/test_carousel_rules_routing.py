"""Tests for the single-source-of-truth pipeline-format -> layout-profile
routing in src/content/carousel_rules.py.

Behavioural contract: every caller that decides "which layout profile
should this format use?" must call `profile_for_format()`. Per-profile
flags (relax_image_floor, etc) live IN the profile dict, not in
inline string matches at call sites.

Pre-Phase-K.3, this decision was duplicated:
  - scripts/autonomous_agent.py:405-406 (agent shim)
  - pipelines/manual/ship_manual_post.py:1822-1825 (CLI default)
  - pipelines/manual/ship_manual_post.py:2027 (`relax=(layout_mode == "readable_list")`)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.content.carousel_rules import (  # noqa: E402
    FORMAT_TO_PROFILE,
    LAYOUT_PROFILES,
    get_profile,
    profile_for_format,
)


# ----- format -> profile routing ------------------------------------

def test_profile_for_format_fact_returns_compact_legacy():
    assert profile_for_format("fact") == "compact_legacy"


def test_profile_for_format_list_returns_readable_list():
    assert profile_for_format("list") == "readable_list"


def test_profile_for_format_news_returns_readable_list():
    assert profile_for_format("news") == "readable_list"


def test_profile_for_format_unknown_defaults_to_compact_legacy():
    # An unknown format must default to compact_legacy (byte-identical
    # to pre-2026-05-08 default). A new format must NOT silently flip
    # to readable_list.
    assert profile_for_format("something-new") == "compact_legacy"
    assert profile_for_format("") == "compact_legacy"


def test_format_to_profile_dict_is_complete():
    # Guard: every active format the agent supports must be routed.
    # Agent's MODE_FORMAT_TYPE supports `list` today (plus the implicit
    # `fact` default). News is retained because the renderer is reused.
    assert "fact" in FORMAT_TO_PROFILE
    assert "list" in FORMAT_TO_PROFILE
    assert "news" in FORMAT_TO_PROFILE


# ----- relax_image_floor lives on the profile -----------------------

def test_compact_legacy_strict_image_floor():
    assert get_profile("compact_legacy")["relax_image_floor"] is False


def test_readable_list_relaxes_image_floor():
    assert get_profile("readable_list")["relax_image_floor"] is True


def test_relax_flag_present_on_every_profile():
    # Guard: a new profile added without `relax_image_floor` would
    # KeyError at the call site in ship_manual_post.py. Catch it here.
    for name, profile in LAYOUT_PROFILES.items():
        assert "relax_image_floor" in profile, (
            f"profile {name!r} missing relax_image_floor"
        )


# ----- call-site wiring ---------------------------------------------

def test_autonomous_agent_uses_profile_for_format():
    """Static check that scripts/autonomous_agent.py uses the helper
    instead of an inline string match. Catches a future edit that
    re-inlines the routing.
    """
    src = (Path(__file__).resolve().parents[1] / "scripts" / "autonomous_agent.py").read_text()
    assert "profile_for_format" in src, (
        "autonomous_agent.py must route layout via profile_for_format()"
    )
    # The old pattern should be gone.
    assert 'if format_type in ("list", "news"):' not in src, (
        "inline format-match must be replaced by profile_for_format()"
    )


def test_ship_manual_uses_profile_for_format():
    src = (Path(__file__).resolve().parents[1] / "pipelines" / "manual" / "ship_manual_post.py").read_text()
    assert "profile_for_format" in src, (
        "ship_manual_post.py must route layout via profile_for_format()"
    )
    # The relax flag must be read from the profile, not an inline match.
    assert 'relax=(layout_mode == "readable_list")' not in src, (
        "inline relax match must be replaced by get_profile(...)['relax_image_floor']"
    )
    assert 'relax=get_profile(layout_mode)["relax_image_floor"]' in src
