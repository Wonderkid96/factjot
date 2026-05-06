# SPEC_FACTJOT_SYSTEM.md

## 1. Status, owner, and what this document is

**Status:** Approved by Toby, 2026-05-06.
**Owner:** Toby Johnson (TJCreate), Lincoln UK.
**Scope:** Top-level system constitution for the factjot repository.
**Replaces:** Nothing. This is the first system-level spec. SPEC_IMAGE_PIPELINE.md continues as a sub-spec.

This document is the constitution for the factjot repo. It defines what the system is, how its pipelines are structured, what counts as success, and how agents and humans are expected to work inside it.

Every agent that is about to make a cross-cutting change (new pipeline, shared module, safety rule, lifecycle change) reads this document first. Every agent making a pipeline-specific change also reads the relevant sub-spec.

This document is product-led first, code-aware second. It does not replace README.md or CLAUDE.md. README.md tells you how to set the system up. CLAUDE.md tells you the operational rules and environment specifics. This spec tells you what the system is, why it works the way it does, and what good looks like.

---

## 2. What factjot is

factjot is an autonomous Instagram publishing system for the @factjot account. It produces, schedules, and publishes verified-fact content in TJCreate's editorial style, with no daily human input on stable repeating pipelines.

The product promise: a single account that posts visually strong, factually correct, legally safe content every day, in a recognisable voice and visual identity, without Toby logging into Instagram.

The technical promise: a repo where every post type follows a predictable lifecycle, every shared rule lives in one place, and every successful run is verifiable from rendered output, not from green tests.

---

## 3. System overview

The system is layered. Each layer has one job.

```
┌─────────────────────────────────────────────────────────────┐
│  insta-brain/    rules, invariants, ledgers, bank, log      │  source of truth
├─────────────────────────────────────────────────────────────┤
│  pipelines/      reel, carousel, list, manual, news         │  product layer
├─────────────────────────────────────────────────────────────┤
│  src/            shared content, research, render, publish  │  shared modules
├─────────────────────────────────────────────────────────────┤
│  data/, output/  ledgers and per-run rendered artefacts     │  state and artefacts
└─────────────────────────────────────────────────────────────┘
```

- `insta-brain/` holds rules, invariants, the curated fact bank, the activity log, and append-only state ledgers (`posted.jsonl`, `reels.jsonl`, etc.). It is the single source of truth for rules.
- `pipelines/<name>/` holds the entry-point scripts for each post type. Each pipeline is a slice through the shared modules.
- `src/` holds the shared content, research, render, and publish modules. Safety-critical behaviour lives here, not inside a pipeline.
- `data/ledgers/` holds repo-tracked append-only records (used images, used footage, API costs, etc.). `output/` holds local-only per-run rendered artefacts for inspection.

If a behaviour is shared across two or more pipelines, it belongs in `src/`, not in any one pipeline.

---

## 4. Current pipelines

The factjot system currently runs five pipelines. They share infrastructure but have distinct product roles.

| Pipeline | Folder | Product role | Trigger |
|---|---|---|---|
| Reels | `pipelines/reel/` | Daily short-form video, single q3 fact, voiceover, footage, captions, story | Autonomous, daily 12:00 BST |
| Scheduled fact carousel | `pipelines/carousel/` | Daily morning carousel, topic-based fact slides | Autonomous, daily 10:00 BST |
| List carousel | `pipelines/list/` | Daily evening list post, pre-resolved packs (e.g. films), TMDB-driven | Autonomous, daily 18:00 BST |
| News carousel | `pipelines/news/` | Conditional carousel reacting to a breaking story | Autonomous, daily 14:00 BST, fires only if breaking-story gate passes |
| Manual / editorial carousel | `pipelines/manual/` | Custom editorial carousel from a written brief | Editorial, on demand |

