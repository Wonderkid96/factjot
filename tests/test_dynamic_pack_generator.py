"""Tests for the Phase O dynamic list-pack generator.

Behavioural contract: the generator produces a pack dict matching
the LIST_PACKS entry shape, with TMDB-resolved tmdb_id on every
item. Items that don't resolve on TMDB are dropped. A pack with
fewer than 4 resolved items is rejected (DynamicPackError).

The local claude CLI call is stubbed (src.core.claude_cli.call_claude_cli,
not the Anthropic API); TMDB calls are stubbed. Only the generator's
parsing + resolution + shaping logic is under test.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.content.dynamic_pack_generator as gen  # noqa: E402


# ----- _theme_fingerprint ------------------------------------------

def test_fingerprint_is_stable_for_identical_input():
    a = gen._theme_fingerprint("Five horror films", "ranked by dread")
    b = gen._theme_fingerprint("Five horror films", "ranked by dread")
    assert a == b


def test_fingerprint_token_order_insensitive():
    """A reordered title with the same tokens should fingerprint the same."""
    a = gen._theme_fingerprint("horror films five", "dread ranked by")
    b = gen._theme_fingerprint("Five horror films", "ranked by dread")
    assert a == b


def test_fingerprint_changes_when_meaningful_token_changes():
    a = gen._theme_fingerprint("Five horror films", "ranked by dread")
    b = gen._theme_fingerprint("Five thriller films", "ranked by dread")
    assert a != b


def test_fingerprint_is_short_and_hex():
    fp = gen._theme_fingerprint("anything here", "and there")
    assert len(fp) == 14
    assert all(c in "0123456789abcdef" for c in fp)


# ----- _parse_payload ----------------------------------------------

def test_parse_strips_code_fences():
    raw = '```json\n{"title": "x", "items": []}\n```'
    payload = gen._parse_payload(raw)
    assert payload["title"] == "x"


def test_parse_extracts_first_object_after_commentary():
    raw = 'Here is the pack:\n{"title": "x", "items": []}\nLet me know.'
    payload = gen._parse_payload(raw)
    assert payload["title"] == "x"


def test_parse_raises_when_no_json():
    with pytest.raises(ValueError, match="no JSON object"):
        gen._parse_payload("just some text, no object at all")


# ----- _resolve_items ----------------------------------------------

class _StubTMDB:
    def __init__(self, movie_map: dict[str, int] | None = None,
                 tv_map: dict[str, int] | None = None) -> None:
        self.movie_map = movie_map or {}
        self.tv_map = tv_map or {}

    def search_movie(self, title: str, year: int | None = None) -> int | None:
        return self.movie_map.get(title.lower())

    def search_tv(self, title: str, year: int | None = None) -> int | None:
        return self.tv_map.get(title.lower())


def test_resolve_drops_unmatched_items(capsys):
    raw_items = [
        {"expected_title": "Real Movie", "year": 1999, "hook": "a", "accent_word": "real"},
        {"expected_title": "Made Up Film", "year": 2050, "hook": "b", "accent_word": ""},
    ]
    tmdb = _StubTMDB(movie_map={"real movie": 1234})
    out = gen._resolve_items(raw_items, "movie", tmdb)
    assert len(out) == 1
    assert out[0]["tmdb_id"] == 1234
    captured = capsys.readouterr()
    assert "DROP no TMDB match" in captured.out


def test_resolve_uses_tv_endpoint_for_tv_kind():
    raw_items = [
        {"expected_title": "Better Call Saul", "year": 2015,
         "hook": "h", "accent_word": ""},
    ]
    tmdb = _StubTMDB(tv_map={"better call saul": 60059})
    out = gen._resolve_items(raw_items, "tv", tmdb)
    assert len(out) == 1
    assert out[0]["tmdb_id"] == 60059
    assert out[0]["kind"] == "tv"


def test_resolve_handles_missing_year_gracefully():
    raw_items = [
        {"expected_title": "Yearless", "hook": "h", "accent_word": ""},
    ]
    tmdb = _StubTMDB(movie_map={"yearless": 7})
    out = gen._resolve_items(raw_items, "movie", tmdb)
    assert len(out) == 1


def test_resolve_handles_bad_year():
    raw_items = [
        {"expected_title": "BadYear", "year": "nineteen", "hook": "h", "accent_word": ""},
    ]
    tmdb = _StubTMDB(movie_map={"badyear": 9})
    out = gen._resolve_items(raw_items, "movie", tmdb)
    assert len(out) == 1


# ----- generate_dynamic_pack (mocked) -------------------------------

_PAYLOAD_JSON = (
    '{"title": "Five films about telegrams",'
    '"subtitle": "before the phone changed everything",'
    '"category": "FILM LIST",'
    '"topic": "film",'
    '"kind": "movie",'
    '"items": ['
    '{"expected_title": "Film A", "year": 1965, "hook": "a hook", "accent_word": "a"},'
    '{"expected_title": "Film B", "year": 1972, "hook": "b hook", "accent_word": "b"},'
    '{"expected_title": "Film C", "year": 1980, "hook": "c hook", "accent_word": "c"},'
    '{"expected_title": "Film D", "year": 1995, "hook": "d hook", "accent_word": "d"},'
    '{"expected_title": "Nonexistent Film", "year": 2050, "hook": "z", "accent_word": ""}'
    '],'
    '"closing_headline": "Which one will you watch?",'
    '"closing_cta": "Comment with your pick.",'
    '"caption": "Five films from the telegram era."}'
)


def _envelope(text: str) -> dict:
    return {"type": "result", "is_error": False, "result": text, "total_cost_usd": 0.01}


def test_generate_returns_pack_in_list_packs_shape(monkeypatch):
    # Stub TMDB - 4 resolve, 1 does not (Nonexistent Film).
    class _T:
        def search_movie(self, title, year=None):
            return {"film a": 1, "film b": 2, "film c": 3, "film d": 4}.get(title.lower())
        def search_tv(self, title, year=None):
            return None
    monkeypatch.setattr(gen, "TMDBClient", _T)

    with patch("src.content.dynamic_pack_generator.call_claude_cli") as fake_call:
        fake_call.return_value = _envelope(_PAYLOAD_JSON)
        pack = gen.generate_dynamic_pack()

    assert pack["title"] == "Five films about telegrams"
    assert pack["category"] == "FILM LIST"
    assert pack["topic"] == "film"
    assert pack["slug"].startswith("dyn_")
    assert pack["_dynamic"] is True
    assert pack["_theme_fingerprint"]
    assert pack["closing"]["headline"] == "Which one will you watch?"
    # 4 of 5 items resolved on TMDB; the unresolved one was dropped.
    assert len(pack["items"]) == 4
    assert all(it["tmdb_id"] for it in pack["items"])
    assert all(it["kind"] == "movie" for it in pack["items"])


def test_calls_cli_with_sonnet(monkeypatch):
    class _T:
        def search_movie(self, title, year=None):
            return {"film a": 1, "film b": 2, "film c": 3, "film d": 4}.get(title.lower())
        def search_tv(self, title, year=None):
            return None
    monkeypatch.setattr(gen, "TMDBClient", _T)

    with patch("src.content.dynamic_pack_generator.call_claude_cli") as fake_call:
        fake_call.return_value = _envelope(_PAYLOAD_JSON)
        gen.generate_dynamic_pack()

    _, kwargs = fake_call.call_args
    assert kwargs["model"] == "sonnet"


def test_generate_raises_when_too_few_items_resolve(monkeypatch):
    """If only 2 of 5 items resolve on TMDB, fail the whole pack."""
    class _T:
        def search_movie(self, title, year=None):
            return {"film a": 1, "film b": 2}.get(title.lower())
        def search_tv(self, title, year=None):
            return None
    monkeypatch.setattr(gen, "TMDBClient", _T)

    with patch("src.content.dynamic_pack_generator.call_claude_cli") as fake_call:
        fake_call.return_value = _envelope(_PAYLOAD_JSON)
        with pytest.raises(gen.DynamicPackError, match="resolved on TMDB"):
            gen.generate_dynamic_pack()


def test_generate_raises_when_cli_unavailable():
    with patch("src.content.dynamic_pack_generator.call_claude_cli") as fake_call:
        fake_call.return_value = None
        with pytest.raises(gen.DynamicPackError, match="claude CLI unavailable"):
            gen.generate_dynamic_pack()


def test_prompt_lists_recent_themes_to_avoid():
    """The model must be told which themes to avoid."""
    prompt = gen._build_prompt(
        recent_themes=["Five war films", "TV shows that ended on time"],
        allowed_categories=["FILM LIST", "TV LIST"],
    )
    assert "RECENT THEMES" in prompt
    assert "Five war films" in prompt
    assert "TV shows that ended on time" in prompt


def test_prompt_bans_circular_shapes():
    """The prompt must explicitly forbid 'german films that are german'
    style circular labelling - the user's specific concern."""
    prompt = gen._build_prompt(recent_themes=[], allowed_categories=["FILM LIST"])
    assert "german films that are german" in prompt.lower()
    assert "circular" in prompt.lower()
