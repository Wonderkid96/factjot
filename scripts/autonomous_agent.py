"""Autonomous agent for the factjot Instagram account.

Sandboxed: the model has NO shell access and NO filesystem access. It
calls a small set of typed tools:

  - list_unposted_topics()  -> compact summary of recent posts (post bank)
  - run_reel(...)           -> compose + publish one reel
  - run_carousel(...)       -> compose + publish one carousel
                              (writer prompt switches by --type)
  - skip(reason)            -> abort this run cleanly with no post

The pipelines themselves (make_reel.py, ship_manual_post.py) run with
full repo access in the host process. Only the model's view is restricted.

Five post modes via --post-mode. Each mode exposes ONLY the tools it
needs and a sharpened, format-locked prompt:

  reel_morning  - 09:00 BST  evergreen reel (run_reel only)
  news          - 12:30 BST  news / current carousel (run_carousel only)
  list          - 15:30 BST  list carousel (run_carousel only)
  reel_evening  - 18:00 BST  evergreen reel (run_reel only)
  fact          - 20:30 BST  fact carousel, single subject (run_carousel only)

Better to skip a slot than ship a weak post. Each mode must call `skip`
with a one-line reason if nothing clears the quality gate.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.content.carousel_rules import (
    BEAT_DENSITY_RULES,
    PHOTOGRAPHABLE_BEATS_RULES,
)

MAX_TURNS = 12
MODEL     = "claude-sonnet-4-6"
HISTORY_LIMIT = 30

# Anthropic Sonnet 4.6 pricing (USD per million tokens, May 2026).
PRICE_INPUT_PER_M  = 3.00
PRICE_OUTPUT_PER_M = 15.00

REPO_ROOT   = Path(__file__).resolve().parent.parent
POSTED_LOG  = REPO_ROOT / "insta-brain" / "data" / "posted.jsonl"
COST_LEDGER = REPO_ROOT / "data" / "ledgers" / "api_usage_costs.jsonl"

SYSTEM = textwrap.dedent("""\
    You are running the factjot Instagram account (@factjot).
    You have three typed tools and nothing else. You cannot read files,
    run shell commands, or inspect the repo. The project context you need
    is in this prompt.
    Be concise. British English. No em dashes.
