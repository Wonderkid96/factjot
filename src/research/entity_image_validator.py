"""Entity image Haiku validator (Phase E.3).

Wikimedia and Wikipedia search return the first reasonably-keyworded hit
for a query, which is often a wrong subject. Real production failures:

- Hillary Clinton 2016 campaign poster behind a deep-ocean submarine reel.
- Engineering officers memorial inscription behind the same script.

This module asks Haiku 4.5 vision to compare a candidate image against the
fact's claim text and the curated image_hint. If the model says the image
does not depict the claim's subject, the caller drops it and continues to
the next candidate.

Soft-fail policy (consistent with `verification.fact_checker`):

- Missing api_key: return ok=True, reason="api_key_missing".
- Anthropic call raises: return ok=True, reason="api_error:<short>".
- Response cannot be parsed: return ok=True, reason="parse_failed:<snippet>".

Hard-fail only when the model itself returns matches=false. The validator
must never block production on its own infrastructure issues; the goal is
to lift quality, not introduce a new failure mode.
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

import requests


_HAIKU_MODEL = "claude-haiku-4-5-20251001"
_PRICING_IN_PER_M = 1.00   # Haiku 4.5: $1 / 1M input tokens
_PRICING_OUT_PER_M = 5.00  # Haiku 4.5: $5 / 1M output tokens
_FETCH_TIMEOUT_S = 10
_MAX_FETCH_BYTES = 4 * 1024 * 1024  # 4 MB ceiling on image bytes sent to Haiku


# Magic-byte to media-type mapping (Anthropic vision accepts these explicitly).
_MEDIA_TYPES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),  # WebP starts with RIFF then 'WEBP' at offset 8
)


def _detect_media_type(data: bytes) -> str:
    """Return Anthropic-compatible media_type for the given image bytes.

    Defaults to image/jpeg if no magic byte matches; Anthropic will reject
    on its own if the bytes are not actually an image.
    """
    if not data:
        return "image/jpeg"
    for magic, mt in _MEDIA_TYPES:
        if data.startswith(magic):
            if mt == "image/webp":
                if len(data) >= 12 and data[8:12] == b"WEBP":
                    return mt
                continue
            return mt
    return "image/jpeg"


def _read_image_bytes(image_url: str) -> bytes | None:
    """Read image bytes from an HTTP(S) URL or a local path.

    Returns up to _MAX_FETCH_BYTES; returns None on any error. Soft-fail
    so callers can continue without validation when network is unavailable.
    """
    try:
        if image_url.startswith(("http://", "https://")):
            r = requests.get(
                image_url,
                headers={"User-Agent": "factjot-bot/1.0 (tobyjohnsonemail@gmail.com)"},
                stream=True,
                timeout=_FETCH_TIMEOUT_S,
            )
            r.raise_for_status()
            buf = bytearray()
            for chunk in r.iter_content(65536):
                buf.extend(chunk)
                if len(buf) >= _MAX_FETCH_BYTES:
                    break
            return bytes(buf[:_MAX_FETCH_BYTES])
        # Treat as local path (or file:// URL).
        local = image_url
        if local.startswith("file://"):
            local = local[7:]
        p = Path(local)
        if not p.exists() or not p.is_file():
            return None
        with open(p, "rb") as f:
            data = f.read(_MAX_FETCH_BYTES)
        return data
    except Exception:
        return None


def _build_prompt(claim_text: str, image_hint: str) -> str:
    """Compose the strict-JSON prompt sent to Haiku alongside the image.

    Kept short to minimise input tokens. The phrasing mirrors the audit
    plan §6 Phase E.3 prompt template; do not rewrite without a paired
    spec change.
    """
    claim = (claim_text or "").strip()
    hint = (image_hint or "").strip()
    return (
        "You are validating whether an image matches a topic claim.\n\n"
        f"Topic claim: \"{claim}\"\n"
        f"Subject hint: \"{hint}\"\n\n"
        "Look at the image and judge: does it plausibly depict the subject of this claim?\n\n"
        "Return strict JSON only:\n"
        "{\"matches\": true|false, \"confidence\": 0.0-1.0, \"reason\": \"<short explanation>\"}\n\n"
        "- matches=true if the image clearly shows the subject (a real photo, "
        "illustration, or archive shot of the named entity or scene).\n"
        "- matches=false if the image shows something different (a person other "
        "than the named one, an unrelated location, abstract or decorative "
        "content, or generic stock not specific to the subject).\n"
        "- confidence is your certainty in the match judgement.\n"
        "- Be strict: a Hillary Clinton poster does NOT match a deep-ocean topic; "
        "an engineering memorial does NOT match a submarine pressure topic."
    )


def _parse_response(raw_text: str) -> tuple[bool | None, float, str]:
    """Extract (matches, confidence, reason) from a model response.

    Returns (None, 0.0, "<error>") on parse failure; caller decides how to
    treat that.
    """
    if not raw_text:
        return None, 0.0, "empty_response"
    m = re.search(r"\{[\s\S]*\}", raw_text)
    if not m:
        return None, 0.0, f"no_json:{raw_text[:60]}"
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        return None, 0.0, f"json_decode:{str(exc)[:40]}"
    matches = data.get("matches")
    conf = data.get("confidence", 0.0)
    reason = str(data.get("reason", "")).strip()[:120]
    if not isinstance(matches, bool):
        return None, 0.0, f"invalid_matches:{matches!r}"
    try:
        conf_f = float(conf)
    except (TypeError, ValueError):
        conf_f = 0.0
    conf_f = max(0.0, min(1.0, conf_f))
    return matches, conf_f, reason or ("matches" if matches else "no_match")


def _compute_cost(usage: Any) -> float:
    """Compute Haiku 4.5 cost in USD for a single response.

    Falls back to 0.0 if usage attributes are missing (mock objects, older
    SDK, etc.). Rounded to 5 dp, consistent with fact_checker.
    """
    try:
        cost = (
            usage.input_tokens / 1_000_000 * _PRICING_IN_PER_M
            + usage.output_tokens / 1_000_000 * _PRICING_OUT_PER_M
        )
    except (AttributeError, TypeError):
        return 0.0
    return round(float(cost), 5)


def _soft_pass(reason: str, cost_usd: float = 0.0) -> dict:
    """Return the canonical soft-fail dict shape.

    The validator fails OPEN on infra issues (missing api_key, fetch
    error, Anthropic SDK missing, API error) so a single failing
    upstream cannot block production. But the caller in video_finder
    discards the returned dict to a bool, hiding which path soft-passed.
    A quota exhaustion or rotated key would let every image through
    the validator unchecked, silently. Surface to the workflow log
    so 'why does my validator never fire' has a visible cause.

    Confidence 1.0 results never come through here so we can be loud.
    """
    print(
        f"[entity-validate] SOFT-PASS reason={reason}",
        flush=True,
    )
    return {
        "ok": True,
        "confidence": 0.0,
        "reason": reason,
        "cost_usd": cost_usd,
    }


def validate_entity_image(
    image_url: str,
    claim_text: str,
    image_hint: str,
    api_key: str,
    *,
    cache: dict[str, dict] | None = None,
) -> dict:
    """Ask Haiku 4.5 vision whether the image matches the topic claim.

    Parameters
    ----------
    image_url
        HTTP(S) URL, file:// URL, or local filesystem path. Bytes are read
        and sent to Haiku as base64; if the URL is HTTP(S) and the upstream
        host blocks the bot, the function falls back to ok=True (soft-pass)
        rather than rejecting the candidate.
    claim_text
        Plain-text claim from the reel/carousel brief.
    image_hint
        Curated subject hint, e.g. "Hillary Clinton 2016 campaign poster".
        May be empty.
    api_key
        Anthropic API key. Empty string -> soft-pass (skip validation).
    cache
        Optional in-memory dict keyed by image_url. The same dict is reused
        across calls in the same `find_videos` invocation so the same URL
        is not validated twice.

    Returns
    -------
    dict with keys:
        ok          - True if image matches OR the call soft-failed.
        confidence  - 0.0-1.0 (0.0 on soft-fail).
        reason      - short human-readable explanation.
        cost_usd    - USD cost of the Haiku call (0.0 on soft-fail).
    """
    # Cache lookup: same URL within one session reuses the previous result.
    if cache is not None and image_url in cache:
        return cache[image_url]

    if not api_key:
        result = _soft_pass("api_key_missing")
        if cache is not None:
            cache[image_url] = result
        return result

    # Fetch bytes (local or remote). Soft-fail if we cannot.
    img_bytes = _read_image_bytes(image_url)
    if img_bytes is None or len(img_bytes) < 64:
        result = _soft_pass("fetch_failed")
        if cache is not None:
            cache[image_url] = result
        return result

    media_type = _detect_media_type(img_bytes)
    b64 = base64.standard_b64encode(img_bytes).decode("ascii")

    try:
        from anthropic import Anthropic
    except ImportError:
        result = _soft_pass("anthropic_sdk_missing")
        if cache is not None:
            cache[image_url] = result
        return result

    prompt = _build_prompt(claim_text, image_hint)

    try:
        client = Anthropic(api_key=api_key)
        res = client.messages.create(
            model=_HAIKU_MODEL,
            max_tokens=200,
            temperature=0.0,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
    except Exception as exc:
        result = _soft_pass(f"api_error:{str(exc)[:80]}")
        if cache is not None:
            cache[image_url] = result
        return result

    cost = _compute_cost(getattr(res, "usage", None))

    raw_text = ""
    try:
        raw_text = res.content[0].text or ""
    except (AttributeError, IndexError):
        raw_text = ""

    matches, confidence, reason = _parse_response(raw_text)

    if matches is None:
        result = {
            "ok": True,
            "confidence": 0.0,
            "reason": f"parse_failed:{reason}",
            "cost_usd": cost,
        }
    else:
        result = {
            "ok": bool(matches),
            "confidence": confidence,
            "reason": reason,
            "cost_usd": cost,
        }

    if cache is not None:
        cache[image_url] = result
    return result
