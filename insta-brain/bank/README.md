# Curated fact bank

Hand-verified gold-standard facts grouped by topic. Each `.md` file is a topic. Each entry follows this format:

```yaml
---
topic: space
claim: "On Venus, a single day lasts longer than a year. One full rotation takes about 243 Earth days, while one orbit around the Sun takes 225."
sources:
  - https://science.nasa.gov/venus/facts/
  - https://www.britannica.com/place/Venus-planet
image_hint: venus surface
verified_by: toby
verified_at: 2026-04-29
---
```

`image_hint` is optional. If set, the image fetcher uses it as the primary search query for that fact (overrides automatic keyword extraction).

The discovery layer reads these files at startup. Bank facts always pass the verification gate (they've been hand-verified) but still go through it for consistency.

Topics currently seeded:
- space.md
- nature.md
- history.md
- tech.md
- ocean.md
- earth.md

Add new topic files as you go. Filenames are lowercase, single-word where possible.
