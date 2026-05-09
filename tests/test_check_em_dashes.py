"""Tests for the targeted em-dash linter (CLAUDE.md section 1.2)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_em_dashes.py"
PY = sys.executable


def _run(args: list[str]) -> tuple[int, str]:
    res = subprocess.run(
        [PY, str(SCRIPT)] + args,
        capture_output=True,
        text=True,
    )
    return res.returncode, res.stdout + res.stderr


def test_clean_repo_returns_zero(tmp_path):
    # A python file outside src/content/ may carry an em-dash in a comment.
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
    assert "bad.html.j2" in out


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
    # Outside src/content/: the rule does not apply.
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "research").mkdir()
    (tmp_path / "src" / "research" / "internal.py").write_text(
        '"x = some — value"\n'
    )
    rc, _ = _run([str(tmp_path)])
    assert rc == 0


def test_yaml_en_dash_fails(tmp_path):
    # En-dash (U+2013) is also banned in YAML.
    (tmp_path / "bad.yaml").write_text("foo: bar – baz\n")
    rc, out = _run([str(tmp_path)])
    assert rc != 0
    assert "bad.yaml" in out


def test_regex_char_class_in_content_passes(tmp_path):
    # A regex char class containing em/en is the allowed exception.
    content_dir = tmp_path / "src" / "content"
    content_dir.mkdir(parents=True)
    (content_dir / "regex_ok.py").write_text(
        'PATTERN = re.compile(r"[—–-]")\n'
    )
    rc, _ = _run([str(tmp_path)])
    assert rc == 0


def test_clean_directory_returns_zero(tmp_path):
    # Empty directory: trivially clean.
    rc, _ = _run([str(tmp_path)])
    assert rc == 0


def test_skips_git_node_modules_pycache(tmp_path):
    # Files inside ignored directories must not trigger failures.
    for ignored in (".git", "node_modules", "__pycache__"):
        d = tmp_path / ignored
        d.mkdir()
        (d / "junk.yml").write_text("foo: — bar\n")
    rc, _ = _run([str(tmp_path)])
    assert rc == 0


def test_default_root_is_current_dir(tmp_path):
    # No positional arg defaults to cwd.
    (tmp_path / "bad.yml").write_text("foo: — bar\n")
    res = subprocess.run(
        [PY, str(SCRIPT)],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "bad.yml" in (res.stdout + res.stderr)
