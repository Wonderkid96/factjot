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
2. **Em dashes in YAML only.** Strip em dashes from `.yml`/`.yaml` files only — GitHub's Go YAML parser silently rejects them and breaks `workflow_dispatch` (422 "no workflow_dispatch trigger"). Em dashes are fine everywhere else: scripts, captions, templates, Python strings. The subtitle chunker treats `—` as a phrase-break signal, so using them in reel scripts actively improves subtitle timing.
3. **British English** throughout copy, captions, comments.
4. **Image-pipeline changes require plan mode.** Any change to `image_sourcer.py`, `image_fetcher.py`, manual carousel rendering, provider order, or candidate scoring begins in plan mode. Plan must list files touched, functions touched, expected behaviour, acceptance tests, rollback path. See `SPEC_IMAGE_PIPELINE.md`.
5. **No empty image boxes.** A carousel slide either shows a real image or uses the intentional typography-only layout. Never a blank rectangle, near-invisible placeholder, or trust-the-renderer empty string. Verify in rendered output, not in unit tests.
6. **Visual success is success.** Tests passing is not enough. Open the rendered artefact (slides, MP4, thumbnail, story) and judge it. See `SPEC_FACTJOT_SYSTEM.md` §10.3, §13.
7. **Reel transitions are hardwired.** `case_file_dynamic` is the only transition mode (hardcoded in `src/render/reel_composer.py`). Do not add env flags, classic fallbacks, or feature toggles. The legacy `REEL_TRANSITIONS_MODE` env var is gone.
8. **Append-only ledgers.** One named exception: `data/ledgers/reel_performance.jsonl` is mutable, fully rewritten on each `fetch_reel_metrics.py` run as engagement numbers accumulate. Do not convert it to append-only.
9. **Font hierarchy.** Four families, weights documented in `brand/brand_kit.json` v2.1: Archivo (Black 900 hook/thumbnail/story cards + Black 900 kinetic subtitles); Instrument Serif (Regular + Italic for headlines, wordmark, carousel titles); Space Grotesk (SemiBold for carousel body in readable_list profile + Bold 700 for labels/kickers/chips/metadata, replaces JetBrains Mono Bold); JetBrains Mono retained on disk for backwards compatibility but no template references it. Any new label/kicker/chip rule using Space Grotesk Bold 700 must apply `text-transform: uppercase` + `letter-spacing: 0.06em-0.1em` to preserve the data-tag affordance lost by dropping monospace.
10. **Canonical Python locally:** `/Library/Frameworks/Python.framework/Versions/Current/bin/python3`. Bare `python3` finds no packages locally. Bare `python3` is only correct inside GitHub Actions.
11. **No repost.** The autonomous agent reads `insta-brain/data/posted.jsonl` and applies a prompt-level duplicate guard rejecting topic, angle, and "same subject framed differently" overlaps. No image reuse across posts (`data/ledgers/used_images.jsonl`). No footage reuse across reels (`data/ledgers/used_footage_urls.jsonl`).
12. **Fix the tool, not the symptom.** A wrong value in a data file means the process that wrote it is broken. Fix the process, then run it to clean up. Patching one bad value guarantees the next one will be wrong too.
13. **Audio must be 48kHz.** Meta rejects 44.1kHz and 96kHz. ElevenLabs returns 44.1kHz by default; always resample before muxing.
14. **Film/TV TMDB artwork is confidence-gated.** Reel TMDB poster/backdrop seeding is additive only. If title match confidence is weak (or year check fails when provided), reject the TMDB match and continue with normal footage fallback.

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

**Carousel renderer ownership (resolved 2026-05-11, Phase K.4).**
Cover, content, and story-frame renderers live in
`src/render/carousel_slides.py`. They are imported by
`pipelines/manual/ship_manual_post.py` (the autonomous carousel path)
and the regression tests in `tests/test_typography_cover.py` and
`tests/test_carousel_slides_byte_stable.py`. The previous dual-role
module `pipelines/news/ship_news_post.py` was deleted along with the
empty `pipelines/news/` package.

Dry-run carousel previews still land in `output/news/...` because
that path is hardcoded in `src/core/paths.py` (`NEWS_RENDERS`).
Renaming the path is a separate cleanup; the renderer ownership
question is settled.

---

## 4. Open decisions, do not resolve in passing

- **INK black hex.** This file historically referenced `#0A0A0A`; `SPEC_IMAGE_PIPELINE.md` §12 references `#0B0B0C`. Final value belongs in `brand/brand_kit.json` once the style guide is migrated, owned by future `SPEC_STYLE_GUIDE.md`. Do not unilaterally normalise either value.

---

## 5. What this project is

