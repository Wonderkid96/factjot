"""Tests for scripts/backfill_reel_performance_slot.py.

Verifies:
  - Slot inference correctly maps timestamps to the 3-slot schedule.
  - Outside-window timestamps map to `unknown`.
  - Re-running the backfill is idempotent (entries already carrying
    a slot field are not changed; total count stays stable).
  - Unparseable lines are preserved (defensive behaviour: we never
    silently delete malformed history).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# Make scripts/ importable.
sys.path.insert(0, str(REPO / "scripts"))

from backfill_reel_performance_slot import backfill, infer_slot  # noqa: E402


# ---------------------------------------------------------------------- #
# infer_slot: pure function tests (no I/O)
# ---------------------------------------------------------------------- #


def test_infer_slot_morning() -> None:
    assert infer_slot("2026-05-09T08:30:00Z") == "reel_morning"


def test_infer_slot_morning_lower_edge() -> None:
    assert infer_slot("2026-05-09T07:00:00Z") == "reel_morning"


def test_infer_slot_midday() -> None:
    assert infer_slot("2026-05-09T13:30:00Z") == "list_midday"


def test_infer_slot_midday_lower_edge() -> None:
    """11:00 UTC opens list_midday."""
    assert infer_slot("2026-05-09T11:00:00Z") == "list_midday"


def test_infer_slot_night() -> None:
    assert infer_slot("2026-05-09T19:45:00Z") == "reel_night"


def test_infer_slot_night_lower_edge() -> None:
    assert infer_slot("2026-05-09T17:00:00Z") == "reel_night"


def test_infer_slot_outside_windows_is_unknown() -> None:
    """00:00 UTC, 06:59, 23:00 are all outside any window."""
    assert infer_slot("2026-05-01T00:00:00Z") == "unknown"
    assert infer_slot("2026-05-09T06:59:00Z") == "unknown"
    assert infer_slot("2026-05-09T22:30:00Z") == "unknown"


def test_infer_slot_handles_explicit_offset() -> None:
    """ISO with +00:00 instead of Z must parse the same."""
    assert infer_slot("2026-05-09T08:30:00+00:00") == "reel_morning"


def test_infer_slot_handles_non_utc_offset() -> None:
    """A +01:00 timestamp at 09:30 == 08:30 UTC -> reel_morning."""
    assert infer_slot("2026-05-09T09:30:00+01:00") == "reel_morning"


def test_infer_slot_unknown_on_garbage() -> None:
    assert infer_slot("not a date") == "unknown"
    assert infer_slot("") == "unknown"


# ---------------------------------------------------------------------- #
# backfill: file rewrite + idempotency
# ---------------------------------------------------------------------- #


def _write_ledger(path: Path, entries: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n",
        encoding="utf-8",
    )


def _read_ledger(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_backfill_attaches_slot_to_existing_entries(tmp_path: Path) -> None:
    p = tmp_path / "perf.jsonl"
    _write_ledger(p, [
        {"reel_id": "a", "posted_at": "2026-05-09T08:30:00Z", "reach": 10},
        {"reel_id": "b", "posted_at": "2026-05-09T13:30:00Z", "reach": 20},
        {"reel_id": "c", "posted_at": "2026-05-09T19:45:00Z", "reach": 30},
    ])
    stats = backfill(p)
    assert stats["updated"] == 3
    assert stats["kept"] == 0

    out = _read_ledger(p)
    assert out[0]["slot"] == "reel_morning"
    assert out[1]["slot"] == "list_midday"
    assert out[2]["slot"] == "reel_night"
    # Pre-existing fields preserved.
    assert out[0]["reach"] == 10


def test_backfill_is_idempotent(tmp_path: Path) -> None:
    """Re-running the backfill must not double-write or change values."""
    p = tmp_path / "perf.jsonl"
    _write_ledger(p, [
        {"reel_id": "a", "posted_at": "2026-05-09T08:30:00Z", "reach": 10},
    ])
    backfill(p)  # first run: updates 1
    after_first = p.read_text()

    stats = backfill(p)  # second run: nothing to do
    assert stats["updated"] == 0
    assert stats["kept"] == 1
    assert p.read_text() == after_first, "ledger bytes must be identical on re-run"


def test_backfill_preserves_existing_slot_value(tmp_path: Path) -> None:
    """If an entry already carries a (possibly hand-corrected) slot,
    backfill must keep it. Manual overrides are honoured."""
    p = tmp_path / "perf.jsonl"
    _write_ledger(p, [
        {"reel_id": "a", "posted_at": "2026-05-09T08:30:00Z",
         "slot": "reel_morning", "reach": 10},
        {"reel_id": "b", "posted_at": "2026-05-09T08:30:00Z",
         "slot": "list_midday", "reach": 20},  # hand-overridden
    ])
    backfill(p)
    out = _read_ledger(p)
    assert out[0]["slot"] == "reel_morning"
    # Backfill must NOT reset the manually-set slot.
    assert out[1]["slot"] == "list_midday"


def test_backfill_handles_outside_window_timestamps(tmp_path: Path) -> None:
    p = tmp_path / "perf.jsonl"
    _write_ledger(p, [
        {"reel_id": "manual", "posted_at": "2026-05-01T00:00:00Z", "reach": 5},
    ])
    backfill(p)
    out = _read_ledger(p)
    assert out[0]["slot"] == "unknown"


def test_backfill_dry_run_does_not_write(tmp_path: Path) -> None:
    p = tmp_path / "perf.jsonl"
    _write_ledger(p, [
        {"reel_id": "a", "posted_at": "2026-05-09T08:30:00Z", "reach": 10},
    ])
    before = p.read_text()
    stats = backfill(p, dry_run=True)
    assert stats.get("dry_run") is True
    assert p.read_text() == before, "dry-run must not modify the file"


def test_backfill_missing_ledger_returns_signal(tmp_path: Path) -> None:
    p = tmp_path / "does_not_exist.jsonl"
    stats = backfill(p)
    assert stats.get("missing_ledger") is True


def test_backfill_preserves_unparseable_lines(tmp_path: Path) -> None:
    """Defensive: malformed JSON is preserved verbatim, not silently dropped."""
    p = tmp_path / "perf.jsonl"
    p.write_text(
        json.dumps({"reel_id": "ok", "posted_at": "2026-05-09T08:30:00Z"}) + "\n"
        + "this is not valid json\n"
        + json.dumps({"reel_id": "ok2", "posted_at": "2026-05-09T13:00:00Z"}) + "\n",
        encoding="utf-8",
    )
    backfill(p)
    text = p.read_text()
    assert "this is not valid json" in text
    # The two well-formed entries got their slot.
    parsed = [
        json.loads(line) for line in text.splitlines()
        if line.startswith("{")
    ]
    assert any(e["slot"] == "reel_morning" for e in parsed)
    assert any(e["slot"] == "list_midday" for e in parsed)
