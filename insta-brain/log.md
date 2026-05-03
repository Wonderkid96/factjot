# factjot agent log

- 2026-05-03 09:32 published 1b93e83f64f352 (TECH, 7 slides, ig_media=18164597572437186)
- 2026-05-03 morning: HALTED brain_stale (video_finder.py newer than log.md); alert appended, no discovery run
- 2026-05-02 22:04 reel 4334c81e57a585 published biology mantis shrimp ig=18083655689091763
- 2026-05-02 22:02 reel FAILED publish — fact='The mantis shrimp punches with the speed of a bullet, accele' topic=biology video_url=https://tmpfiles.org/dl/36224201/final.mp4 error=Reel not ready after 300s: {'ok': False, 'error': {'status_code': 'ERROR', 'status': 'ERROR', 'id': '18097169149917064'}}
- 2026-05-02 21:53 reel 7f219dd429d897 published (space, ig_media=18317490070260182)
- 2026-05-02 21:39 reel 93a193f9096433 published (space, ig_media=18388463002091149)
- 2026-05-02 20:49 reel SHIPPED 'Nine Brains, Eight Decisions' (octopus, biology) → https://www.instagram.com/reel/DX2ahirE5uV/  | FIX: Meta URL-fetch threshold tightened to ~5MB; reels now encoded at crf 30 maxrate 800k (~4-5MB for 60s); Cloudinary + tmpfiles both 413 anything >5MB
- 2026-05-02 20:42 reel FAILED publish — fact='Octopuses have nine brains. One central brain plus a smaller' topic=biology video_url=https://tmpfiles.org/dl/36217422/final.mp4 error=Reel not ready after 300s: {'ok': False, 'error': {'status_code': 'ERROR', 'status': 'ERROR', 'id': '18097155631917064'}}
- 2026-05-02 20:40 reel FAILED publish — fact='In 1908 something exploded above remote Siberia with the for' topic=space video_url=https://tmpfiles.org/dl/36217279/final.mp4 error=Reel not ready after 300s: {'ok': False, 'error': {'status_code': 'ERROR', 'status': 'ERROR', 'id': '18097155262917064'}}
- 2026-05-02 20:35 reel FAILED publish — fact='In 1908 something exploded above remote Siberia with the for' topic=space video_url=https://res.cloudinary.com/dmzer6hgv/video/upload/v177775410 error=Reel not ready after 300s: {'ok': False, 'error': {'status_code': 'ERROR', 'status': 'ERROR', 'id': '18097154578917064'}}
- 2026-05-02 20:32 reel FAILED publish — fact='In 1908 something exploded above remote Siberia with the for' topic=space video_url=https://res.cloudinary.com/dmzer6hgv/video/upload/v177775394 error=Reel not ready after 300s: {'ok': False, 'error': {'status_code': 'ERROR', 'status': 'ERROR', 'id': '18097154266917064'}}
- 2026-05-02 20:13 WORKFLOW FAILED: .github/workflows/reel.yml | run=25260791652 | trigger=workflow_dispatch | ref=main
- 2026-05-02 20:13 reel FAILED publish — fact='In 1908 something exploded above remote Siberia with the for' topic=space video_url=https://res.cloudinary.com/dmzer6hgv/video/upload/v177775279 error=Reel not ready after 300s: {'ok': False, 'error': {'status_code': 'ERROR', 'status': 'ERROR', 'id': '18097149712917064'}}
- 2026-05-02 18:05 published abbfe0cb3c1bd8 (TECH, 2 slides, ig_media=17912739300385468)
- 2026-05-02 15:50 published 19d537d2558d19 (HISTORY, 7 slides, ig_media=18358128016230728)
- 2026-05-02 15:47 published 089e4295b0aee4 (EARTH, 6 slides, ig_media=17883422796395247)
- 2026-05-02 reel quality hardening: 34 q3 facts backfilled with curated reel_script (>=70 words) + reel_title. make_reel._pick_fact now refuses facts missing either; auto-fallback path removed. Hard duration gate < 35s aborts. Em-dashes stripped from caption output (audit found 2 in CTA pool). Sensitivity gate added (matches plan_week). Ledger write order fixed (reels.jsonl first, atomic O_APPEND). Publisher recovery race fixed via media_type filter. TTS fallbacks logged. validate_reel_facts.py CLI added. Replacement reel "The Demon Core" (52.6s) published live ig_media=18075000272243034 to verify the new pipeline.
- 2026-05-02 13:08 carousel BLOCKED (duplicate) post_id=f61e6abc487d1f
- 2026-05-02 09:00 morning: discovery +0, carousel runway: lowest=technology(1), reel runway 3.9 weeks
- 2026-05-01 20:22 reel ee890ddbbfd464 published (space, ig_media=18075000272243034)
- 2026-05-01 19:15 reel a9f7e51e6108a2 published (history, ig_media=18096805417929895)
- 2026-05-01 19:14 dedup hardened: DuplicatePostError gate added to brain.py (fresh disk read). Wired into make_reel.py, ship_first_post.py, publish_due.py. All publish paths now hard-abort on any duplicate — even spontaneous requests.
- 2026-05-01 19:30 DEDUP FIX: brain.list_reel_claims() added. make_reel._record() now writes reel claims to posted.jsonl (blocks carousels too). Toba + Radium Girls backfilled into posted.jsonl. Routines updated with explicit Reel/Carousel/List terminology. CRITICAL_FACTS.md locked terminology table added.
- 2026-05-01 19:03 reel 539e56ba22b1e0 published (history, ig_media=17883372633397966)
- 2026-05-01 18:59 evening: published 057a6b16b76fa4 (ocean, ig=17945912973178658)
- 2026-05-01 18:59 published 057a6b16b76fa4 (OCEAN, 7 slides, ig_media=17945912973178658)
- 2026-05-01 16:17 weekly recheck: token VALID (~59 days, factjot), status green, 13 scheduled in queue, 126 fresh = ~10 days at 2/day. Earlier 13:08 token failure was the rate-limit cleared by the parallel reel-pipeline session. weekly_state.json flipped failed -> ok.
- 2026-05-01 16:16 token refreshed: new expiry ~59 days
- 2026-05-01 19:00 routines updated: AM now does discovery+health check only (no ship_first_post — launchd handles carousels). PM now does status monitoring only. Weekly topup updated with shock-test quality standard for new facts and reel runway check. All three routines set to run fully autonomously with no approval prompts.
- 2026-05-01 18:30 quality hardening: 11 weak/textbook facts downgraded to quirky_score=0 (bananas radioactive, cows 360° vision, hummingbirds, flamingos, etc). plan_week.py now sorts carousels by quirky_score desc — strongest facts always go out first. Shock test criteria documented in rare_fact_bank.py docstring. insta-brain/CLAUDE.md rewritten with mandatory freshness gate rules and Reel pipeline docs. check_brain_fresh.py passes.
- 2026-05-01 18:00+ session end: full Reel pipeline built and live. 2 reels published. Daily 19:00 UTC launchd job loaded. 21 new q3 facts added (152 total, 36 unused q3). CLAUDE.md rewritten. CRITICAL_FACTS.md updated (cadence, paid services). MEMORY_INDEX.md updated with full change log. Brain is current.
- 2026-05-01 15:47 reel 539e56ba22b1e0 published (history, ig_media=18139721830518880)
- 2026-05-01 15:38 reel fd515a94e464e6 published (earth, ig_media=18073737497269159)
- 2026-05-01 15:37 token refreshed: new expiry ~60 days
- 2026-05-01 13:17 weekly: top-up +44 facts (space=0, earth=15, ocean=15, biology=0, history=0, technology=14), token refresh FAILED (API access blocked, alert logged), plan_week scheduled 14 new carousels (0 skipped), runway 12 days (bank-only) -> ~10 days at 2/day (126 fresh after merge)
- 2026-05-01 13:05 session start: read-order complete, working on weekly top-up
- 2026-05-01 10:05 style guide compliance enforced: Space Grotesk added to assets/fonts (SemiBold + Medium) for subtitles. Instrument Serif for display/titles. JetBrains Mono for labels. CTA wordmark fixed to @factjot. in off-white with red dot and italic jot — per brand_kit.json wordmark spec. Hook text positioned top:220px to clear label. All three fonts now wired in reel_text_renderer.py and reel_text_frame.html.j2. Music deferred until usage resets.
- 2026-05-01 09:46 story pipeline audit: unified 9:16 story-frame handoff across ship_first_post/publish_due/publish_now/ship_list_post, removed story text overlays (logo + NEW POST only), centred composition, aligned NEW POST to card-right, and surfaced explicit warning that Graph API cannot publish tappable story links
- 2026-05-01 09:10 session start: read-order complete, working on story-link approach for post backlinks
- 2026-05-01 09:05 morning: discovery +0, published fdb5866b072645 (technology, ig=18098417525120935)
- 2026-05-01 08:05 published fdb5866b072645 (TECH, 7 slides, ig_media=18098417525120935)
- 2026-05-01 09:03 session start: read-order complete, working on AM scheduled routine (discover + publish)
- 2026-05-01 07:55 reels pipeline built: make_reel.py (quirky_score=3 only), edge-tts en-GB-SoniaNeural word-sync, 4-source video_finder (pexels+nasa+archive+pixabay+safety-pool), FFmpeg overlay composition, Cloudinary upload, IG Reels publish_reel(). 18 safety pool clips downloaded (3 per topic). Music: pixabay CDN blocked, nature.mp3 got through, rest need manual download from pixabay.com/music/. First test reel compiled at 8.1MB, 20.6s for Radium Girls history fact. Full stack cost: 0 dollars.
- 2026-05-01 09:30 reels research (not built yet): full technical stack identified. Voice: edge-tts (en-GB-SoniaNeural, free, no key, pip install). Footage: Pexels Video API (already have key, portrait orientation, hd quality filter). Compositing: FFmpeg (scale+crop to 1080x1920, drawtext with fade-in alpha). Hosting for video_url: Cloudinary free tier supports video (stable HTTPS URL, 25GB/month). Music: NO licensed IG music via API — use Pixabay Music (royalty-free, no attribution) or ccMixter CC0 tracks. IG Reels API: media_type=REELS, video_url, share_to_feed, poll status_code until FINISHED, then media_publish. Scope: top-tier facts only (quirky_score=3), one fact per Reel, 15-30s, animated text + relevant footage + voice-over. Build estimated 2-3 days.
- 2026-05-01 09:00 growth features: (1) caption now leads with first fact sentence + "Follow @factjot for more." instead of generic CTA — hooks the 125-char preview; (2) Stories auto-post after every carousel — slide 1 posted to Stories, non-fatal on failure; (3) status.py now surfaces recent comments on latest post so operator knows when to reply; (4) routines updated to reflect Stories step + comment check. Routine impact: AM + PM updated.
- 2026-05-01 08:30 rule 18 added (routine sync): all three Claude scheduled routines updated (topic selection fixed, brain freshness gate added, safe+edgy defaults documented, weekly JSON shape + quirky_score guidance updated, banned phrase list loosened). Rule 18 baked into MEMORY_INDEX update checklist so every future agent knows to check routine impact on code changes.
- 2026-05-01 07:45 publisher bug fixed: instagram_publisher._publish_container now probes account recent media on failure response. If IG committed the post but returned a rate-limit error, we recover the real ig_media_id instead of falsely reporting failure. This caused both list packs to appear as "failed" when they had actually published.
- 2026-05-01 06:53 published 5fc1faf463c4f7 (LIST TV LIST, 7 slides, pack=series_worth_your_weekend, ig_media=17906938260401859) — posted at 06:31 UTC, brain missed due to publish-response race with rate-limit error; now manually recorded
- 2026-05-01 06:53 published 1f8457858b0d37 (LIST FILM LIST, 7 slides, pack=mind_bending_scifi, ig_media=18113410519699601) — posted at 21:54 UTC, brain missed due to same bug; manually recorded
- 2026-05-01 03:00 sensitivity gate narrowed: only animal_welfare auto-routes to controversial. Religion/politics/suicide/sexual/violence patterns demoted to `edgy` (autonomous-publishable, informational tags only). Rule 14 rewritten. Instagram Community Standards added as the explicit outer wall (operator-enforced, separate from classifier). Rule 17 inviolate list updated. Bank breakdown unchanged in numbers (130/4/2) but principle is set for future entries on those subjects.
- 2026-05-01 02:30 rule audit + rule 17 (dynamic curation): added meta-rule defining inviolate vs guidance. Loosened rule 14 (autonomous queue allows edgy now, only controversial gated), rule 15 (dropped arbitrary list cooldowns), rule 16 (cultural-knowledge spoilers allowed with restraint). ship_first_post and plan_week aligned. TV pack renamed series_worth_your_weekend (was mind_bending_tv — same picks, drops the framing-word repetition with films pack). Seeded PACK_BACKLOG_STUBS with 6 varied-tone themes.
- 2026-05-01 02:00 discovery: appended 1 fresh facts from r/todayilearned (rejected 99)
- 2026-04-30 23:30 fallback chain proven + IG app rate-limit hit. Image-host fallback chain (imgbb,tmpfiles) auto-failed-over correctly: imgbb upload → IG fetch failure → next_backend() → tmpfiles re-upload → IG retry. tmpfiles URLs were ACCEPTED by Meta (no fetch error). But IG returned a NEW error code 4/subcode 2207051 "Application request limit reached / Action is blocked" — actual app-level rate limit. Today's load: 7 publishes + ~5 failed publish attempts + 2 diagnostic media-container creates ≈ 80+ API calls. Cooldown 1-24h. Cannot publish until it clears. Tomorrow's autonomous fact slots may be affected if window persists past 09:00.
- 2026-04-30 23:00 imgbb cleanup gap fixed: ImgbbHost.DEFAULT_EXPIRATION_SECONDS now 7 days (was None — no expiration ever passed). Every previous upload stayed on imgbb forever. Pre-existing stale files can't be bulk-deleted (no API endpoint, delete_urls weren't stored), but going forward all uploads auto-expire. Reduces our footprint + anti-abuse signal on imgbb. Not the root cause of tonight's IG fetch failures (imgbb has unlimited free-tier storage), but real hygiene gap regardless.
- 2026-04-30 22:55 image host fallback: added CloudinaryHost adapter + `make_image_host()` factory reading `IMAGE_HOST` env var (default imgbb). ship_first_post / ship_list_post / publish_due all routed through factory. Tonight's list publish failures diagnosed as imgbb<>Meta CDN issue (control test: a TECH PNG that published 4h ago re-uploaded tonight is also rejected by IG). Cloudinary signup pending; once `CLOUDINARY_CLOUD_NAME` + `CLOUDINARY_UPLOAD_PRESET` are set in .env, swap with `IMAGE_HOST=cloudinary`.
- 2026-04-30 22:45 list posts (rule 15): built TMDB + OMDb clients, list_packs registry, ListCarouselRenderer with 3 new templates, ship_list_post.py. First pack `mind_bending_scifi` layout iterated v1→v5 (scores, fonts, runtime, genre, watch providers). Pack-level dedupe via `list:<slug>` — each pack ships once. Live publish failed at IG step (transient fetch error on hook image), brain NOT polluted, retry pending.
- 2026-04-30 18:52 published 05acce0896ef27 (TECH, 7 slides, ig_media=18117730324674287)
- 2026-04-30 18:45 sensitivity filter (rule 14): added sensitivity_guide.py with 3-tier system (safe/edgy/controversial). plan_week hard-gates to safe; ship_first_post defaults safe with --allow-edgy / --allow-controversial opt-ins. Mike Headless Chicken + Tarrare cat-eating explicitly marked controversial. Bank now 135 (129 safe / 4 edgy / 2 controversial).
- 2026-04-30 18:21 published 63475ed0a8ceee (HISTORY, 7 slides, ig_media=18080306243560838) — slide 2 contained Mike Headless Chicken; this prompted the sensitivity-filter build.
- 2026-04-30 18:10 evening: published 65380c2214c2aa (ocean, ig=18082590011431895)
- 2026-04-30 17:12 published 65380c2214c2aa (OCEAN, 7 slides, ig_media=18082590011431895)
- 2026-04-30 18:10 session start: read-order complete, working on evening publish (scheduled task pm-post-1800)
- 2026-04-30 15:30 session start: read-order complete, working on session initialisation
- 2026-04-30 15:16 memory continuity hardening: mandated startup log write in root+brain manuals and strengthened check_brain_fresh required-memory checks
- 2026-04-30 15:16 session start: read-order complete, working on startup memory continuity hardening
- 2026-04-30 14:07 memory hygiene: added current-truth snapshot to MEMORY_INDEX and revalidated freshness gate
- 2026-04-30 14:02 weekly: skip, in-progress lock
- 2026-04-30 09:00 morning: discovery +0, published daf898e23152bc (space, ig=18089517920586284)
- 2026-04-30 08:42 published daf898e23152bc (SPACE, 7 slides, ig_media=18089517920586284)
- 2026-04-30 09:00 strategy pivot: bank schema now carries quirky_score (0-3), intensity (light/medium/heavy), tone (curious/shocking/wholesome/sober). Backward-compat defaults via load_all_facts._with_defaults. ship_first_post sorts fresh_rows by quirky_score desc so screenshot-worthy facts surface first. Appended 25 Tier-1+2 shock facts (Phineas Gage, Mike Headless Chicken, Vasili Arkhipov, Tarrare, Antikythera, Anglerfish fusion, etc) all under 280 chars. Strategy: 60% Tier1 / 30% Tier2 / 10% Tier3 mix; ban graphic violence, current politicians, suicide specifics, religious slander.
- 2026-04-30 08:12 published 41c2a74571ef33 (EARTH, 7 slides, ig_media=17915941620164062)
- 2026-04-30 08:25 bank expansion: added ~47 verified facts across all topics, bank now 107 entries (was 57); plan_week rerun scheduled 9 new carousels for 3-7 May, queue now holds 13 carousels covering through 7 May; runway lifted to ~11 days at 1/day or ~5-6 days at 2/day.
- 2026-04-30 08:00 launchd jobs loaded: publish (every 15 min), discover (daily 03:00), refresh_token (Sun 03:30), plan_week (Sun 04:00). All four registered via launchctl list; first scheduled fire is 1 May 10:00 UTC SPACE post.
- 2026-04-30 07:43 autonomy hardening: scripts/status.py + scripts/heartbeat.py; AlertingService persists to data/alerts.jsonl; launchd plists for discover (03:00 daily), refresh_token (Sun 03:30), plan_week (Sun 04:00); plan_week.py idempotent on post_id AND timeslot, supports --start-tomorrow; 4 carousels queued for 1-2 May.
- 2026-04-30 07:37 discovery: appended 4 fresh facts from r/todayilearned (rejected 96)
- 2026-04-30 07:05 published ee41c1f6bfd4fa (HISTORY, 5 slides, ig_media=18396608134159815)
- 2026-04-30 07:04 published a6846ceac7c4e5 (NATURE, 6 slides, ig_media=17865332346546734)
- 2026-04-30 07:05 published ee41c1f6bfd4fa (HISTORY, 5 slides, ig_media=18396608134159815) — Eiffel/Colosseum/Great Fire/computer-job/quote
- 2026-04-30 07:04 published a6846ceac7c4e5 (NATURE, 6 slides, ig_media=17865332346546734) — sloth/spider/crow/sea-otter/ant/quote
- 2026-04-29 23:25 audit + critical fixes: publish_due.py was using a stub `_to_public_image_urls` returning empty for local PNGs (would have silently failed every cron). Replaced with real imgbb upload via ImgbbHost. Added missing `host=` param to InstagramGraphPublisher. Added `record_quote_used` after publish so closing quotes dedupe. Built scripts/refresh_token.py for 60-day token rotation. Spot audit run before this batch: 13/13 PASS.
- 2026-04-29 23:05 hybrid autonomy: discover_facts.py rebuilt with 8-stage truth gate (Tier 1+2 domains, ≥5000 upvotes, ≥3 day age, top-comment correction-signal scan, source-content cross-check); load_all_facts() merges curated bank + discovered feed; plan_week.py schedules 2/day (10:00+18:00) for 7 days = 14 carousels; launchd publish.plist fires every 15 min. Caption now 'Follow @factjot for fresh facts daily.' (plural). Voyager hint expanded to spacecraft-illustration variant.
- 2026-04-29 22:40 SPACE filter switched from blocklist to ALLOWLIST (SPACE_REQUIRED_TERMS); alt MUST contain a real celestial-subject word like 'galaxy/mars/spacecraft/voyager 1/nasa'; sun/star/earth alone now insufficient. NASA promoted to first provider for SPACE. Voyager hint tightened to 'Voyager 1 probe NASA'.
- 2026-04-29 22:25 added camera/lens/cityscape negatives to SPACE filter; expanded AMBIGUOUS_SUBJECTS_BY_TOPIC space set with Olympus/Apollo/Andromeda/Voyager/Europa/Io; rewired Olympus Mons image_hint to "Mars volcano red planet surface" to bypass camera-brand match
- 2026-04-29 22:10 audit removed 6 bad render folders (001/002/003/004/008/009); kept 005/006/007 (clean); ship_first_post now skips already-posted facts so retries on a topic actually use fresh entries
- 2026-04-29 21:55 switched top-left logo to full factjot wordmark; added Tardigrade image_hint; expanded fact bank from 30 to 57 (runway ~4 days); built scripts/runway.py
- 2026-04-29 21:30 added factjot logo to top-left of every slide; tightened Pexels filter (food/statue/costume); built scripts/check_brain_fresh.py and wired into publish_now/publish_due so a stale brain blocks publishing
- 2026-04-29 19:18 published 0a0961a686fafc (OCEAN, 5 slides, ig_media=18201190513351850)
- 2026-04-29 19:09 published a1b282f51ad0bb (EARTH, 6 slides, ig_media=18117083323665596)
- 2026-04-29 18:42 published 24942cfa604fb6 (HISTORY, 6 slides, ig_media=18324581197280793)
- 2026-04-29 18:34 published b401a141ce2832 (TECH, 6 slides, ig_media=18079671887540791)
- 2026-04-29 18:21 added MEMORY_INDEX workflow and rule 13 for strict cross-agent handover discipline
- 2026-04-29 18:12 increased main slide text size and organised render/image outputs into per-post metadata folders
- 2026-04-29 18:08 published ac1da5622115e6 (SPACE, 7 slides, ig_media=18211394587333889)
- 2026-04-29 17:53 published 9d7f0cb163ad06 (NATURE, 6 slides, ig_media=18008026202905578)
Newest at top. One terse line per non-trivial action. No essays.

