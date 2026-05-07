"""Autonomous agent for the factjot Instagram account.

Sandboxed: the model has NO shell access and NO filesystem access. It can
only call three typed tools:

  - list_unposted_topics()  -> compact summary of recent posts (post bank)
  - run_reel(...)           -> compose + publish one reel
  - run_carousel(...)       -> compose + publish one carousel
                              (use a list-style brief for ranked posts)

The pipelines themselves (make_reel.py, ship_manual_post.py) run with
full repo access in the host process. Only the model's view is restricted.

Three post modes via --post-mode:
  morning  - standard autonomous flow, picks the strongest idea available
  lunch    - same flow, may also consider current/under-the-radar news
             but only if the story passes the same quality bar
  evening  - standard autonomous flow

Lists are not tied to lunch. A list-style carousel may be the strongest
idea in any mode; in that case the agent calls run_carousel with a
list-style brief.
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

VALID_MODES = ("morning", "lunch", "evening")


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
    return _run_pipeline(cmd)


def run_carousel(args: dict, dry_run: bool) -> str:
    cmd = [
        "python3", "-u", "pipelines/manual/ship_manual_post.py",
        "--brief",  args["brief"],
        "--label",  args["label"],
        "--slides", str(args.get("slides", 6)),
    ]
    if dry_run:
        cmd.append("--dry-run")
    return _run_pipeline(cmd)


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
            "Compose and publish one carousel. Use for editorial posts, "
            "current stories, explainers, comparisons, timelines, or "
            "list-style ranked posts (e.g. 'Five tech products that "
            "arrived already dead'). The pipeline writes the slides, "
            "sources images, and uploads to Instagram. Call exactly ONCE."
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
                        "Number of slides. Default 6. For a 5-item list use "
                        "7 (cover + 5 items + closing)."
                    ),
                },
            },
            "required": ["brief", "label"],
            "additionalProperties": False,
        },
    },
]


def execute_tool(name: str, args: dict, dry_run: bool) -> str:
    if name == "list_unposted_topics":
        return build_history_summary()
    if name == "run_reel":
        return run_reel(args, dry_run)
    if name == "run_carousel":
        return run_carousel(args, dry_run)
    return f"ERROR: unknown tool {name}"


# ------------------------------------------------------------------ #
# Prompt
# ------------------------------------------------------------------ #

CORE_PROMPT = textwrap.dedent("""\
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

    AVAILABLE TOOLS

    - list_unposted_topics() - the post bank. Call FIRST.
    - run_reel(script, title, topic, tone_override, hint) - one reel.
    - run_carousel(brief, label, slides) - one carousel. Use this for
      editorial posts, explainers, comparisons, current stories, and
      list-style ranked posts.

    You have NO file access, NO shell access, NO repo browsing. The tools
    above are the only things you can do.

    ONE POST ONLY

    Make one autonomous decision:
    - what to post
    - what format to use
    - what angle to take

    Call exactly one posting tool.
    Do not retry.
    Do not post something merely adequate.
    Adequate is failure.

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

    FORMAT CHOICE

    Pick the format that makes the idea strongest.

    Use a Reel when:
    - there is one clean striking fact
    - it works in 70 to 120 words
    - it can be understood instantly
    - the visual direction is obvious
    - it does not need much context

    Use a carousel when:
    - the idea needs context
    - the idea has multiple moving parts
    - the idea benefits from a timeline
    - the idea is a comparison
    - the idea is editorial
    - the idea is current or under-the-radar news
    - the idea is a list or ranking
    - the idea is stronger as 'here are the pieces' rather than one
      spoken narration

    Prefer carousel when unsure.
    Prefer carousel for lists.

    Format choice is driven by the angle, not the topic.
    Tech, business, shutdowns, product failures, regulation, tribunals,
    and odd internet stories can all be reels OR carousels. Pick whichever
    fits the angle:
    - one striking fact, one mechanism, one decision  → reel
    - multiple parts, a comparison, a timeline, a list → carousel

    LIST POSTS

    Lists are valid in any mode.
    Choose a list-style carousel when:
    - a ranking, comparison, or strange collection is the strongest idea
    - the post collects weird products, failures, obscure examples,
      internet things, business stories, strange laws, or scientific
      examples

    List rules:
    - Prefer 5 items unless the idea genuinely needs 10.
    - Every item must be specific and verifiable.
    - Do not invent rankings.
    - Biggest, oldest, fastest, most expensive, first, last, and longest
      must be factually defensible.
    - Best, worst, most pointless, strangest, dumbest, and most cursed
      must be framed as editorial judgement, not objective fact.
    - Do not repeat a previous list topic, even reworded.
    - Do not reuse too many items from a previous list.
    - No generic listicles.
    - No BuzzFeed wording.
    - If the list would look normal on a generic trivia account, reject it.

    To post a list, call run_carousel with a brief that:
    - names the list title
    - lists every item explicitly
    - states the editorial framing
    - explains what the viewer should understand by the end

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
    - No hashtags unless the pipeline adds them itself.

    For Reels, after writing the script, produce a ranked list of 4 to 6
    footage search strings tuned to how stock libraries and image APIs
    actually index content.
    Search strings should separate:
    - era
    - setting
    - subject
    - object
    - mood
    - composition
    Where the best visual is oblique rather than literal, use oblique
    search terms. Include relevant open-source library search URLs from
    sources like Wikimedia Commons, NASA image library, Wellcome
    Collection, or Internet Archive where the imagery is likely more
    accurate or interesting than generic stock.

    CAROUSEL RULES

    - 6 slides by default.
    - 7 slides for a 5-item list: cover, 5 items, closing.
    - Every slide must have a job.
    - No filler slide.
    - No generic setup slide.
    - For list posts, name every item in the brief.
    - The brief must be precise enough that the slide-writer cannot drift.

    DECISION PROCESS

    1. Call list_unposted_topics() first.
    2. Generate at least 5 candidate ideas.
    3. Reject duplicates and near-duplicates using the post bank.
    4. For each remaining candidate, identify the actual weird bit.
    5. Reject anything where the weird bit is vague, generic, or just the
       main event itself.
    6. Apply the quality gate.
    7. Pick the strongest remaining idea.
    8. Choose the best format.
    9. Before calling the posting tool, write a short decision note:
       - chosen idea
       - actual weird bit
       - why it passed the quality gate
       - why weaker candidates were rejected
       - why the chosen format is best
    10. Call exactly one posting tool.

    If no candidate is strong enough, choose a stronger list-style
    carousel angle rather than forcing a weak Reel.

    POSTING RULES

    - Call list_unposted_topics() first.
    - Call exactly one posting tool.
    - Do not retry on failure.
    - Do not post generic facts.
    - Do not post adequate facts.
    - Do not post because the idea is easy to visualise.
    - Do not post because the idea is safe.
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
    If the answer is no, reject it.
