# Rule 07 — Tooling

## Canonical Python
**Always use:** `/Library/Frameworks/Python.framework/Versions/Current/bin/python3`
Bare `python3` will not have the project's packages.

## Scripts and what they do

| Script | Purpose | When to run |
|---|---|---|
| `scripts/run_pipeline.py --topics <t1> <t2> --count <n>` | Discover → verify → generate → render → enqueue. Does NOT publish. | Once a week to refresh the queue. |
| `scripts/smoke_render.py` | Render a sample carousel from the curated bank end-to-end. | Use to eyeball visual changes after editing the renderer or template. |
| `scripts/review_queue.py {list, approve, schedule}` | Manage `data/approval_queue.jsonl`. | Daily pre-publish gate. |
| `scripts/publish_now.py --post-id <id>` | Host images on imgbb, push the carousel to Instagram, write to `posted.jsonl`. | When approving + publishing manually. |
| `scripts/publish_due.py` | Check the queue for any post with `scheduled_for ≤ now`, publish them. | Run by cron / launchd at e.g. 10:00 daily. |
| `scripts/auto_schedule_weekly.py` | Pick approved posts and assign `scheduled_for` to the next 7 weekdays. | Weekly Sunday housekeeping. |
| `scripts/check_meta_setup.py` | Validate Meta env vars are present and the access token works. | After any `.env` change. |

## Python deps (project root)
`pip install -r requirements.txt` then `playwright install chromium`. Both are one-time.

## Pipeline config
`config/pipeline.yaml` — discovery, render, scheduling, banned-claim terms.
`brand/brand_kit.json` — visual identity. Locked. Don't silently change.

## Where to look when something breaks
- A render is wrong shape → `src/render/templates/slide.html.j2`
- A fact made it through that shouldn't have → `src/verification/fact_checker.py`
- An image is wrong → `src/research/image_fetcher.py` + `src/research/used_images.py`
- A publish failed → `data/publish_failures.jsonl` + `insta-brain/log.md`
- The queue is empty → run `scripts/run_pipeline.py`