- 2026-04-29 brain: initial structure created (CLAUDE, CRITICAL_FACTS, rules 01-11, data ledgers, bank seed)

2026-05-02T13:08:17Z weekly: skip, last ok 2026-05-01T16:17:01Z

## 2026-05-02 — Major session: pipeline hardening + GitHub Actions + TikTok setup

### Reel quality (all 43 q3 facts now curated)
- Wrote reel_script (≥70 words) + reel_title for all 34 previously-bare q3 facts
- Hard gate: _pick_fact rejects facts without both fields; abort if final reel < 35s
- validate_reel_facts.py added; passes clean on all 43 eligible facts

### Audio bug fixed
- loudnorm filter upsampled voice+music mix to 96000 Hz; Instagram rejects this
- Fix: -ar 44100 -ac 2 in FFmpeg output (reel_composer.py)

### Instagram rate limiting incident
- 30+ containers + 3s polling = ~3000 API calls; hit code 4 / subcode 1349210
- All containers showed ERROR until rate limit cleared (~2h)
- Fix: poll every 15s (was 3s); initial 10s wait; code-4 errors trigger 30s backoff

### FFmpeg improvements
- format=auto → format=yuv420 on all 26+ overlay ops (non-standard pixel format risk)
- noise=alls=3:allf=t+u removed (temporal entropy slows Instagram transcoder)
- crf 22 → 26; maxrate 2500k added; profile:v main explicit

