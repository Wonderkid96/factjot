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
# Anthropic vision API rejects images whose base64 encoding exceeds 5 MB
# (5 * 1024 * 1024 = 5242880 bytes). Base64 inflates raw bytes by ~33%, so
# the raw ceiling is 5242880 * 3/4 = 3932160 bytes. We use 3 MB for safety.
_MAX_FETCH_BYTES = 3 * 1024 * 1024  # 3 MB raw — base64 ≤ 4 MB, safely under the 5 MB API limit
_MAX_BASE64_BYTES = 5 * 1024 * 1024  # Anthropic hard limit on base64-encoded image size


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

    For HTTP(S): streams up to _MAX_FETCH_BYTES to cap memory use.
    For local files: reads the whole file OR returns None if the file
    would exceed the Anthropic 5 MB base64 limit after encoding.
    Truncating a local file corrupts the image data (a truncated PNG
    sent to the API returns a 400 invalid_request_error).

    Returns None on any error. Soft-fail so callers can continue
    without validation when the network or filesystem is unavailable.
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
        # Local path or file:// URL — read the whole file.
        local = image_url
        if local.startswith("file://"):
            local = local[7:]
        p = Path(local)
        if not p.exists() or not p.is_file():
            return None
        # Skip before reading if the file is too large to encode within the
        # Anthropic 5 MB base64 limit (base64 factor = 4/3, so max raw is
        # 5 MB * 3/4 = 3.75 MB). Returning None here triggers a soft-pass in
        # the caller, which is then caught as a size-skip, not a parse error.
        raw_size = p.stat().st_size
        if raw_size * 4 > _MAX_BASE64_BYTES * 3:  # raw > 3.75 MB -> base64 > 5 MB
            return None
        with open(p, "rb") as f:
            return f.read()
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

    # Guard: Anthropic rejects images whose base64 size exceeds 5 MB.
    # This fires when _MAX_FETCH_BYTES allows a file through but the
    # base64 expansion pushes it over the API limit (e.g. a 4 MB PNG
    # encodes to 5.3 MB base64 → 400 invalid_request_error).
    if len(b64) > _MAX_BASE64_BYTES:
        result = _soft_pass(f"image_too_large_for_api:{len(b64)//1024}KB_base64")
        if cache is not None:
            cache[image_url] = result
        return result

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


# ---------------------------------------------------------------------------
# Batch validation — sends up to batch_size images in a single Haiku call,
# storing results in cache so subsequent single-image calls are cache hits.
# ---------------------------------------------------------------------------

def _build_batch_prompt(claim_text: str, image_hint: str, n_images: int) -> str:
    claim = (claim_text or "").strip()
    hint = (image_hint or "").strip()
    return (
        f"You are validating whether {n_images} image(s) match a topic claim.\n\n"
        f"Topic claim: \"{claim}\"\n"
        f"Subject hint: \"{hint}\"\n\n"
        f"The images are numbered 0 to {n_images - 1} in the order shown.\n"
        "For EACH image judge: does it plausibly depict the subject?\n\n"
        "Return a JSON array with one object per image, in order:\n"
        "[{\"id\": 0, \"matches\": true|false, \"confidence\": 0.0-1.0, \"reason\": \"short\"}, ...]\n\n"
        "- matches=true  → image clearly shows the subject.\n"
        "- matches=false → unrelated location, wrong person, generic stock.\n"
        "- Be strict: wrong subject → false."
    )


def _parse_batch_response(raw_text: str) -> list[dict]:
    if not raw_text:
        return []
    m = re.search(r"\[[\s\S]*\]", raw_text)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    return []


