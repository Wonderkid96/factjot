# Image Pipeline Spec

**Status:** Approved by Toby, 2026-05-06.
**Parent spec:** `SPEC_FACTJOT_SYSTEM.md`, system constitution. This document is a sub-spec. It inherits all system-wide invariants, safety rules, and agent workflow rules from the parent. Where this spec and the parent disagree, the parent wins.
**Replaces:** Previous SPEC_IMAGE_PIPELINE.md (approved 2026-05-06). The implementation work that followed approval still produced failing carousels, so this spec resets the brief at product level before any further code work.
**Primary target:** Manual carousel image pipeline.

---

## 1. Product goal

A successful manual carousel:

- Looks intentional, like an editor designed it.
- Is visually strong on the cover and on every content slide.
- Is factually accurate, the image actually depicts the subject claimed in the slide text.
- Is legally usable, every image has a verified licence we can post under.
- Is varied enough to feel curated, not "the same image five times".
- Is safe to post immediately, no last-minute panic edit.

Core principle: a safe but ugly carousel is still a failed carousel. The pipeline does not declare success because it avoided wrong images. It declares success only when the rendered output meets the goal above.

---

## 2. Affected pipelines

The repo has multiple pipelines. They are not the same system and must not be conflated.

| Pipeline | Purpose | Spec applies? |
|---|---|---|
| Manual carousel | Custom editorial carousels generated from a user brief | YES, primary target |
| News carousel | Guardian/news-based carousels, shares some manual slide rendering behaviour | Shared concerns covered, full implementation deferred |
| Scheduled fact carousel | Daily recurring fact carousels | Out of scope |
| List carousel | Evening list posts | Out of scope |
| Reel pipeline | Short-form video with facts, voiceover, footage, captions, thumbnail, story | Out of scope |

This spec primarily targets the manual carousel image pipeline first. Any change that touches `render_carousel.py` (fact carousel renderer) or the reel pipeline is out of scope.

---

## 3. Non-negotiables

Every change must respect every item in this list. Failure of any one means the carousel is failed and must not post.

1. No misleading images. The image must depict the subject the slide claims, not a same-named place, person, or product.
2. No empty image boxes. A slide either shows an image or shows an intentional typography-only layout with no photo zone at all.
3. No wrong-subject images. Place de la Concorde never appears in a Concorde aircraft carousel.
4. No repeated weak image across the deck. The same poor image used twice is worse than two intentional text slides.
5. The cover slide must have a usable image. If none exists, the run fails.
6. Typography-only slides must look intentional, not broken.
7. Legal/licence safety matters. Every candidate must have a verified provider and machine-readable licence/status data before Haiku sees it. Final selected images must have a verified usable licence before commit and render.
8. If image quality fails, the run reports failure honestly. It does not pretend success and post a weak carousel.
9. The rendered PDF must be inspected before the task is called done. Tests passing is not enough.

---

## 4. Image intent fields

Sonnet generates the following fields per post during content generation. These resolve the brief into search instructions.

| Field | Purpose |
|---|---|
| `visual_subject` | The thing the carousel is actually about, resolved as a phrase. Example: "Concorde supersonic airliner", not "Concorde". |
| `subject_type` | Coarse category. Example: aircraft, person, place, plant, scientific concept. |
| `source_aliases` | At least two multi-word aliases the subject is known by. Helps metadata matching without single-word ambiguity. |
| `context_words` | Disambiguating terms that must appear alongside ambiguous single words. Example: ["aircraft", "supersonic", "BAC", "Aerospatiale"]. |
| `negative_terms` | Hard-block terms. Example: ["place de la concorde", "obelisk", "fountain", "paris square"]. |
| `preferred_image_types` | Visual modes that suit the subject. Example: ["photograph", "in-flight"]. |
| `avoid_image_types` | Visual modes that hurt. Example: ["map", "diagram", "stamp", "logo"]. |
| `image_queries` | One specific search query per slide, including cover. Tuned to the slide's claim, not to the topic in general. |
| `fallback_query` | A safer secondary query if the slide-specific query returns nothing usable. |

Raw brief text from the user is kept separate from these resolved intent fields. The brief is input. The intent fields are the resolved search instructions used by the sourcer.

---

## 5. Candidate collection

