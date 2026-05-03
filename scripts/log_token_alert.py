"""Write a CRITICAL token-invalid alert to the brain log.

Called from workflow Verify Meta token steps when check_token.py reports
the token is invalid or expired. Always exits 0 -- the calling workflow
step handles the exit 1 separately.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.brain import brain

brain.append_log(
    "CRITICAL: Meta token invalid -- all posts will fail until refreshed. "
    "Visit developers.facebook.com and run refresh_token.py immediately."
)
