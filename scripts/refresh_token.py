"""Refresh the long-lived Instagram access token.

Instagram-login tokens last 60 days. Calling
`graph.instagram.com/refresh_access_token` returns a NEW 60-day token. Run
weekly (or any cadence < 60 days) to keep us out of expiry trouble.

Updates the `META_ACCESS_TOKEN` line in `.env` in place. Logs to brain.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.brain import brain

ENV_PATH = Path(".env")


def main() -> int:
    load_dotenv()
    old = os.getenv("META_ACCESS_TOKEN", "").strip()
    if not old:
        print("ABORT — META_ACCESS_TOKEN not set in .env")
        return 1

    resp = requests.get(
        "https://graph.instagram.com/refresh_access_token",
        params={"grant_type": "ig_refresh_token", "access_token": old},
        timeout=15,
    )
    if not resp.ok:
        print(f"Refresh failed ({resp.status_code}): {resp.text[:200]}")
        return 2

    body = resp.json()
    new = body.get("access_token")
    expires = int(body.get("expires_in", 0))
    if not new:
        print(f"Refresh response missing access_token: {body}")
        return 3

    # Rewrite .env in place — preserve everything else.
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    replaced = False
    for line in lines:
        if line.startswith("META_ACCESS_TOKEN="):
            out.append(f"META_ACCESS_TOKEN={new}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"META_ACCESS_TOKEN={new}")
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")

    days = expires // 86400 if expires else 60
    print(f"Token refreshed. New expiry: ~{days} days.")
    brain.append_log(f"token refreshed: new expiry ~{days} days")
    return 0


if __name__ == "__main__":
    sys.exit(main())