### GitHub Actions deployed
- 4 workflows: carousel-morning, carousel-evening, reel, weekly-plan
- 19 secrets set via gh CLI
- State (.jsonl ledgers) committed back to main after every run
- All 5 launchd jobs unloaded — Actions is now sole scheduler
- Repo made public for GitHub Pages (secrets safe — in GitHub Secrets not code)

### Cloudinary wired
- CloudinaryVideoHost added; primary for reel video uploads
- Credentials: cloud=dmzer6hgv, preset=factjot

### Quote dedup fixed
- QuoteBank._session_hashes prevents same quote in two carousels per plan_week run
- Fixed 5 existing queue duplicates

### TikTok app submitted
- Login Kit + Content Posting API; Direct Post enabled
- Domain verified: wonderkid96.github.io/factjot/
- GitHub Pages deployed for terms/privacy policy pages
- Demo video generated via FFmpeg+Playwright and uploaded
- Awaiting review approval (1-3 business days)

### One-off 21:00 UTC reel trigger
- Added to reel.yml cron for rate-limit recovery post; remove after it fires

## 2026-05-02 evening session — audit + tidy + storage

### 2-slide carousel root-cause + fix
- 18:05 UTC carousel posted 1 slide (Mac 128KB fact). Tech bank exhausted (0 fresh).
- Fix shipped: `CarouselDraftGenerator.generate()` now skips topics with <3 facts (no more silent stubs). `ship_first_post.py` aborts cleanly if topic has <3 fresh facts after sensitivity gate. Brain log entry on abort.
- Tech bank needs topping up before next Saturday evening.

