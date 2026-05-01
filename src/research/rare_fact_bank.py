"""Curated bank of self-contained facts grouped by topic.

## Quality standard — MUST READ before adding any fact

Every fact must pass the SHOCK TEST before entry:

  "Would a smart adult who reads a lot genuinely say 'wait, WHAT?'"

If the answer is "probably, it's a nice fact" — it fails. If the answer is
"that seems impossible, I need to verify this" — it passes.

Three sub-tests:
  1. SUB-KNOWN: Not something a school-age child would know. Not something
     that has been widely shared as internet trivia (bananas radioactive,
     spider silk stronger than steel, tardigrades survive space = FAIL).
  2. SPECIFIC: A real name, number, date, or outcome. Vague facts are weak.
     "Some jellyfish are immortal" is weaker than "Turritopsis dohrnii can
     biologically reverse its own ageing cycle indefinitely."
  3. STAKES: The fact must have emotional or intellectual weight. Not just
     "interesting", but visceral, strange, unjust, or genuinely astonishing.

WEAK (do not add):
  - Animal anatomy quirks everyone has heard (hummingbirds fly backwards,
    cows have 360° vision, goats have rectangular pupils)
  - Common internet trivia (bananas slightly radioactive, wombat cube poo)
  - Cute-but-harmless facts (cows have best friends, sea otters hold hands)
  - Things that feel like a pub quiz rather than a revelation

STRONG (pass the shock test):
  - A single named person changed the course of history and almost nobody
    knows (Vasili Arkhipov, Hiroo Onoda, Radium Girls)
  - A natural phenomenon that sounds completely invented (Dancing Plague,
    Cordyceps, anglerfish biology, Door to Hell)
  - A number or scale that makes you recalculate something (Boötes Void,
    TON 618, Toba supervolcano)

quirky_score field:
  3 = shock tier (Reel-eligible, the only facts make_reel.py picks)
  2 = strong carousel fact (use freely)
  1 = standard fact (use sparingly — prefer upgrading or replacing)
  0 = textbook (do not use for carousels, only background bank)

`RARE_FACT_BANK` is the hand-curated source of truth.
`load_all_facts()` merges it with `data/discovered_facts.jsonl` (auto-pulled
by `scripts/discover_facts.py`) so the publish chain has more runway.
"""
from __future__ import annotations

import json
from pathlib import Path

