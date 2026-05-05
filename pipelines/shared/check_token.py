"""Quick Meta token validity check.

Prints 'ok' if the token can hit the Instagram Graph API, 'invalid' otherwise.
Used as a pre-flight step in all posting workflows.

Exit code is always 0 -- callers decide what to do with the output string.
"""
from __future__ import annotations

import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv

load_dotenv()

token = os.environ.get("META_ACCESS_TOKEN", "").strip()
acct = os.environ.get("INSTAGRAM_ACCOUNT_ID", "").strip()
host = os.environ.get("META_GRAPH_HOST", "graph.instagram.com").strip()
ver = os.environ.get("META_GRAPH_VERSION", "v21.0").strip()

if not token or not acct:
    print("invalid")
    sys.exit(0)

url = "https://" + host + "/" + ver + "/" + acct + "?fields=id&access_token=" + token

try:
    urllib.request.urlopen(url, timeout=10)
    print("ok")
except urllib.error.HTTPError as exc:
    # 400/401 means bad token; any other HTTP error is still "invalid" for safety
    print("invalid")
except Exception:
    print("invalid")