For each slot (cover plus one per content slide):

- Collect a candidate pool. Do not return the first passing image.
- Cap pool size at `MAX_POOL` (current value 40 for manual posts; override permitted for news).
- Search using the resolved `visual_subject` plus the slide-specific `image_queries[i]`. Do not search against the raw brief.
- Try providers in the order defined in section 6.
- A candidate only enters the pool after passing hard validation in section 7.
- If a slot's pool is empty after all providers, the slot enters the typography-only path in section 12, or, for cover, the failure path in section 11.

---

## 6. Provider strategy

Current and approved providers, in order of trust:

1. Wikimedia Commons
2. Wikipedia
3. Smithsonian Open Access
4. Pixabay
5. Pexels (added to the R3 fallback path on 2026-05-07; still excluded from R1/R2 because lifestyle stock cannot satisfy alias gates for named subjects)
6. Openverse, enabled only after live verification of unauthenticated reads and licence/source reliability

Flickr is no longer supported. The Flickr API moved to a premium-only model in 2024 and is no longer accessible to free integrations. Direct Flickr image URLs returned via Openverse also rate-limit our requests with HTTP 429.

### 6.1 Round-aware provider selection (added 2026-05-07)

The image sourcer (`src/research/image_sourcer.py:source_images`) runs three rounds of fetch:

- **R1**: strict slot aliases. Provider order = `TOPIC_PROVIDER_ORDER[topic]` (for editorial: archive-first `commons, wiki, wiki_article, smithsonian, pixabay`).
- **R2**: global aliases. Same provider order as R1.
- **R3**: visual fallback (descriptive B-roll terms like "courtroom legal proceeding"). Aliases dropped. **Provider order overridden to stock-friendly** `("pexels", "pixabay", "smithsonian", "commons")`. Openverse omitted because its results are predominantly Flickr-hosted URLs that 429 our bot IP. This override is implemented via the `provider_override` kwarg threaded through `fetch_pool` and `_iter_candidates`; R1 and R2 leave it unset and fall back to the topic order.

The override exists because R3 is asking different questions than R1/R2: not "find a photo of this named subject" but "find any photo whose tags match these visual concepts". Wikimedia / Wikipedia / Smithsonian title their files by subject identity, so they cannot satisfy descriptive R3 queries even when the underlying photo would have been perfect. Pexels and Pixabay tag photos by visual content, which is what R3 needs.

Future, not in scope of this spec:

- Search-engine APIs (used as candidate discovery only). If ever enabled, they must still go through provider/licence verification before any candidate enters the pool. They never become a direct image source.

Forbidden:

- No Google Images scraping.
- No provider that returns images without machine-verifiable licence data.

---

## 7. Hard validation

Code rejects a candidate before Haiku ever sees it if any of the following is true:

- Licence is unsafe, restrictive, or unknown.
- Source URL is missing or not on a verified provider.
- A term from `negative_terms` matches the candidate's title, description, or tags.
- Metadata is empty or below a minimum signal threshold (no title, no description, no tags).
- The candidate matches only a single ambiguous word from `source_aliases` with no `context_words` present in metadata.
- A known disambiguation trap is detected. Example: a Concorde aircraft search returning a candidate with "Place de la Concorde", "obelisk", "fountain", or "Paris square" in its metadata.

Hard validation is non-overridable. Haiku cannot rescue a candidate that fails here.

---

## 8. Haiku selector contract

Haiku is the judgement layer. Code is the safety layer. Haiku is called only after hard validation.

**Haiku receives, as compact JSON:**

- slot index
- slide query
- slide text, if available
- visual subject
- cover flag
- candidate list, each candidate has:
  - `candidate_id`
  - provider
  - metadata, title, tags
  - deterministic score
  - width
  - height

**Haiku does not receive:**

- full images
- full webpages
- large metadata blobs
- secrets
- final authority over safety
- permission to browse
- permission to invent URLs or IDs

**Haiku returns:**

- ordered candidate IDs, best first then backups
- confidence: `high` | `medium` | `low`
- a short reason string

**Code still enforces, after Haiku returns:**

- licence
- duplicate rules
- cover rules
- no consecutive duplicates
- max reuse cap
- candidate must have passed hard validation

