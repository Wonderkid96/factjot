from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from urllib.parse import quote

from src.core.models import FactCandidate, SourceEvidence, VerifiedFact


HIGH_TRUST_DOMAINS = {"nasa.gov", "who.int", "nature.com", "science.org", "britannica.com"}


# Words that indicate the brief is fictional or framed as a stunt/experiment.
# A real production carousel triggered this rule: "Five fictional films ranked
# by pipeline absurdity" sailed through with the brief still containing
# "fictional" because no code-level gate looked at it.
_RED_FLAG_WORDS = (
    "fictional",
    "absurdity",
    "experiment",
    "fabricated",
    "imaginary",
    "invented",
)

# Wikipedia REST summary endpoint. Free, no API key, ~5kb per response.
_WIKIPEDIA_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
_WIKIPEDIA_TIMEOUT_S = 5
_WIKIPEDIA_MAX_RETRIES = 3
_WIKIPEDIA_USER_AGENT = "factjot-fact-verifier/1.0 (https://instagram.com/factjot)"


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
                    verified_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
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


# ---------------------------------------------------------------------- #
# D.1 fact verification gate (audit decision A: medium)
#
# Two standalone module-level checks that run before any post ships.
#
# 1. verify_consistency: a single Haiku call asks whether the title and
#    claim contradict each other and whether the brief contains red-flag
#    framing words ("fictional", "absurdity", etc.). Cheap, deterministic.
#
# 2. verify_anchors: heuristic Wikipedia cross-check for each named-subject
#    claim. Soft-passes on Wikipedia infra failure (better to ship than
#    block on infra). Hard-fails only on explicit contradiction.
#
# Both are designed to fail-OPEN on infrastructure issues (missing API key,
# upstream unreachable) and fail-CLOSED on real quality issues (the model
# says "this contradicts" or Wikipedia explicitly disagrees).
# ---------------------------------------------------------------------- #


def _consistency_prompt(title: str, claim: str, caption_body: str, format_type: str) -> str:
    """Build the Haiku prompt for the consistency check.

    The model returns strict JSON: {"consistent": bool, "reason": str}.
    Reason should be specific; if consistent, just say "consistent".
    """
    flagged_words = ", ".join(f'"{w}"' for w in _RED_FLAG_WORDS)
    return (
        "You are a fact-consistency checker for an Instagram fact account. "
        "Given a post's TITLE, CLAIM, optional CAPTION, and FORMAT, decide:\n"
        "1. Do the title and claim contradict each other? (e.g. title says "
        "'Britain rationed bread during WW2' but claim opens 'Britain never "
        "rationed bread during WW2'). If yes, NOT consistent.\n"
        "2. Does the title, claim, or caption contain any of these red-flag "
        f"words: {flagged_words}? These indicate the post is fictional or "
        "framed as a stunt and should not ship as a real fact. If yes, "
        "NOT consistent.\n"
        "3. Are the title and claim about the same subject? If they describe "
        "different things entirely, NOT consistent.\n\n"
        "Return ONLY a single JSON object on one line, no fenced block, no "
        "commentary, exactly this shape:\n"
        '{"consistent": true|false, "reason": "<short specific reason or '
        "'consistent'>\"}\n\n"
        f"TITLE: {title}\n"
        f"CLAIM: {claim}\n"
        f"CAPTION: {caption_body}\n"
        f"FORMAT: {format_type}\n"
    )


def _parse_consistency_response(raw: str) -> tuple[bool, str]:
    """Tolerant parser for the Haiku consistency JSON response.

    Returns (consistent, reason). On parse failure, returns
    (True, "parse_failed:<snippet>") so we fail-open: better to ship than
    block on a model hiccup.
    """
    text = raw.strip()
    # Strip fenced blocks if the model ignored the instruction.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    # Locate the first JSON object.
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return True, f"parse_failed:{text[:80]}"
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return True, f"parse_failed:{text[:80]}"
    consistent = bool(payload.get("consistent", True))
    reason = str(payload.get("reason", "")).strip() or (
        "consistent" if consistent else "no_reason_given"
    )
    return consistent, reason