**The manual / editorial carousel is the current problem area.** Image quality, subject accuracy, and visual coherence have failed there in ways the autonomous pipelines have not. Most active spec work today (SPEC_IMAGE_PIPELINE.md, this document) is motivated by manual carousel failures.

The manual pipeline is, however, only one pipeline inside the wider system. Fixes here must not regress the autonomous pipelines, and the autonomous pipelines remain the system's daily output regardless of manual-pipeline state.

Future pipelines (Stories on carousel posts, TikTok crossposting, new editorial formats) will be added under `pipelines/<name>/` following section 15.

---

## 5. Standard pipeline lifecycle

Every pipeline follows the same canonical lifecycle. Not every pipeline uses every stage. Skipping a stage must be deliberate and recorded in the pipeline's sub-spec.

```
SOURCE → VERIFY → GENERATE → ACQUIRE MEDIA → RENDER → (APPROVE) → PUBLISH → LEDGER → MEASURE
```

| Stage | What happens | Notes |
|---|---|---|
| Source | Pick or discover the subject. Reddit for facts, RSS for news, a brief for manual, a curated pack for list, a fact bank entry for reels. | Reddit-only for fact discovery (hard rule). |
| Verify | Confirm the claim is true. ≥ 2 sources, confidence ≥ 0.65, correction-signal scan, source-text support. | Truth gate. Non-overridable. |
| Generate | Resolve copy, scripts, titles, captions, image intent, slide structure. | Where Sonnet/Haiku/Claude are allowed to act. Never as a fact source. |
| Acquire media | Fetch images and/or footage according to declared media intent (see section 8). | Validation is hard. Selection is judgement. |
| Render | Compose the final post artefact (PNG slides, MP4 reel, thumbnail, story). | Output is the truth. Tests are not. |
| Approve | Inspect the rendered output. Required for editorial pipelines, skipped for autonomous (see section 6). | Visual inspection, not code review. |
| Publish | Upload media, post to Instagram Graph API, write per-publish artefacts. | Idempotency-checked. |
| Ledger | Append to ledgers (posted, used images, used footage, etc.). | Append-only with one named exception. |
| Measure | Pull insights, score performance, feed weekly reports. | Ledger may be mutable for live metrics. |

A pipeline that skips Verify is not a pipeline, it is a content laundromat. A pipeline that cannot produce inspectable rendered output is not safe to call autonomous. After any pipeline change, rendered output must be inspected before that change ships. A pipeline that skips Ledger will eventually repost itself.

---

## 6. Two posting modes

Every pipeline runs in one of two modes. The mode determines whether human approval is in the loop.

### 6.1 Autonomous mode

Used by stable scheduled pipelines that have proven their visual and factual quality over time. Currently:

- Reels (`pipelines/reel/`)
- Scheduled fact carousel (`pipelines/carousel/`)
- List carousel (`pipelines/list/`)
- News carousel (`pipelines/news/`), when its breaking-story gate passes

Autonomous mode runs on this stack:

- **GitHub Actions is the production scheduler and the sole posting environment.** It runs 24/7 regardless of Toby's Mac. Every autonomous post leaves the system from a GitHub Actions runner, not from a local machine.
- **cron-job.org is the primary trigger.** It hits GitHub's workflow dispatch API at the scheduled UTC times via a fine-grained PAT.
- **GitHub's built-in cron is the backup trigger.** It is unreliable on its own but useful as belt-and-braces alongside cron-job.org.
- **Backup crons at +45 min** catch cases where both primary triggers slip.
- **launchd jobs are disabled.** Local launchd-based publishing is legacy. Re-enabling launchd without first disabling the GitHub workflows will cause double-posts.
- **Queue-based local publishing** (`scripts/publish_due.py`, `review_queue.py`) is also legacy. The README still describes it; the live system does not use it.

GitHub Actions is the production reality. README.md currently still describes the older launchd + queue-based local publishing flow as if it were live. README.md is to be updated after this spec is approved so that GHA is presented as the production scheduler and the legacy local flow is clearly marked as inactive. CLAUDE.md's "Key source files" table also contains stale paths under `scripts/` for entrypoints that have moved to `pipelines/<name>/`; this is in the same documentation-drift cleanup.

