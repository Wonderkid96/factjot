# Rule 09 — Prompt read order

## The rule
Every agent that touches this codebase or this brain reads the following files, in this order, before doing anything else.

```
1. /Users/Music/.claude/CLAUDE.md            — Toby's universal rules
2. /Users/Music/Documents/Insta-bot/CLAUDE.md — repo-level rules
3. insta-brain/CLAUDE.md                      — brain operating manual
4. insta-brain/CRITICAL_FACTS.md              — top-level invariants
5. insta-brain/rules/index.md                 — every rule's one-liner
6. insta-brain/MEMORY_INDEX.md                — latest handover context + verified changes
7. insta-brain/data/posted.jsonl              — already-shared facts (for dedupe)
8. data/used_images.jsonl                     — already-shipped images (for dedupe)
9. insta-brain/inbox.md                       — Toby's drop-ins, if any
```

If a file does not exist, create it empty and continue. Do not skip the read.

## When to re-read
- At the start of every fresh session.
- After an /undo or context reset.
- Before any code change that touches `src/research/`, `src/content/`, `src/render/`, `src/publish/`, or `scripts/publish_*.py`.

## What "read" means
- Load the entire file into context. Don't skim.
- For `.jsonl` ledgers, build an in-memory set of the dedupe keys (`claim_hash` for posted, `url` and `sha256` for used_images).
- Surface anything in `inbox.md` to Toby in the first reply, then process.

## Hooked into code
The `src/brain.py` module loads steps 6 and 7 automatically on import. Calling `brain.is_fact_posted(claim)` or `brain.is_image_used(url=..., sha256=...)` returns the answer directly. Use it; don't re-implement.

## Why this matters
Without this read order, an agent will:
- Repost a fact already shipped (rule 01 violation).
- Reuse a photo already shipped (rule 02 violation).
- Generate copy that contradicts the voice rules (rule 03 violation).
- Silently break the visual system (rule 04 violation).

The brain only works if it's read first.
