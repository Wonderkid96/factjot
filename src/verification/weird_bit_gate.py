"""Model-judged interestingness gate for autonomous reels (Plan 2 backstop).

`reel_quality.validate_reel_copy` checks shape only: length, and a hook
sentence carrying a concrete anchor plus a turn-signal word. A well-formed
but boring fact passes it cleanly. This module adds a judge that applies the
QUALITY / INTERESTINGNESS GATE from the agent prompt
(`scripts/autonomous_agent.py` SHARED_CORE): a reel only ships if its script
carries a specific weird bit.

Calls the local `claude` CLI (Sonnet, via `src.core.claude_cli`) -- not the
Anthropic API. No ANTHROPIC_API_KEY involved; auth is whatever the CLI
already has on this machine. See `claude_cli` module docstring for why
`--bare` is never used and what that costs.

Two deliberate biases:

* Fail-open. If the judge cannot run (gate disabled, CLI missing, CLI error,
  malformed output) it returns ``(True, "")`` so the autonomous account keeps
  posting on the structural gate alone. The judge is a backstop for the
  egregious case, not a second author, and an unavailable CLI must never
  silence the account.
* Lenient. It rejects only when the model explicitly returns ``passes: false``.
  A false reject costs a whole posting slot, so anything ambiguous ships and
  the agent's own prompt-level gate remains the primary filter.

Disable entirely with ``WEIRD_BIT_GATE=off``.
"""
from __future__ import annotations

import os

from src.core.claude_cli import call_claude_cli

_MODEL = "sonnet"

# Mirrors the INTERESTINGNESS / QUALITY GATE in scripts/autonomous_agent.py
# SHARED_CORE. Kept in sync deliberately: the judge and the agent must share
# one definition of "weird bit", so the gate never rejects what the prompt
# asks the agent to write.
_PROMPT = """\
You are the quality gate for an Instagram account that posts controversial,
shocking, or horrifying true stories. You are given one reel script. Decide
whether it contains a genuine "weird bit" AND whether that weird bit is
shocking, disturbing, or horrifying rather than merely odd or mildly
interesting.

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
not a side detail. It must also clear an intensity bar: a reasonable
listener's honest reaction should be closer to "that's horrifying" or
"wait, WHAT?" than "huh, that's a bit odd" or "that's a fun fact." Mildly
curious or quirky is not enough on its own.

FAIL when there is clearly NO weird bit: the script merely states that an
event happened, or describes something only big, old, famous, sad, expensive,
or dangerous, or needs hype words to sound interesting. FAIL also when the
weird bit is real but only mildly odd or amusing, with no shock, disturbance,
or horror to it. When genuinely unsure whether the intensity clears the bar,
PASS. Do not judge tone, length, grammar, or wording. Judge only whether a
genuinely shocking or horrifying weird bit exists.

SCRIPT:
\"\"\"
{script}
\"\"\"
"""

# --json-schema makes the CLI itself guarantee this shape -- no free-text
# JSON-extraction regex needed, unlike the old direct-API version.
_SCHEMA = {
    "type": "object",
    "properties": {
        "weird_bit": {
            "type": "string",
            "description": "The weird bit in one sentence, or empty if none.",
        },
        "type": {
            "type": "string",
            "description": "One of the nine weird-bit types, or 'none'.",
        },
        "passes": {"type": "boolean"},
        "reason": {
            "type": "string",
            "description": "If failing, one sentence naming what is missing.",
        },
    },
    "required": ["weird_bit", "type", "passes", "reason"],
    "additionalProperties": False,
}

_DEFAULT_FAIL_REASON = (
    "the script has no clear weird bit: it states an event without a "
    "contradiction, absurd mechanism, stupid decision, or strange consequence."
)


def judge_weird_bit(script: str, title: str = "") -> tuple[bool, str]:
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

    envelope = call_claude_cli(
        _PROMPT.format(script=script),
        model=_MODEL,
        json_schema=_SCHEMA,
    )
    if envelope is None:
        return True, ""

    data = envelope.get("structured_output") or {}

    # Lenient: ship unless the judge explicitly says passes=false.
    if data.get("passes") is False:
        reason = (data.get("reason") or "").strip() or _DEFAULT_FAIL_REASON
        wb_type = str(data.get("type") or "none")
        print(f"  [weird-bit] REJECT type={wb_type} reason={reason}", flush=True)
        return False, reason
    return True, ""
