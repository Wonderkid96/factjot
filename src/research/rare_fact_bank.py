"""Curated bank of self-contained facts grouped by topic.

## Quality standard - MUST READ before adding any fact

Every fact must pass the SHOCK TEST before entry:

  "Would a smart adult who reads a lot genuinely say 'wait, WHAT?'"

If the answer is "probably, it's a nice fact" - it fails. If the answer is
"that seems impossible, I need to verify this" - it passes.

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
  1 = standard fact (use sparingly, prefer upgrading or replacing)
  0 = textbook (do not use for carousels, only background bank)

## REEL ELIGIBILITY (quirky_score=3 only) - HARD REQUIREMENTS

Every q3 fact MUST carry these two fields, or `make_reel.py` will refuse
to pick it. There is no auto-fallback path.

  reel_title:  Short documentary-style hook (3-7 words). The opening card.
               Examples: "The Demon Core", "The Girls Who Glowed".
               Must NOT contain em-dashes (brand voice rule).

  reel_script: Hand-written voice-over script, >= 70 words. Narrative
               build with ellipses for dramatic pacing. Targets 35-55s
               of voice at ElevenLabs delivery. Must NOT contain em-dashes.

After editing this file, run:
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
        scripts/validate_reel_facts.py

This was added 2026-05-02 in response to a Switzerland 1986 reel that
shipped at 22.7 seconds with the title "The Story of Until Switzerland"
because both fields were missing on that fact. The auto-formatter and
auto-titler are no longer invoked from make_reel.py. Do not reintroduce.

`RARE_FACT_BANK` is the hand-curated source of truth.
`load_all_facts()` merges it with `data/discovered_facts.jsonl` (auto-pulled
by `scripts/discover_facts.py`) so the publish chain has more runway.
"""
from __future__ import annotations

import json
from pathlib import Path

