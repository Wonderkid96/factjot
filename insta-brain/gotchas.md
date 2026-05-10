# factjot — Gotchas

Things that have been tried, broken, or caused hard-to-trace problems. Every agent must read this before touching the pipeline. Keep it current. If you hit a new wall, add it here.

Related (Obsidian graph hub): [[CLAUDE]] · [[CRITICAL_FACTS]] · [[MEMORY_INDEX]] · [[PUBLISH_PLAN]] · [[rules/index]] · [[rules/09-prompt-read-order]] · [[log]]

---

## YAML / GitHub Actions

**GitHub's Go YAML parser rejects UTF-8 em dashes (`—`) in comments.**
PyYAML accepts them. GitHub silently rejects the whole workflow, causing dispatch to return 422 "no workflow_dispatch trigger". The fix is to use plain hyphens everywhere. This has bitten us twice. Run `grep -r "—" .github/` before pushing any workflow change.

**Multiline Python heredocs inside `run: |` blocks break GitHub YAML parsing.**
Extract all Python logic to standalone scripts in `scripts/`. Never put more than a simple one-liner in a workflow `run:` block.

**[ARCHIVED 2026-05-10 — cron is now GitHub Actions native; cron-job.org removed, `CRON_TRIGGER_PAT` no longer used by any active workflow.]** **GitHub's built-in cron scheduler is unreliable** on free-tier repos. It can be delayed 15-60 minutes or skipped entirely under load. Use cron-job.org to dispatch via the API at exact times. GitHub crons serve only as a backup.

---

## Meta / Instagram API

**Meta's video URL downloader rejects files over ~5MB.**
This limit appeared 2026-05-02 (previously 12MB worked). Primary reel encode: **crf 23**, **preset medium** in `reel_composer.py` `compose()`. Pre-upload: if >4.7MB, two-pass VBR at **crf 30 / maxrate 800k**. On **413**, `make_reel.py` recompresses **crf 33 / maxrate 600k** then **crf 35 / maxrate 500k** (each with matching bufsize).

**Meta requires 48kHz audio. 44.1kHz and 96kHz are both rejected.**
ElevenLabs returns 44.1kHz by default. Always resample to 48kHz in FFmpeg before muxing. 96kHz was encountered once from an edge-tts path and also rejected. **Padding step:** concat of 48 kHz silence + 44.1 kHz TTS without `aresample` produced a 44.1 kHz `voice_padded.mp3` (bad). Fixed in `make_reel.py` with `aresample=48000` + matching channel layout before `concat`, plus `-ar 48000` on the MP3 encode.

**Meta access tokens expire every 60 days.** `refresh_token.py` extends them. If `refresh_token.py` returns "API access blocked", the app was rate-limited by too-rapid API calls. Wait 30 minutes, retry. If still blocked, regenerate from developers.facebook.com.

**Cloudinary URLs are rejected by Meta's video fetcher** even when the file is under 5MB. Meta's fetcher times out before Cloudinary's CDN responds in some regions. Use tmpfiles.org (1-hour expiry) — Meta fetches within the polling window. (Cloudinary remains disabled in production for this reason.)

---

## Word beat detection ("factjot" CTA sync)

**ElevenLabs often renders "factjot" as two tokens: "fact" and "jot".**
The CTA sync code checks for a word beat containing "factjot". If not found, it also checks for consecutive "fact" + "jot" beats. If neither matches, the fallback is time-based (voice_end - 3.5s). If the fallback is off, subtitles and CTA overlap. Always verify the printed "CTA locked to..." log line after a reel render.

---

## Footage

**Short clips loop visibly in FFmpeg, creating a hard jolt.**
`stream_loop -1` is needed so clips can fill their assigned window. If a clip is shorter than its window (e.g., 2s clip in a 7s hook window), FFmpeg loops it — the restart is a hard cut the viewer sees. Minimum accepted clip size is 2MB and minimum duration is 4s (probed with ffprobe). Do not lower these thresholds.

