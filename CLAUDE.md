# factjot, agent operating manual

This file owns: hard rules, plan-mode triggers, environment specifics, pointers.
For everything else, read the right file.

| You need... | Read |
|---|---|
| Architecture, lifecycle, shared-module rules, success criteria, invariant principles | `SPEC_FACTJOT_SYSTEM.md` |
| Image sourcing rules, candidate selection, fallbacks, reuse policy | `SPEC_IMAGE_PIPELINE.md` |
| What actually runs in production, workflow roles, gaps | `docs/PIPELINE_OPERATIONS_REFERENCE.md` |
| Recorded failure modes, why something broke last time | `insta-brain/gotchas.md` |
| Required env keys | `.env.example` |
| Deferred / future work | `ROADMAP.md` |

Owner: Toby Johnson (TJCreate), Lincoln UK. Account: @factjot.

---

## 0. Read order at session start

1. `/Users/Music/.claude/CLAUDE.md` (universal voice rules: no em dashes, British English, etc.)
2. This file
3. `SPEC_FACTJOT_SYSTEM.md`
4. The relevant sub-spec for the area being touched (`SPEC_IMAGE_PIPELINE.md` for any image-pipeline change)
5. `insta-brain/gotchas.md`

If this file disagrees with `SPEC_FACTJOT_SYSTEM.md`, this file wins on environment specifics; the SPEC wins on principles. If either disagrees with the brain (`insta-brain/`), the brain wins.

Run `/compact` when context usage hits 60% to avoid hitting limits mid-task.

---

## 1. Hard rules, never break

These are environment-coded duplicates of the principles in `SPEC_FACTJOT_SYSTEM.md` §12. The principle lives there; the implementation rule lives here.

1. **Never force-push to main.** Force-push silently deletes state commits being written by running workflows (caused the 2026-05-05 triple-post incident). Large-history rewrites happen on a separate branch with workflows paused, then merge.
2. **No em dashes anywhere.** Code, copy, YAML comments. GitHub's Go YAML parser rejects them and silently breaks dispatch (422 "no workflow_dispatch trigger"). Use hyphens, commas, full stops, parentheses, or rewrite.
3. **British English** throughout copy, captions, comments.
4. **Image-pipeline changes require plan mode.** Any change to `image_sourcer.py`, `image_fetcher.py`, manual carousel rendering, provider order, or candidate scoring begins in plan mode. Plan must list files touched, functions touched, expected behaviour, acceptance tests, rollback path. See `SPEC_IMAGE_PIPELINE.md`.
5. **No empty image boxes.** A carousel slide either shows a real image or uses the intentional typography-only layout. Never a blank rectangle, near-invisible placeholder, or trust-the-renderer empty string. Verify in rendered output, not in unit tests.
6. **Visual success is success.** Tests passing is not enough. Open the rendered artefact (slides, MP4, thumbnail, story) and judge it. See `SPEC_FACTJOT_SYSTEM.md` §10.3, §13.
7. **Reel transitions are hardwired.** `case_file_dynamic` is the only transition mode (hardcoded in `src/render/reel_composer.py`). Do not add env flags, classic fallbacks, or feature toggles. The legacy `REEL_TRANSITIONS_MODE` env var is gone.
8. **Append-only ledgers.** One named exception: `data/ledgers/reel_performance.jsonl` is mutable, fully rewritten on each `fetch_reel_metrics.py` run as engagement numbers accumulate. Do not convert it to append-only.
9. **Four brand fonts only.** Instrument Serif, Space Grotesk SemiBold, JetBrains Mono Bold (primaries) plus Archivo Black 900 scoped strictly to short-form video burn-in. No fifth font, no scope creep on Archivo Black.
10. **Canonical Python locally:** `/Library/Frameworks/Python.framework/Versions/Current/bin/python3`. Bare `python3` finds no packages locally. Bare `python3` is only correct inside GitHub Actions.
11. **No repost.** The autonomous agent reads `insta-brain/data/posted.jsonl` and applies a prompt-level duplicate guard rejecting topic, angle, and "same subject framed differently" overlaps. No image reuse across posts (`data/ledgers/used_images.jsonl`). No footage reuse across reels (`data/ledgers/used_footage_urls.jsonl`).
12. **Fix the tool, not the symptom.** A wrong value in a data file means the process that wrote it is broken. Fix the process, then run it to clean up. Patching one bad value guarantees the next one will be wrong too.
13. **Audio must be 48kHz.** Meta rejects 44.1kHz and 96kHz. ElevenLabs returns 44.1kHz by default; always resample before muxing.

