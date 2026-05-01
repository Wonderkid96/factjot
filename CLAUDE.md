# factjot — agent operating manual

Owner: **Toby Johnson (TJCreate)**, Lincoln UK. Instagram: @factjot.
Before anything else, read `/Users/Music/.claude/CLAUDE.md` for Toby's universal rules (no em dashes, British English, voice, etc).

---

## What this project is

Fully automated Instagram account posting:
- **2 carousel posts/day** — morning (10:00 UTC) + evening (18:00 UTC)
- **1 Reel/day** — evening (19:00 UTC), with composite thumbnail + story posted automatically after

Stack: Python 3.11, Playwright + Chromium (HTML rendering), FFmpeg (Reels), ElevenLabs (voice, paid), Instagram Graph API, imgbb + tmpfiles.org (hosting).

---

## Canonical Python path

Always use:
```
/Library/Frameworks/Python.framework/Versions/Current/bin/python3
```
Never bare `python3` — packages will not be found.

---

## Daily automation — launchd jobs

| Label | Schedule | Script |
|---|---|---|
| `com.tjcreate.factjot.discover` | On demand | `scripts/discover_facts.py` |
| `com.tjcreate.factjot.plan_week` | Sunday 04:00 UTC | `scripts/plan_week.py --days 7 --start-tomorrow` |
| `com.tjcreate.factjot.publish` | Every 15 min | `scripts/publish_due.py` |
| `com.tjcreate.factjot.refresh` | Weekly | `scripts/refresh_token.py` |
| `com.tjcreate.factjot.reel` | Daily 19:00 UTC | `scripts/make_reel.py` |

Plists live in `launchd/`. Load with: `launchctl load launchd/<name>.plist`
Logs: `logs/` and `data/launchd_publish.log`.

---

## Reel pipeline — full flow

```
make_reel.py
  pick fact        → quirky_score=3 only, unused, sensitivity-safe
  build VO script  → reel_script.py (narrative build) + randomised outro
  ElevenLabs TTS   → word-level beat timestamps (edge-tts fallback if key missing)
  find 8 clips     → Pexels → Coverr → Pixabay → Wikimedia (all anchored to image_hint)
  render overlays  → Playwright: label bar, hook title, kinetic subtitles, CTA card
  FFmpeg compose   → 8 clips, animated pan-crop, alpha intro, sidechain music, fade-to-black
  thumbnail        → FFmpeg freeze frame at 1.0s + Playwright branded overlay (base64 composited)
  story PNG        → Playwright: "NEW REEL" card with same footage frame behind
  caption          → title + body + CTA + source credits + 3-tier hashtags
  upload MP4       → tmpfiles.org (direct-download URL)
  upload thumbnail → imgbb → passed as cover_url to Instagram
  publish_reel()   → Reel live on feed with branded thumbnail
  post_to_stories()→ Story fires immediately after
  ledger           → insta-brain/data/reels.jsonl
```

**Run commands:**
```bash
cd /Users/Music/Documents/Insta-bot
python3 scripts/make_reel.py                  # post next reel live
python3 scripts/make_reel.py --dry-run        # preview all 3 assets + caption, no post
python3 scripts/make_reel.py --topic earth    # force a specific topic
python3 scripts/make_reel.py --list-facts     # show all unused quirky_score=3 facts
```

---

## Key source files

