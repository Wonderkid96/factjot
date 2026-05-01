from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class SourceEvidence:
    url: str
    publisher: str
    snippet: str
    quality_score: float


@dataclass
class FactCandidate:
    fact_id: str
    topic: str
    claim: str
    rarity_score: float
    discovered_at: str
    source_candidates: list[SourceEvidence] = field(default_factory=list)
    image_hint: str = ""


@dataclass
class VerifiedFact:
    fact_id: str
    topic: str
    claim: str
    verified: bool
    confidence: float
    contradiction_flags: list[str]
    sources: list[SourceEvidence]
    verified_at: str
    image_hint: str = ""


@dataclass
class CarouselPost:
    post_id: str
    series: str
    hook: str
    slides: list[str]
    caption: str
    hashtags: list[str]
    sources: list[str]
    confidence: float
    category: str = "FACT"
    image_queries: list[str] = field(default_factory=list)
    image_credits: list[dict[str, str]] = field(default_factory=list)
    image_prompt: str = ""
    image_relevance_score: float = 0.0
    image_paths: list[str] = field(default_factory=list)
    render_paths: list[str] = field(default_factory=list)
    status: str = "draft"
    publish_at: str | None = None
    closing_quote: str = ""
    closing_attribution: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_dict(self) -> dict[str, Any]:
        return {
            "post_id": self.post_id,
            "series": self.series,
            "hook": self.hook,
            "slides": self.slides,
            "caption": self.caption,
            "hashtags": self.hashtags,
            "sources": self.sources,
            "confidence": self.confidence,
            "category": self.category,
            "image_queries": self.image_queries,
            "image_credits": self.image_credits,
            "image_prompt": self.image_prompt,
            "image_relevance_score": self.image_relevance_score,
            "image_paths": self.image_paths,
            "render_paths": self.render_paths,
            "status": self.status,
            "publish_at": self.publish_at,
            "closing_quote": self.closing_quote,
            "closing_attribution": self.closing_attribution,
            "created_at": self.created_at,
        }
