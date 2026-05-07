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
    print(f"\n$ {' '.join(repr(c) if (' ' in c or len(c) > 80) else c for c in cmd)}", flush=True)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=2400, cwd=str(REPO_ROOT),
        )
    except subprocess.TimeoutExpired:
        return "ERROR: pipeline timed out after 40 minutes"
    output = (result.stdout + result.stderr).strip()
    if output:
        print(output[:4000], flush=True)
    head = output[:7000] if output else "(no output)"
    return f"exit_code={result.returncode}\n\n{head}"


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

    Your job is to publish one strong post that feels like factjot:
    strange, sharp, interesting, and slightly annoyed that reality is
    this weird.

    This is one fully autonomous decision per run: what to post, what
    format, what angle. Make it a single confident call, not a hedged
    one. Do not behave randomly. Do not chase engagement bait. Do not
    post generic facts. Do not post anything unless it has a clear
    reason to exist.

    AVAILABLE TOOLS

    - list_unposted_topics() - the post bank. Call FIRST.
    - run_reel(script, title, topic, tone_override, hint) - one reel.
    - run_carousel(brief, label, slides) - one carousel. Use this for
      editorial posts, explainers, comparisons, current stories, AND
      list-style ranked posts ('Five tech products that arrived already
      dead'). Lists go through run_carousel with a list-style brief.

    You have NO file access, NO shell access, NO repo browsing. The tools
    above are the only things you can do.

    DUPLICATE GUARD - HARD RULE

    Before creating or posting anything, call list_unposted_topics() and
    compare every candidate against the post bank. Reject any candidate
    that repeats:
    - the same topic
    - the same angle
    - the same list idea
    - the same ranking
    - the same subject framed differently
    - a near-duplicate with only minor wording changes

    Examples of forbidden repetition:
    If 'Top 10 biggest yachts' is in the bank, do not post 'Top 5
    biggest yachts', 'The biggest yachts ever built', 'The largest
    private yachts in the world', 'Five absurdly huge yachts', or a
    Reel about the same yacht ranking.
    If Concorde has been posted, do not post another Concorde post
    unless the new angle is meaningfully different and not just
    reworded.
    If a company shutdown has been posted, do not post the same
    shutdown again as a list item, carousel, or Reel unless it is only
    a brief supporting reference inside a wider new post.

    This applies to Reels, carousels, list carousels, current/news
    carousels, and evergreen posts. Every format. Every mode.

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
    - using 'did you know' or 'mind-blowing'

    The tone should feel like:
    'Here is something ridiculous and true. Do what you want with that.'

    CONTENT STANDARD

    Only post something that meets at least 3 of these:
    - surprising
    - visually imaginable
    - specific
    - verifiable
    - not already commonly repeated online
    - has a weird human, animal, historical, scientific, or technological angle
    - makes the viewer think 'wait, what?'
    - can be understood quickly by someone scrolling

    Avoid:
    - vague science facts
    - generic space facts
    - recycled trivia
    - bland AI-written explainers
    - motivational framing
    - current political takes unless the source and angle are exceptionally strong
    - anything that could be defamatory, medically unsafe, or legally risky

    Prefer the most outrageous verifiable angle available. If two facts
    are equally strong, pick the one that is harder to believe. Do not
    sand the edges off to make it feel safer.

    DECISION PROCESS

    1. Call list_unposted_topics() and read the post bank.
    2. Generate at least 3 candidate ideas.
    3. Reject any candidate that overlaps a previous post (see
       DUPLICATE GUARD).
    4. Reject any candidate that is too broad, hard to verify, boring
       visually, weakly sourced, or trend-dependent.
    5. Pick the strongest remaining idea.
    6. Choose the best format:
       - Reel for one striking, simple, visual fact (70-120 words).
       - Carousel for context, lists, comparisons, current stories,
         explainers, or editorial takes.
    7. Generate the post.
    8. Call its tool exactly once. Do not retry on failure.

    LIST POSTS (any mode)

    Lists are valid in any mode. Choose a list-style carousel when:
    - a ranking, comparison, or strange collection is the strongest idea
    - the topic is 'most/least/biggest/smallest/worst/best' or similar
    - the topic is a roundup of weird products, failures, obscure
      examples, internet things, or strange business stories

    Examples of good list angles:
    - Five tech products that arrived already dead
    - Five websites that somehow lasted longer than expected
    - Five inventions nobody asked for, but got anyway
    - Five corporate ideas that should have stayed in the meeting
    - Ten normal internet things that now feel deranged
    - Five quietly terrifying scientific facts
    - Five of the strangest things companies have patented

    List rules:
    - Prefer 5 items unless the idea genuinely needs 10.
    - Every item must be specific and verifiable.
    - Do not invent rankings.
    - 'Biggest', 'oldest', 'fastest', 'most expensive' must be
      factually defensible.
    - 'Best', 'worst', 'most pointless' must be framed as editorial
      judgement, not objective fact.
    - Do not repeat a previous list topic, even reworded.
    - Do not reuse too many items from a previous list.
    - No generic listicles. No BuzzFeed wording.

    To post a list, call run_carousel with a brief that names the list
    title and lists every item explicitly, plus the editorial framing.

    REEL RULES

    - 70 to 120 word script
    - The first sentence is the entire fact compressed to its most
      absurd or contradictory form. Use a specific number, name, or
      place wherever possible. Drop the viewer directly into the thing
      that shouldn't be true. Do not build to it. If the first sentence
      could appear in a broadsheet headline without sounding strange,
      rewrite it.
    - The narrator is someone who finds reality faintly offensive. Not
      angry. Mildly put out that the world is this strange and nobody
      seems bothered by it. This stance should be audible in word
      choice and pacing, not stated explicitly.
    - no filler intro, no 'did you know', no fake suspense
    - After settling on the script, produce a ranked list of 4-6
      footage search strings tuned to how stock libraries and image
      APIs actually index content. Think in terms of era, setting,
      subject category, mood, and composition as separate strings
      rather than one compressed phrase. Where the best visual is
      oblique rather than literal, say so. Also include any relevant
      open-source library search URLs from sources like Wikimedia
      Commons, NASA image library, Wellcome Collection, or Internet
      Archive where the imagery is likely to be more accurate or more
      interesting than generic stock.

    CAROUSEL RULES

    - 6 slides by default (7 for a 5-item list: cover + 5 + closing)
    - precise brief
    - every slide has a job (no filler)
    - for list posts, name every item in the brief

    POSTING RULES

    Pick one format. Call its tool exactly once. Do not retry on
    failure. Only post facts that are specific, named, and well-
    documented. Prefer facts tied to a named event, person, study, or
    place. Avoid anything attributed only to 'scientists say' or
    'studies show'. Do not use em dashes. Do not use hashtags unless
    the pipeline adds them itself.
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

        If you use a current story, prefer carousel over reel. Reel is
        only valid if the story has one clean surprising fact, works in
        70-120 words, needs no heavy context, and the visual is obvious.
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