Safety in autonomous mode lives entirely in code:

- Idempotency check before every post (`check_posted_today.py`).
- Ledger checks before generation (no repost, no image reuse, no footage reuse).
- Hard validation gates on media (licence, provider, subject match).
- Dry-run discipline for any change to a pipeline.
- Failure logging to the brain log on any workflow error.
- A single concurrency group across posting workflows so two triggers cannot publish in parallel.

### 6.2 Editorial approval mode

Used by:

- Manual / editorial carousels (`pipelines/manual/`).
- Any new pipeline that has not yet graduated (see section 15).
- Any experimental or visually unproven format.
- Any pipeline temporarily under remediation after a visible failure.

Editorial mode requires Toby (or a delegated reviewer) to inspect the rendered output before publish. Approval means:

- The rendered PDF or video has been opened.
- Every slide has been looked at.
- Wrong images, weak images, empty image boxes, and broken layouts have been ruled out.
- The cover slide has been judged usable.
- The caption has been read.

Approval is not "the dry run completed". Approval is not "tests passed". Approval is a human looking at the rendered artefact and judging it usable.

A pipeline can move between modes. Graduation rules are in section 15.

---

## 7. Shared modules and responsibilities

Shared code lives in `src/` and `pipelines/shared/`. The principle: if a behaviour is safety-critical or used by more than one pipeline, it lives in shared code. Pipelines compose shared code, they do not re-implement it.

| Shared area | Responsibility |
|---|---|
| `src/core/` | Brand constants, paths, config, models. Single source of truth for fonts, colours, dimensions, output locations. |
| `src/research/` | Fact discovery, fact bank, image sourcer, image fetcher, video finder, narrative beats, used-image and used-footage ledgers. |
| `src/content/` | Copy generation, scripts, titles, captions, hashtags, image intent fields. |
| `src/verification/` | Truth gate. Source checks, correction-signal scans, support checks. |
| `src/render/` | Playwright HTML rendering, FFmpeg composition, thumbnail and story renderers, brand templates. |
| `src/publish/` | Instagram Graph API client, image hosting (imgbb), video hosting (tmpfiles). |
| `src/utils/` | Logging, retry helpers, run loggers. |
| `pipelines/shared/` | Cross-pipeline operational scripts: token refresh, idempotency, scheduling, status, cleanup, heartbeat, brain freshness. |

Anything safety-critical, in particular truth verification, image validation, ledger writes, and Graph API publishing, belongs in shared code. A pipeline must not invent its own truth check, its own image validator, or its own Instagram client. If a pipeline needs behaviour that does not exist in shared code, the shared code is extended first, then the pipeline calls it.

---

## 8. Media sourcing

Pipelines do not invent their own media sourcing. They declare a media intent and let shared sourcing fulfil it.

### 8.1 Declared media intent

Every pipeline that uses media (images or footage) declares, per slot:

- the resolved subject (`visual_subject`, multi-word, disambiguated)
- aliases (`source_aliases`, ≥ 2 multi-word forms)
- context words (`context_words`, must appear alongside ambiguous terms)
- negative terms (`negative_terms`, hard-block)
- preferred and avoided image / footage types
- per-slot queries
- a fallback query

Image intent is detailed in SPEC_IMAGE_PIPELINE.md. Video intent will be detailed in a future SPEC_VIDEO_PIPELINE.md and currently lives implicitly in `narrative_beats.py` and `video_finder.py`.

### 8.2 Reusable sourcing contract

The contract between a pipeline and the sourcer is uniform and reusable across all pipelines:

- The pipeline produces intent. The sourcer produces validated candidates.
- Hard validation (licence, provider, subject match, negative-term checks) happens in shared code, before any model sees a candidate.
- Judgement (Haiku selection for images, scoring for footage) happens in shared code, after hard validation.
- The pipeline receives a final selection per slot, plus a typography-only flag where applicable.

