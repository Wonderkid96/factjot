# Rule 14 — Sensitivity / controversy filter

We post 2 carousels/day on @factjot. The bank carries shock-tier facts because that's what gets shared. The question this rule answers: which facts can the *autonomous* pipeline ship without a human checking, and which need a human to look first?

The answer is narrower than it used to be:

> **Animal cruelty is the only category that auto-blocks. Everything else flows.**

Updated 2026-05-01. Previously religion, politics, suicide context, sexual content, and graphic violence were all auto-blocked. They're now informational tags only — the autonomous queue ships them. Operator and bank curators are the final filter for framing.

## Tiers

- **safe** — default. Nothing flagged. Always autonomous-publishable.
- **edgy** — has at least one informational flag (graphic medical, body horror, religion topic, politics topic, suicide topic, sexual topic, violence topic, etc). **Still autonomous-publishable.** The flag exists so future analytics can see "this fact mentions a sensitive subject" without blocking publish.
- **controversial** — animal-cruelty content. Or anything an author manually flags. **Operator opt-in only.** Auto-classifier currently routes here only on `animal_welfare` triggers. Authors can also set `sensitivity: "controversial"` on a row by hand if they think the framing is too much.

## Why animal cruelty stays restricted

Specific to factjot's audience. Animal-welfare folks are over-represented in the curiosity-content niche, and posts that read as endorsing cruelty (even historically, even framed as "weird historical fact") generate angry comments, unfollows, and don't get shared. The Mike Headless Chicken story burned us — animals being deliberately harmed is the one thing that kills a post for our specific feed.

Other heavy subjects (genocide, suicide, religion, politics) can absolutely be discussed factually — we just need framing discipline, which falls to the bank curators (and the truth gate for discovered facts).

## Instagram Community Standards (the actual outer wall)

Beyond our own editorial line, every post must comply with **Instagram's Community Standards**: <https://help.instagram.com/477434105621119>. Anything that would violate IG terms (graphic gore, hate speech, sexually explicit content, promotion of self-harm, regulated-goods marketing without compliance, dehumanising minorities, election misinformation) does not ship — full stop. This is a hard wall that sits OUTSIDE the sensitivity tiers; the classifier does not check it because the bank is human-curated and discovered facts go through the truth gate.

If discovery starts surfacing IG-violating content, tighten the gate (rule 10). Don't try to encode "is this hate speech?" in regex.

## Default behaviour

- `plan_week.py` (autonomous queue): **safe + edgy.** Only `controversial` is excluded.
- `ship_first_post.py` (manual fire): **safe + edgy by default.** `--safe-only` narrows. `--allow-controversial` widens (use after a quick eyeball check).

## When to override on a bank row

Set `sensitivity` and `sensitivity_flags` explicitly when:
- The auto-classifier missed something (e.g. fact involves animal harm but the regex didn't match).
- A fact has factual-dispute risk (Mike Headless Chicken's brain stem). Add the `factual_dispute` flag.
- The framing is genuinely too dark for our audience even if the regex didn't trigger. Author judgment wins.

## Reviewing flagged facts

```
python3 -c "
from src.research.rare_fact_bank import load_all_facts
for r in load_all_facts():
    if r['sensitivity'] != 'safe':
        print(f\"[{r['sensitivity']}] {r['sensitivity_flags']} :: {r['claim'][:90]}\")
"
```

## Editing the trigger list

`src/research/sensitivity_guide.py` → `TRIGGER_PATTERNS`. Each entry is `(flag_name, tier, [regex patterns])`. Currently only `animal_welfare` is `controversial`. Add to that list if a new pattern of cruelty content needs blocking; route everything else to `edgy` so it stays publishable.
