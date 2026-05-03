"""Curated list packs for entertainment carousels.

Each pack is a hand-picked themed list (e.g. "5 mind-melting sci-fi films").
We intentionally do NOT pull from TMDB top-rated lists - those surface the
same obvious blockbusters every time. The factjot voice is "stuff you didn't
know about", so list curation is human-driven. TMDB is just the metadata +
image source.

A pack contains:

    slug         - file-safe id, used as post_id seed and brain dedupe key
    title        - hook-slide headline (Instrument Serif italic)
    subtitle     - hook-slide kicker line
    category     - slide-corner pill label, e.g. "FILM LIST"
    series       - brand series tag (always "factjot" for now)
    items        - ordered list of dicts:
        kind     - currently "movie" only; later: "tv", "book", "album"
        tmdb_id  - TMDB integer id (resolve manually before adding here)
        hook     - 1-2 sentence pitch in factjot voice (will appear under title)
        accent_word - optional word/phrase from the hook to wrap in [h]…[/h]
                      so it renders italic+orange. If absent, no highlight.
    closing      - dict with `headline` + `cta` for the recap slide
    caption      - IG caption body. Hashtags appended automatically.

Pack rules:
    - 5 items per pack is the standard. 4 minimum, 6 maximum.
    - Items must have a backdrop_path on TMDB (we check at render time).
    - Hooks must be ≤ 200 chars and stay in voice (no flattery, no em dashes).
    - The pack's first item should be the most visually striking - its
      backdrop is reused for the hook slide.
"""
from __future__ import annotations