RARE_FACT_BANK = [
    # ---------- SPACE ----------
    {
        "topic": "space",
        "claim": "On Venus, a single day lasts longer than a year. One full rotation takes about 243 Earth days, while one orbit around the Sun takes 225.",
        "sources": ["https://science.nasa.gov/venus/facts/", "https://www.britannica.com/place/Venus-planet"],
        "image_hint": "Venus planet surface NASA",
    },
    {
        "topic": "space",
        "claim": "A spoonful of a neutron star would weigh roughly 4 billion tonnes on Earth, the same as every car on the planet stacked into a teaspoon.",
        "sources": ["https://www.nasa.gov/feature/goddard/2020/neutron-stars-explained", "https://www.britannica.com/science/neutron-star"],
        "image_hint": "neutron star space",
    },
    {
        "topic": "space",
        "claim": "There is a giant cloud of alcohol drifting in deep space about 10,000 light years from Earth, and it contains enough ethanol for 400 trillion trillion pints.",
        "sources": ["https://www.nationalgeographic.com/science/article/space-alcohol-cloud", "https://www.eso.org/public/news/eso0414/"],
        "image_hint": "nebula deep space",
    },
    {
        "topic": "space",
        "claim": "Saturn would float in water if you could find a bathtub big enough. Its average density is lower than that of water itself.",
        "sources": ["https://science.nasa.gov/saturn/facts/", "https://www.britannica.com/place/Saturn-planet"],
        "image_hint": "Saturn planet rings",
    },
    {
        "topic": "space",
        "claim": "Footprints left by the Apollo astronauts will likely stay on the Moon for millions of years, because there is no wind or water to erase them.",
        "sources": ["https://www.nasa.gov/history/apollo-11-50th-anniversary/", "https://www.britannica.com/topic/Apollo-11"],
        "image_hint": "moon footprint surface",
    },
    {
        "topic": "space",
        "claim": "The Sun makes up 99.86% of all the mass in our solar system. Everything else, every planet, moon, and asteroid combined, is the leftover 0.14%.",
        "sources": ["https://science.nasa.gov/sun/facts/", "https://www.britannica.com/place/Sun"],
    },

    # ---------- EARTH / GEOLOGY ----------
    {
        "topic": "earth",
        "claim": "Earth's inner core appears to be rotating at a slightly different rate from the rest of the planet, based on decades of seismic readings.",
        "sources": ["https://www.nature.com/articles/s41586-023-05791-6", "https://www.science.org/content/article/earth-s-inner-core-may-have-paused-and-reversed-its-spin"],
    },
    {
        "topic": "earth",
        "claim": "Mount Everest grows about 4 millimetres taller every year as the Indian and Eurasian plates continue to grind into each other.",
        "sources": ["https://www.nationalgeographic.com/adventure/article/mount-everest-height", "https://www.britannica.com/place/Mount-Everest"],
    },
    {
        "topic": "earth",
        "claim": "Antarctica holds about 70% of the planet's fresh water, locked up in an ice sheet over 4 kilometres thick in places.",
        "sources": ["https://nsidc.org/learn/parts-cryosphere/ice-sheets", "https://www.britannica.com/place/Antarctica"],
    },
    {
        "topic": "earth",
        "claim": "There are parts of Antarctica's McMurdo Dry Valleys where almost no rain or snow has fallen for nearly 2 million years.",
        "sources": ["https://www.britannica.com/place/McMurdo-Dry-Valleys", "https://earthobservatory.nasa.gov/images/86236/the-dry-valleys-of-antarctica"],
    },
    {
        "topic": "earth",
        "claim": "Iceland is one of the few places on Earth where you can stand on the boundary between two continental plates and watch them pull apart.",
        "sources": ["https://www.britannica.com/place/Mid-Atlantic-Ridge", "https://www.nationalgeographic.com/travel/article/iceland-mid-atlantic-ridge"],
    },

    # ---------- OCEAN ----------
    {
        "topic": "ocean",
        "claim": "The pressure at the bottom of the Mariana Trench is over 1,000 times the air pressure at sea level, equivalent to 50 jumbo jets pressing on a single square metre.",
        "sources": ["https://oceanservice.noaa.gov/facts/deepest-part-of-the-ocean.html", "https://www.nationalgeographic.com/science/article/mariana-trench"],
    },
    {
        "topic": "ocean",
        "claim": "More than 80% of the ocean is unmapped, unobserved, and unexplored. We have better maps of Mars than of our own seafloor.",
        "sources": ["https://oceanservice.noaa.gov/facts/exploration.html", "https://www.nationalgeographic.com/environment/article/ocean-exploration"],
    },
    {
        "topic": "ocean",
        "claim": "There are underwater rivers and waterfalls on the seafloor, where colder, saltier water flows beneath warmer water like a hidden second ocean.",
        "sources": ["https://oceanservice.noaa.gov/facts/underwater-river.html", "https://www.bbc.com/future/article/20151126-the-rivers-that-flow-under-the-sea"],
    },
    {
        "topic": "ocean",
        "claim": "The blue whale's heart is the size of a small car, and you could swim through some of its blood vessels.",
        "sources": ["https://www.nhm.ac.uk/discover/blue-whale-the-largest-creature.html", "https://www.britannica.com/animal/blue-whale"],
    },

    # ---------- BIOLOGY / NATURE ----------
    {
        "topic": "biology",
        "claim": "Octopuses have three hearts and blue blood. Two of those hearts stop beating when the octopus swims, which is why they prefer to crawl.",
        "sources": ["https://www.smithsonianmag.com/smart-news/why-octopuses-have-three-hearts-and-blue-blood-180975272/", "https://www.nhm.ac.uk/discover/octopuses-facts-about-eight-armed-molluscs.html"],
        "image_hint": "octopus underwater",
    },
    {
        "topic": "biology",
        "claim": "Tardigrades can survive being boiled, frozen near absolute zero, dehydrated for decades, and even floated in the vacuum of open space.",
        "sources": ["https://www.nationalgeographic.com/animals/article/tardigrades-water-bears", "https://www.nature.com/articles/srep00064"],
        "image_hint": "water bear microscope",
        "quirky_score": 0,  # textbook tier — deprioritised
    },
    {
        "topic": "biology",
        "claim": "A single honey bee produces about 1/12th of a teaspoon of honey in her entire life. A jar of honey is the work of hundreds of bees.",
        "sources": ["https://www.nationalgeographic.com/animals/invertebrates/facts/honey-bee", "https://www.britannica.com/animal/honeybee"],
    },
    {
        "topic": "biology",
        "claim": "Sharks predate trees. They have been swimming the oceans for more than 400 million years, longer than the existence of forests.",
        "sources": ["https://oceana.org/marine-life/sharks-and-rays/", "https://www.britannica.com/animal/shark"],
    },
    {
        "topic": "biology",
        "claim": "Cows have best friends, and produce more milk on days they get to spend time together. Separating them measurably stresses them out.",
        "sources": ["https://www.bbc.com/news/uk-northern-ireland-13716226", "https://www.cambridge.org/core/journals/animal-welfare/article/effects-of-social-isolation-on-the-behaviour-and-physiology-of-cattle"],
        "quirky_score": 0,  # textbook tier — deprioritised
    },

    # ---------- HISTORY ----------
    {
        "topic": "history",
        "claim": "The Great Fire of London in 1666 destroyed most of the medieval city but caused only a handful of officially recorded deaths.",
        "sources": ["https://www.britannica.com/event/Great-Fire-of-London", "https://www.museumoflondon.org.uk/discover/great-fire-london"],
    },
    {
        "topic": "history",
        "claim": "Cleopatra lived closer in time to the Moon landing than to the construction of the Great Pyramid of Giza.",
        "sources": ["https://www.britannica.com/biography/Cleopatra-queen-of-Egypt", "https://www.nationalgeographic.com/history/article/cleopatra"],
    },
    {
        "topic": "history",
        "claim": "Oxford University was already 300 years old when the Aztec Empire was founded in 1325.",
        "sources": ["https://www.ox.ac.uk/about/organisation/history", "https://www.britannica.com/topic/Aztec"],
    },
    {
        "topic": "history",
        "claim": "The shortest war in recorded history lasted just 38 minutes. It happened in 1896 between Britain and Zanzibar.",
        "sources": ["https://www.britannica.com/event/Anglo-Zanzibar-War", "https://www.bbc.co.uk/teach/articles/zg7qbqt"],
    },
    {
        "topic": "history",
        "claim": "Napoleon was once attacked by a horde of bunnies. He had ordered them released for a hunt, and they swarmed him instead of running.",
        "sources": ["https://www.smithsonianmag.com/smart-news/napoleon-was-once-attacked-by-a-horde-of-bunnies-180953050/", "https://www.britannica.com/biography/Napoleon-I"],
    },

    # ---------- TECHNOLOGY ----------
    {
        "topic": "technology",
        "claim": "The first computer bug was a real moth. In 1947 engineers found one stuck in a relay of the Harvard Mark II and taped it into the logbook.",
        "sources": ["https://www.britannica.com/technology/bug-computing", "https://www.computerhistory.org/revolution/computer-programming/16/314"],
        "image_hint": "vintage computer relay hardware",
    },
    {
        "topic": "technology",
        "claim": "The smartphone in your pocket has more processing power than every computer NASA used to send astronauts to the Moon, by several orders of magnitude.",
        "sources": ["https://www.nasa.gov/history/apollo-11-50th-anniversary/", "https://www.bbc.com/future/article/20190701-apollo-in-50-numbers-the-technology"],
        "image_hint": "smartphone processor technology",
    },
    {
        "topic": "technology",
        "claim": "The term 'metaverse' was coined in 1992 in Neal Stephenson's novel Snow Crash, decades before any modern VR platform existed.",
        "sources": ["https://www.britannica.com/topic/metaverse", "https://www.britannica.com/biography/Neal-Stephenson"],
        "image_hint": "virtual reality headset technology",
    },
    {
        "topic": "technology",
        "claim": "The QWERTY keyboard layout was designed in the 1870s partly to slow typists down, so the metal arms of mechanical typewriters would not jam.",
        "sources": ["https://www.smithsonianmag.com/arts-culture/fact-of-fiction-the-legend-of-the-qwerty-keyboard-49863249/", "https://www.britannica.com/technology/QWERTY"],
        "image_hint": "typewriter qwerty keyboard",
    },
    {
        "topic": "technology",
        "claim": "Wi-Fi was invented as a side effect of an Australian astronomer's failed attempt to detect exploding mini black holes in deep space.",
        "sources": ["https://www.csiro.au/en/about/our-impact/our-history/wifi", "https://www.bbc.com/news/world-australia-58812615"],
        "image_hint": "wifi router wireless network",
    },

    # ---------- SECOND BATCH: 2026-04-29 evening expansion ----------

    # ---------- SPACE (extra) ----------
    {
        "topic": "space",
        "claim": "The Andromeda galaxy is moving toward the Milky Way at about 110 kilometres per second. The two are expected to merge in roughly 4.5 billion years.",
        "sources": ["https://science.nasa.gov/asset/hubble/hubble-andromeda/", "https://www.britannica.com/place/Andromeda-Galaxy"],
        "image_hint": "Andromeda galaxy",
    },
    {
        "topic": "space",
        "claim": "There is a planet 40 light years away thought to be largely made of diamond. It orbits its star in just 18 hours.",
        "sources": ["https://www.cam.ac.uk/research/news/diamond-planet-found-by-cambridge-led-research-team", "https://www.nature.com/articles/nature.2012.11748"],
        "image_hint": "exoplanet space diamond",
    },
    {
        "topic": "space",
        "claim": "If you could drive a car upward at 100 km/h, it would take you over 170 years to reach the Moon.",
        "sources": ["https://science.nasa.gov/moon/facts/", "https://www.britannica.com/place/Moon"],
        "image_hint": "Moon Earth distance",
    },
    {
        "topic": "space",
        "claim": "The footprint of the Sun's heliosphere stretches more than three times the orbit of Pluto. Voyager 1 only crossed its edge in 2012.",
        "sources": ["https://science.nasa.gov/heliophysics/focus-areas/heliosphere/", "https://voyager.jpl.nasa.gov/"],
        "image_hint": "Voyager spacecraft Jupiter Saturn deep space illustration",
    },
    {
        "topic": "space",
        "claim": "Olympus Mons on Mars is the tallest known volcano in the solar system. It is roughly 22 kilometres high, nearly three times the height of Everest.",
        "sources": ["https://science.nasa.gov/resource/olympus-mons/", "https://www.britannica.com/place/Olympus-Mons"],
        "image_hint": "Mars volcano red planet surface",
    },

    # ---------- EARTH (extra) ----------
    {
        "topic": "earth",
        "claim": "The Sahara Desert was once green. Cave paintings show it was full of rivers, lakes, and grazing animals only 6,000 years ago.",
        "sources": ["https://www.nationalgeographic.com/environment/article/green-sahara", "https://www.bbc.com/future/article/20180202-the-mysterious-rock-art-of-the-sahara"],
        "image_hint": "Sahara desert dunes",
    },
    {
        "topic": "earth",
        "claim": "Lightning strikes the Earth about 100 times every second. That works out to roughly 8 million strikes a day.",
        "sources": ["https://www.noaa.gov/jetstream/lightning", "https://www.britannica.com/science/lightning-meteorology"],
        "image_hint": "lightning storm sky",
    },
    {
        "topic": "earth",
        "claim": "The deepest hole ever drilled by humans, the Kola Superdeep Borehole, reached just over 12 kilometres before the rock became too hot to continue.",
        "sources": ["https://www.bbc.com/future/article/20190503-the-deepest-hole-we-have-ever-dug", "https://www.atlasobscura.com/places/kola-superdeep-borehole"],
        "image_hint": "deep borehole drilling",
    },
    {
        "topic": "earth",
        "claim": "There is a single fungus in Oregon that covers nearly 9 square kilometres of forest. It is thought to be the largest living organism on Earth.",
        "sources": ["https://www.scientificamerican.com/article/strange-but-true-largest-organism-is-fungus/", "https://www.fs.usda.gov/detail/malheur/home"],
        "image_hint": "Oregon forest fungus mushroom",
    },
    {
        "topic": "earth",
        "claim": "The temperature of Earth's inner core is about 5,200 °C, roughly the same as the surface of the Sun.",
        "sources": ["https://www.britannica.com/science/core-Earth-structure", "https://www.nature.com/articles/nature11031"],
        "image_hint": "Earth core cross section",
    },

    # ---------- OCEAN (extra) ----------
    {
        "topic": "ocean",
        "claim": "Most of the oxygen we breathe comes from the ocean, not from forests. Marine plants and microbes produce more than half of it.",
        "sources": ["https://oceanservice.noaa.gov/facts/ocean-oxygen.html", "https://www.nationalgeographic.com/environment/article/ocean-oxygen"],
        "image_hint": "ocean phytoplankton surface",
    },
    {
        "topic": "ocean",
        "claim": "There are more pieces of plastic in the ocean than stars in the Milky Way. Estimates put it at over 5 trillion pieces.",
        "sources": ["https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0111913", "https://www.nationalgeographic.com/environment/article/plastic-pollution"],
        "image_hint": "ocean plastic pollution",
    },
    {
        "topic": "ocean",
        "claim": "The longest mountain range on Earth is underwater. The Mid-Ocean Ridge stretches more than 65,000 kilometres around the planet.",
        "sources": ["https://oceanservice.noaa.gov/facts/midoceanridge.html", "https://www.britannica.com/place/Mid-Atlantic-Ridge"],
        "image_hint": "underwater mountain ridge ocean",
    },
    {
        "topic": "ocean",
        "claim": "The sound of a blue whale's call can travel up to 1,600 kilometres through the ocean.",
        "sources": ["https://www.noaa.gov/education/resource-collections/marine-life/whales", "https://www.nhm.ac.uk/discover/blue-whale-the-largest-creature.html"],
        "image_hint": "blue whale ocean diving",
    },

    # ---------- BIOLOGY / NATURE (extra) ----------
    {
        "topic": "biology",
        "claim": "Sloths are so slow that algae grows in their fur, giving them a faint green tint that helps them blend into the canopy.",
        "sources": ["https://www.smithsonianmag.com/smart-news/why-sloths-have-algae-fur-180977789/", "https://www.nationalgeographic.com/animals/mammals/facts/sloths"],
        "image_hint": "sloth tree rainforest",
        "quirky_score": 0,  # textbook tier — deprioritised
    },
    {
        "topic": "biology",
        "claim": "A single strand of spider silk is, by weight, stronger than steel and tougher than Kevlar. Several spiders make webs strong enough to catch small birds.",
        "sources": ["https://www.smithsonianmag.com/smart-news/spider-silk-strong-steel-and-also-stretchy-180956291/", "https://www.nhm.ac.uk/discover/spider-silk-the-toughest-natural-material.html"],
        "image_hint": "spider web macro",
        "quirky_score": 0,  # textbook tier — deprioritised
    },
    {
        "topic": "biology",
        "claim": "Crows can recognise individual human faces and hold a grudge for years. Researchers have shown they pass that grudge on to their offspring.",
        "sources": ["https://www.nationalgeographic.com/animals/article/crows-recognise-human-faces", "https://www.washington.edu/news/2011/06/28/crows-react-to-threats-in-human-like-way/"],
        "image_hint": "crow black bird portrait",
    },
    {
        "topic": "biology",
        "claim": "Sea otters hold hands while sleeping so they don't drift apart on the ocean current. Pups are sometimes wrapped in kelp for the same reason.",
        "sources": ["https://www.nationalgeographic.com/animals/mammals/facts/sea-otter", "https://www.fisheries.noaa.gov/species/sea-otter"],
        "image_hint": "sea otter floating ocean",
    },
    {
        "topic": "biology",
        "claim": "Ants do not sleep in long stretches. Worker ants take roughly 250 short naps a day, totalling under five hours.",
        "sources": ["https://www.smithsonianmag.com/smart-news/ants-take-many-tiny-naps-day-180973421/", "https://www.britannica.com/animal/ant"],
        "image_hint": "ant macro insect",
    },

    # ---------- HISTORY (extra) ----------
    {
        "topic": "history",
        "claim": "The Eiffel Tower was meant to be a temporary structure. Built for the 1889 World's Fair, it was due to be dismantled after 20 years.",
        "sources": ["https://www.toureiffel.paris/en/the-monument/history", "https://www.britannica.com/topic/Eiffel-Tower-Paris-France"],
        "image_hint": "Eiffel Tower Paris",
    },
    {
        "topic": "history",
        "claim": "Rome's Colosseum could be flooded for mock naval battles. Engineers diverted aqueduct water into the arena and filled it with warships.",
        "sources": ["https://www.britannica.com/topic/Colosseum", "https://www.smithsonianmag.com/history/secrets-of-the-colosseum-75827047/"],
        "image_hint": "Roman Colosseum",
    },
    {
        "topic": "history",
        "claim": "When the Great Fire of London ended in 1666, the official death toll listed only six people. Modern historians believe the real number was far higher.",
        "sources": ["https://www.britannica.com/event/Great-Fire-of-London", "https://www.museumoflondon.org.uk/discover/great-fire-london"],
        "image_hint": "old London engraving",
    },
    {
        "topic": "history",
        "claim": "The first known use of the word 'computer' referred to a job, not a machine. It described people, often women, who calculated equations by hand.",
        "sources": ["https://www.computerhistory.org/timeline/computers/", "https://www.britannica.com/technology/computer"],
        "image_hint": "vintage office paperwork",
    },

    # ---------- TECHNOLOGY (extra) ----------
    {
        "topic": "technology",
        "claim": "The Apollo Guidance Computer that landed humans on the Moon ran on roughly 64 kilobytes of memory. A single emoji takes more than that today.",
        "sources": ["https://www.nasa.gov/history/apollo-11-50th-anniversary/", "https://www.computerhistory.org/timeline/computers/"],
        "image_hint": "Apollo guidance computer console",
    },
    {
        "topic": "technology",
        "claim": "The first webcam was set up at Cambridge University in 1991. Its only job was to show whether the lab's coffee pot was full.",
        "sources": ["https://www.cl.cam.ac.uk/coffee/qsf/coffee.html", "https://www.bbc.com/news/technology-19142597"],
        "image_hint": "coffee pot office vintage",
    },
    {
        "topic": "technology",
        "claim": "An average modern car contains over 100 million lines of code. That is more than a passenger jet's flight system.",
        "sources": ["https://spectrum.ieee.org/this-car-runs-on-code", "https://www.bbc.com/future/article/20141217-when-cars-bug-out"],
        "image_hint": "car dashboard electronics",
    },
    {
        "topic": "technology",
        "claim": "The very first website is still online. It was launched by Tim Berners-Lee in 1991 and explained what the World Wide Web was.",
        "sources": ["https://info.cern.ch/", "https://www.w3.org/History.html"],
        "image_hint": "old computer screen text",
    },

    # ---------- THIRD BATCH: 2026-04-30 evening expansion (~50 facts) ----------

    # ---------- SPACE (extra) ----------
    {
        "topic": "space",
        "claim": "Jupiter has been protecting Earth for billions of years. Its enormous gravity pulls in or deflects most comets and asteroids that would otherwise threaten the inner solar system.",
        "sources": ["https://science.nasa.gov/jupiter/facts/", "https://www.britannica.com/place/Jupiter-planet"],
        "image_hint": "Jupiter planet storm",
    },
    {
        "topic": "space",
        "claim": "If you could fold a piece of paper 42 times, it would reach the Moon. Each fold doubles the thickness.",
        "sources": ["https://www.scientificamerican.com/article/folding-paper-half-12-times/", "https://www.guinnessworldrecords.com/world-records/most-times-to-fold-a-piece-of-paper"],
        "image_hint": "Moon surface lunar",
    },
    {
        "topic": "space",
        "claim": "There are more stars in the observable universe than grains of sand on every beach on Earth combined.",
        "sources": ["https://science.nasa.gov/universe/", "https://www.scientificamerican.com/article/are-there-more-stars-than-grains-of-sand/"],
        "image_hint": "starfield galaxy night sky",
    },
    {
        "topic": "space",
        "claim": "The International Space Station travels at about 28,000 kilometres per hour. Astronauts on board see roughly 16 sunrises and sunsets every day.",
        "sources": ["https://www.nasa.gov/international-space-station/", "https://www.esa.int/Science_Exploration/Human_and_Robotic_Exploration/International_Space_Station"],
        "image_hint": "International Space Station orbit",
    },
    {
        "topic": "space",
        "claim": "The Sun loses about 4 million tonnes of mass every second by converting hydrogen into helium and radiating energy.",
        "sources": ["https://science.nasa.gov/sun/facts/", "https://www.britannica.com/place/Sun"],
        "image_hint": "Sun solar surface",
    },
    {
        "topic": "space",
        "claim": "Astronauts on the Apollo 11 mission left a small disc on the Moon containing messages from leaders of 73 countries.",
        "sources": ["https://www.nasa.gov/history/apollo-11-50th-anniversary/", "https://www.smithsonianmag.com/smart-news/apollo-11-goodwill-messages-180972519/"],
        "image_hint": "Moon surface lunar Apollo",
    },
    {
        "topic": "space",
        "claim": "A year on Mercury lasts only 88 Earth days, but a single day on Mercury (sunrise to sunrise) stretches across about 176 Earth days.",
        "sources": ["https://science.nasa.gov/mercury/facts/", "https://www.britannica.com/place/Mercury-planet"],
        "image_hint": "Mercury planet surface",
    },
    {
        "topic": "space",
        "claim": "There is no sound in space. Sound waves need a medium like air or water to travel, and space is mostly empty.",
        "sources": ["https://spaceplace.nasa.gov/sound-in-space/en/", "https://www.britannica.com/science/sound-physics"],
        "image_hint": "deep space stars",
    },

    # ---------- EARTH (extra) ----------
    {
        "topic": "earth",
        "claim": "Earth is not perfectly round. It bulges slightly at the equator, making it about 43 kilometres wider across the middle than from pole to pole.",
        "sources": ["https://www.nationalgeographic.com/science/article/earth-shape", "https://earthobservatory.nasa.gov/features/EarthShape"],
        "image_hint": "Earth from space",
    },
    {
        "topic": "earth",
        "claim": "The Atacama Desert in Chile contains weather stations that have never recorded a single drop of rain.",
        "sources": ["https://www.nationalgeographic.com/environment/article/atacama-desert", "https://earthobservatory.nasa.gov/images/87800/the-driest-place-on-earth"],
        "image_hint": "Atacama desert landscape",
    },
    {
        "topic": "earth",
        "claim": "Lake Vostok in Antarctica has been sealed beneath nearly 4 kilometres of ice for at least 15 million years.",
        "sources": ["https://www.britannica.com/place/Lake-Vostok", "https://earthobservatory.nasa.gov/images/77816/lake-vostok-antarctica"],
        "image_hint": "Antarctica ice sheet",
    },
    {
        "topic": "earth",
        "claim": "The Pacific Ocean is wider than the Moon. Its diameter is about 19,800 kilometres against the Moon's 3,474.",
        "sources": ["https://oceanservice.noaa.gov/facts/oceansize.html", "https://science.nasa.gov/moon/facts/"],
        "image_hint": "Pacific Ocean from space",
    },
    {
        "topic": "earth",
        "claim": "The Amazon rainforest produces about 6% of the world's oxygen. The bigger contributor is the ocean.",
        "sources": ["https://www.nationalgeographic.com/environment/article/amazon-rainforest", "https://oceanservice.noaa.gov/facts/ocean-oxygen.html"],
        "image_hint": "Amazon rainforest canopy",
    },
    {
        "topic": "earth",
        "claim": "There is a single tree in California that has been alive for over 4,800 years. Older than the pyramids of Giza.",
        "sources": ["https://www.nps.gov/grsm/learn/nature/bristlecone-pine.htm", "https://www.fs.usda.gov/detail/inyo/learning/?cid=stelprdb5129900"],
        "image_hint": "ancient bristlecone pine tree",
    },
    {
        "topic": "earth",
        "claim": "Iceland gains roughly 2 centimetres of new land every year as the North American and Eurasian plates pull apart beneath it.",
        "sources": ["https://www.britannica.com/place/Mid-Atlantic-Ridge", "https://www.nationalgeographic.com/travel/article/iceland-mid-atlantic-ridge"],
        "image_hint": "Iceland volcanic landscape",
    },
    {
        "topic": "earth",
        "claim": "Greenland is melting fast enough to add about 280 billion tonnes of water to the oceans every year.",
        "sources": ["https://nsidc.org/learn/parts-cryosphere/ice-sheets/greenland-ice-sheet", "https://climate.nasa.gov/news/2966/greenlands-2019-ice-loss/"],
        "image_hint": "Greenland glacier ice",
    },

    # ---------- OCEAN (extra) ----------
    {
        "topic": "ocean",
        "claim": "The Great Barrier Reef is so large it can be seen from space. It stretches over 2,300 kilometres along Australia's coast.",
        "sources": ["https://www.gbrmpa.gov.au/", "https://www.nationalgeographic.com/environment/article/great-barrier-reef"],
        "image_hint": "Great Barrier Reef coral underwater",
    },
    {
        "topic": "ocean",
        "claim": "About 95% of the ocean and 99% of the seafloor remain unexplored by humans.",
        "sources": ["https://oceanservice.noaa.gov/facts/exploration.html", "https://www.noaa.gov/education/resource-collections/ocean-coasts/ocean-floor-features"],
        "image_hint": "deep ocean abyss",
    },
    {
        "topic": "ocean",
        "claim": "Some species of jellyfish can effectively reverse their lifecycle and revert to a younger form. They are functionally biologically immortal.",
        "sources": ["https://www.nationalgeographic.com/animals/invertebrates/facts/immortal-jellyfish", "https://www.amnh.org/exhibitions/creatures-of-light/biofluorescent-bay/jellyfish"],
        "image_hint": "jellyfish underwater",
    },
    {
        "topic": "ocean",
        "claim": "Sea cucumbers can liquefy their own bodies to squeeze through narrow gaps and then re-solidify on the other side.",
        "sources": ["https://www.nhm.ac.uk/discover/sea-cucumbers-facts.html", "https://oceana.org/marine-life/sea-cucumbers/"],
        "image_hint": "sea cucumber underwater",
    },
    {
        "topic": "ocean",
        "claim": "The largest known living structure on Earth is a clonal colony of seagrass in Shark Bay, Australia, covering about 200 square kilometres.",
        "sources": ["https://royalsocietypublishing.org/doi/10.1098/rspb.2022.0538", "https://www.bbc.com/news/world-australia-61733930"],
        "image_hint": "seagrass underwater meadow",
    },
    {
        "topic": "ocean",
        "claim": "Octopuses can taste with their suckers. Each one carries thousands of chemical-sensing receptors.",
        "sources": ["https://www.smithsonianmag.com/smart-news/octopuses-taste-with-their-suckers-180976049/", "https://www.nature.com/articles/d41586-020-03073-y"],
        "image_hint": "octopus underwater tentacles",
    },
    {
        "topic": "ocean",
        "claim": "Sperm whales sleep vertically near the surface, drifting motionless in groups for short stretches of about 10 to 15 minutes.",
        "sources": ["https://www.britannica.com/animal/sperm-whale", "https://www.nationalgeographic.com/animals/mammals/facts/sperm-whale"],
        "image_hint": "sperm whale ocean diving",
    },
    {
        "topic": "ocean",
        "claim": "Around 50% of marine species could disappear by 2100 if ocean warming continues at current rates.",
        "sources": ["https://www.ipcc.ch/srocc/", "https://www.nationalgeographic.com/environment/article/ocean-warming"],
        "image_hint": "coral reef bleaching ocean",
    },

    # ---------- BIOLOGY (extra) ----------
    {
        "topic": "biology",
        "claim": "A blue whale's tongue alone can weigh as much as an elephant, and its heart is the size of a small car.",
        "sources": ["https://www.nhm.ac.uk/discover/blue-whale-the-largest-creature.html", "https://www.britannica.com/animal/blue-whale"],
        "image_hint": "blue whale ocean diving",
    },
    {
        "topic": "biology",
        "claim": "Polar bears have black skin under their white fur. The fur itself is actually transparent and reflects light.",
        "sources": ["https://www.nationalgeographic.com/animals/mammals/facts/polar-bear", "https://www.nhm.ac.uk/discover/polar-bear-facts.html"],
        "image_hint": "polar bear arctic snow",
        "quirky_score": 0,  # textbook tier — deprioritised
    },
    {
        "topic": "biology",
        "claim": "Cats cannot taste sweetness. Their taste receptors lack the gene needed to register sugar.",
        "sources": ["https://www.smithsonianmag.com/science-nature/why-cant-cats-taste-sweet-180956055/", "https://www.nationalgeographic.com/animals/mammals/facts/domestic-cat"],
        "image_hint": "cat portrait close up",
    },
    {
        "topic": "biology",
        "claim": "Elephants can recognise themselves in mirrors. Only a handful of species have demonstrated this kind of self-awareness.",
        "sources": ["https://www.smithsonianmag.com/smart-news/elephants-recognise-themselves-in-mirrors-180970499/", "https://www.nationalgeographic.com/animals/mammals/facts/african-elephant"],
        "image_hint": "African elephant savanna",
    },
    {
        "topic": "biology",
        "claim": "Wombats produce cube-shaped poo. Their intestines have varying elasticity that moulds the waste into neat blocks.",
        "sources": ["https://www.smithsonianmag.com/smart-news/scientists-finally-solve-mystery-wombats-cube-shaped-poop-180973957/", "https://www.bbc.com/news/world-australia-46559356"],
        "image_hint": "wombat australia wildlife",
        "quirky_score": 0,  # textbook tier — deprioritised
    },
    {
        "topic": "biology",
        "claim": "Bananas are slightly radioactive. They contain potassium-40, an isotope that emits a tiny dose of radiation.",
        "sources": ["https://www.epa.gov/radiation/radioactive-decay-and-half-life", "https://www.britannica.com/science/potassium-40"],
        "image_hint": "bananas yellow fruit",
        "quirky_score": 0,  # textbook tier — deprioritised
    },
    {
        "topic": "biology",
        "claim": "Hummingbirds are the only birds that can fly backwards. Their wings rotate in a near-figure-eight pattern.",
        "sources": ["https://www.nationalgeographic.com/animals/birds/facts/hummingbird", "https://www.audubon.org/news/how-do-hummingbirds-fly"],
        "image_hint": "hummingbird flying flower",
        "quirky_score": 0,  # textbook tier — deprioritised
    },
    {
        "topic": "biology",
        "claim": "Cows have nearly 360-degree vision. Their eyes are positioned to spot predators while grazing.",
        "sources": ["https://www.britannica.com/animal/cattle-livestock", "https://www.nhm.ac.uk/discover/cows-facts.html"],
        "image_hint": "cow grazing field",
        "quirky_score": 0,  # textbook tier — deprioritised
    },
    {
        "topic": "biology",
        "claim": "A group of flamingos is called a flamboyance. Their pink colour comes from the carotenoid pigments in the brine shrimp and algae they eat.",
        "sources": ["https://www.nationalgeographic.com/animals/birds/facts/flamingo", "https://www.britannica.com/animal/flamingo"],
        "image_hint": "flamingo pink wading",
        "quirky_score": 0,  # textbook tier — deprioritised
    },
    {
        "topic": "biology",
        "claim": "Goats have rectangular pupils. The wide horizontal slit gives them nearly panoramic vision to spot predators in tall grass.",
        "sources": ["https://www.nationalgeographic.com/animals/mammals/facts/domestic-goat", "https://www.smithsonianmag.com/smart-news/why-goats-have-rectangular-pupils-180956211/"],
        "image_hint": "goat farm portrait",
        "quirky_score": 0,  # textbook tier — deprioritised
    },

    # ---------- HISTORY (extra) ----------
    {
        "topic": "history",
        "claim": "Vikings reached North America roughly 500 years before Christopher Columbus. Leif Erikson landed on what is now Newfoundland around the year 1000.",
        "sources": ["https://www.britannica.com/biography/Leif-Erikson", "https://www.nationalgeographic.com/history/article/viking-voyage-north-america"],
        "image_hint": "Viking longship coast",
    },
    {
        "topic": "history",
        "claim": "Mount Vesuvius erupted in 79 AD and buried the Roman city of Pompeii under metres of ash. The site lay undiscovered for nearly 1,500 years.",
        "sources": ["https://www.britannica.com/place/Pompeii", "https://www.nationalgeographic.com/history/article/pompeii"],
        "image_hint": "Pompeii ruins Italy",
    },
    {
        "topic": "history",
        "claim": "The Ottoman Empire lasted for over 600 years. It rose in 1299 and dissolved only in 1922.",
        "sources": ["https://www.britannica.com/place/Ottoman-Empire", "https://www.bbc.co.uk/history/historic_figures/sultans.shtml"],
        "image_hint": "Ottoman architecture Istanbul",
    },
    {
        "topic": "history",
        "claim": "Tutankhamun was a relatively minor pharaoh in life. His fame came from the discovery of his nearly intact tomb in 1922.",
        "sources": ["https://www.britannica.com/biography/Tutankhamen", "https://www.nationalgeographic.com/history/article/king-tut-tomb"],
        "image_hint": "Egyptian pharaoh artifact",
    },
    {
        "topic": "history",
        "claim": "The first known recipe for beer comes from a 4,000-year-old Sumerian poem dedicated to Ninkasi, the goddess of brewing.",
        "sources": ["https://www.britannica.com/topic/beer", "https://www.smithsonianmag.com/smart-news/3900-year-old-recipe-beer-180953660/"],
        "image_hint": "ancient sumerian tablet",
    },
    {
        "topic": "history",
        "claim": "The Hundred Years' War lasted 116 years. Fighting between England and France ran from 1337 to 1453.",
        "sources": ["https://www.britannica.com/event/Hundred-Years-War", "https://www.bbc.co.uk/history/british/middle_ages/hundred_years_war_01.shtml"],
        "image_hint": "medieval battle armour",
    },
    {
        "topic": "history",
        "claim": "Genghis Khan's Mongol Empire became the largest contiguous empire in history, stretching from the Pacific Ocean to the gates of Vienna.",
        "sources": ["https://www.britannica.com/biography/Genghis-Khan", "https://www.nationalgeographic.com/history/article/genghis-khan"],
        "image_hint": "Mongolian steppe horseman",
    },
    {
        "topic": "history",
        "claim": "Marie Curie remains the only person ever to win Nobel Prizes in two different sciences: physics in 1903 and chemistry in 1911.",
        "sources": ["https://www.britannica.com/biography/Marie-Curie", "https://www.nobelprize.org/prizes/chemistry/1911/marie-curie/facts/"],
        "image_hint": "Marie Curie laboratory portrait",
    },
    {
        "topic": "history",
        "claim": "The Library of Alexandria once held an estimated 400,000 to 700,000 scrolls. Its loss is considered one of the greatest cultural disasters in history.",
        "sources": ["https://www.britannica.com/topic/Library-of-Alexandria", "https://www.nationalgeographic.com/history/article/library-of-alexandria"],
        "image_hint": "ancient library scrolls",
    },
    {
        "topic": "history",
        "claim": "Stonehenge was built in stages over more than 1,500 years. Construction began around 3000 BC.",
        "sources": ["https://www.britannica.com/topic/Stonehenge", "https://www.english-heritage.org.uk/visit/places/stonehenge/history-and-stories/"],
        "image_hint": "Stonehenge stones landscape",
    },

    # ---------- TECHNOLOGY (extra) ----------
    {
        "topic": "technology",
        "claim": "The first computer programmer was Ada Lovelace. In 1843 she wrote the first algorithm intended to be executed by a machine.",
        "sources": ["https://www.britannica.com/biography/Ada-Lovelace", "https://www.computerhistory.org/babbage/adalovelace/"],
        "image_hint": "Ada Lovelace portrait engraving",
    },
    {
        "topic": "technology",
        "claim": "About 90% of all the world's data was generated in the last two years. Total data created globally is estimated at over 180 zettabytes by 2025.",
        "sources": ["https://www.statista.com/statistics/871513/worldwide-data-created/", "https://www.weforum.org/agenda/2019/04/how-much-data-is-generated-each-day-cf4bddf29f/"],
        "image_hint": "data centre servers",
    },
    {
        "topic": "technology",
        "claim": "The first email was sent in 1971 by Ray Tomlinson. He chose the @ symbol to separate the user from the host machine.",
        "sources": ["https://www.computerhistory.org/timeline/networking-the-web/", "https://www.bbc.com/news/technology-35846421"],
        "image_hint": "vintage computer keyboard",
    },
    {
        "topic": "technology",
        "claim": "Bitcoin's anonymous creator Satoshi Nakamoto published the original white paper in 2008. Their identity has never been confirmed.",
        "sources": ["https://bitcoin.org/bitcoin.pdf", "https://www.britannica.com/topic/Bitcoin"],
        "image_hint": "computer code screen",
    },
    {
        "topic": "technology",
        "claim": "Google was originally called BackRub. Its founders renamed it in 1997 after the mathematical term googol, a 1 followed by 100 zeros.",
        "sources": ["https://about.google/our-story/", "https://www.britannica.com/topic/Google-Inc"],
        "image_hint": "search engine browser",
    },
    {
        "topic": "technology",
        "claim": "The original Macintosh, released in 1984, came with 128 kilobytes of RAM. A single emoji today exceeds that on its own.",
        "sources": ["https://www.computerhistory.org/timeline/computers/", "https://www.britannica.com/technology/Apple-Macintosh"],
        "image_hint": "vintage Macintosh computer",
    },

    # ============================================================
    # SHOCK BATCH — 2026-04-30 (Ripley's tier, Tier 1+2 sources)
    # All entries here pass the screenshot test: specific, sub-known,
    # sourced, visceral, IG-safe. quirky_score 3 = "wait what".
    # ============================================================

    # ---------- HISTORY (shock) ----------
    {
        "topic": "history",
        "claim": "In 1848 a railroad foreman named Phineas Gage had a 3-foot iron rod blown clean through his skull. He survived for 12 more years. His personality changed forever, and the case founded modern neuroscience.",
        "sources": ["https://www.smithsonianmag.com/history/phineas-gage-neurosciences-most-famous-patient-11390067/", "https://www.britannica.com/biography/Phineas-Gage"],
        "image_hint": "vintage skull anatomy diagram",
        "quirky_score": 3,
        "intensity": "medium",
        "tone": "shocking",
    },
    {
        "topic": "history",
        "claim": "In 1945 a Colorado farmer cut off a chicken's head, but the bird kept living. Mike the Headless Chicken survived 18 months, fed milk through a dropper, and toured America earning his owner a fortune.",
        "sources": ["https://www.smithsonianmag.com/smart-news/the-chicken-that-lived-for-18-months-without-a-head-115582153/", "https://www.bbc.com/news/magazine-33946948"],
        "image_hint": "vintage chicken farm 1940s",
        "quirky_score": 3,
        "intensity": "light",
        "tone": "shocking",
        # Brain stem remained intact, which the comments will pile on.
        # Animal-welfare folks see "farmer cut off head" and unfollow.
        # Excluded from default publish; opt-in only via --allow-controversial.
        "sensitivity": "controversial",
        "sensitivity_flags": ["animal_welfare", "factual_dispute"],
    },
    {
        "topic": "history",
        "claim": "In 1962 a Soviet submarine officer named Vasili Arkhipov refused to authorise a nuclear torpedo launch during the Cuban Missile Crisis. He was outvoted 2 to 1, and his veto is the only reason World War 3 did not begin that day.",
        "sources": ["https://www.bbc.com/news/world-europe-39707294", "https://nsarchive2.gwu.edu/nukevault/ebb399/"],
        "image_hint": "Soviet submarine cold war",
        "quirky_score": 3,
        "intensity": "heavy",
        "tone": "sober",
    },
    {
        "topic": "history",
        "claim": "Sarah Winchester, heir to the Winchester rifle fortune, believed she was haunted by the dead. She built a 161-room mansion with stairs to nowhere and doors opening onto walls, with construction running 24 hours a day for 38 years.",
        "sources": ["https://www.smithsonianmag.com/history/sarah-winchester-mystery-mansion-ghosts-180970163/", "https://www.bbc.com/culture/article/20180202-the-real-story-of-the-winchester-mystery-house"],
        "image_hint": "Victorian mansion architecture haunted",
        "quirky_score": 3,
        "intensity": "light",
        "tone": "shocking",
    },
    {
        "topic": "history",
        "claim": "The 18th-century French soldier Tarrare could eat 30 pounds of food in a day. He was documented eating a live eel whole, a doctor's wedding ring, and once attempted to eat a live cat at the hospital.",
        "sources": ["https://www.smithsonianmag.com/smart-news/strange-tale-tarrare-most-disgusting-french-frenchman-180962844/", "https://www.bbc.com/future/article/20191028-the-bottomless-pit-the-man-who-was-always-hungry"],
        "image_hint": "18th century French soldier portrait",
        "quirky_score": 3,
        "intensity": "medium",
        "tone": "shocking",
        # The "live cat" line will trigger animal-welfare backlash.
        # Story is great minus that detail; rewrite if we want to publish.
        "sensitivity": "controversial",
        "sensitivity_flags": ["animal_welfare"],
    },
    {
        "topic": "history",
        "claim": "In 2003 a hiker pinned by a boulder in a Utah canyon used a dull multitool to amputate his own arm. Aron Ralston then rappelled down a cliff and walked 8 miles before being airlifted to safety.",
        "sources": ["https://www.bbc.com/news/world-us-canada-12723799", "https://www.nationalgeographic.com/adventure/article/127-hours-aron-ralston"],
        "image_hint": "Utah canyon red rock",
        "quirky_score": 3,
        "intensity": "heavy",
        "tone": "shocking",
    },
    {
        "topic": "history",
        "claim": "Early 20th-century factory girls painted glow-in-the-dark watch dials with radium paint. Told to lick their brushes for a sharp tip, many died slowly of radiation poisoning. Their lawsuit established workers' rights to know what materials they handle.",
        "sources": ["https://www.smithsonianmag.com/science-nature/luminous-toxic-180962343/", "https://www.bbc.com/news/world-us-canada-43822124"],
        "image_hint": "vintage watch factory women workers",
        "quirky_score": 3,
        "intensity": "heavy",
        "tone": "sober",
        "reel_title": "The Girls Who Glowed",
        "reel_script": (
            "In the 1920s, young women were paid to paint watch dials with radium. "
            "It glowed in the dark. "
            "Their managers told them to shape the brush tip... with their lips. "
            "Every single day. "
            "Many of them died slowly. "
            "Their bones. Their jaws. Eaten away from the inside. "
            "When they sued, the company called them unhealthy women. "
            "They fought anyway... "
            "They won. "
            "And their case rewrote safety law forever."
        ),
    },
    {
        "topic": "history",
        "claim": "Until 1986, women in Switzerland needed their husband's written permission to take a paid job. Married women were legally subordinate to their husbands until a sweeping reform that year.",
        "sources": ["https://www.bbc.com/news/world-europe-30605898", "https://www.britannica.com/topic/womens-suffrage-in-Switzerland"],
        "image_hint": "Swiss alps village 1980s",
        "quirky_score": 3,
        "intensity": "heavy",
        "tone": "sober",
    },

    # ---------- SPACE (shock) ----------
    {
        "topic": "space",
        "claim": "In 1945 and 1946 the same plutonium sphere killed two Manhattan Project scientists in separate criticality accidents. They named it the Demon Core.",
        "sources": ["https://www.bbc.com/future/article/20210121-the-radioactive-core-that-killed-its-scientists", "https://ahf.nuclearmuseum.org/ahf/history/demon-core/"],
        "image_hint": "atomic research laboratory 1940s",
        "quirky_score": 3,
        "intensity": "medium",
        "tone": "shocking",
    },
    {
        "topic": "space",
        "claim": "In 1908 something exploded above remote Siberia with the force of about 1,000 Hiroshima bombs. It flattened 2,150 square kilometres of forest. There was no crater. Astronomers still debate whether it was a comet or asteroid.",
        "sources": ["https://www.nasa.gov/feature/goddard/2018/30-years-since-tunguska", "https://www.britannica.com/event/Tunguska-event"],
        "image_hint": "Siberia forest devastation aerial",
        "quirky_score": 3,
        "intensity": "medium",
        "tone": "shocking",
    },
    {
        "topic": "space",
        "claim": "In 1859 a solar storm hit Earth so violently that telegraph wires sparked, papers caught fire, and auroras were visible in the Caribbean. If the Carrington Event happened today, the electrical grid would be out for years.",
        "sources": ["https://www.nasa.gov/topics/earth/features/sun_darkness.html", "https://www.bbc.com/future/article/20210107-the-1859-solar-storm-that-electrified-earth"],
        "image_hint": "aurora borealis night sky",
        "quirky_score": 3,
        "intensity": "medium",
        "tone": "shocking",
    },
    {
        "topic": "space",
        "claim": "Pluto is smaller than Russia. Its surface area covers 17.7 million km², while Russia alone covers 17.1 million km². Pluto is also smaller than the Moon.",
        "sources": ["https://science.nasa.gov/dwarf-planets/pluto/facts/", "https://www.britannica.com/place/Pluto-dwarf-planet"],
        "image_hint": "Pluto dwarf planet New Horizons",
        "quirky_score": 3,
        "intensity": "light",
        "tone": "shocking",
    },

    # ---------- BIOLOGY (shock) ----------
    {
        "topic": "biology",
        "claim": "Octopuses have nine brains. One central brain plus a smaller brain in each of the eight arms. The arms can react and decide independently of the central brain.",
        "sources": ["https://www.smithsonianmag.com/science-nature/octopuses-have-nine-brains-180977551/", "https://www.nhm.ac.uk/discover/octopus-facts.html"],
        "image_hint": "octopus underwater intelligent",
        "quirky_score": 3,
        "intensity": "light",
        "tone": "shocking",
    },
    {
        "topic": "biology",
        "claim": "The mantis shrimp punches with the speed of a bullet, accelerating its claw at 10,000 g. The strike creates cavitation bubbles that briefly reach the temperature of the Sun's surface.",
        "sources": ["https://www.bbc.com/earth/story/20150403-meet-the-mantis-shrimp", "https://www.smithsonianmag.com/science-nature/strange-and-twisted-life-mantis-shrimp-180970309/"],
        "image_hint": "mantis shrimp colourful underwater",
        "quirky_score": 3,
        "intensity": "light",
        "tone": "shocking",
    },
    {
        "topic": "biology",
        "claim": "Naked mole-rats can survive without oxygen for 18 minutes by switching their metabolism to plant-style fructose burning. They almost never get cancer and can live 30 years.",
        "sources": ["https://www.smithsonianmag.com/science-nature/the-naked-mole-rat-might-just-be-the-strangest-mammal-ever-180974089/", "https://www.science.org/doi/10.1126/science.aab3896"],
        "image_hint": "naked mole rat underground",
        "quirky_score": 3,
        "intensity": "light",
        "tone": "shocking",
    },
    {
        "topic": "biology",
        "claim": "There is a fungus called Cordyceps that hijacks insect brains. It compels infected ants to climb a plant, bite down, and stay still while the fungus erupts from the host's head.",
        "sources": ["https://www.nhm.ac.uk/discover/zombie-ants-cordyceps-fungus.html", "https://www.nationalgeographic.com/animals/article/cordyceps-zombie-fungus"],
        "image_hint": "cordyceps fungus rainforest insect",
        "quirky_score": 3,
        "intensity": "medium",
        "tone": "shocking",
        "reel_title": "The Fungus That Controls Minds",
        "reel_script": "There is a fungus that controls minds. It's called Cordyceps. It finds an ant... infects its brain... and takes the wheel. The ant climbs. It bites down on a leaf. It holds there. And then... the fungus erupts from its head. Nature made this. On purpose.",
    },
    {
        "topic": "biology",
        "claim": "Aphids can be born already pregnant. The next generation is developing inside them before they themselves are born, allowing colonies to multiply almost instantly.",
        "sources": ["https://www.britannica.com/animal/aphid", "https://www.nhm.ac.uk/discover/aphids-tiny-insects-that-rule-summer.html"],
        "image_hint": "aphid macro green leaf",
        "quirky_score": 3,
        "intensity": "light",
        "tone": "shocking",
    },

    # ---------- TECHNOLOGY (shock) ----------
    {
        "topic": "technology",
        "claim": "The Antikythera mechanism is a 2,000-year-old Greek device retrieved from a Mediterranean shipwreck in 1901. It is an analog computer that predicted eclipses and astronomical positions, centuries ahead of its known time.",
        "sources": ["https://www.smithsonianmag.com/history/decoding-antikythera-mechanism-first-computer-180953979/", "https://www.nature.com/articles/444534a"],
        "image_hint": "Antikythera mechanism bronze artefact",
        "quirky_score": 3,
        "intensity": "light",
        "tone": "shocking",
    },
    {
        "topic": "technology",
        "claim": "The Voynich Manuscript is a 600-year-old book written in a language nobody has ever cracked. AI, professional cryptographers, and codebreakers have all failed. Its diagrams of plants and naked figures bathing in green water remain unexplained.",
        "sources": ["https://www.bbc.com/culture/article/20180424-the-mysterious-medieval-book-no-one-can-read", "https://collections.library.yale.edu/catalog/2002046"],
        "image_hint": "medieval manuscript illuminated pages",
        "quirky_score": 3,
        "allow_archival": True,
        "intensity": "light",
        "tone": "shocking",
    },
    {
        "topic": "technology",
        "claim": "The first photograph of a human being was taken by accident in 1838. During an 8-minute exposure of a Paris boulevard, only one man stood still long enough to appear. He was getting his shoes shined.",
        "sources": ["https://www.smithsonianmag.com/smart-news/first-known-photograph-person-was-taken-by-accident-180953759/", "https://www.bbc.com/culture/article/20190426-the-secrets-of-the-worlds-first-photograph-of-a-person"],
        "image_hint": "old Paris boulevard photograph 1830s",
        "quirky_score": 3,
        "allow_archival": True,
        "intensity": "light",
        "tone": "shocking",
    },

    # ---------- OCEAN (shock) ----------
    {
        "topic": "ocean",
        "claim": "Male anglerfish are tiny compared to females. When a male finds a mate he bites her, and his body slowly fuses with hers. He loses his eyes, organs, and identity, becoming a permanent reproductive appendage.",
        "sources": ["https://www.nhm.ac.uk/discover/anglerfish-the-original-approach-to-online-dating.html", "https://www.smithsonianmag.com/smart-news/scientists-finally-spot-male-anglerfish-attached-female-180977089/"],
        "image_hint": "anglerfish deep sea bioluminescent",
        "quirky_score": 3,
        "intensity": "medium",
        "tone": "shocking",
        "reel_title": "The Strangest Love Story in the Ocean",
        "reel_script": (
            "In the deep ocean... something extraordinary happens. "
            "The male anglerfish is tiny. Barely the size of your thumb. "
            "The female is enormous. "
            "When a male finds a female, he doesn't swim away. "
            "He bites into her skin. "
            "And holds on. "
            "His body begins to dissolve. "
            "His blood vessels merge with hers. "
            "His eyes disappear. "
            "His organs... go. "
            "Everything that made him... him. Gone. "
            "All that remains is a small lump on her body. "
            "A permanent passenger. "
            "Fully absorbed. "
            "And when she's ready to reproduce... "
            "He's already there."
        ),
    },
    {
        "topic": "ocean",
        "claim": "The Pacific Ocean contains an underwater waterfall called the Denmark Strait Cataract. It is more than 3 times the height of Angel Falls and carries 50,000 times more water than Niagara.",
        "sources": ["https://oceanservice.noaa.gov/facts/largest-waterfall.html", "https://www.britannica.com/place/Denmark-Strait"],
        "image_hint": "underwater ocean current",
        "quirky_score": 3,
        "intensity": "light",
        "tone": "shocking",
    },

    # ---------- EARTH (shock) ----------
    {
        "topic": "earth",
        "claim": "About 74,000 years ago a supervolcano in Sumatra erupted with such force it may have reduced the entire human population to as few as 3,000 to 10,000 individuals. We almost did not make it.",
        "sources": ["https://www.nature.com/articles/35047075", "https://www.smithsonianmag.com/science-nature/when-humans-faced-extinction-180954055/"],
        "image_hint": "volcano eruption ash cloud",
        "quirky_score": 3,
        "intensity": "heavy",
        "tone": "shocking",
        "reel_title": "The Eruption That Nearly Ended Us",
        "reel_script": (
            "About 74 thousand years ago... a volcano erupted in what's now Indonesia. "
            "But this wasn't ordinary. "
            "This was Mount Toba. "
            "The largest eruption on Earth in two million years. "
            "Ash blanketed the planet. "
            "Sunlight dimmed for years. "
            "Temperatures crashed. "
            "And humanity? "
            "We almost didn't make it. "
            "Every human alive today descends from just a few thousand survivors. "
            "An entire species... hanging by a thread."
        ),
    },
    {
        "topic": "earth",
        "claim": "There is a small waterfall in New York State called Eternal Flame Falls. A pocket of natural methane seeps from the rock behind it. The flame has been burning for thousands of years.",
        "sources": ["https://www.smithsonianmag.com/smart-news/the-fire-eternal-on-a-waterfall-in-new-york-state-180962168/", "https://www.atlasobscura.com/places/eternal-flame-falls"],
        "image_hint": "waterfall flame natural rock",
        "quirky_score": 3,
        "intensity": "light",
        "tone": "shocking",
    },

    # ============================================================
    # EXPANSION BATCH — 2026-05-01
    # 21 new shock-tier facts. All pass: self-contained, sourced,
    # visually specific, IG-safe, not already in the bank.
    # ============================================================

    # ---------- HISTORY ----------
    {
        "topic": "history",
        "claim": "In 1919 a storage tank in Boston exploded and released 2.3 million gallons of molasses through the streets at 35 miles per hour. The wave killed 21 people and injured 150. The neighbourhood smelled of molasses for decades.",
        "sources": ["https://www.smithsonianmag.com/arts-culture/bostons-great-molasses-flood-180956439/", "https://www.bbc.com/news/magazine-38210577"],
        "image_hint": "Boston 1919 historic street archive",
        "quirky_score": 3,
        "intensity": "medium",
        "tone": "shocking",
        "reel_title": "The Great Molasses Flood",
    },
    {
        "topic": "history",
        "claim": "Mary Mallon, known as Typhoid Mary, was an asymptomatic carrier who infected at least 51 people without ever feeling ill herself. She was forcibly quarantined twice and spent her last 23 years imprisoned on a small island, never having been convicted of any crime.",
        "sources": ["https://www.bbc.com/news/health-19543353", "https://www.smithsonianmag.com/history/the-rise-and-fall-of-typhoid-mary-180954325/"],
        "image_hint": "vintage hospital ward early 1900s",
        "quirky_score": 3,
        "intensity": "heavy",
        "tone": "sober",
        "reel_title": "Typhoid Mary",
    },
    {
        "topic": "history",
        "claim": "In 1518 hundreds of people in Strasbourg began dancing uncontrollably and could not stop. Within weeks, roughly 400 people were dancing day and night. Many collapsed from exhaustion and some died. No one has ever explained why.",
        "sources": ["https://www.bbc.com/future/article/20180725-the-mysterious-dancing-plague-of-1518", "https://www.smithsonianmag.com/smart-news/mystery-of-the-dancing-plague-of-1518-finally-solved-180960183/"],
        "image_hint": "medieval town square Strasbourg Europe",
        "quirky_score": 3,
        "intensity": "medium",
        "tone": "shocking",
        "reel_title": "The Dancing Plague of 1518",
        "reel_script": "In 1518, in the city of Strasbourg, people started dancing. And couldn't stop. One by one, more joined. Within weeks, four hundred people were dancing in the streets. Day and night. Some for days without stopping. Their feet bled. Their hearts gave out. People died from exhaustion. Nobody played music. Nobody gave an order. It just... happened. Nobody has ever explained why.",
    },
    {
        "topic": "history",
        "claim": "When Albert Einstein died in 1955, the pathologist who performed his autopsy removed and kept his brain without family consent. Thomas Harvey stored it in jars in his basement for decades, secretly mailing slices to researchers around the world.",
        "sources": ["https://www.bbc.com/news/world-us-canada-22031220", "https://www.smithsonianmag.com/science-nature/true-story-of-how-einsteins-brain-ended-up-in-a-jar-180955435/"],
        "image_hint": "vintage anatomy laboratory specimen jars",
        "quirky_score": 3,
        "intensity": "medium",
        "tone": "shocking",
        "reel_title": "The Man Who Stole Einstein's Brain",
    },
    {
        "topic": "history",
        "claim": "Hiroo Onoda was a Japanese soldier stationed in the Philippines who kept fighting for 29 years after the Second World War ended, because nobody had told him. He emerged from the jungle in 1974, still in uniform. His original commanding officer had to fly from Japan to personally order him to stand down.",
        "sources": ["https://www.bbc.com/news/world-asia-25542656", "https://www.smithsonianmag.com/history/hiroo-onoda-soldier-kept-fighting-wwii-29-years-180953307/"],
        "image_hint": "Philippine jungle dense tropical forest",
        "quirky_score": 3,
        "intensity": "medium",
        "tone": "shocking",
        "reel_title": "The Soldier Who Didn't Know It Was Over",
        "reel_script": "In 1945, the Second World War ended. Almost everyone went home. But deep in the jungles of the Philippines... one soldier kept going. His name was Hiroo Onoda. He fought for 29 years. Ambushes. Skirmishes. Surviving alone in the forest. He believed it was all still happening. In 1974, his original commanding officer flew from Japan just to find him. And ordered him, face to face, to stop. He was 52 years old.",
    },
    {
        "topic": "history",
        "claim": "In 1966 a US Air Force bomber collided with a refuelling aircraft over Spain and accidentally dropped four nuclear bombs. None of them detonated. Two released conventional explosives on impact and scattered radioactive material across farmland near the village of Palomares.",
        "sources": ["https://www.bbc.com/news/world-europe-35314927", "https://nsarchive2.gwu.edu/NSAEBB/NSAEBB481/"],
        "image_hint": "Cold War military jet aircraft 1960s",
        "quirky_score": 3,
        "intensity": "heavy",
        "tone": "sober",
        "reel_title": "The Day Four Nuclear Bombs Fell on Spain",
    },

    # ---------- SPACE ----------
    {
        "topic": "space",
        "claim": "The largest known black hole, TON 618, has a mass 66 billion times that of the Sun. Its event horizon is so large that our entire solar system would fit inside it with room to spare.",
        "sources": ["https://www.nasa.gov/mission_pages/chandra/news/black-hole-image-makes-history", "https://www.britannica.com/science/black-hole"],
        "image_hint": "black hole galaxy accretion disc space",
        "quirky_score": 3,
        "intensity": "medium",
        "tone": "shocking",
        "reel_title": "The Biggest Thing in the Universe",
    },
    {
        "topic": "space",
        "claim": "The Boötes Void is a region of space roughly 330 million light years across that contains almost nothing. Where hundreds of thousands of galaxies should exist by any known model, there are fewer than 60. Nobody knows why it is empty.",
        "sources": ["https://www.britannica.com/science/Bootes-void", "https://www.bbc.com/future/article/20221104-the-biggest-structure-in-the-universe"],
        "image_hint": "deep space galaxy cluster stars void",
        "quirky_score": 3,
        "intensity": "medium",
        "tone": "shocking",
        "reel_title": "The Great Nothing",
    },
    {
        "topic": "space",
        "claim": "Jupiter's moon Europa hides a saltwater ocean beneath its frozen crust containing roughly twice as much water as all of Earth's oceans combined. Scientists consider it one of the most promising places in the solar system to look for life.",
        "sources": ["https://science.nasa.gov/jupiter/moons/europa/", "https://www.britannica.com/place/Europa-moon"],
        "image_hint": "Europa moon Jupiter icy surface NASA",
        "quirky_score": 3,
        "intensity": "medium",
        "tone": "shocking",
        "reel_title": "The Ocean Hidden Beneath the Ice",
    },
    {
        "topic": "space",
        "claim": "In 1977 a radio telescope in Ohio detected a 72-second signal from deep space so unusual that the astronomer circled it and wrote 'Wow!' in the margin. The signal exactly matched what scientists expected an alien transmission to look like. It has never been detected again.",
        "sources": ["https://www.bbc.com/future/article/20220901-the-wow-signal-the-mysterious-radio-transmission", "https://www.seti.org/wow-signal"],
        "image_hint": "radio telescope dish night sky stars",
        "quirky_score": 3,
        "intensity": "medium",
        "tone": "shocking",
        "reel_title": "Wow.",
        "reel_script": "In 1977, a radio telescope in Ohio picked up a signal from deep space. It lasted 72 seconds. It matched exactly what scientists expected from an alien transmission. The astronomer on duty circled it on his printout... and wrote one word. Wow. It has never been detected again. Nobody has explained it. Nobody has found the source. It remains the strongest candidate for contact with something... out there.",
    },

    # ---------- BIOLOGY ----------
    {
        "topic": "biology",
        "claim": "Axolotls can regrow entire limbs, their spinal cord, heart muscle, and parts of their brain. They can also accept transplanted tissue from other axolotls, including eyes and brain sections, without rejection.",
        "sources": ["https://www.nationalgeographic.com/animals/amphibians/facts/axolotl", "https://www.smithsonianmag.com/science-nature/how-axolotls-regrow-their-brains-180979203/"],
        "image_hint": "axolotl pink salamander underwater Mexico",
        "quirky_score": 3,
        "intensity": "light",
        "tone": "shocking",
        "reel_title": "The Animal That Regrows Its Brain",
    },
    {
        "topic": "biology",
        "claim": "Vampire bats adopt orphan young from other mothers and regularly share blood meals with starving colony members. If a bat misses a feed, a neighbour it has previously groomed will regurgitate blood to keep it alive.",
        "sources": ["https://www.smithsonianmag.com/science-nature/vampire-bats-have-friends-180974271/", "https://www.nationalgeographic.com/animals/mammals/facts/common-vampire-bat"],
        "image_hint": "bat cave colony dark hanging",
        "quirky_score": 3,
        "intensity": "light",
        "tone": "shocking",
        "reel_title": "The Most Generous Animal You've Never Heard Of",
    },
    {
        "topic": "biology",
        "claim": "Glass frogs have transparent skin on their underside. You can watch their heart beating, their digestive system working, and see developing eggs inside a pregnant female. They are living windows into a body.",
        "sources": ["https://www.nationalgeographic.com/animals/amphibians/facts/glass-frog", "https://www.bbc.com/news/science-environment-63668019"],
        "image_hint": "glass frog transparent leaf tropical rainforest",
        "quirky_score": 3,
        "intensity": "light",
        "tone": "shocking",
        "reel_title": "You Can See Right Through Them",
    },
    {
        "topic": "biology",
        "claim": "Migratory birds navigate partly via quantum mechanics. Proteins in their eyes react to Earth's magnetic field through a quantum entanglement effect, allowing the birds to literally perceive the magnetic field as a visual overlay on their surroundings.",
        "sources": ["https://www.bbc.com/future/article/20210714-the-birds-that-can-see-earths-magnetic-field", "https://www.nature.com/articles/nature08897"],
        "image_hint": "birds flock migration sky golden light",
        "quirky_score": 3,
        "intensity": "light",
        "tone": "shocking",
        "reel_title": "Birds Can See What We Cannot",
    },

    # ---------- OCEAN ----------
    {
        "topic": "ocean",
        "claim": "The barreleye fish has a completely transparent head filled with fluid. What appears to be its eyes from the front are actually olfactory organs. Its real eyes are the glowing green tubes inside its skull, pointing straight upward.",
        "sources": ["https://www.mbari.org/creatures/barreleye/", "https://www.nationalgeographic.com/animals/fish/facts/barreleye-fish"],
        "image_hint": "barreleye fish deep sea transparent green eyes",
        "quirky_score": 3,
        "intensity": "medium",
        "tone": "shocking",
        "reel_title": "The Fish With a See-Through Head",
        "reel_script": "There is a fish in the deep ocean with a completely transparent head. Inside it... two glowing green tubes point straight upward. Those are its eyes. The dark spots you think are eyes are not eyes at all. They're its nose. Scientists filmed it alive for the first time in 2004. Before that, we thought its head was just differently shaped. We were wrong. The ocean still has things that stop you cold.",
    },
    {
        "topic": "ocean",
        "claim": "The mimic octopus can impersonate at least 15 different marine species, including the lionfish, flatfish, and banded sea snake. It actively selects which animal to impersonate based on which predator is nearby.",
        "sources": ["https://www.smithsonianmag.com/science-nature/the-incredible-mimic-octopus-180949698/", "https://www.nationalgeographic.com/animals/invertebrates/facts/mimic-octopus"],
        "image_hint": "mimic octopus coral reef underwater Indonesia",
        "quirky_score": 3,
        "intensity": "medium",
        "tone": "shocking",
        "reel_title": "The Master of Disguise",
    },
    {
        "topic": "ocean",
        "claim": "Giant oarfish can reach 11 metres in length, making them the longest bony fish on Earth. They swim vertically in the deep ocean and are almost never seen alive. They are thought to be the origin of centuries of sea serpent myths.",
        "sources": ["https://www.nhm.ac.uk/discover/giant-oarfish-facts.html", "https://www.nationalgeographic.com/animals/fish/facts/oarfish"],
        "image_hint": "oarfish long silver fish ocean deep sea",
        "quirky_score": 3,
        "intensity": "medium",
        "tone": "shocking",
        "reel_title": "The Real Sea Serpent",
    },

    # ---------- EARTH ----------
    {
        "topic": "earth",
        "claim": "In Turkmenistan there is a 30-metre wide crater that has been on fire since 1971. Soviet engineers accidentally ignited escaping gas while drilling and expected it to burn out in weeks. It has never stopped. Locals call it the Door to Hell.",
        "sources": ["https://www.bbc.com/future/article/20190501-the-history-of-the-door-to-hell", "https://www.atlasobscura.com/places/darvaza-gas-crater"],
        "image_hint": "Darvaza gas crater fire night Turkmenistan",
        "quirky_score": 3,
        "intensity": "medium",
        "tone": "shocking",
        "reel_title": "The Door to Hell",
        "reel_script": "In 1971, Soviet engineers were drilling for gas in the Karakum desert. The ground collapsed. A crater opened. Gas started escaping. So they did what seemed logical. They lit it on fire. Thinking it would burn out in a few weeks. It is still burning today. Fifty years later. Thirty metres wide. Deep enough to swallow a building. Local people call it the Door to Hell. And no one has ever turned it off.",
    },
    {
        "topic": "earth",
        "claim": "In 1958 an earthquake in Alaska triggered a landslide that generated a wave 524 metres high in Lituya Bay. Taller than the Empire State Building. Two people happened to be anchored in the bay and surfed the wave to safety.",
        "sources": ["https://www.usgs.gov/news/lituya-bay-alaska-mega-tsunami", "https://www.bbc.com/news/science-environment-14229564"],
        "image_hint": "Alaska coast fjord dramatic mountains sea",
        "quirky_score": 3,
        "intensity": "heavy",
        "tone": "shocking",
        "reel_title": "The Tallest Wave Ever Recorded",
    },
    {
        "topic": "earth",
        "claim": "Movile Cave in Romania has been completely sealed from the surface for approximately 5.5 million years. Inside, 48 species of animals live in total darkness, breathing toxic air, feeding on chemosynthetic bacteria. None of them exist anywhere else on Earth.",
        "sources": ["https://www.bbc.com/future/article/20150522-the-cave-sealed-for-millions-of-years", "https://www.nationalgeographic.com/travel/article/movile-cave"],
        "image_hint": "dark cave underground water pool limestone",
        "quirky_score": 3,
        "intensity": "medium",
        "tone": "shocking",
        "reel_title": "The World Sealed for Five Million Years",
    },
    {
        "topic": "earth",
        "claim": "In the Sahara Desert there is a geological formation 50 kilometres across that looks like a giant eye when seen from space. Called the Richat Structure, or Eye of the Sahara, it was formed by an ancient volcanic dome that slowly collapsed over millions of years.",
        "sources": ["https://earthobservatory.nasa.gov/images/36356/richat-structure", "https://www.britannica.com/place/Richat-Structure"],
        "image_hint": "Sahara desert aerial satellite Eye Richat Structure",
        "quirky_score": 3,
        "intensity": "light",
        "tone": "shocking",
        "reel_title": "The Eye of the Sahara",
    },
]


