"""Tests for src.verification.fact_checker.verify_consistency / verify_anchors.

D.1 fact verification gate (audit Phase D, decision A: medium). Two checks
run before any post ships:

1. verify_consistency: a single Haiku call decides whether the title and
   claim contradict, or whether the brief contains red-flag framing words
   ("fictional", "absurdity", "experiment", etc.).

2. verify_anchors: a heuristic Wikipedia REST cross-check on each named-
   subject claim. Soft-passes on Wikipedia infra failure.

Both fail OPEN on infrastructure issues (missing api_key, Wikipedia 5xx)
and fail CLOSED on real quality issues (model says contradicts, summary
explicitly negates a number).
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from src.verification.fact_checker import (
    verify_anchors,
    verify_consistency,
)


def _mock_haiku_response(payload: dict, *, in_tokens: int = 80, out_tokens: int = 30):
    """Build a fake Anthropic SDK messages.create response carrying JSON.

    The consistency parser tolerates bare or fenced JSON; tests use bare
    one-line shape to mirror the deterministic temperature=0 behaviour.
    """
    res = MagicMock()
    res.content = [MagicMock()]
    res.content[0].text = json.dumps(payload)
    res.usage.input_tokens = in_tokens
    res.usage.output_tokens = out_tokens
    return res


# ---------------------------------------------------------------------- #
# verify_consistency
# ---------------------------------------------------------------------- #


def test_consistency_passes_on_clean_brief(monkeypatch):
    """Title and claim agree, no red-flag words. Haiku returns consistent."""
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_haiku_response({
        "consistent": True,
        "reason": "consistent",
    })
    monkeypatch.setattr(
        "anthropic.Anthropic",
        lambda api_key: fake_client,
    )

    result = verify_consistency(
        {
            "title": "Pepsi briefly owned a fleet of Soviet warships",
            "claim": (
                "In 1989, Pepsi accepted 17 Soviet submarines and a "
                "destroyer as payment for cola, briefly making it the "
                "owner of one of the world's largest naval fleets."
            ),
            "format_type": "fact",
        },
        api_key="dummy",
    )

    assert result["ok"] is True
    assert result["reason"] == "consistent"
    assert result["cost_usd"] >= 0.0


def test_consistency_rejects_title_contradicting_claim(monkeypatch):
    """Real production failure: title says one thing, claim says the opposite.

    Reel titled `Britain Rationed Bread After The War` whose claim opens
    `Britain never rationed bread during World War 2`. The consistency
    check rejects.
    """
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_haiku_response({
        "consistent": False,
        "reason": (
            "title says Britain rationed bread; claim says "
            "Britain never rationed bread"
        ),
    })
    monkeypatch.setattr(
        "anthropic.Anthropic",
        lambda api_key: fake_client,
    )

    result = verify_consistency(
        {
            "title": "Britain Rationed Bread After The War",
            "claim": (
                "Britain never rationed bread during World War 2; "
                "rationing began in 1946 once the war was already over."
            ),
        },
        api_key="dummy",
    )

    assert result["ok"] is False
    assert "never" in result["reason"].lower() or "contradict" in result["reason"].lower() or "title" in result["reason"].lower()


def test_consistency_rejects_brief_with_fictional_word(monkeypatch):
    """Real production failure: 'Five fictional films ranked by pipeline absurdity'.

    The local red-flag scan catches this BEFORE the Haiku call, so the
    mock client should never be hit. We assert that the function returns
    ok=False and the reason identifies the offending word.
    """
    fake_client = MagicMock()
    monkeypatch.setattr(
        "anthropic.Anthropic",
        lambda api_key: fake_client,
    )

    result = verify_consistency(
        {
            "title": "Five fictional films ranked by absurdity",
            "claim": (
                "A list of fictional films assembled to test the "
                "pipeline rather than to inform readers."
            ),
        },
        api_key="dummy",
    )

    assert result["ok"] is False
    assert "fictional" in result["reason"].lower()
    # Local red-flag scan must short-circuit the Haiku call.
    assert fake_client.messages.create.call_count == 0


def test_consistency_rejects_brief_with_absurdity_word(monkeypatch):
    """Local red-flag scan catches 'absurdity' before any model call."""
    fake_client = MagicMock()
    monkeypatch.setattr(
        "anthropic.Anthropic",
        lambda api_key: fake_client,
    )

    result = verify_consistency(
        {
            "title": "A test list",
            "claim": "An exploration of pipeline absurdity in production.",
            "format_type": "list",
        },
        api_key="dummy",
    )

    assert result["ok"] is False
    assert "absurdity" in result["reason"].lower()


def test_consistency_fail_open_on_missing_api_key(monkeypatch):
    """Fail-OPEN on infra: missing api_key returns ok=True with explanatory reason.

    The red-flag scan still runs first, so we use a clean brief.
    """
    result = verify_consistency(
        {
            "title": "A clean title",
            "claim": "A clean claim that says nothing controversial.",
        },
        api_key="",
    )

    assert result["ok"] is True
    assert result["reason"] == "api_key_missing"
    assert result["cost_usd"] == 0.0


def test_consistency_fail_open_on_anthropic_exception(monkeypatch):
    """Fail-OPEN when the Anthropic call itself raises."""
    def raising_client(api_key):
        client = MagicMock()
        client.messages.create.side_effect = RuntimeError("network down")
        return client

    monkeypatch.setattr("anthropic.Anthropic", raising_client)

    result = verify_consistency(
        {
            "title": "A clean title",
            "claim": "A clean claim with no red flags.",
        },
        api_key="dummy",
    )

    assert result["ok"] is True
    assert result["reason"].startswith("api_error:")
    assert result["cost_usd"] == 0.0


def test_consistency_fail_open_on_unparseable_response(monkeypatch):
    """Fail-OPEN when the model returns text that cannot be parsed as JSON."""
    fake_client = MagicMock()
    res = MagicMock()
    res.content = [MagicMock()]
    res.content[0].text = "I am not JSON, sorry."
    res.usage.input_tokens = 80
    res.usage.output_tokens = 10
    fake_client.messages.create.return_value = res
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    result = verify_consistency(
        {
            "title": "A clean title",
            "claim": "A clean claim.",
        },
        api_key="dummy",
    )

    assert result["ok"] is True
    assert result["reason"].startswith("parse_failed:")


# ---------------------------------------------------------------------- #
# verify_anchors
# ---------------------------------------------------------------------- #


class _FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


def test_anchors_passes_when_summary_does_not_contradict(monkeypatch):
    """Wikipedia returns a summary that doesn't contradict; verify_anchors returns ok=True."""
    def fake_get(url, timeout, headers):
        # Return a generic, non-contradictory summary for every call.
        return _FakeResponse(200, {
            "extract": (
                "Vioxx (rofecoxib) was a COX-2 selective nonsteroidal "
                "anti-inflammatory drug withdrawn in 2004 due to "
                "cardiovascular safety concerns."
            ),
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Rofecoxib"}},
        })

    monkeypatch.setattr("requests.get", fake_get)

    result = verify_anchors([
        "Vioxx was a controversial drug pulled in 2004 over heart risks."
    ])

    assert result["ok"] is True
    assert result["flagged"] == []
    assert result["cost_usd"] == 0.0


