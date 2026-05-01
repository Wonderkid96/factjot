"""Curated list packs for entertainment carousels.

Each pack is a hand-picked themed list (e.g. "5 mind-melting sci-fi films").
We intentionally do NOT pull from TMDB top-rated lists — those surface the
same obvious blockbusters every time. The factjot voice is "stuff you didn't
know about", so list curation is human-driven. TMDB is just the metadata +
image source.

A pack contains:

    slug         — file-safe id, used as post_id seed and brain dedupe key
    title        — hook-slide headline (Instrument Serif italic)
    subtitle     — hook-slide kicker line
    category     — slide-corner pill label, e.g. "FILM LIST"
    series       — brand series tag (always "factjot" for now)
    items        — ordered list of dicts:
        kind     — currently "movie" only; later: "tv", "book", "album"
        tmdb_id  — TMDB integer id (resolve manually before adding here)
        hook     — 1-2 sentence pitch in factjot voice (will appear under title)
        accent_word — optional word/phrase from the hook to wrap in [h]…[/h]
                      so it renders italic+orange. If absent, no highlight.
    closing      — dict with `headline` + `cta` for the recap slide
    caption      — IG caption body. Hashtags appended automatically.

Pack rules:
    - 5 items per pack is the standard. 4 minimum, 6 maximum.
    - Items must have a backdrop_path on TMDB (we check at render time).
    - Hooks must be ≤ 200 chars and stay in voice (no flattery, no em dashes).
    - The pack's first item should be the most visually striking — its
      backdrop is reused for the hook slide.
"""
from __future__ import annotations

# slug -> pack
LIST_PACKS: dict[str, dict] = {
    "series_worth_your_weekend": {
        "slug": "series_worth_your_weekend",
        "title": "Five sci-fi series worth your weekend",
        "subtitle": "no padding, no eight-season slog.",
        "category": "TV LIST",
        "series": "factjot",
        "items": [
            {
                "kind": "tv",
                "tmdb_id": 95396,  # Severance (2022) — Dan Erickson
                "hook": "Office workers volunteer for a brain implant that walls their work selves off from their personal lives. The smartest premise on prestige TV.",
                "accent_word": "walls their work selves off",
                "imdb_score": "8.7",
                "rotten_score": "97%",
                "genre": "SCI-FI",
            },
            {
                "kind": "tv",
                "tmdb_id": 70523,  # Dark (2017) — Baran bo Odar / Jantje Friese
                "hook": "Children disappear in a small German town. The mystery threads four generations of one family across decades.",
                "accent_word": "four generations",
                "imdb_score": "8.7",
                "rotten_score": "95%",
                "genre": "SCI-FI",
            },
            {
                "kind": "tv",
                "tmdb_id": 81349,  # Devs (2020) — Alex Garland
                "hook": "A tech billionaire's secret quantum project hidden in a Silicon Valley campus. From the writer of Annihilation, slow-burning and quietly terrifying.",
                "accent_word": "secret quantum project",
                "imdb_score": "7.8",
                "rotten_score": "86%",
                "genre": "SCI-FI",
            },
            {
                "kind": "tv",
                "tmdb_id": 93784,  # Tales from the Loop (2020) — Nathaniel Halpern
                "hook": "Anthology episodes set around an underground physics experiment. Each story is a quiet meditation on time, memory, and loss.",
                "accent_word": "quiet meditation",
                "imdb_score": "7.5",
                "rotten_score": "89%",
                "genre": "SCI-FI",
            },
            {
                "kind": "tv",
                "tmdb_id": 69061,  # The OA (2016) — Brit Marling / Zal Batmanglij
                "hook": "A blind woman returns home with her sight restored after seven years missing. The story she tells is unlike anything else on television.",
                "accent_word": "unlike anything else",
                "imdb_score": "7.7",
                "rotten_score": "78%",
                "genre": "SCI-FI",
            },
        ],
        "closing": {
            "headline": "Save this list.",
            "cta": "Follow @factjot for more.",
        },
        "caption": (
            "Five TV shows that mess with your head and respect your time. "
            "Each is a contained run you can finish without it dragging into "
            "season nine. Save it, work through them. Sources via TMDB."
        ),
    },
    "mind_bending_scifi": {
        "slug": "mind_bending_scifi",
        "title": "Five mind-bending sci-fi films",
        "subtitle": "you've probably never seen.",
        "category": "FILM LIST",
        "series": "factjot",
        "items": [
            {
                "kind": "movie",
                "tmdb_id": 329865,  # Arrival (2016) — Denis Villeneuve
                "hook": "Twelve alien craft appear across the planet. A linguist is the world's last shot at understanding what they want before someone fires.",
                "accent_word": "twelve alien craft",
                "imdb_score": "7.9",
                "rotten_score": "94%",
                "genre": "SCI-FI",
            },
            {
                "kind": "movie",
                "tmdb_id": 220289,  # Coherence (2013) — James Ward Byrkit
                "hook": "One dinner party. A passing comet. Suddenly there are several houses on the street, and several versions of every guest.",
                "accent_word": "several versions",
                "imdb_score": "7.2",
                "rotten_score": "88%",
                "genre": "SCI-FI",
            },
            {
                "kind": "movie",
                "tmdb_id": 14337,  # Primer (2004) — Shane Carruth
                "hook": "Two engineers build a time machine in a garage on a 7,000 dollar budget. Nobody who watches it can fully agree on what happens.",
                "accent_word": "7,000 dollar",
                "imdb_score": "6.8",
                "rotten_score": "72%",
                "genre": "SCI-FI",
            },
            {
                "kind": "movie",
                "tmdb_id": 206487,  # Predestination (2014) — Spierig brothers
                "hook": "A time-travelling agent hunts a bomber across decades. The twist is so neat you can re-watch it as a different film.",
                "accent_word": "re-watch it as a different film",
                "imdb_score": "7.4",
                "rotten_score": "84%",
                "genre": "SCI-FI",
            },
            {
                "kind": "movie",
                "tmdb_id": 300668,  # Annihilation (2018) — Alex Garland
                "hook": "A team enters a shimmering zone where biology refuses to behave. From the director of Ex Machina, visually like nothing else.",
                "accent_word": "refuses to behave",
                "imdb_score": "6.8",
                "rotten_score": "89%",
                "genre": "SCI-FI",
            },
        ],
        "closing": {
            "headline": "Save this list.",
            "cta": "Follow @factjot for more.",
        },
        "caption": (
            "Five sci-fi films that mess with your head and stay with you. "
            "Each was made on a tight budget, none rely on spectacle. Save the "
            "list, work your way through. Sources via TMDB."
        ),
    },
}