**The same clip can appear in both the intro section and the main content.**
footage_clips[0] plays under the factjot_intro.mov alpha overlay for the first 1.37s. It continues playing after the overlay ends. This is correct — the overlay is transparent and reveals the footage. Do not add a separate "intro clip" slot; the alpha overlay IS the intro.

**Global footage dedup (`data/ledgers/used_footage_urls.jsonl`) is git-tracked.**
This file must be committed after every reel or the same clip will appear in consecutive reels. It is included in `reel.yml`'s git-add step. Do not gitignore it.

---

## Image dedup

**`data/ledgers/used_images.jsonl` must be git-tracked** or image dedup resets to zero on every GitHub Actions run. It was gitignored until 2026-05-03. It is now tracked and committed in all three posting workflows.

**The brain and image_fetcher previously wrote to two different paths.**
`brain.py` used `data/used_images.jsonl`; `image_fetcher.py` used `data/ledgers/used_images.jsonl` (via paths.py). Neither checked the other's records. Fixed 2026-05-03: `brain.py` now uses `UsedImageLedger()` with no path argument, deferring to paths.py like everything else.

**News/list cover queries can be over-constrained by global aliases.**
`ship_carousel_post.py` (via the wrapped manual module) sends global `source_aliases` to slot 0 when `cover_slot_aliases` is empty. For scene-style cover queries (for example "smartphone chat app"), strict alias gates can reject every candidate (`POOL_REJECT no_alias_match`) even when content slots recover via R3. List mode survives this with typography cover fallback; news/fact hard-fail on `COVER_IMAGE_FAILED`. If a news dry-run shows `image_coverage` high but cover still fails, inspect slot 0 alias gating first.

---

## Duplicate post prevention

**Scout cache reset must not touch publish or dedup ledgers.**
Clearing discovery logs, list pack caches, or reel staging is fine for a fresh candidate inventory. Truncating `insta-brain/data/posted.jsonl`, `insta-brain/data/reels.jsonl`, `insta-brain/data/list_posts.jsonl`, `data/ledgers/used_images.jsonl`, or `data/ledgers/used_footage_urls.jsonl` will break duplicate and reuse guards and can cause the same post or assets to ship again. Use `scripts/clear_scout_caches.sh` for the safe set only. Canonical split: `src/core/paths.py` → `PUBLISH_AND_DEDUP_LEDGERS` vs `SCOUT_INVENTORY_CACHE_LEDGERS`.

**`assert_no_duplicate()` must be called immediately before every Instagram API publish call** — not earlier. It does a fresh disk read to catch posts made by concurrent runs that the in-memory cache doesn't know about. It was missing from `ship_list_post.py` until 2026-05-03.

**[ARCHIVED 2026-05-10 — queue files (`pipelines/shared/queue.jsonl`, `publish_due.py`, `review_queue.py`) are legacy and not referenced by any production workflow. `ship_first_post.py` and `ship_list_post.py` both deleted in Phase G.3 dormant code sweep.]** **The queue (`insta-brain/data/queue.jsonl`) is a legacy artefact** from the old launchd system. GitHub Actions workflows do NOT read it — they generate posts on the fly with `ship_first_post.py` / `ship_list_post.py` / `make_reel.py`. The queue contains render paths pointing to `/home/runner/work/...` which evaporate after each run. Do not populate or read the queue.

---

## Fact quality thresholds — do not lower without a good reason

**[ARCHIVED 2026-05-10 — `discover_facts.py` deleted in Phase G.3 dormant code sweep along with the entire Reddit-discovery pipeline. The autonomous flow's quality gate is the Phase D.1 fact verification (Haiku consistency + Wikipedia anchors) plus the agent's prompt-level INTERESTINGNESS / EVENT-VS-ANGLE / QUALITY gates. `ship_first_post.py` and `restock.py` are also deleted; `MIN_CAROUSEL_SCORE` no longer exists in any live code.]**

**`MIN_UPVOTES = 10_000` in `discover_facts.py`.**
Sub-10k TIL posts rarely clear the shock test. This was raised from 5k after auditing discovered facts — the 5k-10k tier was consistently bland.

