"""Route a free-text fact claim to one of factjot's known topics.

Keyword-based, deterministic, fast. Used by `scripts/discover_facts.py` and
any future feed-processor to slot a claim into `space`, `earth`, `ocean`,
`biology`, `history`, `technology`, or fall back to `science`.
"""
from __future__ import annotations

import re

# Topic → keyword set. First match wins, in declared order.
# Most specific topics listed first so a claim mentioning both "ocean" and
# "earth" routes to ocean.
TOPIC_KEYWORDS: list[tuple[str, set[str]]] = [
    ("space", {
        "space", "planet", "galaxy", "galaxies", "nebula", "cosmos", "universe",
        "milky way", "andromeda", "supernova", "black hole",
        "saturn", "venus", "mars", "jupiter", "mercury", "neptune", "uranus", "pluto",
        "moon", "lunar", "asteroid", "comet", "meteor", "meteorite",
        "astronaut", "spacecraft", "satellite", "rocket", "voyager", "hubble",
        "iss", "space station", "space shuttle",
        "olympus mons", "valles marineris", "interstellar", "starfield", "nasa",
    }),
    ("ocean", {
        "ocean", "marine", "underwater", "seafloor", "sea floor", "abyssal",
        "trench", "mariana", "challenger deep", "reef", "coral",
        "whale", "dolphin", "shark", "octopus", "jellyfish", "plankton",
        "tide", "wave", "tsunami", "current",
    }),
    ("earth", {
        "earth", "geology", "continent", "tectonic", "volcano", "volcanic",
        "earthquake", "fault", "crust", "mantle", "core",
        "mountain", "everest", "himalaya", "andes", "rockies",
        "antarctica", "arctic", "iceberg", "glacier", "permafrost",
        "desert", "sahara", "rainforest", "amazon",
        "lightning", "weather", "climate", "atmosphere", "fungus",
    }),
    ("biology", {
        "animal", "wildlife", "creature", "species", "biology", "biological",
        "octopus", "shark", "bee", "ant", "spider", "tardigrade",
        "cow", "sheep", "horse", "dog", "cat",
        "bird", "crow", "owl", "eagle", "parrot",
        "tree", "plant", "fungus", "microbe", "bacteria", "virus",
        "dna", "evolution", "cell", "neuron", "brain",
        "extinct", "fossil", "dinosaur",
    }),
    ("history", {
        "history", "ancient", "medieval", "century", "empire", "dynasty",
        "rome", "roman", "egypt", "egyptian", "pharaoh", "pyramid",
        "greece", "greek", "persian", "viking", "mongol",
        "war", "battle", "revolution", "siege", "treaty",
        "king", "queen", "emperor", "napoleon", "cleopatra", "shakespeare",
        "renaissance", "industrial revolution", "victorian",
    }),
    ("technology", {
        "technology", "computer", "software", "hardware", "internet",
        "wifi", "wi-fi", "wireless", "router", "ethernet",
        "smartphone", "iphone", "android", "tablet",
        "ai", "artificial intelligence", "neural network", "algorithm",
        "code", "programming", "programmer", "engineer",
        "transistor", "chip", "processor", "cpu", "gpu",
        "robot", "robotic", "drone",
        "metaverse", "virtual reality", "vr", "ar",
        "qwerty", "keyboard", "typewriter",
    }),
]

DEFAULT_TOPIC = "science"

# Image-hint hints per detected keyword. Lets the discoverer pre-fill an
# image_hint that maps cleanly to known image-fetcher behaviours.
IMAGE_HINT_MAP: dict[str, str] = {
    # space
    "saturn": "Saturn planet rings",
    "venus": "Venus planet surface NASA",
    "mars": "Mars planet surface red",
    "jupiter": "Jupiter planet storm",
    "mercury": "Mercury planet",
    "moon": "Moon surface lunar",
    "andromeda": "Andromeda galaxy",
    "voyager": "Voyager spacecraft Jupiter Saturn deep space illustration",
    "olympus mons": "Mars volcano red planet surface",
    "iss": "International Space Station orbit",
    "astronaut": "astronaut spacewalk",
    # earth
    "antarctica": "Antarctica ice landscape",
    "everest": "Mount Everest",
    "sahara": "Sahara desert dunes",
    "lightning": "lightning storm sky",
    # ocean
    "octopus": "octopus underwater",
    "shark": "shark underwater",
    "whale": "whale ocean diving",
    "mariana": "deep sea trench",
    # biology
    "tardigrade": "water bear microscope",
    "honey bee": "honey bee flower",
    "spider": "spider web macro",
    "sloth": "sloth tree rainforest",
    "ant": "ant macro insect",
    "crow": "crow black bird",
    "bee": "honey bee flower",
    # history
    "cleopatra": "ancient Egypt artifact",
    "napoleon": "Napoleon portrait painting",
    "rome": "Roman Colosseum",
    "colosseum": "Roman Colosseum",
    "great fire of london": "old London engraving",
    "eiffel": "Eiffel Tower Paris",
    "pyramid": "Egyptian pyramids Giza",
    # technology
    "smartphone": "smartphone technology",
    "metaverse": "virtual reality headset",
    "qwerty": "typewriter qwerty keyboard",
    "wifi": "wifi router wireless",
    "neutron star": "neutron star space",
    "apollo": "Moon footprint surface",
}


def route_to_topic(claim: str) -> str:
    text = claim.lower()
    for topic, keywords in TOPIC_KEYWORDS:
        if any(_present(kw, text) for kw in keywords):
            return topic
    return DEFAULT_TOPIC


def suggest_image_hint(claim: str, topic: str) -> str:
    text = claim.lower()
    # Prefer multi-word specific hints first (longer keys).
    for key in sorted(IMAGE_HINT_MAP.keys(), key=len, reverse=True):
        if _present(key, text):
            return IMAGE_HINT_MAP[key]
    # Fallback: empty hint (carousel generator will auto-extract).
    return ""


def _present(keyword: str, text: str) -> bool:
    if " " in keyword:
        return keyword in text
    # Whole-word match for single tokens to avoid "art" matching "earth".
    return re.search(rf"\b{re.escape(keyword)}\b", text) is not None
