"""Centralised voice normaliser.

Single source of truth for caption / content normalisation. Every shipping
caption goes through `normalise()` immediately before publish so the
brand-voice rules from CLAUDE.md (no em-dashes, straight quotes, tidy
spacing) are enforced as a runtime guarantee, not just a lint convention.

Behaviour (idempotent, applied in order):

1. U+2014 (em dash) becomes ", " when there is whitespace on BOTH sides;
   otherwise it becomes "-" (hyphen). Em-dashes used as parenthetical
   separators read better as commas; em-dashes used as compound-word
   joiners read better as hyphens.
2. U+2013 (en dash) becomes "-" (hyphen). En-dashes typically join
   numbers / ranges (e.g. 2020 to 2021) where hyphen is the right
   replacement.
3. Smart quotes become straight quotes:
   U+201C / U+201D -> ASCII double-quote
   U+2018 / U+2019 -> ASCII apostrophe
4. Runs of 2 or more horizontal spaces inside a line collapse to a
   single space. Newlines and per-line leading whitespace are preserved.
5. Trailing whitespace is trimmed from every line.

Source-clean rule: this module follows the convention used by
src/content/reel_caption.py. Any em / en literal that appears in a
shipping string in this file is constructed via chr(0x2014) /
chr(0x2013) so the targeted em-dash linter
(scripts/check_em_dashes.py) reads the source as clean.
"""
from __future__ import annotations

import re

# Codepoint sentinels. Held as variables so this file passes the
# targeted em-dash linter even though the module is logically all about
# em / en handling.
_EM_DASH = chr(0x2014)  # U+2014 EM DASH
_EN_DASH = chr(0x2013)  # U+2013 EN DASH

_LDQ = chr(0x201C)  # left double quotation mark
_RDQ = chr(0x201D)  # right double quotation mark
_LSQ = chr(0x2018)  # left single quotation mark
_RSQ = chr(0x2019)  # right single quotation mark

# Match em-dash flanked by ASCII space on BOTH sides. Used for the
# parenthetical-comma swap. We require a literal space on each side so
# we do NOT collapse paragraph breaks (where a newline neighbours an
# em-dash). Anything not matching this falls through to the
# compound-joiner branch and becomes a hyphen.
_EM_PARENTHETICAL = re.compile(r" " + _EM_DASH + r" ")

# Two or more ASCII spaces preceded by a non-space character. The
# preceding-non-space lookbehind keeps leading indentation intact and
# only collapses interior runs (e.g. "hello    world" -> "hello world").
# Tabs and other whitespace are intentionally left untouched.
_MULTI_SPACE = re.compile(r"(?<=\S) {2,}")


def normalise(text: str) -> str:
    """Return `text` with brand-voice normalisation applied.

    See module docstring for the full behavioural contract. The function
    is idempotent: normalise(normalise(x)) == normalise(x) for any x.
    """
    if not text:
        return text

    # 1. Em-dash. Parenthetical (space-flanked) form first, then the
    # remainder become hyphens. Order matters: if we hyphenated first
    # we would lose the bothsides-spaces signal.
    out = _EM_PARENTHETICAL.sub(", ", text)
    out = out.replace(_EM_DASH, "-")

    # 2. En-dash. Always hyphen.
    out = out.replace(_EN_DASH, "-")

    # 3. Smart quotes to straight.
    out = out.replace(_LDQ, '"').replace(_RDQ, '"')
    out = out.replace(_LSQ, "'").replace(_RSQ, "'")

    # 4 + 5. Per-line: collapse multi-space runs, trim trailing
    # whitespace. Newlines and leading whitespace stay.
    cleaned_lines = [
        _MULTI_SPACE.sub(" ", line).rstrip()
        for line in out.split("\n")
    ]
    return "\n".join(cleaned_lines)