**`MIN_CAROUSEL_SCORE = 2` in `ship_first_post.py` and `restock.py`.**
Score=1 facts (generic, low upvotes, no specificity signals) are never posted to carousels unless ALL topics are exhausted (emergency mode). If the runway report shows topics running low, add more curated facts — do not lower the threshold. These two constants are intentionally duplicated in two files; if you change one, change both.

**`_score_fact()` returns 0 (reject tier) for generic openers with no specificity.**
"The X is a Y that..." with no numbers, named persons, or viral signals scores 0 and is dropped at discovery time. Do not remove the boring penalty — discovered facts were routinely Wikipedia-quality before it was added.

---

## Reel quality gates

**[ARCHIVED 2026-05-10 — `rare_fact_bank.py` retired in Phase G.1; `make_reel.py` no longer has a `_pick_fact()` selection path. `--script` and `--title` are now mandatory CLI args supplied by the autonomous agent. `check_reel_runway.py` deleted in Phase G.3. The 70-word minimum still applies (in agent prompt + `make_reel.py` validation), but the q3 / quirky_score system is gone.]**

**q3 facts MUST have curated `reel_script` (>= 70 words) and `reel_title`.**
There is no auto-fallback path. If a discovered fact is missing either field, `make_reel.py` silently skips it. The runway check (`scripts/check_reel_runway.py`) only counts facts that pass ALL gates. Do not lower the 70-word minimum — it exists because 22-word scripts produced 22-second reels that felt broken (2026-05-01 incident).

---

## Instagram carousel cap: 20 images (raised from 10 in August 2024)

**`instagram_publisher.py` previously had a hardcoded cap of 10.** This caused the `top_war_films` post to fail on 2026-05-03 with `Carousel exceeds Instagram's 10-image cap (12)` — but the error was from our own code, not Meta's API. Instagram raised the limit to 20 frames in August 2024. The publisher cap has been updated to 20. `pack_resolver.py` enforces a maximum of 18 items (20 - 2 for hook and closing) and trims silently if exceeded. Do not set the publisher cap below 20 without verifying Meta's current policy.

---

## List pack cache

**[ARCHIVED 2026-05-10 — `prepare_packs.py`, `ship_list_post.py`, `generate_list_packs.py`, `verify_pack_ids.py` all deleted in Phase G.3 dormant code sweep. `weekly-plan.yml` and `list-carousel.yml` workflows deleted earlier. The autonomous list path (`ship_carousel_post.py --type list`) sources lists fresh on each run; there is no cache layer. `list_pack_cache.jsonl` is no longer written or read.]**

**List packs are pre-built on Sunday via `prepare_packs.py`.**
TMDB calls, Playwright rendering, and imgbb uploads all happen on Sunday morning, not at 17:00 UTC post time. `ship_list_post.py` reads `data/ledgers/list_pack_cache.jsonl` — if the pack is cached and valid (<7 days old), it skips all of that work and posts directly. Cache is committed to git by both `weekly-plan.yml` (after prep) and `list-carousel.yml` (after post). Do not gitignore it.

**If the cache is missing at post time**, `ship_list_post.py` falls back to the full TMDB + render + imgbb flow. This is intentional and correct — the fallback path must never be removed.

**`src/content/pack_resolver.py` is the single source of truth for TMDB resolution.**
Both `ship_list_post.py` and `prepare_packs.py` import from it. Do not add TMDB logic to either script directly — put it in pack_resolver.py.

---

## Footage sourcing — named entity extraction (2026-05-04)

**Entity search must use the named person from the claim, not `image_hint`.** Before this fix, `_entity_sources()` in `video_finder.py` received `image_hint` as the entity term (e.g. "vintage skull anatomy diagram" for Phineas Gage) and found nothing useful. Now `find_videos()` extracts proper nouns from the claim text first ("Phineas Gage") and passes those to Wikipedia/Wikimedia. `image_hint` becomes B-roll guidance only.

