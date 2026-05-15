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
    ("natureismetal", 2000),
    ("Astronomy", 2000),
    ("biology", 1500),
    ("geology", 1000),
    ("science", 2000),
    # Higher-signal sources: obscure, specific, lower viral-fact saturation.
    ("history", 1500),
    ("Paleontology", 500),
    ("Anthropology", 500),
    ("neuroanthropology", 300),
    ("lost_technology", 200),
)

# Sources whose content skews toward already-viral internet facts.
# Candidates from these sources receive a novelty penalty at scoring time
# because the agent's NOVELTY GATE explicitly rejects "well-worn internet
# staples" and TIL/IAF/DamnThats are the canonical feeds for those.
VIRAL_FACT_SOURCES: frozenset[str] = frozenset({
    "todayilearned",
    "interestingasfuck",
    "Damnthatsinteresting",
})

TOPIC_KEYWORDS = {
    "history": (
        "war", "battle", "empire", "monarch", "dynasty",
        "revolution", "rebellion", "invasion", "conquest",
        "medieval", "historic", "historical",
        "civilization", "kingdom", "assassination",
        "treaty", "colonial", "slavery", "archaeology", "artifact",
        "plague", "famine", "explorer",
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

_SHOCK_NUMBER_RE = re.compile(
    r"\b\d+\s+(?:people|men|women|children|soldiers|victims|survivors|nations|countries|years|days|hours|months)\b"
    r"|\bonly\s+\d+\b"
    r"|\b\d{4}\b"
)
_SHOCK_OUTCOME_VERBS = (
    "survived", "killed", "executed", "died", "banned", "forbidden",
    "discovered", "exposed",
)
_SHOCK_OUTCOME_VERB_RE = re.compile(
    r"\b(?:" + "|".join(_SHOCK_OUTCOME_VERBS) + r")\b"
)
_SHOCK_CONTRADICTION_SIGNALS = ("despite", " but ", "turned out", "actually", "never knew", "no one told")
_SHOCK_SCALE_SUPERLATIVES = ("world's only", "last ever", "first time", "never before", "only known")
_SHOCK_OUTCOME_NEAR_PROPER_RE = re.compile(
    r"\b[A-Z][a-z]{2,}\b.{0,40}\b(?:" + "|".join(_SHOCK_OUTCOME_VERBS) + r")\b"
    r"|\b(?:" + "|".join(_SHOCK_OUTCOME_VERBS) + r")\b.{0,40}\b[A-Z][a-z]{2,}\b"
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
    shock_score: float
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
    best_topic = "science"  # neutral fallback — avoids defaulting ambiguous titles to history
    best_score = 0          # require at least one keyword match to assign a topic
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


def _shock_score(title: str) -> float:
    """Heuristic shock signal for a Reddit title. Returns 0.0–1.0.

    Signals: specific numbers, outcome verbs, contradiction markers,
    scale superlatives, named person near a shocking outcome verb.
    """
    tl = title.lower()
    score = 0.0
    if _SHOCK_NUMBER_RE.search(tl):
        score += 0.15
    verb_hits = len(_SHOCK_OUTCOME_VERB_RE.findall(tl))
    score += min(0.24, 0.08 * verb_hits)
    if any(s in tl for s in _SHOCK_CONTRADICTION_SIGNALS):
        score += 0.10
    if any(s in tl for s in _SHOCK_SCALE_SUPERLATIVES):
        score += 0.12
    if _SHOCK_OUTCOME_NEAR_PROPER_RE.search(title):
        score += 0.10
    return min(1.0, score)


def _score_title(title: str, post_bank: list[str]) -> tuple[float, float, float, float, float, str]:
    tl = title.lower()
    if any(bad in tl for bad in REJECT_TERMS):
        return 0.0, 0.0, 0.0, 0.0, 0.0, ""
    hook = 0.1
    hook += min(0.6, 0.1 * sum(1 for t in HOOK_TERMS if t in tl))
    hook += min(0.4, 0.08 * sum(1 for t in STORY_TRIGGER_KEYWORDS if t in tl))
    if re.search(r"\b\d{3,}\b", tl):
        hook += 0.1
    visual = 0.2 + min(0.6, 0.08 * sum(1 for t in VISUAL_TERMS if t in tl))
    novelty = _novelty(title, post_bank)
    shock = _shock_score(title)
    confidence = min(1.0, 0.4 * hook + 0.3 * visual + 0.3 * novelty)
    weird_bit = _extract_weird_bit(title)
    return hook, novelty, visual, confidence, shock, weird_bit


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
        hook, novelty, visual, confidence, shock, weird_bit = _score_title(title, post_bank)
        if confidence <= 0.0:
            continue
        # Penalise candidates from viral-fact feeds. These subreddits surface
        # already-famous facts that the agent's NOVELTY GATE will reject anyway;
        # applying the penalty here lets higher-signal sources rank above them
        # instead of wasting the agent's quality-gate budget on easy rejects.
        raw_source = row.get("source", "")
        sub = raw_source.split("r/")[-1] if "r/" in raw_source else raw_source
        if sub in VIRAL_FACT_SOURCES:
            novelty = max(0.0, novelty - 0.25)
        topic = row.get("topic") or _infer_topic(f"{title} {row.get('summary', '')}")
        fmt = _format_type_for_title(title)
        total = 0.35 * hook + 0.25 * novelty + 0.15 * visual + 0.25 * shock
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
            shock_score=round(shock, 3),
            confidence=round(confidence, 3),
            total_score=round(total, 3),
        ))
    candidates.sort(key=lambda c: c.total_score, reverse=True)
    return candidates


def ranked_candidates_for_mode(mode: str, top_n: int = 12) -> list[dict]:
    """Return ranked candidates for autonomous mode with per-topic diversity cap.

    Prefix-matches mode names so any reel_* or list_* slot variant routes
    to the right pool. Enforces a per-topic cap so no single topic dominates
    the returned list regardless of raw score order.
    """
    cands = build_story_candidates()
    if mode.startswith("reel_"):
        pool = [c for c in cands if c.suggested_format == "reel"]
    elif mode == "list" or mode.startswith("list_"):
        pool = [c for c in cands if c.suggested_format == "list"]
    else:
        pool = [c for c in cands if c.suggested_format in ("reel", "list")]

    # Cap per-topic at 3 out of top_n so a single topic can never flood the list.
    per_topic_cap = max(1, top_n // 4)
    topic_counts: dict[str, int] = {}
    diverse: list = []
    for c in pool:
        t = c.topic or "unknown"
        if topic_counts.get(t, 0) < per_topic_cap:
            diverse.append(c)
            topic_counts[t] = topic_counts.get(t, 0) + 1
        if len(diverse) >= top_n:
            break

    return [asdict(c) for c in diverse]


# Allowed list superlatives. Phase D.2 (Q10 hybrid) banned every
# opinion-based superlative ("scariest", "best", "most underrated", etc.)
# because they cannot be defended without fabricated rank reasons. Only
# numeric / defensible superlatives survive, and every one MUST be
# paired with a stated criterion on the cover (see CRITERION_SHAPES).
LIST_SUPERLATIVE_POOL = (
    "biggest",
    "smallest",
    "deadliest",
    "oldest",
    "newest",
    "fastest",
    "slowest",
    "longest",
    "shortest",
    "tallest",
    "largest",
    "richest",
    "youngest",
    "most expensive",
    "least expensive",
    "most profitable",
    "least profitable",
    "costliest",
    "most catastrophic",
)


# Criterion shape per surviving superlative. The criterion is an
# explicit, defensible measurement that anchors the ranking on the
# cover ("Five engineering disasters by death toll"). Every list
# emitted by build_list_reel_possibilities() MUST carry one.
CRITERION_SHAPES: dict[str, str] = {
    "biggest":             "by total size or scale",
    "smallest":             "by recorded size",
    "deadliest":           "by confirmed death toll",
    "oldest":              "by date of origin",
    "newest":              "by date of completion",
    "fastest":             "by recorded speed",
    "slowest":             "by recorded duration",
    "longest":             "by recorded length",
    "shortest":            "by recorded length",
    "tallest":             "by recorded height",
    "largest":             "by total area or volume",
    "richest":             "by recorded net worth",
    "youngest":            "by date of birth or founding",
    "most expensive":      "by recorded cost in USD",
    "least expensive":     "by recorded cost in USD",
    "most profitable":     "by recorded net profit",
    "least profitable":    "by recorded net loss",
    "costliest":           "by total recorded cost",
    "most catastrophic":   "by total recorded damage in USD",
}


# Banned superlatives. Documented here so the autonomous agent prompt
# and the manual pipeline writer prompt can list them explicitly. Each
# is opinion / aesthetic and cannot be ranked from public records.
BANNED_LIST_SUPERLATIVES: tuple[str, ...] = (
    "scariest",
    "most underrated",
    "strangest",
    "most bizarre",
    "best",
    "worst",
    "coolest",
    "weirdest",
    "most surprising",
    "funniest",
    "cutest",
    "most iconic",
    "most influential",
    "most disturbing",
    "safest",
    "most dangerous",
    "least survivable",
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


def _criterion_for_superlative(outcome: str) -> str:
    """Return the canonical criterion phrase for a surviving superlative.

    Phase D.2: every list candidate MUST carry a criterion so the agent
    cannot fall back on "scariest"-style rank fabrication. The criterion
    is the measurable axis the ranking sits on. Falls back to a generic
    "by recorded measurement" for any new superlative not yet mapped.
    """
    return CRITERION_SHAPES.get(outcome, "by recorded measurement")


def build_list_reel_possibilities(
    mode: str,
    *,
    max_outcomes: int = 12,
) -> list[dict]:
    """Return dynamic top-5 list-reel concepts from live candidate titles.

    Output rows are lightweight idea seeds for script drafting. Phase D.2
    adds a mandatory `criterion` field to every emitted candidate, so the
    agent never sees a bare-superlative seed without a defensible axis.
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
        criterion = _criterion_for_superlative(outcome)
        title = f"Five {subject} {criterion}"
        key = title.lower()
        if key in used_titles:
            continue
        used_titles.add(key)
        ideas.append({
            "title": title,
            "topic": topic,
            "outcome": outcome,
            "subject": subject,
            "criterion": criterion,
        })
        if len(ideas) >= max_outcomes:
            break
    return ideas
