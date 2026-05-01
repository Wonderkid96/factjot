# Rule 15 — List-format posts (cadence, dedupe, variety)

We post two shapes of carousel:

1. **Fact carousels** — daily, the bread and butter. Pulled from `RARE_FACT_BANK` + auto-discovered feed via `ship_first_post.py` and the autonomous `plan_week.py` queue.
2. **List posts** — themed, curated, one-off packs. Shipped via `scripts/ship_list_post.py --pack <slug>`. Backed by the TMDB client (films/TV) with the door open to other domains.

This rule covers list posts only.

## Pack structure

Defined in `src/content/list_packs.py`:

```
LIST_PACKS["mind_bending_scifi"] = {
    "slug":      "mind_bending_scifi",
    "title":     "Five mind-bending sci-fi films",
    "subtitle":  "you've probably never seen.",
    "category":  "FILM LIST",
    "series":    "factjot",
    "items":     [ {tmdb_id, hook, accent_word, imdb_score, rotten_score, genre, watch_providers}, ... ],
    "closing":   {headline, cta},
    "caption":   "<IG caption body>",
}
```

Each item gets resolved via TMDB at render time → title, year, director, runtime, poster, backdrop, genres, watch providers (UK/GB region by default).

## Dedupe — never repost a list

`ship_list_post.py` writes the dedupe key `list:<slug>` to `posted.jsonl`. The brain's `is_fact_posted("list:<slug>")` catches re-attempts and aborts before any IG call.

**Each pack ships once, ever.** New packs are the answer to "we want a sci-fi list again", not re-running an old one. The slug is the identity.

Because the dedupe key is the pack slug (not individual TMDB ids), the same film CAN appear across multiple packs — that's intentional. Annihilation might be in `mind_bending_scifi` AND a future `alex_garland_films` pack and that's fine.

## Cadence (editorial, use judgment)

- Fact carousels: 2/day (10:00 + 18:00) Mon–Sun, autonomous
- List posts: roughly weekly, manual fire. Saturday or Sunday evening is a natural slot
- If a great pack is ready and the feed could use it, ship it. Don't wait for an arbitrary cooldown timer.
- If the audience is engaging well with one domain, lean in for a couple of weeks rather than forcing rotation.

## Variety guard rails (guidance, not gates)

The whole point of lists is to feel different from facts. Things worth varying — but worth breaking when curation calls for it:

- **Domain**: film, TV, albums, books, games, docs, photographers, tools. Mix is healthier than mono-culture. But two great film packs back-to-back beats a mediocre album pack just to "rotate".
- **Tone**: shocking, wholesome, cult, prestige, cosy, weird. A wholesome pack after a heavy fact week reads as deliberate counter-programming.
- **Framing word**: don't open two consecutive pack titles with the same hook word. "Five mind-bending films" then "Five mind-bending TV series" reads as a single thought stretched too thin. Use different angles even when picks overlap thematically.
- **Length**: 5 is typical. 3–7 are all acceptable. A focused trio is fine when the items are strong enough to carry the pack.

Domains beyond film/TV need their own data adapter (the `tmdb_client.py` analogue) and possibly a per-domain slide template variant if the visual differs (album art is square; book covers are portrait but no backdrop).

Currently wired:
- `kind: "movie"` — TMDB lookup, full poster + backdrop pipeline

Stub-ready (need adapter):
- `kind: "tv"` — TMDB has a `/tv/{id}` endpoint, same shape
- `kind: "album"` — Spotify Web API, square art, no backdrop
- `kind: "book"` — OpenLibrary covers, no backdrop
- `kind: "game"` — IGDB cover + screenshot

## Pack ideas backlog

Keep at least 5 unshipped packs in `list_packs.py` so we always have something to ship. Drop new packs into the dict, tag them with a `# TODO: ship` comment.

Some seeds:

- `documentaries_that_rewire_you` — The Act of Killing, Stop Making Sense, Threads, Man on Wire, Grizzly Man
- `films_made_for_nothing` — Primer, Clerks, El Mariachi, Tangerine, Following
- `directors_debut_features` — Reservoir Dogs, Following, Bottle Rocket, Following, etc
- `cult_films_most_people_missed` — A Field in England, Beyond the Black Rainbow, Upstream Color
- `non_english_sci_fi` — Stalker, World on a Wire, La Jetée, Solaris (1972), I'm a Cyborg

Curate with the factjot voice: "stuff you didn't know about", not "Rotten Tomatoes top 100".

## Score chip layout

`list_item.html.j2` renders score chips for IMDB + Rotten Tomatoes. Pack-level overrides win; OMDb auto-fetch (when `OMDB_API_KEY` is set) fills any gap. Layout is bold-mono labels above bold-mono accent values, dark pill background.

## Watch providers

`tmdb_client.py:get_watch_providers(tmdb_id, region="GB")` returns canonical short names (PRIME, NETFLIX, ITVX, etc) for UK flatrate streaming. Sub-channel passes ("Arrow Video Channel", "with Ads" variants) are filtered out in `_short_provider_name`. Films with no UK streaming hide the row entirely instead of showing "RENT" (we don't push purchases).

## When the pipeline fails mid-publish

`ship_list_post.py` returns exit-code 7 BEFORE `record_publish` if the IG call errors. That means a failed publish does NOT pollute `posted.jsonl` — the dedupe gate stays open and a retry is safe. Don't add brain entries on failure.
