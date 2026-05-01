from __future__ import annotations

import json
import os
from pathlib import Path


def assert_brand_guidelines_locked(lock_path: str = "brand/visual_guidelines.lock.json") -> None:
    lock = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    if not lock.get("locked", True):
        return
    key_name = lock.get("unlock_env_var", "BRAND_GUIDELINES_UNLOCK_KEY")
    # Only owner can opt-in to edits by setting local env var.
    if os.getenv(key_name):
        return
