# Rule 13 — Memory index discipline

## The rule
Every non-trivial change batch must be indexed in `insta-brain/MEMORY_INDEX.md` before the task is considered complete.

## Required entry format
Each new entry must include:
- date
- what changed
- why
- affected files
- verification performed

## Write behaviour
- Newest entry at top.
- Append-only, never delete old entries.
- Keep entries short but specific enough for a new agent to continue safely.

## Enforcement
If a change is shipped without a memory index entry, add the missing entry immediately and log the omission in `insta-brain/log.md`.

## Automated check
Before any commit, publish, or release, run:

```
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 scripts/check_brain_fresh.py
```

The script fails (exit 1) if any file under `src/`, `scripts/`, `brand/`, or
`src/render/templates/` has been modified more recently than
`insta-brain/MEMORY_INDEX.md` or `insta-brain/log.md`. A 60-second grace
window covers clock skew.

Wire this into:
- The publish flow (`publish_now.py` and `publish_due.py` MUST refuse to ship
  if `check_brain_fresh.py` returns non-zero — a stale brain blocks an
  outgoing post).
- The launchd plist that fires daily auto-publishes.
- Any CI / pre-commit hook the project ever gains.

Failing the check is a rule 13 violation. Fix forward: append the missing
MEMORY_INDEX block, append a one-line `log.md` entry, re-run the check.
