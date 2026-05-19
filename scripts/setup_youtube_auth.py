"""One-time YouTube OAuth setup.

Reads the Google OAuth client secret JSON, opens a browser for you to
click "allow", captures the resulting refresh_token, and prints the
three secrets you need to set in GitHub Actions:

    YOUTUBE_CLIENT_ID
    YOUTUBE_CLIENT_SECRET
    YOUTUBE_REFRESH_TOKEN

Usage:
    python3 scripts/setup_youtube_auth.py /path/to/client_secret_*.json

Run this once. The refresh token is long-lived and rarely needs
regenerating (only if you revoke access in your Google account).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

# Scope for uploading videos. youtube.upload is the minimum needed.
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: setup_youtube_auth.py /path/to/client_secret.json", file=sys.stderr)
        return 1

    secret_path = Path(argv[1]).expanduser()
    if not secret_path.exists():
        print(f"ERROR: not found: {secret_path}", file=sys.stderr)
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), SCOPES)
    print("Opening browser for Google OAuth consent...")
    print("Sign in as thefactjot@gmail.com when prompted.")
    print("If a 'this app isnt verified' warning appears, click")
    print("'Advanced' -> 'Go to factjot-uploader (unsafe)' -> Allow.")
    print()
    creds = flow.run_local_server(
        port=0,
        prompt="consent",
        access_type="offline",
        login_hint="thefactjot@gmail.com",
    )

    if not creds.refresh_token:
        print("ERROR: no refresh_token returned. Did you authorise as the test user?", file=sys.stderr)
        return 1

    data = json.loads(secret_path.read_text(encoding="utf-8"))
    inst = data.get("installed") or data.get("web") or {}
    client_id     = inst.get("client_id", "")
    client_secret = inst.get("client_secret", "")

    print()
    print("=" * 64)
    print("SUCCESS. Add these three secrets to GitHub Actions:")
    print("=" * 64)
    print()
    print(f"YOUTUBE_CLIENT_ID:      {client_id}")
    print(f"YOUTUBE_CLIENT_SECRET:  {client_secret}")
    print(f"YOUTUBE_REFRESH_TOKEN:  {creds.refresh_token}")
    print()
    print("Run these three commands to set them via gh CLI:")
    print()
    print(f"  echo '{client_id}'     | gh secret set YOUTUBE_CLIENT_ID")
    print(f"  echo '{client_secret}' | gh secret set YOUTUBE_CLIENT_SECRET")
    print(f"  echo '{creds.refresh_token}' | gh secret set YOUTUBE_REFRESH_TOKEN")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