""")

VALID_MODES = ("reel_morning", "news", "list", "reel_evening", "fact")

# Which carousel writer prompt does this mode want?
# (run_reel modes are absent here.)
MODE_FORMAT_TYPE: dict[str, str] = {
    "news": "news",
    "list": "list",
    "fact": "fact",
}

# Which tools is each mode allowed to call?
# Locked at the loadout level: tools not listed here are not even shown
# to the model. list_unposted_topics + skip are universal.
MODE_TOOLS: dict[str, tuple[str, ...]] = {
    "reel_morning": ("list_unposted_topics", "run_reel",     "skip"),
    "reel_evening": ("list_unposted_topics", "run_reel",     "skip"),
    "news":         ("list_unposted_topics", "run_carousel", "skip"),
    "list":         ("list_unposted_topics", "run_carousel", "skip"),
    "fact":         ("list_unposted_topics", "run_carousel", "skip"),
}


# ------------------------------------------------------------------ #
# Posting history summary - the post bank the agent uses to dedupe
# ------------------------------------------------------------------ #

def _format_history_entry(entry: dict) -> str | None:
    """Return a richer one-line summary per post for duplicate detection.

    Format: `YYYY-MM-DD [format/CATEGORY] subject - keywords`
    """
    date = (entry.get("published_at") or "")[:10]
    if not date:
        return None
    claim_field = entry.get("claim", "")
    category    = (entry.get("category") or "").upper()
    topic       = (entry.get("topic")    or "").lower()

    if category == "REEL":
        fmt = "reel"
    elif claim_field.startswith("list:"):
        fmt = "list"
    else:
        fmt = "carousel"

    label = topic.upper() if fmt == "reel" else (category or topic.upper() or "-")

    if fmt == "carousel" and ":" in claim_field:
        keywords = claim_field.rsplit(":", 1)[-1]
        keywords = keywords.replace("-", " ").replace("_", " ")
    elif fmt == "list" and ":" in claim_field:
        keywords = claim_field.split(":", 1)[-1].replace(":", " / ")
        keywords = keywords.replace("-", " ").replace("_", " ")
    else:
        snippet = claim_field if not claim_field.startswith(("manual:", "list:", "reel:")) else ""
        keywords = (snippet[:140] + "…") if len(snippet) > 140 else snippet
        keywords = keywords or entry.get("post_id") or "(no-keywords)"

    return f"- {date} [{fmt}/{label}] {keywords}"


def build_history_summary(limit: int = HISTORY_LIMIT) -> str:
    if not POSTED_LOG.exists():
        return "(no posts yet)"

    entries: list[dict] = []
    with POSTED_LOG.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    recent = entries[-limit:]
    lines = [_format_history_entry(e) for e in recent]
    lines = [ln for ln in lines if ln]
    if not lines:
        return "(no posts yet)"
    header = (
        f"Last {len(lines)} posts (most recent at bottom). Use this to "
        "reject any candidate that overlaps a previous topic, angle, list "
        "idea, ranking, or subject, even when worded differently."
    )
    return header + "\n" + "\n".join(lines)


# ------------------------------------------------------------------ #
# Pipeline executors (the only things the agent can trigger)
# ------------------------------------------------------------------ #

def _run_pipeline(cmd: list[str]) -> str:
    """Run a pipeline subprocess and stream its output line-by-line.

    Streaming is critical for diagnosing hangs: if a pipeline gets stuck
    on a network call we want to see the last printed step in the
    GitHub Actions log immediately, not after the subprocess returns.
    """
    print(f"\n$ {' '.join(repr(c) if (' ' in c or len(c) > 80) else c for c in cmd)}", flush=True)
    captured: list[str] = []
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(REPO_ROOT),
            bufsize=1,
        )
    except Exception as exc:
        return f"ERROR: failed to start pipeline: {exc}"

    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            print(f"  | {line}", flush=True)
            captured.append(line)
        rc = proc.wait(timeout=2400)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)
        return "ERROR: pipeline timed out after 40 minutes"

    output = "\n".join(captured).strip()
    head = output[-7000:] if output else "(no output)"
    return f"exit_code={rc}\n\n{head}"


def _tag_failure_kind(raw: str, kind_map: list[tuple[str, str]]) -> str:
    """Prefix a `FAILURE_KIND: <kind>` line to the subprocess output.

    `kind_map` is a list of (sentinel_substring, kind_name) pairs,
    checked in order. The first matching sentinel wins. If none match
    and `exit_code=0` is in the output, the result is tagged as `none`.
    Otherwise the kind is `unknown`.
    """
    for sentinel, kind in kind_map:
        if sentinel in raw:
            return f"FAILURE_KIND: {kind}\n\n{raw}"
    if "exit_code=0" in raw:
        return f"FAILURE_KIND: none\n\n{raw}"
    return f"FAILURE_KIND: unknown\n\n{raw}"


def run_reel(args: dict, dry_run: bool) -> str:
    cmd = [
        "python3", "-u", "pipelines/reel/make_reel.py",
        "--script",        args["script"],
        "--title",         args["title"],
        "--topic",         args["topic"],
        "--tone-override", args["tone_override"],
        "--hint",          args["hint"],
    ]
    if dry_run:
        cmd.append("--dry-run")
    raw = _run_pipeline(cmd)
    return _tag_failure_kind(raw, [
        ("ERROR: TTS returned no word timing", "tts_failed"),
        ("ERROR: could not find any footage",  "no_footage"),
        ("reel FAILED ffmpeg",                 "ffmpeg_failed"),
        ("reel FAILED video upload",           "video_upload_failed"),
        ("reel FAILED publish",                "publish_failed"),
        ("exit_code=10",                       "lock_contention"),
    ])


def run_carousel(args: dict, dry_run: bool, format_type: str = "fact") -> str:
    cmd = [
        "python3", "-u", "pipelines/manual/ship_manual_post.py",
        "--brief",  args["brief"],
        "--label",  args["label"],
        "--slides", str(args.get("slides", 6)),
        "--type",   format_type,
    ]
    if dry_run:
        cmd.append("--dry-run")
    raw = _run_pipeline(cmd)
    return _tag_failure_kind(raw, [
        ("CONTENT_SHAPE_MISMATCH", "content_shape_mismatch"),
        ("COVER_IMAGE_FAILED",     "cover_image_failed"),
        ("PUBLISH FAILED",         "publish_failed"),
    ])


# ------------------------------------------------------------------ #
# Tool schemas exposed to the model
# ------------------------------------------------------------------ #

TOOLS = [
    {
        "name": "list_unposted_topics",
        "description": (
            "Return the post bank: a compact summary of the last 30 posts "
            "to @factjot. Each line is `YYYY-MM-DD [format/CATEGORY] "
            "subject keywords`. Use this to reject any candidate that "
            "overlaps a previous topic, angle, list idea, ranking, or "
            "subject, even when reworded. Call this FIRST."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "run_reel",
        "description": (
            "Compose and publish one reel. The pipeline finds footage, "
            "narrates with ElevenLabs, renders, and uploads to Instagram. "
            "Call this exactly ONCE per session. Do not retry on failure."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "70-120 word narration script. First sentence is the hook.",
                },
                "title": {
                    "type": "string",
                    "description": "Short hook title for the thumbnail (3-7 words).",
                },
                "topic": {
                    "type": "string",
                    "enum": ["history", "science", "biology", "ocean", "earth", "space", "technology"],
                },
                "tone_override": {
                    "type": "string",
                    "enum": ["shocking", "curious", "sober", "wholesome"],
                },
                "hint": {
                    "type": "string",
                    "description": (
                        "Multi-line string containing the ranked footage search terms "
                        "you produced after writing the script. One term per line, "
                        "best-first. Each term should be tuned to how stock libraries "
                        "and image APIs actually index content (era, setting, subject, "
                        "mood, composition as separate terms rather than one compressed "
                        "phrase). Optionally append open-source library search URLs "
                        "(Wikimedia Commons, NASA image library, Wellcome Collection, "
                        "Internet Archive) on their own lines where the imagery there "
                        "is likely more accurate or interesting than generic stock."
                    ),
                },
            },
            "required": ["script", "title", "topic", "tone_override", "hint"],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_carousel",
        "description": (
            "Compose and publish one carousel. The writer prompt and slide "
            "count are decided by the run mode (news / list / fact), not "
            "by this call. You only supply the brief, the label, and the "
            "number of slides. Call exactly ONCE."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "brief": {
                    "type": "string",
                    "description": (
                        "2-4 sentence plain-English brief covering angle, "
                        "tone, and what the viewer should understand by the "
                        "end. For list-style posts, name the list (e.g. "
                        "'Five inventions nobody asked for') and list each "
                        "item explicitly so the slide-writer cannot drift."
                    ),
                },
                "label": {
                    "type": "string",
                    "description": "Category label in CAPS (e.g. TECHNOLOGY, HISTORY, SCIENCE).",
                },
                "slides": {
                    "type": "integer",
                    "description": (
                        "Number of slides. Default 6. Use 7 only for a "
                        "5-item list (cover + 5 items + closing)."
                    ),
                },
            },
            "required": ["brief", "label"],
            "additionalProperties": False,
        },
    },
    {
        "name": "skip",
        "description": (
            "Abort this run with no post. Use ONLY when no candidate "
            "clears the quality gate. Better to skip a slot than ship a "
            "weak post. The next slot will fire normally."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "One-line reason for skipping. Logged for audit.",
                },
            },
            "required": ["reason"],
            "additionalProperties": False,
        },
    },
]


def tools_for_mode(mode: str) -> list[dict]:
    """Return only the tool schemas the given mode is allowed to call."""
    allowed = set(MODE_TOOLS[mode])
    return [t for t in TOOLS if t["name"] in allowed]


def execute_tool(name: str, args: dict, dry_run: bool, mode: str) -> str:
    if name == "list_unposted_topics":
        return build_history_summary()
    if name == "skip":
        return f"SKIPPED: {args.get('reason', '(no reason given)')}"
    if name == "run_reel":
        return run_reel(args, dry_run)
    if name == "run_carousel":
        format_type = MODE_FORMAT_TYPE.get(mode, "fact")
        return run_carousel(args, dry_run, format_type)
    return f"ERROR: unknown tool {name}"


# ------------------------------------------------------------------ #
# Prompt
# ------------------------------------------------------------------ #

SHARED_CORE = textwrap.dedent("""\
    You are running the factjot Instagram account (@factjot).

    Your job is to publish one strong post that feels strange, sharp,
    specific, and worth stopping for.

    factjot is not a trivia page.
    factjot is not a general facts page.
    factjot is not here to explain mildly interesting things politely.
    factjot posts true things where the detail, mechanism, decision,
    consequence, or contradiction makes reality look stranger than it
    should.

    The post should feel like:
    'Here is something ridiculous and true. Do what you want with that.'

    You have NO file access, NO shell access, NO repo browsing. Your
    tools are listed in the MODE block below. Nothing else exists.

    DUPLICATE GUARD - HARD RULE

    Before creating or posting anything, call list_unposted_topics() and
    compare every candidate against the post bank.
    Reject any candidate that repeats:
    - the same subject
    - the same event
    - the same person
    - the same company
    - the same product
    - the same animal
    - the same object
    - the same list idea
    - the same ranking
    - the same angle
    - the same story framed differently
    - a near-duplicate with only minor wording changes
    This applies across every format.

    INTERESTINGNESS GATE - HARD RULE

    Do not post a fact because the subject is famous, dramatic, tragic,
    old, scientific, royal, expensive, dangerous, large, rare, cute,
    disgusting, or visually obvious.
    Those things can help, but they are not the reason to post.

    Only post a candidate if it has a clear weird bit.
    The weird bit must be one of these:
    - a contradiction
    - an absurd mechanism
    - a stupid decision
    - a strange consequence
    - an overlooked detail
    - a design failure
    - a system behaving in a way no normal person would expect
    - a true detail that sounds fake without exaggeration
    - a familiar thing made newly strange by one specific fact

    Before posting, ask:
    'What is the actual weird bit?'
    If the answer is just the main event itself, reject it.
    If the answer is only 'this happened', reject it.
    If the answer needs hype words to sound interesting, reject it.
    If the answer is a specific detail, mechanism, decision,
    contradiction, or consequence, it can continue.

    EVENT VS ANGLE RULE

    A subject is not an angle.
    A disaster, invention, animal, law, product, company, trial, war,
    ship, study, place, object, or discovery is only the subject.
    The angle is the reason the subject becomes strange.

    Weak:
    'A ship sank.'
    Strong:
    'The ship sank because the design, decision-making, cargo, rescue
    system, or political context was absurd in a specific way.'

    Weak:
    'A product failed.'
    Strong:
    'A company spent millions solving a problem people did not have,
    then acted surprised when nobody wanted it.'

    Weak:
    'An animal is unusual.'
    Strong:
    'The animal behaves in a way that sounds like a crime, a loophole,
    a scam, or a design bug in nature.'

    This rule does not ban any topic.
    It bans weak angles.

    QUALITY GATE - HARD RULE

    A candidate must pass all four:
    1. The weird bit is specific.
    2. The weird bit can be said in one sentence.
    3. The weird bit is the main hook, not a side detail.
    4. The weird bit would still be interesting without hype words.

    Then it must pass at least one:
    - It sounds fake but is true.
    - It reveals a stupid decision.
    - It has an absurd consequence.
    - It exposes a strange system, rule, design, belief, or behaviour.
    - It makes a familiar subject feel newly strange.
    - It makes the viewer think 'why did nobody stop this?'
    - It makes the viewer think 'how was that allowed?'
    - It makes the viewer think 'sorry, what?'

    If it does not pass, reject it.

    GOOD FACTJOT AREAS

    Good ideas often come from:
    - failed products
    - strange laws
    - odd business decisions
    - badly designed systems
    - obscure historical details
    - animal behaviour
    - weird science
    - internet history
    - forgotten technology
    - corporate overconfidence
    - public information that sounds like satire
    - absurd consequences of normal decisions
    - quiet shutdowns, recalls, bugs, trials, tribunals, or rule changes

    These are only starting points.
    The idea still needs a strong weird bit.

    SAFETY AND TASTE REJECTIONS

    Reject:
    - sexual violence
    - animal cruelty presented for entertainment
    - child harm
    - graphic injury or gore
    - medical advice
    - financial advice
    - defamatory claims about living people
    - unverified criminal accusations
    - active political outrage bait
    - culture-war bait
    - tragedy treated as a joke
    - recent deaths or disasters handled flippantly
    - anything that needs precise live sourcing but cannot be verified

    VOICE

    factjot is:
    - dry
    - direct
    - British English
    - faintly contemptuous of people who are incurious
    - lightly confused by how stupid or strange reality is
    - funny without trying to be a comedian
    - clever without sounding like a TED Talk

    factjot is not:
    - corporate
    - inspirational
    - wholesome by default
    - clickbait
    - fake edgy
    - American YouTube voice
    - a list of fun facts
    - over-explained
    - full of emojis
    - using em dashes
    - using 'did you know'
    - using 'mind-blowing'
    - using 'you won't believe'
    - using 'this changed everything'

    The narrator should sound like someone calmly pointing at reality
    and asking why everyone is pretending this is normal.

    SKIP RULE - HARD RULE

    Better to miss this slot than ship a weak post.
    If no candidate clears the quality gate, call the `skip` tool with
    a one-line reason. Do not call the posting tool with a weak idea.
    The next slot will fire normally.

    UNIVERSAL POSTING RULES

    - Call list_unposted_topics() FIRST.
    - Call exactly one of: the posting tool, OR `skip`. Never both.
    - Do not retry on failure.
    - Do not use em dashes.
    - Do not use hashtags unless the pipeline adds them itself.
    - Only post facts that are specific, named, and well-documented.
    - Prefer facts tied to a named event, person, study, company,
      product, object, animal, law, place, or date.
    - Avoid anything attributed only to 'scientists say', 'studies show',
      'people believe', or 'experts claim'.

    Final test before posting:
    If this appeared in your own feed, would you stop scrolling because
    the idea itself is weird, not because the wording is loud?
    If the answer is no, skip.
