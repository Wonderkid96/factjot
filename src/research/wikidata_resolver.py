"""Wikidata entity resolver: maps entity names to Wikimedia Commons categories.

Queries the Wikidata SPARQL endpoint for the P373 (Commons category) claim.
Results are cached in-process. All errors produce a None return so callers
never block the footage pipeline.
"""
from __future__ import annotations

import requests

_SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
_WIKIDATA_API = "https://www.wikidata.org/w/api.php"
_TIMEOUT_S = 3
_USER_AGENT = "factjot-bot/1.0 (tobyjohnsonemail@gmail.com)"

_CACHE: dict[str, str | None] = {}


def resolve_commons_category(entity_name: str) -> str | None:
    """Return the Wikimedia Commons category for entity_name, or None.

    Strategy:
      1. Exact SPARQL label match (fast, zero false positives).
      2. Wikidata entity text search (wbsearchentities) — handles common names,
         redirects, and aliases. "Lancaster bomber" -> Q170079 (Avro Lancaster)
         -> Commons category "Avro Lancaster". Tries up to 3 results.

    Caches per process run. Returns None on any network failure or no P373.
    """
    cache_key = entity_name.strip().lower()
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    result = _exact_sparql(entity_name) or _fuzzy_search(entity_name)
    _CACHE[cache_key] = result
    return result


def _exact_sparql(entity_name: str) -> str | None:
    """Exact rdfs:label match via SPARQL."""
    escaped = entity_name.replace('"', '\\"')
    sparql = f"""SELECT ?cat WHERE {{
  ?item rdfs:label "{escaped}"@en .
  ?item wdt:P373 ?cat .
}}
LIMIT 1"""
    try:
        resp = requests.get(
            _SPARQL_ENDPOINT,
            params={"query": sparql, "format": "json"},
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT_S,
        )
        resp.raise_for_status()
        bindings = resp.json()["results"]["bindings"]
        return bindings[0]["cat"]["value"] if bindings else None
    except Exception:
        return None


def _fuzzy_search(entity_name: str) -> str | None:
    """wbsearchentities fallback: handles common names, aliases, and redirects."""
    try:
        resp = requests.get(
            _WIKIDATA_API,
            params={
                "action": "wbsearchentities",
                "search": entity_name,
                "language": "en",
                "type": "item",
                "limit": "3",
                "format": "json",
            },
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT_S,
        )
        resp.raise_for_status()
        for hit in resp.json().get("search", []):
            item_id = hit.get("id")
            if not item_id:
                continue
            cat = _fetch_p373(item_id)
            if cat:
                return cat
    except Exception:
        pass
    return None


def _fetch_p373(item_id: str) -> str | None:
    """Fetch the P373 (Commons category) property for a known Wikidata item ID."""
    sparql = f"SELECT ?cat WHERE {{ wd:{item_id} wdt:P373 ?cat . }} LIMIT 1"
    try:
        resp = requests.get(
            _SPARQL_ENDPOINT,
            params={"query": sparql, "format": "json"},
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT_S,
        )
        resp.raise_for_status()
        bindings = resp.json()["results"]["bindings"]
        return bindings[0]["cat"]["value"] if bindings else None
    except Exception:
        return None
