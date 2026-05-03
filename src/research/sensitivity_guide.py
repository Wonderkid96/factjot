"""Sensitivity / controversy filter for fact selection.

We post 2 carousels/day on @factjot. The bank is heavy on shock-tier facts
because that's what gets screenshot-shared. But "shocking" and "will piss
people off" are not the same thing. Phineas Gage is iconic. Mike the Headless
Chicken upsets animal-welfare folks AND triggers a "his brain stem was
intact, this is misleading" pile-on in the comments. The first is shareable,
the second is a comment-section fire.

This module classifies a fact into one of three tiers:

    safe          → default-publishable, no triggering content
    edgy          → dark/intense but historically well-received
                    (Phineas Gage, Aron Ralston, Demon Core). Opt-in.
    controversial → high risk of negative comments / unfollows.
                    Opt-in via explicit flag only.

Authors can override the auto-classification by setting `sensitivity` and
`sensitivity_flags` directly on a bank row. Otherwise we infer from the
claim text using TRIGGER_PATTERNS.

Public API:

    assess_sensitivity(claim) -> (tier, flags)
        Pure-text classifier. Returns ("safe", []) when nothing triggers.

    apply_sensitivity_defaults(row) -> row
        Backfills row["sensitivity"] and row["sensitivity_flags"] in place
        if they're missing. Called from rare_fact_bank._with_defaults so
        every loaded fact carries the fields.

    filter_for_publish(rows, allow_edgy=False, allow_controversial=False)
        Return a filtered list. Default keeps only `safe`. Each opt-in
        widens the gate. Used by ship_first_post and plan_week.
"""
from __future__ import annotations

import re
from typing import Iterable

# Tier names (string-typed everywhere; no enum to keep JSON-friendly).
SAFE = "safe"
EDGY = "edgy"
CONTROVERSIAL = "controversial"
TIERS = (SAFE, EDGY, CONTROVERSIAL)

# Each trigger maps to (flag_name, tier, [regex patterns]).
# Patterns are case-insensitive, matched against the claim text.
# Order matters: we record ALL flags that hit, but the resulting tier is
# the WORST (most restrictive) hit.
#
# Editorial line (rule 14, updated 2026-05-01):
#   Animal cruelty is the only category that auto-routes to controversial.
#   Religion, politics, sexual content, suicide context, graphic violence
#   are tagged as `edgy` (informational) but do NOT block autonomous publish.
#   Trust the bank curators (and the truth gate for discovered facts) to
#   handle framing. Stay within Instagram's published Community Standards
#   regardless of what the classifier says - the operator is the final filter.
TRIGGER_PATTERNS: list[tuple[str, str, list[str]]] = [
    # --- CONTROVERSIAL (the only auto-blocked tier) ---------------------
    (
        "animal_welfare",
        CONTROVERSIAL,
        [
            r"\bcut off (?:a|the|his|her|its)?\s*\w*\s*(chicken|dog|cat|horse|cow|pig|sheep|rabbit)",
            r"\bdecapitat\w* (?:a|the|his|her)?\s*\w*\s*(chicken|dog|cat|horse|cow|pig|sheep|rabbit)",
            r"\b(live|living) (cat|dog|eel|rat|mouse|rabbit|chicken)\b",
            r"\bate? a (live|living) (cat|dog|eel|rat|mouse|rabbit|chicken)",
            r"\bvivisect",
            r"\btortured? (?:an?|the)? (animal|dog|cat|horse)",
            r"\b(animal|dog|cat|horse|cow|pig) (was )?beaten to death",
            r"\bskinned alive",
            r"\bdog ?fight\w*",
            r"\bcock ?fight\w*",
            r"\bbull ?fight\w*",
        ],
    ),

    # --- EDGY (informational tags; do NOT block autonomous publish) ----
    # These get classified as `edgy` so we know the fact has an intense
    # framing element, but the autonomous queue ships them. Operators can
    # still manually mark a specific row as `controversial` if they think
    # the framing is too much for our audience - author override wins.
    (
        "graphic_medical",
        EDGY,
        [
            r"\bamputat\w+ (his|her|their) own (arm|leg|hand|foot)",
            r"\bcut off (his|her) own (arm|leg|hand|foot)",
            r"\b(iron|metal|tamping) rod through (his|her|the) (skull|head|brain)",
            r"\b(skull|brain) (was|got) (impaled|pierced|perforated)",
            r"\bautops\w+",
            r"\bdissect\w+",
            r"\bdecompos\w+ (body|corpse)",
            r"\bradiation poisoning\b",
            r"\bplague (victim|pit|burial)",
        ],
    ),
    (
        "death_event",
        EDGY,
        [
            r"\bnuclear (bomb|weapon|test|fallout)\b",
            r"\b(executed|execution) (?:by|of) (?:a |the )?(?:firing squad|hanging|guillotine|electric chair|lethal injection|gas chamber|prisoner|criminal|king|queen|emperor|spy|traitor|witch|witches)\b",
            r"\bguillotine\w*",
            r"\bdied (in|of|from) (the|a) (explosion|fire|crash|accident)",
            r"\b(killed|died) (instantly|in agony)",
            r"\bfamine\b",
        ],
    ),
    (
        "body_horror",
        EDGY,
        [
            r"\b(parasite|cordyceps).*(brain|mind|control)",
            r"\bfuses? (his|her|its) body (to|with)",
            r"\bloses? (his|her|its) (eyes|organs|skull)\b",
            r"\binsect.*lays? eggs (in|inside)",
        ],
    ),
    (
        "religion_topic",
        EDGY,
        [
            r"\b(allah|muhammad|prophet muhammad|quran)\b",
            r"\b(jesus christ|crucifixion)\b",
            r"\b(scientology|mormon\w*)\b",
            r"\b(buddhist|hindu|sikh|jewish|jain) (monk|temple|ritual)",
        ],
    ),
    (
        "politics_topic",
        EDGY,
        [
            r"\b(trump|biden|harris|putin|xi jinping|netanyahu|zelensky|starmer|sunak|farage)\b",
            r"\b(election|coup|regime|dictator)\b",
        ],
    ),
    (
        "suicide_topic",
        EDGY,
        [
            r"\b(suicide|hanged (him|her)self|shot (him|her)self|took (his|her) own life)\b",
        ],
    ),
    (
        "sexual_topic",
        EDGY,
        [
            r"\b(rape|raped|incest|paedophil\w+|pedophil\w+)\b",
            r"\bsexually assault\w+",
        ],
    ),
    (
        "violence_topic",
        EDGY,
        [
            r"\b(genocide|massacre|holocaust|ethnic cleansing)\b",
            r"\b(beheaded|decapitated) (a|the|\d+)\s*(person|man|woman|child|prisoner)",
            r"\bschool shooting\b",
        ],
    ),
]