---

## 2. Plan mode required when

- Touching image sourcing, fetcher, manual or news rendering, candidate scoring, provider order, or fallback logic (`SPEC_IMAGE_PIPELINE.md`).
- Touching reel footage sourcing or FFmpeg composition.
- Touching cross-pipeline shared code in `src/core/`, `src/render/`, `src/publish/`, `src/verification/`.
- Touching `brand/brand_kit.json` or `src/core/brand.py`. Every renderer is downstream of these files.
- Adding a new pipeline (`SPEC_FACTJOT_SYSTEM.md` §15).

When in doubt, plan mode. Tightly scoped fixes inside one pipeline that do not touch shared safety code do not need it.

---

## 3. Architecture risks, do not edit blindly

**`pipelines/news/ship_news_post.py` has a dual role.** It is both:
1. The deleted news-pipeline's CLI entry point (no scheduled workflow calls it now).
2. The renderer used by the autonomous carousel pipeline. `pipelines/carousel/ship_carousel_post.py` wraps `pipelines/manual/ship_manual_post.py`, which imports these render helpers. Dry-run previews from the manual module currently land in `output/news/...`.

An edit for one purpose can silently affect the other. Inspect both manual and news rendered output before shipping any change here. Tracked in `SPEC_FACTJOT_SYSTEM.md` §10.1; will be untangled in a deliberate split.

---

## 4. Open decisions, do not resolve in passing

- **INK black hex.** This file historically referenced `#0A0A0A`; `SPEC_IMAGE_PIPELINE.md` §12 references `#0B0B0C`. Final value belongs in `brand/brand_kit.json` once the style guide is migrated, owned by future `SPEC_STYLE_GUIDE.md`. Do not unilaterally normalise either value.

---

## 5. What this project is

Fully automated Instagram account (@factjot). Scheduled evergreen slots run via `autonomous-reel.yml` on GitHub-hosted cron, and breaking news runs via `news-watcher.yml` when Guardian watcher criteria are met. The agent (Sonnet 4.6) writes the brief or script and calls one of `run_reel` / `run_carousel`, or `skip` if nothing clears the quality gate. **The Mac does not need to be on.**

| Mode | BST | UTC cron | Format |
|---|---|---|---|
| `reel_morning` | 09:00 | `0 8 * * *`   | Evergreen reel |
| `list`         | 15:30 | `30 14 * * *` | List carousel |
| `reel_evening` | 18:00 | `0 17 * * *`  | Evergreen reel |
| `fact`         | 20:30 | `30 19 * * *` | Fact carousel (single subject) |

Breaking news is unscheduled: `news-watcher.yml` polls Guardian RSS and only triggers `pipelines/news/ship_news_breaking.py` when a qualifying story is found.

Crons are UTC, tracked to BST in summer. UK clocks fall back in October; UTC equals GMT then, so posts fire at the same UK clock time year-round without intervention.

Stack: Python 3.11, Playwright + Chromium, FFmpeg, ElevenLabs, Anthropic Sonnet 4.6 (agent + carousel writer) and Haiku 4.5 (image selection, repair, hashtags, search expansion), Instagram Graph API, YouTube Data API v3, imgbb + tmpfiles.org.

Successful reels cross-post to YouTube as Shorts (same MP4, same caption + `#Shorts`, same custom thumbnail). Channel: `thefactjot@gmail.com`.

Full architecture, lifecycle stages, shared-module rules, ledger discipline, and definition of success live in `SPEC_FACTJOT_SYSTEM.md`. Workflow file roles and production wiring live in `docs/PIPELINE_OPERATIONS_REFERENCE.md`.

---

## 6. Environment specifics

**Project path:** `~/Developer/Insta-bot`. Never `~/Documents/`. iCloud in `Documents` intercepts FFmpeg writes and produces silent 14-min encode hangs. Do not move back into any iCloud-synced folder.

**Local Python:** `/Library/Frameworks/Python.framework/Versions/Current/bin/python3`.

**Output locations** (gitignored, local only): `output/{reel,carousel,list,news,manual,experiments}/YYYY-MM-DD_HH-MM_TOPIC/`. Folders sort chronologically in Finder.

**Env vars:** required keys in `.env.example`. The autonomous workflow pulls them from GitHub secrets at run time.

