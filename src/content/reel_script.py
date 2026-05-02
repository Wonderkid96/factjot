"""Convert a raw fact claim into a speech-friendly Reel voice-over script.

ElevenLabs reads punctuation as performance direction:
  .   = full stop, breath, neutral
  ,   = short pause, comma breath
  ...  = longer pause, anticipation, drama
  ?   = rising inflection
  !   = emphasis (use sparingly)

Narrative build strategy (documentary-style):
  1. Split the claim into logical beats — one idea per sentence.
  2. Isolate comparisons ("the same as", "equivalent to") as their own
     revelation beat so the listener gets the setup before the wow moment.
  3. Cap sentences at ~12 words; split at natural clause boundaries.
  4. Apply contractions to sound human, strip filler adjectives.
  5. Add ellipses before contrast/reveal words for dramatic pacing.
  6. Return clean string ready for ElevenLabs API.

Usage:
    from src.content.reel_script import to_voice_script
    script = to_voice_script(raw_claim)
"""
from __future__ import annotations

import re


# ------------------------------------------------------------------ #
# Contractions — written prose to spoken shortening
# ------------------------------------------------------------------ #
_CONTRACTIONS = {
    r"\bcould not\b":   "couldn't",
    r"\bwould not\b":   "wouldn't",
    r"\bshould not\b":  "shouldn't",
    r"\bdid not\b":     "didn't",
    r"\bdoes not\b":    "doesn't",
    r"\bdo not\b":      "don't",
    r"\bwill not\b":    "won't",
    r"\bwas not\b":     "wasn't",
    r"\bwere not\b":    "weren't",
    r"\bhave not\b":    "haven't",
    r"\bhas not\b":     "hasn't",
    r"\bhad not\b":     "hadn't",
    r"\bcan not\b":     "can't",
    r"\bcannot\b":      "can't",
    r"\bthey are\b":    "they're",
    r"\bthey have\b":   "they've",
    r"\bit is\b":       "it's",
    r"\bthat is\b":     "that's",
    r"\bwho is\b":      "who's",
    r"\bwhat is\b":     "what's",
    r"\bhe is\b":       "he's",
    r"\bshe is\b":      "she's",
    r"\bwe are\b":      "we're",
    r"\byou are\b":     "you're",
}

# Filler words that add no spoken value
_FILLERS = [
    r"\bin the world\b",
    r"\bit is worth noting that\b",
    r"\binterestingly\b",
    r"\bremarkably\b",
    r"\bsurprisingly\b",
    r"\bincredibly\b",
    r"\bamazingly\b",
    r"\bfascinating(?:ly)?\b",
    r"\bnot(?:ably|eworthily)\b",
    r"\bvery\b",
    r"\bextremely\b",
    r"\bquite\b",
]

# Comparison markers — split the sentence here to create a revelation beat
_COMPARISON_RE = re.compile(
    r",\s*(?:"
    r"the same as|equivalent to|roughly equal to|which is roughly|"
    r"or enough (?:to|for)|that could|which could"
    r")\b",
    re.IGNORECASE,
)

# Clause split for very long sentences
_CLAUSE_SPLIT = re.compile(
    r",\s*(which|who|where|when|although|because|despite|though|since|as)\b",
    re.IGNORECASE,
)


# ------------------------------------------------------------------ #
# Public API
# ------------------------------------------------------------------ #

def to_voice_script(claim: str) -> str:
    """Return an ElevenLabs-optimised VO script from the raw claim.

    Applies: contractions, filler removal, narrative beat structuring
    (comparison isolation, sentence capping), and dramatic pause markers.
    """
    text = _strip_markup(claim)
    text = _apply_contractions(text)
    text = _remove_fillers(text)
    text = _structure_beats(text)
    text = _add_drama(text)
    text = _ensure_terminal_punct(text)
    text = _clean_whitespace(text)
    return text


def estimate_duration_s(script: str, wpm: int = 145) -> float:
    """Rough duration estimate at ElevenLabs delivery pace."""
    return (len(script.split()) / wpm) * 60