def assess_sensitivity(claim: str) -> tuple[str, list[str]]:
    """Classify a claim's sensitivity from its text alone.

    Returns (tier, flags). Tier is the worst hit across all matches;
    flags is every trigger name that matched (deduped, ordered by
    first appearance in TRIGGER_PATTERNS).
    """
    if not claim:
        return SAFE, []
    text = claim.lower()
    hit_flags: list[str] = []
    hit_tiers: set[str] = set()
    for flag, tier, patterns in TRIGGER_PATTERNS:
        for pat in patterns:
            if re.search(pat, text, flags=re.IGNORECASE):
                if flag not in hit_flags:
                    hit_flags.append(flag)
                hit_tiers.add(tier)
                break
    if CONTROVERSIAL in hit_tiers:
        return CONTROVERSIAL, hit_flags
    if EDGY in hit_tiers:
        return EDGY, hit_flags
    return SAFE, hit_flags


def apply_sensitivity_defaults(row: dict) -> dict:
    """Backfill row['sensitivity'] and row['sensitivity_flags'] in place.

    Honours explicit author overrides: if `sensitivity` is already set,
    we leave it alone. Otherwise we derive both fields from the claim
    text via assess_sensitivity().
    """
    if "sensitivity" in row and row["sensitivity"] in TIERS:
        row.setdefault("sensitivity_flags", [])
        return row
    tier, flags = assess_sensitivity(row.get("claim", ""))
    row["sensitivity"] = tier
    # Don't clobber author-supplied flags; merge.
    existing = list(row.get("sensitivity_flags") or [])
    for f in flags:
        if f not in existing:
            existing.append(f)
    row["sensitivity_flags"] = existing
    return row


def filter_for_publish(
    rows: Iterable[dict],
    *,
    allow_edgy: bool = False,
    allow_controversial: bool = False,
) -> list[dict]:
    """Drop rows whose sensitivity tier exceeds what the caller permits.

    Default = safe-only. `allow_edgy` widens to safe+edgy.
    `allow_controversial` implies allow_edgy and lets everything through.
    """
    permitted = {SAFE}
    if allow_edgy or allow_controversial:
        permitted.add(EDGY)
    if allow_controversial:
        permitted.add(CONTROVERSIAL)
    out = []
    for r in rows:
        tier = r.get("sensitivity") or assess_sensitivity(r.get("claim", ""))[0]
        if tier in permitted:
            out.append(r)
    return out


__all__ = [
    "SAFE",
    "EDGY",
    "CONTROVERSIAL",
    "TIERS",
    "assess_sensitivity",
    "apply_sensitivity_defaults",
    "filter_for_publish",
]
