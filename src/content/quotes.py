"""Closing-slide quote bank.

Reads `insta-brain/bank/quotes.md`, parses bullet lines, and picks a quote
that has not yet been published (per `insta-brain/data/posted_quotes.jsonl`).

Quote line formats supported:
    - The world is beautiful, and so are you.
    - "Be kind, for everyone you meet is fighting a hard battle." - Ian Maclaren
    - "It always seems impossible until it's done." — Nelson Mandela

Attribution is whatever follows the closing quote mark + dash separator.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from pathlib import Path

from src.brain import BRAIN_DIR, brain

QUOTES_PATH = BRAIN_DIR / "bank" / "quotes.md"

_LINE_RE = re.compile(r"^\s*-\s+(.*?)\s*$")
_ATTR_RE = re.compile(r"""
    ^
    (?:["“](?P<quote>.+?)["”])    # quoted body
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
                out.append(Quote(text=attr_m.group("quote").strip(),
                                  attribution=attr_m.group("attribution").strip()))
            else:
                # Plain originals — no attribution, may have surrounding quotes still.
                clean = body.strip("\"“”")
                out.append(Quote(text=clean, attribution=""))
        return out

    def pick_unused(self, *, rng: random.Random | None = None) -> Quote | None:
        rng = rng or random.Random()
        used = brain.quote_used_hashes()
        # Filter out used quotes by claim_hash equivalence.
        from src.brain import claim_hash
        fresh = [q for q in self._all if claim_hash(q.text) not in used]
        if not fresh:
            return None
        return rng.choice(fresh)

    def all_count(self) -> int:
        return len(self._all)

    def fresh_count(self) -> int:
        from src.brain import claim_hash
        used = brain.quote_used_hashes()
        return sum(1 for q in self._all if claim_hash(q.text) not in used)