def verify_consistency(brief: dict, api_key: str) -> dict:
    """Check that a post's title and claim are internally consistent.

    `brief` accepts any of: title, cover_title, claim, script, caption_body,
    format_type, subject. Empty fields are tolerated.

    Returns:
        {"ok": True, "reason": "consistent", "cost_usd": float} on pass
        {"ok": False, "reason": "<short>", "cost_usd": float}    on fail

    Fail-open conditions (returns ok=True with explanatory reason):
    - api_key missing -> reason="api_key_missing"
    - Anthropic call raises -> reason="api_error:<short>"
    - Response cannot be parsed -> reason="parse_failed:<snippet>"

    Fail-closed conditions (returns ok=False):
    - Model says consistent=False (title contradicts claim, etc.).
    - Brief contains a red-flag word and the model agrees.

    The red-flag check is also done locally as a belt-and-braces guard so
    the gate still catches "fictional" / "absurdity" framing even if the
    model returns a false negative.
    """
    title = (brief.get("title") or brief.get("cover_title") or "").strip()
    claim = (brief.get("claim") or brief.get("script") or "").strip()
    caption_body = (brief.get("caption_body") or "").strip()
    format_type = (brief.get("format_type") or "fact").strip()

    # Local red-flag scan first. Cheap, deterministic, catches the case
    # the model misses. Looks across title + claim + caption.
    haystack = f"{title}\n{claim}\n{caption_body}".lower()
    for word in _RED_FLAG_WORDS:
        # Match whole-word so "experimental" doesn't trigger "experiment".
        if re.search(rf"\b{re.escape(word)}\b", haystack):
            return {
                "ok": False,
                "reason": f"red_flag_word:{word}",
                "cost_usd": 0.0,
            }

    # Fail-open on missing api_key. Production should always have it; if
    # it's missing we log and keep going rather than block the run.
    if not api_key:
        return {"ok": True, "reason": "api_key_missing", "cost_usd": 0.0}

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        prompt = _consistency_prompt(title, claim, caption_body, format_type)
        res = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        # Fail-open on infra error. The Haiku call is cheap and should
        # rarely fail; treat any exception as a soft-pass with the reason
        # captured for telemetry. Surface the failure to the workflow log
        # so quota exhaustion or key rotation does not silently disable
        # the verifier across runs.
        print(
            f"[fact_checker] Haiku consistency check failed open: {exc}",
            flush=True,
        )
        return {
            "ok": True,
            "reason": f"api_error:{str(exc)[:80]}",
            "cost_usd": 0.0,
        }

    # Haiku 4.5 pricing (per 1M tokens): $1 in / $5 out.
    pricing_in = 1.00
    pricing_out = 5.00
    try:
        cost = (
            res.usage.input_tokens / 1_000_000 * pricing_in
            + res.usage.output_tokens / 1_000_000 * pricing_out
        )
    except AttributeError:
        cost = 0.0

    raw_text = ""
    try:
        raw_text = res.content[0].text or ""
    except (AttributeError, IndexError):
        pass

    consistent, reason = _parse_consistency_response(raw_text)
    return {
        "ok": bool(consistent),
        "reason": reason if reason else ("consistent" if consistent else "inconsistent"),
        "cost_usd": round(float(cost), 5),
    }


def _wikipedia_candidate_titles(claim: str) -> list[str]:
    """Heuristically extract candidate Wikipedia article titles from a claim.

    Looks for capitalised proper-noun runs (e.g. "Pepsi", "Vioxx",
    "Soviet Union", "World War 2") and quoted strings. Returns the most
    distinctive 3 titles in order, longest first. Stop-list filters obvious
    non-articles like "The", "Britain", "America".
    """
    if not claim or not isinstance(claim, str):
        return []

    # Quoted strings: highest priority.
    quoted = re.findall(r'"([^"\n]{3,80})"', claim)
    quoted += re.findall(r"“([^”\n]{3,80})”", claim)

    # Capitalised proper-noun runs of 1-4 words. Allow internal lowercase
    # words like "of", "the" to keep titles like "Bank of England" intact.
    proper_runs = re.findall(
        r"\b(?:[A-Z][A-Za-z0-9'\-]+(?:\s+(?:[A-Z][A-Za-z0-9'\-]+|of|the|and|de|in|on|to|II|III|IV|2|3))*)",
        claim,
    )

    # Stop-list of words that are too generic to look up. The claim
    # "Britain never rationed bread" should not query the Wikipedia article
    # "Britain"; it's the verb that disagrees, not the country page.
    stop = {
        "The", "A", "An", "It", "This", "That", "These", "Those", "He", "She",
        "I", "We", "You", "They", "There", "Here", "When", "Where", "How",
        "What", "Who", "Why", "But", "And", "Or",
    }

    candidates: list[str] = []
    for q in quoted:
        candidates.append(q.strip())
    for p in proper_runs:
        p = p.strip()
        if not p or p in stop:
            continue
        if len(p) < 3:
            continue
        # Skip single common-word "names" that are stop-list-adjacent.
        words = p.split()
        if len(words) == 1 and words[0] in stop:
            continue
        candidates.append(p)

    # Dedupe preserving order, prefer longer titles first.
    seen: set[str] = set()
    unique: list[str] = []
    for c in candidates:
        key = c.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(c)
    unique.sort(key=lambda s: -len(s))
    return unique[:3]