""")


REEL_PROMPT = textwrap.dedent("""\

    MODE: EVERGREEN REEL

    Format is locked: this slot publishes a reel and only a reel.

    AVAILABLE TOOLS
    - list_unposted_topics()
    - run_reel(script, title, topic, tone_override, hint)
    - skip(reason)

    EVERGREEN ONLY

    No news. No current events. No this-week stories. No anything that
    needs the viewer to know what just happened in the world. The reel
    must work the same way next year as it does today.

    Good evergreen subjects:
    - history (named people, named events, with a specific weird angle)
    - science / biology / earth / ocean / space (one striking mechanism)
    - obscure technology, lost or abandoned
    - animal behaviour with a specific named species
    - bureaucratic absurdities, old laws, old rulings, old experiments

    REEL RULES

    - Script must be 70 to 120 words.
    - The first sentence is the hook.
    - The first sentence must contain the weird bit.
    - Do not build up to the fact.
    - Do not start with soft context.
    - Use a specific number, name, place, product, company, animal, or
      object wherever possible.
    - The hook should sound strange without needing hype words.
    - No filler intro.
    - No 'did you know'.
    - No fake suspense.
    - No motivational framing.
    - No fake profundity.

    FOOTAGE QUERIES

    After writing the script, produce a ranked list of 4 to 6 footage
    search strings tuned to how stock libraries and image APIs index
    content. Search strings should separate era, setting, subject,
    object, mood, composition. Where the best visual is oblique, use
    oblique terms. Include open-source library URLs (Wikimedia Commons,
    NASA image library, Wellcome Collection, Internet Archive) on their
    own lines where the imagery is likely more accurate than stock.

    DECISION PROCESS

    1. Call list_unposted_topics().
    2. Generate at least 5 candidate evergreen ideas.
    3. Reject duplicates and near-duplicates against the bank.
    4. Reject any current/news/topical idea outright.
    5. For each remaining candidate, name the actual weird bit.
    6. Apply the interestingness, event-vs-angle, and quality gates.
    7. If nothing clears the bar, call skip(reason).
    8. Otherwise, write the script + ranked footage hints.
    9. Write a short decision note (chosen idea, weird bit, why it
       passed, why weaker candidates failed). Then call run_reel ONCE.