**Concurrency:** the autonomous workflow uses `concurrency.group: factjot-publish` with `cancel-in-progress: false`. Overlapping triggers queue, they do not cancel.

**FFmpeg fallback:** `src/core/ffmpeg_bin.py` auto-detects `ffmpeg-full` when default Homebrew ffmpeg breaks after libvpx upgrades. No manual `FFMPEG_BIN` needed.

---

## 7. Image pipeline rule, read the spec first

Before touching manual carousel image sourcing, image candidate selection, image provider order, image fallbacks, or manual / news slide rendering, read `SPEC_IMAGE_PIPELINE.md`.

The product goal is not just to avoid wrong images. It is a finished carousel that looks intentional, visually strong, factually accurate, legally usable, and safe to post. A safe but ugly carousel is still a failed carousel.

---

## 8. Common local commands

```bash
cd ~/Developer/Insta-bot
PY=/Library/Frameworks/Python.framework/Versions/Current/bin/python3

# Reel: dry-run first, always
$PY pipelines/reel/make_reel.py --dry-run
$PY pipelines/reel/make_reel.py --topic earth
$PY pipelines/reel/make_reel.py --list-facts

# Manual carousel (current autonomous carousel path)
$PY pipelines/carousel/ship_carousel_post.py --dry-run

# Stop a stuck local reel job
scripts/kill_local_reel_jobs.sh
```

A second concurrent `make_reel.py` exits with code `10` (advisory lock at `data/cache/reels/.make_reel.lock`). If a run was killed and the lock remains, delete it.

Per-run logs: `output/reel/<id>/pipeline.log` and `logs/reel_runs/`. Compose stderr: `ffmpeg_compose_stderr.log`. FFmpeg progress: `ffmpeg_progress.txt`. Filter graph script: `ffmpeg_filter_complex.txt`.

---

## 9. Brand and typography (summary)

Source of truth: `brand/brand_kit.json` (v2.0) consumed via `src/core/brand.py`. Templates do not inline values that exist in the JSON. Full schema and migration plan will live in future `SPEC_STYLE_GUIDE.md`.

| Font | Use |
|---|---|
| Instrument Serif Regular + Italic | Hook titles, wordmark, title cards |
| Space Grotesk SemiBold | Subtitles, body copy |
| JetBrains Mono Bold | Labels, badges, tags |
| Archivo Black 900 | Short-form video burn-in subtitles only, never elsewhere |

Carousel body copy honours the Space Grotesk rule when `layout_mode=readable_list` (used by the list and news slots). The fact slot still renders body in Archivo Black 900 via the `compact_legacy` profile pending a separate font decision; see §10.

Wordmark: `fact[regular] jot[italic] .[red]`. Canonical inline 3-part HTML across every template; the legacy PNG fallback was removed 2026-05-07.

Brand colours: PAPER `#F4F1E9`, INK `#0A0A0A` (open decision, see §4), ACCENT `#E6352A`, LIME `#C8DB45`, LILAC `#C4A9D0`. v2 additions: SKY `#C9D8E2`, AVAILABLE `#80EF80`, surface tokens `dark_bg`, `surface`, `elevated`, brand gradient at 90°.

Shadow: hard drop `2px 2px 0 rgba(0,0,0,0.5)`, no blur.

---

## 10. Carousel layout profiles

Source of truth: `src/content/carousel_rules.py` -> `LAYOUT_PROFILES`.
Two profiles. Pick by `--layout-mode` on `pipelines/carousel/ship_carousel_post.py`, or let the agent's `run_carousel` derive it from `format_type`.

| Profile | Body font | Container | Char cap | Used by |
|---|---|---|---|---|
| `compact_legacy` | Archivo Black 900 (48px / 42px) | anchored bottom-left | 24 hard | fact slot; default for `--type=fact|news` direct CLI |
| `readable_list` | Space Grotesk SemiBold | half-box bottom 50%, JS auto-fit (64 -> 28 px) | 56 hard | list slot and watcher-triggered news |

Routing:
- Agent `run_carousel(format_type=list)` appends `--layout-mode readable_list`. Fact stays default. Reels never read layout_mode.
- Direct CLI without `--layout-mode` defaults to `compact_legacy` for any sub-type.
- compact_legacy is byte-identical to pre-2026-05-08 output. Existing fact carousels render unchanged.

