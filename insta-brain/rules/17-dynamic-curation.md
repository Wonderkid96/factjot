# Rule 17 — Dynamic curation (the meta-rule)

The other rules are scaffolding, not handcuffs. Use them to stay aligned with the brand and avoid known traps. Override them when the curation calls for it and you can articulate why.

## What's actually inviolate

These break us if broken. Not negotiable:

1. **No em dashes.** Comes from Toby's CLAUDE.md, applies everywhere.
2. **No reposting facts.** Rule 01. Same hash → same fact → already shipped.
3. **No reusing images.** Rule 02. Visual fatigue kills feeds.
4. **No animal-cruelty content auto-publishing.** Rule 14. The only sensitivity tier the autonomous queue gates out. Operator can opt in via `--allow-controversial`.
5. **Stay within Instagram Community Standards.** <https://help.instagram.com/477434105621119>. Hate speech, graphic gore, sexually explicit content, regulated-goods marketing without compliance, election misinformation — none of it ships, full stop. This sits OUTSIDE the sensitivity classifier and is the operator's responsibility.
6. **Each list pack ships once.** Rule 15. Slug is identity.
7. **Sources required and verified.** ≥2 trusted-domain sources for every fact slide.
8. **Brand kit is locked.** Rule 04. Colours, fonts, layout — visual rules don't move.

What this list deliberately does NOT include: religion, politics, suicide context, sexual topics, graphic violence in factual context. Those subjects can be discussed factually as long as the framing is responsible and the post stays within IG terms. They get tagged as `edgy` for analytics but don't block publish.

## What's guidance, not law

Treat these as defaults that can flex when there's a reason:

- **Sensitivity tiers** (rule 14). Auto-classifier flags things; the operator can override. Edgy facts auto-publish now because they're well-loved. Borderline calls go to your judgment.
- **Spoilers** (rule 16). The 30-minute rule is a guide. Cultural-knowledge reveals are different from genuine twists. Use restraint and trust the audience.
- **List cadence** (rule 15). "Roughly weekly" doesn't mean "exactly weekly". If a great pack is ready and the feed wants it, ship.
- **Variety dimensions** (rule 15). Domain rotation, tone rotation, framing-word variety — all guidance. Two great film packs in a row beats forcing a mediocre album pack just to rotate.
- **Item count per pack** (rule 15). 5 is typical. 3–7 are all fine.
- **Quirky_score sorting** in `ship_first_post.py`. Default biases toward shock-tier facts. The operator can sort differently if a topic's pool needs balance.
- **Truth gate stages** (rule 10). The 8-stage filter for r/TIL discoveries is calibrated for the volume we expect. If discovery starts producing too few or too many false positives, tune the thresholds — they're not sacred numbers.

## Default disposition: lean toward shipping

When you're stuck choosing between "polish more" and "ship now":

- **Ship now**, unless shipping breaks one of the inviolate rules above.
- We learn more from a published post and the analytics that follow than from a perfect draft.
- A small layout flaw is usually invisible at IG-feed scroll speed.
- Better to publish 5 good posts this week than perfect 1 next week.

The exception: anything that would damage trust (factual errors, spoilers in a sensitive context, a pack that punches down) — fix before shipping.

## Default disposition: trust the operator

When the autonomous pipeline disagrees with what a human operator wants to do, the human wins. The pipeline exists to handle the steady state — facts every day at 10:00 and 18:00. It's not in charge of editorial calls. Operator overrides are normal and don't need a justification beyond "I want to ship this".

## When in doubt about a rule

Read the rule once, decide if it applies. If you find yourself bending it three times in a row, that's a signal the rule needs an update — propose an edit rather than keep working around it.
