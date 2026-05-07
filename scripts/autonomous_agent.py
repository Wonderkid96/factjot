"""Autonomous agent for the factjot Instagram account.

Sandboxed: the model has NO shell access and NO filesystem access. It can
only call three typed tools:

  - list_unposted_topics()  -> compact summary of recent posts
  - run_reel(...)           -> compose + publish one reel
  - run_carousel(...)       -> compose + publish one carousel

The pipelines themselves (make_reel.py, ship_manual_post.py) run with
full repo access in the host process. Only the model's view is restricted.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import anthropic

MAX_TURNS = 12
MODEL     = "claude-haiku-4-5-20251001"
HISTORY_LIMIT = 25

REPO_ROOT  = Path(__file__).resolve().parent.parent
POSTED_LOG = REPO_ROOT / "insta-brain" / "data" / "posted.jsonl"

SYSTEM = textwrap.dedent("""\
    You are running the factjot Instagram account (@factjot).
    You have three typed tools and nothing else. You cannot read files,
    run shell commands, or inspect the repo. The project context you need
    is in this prompt.
    Be concise. British English. No em dashes.
""")


# ------------------------------------------------------------------ #
# Posting history summary
# ------------------------------------------------------------------ #

def _format_history_entry(entry: dict) -> str | None:
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
        # Everything else is a carousel (manual/editorial AND legacy fact
        # carousels where topic was set to "factjot" generically).
        fmt = "carousel"

    label = topic.upper() if fmt == "reel" else (category or topic.upper() or "-")

    if fmt == "carousel" and ":" in claim_field:
        keywords = claim_field.rsplit(":", 1)[-1]
    elif fmt == "list" and ":" in claim_field:
        keywords = claim_field.split(":", 1)[-1].replace(":", " / ")
    else:
        snippet = claim_field if not claim_field.startswith(("manual:", "list:", "reel:")) else ""
        keywords = (snippet[:90] + "…") if len(snippet) > 90 else snippet
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
    header = f"Last {len(lines)} posts (most recent at bottom):"
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
            "Return a compact summary of the last 25 posts to @factjot so you "
            "can avoid repeating topics, slugs, formats, or angles. "
            "Each line is `YYYY-MM-DD [format/CATEGORY] slug-with-keywords`. "
            "Call this FIRST, before deciding what to post."
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
                    "description": "2-5 word footage hint for the stock-clip search (e.g. 'phineas gage railway').",
                },
            },
            "required": ["script", "title", "topic", "tone_override", "hint"],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_carousel",
        "description": (
            "Compose and publish one editorial carousel. The pipeline writes "
            "the slides, sources images, and uploads to Instagram. "
            "Call this exactly ONCE per session. Do not retry on failure."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "brief": {
                    "type": "string",
                    "description": "2-4 sentence plain-English brief covering angle, tone, and the one thing the viewer should understand by the end.",
                },
                "label": {
                    "type": "string",
                    "description": "Category label in CAPS (e.g. TECHNOLOGY, HISTORY, SCIENCE).",
                },
                "slides": {
                    "type": "integer",
                    "description": "Number of slides. Default 6.",
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

PROMPT = textwrap.dedent("""\
    You are running the factjot Instagram account (@factjot).

    Your job is to publish one strong post that feels like factjot:
    strange, sharp, interesting, and slightly annoyed that reality is
    this weird.

    Do not behave randomly. Do not chase engagement bait. Do not post
    generic facts. Do not post anything unless it has a clear reason
    to exist.

    AVAILABLE TOOLS

    - list_unposted_topics() - call FIRST to see what has already been
      posted so you do not repeat topics, slugs, or angles.
    - run_reel(script, title, topic, tone_override, hint) - publish one reel.
    - run_carousel(brief, label, slides) - publish one carousel.

    You have NO file access, NO shell access, NO repo browsing. The tools
    above are the only things you can do.

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

    DECISION PROCESS

    Before posting, internally choose 3 candidate ideas.
    Reject any candidate that is:
    - too similar to a previous post (consult list_unposted_topics)
    - too broad
    - too hard to verify
    - too boring visually
    - too dependent on a trending context

    Pick the strongest remaining idea.

    FORMAT CHOICE

    Choose REEL only if the idea works as one striking narrated fact
    with a clear visual image.

    Choose CAROUSEL only if the idea needs explanation, contrast,
    timeline, context, or multiple beats.

    Do not choose carousel just because you have more to say.
    Do not choose reel if the fact needs too much setup.

    REEL RULES

    - one jaw-dropping fact
    - 70 to 120 word script, first sentence is the hook
    - no filler intro, no 'did you know', no fake suspense
    - hint is 2-5 words, anchored to the actual visual subject

    CAROUSEL RULES

    - 6 slides by default
    - precise brief
    - every slide has a job (no filler)
    - works as an explainer, contrast, timeline, or short editorial

    POSTING RULES

    Pick one format. Call its tool exactly once. Do not retry on failure.
    Do not invent sources. Do not use em dashes. Do not use hashtags
    unless the pipeline adds them itself.

    If the best available idea feels weak, still post the strongest
    acceptable idea, but keep it narrow and specific rather than trying
    to make it sound bigger than it is.
""")


# ------------------------------------------------------------------ #
# Agent loop
# ------------------------------------------------------------------ #

def main() -> int:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 1

    dry_run = os.getenv("DRY_RUN", "false").strip().lower() == "true"
    print(f"[autonomous-agent] dry_run={dry_run} model={MODEL} max_turns={MAX_TURNS}", flush=True)

    client   = anthropic.Anthropic(api_key=api_key)
    messages: list[dict] = [{"role": "user", "content": PROMPT}]

    for turn in range(MAX_TURNS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM,
            tools=TOOLS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            print("\n[autonomous-agent] finished (end_turn).", flush=True)
            return 0
        if response.stop_reason != "tool_use":
            print(f"[autonomous-agent] unexpected stop_reason: {response.stop_reason}", flush=True)
            return 1

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

    print(f"[autonomous-agent] hit max turns ({MAX_TURNS}).", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
