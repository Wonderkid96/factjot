# Rule 18 — Keep routines in sync with code

The three Claude scheduled routines are live operational prompts, not documentation. When code changes, they must be updated to match. A stale routine is a broken routine.

## The three routines

| Task ID | Schedule | Prompt path |
|---|---|---|
| `factjot---am-post---900am` | 09:02 daily | `~/.claude/scheduled-tasks/factjot---am-post---900am/SKILL.md` |
| `factjot---pm-post-1800` | 18:09 daily | `~/.claude/scheduled-tasks/factjot---pm-post-1800/SKILL.md` |
| `factjot---topup` | 14:04 daily | `~/.claude/scheduled-tasks/factjot---topup/SKILL.md` |

Update via: `mcp__scheduled-tasks__update_scheduled_task` with the task ID and new `prompt`.

## What triggers a routine update

Any change to the following MUST be followed by an immediate routine review:

- **Script flags or defaults change** — e.g. `ship_first_post.py` defaulting to safe+edgy (not just safe) changed what flag the morning/evening routines needed to document.
- **New script added to the pipeline** — e.g. `check_brain_fresh.py` becoming a mandatory first step needed adding to both fact routines.
- **Topic list changes** — if a new topic is added to the bank, the weekly top-up step 6 list needs updating.
- **Sensitivity gate changes** — if what the autonomous queue allows shifts (e.g. edgy now auto-queues), the routines referencing that behaviour need updating.
- **New ledger files** — if a new brain file is introduced that routines should write to or check.
- **Python path changes** — if the canonical Python path moves.
- **New mandatory step** — e.g. if we add a rate-limit check before publishing, it needs to be wired into the routines.
- **Behavioural fix** — if a script's behaviour changes (e.g. publisher now recovers from false-failure responses), document it in any relevant routine if it changes what the routine should do.

## How to check and update

1. Read the current routine prompts — `Read ~/.claude/scheduled-tasks/<task-id>/SKILL.md`
2. Compare against changed code.
3. Update via `mcp__scheduled-tasks__update_scheduled_task`.
4. Append a line to `insta-brain/log.md`: `"routine update: <task-id> — <what changed and why>"`

## When in doubt

If a code change touches any script referenced in a routine, open the routine and read it. Takes 30 seconds. Costs nothing. A single stale flag in a routine that fires twice a day causes 14 wrong publishes per week before anyone notices.

## Enforcement

This rule applies to every agent, every session. It's part of the MEMORY_INDEX update checklist (rule 13). When writing a MEMORY_INDEX entry for a code change, add a "routine impact" line — even if the answer is "no routine change needed."
