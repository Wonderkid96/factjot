"""Minimal TMDB API client for list-format carousels.

We use TMDB to populate film/TV list posts (e.g. "5 mind-melting sci-fi films").
Auth is via the v4 read access token (Bearer header). The v3 api_key is also
in .env as a backup but every call here uses the Bearer flow.

Public API:

    TMDBClient.get_movie(tmdb_id) -> dict        # title, year, overview, ids
    TMDBClient.get_movie_images(tmdb_id) -> dict # poster URLs, backdrop URLs
    TMDBClient.poster_url(path, size="w780")     # build a CDN URL
    TMDBClient.backdrop_url(path, size="w1280")  # ditto for backdrops

We keep this small on purpose: list packs are pre-curated by humans (we know
which films we want to feature). The client just resolves IDs to titles +
poster/backdrop URLs.
"""
from __future__ import annotations

import os
from typing import Any

import requests

TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG_BASE = "https://image.tmdb.org/t/p"  # then /<size>/<path>

# Sizes TMDB accepts. Posters: w92/154/185/342/500/780/original.
# Backdrops: w300/780/1280/original. We default to w780 poster + w1280 backdrop
# which look crisp at our 1080x1350 canvas.
DEFAULT_POSTER_SIZE = "w780"
DEFAULT_BACKDROP_SIZE = "w1280"


class TMDBError(RuntimeError):
    pass