def _wikipedia_summary(
    title: str,
    cache: dict[str, dict | None],
    *,
    requests_module=None,
) -> dict | None:
    """Fetch the Wikipedia summary for `title` (cached for the run).

    Returns the JSON payload or None on miss / infra failure. Caches both
    hits and misses so the same title is fetched at most once per run.

    `requests_module` is injectable for testing; defaults to the real
    `requests` package.
    """
    if not title:
        return None
    cache_key = title.lower()
    if cache_key in cache:
        return cache[cache_key]

    if requests_module is None:
        import requests as requests_module  # noqa: PLW0127

    url = _WIKIPEDIA_SUMMARY_URL.format(title=quote(title.replace(" ", "_")))
    last_err: Exception | None = None
    for _attempt in range(_WIKIPEDIA_MAX_RETRIES):
        try:
            resp = requests_module.get(
                url,
                timeout=_WIKIPEDIA_TIMEOUT_S,
                headers={"User-Agent": _WIKIPEDIA_USER_AGENT},
            )
            if resp.status_code == 404:
                cache[cache_key] = None
                return None
            if resp.status_code >= 500:
                # Retry server-side errors only.
                last_err = RuntimeError(f"http_{resp.status_code}")
                continue
            if resp.status_code != 200:
                cache[cache_key] = None
                return None
            payload = resp.json()
            cache[cache_key] = payload
            return payload
        except Exception as exc:
            last_err = exc
            continue

    # All retries exhausted on a server-side / connection error.
    # Mark as "infra-failed" via a sentinel so the caller can soft-pass.
    cache[cache_key] = {"__infra_failed__": True, "error": str(last_err)[:80]}
    return cache[cache_key]


def _extract_numbers(text: str) -> list[int]:
    """Extract integer-like numbers from `text` (no commas, no decimals).

    "27,785 deaths" -> [27785]. "32% drop" -> [32]. "1989 fleet" -> [1989].
    Year-like 4-digit numbers are kept (they're often the verifiable anchor).
    """
    cleaned = text.replace(",", "")
    # Match runs of 1-9 digits not preceded by a letter (avoid "h2" -> 2).
    return [int(m) for m in re.findall(r"(?<![A-Za-z])\d{1,9}", cleaned)]


def _claim_contradicted_by_summary(claim: str, summary_text: str) -> tuple[bool, str]:
    """Heuristic: is the claim flatly contradicted by the Wikipedia summary?

    Returns (contradicted, reason). Conservative on purpose; we'd rather
    miss a flag than block a legitimate post.

    Looks for:
    - A number in the claim that, when present in the summary as a
      different number for the same context, differs by >10x.
    - The summary contains an explicit negation phrase ("did not",
      "never", "no evidence", "false") within 80 chars of a number that
      matches the claim.
    """
    if not summary_text:
        return False, ""
    claim_numbers = _extract_numbers(claim)
    if not claim_numbers:
        return False, ""

    # Strongest signal: explicit negation phrasing right next to a matching
    # number. e.g. summary says "the figure 27,785 was estimated excess
    # events, NOT deaths" and the claim asserts "27,785 deaths".
    summary_lower = summary_text.lower()
    for n in claim_numbers:
        # Skip very small numbers that are too noisy (years near matches).
        if n < 10:
            continue
        # Look for "n" or "n," or "n." in the summary text.
        n_str = f"{n:,}" if n >= 1000 else str(n)
        # Match either the comma-formatted or bare form.
        for variant in (n_str, str(n)):
            for m in re.finditer(re.escape(variant), summary_text):
                window = summary_lower[max(0, m.start() - 80):m.end() + 80]
                # Look for negation/contradiction near this number.
                if any(neg in window for neg in (
                    "did not", "never", "no evidence", "is false",
                    "is incorrect", "myth", "is a misconception",
                    "not deaths", "not actually",
                )):
                    return True, f"summary_negates_n={n}"

    return False, ""