**Narrative beats now use claim entities.** `shot_list()` in `narrative_beats.py` previously expanded all 5 beats from `image_hint` alone. Now, when the claim contains named persons or years, the SUBJECT beat targets the actual person (e.g. "Phineas Gage 1848 portrait close up") and the DETAIL beat uses `image_hint` as B-roll. Pure `image_hint`-expansion only runs when the claim has no named entity (animals, phenomena).

**`image_hint` role:** B-roll context only. Should describe the visual setting/object for the DETAIL beat, not the person's name. The entity search handles person-finding automatically.

## Entity-first footage sourcing

**Tier 0 (Wikipedia/Wikimedia/Archive) runs before all Pexels B-roll.**
For a fact about Phineas Gage, the pipeline searches Wikipedia for "Phineas Gage" first and downloads the actual historical photograph before trying any Pexels query. This is implemented in `_entity_sources()` in `video_finder.py`. Do not move or remove this — it is what makes reels about real people/events look credible.

**Wikimedia Commons requires a two-step API call** (search then imageinfo). Do not try to shortcut it with a direct URL construction — filenames are not URL-safe and the API handles normalisation correctly.

---

## Reel thumbnail design

**Current design (2026-05-03): `factjot.` top-left, `TOPIC` top-right, title centred, corner brackets.**
No logo divider line. No bottom strip. No flanking lines around the logo. The thumbnail template went through many iterations — the settled design is in `src/render/templates/reel_thumbnail.html.j2`. Do not add back elements that were removed (bottom @factjot strip, flanking lines around wordmark) without testing a preview render first via `render_thumbnail()`.

---

## FFmpeg in GitHub Actions (CI)

**FFmpeg hangs indefinitely in GitHub Actions without `-nostdin`.**
Without `-nostdin`, FFmpeg opens stdin in interactive mode waiting for keypresses (q to quit, ? for help). In a TTY-less CI environment, stdin is a dead pipe and FFmpeg sits there forever. This caused every reel build to time out at 20 minutes. The fix is two-pronged: add `-nostdin` to the FFmpeg command AND `stdin=subprocess.DEVNULL` in the Python Popen call. Both are now in `src/render/reel_composer.py`. Never remove them.

**20+ sequential PNG overlay stages are the wrong approach for kinetic subtitles.**
Each overlay stage re-renders the full 1080x1920 frame. 27 subtitle chunks = 27 full-frame renders per output frame. The correct approach is FFmpeg's native `ass` filter (`--enable-libass` is compiled into the static FFmpeg build used on GitHub Actions). One `.ass` file replaces all subtitle PNG inputs. `generate_ass_file()` in `src/render/tts_engine.py` generates the file from word beats; `compose()` in `reel_composer.py` applies it via `-filter_complex "[prev]ass=filename=...:[after_subs]"`. The PNG approach was abandoned 2026-05-03. Pass **`fontsdir=assets/fonts/subtitle_fonts`** only so libass does not scan the whole font tree.

**Primary reel encode (current):** `libx264` **preset medium**, **crf 23**, **48 kHz** AAC. Pre-upload size check at 4.7MB triggers two-pass VBR at crf 30 / maxrate 800k. The earlier ultrafast/crf-30 constant approach was retired once tmpfiles proved fast enough that quality budget could go up.

**The real “hung forever” bug (2026-05-03): stderr pipe backpressure, not “slow filter init”.** We briefly used **`-progress pipe:2`**, which floods stderr with progress lines. **`compose()`** then used **`stderr=None`** so FFmpeg **inherited** the parent’s stderr. In Cursor’s agent shell (and any parent whose stderr is a **pipe** with a small kernel buffer), nothing drains that pipe fast enough. Once the buffer fills (~64KB), **FFmpeg blocks on every stderr write** and the encode never advances (looks stuck on frame 0 for hours). **Fix:** remove **`-progress pipe:2`** entirely; write compose **stderr to `ffmpeg_compose_stderr.log`** in the reel cache dir (disk never blocks the writer). On failure, the raised error includes a tail of that log. **`reel.yml`** still uses **`python3 -u`** and **`PYTHONUNBUFFERED=1`** for Python-side logs.

