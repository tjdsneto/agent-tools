import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check-maestro"

SKILL_MD = """---
name: conduct
---
## Before
before line
## The human
human line one
human line two
## After
after line
"""


@pytest.fixture
def upstream(tmp_path):
    d = tmp_path / "conduct"
    (d / "references").mkdir(parents=True)
    (d / "SKILL.md").write_text(SKILL_MD)
    (d / "references" / "decisions-ledger.md").write_text("ledger one\n")
    return d


def run(tmp_path, upstream, *args):
    env = {
        **os.environ,
        "MAESTRO_CONDUCT_DIR": str(upstream),
        "MAESTRO_BASELINE_DIR": str(tmp_path / "baseline"),
    }
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], env=env, capture_output=True, text=True
    )


def edit(path, old, new):
    path.write_text(path.read_text().replace(old, new))


def test_update_then_check_passes(tmp_path, upstream):
    assert run(tmp_path, upstream, "--update").returncode == 0
    r = run(tmp_path, upstream)
    assert r.returncode == 0
    assert "unchanged" in r.stdout


def test_human_section_edit_fails(tmp_path, upstream):
    run(tmp_path, upstream, "--update")
    edit(upstream / "SKILL.md", "human line two", "human line CHANGED")
    r = run(tmp_path, upstream)
    assert r.returncode == 1
    assert "human line CHANGED" in r.stdout


def test_other_section_edit_ignored(tmp_path, upstream):
    run(tmp_path, upstream, "--update")
    edit(upstream / "SKILL.md", "after line", "after CHANGED")
    assert run(tmp_path, upstream).returncode == 0


def test_ledger_edit_fails(tmp_path, upstream):
    run(tmp_path, upstream, "--update")
    edit(upstream / "references" / "decisions-ledger.md", "ledger one", "ledger two")
    r = run(tmp_path, upstream)
    assert r.returncode == 1
    assert "ledger two" in r.stdout


def test_missing_upstream_exits_2(tmp_path):
    r = run(tmp_path, tmp_path / "nope")
    assert r.returncode == 2
    assert "upstream conduct not found" in r.stderr


def test_no_baseline_fails(tmp_path, upstream):
    assert run(tmp_path, upstream).returncode == 1
