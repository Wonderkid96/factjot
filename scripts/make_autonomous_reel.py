"""Fully autonomous factjot Reel — Claude decides everything.

Claude is given the factjot brand voice and complete creative freedom.
No topic constraint, no script template, no fact bank. Claude calls
post_reel() with whatever it decides is worth sharing.

The tool call pipes directly into the standard make_reel.py pipeline:
number normalisation → TTS → footage → FFmpeg compose → upload → publish.

Usage:
    python3 scripts/make_autonomous_reel.py
    python3 scripts/make_autonomous_reel.py --dry-run
    python3 scripts/make_autonomous_reel.py --model claude-opus-4-7
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv()

from make_reel import make_reel


_SYSTEM_PROMPT = """\
You are running the factjot Instagram account (@factjot).

factjot posts short-form video reels about things that are genuinely surprising. \
The voice is dry, direct, occasionally condescending, and faintly contemptuous of people \
who don't find this as interesting as you do. British English. No em dashes.

THE VOICE: Think of a very knowledgeable person who is slightly tired of how unimpressive \
most people's general knowledge is, but still bothers to share things because somewhere \
deep down they care. Dry asides are encouraged. Mild condescension is fine. Occasional \
acknowledgement that some people won't care is welcome.

Examples of the tone:
- "Nobody asked, but here it is anyway."
- "This is the kind of thing that will make you unbearable at dinner parties. You're welcome."
- "If you already knew this, you can ignore it. You probably didn't."
- "Twenty-one people drowned in molasses. Which is, by any measure, a bad day."
- "This is interesting if you find things interesting."
- A dry understatement where a normal person would use an exclamation mark.

Your job: decide what to post. Complete creative freedom. It can be a historical fact, \
a scientific observation, a thought experiment, something about language, mathematics, \
nature, human behaviour, or anything else you genuinely find interesting.

The only rules:
1. Lead with the most surprising sentence. Do not build toward it.
2. Keep the dry, slightly-condescending factjot voice throughout.
3. 70-120 words. The reel runs 35-45 seconds.
4. No em dashes. Use commas, full stops, or rewrite.
5. No corporate fluff. No "fascinating" or "incredible" or "amazing".

When you are ready, call post_reel with your content.\
"""

_POST_REEL_TOOL = {
    "name": "post_reel",
    "description": (
        "Submit your reel content to be rendered and posted to Instagram. "
        "Call this once you have decided what to post."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "reel_script": {
                "type": "string",
                "description": (
                    "The voice-over script the narrator will read aloud. "
                    "70-120 words. No stage directions, no speaker labels. "
                    "No em dashes."
                ),
            },
            "reel_title": {
                "type": "string",
                "description": (
                    "Short punchy title shown on the opening hook card. "
                    "Max 8 words. No em dashes."
                ),
            },
            "topic": {
                "type": "string",
                "enum": ["history", "science", "biology", "ocean", "earth", "space", "technology"],
                "description": "Closest topic category — used for footage sourcing.",
            },
            "tone": {
                "type": "string",
                "enum": ["shocking", "curious", "sober", "wholesome"],
                "description": (
                    "Emotional register. Determines narrator voice settings and music. "
                    "'shocking' = more dramatic delivery, 'sober' = measured and calm."
                ),
            },
            "image_hint": {
                "type": "string",
                "description": (
                    "2-5 word visual search hint for stock footage. "
                    "Describe what you want to see in the background "
                    "(e.g. 'underwater ocean deep sea', 'vintage archive black white city')."
                ),
            },
        },
        "required": ["reel_script", "reel_title", "topic", "tone", "image_hint"],
    },
}


def call_claude(model: str) -> dict:
    """Call the Claude API and extract the post_reel tool call."""
    import anthropic

    client = anthropic.Anthropic()

    print(f"[autonomous] calling {model}...")
    print(f"[autonomous] prompt: complete creative freedom, factjot voice\n")

    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        tools=[_POST_REEL_TOOL],
        tool_choice={"type": "any"},
        messages=[
            {"role": "user", "content": "Post something."},
        ],
    )

    # Extract the post_reel tool call
    for block in response.content:
        if block.type == "tool_use" and block.name == "post_reel":
            data = block.input
            print(f"[autonomous] Claude chose:")
            print(f"  title : {data['reel_title']}")
            print(f"  topic : {data['topic']}  tone: {data['tone']}")
            print(f"  hint  : {data['image_hint']}")
            print(f"  script ({len(data['reel_script'].split())} words):")
            for line in data["reel_script"].split(". "):
                print(f"    {line.strip()}.")
            print()
            return data

    raise RuntimeError(
        f"Claude did not call post_reel. Stop reason: {response.stop_reason}. "
        f"Content: {response.content}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fully autonomous factjot Reel — Claude decides everything."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Compose but skip upload and publish")
    parser.add_argument("--model", default="claude-opus-4-7",
                        help="Claude model to use (default: claude-opus-4-7)")
    parser.add_argument("--voice", default="en-GB-RyanNeural",
                        help="TTS voice")
    args = parser.parse_args()

    # Step 1: Let Claude decide what to post
    try:
        data = call_claude(args.model)
    except Exception as exc:
        print(f"ERROR: Claude API call failed: {exc}")
        return 1

    # Step 2: Build a fact-shaped dict the pipeline understands
    autonomous_fact = {
        "claim":        data["reel_script"][:300],   # unique per run, used for dedup
        "reel_script":  data["reel_script"],
        "reel_title":   data["reel_title"],
        "topic":        data["topic"],
        "tone":         data["tone"],
        "image_hint":   data["image_hint"],
        "quirky_score": 3,
        "allow_archival": False,
        "sources":      [],
        "autonomous":   True,
    }

    # Step 3: Run the standard pipeline
    return make_reel(
        topic=None,
        dry_run=args.dry_run,
        voice=args.voice,
        _autonomous=autonomous_fact,
    )


if __name__ == "__main__":
    sys.exit(main())