**GitHub Actions log looks empty mid-encode:** FFmpeg can still print nothing useful for minutes during heavy **filter graph init**. A naive blocking `read()` on `stderr=PIPE` in Python without draining in parallel can deadlock the child. **`_pump_ffmpeg_stderr`** (same file) is the pattern for interactive pumping with a heartbeat; main compose no longer inherits a narrow pipe for high-volume stderr.

**ProRes 4444 intro (`factjot_intro.mov`) is `yuva444p12le` — 12-bit with full alpha.**
Scaling it with `flags=lanczos` inside the filter graph is expensive. Changed to `flags=bilinear`. Also added `eof_action=pass` to the intro overlay so FFmpeg doesn't attempt to hold the stream open after the intro's 1.37s duration ends.

**Archive.org search requests with a 20s timeout block the footage finder.**
For facts where Archive has no relevant footage (most modern facts), every query waits the full timeout before moving on. With 3-5 queries per reel, this added 60-100s of dead wait. `_HTTP_TIMEOUT` in `video_finder.py` cut from 20s to 10s.

**Tier-0 still JPEGs + `stream_loop` + default image2 25 fps = multi-hour “stuck on frame 0”.** Not corrupt media: valid JPEGs and MP4s. **image2** defaults to **25 fps**, so a **~10 s** still window forced **~250** full **4K** decodes before **`concat`** could output; **25 vs 29.97 vs 60** fps across legs also broke **`concat`** expectations. Fixed in `reel_composer.py`: **`-framerate 1`** before **`-i`** for still suffixes, and **`,fps=30`** after each clip's pan crop so every leg is **30 fps** before **`concat`**.

---

## Local macOS (FFmpeg)

**Subtitles use PNG overlays, not the `.ass` filter.** The ass filter was tried (commit 6ba92ce) but caused a hard deadlock at frame ~275 on ffmpeg-full/macOS -- the frame counter froze completely (not just slow; zero progress for 33 minutes) before receiving SIGTERM and exiting 255. Root cause was not fully isolated but the deadlock was reproducible. Reverted to per-chunk PNG overlays with `enable='between(t,...)'` windows. PNG overlays are proven to work on CI and are simple to debug.

**Wikipedia/Wikimedia JPEG stills as footage inputs deadlock FFmpeg on macOS (fixed 2026-05-04).** Stills fed via `-framerate 1 -stream_loop -1` + `fps=30` in the filter graph create a 1->30 frame imbalance. The `image2` demuxer fires one frame per second; `fps=30` must generate 30 output frames from each, backing up the concat/overlay pipeline. All `av:h264:df*` decoder threads (16-28 spawned by ffmpeg-full on Apple Silicon) block on condvar waiting for each other — `sch_wait` on main thread, total deadlock. Confirmed via `sample` profiling. Fix: `_still_to_mp4()` in `reel_composer.py` pre-renders each JPEG/PNG/WebP to a proper 30fps H264 MP4 before the main compose. Also: thumbnail frame extraction must fall back to `final.mp4` when `footage_clips[0]` is a still (JPEG has no seekable duration at 1.0s).

**Wikimedia entity images crash `dec:png` with task error -1145393733 (fixed 2026-05-04).** FFmpeg's PNG decoder crashes on images downloaded from Wikimedia Commons that are: RGBA, 16-bit, palette mode, CMYK, or extremely large (8640x5760 seen). `_valid_image()` checks magic bytes only — it does not catch these. When the decoder crashes, libx264 terminates with EINVAL (-22), the whole reel fails. Fix: `_normalise_still()` in `reel_composer.py` runs every entity still through Pillow BEFORE passing it to FFmpeg — converts any mode to RGB, caps to 1920px on the long edge, saves as a clean JPEG. FFmpeg then receives a perfectly standard input it cannot crash on. Do not bypass `_normalise_still()` as an "optimisation" — it fixes a real production crash, not a theoretical one.