""")


MODE_NOTES = {
    "morning": textwrap.dedent("""\

        MODE: MORNING

        Standard autonomous flow. Pick the strongest interesting post
        available, in any format (reel / carousel / list carousel).
        No news permission today.
    """),
    "lunch": textwrap.dedent("""\

        MODE: LUNCH

        Standard autonomous flow with one extra option: you may consider
        current, breaking, recent, weird, or under-the-radar news from
        your knowledge if a story passes the same quality bar.

        Lunch is NOT a news slot by default. Only use a current story if
        it is genuinely strong. If nothing current passes the bar, fall
        back to the normal autonomous flow.

        Current story quality bar:
        Ask: 'Would this still be interesting if it happened last year?'
        If no, reject it.
        Ask: 'Is there a strange, revealing, funny, bleak, surprising,
        or useful angle?' If no, reject it.

        Look for:
        - under-the-radar tech news
        - weird business stories
        - overlooked internet culture stories
        - platform shutdowns
        - strange product launches
        - regulatory or tribunal stories with a specific odd angle
        - AI stories only if genuinely strange, specific, or revealing
        - science/space/environment stories if current and under-discussed
        - companies quietly killing features or products
        - obscure updates with surprisingly large consequences

        Reject:
        - generic AI hype
        - routine product updates
        - bland startup news
        - earnings reports
        - vague 'could change everything' stories
        - political commentary for its own sake
        - celebrity gossip
        - culture-war or outrage bait
        - rumours or leaks
        - stories that are only interesting because they trend
        - stories needing too much context
        - stories with weak sourcing

        If you use a current story, choose the format that fits the angle.
        A reel works when the story has one clean surprising fact, fits in
        70-120 words, needs no heavy context, and the visual is obvious.
        A carousel works when the story needs multiple beats, comparison,
        or timeline. Do not default to carousel just because it is news.
    """),
    "evening": textwrap.dedent("""\

        MODE: EVENING

        Standard autonomous flow. Pick the strongest interesting post
        available, in any format (reel / carousel / list carousel).
        No news permission today.
    """),
}


def build_prompt(mode: str) -> str:
    return CORE_PROMPT + MODE_NOTES[mode]


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
    messages: list[dict] = [{"role": "user", "content": prompt}]

    total_input  = 0
    total_output = 0
    final_status = "unknown"
    exit_code    = 0

    try:
        for turn in range(MAX_TURNS):
            response = client.messages.create(
                model=MODEL,
                max_tokens=4096,
                system=SYSTEM,
                tools=TOOLS,
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
                output = execute_tool(block.name, block.input, dry_run)
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     output,
                })

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
