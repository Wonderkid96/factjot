# factjot 2026-05-09 audit implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the 13 decisions locked in during the 2026-05-09 multi-agent audit, in a sequenced set of phases that ship safely against a live production system without missing scheduled posts.

**Architecture:** One phase per coherent concern. Each phase = one or more PRs (depending on plan-mode requirements). Phases sequenced so each one builds on the gates introduced by earlier ones (e.g., voice normaliser ships before fact verification needs it; lint gates ship before new structural code lands). Production runs throughout; the autonomous workflow keeps publishing during the work, with a rollback path documented per phase.

**Tech stack:** Python 3.11, Playwright + Chromium, FFmpeg, ElevenLabs, Anthropic Claude (Sonnet 4.6 + Haiku 4.5), Instagram Graph API, YouTube Data API v3, GitHub Actions cron, pytest, pre-commit, ruff.

---

## 0. Status as of 2026-05-10

**Shipped:**
- Phase A code fixes (`ee33718` on `main`): story_scout prefix-match, agent exit-1 on publish failure, music glob webm fallback, antagonist tags stripped from hashtag builder.
- Phase A doc reconciliation (`8e6e8d8`): SPEC §6.1 aligned to 5-slot reality, ROADMAP.md created.
- Phase B.1 (`523ab65`, PR #1 merged): em-dash rule scoped to shipping content + YAML, 4 ship-string violations stripped.

**Pending (this plan):**
- Phase B.2: install lint gates
- Phase C: voice + dedup integrity
- Phase D: content quality gates
- Phase E: visual integrity
- Phase F: YouTube divergence
- Phase G: structural cleanup
- Phase H: observability + tests

**Out of scope (deferred queue):** monthly performance review process, mid-weight Haiku reports, carousel metrics ledger, Phase 8 vision frame selector. See `ROADMAP.md` and `project_deferred_work_post_audit.md`.

---

## 1. Phase summary

| Phase | Concern | Effort | Plan-mode? | Depends on |
|---|---|---|---|---|
| **B.2** | Lint gates (pre-commit + ruff + em-dash check) | 2-4h | no | B.1 (rule scope) |
| **C** | Voice normaliser + subject fingerprint dedup | 4-8h | partial | B.2 |
| **D** | Fact verification + list format rule | 1-2d | YES | C (voice normaliser) |
| **E** | Font hierarchy + entity validation + thumbnail Haiku-pick + empty-cover typography | 2-3d | YES (every sub-task) | none, parallelisable with D |
| **F** | YouTube description + title + higher-bitrate encode | 4-8h | partial | E (thumbnail overlay) |
| **G** | Retire rare_fact_bank.py + kill news pipeline + dead code sweep + brain rewrite | 1-2d | partial | none, parallelisable with E/F |
| **H** | Smoke tests + brain reconciliation + slot backfill | 1d | no | G (post-cleanup state) |

**Total:** roughly 5-9 working days end-to-end.

**Recommended order:** B.2 → C → D → E → F → G → H (linear). Parallel branches possible if multiple sessions: (C → D) and E and G can interleave once B.2 is in.

---

## 2. Decision-to-phase mapping

Every audit decision lands in a specific phase. Cross-reference for completeness:

| # | Decision | Phase |
|---|---|---|
| A | Fact verification (medium) | D |
| B | Kill news pipeline | G |
| C | Font system rationalisation | E |
| D | Cadence to 3 slots | E (workflow change bundled with visual phase) |
| E | Wikimedia entity Haiku validation | E |
| F | Thumbnail Haiku-pick + brand overlay | E |
| G | YouTube full divergence | F |
| H | Strip antagonist hashtags | A (already shipped) |
| I | News-watcher cron | G (auto-resolved by B) |
| J | Retire rare_fact_bank.py | G |
| K | List format rule | D |
| L | Pre-commit + ruff lint | B.2 |
| M | Carousel writer prompt cache (5-min TTL) | C |

Plus structural items from the audit synthesis not tied to a specific decision:
- Voice normaliser module (P1 from audit) → C
- Subject fingerprint dedup (P0 #4 from audit) → C
- Empty-cover typography variant (P0 #3 from audit) → E
- Brain/gotchas reconciliation (P2 from audit) → G/H
- Smoke tests on reel_composer / instagram_publisher (P2 from audit) → H
- Backfill `slot` field on reel_performance.jsonl → H

---

## 3. Phase B.2 — install lint gates

**Goal:** Install pre-commit + ruff lint + targeted em-dash check script. Encode the B.1 rule scoping in code so the rule is enforced rather than relying on memory.

**Files:**
- Create: `scripts/check_em_dashes.py` (the em-dash check, file-type and content-location scoped)
- Create: `.pre-commit-config.yaml`
- Create: `pyproject.toml` (or `ruff.toml`) for ruff config — `pyproject.toml` is preferred so future tooling shares it
- Create: `scripts/setup_dev.sh`
- Create: `tests/test_no_em_dashes.py`
- Modify: `.github/workflows/test.yml` (add ruff + em-dash check steps)

**Branch:** `audit-phaseB2-lint-gates`

### Task B.2.1 — em-dash check script

**Files:**
- Create: `scripts/check_em_dashes.py`
- Test: `tests/test_check_em_dashes.py`

- [ ] **Step 1: Write failing tests for the script's three behaviours**

```python
# tests/test_check_em_dashes.py
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_em_dashes.py"
PY = sys.executable

def _run(args: list[str]) -> tuple[int, str]:
    res = subprocess.run([PY, str(SCRIPT)] + args, capture_output=True, text=True)
    return res.returncode, res.stdout + res.stderr

def test_clean_repo_returns_zero(tmp_path):
    (tmp_path / "fine.py").write_text("x = 1  # comment with em-dash —, allowed\n")
    rc, _ = _run([str(tmp_path)])
    assert rc == 0

def test_yaml_em_dash_fails(tmp_path):
    (tmp_path / "bad.yml").write_text("foo: bar — baz\n")
    rc, out = _run([str(tmp_path)])
    assert rc != 0
    assert "bad.yml" in out

def test_jinja_em_dash_fails(tmp_path):
    (tmp_path / "bad.html.j2").write_text("<p>hello — world</p>\n")
    rc, out = _run([str(tmp_path)])
    assert rc != 0

def test_python_string_em_dash_in_content_module_fails(tmp_path):
    content_dir = tmp_path / "src" / "content"
    content_dir.mkdir(parents=True)
    (content_dir / "list_themes.py").write_text(
        '"title": "five things — done"\n'
    )
    rc, out = _run([str(tmp_path)])
    assert rc != 0
    assert "list_themes.py" in out

def test_python_comment_em_dash_in_content_module_passes(tmp_path):
    content_dir = tmp_path / "src" / "content"
    content_dir.mkdir(parents=True)
    (content_dir / "ok.py").write_text("# this is a comment — fine\n")
    rc, _ = _run([str(tmp_path)])
    assert rc == 0

def test_python_em_dash_in_internal_module_passes(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "research").mkdir()
    (tmp_path / "src" / "research" / "internal.py").write_text(
        '"x = some — value"\n'  # Not in content/, allowed
    )
    rc, _ = _run([str(tmp_path)])
    assert rc == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/Library/Frameworks/Python.framework/Versions/Current/bin/python3 -m pytest tests/test_check_em_dashes.py -v`
Expected: 6 tests, all FAIL with "FileNotFoundError" or non-zero exit because the script doesn't exist yet.

- [ ] **Step 3: Write the script**

```python
#!/usr/bin/env python3
"""Targeted em-dash linter per CLAUDE.md §1.2 (post 2026-05-10).

Exits 1 if it finds U+2014 (em-dash) or U+2013 (en-dash) in any
in-scope location:

In scope:
- All .yml, .yaml (production-breaking parser issue)
- All .j2 templates (they emit shipping copy)
- Python string literals in src/content/*.py (shipping content)

Out of scope (allowed):
- Code comments anywhere
- Internal modules outside src/content/
- Regex character classes like [—–-]
- .md technical docs
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

EM, EN = "—", "–"

# Files to scan for ANY occurrence (no comment/string discrimination).
BLANKET_PATTERNS = ("*.yml", "*.yaml", "*.j2")

# Python content modules: scan string literals only, not comments.
CONTENT_PATH_FRAGMENT = "src/content/"

# Regex char class exception: a line containing only [...—...] inside
# square brackets is a regex escape and stays.
REGEX_CHAR_CLASS = re.compile(r"\[[^\]]*[—–][^\]]*\]")


def _is_python_comment_line(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith("#")


def _line_is_string_with_em(line: str) -> bool:
    """True if the line is a Python string literal containing em/en
    that isn't entirely a regex character class."""
    if EM not in line and EN not in line:
        return False
    if _is_python_comment_line(line):
        return False
    if REGEX_CHAR_CLASS.search(line):
        # Strip the regex match, recheck
        without_class = REGEX_CHAR_CLASS.sub("", line)
        if EM not in without_class and EN not in without_class:
            return False
    return True


def _scan_blanket_file(path: Path) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    try:
        for i, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if EM in line or EN in line:
                hits.append((i, line))
    except OSError:
        pass
    return hits


def _scan_content_python(path: Path) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    try:
        for i, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if _line_is_string_with_em(line):
                hits.append((i, line))
    except OSError:
        pass
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "roots",
        nargs="*",
        default=["."],
        help="Directories to scan (default: current directory)",
    )
    args = parser.parse_args()

    failures: list[tuple[Path, int, str]] = []

    for root_str in args.roots:
        root = Path(root_str).resolve()
        for pattern in BLANKET_PATTERNS:
            for f in root.rglob(pattern):
                if "/.git/" in str(f) or "/node_modules/" in str(f):
                    continue
                for line_no, line in _scan_blanket_file(f):
                    failures.append((f, line_no, line))
        for f in root.rglob("*.py"):
            if CONTENT_PATH_FRAGMENT not in str(f):
                continue
            if "/__pycache__/" in str(f):
                continue
            for line_no, line in _scan_content_python(f):
                failures.append((f, line_no, line))

    if failures:
        print("Em-dash check failed. Locations:", file=sys.stderr)
        for f, line_no, line in failures:
            print(f"  {f}:{line_no}  {line.rstrip()[:120]}", file=sys.stderr)
        print(
            f"\n{len(failures)} violation(s). See CLAUDE.md §1.2 for the rule.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Library/Frameworks/Python.framework/Versions/Current/bin/python3 -m pytest tests/test_check_em_dashes.py -v`
Expected: 6 tests, all PASS.

- [ ] **Step 5: Run the script against the actual repo**

Run: `/Library/Frameworks/Python.framework/Versions/Current/bin/python3 scripts/check_em_dashes.py .`
Expected: exit 0 (the B.1 sweep already cleaned the in-scope locations). If any hit is reported, investigate before continuing.

- [ ] **Step 6: Commit**

```bash
git add scripts/check_em_dashes.py tests/test_check_em_dashes.py
git commit -m "feat(lint): add targeted em-dash check script"
```

### Task B.2.2 — pre-commit config

**Files:**
- Create: `.pre-commit-config.yaml`
- Create: `scripts/setup_dev.sh`

- [ ] **Step 1: Write the pre-commit config**

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: em-dash-check
        name: Em-dash check (CLAUDE.md §1.2)
        entry: /Library/Frameworks/Python.framework/Versions/Current/bin/python3 scripts/check_em_dashes.py
        language: system
        pass_filenames: false
        always_run: true

      - id: ruff-lint
        name: Ruff lint
        entry: /Library/Frameworks/Python.framework/Versions/Current/bin/python3 -m ruff check
        language: system
        types: [python]
        pass_filenames: true
```

- [ ] **Step 2: Write setup_dev.sh**

```bash
#!/usr/bin/env bash
# Set up the local dev environment for factjot.
# Run once after cloning the repo.

set -euo pipefail

PY=/Library/Frameworks/Python.framework/Versions/Current/bin/python3

echo "Installing pre-commit..."
$PY -m pip install --upgrade pre-commit ruff

echo "Installing git hook..."
pre-commit install

echo "Running pre-commit on all files (one-time check)..."
pre-commit run --all-files || {
  echo "Pre-commit found violations. Fix them before committing."
  exit 1
}

echo "Setup complete. Em-dash check + ruff lint will run on every commit."
```

- [ ] **Step 3: Make setup_dev.sh executable and test the install**

Run: `chmod +x scripts/setup_dev.sh && scripts/setup_dev.sh`
Expected: pre-commit installed, git hook installed, all-files run passes.

- [ ] **Step 4: Verify the hook fires on a fake violation**

```bash
echo 'x = "hello — world"' > src/content/throwaway_test.py
git add src/content/throwaway_test.py
git commit -m "test commit" || echo "GOOD: hook blocked it"
git reset HEAD src/content/throwaway_test.py
rm src/content/throwaway_test.py
```

Expected: commit FAILS with em-dash check error, file gets cleaned up.

- [ ] **Step 5: Commit**

```bash
git add .pre-commit-config.yaml scripts/setup_dev.sh
git commit -m "feat(lint): pre-commit hook with em-dash + ruff checks"
```

### Task B.2.3 — ruff config

**Files:**
- Create: `pyproject.toml`

- [ ] **Step 1: Write pyproject.toml**

```toml
[tool.ruff]
line-length = 100
target-version = "py311"

extend-exclude = [
  ".git",
  "__pycache__",
  ".claude",
  "data",
  "output",
  "logs",
  "assets",
  "brand/fonts",
  "node_modules",
]

[tool.ruff.lint]
# Minimal ruleset per audit decision L. Catches dead imports (F401),
# undefined names (F821), redefined names (F811), comparison errors
# (E711/E712). Does NOT include style or formatting rules - those
# would require a separate format-churn commit.
select = ["F401", "F821", "F811", "E711", "E712"]

# Generated/legacy files we don't lint yet.
[tool.ruff.lint.per-file-ignores]
"src/research/rare_fact_bank.py" = ["F401"]  # Will be retired in Phase G.
```

- [ ] **Step 2: Run ruff against the repo**

Run: `/Library/Frameworks/Python.framework/Versions/Current/bin/python3 -m ruff check .`
Expected: may surface unused imports introduced by Phase A's edits or in pre-existing dormant code. List violations and decide one of:
  - Fix the import (preferred when the surrounding file is alive).
  - Add a per-file ignore in `pyproject.toml` (only for confirmed dormant code on the Phase G deletion list).

- [ ] **Step 3: Apply fixes for any non-dormant violations**

Edit each affected file. Add per-file ignores ONLY for files explicitly listed for deletion in Phase G.

- [ ] **Step 4: Verify clean**

Run: `/Library/Frameworks/Python.framework/Versions/Current/bin/python3 -m ruff check .`
Expected: exit 0 with no violations.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml [any files fixed]
git commit -m "feat(lint): ruff config with minimal correctness ruleset"
```

### Task B.2.4 — wire CI

**Files:**
- Modify: `.github/workflows/test.yml`

- [ ] **Step 1: Read current test.yml**

Run: `cat .github/workflows/test.yml`

- [ ] **Step 2: Add em-dash + ruff steps**

Add these steps before the existing pytest step:

```yaml
      - name: Em-dash check
        run: python3 scripts/check_em_dashes.py .

      - name: Ruff lint
        run: |
          python3 -m pip install ruff
          python3 -m ruff check .
```

- [ ] **Step 3: Commit and verify CI on the next push**

```bash
git add .github/workflows/test.yml
git commit -m "ci: run em-dash check + ruff lint on PRs"
```

After push, watch the CI run on the next PR (B.2 itself, when opened). Both new steps should be green.

### Task B.2.5 — open Phase B.2 PR

- [ ] **Step 1: Push branch and open PR**

```bash
git push -u origin audit-phaseB2-lint-gates
gh pr create --title "Phase B.2: pre-commit hook + ruff lint + em-dash check" --body "..."
```

- [ ] **Step 2: Confirm CI green**

Run: `gh pr view <N> --json statusCheckRollup`

- [ ] **Step 3: Merge**

```bash
gh pr merge <N> --squash --delete-branch
git checkout main && git pull
```

**Acceptance:**
- `git commit` from any working state runs the em-dash + ruff checks before completing.
- A new em-dash typed into a `.yml`, `.j2`, or `src/content/*.py` string blocks the commit.
- An unused import in any non-dormant `.py` file blocks the commit.
- CI on PRs runs the same two checks plus pytest.

**Rollback:** revert the merged commit. Pre-commit hook stays installed but harmless without the script; remove with `pre-commit uninstall`.

---

## 4. Phase C — voice + dedup integrity

**Goal:** Centralise voice normalisation (em-dash strip, smart-quote conversion, double-space collapse) into one module called from every caption builder. Add subject-fingerprint dedup so the autonomous agent cannot ship the same subject twice in 14 days.

**Effort:** 4-8 hours.

**Plan-mode:** partial — voice normaliser is content/ scope (no plan mode). Subject fingerprint touches the agent prompt and `src/brain.py`; agent prompt changes are content scope (no plan mode), but the brain change is a shared safety module — flag for plan mode if the change touches more than the dedup helper.

**Files:**
- Create: `src/content/voice_normaliser.py` — em-dash strip, en-dash strip, smart quote → straight, double-space collapse, etc. Single function `normalise(text: str) -> str`.
- Modify: `src/content/reel_caption.py` — replace `_strip_em_dashes` with import from voice_normaliser; call before final `caption[:2200]` truncate.
- Modify: `src/content/quotes.py` — replace its `_strip_em_dashes` with the shared one.
- Modify: `pipelines/manual/ship_manual_post.py` — wrap final caption build in `voice_normaliser.normalise(...)` before publish.
- Modify: `pipelines/news/ship_news_post.py` — same. (This file is on the Phase G deletion list, but if Phase C ships first, briefly add the wrapper anyway to prevent en-dashes leaking during the gap. Or skip if Phase G is queued tightly behind C.)
- Create: `src/brain.py` (or extend) — `subject_fingerprint(text: str) -> str` returning a normalised noun-phrase fingerprint.
- Modify: `scripts/autonomous_agent.py` — `build_history_summary` includes the fingerprint per entry; `_format_history_entry` adds a fingerprint line; new code-level reject in `main()` if the chosen brief's fingerprint matches anything in last 14 days.
- Modify: `src/content/carousel_writer.py:218-229` — add `cache_control: {"type": "ephemeral"}` to EDITORIAL_PROMPT_TEMPLATE prefix. (Decision M, lives here because carousel writer is the same area as voice work.)
- Test: `tests/test_voice_normaliser.py`, `tests/test_subject_fingerprint.py`, `tests/test_carousel_writer_caching.py`.

**Dependencies:** Phase B.2's lint gates active (so the new module passes ruff cleanly).

**Acceptance:**
- Every caption that ships goes through `voice_normaliser.normalise(...)` immediately before the publish call. Verifiable by greping for `media_publish` and tracing back to confirm the wrapper.
- A reel or carousel whose subject fingerprint matches any of the last 14 days posts gets rejected at the agent loop with a `code-level dedup reject` log line, before the publish tool fires.
- `data/ledgers/api_usage_costs.jsonl` shows `cache_creation_input_tokens` once per carousel run with `cache_read_input_tokens` increasing on subsequent in-render Haiku calls. Net cost per carousel down ~£0.005.
- Test suite: `pytest tests/test_voice_normaliser.py tests/test_subject_fingerprint.py tests/test_carousel_writer_caching.py -v` passes.

**Rollback:** voice_normaliser is additive (the existing `_strip_em_dashes` callsites keep working until removed); revert in pieces if needed. Subject fingerprint adds a check; revert the agent loop changes to disable.

**Risks:**
- Subject fingerprint false positives could over-reject (e.g., two unrelated facts about Soviet history collapsed to "Soviet"). Mitigation: log every reject for a week, manually audit, tune the fingerprint.
- Voice normaliser stripping en-dashes from quoted source material (e.g., a Guardian headline). Mitigation: apply the normaliser only to factjot-authored copy, not to verbatim third-party. Since news pipeline is going away in Phase G, this risk window is short.

---

## 5. Phase D — content quality gates

**Goal:** Add the Q1/A fact verification gate (Haiku consistency check + Wikipedia cross-check on numeric/named claims) and the Q10/K list format rule (defensible criterion stated upfront, opinion superlatives stripped).

**Effort:** 1-2 days.

**Plan-mode:** YES (plan-mode required per CLAUDE.md §2 - touches `src/verification/`, agent prompt, writer prompt).

**Files:**
- Modify: `src/verification/fact_checker.py` — currently exists but unreferenced. Add `verify_consistency(brief: dict) -> dict` that returns `{ok: bool, reason: str}` checking title vs claim does not contradict, brief text does not contain "fictional"/"absurdity"/"experiment".
- Add to same file: `verify_anchors(claims: list[Claim]) -> dict` that uses Wikipedia API to cross-check every numeric/named claim. Returns `{ok: bool, flagged: list[str]}`. Use `wikipedia-api` Python package or direct `requests` against the Wikipedia REST API.
- Modify: `pipelines/manual/ship_manual_post.py` — call `verify_consistency` and `verify_anchors` immediately after `_generate_list_content` returns; reject the run with FAILURE_KIND `fact_verification_failed` if either fails.
- Modify: `pipelines/reel/make_reel.py` — same hook, called on the script before TTS fires (cheaper to reject early).
- Modify: `scripts/autonomous_agent.py` — agent prompt updated with the list format rule (criterion required, opinion superlatives banned, criterion source cited on closing slide).
- Modify: `src/research/story_scout.py` — `LIST_SUPERLATIVE_POOL` (lines 351-377) strip opinion superlatives (`scariest`, `most underrated`, `strangest`, `most bizarre`, `best`, `worst`, `most iconic`, `most influential`, `most disturbing`, `funniest`). Keep numeric: `biggest`, `oldest`, `fastest`, `deadliest`, `longest`, `costliest`.
- Modify: `src/research/story_scout.py` — `build_list_reel_possibilities()` requires a `criterion` field per candidate.
- Modify: `pipelines/manual/ship_manual_post.py` — `LIST_CONTENT_PROMPT` updated to require criterion in cover headline and re-cite on closing slide.
- Test: `tests/test_fact_checker.py`, `tests/test_list_format_rule.py`.

**Dependencies:** Phase C's voice normaliser (the new fact-checker output strings should also be voice-normalised when surfaced to the user).

**Acceptance:**
- A test fact ("Britain rationed bread during WW2") passed to `verify_consistency` against a claim that says the opposite returns `ok: False`.
- A list brief with `format: "Five fictional films ranked by pipeline absurdity"` is rejected at the agent loop with `FAILURE_KIND: fact_verification_failed`.
- A list brief with `criterion: "by death toll"` and 5 real engineering disasters passes.
- A list brief with cover `"Five scariest films"` (bare opinion superlative) is rejected at the candidate-generation step in `build_list_reel_possibilities`.
- Test suite passes.
- Live: a real autonomous run completes a list carousel with a defensible criterion stated on cover and source cited on closing slide.

**Rollback:** revert the fact-checker integration in pipelines (the module stays in place, just unwired). List format rule revert: restore `LIST_SUPERLATIVE_POOL` from git history.

**Risks:**
- Wikipedia API rate limits or downtime block legitimate runs. Mitigation: cache results for 24h, fall back to soft-fail (warn + ship) if Wikipedia is unreachable for >3 retries. Strict-fail is safer in v1; soft-fail can land later if rejection rate is too high.
- Fact-checker false positives reject valid content (model uncertainty, ambiguous claims). Mitigation: log every rejection with the model's reasoning to `data/ledgers/fact_check_rejections.jsonl`; review weekly, tune the prompt.
- List format rule is too strict and the agent calls `skip` on every list slot for the first week. Mitigation: this is the desired outcome until the criterion-required prompt produces well-shaped briefs. Monitor skip rate; tune prompt examples if skip rate >50% after a week.

---

## 6. Phase E — visual integrity

**Goal:** Ship the font hierarchy migration (Q3/C), entity image Haiku validation (Q5/E), thumbnail Haiku-pick + brand overlay (Q6/F), and the empty-cover typography variant (audit P0 #3). Also moves the workflow cadence from 5 slots to 3 (Q4/D), since that change touches `autonomous-reel.yml` which is rendered alongside the visual stack.

**Effort:** 2-3 days. The largest phase.

**Plan-mode:** YES on every sub-task — touches `src/render/`, `brand/brand_kit.json`, `src/core/brand.py`, every template, and the workflow file.

**Sub-phases (separate PRs):**

### E.1 Font hierarchy migration

**Files:**
- Modify: `brand/brand_kit.json` — add `Archivo Bold 700`, `Space Grotesk Bold 700`. Remove `JetBrains Mono Bold`.
- Add font files to `brand/fonts/` and `assets/fonts/`.
- Modify: `src/render/templates/reel_text_frame.html.j2` — `.subtitle` rule: `font-family: "Archivo"; font-weight: 700;`.
- Modify: every template currently using JetBrains Mono — `list_item.html.j2`, `list_hook.html.j2`, `list_closing.html.j2`, `closing.html.j2`, `slide.html.j2`, `stories_frame.html.j2`, `reel_thumbnail.html.j2`, `reel_story.html.j2`, `reel_text_frame.html.j2` `.label-topic`, `reel_case_doc.html.j2`, `reel_photo_insert.html.j2` — swap to `font-family: "Space Grotesk"; font-weight: 700;` and remove `ui-monospace, monospace` fallback.
- Add `text-transform: uppercase` and `letter-spacing: 0.06em-0.1em` to label CSS to compensate for lost monospace affordance.
- Modify: `src/core/brand.py` — expose new font tokens.
- Modify: `CLAUDE.md` §1.9 and §9 — rewrite per `project_font_hierarchy.md`.
- Delete: JetBrains Mono font files from `assets/fonts/` once references are gone.
- Test: render representative examples of every template, eyeball the output.

**Acceptance:** dry-run a reel + a list carousel + a fact carousel + a story; visual inspection confirms the new hierarchy. No JetBrains Mono in any rendered artefact.

### E.2 Empty-cover typography variant

**Files:**
- Modify: `pipelines/news/ship_news_post.py` — add typography variant to `render_cover_slide` (full-canvas Instrument Serif title + label pill + accent rule); branch on empty `photo_data_url`. Thread `layout_mode` through.
- Modify: `pipelines/news/ship_news_post.py:602-655` — `render_story_frame` gets a typography story variant.
- Modify: `pipelines/manual/ship_manual_post.py` — pass `layout_mode` to `render_cover_slide` so list mode gets readable_list cover too.
- Update SPEC_IMAGE_PIPELINE.md §11 if list mode keeps typography fallback (which it does post-2026-05-09); explicitly sanction it.

**Acceptance:** a list run with no usable cover image renders a typography cover that is visibly intentional (accent rule visible, Instrument Serif title, factjot wordmark), not a black canvas.

### E.3 Entity image Haiku validation

**Files:**
- Modify: `src/research/video_finder.py:481-549` — every entity-tier image gets a Haiku check before entering `footage_clips`. Reject on subject mismatch.
- Reuse the Haiku call shape from existing `src/research/image_sourcer.py` validation logic for consistency.
- Test: a reel about "deep ocean pressure" no longer accepts a Hillary Clinton poster as `footage_clips[0]`.

**Acceptance:** running the real "deep ocean pressure" script (the one that produced the Hillary-Clinton-thumbnail incident) renders a topic-appropriate cover, not the off-subject Wikimedia hit.

### E.4 Thumbnail Haiku-pick + brand overlay

**Files:**
- Create: `src/render/thumbnail_picker.py` — render 3 candidate thumbnails per reel (different clips, different frames), Haiku-score on stop-scroll-strength, return strongest. Batch the call with E.3's entity validation (one Haiku call covers both subject-correctness and rank).
- Create: `src/render/templates/reel_thumbnail_overlay.html.j2` — brand overlay per `project_font_hierarchy.md`: 4-6 word headline in Archivo Black 900 INK on PAPER scrim (lower-third) + optional 2-3 word kicker in Space Grotesk Bold 700 uppercase letter-spacing 0.08em + 2px hard drop shadow + wordmark upper corner.
- Create: `src/content/thumbnail_headline.py` — Haiku call to shorten `reel_title` to 4-6 words for the overlay if the title is longer.
- Modify: `pipelines/reel/make_reel.py:961-993` — replace the `footage_clips[0]` cover heuristic with the picker + overlay.
- Modify: `scripts/upload_to_youtube.py` — same overlay-bearing thumbnail used for YouTube custom thumbnail (per Q6: one asset, two surfaces).

**Acceptance:** every recent reel re-rendered with the new thumbnail picker + overlay shows: (a) topic-appropriate footage frame, (b) clear factjot-shaped overlay text, (c) wordmark upper corner, (d) hard drop shadow, no soft gradients. Visual check on 5 reels.

### E.5 Cadence to 3 slots

**Files:**
- Modify: `.github/workflows/autonomous-reel.yml` — strip 2 slots from the cron block (per Q4 the recommended times are 09:00 / 14:00 / 20:30 BST; confirm exact times with Toby at execution time).
- Modify: `scripts/autonomous_agent.py` — VALID_MODES, MODE_PROMPTS, _MODE_FROM_CRON updated to drop the removed modes.
- Modify: `SPEC_FACTJOT_SYSTEM.md` §6.1 — update the 5-slot table to 3 slots; remove the "planned change" note (now shipped).
- Modify: `CLAUDE.md` §5 — same.
- Modify: `src/research/story_scout.py:339-348` — prefix-match logic survives unchanged; just verify the new mode names route correctly.

**Acceptance:** 3 cron slots fire per day. Each slot runs to completion. No orphaned mode references.

**Risks across Phase E:**
- Font migration breaks rendered output (line breaks, character widths, alignment). Mitigation: render every template type before committing.
- Empty-cover variant ships visually weak. Mitigation: design pass with Toby; iterate.
- Entity Haiku validation rejects too aggressively, leaving reels without footage. Mitigation: log all rejections; if rejection rate >30%, soften the prompt.
- Thumbnail Haiku-pick costs add up at scale (~£0.005/reel × 3 reels/day = ~£0.45/month). Acceptable.
- Cadence cut to 3 slots reduces total reach; expected per Q4 reasoning. Two-week test window.

**Rollback per sub-phase:** each E.x is its own PR; revert any one without affecting the others.

---

## 7. Phase F — YouTube divergence

**Goal:** Ship the Q7/G full divergence: Haiku-written Shorts-shaped description + Haiku-written keyword-leading 60-100 char Shorts title + separate higher-bitrate encode pass for YouTube alongside the Meta 5MB encode.

**Effort:** 4-8 hours.

**Plan-mode:** partial — touches `scripts/upload_to_youtube.py` (not in plan-mode list) and adds a new encode call in reel pipeline (in `pipelines/reel/`, not `src/render/`, so not plan-mode required strictly speaking — but the encode call shape change should be reviewed).

**Files:**
- Create: `src/content/youtube_description.py` — Haiku call returning a Shorts-shaped description: 2-line hook + blank line + 3 source URLs + 5 niche hashtags + final `#Shorts`.
- Create: `src/content/youtube_title.py` — Haiku call shortening the reel's IG hook to a 60-100 char keyword-leading title.
- Modify: `scripts/upload_to_youtube.py:170-184` — replace `_description_from_reel_meta` with `youtube_description.build(...)`. Add a `_title_from_reel_meta` that calls `youtube_title.build(...)`.
- Modify: `pipelines/reel/make_reel.py` — after the Meta-shaped MP4 is encoded, run a second FFmpeg pass at `crf 22 maxrate 4M` to produce `final_youtube.mp4`. Pass that path to `scripts/upload_to_youtube.py`.
- Modify: `src/render/reel_composer.py` — expose a `compose_for_youtube(...)` variant or accept a quality preset arg. The encoding logic is the same FFmpeg pipeline; just different output settings.
- Test: `tests/test_youtube_description.py`, `tests/test_youtube_title.py`.

**Dependencies:** Phase E.4 (thumbnail overlay system) for the YouTube custom thumbnail.

**Acceptance:**
- Last 5 YouTube uploads (post-merge) have descriptions that read as written FOR YouTube: short hook, source URLs as clickable links not domains, 5 hashtags max ending with `#Shorts`.
- Last 5 YouTube titles are <=100 chars, lead with a keyword.
- Last 5 YouTube uploads visibly sharper than the IG version (compared side-by-side at 1080p).
- `data/ledgers/youtube_uploads.jsonl` records both encode paths and the title/description used.

**Rollback:** revert the upload script change; YouTube reverts to verbatim IG copy. Encode change can stay in place harmlessly.

**Risks:**
- The second encode pass adds ~30s per reel. Acceptable on the GitHub Actions runner; well inside the 45-minute job budget.
- Haiku-written titles drift off-brand. Mitigation: same hook-balance principle from `project_hook_balance_principle.md`; explicit good/bad examples in the prompt.

---

## 8. Phase G — structural cleanup

**Goal:** Retire `rare_fact_bank.py` (Q9/J), kill the news pipeline (Q2/B and Q9/I), sweep dormant code per CLAUDE.md §12, rewrite `insta-brain/CLAUDE.md` and `PUBLISH_PLAN.md` to match current reality.

**Effort:** 1-2 days. Best done in 3 separate PRs to keep blast radius small.

**Plan-mode:** partial — file deletion does not need plan mode, but the brain rewrite does need careful drafting (heavy doc work).

### G.1 Retire `rare_fact_bank.py`

Per Toby's corrected scope from Q9 (9 import sites, refactor metrics consumer first):

**Files:**
- Modify: `pipelines/reel/fetch_reel_metrics.py` — switch from `load_all_facts()` to reading `data/ledgers/reel_performance.jsonl` directly. Verify all metadata it needs is in the performance ledger.
- Modify: `pipelines/reel/make_reel.py:488-502` — remove `_pick_fact()` function and surrounding fallback branch. Make `--script` mandatory. Update the error message to clearly say "use --script or run via the autonomous agent".
- Modify: `pipelines/reel/make_reel.py:304,356,1245` — remove `load_all_facts` import and the call sites.
- Delete: `src/research/rare_fact_bank.py`.
- Delete: `pipelines/reel/validate_reel_facts.py` (the bank's validator).
- Move (don't delete from main repo, archive per workspace rules): `data/ledgers/discovered_facts.jsonl` → `Brain/raw/archive/relevance/discovered_facts_archived_2026-05-10.jsonl` with header `reference_permitted: false`.
- Modify: `CLAUDE.md` §12 — remove the `rare_fact_bank` and `discovered_facts.jsonl` entries; update the dormant-helpers list to reflect what's actually been deleted.
- Remove the `feedback_validate_reel_facts.md` memory entry (becomes stale on this ship).

**Acceptance:** `pytest tests/ -v` passes; smoke check `python3 pipelines/reel/make_reel.py --dry-run --topic earth` errors gracefully with "use --script" message; `python3 -c "import pipelines.reel.fetch_reel_metrics"` clean.

### G.2 Kill news pipeline

Per Q2/B decision and Q9/I auto-resolution:

**Files:**
- Delete: `.github/workflows/news-watcher.yml`.
- Delete: `pipelines/news/ship_news_breaking.py`.
- Delete: `pipelines/news/check_guardian_rss.py`.
- Modify: `pipelines/news/ship_news_post.py` — leave the file in place because `pipelines/manual/ship_manual_post.py` imports its render helpers (per CLAUDE.md §3 dual role); add a top-of-file comment that the CLI entry point is dead and only the renderer functions are still imported.
- Modify: `pipelines/news/__init__.py` — explicit exports list, only the renderer helpers.
- Archive: `data/ledgers/news_posts.jsonl` → `Brain/raw/archive/relevance/news_posts_archived_2026-05-10.jsonl`.
- Modify: `CLAUDE.md` and `SPEC_FACTJOT_SYSTEM.md` — strip news-watcher references; news pipeline is no longer documented as live.
- Modify: `insta-brain/gotchas.md` — strip news-watcher references.

**Acceptance:** no scheduled workflow references news-watcher; `gh workflow list` shows news-watcher absent or disabled; manual carousel renders still work (the renderer imports survive).

### G.3 Dormant code sweep

**Files (delete):**
- `pipelines/shared/publish_now.py`
- `pipelines/shared/plan_week.py`
- `pipelines/list/ship_list_post.py`
- `pipelines/list/generate_list_packs.py`
- `pipelines/list/prepare_packs.py`
- `pipelines/list/verify_pack_ids.py`
- `pipelines/carousel/ship_first_post.py`
- `pipelines/carousel/restock.py`
- `pipelines/carousel/discover_facts.py`
- `pipelines/reel/discover_reel_facts.py`
- `pipelines/reel/runway.py`
- `pipelines/reel/check_reel_runway.py`

Plus any references in `pipelines/{shared,list,carousel,reel}/__init__.py` exports.

**Acceptance:** `git grep` for each deleted module name returns no live references (only deleted-file diff context). `pytest` still passes. `python3 -m ruff check .` clean.

### G.4 Brain rewrite

**Files:**
- Modify: `insta-brain/CLAUDE.md` — full rewrite to match current production. Drop references to deleted workflows (carousel-morning.yml, reel.yml, list-carousel.yml, weekly-plan.yml), cron-job.org, the old invariant list with 3 fonts. Match the new font hierarchy. Match the 3-slot schedule (assuming Phase E.5 has shipped; otherwise match current 5-slot reality and flag).
- Modify: `insta-brain/PUBLISH_PLAN.md` — same.
- Modify: `insta-brain/CRITICAL_FACTS.md` — same.
- Modify: `insta-brain/gotchas.md` — strip stale entries (cron-job.org, queue, weekly-plan); add new entries for the audit-2026-05-09 changes (subject fingerprint dedup, fact verification gate, font hierarchy migration).

**Acceptance:** read the brain front-to-back; every claim matches the current code or active workflow. No mention of deleted workflows.

**Rollback per sub-phase:** revert each PR independently. The `rare_fact_bank.py` retire is the riskiest — if anything still imports it after merge, ruff catches it (Phase B.2 already shipped) but if a runtime path imports it dynamically, that won't be caught until it fires. Test by running `python3 pipelines/reel/make_reel.py --dry-run --script "..."` and verifying success before merging.

---

## 9. Phase H — observability + tests

**Goal:** Add the smoke tests on the catastrophic-failure surfaces (FFmpeg compose, instagram_publisher, image_host), backfill the `slot` field on `reel_performance.jsonl` for the deferred monthly review, and reconcile any remaining brain/gotchas drift.

**Effort:** 1 day.

**Plan-mode:** no.

**Files:**

### H.1 Smoke tests

- Create: `tests/test_reel_composer_smoke.py` — golden-file test with a 2-second fixture: assert exit code 0, output exists, codec/fps/sample-rate match expected (1080x1920 H264, 30fps, AAC 48kHz mono).
- Create: `tests/test_instagram_publisher_smoke.py` — contract test mocking the Graph API: validates payload shape, retry behaviour, idempotency-token usage, story-container polling (the fix in commit `3a366e1`).
- Create: `tests/test_image_host_smoke.py` — contract test mocking imgbb and tmpfiles: upload → URL retrieval → expiry handling.

### H.2 Slot backfill on reel_performance.jsonl

- Create: `scripts/backfill_reel_performance_slot.py` — read every entry, infer slot from the `posted_at` timestamp (matching against the cron schedule), write `slot` field, save back.
- Run once locally; commit the updated ledger.
- Modify: `pipelines/reel/fetch_reel_metrics.py` — add `slot` field on every new write going forward.
- Modify: `pipelines/reel/make_reel.py` — pass mode through so it can be recorded.

### H.3 Brain reconciliation

- Modify: `insta-brain/gotchas.md` — add entries for (a) the 2026-05-05 force-push triple-post, (b) the IG story-container FINISHED race fix (commit `3a366e1`), (c) the entity-vs-beat crowding fix, (d) the YouTube `youtube_uploads.jsonl` first-cross-post `git add` abort fix from the workflow.

**Acceptance:**
- `pytest tests/test_reel_composer_smoke.py tests/test_instagram_publisher_smoke.py tests/test_image_host_smoke.py -v` passes.
- `data/ledgers/reel_performance.jsonl` every entry has a `slot` field.
- A 30-line Python one-liner can answer "median reach by slot for the last 30 days".
- `gotchas.md` covers every failure mode the audit referenced.

**Rollback:** tests are additive; never regret. Slot backfill is one ledger; if wrong, regenerate from the same script.

**Risks:** none material.

---

## 10. Risk register (cross-phase)

| Risk | Impact | Mitigation |
|---|---|---|
| Mid-phase change breaks a scheduled slot | Missed post | Each phase has a documented rollback (per phase section). Plan-mode phases require dry-run before merge. |
| Phase E font migration breaks rendered output | Visually broken posts ship | Render every template type before committing E.1. Set `--dry-run` smoke render in CI. |
| Phase D fact-checker false positives | Agent skips every slot for days | Soft-fail in v1 (warn + ship) is on the table if hard-fail rejection rate >50% after 3 days. |
| Workflow run starts during a destructive change (Phase G deletion) | Runtime ImportError → missed post | Time deletions to land between scheduled slots (the 2.5h gap between morning and midday is the safest window). |
| Phase G news pipeline kill leaves a dangling import in manual flow | Manual carousel breaks | G.2 explicitly leaves `pipelines/news/ship_news_post.py` in place because manual flow imports its renderer. Verified before delete. |
| Phase E.5 cadence cut produces a slot-routing bug | Wrong content fires at wrong time | Phase A's prefix-match in story_scout already handles this; verify the 3 new mode names route correctly via test before merge. |
| Anthropic API outage during Phase D | Fact-checker times out, agent falls back | Cache 24h, soft-fail after 3 retries with explicit log. |
| Wikipedia API rate limit during Phase D | Same | Same cache + soft-fail strategy. |

---

## 11. Acceptance for "audit complete"

The audit is considered fully implemented when:

1. All 13 decisions have a corresponding shipped PR or are explicitly deferred to the queue with a written reason.
2. Every audit P0 (`Critical`) finding from the synthesis has been addressed.
3. Every audit P1 (`High`) finding has either shipped or has a tracked ticket.
4. The pre-commit hook + ruff lint + em-dash check is enforced on every commit and PR.
5. A live autonomous slot fires successfully end-to-end with: voice-normalised caption, fact-verified content, defensible-criterion list (when list slot fires), Haiku-validated entity image, Haiku-picked thumbnail with brand overlay, full YouTube divergence (own description, own title, sharper encode), and ledger entries with `slot` field.
6. `gotchas.md` and `insta-brain/CLAUDE.md` match current production reality.
7. The deferred-work queue has been reviewed; items still relevant move to `ROADMAP.md`, items obsolete are deleted.

---

## 12. Out-of-scope (deferred to future)

- Monthly human-in-the-loop performance review (trigger: 4 weeks post-audit-ship).
- Mid-weight Haiku performance reports (trigger: 100 reels post-audit-ship).
- Carousel metrics ledger.
- Phase 8 vision frame selector.
- Voice rules centralisation into `src/content/voice.py` (audit P2; partially covered by Phase C voice normaliser, full centralisation deferred).
- TMDB-style confidence gating on carousel side (audit P2; reels-only gating ships in Phase E.3).
- Format-consolidation question (reels-only vs. keep lists). Requires carousel metrics ledger first.
