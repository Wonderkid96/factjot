"""Footage dedup guard tests.

Covers the safety-pool dedup leak that caused the same surgery clip to
reappear across reels (root cause: Pass 3 of find_videos was not consulting
the used-footage ledger), plus the dry-run gating in the ledger writer.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.research import video_finder
from src.research import narrative_beats, visual_intents
from pipelines.reel.make_reel import _append_footage_ledger


def _make_safety_pool(root: Path, names: list[str]) -> list[Path]:
    pool = root / "pool"
    pool.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for n in names:
        p = pool / f"{n}.mp4"
        p.write_bytes(b"\x00")  # placeholder; find_videos doesn't decode
        paths.append(p)
    return paths


class _FakeEnts:
    nouns: list[str] = []
    proper_nouns: list[str] = []


def _stub_find_videos_neighbours():
    """Patch the network/entity-tier calls so only the safety pool runs.

    extract_entities and generate_all_beat_queries are imported lazily
    inside find_videos, so they must be patched at their source modules.
    """
    return [
        patch.object(narrative_beats, "extract_entities", return_value=_FakeEnts()),
        patch.object(visual_intents, "generate_all_beat_queries", return_value=[]),
        patch.object(video_finder, "_entity_sources", return_value=[]),
        patch.object(video_finder, "_collect_beat_candidates", return_value=[]),
    ]


class TestSafetyPoolDedup(unittest.TestCase):
    def test_skips_safety_clip_blocked_by_filename(self) -> None:
        """Stem present in blocked_filenames is rejected; the next is chosen."""
        with TemporaryDirectory() as td:
            tmp = Path(td)
            pool = _make_safety_pool(tmp, ["safety_00", "safety_01", "safety_02"])
            with patch.object(video_finder, "_safety_pool_pick", return_value=list(pool)):
                with self._stubs():
                    clips = video_finder.find_videos(
                        image_hint="", claim="x", topic="history",
                        out_dir=tmp / "out", count=2,
                        used_source_registry=set(),
                        blocked_filenames={"safety_00"},
                    )
        chosen = {Path(p).stem for p in clips}
        self.assertNotIn("safety_00", chosen)
        self.assertEqual(len(chosen), 2)
        self.assertTrue(chosen.issubset({"safety_01", "safety_02"}))

    def test_skips_safety_clip_blocked_by_path_in_registry(self) -> None:
        """Absolute path in used_source_registry is rejected."""
        with TemporaryDirectory() as td:
            tmp = Path(td)
            pool = _make_safety_pool(tmp, ["safety_00", "safety_01", "safety_02"])
            blocked_path = str(pool[1])  # block safety_01 by path
            with patch.object(video_finder, "_safety_pool_pick", return_value=list(pool)):
                with self._stubs():
                    clips = video_finder.find_videos(
                        image_hint="", claim="x", topic="history",
                        out_dir=tmp / "out", count=2,
                        used_source_registry={blocked_path},
                        blocked_filenames=set(),
                    )
        chosen_paths = {str(Path(p)) for p in clips}
        self.assertNotIn(blocked_path, chosen_paths)
        self.assertEqual(len(chosen_paths), 2)

    def test_returns_empty_when_all_safety_used(self) -> None:
        """If every safety clip is blocked the function fails safely (no clips)."""
        with TemporaryDirectory() as td:
            tmp = Path(td)
            pool = _make_safety_pool(tmp, ["safety_00", "safety_01"])
            blocked = {p.stem for p in pool}
            with patch.object(video_finder, "_safety_pool_pick", return_value=list(pool)):
                with self._stubs():
                    clips = video_finder.find_videos(
                        image_hint="", claim="x", topic="history",
                        out_dir=tmp / "out", count=2,
                        used_source_registry=set(),
                        blocked_filenames=blocked,
                    )
        self.assertEqual(list(clips), [])

    def _stubs(self):
        # Tiny context manager that enters all neighbour patches together.
        class _Bundle:
            def __init__(self, ps):
                self._ps = ps
            def __enter__(self):
                self._actives = [p.__enter__() for p in self._ps]
                return self
            def __exit__(self, *a):
                for p in reversed(self._ps):
                    p.__exit__(*a)
        return _Bundle(_stub_find_videos_neighbours())


class TestRemoteUrlSkip(unittest.TestCase):
    """Pexels-side dedup: a video id already in skip_urls is filtered out."""

    def test_pexels_skips_blocked_video_id(self) -> None:
        fake_response = {
            "videos": [
                {
                    "id": 111,
                    "url": "https://pexels.com/video/foo-snake/",
                    "video_files": [{"link": "https://cdn/111.mp4", "height": 1280, "width": 720}],
                },
                {
                    "id": 222,
                    "url": "https://pexels.com/video/foo-snake-other/",
                    "video_files": [{"link": "https://cdn/222.mp4", "height": 1280, "width": 720}],
                },
            ]
        }

        class _Resp:
            def raise_for_status(self): pass
            def json(self): return fake_response

        skip = {"pexels:111"}
        with patch.object(video_finder, "requests") as mock_req, \
             patch.dict("os.environ", {"PEXELS_API_KEY": "test"}):
            mock_req.get.return_value = _Resp()
            url = video_finder._pexels_video_url("snake", "nature", skip_urls=skip)

        self.assertEqual(url, "https://cdn/222.mp4")
        self.assertIn("pexels:222", skip)


class TestDryRunLedgerGate(unittest.TestCase):
    def test_dry_run_does_not_write(self) -> None:
        with TemporaryDirectory() as td:
            ledger = Path(td) / "used_footage.jsonl"
            wrote = _append_footage_ledger(
                dry_run=True,
                ledger_path=ledger,
                registry={"pexels:42", "https://cdn/x.mp4"},
                footage_clips=[Path(td) / "clip_a.mp4"],
                reel_id="abc",
                reel_title="Title",
                topic="history",
            )
        self.assertFalse(wrote)
        self.assertFalse(ledger.exists())

    def test_real_run_writes_with_metadata(self) -> None:
        with TemporaryDirectory() as td:
            ledger = Path(td) / "used_footage.jsonl"
            clip = Path(td) / "safety_07.mp4"
            wrote = _append_footage_ledger(
                dry_run=False,
                ledger_path=ledger,
                registry={"pexels:42"},
                footage_clips=[clip],
                reel_id="abc",
                reel_title="Galloping Gertie",
                topic="history",
            )
            self.assertTrue(wrote)
            rows = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()]
            self.assertEqual(len(rows), 2)
            url_row = next(r for r in rows if "url" in r)
            self.assertEqual(url_row["provider"], "pexels")
            self.assertEqual(url_row["provider_video_id"], "42")
            self.assertEqual(url_row["topic"], "history")
            self.assertEqual(url_row["reel_title"], "Galloping Gertie")
            self.assertIn("published_at", url_row)
            file_row = next(r for r in rows if "filename" in r)
            self.assertEqual(file_row["filename"], "safety_07")
            self.assertEqual(file_row["reel_id"], "abc")

    def test_real_run_does_not_set_provider_for_raw_urls(self) -> None:
        """Raw http(s) URLs should not be parsed as provider:id."""
        with TemporaryDirectory() as td:
            ledger = Path(td) / "used_footage.jsonl"
            _append_footage_ledger(
                dry_run=False,
                ledger_path=ledger,
                registry={"https://cdn.pixabay.com/video/2019/foo.mp4"},
                footage_clips=[],
                reel_id="abc",
                reel_title="t",
                topic="history",
            )
            row = json.loads(ledger.read_text().splitlines()[0])
            self.assertNotIn("provider", row)
            self.assertNotIn("provider_video_id", row)


if __name__ == "__main__":
    unittest.main()
