"""Minimal OMDb API client for IMDB + Rotten Tomatoes scores.

OMDb (omdbapi.com) is the only practical free source for both IMDB rating
and Rotten Tomatoes score in a single call. Free tier: 1000 requests/day.
Sign up at omdbapi.com → Patreon-free tier → key by email.

We use OMDb only when:
    - OMDB_API_KEY is set in the environment
    - the pack item does NOT have hardcoded imdb_score / rotten_score

Pack-level overrides always win. OMDb is fallback automation, not the source
of truth — scores can drift over time and a curated pack is allowed to
freeze them.

Public API:

    OMDbClient.scores_by_imdb_id(imdb_id) -> {"imdb": "7.9", "rotten": "94%"}
        Returns missing keys when OMDb has nothing. Empty dict if no key set.
"""
from __future__ import annotations

import os
from typing import Any

import requests

OMDB_BASE = "https://www.omdbapi.com/"


class OMDbClient:
    def __init__(self, api_key: str | None = None, timeout: int = 8) -> None:
        self._key = api_key or os.environ.get("OMDB_API_KEY", "")
        self._timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self._key)

    def scores_by_imdb_id(self, imdb_id: str) -> dict[str, str]:
        """Return {imdb, rotten} where present. Empty dict if disabled or no data."""
        if not self.enabled or not imdb_id:
            return {}
        try:
            r = requests.get(
                OMDB_BASE,
                params={"apikey": self._key, "i": imdb_id, "tomatoes": "true"},
                timeout=self._timeout,
            )
            if r.status_code >= 400:
                return {}
            data: dict[str, Any] = r.json()
            if data.get("Response") != "True":
                return {}
        except (requests.RequestException, ValueError):
            return {}

        out: dict[str, str] = {}
        imdb = data.get("imdbRating")
        if imdb and imdb != "N/A":
            out["imdb"] = imdb
        for entry in data.get("Ratings", []):
            if entry.get("Source") == "Rotten Tomatoes":
                val = entry.get("Value", "")
                if val:
                    out["rotten"] = val
                break
        return out


__all__ = ["OMDbClient"]
