from __future__ import annotations

import hashlib
import random
import re
from dataclasses import dataclass


_NUMBER_WORDS: dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

_WEAK_ENDINGS = frozenset(
    {
        "and",
        "or",
        "but",
        "the",
        "a",
        "an",
        "in",
        "of",
        "to",
        "at",
        "by",
        "for",
        "with",
        "as",
        "that",
        "this",
        "its",
        "their",
        "his",
        "her",
        "it",
        "was",
        "is",
        "are",
        "be",
        "been",
        "being",
        "have",
        "had",
        "has",
        "do",
        "did",
        "does",
        "will",
        "would",
        "could",
        "should",
        "then",
        "than",
        "so",
    }
)

_CURIOSITY_WORDS = frozenset(
    {
        "accidentally",
        "accident",
        "almost",
        "nearly",
        "secret",
        "shocking",
        "surprising",
        "unexpected",
        "unexpectedly",
        "hidden",
        "almost",
        "danger",
        "dangerous",
        "wiped",
        "detonated",
        "exploded",
        "dropped",
    }
)

_YEAR_RE = re.compile(r"\b(?:18|19|20)\d{2}s?\b")
_NUMBER_TOKEN_RE = re.compile(r"\b\d+(?:st|nd|rd|th)?\b")
_PROPER_RE = re.compile(r"\b([A-Z][a-z]{2,}|US|UK)\b")
_TOKEN_RE = re.compile(r"[A-Za-z0-9']+")


@dataclass(frozen=True)
class HookCandidate:
    text: str
    score: float


def _strip_markup(text: str) -> str:
    # Reel claims can include bracket emphasis tokens in other contexts.
    return re.sub(r"\[/?[ih]\]", "", text).strip()


def _normalise_spacing(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text)


def _upper_numbers(text: str) -> str:
    """Uppercase number words/digits for punchiness."""
    words = text.split()
    out: list[str] = []
    for w in words:
        wl = w.lower().strip(",.;:!?")
        if wl in _NUMBER_WORDS:
            out.append(w.upper())
        elif _NUMBER_TOKEN_RE.fullmatch(wl):
            out.append(wl.upper())
        else:
            out.append(w)
    return " ".join(out)


def _trim_weak_endings(words: list[str]) -> list[str]:
    while words:
        last = words[-1].lower().strip(",.;:!?")
        if len(words) <= 3:
            return words
        if last in _WEAK_ENDINGS:
            words = words[:-1]
            continue
        return words
    return words