# slug -> pack
LIST_PACKS: dict[str, dict] = {
    "war_films_definitive": {
        "slug": "war_films_definitive",
        "title": "Eight war films worth your time",
        "subtitle": "ranked by staying power, not box office.",
        "category": "FILM LIST",
        "series": "factjot",
        "items": [
            {
                "kind": "movie",
                "tmdb_id": 28,
                "expected_title": "Apocalypse Now",
                "hook": "A US captain travels upriver through Vietnam to find a rogue colonel who has declared himself a god. Coppola lost his mind making it. The film is better for it.",
                "accent_word": "declared himself a god",
                "imdb_score": "8.4",
                "rotten_score": "98%",
                "genre": "WAR",
            },
            {
                "kind": "movie",
                "tmdb_id": 857,
                "expected_title": "Saving Private Ryan",
                "hook": "The Omaha Beach sequence runs 27 unbroken minutes and has never been equalled. Everything that follows is quieter and just as devastating.",
                "accent_word": "27 unbroken minutes",
                "imdb_score": "8.6",
                "rotten_score": "93%",
                "genre": "WAR",
            },
            {
                "kind": "movie",
                "tmdb_id": 975,
                "expected_title": "Paths of Glory",
                "hook": "Three French soldiers are court-martialled for cowardice after a suicidal attack their commanders ordered knowing it would fail. Kubrick at 29. Banned in France for 18 years.",
                "accent_word": "banned in France for 18 years",
                "imdb_score": "8.4",
                "rotten_score": "96%",
                "genre": "WAR",
            },
            {
                "kind": "movie",
                "tmdb_id": 600,
                "expected_title": "Full Metal Jacket",
                "hook": "Two films stitched together: a boot camp that ends in murder, and a war that ends in nothing. Kubrick shot the entire Vietnam sequence in a derelict gasworks in East London.",
                "accent_word": "East London",
                "imdb_score": "8.0",
                "rotten_score": "91%",
                "genre": "WAR",
            },
            {
                "kind": "movie",
                "tmdb_id": 387,
                "expected_title": "Das Boot",
                "hook": "A German submarine crew in 1941. Months of claustrophobia and creeping dread, then sudden violent death. The most uncomfortable two and a half hours in cinema.",
                "accent_word": "creeping dread",
                "imdb_score": "8.4",
                "rotten_score": "99%",
                "genre": "WAR",
            },
            {
                "kind": "movie",
                "tmdb_id": 11778,
                "expected_title": "The Deer Hunter",
                "hook": "Three friends go to Vietnam. What it does to them is shown slowly, obliquely, without mercy. Won five Oscars. The Russian roulette sequences are not a metaphor.",
                "accent_word": "not a metaphor",
                "imdb_score": "8.1",
                "rotten_score": "93%",
                "genre": "WAR",
            },
            {
                "kind": "movie",
                "tmdb_id": 530915,
                "expected_title": "1917",
                "hook": "Two soldiers have six hours to deliver a message that could save 1,600 lives. Shot to appear as a single continuous take. It is not - but you will never find the cut.",
                "accent_word": "you will never find the cut",
                "imdb_score": "8.3",
                "rotten_score": "89%",
                "genre": "WAR",
            },
            {
                "kind": "movie",
                "tmdb_id": 792,
                "expected_title": "Platoon",
                "hook": "Oliver Stone served two tours in Vietnam. This is what he saw. Not a reconstruction. Won Best Picture.",
                "accent_word": "not a reconstruction",
                "imdb_score": "7.8",
                "rotten_score": "87%",
                "genre": "WAR",
            },
            {
                "kind": "movie",
                "tmdb_id": 374720,
                "expected_title": "Dunkirk",
                "hook": "338,000 men evacuated from a beach with no plan and nowhere near enough boats. Three timelines that converge at the same moment. No score, just sound design.",
                "accent_word": "no plan",
                "imdb_score": "7.8",
                "rotten_score": "92%",
                "genre": "WAR",
            },
            {
                "kind": "movie",
                "tmdb_id": 324786,
                "expected_title": "Hacksaw Ridge",
                "hook": "Desmond Doss refused to carry a weapon. He was mocked, beaten, court-martialled. Then he saved 75 men at Okinawa and became the only conscientious objector to receive the Medal of Honor.",
                "accent_word": "only conscientious objector",
                "imdb_score": "8.1",
                "rotten_score": "84%",
                "genre": "WAR",
            },
        ],
        "closing": {
            "headline": "Save this list.",
            "cta": "Follow @factjot for more.",
        },
        "caption": (
            "Ten war films. Ranked by staying power. "
            "Every one of these will change how you think about the genre. "
            "Sources via TMDB."
        ),
    },
    "series_worth_your_weekend": {
        "slug": "series_worth_your_weekend",
        "title": "Five sci-fi series worth your weekend",
        "subtitle": "no padding, no eight-season slog.",
        "category": "TV LIST",
        "series": "factjot",
        "items": [
            {
                "kind": "tv",
                "tmdb_id": 95396,  # Severance (2022) - Dan Erickson
                "expected_title": "Severance",
                "hook": "Office workers volunteer for a brain implant that walls their work selves off from their personal lives. The smartest premise on prestige TV.",
                "accent_word": "walls their work selves off",
                "imdb_score": "8.7",
                "rotten_score": "97%",
                "genre": "SCI-FI",
            },
            {
                "kind": "tv",
                "tmdb_id": 70523,  # Dark (2017) - Baran bo Odar / Jantje Friese
                "expected_title": "Dark",
                "hook": "Children disappear in a small German town. The mystery threads four generations of one family across decades.",
                "accent_word": "four generations",
                "imdb_score": "8.7",
                "rotten_score": "95%",
                "genre": "SCI-FI",
            },
            {
                "kind": "tv",
                "tmdb_id": 81349,  # Devs (2020) - Alex Garland
                "expected_title": "Devs",
                "hook": "A tech billionaire's secret quantum project hidden in a Silicon Valley campus. From the writer of Annihilation, slow-burning and quietly terrifying.",
                "accent_word": "secret quantum project",
                "imdb_score": "7.8",
                "rotten_score": "86%",
                "genre": "SCI-FI",
            },
            {
                "kind": "tv",
                "tmdb_id": 93784,  # Tales from the Loop (2020) - Nathaniel Halpern
                "expected_title": "Tales from the Loop",
                "hook": "Anthology episodes set around an underground physics experiment. Each story is a quiet meditation on time, memory, and loss.",
                "accent_word": "quiet meditation",
                "imdb_score": "7.5",
                "rotten_score": "89%",
                "genre": "SCI-FI",
            },
            {
                "kind": "tv",
                "tmdb_id": 69061,  # The OA (2016) - Brit Marling / Zal Batmanglij
                "expected_title": "The OA",
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
                "tmdb_id": 329865,  # Arrival (2016) - Denis Villeneuve
                "expected_title": "Arrival",
                "hook": "Twelve alien craft appear across the planet. A linguist is the world's last shot at understanding what they want before someone fires.",
                "accent_word": "twelve alien craft",
                "imdb_score": "7.9",
                "rotten_score": "94%",
                "genre": "SCI-FI",
            },
            {
                "kind": "movie",
                "tmdb_id": 220289,  # Coherence (2013) - James Ward Byrkit
                "expected_title": "Coherence",
                "hook": "One dinner party. A passing comet. Suddenly there are several houses on the street, and several versions of every guest.",
                "accent_word": "several versions",
                "imdb_score": "7.2",
                "rotten_score": "88%",
                "genre": "SCI-FI",
            },
            {
                "kind": "movie",
                "tmdb_id": 14337,  # Primer (2004) - Shane Carruth
                "expected_title": "Primer",
                "hook": "Two engineers build a time machine in a garage on a 7,000 dollar budget. Nobody who watches it can fully agree on what happens.",
                "accent_word": "7,000 dollar",
                "imdb_score": "6.8",
                "rotten_score": "72%",
                "genre": "SCI-FI",
            },
            {
                "kind": "movie",
                "tmdb_id": 206487,  # Predestination (2014) - Spierig brothers
                "expected_title": "Predestination",
                "hook": "A time-travelling agent hunts a bomber across decades. The twist is so neat you can re-watch it as a different film.",
                "accent_word": "re-watch it as a different film",
                "imdb_score": "7.4",
                "rotten_score": "84%",
                "genre": "SCI-FI",
            },
            {
                "kind": "movie",
                "tmdb_id": 300668,  # Annihilation (2018) - Alex Garland
                "expected_title": "Annihilation",
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
    "war_films": {
        "slug": "war_films",
        "title": "Five war films that don't glorify it",
        "subtitle": "the ones that show what it actually costs.",
        "category": "FILM LIST",
        "series": "factjot",
        "items": [
            {
                "kind": "movie",
                "tmdb_id": 374720,  # Dunkirk (2017) - Christopher Nolan
                "expected_title": "Dunkirk",
                "hook": "400,000 soldiers stranded on a beach. Nolan strips out all dialogue you don't need and leaves only the noise of dying.",
                "accent_word": "400,000 soldiers",
                "imdb_score": "7.8",
                "rotten_score": "92%",
                "genre": "WAR",
            },
            {
                "kind": "movie",
                "tmdb_id": 530915,  # 1917 (2019) - Sam Mendes
                "expected_title": "1917",
                "hook": "Two soldiers cross no man's land to stop an ambush. Shot to appear as one unbroken take. The tension never releases.",
                "accent_word": "one unbroken take",
                "imdb_score": "8.3",
                "rotten_score": "89%",
                "genre": "WAR",
            },
            {
                "kind": "movie",
                "tmdb_id": 324786,  # Hacksaw Ridge (2016) - Mel Gibson
                "expected_title": "Hacksaw Ridge",
                "hook": "A conscientious objector refuses to carry a weapon and saves 75 men at Okinawa. Based entirely on a true story.",
                "accent_word": "75 men",
                "imdb_score": "8.1",
                "rotten_score": "84%",
                "genre": "WAR",
            },
            {
                "kind": "movie",
                "tmdb_id": 11329,  # Come and See (1985) - Elem Klimov
                "expected_title": "Come and See",
                "hook": "A Belarusian boy joins the resistance in 1943. The most viscerally disturbing anti-war film ever made. Watch it once.",
                "accent_word": "most viscerally disturbing",
                "imdb_score": "8.3",
                "rotten_score": "100%",
                "genre": "WAR",
            },
            {
                "kind": "movie",
                "tmdb_id": 857,  # Saving Private Ryan (1998) - Steven Spielberg
                "expected_title": "Saving Private Ryan",
                "hook": "The D-Day opening is 27 minutes long and still the most accurate depiction of the beach landings ever committed to film.",
                "accent_word": "27 minutes",
                "imdb_score": "8.6",
                "rotten_score": "93%",
                "genre": "WAR",
            },
        ],
        "closing": {
            "headline": "Save this list.",
            "cta": "Follow @factjot for more.",
        },
        "caption": (
            "Five war films that make you feel the weight of it, not the thrill. "
            "No glory, no easy heroism. Each one is a different angle on the same "
            "horror. Sources via TMDB."
        ),
    },
    "horror_films": {
        "slug": "horror_films",
        "title": "Five horror films that actually scared people",
        "subtitle": "no jump scares. pure dread.",
        "category": "HORROR LIST",
        "series": "factjot",
        "items": [
            {
                "kind": "movie",
                "tmdb_id": 493922,  # Hereditary (2018) - Ari Aster
                "expected_title": "Hereditary",
                "hook": "A family inherits more than grief after their grandmother dies. The scariest film in a decade, and it barely raises its voice.",
                "accent_word": "barely raises its voice",
                "imdb_score": "7.3",
                "rotten_score": "89%",
                "genre": "HORROR",
            },
            {
                "kind": "movie",
                "tmdb_id": 310131,  # The Witch (2015) - Robert Eggers
                "expected_title": "The Witch",
                "hook": "A Puritan family is banished to the edge of a New England forest in 1630. Something is wrong with the woods. Something is wrong with the goat.",
                "accent_word": "wrong with the goat",
                "imdb_score": "6.9",
                "rotten_score": "90%",
                "genre": "HORROR",
            },
            {
                "kind": "movie",
                "tmdb_id": 419430,  # Get Out (2017) - Jordan Peele
                "expected_title": "Get Out",
                "hook": "A Black man visits his white girlfriend's family for the weekend. Jordan Peele's debut is a horror film about a horror that already exists.",
                "accent_word": "already exists",
                "imdb_score": "7.7",
                "rotten_score": "98%",
                "genre": "HORROR",
            },
            {
                "kind": "movie",
                "tmdb_id": 272841,  # It Follows (2014) - David Robert Mitchell
                "expected_title": "It Follows",
                "hook": "After a sexual encounter, something starts following you. It walks. It never stops. The concept is simple and relentless.",
                "accent_word": "walks. It never stops",
                "imdb_score": "6.8",
                "rotten_score": "96%",
                "genre": "HORROR",
            },
            {
                "kind": "movie",
                "tmdb_id": 447332,  # A Quiet Place (2018) - John Krasinski
                "expected_title": "A Quiet Place",
                "hook": "Creatures hunt by sound. A family with a deaf daughter has a slight advantage. A horror film with almost no dialogue.",
                "accent_word": "almost no dialogue",
                "imdb_score": "7.5",
                "rotten_score": "95%",
                "genre": "HORROR",
            },
        ],
        "closing": {
            "headline": "Save this list.",
            "cta": "Follow @factjot for more.",
        },
        "caption": (
            "Five horror films that work through atmosphere and dread, not shock. "
            "Each one has something genuinely unsettling at its core. "
            "Watch them alone. Sources via TMDB."
        ),
    },
    "crime_thrillers": {
        "slug": "crime_thrillers",
        "title": "Five crime thrillers that keep you guessing",
        "subtitle": "plots that don't insult your intelligence.",
        "category": "FILM LIST",
        "series": "factjot",
        "items": [
            {
                "kind": "movie",
                "tmdb_id": 207,  # No Country for Old Men (2007) - Coen Brothers
                "expected_title": "No Country for Old Men",
                "hook": "A hunter stumbles onto a drug deal gone wrong and takes the money. What follows him is not a man in any normal sense.",
                "accent_word": "not a man in any normal sense",
                "imdb_score": "8.2",
                "rotten_score": "93%",
                "genre": "THRILLER",
            },
            {
                "kind": "movie",
                "tmdb_id": 769,  # Chinatown (1974) - Roman Polanski
                "expected_title": "Chinatown",
                "hook": "A private detective in 1930s Los Angeles takes a simple adultery case. It leads somewhere no detective ever comes back from clean.",
                "accent_word": "no detective ever comes back from clean",
                "imdb_score": "8.2",
                "rotten_score": "99%",
                "genre": "THRILLER",
            },
            {
                "kind": "movie",
                "tmdb_id": 745,  # Se7en (1995) - David Fincher
                "expected_title": "Se7en",
                "hook": "Two detectives hunt a killer using the seven deadly sins as a template. The ending is one of cinema's most unflinching.",
                "accent_word": "most unflinching",
                "imdb_score": "8.6",
                "rotten_score": "82%",
                "genre": "THRILLER",
            },
            {
                "kind": "movie",
                "tmdb_id": 497,  # The Departed (2006) - Martin Scorsese
                "expected_title": "The Departed",
                "hook": "An undercover cop inside the mob. A mob mole inside the police. Each is hunting the other without knowing who they are.",
                "accent_word": "hunting the other",
                "imdb_score": "8.5",
                "rotten_score": "91%",
                "genre": "THRILLER",
            },
            {
                "kind": "movie",
                "tmdb_id": 274,  # The Silence of the Lambs (1991) - Jonathan Demme
                "expected_title": "The Silence of the Lambs",
                "hook": "An FBI trainee asks a cannibal psychiatrist to help catch a serial killer. He agrees. The price is a conversation.",
                "accent_word": "price is a conversation",
                "imdb_score": "8.6",
                "rotten_score": "95%",
                "genre": "THRILLER",
            },
        ],
        "closing": {
            "headline": "Save this list.",
            "cta": "Follow @factjot for more.",
        },
        "caption": (
            "Five crime thrillers that hold together under repeat viewing. "
            "Smart writing, no easy resolutions. If you've seen them all, "
            "you know why they're on here. Sources via TMDB."
        ),
    },
    "films_for_bad_days": {
        "slug": "films_for_bad_days",
        "title": "Five films for when you've had a terrible day",
        "subtitle": "comfort viewing that isn't condescending.",
        "category": "FILM LIST",
        "series": "factjot",
        "items": [
            {
                "kind": "movie",
                "tmdb_id": 346648,  # Paddington 2 (2017) - Paul King
                "expected_title": "Paddington 2",
                "hook": "Paddington goes to prison. Somehow it is the warmest film of the decade. Critics called it one of the best sequels ever made.",
                "accent_word": "warmest film of the decade",
                "imdb_score": "7.8",
                "rotten_score": "99%",
                "genre": "COMEDY",
            },
            {
                "kind": "movie",
                "tmdb_id": 409,  # Amelie (2001) - Jean-Pierre Jeunet
                "expected_title": "Amelie",
                "hook": "A Parisian woman quietly improves the lives of strangers while avoiding her own happiness. Visually unlike anything else from 2001.",
                "accent_word": "quietly improves",
                "imdb_score": "8.3",
                "rotten_score": "89%",
                "genre": "COMEDY",
            },
            {
                "kind": "movie",
                "tmdb_id": 140607,  # Sing Street (2016) - John Carney
                "expected_title": "Sing Street",
                "hook": "A Dublin teenager starts a band to impress a girl in 1985. Every song is good. Every scene is kind.",
                "accent_word": "every scene is kind",
                "imdb_score": "7.9",
                "rotten_score": "97%",
                "genre": "DRAMA",
            },
            {
                "kind": "movie",
                "tmdb_id": 245891,  # John Wick (2014) - Chad Stahelski
                "expected_title": "John Wick",
                "hook": "A retired hitman's dog is killed. What follows is two hours of extremely cathartic precision violence. Exactly what some days need.",
                "accent_word": "extremely cathartic",
                "imdb_score": "7.4",
                "rotten_score": "86%",
                "genre": "ACTION",
            },
            {
                "kind": "movie",
                "tmdb_id": 72105,  # Chef (2014) - Jon Favreau
                "expected_title": "Chef",
                "hook": "A chef quits his restaurant job, buys a food truck, and drives it across America with his son. Nobody is a villain.",
                "accent_word": "nobody is a villain",
                "imdb_score": "7.3",
                "rotten_score": "86%",
                "genre": "DRAMA",
            },
        ],
        "closing": {
            "headline": "Save this list.",
            "cta": "Follow @factjot for more.",
        },
        "caption": (
            "Five films that are genuinely good for you on a rough day. "
            "Not saccharine, not stupid. Just well-made stories that leave you "
            "feeling something other than drained. Sources via TMDB."
        ),
    },
    "directors_first_features": {
        "slug": "directors_first_features",
        "title": "Five debut films that announced a director",
        "subtitle": "before they were household names.",
        "category": "FILM LIST",
        "series": "factjot",
        "items": [
            {
                "kind": "movie",
                "tmdb_id": 11134,  # Following (1998) - Christopher Nolan
                "expected_title": "Following",
                "hook": "Nolan's debut, shot on weekends for 6,000 dollars in black and white. A neo-noir about a writer who follows strangers. It works completely.",
                "accent_word": "6,000 dollars",
                "imdb_score": "7.5",
                "rotten_score": "79%",
                "genre": "THRILLER",
            },
            {
                "kind": "movie",
                "tmdb_id": 500,  # Reservoir Dogs (1992) - Quentin Tarantino
                "expected_title": "Reservoir Dogs",
                "hook": "A diamond heist that the film never shows. Just the aftermath, a warehouse, and a cast of criminals who don't trust each other.",
                "accent_word": "never shows",
                "imdb_score": "8.3",
                "rotten_score": "91%",
                "genre": "THRILLER",
            },
            {
                "kind": "movie",
                "tmdb_id": 10929,  # Pi (1998) - Darren Aronofsky
                "expected_title": "Pi",
                "hook": "A mathematician believes a 216-digit number holds the key to everything. Shot in paranoid black and white for 60,000 dollars.",
                "accent_word": "key to everything",
                "imdb_score": "7.4",
                "rotten_score": "84%",
                "genre": "THRILLER",
            },
            {
                "kind": "movie",
                "tmdb_id": 40096,  # Bottle Rocket (1996) - Wes Anderson
                "expected_title": "Bottle Rocket",
                "hook": "Three friends with no criminal talent attempt to become criminals. Wes Anderson's first film, before the symmetry fully locked in.",
                "accent_word": "no criminal talent",
                "imdb_score": "7.0",
                "rotten_score": "85%",
                "genre": "COMEDY",
            },
            {
                "kind": "movie",
                "tmdb_id": 666,  # Eraserhead (1977) - David Lynch
                "expected_title": "Eraserhead",
                "hook": "Lynch's first feature took five years to make and was shot mostly at night. Nobody agreed on what it meant, including Lynch.",
                "accent_word": "five years to make",
                "imdb_score": "7.4",
                "rotten_score": "89%",
                "genre": "HORROR",
            },
        ],
        "closing": {
            "headline": "Save this list.",
            "cta": "Follow @factjot for more.",
        },
        "caption": (
            "Five debut features that signalled exactly what kind of director "
            "was coming. All made on tiny budgets, all completely singular. "
            "A masterclass in doing more with less. Sources via TMDB."
        ),
    },
}


# ---------------------------------------------------------------------------
# Pack backlog - seeded stubs for the next few Saturdays.
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
        "intent": "Docs that change how you think - not just inform. The Act of Killing, Stop Making Sense, Grizzly Man, Man on Wire, Threads.",
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