""")


NEWS_PROMPT = textwrap.dedent("""\

    MODE: NEWS / CURRENT CAROUSEL

    Format is locked: this slot publishes a carousel framed around a
    current or recent story. The pipeline writes the slides; you supply
    the brief and the label.

    AVAILABLE TOOLS
    - list_unposted_topics()
    - run_carousel(brief, label, slides)   [slides default 6]
    - skip(reason)

    Use your training knowledge to find a current or recent story. The
    bar is the story's STRANGENESS, not its recency. A 30-day-old story
    with a strange angle beats a today-story with a generic angle every
    time. Prefer stories from the last 30 days; the last 7 if available.

    QUALIFYING STORY

    Ask:
    1. 'Would this still be interesting if it happened a year from now?'
       If no, reject. Pure recency is not enough.
    2. 'Is there a strange, revealing, funny, bleak, or absurd angle?'
       If no, reject.
    3. 'Can the angle be said in one clean sentence?'
       If no, reject.

    Look for:
    - under-the-radar tech stories with a specific odd detail
    - weird business decisions and product failures
    - regulatory rulings, tribunals, or trials with absurd context
    - platform shutdowns, feature deletions, quiet recalls
    - internet culture moments that reveal something about a system
    - science / space / environment stories that are current and
      under-discussed
    - obscure updates with surprisingly large consequences

    Reject:
    - generic AI hype
    - earnings or routine product launches
    - vague 'could change everything' framing
    - political outrage bait or culture-war bait
    - celebrity gossip
    - rumours, leaks, unverified claims
    - tragedy treated as content
    - anything you cannot defend factually from training knowledge

    CAROUSEL RULES

    - 6 slides (cover + 5 content). Do not request 7 unless the story
      genuinely needs it.
    - Every slide must do work. No setup-only slides.
    - Brief must include: the story, the angle, what the viewer should
      understand by the end, the named entities involved, and any
      specific dates / numbers / names that anchor it.

    {beat_density_rules}

    The slide writer renders at 16-22 chars per line, hard cap 24, in
    Archivo Black 900 at 42px. If your beat needs more than 3 short
    sentences to express, it is two beats.

    {photographable_beats_rules}

    DECISION PROCESS

    1. Call list_unposted_topics().
    2. Surface at least 4 candidate current stories from training.
    3. Reject duplicates and near-duplicates against the bank.
    4. For each candidate, name the actual weird bit + the angle.
    5. Apply the qualifying-story checks and the quality gate.
    6. If nothing clears the bar, call skip(reason).
    7. Otherwise, write the brief + label.
    8. Decision note (chosen story, angle, why it passed, why weaker
       candidates failed). Call run_carousel ONCE with slides=6.