def generate_hook_candidates(
    claim: str,
    topic: str,
    *,
    seed: int,
    max_candidates: int = 10,
    max_words: int = 7,
) -> list[str]:
    """Generate short hook-title candidates from the raw claim.

    This is deliberately "span-based" (extracts phrases from the claim)
    instead of free-form rewriting. That keeps the risk of accidental
    misinformation low while still improving scroll-stopping phrasing.
    """
    _ = topic  # topic is used in scoring; kept for future specialisation.
    claim = _strip_markup(claim)

    # Prefer first sentence for the hook card.
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", claim) if s.strip()]
    base = sentences[0] if sentences else claim
    base = base.strip().rstrip(".")

    toks = _tokens(base)
    if len(toks) < 3:
        return [_upper_numbers(base)]

    anchor_idxs: list[int] = []
    joined_lower = " ".join(toks).lower()

    # Anchor around numbers, years, then proper nouns.
    for i, w in enumerate(toks):
        wl = w.lower().strip(",.;:!?")
        if _YEAR_RE.fullmatch(wl):
            anchor_idxs.append(i)
        elif _NUMBER_TOKEN_RE.fullmatch(wl) or wl in _NUMBER_WORDS:
            anchor_idxs.append(i)
        elif _PROPER_RE.fullmatch(w):
            anchor_idxs.append(i)

    # Fallback: anchor at start and middle.
    if not anchor_idxs:
        anchor_idxs = [0, min(1, len(toks) - 1), len(toks) // 2]

    # Deterministic span exploration.
    rng = random.Random(seed)
    candidate_spans: set[str] = set()

    span_lengths = [max_words, max_words - 1, max_words - 2]
    rng.shuffle(span_lengths)

    for anchor in anchor_idxs[:6]:
        for L in span_lengths:
            half = L // 2
            start = max(0, anchor - half)
            end = min(len(toks), start + L)
            start = max(0, end - L)  # keep length stable at boundaries
            span_words = toks[start:end]
            span_words = _trim_weak_endings(span_words)
            if len(span_words) < 3 or len(span_words) > max_words:
                continue
            span = " ".join(span_words).strip()
            if not span:
                continue
            candidate_spans.add(span)

    if not candidate_spans:
        # Last resort: first <=max_words words
        first = toks[:max_words]
        first = _trim_weak_endings(first)
        candidate_spans.add(" ".join(first))

    candidates = sorted(candidate_spans)
    # Add some deterministic variety by choosing a subset.
    if len(candidates) > max_candidates:
        # Stable selection: shuffle with seed then take.
        rng.shuffle(candidates)
        candidates = candidates[:max_candidates]

    return [_upper_numbers(c) for c in candidates]


def _score_candidate(text: str, *, claim: str) -> float:
    """Heuristic score in [0, 1] for scroll-stopping quality."""
    words = text.split()
    n_words = len(words)
    wl = text.lower()
    claim_lower = claim.lower()

    score = 0.0

    # Length: prefer 4-6 words for a title card.
    if 4 <= n_words <= 6:
        score += 0.35
    elif 3 <= n_words <= 7:
        score += 0.20

    # Curiosity: reward explicit curiosity words present in the text.
    if any(w in wl for w in _CURIOSITY_WORDS):
        score += 0.25

    # Numbers and years: strong anchors for attention.
    has_digit = bool(_NUMBER_TOKEN_RE.search(text))
    has_number_word = any(nw in wl for nw in _NUMBER_WORDS)
    if has_digit or has_number_word:
        score += 0.35

    if _YEAR_RE.search(text):
        score += 0.20

    # Proper nouns: mostly a weak proxy for specificity, capped.
    proper = _PROPER_RE.findall(text)
    score += min(0.18, 0.06 * len(proper))

    # Claim consistency: do not reward phrases that use words absent from claim.
    claim_toks = set(_tokens(claim_lower))
    span_toks = set(_tokens(wl))
    overlap = len(span_toks.intersection(claim_toks))
    if claim_toks:
        score += min(0.20, 0.20 * overlap / max(len(span_toks), 1))

    # Penalise weak trailing word.
    if words:
        last = words[-1].lower().strip(",.;:!?")
        if last in _WEAK_ENDINGS:
            score -= 0.20

    # Clamp.
    return max(0.0, min(1.0, score))


def optimise_hook(
    claim: str,
    topic: str,
    *,
    seed: int,
    max_candidates: int = 10,
    top_n: int = 3,
) -> tuple[str, list[tuple[str, float]]]:
    """Return (winner_text, top_n_candidates_with_scores)."""
    # Topic is included for deterministic candidate generation in future.
    _ = topic
    candidates = generate_hook_candidates(
        claim,
        topic,
        seed=seed,
        max_candidates=max_candidates,
        max_words=7,
    )

    scored: list[HookCandidate] = []
    for c in candidates:
        scored.append(HookCandidate(text=c, score=_score_candidate(c, claim=claim)))

    # Deterministic ordering: score desc, then text asc.
    scored.sort(key=lambda x: (-x.score, x.text))
    winner = scored[0].text
    top = scored[: min(top_n, len(scored))]

    # Tests expect exactly top-3.
    # Pad (with best duplicates) if generator produced fewer.
    if len(top) < top_n and top:
        while len(top) < top_n:
            top.append(top[-1])

    return winner, [(c.text, c.score) for c in top]


def seed_from_claim_and_topic(claim: str, topic: str) -> int:
    """Stable seed helper for deterministic hook selection."""
    h = hashlib.sha1(f"{topic}:{claim}".encode("utf-8", errors="ignore")).hexdigest()
    return int(h[:8], 16)

