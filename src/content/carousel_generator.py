from __future__ import annotations

import hashlib
import re
from collections import OrderedDict
from typing import Sequence

from src.content.image_relevance import ImageRelevanceService
from src.content.quotes import QuoteBank
from src.core.models import CarouselPost, VerifiedFact


# Topic → display category. Anything not listed falls back to topic.upper().
TOPIC_CATEGORY = {
    "space": "SPACE",
    "astronomy": "SPACE",
    "earth": "EARTH",
    "geology": "EARTH",
    "ocean": "OCEAN",
    "biology": "NATURE",
    "history": "HISTORY",
    "technology": "TECH",
    "metaverse": "TECH",
    "ai": "AI",
    "science": "SCIENCE",
}

STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "at", "for", "and", "or", "but",
    "is", "are", "was", "were", "be", "been", "being", "it", "its", "this",
    "that", "those", "these", "such", "with", "from", "by", "as", "than",
    "then", "so", "if", "while", "which", "who", "whom", "whose", "where",
    "when", "what", "why", "how", "about", "into", "onto", "upon", "off",
    "out", "over", "under", "between", "across", "through", "very", "much",
    "many", "more", "most", "some", "any", "all", "each", "every", "no",
    "not", "only", "also", "even", "just", "still", "yet", "they", "their",
    "them", "his", "her", "he", "she", "we", "you", "your", "our", "us",
    "stop", "beating", "takes", "take", "taking", "make", "makes", "making",
    "have", "has", "had", "having", "does", "doing", "did", "do", "done",
    "would", "could", "should", "will", "shall", "may", "might", "must",
    "can", "cant", "wont", "say", "said", "says", "saying",
}

WRITTEN_NUMBERS = {
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen", "twenty", "thirty",
    "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred",
    "thousand", "million", "billion", "trillion",
}


