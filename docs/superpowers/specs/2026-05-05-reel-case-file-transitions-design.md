# Reel Case-File Transition Design

Date: 2026-05-05
Status: Draft approved in chat, pending final user review
Owner: Reel pipeline (`scripts/make_reel.py`, `src/render/reel_composer.py`)

## Goal

Improve reel watch experience by making clip edits feel more dynamic and less repetitive while preserving stability.

Primary style target:

- Unique output per reel
- Consistent "case file / projector slide" visual language
- Dynamic but not messy

## Scope

In scope:

- Introduce one transition template family (`case_file_dynamic`) with bounded random variation
- Add narration-aware placement of transition joins
- Add subtle finishing texture layer (grit + weave) as final visual treatment
- Keep compatibility and fail-safe behavior for publish pipeline

Out of scope:

- Re-architecting footage retrieval
- Reworking subtitle renderer, TTS, upload/publish APIs
- Multi-template transition engine in this phase

## Current-State Summary

`src/render/reel_composer.py` currently:

- Pre-processes clips (scale/crop/pan)
- Joins clips primarily via concat (hard cuts)
- Applies overlays, intro alpha overlay, fade-to-black, audio chain

This is stable but perceived as visually predictable.

## Proposed Architecture

### 1) Transition Mode Flag

Add runtime mode selection:

- `REEL_TRANSITIONS_MODE=classic|case_file_dynamic`
- Default: `classic` (non-breaking rollout)

Behavior:

- `classic`: existing concat join path unchanged
- `case_file_dynamic`: new join-builder path used for visual transitions

### 2) Transition Template (Single Family, Dynamic Components)

Template name: `case_file_pivot`

Visual behavior:

- Outgoing clip pivots around a lower anchor point
- Incoming clip enters with short overlap, optionally on top for "paper toss" feel
- Motion settles quickly to keep readability for subtitles

Dynamic parameters (bounded):

- `pivot_side`: `left` or `right`
- `pivot_y_ratio`: `0.72-0.88`
- `rotate_deg`: `6-14`
- `overlap_s`: `0.16-0.32`
- `layer_order`: mostly incoming-under, occasional incoming-over
- `speed_curve`: mostly ease-out, occasional ease-in-out

Rules:

- Use transition on a subset of joins (target 40-60%)
- Keep remaining joins as clean cuts for pacing balance
- Avoid same variant back-to-back

### 3) Deterministic Randomization

Use seeded RNG for reproducibility:

- Seed source: `reel_id` (or deterministic derivative)
- Ensures each reel feels unique while reruns remain stable/debuggable

### 4) Narration-Aware Placement

Transition selection should favor joins near chunk/beat boundaries:

- Prefer transitions where subtitle chunk boundary is nearby
- Avoid high-motion transition at readability-critical moments (dense subtitle windows)

Fallback:

- If beat metadata is unavailable, use deterministic spacing over joins

### 5) Subtle Texture Finish (Final Visual Pass)

Add final texture blend stage after transitions/overlays and before final fade output mapping.

Assets (animated, loopable):

- Grit/grain default source provided by user:
  - `/Users/Music/Downloads/film-grain-and-scratches-overlay-on-black-backgrou-2025-12-17-07-15-10-utc (2).mov`
  - Blend intent: `screen` mode behavior over reel image
- Weave layer source: pending user-provided animated loop

Controls:

- `REEL_TEXTURE_FINISH=on|off` (default `on`)
- `REEL_TEXTURE_INTENSITY=low|medium` (default `low`)

Target intensity:

- Grain opacity ~4-8%
- Weave opacity ~3-6%

Quality constraints:

- Must remain subtle; no readability loss on subtitles or CTA
- Disable/adapt automatically if sizing/encode constraints are threatened
- Texture inputs must be animated loops (no static texture frames)

## Safety and Non-Breaking Guarantees

1. Keep existing pipeline behavior untouched when mode is `classic`.
2. Isolate new logic in dedicated helper module (proposed: `src/render/reel_transitions.py`).
3. Preserve existing output constraints:
  - 1080x1920
  - 30fps
  - yuv420p
  - existing audio chain and duration gates
4. Validate generated graph values before ffmpeg execution:
  - no negative times
  - bounded overlap
  - valid stream label chaining
5. Auto-fallback:
  - any transition-graph build failure logs warning and falls back to classic concat

## Rollout Plan

Phase 1:

- Ship code path behind flags, defaulting to `classic`
- Dry-run local validation + one CI reel generation test run

Phase 2:

- Enable `case_file_dynamic` with `REEL_TEXTURE_INTENSITY=low` in controlled runs
- Compare watch quality manually on several generated reels

Phase 3:

- Promote `case_file_dynamic` default if stable
- Keep `classic` escape hatch for immediate rollback

## Verification Plan

Functional checks:

- Reel composes successfully in both modes
- No regressions in upload/publish flow
- Existing duration and minimum length gates still enforced

Visual checks:

- Case-file transitions present and subtle
- Variation across reels without style drift
- Subtitles remain readable during transitions and texture pass

Technical checks:

- ffmpeg command/filter graph validation passes
- Output file remains within publish constraints or existing two-pass handling
- No increase in failure rate from ffmpeg graph errors

## Risks and Mitigations

Risk: Complex filter graph introduces instability.
Mitigation: Single template family, bounded parameters, strict fallback to classic.

Risk: Texture layer harms clarity.
Mitigation: default `low` intensity, readability checks, toggle off via env.

Risk: Render time increases significantly.
Mitigation: high-quality mode accepted by user; keep overlap durations short and effects minimal.

## Open Decisions

None blocking for implementation planning.
Current defaults locked:

- Transition mode target: `case_file_dynamic` (flagged rollout)
- Texture intensity default: `low`
- Style objective: unique outputs, consistent family look