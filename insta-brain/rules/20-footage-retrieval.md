# Rule 20 — Footage Retrieval Architecture

Related: [[rules/19_reels_strategy]] · [[gotchas]] · [[MEMORY_INDEX]]

## Current architecture (as of 2026-05-05)

Four-tier waterfall inside `src/research/video_finder.py`:

```
Tier 0: Entity tier          — named entity from claim → Wikimedia Commons (max 2 clips)
Tier 1: Narrative beats      — shot_list() from narrative_beats.py → all sources
Tier 2: Last-resort keywords — _extract_hint_keywords() → Wikimedia only
Tier 3: Safety pool          — pre-downloaded generic clips by topic
```

`narrative_beats.py` is **pure regex + hardcoded templates**. No LLM. Fast,
deterministic, but brittle. It produces one query string per beat (e.g.
"octopus close up portrait") from topic-specific templates filled with
extracted entities.

**The gap:** queries are keyword-driven (what describes this beat?) not
intent-driven (what footage expresses this beat visually?). A query like
"octopus close up portrait" is technically correct but cinematically vague.
Pexels returns whatever matches the words, not what serves the scene.

---

## Recall-first retrieval upgrade

**Built 2026-05-05.**

### New module: `src/research/visual_intents.py`

One Claude Haiku call per reel before footage search. Generates 9 visually
grounded search queries per beat for all 5 beats (45 queries total). Falls
back to regex expansion silently if Claude unavailable.

**Design:**
- Input: claim + topic + image_hint + reel_script (first 600 chars)
- Output: JSON object with 5 keys (ESTABLISHING/SUBJECT/DETAIL/CONSEQUENCE/ATMOSPHERE), each an array of 9 queries
- Model: `claude-haiku-4-5-20251001`
- Fallback: regex expansion from shot_list() + _expand_hint() + _TOPIC_GENERIC

**Query format (what Claude must produce):**
Good: `"octopus tentacles coral reef macro slow motion"`
Bad: `"marine biology intelligence"` (abstract, not visual)

**Scoring:** positional. queries[0] = 0.88, decays 0.08/step, floor 0.25.
Entity tier clips always 1.0.

### Changes to `video_finder.py`

`find_videos()` gets optional `reel_script: str = ""` param. New:

- `_Candidate` dataclass: `(path, score, beat_idx)`
- `_collect_beat_candidates()`: tries all queries for one beat, collects up
  to 3 candidates, scores by position, returns sorted by score desc
- Updated `find_videos()`: two-pass fill after entity tier:
  - Pass 1: one best clip per beat (beat diversity)
  - Pass 2: remaining candidates sorted by score (promotion before safety pool)
  - Pass 3: safety pool only if still underfilled

Last-resort keyword decomposition tier **removed** (replaced by richer beat queries).

### Changes to `make_reel.py`

Added `reel_script=vo_script` to the `find_videos()` call. `vo_script` is
available at this point because TTS synthesis runs before footage search.

### `narrative_beats.py`

Unchanged. Used as fallback inside `_regex_fallback()` in `visual_intents.py`.

---

## What was deliberately NOT built

These were considered and rejected:

| Idea | Why rejected |
|---|---|
| CLIP embeddings for clip scoring | Requires vision model per clip. Fixes ranking, not retrieval. The core problem is wrong queries, not wrong ranking. |
| Coherence validator post-selection | Computationally wasteful. Would reject clips from an already-weak pool. Fix the pool first. |
| Visual memory bank | Premature. Needs stable retrieval quality + consistent tagging before it adds signal. |
| Scene coverage planning | Already approximated by entity cap (max 2) + beat ordering. Not worth formalising. |
| Full "scene graph" architecture | Overengineering for a 4-5 clip reel. The query expressiveness problem is narrow; the solution should be too. |

---

## Known remaining weaknesses (post-upgrade)

Even with the intent layer, these cases will still struggle:

- **Entity with no Wikimedia presence**: niche science facts, recent events.
  The entity tier returns nothing and intents must carry the load alone.
- **Highly abstract topics** (blindsight, quantum effects): stock footage is
  inherently generic. No query improves on "scientist in lab".
- **Very niche named places**: Darvaza, Zealandia -- better with this upgrade,
  but fallback_queries are still guesses if the specific footage doesn't exist
  on Pexels/Pixabay.

For facts where visuals are critical and generic: set `allow_archival=True`
in the fact definition. Archive.org has real historical footage that stock
sites don't.

---

## File map

| File | Role |
|---|---|
| `src/research/visual_intents.py` | NEW — VisualIntent dataclass + shot_intents() Claude call |
| `src/research/narrative_beats.py` | UNCHANGED — regex fallback, used inside shot_intents() |
| `src/research/video_finder.py` | MODIFIED — accept intents param, _try_queries(), negative filter |
| `scripts/make_reel.py` | MODIFIED — call shot_intents(), pass to find_videos() |