def test_anchors_flags_when_summary_contradicts_number(monkeypatch):
    """Real production failure mode: the summary contains the same number
    but with explicit negation phrasing nearby ('not deaths').
    """
    def fake_get(url, timeout, headers):
        return _FakeResponse(200, {
            "extract": (
                "A controversial study estimated 27,785 excess events, "
                "not deaths, were associated with the drug. The figure "
                "represents heart attacks and sudden cardiac deaths "
                "combined."
            ),
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Rofecoxib"}},
        })

    monkeypatch.setattr("requests.get", fake_get)

    result = verify_anchors([
        "Vioxx was linked to 27,785 heart attack deaths in the early 2000s."
    ])

    assert result["ok"] is False
    assert len(result["flagged"]) == 1
    flagged = result["flagged"][0]
    assert "27,785" in flagged["claim"] or "27785" in flagged["claim"]
    assert "n=27785" in flagged["reason"] or "summary_negates" in flagged["reason"]
    assert flagged["wikipedia_url"] is not None


def test_anchors_soft_passes_on_wikipedia_503(monkeypatch):
    """Fail-OPEN: every Wikipedia lookup returns 503; verify_anchors returns
    ok=True with a warning rather than blocking the post.
    """
    call_count = {"n": 0}

    def fake_get(url, timeout, headers):
        call_count["n"] += 1
        return _FakeResponse(503)

    monkeypatch.setattr("requests.get", fake_get)

    result = verify_anchors([
        "Pepsi briefly owned 17 Soviet warships in 1989."
    ])

    assert result["ok"] is True
    assert result["flagged"] == []
    assert result.get("warning") == "wikipedia unreachable"
    # All retries should have been exhausted on the only candidate.
    assert call_count["n"] >= 3


