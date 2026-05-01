# Rule 11 — Never ship a slide without a real image

## The rule
Every slide on every post must have a real photographic background. No procedural gradients, no solid colours, no placeholder boxes. If the image fetcher cannot supply one, the slide does NOT ship — the post is held for human review.

## Why
- Procedural gradients shipped briefly during early prototyping and looked obviously bot-made.
- Without a relevant image, the slide carries no extra information beyond the text — a wasted slide on Instagram, where image-led carousels outperform text-led ones.
- Cohesion: a single naked slide in a 6-slide carousel ruins the entire post.

## How
1. `src/research/image_fetcher.py` raises `NoImageFound` if it cannot return a fresh, on-topic image for any of its query variants.
2. The renderer catches `NoImageFound` and tries one fallback: the post's anchor image (the first slide's photo). This is acceptable visual reuse INSIDE one post — not across posts.
3. If the anchor itself failed, the slide is dropped from the carousel and the post is marked `qa_failed: missing_image_<n>` in `data/queue.jsonl`. It will not auto-publish.
4. The pipeline never substitutes a procedural gradient. The gradient fallback was deliberately removed.

## Cohesion across the carousel
Slides in one post should look like they belong together. The image fetcher uses the post's anchor query (the strongest noun phrase from slide 1) on every slide so every photo stays on-subject. Per-slide queries broaden the visual without leaving the topic.

## Quality bar
Candidate images are rejected if:
- Smaller than 480x480 (low resolution)
- Average luminance under 30 (mostly-black thumbnail)
- Average luminance above 230 (washed-out white)
- Already in `data/used_images.jsonl` (by URL or content SHA)

## When the fetcher fails repeatedly
If a topic consistently fails to surface fresh images (after 3 runs), add a `bank/<topic>.md` entry with a `image_hint: <better query>` field and re-discover. The discovery layer will use the hint as the primary search term.
