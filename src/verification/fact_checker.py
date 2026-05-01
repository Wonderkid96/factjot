from __future__ import annotations

from datetime import datetime
import re

from src.core.models import FactCandidate, SourceEvidence, VerifiedFact


HIGH_TRUST_DOMAINS = {"nasa.gov", "who.int", "nature.com", "science.org", "britannica.com"}


class FactVerificationLayer:
    def __init__(self, min_sources: int = 2, min_confidence: float = 0.65) -> None:
        self.min_sources = min_sources
        self.min_confidence = min_confidence

    def verify(self, candidates: list[FactCandidate]) -> list[VerifiedFact]:
        verified_facts: list[VerifiedFact] = []
        for candidate in candidates:
            contradiction_flags = self._scan_contradictions(candidate.claim)
            confidence = self._confidence(candidate.source_candidates, contradiction_flags)
            is_verified = (
                len(candidate.source_candidates) >= self.min_sources
                and confidence >= self.min_confidence
                and not contradiction_flags
                and self._has_concrete_anchor(candidate.claim)
            )
            verified_facts.append(
                VerifiedFact(
                    fact_id=candidate.fact_id,
                    topic=candidate.topic,
                    claim=candidate.claim,
                    verified=is_verified,
                    confidence=confidence,
                    contradiction_flags=contradiction_flags,
                    sources=candidate.source_candidates,
                    verified_at=datetime.utcnow().isoformat() + "Z",
                    image_hint=candidate.image_hint,
                )
            )
        return [f for f in verified_facts if f.verified]

    def _confidence(self, sources: list[SourceEvidence], flags: list[str]) -> float:
        if not sources:
            return 0.0
        mean_quality = sum(s.quality_score for s in sources) / len(sources)
        high_trust_bonus = 0.06 if any(s.publisher in HIGH_TRUST_DOMAINS for s in sources) else 0.0
        penalty = min(len(flags) * 0.15, 0.45)
        return max(0.0, min(mean_quality + high_trust_bonus - penalty, 0.99))

    @staticmethod
    def _scan_contradictions(claim: str) -> list[str]:
        lowered = claim.lower()
        flags: list[str] = []
        for marker in ("always", "never", "guaranteed", "proven cure"):
            if marker in lowered:
                flags.append(marker)
        return flags

    @staticmethod
    def _has_concrete_anchor(claim: str) -> bool:
        # Reduce fluffy facts by requiring numbers or named entities heuristics.
        if re.search(r"\b\d{2,4}\b", claim):
            return True
        anchor_terms = ("nasa", "antarctica", "venus", "harvard", "london", "mariana")
        return any(t in claim.lower() for t in anchor_terms)
