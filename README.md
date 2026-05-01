# factjot

Automated Instagram carousel pipeline. One daily post under [@factjot](https://instagram.com/factjot), 6 self-contained verified facts plus a wholesome closing-quote slide, rendered in TJCreate's editorial style and published via Instagram Graph API. End-to-end, fully automated, all free tools.

> **Read first:** every agent and human contributor reads `insta-brain/CLAUDE.md` and `insta-brain/CRITICAL_FACTS.md` before touching this repo. The brain is the single source of truth for rules.

---

## How autonomous posting works (in plain English)

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

## End-to-end pipeline

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

## Quick start (fresh machine)

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

## Scripts (entry points)

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

## Scheduling (auto-publish)

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

## Toby vs the bot

| Toby | The bot |
|---|---|
| One-time Meta + image-host setup | All discovery, verification, generation, rendering |
| Weekly: skim `data/posts/<post_id>/` and approve | All scheduling, publishing, dedupe |
| Add ideas to `insta-brain/inbox.md` | Metric pulling, weekly reports |
| Refresh access token every ~50 days | Never invents a fact, never reposts |
| Edit `bank/*.md` for gold-standard facts | Holds posts for review when image fetcher fails |

Toby never logs into Instagram to post. He approves; the bot ships.

---

## Image source coverage

The fetcher iterates each source in this order until it finds a fresh, unused image. If every source fails for every query variant, the slide is held for review (rule 11).

1. Pexels (key) — high-quality stock
2. Pixabay (key) — big library
3. Openverse (no key) — aggregator
4. iNaturalist (no key) — biology / nature
5. NASA Images (no key) — space
6. Smithsonian (no key) — broad cultural / scientific
7. Wikipedia opensearch + REST summary (no key)
8. Wikimedia Commons file search (no key)

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