**Pipelines must not invent their own one-off sourcing logic.** A pipeline may not call image or footage providers directly except through `src/research/`. A pipeline may not invent its own candidate scoring, its own licence policy, or its own dedupe logic. A pipeline may not bolt on a private "just for this format" fetcher.

If a new pipeline genuinely needs sourcing behaviour that does not fit the existing contract, that is a sub-spec change, not a private workaround. The new behaviour gets added to shared sourcing, with explicit approval, and the relevant sub-spec records the change.

### 8.3 Provider trust

Provider order, licence policy, and validation rules are owned by the relevant sub-spec. Image providers are listed in SPEC_IMAGE_PIPELINE.md section 6. Video providers and tier order are listed in CLAUDE.md (footage quality rules) and will move into SPEC_VIDEO_PIPELINE.md when written.

---

## 9. Style guide and brand tokens

Brand and style tokens have one source. Renderers consume tokens, they do not declare them. A hardcoded hex code, font family, font size, or layout constant in a template is a violation, the same way an invented fact is.

This section describes the target architecture. Some current templates and renderers still inline values; those are tracked for migration in `SPEC_STYLE_GUIDE.md` and are not yet aligned with this spec. The architecture below is what the system is moving towards, not a claim that every template already follows it.

### 9.1 Files and roles

- `brand/brand_kit.json` is the single JSON source of truth for visual style tokens. Locked. Versioned in git. Edited deliberately.
- `src/core/brand.py` is the typed loader and interface. It reads `brand_kit.json` at import time and exposes typed access (`BRAND.palette`, `BRAND.fonts`, `BRAND.type_scale`, `BRAND.spacing`, `BRAND.layout`, `BRAND.formats.<format_name>`). It does not redefine values. It is interface, not source.
- `src/render/templates/*.html.j2` and any other renderer templates are pure consumers. They receive tokens through Jinja context. They do not inline values that exist in `brand_kit.json`.

There is no second style file. There is no `style_guide.json`. There is no parallel set of constants in Python that contradicts the JSON. One source, one loader, one consumption path.

### 9.2 brand_kit.json structure

`brand/brand_kit.json` has these top-level keys:

- `palette`: named colours (paper, ink, accent, lime, lilac, etc.).
- `fonts`: the three brand fonts and their files.
- `voice`: voice principles and copy rules (already present, unchanged by this spec).
- `type_scale`: base sizes and ratios.
- `spacing`: base spacing units.
- `layout`: canvas dimensions, safe zones, common layout constants.
- `formats`: per-format token bundles (see 9.3).

Format-specific tokens override or extend top-level tokens, they do not contradict them. If a format declares an `accent` colour, it must reference the palette, not invent a new hex. Full schema lives in `SPEC_STYLE_GUIDE.md`.

### 9.3 Format coverage

Every current renderer has its own block under `formats`:

- `manual_carousel`
- `fact_carousel`
- `news_carousel`
- `list_carousel`
- `reel_thumbnail`
- `reel_story`
- `reel_overlay` (kinetic subtitles, hook title, label bar, CTA card)

A new post format adds a new format block in the same commit as the new pipeline (per section 15 rules). Adding a new format is a `brand_kit.json` change and triggers the testing rule in 9.5.

### 9.4 Renderer consumption contract

- Python loads tokens once via `src/core/brand.py`.
- Python passes resolved tokens into the Jinja context per render call.
- Templates reference only context variables, never raw values that exist in `brand_kit.json`.
- A renderer that needs a value not yet in `brand_kit.json` adds the value to the JSON first, then consumes it. It does not invent the value inline.

A pipeline that needs a one-off visual treatment (for example an experimental layout) does not bypass this contract by hardcoding values. The new tokens are added to `brand_kit.json` under the appropriate format block, even if only that format uses them.

