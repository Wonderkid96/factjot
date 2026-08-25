"""Tests for the mandatory subject_key dedup layer.

Behavioural contract:
- run_reel / run_carousel with a subject_key already in the used set are
  hard-blocked before the pipeline subprocess fires.
- Fuzzy Jaccard matching at 0.7 blocks near-identical variants (e.g. 'radium-girl'
  blocked by 'radium-girls').
- An unrelated subject_key is not blocked.
- In-session poisoning blocks a second dispatch before the on-disk ledger
  is updated (same fix pattern as fingerprint dedup).
- An empty or missing subject_key does not crash (backward compat for
  manual CLI calls that predate this field).

Note on Brain isolation: Brain's file paths are module-level constants
(SUBJECT_KEYS_PATH etc.). Tests that write subject keys patch those
constants to temp files to avoid polluting the real ledger.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scripts.autonomous_agent as agent
from src.brain import Brain

# Minimal valid hint satisfying the 3-line / 8-char-per-line quality gate.
_VALID_HINT = "Cold War submarine fleet at dock\nSoviet naval base 1980s\nsubmarine conning tower portrait"
_VALID_SCRIPT = (
    "In 1960, the CIA failed to turn a cat into a listening device after spending 20 million dollars. "
    "The plan was simple. "
    "A microphone went in the cat, an antenna went down its tail, and agents trained it to walk near Soviet targets. "
    "The first field test ended almost immediately. "
    "The cat crossed the road and was hit by a taxi. "
    "The project was cancelled, and the report concluded that cats were not especially reliable intelligence officers. "
    "That was the official lesson."
)


def _make_brain_with_keys(*keys: str) -> Brain:
    """Return a Brain whose in-memory subject_keys set is pre-seeded.

    Uses a temp directory for the brain dir but patches SUBJECT_KEYS_PATH
    to a temp file so record_subject_key does not write to the real ledger.
    This keeps the real insta-brain/data/subject_keys.jsonl clean.
    """
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tf:
        tmp_path = Path(tf.name)

    with patch("src.brain.SUBJECT_KEYS_PATH", tmp_path):
        with tempfile.TemporaryDirectory() as tmp:
            b = Brain(brain_dir=Path(tmp) / "brain")
            for k in keys:
                b.record_subject_key(k)
    return b


# ------------------------------------------------------------------ #
# Brain: is_subject_used + find_subject_collision
# ------------------------------------------------------------------ #

def test_brain_is_subject_used_exact_match():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tf:
        tmp_path = Path(tf.name)
    with patch("src.brain.SUBJECT_KEYS_PATH", tmp_path):
        with tempfile.TemporaryDirectory() as tmp:
            b = Brain(brain_dir=Path(tmp) / "brain")
            b.record_subject_key("radium-girls", post_id="legacy")
            assert b.is_subject_used("radium-girls") is True
            assert b.is_subject_used("molasses-flood") is False


def test_brain_is_subject_used_normalises_case():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tf:
        tmp_path = Path(tf.name)
    with patch("src.brain.SUBJECT_KEYS_PATH", tmp_path):
        with tempfile.TemporaryDirectory() as tmp:
            b = Brain(brain_dir=Path(tmp) / "brain")
            b.record_subject_key("radium-girls")
            assert b.is_subject_used("Radium-Girls") is True
            assert b.is_subject_used("RADIUM-GIRLS") is True


def test_brain_find_subject_collision_close_variant():
    # 'radium-girl' vs 'radium-girls':
    # c_tokens={'radium','girl'}, s_tokens={'radium','girls'}
    # intersection={'radium'}, union={'radium','girl','girls'} -> 1/3=0.33 < 0.4
    b = Brain.__new__(Brain)
    b._subject_keys = {"radium-girls"}
    assert b.find_subject_collision("radium-girl") is None


def test_brain_find_subject_collision_high_overlap():
    # 'great-molasses-flood-1919' vs 'great-molasses-flood': 3/4=0.75 >= 0.7
    b = Brain.__new__(Brain)
    b._subject_keys = {"great-molasses-flood"}
    result = b.find_subject_collision("great-molasses-flood-1919")
    assert result == "great-molasses-flood"


def test_brain_find_subject_collision_unrelated_returns_none():
    b = Brain.__new__(Brain)
    b._subject_keys = {"radium-girls"}
    assert b.find_subject_collision("operation-acoustic-kitty") is None


def test_brain_record_subject_key_idempotent():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tf:
        tmp_path = Path(tf.name)
    with patch("src.brain.SUBJECT_KEYS_PATH", tmp_path):
        with tempfile.TemporaryDirectory() as tmp:
            b = Brain(brain_dir=Path(tmp) / "brain")
            b.record_subject_key("idempotent-test-key")
            before = len(b._subject_keys)
            b.record_subject_key("idempotent-test-key")
            after = len(b._subject_keys)
    assert before == after, "second record_subject_key call must not add a duplicate"


# ------------------------------------------------------------------ #
# agent._find_key_collision
# ------------------------------------------------------------------ #

def test_find_key_collision_exact_match():
    used = {"radium-girls", "molasses-flood"}
    assert agent._find_key_collision("radium-girls", used) == "radium-girls"


def test_find_key_collision_high_jaccard():
    used = {"great-molasses-flood"}
    # 'great-molasses-flood-1919' -> tokens {'great','molasses','flood','1919'}
    # stored -> {'great','molasses','flood'}, intersection 3, union 4 -> 0.75 >= 0.7
    assert agent._find_key_collision("great-molasses-flood-1919", used) == "great-molasses-flood"


def test_find_key_collision_unrelated_returns_none():
    used = {"radium-girls", "molasses-flood"}
    assert agent._find_key_collision("operation-acoustic-kitty", used) is None


def test_find_key_collision_empty_candidate_returns_none():
    used = {"radium-girls"}
    assert agent._find_key_collision("", used) is None


# ------------------------------------------------------------------ #
# execute_tool: exact block
# ------------------------------------------------------------------ #

def _minimal_reel_args(subject_key: str) -> dict:
    return {
        "script": _VALID_SCRIPT,
        "title":  "The Spy Cat That Failed",
        "topic":  "history",
        "tone_override": "sober",
        "hint":   _VALID_HINT,
        "subject_key": subject_key,
    }


def test_exact_subject_key_blocks_dispatch():
    used = {"radium-girls"}
    result = agent.execute_tool(
        "run_reel",
        _minimal_reel_args("radium-girls"),
        dry_run=True,
        mode="reel_morning",
        recent_fingerprints=[],
        used_subject_keys=used,
    )
    assert "FAILURE_KIND: duplicate_subject" in result
    assert "radium-girls" in result


def test_fuzzy_subject_key_blocks_close_variant():
    # 'great-molasses-flood-1919' has 0.75 Jaccard overlap (>= 0.7) with 'great-molasses-flood'
    used = {"great-molasses-flood"}
    args = {
        "script": (
            "In 1919, a Boston storage tank burst and sent 2.3 million gallons of molasses "
            "through the streets, killing 21 people and trapping horses in the wave. "
            "Houses shifted off their foundations as the flood tore through the neighbourhood. "
            "The company blamed anarchists for sabotage. "
            "Investigators later found the real cause: the tank had been built too thin to "
            "hold its own contents and had been leaking for weeks before it failed. "
            "Nobody had ordered it checked."
        ),
        "title":  "The Molasses Flood That Killed 21",
        "topic":  "history",
        "tone_override": "sober",
        "hint":   "Boston industrial waterfront 1919\nmolasses flood historic photograph\nBoston North End street scene early 20th century",
        "subject_key": "great-molasses-flood-1919",
    }
    result = agent.execute_tool(
        "run_reel", args, dry_run=True, mode="reel_morning",
        recent_fingerprints=[], used_subject_keys=used,
    )
    assert "FAILURE_KIND: duplicate_subject" in result


def test_different_subject_key_is_not_blocked():
    used = {"radium-girls"}
    args = {
        "script": _VALID_SCRIPT,
        "title":  "The Spy Cat That Failed",
        "topic":  "history",
        "tone_override": "curious",
        "hint":   "CIA cold war operations 1960s\nspy cat surveillance equipment\nLangley Virginia intelligence archive",
        "subject_key": "operation-acoustic-kitty",
    }
    # Should NOT be blocked — we patch the subprocess so it doesn't actually run.
    with patch("scripts.autonomous_agent._run_pipeline", return_value="reel published ok"):
        result = agent.execute_tool(
            "run_reel", args, dry_run=True, mode="reel_morning",
            recent_fingerprints=[], used_subject_keys=used,
        )
    assert "FAILURE_KIND: duplicate_subject" not in result


def test_in_session_subject_key_poison_blocks_second_call():
    used: set[str] = set()
    args = _minimal_reel_args("radium-girls")

    # First call — should clear (no existing key); patch pipeline to avoid real run.
    with patch("scripts.autonomous_agent._run_pipeline", return_value="reel published ok"):
        first = agent.execute_tool(
            "run_reel", args, dry_run=True, mode="reel_morning",
            recent_fingerprints=[], used_subject_keys=used,
        )
    assert "FAILURE_KIND: duplicate_subject" not in first
    assert "radium-girls" in used  # poisoned in-session

    # Second call — must be blocked by in-session cache.
    second = agent.execute_tool(
        "run_reel", args, dry_run=True, mode="reel_morning",
        recent_fingerprints=[], used_subject_keys=used,
    )
    assert "FAILURE_KIND: duplicate_subject" in second


def test_missing_subject_key_does_not_crash():
    used: set[str] = set()
    args = {
        "script": "Some script.",
        "title":  "Some Title",
        "topic":  "history",
        "tone_override": "curious",
        "hint":   _VALID_HINT,
        # subject_key intentionally absent — backward compat for old callers
    }
    with patch("scripts.autonomous_agent._run_pipeline", return_value="ok"):
        result = agent.execute_tool(
            "run_reel", args, dry_run=True, mode="reel_morning",
            recent_fingerprints=[], used_subject_keys=used,
        )
    assert "FAILURE_KIND: duplicate_subject" not in result