RARE_FACT_BANK = [
    {'topic': 'history',
     'claim': 'In 1848 a railroad foreman named Phineas Gage had a 3-foot iron rod blown clean through '
              'his skull. He survived for 12 more years. His personality changed forever, and the case '
              'founded modern neuroscience.',
     'sources': ['https://www.smithsonianmag.com/history/phineas-gage-neurosciences-most-famous-patient-11390067/',
                 'https://www.britannica.com/biography/Phineas-Gage'],
     'image_hint': 'railroad construction workers explosion 1848',
     'quirky_score': 3,
     'intensity': 'medium',
     'tone': 'shocking',
     'reel_title': 'The Man With a Spike Through His Head',
     'reel_script': 'A 3-foot iron rod shot through Phineas Gage\'s skull in 1848 and he sat up, '
                    'talked, and walked to the doctor. The rod entered under his cheek and left '
                    'through the top of his head. He lived 12 more years. But everyone who knew him '
                    'said he was gone. Not dead. Just different. His personality, his patience, his '
                    'judgment, all of it replaced by something else. He became proof that who you '
                    'are lives in specific tissue. Damage the tissue and the person does not '
                    'survive, even if the body does.'},
    {'topic': 'history',
     'claim': "In 1945 a Colorado farmer cut off a chicken's head, but the bird kept living. Mike the "
              'Headless Chicken survived 18 months, fed milk through a dropper, and toured America '
              'earning his owner a fortune.',
     'sources': ['https://www.smithsonianmag.com/smart-news/the-chicken-that-lived-for-18-months-without-a-head-115582153/',
                 'https://www.bbc.com/news/magazine-33946948'],
     'image_hint': 'vintage chicken farm 1940s',
     'quirky_score': 3,
     'intensity': 'light',
     'tone': 'shocking',
     'sensitivity': 'controversial',
     'sensitivity_flags': ['animal_welfare', 'factual_dispute']},
    {'topic': 'history',
     'claim': 'In 1937 a defrocked English priest named Harold Davidson was mauled to death by a lion '
              'in a sideshow at Skegness. He had spent five years protesting his innocence after a '
              'scandal stripped him of his church, exhibiting himself in a barrel on Blackpool '
              "seafront and finally re-enacting Daniel in the Lions' Den live in a cage with two "
              'lions. The lions did not play along.',
     'sources': ['https://en.wikipedia.org/wiki/Harold_Davidson',
                 'https://en.wikipedia.org/wiki/List_of_unusual_deaths_in_the_20th_century'],
     'image_hint': 'lion tamer circus vintage 1930s',
     'quirky_score': 3,
     'intensity': 'medium',
     'tone': 'shocking',
     'reel_title': "The Priest Who Died in the Lions' Den",
     'reel_script': 'Harold Davidson spent five years protesting his innocence after the Church threw '
                    'him out in a scandal. He exhibited himself in a barrel on Blackpool seafront. '
                    'He performed in sideshows. By 1937 his act had escalated to re-enacting Daniel '
                    "in the Lions' Den, live, in a cage, with two actual lions, in Skegness. The "
                    'lions were not briefed on the story. They mauled him. He died two days later. '
                    'The case for his innocence died with him, inside a cage, in a seaside resort.',
     'discovered_via': 'wikipedia:unusual_deaths'},
    {'topic': 'history',
     'claim': 'In 1962 a Soviet submarine officer named Vasili Arkhipov refused to authorise a nuclear '
              'torpedo launch during the Cuban Missile Crisis. He was outvoted 2 to 1, and his veto is '
              'the only reason World War 3 did not begin that day.',
     'sources': ['https://www.bbc.com/news/world-europe-39707294',
                 'https://nsarchive2.gwu.edu/nukevault/ebb399/'],
     'image_hint': 'nuclear submarine torpedo cold war military',
     'quirky_score': 3,
     'intensity': 'heavy',
     'tone': 'sober',
     'reel_title': 'The Man Who Saved the World',
     'reel_script': 'In October 1962, a Soviet submarine near Cuba had been out of contact with '
                    'Moscow for days. American destroyers were dropping depth charges above them. '
                    'The crew believed war had already started. The submarine had one nuclear '
                    'torpedo. Launching required three officers to agree. Two voted yes. One man '
                    'said no. His name was Vasili Arkhipov. You have never heard of him. There is '
                    'no monument to him. He is not in school textbooks. And he is the reason you '
                    'are alive.'},
    {'topic': 'history',
     'claim': 'Sarah Winchester, heir to the Winchester rifle fortune, believed she was haunted by the '
              'dead. She built a 161-room mansion with stairs to nowhere and doors opening onto walls, '
              'with construction running 24 hours a day for 38 years.',
     'sources': ['https://www.smithsonianmag.com/history/sarah-winchester-mystery-mansion-ghosts-180970163/',
                 'https://www.bbc.com/culture/article/20180202-the-real-story-of-the-winchester-mystery-house'],
     'image_hint': 'Victorian mansion architecture haunted',
     'quirky_score': 3,
     'intensity': 'light',
     'tone': 'shocking',
     'reel_title': 'The House That Never Stopped',
     'reel_script': 'Sarah Winchester believed she was haunted by everyone her family\'s rifles had '
                    'killed. A medium told her the spirits would take her if construction ever '
                    'stopped. So she kept building. For 38 years. Round the clock. 161 rooms. '
                    'Stairs that lead directly into ceilings. Doors that open onto walls. Hallways '
                    'that go nowhere. She kept the carpenters employed and the ghosts, presumably, '
                    'at bay. Construction stopped when she died in 1922. The house still stands. '
                    'You can visit it. Whether you should is a separate question.'},
    {'topic': 'history',
     'claim': 'The 18th-century French soldier Tarrare could eat 30 pounds of food in a day. He was '
              "documented eating a live eel whole, a doctor's wedding ring, and once attempted to eat "
              'a live cat at the hospital.',
     'sources': ['https://www.smithsonianmag.com/smart-news/strange-tale-tarrare-most-disgusting-french-frenchman-180962844/',
                 'https://www.bbc.com/future/article/20191028-the-bottomless-pit-the-man-who-was-always-hungry'],
     'image_hint': '18th century French soldier portrait',
     'quirky_score': 3,
     'intensity': 'medium',
     'tone': 'shocking',
     'sensitivity': 'controversial',
     'sensitivity_flags': ['animal_welfare']},
    {'topic': 'history',
     'claim': 'In 2003 a hiker pinned by a boulder in a Utah canyon used a dull multitool to amputate '
              'his own arm. Aron Ralston then rappelled down a cliff and walked 8 miles before being '
              'airlifted to safety.',
     'sources': ['https://www.bbc.com/news/world-us-canada-12723799',
                 'https://www.nationalgeographic.com/adventure/article/127-hours-aron-ralston'],
     'image_hint': 'Utah canyon red rock',
     'quirky_score': 3,
     'intensity': 'heavy',
     'tone': 'shocking',
     'reel_title': '127 Hours',
     'reel_script': 'Aron Ralston went hiking alone in Utah in 2003 and told no one where he was '
                    'going. A boulder shifted and pinned his arm. He waited five days. No water, '
                    'no food, hallucinating. Then he broke the bones in his own forearm, cut '
                    'through the remaining tissue with a dull multitool, rappelled a cliff with '
                    'one arm, and walked eight miles. He survived. He later said it was the best '
                    'decision he ever made. Most people would have led with not going alone.'},
    {'topic': 'history',
     'claim': 'Early 20th-century factory girls painted glow-in-the-dark watch dials with radium '
              'paint. Told to lick their brushes for a sharp tip, many died slowly of radiation '
              "poisoning. Their lawsuit established workers' rights to know what materials they "
              'handle.',
     'sources': ['https://www.smithsonianmag.com/science-nature/luminous-toxic-180962343/',
                 'https://www.bbc.com/news/world-us-canada-43822124'],
     'image_hint': 'radium watch factory workers 1920s glow paint',
     'quirky_score': 3,
     'intensity': 'heavy',
     'tone': 'sober',
     'reel_title': 'The Girls Who Glowed',
     'reel_script': 'In the 1920s, factories paid young women to paint watch dials with radium paint '
                    'and told them to sharpen their brushes with their lips. Every day. The company '
                    'knew radium was dangerous. They said nothing. The women began dying. Bones '
                    'dissolving from inside. Jaws falling off. When they sued, the company called '
                    'them unhealthy and tried to bury the case. Some of them testified from '
                    'hospital beds. They won. Their lawsuit created the legal framework for '
                    'workers to know what they are being asked to handle. The company was wrong '
                    'about everything except one thing. It was profitable.'},
    {'topic': 'history',
     'claim': "Until 1986, women in Switzerland needed their husband's written permission to take a "
              'paid job. Married women were legally subordinate to their husbands until a sweeping '
              'reform that year.',
     'sources': ['https://www.bbc.com/news/world-europe-30605898',
                 'https://www.britannica.com/topic/womens-suffrage-in-Switzerland'],
     'image_hint': 'Swiss alps village 1980s',
     'quirky_score': 3,
     'intensity': 'heavy',
     'tone': 'sober',
     'reel_title': 'Switzerland, 1986',
     'reel_script': 'Until 1986, a married woman in Switzerland needed her husband\'s written '
                    'permission to take a paid job. She could not open a bank account without '
                    'him. Could not sign a lease. Legally subordinate. This was not the Middle '
                    'Ages. This was the same year as Top Gun. The same year as Chernobyl. '
                    'Switzerland, which is famous for being civilised and neutral and correct '
                    'about most things, put this to a national vote. The vote was to change it. '
                    'Which does raise the question of what the other votes were about.'},
    {'topic': 'space',
     'claim': 'In 1945 and 1946 the same plutonium sphere killed two Manhattan Project scientists in '
              'separate criticality accidents. They named it the Demon Core.',
     'sources': ['https://www.bbc.com/future/article/20210121-the-radioactive-core-that-killed-its-scientists',
                 'https://ahf.nuclearmuseum.org/ahf/history/demon-core/'],
     'image_hint': 'atomic research laboratory 1940s',
     'quirky_score': 3,
     'intensity': 'medium',
     'tone': 'shocking',
     'reel_title': 'The Demon Core',
     'reel_script': 'The Manhattan Project built a third plutonium core in 1945. Japan surrendered '
                    'before they needed it, so scientists used it for experiments instead. They '
                    'called this tickling the dragon\'s tail, which tells you something about the '
                    'culture. In 1945 a screwdriver slipped. Harry Daghlian absorbed a lethal dose '
                    'and died. In 1946 a different accident with the same sphere killed Louis '
                    'Slotin. Same core. Same lab. Two men. They named it the Demon Core and '
                    'melted it down. Probably should have done that first.'},
    {'topic': 'space',
     'claim': 'In 1908 something exploded above remote Siberia with the force of about 1,000 Hiroshima '
              'bombs. It flattened 2,150 square kilometres of forest. There was no crater. Astronomers '
              'still debate whether it was a comet or asteroid.',
     'sources': ['https://www.nasa.gov/feature/goddard/2018/30-years-since-tunguska',
                 'https://www.britannica.com/event/Tunguska-event'],
     'image_hint': 'Siberia forest devastation aerial',
     'quirky_score': 3,
     'intensity': 'medium',
     'tone': 'shocking',
     'reel_title': 'The Explosion With No Crater',
     'reel_script': 'Something exploded above Siberia in 1908 with the force of a thousand Hiroshima '
                    'bombs. It flattened two thousand square kilometres of forest. Windows shattered '
                    'hundreds of miles away. The night sky over Europe glowed for days. There was '
                    'no crater. No fragments. No metal. It detonated in the air and left nothing '
                    'behind. Scientists still disagree on what it was. Asteroid, comet, something '
                    'else. It hit one of the emptiest places on Earth. If it had arrived four hours '
                    'later, it would have hit St Petersburg.'},
    {'topic': 'space',
     'claim': 'In 1859 a solar storm hit Earth so violently that telegraph wires sparked, papers '
              'caught fire, and auroras were visible in the Caribbean. If the Carrington Event '
              'happened today, the electrical grid would be out for years.',
     'sources': ['https://www.nasa.gov/topics/earth/features/sun_darkness.html',
                 'https://www.bbc.com/future/article/20210107-the-1859-solar-storm-that-electrified-earth'],
     'image_hint': 'aurora borealis night sky',
     'quirky_score': 3,
     'intensity': 'medium',
     'tone': 'shocking',
     'reel_title': 'The Day the Sun Struck Earth',
     'reel_script': 'In 1859 a solar storm hit Earth so hard that telegraph operators got electric '
                    'shocks through their machines. Auroras were visible in the Caribbean. Papers '
                    'caught fire on telegraph desks. Some machines kept sending messages after '
                    'being unplugged. The Carrington Event is the strongest solar storm ever '
                    'recorded. If it happened today, the global electrical grid would be down for '
                    'years. Trillions in damage. Billions without power. Storms like it happen '
                    'roughly every century. The last one was 1859. You do the maths.'},
    {'topic': 'space',
     'claim': 'Pluto is smaller than Russia. Its surface area covers 17.7 million km², while Russia '
              'alone covers 17.1 million km². Pluto is also smaller than the Moon.',
     'sources': ['https://science.nasa.gov/dwarf-planets/pluto/facts/',
                 'https://www.britannica.com/place/Pluto-dwarf-planet'],
     'image_hint': 'Pluto dwarf planet New Horizons',
     'quirky_score': 3,
     'intensity': 'light',
     'tone': 'shocking',
     'reel_title': 'Pluto Is Smaller Than Russia',
     'reel_script': 'Pluto is smaller than Russia. Not the solar system. Not the universe. One '
                    'country. Pluto\'s surface area is 17.7 million square kilometres. Russia is '
                    '17.1 million. They are roughly the same size. Pluto is also smaller than our '
                    'Moon. If you placed Pluto over the Moon, it would disappear behind it. The '
                    'object we spent decades calling a planet is smaller than the thing we look at '
                    'every night and take for granted. It was demoted in 2006. Given everything, '
                    'that seems fair.'},
    {'topic': 'biology',
     'claim': 'Octopuses have nine brains. One central brain plus a smaller brain in each of the eight '
              'arms. The arms can react and decide independently of the central brain.',
     'sources': ['https://www.smithsonianmag.com/science-nature/octopuses-have-nine-brains-180977551/',
                 'https://www.nhm.ac.uk/discover/octopus-facts.html'],
     'image_hint': 'octopus underwater intelligent',
     'quirky_score': 3,
     'intensity': 'light',
     'tone': 'shocking',
     'reel_title': 'Nine Brains, Eight Decisions',
     'reel_script': 'An octopus has nine brains. One central brain and one in each of its eight '
                    'arms. Each arm can taste, think, and make decisions independently. Cut an arm '
                    'off and it keeps moving, grabbing food, reacting to threats, with no input '
                    'from the central brain at all. When an octopus solves a problem, nine minds '
                    'are involved. What that experience is like from the inside, we have no way '
                    'of knowing. They diverged from our evolutionary line 750 million years ago '
                    'and arrived at intelligence through an entirely different route. We share a '
                    'planet with them and barely understand them.'},
    {'topic': 'biology',
     'claim': 'The mantis shrimp punches with the speed of a bullet, accelerating its claw at 10,000 '
              'g. The strike creates cavitation bubbles that briefly reach the temperature of the '
              "Sun's surface.",
     'sources': ['https://www.bbc.com/earth/story/20150403-meet-the-mantis-shrimp',
                 'https://www.smithsonianmag.com/science-nature/strange-and-twisted-life-mantis-shrimp-180970309/'],
     'image_hint': 'mantis shrimp colourful underwater',
     'quirky_score': 3,
     'intensity': 'light',
     'tone': 'shocking',
     'reel_title': 'The Deadliest Punch in Nature',
     'reel_script': 'The mantis shrimp is roughly the size of your hand and throws the fastest punch '
                    'in the animal kingdom. Its claw accelerates at 10,000 g, faster than a bullet. '
                    'The strike boils the water around it. The resulting cavitation bubble reaches '
                    'the temperature of the Sun\'s surface for a fraction of a second. It can crack '
                    'glass aquarium walls. It also has 16 colour receptors. Humans have 3. What it '
                    'sees, we cannot visualise. A creature the size of your hand that punches '
                    'harder than physics should allow and perceives a world we cannot access.'},
    {'topic': 'biology',
     'claim': 'Naked mole-rats can survive without oxygen for 18 minutes by switching their metabolism '
              'to plant-style fructose burning. They almost never get cancer and can live 30 years.',
     'sources': ['https://www.smithsonianmag.com/science-nature/the-naked-mole-rat-might-just-be-the-strangest-mammal-ever-180974089/',
                 'https://www.science.org/doi/10.1126/science.aab3896'],
     'image_hint': 'naked mole rat underground',
     'quirky_score': 3,
     'intensity': 'light',
     'tone': 'shocking',
     'reel_title': "The Mammal That Shouldn't Exist",
     'reel_script': 'The naked mole-rat can survive 18 minutes without oxygen by switching its '
                    'metabolism to burn fructose, like a plant. No other vertebrate does this. '
                    'It almost never gets cancer. It barely feels pain. It lives 30 years, '
                    'when comparable rodents live 3. It does not age in any way scientists '
                    'can measure. It is ugly, hairless, nearly blind, and lives underground '
                    'in a colony with a queen, like an insect. Everything about it is wrong '
                    'for a mammal. And it is currently the most interesting animal in '
                    'medical research.'},
    {'topic': 'biology',
     'claim': 'There is a fungus called Cordyceps that hijacks insect brains. It compels infected ants '
              "to climb a plant, bite down, and stay still while the fungus erupts from the host's "
              'head.',
     'sources': ['https://www.nhm.ac.uk/discover/zombie-ants-cordyceps-fungus.html',
                 'https://www.nationalgeographic.com/animals/article/cordyceps-zombie-fungus'],
     'image_hint': 'cordyceps fungus rainforest insect',
     'quirky_score': 3,
     'intensity': 'medium',
     'tone': 'shocking',
     'reel_title': 'The Fungus That Controls Minds',
     'reel_script': 'There is a fungus called Cordyceps that infects ants, grows through their '
                    'muscles and into their brains, compels them to climb to a specific height '
                    'on a specific type of plant, forces them to bite down on a leaf, and then '
                    'erupts from their heads to spread spores onto the colony below. The fungus '
                    'does not kill the ant immediately. It drives it first. The ant becomes '
                    'a vehicle. Scientists have found fossilised leaves with Cordyceps bite '
                    'marks from 48 million years ago. It has been doing this for a very long '
                    'time.'},
    {'topic': 'biology',
     'claim': 'Aphids can be born already pregnant. The next generation is developing inside them '
              'before they themselves are born, allowing colonies to multiply almost instantly.',
     'sources': ['https://www.britannica.com/animal/aphid',
                 'https://www.nhm.ac.uk/discover/aphids-tiny-insects-that-rule-summer.html'],
     'image_hint': 'aphid macro green leaf',
     'quirky_score': 3,
     'intensity': 'light',
     'tone': 'shocking',
     'reel_title': 'Born Already Pregnant',
     'reel_script': 'Aphids can be born already pregnant. The next generation is developing inside '
                    'them before they have been born themselves. Three generations nested inside '
                    'each other before any of them sees daylight. When food is available, females '
                    'skip males entirely and clone themselves. One aphid in spring becomes '
                    'thousands by midsummer. They are simultaneously grandmother, mother, and '
                    'daughter before they take their first breath. Biologically this is called '
                    'telescoping generations. Practically it means a garden can become an infestation '
                    'in a week.'},
    {'topic': 'technology',
     'claim': 'The Antikythera mechanism is a 2,000-year-old Greek device retrieved from a '
              'Mediterranean shipwreck in 1901. It is an analog computer that predicted eclipses and '
              'astronomical positions, centuries ahead of its known time.',
     'sources': ['https://www.smithsonianmag.com/history/decoding-antikythera-mechanism-first-computer-180953979/',
                 'https://www.nature.com/articles/444534a'],
     'image_hint': 'Antikythera mechanism bronze artefact',
     'quirky_score': 3,
     'intensity': 'light',
     'tone': 'shocking',
     'reel_title': 'The Ancient Computer',
     'reel_script': 'In 1901 divers found a corroded lump of bronze in a Roman shipwreck. It sat in '
                    'a museum drawer for decades. Someone eventually X-rayed it. Inside were 30 '
                    'precisely cut interlocking bronze gears. It was a computer. Built 2,000 years '
                    'ago. It predicted eclipses, tracked planetary positions, and followed the '
                    'Olympic cycle. Nothing of comparable mechanical complexity would appear again '
                    'for another 1,400 years. We do not know who built it. Whatever civilisation '
                    'produced this knowledge, that knowledge did not survive. The machine did.'},
    {'topic': 'technology',
     'claim': 'The Voynich Manuscript is a 600-year-old book written in a language nobody has ever '
              'cracked. AI, professional cryptographers, and codebreakers have all failed. Its '
              'diagrams of plants and naked figures bathing in green water remain unexplained.',
     'sources': ['https://www.bbc.com/culture/article/20180424-the-mysterious-medieval-book-no-one-can-read',
                 'https://collections.library.yale.edu/catalog/2002046'],
     'image_hint': 'medieval manuscript illuminated pages',
     'quirky_score': 3,
     'allow_archival': True,
     'intensity': 'light',
     'tone': 'shocking',
     'reel_title': 'The Book Nobody Can Read',
     'reel_script': 'The Voynich Manuscript is 600 years old, 240 pages long, and completely '
                    'unreadable. Every word is written in a language that has never been identified. '
                    'The illustrations show plants no botanist recognises, star charts matching no '
                    'known sky, and figures bathing in green water through interconnecting tubes. '
                    'Codebreakers from both World Wars failed. The CIA failed. Modern AI failed. '
                    'Statistical analysis confirms it follows the patterns of real language. We '
                    'just cannot identify which one. It sits in a vault at Yale. Either it is the '
                    'most elaborate hoax in history or something is waiting to be understood.'},
    {'topic': 'technology',
     'claim': 'The first photograph of a human being was taken by accident in 1838. During an 8-minute '
              'exposure of a Paris boulevard, only one man stood still long enough to appear. He was '
              'getting his shoes shined.',
     'sources': ['https://www.smithsonianmag.com/smart-news/first-known-photograph-person-was-taken-by-accident-180953759/',
                 'https://www.bbc.com/culture/article/20190426-the-secrets-of-the-worlds-first-photograph-of-a-person'],
     'image_hint': 'old Paris boulevard photograph 1830s',
     'quirky_score': 3,
     'allow_archival': True,
     'intensity': 'light',
     'tone': 'shocking',
     'reel_title': 'The First Person Ever Photographed',
     'reel_script': 'The first photograph of a human being was taken by accident. In 1838, Daguerre '
                    'pointed a camera at a Paris boulevard. The exposure took 8 minutes. Everything '
                    'moving, carriages, horses, hundreds of pedestrians, vanished. The street looked '
                    'empty. Except for one man who stayed still long enough to appear. He was getting '
                    'his shoes shined. We do not know his name. He did not know he was being '
                    'photographed. He did not know photography existed. He is the first human being '
                    'ever captured on camera, and he was just standing there.'},
    {'topic': 'ocean',
     'claim': 'Male anglerfish are tiny compared to females. When a male finds a mate he bites her, '
              'and his body slowly fuses with hers. He loses his eyes, organs, and identity, becoming '
              'a permanent reproductive appendage.',
     'sources': ['https://www.nhm.ac.uk/discover/anglerfish-the-original-approach-to-online-dating.html',
                 'https://www.smithsonianmag.com/smart-news/scientists-finally-spot-male-anglerfish-attached-female-180977089/'],
     'image_hint': 'anglerfish deep sea bioluminescent',
     'quirky_score': 3,
     'intensity': 'medium',
     'tone': 'shocking',
     'reel_title': 'The Strangest Love Story in the Ocean',
     'reel_script': 'The male anglerfish finds a mate by biting into her skin and then dissolving. '
                    'His blood vessels merge with hers. His eyes go. His organs go. His immune '
                    'system goes. Everything that made him a separate organism disappears. What '
                    'remains is a small lump on her body, genetically distinct but physically '
                    'merged, permanently attached. He provides sperm on demand. She provides '
                    'everything else. Scientists discovered this because they kept finding female '
                    'anglerfish with unexplained lumps on them. The lumps were the males. Nobody '
                    'had suspected this was possible.'},
    {'topic': 'ocean',
     'claim': 'The Pacific Ocean contains an underwater waterfall called the Denmark Strait Cataract. '
              'It is more than 3 times the height of Angel Falls and carries 50,000 times more water '
              'than Niagara.',
     'sources': ['https://oceanservice.noaa.gov/facts/largest-waterfall.html',
                 'https://www.britannica.com/place/Denmark-Strait'],
     'image_hint': 'underwater ocean current',
     'quirky_score': 3,
     'intensity': 'light',
     'tone': 'shocking',
     'reel_title': "The World's Tallest Waterfall",
     'reel_script': 'The tallest waterfall on Earth is underwater. Between Greenland and Iceland, '
                    'cold dense Arctic water crashes into the warmer Atlantic and falls three and a '
                    'half kilometres. The Denmark Strait Cataract. Three times taller than Angel '
                    'Falls. It carries fifty thousand times more water per second than Niagara. It '
                    'has been falling continuously for thousands of years. No one has ever seen it '
                    'and no one ever will. The largest waterfall on the planet, hidden beneath '
                    'the sea, completely invisible, falling right now.'},
    {'topic': 'earth',
     'claim': 'About 74,000 years ago a supervolcano in Sumatra erupted with such force it may have '
              'reduced the entire human population to as few as 3,000 to 10,000 individuals. We almost '
              'did not make it.',
     'sources': ['https://www.nature.com/articles/35047075',
                 'https://www.smithsonianmag.com/science-nature/when-humans-faced-extinction-180954055/'],
     'image_hint': 'volcano eruption ash cloud',
     'quirky_score': 3,
     'intensity': 'heavy',
     'tone': 'shocking',
     'reel_title': 'The Eruption That Nearly Ended Us',
     'reel_script': 'Seventy-four thousand years ago a volcano in Indonesia erupted and reduced the '
                    'entire human population to somewhere between three and ten thousand people. '
                    'Every human alive today is descended from those survivors. Mount Toba threw '
                    'two thousand eight hundred cubic kilometres of material into the sky. Ash '
                    'covered the planet from India to East Africa. Temperatures dropped. Food '
                    'chains collapsed. The species nearly ended. We do not know why enough people '
                    'survived. We just know they did, and here we are, remarkably, as a result.'},
    {'topic': 'earth',
     'claim': 'There is a small waterfall in New York State called Eternal Flame Falls. A pocket of '
              'natural methane seeps from the rock behind it. The flame has been burning for thousands '
              'of years.',
     'sources': ['https://www.smithsonianmag.com/smart-news/the-fire-eternal-on-a-waterfall-in-new-york-state-180962168/',
                 'https://www.atlasobscura.com/places/eternal-flame-falls'],
     'image_hint': 'waterfall flame natural rock',
     'quirky_score': 3,
     'intensity': 'light',
     'tone': 'shocking',
     'reel_title': 'The Fire That Never Goes Out',
     'reel_script': 'Behind a waterfall in upstate New York there is a flame burning underwater. '
                    'Natural methane seeps up through the rock and has been feeding it for thousands '
                    'of years. Native Americans knew about it. European settlers found it already '
                    'lit. Wind does not kill it. Rain does not kill it. The waterfall directly in '
                    'front of it does not kill it. It is just there, burning quietly behind the '
                    'water, in a forest in New York, and has been for longer than recorded history. '
                    'Eternal Flame Falls. You can visit it. Take a lighter just in case.'},
    {'topic': 'history',
     'claim': 'In 1919 a storage tank in Boston exploded and released 2.3 million gallons of molasses '
              'through the streets at 35 miles per hour. The wave killed 21 people and injured 150. '
              'The neighbourhood smelled of molasses for decades.',
     'sources': ['https://www.smithsonianmag.com/arts-culture/bostons-great-molasses-flood-180956439/',
                 'https://www.bbc.com/news/magazine-38210577'],
     'image_hint': 'Boston 1919 historic street archive',
     'quirky_score': 3,
     'intensity': 'medium',
     'tone': 'shocking',
     'reel_title': 'The Great Molasses Flood',
     'reel_script': 'In January 1919 a storage tank in Boston collapsed and released two point three '
                    'million gallons of molasses through the streets at 35 miles per hour. The wave '
                    'was 15 feet tall. It demolished buildings, threw a freight train off its '
                    'tracks, and killed 21 people. One hundred and fifty were injured. Horses '
                    'drowned. The cleanup took weeks. Locals said the neighbourhood smelled of '
                    'molasses for decades. On hot days, some say it still does. Twenty-one people '
                    'died in a flood of molasses. This is not a metaphor.'},
    {'topic': 'history',
     'claim': 'Mary Mallon, known as Typhoid Mary, was an asymptomatic carrier who infected at least '
              '51 people without ever feeling ill herself. She was forcibly quarantined twice and '
              'spent her last 23 years imprisoned on a small island, never having been convicted of '
              'any crime.',
     'sources': ['https://www.bbc.com/news/health-19543353',
                 'https://www.smithsonianmag.com/history/the-rise-and-fall-of-typhoid-mary-180954325/'],
     'image_hint': 'vintage hospital ward early 1900s',
     'quirky_score': 3,
     'intensity': 'heavy',
     'tone': 'sober',
     'reel_title': 'Typhoid Mary',
     'reel_script': 'Mary Mallon infected at least 51 people with typhoid fever and spent the last '
                    '23 years of her life imprisoned on a small island, having never been convicted '
                    'of any crime. She was a healthy carrier. Her body produced typhoid bacteria '
                    'without making her ill. She cooked for families across New York. They got sick. '
                    'She moved on. Authorities eventually quarantined her by force. She was released, '
                    'promised not to cook, and went straight back to cooking. They quarantined her '
                    'again. She died on the island. Her only crime was existing.'},
    {'topic': 'history',
     'claim': 'In 1518 hundreds of people in Strasbourg began dancing uncontrollably and could not '
              'stop. Within weeks, roughly 400 people were dancing day and night. Many collapsed from '
              'exhaustion and some died. No one has ever explained why.',
     'sources': ['https://www.bbc.com/future/article/20180725-the-mysterious-dancing-plague-of-1518',
                 'https://www.smithsonianmag.com/smart-news/mystery-of-the-dancing-plague-of-1518-finally-solved-180960183/'],
     'image_hint': 'medieval town square Strasbourg Europe',
     'quirky_score': 3,
     'intensity': 'medium',
     'tone': 'shocking',
     'reel_title': 'The Dancing Plague of 1518',
     'reel_script': 'In July 1518 a woman in Strasbourg walked into the street and started dancing. '
                    'She danced for days. Within a week, thirty people had joined her. Within a '
                    'month, four hundred. All dancing, day and night, without music, without rest. '
                    'The city hired musicians to play along. It got worse. Feet bled. Hearts gave '
                    'out. Some died from exhaustion. No one had organised it. No one had started '
                    'it. It just happened and then, after a few weeks, it stopped. Five hundred '
                    'years later, no one has explained why. This actually happened.'},
    {'topic': 'history',
     'claim': 'When Albert Einstein died in 1955, the pathologist who performed his autopsy removed '
              'and kept his brain without family consent. Thomas Harvey stored it in jars in his '
              'basement for decades, secretly mailing slices to researchers around the world.',
     'sources': ['https://www.bbc.com/news/world-us-canada-22031220',
                 'https://www.smithsonianmag.com/science-nature/true-story-of-how-einsteins-brain-ended-up-in-a-jar-180955435/'],
     'image_hint': 'brain specimen laboratory jar formaldehyde vintage',
     'quirky_score': 3,
     'intensity': 'medium',
     'tone': 'shocking',
     'reel_title': "The Man Who Stole Einstein's Brain",
     'reel_script': 'When Einstein died in 1955, the pathologist removed his brain without asking '
                    'anyone. His name was Thomas Harvey. He kept it in a jar in his basement for '
                    'decades. He sliced it into 240 pieces. He drove it across America in a box '
                    'in the boot of his car. He mailed sections to researchers around the world. '
                    'He lost his medical licence and his marriage in the process. He never gave '
                    'it back. Einstein\'s brain is still in collections today, catalogued and '
                    'studied. Harvey\'s position was that he had done science a service. '
                    'The family disagreed.'},
    {'topic': 'history',
     'claim': 'Hiroo Onoda was a Japanese soldier stationed in the Philippines who kept fighting for '
              '29 years after the Second World War ended, because nobody had told him. He emerged from '
              'the jungle in 1974, still in uniform. His original commanding officer had to fly from '
              'Japan to personally order him to stand down.',
     'sources': ['https://www.bbc.com/news/world-asia-25542656',
                 'https://www.smithsonianmag.com/history/hiroo-onoda-soldier-kept-fighting-wwii-29-years-180953307/'],
     'image_hint': 'Philippine jungle dense tropical forest',
     'quirky_score': 3,
     'intensity': 'medium',
     'tone': 'shocking',
     'reel_title': "The Soldier Who Didn't Know It Was Over",
     'reel_script': 'Hiroo Onoda fought in the Philippine jungle until 1974 because no one had told '
                    'him the war ended in 1945. He conducted ambushes and skirmishes for 29 years. '
                    'He survived alone in the forest. Leaflets were dropped. He dismissed them as '
                    'enemy propaganda. Family members recorded messages. He did not believe them. '
                    'Eventually Japan flew his original commanding officer, now elderly, to the '
                    'jungle to personally order him to stand down. He came out in uniform, weapon '
                    'in hand, having done his duty. He was 52.'},
    {'topic': 'history',
     'claim': 'In 1966 a US Air Force bomber collided with a refuelling aircraft over Spain and '
              'accidentally dropped four nuclear bombs. None of them detonated. Two released '
              'conventional explosives on impact and scattered radioactive material across farmland '
              'near the village of Palomares.',
     'sources': ['https://www.bbc.com/news/world-europe-35314927',
                 'https://nsarchive2.gwu.edu/NSAEBB/NSAEBB481/'],
     'image_hint': 'Cold War military jet aircraft 1960s',
     'quirky_score': 3,
     'intensity': 'heavy',
     'tone': 'sober',
     'reel_title': 'The Day Four Nuclear Bombs Fell on Spain',
     'reel_script': 'In January 1966 an American B-52 carrying four hydrogen bombs collided with '
                    'a refuelling aircraft off the Spanish coast. The bomber broke apart. All four '
                    'bombs fell. None detonated. Two broke open on impact and scattered plutonium '
                    'across farmland near the village of Palomares. American crews removed one '
                    'thousand four hundred tonnes of contaminated soil and quietly took it to '
                    'South Carolina. The Spanish government was told to say the area was safe. '
                    'Locals are still being health-monitored today. The contamination is still '
                    'there. This was standard Cold War patrol.'},
    {'topic': 'space',
     'claim': 'The largest known black hole, TON 618, has a mass 66 billion times that of the Sun. Its '
              'event horizon is so large that our entire solar system would fit inside it with room to '
              'spare.',
     'sources': ['https://www.nasa.gov/mission_pages/chandra/news/black-hole-image-makes-history',
                 'https://www.britannica.com/science/black-hole'],
     'image_hint': 'black hole galaxy accretion disc space',
     'quirky_score': 3,
     'intensity': 'medium',
     'tone': 'shocking',
     'reel_title': 'The Biggest Thing in the Universe',
     'reel_script': 'TON 618 is a black hole with a mass sixty-six billion times that of the Sun. '
                    'Its event horizon is large enough to contain our entire solar system forty '
                    'times over. The Sun, all eight planets, Pluto, all of it, would fit inside '
                    'the event horizon with room to spare. Nothing that crosses it returns. Time '
                    'stops near it. It is the largest single object ever measured by humans. It '
                    'is eighteen billion light years away and currently feeding. We found it '
                    'by accident while studying something else.'},
    {'topic': 'space',
     'claim': 'The Boötes Void is a region of space roughly 330 million light years across that '
              'contains almost nothing. Where hundreds of thousands of galaxies should exist by any '
              'known model, there are fewer than 60. Nobody knows why it is empty.',
     'sources': ['https://www.britannica.com/science/Bootes-void',
                 'https://www.bbc.com/future/article/20221104-the-biggest-structure-in-the-universe'],
     'image_hint': 'deep space galaxy cluster stars void',
     'quirky_score': 3,
     'intensity': 'medium',
     'tone': 'shocking',
     'reel_title': 'The Great Nothing',
     'reel_script': 'There is a region of space three hundred and thirty million light years across '
                    'that contains almost nothing. The Boötes Void. By every model we have, it '
                    'should contain at least two thousand galaxies. It contains fewer than sixty. '
                    'No one knows why. Some scientists think it is a statistical coincidence. '
                    'Others think it is evidence of something our current understanding cannot '
                    'account for. It is the emptiest known place in the universe, and it is '
                    'genuinely enormous, and we have no satisfactory explanation for it.'},
    {'topic': 'space',
     'claim': "Jupiter's moon Europa hides a saltwater ocean beneath its frozen crust containing "
              "roughly twice as much water as all of Earth's oceans combined. Scientists consider it "
              'one of the most promising places in the solar system to look for life.',
     'sources': ['https://science.nasa.gov/jupiter/moons/europa/',
                 'https://www.britannica.com/place/Europa-moon'],
     'image_hint': 'Europa moon Jupiter icy surface NASA',
     'quirky_score': 3,
     'intensity': 'medium',
     'tone': 'shocking',
     'reel_title': 'The Ocean Hidden Beneath the Ice',
     'reel_script': 'Europa is a moon of Jupiter covered in ice. Beneath that ice is a saltwater '
                    'ocean containing twice as much water as all of Earth\'s oceans combined. '
                    'It is kept liquid by the gravitational pull of Jupiter, which generates '
                    'heat. Hydrothermal vents likely line the ocean floor. On Earth, every '
                    'hydrothermal vent is crowded with life. Scientists consider Europa the '
                    'most likely place in the solar system to find it elsewhere. We have not '
                    'looked yet. We are planning a mission. In the meantime, the ocean is '
                    'just there, in the dark.'},
    {'topic': 'space',
     'claim': 'In 1977 a radio telescope in Ohio detected a 72-second signal from deep space so '
              "unusual that the astronomer circled it and wrote 'Wow!' in the margin. The signal "
              'exactly matched what scientists expected an alien transmission to look like. It has '
              'never been detected again.',
     'sources': ['https://www.bbc.com/future/article/20220901-the-wow-signal-the-mysterious-radio-transmission',
                 'https://www.seti.org/wow-signal'],
     'image_hint': 'radio telescope dish night sky stars',
     'quirky_score': 3,
     'intensity': 'medium',
     'tone': 'shocking',
     'reel_title': 'Wow.',
     'reel_script': 'In 1977 a radio telescope in Ohio picked up a signal from space. It lasted '
                    '72 seconds, was extraordinarily loud, and matched almost exactly what '
                    'scientists expected an alien transmission to look like. The astronomer on '
                    'duty circled the numbers on the printout and wrote one word in the margin: '
                    'Wow. Nothing like it has been detected since. No natural explanation has '
                    'been confirmed. Nearly fifty years later the Wow signal remains the most '
                    'credible candidate for contact we have ever found. We looked for it again. '
                    'It was gone.'},
    {'topic': 'biology',
     'claim': 'Axolotls can regrow entire limbs, their spinal cord, heart muscle, and parts of their '
              'brain. They can also accept transplanted tissue from other axolotls, including eyes and '
              'brain sections, without rejection.',
     'sources': ['https://www.nationalgeographic.com/animals/amphibians/facts/axolotl',
                 'https://www.smithsonianmag.com/science-nature/how-axolotls-regrow-their-brains-180979203/'],
     'image_hint': 'axolotl pink salamander underwater Mexico',
     'quirky_score': 3,
     'intensity': 'light',
     'tone': 'shocking',
     'reel_title': 'The Animal That Regrows Its Brain',
     'reel_script': 'The axolotl can regrow its limbs, spinal cord, heart muscle, and parts of its '
                    'brain. Cut a leg off and it grows back with perfect bone, muscle, and nerves. '
                    'Damage the heart, it regrows. Take part of the brain, it regrows that too. '
                    'Transplant an eye from another axolotl, no rejection. No other vertebrate '
                    'does any of this. Scientists study it hoping to understand how to apply '
                    'the same principles to human medicine. The axolotl is nearly extinct in '
                    'the wild. We are studying it to learn how to rebuild ourselves while '
                    'failing to keep it alive.'},
    {'topic': 'biology',
     'claim': 'Vampire bats adopt orphan young from other mothers and regularly share blood meals with '
              'starving colony members. If a bat misses a feed, a neighbour it has previously groomed '
              'will regurgitate blood to keep it alive.',
     'sources': ['https://www.smithsonianmag.com/science-nature/vampire-bats-have-friends-180974271/',
                 'https://www.nationalgeographic.com/animals/mammals/facts/common-vampire-bat'],
     'image_hint': 'bat cave colony dark hanging',
     'quirky_score': 3,
     'intensity': 'light',
     'tone': 'shocking',
     'reel_title': "The Most Generous Animal You've Never Heard Of",
     'reel_script': 'Vampire bats die if they go two nights without feeding. Their bodies cannot '
                    'store the energy. When one bat misses a meal, another bat will regurgitate '
                    'blood into its mouth. Not for its young. For a friend. They track who has '
                    'fed them and pay it back later. They adopt orphaned young from other mothers. '
                    'They form long-term bonds. The animal we chose to represent evil and death '
                    'turns out to run a sophisticated mutual aid system in the dark. We got '
                    'that one quite wrong.'},
    {'topic': 'biology',
     'claim': 'Glass frogs have transparent skin on their underside. You can watch their heart '
              'beating, their digestive system working, and see developing eggs inside a pregnant '
              'female. They are living windows into a body.',
     'sources': ['https://www.nationalgeographic.com/animals/amphibians/facts/glass-frog',
                 'https://www.bbc.com/news/science-environment-63668019'],
     'image_hint': 'glass frog transparent leaf tropical rainforest',
     'quirky_score': 3,
     'intensity': 'light',
     'tone': 'shocking',
     'reel_title': 'You Can See Right Through Them',
     'reel_script': 'The glass frog has a transparent underside. You can watch its heart beating. '
                    'You can see the blood moving through the chambers. You can see its stomach '
                    'digesting. In a pregnant female, you can count the developing eggs. It is '
                    'a small frog you can see directly through, sitting on a leaf in Central '
                    'America, entirely visible to you and entirely invisible to predators, who '
                    'look through it and see the leaf. Evolution produced an animal that is '
                    'simultaneously a window and a camouflage mechanism. Both at once.'},
    {'topic': 'biology',
     'claim': 'Migratory birds navigate partly via quantum mechanics. Proteins in their eyes react to '
              "Earth's magnetic field through a quantum entanglement effect, allowing the birds to "
              'literally perceive the magnetic field as a visual overlay on their surroundings.',
     'sources': ['https://www.bbc.com/future/article/20210714-the-birds-that-can-see-earths-magnetic-field',
                 'https://www.nature.com/articles/nature08897'],
     'image_hint': 'birds flock migration sky golden light',
     'quirky_score': 3,
     'intensity': 'light',
     'tone': 'shocking',
     'reel_title': 'Birds Can See What We Cannot',
     'reel_script': 'Migratory birds navigate partly through quantum mechanics. Proteins in their '
                    'eyes react to Earth\'s magnetic field via quantum entanglement, allowing them '
                    'to perceive the magnetic field as a visual overlay. They can literally see '
                    'which direction is north. We have the same proteins. We appear to have lost '
                    'the ability to use them at some point in our evolutionary history. Birds '
                    'are using a mechanism we cannot fully replicate in a laboratory to find '
                    'their way across continents in the dark. They do this every year without '
                    'particularly thinking about it.'},
    {'topic': 'ocean',
     'claim': 'The barreleye fish has a completely transparent head filled with fluid. What appears to '
              'be its eyes from the front are actually olfactory organs. Its real eyes are the glowing '
              'green tubes inside its skull, pointing straight upward.',
     'sources': ['https://www.mbari.org/creatures/barreleye/',
                 'https://www.nationalgeographic.com/animals/fish/facts/barreleye-fish'],
     'image_hint': 'barreleye fish deep sea transparent green eyes',
     'quirky_score': 3,
     'intensity': 'medium',
     'tone': 'shocking',
     'reel_title': 'The Fish With a See-Through Head',
     'reel_script': 'The barreleye fish has a completely transparent head. Inside it, two glowing '
                    'green tubes point straight upward. Those are its eyes. The dark spots on the '
                    'front that look like eyes are its nostrils. Scientists first filmed it alive '
                    'in 2004. Before that, the head always collapsed when brought to the surface '
                    'and we had no idea what it actually looked like. We assumed wrong. It has '
                    'a fluid-filled transparent skull containing rotating tubular eyes. The ocean '
                    'spent millions of years producing this and did not tell anyone.'},
    {'topic': 'ocean',
     'claim': 'The mimic octopus can impersonate at least 15 different marine species, including the '
              'lionfish, flatfish, and banded sea snake. It actively selects which animal to '
              'impersonate based on which predator is nearby.',
     'sources': ['https://www.smithsonianmag.com/science-nature/the-incredible-mimic-octopus-180949698/',
                 'https://www.nationalgeographic.com/animals/invertebrates/facts/mimic-octopus'],
     'image_hint': 'mimic octopus coral reef underwater Indonesia',
     'quirky_score': 3,
     'intensity': 'medium',
     'tone': 'shocking',
     'reel_title': 'The Master of Disguise',
     'reel_script': 'The mimic octopus impersonates other animals. It can reshape itself into a '
                    'venomous lionfish, flatten out into a flounder, or trail two arms to become '
                    'a banded sea snake. At least fifteen different species. More importantly, '
                    'it selects which animal to imitate based on which predator is nearby. Faced '
                    'with a damselfish, it becomes the sea snake that eats damselfish. It is '
                    'the only known animal that actively chooses its disguise in response to '
                    'a specific threat. It is improvising. A small octopus, lying to its '
                    'predators in real time.'},
    {'topic': 'ocean',
     'claim': 'Giant oarfish can reach 11 metres in length, making them the longest bony fish on '
              'Earth. They swim vertically in the deep ocean and are almost never seen alive. They are '
              'thought to be the origin of centuries of sea serpent myths.',
     'sources': ['https://www.nhm.ac.uk/discover/giant-oarfish-facts.html',
                 'https://www.nationalgeographic.com/animals/fish/facts/oarfish'],
     'image_hint': 'oarfish long silver fish ocean deep sea',
     'quirky_score': 3,
     'intensity': 'medium',
     'tone': 'shocking',
     'reel_title': 'The Real Sea Serpent',
     'reel_script': 'The giant oarfish grows up to eleven metres long, swims vertically with its '
                    'head pointing up and body trailing below it like a silver ribbon, and is '
                    'almost never seen alive. It is the longest bony fish on Earth. When they '
                    'wash up on beaches, people photograph them in shock because they look '
                    'exactly like sea serpents. Because they are sea serpents. The creatures '
                    'in centuries of sailor stories were real. They were just deep enough that '
                    'we could not find them. They were always down there.'},
    {'topic': 'earth',
     'claim': 'In Turkmenistan there is a 30-metre wide crater that has been on fire since 1971. '
              'Soviet engineers accidentally ignited escaping gas while drilling and expected it to '
              'burn out in weeks. It has never stopped. Locals call it the Door to Hell.',
     'sources': ['https://www.bbc.com/future/article/20190501-the-history-of-the-door-to-hell',
                 'https://www.atlasobscura.com/places/darvaza-gas-crater'],
     'image_hint': 'Darvaza gas crater fire night Turkmenistan',
     'quirky_score': 3,
     'intensity': 'medium',
     'tone': 'shocking',
     'reel_title': 'The Door to Hell',
     'reel_script': 'In 1971 Soviet engineers drilled for gas in the Turkmenistan desert, the ground '
                    'collapsed, and a crater opened with gas escaping. They lit it on fire, '
                    'expecting it to burn out within weeks. It has been burning continuously for '
                    'over fifty years. Thirty metres wide, deep enough to swallow a building, '
                    'visible from miles away at night. Local people call it the Door to Hell. '
                    'No one has turned it off because no one is sure how, and at this point it '
                    'has become a tourist attraction. Which feels appropriate.'},
    {'topic': 'earth',
     'claim': 'In 1958 an earthquake in Alaska triggered a landslide that generated a wave 524 metres '
              'high in Lituya Bay. Taller than the Empire State Building. Two people happened to be '
              'anchored in the bay and surfed the wave to safety.',
     'sources': ['https://www.usgs.gov/news/lituya-bay-alaska-mega-tsunami',
                 'https://www.bbc.com/news/science-environment-14229564'],
     'image_hint': 'Alaska coast fjord dramatic mountains sea',
     'quirky_score': 3,
     'intensity': 'heavy',
     'tone': 'shocking',
     'reel_title': 'The Tallest Wave Ever Recorded',
     'reel_script': 'In July 1958 an earthquake in Alaska sent ninety million tonnes of rock into '
                    'Lituya Bay. The wave that resulted was five hundred and twenty-four metres '
                    'tall. Higher than the Empire State Building. The largest wave ever recorded. '
                    'It stripped the forest from the cliffs on both sides of the bay. Two fishing '
                    'boats were anchored there. Both survived. They rode the wave over the trees '
                    'and down the other side. When they told people what had happened, nobody '
                    'believed them. Then the photographs came out.'},
    {'topic': 'earth',
     'claim': 'Movile Cave in Romania has been completely sealed from the surface for approximately '
              '5.5 million years. Inside, 48 species of animals live in total darkness, breathing '
              'toxic air, feeding on chemosynthetic bacteria. None of them exist anywhere else on '
              'Earth.',
     'sources': ['https://www.bbc.com/future/article/20150522-the-cave-sealed-for-millions-of-years',
                 'https://www.nationalgeographic.com/travel/article/movile-cave'],
     'image_hint': 'dark cave underground water pool limestone',
     'quirky_score': 3,
     'intensity': 'medium',
     'tone': 'shocking',
     'reel_title': 'The World Sealed for Five Million Years',
     'reel_script': 'Movile Cave in Romania has been sealed from the surface for five and a half '
                    'million years. No sunlight reaches it. The air is toxic. And forty-eight '
                    'species of animals live inside, all blind, all pale, all found nowhere else '
                    'on Earth. They survive by eating bacteria that extract energy from the '
                    'toxic gases in the rock rather than from sunlight. A complete, self-contained '
                    'ecosystem, operating in total darkness for longer than the human species '
                    'has existed. It was discovered in 1986. Scientists were not expecting it.'},
    {'topic': 'earth',
     'claim': 'In the Sahara Desert there is a geological formation 50 kilometres across that looks '
              'like a giant eye when seen from space. Called the Richat Structure, or Eye of the '
              'Sahara, it was formed by an ancient volcanic dome that slowly collapsed over millions '
              'of years.',
     'sources': ['https://earthobservatory.nasa.gov/images/36356/richat-structure',
                 'https://www.britannica.com/place/Richat-Structure'],
     'image_hint': 'Sahara desert aerial satellite Eye Richat Structure',
     'quirky_score': 3,
     'intensity': 'light',
     'tone': 'shocking',
     'reel_title': 'The Eye of the Sahara',
     'reel_script': 'There is a fifty-kilometre circle of concentric rock rings in the middle of the '
                    'Sahara that looks, from space, exactly like a giant eye staring upward. It '
                    'can only be properly seen from orbit. Astronauts photographed it in the '
                    '1960s and had no idea what it was. The answer turned out to be geological: '
                    'a dome that collapsed over millions of years with different rock layers '
                    'eroding at different speeds. One of the most visually striking formations '
                    'on the planet, sitting in a desert, visible only from space, unnoticed '
                    'for most of human history.'},
    {'topic': 'earth',
     'claim': 'Australia drifts north at roughly 7 centimetres a year. It has moved so far that GPS '
              'coordinates used in the 1990s are now off by more than 1.5 metres.',
     'sources': ['https://www.bbc.com/news/world-australia-38650191',
                 'https://www.geoscience.gov.au/news/australias-position-latitude-and-longitude-has-shifted-more-you-might-think'],
     'image_hint': 'Australia aerial tectonic plate geology drift',
     'quirky_score': 3,
     'intensity': 'light',
     'tone': 'shocking',
     'reel_title': 'Australia Is Moving. Literally.',
     'reel_script': 'Australia drifts north at seven centimetres per year. The GPS coordinates '
                    'from the 1990s are now off by more than one and a half metres. In aviation '
                    'and shipping, one and a half metres matters considerably. Australia had to '
                    'officially update its own coordinates. The country moved far enough that '
                    'it had to reposition itself on paper. Every continent is doing this. The '
                    'ground is not fixed. It never was. We just did not have accurate enough '
                    'instruments to notice until recently.'},
    {'topic': 'earth',
     'claim': 'Lake Hillier in Western Australia stays bright bubblegum pink all year round. The '
              'colour comes from a combination of salt-loving algae and bacteria that thrive in its '
              'extreme salinity.',
     'sources': ['https://www.nationalgeographic.com/travel/article/lake-hillier-pink-lake-australia',
                 'https://www.bbc.com/travel/article/20140130-australias-pink-lake-explained'],
     'image_hint': 'pink lake aerial',
     'quirky_score': 3,
     'intensity': 'light',
     'tone': 'shocking',
     'reel_title': 'The Lake That Stays Pink',
     'reel_script': 'Lake Hillier in Western Australia is permanently bubblegum pink. Not at sunset. '
                    'Not from a certain angle. The water itself is pink. Fill a glass from it and '
                    'the glass stays pink. The lake is ten times saltier than the ocean and is '
                    'filled with salt-loving algae and bacteria that produce the colour. Most '
                    'things cannot survive in it. These organisms thrive in it and turn the '
                    'entire thing flamingo pink. It has been this colour for as long as anyone '
                    'has looked. Nature did something completely absurd and it has been there '
                    'the whole time.'},
    {'topic': 'earth',
     'claim': "Earth's gravity is measurably weaker over Hudson Bay in Canada. A massive ice sheet "
              'that sat there during the last Ice Age compressed the crust so much that the rock is '
              'still slowly rebounding, leaving less mass under that region.',
     'sources': ['https://www.nasa.gov/feature/goddard/2016/nasa-grace-data-explain-hudson-bay-gravity-low',
                 'https://www.bbc.com/future/article/20160126-why-does-gravity-vary-across-earth'],
     'image_hint': 'Earth gravity anomaly satellite aerial Hudson Bay',
     'quirky_score': 3,
     'intensity': 'medium',
     'tone': 'shocking',
     'reel_title': 'The Place Where Gravity Is Weaker',
     'reel_script': 'Gravity is measurably weaker over Hudson Bay in Canada. If you stood there '
                    'you would weigh very slightly less than anywhere else on Earth. The reason: '
                    'twenty thousand years ago a kilometre-thick ice sheet sat on that land and '
                    'compressed the crust. The ice melted. The crust is still slowly rising back. '
                    'There is less rock mass under that region than there should be. Less mass '
                    'means less gravity. The planet is still physically recovering from the last '
                    'Ice Age and you can detect the recovery from orbit. The wound in the crust '
                    'is measurable.'},
    {'topic': 'earth',
     'claim': 'Lake Nyos in Cameroon released a vast cloud of carbon dioxide in 1986, silently '
              'suffocating 1,746 people, 3,500 livestock, and every living thing within 25 kilometres. '
              'No one heard anything. No one had any warning.',
     'sources': ['https://www.bbc.com/future/article/20160706-the-deadly-lake-that-burps-poison',
                 'https://www.britannica.com/place/Lake-Nyos'],
     'image_hint': 'crater lake at dawn',
     'quirky_score': 3,
     'intensity': 'heavy',
     'tone': 'sober',
     'reel_title': 'The Lake That Exhaled Death',
     'reel_script': 'On the night of August 21st 1986, Lake Nyos in Cameroon released one million '
                    'tonnes of carbon dioxide in a single silent eruption. The cloud rolled down '
                    'the hillside. Heavier than air, it flowed into every village and every home. '
                    'One thousand seven hundred and forty-six people died in their sleep. Three '
                    'thousand five hundred livestock. Every bird. Every insect. No sound. No '
                    'warning. Survivors woke next to everyone they knew, already dead. The lake '
                    'is still there. Magma is still saturating the water beneath it. It is '
                    'still filling.'},
    {'topic': 'earth',
     'claim': 'Earth has a small companion called Kamoʻoalewa (2016 HO3) that has been orbiting near '
              'our planet for at least a century. It is not a moon. It loops around Earth in a complex '
              'spiral, neither captured nor fully free.',
     'sources': ['https://www.nasa.gov/solar-system/asteroid-2016-ho3-earths-quasi-satellite/',
                 'https://www.bbc.com/news/science-environment-38476281'],
     'image_hint': 'small asteroid in space',
     'quirky_score': 3,
     'intensity': 'light',
     'tone': 'shocking',
     'reel_title': "Earth's Hidden Second Companion",
     'reel_script': 'Earth has a small companion asteroid called Kamoʻoalewa that has been orbiting '
                    'near us for at least a century. It is not a moon. Gravity has not fully captured '
                    'it but it is not free either. It traces a complex looping spiral around Earth '
                    'year after year. Scientists analysed its composition and found it matches '
                    'the surface of our Moon, not a typical asteroid. Kamoʻoalewa may be a '
                    'fragment knocked off the Moon by an ancient impact, drifting alongside us '
                    'ever since. We only discovered it in 2016.'},
    {'topic': 'earth',
     'claim': 'Earth went through what scientists call the Boring Billion. For almost a billion years, '
              'from roughly 1.8 to 0.8 billion years ago, the planet barely changed. Oxygen levels '
              'stalled. Evolution nearly froze. Then, without clear reason, everything exploded into '
              'complexity.',
     'sources': ['https://www.bbc.com/future/article/20220309-the-mystery-of-earths-boring-billion-years',
                 'https://www.smithsonianmag.com/science-nature/earths-boring-billion-years-180980214/'],
     'image_hint': 'ancient rock strata geological sediment fossil layers',
     'quirky_score': 3,
     'intensity': 'medium',
     'tone': 'shocking',
     'reel_title': 'The Billion Years Nothing Happened',
     'reel_script': 'For almost a billion years, from roughly 1.8 to 0.8 billion years ago, '
                    'nothing happened on Earth. No new body plans. No meaningful evolution. '
                    'Oxygen levels flatlined. Scientists call it the Boring Billion. We do not '
                    'fully understand why evolution stalled. We do not fully understand what '
                    'ended it. Around 800 million years ago something triggered a cascade and '
                    'complex life exploded into existence. A billion years of complete stagnation '
                    'followed by everything. The planet was, for reasons we cannot explain, '
                    'waiting. Then it stopped waiting.'},
    {'topic': 'earth',
     'claim': 'Zealandia, a continent mostly hidden beneath the South Pacific Ocean, is 94% submerged '
              'and four times the size of Greenland. Scientists only formally recognised it as a '
              'continent in 2017.',
     'sources': ['https://www.bbc.com/news/science-environment-39013094',
                 'https://www.nationalgeographic.com/science/article/new-zealands-zealandia-continent'],
     'image_hint': 'ocean bathymetry map',
     'quirky_score': 3,
     'intensity': 'light',
     'tone': 'shocking',
     'reel_title': 'The Continent We Nearly Missed',
     'reel_script': 'There is a continent called Zealandia that is ninety-four percent underwater. '
                    'It is four times the size of Greenland. It has mountains, tectonic activity, '
                    'and all the geological features of a continent. The only part above sea level '
                    'is New Zealand. Scientists formally recognised it as a continent in 2017. '
                    'It was sitting there the entire time. We mapped the surface of Mars before '
                    'we properly understood what was beneath the ocean we have been sailing '
                    'across for millennia. The count is eight continents now. Adjust accordingly.'},
    {'topic': 'earth',
     'claim': 'The Salar de Uyuni salt flat in Bolivia is so large and so perfectly flat that it '
              'becomes a near-perfect mirror when covered by a thin layer of water. It is used to '
              'calibrate satellites in orbit.',
     'sources': ['https://www.nationalgeographic.com/travel/article/salar-de-uyuni',
                 'https://earthobservatory.nasa.gov/images/147516/the-worlds-largest-salt-flat'],
     'image_hint': 'salt flat reflection sky',
     'quirky_score': 3,
     'intensity': 'light',
     'tone': 'shocking',
     'reel_title': 'The Mirror at the Top of the World',
     'reel_script': 'The Salar de Uyuni in Bolivia is ten thousand square kilometres of dried salt '
                    'at thirty-six hundred metres above sea level. When it rains, a thin film of '
                    'water turns the entire surface into a perfect mirror. The sky reflects. The '
                    'horizon disappears. You cannot tell where the ground ends and the sky begins. '
                    'It is so flat and so large that space agencies use it to calibrate their '
                    'satellites. The most precise instruments we have built check themselves '
                    'against an ancient lake bed in Bolivia. It works because the lake bed '
                    'is flatter than our instruments.'},
    {'topic': 'ocean',
     'claim': 'The colossal squid has the largest eyes of any known animal. They can reach 27 '
              'centimetres across, about the size of a football, and are thought to help detect the '
              'bioluminescent flashes of predators like sperm whales in the deep dark ocean.',
     'sources': ['https://www.nhm.ac.uk/discover/colossal-squid.html',
                 'https://www.smithsonianmag.com/science-nature/the-giant-squid-the-colossal-squid-180949873/'],
     'image_hint': 'giant squid eye',
     'quirky_score': 3,
     'intensity': 'light',
     'tone': 'shocking',
     'reel_title': 'The Biggest Eyes on Earth',
     'reel_script': 'The colossal squid has eyes twenty-seven centimetres across. The size of a '
                    'football. Each one. They are the largest eyes of any known animal. The reason '
                    'is that at a thousand metres down there is almost no light, but sperm whales '
                    'hunt there and when they move fast, bioluminescent plankton lights up around '
                    'them. The squid can detect that faint glow from a hundred and twenty metres '
                    'away. It evolved football-sized eyes to see its predator by the light it '
                    'disturbs. The colossal squid weighs over four hundred kilograms and we have '
                    'only ever seen a handful alive.'},
    {'topic': 'ocean',
     'claim': 'In 1997 NOAA hydrophones picked up a powerful underwater sound called the Bloop. It was '
              'extraordinarily loud, detected by sensors thousands of kilometres apart. Scientists '
              'later attributed it to an icequake, but for years it was unexplained.',
     'sources': ['https://oceanservice.noaa.gov/facts/bloop.html',
                 'https://www.bbc.com/future/article/20160218-the-mystery-of-the-bloop-sound-from-the-deep-sea'],
     'image_hint': 'deep ocean sonar',
     'quirky_score': 3,
     'intensity': 'medium',
     'tone': 'shocking',
     'reel_title': 'The Sound From the Deep',
     'reel_script': 'In 1997 NOAA hydrophones picked up a sound from the Pacific loud enough to be '
                    'detected by sensors thousands of kilometres apart. The profile matched no '
                    'known geological event and no known animal. Scientists called it the Bloop. '
                    'For years there was no explanation. The location happened to be sixteen '
                    'hundred kilometres from where Lovecraft placed R\'lyeh, which was not '
                    'helpful. We now believe it was an icequake, a glacier fracturing under its '
                    'own weight. But for several years the ocean had made a noise louder than '
                    'anything we had heard, and we had no idea what caused it.'},
    {'topic': 'ocean',
     'claim': 'Below 200 metres the Black Sea is anoxic. No oxygen reaches those depths, so organic '
              'material cannot fully decompose. Ancient shipwrecks discovered there are preserved '
              'almost perfectly, with masts, figureheads, and ropes still intact after thousands of '
              'years.',
     'sources': ['https://www.nationalgeographic.com/history/article/black-sea-ancient-shipwrecks',
                 'https://www.bbc.com/news/world-europe-41717747'],
     'image_hint': 'preserved ancient shipwreck',
     'quirky_score': 3,
     'intensity': 'medium',
     'tone': 'shocking',
     'reel_title': 'The Ships That Never Rotted',
     'reel_script': 'The Black Sea below two hundred metres contains almost no oxygen. Bacteria '
                    'cannot survive. Wood does not rot. Ships that sank there thousands of years '
                    'ago are still sitting on the seabed, intact. In 2017 a robot submarine '
                    'found a Greek vessel over two thousand four hundred years old with the mast '
                    'standing, the rudder in place, and the ropes still hanging. It is the '
                    'best-preserved ancient ship ever discovered. There are dozens more around it. '
                    'An entire archive of maritime history, preserved by accident in a dead sea, '
                    'waiting for someone to look.'},
    {'topic': 'ocean',
     'claim': 'Greenland shark can live for at least 270 years, making them the longest-lived '
              'vertebrate on Earth. They are not sexually mature until they are around 150 years old. '
              'Some alive today may have been born in the 1700s.',
     'sources': ['https://www.smithsonianmag.com/smart-news/greenland-sharks-can-live-for-hundreds-of-years-180960101/',
                 'https://www.bbc.com/earth/story/20160811-greenland-sharks-live-for-400-years'],
     'image_hint': 'Greenland shark deep water',
     'quirky_score': 3,
     'intensity': 'medium',
     'tone': 'shocking',
     'reel_title': 'The Shark Born Before America',
     'reel_script': 'Greenland sharks can live for at least two hundred and seventy years. Some '
                    'possibly four hundred. They grow barely a centimetre per year. They do not '
                    'reach sexual maturity until they are roughly a hundred and fifty years old. '
                    'There are Greenland sharks swimming in the North Atlantic right now that '
                    'were alive when the American Revolution happened. They are the oldest '
                    'vertebrates ever recorded. They saw the Industrial Revolution. Both World '
                    'Wars. Everything. Slowly moving under the ice, largely unbothered.'},
    {'topic': 'ocean',
     'claim': 'Horseshoe crabs predate the dinosaurs by hundreds of millions of years. Their blood is '
              'bright blue and contains a compound called LAL that is so effective at detecting '
              'bacterial contamination that it is used to test every injectable drug and vaccine given '
              'to humans.',
     'sources': ['https://www.smithsonianmag.com/science-nature/the-blood-of-the-crab-3279007/',
                 'https://www.nhm.ac.uk/discover/horseshoe-crabs-living-fossils.html'],
     'image_hint': 'horseshoe crab beach',
     'quirky_score': 3,
     'intensity': 'medium',
     'tone': 'shocking',
     'reel_title': 'Your Vaccine Passed Through This Crab',
     'reel_script': 'Every injectable drug you have ever received was tested using the blood of a '
                    'horseshoe crab. Their blood is bright blue and contains a compound called '
                    'LAL that reacts instantly to bacterial contamination. No lab has replicated '
                    'it. The pharmaceutical industry harvests it to test every vaccine, every IV '
                    'drip, every injectable medication given to a human. The horseshoe crab '
                    'has not changed significantly in four hundred and fifty million years. '
                    'It predates the dinosaurs. It is currently keeping every hospital on '
                    'Earth safe. We have not found a better way.'},
    {'topic': 'ocean',
     'claim': 'The pistol shrimp snaps its claw shut so fast it creates a cavitation bubble that '
              'briefly reaches temperatures of around 8,000 Kelvin, almost as hot as the surface of '
              'the Sun. The resulting shockwave stuns or kills prey instantly.',
     'sources': ['https://www.smithsonianmag.com/science-nature/the-snapping-shrimp-the-loudest-animal-in-the-sea-180978621/',
                 'https://www.nhm.ac.uk/discover/pistol-shrimp-facts.html'],
     'image_hint': 'tropical pistol shrimp',
     'quirky_score': 3,
     'intensity': 'light',
     'tone': 'shocking',
     'reel_title': 'The Shrimp That Shoots Plasma',
     'reel_script': 'The pistol shrimp is the size of a finger with one comically oversized claw. '
                    'It snaps that claw faster than a bullet, creating a cavitation bubble that '
                    'for a fraction of a second reaches eight thousand Kelvin. The surface of '
                    'the Sun is about five thousand five hundred Kelvin. The bubble collapses '
                    'into a shockwave that kills prey instantly. No chase, no bite, just a snap. '
                    'During World War Two, submarines hid near pistol shrimp colonies because '
                    'the collective noise masked their own acoustic signature from enemy sonar. '
                    'A small shrimp was providing cover for warships.'},
    {'topic': 'ocean',
     'claim': 'In 2023 scientists filmed a snailfish 8,336 metres beneath the surface of the Pacific '
              'Ocean, the deepest fish ever observed. At that depth, the pressure is 800 times the '
              'pressure at sea level. The fish appeared completely calm.',
     'sources': ['https://www.bbc.com/news/science-environment-64864789',
                 'https://www.nhm.ac.uk/discover/snailfish-facts.html'],
     'image_hint': 'translucent deep sea fish',
     'quirky_score': 3,
     'intensity': 'light',
     'tone': 'shocking',
     'reel_title': 'The Deepest Fish Ever Found',
     'reel_script': 'In 2023 a camera descended to eight thousand three hundred and thirty-six '
                    'metres in the Izu-Ogasawara Trench. At that depth the pressure is eight '
                    'hundred times surface pressure. It is enough to crush tissue instantly. '
                    'There was a fish. A snailfish. Translucent, barely thirty centimetres '
                    'long, drifting calmly. The deepest vertebrate ever recorded, in permanent '
                    'darkness at crushing pressure in near-freezing water, apparently '
                    'unconcerned. The ocean keeps producing things we did not think were '
                    'possible. We have explored less than twenty percent of it.'},
    {'topic': 'ocean',
     'claim': 'The megalodon, the largest shark ever to live, could grow up to 18 metres long and had '
              'teeth the size of a human hand. It went extinct roughly 3.6 million years ago. Its bite '
              'force was estimated at 110,000 newtons, the strongest of any known animal.',
     'sources': ['https://www.smithsonianmag.com/science-nature/megalodon-how-big-was-it-180979650/',
                 'https://www.nhm.ac.uk/discover/megalodon-facts.html'],
     'image_hint': 'fossil megalodon tooth',
     'quirky_score': 3,
     'intensity': 'medium',
     'tone': 'shocking',
     'reel_title': 'The Shark That Makes Great Whites Look Small',
     'reel_script': 'The megalodon was eighteen metres long, three times the length of a great white, '
                    'with teeth the size of a human hand and a bite force of a hundred and ten '
                    'thousand newtons, the strongest of any measured animal. It hunted whales. '
                    'Fossil whale bones carry megalodon bite marks going straight through them. '
                    'It went extinct three point six million years ago and nobody is entirely '
                    'sure why. The great white shark is its closest living relative and fills '
                    'the ecological gap it left. When people say great whites are terrifying, '
                    'they are correct, but they are also missing context.'},
    {'topic': 'ocean',
     'claim': 'Leatherback sea turtles regularly dive past 1,000 metres in search of jellyfish. They '
              'are the deepest-diving reptiles on Earth and can travel over 10,000 kilometres in a '
              'single migration across the Pacific Ocean.',
     'sources': ['https://www.nationalgeographic.com/animals/reptiles/facts/leatherback-sea-turtle',
                 'https://oceanservice.noaa.gov/education/tutorial_currents/media/supp_cur09c.html'],
     'image_hint': 'leatherback sea turtle',
     'quirky_score': 3,
     'intensity': 'light',
     'tone': 'shocking',
     'reel_title': 'The Turtle That Dives a Kilometre Deep',
     'reel_script': 'The leatherback sea turtle weighs up to nine hundred kilograms, dives past a '
                    'thousand metres in search of jellyfish, regulates its own body temperature '
                    'in freezing water, and crosses the entire Pacific Ocean during migration. '
                    'Over ten thousand kilometres, navigating by the Earth\'s magnetic field, '
                    'without stopping. The leatherback lineage is a hundred million years old. '
                    'It survived whatever killed the dinosaurs. It is currently endangered '
                    'primarily due to plastic bags, which resemble jellyfish from below and '
                    'which it cannot distinguish. We are losing them to our rubbish.'},
    {'topic': 'biology',
     'claim': 'Captive octopuses have been observed recognising and treating individual humans '
              'differently. In studies, animals actively sprayed water at disliked handlers and were '
              'visibly friendlier toward others, demonstrating long-term individual memory for human '
              'faces.',
     'sources': ['https://www.smithsonianmag.com/science-nature/the-mind-of-an-octopus-180949735/',
                 'https://www.nhm.ac.uk/discover/octopus-facts.html'],
     'image_hint': 'octopus eye contact',
     'quirky_score': 3,
     'intensity': 'light',
     'tone': 'shocking',
     'reel_title': 'The Animal That Holds a Grudge',
     'reel_script': 'A research facility in Seattle ran a simple experiment. One staff member fed the '
                    'octopuses daily. Another poked them with a stick. After a few weeks, the '
                    'octopuses began directing their water jets at the poker specifically. Not at '
                    'everyone. At that person. They also reached toward the feeder more often. '
                    'Deliberate. Targeted. Personal. These animals share no common ancestor with you '
                    'for 750 million years. No neocortex. No shared evolutionary context. They still '
                    'remembered who you were, tracked you across days, and arrived at a conclusion. '
                    'The polite term is individual recognition. The accurate term is grudge.'},
    {'topic': 'science',
     'claim': 'Some people with damage to the primary visual cortex insist they see nothing, yet can '
              'guess the location or orientation of objects on a screen far better than chance. This '
              'dissociation between visual processing and conscious sight is called blindsight.',
     'sources': ['https://plato.stanford.edu/entries/blindsight/',
                 'https://www.britannica.com/science/blindsight'],
     'image_hint': 'brain MRI neuroscience laboratory vision',
     'quirky_score': 3,
     'intensity': 'medium',
     'tone': 'shocking',
     'reel_title': 'The Eyes That Deny They See',
     'reel_script': 'Damage the primary visual cortex and the patient reports complete blindness in '
                    'that zone. Nothing. Black. Researchers flash a shape into it and ask them to '
                    'guess its location. The patient objects. They saw nothing. Guess anyway. The '
                    'guesses land far above chance. Point at it. The hand finds it. The lesion wiped '
                    'out conscious sight but left other pathways intact, ones that still carry '
                    'position, movement, and emotion. The inner voice insists on darkness. The hand '
                    'knows better. Researchers call this blindsight. Seeing and processing visual '
                    'information are not the same thing, and only one requires your permission.'},
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
