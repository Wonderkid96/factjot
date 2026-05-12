"""Tests for the Wikidata entity resolver."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests

from src.research import wikidata_resolver


def _sparql_response(category_value: str | None) -> dict:
    if category_value is None:
        return {"results": {"bindings": []}}
    return {"results": {"bindings": [{"cat": {"type": "literal", "value": category_value}}]}}


def test_returns_category_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    wikidata_resolver._CACHE.clear()
    mock_resp = MagicMock()
    mock_resp.json.return_value = _sparql_response("Vasili Arkhipov")
    mock_resp.raise_for_status = lambda: None
    monkeypatch.setattr("requests.get", lambda *a, **kw: mock_resp)

    result = wikidata_resolver.resolve_commons_category("Vasili Arkhipov")
    assert result == "Vasili Arkhipov"


def test_returns_none_on_empty_bindings(monkeypatch: pytest.MonkeyPatch) -> None:
    wikidata_resolver._CACHE.clear()
    mock_resp = MagicMock()
    mock_resp.json.return_value = _sparql_response(None)
    mock_resp.raise_for_status = lambda: None
    monkeypatch.setattr("requests.get", lambda *a, **kw: mock_resp)

    result = wikidata_resolver.resolve_commons_category("Nonexistent Entity XYZ")
    assert result is None


def test_returns_none_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    wikidata_resolver._CACHE.clear()
    monkeypatch.setattr("requests.get", lambda *a, **kw: (_ for _ in ()).throw(ConnectionError("refused")))

    result = wikidata_resolver.resolve_commons_category("Anything")
    assert result is None


def test_returns_none_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    wikidata_resolver._CACHE.clear()

    def _raise(*a, **kw):
        raise requests.exceptions.Timeout("3s exceeded")

    monkeypatch.setattr("requests.get", _raise)
    result = wikidata_resolver.resolve_commons_category("Apollo 13")
    assert result is None


def test_cache_prevents_second_network_call(monkeypatch: pytest.MonkeyPatch) -> None:
    wikidata_resolver._CACHE.clear()
    call_count = 0

    def _fake_get(*a, **kw):
        nonlocal call_count
        call_count += 1
        mock_resp = MagicMock()
        mock_resp.json.return_value = _sparql_response("Apollo 13")
        mock_resp.raise_for_status = lambda: None
        return mock_resp

    monkeypatch.setattr("requests.get", _fake_get)
    first = wikidata_resolver.resolve_commons_category("Apollo 13")
    second = wikidata_resolver.resolve_commons_category("Apollo 13")

    assert first == second == "Apollo 13"
    assert call_count == 1


def test_none_result_is_also_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    wikidata_resolver._CACHE.clear()
    call_count = 0

    def _fail(*a, **kw):
        nonlocal call_count
        call_count += 1
        raise ConnectionError("fail")

    monkeypatch.setattr("requests.get", _fail)
    wikidata_resolver.resolve_commons_category("Unknown Thing")
    wikidata_resolver.resolve_commons_category("Unknown Thing")

    assert call_count == 1