class CarouselDraftGenerator:
    """Builds factjot carousels where each slide is its own self-contained fact.

    A post is a topic-grouped bundle: 5-6 distinct facts on the same theme,
    one fact per slide, each with its own background image. No CTA filler
    slides, no "stop scrolling" intros.

    Inline highlight markup the renderer understands:

        [i]…[/i]   italic, white                    (key entity / what the fact is about)
        [h]…[/h]   italic, accent orange (#E6352A)  (the killer detail / payoff)

    Highlight rules (auto-applied by `_mark`):
        1. Wrap the FIRST numeric / quantity / year token in [h]…[/h]. This is
           the "killer detail": a number, money figure, year, or "%".
        2. Wrap the central key noun phrase (proper noun preferred) in [i]…[/i].
        3. Never highlight stopwords. At most ONE [h] and ONE [i] per slide.
        4. If no number exists, the slide may carry only an [i] mark, or none.
    """

    # Slide character cap. The renderer will pick a font size between min and
    # max based on actual length, but we never let a single slide exceed this.
    MAX_SLIDE_CHARS = 320

    SLIDES_PER_POST = 6
    MIN_SLIDES_PER_POST = 3

    def __init__(self, max_slide_words: int = 60) -> None:
        self.max_slide_words = max_slide_words
        self.image_relevance = ImageRelevanceService()
        self.quote_bank = QuoteBank()

    # ----- entry point -----

    def generate(self, facts: Sequence[VerifiedFact], default_series: list[str]) -> list[CarouselPost]:
        # Group facts by topic so each post is one coherent set.
        grouped: dict[str, list[VerifiedFact]] = OrderedDict()
        for fact in facts:
            grouped.setdefault(fact.topic.lower().strip(), []).append(fact)

        posts: list[CarouselPost] = []
        for index, (topic, topic_facts) in enumerate(grouped.items()):
            if len(topic_facts) < self.MIN_SLIDES_PER_POST:
                # Hard floor: never ship a carousel with fewer than 3 slides.
                # Silently producing a 1-slide carousel was the cause of the
                # 18:05 UTC 2026-05-02 incident (Mac 128KB RAM single-slide post).
                # When a topic is exhausted, return nothing and let the caller
                # decide what to do (skip slot, fall back to another topic).
                continue
            chunk = topic_facts[: self.SLIDES_PER_POST]
            series = default_series[index % len(default_series)] if default_series else "factjot"
            seed_id = "+".join(f.fact_id for f in chunk)
            post_id = hashlib.sha1(f"{seed_id}:{series}".encode("utf-8")).hexdigest()[:14]
            category = TOPIC_CATEGORY.get(
                topic, re.sub(r"\W+", "", topic).upper() or "FACT",
            )

            slides: list[str] = []
            image_queries: list[str] = []
            sources: list[str] = []
            for fact in chunk:
                slide_text = self._tighten(fact.claim)
                slides.append(self._mark(slide_text))
                # Use the curator's image_hint if set, else auto-extract.
                if fact.image_hint:
                    image_queries.append(fact.image_hint)
                else:
                    image_queries.append(self._image_query(fact.claim, fact.topic))
                sources.extend(s.url for s in fact.sources)

            hook = self._strip_markup(slides[0]) if slides else ""
            caption = self._caption(chunk)
            hashtags = self._hashtags(topic, category)

            avg_confidence = (
                sum(f.confidence for f in chunk) / len(chunk) if chunk else 0.0
            )
            anchor_claim = chunk[0].claim if chunk else ""
            image_prompt = self.image_relevance.build_image_prompt(
                anchor_claim, topic,
                style_hint="moody documentary photography, dark cinematic lighting, real subject, no text",
            )
            image_relevance_score = self.image_relevance.relevance_score(anchor_claim, image_prompt)

            quote = self.quote_bank.pick_unused()
            closing_quote = quote.text if quote else ""
            closing_attribution = quote.attribution if quote else ""

            posts.append(
                CarouselPost(
                    post_id=post_id,
                    series=series,
                    hook=hook,
                    slides=slides,
                    caption=caption,
                    hashtags=hashtags,
                    sources=sources,
                    confidence=avg_confidence,
                    category=category,
                    image_queries=image_queries,
                    image_prompt=image_prompt,
                    image_relevance_score=image_relevance_score,
                    closing_quote=closing_quote,
                    closing_attribution=closing_attribution,
                )
            )
        return posts

    # ----- text trimming -----

    def _tighten(self, text: str) -> str:
        cleaned = re.sub(r"\s+", " ", text).strip()
        if len(cleaned) > self.MAX_SLIDE_CHARS:
            # Trim at a clean sentence boundary if possible.
            truncated = cleaned[: self.MAX_SLIDE_CHARS]
            last_period = max(truncated.rfind("."), truncated.rfind("!"), truncated.rfind("?"))
            if last_period > self.MAX_SLIDE_CHARS * 0.6:
                cleaned = truncated[: last_period + 1]
            else:
                cleaned = truncated.rstrip(",;: ").rstrip() + "..."
        words = cleaned.split()
        if len(words) > self.max_slide_words:
            cleaned = " ".join(words[: self.max_slide_words]).rstrip(",;: ") + "..."
        return cleaned

    # ----- highlight markup -----

    NUMBER_PATTERN = re.compile(
        r"""
        (
            \$?\d[\d,]*(?:\.\d+)?            # 1, 1,000, 4.5
            (?:                              # optional fractions / ordinals / ranges
                \s*[/\-]\s*\d+(?:st|nd|rd|th)?
                | (?:st|nd|rd|th)
            )?
            (?:                              # optional unit
                \s?(?:%|million|billion|trillion|thousand
                     |years?|days?|hours?|minutes?|seconds?|times?
                     |tonnes?|kilometres?|kilometers?|metres?|meters?
                     |miles?|feet|inches?|cm|mm|kg|g)
            )?
        )
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    WRITTEN_NUMBER_PATTERN = re.compile(
        r"\b("
        + "|".join(sorted(WRITTEN_NUMBERS, key=len, reverse=True))
        + r")\b",
        re.IGNORECASE,
    )

    def _mark(self, text: str) -> str:
        marked, h_span = self._mark_killer_detail(text)
        marked = self._mark_key_entity(marked, h_span)
        return marked

    def _mark_killer_detail(self, text: str) -> tuple[str, tuple[int, int] | None]:
        match = self.NUMBER_PATTERN.search(text)
        if match is None:
            match = self.WRITTEN_NUMBER_PATTERN.search(text)
        if not match:
            return text, None
        start, end = match.span(1)
        captured = text[start:end].rstrip()
        end = start + len(captured)
        wrapped = f"{text[:start]}[h]{captured}[/h]{text[end:]}"
        return wrapped, (start, end)

    def _mark_key_entity(self, text: str, h_span: tuple[int, int] | None) -> str:
        tokens = list(re.finditer(r"[A-Za-z][A-Za-z'\-]+", text))
        candidate = None
        for tok in tokens:
            word = tok.group(0)
            low = word.lower()
            if low in STOPWORDS or low in WRITTEN_NUMBERS:
                continue
            if "[h]" in text[max(0, tok.start() - 3): tok.end() + 4]:
                continue
            if word[0].isupper() and tok.start() != 0:
                candidate = tok
                break

        if candidate is None and tokens:
            first = tokens[0]
            first_word = first.group(0)
            first_low = first_word.lower()
            if (
                first_word[0].isupper()
                and first_low not in STOPWORDS
                and first_low not in WRITTEN_NUMBERS
                and len(first_word) >= 4
                and "[h]" not in text[: first.end() + 4]
            ):
                candidate = first

        if candidate is None:
            return text

        start, end = candidate.span()
        next_match = re.match(r"\s+([A-Z][A-Za-z'\-]+)", text[end:])
        if next_match:
            next_low = next_match.group(1).lower()
            if next_low not in STOPWORDS and next_low not in WRITTEN_NUMBERS:
                end += len(next_match.group(0))
        return f"{text[:start]}[i]{text[start:end]}[/i]{text[end:]}"

    @staticmethod
    def _strip_markup(text: str) -> str:
        return re.sub(r"\[/?[ihab]\]", "", text)

    # ----- image queries -----

    # Words that look like content words but make terrible image queries.
    WEAK_IMAGE_WORDS = {
        "single", "every", "anything", "nothing", "something", "someone",
        "produces", "producing", "produce", "produced", "containing", "contains",
        "appears", "appeared", "becomes", "became", "begins", "began",
        "creates", "created", "shown", "found", "finding",
        "almost", "later", "always", "whole", "entire",
        "different", "various", "several", "kind", "type",
        "world", "modern", "ancient", "recent", "current",
        "stop", "stopped", "stopping", "starting", "stops",
        "there", "more", "less", "most", "people", "things",
        "across", "through", "during", "before", "after",
        "great", "first", "shortest", "longest", "largest", "smallest",
    }
    STRONG_IMAGE_PHRASES = (
        "neutron star",
        "black hole",
        "milky way",
        "solar system",
        "venus",
        "saturn",
        "apollo",
    )

    def _image_query(self, claim: str, topic: str) -> str:
        """Return ONE strong subject keyword for the image search.

        Each fact has a clear subject (Sharks, Venus, Octopuses). Pulling
        that one keyword and letting the fetcher's variants broaden if
        needed lands on the canonical article. Mixing in verbs or filler
        words made the search match unrelated results.

        Selection order:
            1. First sentence-internal proper noun (e.g. "Sharks", "Venus").
            2. Sentence-start proper noun if it's clearly a name (≥4 chars,
               not a generic opener).
            3. Longest non-stopword content noun.
            4. Topic.
        """
        cleaned = self._strip_markup(claim)
        low_cleaned = cleaned.lower()

        # 0. Prefer strong domain phrases before single-word proper nouns.
        for phrase in self.STRONG_IMAGE_PHRASES:
            if phrase in low_cleaned:
                if topic.strip().lower() == "space" and phrase in {"venus", "saturn"}:
                    return f"{phrase} planet space"
                return phrase

        # 0b. Prefer title-cased multi-word entities for historical events
        # and named concepts (for example "Great Fire London").
        chunks = re.findall(r"\b(?:[A-Z][A-Za-z'\-]+(?:\s+|$)){2,5}", cleaned)
        for chunk in chunks:
            words = [w for w in re.findall(r"[A-Za-z][A-Za-z'\-]+", chunk)]
            kept_words = [
                w for w in words
                if w.lower() not in STOPWORDS
                and w.lower() not in WRITTEN_NUMBERS
                and w.lower() not in self.WEAK_IMAGE_WORDS
            ]
            if len(kept_words) >= 2:
                return " ".join(kept_words[:3])

        # 0c. Use the lead clause subject (first ~10 words) before we fall
        # back to single-token proper nouns.
        lead = cleaned.split(".")[0]
        lead_words = re.findall(r"[A-Za-z][A-Za-z'\-]+", lead)[:10]
        lead_kept = [
            w for w in lead_words
            if w.lower() not in STOPWORDS
            and w.lower() not in WRITTEN_NUMBERS
            and w.lower() not in self.WEAK_IMAGE_WORDS
        ]
        if len(lead_kept) >= 2:
            return " ".join(lead_kept[:3])

        # 1. Proper nouns NOT at sentence start (those are real names).
        for tok in re.finditer(r"(?<!^)(?<!\.\s)\b([A-Z][A-Za-z\-']{2,})\b", cleaned):
            word = tok.group(1)
            low = word.lower()
            if (low not in STOPWORDS and low not in WRITTEN_NUMBERS
                    and low not in self.WEAK_IMAGE_WORDS):
                return word

        # 2. Sentence-start proper noun, if it's distinctive enough.
        first = re.match(r"\s*([A-Z][A-Za-z\-']{3,})", cleaned)
        if first:
            word = first.group(1)
            low = word.lower()
            if (low not in STOPWORDS and low not in WRITTEN_NUMBERS
                    and low not in self.WEAK_IMAGE_WORDS):
                return word

        # 3. Longest content noun.
        content = [
            w for w in re.findall(r"[A-Za-z][A-Za-z\-']{3,}", cleaned)
            if w.lower() not in STOPWORDS
            and w.lower() not in WRITTEN_NUMBERS
            and w.lower() not in self.WEAK_IMAGE_WORDS
        ]
        if content:
            return max(content, key=len)

        # 4. Last resort.
        return topic or "factjot"

    # ----- caption + hashtags -----

    @staticmethod
    def _caption(facts: list[VerifiedFact]) -> str:
        # Lead with the first (most quirky-scored) fact as the hook sentence.
        # IG shows ~125 chars before "more" — those chars need to earn a tap,
        # not waste themselves on a generic CTA. The CTA follows after.
        hook = ""
        if facts:
            claim = re.sub(r"\[/?[ih]\]", "", facts[0].claim).strip()
            # Take the first sentence only — punchy, not the full paragraph.
            first_sentence = claim.split(". ")[0].strip().rstrip(".")
            if len(first_sentence) > 200:
                first_sentence = first_sentence[:200].rstrip()
            hook = first_sentence + "."
        cta = "Follow @factjot for more."
        if hook:
            return f"{hook}\n\n{cta}"
        return cta

    @staticmethod
    def _hashtags(topic: str, category: str) -> list[str]:
        normalized_topic = re.sub(r"\W+", "", topic.strip()).lower()
        normalized_cat = re.sub(r"\W+", "", category.strip()).lower()
        # 15-tag mix: brand → broad-reach → category → topic. Stays under the
        # 30-tag IG cap with room to add per-claim niche tags later.
        tags = [
            "#factjot",
            "#didyouknow",
            "#facts",
            "#dailyfact",
            "#interestingfacts",
            "#funfacts",
            "#mindblown",
            "#learnsomething",
            "#todayilearned",
            "#knowledge",
            "#curiosity",
        ]
        if normalized_cat:
            tags.append(f"#{normalized_cat}")
            tags.append(f"#{normalized_cat}facts")
        if normalized_topic and normalized_topic != normalized_cat:
            tags.append(f"#{normalized_topic}")
            tags.append(f"#{normalized_topic}facts")
        # Dedupe while preserving order.
        seen: set[str] = set()
        out: list[str] = []
        for t in tags:
            low = t.lower()
            if low in seen:
                continue
            seen.add(low)
            out.append(t)
        return out[:15]
