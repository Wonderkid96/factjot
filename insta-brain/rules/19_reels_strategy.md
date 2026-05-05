# Rule 19 — Reels Strategy (LOCKED)

This is the canonical structure for every factjot Reel. The pipeline
(`scripts/make_reel.py`, `src/render/reel_composer.py`,
`src/render/reel_overlay.py`, `src/research/narrative_beats.py`,
`src/research/video_finder.py`) MUST conform. Any change to these
parameters requires updating this file.

## Core principle

**One Reel = one fact arc.** Hook → context → twist → payoff → CTA.
Length 18-28 seconds. Fast enough for retention, long enough for story.

## Practical structure (proven template)

| Window  | Beat                                    |
|---------|-----------------------------------------|
| 0-1.5s  | **Hook** — shocking, specific, concrete |
| 1.5-6s  | **Setup** — who/where/when in one sentence |
| 6-14s   | **Escalation** — 2-3 beats with rising stakes |
| 14-20s  | **Twist** — the "wait, what?" line     |
| 20-26s  | **Meaning + CTA** — why it matters + "Follow for more" |

## Voice + delivery

- British male voice (`en-GB-RyanNeural`), medium energy, NOT robotic.
- Write VO like speech, not article prose: short clauses, contractions,
  rhythmic punctuation.
- Build in micro-pauses every 1-2 lines so it breathes.
- Emphasise ONE keyword per beat — never five.
- Alternate short lines and pause lines. Never machine-gun text.

## Editing rules

- Cut every 1.0-2.2s unless a beat needs a dramatic hold.
- Add motion every beat: zoom, pan, parallax, crop shift, animated text.
- Text animation: simple and intentional. No flashy gimmicks.
- Music supports momentum, never fights narration.
- Light SFX accents only on reveal moments.
- Transition mode defaults to `classic`, with optional `case_file_dynamic`
  for varied joins in the same visual family.
- Animated grit finish is allowed as a subtle texture layer over final video.

## Retention rules

- Front-load novelty in first 2 seconds.
- Tease a missing piece early ("and that's not even the wildest part").
- Avoid full explanation too early.
- On-screen text MUST be readable in silent mode.
- End with a loop-friendly final line that echoes the hook.

## Production workflow

1. Pick only high-storyability facts (clear character, stakes, twist).
2. Script first → VO timing → visuals to the waveform.
3. Auto-generate shot list per sentence beat (`narrative_beats.shot_list`).
4. One visual QA pass: relevance, legibility, pacing.
5. Track per Reel: 3-second hold, average watch time, completion, shares, saves.

## Hard constants and runtime toggles in code

These constants/toggles in `src/render/reel_composer.py` MUST align with the spec:

```python
TARGET_DURATION_S = (18, 28)       # min, max total length
TARGET_CLIP_LEN_S = 1.8            # cut every ~1.8s (within 1.0-2.2s band)
HOOK_WINDOW_S    = (0.0, 1.5)
SETUP_WINDOW_S   = (1.5, 6.0)
ESCALATION_S     = (6.0, 14.0)
TWIST_S          = (14.0, 20.0)
CTA_S            = (20.0, 26.0)
KEN_BURNS_ZOOM   = 0.18            # 18% zoom across each clip
DEFAULT_VOICE    = "en-GB-RyanNeural"
REEL_TRANSITIONS_MODE = "classic|case_file_dynamic"   # env toggle (default classic)
REEL_TEXTURE_FINISH = "on|off"                        # env toggle (default on)
REEL_TEXTURE_INTENSITY = "low|medium"                 # env toggle (default low)
REEL_GRIT_OVERLAY_PATH = "/abs/path/to/animated.mov"  # env override
REEL_HOOK_OPTIMISER = "off|on"                        # env toggle (default off)
REEL_PACING_PROFILE = "classic|dynamic_lite"          # env toggle (default classic)
REEL_CLIP_MIN_CONF_SCORE = 0.45                       # low-confidence clip filter
```

## Compose template requirement

- FFmpeg compose must write a filter graph template file per run:
  `data/cache/reels/<reel_id>/ffmpeg_filter_complex.txt`
- FFmpeg must execute via `-filter_complex_script` for maintainability.
- Keep classic path and fallback behaviour available for reliability.

## Usage and cost tracking

- Each reel run must append usage metadata to:
  `data/ledgers/api_usage_costs.jsonl`
- Minimum logged fields: reel id, topic, TTS backend, TTS characters,
  duration, transitions mode, texture mode, estimated TTS cost.
- Hook optimiser runs must append candidate/winner metadata to:
  `data/ledgers/hook_optimiser.jsonl`
- Reel generation runs should append generation features to:
  `data/ledgers/reel_generation_features.jsonl`
  (hook mode, pacing mode, subtitle chunk count, footage confidence summary).

## Verification checklist (before enabling by default)

1. Run dry-run with defaults and confirm no behaviour change.
2. Run dry-run with `REEL_HOOK_OPTIMISER=on` and verify hook ledger appends.
3. Run dry-run with `REEL_PACING_PROFILE=dynamic_lite` and verify subtitle readability.
4. Confirm low-confidence filter does not cause frequent underfilled clip sets.
5. Keep classic fallback path available at all times.

## What still needs building (open spec items)

These are TBD pieces called out by the strategy:

- **Script formatter** (`src/content/reel_script.py`) — converts raw bank claim
  into speech-friendly VO with explicit micro-pause markers (commas, em
  dashes, line breaks) and one clear keyword emphasis per beat.
- **Storyability scorer** (`src/research/storyability.py`) — rates each
  `quirky_score=3` fact on (character, stakes, twist, visual concreteness)
  to predict Reel performance before we produce.
- **Per-Reel metrics ledger** (`insta-brain/data/reels.jsonl` extended) —
  3s hold, avg watch time, completion %, shares, saves, polled from IG
  Insights API daily and stitched onto each reel record.
