"""Minimal autonomous agent using the Anthropic SDK directly.

Runs a multi-turn tool-use loop: Claude decides what to do, calls bash
commands, reads output, and continues until it finishes or hits max turns.
Bypasses the Claude Code CLI entirely — no TTY required, works in CI.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import anthropic

MAX_TURNS = 40
MODEL     = "claude-haiku-4-5-20251001"

SYSTEM = textwrap.dedent("""\
    You are running the factjot Instagram account (@factjot).
    You have Bash access. Use it to read files, then post content.
    Be concise. Do not explain your reasoning at length.
    British English. No em dashes.
""")

def _build_prompt() -> str:
    dry_run = os.getenv("DRY_RUN", "false").strip().lower() == "true"
    dry_flag = " \\\n          --dry-run" if dry_run else ""
    return textwrap.dedent(f"""\
        You are running the factjot Instagram account (@factjot).

        Your job is to publish one strong post that feels like factjot:
        strange, sharp, interesting, and slightly annoyed that reality is
        this weird.

        Do not behave randomly. Do not chase engagement bait. Do not post
        generic facts. Do not post anything unless it has a clear reason
        to exist.

        First read:
        1. CLAUDE.md
        2. insta-brain/data/posted.jsonl

        Use those to understand the project and avoid repeating topics,
        angles, wording, or formats that have already been used.

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
        - too similar to a previous post
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

        Use this for:
        - one jaw-dropping fact
        - a strange historical moment
        - a visual scientific or natural phenomenon
        - something that can be understood in 70 to 120 words

        The first sentence must be the hook.
        The script must stay tight.
        No filler intro.
        No 'did you know'.
        No 'in today's video'.
        No fake suspense.

        Run:

            python3 -u pipelines/reel/make_reel.py \\\\
              --script "70-120 word script, first sentence is the most surprising" \\\\
              --title "short hook title" \\\\
              --topic <history|science|biology|ocean|earth|space|technology> \\\\
              --tone-override <shocking|curious|sober|wholesome> \\\\
              --hint "2-5 word footage hint"{dry_flag}

        CAROUSEL RULES

        Use this for:
        - a compact explainer
        - a strange news-adjacent story
        - a subject with multiple angles
        - a short editorial observation
        - something that benefits from 6 slides

        The brief should be precise.
        The slides should build a small argument or reveal.
        Do not make a generic educational carousel.
        Do not include filler slides.
        Every slide needs a job.

        Run:

            python3 -u pipelines/manual/ship_manual_post.py \\\\
              --brief "2-4 sentence plain-English description of the post. Include the angle, the intended tone, and what the viewer should understand by the end." \\\\
              --label "CATEGORY IN CAPS" \\\\
              --slides 6{dry_flag}

        POSTING RULES

        Pick one format.
        Run it once.
        Do not retry on failure.
        Do not post more than once.
        Do not invent sources.
        Do not use em dashes.
        Do not use hashtags unless the project files explicitly require them.
        Do not explain what you are doing after the post command.

        If the best available idea feels weak, still post the strongest
        acceptable idea, but keep it narrow and specific rather than
        trying to make it sound bigger than it is.
    """)

BASH_TOOL = {
    "name": "bash",
    "description": "Run a bash command and return stdout + stderr.",
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The bash command to run."}
        },
        "required": ["command"],
    },
}


def run_bash(command: str) -> str:
    print(f"\n$ {command}", flush=True)
    result = subprocess.run(
        command, shell=True, capture_output=True, text=True, timeout=600,
    )
    output = (result.stdout + result.stderr).strip()
    if output:
        print(output[:4000], flush=True)
    return output[:8000] if output else "(no output)"


def main() -> int:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 1

    client   = anthropic.Anthropic(api_key=api_key)
    messages = [{"role": "user", "content": _build_prompt()}]

    for turn in range(MAX_TURNS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM,
            tools=[BASH_TOOL],
            messages=messages,
        )

        # Append assistant turn
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            print("\nAgent finished.", flush=True)
            return 0

        if response.stop_reason != "tool_use":
            print(f"Unexpected stop_reason: {response.stop_reason}", flush=True)
            return 1

        # Execute tool calls and collect results
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            output = run_bash(block.input["command"])
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output,
            })

        messages.append({"role": "user", "content": tool_results})

    print(f"Hit max turns ({MAX_TURNS}).", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
