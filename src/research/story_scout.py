"""Story scout: Reddit-first candidate discovery + scoring.

This module runs before writing scripts/slides. It finds candidate stories,
scores them for interestingness and novelty, and returns ranked options for
reel/list/fact modes.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import requests

from src.core.paths import POSTED, REEL_DISCOVERY_STAGING

USER_AGENT = "factjot-story-scout/1.0 (@factjot)"
POSTED_LOG = POSTED
STAGING_REEL = REEL_DISCOVERY_STAGING
MAX_POST_BANK = 300

REDDIT_SOURCES = (
    ("todayilearned", 12000),
    ("interestingasfuck", 10000),
    ("Damnthatsinteresting", 10000),
    ("UnresolvedMysteries", 1500),
    ("history", 3000),
    ("science", 2000),
)

TOPIC_KEYWORDS = {
    "history": (
        "war", "battle", "empire", "king", "queen", "monarch", "dynasty",
        "revolution", "rebellion", "uprising", "invasion", "conquest",
        "ancient", "medieval", "century", "historic", "historical",
        "civilization", "kingdom", "throne", "crown", "castle", "army",
        "general", "soldier", "trial", "execution", "betrayal", "assassination",
        "treaty", "colony", "colonial", "slavery", "archaeology", "artifact",
        "ruins", "legend", "myth", "lost city", "royal", "succession",
        "plague", "famine", "explorer", "expedition", "old", "forgotten",
    ),
    "science": (
        "experiment", "research", "scientist", "discovery", "breakthrough",
        "laboratory", "lab", "theory", "hypothesis", "evidence", "data",
        "study", "physics", "chemistry", "biology", "genetics", "neuroscience",
        "brain", "mind", "memory", "consciousness", "particle", "quantum",
        "atom", "molecule", "radiation", "energy", "gravity", "evolution",
        "mutation", "vaccine", "disease", "medicine", "cure", "invention",
        "nobel", "mystery", "unsolved", "controversial", "secret experiment",
        "ethics", "accident", "failure", "success", "innovation",
    ),
    "space": (
        "nasa", "space", "planet", "galaxy", "moon", "mars", "venus",
        "jupiter", "saturn", "orbit", "asteroid", "comet", "meteor",
        "telescope", "astronaut", "rocket", "launch", "mission", "apollo",
        "spacecraft", "satellite", "space station", "black hole", "supernova",
        "nebula", "star", "exoplanet", "alien", "extraterrestrial", "ufo",
        "signal", "deep space", "cosmos", "universe", "gravity", "zero gravity",
        "space race", "landing", "crash", "lost mission", "mystery signal",
        "habitable", "terraforming", "eclipse", "solar system", "milky way",
    ),
    "ocean": (
        "ocean", "sea", "deep", "deep sea", "underwater", "marine", "fish",
        "shark", "whale", "dolphin", "octopus", "squid", "coral", "reef",
        "shipwreck", "submarine", "diver", "diving", "island", "tide",
        "wave", "storm", "tsunami", "current", "seafloor", "trench",
        "mariana trench", "hydrothermal vent", "sea monster", "kraken",
        "pirate", "sailor", "voyage", "expedition", "lost at sea",
        "treasure", "survival", "rescue", "fishing", "pollution", "plastic",
        "climate", "iceberg", "arctic", "antarctic", "mysterious creature",
    ),
    "earth": (
        "earth", "volcano", "eruption", "earthquake", "fault", "geology",
        "rock", "mineral", "fossil", "climate", "weather", "storm",
        "hurricane", "tornado", "flood", "drought", "desert", "forest",
        "rainforest", "mountain", "continent", "island", "cave", "glacier",
        "ice age", "landslide", "avalanche", "meteor impact", "crater",
        "plate tectonics", "natural disaster", "survival", "expedition",
        "lost world", "ancient earth", "prehistoric", "environment",
        "global warming", "climate change", "wildfire", "ecosystem",
        "terrain", "wilderness", "discovery", "hidden cave", "sinkhole",
    ),
    "biology": (
        "animal", "species", "evolution", "mutation", "adaptation",
        "predator", "prey", "mammal", "reptile", "bird", "insect",
        "fungus", "bacteria", "virus", "parasite", "plant", "forest",
        "jungle", "wildlife", "ecosystem", "extinction", "endangered",
        "dinosaur", "fossil", "genetics", "dna", "gene", "clone",
        "hybrid", "creature", "monster", "unknown species", "new species",
        "camouflage", "venom", "poison", "swarm", "colony", "queen insect",
        "migration", "survival", "natural selection", "symbiosis",
        "disease", "outbreak", "infection", "lab creature", "zoology",
    ),
    "technology": (
        "computer", "internet", "software", "hardware", "chip", "microchip",
        "robot", "robotics", "algorithm", "ai", "artificial intelligence",
        "machine learning", "neural network", "code", "programming",
        "hacker", "cyberattack", "cybersecurity", "encryption", "password",
        "database", "server", "network", "app", "startup", "silicon valley",
        "invention", "innovation", "automation", "drone", "android",
        "virtual reality", "augmented reality", "simulation", "metaverse",
        "surveillance", "privacy", "data", "glitch", "bug", "virus",
        "malware", "quantum computer", "nanotechnology", "biotech",
        "future", "dystopia", "cyborg", "machine", "device",
    ),
}

STORY_TRIGGER_KEYWORDS = (
    "mystery", "secret", "hidden", "lost", "forgotten", "dangerous",
    "survival", "betrayal", "escape", "rescue", "discovery", "forbidden",
    "ancient", "haunted", "cursed", "unknown", "unsolved", "conspiracy",
    "experiment gone wrong", "last survivor", "final mission", "race against time",
    "treasure", "legend", "myth", "disaster", "collapse", "invasion",
    "vanished", "strange signal", "impossible", "creature", "war", "trial",
    "expedition", "journey", "revenge", "sacrifice", "hero", "villain",
)

HOOK_TERMS = (
    "only", "largest", "smallest", "first", "last", "secret", "hidden", "never",
    "killed", "dead", "died", "exploded", "banned", "failed",
    "collapsed", "mystery",
    "unknown", "strangest", "weird", "impossible", "accident", "mistake",
)

VISUAL_TERMS = (
    "photo", "video", "image", "ship", "plane", "animal",
    "building", "city",
    "ocean", "space", "laboratory", "forest", "desert", "crater", "bridge",
)

REJECT_TERMS = (
    "opinion", "politics", "election", "celebrity drama",
    "rumour", "leak",
    "nsfw", "graphic", "gore",
)


@dataclass
class Candidate:
    source: str
    source_id: str
    title: str
    summary: str
    topic: str
    suggested_format: str
    weird_bit: str
    hook_score: float
    novelty_score: float
    visual_score: float
    confidence: float
    total_score: float


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _tokenise(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{4,}", text.lower()))


def _load_post_bank(limit: int = MAX_POST_BANK) -> list[str]:
    if not POSTED_LOG.exists():
        return []
    out: list[str] = []
    with POSTED_LOG.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            claim = _normalise(str(row.get("claim", "")))
            if claim:
                out.append(claim)
    return out[-limit:]


def _novelty(title: str, post_bank: list[str]) -> float:
    t = _tokenise(title)
    if not t or not post_bank:
        return 1.0
    max_overlap = 0.0
    for old in post_bank:
        o = _tokenise(old)
        if not o:
            continue
        overlap = len(t & o) / max(1, min(len(t), len(o)))
        if overlap > max_overlap:
            max_overlap = overlap
    return max(0.0, 1.0 - max_overlap)


def _infer_topic(text: str) -> str:
    text_l = text.lower()
    best_topic = "history"
    best_score = -1
    for topic, kws in TOPIC_KEYWORDS.items():
        score = sum(1 for kw in kws if kw in text_l)
        if score > best_score:
            best_score = score
            best_topic = topic
    return best_topic


def _extract_weird_bit(title: str) -> str:
    title = _normalise(title)
    parts = re.split(r"[:;\-]\s+", title, maxsplit=1)
    return parts[-1] if parts else title


def _score_title(title: str, post_bank: list[str]) -> tuple[float, float, float, float, str]:
    tl = title.lower()
    if any(bad in tl for bad in REJECT_TERMS):
        return 0.0, 0.0, 0.0, 0.0, ""
    hook = 0.1
    hook += min(0.6, 0.1 * sum(1 for t in HOOK_TERMS if t in tl))
    hook += min(0.4, 0.08 * sum(1 for t in STORY_TRIGGER_KEYWORDS if t in tl))
    if re.search(r"\b\d{3,}\b", tl):
        hook += 0.1
    visual = 0.2 + min(0.6, 0.08 * sum(1 for t in VISUAL_TERMS if t in tl))
    novelty = _novelty(title, post_bank)
    confidence = min(1.0, 0.4 * hook + 0.3 * visual + 0.3 * novelty)
    weird_bit = _extract_weird_bit(title)
    return hook, novelty, visual, confidence, weird_bit


def _format_type_for_title(title: str) -> str:
    tl = title.lower()
    if re.search(r"\b(top|five|worst|best|largest|smallest|deadliest)\b", tl):
        return "list"
    return "reel"


def _fetch_reddit_top(subreddit: str, min_upvotes: int, limit: int) -> list[dict]:
    try:
        resp = requests.get(
            f"https://www.reddit.com/r/{subreddit}/top.json",
            params={"t": "month", "limit": limit},
            headers={"User-Agent": USER_AGENT},
            timeout=12,
        )
        resp.raise_for_status()
        rows = resp.json().get("data", {}).get("children", [])
    except Exception:
        return []
    out: list[dict] = []
    now = time.time()
    for row in rows:
        data = row.get("data", {})
        ups = int(data.get("ups", 0) or 0)
        if ups < min_upvotes:
            continue
        age_days = (now - float(data.get("created_utc", now))) / 86400
        if age_days < 2:
            continue
        title = _normalise(str(data.get("title", "")))
        if len(title) < 20:
            continue
        out.append({
            "source": f"reddit:r/{subreddit}",
            "source_id": str(data.get("id", "")),
            "title": title,
            "summary": _normalise(str(data.get("selftext", "")))[:500],
        })
    return out


def _load_staging_reel_candidates() -> list[dict]:
    if not STAGING_REEL.exists():
        return []
    out: list[dict] = []
    with STAGING_REEL.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            title = _normalise(str(row.get("reddit_title", "")))
            if not title:
                continue
            out.append({
            "source": f"staging:{row.get('subreddit', 'unknown')}",
                "source_id": str(row.get("reddit_id", "")),
                "title": title,
                "summary": _normalise(str(row.get("reel_script", "")))[:500],
                "topic": str(row.get("topic", "")),
            })
    return out


def build_story_candidates(limit_per_source: int = 20) -> list[Candidate]:
    post_bank = _load_post_bank()
    raw: list[dict] = []
    raw.extend(_load_staging_reel_candidates())
    for sub, min_upvotes in REDDIT_SOURCES:
        raw.extend(_fetch_reddit_top(sub, min_upvotes=min_upvotes, limit=limit_per_source))
    seen_titles: set[str] = set()
    candidates: list[Candidate] = []
    for row in raw:
        title = _normalise(row.get("title", ""))
        if not title:
            continue
        key = title.lower()
        if key in seen_titles:
            continue
        seen_titles.add(key)
        hook, novelty, visual, confidence, weird_bit = _score_title(title, post_bank)
        if confidence <= 0.0:
            continue
        topic = row.get("topic") or _infer_topic(f"{title} {row.get('summary', '')}")
        fmt = _format_type_for_title(title)
        total = 0.45 * hook + 0.35 * novelty + 0.20 * visual
        candidates.append(Candidate(
            source=row.get("source", "unknown"),
            source_id=row.get("source_id", ""),
            title=title,
            summary=row.get("summary", ""),
            topic=topic,
            suggested_format=fmt,
            weird_bit=weird_bit,
            hook_score=round(hook, 3),
            novelty_score=round(novelty, 3),
            visual_score=round(visual, 3),
            confidence=round(confidence, 3),
            total_score=round(total, 3),
        ))
    candidates.sort(key=lambda c: c.total_score, reverse=True)
    return candidates


def ranked_candidates_for_mode(mode: str, top_n: int = 12) -> list[dict]:
    """Return ranked candidates for autonomous mode."""
    cands = build_story_candidates()
    if mode in ("reel_morning", "reel_evening"):
        pool = [c for c in cands if c.suggested_format == "reel"]
    elif mode == "list":
        pool = [c for c in cands if c.suggested_format == "list"]
    else:  # fact mode
        pool = [c for c in cands if c.suggested_format in ("reel", "list")]
    return [asdict(c) for c in pool[:top_n]]


LIST_SUPERLATIVE_POOL = (
    "biggest",
    "smallest",
    "best",
    "worst",
    "deadliest",
    "safest",
    "strangest",
    "oldest",
    "newest",
    "fastest",
    "slowest",
    "most expensive",
    "least expensive",
    "most profitable",
    "least profitable",
    "most dangerous",
    "least survivable",
    "most bizarre",
    "most underrated",
    "most catastrophic",
    "scariest",
    "funniest",
    "most iconic",
    "most influential",
    "most disturbing",
)

_LIST_SUBJECT_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "over", "under",
    "after", "before", "when", "where", "while", "about", "than", "then", "they",
    "them", "their", "his", "her", "its", "your", "our", "was", "were", "are",
    "is", "been", "being", "have", "has", "had", "will", "would", "could", "should",
    "said", "says", "til", "todayilearned",
}

_TOPIC_LIST_HEADS = {
    "history": "historical events",
    "science": "scientific discoveries",
    "space": "space missions",
    "ocean": "ocean mysteries",
    "earth": "natural events",
    "biology": "biological discoveries",
    "technology": "technology failures",
}

_OPEN_SUBJECT_NOUNS = (
    "films",
    "movies",
    "songs",
    "albums",
    "games",
    "books",
    "characters",
    "creatures",
    "inventions",
    "experiments",
    "missions",
    "events",
    "disasters",
    "mysteries",
    "heists",
    "trials",
    "scandals",
    "survival stories",
)


def _subject_seed_from_row(title: str, weird_bit: str, topic: str) -> str:
    text = f"{title} {weird_bit}".lower()
    topic_words = TOPIC_KEYWORDS.get(topic, ())
    hits: list[str] = []
    for kw in topic_words:
        k = kw.lower().strip()
        if not k or len(k) < 4:
            continue
        if k in text and k not in hits:
            hits.append(k)
        if len(hits) >= 2:
            break
    if hits:
        # Prefer "adjective + noun" style when we can detect a concrete noun.
        noun = next((n for n in _OPEN_SUBJECT_NOUNS if n in text), "")
        if noun:
            return noun
        return _TOPIC_LIST_HEADS.get(topic, "historical events")

    noun = next((n for n in _OPEN_SUBJECT_NOUNS if n in text), "")
    if noun:
        return noun

    return _TOPIC_LIST_HEADS.get(topic, "historical events")


def build_list_reel_possibilities(
    mode: str,
    *,
    max_outcomes: int = 12,
) -> list[dict]:
    """Return dynamic top-5 list-reel concepts from live candidate titles.

    Output rows are lightweight idea seeds for script drafting.
    """
    top = ranked_candidates_for_mode(mode, top_n=30)
    if not top:
        return []

    seeds: list[tuple[str, str]] = []
    for row in top:
        topic = str(row.get("topic", "")).strip().lower() or "history"
        title = str(row.get("title", "")).strip()
        weird_bit = str(row.get("weird_bit", "")).strip()
        if not title:
            continue
        seeds.append((topic, _subject_seed_from_row(title, weird_bit, topic)))

    ideas: list[dict] = []
    used_titles: set[str] = set()
    for i, (topic, subject) in enumerate(seeds):
        outcome = LIST_SUPERLATIVE_POOL[i % len(LIST_SUPERLATIVE_POOL)]
        title = f"Top 5 {outcome} {subject}"
        key = title.lower()
        if key in used_titles:
            continue
        used_titles.add(key)
        ideas.append({
            "title": title,
            "topic": topic,
            "outcome": outcome,
            "subject": subject,
        })
        if len(ideas) >= max_outcomes:
            break
    return ideas