**Default Homebrew `ffmpeg` (8.0.1_2) is broken after libvpx upgrade.** After Homebrew updated libvpx from v11 to 1.16.0, `ffmpeg 8.0.1_2` crashes with `dyld: Library not loaded: libvpx.11.dylib`. `assert_reel_ffmpeg_ready()` now auto-falls-back to `ffmpeg-full` (Apple Silicon: `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg`) when the default binary fails its `-version` probe and `FFMPEG_BIN` is not explicitly set. No manual env var needed. If `ffmpeg-full` is not installed: `brew install ffmpeg-full`.

**iCloud intercepts FFmpeg output when the project lives in `~/Documents/`.** macOS iCloud Drive syncs `~/Desktop`, `~/Documents`, and `~/Downloads`. When FFmpeg tried to write `final.mp4` inside the iCloud-synced Documents folder, iCloud's FileProvider daemon intercepted the file creation and held it in a delete-queue staging area (`~/Library/Application Support/FileProvider/.../wharf/wharf/delete/...`). FFmpeg kept running at ~170% CPU for 14+ minutes but wrote zero bytes to the actual output path. **Fix: the project now lives at `~/Developer/Insta-bot`** (outside iCloud's reach). Do not move it back into any iCloud-synced folder.

**Only one local `make_reel.py` at a time (2026-05-04).** Several terminals or agents each starting a full reel left **multiple FFmpeg composes** at ~170% CPU each (fans pegged). **`fcntl` advisory lock** on `data/cache/reels/.make_reel.lock` makes a second run exit **10** with a clear message. **`scripts/kill_local_reel_jobs.sh`** kills matching FFmpeg + `make_reel.py` under this repo only. **Logs:** each run writes **`data/cache/reels/<id>/pipeline.log`** and **`logs/reel_runs/<UTC>_<id>.log`** (timestamped milestones plus anything sent through `ReelRunLogger.emit`).

**FFmpeg compose exit 255 on Mac:** treat as a real filter / encode failure, not "slow init". Read **`ffmpeg_compose_stderr.log`** and **`ffmpeg_debug.txt`** under **`data/cache/reels/<id>/`**. Do not confuse with SIGTERM (below).

**Local encode "frozen" at low frame count but stderr still growing:** on **Apple Silicon** + **`ffmpeg-full`**, full graphs (ass + many inputs + x264) have been observed at **~0.005x–0.02x** real-time (tens of minutes for tens of seconds of output). That is **not** the old stderr pipe deadlock if **`ffmpeg_compose_stderr.log`** keeps growing. For a reliable full encode + publish, use **`reel.yml`** on **ubuntu-latest** until the Mac path is profiled.

**`Exiting normally, received signal 15`:** FFmpeg received **SIGTERM** ( **`kill_local_reel_jobs.sh`**, Cursor task timeout, manual **Stop**, or OS). Python often ends with **`exit 5`** after compose failure handling. Not a token or Meta error.

---

## 2026-05-05: force-push to main triggered triple-post incident

Someone force-pushed to `main` while three publish workflows were running concurrently. The workflows' state-commit step (`git pull --rebase --autostash` then `git push`) lost their state commits because the `main` ref had been rewritten beneath them; the next scheduled runs re-read `posted.jsonl` from an earlier git state and re-published the same posts. Three identical posts shipped in 8 minutes.

**Mitigation:**
- Hard rule "never force-push to main" added to project-root `CLAUDE.md` §1.1 and `SPEC_FACTJOT_SYSTEM.md` §12.14.
- Large-history rewrites now happen on a separate branch with workflows paused; the rewrite branch is then merged in.
- Concurrency group `factjot-publish` with `cancel-in-progress: false` already in place to keep overlapping triggers queueing rather than racing, but it doesn't protect against ref rewrites — the force-push rule does.

**Lesson:** running publish workflows are mid-write to a shared ledger. Any operation that rewrites the ref under them is destructive.

