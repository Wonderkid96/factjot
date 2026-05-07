"""Find a unique, on-topic photo for each carousel slide.

Sources, tried in order until one returns an image we have NEVER used before:
    1. Pexels API           (free key, best photo quality)
    2. Pixabay API          (free key, big library)
    3. Openverse API        (free, no key, aggregates Flickr / Wikimedia / etc)
    4. Wikipedia opensearch (find the closest article, take its lead image)
    5. Wikimedia Commons    (file search)

Behaviour:
    * We pull MANY candidates from each source and skip any whose URL or
      pixel-content SHA we've stored in `data/used_images.jsonl` from a
      previous post. So no slide repeats an image already shipped.
    * Queries are progressively broadened (slide-specific → topic-only) so
      we don't fall back to a generic gradient.
    * No procedural fallback - if every source for every variant fails,
      we raise NoImageFound so the slide is flagged for review rather
      than shipping with a black/white gradient.

Cache layout (folder per category):
    data/images/<category-slug>/<query-slug>.jpg
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import requests
from PIL import Image
from dotenv import load_dotenv

from src.research.used_images import UsedImageLedger

log = logging.getLogger(__name__)


@dataclass
class PoolCandidate:
    """A single validated image candidate ready for scoring and selection."""
    provider:     str
    url:          str
    meta:         str
    content:      bytes
    img:          Image.Image
    credit_name:  str
    credit_url:   str
    allow_reason: str
    width:        int = 0
    height:       int = 0

def _alias_matches(alias: str, m: str) -> bool:
    """Return True if every word in alias is a complete alphanumeric token in m.

    Uses token-boundary matching, not substring matching, so 'Concord' does not
    false-match 'Concorde'. m is expected to already be lowercased by the caller.
    Multi-word aliases match words in any order.
    """
    meta_tokens = set(re.findall(r"[a-z0-9]+", m))
    return all(w.lower() in meta_tokens for w in alias.split())


WEAK_QUERY_WORDS = {
    "single", "every", "anything", "nothing", "something", "someone",
    "produces", "producing", "produce", "produced", "containing", "contains",
    "appears", "appeared", "becomes", "became", "begins", "began",
    "create", "creates", "created", "show", "showed", "shows", "shown",
    "find", "finds", "found", "finding", "near", "almost", "later", "always",
    "whole", "entire", "pieces", "piece", "part", "parts",
    "different", "various", "several", "kind", "kinds", "type", "types",
    "way", "ways", "thing", "things", "place", "places", "world", "modern",
    "ancient", "recent", "current", "earlier", "today",
    "stop", "stopped", "stopping", "starting", "starts",
    "people", "across", "through", "during", "before", "after",
}

# Ambiguous one-word subjects that often return the wrong domain unless
# we lead with a topic disambiguator (for example Venus flytrap vs Venus).
AMBIGUOUS_SUBJECTS_BY_TOPIC = {
    # Single-word subjects that overlap with non-space meanings:
    #   Olympus    → camera brand
    #   Apollo     → mission posters / Greek god
    #   Andromeda  → constellation / girl name
    #   Voyager    → ship / spacecraft / film name
    #   Europa     → continent
    #   Io         → cinematography term
    "space": {"venus", "mercury", "saturn", "jupiter", "mars",
               "olympus", "apollo", "andromeda", "voyager", "europa", "io"},
    "earth": {"mercury"},
}


class NoImageFound(Exception):
    """Raised when no fresh, on-topic image can be sourced for a slide."""


class _Candidate:
    __slots__ = ("provider", "url", "img", "content", "credit_name", "credit_url", "meta_text")

    def __init__(self, provider: str, url: str, img: Image.Image, content: bytes,
                 credit_name: str = "", credit_url: str = "", meta_text: str = "") -> None:
        self.provider = provider
        self.url = url
        self.img = img
        self.content = content
        self.credit_name = credit_name
        self.credit_url = credit_url
        self.meta_text = meta_text


class ImageFetcher:
    PEXELS_SEARCH = "https://api.pexels.com/v1/search"
    PIXABAY_SEARCH = "https://pixabay.com/api/"
    OPENVERSE_SEARCH = "https://api.openverse.org/v1/images/"
    WIKI_OPENSEARCH = "https://en.wikipedia.org/w/api.php"
    WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
    COMMONS_API = "https://commons.wikimedia.org/w/api.php"
    NASA_SEARCH = "https://images-api.nasa.gov/search"
    SMITHSONIAN_SEARCH = "https://api.si.edu/openaccess/api/v1.0/search"
    INATURALIST_SEARCH = "https://api.inaturalist.org/v1/taxa"
    FLICKR_SEARCH      = "https://www.flickr.com/services/rest/"

    MIN_IMAGE_BYTES = 12 * 1024
    MIN_IMAGE_DIM = 480
    MAX_RESULTS_PER_PROVIDER = 24

    # Provider preference per topic. The first matched key in the topic
    # string wins. Sources not listed here run in default order.
    TOPIC_PROVIDER_ORDER = {
        "nature": ("pexels", "pixabay", "inaturalist", "openverse", "wiki", "commons", "nasa", "smithsonian"),
        "biology": ("pexels", "pixabay", "inaturalist", "openverse", "wiki", "commons", "nasa", "smithsonian"),
        "ocean": ("pexels", "pixabay", "inaturalist", "openverse", "wiki", "commons", "nasa", "smithsonian"),
        "space": ("nasa", "wiki", "commons", "smithsonian", "openverse", "pexels", "pixabay", "inaturalist"),
        "earth": ("pexels", "pixabay", "wiki", "openverse", "commons", "nasa", "smithsonian", "inaturalist"),
        "history": ("pexels", "pixabay", "wiki", "commons", "smithsonian", "openverse", "nasa", "inaturalist"),
        "tech": ("pexels", "pixabay", "wiki", "commons", "openverse", "smithsonian", "nasa", "inaturalist"),
        # editorial: named subjects (aircraft, events, people, technology).
        # Commons first: file titles contain the proper name ("Concorde arp.jpg").
        # Wikipedia lead image: by definition the right photo for the article.
        # Smithsonian: strong historical archive, well-tagged.
        # Pixabay last: some historical photos, but broad tag matching needs alias gate.
        # Pexels excluded: lifestyle stock, unreliable for specific named subjects.
        # Openverse excluded 2026-05-06: API works unauthenticated (240 results for "Concorde aircraft")
        #   but ~100% of results are Flickr-hosted images. Flickr returns HTTP 429 on direct
        #   image download from our bot IP regardless of Referer header. Re-evaluate if we
        #   get a Flickr API key or if Openverse adds a non-Flickr CDN proxy for full images.
        # wiki_article: fetches all inline photos from the Wikipedia article body,
        #   not just the lead image. Yields cockpit, cabin, historical, and detail shots.
        "editorial": ("commons", "wiki", "wiki_article", "smithsonian", "flickr", "pixabay"),
    }
    DEFAULT_PROVIDER_ORDER = ("pexels", "pixabay", "flickr", "openverse", "wiki", "commons", "inaturalist", "nasa", "smithsonian")
    # Keep the system flexible: Pexels/Pixabay first, but allow fallbacks.
    # Relevance is handled via stronger query variants + soft metadata checks.
    SPACE_POSITIVE_TERMS = {
        "space", "planet", "astronomy", "galaxy", "nebula", "cosmos", "solar", "orbit",
        "saturn", "venus", "mars", "jupiter", "mercury", "moon", "sun", "star", "milky way",
        "spacecraft", "satellite", "telescope", "lunar", "celestial", "asteroid", "comet",
    }

    # ALLOWLIST. For SPACE topic an image's alt text MUST contain at least one
    # of these real-celestial-subject words. Pexels is full of "space-themed"
    # stock (camera lens-flare = "sun", studio control panel = "shuttle cockpit")
    # which were slipping past a positive-only filter. Words deliberately
    # excluded: "sun", "star", "earth" alone - they match too loosely (lens
    # flares, starfield wallpapers, Earth toned objects).
    SPACE_REQUIRED_TERMS = {
        "galaxy", "galaxies", "nebula", "milky way", "constellation",
        "saturn", "venus", "mars", "martian", "jupiter", "jovian",
        "mercury planet", "neptune", "uranus", "pluto",
        "moon surface", "moon landing", "lunar",
        "comet", "asteroid", "meteor", "meteorite", "meteor shower",
        "astronaut", "cosmonaut", "spacewalk", "spacesuit",
        "spacecraft", "rocket launch", "rocket engine",
        "satellite orbit", "iss", "international space station",
        "space station", "space shuttle", "launch pad",
        "solar system", "outer space", "deep space", "interstellar",
        "starfield", "cosmos", "universe",
        "supernova", "black hole", "hubble", "james webb",
        "voyager 1", "voyager 2", "voyager probe",
        "nasa image", "nasa photo", "nasa mission",
        "olympus mons", "mariner valley", "valles marineris",
    }
    SPACE_NEGATIVE_TERMS = {
        # Plant/wildlife contamination
        "leaf", "fern", "flower", "plant", "botanical", "garden", "forest", "tree", "mushroom",
        "bird", "animal", "insect", "wildlife",
        # Statue / artwork contamination (Venus de Milo, etc.)
        "statue", "sculpture", "marble", "louvre", "milo", "venus de",
        # Abstract / studio renders that aren't real photography
        "abstract", "3d render", "render of", "gradient", "metal label",
        # Studio shoots and lifestyle that contain space-y words but aren't space
        "model posing", "hoodie", "person with",
        # Camera / lens / photography contamination - "Olympus", "Sun" can
        # match a vintage camera with sun-flare bokeh.
        "camera", "vintage camera", "trip 35", "lens", "dslr", "shutter",
        "bokeh", "flash", "polaroid", "instax", "tripod",
        # Cityscape / building contamination (Venus + Viña del Mar conjunction).
        "city", "skyline", "aerial view", "building", "street", "rooftop",
        "village", "town",
    }
    BIOLOGY_NEGATIVE_TERMS = {
        # Food contamination
        "grilled", "served", "plate", "gourmet", "sauce", "recipe", "cooked",
        "cuisine", "restaurant", "kitchen", "meal", "garnish", "marinated",
        "dish", "platter", "delicacy", "fried", "stir-fried", "appetizer",
        "tentacles served", "tentacle dipped",
        # Jewelry / decorative / artistic representations of animals
        "ring", "necklace", "pendant", "bracelet", "earring", "brooch",
        "tattoo", "tattoos", "logo", "drawing", "illustration", "artwork",
        "sculpture", "figurine", "ornament", "decorative", "leather",
        "embroidery", "embroidered", "knitted", "stuffed toy", "plush",
        "cartoon", "vector", "icon",
    }
    HISTORY_NEGATIVE_TERMS = {
        "halloween", "cosplay", "costume", "themed", "photoshoot",
        "model posing", "festival makeup", "stage makeup",
    }
    NEGATIVE_TERMS_BY_TOPIC = {
        "space": SPACE_NEGATIVE_TERMS,
        "earth": SPACE_NEGATIVE_TERMS,
        "biology": BIOLOGY_NEGATIVE_TERMS,
        "nature": BIOLOGY_NEGATIVE_TERMS,
        "ocean": BIOLOGY_NEGATIVE_TERMS,
        "history": HISTORY_NEGATIVE_TERMS,
    }
    INTENT_STOPWORDS = {
        # Topic-shaped words. They appear in the disambiguator suffix we tack
        # onto queries (e.g. "Tardigrades animal wildlife") and must not count
        # as primary intent - otherwise any wildlife photo with "wildlife" in
        # its alt text passes the candidate-allowed gate even when the actual
        # subject is missing (e.g. a deer photo for a tardigrade fact).
        "planet", "space", "astronomy", "science", "photo", "photography", "image",
        "animal", "wildlife", "nature", "creature", "marine", "underwater",
        "geology", "landscape", "historic", "technology", "computer", "laboratory",
        "the", "a", "an", "of", "and", "for", "in", "on", "to", "with",
    }
    TERM_EXPANSIONS_BIO = {
        "tardigrade": {"tardigrade", "tardigrades", "water bear", "microscope", "microscopic"},
    }
    TERM_EXPANSIONS = {
        "wifi": {"wifi", "wi-fi", "wireless", "router", "network"},
        "qwerty": {"qwerty", "keyboard", "typewriter"},
        "neutron": {"neutron", "star", "space"},
        "apollo": {"apollo", "moon", "astronaut", "space"},
        "metaverse": {"metaverse", "virtual", "reality", "vr"},
    }

    # Disambiguator word appended to a single-word keyword so search engines
    # don't confuse, say, "Venus" the planet with "Venus" the plant. The
    # word should be specific enough to anchor the right meaning but generic
    # enough to combine with any subject in the topic.
    TOPIC_DISAMBIGUATOR = {
        "space": "planet astronomy",
        "earth": "geology landscape",
        "ocean": "marine underwater",
        "nature": "animal wildlife",
        "biology": "animal wildlife",
        "history": "historic photograph",
        "tech": "technology",
        "ai": "computer technology",
        "science": "science laboratory",
    }

    def __init__(self, cache_dir: str | None = None,
                 target_size: tuple[int, int] = (1080, 1350),
                 ledger: UsedImageLedger | None = None) -> None:
        from src.core.paths import IMAGES_CACHE
        load_dotenv()
        self.cache_dir = Path(cache_dir) if cache_dir else IMAGES_CACHE
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.target_size = target_size
        self.pexels_key = os.getenv("PEXELS_API_KEY", "").strip()
        self.pixabay_key = os.getenv("PIXABAY_API_KEY", "").strip()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "factjot-bot/1.0 (educational carousel renderer)"})
        self.ledger = ledger or UsedImageLedger()

    # ----- public API -----

    def fetch(self, query: str, topic: str = "", seed: str = "",
              post_id: str = "", slide_index: int = 0,
              intent_text: str = "",
              source_aliases: list[str] | None = None,
              negative_terms: list[str] | None = None,
              context_words: list[str] | None = None,
              extra_fallbacks: list[str] | None = None,
              ) -> tuple[Path, dict[str, str]]:
        category = self._slug(topic) or "misc"
        post_slug = self._slug(post_id) if post_id else "unassigned"
        category_dir = self.cache_dir / category / post_slug
        category_dir.mkdir(parents=True, exist_ok=True)

        cache_key = self._cache_key(query, topic, seed)
        slide_token = f"s{slide_index:02d}" if slide_index > 0 else "s00"
        cached = category_dir / f"{slide_token}_{cache_key}.jpg"

        for variant in self._query_variants(query, topic, extra_fallbacks=extra_fallbacks):
            for cand in self._iter_candidates(variant, topic=topic):
                allowed, reason = self._candidate_allowed(
                    cand, topic, variant, intent_text,
                    source_aliases=source_aliases,
                    negative_terms=negative_terms,
                    context_words=context_words,
                )
                if not allowed:
                    log.debug("REJECT %s | provider=%s | meta=%r", reason, cand.provider, (cand.meta_text or "")[:120])
                    continue
                content_sha = self.ledger.sha256_of(cand.content)
                if self.ledger.is_used(url=cand.url, sha256=content_sha):
                    log.debug("SKIP already_used | provider=%s | url=%s", cand.provider, cand.url[:80])
                    continue
                self._save(cand.img, cached)
                self.ledger.mark_used(
                    url=cand.url, sha256=content_sha, provider=cand.provider,
                    post_id=post_id, slide_index=slide_index, query=variant,
                )
                return cached, {
                    "provider": cand.provider,
                    "name": cand.credit_name,
                    "url": cand.credit_url,
                    "meta": cand.meta_text or "",
                    "reason": reason,
                }

        raise NoImageFound(f"No fresh image for query={query!r} topic={topic!r}")

    def fetch_pool(
        self,
        query: str,
        topic: str = "",
        post_id: str = "",
        slide_index: int = 0,
        intent_text: str = "",
        source_aliases: list[str] | None = None,
        negative_terms: list[str] | None = None,
        context_words: list[str] | None = None,
        extra_fallbacks: list[str] | None = None,
        max_pool: int = 20,
    ) -> list[PoolCandidate]:
        """Collect up to max_pool candidates that pass _candidate_allowed().

        Does NOT save or mark images as used — call commit_candidate() on the
        selected winner afterwards.
        """
        pool: list[PoolCandidate] = []
        seen_urls: set[str] = set()

        for variant in self._query_variants(query, topic, extra_fallbacks=extra_fallbacks):
            for cand in self._iter_candidates(variant, topic=topic):
                if cand.url in seen_urls:
                    continue
                allowed, reason = self._candidate_allowed(
                    cand, topic, variant, intent_text,
                    source_aliases=source_aliases,
                    negative_terms=negative_terms,
                    context_words=context_words,
                )
                if not allowed:
                    log.debug("POOL_REJECT %s | %s | meta=%r", reason, cand.provider, (cand.meta_text or "")[:80])
                    continue
                seen_urls.add(cand.url)
                w, h = cand.img.size if cand.img else (0, 0)
                pool.append(PoolCandidate(
                    provider=cand.provider,
                    url=cand.url,
                    meta=cand.meta_text or "",
                    content=cand.content,
                    img=cand.img,
                    credit_name=cand.credit_name,
                    credit_url=cand.credit_url,
                    allow_reason=reason,
                    width=w,
                    height=h,
                ))
                if len(pool) >= max_pool:
                    return pool
        return pool

    def commit_candidate(
        self,
        cand: PoolCandidate,
        query: str,
        topic: str,
        post_id: str,
        slide_index: int,
    ) -> tuple[Path, dict[str, str]]:
        """Save the selected candidate to cache and mark it as used in the ledger."""
        category  = self._slug(topic) or "misc"
        post_slug = self._slug(post_id) if post_id else "unassigned"
        category_dir = self.cache_dir / category / post_slug
        category_dir.mkdir(parents=True, exist_ok=True)

        cache_key   = self._cache_key(query, topic, "")
        slide_token = f"s{slide_index:02d}" if slide_index > 0 else "s00"
        cached      = category_dir / f"{slide_token}_{cache_key}.jpg"

        self._save(cand.img, cached)
        sha = self.ledger.sha256_of(cand.content)
        self.ledger.mark_used(
            url=cand.url, sha256=sha, provider=cand.provider,
            post_id=post_id, slide_index=slide_index, query=query,
        )
        return cached, {
            "provider": cand.provider,
            "name":     cand.credit_name,
            "url":      cand.credit_url,
            "meta":     cand.meta,
            "reason":   cand.allow_reason,
        }

    # ----- query construction -----

    # Topic strings that are pipeline labels, not meaningful search terms.
    _NON_SEARCH_TOPICS = frozenset({"editorial", "misc", "general", "fact", "news", "film"})

    def _query_variants(self, query: str, topic: str,
                        extra_fallbacks: list[str] | None = None) -> list[str]:
        """Build progressively broader queries.

        Order: specific slot query → first two words → proper noun →
        caller-supplied fallbacks (visual_subject, fallback_query) →
        topic disambiguator (only if topic is a real search term).
        Never degrades to bare "editorial" or other pipeline label strings.
        """
        cleaned = re.sub(r"\[/?[ihab]\]", "", query)
        words = re.findall(r"[A-Za-z][A-Za-z'\-]+", cleaned)
        kept = [w for w in words if w.lower() not in WEAK_QUERY_WORDS]

        variants: list[str] = []

        def add(s: str) -> None:
            s = s.strip()
            if s and s.lower() not in [v.lower() for v in variants]:
                variants.append(s)

        topic_low = topic.strip().lower()
        disamb = self.TOPIC_DISAMBIGUATOR.get(topic_low, "")
        proper = next((w for w in kept if w[0].isupper() and len(w) >= 3), None)
        first = kept[0] if kept else None
        subject = proper or first
        subject_low = (subject or "").lower()
        ambiguous_for_topic = AMBIGUOUS_SUBJECTS_BY_TOPIC.get(topic_low, set())
        subject_is_ambiguous = bool(subject) and subject_low in ambiguous_for_topic

        if subject and disamb and subject_is_ambiguous:
            add(f"{subject} {disamb}")
            if topic_low == "space":
                add(f"{subject} planet space")
        if len(kept) >= 2:
            add(" ".join(kept[:2]))
        if subject:
            add(subject)
        if disamb:
            add(disamb)

        # Caller-supplied fallbacks (e.g. fallback_query, visual_subject).
        for fb in (extra_fallbacks or []):
            if fb:
                add(fb)

        # Only use the topic string as a search term if it is a real search
        # concept, not a pipeline routing label like "editorial".
        if topic and topic_low not in self._NON_SEARCH_TOPICS:
            add(topic.strip())

        return variants

    def _provider_order(self, topic: str) -> tuple[str, ...]:
        topic_low = topic.strip().lower()
        return self.TOPIC_PROVIDER_ORDER.get(topic_low, self.DEFAULT_PROVIDER_ORDER)

    # ----- candidate iterators -----

    def _iter_candidates(self, term: str, topic: str = "") -> Iterator[_Candidate]:
        if not term:
            return
        sources_by_name = {
            "pexels": self._pexels_candidates,
            "pixabay": self._pixabay_candidates,
            "flickr": self._flickr_candidates,
            "openverse": self._openverse_candidates,
            "inaturalist": self._inaturalist_candidates,
            "nasa": self._nasa_candidates,
            "smithsonian": self._smithsonian_candidates,
            "wiki": self._wiki_candidates,
            "wiki_article": self._wiki_article_images_candidates,
            "commons": self._commons_candidates,
        }
        order = self._provider_order(topic)
        for name in order:
            source = sources_by_name.get(name)
            if source is None:
                continue
            try:
                for cand in source(term, topic):
                    if cand is not None:
                        yield cand
            except Exception as exc:
                log.debug("source %s failed for %r: %s", name, term, exc)

    def _pexels_candidates(self, term: str, topic: str = "") -> Iterator[_Candidate]:
        if not self.pexels_key:
            return
        resp = self.session.get(
            self.PEXELS_SEARCH,
            headers={"Authorization": self.pexels_key},
            params={"query": term, "per_page": self.MAX_RESULTS_PER_PROVIDER,
                    "orientation": "portrait", "size": "large"},
            timeout=10,
        )
        if not resp.ok:
            return
        for photo in resp.json().get("photos", [])[: self.MAX_RESULTS_PER_PROVIDER]:
            if not self._pexels_photo_allowed(photo, topic):
                continue
            url = (photo.get("src") or {}).get("large2x") or photo.get("src", {}).get("large")
            photographer = str(photo.get("photographer", "")).strip()
            photographer_url = str(photo.get("photographer_url", "")).strip()
            yield from self._make_candidate(
                "pexels", url,
                credit_name=photographer,
                credit_url=photographer_url,
                meta_text=str(photo.get("alt", "")),
            )

    def _pixabay_candidates(self, term: str, topic: str = "") -> Iterator[_Candidate]:
        if not self.pixabay_key:
            return
        resp = self.session.get(
            self.PIXABAY_SEARCH,
            params={"key": self.pixabay_key, "q": term, "per_page": self.MAX_RESULTS_PER_PROVIDER,
                    "image_type": "photo", "orientation": "vertical", "safesearch": "true"},
            timeout=10,
        )
        if not resp.ok:
            return
        for hit in resp.json().get("hits", [])[: self.MAX_RESULTS_PER_PROVIDER]:
            url = hit.get("largeImageURL") or hit.get("webformatURL")
            author = str(hit.get("user", "")).strip()
            page_url = str(hit.get("pageURL", "")).strip()
            yield from self._make_candidate(
                "pixabay", url,
                credit_name=author,
                credit_url=page_url,
                meta_text=" ".join([str(hit.get("tags", "")), author]),
            )

    def _flickr_candidates(self, term: str, topic: str = "") -> Iterator[_Candidate]:
        api_key = os.getenv("FLICKR_API_KEY", "").strip()
        if not api_key:
            return
        resp = self.session.get(
            self.FLICKR_SEARCH,
            params={
                "method":       "flickr.photos.search",
                "api_key":      api_key,
                "text":         term,
                "license":      "4,5,9,10",   # CC-BY, CC-BY-SA, CC0, PDM
                "sort":         "relevance",
                "extras":       "url_b,tags,description,owner_name",
                "per_page":     self.MAX_RESULTS_PER_PROVIDER,
                "format":       "json",
                "nojsoncallback": 1,
            },
            timeout=10,
        )
        if not resp.ok:
            return
        photos = resp.json().get("photos", {}).get("photo", [])
        for photo in photos[: self.MAX_RESULTS_PER_PROVIDER]:
            url = photo.get("url_b")
            if not url:
                continue
            title = str(photo.get("title", ""))
            tags  = str(photo.get("tags", ""))
            desc  = str((photo.get("description") or {}).get("_content", ""))
            owner = str(photo.get("ownername", ""))
            meta  = f"{title} {tags} {desc}".strip()
            page_url = (
                f"https://www.flickr.com/photos/{photo.get('owner', '')}"
                f"/{photo.get('id', '')}"
            )
            yield from self._make_candidate(
                "flickr", url,
                credit_name=owner,
                credit_url=page_url,
                meta_text=meta,
            )

    def _openverse_candidates(self, term: str, topic: str = "") -> Iterator[_Candidate]:
        resp = self.session.get(
            self.OPENVERSE_SEARCH,
            params={"q": term, "page_size": self.MAX_RESULTS_PER_PROVIDER,
                    "mature": "false", "format": "json",
                    "aspect_ratio": "tall", "size": "large"},
            timeout=12,
        )
        if not resp.ok:
            return
        for result in resp.json().get("results", [])[: self.MAX_RESULTS_PER_PROVIDER]:
            url = result.get("url") or result.get("thumbnail")
            creator = str(result.get("creator", "")).strip()
            landing_url = str(result.get("foreign_landing_url", "")).strip()
            yield from self._make_candidate(
                "openverse", url,
                credit_name=creator,
                credit_url=landing_url,
                meta_text=" ".join([str(result.get("title", "")), creator]),
            )

    def _wiki_candidates(self, term: str, topic: str = "") -> Iterator[_Candidate]:
        resp = self.session.get(
            self.WIKI_OPENSEARCH,
            params={"action": "opensearch", "search": term, "limit": 8,
                    "namespace": 0, "format": "json"},
            timeout=10,
        )
        if not resp.ok:
            return
        data = resp.json()
        if not isinstance(data, list) or len(data) < 2:
            return
        for title in data[1]:
            url = self._wiki_summary_image_url(title)
            page_url = f"https://en.wikipedia.org/wiki/{str(title).replace(' ', '_')}"
            yield from self._make_candidate(
                "wikipedia", url,
                credit_name=title,
                credit_url=page_url,
                meta_text=title,
            )

    def _wiki_article_images_candidates(self, term: str, topic: str = "") -> Iterator[_Candidate]:
        """Fetch all inline photos from a Wikipedia article body.

        Unlike _wiki_candidates() which returns only the lead image, this extracts
        every photo embedded in the article — cockpit, cabin, historical shots, etc.
        All images are CC-licensed or public domain via Wikimedia Commons.
        """
        # Find best matching article via opensearch
        resp = self.session.get(
            self.WIKI_OPENSEARCH,
            params={"action": "opensearch", "search": term, "limit": 3,
                    "namespace": 0, "format": "json"},
            timeout=10,
        )
        if not resp.ok:
            return
        data = resp.json()
        if not (isinstance(data, list) and len(data) >= 2 and data[1]):
            return
        article_title = data[1][0]

        # Get all image filenames embedded in the article (up to 50)
        resp2 = self.session.get(
            self.WIKI_OPENSEARCH,
            params={"action": "query", "format": "json",
                    "titles": article_title, "prop": "images", "imlimit": 50},
            timeout=10,
        )
        if not resp2.ok:
            return
        pages = (resp2.json().get("query") or {}).get("pages", {})
        if not pages:
            return
        page = next(iter(pages.values()))

        # Filter to JPEG/PNG; skip SVGs, diagrams, logos, maps
        _SKIP = (
            ".svg", ".gif", ".ogg", ".wav", ".ogv", ".webm",
            "commons-logo", "wikimedia-logo", "-icon", "icon-",
            "flag_of", "coat_of", "symbol", "route_", "route-",
            "silhouette", "diagram", "scheme", "map", "blank", "signature",
            "screenshot", "infobox", "table", "template", "talk_page",
        )
        file_titles = [
            img["title"] for img in page.get("images", [])
            if img.get("title")
            and img["title"].lower().endswith((".jpg", ".jpeg", ".png"))
            and not any(p in img["title"].lower() for p in _SKIP)
        ]
        if not file_titles:
            return

        # Batch imageinfo requests to get URLs (up to 20 titles per API call)
        for i in range(0, len(file_titles), 20):
            batch = file_titles[i: i + 20]
            resp3 = self.session.get(
                self.WIKI_OPENSEARCH,
                params={
                    "action": "query", "format": "json",
                    "titles": "|".join(batch),
                    "prop": "imageinfo",
                    "iiprop": "url|mime|size",
                    "iiurlwidth": 1280,
                },
                timeout=12,
            )
            if not resp3.ok:
                continue
            pages3 = (resp3.json().get("query") or {}).get("pages", {}) or {}
            for pg in pages3.values():
                for info in (pg.get("imageinfo") or []):
                    url = info.get("thumburl") or info.get("url")
                    mime = info.get("mime", "")
                    if not url or "image" not in mime:
                        continue
                    if not url.lower().endswith((".jpg", ".jpeg", ".png")):
                        continue
                    file_name = str(pg.get("title", "")).replace("File:", "").strip()
                    # meta includes article title + filename so alias gate can
                    # match both the subject name and descriptive filename words
                    meta = f"{article_title} {file_name}"
                    yield from self._make_candidate(
                        "wikipedia", url,
                        credit_name=f"Wikipedia / {file_name}",
                        credit_url=(
                            "https://commons.wikimedia.org/wiki/File:"
                            + file_name.replace(" ", "_")
                        ),
                        meta_text=meta,
                    )

    def _wiki_summary_image_url(self, title: str) -> str | None:
        if not title:
            return None
        normalized = title.replace(" ", "_")
        try:
            resp = self.session.get(self.WIKI_SUMMARY.format(title=normalized), timeout=10)
        except requests.RequestException:
            return None
        if not resp.ok:
            return None
        data = resp.json()
        return ((data.get("originalimage") or {}).get("source")
                or (data.get("thumbnail") or {}).get("source"))

    def _nasa_candidates(self, term: str, topic: str = "") -> Iterator[_Candidate]:
        # NASA Images API - free, no key, excellent space coverage.
        resp = self.session.get(
            self.NASA_SEARCH,
            params={"q": term, "media_type": "image", "page_size": self.MAX_RESULTS_PER_PROVIDER},
            timeout=10,
        )
        if not resp.ok:
            return
        items = (resp.json().get("collection") or {}).get("items", [])
        for item in items[: self.MAX_RESULTS_PER_PROVIDER]:
            for link in item.get("links", []):
                url = link.get("href")
                if url and url.lower().endswith((".jpg", ".jpeg", ".png")):
                    yield from self._make_candidate(
                        "nasa", url,
                        credit_name="NASA",
                        credit_url="https://images.nasa.gov/",
                        meta_text=" ".join((item.get("data") or [{}])[0].get("title", "").split()),
                    )
                    break

    def _smithsonian_candidates(self, term: str, topic: str = "") -> Iterator[_Candidate]:
        # Smithsonian Open Access - free, optional API key for higher limits.
        api_key = os.getenv("SMITHSONIAN_API_KEY", "").strip() or "DEMO_KEY"
        resp = self.session.get(
            self.SMITHSONIAN_SEARCH,
            params={"q": term, "rows": self.MAX_RESULTS_PER_PROVIDER, "api_key": api_key},
            timeout=12,
        )
        if not resp.ok:
            return
        rows = ((resp.json().get("response") or {}).get("rows")) or []
        for row in rows[: self.MAX_RESULTS_PER_PROVIDER]:
            online_media = (((row.get("content") or {}).get("descriptiveNonRepeating")
                              or {}).get("online_media") or {}).get("media", [])
            for media in online_media:
                url = media.get("content")
                if url and url.lower().endswith((".jpg", ".jpeg", ".png")):
                    yield from self._make_candidate(
                        "smithsonian", url,
                        credit_name="Smithsonian",
                        credit_url="https://www.si.edu/openaccess",
                        meta_text=str(((row.get("content") or {}).get("descriptiveNonRepeating") or {}).get("title", {}).get("content", "")),
                    )
                    break

    def _inaturalist_candidates(self, term: str, topic: str = "") -> Iterator[_Candidate]:
        # iNaturalist - free, no key, perfect for biology / nature subjects.
        resp = self.session.get(
            self.INATURALIST_SEARCH,
            params={"q": term, "per_page": self.MAX_RESULTS_PER_PROVIDER, "is_active": "true"},
            timeout=10,
        )
        if not resp.ok:
            return
        for taxon in resp.json().get("results", [])[: self.MAX_RESULTS_PER_PROVIDER]:
            photo = taxon.get("default_photo") or {}
            url = photo.get("medium_url") or photo.get("original_url") or photo.get("large_url")
            if url:
                # Upgrade thumbnail size hint where possible.
                url = url.replace("/medium.", "/large.").replace("/square.", "/large.")
                attribution = str(photo.get("attribution", "")).strip()
                taxon_url = str(taxon.get("wikipedia_url", "")).strip() or "https://www.inaturalist.org/"
                yield from self._make_candidate(
                    "inaturalist", url,
                    credit_name=attribution,
                    credit_url=taxon_url,
                    meta_text=" ".join([str(taxon.get("name", "")), str(taxon.get("preferred_common_name", ""))]),
                )

    def _commons_candidates(self, term: str, topic: str = "") -> Iterator[_Candidate]:
        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrnamespace": 6,
            "gsrsearch": f"{term} filemime:image/jpeg",
            "gsrlimit": self.MAX_RESULTS_PER_PROVIDER,
            "prop": "imageinfo",
            "iiprop": "url|mime|size",
            "iiurlwidth": 1280,
        }
        resp = self.session.get(self.COMMONS_API, params=params, timeout=10)
        if not resp.ok:
            return
        pages = (resp.json().get("query") or {}).get("pages", {}) or {}
        for page in pages.values():
            for info in page.get("imageinfo", []):
                url = info.get("thumburl") or info.get("url")
                if url and url.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                    yield from self._make_candidate(
                        "wikimedia_commons", url,
                        credit_name=str(page.get("title", "")).replace("File:", "").strip(),
                        credit_url="https://commons.wikimedia.org/",
                        meta_text=str(page.get("title", "")),
                    )

    # ----- shared helpers -----

    def _make_candidate(self, provider: str, url: str | None,
                        credit_name: str = "", credit_url: str = "",
                        meta_text: str = "") -> Iterator[_Candidate]:
        if not url:
            return
        if self.ledger.is_used(url=url):
            return
        try:
            resp = self.session.get(url, timeout=15)
        except requests.RequestException:
            return
        if not resp.ok or len(resp.content) < self.MIN_IMAGE_BYTES:
            return
        try:
            img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        except Exception:
            return
        if min(img.size) < self.MIN_IMAGE_DIM:
            return
        yield _Candidate(
            provider, url, img, resp.content,
            credit_name=credit_name,
            credit_url=credit_url,
            meta_text=meta_text,
        )

    def _pexels_photo_allowed(self, photo: dict, topic: str) -> bool:
        """Reject Pexels photos whose alt text reveals the wrong domain.

        Pexels treats queries permissively, so we have to filter:
        - Space subjects often return statues, abstract renders, and lifestyle.
        - Biology subjects often return cooked-food photography.
        - History subjects often return Halloween costume shoots.
        """
        topic_low = topic.strip().lower()
        alt = str(photo.get("alt", "")).strip().lower()
        if not alt:
            # No metadata, can't verify subject - too risky for any topic.
            return False

        # Universal negative-term filter per topic.
        negs = self.NEGATIVE_TERMS_BY_TOPIC.get(topic_low, set())
        if any(n in alt for n in negs):
            return False

        # Space topic uses an ALLOWLIST: alt MUST explicitly contain a real
        # celestial-subject word. Generic positive matches like "sun" alone
        # are not enough (sun-flare on a camera passes them).
        if topic_low == "space":
            has_required = any(t in alt for t in self.SPACE_REQUIRED_TERMS)
            if not has_required:
                return False
        return True

    def _candidate_allowed(self, cand: _Candidate, topic: str, query_variant: str,
                           intent_text: str = "",
                           source_aliases: list[str] | None = None,
                           negative_terms: list[str] | None = None,
                           context_words: list[str] | None = None,
                           ) -> tuple[bool, str]:
        """Return (allowed, reason_string) for every candidate.

        reason_string is logged at DEBUG level so you can trace exactly why
        each image was accepted or rejected.
        """
        topic_low = topic.strip().lower()
        meta = (cand.meta_text or "").strip().lower()

        # --- 1. Negative terms: hard reject before anything else ----
        if negative_terms and meta:
            hit = next((t for t in negative_terms if t.lower() in meta), None)
            if hit:
                return False, f"negative_term={hit!r}"

        # --- 2. Source aliases + context_words ---
        if source_aliases:
            if meta:
                matched = [a for a in source_aliases if _alias_matches(a, meta)]
                if not matched:
                    return False, f"no_alias_match aliases={[a[:20] for a in source_aliases[:3]]}"

                # Single-word alias matches are ambiguous only in tag-based
                # providers (pixabay, pexels) where photographers tag broadly.
                # e.g. "concorde" tags photos of Place de la Concorde in Paris.
                # Archive providers (commons, wiki, smithsonian) title files by
                # their actual subject — "File:Concorde arp.jpg" is authoritative
                # without needing additional context words.
                _TAG_PROVIDERS = {"pixabay", "pexels"}
                # Single-word check: apply context gate only when every matched
                # alias is a single word AND we are on a tag-based provider.
                all_single_word = all(len(a.split()) == 1 for a in matched)
                if all_single_word and context_words and cand.provider in _TAG_PROVIDERS:
                    ctx_hit = next((c for c in context_words if c.lower() in meta), None)
                    if not ctx_hit:
                        return False, (
                            f"single_alias={matched[0]!r} no context_word "
                            f"({[c[:15] for c in context_words[:4]]}) in tags"
                        )
                    return True, f"alias={matched[0]!r} + context={ctx_hit!r} (tag provider)"

                return True, f"alias={matched[0]!r} ({'multi-word' if not all_single_word else 'archive-trusted'})"
            else:
                if cand.provider != "nasa":
                    return False, "no_meta and provider not nasa"
                return True, "nasa_trusted_no_meta"

        # --- 3. Fallback: intent_text subject terms (used when no aliases provided) ---
        subject_terms = self._intent_terms(intent_text) if intent_text else []

        intent_terms = self._intent_terms(query_variant)
        for t in subject_terms:
            if t not in intent_terms:
                intent_terms.append(t)

        expanded_terms: list[str] = []
        for term in intent_terms:
            expanded = self.TERM_EXPANSIONS.get(term)
            if expanded:
                for e in expanded:
                    if e not in expanded_terms:
                        expanded_terms.append(e)
            if term not in expanded_terms:
                expanded_terms.append(term)

        # Pexels/Pixabay always supply metadata; empty = no usable signal.
        _META_REQUIRED = {"pexels", "pixabay"}
        if not meta and cand.provider in _META_REQUIRED and subject_terms:
            return False

        if subject_terms and meta:
            hit = next((t for t in subject_terms if t in meta), None)
            if not hit:
                return False, f"no_subject_term_in_meta terms={subject_terms[:3]}"
        elif subject_terms and not meta:
            if cand.provider != "nasa":
                return False, "no_meta_subject_terms_require_nasa"

        if not subject_terms and meta and expanded_terms:
            hit = next((t for t in expanded_terms if t in meta), None)
            if not hit:
                return False, f"no_expanded_term_in_meta terms={expanded_terms[:3]}"

        ok = self._space_check(cand, topic_low, meta)
        return ok, ("pass_intent_terms" if ok else "space_check_failed")

    def _space_check(self, cand: "_Candidate", topic_low: str, meta: str) -> bool:
        """Space-topic allowlist gate. Returns True for all other topics."""
        if topic_low != "space":
            return True
        if cand.provider == "nasa":
            return True
        if not meta:
            return False
        has_required = any(t in meta for t in self.SPACE_REQUIRED_TERMS)
        has_negative = any(t in meta for t in self.SPACE_NEGATIVE_TERMS)
        if has_negative:
            return False
        return has_required

    def _intent_terms(self, text: str) -> list[str]:
        text = text.lower().replace("wi-fi", "wifi")
        words = re.findall(r"[a-zA-Z][a-zA-Z\-]{2,}", text)
        terms = [w for w in words if w not in self.INTENT_STOPWORDS]
        out: list[str] = []
        for t in sorted(set(terms), key=len, reverse=True):
            if t not in out:
                out.append(t)
        # Drop any term that is a strict substring of a longer term already in
        # the list. Prevents "sonic" matching Sonic the Hedgehog tags when the
        # query contains "supersonic" (which already covers the concept).
        out = [t for t in out if not any(t in other for other in out if other != t)]
        return out[:4]

    def _save(self, img: Image.Image, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        target_w, target_h = self.target_size
        sw, sh = img.size
        scale = max(target_w / sw, target_h / sh)
        new_size = (max(1, int(sw * scale)), max(1, int(sh * scale)))
        img = img.resize(new_size, Image.LANCZOS)
        left = (img.size[0] - target_w) // 2
        top = (img.size[1] - target_h) // 2
        img = img.crop((left, top, left + target_w, top + target_h))
        img.save(path, format="JPEG", quality=88)

    def _cache_valid(self, path: Path) -> bool:
        return path.exists() and path.stat().st_size > self.MIN_IMAGE_BYTES

    @staticmethod
    def _cache_key(*parts: str) -> str:
        key = "|".join(p.strip().lower() for p in parts if p)
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _slug(text: str) -> str:
        text = re.sub(r"[^A-Za-z0-9]+", "-", text.strip().lower())
        return text.strip("-")