# ---------------------------------------------------------------------------
# Pack backlog — seeded stubs for the next few Saturdays.
# Each stub has slug + title + subtitle + intent; items are TODO.
# Keep at least 4 stubs in flight so we never default to repeating a theme.
# Variety dimensions to rotate: TONE (shocking / wholesome / cult / prestige
# / cosy / weird), ANGLE (budget / era / country / director / format / mood),
# DOMAIN (film / TV / docs / albums / books / games / photographers).
# ---------------------------------------------------------------------------

PACK_BACKLOG_STUBS: dict[str, dict] = {
    "films_made_for_nothing": {
        "title": "Five films made for nothing",
        "subtitle": "and worth more than most blockbusters.",
        "category": "FILM LIST",
        "tone": "scrappy",
        "angle": "budget",
        "intent": "Sub-100k-dollar features that out-thought studio money. Primer ($7k), Clerks ($27k), Tangerine ($shot on iPhone), Following (Nolan's debut), El Mariachi.",
    },
    "comfort_films_for_bad_days": {
        "title": "Five comfort films for bad days",
        "subtitle": "the cinematic equivalent of a hot mug.",
        "category": "FILM LIST",
        "tone": "wholesome",
        "angle": "mood",
        "intent": "Counter-programming after a heavy week. Paddington 2, Studio Ghibli pick, Amelie, Chef, Sing Street.",
    },
    "documentaries_that_rewire_you": {
        "title": "Five documentaries that rewire you",
        "subtitle": "you'll see the world differently after each.",
        "category": "DOC LIST",
        "tone": "weighty",
        "angle": "form",
        "intent": "Docs that change how you think — not just inform. The Act of Killing, Stop Making Sense, Grizzly Man, Man on Wire, Threads.",
    },
    "non_english_masterpieces": {
        "title": "Five non-English films you'd be wrong to skip",
        "subtitle": "subtitles are a small price.",
        "category": "FILM LIST",
        "tone": "global",
        "angle": "geography",
        "intent": "Anti-Hollywood-default. Stalker (USSR), Oldboy (Korea), Spirited Away (Japan), City of God (Brazil), A Separation (Iran).",
    },
    "one_room_thrillers": {
        "title": "Five thrillers set in one room",
        "subtitle": "the constraint is the magic.",
        "category": "FILM LIST",
        "tone": "tense",
        "angle": "constraint",
        "intent": "Confined-space tension. Buried, Locke, Phone Booth, Rope, 12 Angry Men.",
    },
    "directors_first_features": {
        "title": "Five debut features that announced a director",
        "subtitle": "before they were household names.",
        "category": "FILM LIST",
        "tone": "prestige",
        "angle": "career",
        "intent": "First feature from now-major directors. Following (Nolan), Reservoir Dogs (Tarantino), Bottle Rocket (Wes Anderson), Pi (Aronofsky), Eraserhead (Lynch).",
    },
}


def get_pack(slug: str) -> dict:
    if slug not in LIST_PACKS:
        raise KeyError(
            f"Unknown list pack: {slug!r}. Known: {sorted(LIST_PACKS)}"
        )
    return LIST_PACKS[slug]


def list_packs() -> list[str]:
    return sorted(LIST_PACKS.keys())


def list_backlog_stubs() -> list[str]:
    """Pack ideas waiting to be fleshed out with TMDB ids + hooks."""
    return sorted(PACK_BACKLOG_STUBS.keys())


__all__ = ["LIST_PACKS", "PACK_BACKLOG_STUBS", "get_pack", "list_packs", "list_backlog_stubs"]
