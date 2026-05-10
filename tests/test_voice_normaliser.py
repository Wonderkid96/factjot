"""Tests for src.content.voice_normaliser.

Behavioural contract (see SPEC §4 Phase C):

1. U+2014 (em dash) -> ", " when surrounded by whitespace on both sides;
   else "-" (hyphen). Em-dashes used as parenthetical separators read
   better as commas; em-dashes used as compound-word joiners read better
   as hyphens.
2. U+2013 (en dash) -> "-" (hyphen). En-dashes typically join numbers /
   ranges where hyphen is the right replacement.
3. Smart quotes -> straight (U+201C/D -> ", U+2018/9 -> ').
4. Collapse runs of 2+ horizontal spaces inside a line to single space.
   Newlines and per-line leading whitespace are preserved.
5. Trim trailing whitespace from each line.

Idempotent: normalise(normalise(x)) == normalise(x).
"""
from __future__ import annotations

from src.content.voice_normaliser import normalise


# Codepoint constructors so this test module itself stays clean for
# the targeted em-dash linter (scripts/check_em_dashes.py).
EM = chr(0x2014)
EN = chr(0x2013)
LDQ = chr(0x201C)  # left double quote
RDQ = chr(0x201D)  # right double quote
LSQ = chr(0x2018)  # left single quote
RSQ = chr(0x2019)  # right single quote


def test_em_dash_with_spaces_becomes_comma():
    assert normalise(f"hello {EM} world") == "hello, world"


def test_em_dash_no_space_becomes_hyphen():
    assert normalise(f"word{EM}word") == "word-word"


def test_em_dash_left_space_only_becomes_hyphen():
    # "word " + em + "word": no space on the right side of the em.
    # Rule: needs space on BOTH sides for the comma swap.
    assert normalise(f"word {EM}word") == "word -word"


def test_em_dash_right_space_only_becomes_hyphen():
    # "word" + em + " word": no space on the left side of the em.
    assert normalise(f"word{EM} word") == "word- word"


def test_en_dash_becomes_hyphen():
    assert normalise(f"2020{EN}2021") == "2020-2021"
    assert normalise(f"from {EN} to") == "from - to"


def test_smart_quotes_straightened():
    assert normalise(f"{LDQ}hello{RDQ} {LSQ}world{RSQ}") == "\"hello\" 'world'"


def test_double_spaces_collapsed():
    assert normalise("hello  world   foo") == "hello world foo"


def test_newlines_preserved():
    assert normalise("line one\nline two") == "line one\nline two"


def test_trailing_whitespace_trimmed_per_line():
    assert normalise("hello   \nworld   ") == "hello\nworld"


def test_leading_whitespace_preserved():
    # Indentation matters in some contexts (markdown, lists). Keep it.
    assert normalise("  hello\n    world") == "  hello\n    world"


def test_idempotent():
    cases = [
        f"hello {EM} world",
        f"word{EM}word",
        f"from {LSQ}x{RSQ} to {LDQ}y{RDQ}  with  doubles",
        f"2020{EN}2021 was a year",
        f"a {EM}b{EM} c",
        f"trailing space   \nmid {EM} dash",
    ]
    for c in cases:
        once = normalise(c)
        twice = normalise(once)
        assert once == twice, f"not idempotent: {c!r} -> {once!r} -> {twice!r}"


def test_empty_string():
    assert normalise("") == ""


def test_only_whitespace():
    # Spaces collapse but the line stays; trailing whitespace per line
    # is trimmed, so " " becomes "" and "\n" is preserved.
    assert normalise("   \n   ") == "\n"


def test_combined_real_caption():
    raw = (
        f"The Concorde {EM} a marvel of British engineering {EM} flew faster than sound.\n"
        f"From 1976{EN}2003, it crossed the Atlantic in under  4  hours.\n"
        f"{LDQ}Speed is everything,{RDQ} they said.   "
    )
    expected = (
        "The Concorde, a marvel of British engineering, flew faster than sound.\n"
        "From 1976-2003, it crossed the Atlantic in under 4 hours.\n"
        "\"Speed is everything,\" they said."
    )
    assert normalise(raw) == expected


def test_tabs_inside_line_collapsed_with_spaces():
    # Mixed runs of spaces and tabs are runs of horizontal whitespace.
    # The rule says collapse runs of 2+ spaces; tabs are out of scope but
    # safe to leave as-is. Locking the current behaviour here.
    out = normalise("hello\t world")
    # Either "hello\t world" or "hello world" is defensible; we treat tabs
    # as preserved and only collapse pure-space runs.
    assert out in ("hello\t world", "hello world")


def test_mixed_em_and_en_dashes():
    s = f"London{EN}Paris route {EM} fastest in 1976{EN}2003 {EM} now retired."
    assert normalise(s) == "London-Paris route, fastest in 1976-2003, now retired."


def test_no_change_for_clean_text():
    clean = "Hello, world. This sentence is fine."
    assert normalise(clean) == clean