class TMDBClient:
    def __init__(self, read_token: str | None = None, timeout: int = 12) -> None:
        token = read_token or os.environ.get("TMDB_READ_TOKEN")
        if not token:
            raise TMDBError("TMDB_READ_TOKEN missing from environment")
        self._headers = {
            "Authorization": f"Bearer {token}",
            "accept": "application/json",
        }
        self._timeout = timeout

    # ----- core ----------------------------------------------------------

    def _get(self, path: str, params: dict | None = None) -> dict[str, Any]:
        url = f"{TMDB_BASE}{path}"
        r = requests.get(url, headers=self._headers, params=params or {}, timeout=self._timeout)
        if r.status_code >= 400:
            raise TMDBError(f"TMDB {path} -> {r.status_code}: {r.text[:200]}")
        return r.json()

    # ----- public --------------------------------------------------------

    def get_movie(self, tmdb_id: int) -> dict[str, Any]:
        """Return the core movie record for a TMDB id."""
        return self._get(f"/movie/{tmdb_id}", {"language": "en-GB"})

    def get_movie_images(self, tmdb_id: int) -> dict[str, Any]:
        """Return posters + backdrops for a TMDB id.

        Pulls language-agnostic images (include_image_language=null,en) so we
        always have a fallback if the en-GB poster set is empty.
        """
        return self._get(
            f"/movie/{tmdb_id}/images",
            {"include_image_language": "en,null"},
        )

    def get_movie_credits(self, tmdb_id: int) -> dict[str, Any]:
        """Cast + crew. We pull the director from the crew array."""
        return self._get(f"/movie/{tmdb_id}/credits")

    # ----- TV ------------------------------------------------------------

    def get_tv_show(self, tmdb_id: int) -> dict[str, Any]:
        """Return the core TV-show record. Different shape from movies:
            name, first_air_date, last_air_date, number_of_seasons,
            number_of_episodes, episode_run_time (list, often empty),
            created_by (list of creator dicts), genres, networks, etc.
        """
        return self._get(f"/tv/{tmdb_id}", {"language": "en-GB"})

    def get_tv_credits(self, tmdb_id: int) -> dict[str, Any]:
        """Cast + crew for a TV show.

        TV doesn't have a single "Director" - series have creators (in
        `created_by` on the show record) plus rotating per-episode directors.
        For our slide we treat the first `created_by` as the credit.
        """
        return self._get(f"/tv/{tmdb_id}/credits")

    def get_tv_external_ids(self, tmdb_id: int) -> dict[str, Any]:
        """Pulls the show's IMDB id (tt-format), used for OMDb score lookups."""
        return self._get(f"/tv/{tmdb_id}/external_ids")

    def get_tv_watch_providers(self, tmdb_id: int, region: str = "GB") -> list[str]:
        """UK flatrate streaming providers for a TV show. Same cleaning
        as the movie equivalent - unknown providers and sub-channels are
        filtered out so the slide stays clean.
        """
        try:
            data = self._get(f"/tv/{tmdb_id}/watch/providers")
        except TMDBError:
            return []
        region_block = (data.get("results") or {}).get(region) or {}
        flatrate = region_block.get("flatrate") or []
        flatrate.sort(key=lambda p: p.get("display_priority", 999))
        out: list[str] = []
        seen: set[str] = set()
        for p in flatrate:
            name = p.get("provider_name", "")
            short = self._short_provider_name(name)
            if not short or short in seen:
                continue
            if any(bad in name.lower() for bad in ("channel", "with ads", "free", "trial")):
                continue
            seen.add(short)
            out.append(short)
        return out

    @staticmethod
    def first_creator_name(show: dict, credits: dict | None = None) -> str:
        """Name of the show's primary creator. Falls back to the first
        executive producer if no credited creator exists.
        """
        creators = show.get("created_by") or []
        if creators and creators[0].get("name"):
            return creators[0]["name"]
        if credits:
            for c in credits.get("crew", []):
                if c.get("job") == "Executive Producer" and c.get("name"):
                    return c["name"]
        return ""

    def get_watch_providers(self, tmdb_id: int, region: str = "GB") -> list[str]:
        """Return streaming-service short names for a region (default GB).

        TMDB's watch-provider data covers flatrate (subscription), rent, and
        buy. We only surface flatrate here - that's what "where to watch"
        means to most viewers. List is ordered by TMDB's display priority.

        We dedupe near-identical entries (e.g. "Amazon Prime Video" and
        "Amazon Prime Video with Ads" both collapse to "PRIME") and skip
        anything that doesn't map to a known short name - that's what
        filters out random channel-pass entries like "Arrow Video Amazon
        Channel" which aren't where most viewers will actually watch.
        """
        try:
            data = self._get(f"/movie/{tmdb_id}/watch/providers")
        except TMDBError:
            return []
        region_block = (data.get("results") or {}).get(region) or {}
        flatrate = region_block.get("flatrate") or []
        flatrate.sort(key=lambda p: p.get("display_priority", 999))
        out: list[str] = []
        seen: set[str] = set()
        for p in flatrate:
            name = p.get("provider_name", "")
            short = self._short_provider_name(name)
            # Skip anything we don't recognise OR which looks like a
            # sub-channel ("X Channel", "with Ads") - these are noisy.
            if not short or short in seen:
                continue
            if any(bad in name.lower() for bad in (
                "channel", "with ads", "free", "trial",
            )):
                continue
            seen.add(short)
            out.append(short)
        return out

    @staticmethod
    def _short_provider_name(name: str) -> str:
        """Compact provider names for slide chips.

        Returns "" for anything not in this whitelist - that's intentional.
        We only show major UK services so the slide stays clean. Sub-channel
        rentals get filtered out by the caller.
        """
        if not name:
            return ""
        # Normalise for matching.
        n = name.lower()
        if "amazon prime" in n or n in ("prime video", "prime"):
            return "PRIME"
        if "apple tv" in n:
            return "APPLE TV+"
        if "netflix" in n:
            return "NETFLIX"
        if "disney" in n:
            return "DISNEY+"
        if "iplayer" in n:
            return "iPLAYER"
        if "mubi" in n:
            return "MUBI"
        if "now tv cinema" in n or n == "now" or n == "now tv":
            return "NOW"
        if "sky go" in n or n == "sky":
            return "SKY"
        if "channel 4" in n or "all 4" in n:
            return "CHANNEL 4"
        if "itvx" in n or "itv hub" in n:
            return "ITVX"
        if "paramount" in n:
            return "PARAMOUNT+"
        if "bfi player" in n:
            return "BFI"
        return ""  # filter unknowns

    def director_name(self, credits: dict[str, Any]) -> str:
        for member in credits.get("crew", []):
            if member.get("job") == "Director":
                return member.get("name", "")
        return ""

    # ----- url helpers ---------------------------------------------------

    @staticmethod
    def poster_url(path: str | None, size: str = DEFAULT_POSTER_SIZE) -> str:
        if not path:
            return ""
        return f"{TMDB_IMG_BASE}/{size}{path}"

    @staticmethod
    def backdrop_url(path: str | None, size: str = DEFAULT_BACKDROP_SIZE) -> str:
        if not path:
            return ""
        return f"{TMDB_IMG_BASE}/{size}{path}"

    @classmethod
    def best_backdrop(cls, movie: dict, images: dict | None = None,
                      size: str = DEFAULT_BACKDROP_SIZE) -> str:
        """Pick the strongest backdrop available for a film.

        Prefers the canonical backdrop_path on the movie record. Falls back
        to the highest-rated entry in /images.backdrops if needed.
        """
        if movie.get("backdrop_path"):
            return cls.backdrop_url(movie["backdrop_path"], size)
        if images:
            backdrops = sorted(
                images.get("backdrops", []),
                key=lambda b: (b.get("vote_average", 0), b.get("width", 0)),
                reverse=True,
            )
            if backdrops:
                return cls.backdrop_url(backdrops[0]["file_path"], size)
        return ""

    @classmethod
    def best_poster(cls, movie: dict, images: dict | None = None,
                    size: str = DEFAULT_POSTER_SIZE) -> str:
        if movie.get("poster_path"):
            return cls.poster_url(movie["poster_path"], size)
        if images:
            posters = sorted(
                images.get("posters", []),
                key=lambda p: (p.get("vote_average", 0), p.get("width", 0)),
                reverse=True,
            )
            if posters:
                return cls.poster_url(posters[0]["file_path"], size)
        return ""


__all__ = ["TMDBClient", "TMDBError", "DEFAULT_POSTER_SIZE", "DEFAULT_BACKDROP_SIZE"]