### 9.5 Style-change testing

Any change to `brand/brand_kit.json` or `src/core/brand.py` requires a smoke render across every format before it ships:

- A shared script renders representative content for every format (manual carousel, fact carousel, news carousel, list carousel, reel thumbnail, reel story, reel overlay).
- Output is written to `output/style_check/YYYY-MM-DD_HH-MM/<format>/`.
- Output is opened and inspected.
- A green test run does not substitute for visual inspection.

Detail of the smoke-render script (entry point, representative inputs, what to look at) lives in `SPEC_STYLE_GUIDE.md`.

### 9.6 Migration note

Existing templates and renderers may still inline values that this spec says they should not. The migration from scattered inline values to consumption-only templates is a separate implementation step. It does not happen on the basis of this spec alone. The migration plan, audit list, and ordering live in `SPEC_STYLE_GUIDE.md`.

---

## 10. Rendering, dry runs, and output

Rendering is the moment of truth. Tests passing is not success. Code completing is not success. The rendered artefact is the only thing that proves the pipeline worked.

### 10.1 Output locations

Every pipeline writes its rendered artefacts to `output/<pipeline>/YYYY-MM-DD_HH-MM_TOPIC/`. Folders sort chronologically in Finder, so any agent or human can open the most recent run and inspect it.

```
output/
  carousel/    fact carousel slides
  reel/        reel build artefacts (final.mp4, thumbnail.png, story.png, footage)
  list/        list carousel slides
  news/        news carousel previews
  manual/      manual carousel previews and PDFs (editorial inspection)
  experiments/ prototype pipeline output
```

`output/` is gitignored and local. Repo-tracked state lives in `data/ledgers/` and `insta-brain/data/`.

**Known implementation mismatch.** `output/manual/` is the desired location for manual carousel previews. In the current implementation the manual pipeline still renders through the news renderer (`pipelines/news/ship_news_post.py`) and writes its dry-run previews into `output/news/...`. This is a documented mismatch to audit and align after this spec is approved. The target state is that every pipeline writes to its own `output/<pipeline>/` directory.

### 10.2 Dry runs

Every pipeline supports `--dry-run`. Dry-run produces the rendered artefacts and reports what would be written or published, but must not mutate production publish ledgers unless explicitly documented. Dry-run does not call the Graph API. Dry-run is mandatory before any code change to a pipeline ships, and is the basis for editorial approval.

### 10.3 Inspection rule

- **Editorial-mode pipelines:** rendered output must be inspected by Toby (or a delegated reviewer) before publish.
- **Autonomous-mode pipelines:** rendered output must be inspected after any code change to that pipeline before the change is allowed to ship to production.

Detail on rendering, brand templates, and FFmpeg composition belongs in a future SPEC_RENDERING.md. This spec only states the principle: the rendered artefact is the truth.

---

## 11. Ledgers and the brain

Ledgers are how the system remembers what it has done. The brain is how the system remembers what it should do.

### 11.1 The brain

`insta-brain/` is the operating manual. It contains:

- `CLAUDE.md`, brain operating rules.
- `CRITICAL_FACTS.md`, invariants.
- `rules/`, numbered rule files.
- `bank/`, curated facts and quotes.
- `data/`, append-only state ledgers (`posted.jsonl`, `reels.jsonl`, `queue.jsonl`, etc.).
- `inbox.md`, idea capture.
- `log.md`, rolling activity log.
- `gotchas.md`, recorded failure modes.

The brain is read at the start of every session. It is the source of truth for rules. When a rule changes, the brain changes first, then code follows.

### 11.2 Ledger discipline

Ledgers are append-only. Historical lines are never edited. There is one named exception:

- `data/ledgers/reel_performance.jsonl` is mutable. It is fully rewritten by `fetch_reel_metrics.py` to update engagement numbers as they accumulate. It must not be converted to append-only.

