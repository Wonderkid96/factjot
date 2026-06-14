"""Model-judged interestingness gate for autonomous reels (Plan 2 backstop).

`reel_quality.validate_reel_copy` checks shape only: length, and a hook
sentence carrying a concrete anchor plus a turn-signal word. A well-formed
but boring fact passes it cleanly. This module adds a cheap Haiku judge that
applies the QUALITY / INTERESTINGNESS GATE from the agent prompt
(`scripts/autonomous_agent.py` SHARED_CORE): a reel only ships if its script
carries a specific weird bit.

Two deliberate biases:

* Fail-open. If the judge cannot run (gate disabled, no API key, SDK missing,
  API error, malformed output) it returns ``(True, "")`` so the autonomous
  account keeps posting on the structural gate alone. The judge is a backstop
  for the egregious case, not a second author, and an API hiccup must never
  silence the account.
* Lenient. It rejects only when the model explicitly returns ``passes: false``.
  A false reject costs a whole posting slot, so anything ambiguous ships and
  the agent's own prompt-level gate remains the primary filter.

Disable entirely with ``WEIRD_BIT_GATE=off``.
"""
from __future__ import annotations

import json
import os

_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 400

# Mirrors the INTERESTINGNESS / QUALITY GATE in scripts/autonomous_agent.py
# SHARED_CORE. Kept in sync deliberately: the judge and the agent must share
# one definition of "weird bit", so the gate never rejects what the prompt
# asks the agent to write.
_PROMPT = """\
You are the quality gate for an Instagram account that posts strange-but-true
facts. You are given one reel script. Decide only whether it contains a genuine
"weird bit": a specific detail, mechanism, decision, contradiction, or
consequence that makes reality look stranger than it should.

A weird bit is ONE of:
- a contradiction
- an absurd mechanism
- a stupid decision
- a strange consequence
- an overlooked detail
- a design failure
- a system behaving in a way no normal person would expect
- a true detail that sounds fake without exaggeration
- a familiar thing made newly strange by one specific fact

It must be specific, sayable in one sentence, and the main point of the script,
not a side detail. It must still be interesting without hype words.

FAIL only when there is clearly NO weird bit: the script merely states that an
event happened, or describes something only big, old, famous, sad, expensive,
or dangerous, or needs hype words to sound interesting. When genuinely unsure,
PASS. Do not judge tone, length, grammar, or wording. Judge only whether a
weird bit exists.

SCRIPT:
\"\"\"
{script}
\"\"\"

Return JSON only, no prose:
{{"weird_bit": "<the weird bit in one sentence, or empty if none>", "type": "<one of the nine types, or none>", "passes": <true or false>, "reason": "<if failing, one sentence naming what is missing>"}}
"""

_DEFAULT_FAIL_REASON = (
    "the script has no clear weird bit: it states an event without a "
    "contradiction, absurd mechanism, stupid decision, or strange consequence."
)


def _extract_json(raw: str) -> dict:
    """Pull the first JSON object out of a model response.

    Tolerates code fences and stray prose around the object by slicing from
    the first ``{`` to the last ``}``. Raises on anything unparseable so the
    caller fails open.
    """
    text = (raw or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object in response")
    return json.loads(text[start : end + 1])


def judge_weird_bit(
    script: str,
    title: str = "",
    api_key: str | None = None,
) -> tuple[bool, str]:
    """Return ``(ok, reason)`` for whether ``script`` carries a weird bit.

    ``ok=True`` ships the reel. ``ok=False`` routes through the agent's
    existing ``reel_copy_quality_failed`` retry path carrying ``reason``.
    Fails open on any infra problem (see module docstring). ``title`` is
    accepted for symmetry with ``validate_reel_copy`` and future use; the
    judgement is made on the script.
    """
    if os.getenv("WEIRD_BIT_GATE", "on").strip().lower() == "off":
        return True, ""

    script = (script or "").strip()
    if not script:
        # Emptiness is the structural gate's job; nothing for the judge to do.
        return True, ""

    api_key = (api_key or os.getenv("ANTHROPIC_API_KEY", "")).strip()
    if not api_key:
        return True, ""

    try:
        from anthropic import Anthropic
    except ImportError:
        return True, ""

    try:
        client = Anthropic(api_key=api_key)
        res = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": _PROMPT.format(script=script)}],
        )
        data = _extract_json(res.content[0].text)
    except Exception as exc:  # noqa: BLE001 - any failure must fail open
        print(
            f"  [weird-bit] judge unavailable, failing open: {str(exc)[:80]}",
            flush=True,
        )
        return True, ""

    # Lenient: ship unless the judge explicitly says passes=false.
    if data.get("passes") is False:
        reason = (data.get("reason") or "").strip() or _DEFAULT_FAIL_REASON
        wb_type = str(data.get("type") or "none")
        print(f"  [weird-bit] REJECT type={wb_type} reason={reason}", flush=True)
        return False, reason
    return True, ""
