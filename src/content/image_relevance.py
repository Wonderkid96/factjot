from __future__ import annotations

import re


class ImageRelevanceService:
    def build_image_prompt(self, claim: str, topic: str, style_hint: str) -> str:
        key_terms = self._keywords(claim)[:6]
        terms = ", ".join(key_terms) if key_terms else topic
        return (
            f"Editorial modern carousel visual, {style_hint}, about {topic}. "
            f"Include concepts tied to: {terms}. No text overlays, no logos."
        )

    def relevance_score(self, claim: str, image_prompt: str) -> float:
        claim_terms = set(self._keywords(claim))
        prompt_terms = set(self._keywords(image_prompt))
        if not claim_terms:
            return 0.0
        overlap = len(claim_terms.intersection(prompt_terms))
        return min(overlap / max(len(claim_terms), 1) + 0.25, 1.0)

    @staticmethod
    def _keywords(text: str) -> list[str]:
        words = re.findall(r"[a-zA-Z]{4,}", text.lower())
        stop = {"that", "with", "from", "this", "were", "have", "about", "into", "your", "they"}
        return [w for w in words if w not in stop]