| File | Purpose |
|---|---|
| `scripts/make_reel.py` | Main Reel pipeline entry point |
| `scripts/plan_week.py` | Plans 7 days of carousels + checks Reel runway |
| `scripts/publish_due.py` | Publishes scheduled carousel posts |
| `scripts/refresh_token.py` | Refreshes Meta 60-day access token |
| `src/research/rare_fact_bank.py` | 152 curated facts — source of truth |
| `src/research/narrative_beats.py` | 5 footage queries derived from `image_hint` |
| `src/research/video_finder.py` | Multi-source footage finder with relevance scoring |
| `src/content/reel_script.py` | Formats claim into dramatic VO (narrative build + ellipses) |
| `src/content/reel_title.py` | Documentary-style title generator (known titles + auto-fallback) |
| `src/content/reel_caption.py` | Caption: title + body + CTA + source credits + 3-tier hashtags |
| `src/render/tts_engine.py` | ElevenLabs primary, edge-tts fallback — returns word beats |
| `src/render/reel_composer.py` | FFmpeg composition — constants, timing, filter graph builder |
| `src/render/reel_text_renderer.py` | Playwright overlay renderer (all overlay PNGs) |
| `src/render/reel_thumbnail.py` | Footage frame base64 + branded overlay composite |
| `src/render/reel_story.py` | Story PNG renderer (same footage frame + story card) |
| `src/render/templates/reel_text_frame.html.j2` | Reel overlay template |
| `src/render/templates/reel_thumbnail.html.j2` | Thumbnail template |
| `src/render/templates/reel_story.html.j2` | Story template |
| `src/publish/instagram_publisher.py` | `publish_reel()` + `post_to_stories()` |
| `src/publish/image_host.py` | imgbb + tmpfiles with PNG salting for fresh URLs |
| `src/core/brand.py` | Brand constants — fonts, colours, dimensions |
| `src/core/paths.py` | All file paths — single source of truth |

---

## Fact bank

- **152 total facts** across space, earth, ocean, biology, history, technology
- **45 quirky_score=3** (shock/viral tier — the only ones used for Reels)
- **9 have hand-crafted `reel_script`** fields (highest quality VO — always preferred)
- **25 have hand-crafted `reel_title`** fields (documentary-style hook titles)
- `allow_archival=True` set on facts where low-quality archival footage is appropriate (Voynich Manuscript, First Photograph)

**Runway rule:** at 1 Reel/day, always keep at least 14 unused q3 facts (2 weeks buffer). `plan_week.py` checks and alerts Sunday mornings. Add facts manually to `rare_fact_bank.py` or run `discover_facts.py`.

**To add a new reel-tier fact:**
```python
{
    "topic": "history",               # space/earth/ocean/biology/history/technology
    "claim": "...",                   # 2-3 sentences, self-contained, sourced
    "sources": ["url1", "url2"],      # minimum 2 reputable sources
    "image_hint": "...",              # 3-6 words describing the visual subject
    "quirky_score": 3,                # 3 = "wait, what?" tier
    "reel_title": "...",              # optional, always use if possible
    "reel_script": "...",             # optional, write for drama + ellipses
}
```

---

## Footage quality rules

- All 5 beat queries are anchored to `image_hint` — they never drift to generic topic b-roll
- Non-archival (default): 800KB minimum, Archive.org skipped, NASA space-only
- Archival (`allow_archival=True`): 50KB minimum, all sources enabled
- `used_source_urls` set prevents same video appearing twice per Reel
- Pexels fetches 15 results per query to allow deduplication to find alternatives

---

## Reel timing constants

| Constant | Value | Meaning |
|---|---|---|
| `INTRO_S` | 3.5s | Silent window — hook title visible, voice starts after |
| `MUSIC_VOLUME` | 0.24 | Background music (sidechain-ducked under voice) |
| `FADE_TO_BLACK_S` | 1.5s | Final fade duration |
| `KEN_BURNS_ZOOM` | 0.10 | 10% overscan — subtle pan, not shaky |
| CTA timing | dynamic | Card appears when narrator says "factjot" (word-beat sync) |
| Total duration | `voice_end + 0.8 + 1.5s` | Tight — no dead air after voice |

---

## Label design — full-width carousel-style header

`factjot. [────────────────────] TOPIC`

- Left: Instrument Serif wordmark (`fact` regular, `jot` italic, `.` accent red)
- Middle: `flex: 1 1 auto` separator line (off-white, opacity 0.38) — expands full width
- Right: JetBrains Mono uppercase, letter-spacing 0.18em
- Position: `top: 88px; left: 56px; right: 56px` (matches carousel slides exactly)

---

## Typography — strict brand rule

