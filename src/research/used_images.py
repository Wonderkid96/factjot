"""Append-only ledger of images we have already used.

We dedupe by both URL and content SHA-256 so re-encoded copies of the same
image (different URL, same pixels) still count as a duplicate.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


class UsedImageLedger:
    def __init__(self, path: str | None = None) -> None:
        from src.core.paths import USED_IMAGES
        path = path or str(USED_IMAGES)
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self._urls: set[str] = set()
        self._shas: set[str] = set()
        self._lock = Lock()
        self._load()

    def _load(self) -> None:
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("url"):
                    self._urls.add(row["url"])
                if row.get("sha256"):
                    self._shas.add(row["sha256"])

    @staticmethod
    def sha256_of(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def is_used(self, url: str | None = None, sha256: str | None = None) -> bool:
        with self._lock:
            if url and url in self._urls:
                return True
            if sha256 and sha256 in self._shas:
                return True
            return False

    def clear_post(self, post_id: str) -> None:
        """Remove all ledger entries for a given post_id and rewrite the file."""
        if not post_id:
            return
        with self._lock:
            lines: list[str] = []
            if self.path.exists():
                for line in self.path.read_text(encoding="utf-8").splitlines():
                    try:
                        row = json.loads(line)
                        if row.get("post_id") == post_id:
                            continue
                    except json.JSONDecodeError:
                        pass
                    lines.append(line)
            self.path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
            # Reload sets from the rewritten file
            self._urls.clear()
            self._shas.clear()
            self._load()

    def mark_used(self, *, url: str, sha256: str, provider: str,
                  post_id: str = "", slide_index: int = 0,
                  query: str = "") -> None:
        row = {
            "url": url,
            "sha256": sha256,
            "provider": provider,
            "post_id": post_id,
            "slide_index": slide_index,
            "query": query,
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=True) + "\n")
            self._urls.add(url)
            self._shas.add(sha256)
