# factjot

Automated Instagram carousel pipeline. One daily post under [@factjot](https://instagram.com/factjot), 6 self-contained verified facts plus a wholesome closing-quote slide, rendered in TJCreate's editorial style and published via Instagram Graph API. End-to-end, fully automated, all free tools.

> **Read first:** every agent and human contributor reads `insta-brain/CLAUDE.md` and `insta-brain/CRITICAL_FACTS.md` before touching this repo. The brain is the single source of truth for rules.

> ## README is being modernised, read this notice first
>
> This document is partly legacy. The system has changed since several sections below were written. Until this README is fully updated, treat the following as authoritative:
>
> - **Production scheduler is GitHub Actions, not local launchd.** The launchd plist install steps, `scripts/publish_due.py`, `scripts/review_queue.py`, and the queue-based "approve then publish" flow described in this README are **legacy** unless explicitly revived. Autonomous posting now happens entirely from GitHub Actions runners. See `CLAUDE.md` "Daily automation" and `SPEC_FACTJOT_SYSTEM.md` section 6 for the current flow.
> - **Pipeline entrypoints live under `pipelines/<name>/`, not `scripts/`.** Most rows in this README's "Scripts" table point at `scripts/<name>.py` paths that no longer exist there. The current entrypoints are `pipelines/carousel/ship_carousel_post.py`, `pipelines/reel/make_reel.py`, plus shared operational scripts in `pipelines/shared/`.
> - **Manual / editorial carousels are gated, autonomous pipelines are not.** Approval today means a human inspecting rendered output before publish, only for editorial content. Scheduled autonomous slots currently run reel/list/reel/list/reel; breaking news posts are watcher-triggered, not scheduled. The old queue/approve-and-ship rhythm is legacy.
> - **Higher authority on current architecture:** `SPEC_FACTJOT_SYSTEM.md` (system constitution) and `CLAUDE.md` (project operating rules). On any conflict, prefer the spec, then `CLAUDE.md`, then this README.
> - **Image provider order and manual carousel image behaviour are owned by `SPEC_IMAGE_PIPELINE.md`.** The "Image source coverage" list further down may be stale and is being deferred to the spec.
> - **`pipelines/news/ship_news_post.py` currently has dual responsibility** as the breaking-news implementation and the renderer used by the manual carousel pipeline. The canonical workflow entrypoint is `pipelines/news/ship_news_breaking.py` (wrapper). This remains a known architecture risk to untangle deliberately, not in passing.
>
> Sections describing the older flow are tagged **[LEGACY]** below. They are kept for reference, not because they reflect today's behaviour.

---

## Manual prompt runs (GitHub Actions)

Use workflow dispatch on `.github/workflows/manual-run.yml` when you want Claude-style "run this prompt now" execution without touching schedule wiring.

- `pipeline=carousel_fact|carousel_list|carousel_news` with `brief` input runs `pipelines/carousel/ship_carousel_post.py`.
- `pipeline=reel` with `script` + `title` runs `pipelines/reel/make_reel.py`.
- Keep `dry_run=true` for previews; set `dry_run=false` only when ready to publish.
- For local list validation speed, use `--smoke-mode` with dry-run (`pipelines/carousel/ship_carousel_post.py --type list --brief "..." --dry-run --smoke-mode`).
- Rendered artefacts are uploaded as a workflow artifact and written under `output/{manual,news,reel}/...`.

### Current autonomous daily schedule

`autonomous-reel.yml` runs five fixed slots per day:

- `reel_morning` (09:00 BST)
- `list_midday` (12:30 BST)
- `reel_afternoon` (15:30 BST)
- `list_evening` (18:00 BST)
- `reel_night` (20:30 BST)

### Reel format for list ideas

When static list posts are paused, convert list concepts into a 3-item reel script:

```text
Hook: one sentence with the weird bit and list frame.
Item 1: proper noun + hard fact.
Item 2: proper noun + hard fact.
Item 3: proper noun + hard fact.
Close: one sentence with the pattern or consequence.
```

Rules:
- keep total script length 70 to 120 words
- use 3 items only for reel pacing
- each item must include at least one named entity and one concrete number/date/fact
- no teaser language or "number X" filler

Example:

```text
Three engineering disasters killed more people than many wars, and each one followed ignored warnings. Banqiao Dam failed in 1975 after extreme rain, and up to 170,000 people died in the floods that followed. Chernobyl exploded in 1986 and forced around 350,000 people to evacuate permanently. Bhopal leaked methyl isocyanate in 1984, and at least 15,000 people died over time. The pattern is not bad luck, it is systems choosing to ignore known risk.
```

---

## Quick troubleshooting (current pipelines)

| Symptom | Expected guardrail | Action |
|---|---|---|
| `RuntimeError: OVERCAP_SLIDE_LINES` | `compact_legacy` cap blocked an unreadable slide | Shorten the brief wording and re-run. The gate is working as intended. |
| Reel aborts `below floor` duration | Reel quality gate rejected too-short composition | Re-run with a longer script or richer topic facts; keep floor unchanged. |
| List dry-run takes too long in image sourcing | Multi-round provider search still active | Keep run as dry-run and inspect logs/artifacts; if repeated, re-run with a more concrete brief. |
| No breaking-news post appears | Watcher found no qualifying Guardian story | Run `news-watcher.yml` manually with `article_url` input to force a test post path. |
| Workflow succeeds but no state commit | No tracked ledger files changed | This is normal; no action needed. |

---

## How autonomous posting works (in plain English) [LEGACY trigger description]

> **[LEGACY]** This section describes the original local-launchd flow. The Graph API mechanics (imgbb upload, `/media` child containers, `/media` carousel parent, `/media_publish`) are still accurate. The trigger is no longer launchd; GitHub Actions fires `pipelines/<name>/ship_*.py` entrypoints on cron. See `CLAUDE.md` "Daily automation" for the current flow.

The API route is **Meta's Instagram Graph API**. It is the only sanctioned, supported, free way to post to Instagram from a script.

When a scheduled post fires:

1. **At the scheduled time** (e.g. 10:00 local), a launchd job on your Mac wakes up and runs `scripts/publish_due.py`.
2. The script reads `insta-brain/data/queue.jsonl`, finds posts where `scheduled_for ≤ now`, picks the next one.
3. **Uploads the 7 PNGs to imgbb** (free image host). imgbb returns 7 public URLs.
4. **POSTs each URL to Instagram's `/media` endpoint** with `is_carousel_item=true`. Meta returns 7 child container IDs.
5. **POSTs once more to `/media`** with `media_type=CAROUSEL`, all 7 children, plus the caption. Meta returns one carousel container ID.
6. **POSTs to `/media_publish`** with that container ID. Meta publishes the post and returns an `ig_media_id`.
7. The script writes the success to `posted.jsonl`, `posted_quotes.jsonl`, and `log.md`.

No browser automation, no third-party scheduler, no manual step. Just HTTP calls to Meta from your Mac.

---

## End-to-end pipeline [LEGACY single-pipeline view]

> **[LEGACY]** The diagram and table below describe the older fact-carousel-only pipeline. The current system runs five pipelines (reels, fact carousel, list, news, manual) and the canonical lifecycle has nine stages: `SOURCE → VERIFY → GENERATE → ACQUIRE MEDIA → RENDER → (APPROVE) → PUBLISH → LEDGER → MEASURE`. See `SPEC_FACTJOT_SYSTEM.md` section 5 for the current lifecycle. Several `scripts/<name>.py` paths in the table no longer exist there; current entrypoints are under `pipelines/<name>/`. Render output is now `output/<pipeline>/...` not `data/renders/...`.

```
DISCOVER → VERIFY → GENERATE → RENDER → APPROVE → PUBLISH → MEASURE
```

| Stage | Code | Brain interaction |
|---|---|---|
| **Discover** facts | `src/research/fact_discovery.py`, `src/research/rare_fact_bank.py`, `insta-brain/bank/*.md` | Reads `posted.jsonl` to skip reposts (rule 01) |
| **Verify** ≥ 2 sources | `src/verification/fact_checker.py` | Stateless; rule 10 (truth) |
| **Generate** copy | `src/content/carousel_generator.py`, `src/content/quotes.py` | Reads `posted_quotes.jsonl` to skip used quotes |
| **Fetch** photos | `src/research/image_fetcher.py`, `src/research/used_images.py` | Reads + writes `used_images.jsonl` (rule 02, 11) |
| **Render** to PNG | `src/render/render_carousel.py`, `src/render/templates/*.html.j2` | Writes per-post folders under `data/renders/<nnn>_<date>_<category>_<series>_<post_id>/` (rule 04) |
| **Bundle** post | `data/posts/<post_id>/post.yaml` + `slides/*.png` | Hand-editable artefact |
| **Approve** human gate | `scripts/review_queue.py` | Updates `queue.jsonl` row status |
| **Publish** to IG | `scripts/publish_now.py`, `scripts/publish_due.py`, `src/publish/instagram_publisher.py`, `src/publish/image_host.py` | Appends `posted.jsonl`, `log.md` (rule 05) |
| **Measure** | `scripts/fetch_metrics.py` | Appends `stats.jsonl` |
| **Report** | `scripts/weekly_report.py` | Writes `reports/weekly/<iso-week>.md` |

The full step-by-step is in `insta-brain/PUBLISH_PLAN.md`. This README is the orientation; the brain is the manual.

---

## Quick start (fresh machine) [PARTLY LEGACY]

> **[LEGACY]** Steps 3-6 below reference `scripts/<name>.py` paths and a launchd-based auto-publish loop. Operational scripts moved to `pipelines/shared/<name>.py`, and autonomous publishing is now run by GitHub Actions, not launchd. The Python venv and Playwright install steps are still correct.

```bash
# 1. Python deps
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# 2. Credentials (see Setup)
cp .env.example .env
# edit .env to fill in keys

# 3. Verify Meta setup
python3 scripts/check_meta_setup.py

# 4. Generate one week of posts
python3 scripts/plan_week.py

# 5. Approve
python3 scripts/review_queue.py list
python3 scripts/review_queue.py approve --post-id <id>

# 6. Auto-publish runs every 15 min via launchd (see Scheduling)
```

**Always use the canonical Python path** in scripts and cron:
`/Library/Frameworks/Python.framework/Versions/Current/bin/python3`

---

## Setup (one-time, all free)

### Meta / Instagram Graph API
1. Convert @factjot to a Professional account (Business or Creator).
2. Link it to a Facebook Page Toby controls.
3. Create a Meta Developer app at https://developers.facebook.com/apps/ (Business type).
4. Add the **Instagram Graph API** product to the app.
5. Generate a long-lived access token (~60 day expiry) with scopes:
   `instagram_content_publish`, `instagram_basic`, `pages_read_engagement`, `pages_show_list`.
6. Note the numeric IG Account ID and Facebook Page ID.

### Image hosts
| Service | URL | Required? |
|---|---|---|
| imgbb (hosts the PNGs Meta fetches) | https://api.imgbb.com/ | **Yes** |
| Pexels (high-quality stock) | https://www.pexels.com/api/ | Strongly recommended |
| Pixabay (huge stock library) | https://pixabay.com/api/docs/ | Strongly recommended |
| Smithsonian (optional higher rate) | https://api.si.edu/openaccess/api/v1.0/getsignup | Optional |

### Sources used WITHOUT keys
- NASA Images API (excellent for SPACE)
- Smithsonian Open Access (DEMO_KEY tier)
- iNaturalist (perfect for NATURE)
- Openverse (aggregates Flickr / Wikimedia / Europeana)
- Wikipedia opensearch + Wikimedia Commons

### .env
See `.env.example`. Bot will refuse to publish unless `INSTAGRAM_ACCOUNT_ID`, `META_ACCESS_TOKEN`, `IMGBB_API_KEY` are present.

---

## Scripts (entry points) [PARTLY LEGACY, paths stale]

> **[LEGACY paths]** Almost every row below names a path under `scripts/`. The `scripts/` directory is now effectively empty, the operational scripts have moved. Current locations:
>
> | Old path in this table | Current path |
> |---|---|
> | `scripts/plan_week.py` | `pipelines/shared/plan_week.py` |
> | `scripts/smoke_render.py` | `pipelines/carousel/smoke_render.py` |
> | `scripts/review_queue.py` | `pipelines/shared/review_queue.py` (legacy queue, not used by autonomous flow) |
> | `scripts/publish_now.py` | `pipelines/shared/publish_now.py` (legacy, manual override only) |
> | `scripts/publish_due.py` | `pipelines/shared/publish_due.py` (legacy, launchd-era) |
> | `scripts/check_meta_setup.py` | `pipelines/shared/check_meta_setup.py` |
> | `scripts/auto_schedule_weekly.py` | `pipelines/shared/auto_schedule_weekly.py` |
> | `scripts/refresh_token.py` | `pipelines/shared/refresh_token.py` |
>
> Posting entrypoints (which the table below does not list) are in `pipelines/<pipeline>/`: `ship_carousel_post.py` (carousel), `make_reel.py` (reel), `ship_news_breaking.py` (watcher-triggered breaking news). Legacy files remain on disk (`ship_first_post.py`, `ship_list_post.py`, `ship_news_post.py`, `ship_manual_post.py`) but are not scheduled autonomous production entrypoints.
>
> `scripts/run_pipeline.py`, `scripts/fetch_metrics.py`, and `scripts/weekly_report.py` are not in the live `scripts/` directory. Their successors (where they exist) are in `pipelines/reel/fetch_reel_metrics.py` and the `weekly-plan.yml` workflow. The "Auto-fired by launchd" notes are legacy.
>
> The original table is preserved below for reference until this section is fully rewritten.

| Script | Purpose | When to run |
|---|---|---|
| `scripts/plan_week.py` | Generate 7 carousels for the next 7 days | Sunday morning, weekly |
| `scripts/run_pipeline.py --topics ... --count N` | Single-run discovery → render → enqueue | Ad hoc |
| `scripts/smoke_render.py` | Render samples from the curated bank to eyeball visual changes | After renderer edits |
| `scripts/review_queue.py {list, approve, schedule}` | Inspect / approve / kill queued posts | Daily, pre-publish |
| `scripts/publish_now.py --post-id <id>` | Force-publish a specific post immediately | Manual override |
| `scripts/publish_due.py` | Publish all posts whose `scheduled_for ≤ now` | Auto-fired by launchd every 15 min |
| `scripts/fetch_metrics.py` | Pull IG insights for posts < 7 days old | Auto-fired by launchd nightly 22:00 |
| `scripts/weekly_report.py` | Aggregate stats into `reports/weekly/<iso>.md` | Sunday 23:00 |
| `scripts/check_meta_setup.py` | Validate `.env` and token | After any `.env` change |
| `scripts/auto_schedule_weekly.py` | Assign optimal slots to approved posts | Sunday housekeeping |
| `scripts/refresh_token.py` (TBD) | Refresh long-lived Meta token | Every ~50 days |

---

## Folder map

> **Updated.** The current top-level structure includes a `pipelines/` directory that holds every post-type entrypoint. The original tree below did not show it. Rendered output now lives under `output/<pipeline>/...`, and the in-flight `data/posts/` / `data/renders/` paths have largely been replaced by `output/` and `data/ledgers/`. The original tree is preserved below for reference; treat it as orientation, not the live layout.

Current top-level layout (high signal):

```
Insta-bot/
├── README.md                      # this file (partly legacy, see notice)
├── CLAUDE.md                      # project-level operating rules (current)
├── SPEC_FACTJOT_SYSTEM.md         # system constitution (current)
├── SPEC_IMAGE_PIPELINE.md         # image pipeline sub-spec
├── insta-brain/                   # operating manual + ledgers + rules + bank
├── brand/brand_kit.json           # locked visual identity (single source of truth)
├── assets/                        # fonts, music, intros, safety footage
├── config/pipeline.yaml           # pipeline knobs
├── .github/workflows/             # GitHub Actions (production scheduler)
├── launchd/                       # macOS launchd plists (legacy, not used)
├── src/                           # shared modules (core, research, content, render, publish, verification, utils)
├── pipelines/                     # post-type entrypoints (current home)
│   ├── reel/                      # make_reel.py + reel-only helpers
│   ├── carousel/                  # ship_first_post.py (morning fact carousel) + helpers
│   ├── list/                      # ship_list_post.py (evening list) + pack tooling
│   ├── news/                      # ship_news_post.py (news + currently shared as manual renderer)
│   ├── manual/                    # ship_manual_post.py (legacy module wrapped by ship_carousel_post.py)
│   └── shared/                    # cross-pipeline ops (publish, token, idempotency, status, etc.)
├── output/                        # per-run rendered artefacts (gitignored, local only)
├── data/                          # repo-tracked state (ledgers + caches)
└── scripts/                       # mostly legacy, now contains very little (kill_local_reel_jobs.sh)
```

Original tree (legacy view, kept for reference):

```
Insta-bot/
├── README.md                      # this file (rule 12: keep up to date)
├── CLAUDE.md                      # repo-level rules
├── insta-brain/                   # operating manual + ledgers + rules + bank
│   ├── CLAUDE.md                  # brain operating manual (always read first)
│   ├── CRITICAL_FACTS.md          # invariants, hard rules
│   ├── PUBLISH_PLAN.md            # full end-to-end publish steps
│   ├── rules/                     # numbered rules, each its own file
│   ├── bank/                      # hand-curated facts + quotes
│   ├── data/                      # append-only ledgers
│   ├── reports/weekly/            # auto-generated weekly performance reports
│   ├── inbox.md                   # frictionless idea capture
│   └── log.md                     # rolling agent activity log (newest at top)
├── brand/brand_kit.json           # locked visual identity
├── assets/fonts/                  # Instrument Serif, JetBrains Mono
├── config/pipeline.yaml           # pipeline knobs
├── launchd/                       # macOS launch agent plists
├── src/
│   ├── brain.py                   # single API for posted/used/quote dedupe
│   ├── core/                      # config, models, json store
│   ├── research/                  # fact discovery, image fetcher, dedupe ledgers
│   ├── content/                   # carousel generator, quotes, image relevance
│   ├── verification/              # fact checker
│   ├── render/                    # HTML+Playwright renderer + templates
│   ├── publish/                   # IG Graph API client + image host (imgbb)
│   ├── review/                    # approval queue, scheduler
│   ├── analytics/                 # performance tracker, alerting
│   └── utils/                     # logging, retry helpers
├── scripts/                       # entry points (one purpose each)
└── data/                          # runtime artefacts
    ├── posts/<post_id>/           # per-post bundles (post.yaml + slides/)
    ├── renders/<nnn>_<date>_<category>_<series>_<post_id>/slide_XX.png  # rendered slides per post
    ├── images/<category>/<post_id>/                                # cached source photos per post
    └── used_images.jsonl          # global image dedupe ledger
```

---

## Rules summary

Full text in `insta-brain/rules/`. One-line summaries:

| # | Rule | One-liner |
|---|---|---|
| 01 | No repost | Hash check `posted.jsonl` before generation |
| 02 | No image reuse | Hash check `used_images.jsonl` (URL + content SHA) |
| 03 | Voice | Direct, dry, British English, no em dashes, banned phrases |
| 04 | Visual design | Locked palette, fonts, layout. Brand kit is source of truth |
| 05 | Publishing | Graph API only. Free hosting only |
| 06 | Data capture | What writes where, append-only |
| 07 | Tooling | Canonical Python path, what each script does |
| 08 | Content pipeline | The five stages; never skip one |
| 09 | Prompt read order | Files an agent loads at session start |
| 10 | Truth | Every fact 100% verified, ≥ 2 sources |
| 11 | No naked slides | Never ship a slide without a real photo |
| 12 | Living docs | Keep this README and the brain in sync (see below) |
| 13 | Memory index discipline | Every non-trivial change batch must be recorded in `insta-brain/MEMORY_INDEX.md` |

---

## Rule 12 — Living docs

This README and the `insta-brain/` folder are non-negotiable to keep current. Whenever any of the following changes, update both in the same commit:

- A new script in `scripts/`
- A new module under `src/`
- A new data ledger or schema change
- A new rule file in `insta-brain/rules/`
- A new env var in `.env.example`
- A behaviour change a new contributor would not infer from code

Specifically:
- Add the script to the **Scripts** table.
- Add the rule's one-liner to the **Rules summary** table.
- Update the **Folder map** if the directory tree changes.
- Append one line to `insta-brain/log.md` describing the change.

If you add a feature without updating the docs, future agents will not know it exists. The brain breaks. Don't break the brain.

---

## Scheduling (auto-publish) [LEGACY]

> **[LEGACY]** This entire section describes the launchd-based local publishing flow, which is **disabled**. Autonomous posting is now run by GitHub Actions, triggered primarily by cron-job.org with GitHub's built-in cron as backup. Do not install the launchd plist; doing so while the GitHub workflows are live will cause double-posts (this happened on 2026-05-05). For the current schedule and workflow inventory, see `CLAUDE.md` "Daily automation". The block below is preserved for reference only.

A macOS launchd job at `launchd/com.tjcreate.factjot.publish.plist` fires `scripts/publish_due.py` every 15 minutes.

Default optimal slots (set in `config/pipeline.yaml`):
- **Mon-Fri 10:00 local**
- **Sat-Sun 11:00 local**

Both are proven IG sweet spots for educational accounts.

To install:
```bash
cp launchd/com.tjcreate.factjot.publish.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.tjcreate.factjot.publish.plist
```

---

## Toby vs the bot [PARTLY LEGACY]

> **[LEGACY]** "Weekly: skim and approve" describes the old queue/approve cadence. Today the autonomous pipelines (reels, fact carousel, list carousel, news carousel) post without per-run approval; only manual / editorial carousels are gated, and approval there means inspecting the rendered output before publishing. See `SPEC_FACTJOT_SYSTEM.md` section 6 for the two-mode model.

| Toby | The bot |
|---|---|
| One-time Meta + image-host setup | All discovery, verification, generation, rendering |
| Weekly: skim `data/posts/<post_id>/` and approve | All scheduling, publishing, dedupe |
| Add ideas to `insta-brain/inbox.md` | Metric pulling, weekly reports |
| Refresh access token every ~50 days | Never invents a fact, never reposts |
| Edit `bank/*.md` for gold-standard facts | Holds posts for review when image fetcher fails |

Toby never logs into Instagram to post. He approves; the bot ships.

---

## Image source coverage [DEFERRED to spec]

> **Source of truth: `SPEC_IMAGE_PIPELINE.md` section 6.** The current image provider order, validation rules, and licence policy for the manual carousel image pipeline are owned by that spec, not by this README. The list previously published here was inconsistent with the spec (it placed Pexels first, while the spec places Wikimedia first and excludes Pexels for images). To avoid agents following a stale order, the list has been removed from this README. Pexels remains a footage source for reels, governed by `CLAUDE.md` "Footage quality rules" until `SPEC_VIDEO_PIPELINE.md` is written.

---

## Troubleshooting

| Symptom | Where to look |
|---|---|
| Render is wrong shape / colours | `src/render/templates/slide.html.j2`, `brand/brand_kit.json` |
| Wrong/abstract image on a slide | `src/research/image_fetcher.py::_query_variants`, set Pexels + Pixabay keys |
| Wrong fact through gate | `src/verification/fact_checker.py`, `insta-brain/rules/10-truth.md` |
| Publish failed | `data/publish_failures.jsonl`, `insta-brain/log.md`, then `scripts/check_meta_setup.py` |
| Queue empty | `scripts/plan_week.py` |
| Token expired | Re-run OAuth, update `.env`, restart launchd |

---

Built by Toby Johnson (TJCreate) with Claude. Visual identity inherited from [tjcreate.co.uk](https://tjcreate.co.uk).