| Font | Use | File |
|---|---|---|
| Instrument Serif Regular + Italic | Hook titles, wordmark, title cards | `assets/fonts/InstrumentSerif-*.ttf` |
| Space Grotesk SemiBold 600 | Subtitles, body text | `assets/fonts/SpaceGrotesk-SemiBold.ttf` |
| JetBrains Mono Bold 700 | Labels, badges, tags | `assets/fonts/JetBrainsMono-Bold.ttf` |

Wordmark: `fact`*`jot`*`.` — "jot" italic, "." in `#E6352A`, base off-white `#EDE8DD`.
Brand colours: PAPER `#F4F1E9` INK `#0A0A0A` ACCENT `#E6352A` LIME `#C8DB45` LILAC `#C4A9D0`.
Shadow style: hard drop `2px 2px 0 rgba(0,0,0,0.5)` — matches carousels, no blur.

---

## API keys (all in `.env`)

| Key | Service | Notes |
|---|---|---|
| `META_ACCESS_TOKEN` | Instagram Graph API | 60-day rolling. Refresh weekly via `refresh_token.py`. |
| `ELEVENLABS_API_KEY` | Voice | Paid. Voice ID: `3WqHLnw80rOZqJzW9YRB`. ~500 chars/reel. |
| `PEXELS_API_KEY` | Primary footage | Free, 200 req/hr |
| `COVERR_API_KEY` | Secondary footage | Demo, 1,000 calls/month |
| `PIXABAY_API_KEY` | Tertiary footage | Free |
| `IMGBB_API_KEY` | Thumbnail + story hosting | Free |
| `MUSIC_CREDIT` | Caption credit line | Set to "Track · Artist" for background music |

**Token failure:** if `refresh_token.py` returns "API access blocked", the account was rate-limited by rapid API calls. Wait 30 min, then retry. If still blocked, regenerate via `setup_token.py` with a fresh short-lived token from developers.facebook.com → factjot app → Instagram → API Setup.

---

## Caption structure

Every Reel caption:
```
[Title or first sentence of claim]
[1 punchy sentence — the most striking detail]

[Randomised CTA — "Follow @factjot..."]

📚 Source: [Publisher names from sources field]
📹 Footage: Pexels.com
🎵 Music: [MUSIC_CREDIT from .env, if set]

[3-tier hashtags: broad + topic + subject-specific]
```

Hashtags are 3-tier: 5 broad (`#facts #didyouknow`) + 5 topic (`#earthscience`) + 5 subject-specific extracted from the claim/title (`#supervolcano #humanevolution`).

---

## Invariants — never break

1. Never repost a fact — check `insta-brain/data/posted.jsonl`.
2. Never reuse a carousel image — check `data/ledgers/used_images.jsonl`.
3. Every fact must be 100% true — 2+ reputable sources, confidence ≥ 0.65.
4. No em dashes — anywhere, ever.
5. British English throughout all copy.
6. Append-only ledgers — never edit historical lines.
7. Three fonts only — brand-locked.
8. Reels use `quirky_score=3` facts only.
9. Always use the full Python path.
10. `--dry-run` first if you're unsure — it generates all assets without posting.

---

## What is NOT yet done (next session)

- Stories on carousel posts — `publish_due.py` doesn't post stories after carousels yet
- Weekly reel schedule planner — `plan_week.py` checks runway but doesn't pre-assign facts to days
- Carousel story images — no template exists yet for carousel story cards

---

## Directory map

```
src/research/       Fact bank, video finder, narrative beats, sensitivity guide
src/content/        Script, title, caption generators
src/render/         Playwright renderers, FFmpeg composer, thumbnail, story
src/publish/        Instagram Graph API, image hosting
src/core/           Brand, paths, config, models
assets/fonts/       Brand fonts
assets/music/       default.mp3 — Reel background music
assets/intros/      factjot_intro.mov — ProRes 4444 alpha intro overlay
assets/video/       Safety footage pool (fallback)
data/cache/reels/   Per-reel output — final.mp4, thumbnail.png, story.png, footage
data/ledgers/       Append-only records
insta-brain/        Brain + ledgers
launchd/            macOS launchd plists
logs/               Job stdout/stderr
config/             pipeline.yaml — schedule, thresholds, settings
brand/              brand_kit.json (locked)
```
