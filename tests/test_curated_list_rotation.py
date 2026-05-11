"""Tests for the Phase N curated list rotation logic.

Behavioural contract: ship_curated_list picks the least-recently-used
pack from src/content/list_packs.py. "Used" is backfilled from two
sources: the dedicated used_list_themes.jsonl ledger AND the
brain's posted.jsonl history (for packs shipped before this script
existed). Without the backfill, the rotation would re-pick already-
shipped packs that the brain dedup would then reject, looping.

TMDB calls and Playwright rendering are NOT exercised here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pipelines.list.ship_curated_list as ship  # noqa: E402
from src.content.list_packs import LIST_PACKS  # noqa: E402


# ----- _load_used_slugs ---------------------------------------------

def test_empty_ledger_and_no_posted_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(ship, "USED_LIST_THEMES", tmp_path / "missing.jsonl")
    import src.core.paths as paths
    monkeypatch.setattr(paths, "POSTED", tmp_path / "missing_posted.jsonl")
    assert ship._load_used_slugs() == {}


def test_used_themes_ledger_loaded(monkeypatch, tmp_path):
    ledger = tmp_path / "used_list_themes.jsonl"
    ledger.write_text(
        json.dumps({"slug": "horror_films", "posted_at": "2026-05-10T12:00:00Z"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ship, "USED_LIST_THEMES", ledger)
    import src.core.paths as paths
    monkeypatch.setattr(paths, "POSTED", tmp_path / "missing_posted.jsonl")
    used = ship._load_used_slugs()
    assert used == {"horror_films": "2026-05-10T12:00:00Z"}


def test_posted_backfill_picks_up_historical_packs(monkeypatch, tmp_path):
    """Pre-Phase-N packs that shipped via the old prepare_packs.py path
    only landed in posted.jsonl. The backfill must surface them."""
    posted = tmp_path / "posted.jsonl"
    posted.write_text(
        json.dumps({"claim": "list:mind_bending_scifi", "published_at": "2026-05-01T06:53:43Z"}) + "\n"
        + json.dumps({"claim": "list:war_films_definitive", "published_at": "2026-05-03T18:03:28Z"}) + "\n"
        + json.dumps({"claim": "some other claim", "published_at": "2026-05-04T00:00:00Z"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ship, "USED_LIST_THEMES", tmp_path / "missing.jsonl")
    import src.core.paths as paths
    monkeypatch.setattr(paths, "POSTED", posted)
    used = ship._load_used_slugs()
    assert used == {
        "mind_bending_scifi": "2026-05-01T06:53:43Z",
        "war_films_definitive": "2026-05-03T18:03:28Z",
    }


def test_both_sources_merge_keeping_latest(monkeypatch, tmp_path):
    ledger = tmp_path / "used_list_themes.jsonl"
    ledger.write_text(
        json.dumps({"slug": "horror_films", "posted_at": "2026-04-15T00:00:00Z"}) + "\n",
        encoding="utf-8",
    )
    posted = tmp_path / "posted.jsonl"
    posted.write_text(
        json.dumps({"claim": "list:horror_films", "published_at": "2026-05-09T00:00:00Z"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ship, "USED_LIST_THEMES", ledger)
    import src.core.paths as paths
    monkeypatch.setattr(paths, "POSTED", posted)
    used = ship._load_used_slugs()
    # Latest of the two timestamps wins.
    assert used["horror_films"] == "2026-05-09T00:00:00Z"


# ----- _pick_pack rotation ------------------------------------------

def test_pick_pack_force_returns_named(monkeypatch):
    monkeypatch.setattr(ship, "_load_used_slugs", lambda: {})
    slug, pack = ship._pick_pack(force_slug="horror_films")
    assert slug == "horror_films"
    assert pack is LIST_PACKS["horror_films"]


def test_pick_pack_force_unknown_exits(monkeypatch):
    monkeypatch.setattr(ship, "_load_used_slugs", lambda: {})
    with pytest.raises(SystemExit):
        ship._pick_pack(force_slug="not_a_real_pack")


def test_pick_pack_prefers_never_used(monkeypatch):
    """When some packs have history and some don't, never-used wins."""
    used = {
        "war_films_definitive": "2026-05-03T18:03:28Z",
        "mind_bending_scifi": "2026-05-01T06:53:43Z",
        "series_worth_your_weekend": "2026-05-01T06:53:43Z",
    }
    monkeypatch.setattr(ship, "_load_used_slugs", lambda: used)
    slug, _ = ship._pick_pack()
    # Picked slug must be one of the never-used packs.
    never_used = [s for s in LIST_PACKS.keys() if s not in used]
    assert slug in never_used


def test_pick_pack_recycles_oldest_when_all_used(monkeypatch):
    """When every pack has shipped at some point, the oldest is recycled."""
    used = {slug: "2026-05-05T00:00:00Z" for slug in LIST_PACKS}
    # Make one strictly older than the others.
    oldest_slug = "horror_films"
    used[oldest_slug] = "2026-01-01T00:00:00Z"
    monkeypatch.setattr(ship, "_load_used_slugs", lambda: used)
    slug, _ = ship._pick_pack()
    assert slug == oldest_slug


# ----- _record_used appends -----------------------------------------

def test_record_used_appends(monkeypatch, tmp_path):
    ledger = tmp_path / "used_list_themes.jsonl"
    monkeypatch.setattr(ship, "USED_LIST_THEMES", ledger)
    ship._record_used("horror_films")
    ship._record_used("crime_thrillers")
    rows = [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]
    assert len(rows) == 2
    assert rows[0]["slug"] == "horror_films"
    assert rows[1]["slug"] == "crime_thrillers"
    assert all(r.get("posted_at") for r in rows)


# ----- _build_caption shape -----------------------------------------

def test_build_caption_contains_body_cta_sources_hashtags(monkeypatch):
    pack = {
        "title": "test pack",
        "caption": "five films that prove the point.",
        "topic": "film",
    }
    # Stub hashtag_builder to avoid the Haiku call.
    import pipelines.list.ship_curated_list as sl
    monkeypatch.setattr(sl, "build_hashtags", lambda **kw: "#films #factjot")
    caption = ship._build_caption(pack, sources=[
        "https://www.themoviedb.org/movie/1",
        "https://www.themoviedb.org/movie/2",
        "https://www.themoviedb.org/movie/3",
    ])
    assert "five films that prove the point." in caption
    assert "Follow @factjot" in caption
    assert "Sources:" in caption
    # Only the first TWO sources are surfaced to keep the caption short.
    assert "themoviedb.org/movie/1" in caption
    assert "themoviedb.org/movie/2" in caption
    assert "themoviedb.org/movie/3" not in caption
    assert "#films" in caption


def test_build_caption_no_sources_skips_section(monkeypatch):
    pack = {"caption": "body text", "topic": "film"}
    import pipelines.list.ship_curated_list as sl
    monkeypatch.setattr(sl, "build_hashtags", lambda **kw: "#x")
    caption = ship._build_caption(pack, sources=[])
    assert "Sources:" not in caption


# ----- agent routing static check ------------------------------------

def test_autonomous_agent_routes_list_midday_to_curated_pipeline():
    """The agent's main() must call ship_curated_list for list_midday
    rather than going into the LLM loop. Static-source assertion so a
    refactor that breaks the routing is caught immediately."""
    src = (Path(__file__).resolve().parents[1] / "scripts" / "autonomous_agent.py").read_text()
    assert 'mode == "list_midday"' in src
    assert "pipelines.list.ship_curated_list" in src