Image scoring under `readable_list` runs `ImageSourcer(relax=True)`: R3 score floor drops 8 -> 6 to admit moderately-confident candidates on item slides where named-subject metadata is weak. compact_legacy callers leave `relax=False`.

## 11. Where things live

- **Pipelines:** `pipelines/{reel,manual,news,carousel,list,shared}/`. Only `reel/make_reel.py` and `carousel/ship_carousel_post.py` are intentional production entry points (autonomous workflow calls them via the agent's `run_reel` / `run_carousel` tools). Other pipeline files are legacy; see `docs/PIPELINE_OPERATIONS_REFERENCE.md` §2.
- **Shared modules:** `src/{core,research,content,verification,render,publish,utils}/`. Responsibilities table in `SPEC_FACTJOT_SYSTEM.md` §7.
- **Workflows:** `.github/workflows/`. Active posting workflows are `autonomous-reel.yml` (scheduled reels/list/fact) and `news-watcher.yml` (breaking news watcher-triggered posts). `test.yml` runs PR pytest, `pages.yml` builds docs.
- **State (git-tracked):** `insta-brain/data/posted.jsonl`, `insta-brain/data/reels.jsonl`, `data/ledgers/used_images.jsonl`, `data/ledgers/used_footage_urls.jsonl`, `data/ledgers/api_usage_costs.jsonl`, `data/ledgers/youtube_uploads.jsonl`, `data/ledgers/reel_performance.jsonl` (mutable). Invariant each ledger guards: `SPEC_FACTJOT_SYSTEM.md` §11.2.
- **Brain:** `insta-brain/`. `gotchas.md` is mandatory reading.
- **Per-run output:** `output/<pipeline>/...` (gitignored, local only).
- **Roadmap:** deferred work in `ROADMAP.md`. Do not implement without explicit go-ahead.

---

## 12. Legacy and dormant code

These exist on disk but no scheduled workflow calls them. Do not re-introduce a scheduled cron without first disabling the autonomous workflow, or double-posting will follow.

- `src/research/rare_fact_bank.py` and `data/ledgers/discovered_facts.jsonl`: dormant. The autonomous reel path provides `--script` directly via the agent and bypasses `_pick_fact()`. The historical rule "facts must come from Reddit only" applied to the deleted Reddit-discovery pipeline; it does not apply to the autonomous flow.
- `pipelines/shared/publish_due.py`, `review_queue.py`, `queue.jsonl`: legacy queue-based publishing. Not used by the autonomous flow.
- `pipelines/carousel/ship_first_post.py`, `pipelines/list/ship_list_post.py`, `pipelines/news/ship_news_post.py` (as a CLI entry point): scheduled workflows are deleted. `ship_news_post.py` is still imported as a renderer by the manual pipeline (see §3).
- `pipelines/reel/discover_reel_facts.py`, `pipelines/reel/runway.py`, `pipelines/carousel/restock.py`, `pipelines/reel/check_reel_runway.py`: discovery / runway helpers tied to the deleted weekly-plan workflow.
- launchd jobs: disabled.
- cron-job.org backup: removed; `CRON_TRIGGER_PAT` is no longer required by any active workflow.

---

## 13. Fix philosophy

Every fix must be a long-term structural fix, not a temporary patch. A patch that suppresses a symptom will reappear elsewhere. Before shipping, ask: does this remove the root cause, or hide it? If it hides it, keep digging.

If you discover a new failure mode, append to `insta-brain/gotchas.md` before closing the session.

---

## 14. Debugging workflow failures

1. Open `github.com/Wonderkid96/factjot` → Actions → failed run → step logs.
2. Common causes:
   - Meta token expired: refresh and update `META_ACCESS_TOKEN` secret.
   - YAML parse error (422 on dispatch): check for em dashes or heredocs.
   - Git push conflict: rebase step.
   - Meta 413 (video too large): the encoder retry chain handles most cases automatically.
3. Do not run scripts locally while a workflow run is in flight. Ledger files race.

---

## 15. Open work

- `ROADMAP.md` tracks deferred phases (currently Phase 8, vision-based frame selector). Do not pick up without explicit instruction.
- TikTok: app submitted for review 2026-05-02; not yet wired into the autonomous workflow.
- Meta System User token: switching from 60-day rolling to permanent requires manual setup in Meta Business Manager.
- Per-run agent decision-note logging: the agent writes a private decision note in its assistant message; the workflow currently only logs subprocess output. Surfacing the model's text content blocks in run logs is open.