**MIN_SCORE override rule:**

- The deterministic score is a quality signal, not a verdict.
- If Haiku confidence is `high`, Haiku may select a candidate below MIN_SCORE.
- If Haiku confidence is `medium` or `low`, the MIN_SCORE floor is enforced.
- If Haiku's full ordered list fails the floor at medium/low confidence, the slot falls back per section 12.

**`relax=True` (readable_list profile, added 2026-05-08):**

- `ImageSourcer(relax=True)` lowers the **R3 floor only** from `MIN_SCORE_R3=8` to `MIN_SCORE_R3_RELAXED=6`. R1 and R2 floors are unchanged.
- Threaded by `pipelines/carousel/ship_carousel_post.py` (manual module wrapper) when `--layout-mode=readable_list` (i.e. list and news slots via the autonomous agent).
- Rationale: list item slides like "Refrigerator Safety Act 1956" have weak literal subject-term matches in stock metadata, so the strict R3 floor was rejecting candidates Haiku correctly judged as serviceable. The relaxed floor lets a Haiku `medium` pick at score 6-7 commit instead of the typography fallback. compact_legacy callers (fact slot, direct CLI) leave `relax=False` and keep the strict floor.
- Out of scope for the relax flag in this iteration: the `no_subject_term_in_meta` POOL_REJECT remains a hard reject; only the score floor moved.

---

## 9. Deterministic scoring role

Scoring supports Haiku, it does not replace judgement. Scoring helps rank candidates the way a human editor skims a contact sheet.

Scoring components:

- alias match strength (multi-word match > single + context > single alone)
- provider trust
- query relevance, terms from `image_queries` matched in metadata
- preferred image type bonus
- avoid image type penalty
- resolution bonus
- duplicate/reuse penalty

Scores are emitted into Haiku's prompt as a single integer per candidate. Haiku is allowed to override the rank ordering at high confidence.

---

## 10. Duplicate and reuse rules

- No consecutive duplicate image. Slide N and slide N+1 cannot show the same URL.
- The same URL is capped at 2 uses per carousel.
- Repeated weak images are treated as worse than typography-only.
- If sources are thin, the pipeline prefers an intentional typography-only slide to a recycled weak image.

---

## 11. Cover image contract

The cover slide must show a real image, with one explicit exception for list mode (see below).

Order of attempts:

1. Best Haiku pick from cover slot pool.
2. Backup Haiku picks from cover slot pool.
3. Strongest deterministic candidate matching `visual_subject` directly.
4. Fallback query candidate.
5. If none succeed:
   - **fact / news cover:** raise `COVER_IMAGE_FAILED`. The run ends. No partial carousel is rendered. No partial carousel is posted.
   - **list cover (`layout_mode=readable_list`):** route into the typography cover variant in section 12. List items are intentionally heterogeneous (a list of items is not a single subject), and a deliberate typography cover is preferable to either a misleading "stock list" image or aborting the post. The renderer logs `cover_image_status=typography_fallback` and the carousel-quality ledger records `cover_typography_fallback=true`.

The typography cover is never silently chosen. It is only used when the policy above explicitly routes there. An empty `photo_data_url` reaching the cover renderer for any other slot is a bug, not a fallback.

---

## 12. Typography-only fallback contract

Triggered when a content slot has no usable image after Haiku selection and deterministic fallback, or when the cover slot routes into the list typography cover (per section 11).

Required behaviour for any typography slide (cover or content):

- Do not render an empty photo rectangle. The renderer branches on slide state, never on truthiness of an empty string.
- Remove the photo zone from the layout entirely. The text card expands to full canvas (1080 x 1350).
- Vertically balanced typography. Centred or balanced, not top-aligned.
- Factjot brand styling preserved (wordmark top, index pill, brand background from `brand/brand_kit.json`).
- Subtle texture, grain, or a single accent rule allowed. Nothing more elaborate.
- No "No image" label. No placeholder text. No black box where a photo should be.

Cover-specific additions (typography cover variant):

