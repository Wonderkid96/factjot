# Rule 16 — No spoilers in list-post hooks

**Strong default, with judgment.** Hooks for any list-post item should not give away central plot twists, endings, character deaths, or reveals that land after the first 30 minutes — for works whose audience hasn't already had the twist soak into pop culture.

The exception: when a reveal is so culturally saturated that pretending it's secret reads as cute (Snape kills Dumbledore, Bruce Willis is dead, Vader is Luke's father, Rosebud is the sled). For those you can allude to the twist without ruining anything, because the people who care already know. Use restraint anyway — even saturated reveals shouldn't be the *only* hook, and the framing matters.

The hook is a sales line, not a recap. It should make someone want to watch / read / play. Spoiling the payoff costs us followers and trust. People who already know the work will roll their eyes; people who don't will feel cheated when they hit the moment.

## What counts as a spoiler

- **Central twist or reveal** — anything in the third act. "The twin is dead the whole time", "the AI was the killer", "the mountain was a metaphor for grief".
- **The mechanism behind the premise** if it's revealed late. Arrival's "the language lets you remember the future" is the *whole point* of the film, revealed at the end. Saying it in the hook is a spoiler.
- **Specific scenes** that are climactic or signature. Mentioning "the bear scene", "the dinner table fight", "the long take in the trenches" primes viewers and dulls the impact.
- **Character deaths** at any point. Even a death in act 1 is a spoiler if it's a turning point.
- **Endings**. Always. "Bittersweet ending", "shocking final frame", anything that implies the shape of the resolution.

## What's fair game

- The first-act premise. The trailer-level setup. "Two engineers build a time machine in a garage" is fine for Primer because that's where the film begins.
- Genre, tone, mood. "Quietly devastating", "cult horror", "wholesome heist".
- Real-world context. "Made for $7,000", "shot in one take", "the director's debut".
- Awards and recognition. "Won Cannes", "Oscar-nominated".
- Director's other work. "From the director of Ex Machina".
- Critic-quote-style assessments without specifics. "The most thoughtful sci-fi of the decade", not "the ending will haunt you".

## The 30-minute rule

If something happens in the first 30 minutes (or first 10% of a long-form work), it's premise. After that, it's plot — handle with care. When in doubt, ask: "Could this go on the back of the DVD case?"

## Why we care

We're trying to grow @factjot as a "save for later" feed. People save lists they want to act on. If they've already had the surprise spoiled, they don't bother watching, and the post fails its job. Spoiler-free hooks compound trust over time — followers learn that our recommendations are safe to read.

## Enforcement

This is editorial discipline, not code. Every new pack added to `src/content/list_packs.py` must be spoiler-audited before it ships. When in doubt:

1. Strip back to the premise only.
2. Add tone or context (awards, budget, director).
3. Resist the urge to be clever about the ending.

## Existing packs audit (2026-04-30)

- `mind_bending_scifi` Arrival hook rewritten — original "remember the future before it happens" gave away the twist. Replaced with premise-only.
- `mind_bending_scifi` Annihilation hook rewritten — "the bear scene alone" was a signature-scene tease. Replaced with mood/visual description.
- `mind_bending_scifi` Predestination hook kept — "the twist is so neat" mentions there IS a twist but reveals nothing. Borderline but acceptable.