---

## 2026-05-09: IG story container FINISHED race produced partial-render stories

Stories were sometimes published before their cover image upload to IG completed, producing partial-render stories (the cover frame would be missing or half-rendered). The reel publish step worked, but the immediately-following story publish call to `media_publish` hit the IG API before the story container had reached `status_code: FINISHED`.

**Fix (commit `3a366e1`):** before calling `media_publish` for the story, poll the story container for `status_code: FINISHED`. The reel-side polling pattern (15 s intervals, not 3 s, to avoid rate-limiting) was extended to the story container.

**Do not remove the polling loop.** "It usually works without it" is the failure mode this fix addresses.

---

## 2026-05-09: entity-vs-beat crowding — wrong-subject thumbnails from `footage_clips[0]`

Thumbnails picked from `footage_clips[0]` were sometimes off-subject because the entity tier (Wikipedia / Wikimedia / Internet Archive) scored 1.0 by construction (entity = subject, by definition) and outranked B-roll candidates that were actually about the right thing. A reel about person X could end up with a thumbnail of an unrelated entity Wikipedia happened to return for an ambiguous search.

**Fix (Phase E.3):** entity image Haiku validation — every entity tier hit is run through Haiku 4.5 with the actual claim text, and Haiku rejects wrong-subject hits before they enter `footage_clips`. The thumbnail picker (Phase E.4) now sees a clean `footage_clips` array.

**Do not bypass `validate_entity_image()` as an "optimisation".** It fixes a real production failure mode where a 1.0 score is wrong by construction.

---

## 2026-05-10: youtube_uploads.jsonl first-cross-post `git add` abort

The autonomous workflow's `git add` step aborted on first cross-post because `data/ledgers/youtube_uploads.jsonl` did not yet exist. The previous form was a single `git add ledger1 ledger2 ...` which fails the whole step on the first missing file, silently leaving every other state file unstaged. The `git commit` step then had nothing to commit, the workflow looked green, and the next run re-read stale state.

**Fix (workflow change in `autonomous-reel.yml:200-220`):** stage each ledger separately, guarded by `if [ -e "$f" ]; then git add "$f" || true; fi`. A missing file no longer aborts the step; existing ledgers stage normally.

```yaml
for f in \
  insta-brain/data/posted.jsonl \
  insta-brain/data/reels.jsonl \
  ...
  data/ledgers/youtube_uploads.jsonl
do
  if [ -e "$f" ]; then
    git add "$f" || true
  fi
done
```

**Lesson:** any `git add <list>` in a workflow has to tolerate the first-time-creation case. New ledgers must not abort the commit step.

---

## 2026-05-09: phone-with-no-apps near-duplicate cluster

Eight carousels about the same speculative product story shipped in five hours under different slugs. The agent's existing duplicate guard (last 30 entries, topic / angle / "same subject framed differently") missed it because each carousel had a slightly different angle and slug, but they were all the same subject in different framings.

**Fix (Phase C.3):** subject-fingerprint dedup added to the agent loop. Computes a token-set fingerprint per brief, compares against the last 14 days of `posted.jsonl` using Jaccard similarity. Anything ≥ 0.6 is rejected before the brief enters `run_carousel` / `run_reel`. Sits in front of the prompt-level guard, not behind it.

**Do not lower the 0.6 threshold without watching the false-positive rate for two weeks.** The threshold was tuned against the cluster that triggered this fix.

---

## 2026-05-09: fictional-films carousel — $0 fact verification gate

A list carousel shipped with four invented films because no fact verification gate existed. The agent had hallucinated film titles that fit the criterion ("films with X premise") but did not exist. The image fetcher dutifully searched for them, found nothing, fell back to typography slides for each, and the carousel still posted because the format was technically valid.

**Fix (Phase D.1):** fact verification gate. Two layers, both running before publish:
1. Haiku 4.5 consistency check on the brief — flags briefs containing "fictional", "absurdity", "experiment" without justification at $0 cost. Catches the cheapest failure cases first.
2. Numeric and named claims are cross-checked against Wikipedia anchors. If a claim cannot be anchored, the gate rejects.

