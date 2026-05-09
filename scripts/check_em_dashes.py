#!/usr/bin/env python3
"""Targeted em-dash linter per CLAUDE.md section 1.2 (post 2026-05-10).

Exits 1 if it finds U+2014 (em-dash) or U+2013 (en-dash) in any
in-scope location:

In scope:
- All .yml, .yaml (production-breaking parser issue with GitHub's Go YAML parser)
- All .j2 templates (they emit shipping copy)
- Python string literals in src/content/*.py (shipping content)

Out of scope (allowed):
- Code comments anywhere (lines beginning with '#' after strip)
- Python files outside src/content/
- Regex character classes like [-...em-dash...]
- .md technical docs
- Anything under .git/, node_modules/, __pycache__/
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Sentinels we lint for. Held as variables (not literals in this docstring)
# so this very file passes the linter when run on the repo.
EM = "—"  # em-dash
EN = "–"  # en-dash

# File-name globs scanned for ANY occurrence (no comment / string discrimination).
BLANKET_PATTERNS = ("*.yml", "*.yaml", "*.j2")

# Python content modules: scan string literals only, skipping comment lines.
CONTENT_PATH_FRAGMENT = ("src", "content")

# Directory names that are always skipped when walking the tree.
# These cover VCS state, dependency caches, virtual envs, and the local
# Claude Code sandbox (worktrees, settings) that lives outside the repo.
IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    ".claude",
    "node_modules",
    "__pycache__",
}

# Regex character class containing em / en, e.g. r"[--]". Such matches are
# explicitly permitted by the rule and should not trigger a violation.
REGEX_CHAR_CLASS = re.compile(r"\[[^\]]*[" + EM + EN + r"][^\]]*\]")


def _is_python_comment_line(line: str) -> bool:
    """True if the stripped line starts with '#' (a Python comment)."""
    return line.lstrip().startswith("#")


def _line_has_inscope_dash(line: str) -> bool:
    """True if the line carries an em / en dash that the rule covers.

    A line whose only em / en dash sits inside a regex character class is
    allowed. Otherwise any em / en outside such a class triggers the rule.
    """
    if EM not in line and EN not in line:
        return False
    without_class = REGEX_CHAR_CLASS.sub("", line)
    return EM in without_class or EN in without_class


def _is_path_in_ignored_dir(path: Path) -> bool:
    """True if any path part is in the ignored-directories set."""
    return any(part in IGNORED_DIRS for part in path.parts)


def _is_content_python(path: Path) -> bool:
    """True if a .py file lives under src/content/ (any depth)."""
    parts = path.parts
    target = CONTENT_PATH_FRAGMENT
    for i in range(len(parts) - len(target)):
        if parts[i : i + len(target)] == target:
            return True
    return False


def _scan_blanket_file(path: Path) -> list[tuple[int, str]]:
    """Return (line_no, line) tuples for any line containing em / en."""
    hits: list[tuple[int, str]] = []
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return hits
    for line_no, line in enumerate(text.splitlines(), 1):
        if EM in line or EN in line:
            hits.append((line_no, line))
    return hits


def _scan_content_python(path: Path) -> list[tuple[int, str]]:
    """Return (line_no, line) for non-comment, non-regex-class hits."""
    hits: list[tuple[int, str]] = []
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return hits
    for line_no, line in enumerate(text.splitlines(), 1):
        if _is_python_comment_line(line):
            continue
        if _line_has_inscope_dash(line):
            hits.append((line_no, line))
    return hits


def scan_root(root: Path) -> list[tuple[Path, int, str]]:
    """Walk root, return all (path, line_no, line) violations."""
    failures: list[tuple[Path, int, str]] = []

    for pattern in BLANKET_PATTERNS:
        for f in root.rglob(pattern):
            if _is_path_in_ignored_dir(f):
                continue
            if not f.is_file():
                continue
            for line_no, line in _scan_blanket_file(f):
                failures.append((f, line_no, line))

    for f in root.rglob("*.py"):
        if _is_path_in_ignored_dir(f):
            continue
        if not f.is_file():
            continue
        if not _is_content_python(f):
            continue
        for line_no, line in _scan_content_python(f):
            failures.append((f, line_no, line))

    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "roots",
        nargs="*",
        default=["."],
        help="Directories to scan (default: current directory).",
    )
    args = parser.parse_args(argv)

    failures: list[tuple[Path, int, str]] = []
    for root_str in args.roots:
        root = Path(root_str).resolve()
        if not root.exists():
            print(f"check_em_dashes: root does not exist: {root}", file=sys.stderr)
            return 2
        failures.extend(scan_root(root))

    if failures:
        print("Em-dash check failed. Locations:", file=sys.stderr)
        for f, line_no, line in failures:
            snippet = line.rstrip()[:120]
            print(f"  {f}:{line_no}  {snippet}", file=sys.stderr)
        print(
            f"\n{len(failures)} violation(s). See CLAUDE.md section 1.2 for the rule.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
