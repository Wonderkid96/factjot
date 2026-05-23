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
    BRAIN_DIR,
    POSTED as POSTED_PATH,
    POSTED_QUOTES as POSTED_QUOTES_PATH,
    REELS_LEDGER as REELS_PATH,
    LIST_POSTS as LIST_POSTS_PATH,
    BRAIN_QUEUE as QUEUE_PATH,
    STATS as STATS_PATH,
    TRENDS as TRENDS_PATH,
    BRAIN_LOG as LOG_PATH,
    BRAIN_INBOX as INBOX_PATH,
    SUBJECT_KEYS as SUBJECT_KEYS_PATH,
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


# ----- subject fingerprint dedup (audit Phase C.3) -----------------
#
# Why a fingerprint and not a full claim hash? claim_hash is exact-match;
# the prompt-level dedup guard already covers exact reposts. The 2026-05-06
# incident shipped 8 carousels about "phone with no apps" under different
# slugs because each was rephrased enough that exact hashing did not catch
# the duplicate. The fingerprint reduces a subject to its top 3-5 longest
# content tokens, sorted alphabetically, so two posts about the same
# subject framed differently produce overlapping fingerprints.
#
# This is a heuristic. False positives are acceptable (the agent skips a
# slot, preferable to a duplicate). False negatives are the bigger concern.

_FINGERPRINT_STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "and", "or",
    "but", "with", "from", "as", "by", "that", "this", "these", "those",
    "is", "was", "were", "are", "be", "been", "being", "has", "have",
    "had", "do", "did", "does", "will", "would", "could", "should",
    "may", "might", "can", "must", "not", "no", "what", "which", "who",
    "when", "where", "why", "how", "you", "your", "yours", "my", "our",
    "we", "us", "they", "them", "their",
})

_FINGERPRINT_MIN_TOKEN_LEN = 3
_FINGERPRINT_MAX_TOKENS    = 5


def subject_fingerprint(text: str) -> str:
    """Return a normalised noun-phrase fingerprint for `text`.

    Approach:
        1. Lowercase.
        2. Strip punctuation (keep letters and digits).
        3. Tokenise on whitespace.
        4. Drop common stopwords.
        5. Drop tokens shorter than 3 chars or all-digit.
        6. Take the top 3-5 longest remaining tokens, sort alphabetically,
           join with "-".

    Empty / stopwords-only / digits-only input returns "".
    """
    if not text:
        return ""
    lowered = text.lower()
    # Replace any character that is not a letter or digit with a space.
    # This handles punctuation, hyphens, smart quotes, em-dashes, etc.
    cleaned = re.sub(r"[^a-z0-9]+", " ", lowered)
    tokens = cleaned.split()
    kept: list[str] = []
    for tok in tokens:
        if len(tok) < _FINGERPRINT_MIN_TOKEN_LEN:
            continue
        if tok in _FINGERPRINT_STOPWORDS:
            continue
        if tok.isdigit():
            continue
        kept.append(tok)
    if not kept:
        return ""
    # Sort by (-length, alphabetical) so longest tokens win, with stable
    # alphabetical ordering when lengths tie. Then take top N.
    kept_sorted = sorted(set(kept), key=lambda t: (-len(t), t))
    top = kept_sorted[:_FINGERPRINT_MAX_TOKENS]
    # Inputs with fewer than 3 distinct content tokens are too thin to
    # fingerprint reliably. Return what we have anyway; the all-stopwords /
    # all-digit case returned "" earlier. The collision check uses Jaccard
    # similarity which already tolerates short fingerprints.
    return "-".join(sorted(top))


def fingerprint_similarity(fp1: str, fp2: str) -> float:
    """Return Jaccard similarity in [0, 1] between two fingerprints.

    Empty fingerprint on either side returns 0.0 (cannot match what we
    cannot characterise).
    """
    if not fp1 or not fp2:
        return 0.0
    set1 = set(fp1.split("-"))
    set2 = set(fp2.split("-"))
    if not set1 or not set2:
        return 0.0
    intersection = set1 & set2
    union = set1 | set2
    if not union:
        return 0.0
    return len(intersection) / len(union)


