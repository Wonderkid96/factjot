from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.core.config import load_config


def main() -> None:
    cfg = load_config()
    checks = {
        "INSTAGRAM_ACCOUNT_ID": bool(cfg.env["INSTAGRAM_ACCOUNT_ID"]),
        "FACEBOOK_PAGE_ID": bool(cfg.env["FACEBOOK_PAGE_ID"]),
        "META_ACCESS_TOKEN": bool(cfg.env["META_ACCESS_TOKEN"]),
    }
    for key, ok in checks.items():
        print(f"{key}: {'OK' if ok else 'MISSING'}")

    if all(checks.values()):
        print("Meta setup looks complete.")
    else:
        print("Complete account linking and add credentials in .env before publishing.")


if __name__ == "__main__":
    main()