Fully automated Instagram account (@factjot). Scheduled evergreen slots run via `autonomous-reel.yml` on GitHub-hosted cron. The agent (Sonnet 4.6) writes the brief or script and calls one of `run_reel` / `run_carousel`, or `skip` if nothing clears the quality gate. **The Mac does not need to be on.**

| Mode | BST | UTC cron | Format |
|---|---|---|---|
| `reel_morning`   | 09:00 | `0 8 * * *`    | Evergreen reel |
| `list_midday`    | ~12:00 | `30 11 * * *`  | List carousel |

(Cut from 5 slots to 3 on 2026-05-10, then to 2 slots on 2026-05-19: 1 reel + 1 list per day.)

The breaking-news pipeline was killed in audit Phase G.2 (decision B). `news-watcher.yml`, `pipelines/news/ship_news_breaking.py`, and `pipelines/news/check_guardian_rss.py` are gone. The dual-role `ship_news_post.py` module was retired in Phase K.4 (2026-05-11): renderer primitives moved to `src/render/carousel_slides.py`; the news CLI helpers (which had no live caller) were deleted with the rest of the file. The whole `pipelines/news/` package is gone.

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

**Feature toggles (optional, default on, fail-open):** two model-judged interestingness gates added 2026-06-14, both Haiku, both unset in GitHub secrets so they run by default. `STORY_RERANK=off` disables the candidate re-rank (`src/research/interestingness_ranker.py`, wired into `story_scout.ranked_candidates_for_mode`): it reorders the top heuristic story candidates by weird-bit density before the agent sees them. `WEIRD_BIT_GATE=off` disables the pre-publish backstop (`src/verification/weird_bit_gate.py`, wired into the `run_reel` handler): it rejects a structurally-valid but boring script via the existing `reel_copy_quality_failed` retry path. Both fail open: if Haiku cannot run, posting proceeds on the structural gate alone.

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

# Reel: dry-run first, always. --script + --title are required.
$PY pipelines/reel/make_reel.py --script "..." --title "..." --topic earth --dry-run

# Manual carousel (current autonomous carousel path)
$PY pipelines/carousel/ship_carousel_post.py --dry-run
$PY pipelines/carousel/ship_carousel_post.py --type list --brief "..." --dry-run --smoke-mode

# Manual reel (script/title driven)
$PY pipelines/reel/make_reel.py --script "..." --title "..." --topic science --tone-override curious --dry-run