class Brain:
    """In-memory mirror of the brain's dedupe ledgers + write API."""

    def __init__(self, brain_dir: Path = BRAIN_DIR) -> None:
        self.brain_dir = Path(brain_dir)
        self.data_dir = self.brain_dir / "data"
        self.brain_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for path in (POSTED_PATH, QUEUE_PATH, STATS_PATH, TRENDS_PATH, LOG_PATH, INBOX_PATH,
                     SUBJECT_KEYS_PATH):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)

        self._lock = Lock()
        self._posted_hashes: set[str] = set()
        self._posted_quote_hashes: set[str] = set()
        self._subject_keys: set[str] = set()
        self._load_posted()
        self._load_posted_quotes()
        self._load_subject_keys()

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

    # ----- subject-key dedup (permanent, all-time) -----

    def is_subject_used(self, key: str) -> bool:
        """Return True if this canonical subject key has ever been posted."""
        return key.strip().lower() in self._subject_keys

    def find_subject_collision(self, key: str) -> str | None:
        """Return the first stored key that is too similar to `key`, or None.

        Uses Jaccard similarity on raw hyphen-split tokens at threshold 0.7.
        Catches near-identical variants (typos, singular/plural) without
        blocking genuinely different stories that share common words like
        'great', 'flood', or a year number.
        """
        candidate_tokens = set((key.strip().lower()).split("-")) - {""}
        if not candidate_tokens:
            return None
        for stored in self._subject_keys:
            stored_tokens = set(stored.split("-")) - {""}
            if not stored_tokens:
                continue
            intersection = candidate_tokens & stored_tokens
            union = candidate_tokens | stored_tokens
            if union and len(intersection) / len(union) >= 0.7:
                return stored
        return None

    def assert_no_duplicate(self, claims: list[str]) -> None:
        """Hard gate - raises DuplicatePostError if ANY claim has already been posted.

        Reads directly from disk on every call (not from the in-memory cache)
        so it catches facts posted in other processes since this session started.

        Call this immediately before every Instagram API publish call. If it
        raises, abort the post unconditionally - no exceptions, no overrides.
        """
        # Fresh read from disk - bypasses the in-memory cache
        posted_on_disk: set[str] = set()
        for path in (POSTED_PATH, REELS_PATH, LIST_POSTS_PATH):
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

    def record_subject_key(self, key: str, *, post_id: str = "", published_at: str = "") -> None:
        """Append one subject_key entry to the permanent dedup ledger.

        Idempotent: if the key is already in-memory it is not written again.
        Call this after a successful publish, not before.
        """
        key = key.strip().lower()
        if not key:
            return
        if key in self._subject_keys:
            return
        row = {
            "subject_key": key,
            "post_id": post_id,
            "published_at": published_at or _now_iso(),
        }
        with self._lock:
            with SUBJECT_KEYS_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=True) + "\n")
            self._subject_keys.add(key)

    def record_publish(self, *, post_id: str, ig_media_id: str, slides: list[dict],
                       subject_key: str = "") -> None:
        """Append one row per slide claim. `slides` items must have:
            claim, topic, category, sources (list of urls)
        Optional per-slide fields written through if present:
            reel_title (subject identity for reels - feeds fingerprint dedup),
            list_title, list_subtitle, list_fingerprint, list_items
        Optional kwarg:
            subject_key (canonical dedup identifier, permanent all-time block)
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
                    # Pass through subject-identity fields when the caller
                    # supplies them. Reels supply reel_title; carousels
                    # do not, so the field is omitted rather than blank.
                    reel_title = slide.get("reel_title")
                    if reel_title:
                        row["reel_title"] = reel_title
                    for key in ("list_title", "list_subtitle", "list_fingerprint", "list_items"):
                        value = slide.get(key)
                        if value:
                            row[key] = value
                    sk = (slide.get("subject_key") or subject_key or "").strip().lower()
                    if sk:
                        row["subject_key"] = sk
                    fh.write(json.dumps(row, ensure_ascii=True) + "\n")
                    self._posted_hashes.add(h)
        # Record subject key in its own permanent ledger (outside the POSTED lock
        # so record_subject_key acquires the lock independently).
        sk = subject_key.strip().lower() if subject_key else ""
        if not sk:
            # Fall back to slide-level key if kwarg was not supplied.
            for slide in slides:
                sk = (slide.get("subject_key") or "").strip().lower()
                if sk:
                    break
        if sk:
            self.record_subject_key(sk, post_id=post_id, published_at=when)

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

    def _load_subject_keys(self) -> None:
        SUBJECT_KEYS_PATH.touch(exist_ok=True)
        with SUBJECT_KEYS_PATH.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                k = row.get("subject_key", "")
                if k:
                    self._subject_keys.add(k.strip().lower())


# Module-level singleton. Importing `from src.brain import brain` gives every
# caller the same in-memory ledger.
brain = Brain()