# ------------------------------------------------------------------ #
# Beat structure — the core narrative shaper
# ------------------------------------------------------------------ #

def _structure_beats(text: str) -> str:
    """Break the text into punchy documentary beats.

    Process:
      1. Split at existing sentence boundaries.
      2. For each sentence, isolate any comparison ("the same as ...") as
         a separate revelation beat so the listener gets setup then payoff.
      3. Cap any remaining long sentence at ~12 words at a natural break.
      4. Join all beats with a single space — punctuation handles pauses.
    """
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    beats: list[str] = []
    for sent in sentences:
        for sub in _split_comparison(sent):
            beats.extend(_cap_sentence(sub))
    return " ".join(beats)


def _split_comparison(sent: str) -> list[str]:
    """Split 'X weighs 4 billion tonnes, the same as every car on Earth'
    into ['X weighs 4 billion tonnes.', 'The same as every car on Earth.']

    This makes the listener absorb the stat before hearing the analogy,
    which lands harder than reading both in one breath.
    """
    m = _COMPARISON_RE.search(sent)
    if m and len(sent) > 50:
        left = sent[:m.start()].rstrip(".,") + "."
        right = sent[m.start() + 2:].strip()
        if right and not right[0].isupper():
            right = right[0].upper() + right[1:]
        if not right.endswith((".", "!", "?")):
            right += "."
        return [left, right]

    # Also split very long sentences at subordinate clauses
    m2 = _CLAUSE_SPLIT.search(sent)
    if m2 and len(sent) > 110:
        left = sent[:m2.start()].rstrip(".,") + "."
        right = sent[m2.start() + 2:].strip()
        if right and not right[0].isupper():
            right = right[0].upper() + right[1:]
        return [left, right]

    return [sent]


def _cap_sentence(sent: str, max_words: int = 12) -> list[str]:
    """Split a sentence over max_words words at the most natural break."""
    words = sent.split()
    if len(words) <= max_words:
        return [sent]

    # Find first coordinating conjunction after word 5
    for i in range(5, len(words) - 2):
        w = words[i].lower().rstrip(".,;:")
        if w in ("and", "but", "so", "while", "as", "with", "or"):
            left = " ".join(words[:i]).rstrip(",") + "."
            right = " ".join(words[i:]).strip()
            if right and not right[0].isupper():
                right = right[0].upper() + right[1:]
            return [left, right]

    return [sent]


# ------------------------------------------------------------------ #
# Drama layer — ElevenLabs pause and emphasis signals
# ------------------------------------------------------------------ #

def _add_drama(text: str) -> str:
    """Insert pauses at pivots for dramatic pacing.

    Uses a single comma-breath (,) rather than ellipsis (...) at most
    pivots. ElevenLabs at low-stability settings interprets '...' as a
    very long hold (2-3s) which sounds unnatural in short-form video.
    A comma creates a brief, natural breath without killing the momentum.
    Reserve '...' only for the single biggest reveal in the script.
    """
    # Pivot words: brief comma breath before them
    text = re.sub(
        r"\.\s+(But|And then|Then|Until|Except|Nobody|No one|Nothing|He was|She was)\b",
        r". \1",
        text,
    )

    # Collapse any accidental over-punctuation (.... → ...)
    text = re.sub(r"\.{4,}", "...", text)

    return text


# ------------------------------------------------------------------ #
# Low-level helpers
# ------------------------------------------------------------------ #

def _strip_markup(text: str) -> str:
    return re.sub(r"\[/?[ih]\]", "", text).strip()


def _apply_contractions(text: str) -> str:
    for pattern, replacement in _CONTRACTIONS.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def _remove_fillers(text: str) -> str:
    for pattern in _FILLERS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    return text


def _ensure_terminal_punct(text: str) -> str:
    text = text.rstrip()
    if text and text[-1] not in ".!?":
        text += "."
    return text


def _clean_whitespace(text: str) -> str:
    text = re.sub(r"[ \t]{2,}", " ", text)   # collapse multi-spaces to one
    text = re.sub(r" ,", ",", text)
    text = re.sub(r" \.", ".", text)
    return text.strip()
