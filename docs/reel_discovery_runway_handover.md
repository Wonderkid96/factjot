# Reel Discovery and Runway Handover

This document explains how reel candidates should be discovered, verified, enriched, and queued with low daily API cost.

## Goal

- Keep reels shockworthy and fresh.
- Keep truth standards high.
- Keep daily cost low and predictable.
- Avoid emergency low-quality picks.

## Current state summary

- Reels are selected from merged fact pool:
  - `src/research/rare_fact_bank.py` (`RARE_FACT_BANK`)
  - `data/ledgers/discovered_facts.jsonl` (discovery feed)
- Merge function: `load_all_facts()` in `src/research/rare_fact_bank.py`
- Picker: `_pick_fact()` in `scripts/make_reel.py`
- Discovery runner: `scripts/discover_facts.py`
- Weekly trigger: `.github/workflows/weekly-plan.yml` via `scripts/restock.py`
- Daily emergency trigger: `.github/workflows/reel.yml` when runway is low

## Truth gates (must stay strict)

Discovery currently rejects candidates when:

- source domain is not allowlisted
- post is too new (`young_post`)
- upvotes below subreddit threshold
- correction signals are found in top comments
- claim tokens are not supported by fetched source text (`source_unsupported`)

Keep these as the hard safety layer. Reddit title is a lead, not final truth.

## Recommended operating model

## 1) Daily cheap pass

Run discovery every day.

- Append verified candidates to `data/ledgers/discovered_facts.jsonl`
- Do not run script generation by default
- Log reject reasons and monitor reject mix

## 2) Runway controller

Use a fixed runway threshold for enrichment:

- target runway: 10-14 days
- if runway >= threshold: skip enrichment
- if runway < threshold: run enrichment batch

Enrichment means adding:

- `reel_title`
- `reel_script` (>=70 words)

Only enriched rows become postable reel candidates.

## 3) Weekly deep harvest

Current discovery window is narrow if only `top/month` is scanned.

Expand breadth:

- scan windows: `top/month`, `top/year`, `top/all`
- paginate with `after` cursor
- persist scan state per subreddit and window

Suggested state ledger:

- `data/ledgers/discovery_scan_state.json`
  - subreddit
  - feed window
  - cursor
  - last scanned at

This ensures each run searches a different slice instead of repeating the same top items.

## 4) Candidate scoring priorities

Rank candidates by:

- quirky score
- source credibility tier
- specificity (named entities, dates, numbers)
- novelty and stakes
- duplicate risk

Use performance weighting as a tie-breaker, not primary selector.

## Why reels felt boring

Main causes:

- discovery feed was reset and temporarily empty
- strict gates plus narrow scan window yielded very low append count
- picker can only choose from what is available and enriched

So this is mostly an intake and enrichment throughput problem, not only picker logic.

## Daily schedule suggestion

- Every day:
  - run discovery
  - update reject summary metrics
  - check runway
  - enrich only if below threshold
- Weekly:
  - run deep Reddit coverage job (year/all plus pagination)
  - refresh shortlist for next 10-14 days

## Non-negotiables

- Never weaken truth checks to increase volume.
- Broaden scan coverage before lowering quality gates.
- Keep `source_unsupported` rejection in place.
- Keep anti-repost checks as is (`posted.jsonl`, `reels.jsonl`).

## Quick command checklist (local)

```bash
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 scripts/discover_facts.py
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 scripts/check_reel_runway.py
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 scripts/restock.py
```

## Handover note for Claude sessions

When credits are available, ask Claude to:

- run discovery
- inspect reject reasons
- enrich only top verified candidates until runway >= 10 days
- stop enrichment once runway target is reached

