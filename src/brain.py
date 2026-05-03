"""factjot brain integration.

Single entry point any pipeline code can import to:
    * check if a fact has already been published
    * check if an image has already been used
    * record a publish event
    * append an agent activity line to log.md

The brain on disk is at `insta-brain/`. This module is the only sanctioned way
to read/write its data ledgers. Hand-edit the markdown rules; let code touch
the .jsonl files.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from src.research.used_images import UsedImageLedger

log = logging.getLogger(__name__)


class DuplicatePostError(RuntimeError):
    """Raised when a claim that has already been published is about to post again.

    This is a hard block - callers must not catch and suppress this exception.
    Log it, alert, and abort. Never override.
    """

# Path constants are imported from src.core.paths (single source of truth).
# Local aliases preserved so the rest of this file reads naturally.
from src.core.paths import (
    REPO_ROOT,
    BRAIN_DIR,
    BRAIN_DATA as DATA_DIR,
    BRAIN_RULES as RULES_DIR,
    BRAIN_BANK as BANK_DIR,
    POSTED as POSTED_PATH,
    POSTED_QUOTES as POSTED_QUOTES_PATH,
    REELS_LEDGER as REELS_PATH,
    BRAIN_QUEUE as QUEUE_PATH,
    STATS as STATS_PATH,
    TRENDS as TRENDS_PATH,
    BRAIN_LOG as LOG_PATH,
    BRAIN_INBOX as INBOX_PATH,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalise_claim(claim: str) -> str:
    """Lower, collapse whitespace, strip punctuation. Used for hashing."""
    cleaned = re.sub(r"\s+", " ", claim).strip().lower()
    cleaned = cleaned.strip(" .!?,:;\"'")
    return cleaned


def claim_hash(claim: str) -> str:
    return hashlib.sha256(normalise_claim(claim).encode("utf-8")).hexdigest()


class Brain:
    """In-memory mirror of the brain's dedupe ledgers + write API."""

    def __init__(self, brain_dir: Path = BRAIN_DIR) -> None:
        self.brain_dir = Path(brain_dir)
        self.data_dir = self.brain_dir / "data"
        self.brain_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for path in (POSTED_PATH, QUEUE_PATH, STATS_PATH, TRENDS_PATH, LOG_PATH, INBOX_PATH):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)

        self._lock = Lock()
        self._posted_hashes: set[str] = set()
        self._posted_quote_hashes: set[str] = set()
        self._load_posted()
        self._load_posted_quotes()

        # Image dedupe - uses the canonical path from paths.py so brain and
        # image_fetcher both read/write the same file.
        self.images = UsedImageLedger()

    # ----- read APIs -----

    def is_fact_posted(self, claim: str) -> bool:
        return claim_hash(claim) in self._posted_hashes

    def is_quote_used(self, quote: str) -> bool:
        return claim_hash(quote) in self._posted_quote_hashes

    def quote_used_hashes(self) -> set[str]:
        return set(self._posted_quote_hashes)

    def is_image_used(self, *, url: str | None = None, sha256: str | None = None) -> bool:
        return self.images.is_used(url=url, sha256=sha256)

    def posted_hashes(self) -> set[str]:
        return set(self._posted_hashes)

    def posted_count(self) -> int:
        return len(self._posted_hashes)

    def assert_no_duplicate(self, claims: list[str]) -> None:
        """Hard gate - raises DuplicatePostError if ANY claim has already been posted.

        Reads directly from disk on every call (not from the in-memory cache)
        so it catches facts posted in other processes since this session started.

        Call this immediately before every Instagram API publish call. If it
        raises, abort the post unconditionally - no exceptions, no overrides.
        """
        # Fresh read from disk - bypasses the in-memory cache
        posted_on_disk: set[str] = set()
        for path in (POSTED_PATH, REELS_PATH):
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                        h = row.get("claim_hash") or claim_hash(row.get("claim", ""))
                        if h:
                            posted_on_disk.add(h)
                    except (json.JSONDecodeError, Exception):
                        continue

        duplicates = [c for c in claims if claim_hash(c) in posted_on_disk]
        if duplicates:
            raise DuplicatePostError(
                f"DUPLICATE BLOCKED - {len(duplicates)} claim(s) already posted:\n"
                + "\n".join(f"  • {c[:100]}" for c in duplicates)
            )

    def list_reel_claims(self) -> set[str]:
        """Return the set of fact claims already published as Reels (videos).

        Reads insta-brain/data/reels.jsonl. Used by make_reel.py to prevent
        the same fact being turned into a video twice.
        """
        claims: set[str] = set()
        if not REELS_PATH.exists():
            return claims
        with REELS_PATH.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    c = row.get("claim", "")
                    if c:
                        claims.add(c)
                except json.JSONDecodeError:
                    continue
        return claims

    # ----- write APIs -----

    def record_publish(self, *, post_id: str, ig_media_id: str, slides: list[dict]) -> None:
        """Append one row per slide claim. `slides` items must have:
            claim, topic, category, sources (list of urls)
        """
        when = _now_iso()
        with self._lock:
            with POSTED_PATH.open("a", encoding="utf-8") as fh:
                for slide in slides:
                    claim = slide["claim"]
                    h = claim_hash(claim)
                    row = {
                        "claim_hash": h,
                        "claim": claim,
                        "topic": slide.get("topic", ""),
                        "category": slide.get("category", ""),
                        "post_id": post_id,
                        "ig_media_id": ig_media_id,
                        "published_at": when,
                        "sources": slide.get("sources", []),
                    }
                    fh.write(json.dumps(row, ensure_ascii=True) + "\n")
                    self._posted_hashes.add(h)

    def append_log(self, line: str) -> None:
        """Prepend a line to insta-brain/log.md.

        Logging never raises. If disk write fails (full disk, permissions,
        locked file), we print a warning to stderr and continue. The whole
        point of this log is observability AFTER a publish; if it could
        crash a publish in flight it would be actively making things worse.
        """
        when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        entry = f"- {when} {line.strip()}\n"
        try:
            with self._lock:
                current = LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.exists() else ""
                # Newest at top, after the header.
                if current.startswith("# "):
                    head, _, body = current.partition("\n")
                    LOG_PATH.write_text(head + "\n\n" + entry + body.lstrip("\n"), encoding="utf-8")
                else:
                    LOG_PATH.write_text(entry + current, encoding="utf-8")
        except OSError as exc:
            import sys as _sys
            print(f"[brain.append_log] WARN failed to write log: {exc}", file=_sys.stderr)

    def append_queue(self, row: dict) -> None:
        with self._lock:
            with QUEUE_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=True) + "\n")

    def append_stats(self, row: dict) -> None:
        with self._lock:
            with STATS_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=True) + "\n")

    def record_quote_used(self, quote: str, *, attribution: str = "",
                          post_id: str = "", ig_media_id: str = "") -> None:
        h = claim_hash(quote)
        row = {
            "quote_hash": h,
            "quote": quote,
            "attribution": attribution,
            "post_id": post_id,
            "ig_media_id": ig_media_id,
            "ts": _now_iso(),
        }
        with self._lock:
            with POSTED_QUOTES_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=True) + "\n")
            self._posted_quote_hashes.add(h)

    # ----- internals -----

    def _load_posted(self) -> None:
        if not POSTED_PATH.exists():
            return
        with POSTED_PATH.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                h = row.get("claim_hash")
                if h:
                    self._posted_hashes.add(h)

    def _load_posted_quotes(self) -> None:
        POSTED_QUOTES_PATH.touch(exist_ok=True)
        with POSTED_QUOTES_PATH.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                h = row.get("quote_hash")
                if h:
                    self._posted_quote_hashes.add(h)


# Module-level singleton. Importing `from src.brain import brain` gives every
# caller the same in-memory ledger.
brain = Brain()