""")


LIST_PROMPT = textwrap.dedent("""\

    MODE: LIST CAROUSEL

    Format is locked: this slot publishes a list-style carousel.

    AVAILABLE TOOLS
    - list_unposted_topics()
    - run_carousel(brief, label, slides)   [slides default 7]
    - skip(reason)

    LIST RULES

    - 5 items. 7 slides total: cover, 5 items, closing.
    - Every item must be specific, named, and verifiable.
    - Do not invent rankings. Do not invent superlatives.
    - 'Biggest / oldest / fastest / first / last / longest' must be
      factually defensible from training knowledge.
    - 'Best / worst / strangest / dumbest / most cursed' must be
      framed as editorial judgement, not objective fact.
    - The list must have an editorial frame, not a generic 'fun facts
      about X' shape.
    - No BuzzFeed shapes. No 'you won't believe number 4'. No 'top 5
      X you forgot about'.
    - If the list would look at home on a generic trivia account,
      reject it.

    Good list shapes:
    - 'Five tech products that arrived already dead'
    - 'Five regulations that exist because of one specific incident'
    - 'Five experiments that should never have been approved'
    - 'Five animals that solved a problem evolution did not need to'
    - 'Five companies that refused to admit their product was finished'

    Bad list shapes:
    - 'Five amazing facts about space'
    - 'Top 5 weirdest animals'
    - 'Best inventions of all time'
    - 'Things you didn't know about X'

    BRIEF SHAPE

    Brief MUST include:
    - the list title (5-9 words, voice-correct, banned shapes apply)
    - every item explicitly named, one per line, in order
    - a one-line angle per item (why this item belongs in this list)
    - the editorial framing (what the 5 together reveal)
    - what the closing slide should make the viewer think

    {beat_density_rules}

    Each list item gets ONE slide. The item slide carries ONE angle on
    that item, not two. Do not pack two items into one slide. The slide
    writer has 18-28 characters per line, max 32, in Archivo Black 900.

    {photographable_beats_rules}

    DECISION PROCESS

    1. Call list_unposted_topics().
    2. Generate at least 3 candidate list ideas.
    3. Reject duplicates and overlap with previous lists.
    4. For each, identify the editorial frame and the 5 items.
    5. If you cannot defend all 5 items from training knowledge,
       reject the list (or replace items).
    6. Apply the interestingness + quality gates to the LIST as a whole
       (not to each item individually).
    7. If nothing clears the bar, call skip(reason).
    8. Otherwise, write the brief and call run_carousel ONCE with
       slides=7.