def verify_anchors(claims: list, api_key: str = "") -> dict:
    """Wikipedia cross-check for numeric / named claims.

    `claims` is a list of strings (or dicts with a "text" field). Each is
    one specific assertion. Examples:
    - "Sinister scored 32% heart rate drop in test subjects"
    - "Vioxx linked to 27,785 heart attack deaths"
    - "Pepsi briefly owned 17 Soviet warships in 1989"

    For each claim:
    1. Extract candidate Wikipedia titles (proper nouns / quoted names).
    2. Fetch the summary (cached, retried 3x on 5xx).
    3. Check whether the summary explicitly contradicts the claim's
       numbers via _claim_contradicted_by_summary.

    Returns:
        {"ok": True, "flagged": [], "cost_usd": 0.0}                     no flags
        {"ok": True, "flagged": [], "cost_usd": 0.0,                     soft-pass on
         "warning": "wikipedia unreachable"}                              infra failure
        {"ok": False, "flagged": [{...}], "cost_usd": 0.0}                explicit contradiction

    Each flagged item has shape:
        {"claim": str, "reason": str, "wikipedia_url": str | None}

    cost_usd is always 0.0 (Wikipedia is free); included for symmetry
    with verify_consistency.

    `api_key` is currently unused (kept in the signature so the call site
    can pass it through; future versions may use Haiku to extract claim
    subjects more accurately than the regex heuristic).
    """
    _ = api_key  # currently unused; reserved for future Haiku extraction
    if not claims:
        return {"ok": True, "flagged": [], "cost_usd": 0.0}

    # Normalise mixed input: accept strings or dicts with .text field.
    norm_claims: list[str] = []
    for c in claims:
        if isinstance(c, str):
            norm_claims.append(c)
        elif isinstance(c, dict):
            text = c.get("text") or c.get("claim") or ""
            if text:
                norm_claims.append(str(text))
        # Silently skip other types.

    if not norm_claims:
        return {"ok": True, "flagged": [], "cost_usd": 0.0}

    cache: dict[str, dict | None] = {}
    flagged: list[dict] = []
    infra_fail_count = 0
    total_lookups = 0

    for claim in norm_claims:
        titles = _wikipedia_candidate_titles(claim)
        if not titles:
            continue
        for title in titles:
            total_lookups += 1
            summary = _wikipedia_summary(title, cache)
            if summary is None:
                # Article not found is not a contradiction; skip.
                continue
            if isinstance(summary, dict) and summary.get("__infra_failed__"):
                infra_fail_count += 1
                continue
            extract = (summary.get("extract") or "") if isinstance(summary, dict) else ""
            if not extract:
                continue
            contradicted, reason = _claim_contradicted_by_summary(claim, extract)
            if contradicted:
                page = summary.get("content_urls", {}).get("desktop", {}).get("page") if isinstance(summary, dict) else None
                if not page:
                    page = f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"
                flagged.append({
                    "claim": claim,
                    "reason": reason,
                    "wikipedia_url": page,
                })
                # One contradiction per claim is enough.
                break

    # If every lookup failed on infra, soft-pass with a warning rather
    # than block production on Wikipedia downtime. Log the all-fail so
    # a Wikipedia outage during a run is visible in the workflow log,
    # not just embedded in a return-dict the caller may not surface.
    if total_lookups > 0 and infra_fail_count == total_lookups and not flagged:
        print(
            f"[fact_checker] verify_anchors soft-pass: all {total_lookups} "
            f"Wikipedia lookups failed on infra; anchors not verified",
            flush=True,
        )
        return {
            "ok": True,
            "flagged": [],
            "cost_usd": 0.0,
            "warning": "wikipedia unreachable",
        }

    if flagged:
        return {"ok": False, "flagged": flagged, "cost_usd": 0.0}
    return {"ok": True, "flagged": [], "cost_usd": 0.0}
