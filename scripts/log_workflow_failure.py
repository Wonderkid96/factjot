"""Log a GitHub Actions workflow failure to insta-brain/log.md.

Called by the `Capture failure to brain log` step in every workflow when a
job fails. Reads context from env vars set by the workflow:

    WORKFLOW_FILE  e.g. ".github/workflows/reel.yml"
    RUN_ID         e.g. "25260723991"
    TRIGGER        e.g. "schedule" / "workflow_dispatch" / "push"
    REF            e.g. "main"

Best-effort. Never raises — failure to log shouldn't itself fail the workflow.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    workflow = os.environ.get("WORKFLOW_FILE", "?")
    run_id = os.environ.get("RUN_ID", "?")
    trigger = os.environ.get("TRIGGER", "?")
    ref = os.environ.get("REF", "?")
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv()
    except Exception:
        pass
    try:
        from src.brain import brain  # type: ignore
        brain.append_log(
            f"WORKFLOW FAILED: {workflow} | run={run_id} | "
            f"trigger={trigger} | ref={ref}"
        )
        print("Failure logged to brain.")
    except Exception as exc:
        print(f"Could not log failure: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