def _validate_batch_chunk(
    image_paths: list[str],
    claim_text: str,
    image_hint: str,
    api_key: str,
    *,
    cache: dict[str, dict] | None = None,
) -> list[dict]:
    """Send up to 4 images in one Haiku call. Returns one result per input."""
    n = len(image_paths)

    # Load image bytes; soft-pass immediately on fetch failure.
    loaded: list[tuple[int, bytes, str]] = []  # (original_idx, img_bytes, media_type)
    pre_results: dict[int, dict] = {}
    for idx, path in enumerate(image_paths):
        img_bytes = _read_image_bytes(path)
        if img_bytes is None or len(img_bytes) < 64:
            pre_results[idx] = _soft_pass("fetch_failed")
        else:
            loaded.append((idx, img_bytes, _detect_media_type(img_bytes)))

    if not loaded:
        out = [pre_results[i] for i in range(n)]
        if cache is not None:
            for path, result in zip(image_paths, out):
                cache[path] = result
        return out

    # Build content: one image block per loaded image, then the batch prompt.
    # Skip images whose base64 encoding would exceed the 5 MB API limit.
    content: list[dict] = []
    loaded_filtered: list[tuple[int, bytes, str]] = []
    for orig_idx, img_bytes, media_type in loaded:
        b64_data = base64.standard_b64encode(img_bytes).decode("ascii")
        if len(b64_data) > _MAX_BASE64_BYTES:
            pre_results[orig_idx] = _soft_pass(f"image_too_large_for_api:{len(b64_data)//1024}KB_base64")
            continue
        loaded_filtered.append((orig_idx, img_bytes, media_type))
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": b64_data,
            },
        })
    loaded = loaded_filtered
    content.append({"type": "text", "text": _build_batch_prompt(claim_text, image_hint, len(loaded))})

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        res = client.messages.create(
            model=_HAIKU_MODEL,
            max_tokens=max(200, 80 * len(loaded)),
            temperature=0.0,
            messages=[{"role": "user", "content": content}],
        )
    except Exception as exc:
        soft = _soft_pass(f"api_error:{str(exc)[:80]}")
        out = [pre_results.get(i, soft) for i in range(n)]
        if cache is not None:
            for path, result in zip(image_paths, out):
                cache[path] = result
        return out

    cost = _compute_cost(getattr(res, "usage", None))
    cost_per = cost / max(1, len(loaded))

    raw_text = ""
    try:
        raw_text = res.content[0].text or ""
    except (AttributeError, IndexError):
        pass

    parsed = _parse_batch_response(raw_text)

    api_results: dict[int, dict] = {}
    for batch_pos, (orig_idx, _, _) in enumerate(loaded):
        if batch_pos < len(parsed):
            pr = parsed[batch_pos]
            matches = pr.get("matches")
            conf = max(0.0, min(1.0, float(pr.get("confidence", 0.0))))
            reason = str(pr.get("reason", "")).strip()[:120]
            if matches is None:
                api_results[orig_idx] = {"ok": True, "confidence": 0.0, "reason": f"parse_failed:{reason}", "cost_usd": cost_per}
            else:
                api_results[orig_idx] = {"ok": bool(matches), "confidence": conf, "reason": reason, "cost_usd": cost_per}
        else:
            api_results[orig_idx] = _soft_pass("parse_failed", cost_usd=cost_per)

    out = []
    for i in range(n):
        result = pre_results.get(i) or api_results.get(i) or _soft_pass("missing_result")
        out.append(result)
        if cache is not None:
            cache[image_paths[i]] = result
    return out


def validate_entity_images_batch(
    image_paths: list[str],
    claim_text: str,
    image_hint: str,
    api_key: str,
    *,
    cache: dict[str, dict] | None = None,
    batch_size: int = 4,
) -> list[dict]:
    """Validate multiple still images against a claim in batched Haiku calls.

    Sends up to `batch_size` images per API call instead of one at a time.
    Results are stored in `cache` (keyed by image path string) so subsequent
    calls to `validate_entity_image()` for the same paths are cache hits.

    Args:
        image_paths: Ordered list of local paths or HTTP URLs to validate.
        claim_text:  Reel/carousel claim text.
        image_hint:  Subject hint (may be empty).
        api_key:     Anthropic API key. Empty string → all soft-pass.
        cache:       Shared result cache (mutated in place).
        batch_size:  Images per API call (max 4; Anthropic vision limit).

    Returns:
        List of result dicts in the same order as `image_paths`.
    """
    results: list[dict | None] = [None] * len(image_paths)

    # Check cache and soft-pass on missing api_key first.
    pending: list[int] = []
    for i, path in enumerate(image_paths):
        if cache is not None and path in cache:
            results[i] = cache[path]
        elif not api_key:
            results[i] = _soft_pass("api_key_missing")
            if cache is not None:
                cache[path] = results[i]
        else:
            pending.append(i)

    # Process uncached images in batches.
    for start in range(0, len(pending), batch_size):
        chunk_indices = pending[start:start + batch_size]
        chunk_paths = [image_paths[i] for i in chunk_indices]
        chunk_results = _validate_batch_chunk(chunk_paths, claim_text, image_hint, api_key, cache=cache)
        for i, result in zip(chunk_indices, chunk_results):
            results[i] = result

    return [r for r in results]  # type: ignore[misc]