def test_anchors_soft_passes_on_connection_error(monkeypatch):
    """Fail-OPEN on requests.get raising (DNS failure, timeout, etc.)."""
    def fake_get(url, timeout, headers):
        raise ConnectionError("dns failure")

    monkeypatch.setattr("requests.get", fake_get)

    result = verify_anchors([
        "Pepsi briefly owned 17 Soviet warships in 1989."
    ])

    assert result["ok"] is True
    assert result["flagged"] == []
    assert result.get("warning") == "wikipedia unreachable"


def test_anchors_handles_empty_claims_list():
    """An empty claims list is a no-op: ok=True, no flags."""
    result = verify_anchors([])
    assert result["ok"] is True
    assert result["flagged"] == []
    assert result["cost_usd"] == 0.0


def test_anchors_handles_claim_without_proper_nouns(monkeypatch):
    """A claim with no extractable Wikipedia title is silently passed."""
    # If verify_anchors does try to fetch, the fake will fail loudly.
    def fake_get(url, timeout, headers):
        raise AssertionError(f"unexpected wikipedia call: {url}")

    monkeypatch.setattr("requests.get", fake_get)

    result = verify_anchors([
        "an event happened sometime"  # no proper nouns, no numbers worth checking
    ])

    assert result["ok"] is True
    assert result["flagged"] == []


def test_anchors_passes_when_article_404s(monkeypatch):
    """Wikipedia returning 404 is not a contradiction; verify_anchors passes."""
    def fake_get(url, timeout, headers):
        return _FakeResponse(404)

    monkeypatch.setattr("requests.get", fake_get)

    result = verify_anchors([
        "Some Obscure Subject did some specific thing in 2020."
    ])

    assert result["ok"] is True
    assert result["flagged"] == []
    # 404 is not a soft-pass condition; no warning.
    assert "warning" not in result


# ---------------------------------------------------------------------- #
# Integration sanity: the two functions are independent
# ---------------------------------------------------------------------- #


def test_consistency_and_anchors_can_run_together(monkeypatch):
    """Both functions on the same brief: consistency mocks Haiku,
    anchors mocks Wikipedia, neither should leak state to the other.
    """
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_haiku_response({
        "consistent": True,
        "reason": "consistent",
    })
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    def fake_get(url, timeout, headers):
        return _FakeResponse(200, {
            "extract": "A neutral encyclopedic description with no contradictions.",
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Test"}},
        })

    monkeypatch.setattr("requests.get", fake_get)

    consistency = verify_consistency(
        {
            "title": "A clean test title",
            "claim": "A clean claim about something specific in 1989.",
        },
        api_key="dummy",
    )
    anchors = verify_anchors(
        ["A claim about something specific in 1989."],
        api_key="dummy",
    )

    assert consistency["ok"] is True
    assert anchors["ok"] is True
