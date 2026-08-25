"""Thin wrapper around the local `claude` CLI for one-shot judge/classifier calls.

Deliberately NOT the Anthropic Python SDK. `weird_bit_gate` and
`interestingness_ranker` call Claude through the CLI binary already
installed and authenticated on this machine (subscription-backed session,
OAuth, or keychain), not an ANTHROPIC_API_KEY. This is a hard requirement,
not a style choice: `--bare` mode would be the leaner, cheaper invocation,
but `claude --help` states it plainly -- "Anthropic auth is strictly
ANTHROPIC_API_KEY or apiKeyHelper via --settings (OAuth and keychain are
never read)" in `--bare` mode. Using `--bare` would silently force API-key
auth and defeat the point, so this module never passes it.

Trade-off worth knowing: without `--bare`, every call loads this repo's
full CLAUDE.md and project context (measured ~31k cache-creation tokens on
a two-word test prompt from this project root), which a raw API call would
not. For the 2-3 calls/day these gates make, that costs a few seconds of
latency and draws on the local Claude subscription's usage, not per-token
API billing. `--tools ""` hard-disables tool use, so the worst case is a
slower or slightly unfocused judge, never an agentic action.

Every failure mode returns None so callers can fail open: CLI not on PATH,
non-zero exit, timeout, malformed JSON, or an explicit `is_error` in the
response envelope.

A second entry point, ``call_claude_cli_with_image``, covers the vision
case (thumbnail-frame scoring). The CLI has no raw image-attachment flag
outside `--bare`, so instead of disabling tools it grants only the `Read`
tool, scoped to the image's own directory via `--add-dir`, and the prompt
tells the model which file to Read. Confirmed working against a real
mismatched frame during development: asked to score an unrelated car-
dashboard photo against a pine-tree story, it read the file and returned
`score=0` with the correct reason. Costs more than the text-only path
(observed ~16s and ~$0.12 of subscription usage per image, mostly cache-
creation for project context) so it defaults to a longer timeout.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

_DEFAULT_TIMEOUT_S = 60
_IMAGE_DEFAULT_TIMEOUT_S = 90


def _run_cli(cmd: list[str], timeout: int) -> dict | None:
    """Shared subprocess + envelope handling for both entry points below."""
    if shutil.which("claude") is None:
        print("  [claude-cli] `claude` not found on PATH", flush=True)
        return None

    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        print(f"  [claude-cli] call failed, failing open: {str(exc)[:120]}", flush=True)
        return None

    if res.returncode != 0:
        print(
            f"  [claude-cli] exit {res.returncode}: {res.stderr.strip()[:200]}",
            flush=True,
        )
        return None

    try:
        envelope = json.loads(res.stdout)
    except json.JSONDecodeError:
        print("  [claude-cli] malformed JSON on stdout, failing open", flush=True)
        return None

    if envelope.get("is_error"):
        print(f"  [claude-cli] is_error: {str(envelope.get('result'))[:200]}", flush=True)
        return None

    return envelope


def call_claude_cli(
    prompt: str,
    model: str = "sonnet",
    json_schema: dict | None = None,
    timeout: int = _DEFAULT_TIMEOUT_S,
) -> dict | None:
    """Run one non-interactive `claude -p` call and return the parsed envelope.

    ``model`` accepts the CLI's short aliases ('sonnet', 'opus', 'haiku',
    'fable') or a full model ID. When ``json_schema`` is given, the CLI
    validates its own output against it and the returned envelope carries a
    ``structured_output`` key holding the parsed, schema-conformant object --
    no downstream JSON-extraction regex needed. Without a schema, read the
    plain-text answer from the envelope's ``result`` key.

    Returns ``None`` on any failure: binary missing, non-zero exit, timeout,
    unparseable stdout, or an ``is_error`` envelope. Callers must treat that
    as "the judge could not run" and fail open, never as "the answer was no".
    """
    cmd = [
        "claude", "-p", prompt,
        "--model", model,
        "--output-format", "json",
        "--no-session-persistence",
        "--tools", "",
    ]
    if json_schema is not None:
        cmd += ["--json-schema", json.dumps(json_schema)]
    return _run_cli(cmd, timeout)


def call_claude_cli_with_image(
    image_path: Path,
    prompt: str,
    model: str = "haiku",
    json_schema: dict | None = None,
    timeout: int = _IMAGE_DEFAULT_TIMEOUT_S,
) -> dict | None:
    """Run one non-interactive `claude -p` call with vision via the `Read` tool.

    ``prompt`` must tell the model to Read the file at ``image_path`` --
    this function only wires up permission to do so (``--allowedTools Read``
    scoped to the image's parent directory via ``--add-dir``). Same envelope
    shape and same fail-open contract as ``call_claude_cli``.
    """
    image_path = Path(image_path)
    if not image_path.is_file():
        print(f"  [claude-cli] image not found: {image_path}", flush=True)
        return None

    cmd = [
        "claude", "-p", prompt,
        "--model", model,
        "--output-format", "json",
        "--no-session-persistence",
        "--allowedTools", "Read",
        "--add-dir", str(image_path.parent),
    ]
    if json_schema is not None:
        cmd += ["--json-schema", json.dumps(json_schema)]
    return _run_cli(cmd, timeout)
