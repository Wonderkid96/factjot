#!/usr/bin/env bash
# scripts/setup_dev.sh
# Idempotent local dev setup: install pre-commit + ruff, register the hook,
# run once. Canonical Python is required (CLAUDE.md hard rule). Bare python3
# will not have the right packages.
set -euo pipefail

PY="/Library/Frameworks/Python.framework/Versions/Current/bin/python3"

if [[ ! -x "$PY" ]]; then
  echo "ERROR: canonical Python not found at $PY" >&2
  echo "See CLAUDE.md §6 (Environment specifics)." >&2
  exit 1
fi

echo "[setup_dev] Using Python: $PY"
"$PY" --version

# Pre-flight git config checks. Fail fast so we don't pip install only to
# discover hooks won't fire.

# A global core.hooksPath (empty or otherwise) silently disables per-repo
# hooks even after pre-commit installs them. Detect and fail loudly so the
# user can fix their ~/.gitconfig themselves.
if git config --global --get-all core.hooksPath >/dev/null 2>&1; then
  global_hooks_path="$(git config --global --get core.hooksPath || true)"
  echo "ERROR: global core.hooksPath is set in ~/.gitconfig (value: '${global_hooks_path}')." >&2
  echo "An empty value disables hooks entirely; a custom path overrides per-repo hooks." >&2
  echo "Run: git config --global --unset-all core.hooksPath" >&2
  echo "Then re-run scripts/setup_dev.sh." >&2
  exit 1
fi

# pre-commit refuses to install when core.hooksPath is set in the local
# repo config, even when it points at the default .git/hooks. Clear that
# no-op override; bail loudly if the repo has a real custom hooks path.
if hooks_path="$(git config --local --get core.hooksPath || true)"; [[ -n "${hooks_path:-}" ]]; then
  default_hooks_path="$(git rev-parse --git-path hooks)"
  if [[ "$hooks_path" == "$default_hooks_path" || "$hooks_path" == ".git/hooks" ]]; then
    echo "[setup_dev] Clearing redundant local core.hooksPath ($hooks_path)..."
    git config --local --unset-all core.hooksPath
  else
    echo "ERROR: repo has a custom core.hooksPath ($hooks_path)." >&2
    echo "Resolve manually before re-running setup_dev.sh." >&2
    exit 1
  fi
fi

echo "[setup_dev] Installing pre-commit and ruff..."
"$PY" -m pip install --user --upgrade pre-commit ruff

echo "[setup_dev] Registering git hook..."
"$PY" -m pre_commit install

echo "[setup_dev] Running pre-commit against all files..."
"$PY" -m pre_commit run --all-files

echo "[setup_dev] Done."
