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
        Post something genuinely interesting to @factjot. Complete creative
        freedom - any topic, any subject, no template.

        The factjot voice: dry, direct, faintly contemptuous of people who
        don't find things interesting. Never sensational. Never corporate.

        Steps:
        1. Read CLAUDE.md to understand the project and pipelines.
        2. Read insta-brain/data/posted.jsonl to see what has been posted.
           Pick something that is NOT already covered.
        3. Choose a format:

        REEL - a single striking fact, narrated. Best for jaw-dropping claims,
        moments in history, anything with strong visual potential.

            python3 -u pipelines/reel/make_reel.py \\\\
              --script "<70-120 word script, lead with the most surprising sentence>" \\\\
              --title "<hook title>" \\\\
              --topic <history|science|biology|ocean|earth|space|technology> \\\\
              --tone-override <shocking|curious|sober|wholesome> \\\\
              --hint "<2-5 word footage hint>"{dry_flag}

        CAROUSEL - a news story, explainer, or multi-angle take. Best for
        current events or anything needing more than one sentence.

            python3 -u pipelines/manual/ship_manual_post.py \\\\
              --brief "<2-4 sentence plain-English brief>" \\\\
              --label "<CATEGORY IN CAPS>" \\\\
              --slides 6{dry_flag}

        Pick one format. Run it once. Stop after it completes or fails.
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
