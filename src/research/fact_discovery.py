"""ORPHANED — DO NOT IMPORT. rare_fact_bank.py was deleted Phase G.1.

This module is dead code retained only because it sits outside the explicit
Phase G deletion list. Importing it raises `ImportError` on the
`rare_fact_bank` line below. Do not resuscitate `rare_fact_bank.py` to
"unbreak" this module — the autonomous flow's quality gate is now Phase D
fact verification (Haiku consistency + Wikipedia anchors), not the legacy
Reddit-discovery + rare-fact-bank path. See `CLAUDE.md §12`.
"""
from __future__ import annotations

import hashlib
import random
import re
from datetime import datetime, timezone
from typing import Iterable

import requests

from src.brain import brain, claim_hash
from src.core.models import FactCandidate, SourceEvidence
# BROKEN IMPORT: rare_fact_bank.py was deleted Phase G.1. Importing this
# module raises ImportError immediately. Do not recreate the deleted file.
from src.research.rare_fact_bank import RARE_FACT_BANK
from src.research.source_registry import get_source_pool


TRUSTED_PUBLISHERS = {
    "wikipedia.org": 0.72,
    "nasa.gov": 0.95,
    "who.int": 0.93,
    "britannica.com": 0.83,
    "nationalgeographic.com": 0.84,
}


class FactDiscoveryService:
    def __init__(self, max_candidates_per_topic: int = 20, existing_claims: set[str] | None = None) -> None:
        self.max_candidates_per_topic = max_candidates_per_topic
        self.existing_claims = existing_claims or set()
        # Brain enforces "never repost a fact" via the canonical claim hash
        # on top of any per-session dedupe the caller passes in.
        self._posted_hashes = brain.posted_hashes()

    def discover(self, topics: Iterable[str], count: int = 10) -> list[FactCandidate]:
        candidates: list[FactCandidate] = []
        topic_set = {t.lower().strip() for t in topics}

        for row in RARE_FACT_BANK:
            if (row["topic"] in topic_set
                    and row["claim"] not in self.existing_claims
                    and claim_hash(row["claim"]) not in self._posted_hashes):
                fact_id = hashlib.sha1(f"{row['topic']}:{row['claim']}".encode("utf-8")).hexdigest()[:12]
                candidates.append(
                    FactCandidate(
                        fact_id=fact_id,
                        topic=row["topic"],
                        claim=row["claim"],
                        rarity_score=0.95,
                        discovered_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                        image_hint=row.get("image_hint", ""),
                        source_candidates=[
                            SourceEvidence(
                                url=url,
                                publisher=url.replace("https://", "").split("/")[0].replace("www.", ""),
                                snippet=row["claim"][:170],
                                quality_score=TRUSTED_PUBLISHERS.get(
                                    url.replace("https://", "").split("/")[0].replace("www.", ""),
                                    0.82,
                                ),
                            )
                            for url in row["sources"]
                        ],
                    )
                )

        for topic in topics:
            discovered = self._discover_topic(topic, limit=self.max_candidates_per_topic)
            candidates.extend(discovered)
        deduped = self._dedupe_similar(candidates)
        filtered = [c for c in deduped if c.rarity_score >= 0.78 and self._is_mind_blowing(c.claim)]
        filtered.sort(key=lambda c: c.rarity_score, reverse=True)
        return filtered[:count]

    def _discover_topic(self, topic: str, limit: int = 10) -> list[FactCandidate]:
        seed_claims = self._topic_seed_claims(topic)
        items: list[FactCandidate] = []
        for claim in seed_claims[:limit]:
            if claim in self.existing_claims:
                continue
            if claim_hash(claim) in self._posted_hashes:
                continue
            fact_id = hashlib.sha1(f"{topic}:{claim}".encode("utf-8")).hexdigest()[:12]
            rarity = self._rarity_score(claim)
            items.append(
                FactCandidate(
                    fact_id=fact_id,
                    topic=topic,
                    claim=claim,
                    rarity_score=rarity,
                    discovered_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    image_hint="",
                    source_candidates=self._build_source_candidates(topic, claim),
                )
            )
        return items

    def _topic_seed_claims(self, topic: str) -> list[str]:
        page = topic.strip().replace(" ", "_")
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{page}"
        claims: list[str] = []
        try:
            resp = requests.get(url, timeout=10)
            if resp.ok:
                data = resp.json()
                extract = data.get("extract", "")
                if extract:
                    parts = [s.strip() for s in extract.split(".") if len(s.strip()) > 40]
                    parts = [p for p in parts if self._has_specificity(p)]
                    claims.extend(parts[:8])
        except requests.RequestException:
            pass

        if not claims:
            claims = [
                f"{topic.title()} includes overlooked discoveries with measurable global impact",
                f"Researchers in {topic.title()} documented unexpected behavior in natural systems",
                f"Historical records about {topic.title()} reveal events often absent from textbooks",
            ]
        return claims

    def _build_source_candidates(self, topic: str, claim: str) -> list[SourceEvidence]:
        pool = get_source_pool(topic)
        out: list[SourceEvidence] = []
        for source_url in pool[:3]:
            publisher = source_url.replace("https://", "").split("/")[0].replace("www.", "")
            quality = TRUSTED_PUBLISHERS.get(publisher, 0.8)
            out.append(
                SourceEvidence(
                    url=source_url,
                    publisher=publisher,
                    snippet=f"Candidate evidence for claim: {claim[:140]}",
                    quality_score=quality,
                )
            )
        return out

    @staticmethod
    def _rarity_score(claim: str) -> float:
        uncommon_markers = ("first", "only", "unexpected", "rare", "unusual", "hidden")
        marker_bonus = sum(0.05 for m in uncommon_markers if m in claim.lower())
        length_bonus = min(len(claim) / 500, 0.12)
        noise = random.uniform(0.45, 0.78)
        return min(noise + marker_bonus + length_bonus, 0.99)

    @staticmethod
    def _has_specificity(claim: str) -> bool:
        if re.search(r"\b\d{2,4}\b", claim):
            return True
        specific_words = ("first", "deepest", "oldest", "only", "million", "billion", "century")
        return any(w in claim.lower() for w in specific_words)

    @staticmethod
    def _is_mind_blowing(claim: str) -> bool:
        generic_patterns = (
            "includes overlooked discoveries",
            "unexpected behavior in natural systems",
            "often absent from textbooks",
        )
        if any(p in claim.lower() for p in generic_patterns):
            return False
        return FactDiscoveryService._has_specificity(claim)

    @staticmethod
    def _dedupe_similar(candidates: list[FactCandidate]) -> list[FactCandidate]:
        accepted: list[FactCandidate] = []
        for c in sorted(candidates, key=lambda x: x.rarity_score, reverse=True):
            if not any(FactDiscoveryService._too_similar(c.claim, a.claim) for a in accepted):
                accepted.append(c)
        return accepted

    @staticmethod
    def _too_similar(a: str, b: str) -> bool:
        a_tokens = set(re.findall(r"[a-zA-Z]{4,}", a.lower()))
        b_tokens = set(re.findall(r"[a-zA-Z]{4,}", b.lower()))
        if not a_tokens or not b_tokens:
            return False
        jaccard = len(a_tokens.intersection(b_tokens)) / len(a_tokens.union(b_tokens))
        return jaccard >= 0.62