### Storage cleanup
- `data/cache/` was 2.7GB locally (722MB reels, 1.9GB renders).
- New `scripts/cleanup_caches.py`: prunes per-reel and per-carousel caches that are published in the ledgers AND older than --keep-days. Trims `insta-brain/log.md` to last N lines. `--dry-run` flag.
- Wired into Sunday `weekly-plan.yml`: runs every week with --keep-days 14 --keep-log-lines 500.

### TikTok credentials stored
- `TIKTOK_CLIENT_KEY` and `TIKTOK_CLIENT_SECRET` in .env and GitHub Secrets.
- Awaiting TikTok app review approval before integration is wired.

### Code quality audit (2026-05-02 evening)
Subagent audit returned ~40 findings. Critical to fix BEFORE next reel run (post-21:00 UTC tonight):
1. **Hash mismatch in reel dedup** — `make_reel._record` writes SHA1, `brain.assert_no_duplicate` reads SHA256. Reel dedup gate is broken. Fix: use `brain.claim_hash(claim)` consistently.
2. **Atomic .env writes** — `refresh_token.py` rewrites .env with truncate-and-write. Crash mid-write nukes credentials. Fix: tmp file + os.replace.
3. **Atomic queue.jsonl writes** — `approval_queue.update_status` same pattern.
4. **ElevenLabs alignment crash safety** — empty alignment data crashes `word_beats[-1]` after MP4 written.
5. **Bare `except (json.JSONDecodeError, Exception)` in brain dedup** — swallows every error.
Plus dead code removal (audio_duration, group_into_lines, find_video, HOOK_LABEL_*, etc.) and several Medium-tier issues. Full list captured in MEMORY_INDEX.

### Reel folder naming (queued for after 21:00 UTC reel posts)
- Replace SHA-1 hex IDs with human-readable `<topic>_<slug>` (e.g. `space_the-demon-core`).
- Implementation written but not pushed; held until tonight's reel completes.


---

Related: [[CLAUDE]] · [[CRITICAL_FACTS]] · [[MEMORY_INDEX]] · [[PUBLISH_PLAN]] · [[rules/index]]