""")


FACT_PROMPT = textwrap.dedent("""\

    MODE: FACT CAROUSEL

    Format is locked: this slot publishes a single-subject fact
    carousel. One subject, six slides, told properly.

    AVAILABLE TOOLS
    - list_unposted_topics()
    - run_carousel(brief, label, slides)   [slides default 6]
    - skip(reason)

    A fact carousel is NOT a list. It is one subject with enough
    strangeness or specificity to reward 6 slides of sustained attention.
    Subject can be anything: a person, an event, a place, an object, an
    invention, a phenomenon, a system, a study, a rule, an animal.

    The carousel should build:
    1. cover         - hook the subject and the question / angle
    2. setup         - what the subject is, briefly
    3. mechanism     - how it works / how it happened
    4. consequence   - what it caused / what changed
    5. contradiction - the bit that makes it strange
    6. closing       - the line that makes the viewer think

    These are illustrative slot-types, not strict labels. The point is
    the carousel must move forward. Every slide must add information,
    not restate the cover.

    EVERGREEN

    No news. No current events. The subject can be old or unfamiliar
    but the subject's strangeness must hold up without breaking news.

    Good fact subjects:
    - Concorde, the Voynich Manuscript, Phineas Gage, Gobekli Tepe
    - the Stanford prison experiment, the Antikythera mechanism
    - obscure inventions, abandoned technologies, dead languages
    - bureaucratic failures, lost lawsuits, forgotten experiments
    - specific named animals or species with a strange behaviour
    - geological / astronomical phenomena with a precise mechanism

    Bad fact subjects:
    - 'space is big' / 'the ocean is deep'
    - generic 'top scientist discovers' framing
    - subjects that boil down to one sentence (those belong in reels)
    - subjects you can't defend factually from training knowledge

    BRIEF SHAPE

    Brief MUST include:
    - the subject (canonical proper name)
    - the angle (the weird bit, the contradiction, the consequence)
    - the 5 beats the carousel should hit, in order
    - what the closing slide should make the viewer think

    {beat_density_rules}

    If the story has 7 distinct things worth saying, write 7 beats and
    call run_carousel with slides=8 (cover + 7). Better to have more
    short slides than fewer crowded ones.

    Each line on a slide is rendered in Archivo Black 900 at 42px. The
    writer has 16-22 characters per line, hard cap 24. If your beat
    needs more than 3 short sentences to express, it is two beats.

    {photographable_beats_rules}

    DECISION PROCESS

    1. Call list_unposted_topics().
    2. Generate at least 4 candidate fact subjects.
    3. Reject duplicates and near-duplicates against the bank.
    4. For each, identify the weird bit and the 5 beats it would carry.
    5. Reject any subject whose strangeness is exhausted in 1-2 slides
       (those belong in a reel slot, not here).
    6. Apply the quality gate.
    7. If nothing clears the bar, call skip(reason).
    8. Otherwise, write the brief and call run_carousel ONCE with
       slides=6.