# Stop a stuck local reel job
scripts/kill_local_reel_jobs.sh
```

A second concurrent `make_reel.py` exits with code `10` (advisory lock at `data/cache/reels/.make_reel.lock`). If a run was killed and the lock remains, delete it.

Per-run logs: `output/reel/<id>/pipeline.log` and `logs/reel_runs/`. Compose stderr: `ffmpeg_compose_stderr.log`. FFmpeg progress: `ffmpeg_progress.txt`. Filter graph script: `ffmpeg_filter_complex.txt`.

---

## 9. Brand and typography (summary)

Source of truth: `brand/brand_kit.json` (v2.1) consumed via `src/core/brand.py`. Templates do not inline values that exist in the JSON. Full schema and migration plan will live in future `SPEC_STYLE_GUIDE.md`.

| Font | Use |
|---|---|
| Instrument Serif Regular + Italic | Hook titles, wordmark, title cards |
| Space Grotesk SemiBold | Carousel body copy (readable_list profile) |
| Space Grotesk Bold 700 | Labels, kickers, chips, metadata, score badges, item indexes, source attributions |
| Archivo Black 900 | Hook cards, intro/title cards, thumbnails, story cards |
| Archivo Bold 700 | Kinetic reel subtitles (replaces Space Grotesk Medium 500) |

JetBrains Mono Bold removed from active brand system as of 2026-05-10. Files retained on disk for any external consumer; no template imports them.

Carousel body copy honours the Space Grotesk SemiBold rule when `layout_mode=readable_list` (used by the list slot, and available for news when explicitly selected). The fact slot still renders body in Archivo Black 900 via the `compact_legacy` profile pending a separate font decision; see §10.

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
| `readable_list` | Space Grotesk SemiBold | half-box bottom 50%, JS auto-fit (64 -> 28 px) | 56 hard | list slot; optional for news when explicitly selected |

Routing:
- Agent `run_carousel(format_type=list)` appends `--layout-mode readable_list`. Fact stays default. Reels never read layout_mode.
- Direct CLI without `--layout-mode` defaults to `compact_legacy` for any sub-type.
- compact_legacy is byte-identical to pre-2026-05-08 output. Existing fact carousels render unchanged.

Image scoring under `readable_list` runs `ImageSourcer(relax=True)`: R3 score floor drops 8 -> 6 to admit moderately-confident candidates on item slides where named-subject metadata is weak. compact_legacy callers leave `relax=False`.

## 11. Where things live

- **Pipelines:** `pipelines/{reel,manual,news,carousel,list,shared}/`. Only `reel/make_reel.py` and `carousel/ship_carousel_post.py` are intentional production entry points (autonomous workflow calls them via the agent's `run_reel` / `run_carousel` tools). Other pipeline files are legacy; see `docs/PIPELINE_OPERATIONS_REFERENCE.md` §2.
- **Shared modules:** `src/{core,research,content,verification,render,publish,utils}/`. Responsibilities table in `SPEC_FACTJOT_SYSTEM.md` §7.
- **Workflows:** `.github/workflows/`. Active posting workflows are `autonomous-reel.yml` (scheduled three-slot reel/list/reel sequence) and `manual-run.yml` (workflow_dispatch prompt-driven manual reel/carousel runs). `test.yml` runs PR pytest, `pages.yml` builds docs.
- **State (git-tracked):** `insta-brain/data/posted.jsonl`, `insta-brain/data/reels.jsonl`, `data/ledgers/used_images.jsonl`, `data/ledgers/used_footage_urls.jsonl`, `data/ledgers/api_usage_costs.jsonl`, `data/ledgers/youtube_uploads.jsonl`, `data/ledgers/reel_performance.jsonl` (mutable). Invariant each ledger guards: `SPEC_FACTJOT_SYSTEM.md` §11.2.
- **Brain:** `insta-brain/`. `gotchas.md` is mandatory reading.
- **Per-run output:** `output/<pipeline>/...` (gitignored, local only).
- **Roadmap:** deferred work in `ROADMAP.md`. Do not implement without explicit go-ahead.

---

## 12. Legacy and dormant code

The audit-2026-05-09 Phase G cleanup deleted the obviously-dormant scripts. What remains here is a short list of dual-role files and lingering helpers that survived the sweep, plus the deleted infrastructure.

- `pipelines/shared/publish_due.py`, `review_queue.py`, `queue.jsonl`: legacy queue-based publishing. Not used by the autonomous flow.
- launchd jobs: disabled.
- cron-job.org backup: removed; `CRON_TRIGGER_PAT` is no longer required by any active workflow.

Deleted in Phase G.1 (rare_fact_bank retire):
- `src/research/rare_fact_bank.py`, `pipelines/reel/validate_reel_facts.py`. The legacy `_pick_fact()` selection path in `make_reel.py` was removed; `--script` is now mandatory. The autonomous reel path always supplies it via `run_reel`. The `data/ledgers/discovered_facts.jsonl` ledger was archived to `Brain/raw/archive/relevance/`.

Deleted in Phase G.2 (news pipeline kill):
- `.github/workflows/news-watcher.yml`, `pipelines/news/ship_news_breaking.py`, `pipelines/news/check_guardian_rss.py`. The `data/ledgers/news_posts.jsonl` ledger was archived to `Brain/raw/archive/relevance/`.

Deleted in Phase G.3 (dormant code sweep):
- `pipelines/shared/publish_now.py`, `pipelines/shared/plan_week.py`, `pipelines/list/ship_list_post.py`, `pipelines/list/generate_list_packs.py`, `pipelines/list/prepare_packs.py`, `pipelines/list/verify_pack_ids.py`, `pipelines/carousel/ship_first_post.py`, `pipelines/carousel/restock.py`, `pipelines/carousel/discover_facts.py`, `pipelines/reel/discover_reel_facts.py`, `pipelines/reel/runway.py`, `pipelines/reel/check_reel_runway.py`.

Deleted in Phase J (2026-05-11 cleanup, post audit /debatemax 001 follow-up):
- `src/research/fact_discovery.py`, `pipelines/carousel/smoke_render.py`. Both were orphans flagged in Phase G but left behind. Now removed.

Deleted in Phase K (2026-05-11 structural fixes):
- `pipelines/news/ship_news_post.py` and the empty `pipelines/news/` package. Renderer primitives moved to `src/render/carousel_slides.py`; the news-CLI helpers (`build_caption`, `_log_posted`, `main`, etc.) had no live caller and went with the file.

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

## 15. ECC harness rules

The machine runs the `everything-claude-code` plugin. Standard rules apply:

- **Use ECC tools when the task fits.** Python review → `python-reviewer` or `/ecc:code-review`. Planning → `planner` or `/ecc:plan`. TDD → `tdd-guide`. Build/test fails → `*-build-resolver` agents (none match Python directly; use `/ecc:build-fix`). Library docs (Anthropic SDK, Playwright, etc.) → `documentation-lookup` (Context7). Non-trivial decisions → `/debate` or `/debatemax`. Name the tool in chat before invoking.
- **Brain authority wins over ECC stores.** Do not write Toby-specific facts (identity, clients, rates, voice rules, finances) to ECC's MCP memory graph (`mcp__plugin_everything-claude-code_memory__*`) or promote them via `/ecc:promote` / `/ecc:learn`. Generic factjot pipeline patterns are fine. Brain path: `/Users/Music/Developer/Mind/Brain/`.
- Voice/brand profile lives in `Brain/wiki/freelance/voice.md` and `brand.md`. Point `brand-voice` / `article-writing` at those, never at a parallel store.

---

## 16. External credentials — maintenance and recovery

These credentials are not in the repo. When they expire they fail silently (workflow steps use `continue-on-error: true`) and the affected feature stops working with no visible error. Check `data/ledgers/youtube_uploads.jsonl` — if the last entry is more than a couple of days old but reels are posting normally, a credential has expired.

### YouTube OAuth (YOUTUBE_REFRESH_TOKEN)

**What it does:** cross-posts every reel to YouTube Shorts immediately after the IG publish.

**Why it breaks:** Google OAuth refresh tokens can be revoked if the Google account password changes, if Google detects suspicious activity, or if too many tokens are issued for the same app. Error signature in GitHub Actions logs:
```
google.auth.exceptions.RefreshError: invalid_grant: Token has been expired or revoked.
```

**How to diagnose:** compare the last timestamp in `data/ledgers/youtube_uploads.jsonl` against `insta-brain/data/reels.jsonl`. If reels are posting but YouTube uploads have stopped, the token is expired.

**Client secret JSON (local machine — do not delete or move):**
```
/Users/Music/Downloads/client_secret_85373199140-c9eiddkt48uilabk02b5agnfa4hefc9p.apps.googleusercontent.com.json
```
This is the Google Cloud OAuth 2.0 desktop-app credential for the factjot YouTube uploader. GCP project: `factjot-youtube`, owned by `thefactjot@gmail.com`. If it disappears, regenerate from Google Cloud Console (factjot-youtube project → APIs and Services → Credentials) signed in as `thefactjot@gmail.com`.

**Auth re-run command (must use absolute paths — run from anywhere):**
```bash
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
  /Users/Music/Developer/Insta-bot/scripts/setup_youtube_auth.py \
  "/Users/Music/Downloads/client_secret_85373199140-c9eiddkt48uilabk02b5agnfa4hefc9p.apps.googleusercontent.com.json"