Every other ledger is append-only. Every ledger guards a specific invariant:

- `insta-brain/data/posted.jsonl` guards "no repost".
- `data/ledgers/used_images.jsonl` guards "no image reuse across posts".
- `data/ledgers/used_footage_urls.jsonl` guards "no footage reuse across reels".
- `data/ledgers/discovered_facts.jsonl` guards "no re-harvest of the same Reddit post".
- `data/ledgers/api_usage_costs.jsonl` records cost per run.

A change that writes to a ledger inconsistently with its invariant is a system bug, not a pipeline bug.

---

## 12. Safety rules and invariants

These rules apply across the whole system. They are not negotiable. Most are duplicated in CLAUDE.md and the brain. They are stated here as principles, not duplicated word for word.

1. **Truth.** Every published fact is verified. ≥ 2 reputable sources, confidence ≥ 0.65, source-text supported. Reddit is a lead, never proof.
2. **Reddit-only fact origin.** Facts come from Reddit posts with real citations. Claude may write a `reel_script` from a Reddit-sourced fact, never invent the fact itself.
3. **No repost.** Hash-checked against `posted.jsonl` before generation.
4. **No image reuse across posts.** Hash-checked against `used_images.jsonl`. Within a single carousel, reuse is governed by SPEC_IMAGE_PIPELINE.md.
5. **No footage reuse across reels.** Hash-checked against `used_footage_urls.jsonl`.
6. **No empty image boxes.** A slide either shows a real image or uses an intentional typography-only layout. Never an empty photo rectangle, blank image slot, or near-invisible placeholder.
7. **British English.** All copy, all captions, all comments.
8. **No em dashes.** Anywhere, ever. Including YAML workflow comments.
9. **Three brand fonts only.** Instrument Serif, Space Grotesk SemiBold, JetBrains Mono Bold.
10. **Idempotency.** No pipeline publishes twice on the same day for the same slot. Checked before every post.
11. **Concurrency.** All publishing workflows share one concurrency group. Two triggers cannot publish in parallel.
12. **Append-only ledgers**, with the one named exception in section 11.2.
13. **Image pipeline changes require plan mode.** Any change to image sourcer, fetcher, candidate selection, or fallback logic begins in plan mode. See SPEC_IMAGE_PIPELINE.md.
14. **Never force-push to main.** Force-push silently deletes state commits written by running workflows. The 2026-05-05 triple-post incident was caused by force-push. Large-file removal happens on a separate branch with workflows paused.
15. **Canonical Python path locally.** `/Library/Frameworks/Python.framework/Versions/Current/bin/python3`. Bare `python3` only inside GitHub Actions.
16. **Style tokens have one source.** All visual style tokens (palette, fonts, type scale, spacing, layout constants, format-specific values) live in `brand/brand_kit.json` and are accessed only through `src/core/brand.py`. Templates and pipelines do not duplicate, redefine, or inline these values. This is the target architecture; existing inline values in templates are tracked for migration in `SPEC_STYLE_GUIDE.md`.

---

## 13. Definition of success

A pipeline is not successful because the code ran.
A pipeline is successful only when the rendered output is:

1. **Visually usable.** The post looks intentional and brand-correct.
2. **Factually accurate.** Every claim is verified against ≥ 2 reputable sources.
3. **Legally safe.** Every image and clip has a verified provider and a usable licence.
4. **Correctly logged.** Ledgers, brain log, and per-run logs reflect what happened.
5. **Safe to publish.** Idempotency and dedupe gates have passed, and (in editorial mode) a human has inspected the artefact.

All five must hold. Four out of five is a failure.

> **Hard principle.** Future agents must not optimise for code passing tests while ignoring rendered output. Tests prove code correctness. Rendered output proves product correctness. The product is the bar.

---

## 14. Agent workflow and read order

This section defines how agents (and humans) are expected to work inside the repo.

### 14.1 Read order at session start

