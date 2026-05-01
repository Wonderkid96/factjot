# Rule 04 — Visual design

## The rule
Every slide follows this visual system. The brand kit at `brand/brand_kit.json` is locked; do not silently change it. If a change is needed, update it AND this rule together.

## Canvas
- **Dimensions:** 1080 x 1350 (Instagram portrait). Renderer outputs 2160 x 2700 (2x scale) for retina sharpness.
- **Aspect ratio:** 4:5 (Instagram's tallest allowed for feed posts).

## Layout (top to bottom)
1. **Top row:** mono `FACTJOT` left, `01 / 06` index right. JetBrains Mono Bold, 22px (line-spacing 0.18em), off-white.
2. **Photo:** full-bleed background, cover-fit (no letterbox).
3. **Bottom darken gradient:** vertical, transparent at ~38% to ~94% near-black at the bottom edge. Anchors the headline against any photo.
4. **Vignette:** gentle radial darken, transparent until 70% radius, ~22% black at corners. Just enough to anchor edges, never crushing.
5. **Category pill:** red (`#E6352A`) rounded pill, white JetBrains Mono Bold 20px text, letter-spacing 0.32em. One word, ALL CAPS.
6. **Headline:** Instrument Serif Regular, mixed case, sentence-style. Auto-sized between 60px and 128px. Tight letter-spacing (-0.012em). Anchored to the lower portion of the frame.
   Add a subtle diagonal drop shadow (down-right) to preserve readability on high-contrast photo backgrounds.
7. **Trailing period:** the final terminal punctuation of the headline is rendered in accent orange (`#E6352A`). It is the actual full stop, NOT a separate floating dot.
8. **Grain:** SVG noise overlay, 6% opacity, multiply blend.

## Palette (locked)
- `paper`: `#F4F1E9` (rarely used, kept for cross-brand consistency)
- `near-black`: `#0B0B0C` (page bg, gradient terminus)
- `accent`: `#E6352A` (highlights, pill, trailing period)
- `lime`: `#C8DB45` (reserved, not used in current layout)
- `lilac`: `#C4A9D0` (reserved, not used in current layout)
- `off-white`: `#EDE8DD` (mono labels)
- `white`: `#FFFFFF` (default headline)

## Typography (locked)
- **Headline:** Instrument Serif Regular and Italic. Source: `assets/fonts/InstrumentSerif-{Regular,Italic}.ttf`. Base ladder lives in `src/render/render_carousel.py::SIZE_LADDER`.
- **Mono labels (wordmark, index, pill):** JetBrains Mono Bold. Source: `assets/fonts/JetBrainsMono-Bold.ttf`. Always all caps, with explicit letter-spacing.
- We never use a third typeface. Don't introduce one.

## Highlight markup
Slide text supports two inline tokens:
- `[i]…[/i]` → italic, white. Used for the key entity (proper noun, the "what" of the fact). One per slide max.
- `[h]…[/h]` → italic, accent orange. Used for the killer detail (number, year, money figure, payoff word). One per slide max.

The carousel generator picks these automatically. Never combine three highlights on one slide; the eye loses the focus.

## Image rules (visual cohesion)
- Always full-bleed, cover-fit.
- Real photographs only. No clip art, no diagrams, no charts.
- Reject candidate images that are mostly black/white/grey average luminance under 30 or above 230. The fetcher does this.
- Reject candidate images smaller than 480x480.
- Per-carousel cohesion: every slide gets its own image, but the post should feel like one body of work. Anchor query keeps the post on-subject.

## Cohesion checklist (run before approving a render)
- [ ] Every slide is exactly 1080 x 1350 (or 2160 x 2700 retina)
- [ ] FACTJOT wordmark and index appear top-row on every slide
- [ ] Category pill identical across all slides of one post
- [ ] No image repeats across slides of one post (unless a slide had to fall back)
- [ ] Trailing period of every headline is accent orange
- [ ] Text remains legible over bright or high-detail image regions (gradient and subtle diagonal shadow both visible)
- [ ] No em dashes anywhere
- [ ] No floating dot circle separate from the period
