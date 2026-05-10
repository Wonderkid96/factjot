"""Tests for the in-session subject-fingerprint dedup in
scripts/autonomous_agent.py.

Behavioural contract: if the agent dispatches a reel or carousel in
turn N of a session, the same subject must be rejected if it
re-appears in turn N+M of the same session, even before the on-disk
ledger commit (which only lands after the workflow's git push step at
the end of the run).

Live regression that motivated these tests: 2026-05-09 "Top 5
scariest films" double-post. Two reels with the same title, different
scripts, shipped 21 minutes apart within the same agent session.
Phase C subject-fingerprint dedup was in place at the time. The cause
was that `recent_fingerprints` was loaded once from disk at session
start and never updated after a successful in-session dispatch.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scripts.autonomous_agent as agent  # noqa: E402
from src.brain import subject_fingerprint  # noqa: E402


# ----- candidate text source: title-first for reels ----------------

def test_reel_candidate_text_prefers_title_over_script():
    # Two reels with identical title and different scripts must collide.
    # Pre-fix this returned the long script and a different fingerprint
    # for every script body.
    args_first = {
        "title":  "Top 5 scariest films",
        "script": "Five horror films changed cinema by weaponising fear...",
    }
    args_second = {
        "title":  "Top 5 scariest films",
        "script": "Horror history is basically five moments where audiences...",
    }
    t1 = agent._candidate_subject_text("run_reel", args_first)
    t2 = agent._candidate_subject_text("run_reel", args_second)
    assert t1 == t2, (
        "title-first selection must produce identical candidate text "
        "for identical titles regardless of script body"
    )
    assert subject_fingerprint(t1) == subject_fingerprint(t2)


def test_reel_candidate_text_falls_back_to_script_when_title_missing():
    args = {"script": "The Soviet Union built a radar so loud..."}
    t = agent._candidate_subject_text("run_reel", args)
    assert "Soviet" in t


# ----- carousel candidate text: brief over category label ----------

def test_carousel_candidate_text_prefers_brief_over_label():
    # `label` is a CAPS category (HISTORY, TECHNOLOGY). It must NOT be
    # used as fingerprint source - that would collide every carousel in
    # the same category.
    args = {
        "brief": "Five mega projects that failed catastrophically",
        "label": "HISTORY",
    }
    t = agent._candidate_subject_text("run_carousel", args)
    assert "mega" in t.lower()
    assert t != "HISTORY"


# ----- in-session poison: second dispatch blocked --------------------

def test_in_session_second_dispatch_with_same_title_is_blocked(
    monkeypatch, tmp_path
):
    """Regression: 2026-05-09 horror-films double-post.

    Simulate two consecutive run_reel calls in the same session with
    the same title and different scripts. The second must collide.
    """
    # Empty recent_fingerprints (fresh session, no prior posts).
    recent: list[tuple[str, str, str]] = []

    # Block run_reel from actually firing a subprocess.
    def _fake_run_reel(args, dry_run):
        return "exit_code=0\n\nfake reel published"

    monkeypatch.setattr(agent, "run_reel", _fake_run_reel)

    # First dispatch - must succeed and poison the cache.
    out1 = agent.execute_tool(
        "run_reel",
        {
            "title":  "Top 5 scariest films",
            "script": "Five horror films changed cinema...",
        },
        dry_run=True,
        mode="reel_morning",
        recent_fingerprints=recent,
    )
    assert "exit_code=0" in out1
    assert len(recent) == 1, "first dispatch must append to in-memory cache"

    # Second dispatch with same title - must be rejected.
    out2 = agent.execute_tool(
        "run_reel",
        {
            "title":  "Top 5 scariest films",
            "script": "Horror history is basically five moments...",
        },
        dry_run=True,
        mode="reel_morning",
        recent_fingerprints=recent,
    )
    assert "FAILURE_KIND: duplicate_subject" in out2, (
        "same-session second dispatch with same title must be rejected"
    )


def test_in_session_distinct_subjects_both_dispatch(monkeypatch):
    """Two genuinely different reels in the same session must both ship."""
    recent: list[tuple[str, str, str]] = []

    def _fake_run_reel(args, dry_run):
        return "exit_code=0\n\nfake reel published"

    monkeypatch.setattr(agent, "run_reel", _fake_run_reel)

    out1 = agent.execute_tool(
        "run_reel",
        {"title": "Pepsi Once Owned a Navy",
         "script": "In 1989 PepsiCo briefly owned 17 Soviet submarines..."},
        dry_run=True,
        mode="reel_morning",
        recent_fingerprints=recent,
    )
    out2 = agent.execute_tool(
        "run_reel",
        {"title": "The Syrup Wave That Killed 21",
         "script": "In January 1919 a Boston molasses tank burst..."},
        dry_run=True,
        mode="reel_morning",
        recent_fingerprints=recent,
    )
    assert "exit_code=0" in out1
    assert "exit_code=0" in out2
    assert len(recent) == 2


# ----- history summary reads reels.jsonl ----------------------------

def test_build_history_summary_merges_reels_and_posted(monkeypatch, tmp_path):
    """build_history_summary must read reels.jsonl in addition to
    posted.jsonl. Pre-fix it read only posted.jsonl, which historically
    did not carry reel_title - so the fingerprint hint shown to the
    agent in the prompt was wrong for reel rows.
    """
    import json

    posted = tmp_path / "posted.jsonl"
    reels = tmp_path / "reels.jsonl"

    # Reel only in reels.jsonl with reel_title.
    reels.write_text(json.dumps({
        "reel_id":       "abc123",
        "post_id":       "abc123",
        "ig_media_id":   "ig_001",
        "claim":         "Long script body here...",
        "claim_hash":    "h1",
        "topic":         "history",
        "reel_title":    "Pepsi Once Owned a Navy",
        "published_at":  "2026-05-09T14:55:18Z",
    }) + "\n")

    # Posted.jsonl has only the mirrored claim (no reel_title - the
    # historical shape before the fix to record_publish).
    posted.write_text(json.dumps({
        "claim_hash":   "h1",
        "claim":        "Long script body here...",
        "topic":        "history",
        "category":     "REEL",
        "post_id":      "abc123",
        "ig_media_id":  "ig_001",
        "published_at": "2026-05-09T14:55:18Z",
    }) + "\n")

    monkeypatch.setattr(agent, "POSTED_LOG", posted)
    monkeypatch.setattr(agent, "REELS_LOG",  reels)

    summary = agent.build_history_summary(limit=10)
    assert "Pepsi" in summary or "navy" in summary.lower(), (
        "merged summary must surface reel_title from reels.jsonl"
    )
