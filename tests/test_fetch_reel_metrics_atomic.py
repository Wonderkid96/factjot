"""Tests for the atomic rewrite of reel_performance.jsonl in
pipelines/reel/fetch_reel_metrics.py.

Behavioural contract: a SIGKILL, process crash, or exception mid-write
must leave the original ledger fully intact, never half-written.
The full-rewrite path uses a temp file + os.replace, which is
POSIX-atomic on the same filesystem.

Pre-Phase-K, the metrics flow opened PERF_LOG with mode "w" and
streamed records line-by-line. A crash between line N and line N+1
left a truncated ledger. The git workflow step would then commit the
truncation as a valid update.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines.reel.fetch_reel_metrics import atomic_write_ledger


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_write_matches_expected_jsonl(tmp_path):
    path = tmp_path / "ledger.jsonl"
    records = {
        "a": {"reel_id": "a", "reach": 100},
        "b": {"reel_id": "b", "reach": 200},
    }
    atomic_write_ledger(path, records)
    rows = _read_jsonl(path)
    assert len(rows) == 2
    assert rows[0]["reel_id"] == "a"
    assert rows[1]["reel_id"] == "b"


def test_no_tmp_file_remains_after_success(tmp_path):
    path = tmp_path / "ledger.jsonl"
    atomic_write_ledger(path, {"a": {"reel_id": "a"}})
    tmp = path.with_suffix(path.suffix + ".tmp")
    assert not tmp.exists(), "tmp file must be moved by os.replace, not left behind"


def test_exception_mid_write_preserves_original(tmp_path):
    """Inject an unserialisable record so json.dumps raises mid-loop.
    Assert the original ledger content is untouched (atomicity).
    """
    path = tmp_path / "ledger.jsonl"
    # Seed the ledger with one good record.
    seeded = {"seed": {"reel_id": "seed", "reach": 999}}
    atomic_write_ledger(path, seeded)
    seed_bytes = path.read_bytes()

    # Now attempt a rewrite that will fail mid-loop. A set is not
    # JSON-serialisable; json.dumps raises TypeError on the bad record
    # AFTER the good one. The tmp file gets partially written then
    # the exception propagates before os.replace can run.
    bad_records = {
        "good": {"reel_id": "good", "reach": 1},
        "bad":  {"reel_id": "bad", "set": {1, 2, 3}},  # unserialisable
    }
    with pytest.raises(TypeError):
        atomic_write_ledger(path, bad_records)

    # Original is unchanged byte-for-byte.
    assert path.read_bytes() == seed_bytes


def test_overwrite_replaces_content_atomically(tmp_path):
    path = tmp_path / "ledger.jsonl"
    atomic_write_ledger(path, {"a": {"reel_id": "a", "v": 1}})
    atomic_write_ledger(path, {"a": {"reel_id": "a", "v": 2}})
    rows = _read_jsonl(path)
    assert len(rows) == 1
    assert rows[0]["v"] == 2


def test_creates_parent_directory(tmp_path):
    path = tmp_path / "subdir" / "nested" / "ledger.jsonl"
    atomic_write_ledger(path, {"a": {"reel_id": "a"}})
    assert path.exists()