**Soft-fail-then-hard-fail rollout:** v1 ships with hard rejection. If hard-rejection rate exceeds 50% after 3 days, drop to soft-fail (warn + ship + log) for tuning, then re-tighten.

**Do not remove the gate to "speed things up".** The cheapest layer (Haiku consistency) is essentially free; the expensive layer (Wikipedia anchoring) is bounded by the number of named entities per claim, typically 1-3.

---

## 2026-05-10: reel cover never reached IG — half-built "one asset, two surfaces"

Phase E.4's stated intent (per `src/render/reel_thumbnail.py:13-16` and the `_prepare_thumbnail` docstring at `scripts/upload_to_youtube.py:298-302`) was: render a single overlay-bearing asset, ship it to both the IG Reel cover and the YouTube custom thumbnail. The implementation only honoured that intent on the YouTube side. `_prepare_thumbnail` converts `thumbnail.png` -> JPEG and re-encodes if >2MB; the IG side in `make_reel.py:986-1000` uploaded the rendered PNG raw.

**Failure mode:** IG Reels `cover_url` accepts JPEG only and is hard-capped under ~0.5MB. The rendered overlay PNG is ~3.3MB. IG's container processing silently drops a non-conforming `cover_url` without setting `ERROR` -- `_wait_for_finished` returns `FINISHED` and `publish_reel` returns `ok: True` regardless. The reel posts; the custom cover does not. IG falls back to an auto-extracted video frame for the Reels Tab grid. Because the publish path returns success, no log surfaces the loss; you only notice by visiting the IG profile and seeing the wrong frame on the grid.

**Why this stuck:** the YouTube docstring said "one asset, two surfaces" and the IG upload site sat 50 lines below the rendering site, so reading the code top-down reads as if both surfaces are wired up. The asymmetry only shows when you trace the actual file extension that gets uploaded.

**Fix (2026-05-10):** `make_reel.py` now emits ONE IG-compliant JPEG (`thumbnail.jpg`, <=450KB at q=85->75->65 fallback) alongside the rendered PNG. Helper `_shrink_thumbnail_to_ig_jpeg` in `pipelines/reel/make_reel.py` raises `RuntimeError` if compression cannot meet the cap -- failure is loud, not silent. Both surfaces consume the same JPEG: IG `cover_url` upload uses it directly; `upload_to_youtube.py:_prepare_thumbnail` prefers `thumbnail.jpg` if present and falls back to PNG conversion only for older runs without one. The PNG is kept on disk for archive/preview but is no longer uploaded anywhere.

**Regression guards (`tests/test_make_reel_thumbnail_jpg.py`):**
- `test_shrink_emits_jpeg_under_ig_cap`: output magic bytes must be `\xff\xd8\xff`, size must be <= `_IG_COVER_TARGET_BYTES`, dimensions 1080x1920.
- `test_ig_cover_target_under_meta_hard_cap`: pins `_IG_COVER_TARGET_BYTES` below 500KB so a "raise the cap" PR fails CI rather than reintroducing silent drops.
- `test_shrink_raises_when_pillow_missing`: the previous behaviour (skip conversion, hand IG a 3.3MB PNG) is now an explicit `RuntimeError`.

**Future trap to avoid:** if the picker / overlay path ever consolidates and someone deletes the helper as "redundant" because both surfaces upload `thumbnail.png`, the IG side will silently break again. Keep the JPEG step until IG `cover_url` accepts PNG (it does not, as of v21.0). Do not "simplify" by emitting JPEG only and deleting the PNG either: the high-quality PNG is the archive copy used for dry-run preview and any future re-render.

---

## Fix philosophy (mandatory)

Every fix must be a long-term structural fix, not a temporary patch. A patch that suppresses a symptom without removing its root cause will reappear in a different form or a different part of the pipeline. Before shipping any fix, ask: does this eliminate the cause, or does it hide it? If it hides it, keep digging.