```
The script opens a browser. Sign in as `thefactjot@gmail.com`. If shown "This app isn't verified", click Advanced → Go to factjot-uploader (unsafe) → Allow. The script prints three `gh secret set` commands — run all three.

**GitHub secrets to update:**
```bash
echo '<YOUTUBE_CLIENT_ID>'     | gh secret set YOUTUBE_CLIENT_ID     --repo Wonderkid96/factjot
echo '<YOUTUBE_CLIENT_SECRET>' | gh secret set YOUTUBE_CLIENT_SECRET --repo Wonderkid96/factjot
echo '<YOUTUBE_REFRESH_TOKEN>' | gh secret set YOUTUBE_REFRESH_TOKEN --repo Wonderkid96/factjot
```

**Workflow location:** `.github/workflows/autonomous-reel.yml` lines 171-183. Fires after every `reel_morning` run (the only reel slot as of 2026-05-19). Uses `continue-on-error: true` — failures are intentionally silent because YouTube is secondary. That silence is exactly why a broken token is hard to spot; always diagnose by ledger comparison, not by workflow status.

**Verification after fix:** trigger a manual `reel_morning` dispatch. Check `data/ledgers/youtube_uploads.jsonl` in the next state commit.

### Meta access token (META_ACCESS_TOKEN)

Expires every 60 days. `pipelines/shared/refresh_token.py` extends it automatically on every workflow run. If it returns "API access blocked", wait 30 minutes and retry. If still blocked, regenerate from developers.facebook.com under the factjot app.

### ElevenLabs API key (ELEVENLABS_API_KEY)

No expiry, but has a monthly quota. If TTS fails with 429, the monthly quota is exhausted. Edge TTS is the auto-fallback. Locked voice ID: `onwK4e9ZLuTAKqWW03F9` (alias "daniel"). Lives in `ELEVENLABS_VOICE` secret and local `.env`.

---

## 17. Open work

- `ROADMAP.md` tracks deferred phases (currently Phase 8, vision-based frame selector). Do not pick up without explicit instruction.
- TikTok: app submitted for review 2026-05-02; not yet wired into the autonomous workflow.
- Meta System User token: switching from 60-day rolling to permanent requires manual setup in Meta Business Manager.
- Per-run agent decision-note logging: the agent writes a private decision note in its assistant message; the workflow currently only logs subprocess output. Surfacing the model's text content blocks in run logs is open.
