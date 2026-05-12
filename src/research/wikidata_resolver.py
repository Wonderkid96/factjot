"""Wikidata entity resolver: maps entity names to Wikimedia Commons categories.

Queries the Wikidata SPARQL endpoint for the P373 (Commons category) claim.
Results are cached in-process. All errors produce a None return so callers
never block the footage pipeline.
"""
from __future__ import annotations

import requests

_SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
_TIMEOUT_S = 3
_USER_AGENT = "factjot-bot/1.0 (tobyjohnsonemail@gmail.com)"

_CACHE: dict[str, str | None] = {}


def resolve_commons_category(entity_name: str) -> str | None:
    """Return the Wikimedia Commons category for entity_name, or None.

    Uses Wikidata P373 (Commons category). Caches per process run.
    Returns None on any network failure, timeout, or missing P373 claim.

    Args:
        entity_name: Human-readable English entity name, e.g. "Vasili Arkhipov".

    Returns:
        Category name without the "Category:" prefix, e.g. "Vasili Arkhipov",
        or None if not found or on any error.
    """
    cache_key = entity_name.strip().lower()
    if cache_key in _CACHE:
        return _CACHE[cache_key]

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
        result: str | None = bindings[0]["cat"]["value"] if bindings else None
    except Exception:
        result = None

    _CACHE[cache_key] = result
    return result
