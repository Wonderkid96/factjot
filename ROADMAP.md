# factjot ROADMAP

Deferred work, not active. **Do not implement any item below without explicit go-ahead from Toby.** Active work lives in `CLAUDE.md`, `SPEC_FACTJOT_SYSTEM.md`, and the audit decision log.

## Phase 8 - Vision frame selector

Logged in `CLAUDE.md` §15. Future improvement: a vision model picks the best thumbnail and best per-clip frame from a pre-filtered shortlist, replacing the current `footage_clips[0]` heuristic at `pipelines/reel/make_reel.py:961-993`. Goes deeper than the audit-2026-05-09 Q6 decision (Haiku-pick from 3 candidates with brand overlay) by extracting frames across every footage clip and ranking the entire pool, not just three pre-rendered candidates.

**Status:** deferred until per-frame quality is proven the bottleneck. The Q6 implementation is the cheap version; Phase 8 is the bigger lift that may not earn back its cost until reach is materially higher.

**Trigger to revisit:** when the Q6 thumbnail-pick has been live for at least 50 reels and the performance ledger shows a stable plateau, or when `data/ledgers/reel_performance.jsonl` indicates that thumbnail click-through is the limiting factor.

## Audit-2026-05-09 deferred work

The full deferred queue from the multi-agent audit lives in user memory at:

`/Users/Music/.claude/projects/-Users-Music-Developer-Insta-bot/memory/project_deferred_work_post_audit.md`

Items currently parked there:

1. **Monthly human-in-the-loop performance review.** Read `data/ledgers/reel_performance.jsonl` top 3 / bottom 3 by reach and saves; update agent prompt manually based on observed patterns. Trigger: when 4 weeks have passed since the audit changes ship.
2. **Mid-weight Haiku performance reports.** Structured logging of hook attributes plus monthly Haiku-generated analysis. Trigger: when the performance ledger reaches 100 rows post-audit-ship.
3. **Full auto-tuning loop.** Declined. Goodhart's Law plus brand erosion makes this a net negative.
4. **Carousel metrics ledger.** Carousel and list equivalent of `reel_performance.jsonl`. Required before "should we drop carousels entirely" can be answered with data. Ship after the Q1 fact verification gate.

## Other longer-tail audit items

These are tracked as P2 in the audit synthesis and are not yet locked into a phase:

- TMDB-style confidence gating on the carousel image side (currently reels-only).
- Voice rules centralisation: agent prompt and writer prompt currently duplicate the banned-phrase list. Move to a shared `src/content/voice.py`.
- Smoke tests on `src/render/reel_composer.py`, `src/publish/instagram_publisher.py`, `src/publish/image_host.py`. The most catastrophic-failure surfaces are the least tested.
- Brain and `gotchas.md` reconciliation. Significant rewrite job; deserves its own session.
- Backfill `slot` field on `data/ledgers/reel_performance.jsonl` so the deferred monthly review can analyse "which slot performs best".
