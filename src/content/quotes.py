"""Closing-slide quote bank.

Reads `insta-brain/bank/quotes.md`, parses bullet lines, and picks a quote
that has not yet been published (per `insta-brain/data/posted_quotes.jsonl`).

Quote line formats supported:
    - The world is beautiful, and so are you.
    - "Be kind, for everyone you meet is fighting a hard battle." - Ian Maclaren
    - "It always seems impossible until it's done." - Nelson Mandela

Attribution is whatever follows the closing quote mark + dash separator.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from pathlib import Path

from src.brain import BRAIN_DIR, brain
from src.content.voice_normaliser import normalise

QUOTES_PATH = BRAIN_DIR / "bank" / "quotes.md"

_LINE_RE = re.compile(r"^\s*-\s+(.*?)\s*$")
_ATTR_RE = re.compile(r"""
    ^
    (?:["“](?P<quote>.+?)["”])    # quoted body (straight or curly quotes)
    \s*[—–\-]\s*                  # em/en/hyphen separator
    (?P<attribution>.+?)
    \s*$
""", re.VERBOSE)


@dataclass
class Quote:
    text: str
    attribution: str = ""

    @property
    def display(self) -> str:
        return self.text


class QuoteBank:
    def __init__(self, path: Path = QUOTES_PATH) -> None:
        self.path = Path(path)
        self._all = self._load()
        # Session-level picks: quotes selected during this planning run but not
        # yet written to posted_quotes.jsonl (that only happens at publish time).
        # Without this, every carousel in a plan_week run sees the same available
        # pool and can receive the same quote. This set grows across calls within
        # a single process lifetime.
        self._session_hashes: set[str] = set()

    def _load(self) -> list[Quote]:
        if not self.path.exists():
            return []
        out: list[Quote] = []
        for raw_line in self.path.read_text(encoding="utf-8").splitlines():
            m = _LINE_RE.match(raw_line)
            if not m:
                continue
            body = m.group(1).strip()
            attr_m = _ATTR_RE.match(body)
            if attr_m:
                # Apply the shared voice normaliser at parse time so
                # downstream consumers (closing-slide renderer, carousel
                # caption builder, etc.) all see brand-safe quote text:
                # smart quotes straightened, em / en dashes resolved,
                # spacing tidied. Replaces the ad-hoc per-call cleanup
                # that used to live in callers.
                out.append(Quote(
                    text=normalise(attr_m.group("quote").strip()),
                    attribution=normalise(attr_m.group("attribution").strip()),
                ))
            else:
                # Plain originals: no attribution, strip any surrounding quote chars.
                clean = body.strip('"“”')
                out.append(Quote(text=normalise(clean), attribution=""))
        return out

    def pick_unused(self, *, rng: random.Random | None = None) -> Quote | None:
        """Return a quote not yet published OR already assigned this session.

        Checks two exclusion sets:
          1. posted_quotes.jsonl on disk (quotes already published).
          2. _session_hashes (quotes handed out in this process run but not
             yet committed to disk, e.g. during plan_week where 14 carousels
             are generated before any are published).

        The picked quote is immediately added to _session_hashes so the next
        call in the same session cannot pick the same one.
        """
        rng = rng or random.Random()
        from src.brain import claim_hash
        used = brain.quote_used_hashes() | self._session_hashes
        fresh = [q for q in self._all if claim_hash(q.text) not in used]
        if not fresh:
            # All quotes exhausted including session picks. Fall back to only
            # excluding published ones so the bot does not go silent.
            used = brain.quote_used_hashes()
            fresh = [q for q in self._all if claim_hash(q.text) not in used]
        if not fresh:
            return None
        picked = rng.choice(fresh)
        self._session_hashes.add(claim_hash(picked.text))
        return picked

    def all_count(self) -> int:
        return len(self._all)

    def fresh_count(self) -> int:
        from src.brain import claim_hash
        used = brain.quote_used_hashes()
        return sum(1 for q in self._all if claim_hash(q.text) not in used)