from src.core.paths import DISCOVERED_FACTS as DISCOVERED_PATH  # canonical path


def _with_defaults(row: dict) -> dict:
    """Backfill new schema fields on legacy entries.

    quirky_score:        0 (textbook) → 3 (wait what). Defaults to 1.
    intensity:           light / medium / heavy. Defaults to light.
    tone:                curious / shocking / wholesome / sober. Defaults to curious.
    sensitivity:         safe / edgy / controversial. Auto-derived from claim
                         text via sensitivity_guide unless the author set it.
    sensitivity_flags:   list of triggered categories (animal_welfare,
                         graphic_medical, religion, current_politics, etc).
    """
    from .sensitivity_guide import apply_sensitivity_defaults
    if "quirky_score" not in row:
        row["quirky_score"] = 1
    if "intensity" not in row:
        row["intensity"] = "light"
    if "tone" not in row:
        row["tone"] = "curious"
    apply_sensitivity_defaults(row)
    return row


def load_all_facts() -> list[dict]:
    """Curated bank + auto-discovered feed, deduped by claim.

    Curated facts always rank first so plan_week consumes the gold-standard
    set before reaching for r/TIL imports. Every returned row has the
    quirky_score / intensity / tone fields populated (defaults applied to
    legacy entries that pre-date the schema upgrade).
    """
    seen_claims: set[str] = set()
    out: list[dict] = []
    for row in RARE_FACT_BANK:
        c = row["claim"]
        if c in seen_claims:
            continue
        seen_claims.add(c)
        out.append(_with_defaults(dict(row)))
    if DISCOVERED_PATH.exists():
        with DISCOVERED_PATH.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                c = row.get("claim")
                if not c or c in seen_claims:
                    continue
                seen_claims.add(c)
                out.append(_with_defaults(row))
    return out