""")


_CAROUSEL_RULE_BINDINGS = dict(
    beat_density_rules         = BEAT_DENSITY_RULES,
    photographable_beats_rules = PHOTOGRAPHABLE_BEATS_RULES,
)

MODE_PROMPTS: dict[str, str] = {
    "reel_morning": REEL_PROMPT,
    "reel_evening": REEL_PROMPT,
    "news":         NEWS_PROMPT.format(**_CAROUSEL_RULE_BINDINGS),
    "list":         LIST_PROMPT.format(**_CAROUSEL_RULE_BINDINGS),
    "fact":         FACT_PROMPT.format(**_CAROUSEL_RULE_BINDINGS),
}


def build_prompt(mode: str) -> str:
    return SHARED_CORE + MODE_PROMPTS[mode]


# ------------------------------------------------------------------ #
# Agent loop
# ------------------------------------------------------------------ #

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="factjot autonomous agent")
    parser.add_argument(
        "--post-mode",
        choices=VALID_MODES,
        default=os.getenv("POST_MODE", "morning"),
        help="Posting mode (also reads POST_MODE env). morning/lunch/evening.",
    )
    args = parser.parse_args(argv)
    mode = args.post_mode

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 1

    dry_run = os.getenv("DRY_RUN", "false").strip().lower() == "true"
    print(
        f"[autonomous-agent] mode={mode} dry_run={dry_run} "
        f"model={MODEL} max_turns={MAX_TURNS}",
        flush=True,
    )

    client   = anthropic.Anthropic(api_key=api_key)
    prompt   = build_prompt(mode)
    tools    = tools_for_mode(mode)
    messages: list[dict] = [{"role": "user", "content": prompt}]

    total_input  = 0
    total_output = 0
    final_status = "unknown"
    exit_code    = 0
    skipped      = False

    try:
        for turn in range(MAX_TURNS):
            response = client.messages.create(
                model=MODEL,
                max_tokens=4096,
                system=SYSTEM,
                tools=tools,
                messages=messages,
            )
            usage = getattr(response, "usage", None)
            if usage is not None:
                total_input  += getattr(usage, "input_tokens",  0) or 0
                total_output += getattr(usage, "output_tokens", 0) or 0

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                print("\n[autonomous-agent] finished (end_turn).", flush=True)
                final_status = "end_turn"
                break
            if response.stop_reason != "tool_use":
                print(f"[autonomous-agent] unexpected stop_reason: {response.stop_reason}", flush=True)
                final_status = f"stop_{response.stop_reason}"
                exit_code = 1
                break

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                print(f"\n[tool] {block.name}({list(block.input.keys())})", flush=True)
                if block.name == "skip":
                    reason = block.input.get("reason", "(no reason given)")
                    print(f"\n[SKIP] mode={mode} reason={reason}", flush=True)
                    final_status = "skipped"
                    skipped = True
                    break
                output = execute_tool(block.name, block.input, dry_run, mode)
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     output,
                })

            if skipped:
                break

            messages.append({"role": "user", "content": tool_results})
        else:
            print(f"[autonomous-agent] hit max turns ({MAX_TURNS}).", flush=True)
            final_status = "max_turns"
    finally:
        _log_cost(mode, dry_run, total_input, total_output, final_status)

    return exit_code


def _log_cost(mode: str, dry_run: bool, input_tokens: int, output_tokens: int, status: str) -> None:
    """Append per-run cost estimate to data/ledgers/api_usage_costs.jsonl."""
    from datetime import datetime, timezone
    cost_in  = input_tokens  / 1_000_000 * PRICE_INPUT_PER_M
    cost_out = output_tokens / 1_000_000 * PRICE_OUTPUT_PER_M
    total    = round(cost_in + cost_out, 6)
    record = {
        "timestamp":     datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "source":        "autonomous_agent",
        "mode":          mode,
        "dry_run":       dry_run,
        "model":         MODEL,
        "input_tokens":  input_tokens,
        "output_tokens": output_tokens,
        "stop_status":   status,
        "cost_estimate_usd": {
            "anthropic_input":  round(cost_in, 6),
            "anthropic_output": round(cost_out, 6),
            "total":            total,
        },
        "pricing_meta": {
            "input_per_million_usd":  PRICE_INPUT_PER_M,
            "output_per_million_usd": PRICE_OUTPUT_PER_M,
        },
    }
    try:
        COST_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with COST_LEDGER.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        print(
            f"[cost] in={input_tokens} out={output_tokens} "
            f"total=${total:.4f} (mode={mode}, model={MODEL})",
            flush=True,
        )
    except Exception as exc:
        print(f"[cost] failed to write ledger: {exc}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
