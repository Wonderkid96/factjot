#!/usr/bin/env python3
"""Verify and auto-fix all TMDB IDs in list_packs.py.

For every pack item that has an expected_title, fetches the TMDB record
for its stored tmdb_id and checks the title matches. When there is a
mismatch it searches TMDB for the correct ID and patches list_packs.py
in place.

Run manually or via weekly-plan.yml (before prepare_packs.py).
If no mismatches are found, exits cleanly with no file changes.

Usage:
    python3 pipelines/list/verify_pack_ids.py
    python3 pipelines/list/verify_pack_ids.py --dry-run
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from src.content.list_packs import LIST_PACKS
from src.research.tmdb_client import TMDBClient


def _titles_match(a: str, b: str) -> bool:
    import unicodedata
    def _norm(s: str) -> str:
        s = unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().lower().strip()
        return re.sub(r"[^a-z0-9 ]", "", s)
    na, nb = _norm(a), _norm(b)
    return na in nb or nb in na


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Report issues without patching")
    args = parser.parse_args()

    tmdb = TMDBClient()
    pack_file = Path("src/content/list_packs.py")
    source = pack_file.read_text(encoding="utf-8")

    fixes: list[tuple[int, str, int, str]] = []   # (old_id, expected_title, new_id, kind)
    errors: list[str] = []

    print("Verifying TMDB IDs in list_packs.py...")

    for slug, pack in LIST_PACKS.items():
        for item in pack.get("items", []):
            expected = item.get("expected_title")
            if not expected:
                continue
            tmdb_id = item.get("tmdb_id")
            if not tmdb_id:
                continue
            kind = item.get("kind", "movie")

            try:
                if kind == "movie":
                    entity = tmdb.get_movie(int(tmdb_id))
                    actual = entity.get("title") or entity.get("original_title") or ""
                    year   = (entity.get("release_date") or "")[:4]
                else:
                    entity = tmdb.get_tv_show(int(tmdb_id))
                    actual = entity.get("name") or entity.get("original_name") or ""
                    year   = (entity.get("first_air_date") or "")[:4]
            except Exception as exc:
                errors.append(f"  {slug} / {expected!r}: TMDB fetch failed ({exc})")
                continue

            if _titles_match(expected, actual):
                continue

            # Mismatch -- search for the correct ID
            print(f"  MISMATCH  {slug}: ID {tmdb_id} -> {actual!r}, expected {expected!r}")
            try:
                year_int = int(year) if year else None
                if kind == "movie":
                    new_id = tmdb.search_movie(expected, year_int)
                else:
                    new_id = tmdb.search_tv(expected, year_int)

                if not new_id:
                    errors.append(f"  {slug} / {expected!r}: could not find correct TMDB ID")
                    continue

                # Verify the new ID returns the right title
                if kind == "movie":
                    check = tmdb.get_movie(new_id)
                    check_title = check.get("title") or check.get("original_title") or ""
                else:
                    check = tmdb.get_tv_show(new_id)
                    check_title = check.get("name") or check.get("original_name") or ""

                if not _titles_match(expected, check_title):
                    errors.append(f"  {slug} / {expected!r}: search returned {check_title!r} (ID {new_id}), still wrong")
                    continue

                print(f"  FIX       {slug}: {tmdb_id} -> {new_id}  ({check_title!r})")
                fixes.append((tmdb_id, expected, new_id, kind))
            except Exception as exc:
                errors.append(f"  {slug} / {expected!r}: search failed ({exc})")

    if not fixes and not errors:
        print("All TMDB IDs verified -- no fixes needed.")
        return 0

    if errors:
        print("\nIssues that could not be auto-fixed:")
        for e in errors:
            print(e)

    if fixes:
        print(f"\n{len(fixes)} fix(es) found.")
        if args.dry_run:
            print("Dry run -- not patching list_packs.py.")
        else:
            patched = source
            for old_id, expected, new_id, _kind in fixes:
                # Replace the specific tmdb_id line closest to expected_title context
                # Pattern: "tmdb_id": OLD, followed somewhere by expected_title
                patched = re.sub(
                    rf'"tmdb_id":\s*{old_id}(?=.*?{re.escape(expected)})',
                    f'"tmdb_id": {new_id}',
                    patched,
                    count=1,
                    flags=re.DOTALL,
                )
            pack_file.write_text(patched, encoding="utf-8")
            print(f"Patched {pack_file}  ({len(fixes)} ID(s) corrected).")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