1. `/Users/Music/.claude/CLAUDE.md` (Toby's universal rules).
2. `Insta-bot/CLAUDE.md` (project-level rules).
3. `Insta-bot/SPEC_FACTJOT_SYSTEM.md` (this document).
4. The relevant sub-spec for the area being touched (`SPEC_IMAGE_PIPELINE.md`, future `SPEC_VIDEO_PIPELINE.md`, `SPEC_RENDERING.md`, `SPEC_STYLE_GUIDE.md`, `SPEC_NEW_PIPELINE_TEMPLATE.md`).
5. `insta-brain/CRITICAL_FACTS.md` and `insta-brain/gotchas.md`.
6. README.md only as orientation, never as final truth on operational behaviour. CLAUDE.md and the brain win on conflicts.

### 14.2 When plan mode is required

Plan mode is required before code changes that touch:

- Image sourcing, image candidate selection, image provider order, image fallbacks, manual/news slide rendering (SPEC_IMAGE_PIPELINE.md).
- The reel pipeline's footage sourcing or composition.
- Shared safety modules (verification, sourcer, publisher).
- Cross-pipeline shared code in `src/core/`, `src/render/`, `src/publish/`.
- `brand/brand_kit.json` or `src/core/brand.py`. Every renderer is downstream of these files, so every change here can affect every post format.
- A new pipeline (see section 15).

Plan mode is not required for tightly scoped fixes inside a single pipeline that do not touch shared safety code. When in doubt, plan mode.

### 14.3 Dry-run discipline

`--dry-run` first. Always. The default for any change is: produce rendered output, open it, judge it, then ship.

### 14.4 Fix the tool, not the symptom

If a value in a data file is wrong (a wrong TMDB ID, a wrong path, a wrong ID in a ledger), do not patch the value. Find the process that wrote it wrong and fix that process. Patching one bad value means the next one will be wrong too.

### 14.5 Inspection over assertion

The rendered output is the truth. A green test does not prove the carousel looks correct, the reel plays correctly, or the cover image depicts the right subject. Open the artefact and judge it.

### 14.6 Commit and push discipline

- Commit working changes with clear messages.
- Never force-push to main. Use a separate branch if history needs editing.
- Update `insta-brain/log.md` when a non-trivial change ships.
- Update README.md and any affected sub-spec in the same commit (Rule 12, living docs).

### 14.7 Memory and gotchas

If a new failure mode is discovered, record it in `insta-brain/gotchas.md` before closing the session. If a non-trivial change batch ships, record it in `insta-brain/MEMORY_INDEX.md`.

---

## 15. Adding a new post format

A new post format is added as a new pipeline, not as a fork of an existing one.

### 15.1 Required steps

1. **Write a sub-spec first.** Before any code, the new pipeline gets a sub-spec following the format of SPEC_IMAGE_PIPELINE.md. The sub-spec defines product goal, lifecycle, media intent, ledgers, success criteria, acceptance tests, and approval status. A future SPEC_NEW_PIPELINE_TEMPLATE.md will provide a fill-in template.
2. **Classify the mode.** New pipelines start in editorial approval mode by default. Autonomous mode is earned, not given.
3. **Declare the lifecycle stages.** Which of the canonical stages from section 5 apply, which are skipped, and why.
4. **Declare the media intent contract.** If the pipeline uses images or footage, it declares its intent fields and consumes shared sourcing per section 8. It does not invent its own sourcing.
5. **Declare the ledgers.** Which ledgers it writes, which invariants they guard. New ledgers are added to `data/ledgers/` with append-only semantics unless explicitly justified.
6. **Build under `pipelines/<name>/`.** The entry-point script lives there. Shared behaviour goes into `src/`.
7. **Do not start by copying an existing pipeline.** New pipelines must not start by copying and mutating an existing pipeline without a spec. Copying is allowed only after the new pipeline contract is written. Forking another pipeline is not a substitute for thinking through the new pipeline's lifecycle, media intent, ledgers, and success criteria.
8. **Declare a format block in `brand/brand_kit.json`.** A new pipeline that renders visual output adds its `formats.<format_name>` block in the same commit, per section 9.3. It does not inline style values.
9. **Update README.md, CLAUDE.md, and this spec.** New pipelines are added to section 4 and the new sub-spec is added to section 16.

### 15.2 Graduation rules

A new pipeline graduates from editorial approval mode to autonomous mode only after all of the following:

- A defined run of successful editorial-mode posts (suggested floor: 14 consecutive runs with no visual or factual failures).
- Clean ledgers across that run (no dedupe violations, no failed publishes, no manual interventions).
- No empty image boxes, no wrong-subject images, no caption errors across that run.
- Dry-runs reproduce live runs faithfully (no surprises between dry-run output and what gets posted).
- Explicit Toby approval. Graduation is recorded in the pipeline's sub-spec and in `insta-brain/log.md`.

A pipeline can be demoted back to editorial mode at any time after a visible failure. Demotion is automatic on:

- Any wrong-subject image reaching publish.
- Any empty image box reaching publish.
- Any factual error reaching publish.
- Any double-post.
- Any unplanned outage in the pipeline's posting cadence.

Demotion is recorded in the pipeline's sub-spec. Re-graduation follows the same rules as initial graduation.

---

## 16. Sub-spec index

| Sub-spec | Status | Scope |
|---|---|---|
| `SPEC_IMAGE_PIPELINE.md` | Draft, awaiting Toby approval, 2026-05-06 | Image sourcing, candidate validation, Haiku selection, typography-only fallback, manual/news image rendering. |
| `SPEC_VIDEO_PIPELINE.md` | Reserved | Reel footage sourcing, narrative beats, FFmpeg composition, voice timing, thumbnail and story rendering. |
| `SPEC_RENDERING.md` | Reserved | Brand templates, Playwright rendering, slide and reel layout, dry-run output structure. |
| `SPEC_STYLE_GUIDE.md` | Reserved | Single-source style guide. Full token schema for `brand/brand_kit.json`, per-format token tables, consumption contract for `src/core/brand.py`, smoke-render acceptance tests, migration plan from scattered inline values. |
| `SPEC_NEW_PIPELINE_TEMPLATE.md` | Reserved | Fill-in template for new pipeline sub-specs. |

Future sub-specs are added to this table as they are written.

---

## 17. Living document rule

This spec must remain accurate. It is updated whenever any of the following changes:

- A new pipeline is added or retired.
- The standard lifecycle changes.
- A pipeline graduates between editorial and autonomous modes, or is demoted.
- A safety invariant is added, removed, or revised.
- The shared module structure changes in a way a new contributor would not infer from code.
- A new sub-spec is written.
- A change is made to `brand/brand_kit.json`'s top-level structure or to the loader contract in `src/core/brand.py`.

Updates happen in the same commit as the underlying change. A line is appended to `insta-brain/log.md` describing the update.

If this document and CLAUDE.md disagree, CLAUDE.md wins on environment specifics (paths, tokens, schedules) and this document wins on principles and structure. If both disagree with the brain, the brain wins.

---

## 18. Approval

Spec written: 2026-05-06.
Approved by Toby: 2026-05-06.

Next steps are:

1. Sub-specs may be drafted in priority order: `SPEC_STYLE_GUIDE.md`, `SPEC_VIDEO_PIPELINE.md`, `SPEC_RENDERING.md`, `SPEC_NEW_PIPELINE_TEMPLATE.md`.
2. The existing `SPEC_IMAGE_PIPELINE.md` is treated as the reference style for further sub-specs.
3. Implementation work that compares the current code against this spec follows once both this document and `SPEC_IMAGE_PIPELINE.md` are approved.
4. No code changes are made on the basis of this spec until Toby approves. No template migration begins on the basis of this spec alone.