- Full-canvas Instrument Serif title (the cover headline), balanced and biased to the upper third.
- Label pill with Space Grotesk Bold 700, uppercase, 0.08em tracking.
- Red accent rule, 4px x 120px in `--accent` (`#E6352A`), positioned below the title.
- Wordmark sized to match the photo cover variant.
- Two palette variants chosen by `layout_mode`:
  - `compact_legacy`: INK ground (`#0A0A0A`), off-white type, white wordmark.
  - `readable_list`: PAPER ground (`#F4F1E9`), INK type, dark wordmark. Provides visual contrast against the readable_list dark photo covers in the same feed.

Content-slide additions:

- Red keyword markup (`[r]...[/r]`) renders as on regular slides.

The slide must be visually comparable in quality to an image slide. If a viewer has to ask "is something missing here?", the layout has failed.

---

## 13. Renderer requirements

The manual/news renderer must distinguish three slide states explicitly:

1. Slide with image. Photo zone rendered, image data URL provided.
2. Deliberate typography-only slide. Photo zone removed, full-canvas text card.
3. Cover image failure. Run aborts before this state can render.

Hard requirement: an empty string for image data must not silently become an empty photo box. The renderer branches on slide state, not on truthiness of a string.

---

## 14. Logging requirements

Every run logs, per slot:

- generated image intent fields (visual_subject, aliases, context words, negative terms, queries)
- provider order used
- candidate pool size
- Haiku candidate selections and confidence
- deterministic scores per candidate
- rejected candidates and the rejection reason
- selected candidate per slot (provider, ID, score)
- typography-only slots flagged
- cover failure if it occurs
- final image coverage summary, e.g. "6/7 image, 1/7 typography-only"

Format follows the existing DEBUG channel in `image_sourcer.py`. No new log files required.

---

## 15. Acceptance tests

A reset is only credible if the failures already seen do not return. Each case must pass on a `--dry-run` plus rendered PDF inspection.

1. **Concorde aircraft.** No Place de la Concorde. No Paris obelisks. No generic Paris landmarks. No empty image boxes. Cover is a recognisable photo of the BAC/Aerospatiale Concorde aircraft.
2. **Concord, Massachusetts.** No Concorde aircraft. No Paris square. Images depict the town.
3. **Concord grape.** No Concorde aircraft, no town of Concord. Images depict the grape variety or vines.
4. **Niche science topic** (e.g. a specific protein, a specific theorem). Diagrams or typography-only allowed if intentional. No misleading "stock science" filler.
5. **Historical person.** Portraits or archive images preferred. No random unrelated people. Typography-only acceptable for slides where no archive image fits.
6. **Topic with no good images.** Content slides become intentional typography-only cards. The cover fails with `COVER_IMAGE_FAILED` if no valid subject image exists.

Each test case is run with `--dry-run`, the rendered PDF is opened, and the result is judged visually as well as by log output.

---

## 16. Definition of done

A change is not done because tests pass.

A change is done only when ALL of the following are true:

1. `--dry-run` succeeds end to end on a representative brief.
2. The rendered PDF has been opened and inspected by a human.
3. The output visually meets this spec.
4. No empty photo boxes appear anywhere.
5. No wrong-subject images appear anywhere.
6. The cover image is correct, relevant, and present.
7. Failures are reported honestly. A failed run exits non-zero with a clear reason.
8. Logging shows pool sizes, Haiku decisions, and final selections per slot.

If any of the above is unverified, the work is not done.

---

## 17. Out of scope

For this implementation:

- No Google Images scraping.
- No broad rebuild of the reel pipeline.
- No broad rebuild of the list carousel pipeline.
- No broad rebuild of the scheduled fact carousel pipeline.
- No full visual AI verification step (no model looking at the actual image bytes).
- No expensive model calls beyond the cheap Haiku selector.

---

## 18. Future work

Tracked, not in scope here:

- Search-engine API candidate discovery with mandatory licence verification.
- Visual AI verification, a vision model checks that the actual image content matches the subject.
- Richer provider-specific adapters (better Wikimedia category traversal, better Smithsonian metadata extraction).
- An image quality model (sharpness, composition, subject-fills-frame).

---

## Approval

Spec written: 2026-05-06.
Approved by Toby: 2026-05-06.

Next steps are:

1. Compare the current implementation against this spec.
2. Identify the smallest set of changes to bring the implementation into compliance.
3. Propose that change set as an implementation plan.
4. Do not modify any code before steps 1 to 3 are agreed.
