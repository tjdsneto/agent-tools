# claude-session-mngr Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only `claude-session-mngr` capability that reports every Claude Code
session touched today — running (including cmux-delegated tabs) or already closed — with
per-session and daily-total token counts.

**Architecture:** A pure/testable library (`_sessions.py`) holds all parsing, correlation, and
aggregation logic as small functions that take plain data in and return plain data out (no
subprocess calls inside the pure functions — those are isolated in a handful of thin I/O
wrapper functions at the bottom of the same file). A thin CLI script (`session-report`) wires
the I/O wrappers together and prints a table or `--json`. Exposed globally via a `bin/`
symlink, matching how `opc`/`buddy` are already exposed.

**Tech Stack:** Python 3 stdlib only (`json`, `re`, `subprocess`, `pathlib`, `datetime`,
`argparse`, `unittest`) — no third-party dependencies, no venv (mirrors
`ai/claude/scripts/test_park.py`'s convention, not `bookmarks`' pytest-venv convention, since
there's nothing here that needs a package pytest doesn't already give you via `unittest`).

**Reference spec:** `docs/superpowers/specs/2026-07-28-claude-session-mngr-design.md`

---

## Before you start

All commands below assume your shell's cwd is the repo root
(`/Users/tjdsneto/projects/tjdsneto-setup`). This repo commits directly to `master` — no
branches (see the repo's `CLAUDE.md`). Commit after every task, in order, so the diff never
sits large and uncommitted for long (there may be a sibling session also committing to this
repo concurrently).

Every code fact below (the `ps`/`cmux` output shapes, the transcript JSON shape) was verified
live against the real machine during design — see the spec's "Implementation risks — resolved
during design" section if you want the raw evidence.

---

### Task 1: Time/usage helpers — `local_midnight`, `parse_ts`, `sum_usage`

**Files:**
- Create: `claude-session-mngr/scripts/_sessions.py`
- Create: `claude-session-mngr/scripts/tests/test_sessions.py`

- [ ] **Step 1: Write the failing tests**

Create `claude-session-mngr/scripts/tests/test_sessions.py`:

```python
"""Tests for _sessions.py. Run: python3 claude-session-mngr/scripts/tests/test_sessions.py -v"""
import pathlib
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import _sessions as s


class LocalMidnightTests(unittest.TestCase):
    def test_returns_midnight_same_day_same_tz(self):
        now = datetime(2026, 7, 28, 14, 32, 9, tzinfo=timezone.utc)
        midnight = s.local_midnight(now)
        self.assertEqual(
            midnight, datetime(2026, 7, 28, 0, 0, 0, tzinfo=timezone.utc)
        )


class ParseTsTests(unittest.TestCase):
    def test_parses_z_suffixed_timestamp(self):
        ts = s.parse_ts("2026-07-28T13:40:40.903Z")
        self.assertEqual(ts.year, 2026)
        self.assertEqual(ts.tzinfo, timezone.utc)

    def test_returns_none_for_missing(self):
        self.assertIsNone(s.parse_ts(None))

    def test_returns_none_for_garbage(self):
        self.assertIsNone(s.parse_ts("not-a-timestamp"))


class SumUsageTests(unittest.TestCase):
    def test_sums_known_fields(self):
        usage = {
            "input_tokens": 2,
            "cache_creation_input_tokens": 26780,
            "cache_read_input_tokens": 29434,
            "output_tokens": 928,
        }
        self.assertEqual(
            s.sum_usage(usage),
            {"input": 2, "cache_write": 26780, "cache_read": 29434, "output": 928},
        )

    def test_missing_fields_default_to_zero(self):
        self.assertEqual(
            s.sum_usage({"output_tokens": 5}),
            {"input": 0, "cache_write": 0, "cache_read": 0, "output": 5},
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 claude-session-mngr/scripts/tests/test_sessions.py -v`
Expected: `ModuleNotFoundError: No module named '_sessions'` (the file doesn't exist yet).

- [ ] **Step 3: Write the minimal implementation**

Create `claude-session-mngr/scripts/_sessions.py`:

```python
"""Session/token reporting for Claude Code — parsing, correlation, and aggregation.

Pure functions take plain data in and return plain data out (no subprocess calls).
The handful of I/O wrapper functions at the bottom are the only ones that touch the
OS (ps/lsof/cmux/filesystem); everything else is unit-testable without mocking.
"""
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePath

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


def local_midnight(now=None):
    """Return today's local midnight as an aware datetime (tz preserved from `now`)."""
    now = now or datetime.now().astimezone()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def parse_ts(ts_str):
    """Parse a transcript's ISO timestamp string (Z-suffixed UTC) to an aware datetime."""
    if not ts_str:
        return None
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(ts_str)
    except ValueError:
        return None


def sum_usage(usage):
    """Extract the four token categories we report from a message.usage dict."""
    return {
        "input": usage.get("input_tokens", 0),
        "cache_write": usage.get("cache_creation_input_tokens", 0),
        "cache_read": usage.get("cache_read_input_tokens", 0),
        "output": usage.get("output_tokens", 0),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 claude-session-mngr/scripts/tests/test_sessions.py -v`
Expected: `OK` — all 6 tests pass (note: `parse_ts` uses `timezone.utc` for the `Z` case,
confirm `ts.tzinfo == timezone.utc` — `fromisoformat("...+00:00")` yields exactly that).

- [ ] **Step 5: Commit**

```bash
git add claude-session-mngr/scripts/_sessions.py claude-session-mngr/scripts/tests/test_sessions.py
git commit -m "feat(claude-session-mngr): add time/usage parsing helpers"
```

---

### Task 2: `parse_transcript_lines`

**Files:**
- Modify: `claude-session-mngr/scripts/_sessions.py` (append)
- Modify: `claude-session-mngr/scripts/tests/test_sessions.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `claude-session-mngr/scripts/tests/test_sessions.py` (add the import at top: this
class also needs `json`, add `import json` near the top imports):

```python
class ParseTranscriptLinesTests(unittest.TestCase):
    MIDNIGHT = datetime(2026, 7, 28, 0, 0, 0, tzinfo=timezone.utc)

    def _line(self, obj):
        return json.dumps(obj)

    def test_sums_only_todays_assistant_lines(self):
        lines = [
            self._line({
                "type": "assistant", "cwd": "/repo", "gitBranch": "master",
                "timestamp": "2026-07-27T23:59:00.000Z",
                "message": {"usage": {"input_tokens": 100, "output_tokens": 50}},
            }),
            self._line({
                "type": "assistant", "cwd": "/repo", "gitBranch": "master",
                "timestamp": "2026-07-28T09:00:00.000Z",
                "message": {"usage": {"input_tokens": 2, "output_tokens": 928,
                                       "cache_creation_input_tokens": 26780,
                                       "cache_read_input_tokens": 29434}},
            }),
        ]
        result = s.parse_transcript_lines(lines, self.MIDNIGHT)
        self.assertEqual(result["tokens"],
                          {"input": 2, "cache_write": 26780, "cache_read": 29434, "output": 928})
        self.assertEqual(result["cwd"], "/repo")
        self.assertEqual(result["branch"], "master")
        self.assertEqual(result["last_active"], datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc))

    def test_returns_none_when_nothing_today(self):
        lines = [self._line({
            "type": "assistant", "timestamp": "2026-07-27T23:59:00.000Z",
            "message": {"usage": {"input_tokens": 1}},
        })]
        self.assertIsNone(s.parse_transcript_lines(lines, self.MIDNIGHT))

    def test_skips_unparseable_lines(self):
        lines = ["not json at all", self._line({
            "type": "assistant", "timestamp": "2026-07-28T09:00:00.000Z",
            "message": {"usage": {"output_tokens": 3}},
        })]
        result = s.parse_transcript_lines(lines, self.MIDNIGHT)
        self.assertEqual(result["tokens"]["output"], 3)

    def test_title_from_custom_title_record(self):
        lines = [
            self._line({
                "type": "user", "timestamp": "2026-07-28T09:00:00.000Z",
                "message": {"content": "hello there"},
            }),
            self._line({"type": "custom-title", "customTitle": "My Session"}),
        ]
        result = s.parse_transcript_lines(lines, self.MIDNIGHT)
        self.assertEqual(result["title"], "My Session")

    def test_title_falls_back_to_first_user_message(self):
        lines = [self._line({
            "type": "user", "timestamp": "2026-07-28T09:00:00.000Z",
            "message": {"content": "hello there"},
        })]
        result = s.parse_transcript_lines(lines, self.MIDNIGHT)
        self.assertEqual(result["title"], "hello there")
```

Also add `import json` to the top of the test file's import block.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 claude-session-mngr/scripts/tests/test_sessions.py -v`
Expected: `AttributeError: module '_sessions' has no attribute 'parse_transcript_lines'`

- [ ] **Step 3: Write the minimal implementation**

Append to `claude-session-mngr/scripts/_sessions.py` (`json` is already imported from Task 1):

```python
def _extract_user_text(obj):
    content = obj.get("message", {}).get("content", [])
    if isinstance(content, str):
        text = content.strip()
        return text[:200] if text and not text.startswith("<") else None
    if isinstance(content, list):
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                text = c.get("text", "").strip()
                if text and not text.startswith("<"):
                    return text[:200]
    return None


def parse_transcript_lines(lines, midnight):
    """Parse one transcript's lines, keeping only today's (>= midnight) for token sums.

    Returns None if the transcript has no line timestamped today, even if it passed
    the file-mtime prefilter (a file can be touched today without any new event, or
    the mtime filter can be a loose approximation).
    """
    totals = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
    cwd = branch = title = first_msg = last_active = None
    found_today = False

    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue

        if not cwd and obj.get("cwd"):
            cwd = obj["cwd"]
        if not branch and obj.get("gitBranch"):
            branch = obj["gitBranch"]
        if obj.get("type") == "custom-title":
            title = obj.get("customTitle") or obj.get("title")
        if obj.get("type") == "user" and not first_msg:
            first_msg = _extract_user_text(obj)

        ts = parse_ts(obj.get("timestamp"))
        if ts is None or ts < midnight:
            continue
        found_today = True
        if last_active is None or ts > last_active:
            last_active = ts

        if obj.get("type") == "assistant":
            msg = obj.get("message") or {}
            usage = msg.get("usage")
            if usage:
                u = sum_usage(usage)
                for key in totals:
                    totals[key] += u[key]

    if not found_today:
        return None

    return {
        "cwd": cwd,
        "branch": branch,
        "title": title or first_msg,
        "tokens": totals,
        "last_active": last_active,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 claude-session-mngr/scripts/tests/test_sessions.py -v`
Expected: `OK` — 11 tests pass.

- [ ] **Step 5: Commit**

```bash
git add claude-session-mngr/scripts/_sessions.py claude-session-mngr/scripts/tests/test_sessions.py
git commit -m "feat(claude-session-mngr): parse a transcript's today-only token totals"
```

---

### Task 3: `find_todays_transcript_paths` + `session_key_for_path`

> **Amended during implementation (discovered by Task 3's own code-quality review):**
> subagent/Task-tool transcripts do NOT live inline in the parent session's transcript
> with an `isSidechain` marker (the original assumption, both here and in the design
> spec) — they live in **separate nested files**: `<project>/<session-id>/subagents/
> agent-<hash>.jsonl`. Verified live: 519 such files exist on this machine right now,
> with real token usage in them, none reachable by the original `*/*.jsonl` glob. Left
> unfixed, daily totals would silently undercount on any day that used subagents —
> which is routine, and is exactly the "cmux/agent sprawl" scenario this tool exists to
> surface. Fix, decided with Tiago: widen the glob, and add `session_key_for_path` so
> `gather_report` (Task 9, also amended) can fold a subagent file's usage into its
> *parent* session's totals instead of the file's own name. Each subagent file's own
> JSON lines also carry a `sessionId` field equal to the parent's — confirmed live —
> but the path-based key below is cheaper (no need to open/parse the file just to find
> out which session it belongs to) and was confirmed to give the identical value.

**Files:**
- Modify: `claude-session-mngr/scripts/_sessions.py` (append)
- Modify: `claude-session-mngr/scripts/tests/test_sessions.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `claude-session-mngr/scripts/tests/test_sessions.py` (add `import os` and
`import tempfile` to the top imports):

```python
class FindTodaysTranscriptPathsTests(unittest.TestCase):
    def test_filters_by_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            project_dir = root / "-Users-tjdsneto-projects-example"
            project_dir.mkdir()
            old_file = project_dir / "old-session.jsonl"
            new_file = project_dir / "new-session.jsonl"
            old_file.write_text("{}\n")
            new_file.write_text("{}\n")

            midnight = datetime(2026, 7, 28, 0, 0, 0, tzinfo=timezone.utc)
            yesterday_ts = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc).timestamp()
            today_ts = datetime(2026, 7, 28, 9, 0, 0, tzinfo=timezone.utc).timestamp()
            os.utime(old_file, (yesterday_ts, yesterday_ts))
            os.utime(new_file, (today_ts, today_ts))

            found = s.find_todays_transcript_paths(midnight, claude_dir=root)
            self.assertEqual(found, [new_file])

    def test_missing_dir_returns_empty(self):
        midnight = datetime(2026, 7, 28, 0, 0, 0, tzinfo=timezone.utc)
        found = s.find_todays_transcript_paths(
            midnight, claude_dir=pathlib.Path("/nonexistent/does-not-exist")
        )
        self.assertEqual(found, [])

    def test_includes_subagent_transcripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            session_dir = root / "-Users-tjdsneto-projects-example" / "abc123"
            subagents_dir = session_dir / "subagents"
            subagents_dir.mkdir(parents=True)
            subagent_file = subagents_dir / "agent-xyz.jsonl"
            subagent_file.write_text("{}\n")

            midnight = datetime(2026, 7, 28, 0, 0, 0, tzinfo=timezone.utc)
            today_ts = datetime(2026, 7, 28, 9, 0, 0, tzinfo=timezone.utc).timestamp()
            os.utime(subagent_file, (today_ts, today_ts))

            found = s.find_todays_transcript_paths(midnight, claude_dir=root)
            self.assertEqual(found, [subagent_file])


class SessionKeyForPathTests(unittest.TestCase):
    def test_top_level_file_keys_on_stem(self):
        path = pathlib.Path("/root/-Users-x-project/abc123.jsonl")
        self.assertEqual(s.session_key_for_path(path), "abc123")

    def test_subagent_file_keys_on_parent_session_id(self):
        path = pathlib.Path("/root/-Users-x-project/abc123/subagents/agent-xyz.jsonl")
        self.assertEqual(s.session_key_for_path(path), "abc123")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 claude-session-mngr/scripts/tests/test_sessions.py -v`
Expected: `AttributeError: module '_sessions' has no attribute 'find_todays_transcript_paths'`
(and, once that's added, a second failure for `session_key_for_path` — add both functions
in Step 3 before re-running, per the note below).

- [ ] **Step 3: Write the minimal implementation**

Append to `claude-session-mngr/scripts/_sessions.py`:

```python
def find_todays_transcript_paths(midnight, claude_dir=CLAUDE_PROJECTS_DIR):
    """List transcript files whose mtime is >= midnight (a cheap candidate prefilter —
    the actual today/not-today decision happens per-line in parse_transcript_lines).

    Includes both top-level session transcripts (<project>/<session-id>.jsonl) and
    subagent transcripts (<project>/<session-id>/subagents/<file>.jsonl) — Task-tool
    delegated work writes its usage to the latter, not inline in the parent file.
    """
    if not claude_dir.is_dir():
        return []
    cutoff = midnight.timestamp()
    candidates = list(claude_dir.glob("*/*.jsonl")) + list(claude_dir.glob("*/*/subagents/*.jsonl"))
    return [p for p in candidates if p.stat().st_mtime >= cutoff]


def session_key_for_path(path):
    """Return the session id a transcript file's usage should be attributed to.

    Subagent transcripts (<project>/<session-id>/subagents/<file>.jsonl) fold into
    their parent session; top-level transcripts (<project>/<session-id>.jsonl) key
    on their own filename stem, which IS the session id.
    """
    if path.parent.name == "subagents":
        return path.parent.parent.name
    return path.stem
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 claude-session-mngr/scripts/tests/test_sessions.py -v`
Expected: `OK` — 16 tests pass.

- [ ] **Step 5: Commit**

```bash
git add claude-session-mngr/scripts/_sessions.py claude-session-mngr/scripts/tests/test_sessions.py
git commit -m "feat(claude-session-mngr): find today's candidate transcripts by mtime

Includes subagent/Task-tool transcripts (<session-id>/subagents/*.jsonl),
not just top-level ones — verified live these are separate files, not
inline sidechain lines as originally assumed. session_key_for_path lets
gather_report (Task 9) fold their usage into the parent session."
```

> **If Task 3 was already implemented and committed before this amendment landed**
> (i.e. you're fixing it up after the fact rather than building it fresh): treat this
> as a follow-up fix on top of the existing commit — same TDD flow (add the 3 new
> tests + `session_key_for_path`, widen the glob), commit message
> `fix(claude-session-mngr): include subagent transcripts and add session_key_for_path`.

---

### Task 4: `parse_ps_output`

**Files:**
- Modify: `claude-session-mngr/scripts/_sessions.py` (append)
- Modify: `claude-session-mngr/scripts/tests/test_sessions.py` (append)

This is the corrected filter from the spec: match on `argv[0]`'s basename being `claude`, not
on `"stream-json" in line` (verified during design to miss every cmux-launched session).

- [ ] **Step 1: Write the failing test**

Append to `claude-session-mngr/scripts/tests/test_sessions.py`:

```python
PS_SAMPLE = (
    "31443 ttys001  /Users/tjdsneto/.nvm/versions/node/v20.20.2/bin/claude "
    "--session-id 6fd0cd9d-4c9d-40bc-baa9-9ccad36956a6 --dangerously-skip-permissions do the thing\n"
    "68474 ttys011  /Users/tjdsneto/.nvm/versions/node/v20.20.2/bin/claude "
    "--resume 51aa2e3f-ae51-404b-b672-8a872fe0ee1b --dangerously-skip-permissions do the other thing\n"
    "53633 ttys000  /Users/tjdsneto/.nvm/versions/node/v20.20.2/bin/claude --dangerously-skip-permissions\n"
    "56838 ??       /bin/zsh -c source snapshot.sh\n"
)


class ParsePsOutputTests(unittest.TestCase):
    def test_extracts_claude_processes_only(self):
        procs = s.parse_ps_output(PS_SAMPLE)
        self.assertEqual(len(procs), 3)
        self.assertTrue(all(p["pid"] for p in procs))

    def test_extracts_session_id_flag(self):
        procs = s.parse_ps_output(PS_SAMPLE)
        by_pid = {p["pid"]: p for p in procs}
        self.assertEqual(by_pid["31443"]["session_id"], "6fd0cd9d-4c9d-40bc-baa9-9ccad36956a6")

    def test_extracts_resume_flag(self):
        procs = s.parse_ps_output(PS_SAMPLE)
        by_pid = {p["pid"]: p for p in procs}
        self.assertEqual(by_pid["68474"]["session_id"], "51aa2e3f-ae51-404b-b672-8a872fe0ee1b")

    def test_no_id_flag_gives_none(self):
        procs = s.parse_ps_output(PS_SAMPLE)
        by_pid = {p["pid"]: p for p in procs}
        self.assertIsNone(by_pid["53633"]["session_id"])

    def test_captures_tty(self):
        procs = s.parse_ps_output(PS_SAMPLE)
        by_pid = {p["pid"]: p for p in procs}
        self.assertEqual(by_pid["31443"]["tty"], "ttys001")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 claude-session-mngr/scripts/tests/test_sessions.py -v`
Expected: `AttributeError: module '_sessions' has no attribute 'parse_ps_output'`

- [ ] **Step 3: Write the minimal implementation**

Append to `claude-session-mngr/scripts/_sessions.py`:

```python
SESSION_ID_FLAG_RE = re.compile(r"--(?:session-id|resume)\s+(\S+)")


def parse_ps_output(text):
    """Parse `ps -eo pid=,tty=,command=` output into live claude-CLI process records.

    Filters to processes whose argv[0] basename is exactly "claude" — NOT a
    "stream-json" substring match (that misses cmux-launched interactive sessions
    entirely; verified live during design).
    """
    processes = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        pid, tty, command = parts
        argv0 = command.split(None, 1)[0]
        if PurePath(argv0).name != "claude":
            continue
        match = SESSION_ID_FLAG_RE.search(command)
        processes.append({
            "pid": pid,
            "tty": tty,
            "session_id": match.group(1) if match else None,
        })
    return processes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 claude-session-mngr/scripts/tests/test_sessions.py -v`
Expected: `OK` — 21 tests pass.

- [ ] **Step 5: Commit**

```bash
git add claude-session-mngr/scripts/_sessions.py claude-session-mngr/scripts/tests/test_sessions.py
git commit -m "feat(claude-session-mngr): parse live claude processes from ps output"
```

---

### Task 5: `parse_cmux_tree_json`

**Files:**
- Modify: `claude-session-mngr/scripts/_sessions.py` (append)
- Modify: `claude-session-mngr/scripts/tests/test_sessions.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `claude-session-mngr/scripts/tests/test_sessions.py`:

```python
CMUX_TREE_SAMPLE = {
    "windows": [
        {
            "workspaces": [
                {
                    "title": "GCal integration",
                    "ref": "workspace:2",
                    "panes": [
                        {
                            "surfaces": [
                                {"type": "terminal", "tty": "ttys011", "title": "..."},
                            ]
                        }
                    ],
                },
                {
                    "title": "No panes yet",
                    "ref": "workspace:9",
                    "panes": [],
                },
                {
                    "title": "Has a browser surface",
                    "ref": "workspace:3",
                    "panes": [
                        {
                            "surfaces": [
                                {"type": "browser", "tty": None, "title": "some site"},
                            ]
                        }
                    ],
                },
            ]
        }
    ]
}


class ParseCmuxTreeJsonTests(unittest.TestCase):
    def test_maps_tty_to_workspace_title(self):
        result = s.parse_cmux_tree_json(CMUX_TREE_SAMPLE)
        self.assertEqual(result, {"ttys011": "GCal integration"})

    def test_ignores_non_terminal_surfaces(self):
        result = s.parse_cmux_tree_json(CMUX_TREE_SAMPLE)
        self.assertNotIn(None, result)

    def test_empty_tree_gives_empty_map(self):
        self.assertEqual(s.parse_cmux_tree_json({"windows": []}), {})

    def test_maps_multiple_workspaces(self):
        tree = {
            "windows": [{
                "workspaces": [
                    {"title": "Workspace A", "ref": "workspace:1", "panes": [
                        {"surfaces": [{"type": "terminal", "tty": "ttys001", "title": "..."}]}
                    ]},
                    {"title": "Workspace B", "ref": "workspace:2", "panes": [
                        {"surfaces": [{"type": "terminal", "tty": "ttys002", "title": "..."}]}
                    ]},
                ]
            }]
        }
        result = s.parse_cmux_tree_json(tree)
        self.assertEqual(result, {"ttys001": "Workspace A", "ttys002": "Workspace B"})
```

> **Amended after code-quality review**: the original 3 tests all shared `CMUX_TREE_SAMPLE`,
> which happens to have only one workspace with a terminal surface — nothing proved the
> function accumulates across multiple matches rather than handling just one. Added
> `test_maps_multiple_workspaces` with its own inline two-workspace fixture to close the gap
> (committed separately as `test(claude-session-mngr): cover multiple cmux workspaces in
> parse_cmux_tree_json`, on top of this task's own commit).

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 claude-session-mngr/scripts/tests/test_sessions.py -v`
Expected: `AttributeError: module '_sessions' has no attribute 'parse_cmux_tree_json'`

- [ ] **Step 3: Write the minimal implementation**

Append to `claude-session-mngr/scripts/_sessions.py`:

```python
def parse_cmux_tree_json(data):
    """Build a {tty: workspace_title} map from `cmux tree --all --json` output."""
    tty_map = {}
    for window in data.get("windows", []):
        for workspace in window.get("workspaces", []):
            title = workspace.get("title") or workspace.get("ref")
            for pane in workspace.get("panes", []):
                for surface in pane.get("surfaces", []):
                    if surface.get("type") == "terminal" and surface.get("tty"):
                        tty_map[surface["tty"]] = title
    return tty_map
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 claude-session-mngr/scripts/tests/test_sessions.py -v`
Expected: `OK` — 25 tests pass.

- [ ] **Step 5: Commit**

```bash
git add claude-session-mngr/scripts/_sessions.py claude-session-mngr/scripts/tests/test_sessions.py
git commit -m "feat(claude-session-mngr): parse cmux tree JSON into a tty->workspace map"
```

---

### Task 6: `match_live_processes`

**Files:**
- Modify: `claude-session-mngr/scripts/_sessions.py` (append)
- Modify: `claude-session-mngr/scripts/tests/test_sessions.py` (append)

**Contract:** `match_live_processes(processes, sessions) -> {session_id: {"pid", "tty"}}`.
`processes` is a list of dicts with `pid`, `tty`, `session_id` (optional), `cwd` (optional —
already resolved by the caller via `lsof`, this function does no I/O). `sessions` is a dict of
`session_id -> parsed_transcript_dict` (as returned by `parse_transcript_lines`, keyed by the
transcript's filename stem). Explicit `session_id` matches win; otherwise, fall back to the
session in the same `cwd` with the most recent `last_active`, skipping sessions already claimed.

- [ ] **Step 1: Write the failing tests**

Append to `claude-session-mngr/scripts/tests/test_sessions.py`:

```python
class MatchLiveProcessesTests(unittest.TestCase):
    def _session(self, cwd, last_active):
        return {"cwd": cwd, "branch": None, "title": None,
                "tokens": {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0},
                "last_active": last_active}

    def test_matches_by_explicit_session_id(self):
        sessions = {"abc": self._session("/repo", datetime(2026, 7, 28, 9, tzinfo=timezone.utc))}
        processes = [{"pid": "1", "tty": "ttys001", "session_id": "abc", "cwd": "/repo"}]
        matched = s.match_live_processes(processes, sessions)
        self.assertEqual(matched, {"abc": {"pid": "1", "tty": "ttys001"}})

    def test_ignores_id_not_in_todays_sessions(self):
        processes = [{"pid": "1", "tty": "ttys001", "session_id": "unknown-id", "cwd": "/repo"}]
        matched = s.match_live_processes(processes, {})
        self.assertEqual(matched, {})

    def test_falls_back_to_newest_by_cwd_when_no_id(self):
        sessions = {
            "older": self._session("/repo", datetime(2026, 7, 28, 8, tzinfo=timezone.utc)),
            "newer": self._session("/repo", datetime(2026, 7, 28, 9, tzinfo=timezone.utc)),
        }
        processes = [{"pid": "1", "tty": "ttys001", "session_id": None, "cwd": "/repo"}]
        matched = s.match_live_processes(processes, sessions)
        self.assertEqual(matched, {"newer": {"pid": "1", "tty": "ttys001"}})

    def test_two_processes_same_cwd_claim_different_sessions(self):
        sessions = {
            "older": self._session("/repo", datetime(2026, 7, 28, 8, tzinfo=timezone.utc)),
            "newer": self._session("/repo", datetime(2026, 7, 28, 9, tzinfo=timezone.utc)),
        }
        processes = [
            {"pid": "1", "tty": "ttys001", "session_id": None, "cwd": "/repo"},
            {"pid": "2", "tty": "ttys002", "session_id": None, "cwd": "/repo"},
        ]
        matched = s.match_live_processes(processes, sessions)
        self.assertEqual(len(matched), 2)
        self.assertEqual({v["pid"] for v in matched.values()}, {"1", "2"})

    def test_no_cwd_match_is_ignored(self):
        sessions = {"a": self._session("/repo", datetime(2026, 7, 28, 9, tzinfo=timezone.utc))}
        processes = [{"pid": "1", "tty": "ttys001", "session_id": None, "cwd": "/other"}]
        self.assertEqual(s.match_live_processes(processes, sessions), {})

    def test_explicit_id_preempts_fallback_target_for_another_process(self):
        sessions = {
            "newest": self._session("/repo", datetime(2026, 7, 28, 9, tzinfo=timezone.utc)),
            "older": self._session("/repo", datetime(2026, 7, 28, 8, tzinfo=timezone.utc)),
        }
        processes = [
            {"pid": "1", "tty": "ttys001", "session_id": "newest", "cwd": "/repo"},
            {"pid": "2", "tty": "ttys002", "session_id": None, "cwd": "/repo"},
        ]
        matched = s.match_live_processes(processes, sessions)
        self.assertEqual(matched, {
            "newest": {"pid": "1", "tty": "ttys001"},
            "older": {"pid": "2", "tty": "ttys002"},
        })
```

> **Amended after code-quality review**: the original 5 tests proved pass 2's internal
> claim-tracking (two no-id processes competing) but never proved the plan's central
> guarantee — an explicit `session_id` match pre-empting what would otherwise be a SECOND,
> different process's fallback target. Added `test_explicit_id_preempts_fallback_target_for_
> another_process` to close the gap (committed separately as `test(claude-session-mngr):
> cover explicit-id precedence over another process's fallback`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 claude-session-mngr/scripts/tests/test_sessions.py -v`
Expected: `AttributeError: module '_sessions' has no attribute 'match_live_processes'`

- [ ] **Step 3: Write the minimal implementation**

Append to `claude-session-mngr/scripts/_sessions.py`:

```python
def match_live_processes(processes, sessions):
    """Correlate live claude processes to today's sessions. See Task 6 docstring in the
    plan for the matching contract (explicit id first, then newest-in-cwd fallback)."""
    matched = {}
    claimed = set()

    for proc in processes:
        sid = proc.get("session_id")
        if sid and sid in sessions and sid not in claimed:
            matched[sid] = {"pid": proc["pid"], "tty": proc["tty"]}
            claimed.add(sid)

    for proc in processes:
        sid = proc.get("session_id")
        if sid and sid in claimed:
            continue
        cwd = proc.get("cwd")
        if not cwd:
            continue
        candidates = sorted(
            (
                (data["last_active"], s_id)
                for s_id, data in sessions.items()
                if data.get("cwd") == cwd and s_id not in claimed
            ),
            reverse=True,
        )
        if not candidates:
            continue
        _, best_id = candidates[0]
        matched[best_id] = {"pid": proc["pid"], "tty": proc["tty"]}
        claimed.add(best_id)

    return matched
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 claude-session-mngr/scripts/tests/test_sessions.py -v`
Expected: `OK` — 31 tests pass.

- [ ] **Step 5: Commit**

```bash
git add claude-session-mngr/scripts/_sessions.py claude-session-mngr/scripts/tests/test_sessions.py
git commit -m "feat(claude-session-mngr): correlate live processes to today's sessions"
```

---

### Task 7: `build_report`

**Files:**
- Modify: `claude-session-mngr/scripts/_sessions.py` (append)
- Modify: `claude-session-mngr/scripts/tests/test_sessions.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `claude-session-mngr/scripts/tests/test_sessions.py`:

```python
class BuildReportTests(unittest.TestCase):
    def _session(self, cwd, tokens, last_active, title="t"):
        return {"cwd": cwd, "branch": "master", "title": title,
                "tokens": tokens, "last_active": last_active}

    def test_totals_sum_across_sessions(self):
        sessions = {
            "a": self._session("/repo", {"input": 10, "cache_write": 0, "cache_read": 0, "output": 5},
                                datetime(2026, 7, 28, 8, tzinfo=timezone.utc)),
            "b": self._session("/repo2", {"input": 1, "cache_write": 2, "cache_read": 3, "output": 4},
                                datetime(2026, 7, 28, 9, tzinfo=timezone.utc)),
        }
        report = s.build_report(sessions, matched={}, cmux_map={})
        self.assertEqual(report["totals"],
                          {"input": 11, "cache_write": 2, "cache_read": 3, "output": 9})
        self.assertEqual(report["session_count"], 2)
        self.assertEqual(report["running_count"], 0)

    def test_running_session_gets_workspace_label(self):
        zero = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
        sessions = {"a": self._session("/repo", zero, datetime(2026, 7, 28, 8, tzinfo=timezone.utc))}
        matched = {"a": {"pid": "1", "tty": "ttys001"}}
        cmux_map = {"ttys001": "My Workspace"}
        report = s.build_report(sessions, matched, cmux_map)
        row = report["rows"][0]
        self.assertEqual(row["status"], "running")
        self.assertEqual(row["workspace"], "My Workspace")
        self.assertEqual(report["running_count"], 1)

    def test_closed_session_has_no_workspace(self):
        zero = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
        sessions = {"a": self._session("/repo", zero, datetime(2026, 7, 28, 8, tzinfo=timezone.utc))}
        report = s.build_report(sessions, matched={}, cmux_map={})
        row = report["rows"][0]
        self.assertEqual(row["status"], "closed")
        self.assertIsNone(row["workspace"])

    def test_running_session_without_cmux_match_has_no_workspace(self):
        zero = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
        sessions = {"a": self._session("/repo", zero, datetime(2026, 7, 28, 8, tzinfo=timezone.utc))}
        matched = {"a": {"pid": "1", "tty": "ttys999"}}
        report = s.build_report(sessions, matched, cmux_map={})
        self.assertIsNone(report["rows"][0]["workspace"])

    def test_rows_sorted_by_last_active_desc(self):
        zero = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
        sessions = {
            "older": self._session("/repo", zero, datetime(2026, 7, 28, 8, tzinfo=timezone.utc)),
            "newer": self._session("/repo", zero, datetime(2026, 7, 28, 9, tzinfo=timezone.utc)),
        }
        report = s.build_report(sessions, matched={}, cmux_map={})
        self.assertEqual([r["session_id"] for r in report["rows"]], ["newer", "older"])

    def test_running_count_with_multiple_running_sessions(self):
        zero = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
        sessions = {
            "a": self._session("/repo", zero, datetime(2026, 7, 28, 8, tzinfo=timezone.utc)),
            "b": self._session("/repo2", zero, datetime(2026, 7, 28, 9, tzinfo=timezone.utc)),
        }
        matched = {
            "a": {"pid": "1", "tty": "ttys001"},
            "b": {"pid": "2", "tty": "ttys002"},
        }
        report = s.build_report(sessions, matched, cmux_map={})
        self.assertEqual(report["running_count"], 2)
        self.assertEqual({r["status"] for r in report["rows"]}, {"running"})
```

> **Amended after code-quality review**: all original 5 tests exercised `running_count` at
> either 0 or 1 — nothing proved it correctly accumulates across 2+ concurrently running
> sessions rather than, e.g., saturating at 1. Added `test_running_count_with_multiple_
> running_sessions` to close the gap (committed separately as `test(claude-session-mngr):
> cover running_count with multiple concurrent sessions`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 claude-session-mngr/scripts/tests/test_sessions.py -v`
Expected: `AttributeError: module '_sessions' has no attribute 'build_report'`

- [ ] **Step 3: Write the minimal implementation**

Append to `claude-session-mngr/scripts/_sessions.py`:

```python
def build_report(sessions, matched, cmux_map):
    """Assemble the final report: rows (one per today's session) + daily totals."""
    rows = []
    totals = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
    running_count = 0

    for sid, data in sessions.items():
        running = sid in matched
        workspace = None
        if running:
            running_count += 1
            workspace = cmux_map.get(matched[sid]["tty"])
        for key in totals:
            totals[key] += data["tokens"][key]
        rows.append({
            "session_id": sid,
            "cwd": data["cwd"],
            "title": data["title"],
            "status": "running" if running else "closed",
            "workspace": workspace,
            "tokens": data["tokens"],
            "last_active": data["last_active"],
        })

    rows.sort(key=lambda r: r["last_active"], reverse=True)

    return {
        "rows": rows,
        "totals": totals,
        "session_count": len(rows),
        "running_count": running_count,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 claude-session-mngr/scripts/tests/test_sessions.py -v`
Expected: `OK` — 37 tests pass.

- [ ] **Step 5: Commit**

```bash
git add claude-session-mngr/scripts/_sessions.py claude-session-mngr/scripts/tests/test_sessions.py
git commit -m "feat(claude-session-mngr): assemble the merged report + daily totals"
```

---

### Task 8: `format_report_table`

**Files:**
- Modify: `claude-session-mngr/scripts/_sessions.py` (append)
- Modify: `claude-session-mngr/scripts/tests/test_sessions.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `claude-session-mngr/scripts/tests/test_sessions.py`:

```python
class FormatReportTableTests(unittest.TestCase):
    def test_empty_report_has_clear_message(self):
        report = {"rows": [], "totals": {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0},
                   "session_count": 0, "running_count": 0}
        self.assertEqual(s.format_report_table(report), "No sessions today.")

    def test_table_includes_session_and_totals(self):
        report = {
            "rows": [{
                "session_id": "6fd0cd9d-4c9d-40bc-baa9-9ccad36956a6",
                "cwd": "/repo", "title": "My Session", "status": "running",
                "workspace": "claude-session-mngr",
                "tokens": {"input": 2, "cache_write": 26780, "cache_read": 29434, "output": 928},
                "last_active": datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc),
            }],
            "totals": {"input": 12, "cache_write": 100, "cache_read": 200, "output": 300},
            "session_count": 1, "running_count": 1,
        }
        table = s.format_report_table(report)
        self.assertIn("6fd0cd9d", table)
        self.assertIn("running", table)
        self.assertIn("claude-session-mngr", table)
        self.assertIn("My Session", table)
        self.assertIn("928", table)
        self.assertIn("1 sessions, 1 running", table)
        footer = table.splitlines()[-1]
        self.assertIn("input=12", footer)
        self.assertIn("cache_write=100", footer)
        self.assertIn("cache_read=200", footer)
        self.assertIn("output=300", footer)
```

> **Amended after code-quality review**: the original test reused identical values for the
> row's tokens and `report["totals"]`, so it couldn't distinguish a footer field-swap (e.g.
> `cache_write`/`cache_read` transposed) from correct output — verified by injection that
> swapping those two fields still passed every original assertion. Now uses distinct
> totals (12/100/200/300) from the row's tokens (2/26780/29434/928) and asserts each footer
> field explicitly.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 claude-session-mngr/scripts/tests/test_sessions.py -v`
Expected: `AttributeError: module '_sessions' has no attribute 'format_report_table'`

- [ ] **Step 3: Write the minimal implementation**

Append to `claude-session-mngr/scripts/_sessions.py`:

```python
def format_report_table(report):
    """Render the report as a human-readable table + totals footer."""
    if not report["rows"]:
        return "No sessions today."

    header = (
        f"{'Session':10}  {'Status':8}  {'Workspace':22}  {'Input':>8}  {'C.Write':>8}  "
        f"{'C.Read':>8}  {'Output':>8}  {'Last active':16}  Title / cwd"
    )
    lines = [header, "-" * len(header)]

    for row in report["rows"]:
        tokens = row["tokens"]
        workspace = (row["workspace"] or "")[:22]
        last_active = row["last_active"].astimezone().strftime("%H:%M")
        label = (row["title"] or row["cwd"] or "")[:50]
        lines.append(
            f"{row['session_id'][:8]:10}  {row['status']:8}  {workspace:22}  "
            f"{tokens['input']:>8}  {tokens['cache_write']:>8}  {tokens['cache_read']:>8}  "
            f"{tokens['output']:>8}  {last_active:16}  {label}"
        )

    totals = report["totals"]
    lines.append("-" * len(header))
    lines.append(
        f"TOTAL ({report['session_count']} sessions, {report['running_count']} running): "
        f"input={totals['input']}  cache_write={totals['cache_write']}  "
        f"cache_read={totals['cache_read']}  output={totals['output']}"
    )
    return "\n".join(lines)
```

> **Amended after code-quality review**: `workspace` was the only display field NOT
> truncated (`session_id` gets `[:8]`, `label` gets `[:50]`) — a cmux workspace title longer
> than 22 chars would overflow the column and misalign every subsequent field in that row.
> Reproduced live during review; fixed by slicing `workspace` to `[:22]` before formatting.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 claude-session-mngr/scripts/tests/test_sessions.py -v`
Expected: `OK` — 39 tests pass.

- [ ] **Step 5: Commit**

```bash
git add claude-session-mngr/scripts/_sessions.py claude-session-mngr/scripts/tests/test_sessions.py
git commit -m "feat(claude-session-mngr): render the report as a human-readable table"
```

> **If Task 8 was already implemented and committed before this amendment landed**: apply
> as a follow-up fix, commit message `fix(claude-session-mngr): truncate workspace column
> and strengthen totals-footer test`.

---

### Task 9: `merge_parsed_sessions` + I/O wrappers + `gather_report` orchestration

> **Amended during implementation** (see Task 3's amendment note): `gather_report`'s
> session-building loop originally keyed on `path.stem` and overwrote blindly. Now that
> `find_todays_transcript_paths` also returns subagent transcripts, multiple files can
> map to the same session (via `session_key_for_path`), so this task adds
> `merge_parsed_sessions` and changes the loop to merge instead of overwrite.

**Files:**
- Modify: `claude-session-mngr/scripts/_sessions.py` (append)
- Modify: `claude-session-mngr/scripts/tests/test_sessions.py` (append)

`run_ps` and `get_process_cwd` are thin, untested I/O wrappers (mirrors `active-sessions`,
which has zero tests for its own `ps`/`lsof` calls). `get_cmux_tty_workspace_map` is different:
the spec explicitly requires testing its "cmux missing/failed → graceful empty map" contract
(this is the whole point of treating cmux as a soft dependency), so it takes an injectable
`run` callable — production code passes `subprocess.run` (the default), tests pass a fake.
`merge_parsed_sessions` is a small pure function, tested directly like the rest of the module.

- [ ] **Step 1: Write the failing tests**

Append to `claude-session-mngr/scripts/tests/test_sessions.py` (add `import subprocess` to the
test file's top imports):

```python
class MergeParsedSessionsTests(unittest.TestCase):
    def test_sums_tokens_and_keeps_latest_last_active(self):
        a = {"cwd": "/repo", "branch": "master", "title": "Main",
             "tokens": {"input": 10, "cache_write": 0, "cache_read": 0, "output": 5},
             "last_active": datetime(2026, 7, 28, 8, tzinfo=timezone.utc)}
        b = {"cwd": None, "branch": None, "title": None,
             "tokens": {"input": 1, "cache_write": 2, "cache_read": 3, "output": 4},
             "last_active": datetime(2026, 7, 28, 9, tzinfo=timezone.utc)}
        merged = s.merge_parsed_sessions(a, b)
        self.assertEqual(merged["tokens"],
                          {"input": 11, "cache_write": 2, "cache_read": 3, "output": 9})
        self.assertEqual(merged["last_active"], datetime(2026, 7, 28, 9, tzinfo=timezone.utc))
        self.assertEqual(merged["cwd"], "/repo")
        self.assertEqual(merged["title"], "Main")


class GetCmuxTtyWorkspaceMapTests(unittest.TestCase):
    def test_returns_map_on_success(self):
        def fake_run(*args, **kwargs):
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout=json.dumps(CMUX_TREE_SAMPLE)
            )
        result = s.get_cmux_tty_workspace_map(run=fake_run)
        self.assertEqual(result, {"ttys011": "GCal integration"})

    def test_returns_empty_when_binary_missing(self):
        def fake_run(*args, **kwargs):
            raise FileNotFoundError("cmux not found")
        self.assertEqual(s.get_cmux_tty_workspace_map(run=fake_run), {})

    def test_returns_empty_on_nonzero_exit(self):
        def fake_run(*args, **kwargs):
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="")
        self.assertEqual(s.get_cmux_tty_workspace_map(run=fake_run), {})

    def test_returns_empty_on_timeout(self):
        def fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="cmux", timeout=2)
        self.assertEqual(s.get_cmux_tty_workspace_map(run=fake_run), {})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 claude-session-mngr/scripts/tests/test_sessions.py -v`
Expected: `AttributeError: module '_sessions' has no attribute 'merge_parsed_sessions'`
(and, once that's added, `get_cmux_tty_workspace_map` — add both functions in Step 3 before
re-running).

- [ ] **Step 3: Write the implementation**

Append to `claude-session-mngr/scripts/_sessions.py`:

```python
def merge_parsed_sessions(a, b):
    """Combine two parsed transcript results attributed to the same session key
    (e.g. a top-level session's own file + one of its subagent transcripts)."""
    totals = {key: a["tokens"][key] + b["tokens"][key] for key in a["tokens"]}
    return {
        "cwd": a["cwd"] or b["cwd"],
        "branch": a["branch"] or b["branch"],
        "title": a["title"] or b["title"],
        "tokens": totals,
        "last_active": max(a["last_active"], b["last_active"]),
    }


def run_ps():
    result = subprocess.run(
        ["ps", "-eo", "pid=,tty=,command="], capture_output=True, text=True
    )
    return result.stdout


def get_process_cwd(pid):
    try:
        result = subprocess.run(
            ["lsof", "-p", pid], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if " cwd " in line:
                return line.split()[-1]
    except Exception:
        pass
    return None


def get_cmux_tty_workspace_map(timeout=2, run=subprocess.run):
    try:
        result = run(
            ["cmux", "tree", "--all", "--json"],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            return {}
        data = json.loads(result.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return {}
    return parse_cmux_tree_json(data)


def gather_report(now=None):
    """Full pipeline: today's transcripts + live processes + cmux -> merged report."""
    now = now or datetime.now().astimezone()
    midnight = local_midnight(now)

    sessions = {}
    for path in find_todays_transcript_paths(midnight):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        parsed = parse_transcript_lines(lines, midnight)
        if not parsed:
            continue
        key = session_key_for_path(path)
        sessions[key] = merge_parsed_sessions(sessions[key], parsed) if key in sessions else parsed

    processes = parse_ps_output(run_ps())
    for proc in processes:
        proc["cwd"] = get_process_cwd(proc["pid"])

    matched = match_live_processes(processes, sessions)
    cmux_map = get_cmux_tty_workspace_map()

    return build_report(sessions, matched, cmux_map)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 claude-session-mngr/scripts/tests/test_sessions.py -v`
Expected: `OK` — 44 tests pass (39 from Tasks 1-8, plus 1 for `merge_parsed_sessions` and 4
for `get_cmux_tty_workspace_map`; `run_ps`/`get_process_cwd`/`gather_report` add no tests of
their own — they're thin I/O glue, verified instead by Step 5's live smoke test).

- [ ] **Step 5: Manual smoke test against the real machine**

Run:
```bash
python3 -c "
import sys; sys.path.insert(0, 'claude-session-mngr/scripts')
import _sessions as s
report = s.gather_report()
print(s.format_report_table(report))
"
```
Expected: a table listing today's real Claude Code sessions (including this one), with
non-zero token counts and, if cmux is running, at least one row tagged `running` with a
cmux workspace name matching one of your actual open cmux tabs. No traceback.

- [ ] **Step 6: Commit**

```bash
git add claude-session-mngr/scripts/_sessions.py claude-session-mngr/scripts/tests/test_sessions.py
git commit -m "feat(claude-session-mngr): wire up ps/lsof/cmux I/O and the gather_report pipeline"
```

---

### Task 10: `session-report` CLI

**Files:**
- Create: `claude-session-mngr/scripts/session-report`

- [ ] **Step 1: Write the CLI script**

Create `claude-session-mngr/scripts/session-report`:

```python
#!/usr/bin/env python3
"""session-report - Report on Claude Code sessions touched today.

Shows every session (running or already closed) with activity today, tagged with its
cmux workspace when running inside one, plus per-session and daily-total token counts.
Read-only: never mutates cmux, Claude Code, or any transcript.

Usage:
    session-report          # human-readable table
    session-report --json   # machine-readable
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _sessions as s


def _json_default(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Not JSON serializable: {obj!r}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    report = s.gather_report()

    if args.json:
        print(json.dumps(report, indent=2, default=_json_default))
    else:
        print(s.format_report_table(report))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make it executable**

Run: `chmod +x claude-session-mngr/scripts/session-report`

- [ ] **Step 3: Run it directly and verify both output modes**

Run: `python3 claude-session-mngr/scripts/session-report`
Expected: the same table as Task 9's smoke test.

Run: `python3 claude-session-mngr/scripts/session-report --json`
Expected: valid JSON (pipe to `python3 -m json.tool` to confirm it parses:
`python3 claude-session-mngr/scripts/session-report --json | python3 -m json.tool > /dev/null`
— exit code 0, no error).

- [ ] **Step 4: Commit**

```bash
git add claude-session-mngr/scripts/session-report
git commit -m "feat(claude-session-mngr): add the session-report CLI entrypoint"
```

---

### Task 11: Expose as a global command via `bin/`

**Files:**
- Create: `bin/session-report` (symlink)

- [ ] **Step 1: Create the symlink**

Run (from repo root):
```bash
ln -s ../claude-session-mngr/scripts/session-report bin/session-report
```

- [ ] **Step 2: Verify it resolves and runs**

Run: `ls -la bin/session-report`
Expected: shows `bin/session-report -> ../claude-session-mngr/scripts/session-report`.

Run: `bin/session-report` (or, if your shell has already re-read `$PATH` and this repo's
`bin/` is on it — confirmed earlier during design that it is — just `session-report` from
any directory)
Expected: same table output as Task 10, no "command not found", no broken-symlink error.

- [ ] **Step 3: Commit**

```bash
git add bin/session-report
git commit -m "feat(claude-session-mngr): expose session-report as a global bin/ command"
```

---

### Task 12: Claude-facing skill doc

**Files:**
- Create: `ai/skills/claude/claude-session-mngr/SKILL.md`

- [ ] **Step 1: Write the skill**

Create `ai/skills/claude/claude-session-mngr/SKILL.md`:

```markdown
---
name: claude-session-mngr
description: Report on Claude Code sessions touched today (running — including cmux-delegated tabs — or already closed), with per-session and daily token totals. Use when Tiago asks "what sessions are running", "how many tokens today", "session report", "what did I run today", or wants visibility into Claude Code session/token sprawl.
user-invocable: true
argument-hint: "[--json]"
---

# claude-session-mngr

Read-only report of every Claude Code session touched today. Run:

```bash
session-report
```

or, for machine-readable output:

```bash
session-report --json
```

## What it shows

One row per session with any activity today (regardless of whether the process is still
running): session id (short), running/closed status, cmux workspace name (if it's running
inside a cmux tab — blank for plain-terminal or already-closed sessions), per-category token
counts (input / cache-write / cache-read / output), and last-active time. A totals footer
gives the daily grand total per token category plus session/running counts.

## How it works

- **"Today"** means any transcript line timestamped since local midnight — a session that
  started yesterday and continued into today still counts, but only today's tokens are summed.
- **cmux correlation** is a soft dependency: if `cmux` isn't running or the call fails, every
  session just shows with no workspace label (falls back to "plain terminal"). Never errors.
- **Includes subagent/Task-tool usage** — a session's token total includes any subagents it
  delegated to (`<session-id>/subagents/*.jsonl`), folded into the parent session's row rather
  than shown as separate rows.
- **Never mutates anything** — pure read of `~/.claude/projects/*/*.jsonl` and its `subagents/`
  transcripts, `ps`, `lsof`, and `cmux tree --all --json`.

## Related

- `session-awareness` skill (`active-sessions`/`list-sessions`) is a separate, pre-existing
  tool with some overlap (live-process listing). Its fate (retire/keep/merge) is undecided —
  see `docs/superpowers/specs/2026-07-28-claude-session-mngr-design.md`.
- Implementation lives in `claude-session-mngr/scripts/` (`_sessions.py` is the tested
  library; `session-report` is the thin CLI). Tests:
  `python3 claude-session-mngr/scripts/tests/test_sessions.py -v`.
```

- [ ] **Step 2: Deploy it locally**

Run: `./install.sh`
Expected: output includes `Linked claude-session-mngr (claude)` under the
"ai/skills/claude/ → Claude Code only" section.

- [ ] **Step 3: Verify the symlink landed**

Run: `ls -la ~/.claude/skills/claude-session-mngr/`
Expected: `SKILL.md -> .../ai/skills/claude/claude-session-mngr/SKILL.md`.

- [ ] **Step 4: Commit**

```bash
git add ai/skills/claude/claude-session-mngr/SKILL.md
git commit -m "feat(claude-session-mngr): add the Claude-facing skill doc"
```

---

### Task 13: Capability README

**Files:**
- Create: `claude-session-mngr/README.md`

- [ ] **Step 1: Write the README**

Create `claude-session-mngr/README.md`:

```markdown
# claude-session-mngr

Read-only report of Claude Code sessions touched today — running (including cmux-delegated
tabs) or already closed — with per-session and daily token totals.

## Run it

```bash
session-report          # human-readable table (global command, via bin/session-report)
session-report --json   # machine-readable
```

## Layout

- `scripts/_sessions.py` — pure/testable library: transcript parsing, `ps`/`lsof`/`cmux`
  correlation, aggregation. No subprocess calls except in the small set of I/O wrapper
  functions at the bottom of the file.
- `scripts/session-report` — thin CLI: calls `_sessions.gather_report()`, prints table or JSON.
- `scripts/tests/test_sessions.py` — unit tests, stdlib `unittest`, no venv needed (no
  third-party dependencies anywhere in this capability).

## Tests

```bash
python3 claude-session-mngr/scripts/tests/test_sessions.py -v
```

## Design notes

Full design rationale, data-source verification, and resolved risks:
`docs/superpowers/specs/2026-07-28-claude-session-mngr-design.md`.
```

- [ ] **Step 2: Commit**

```bash
git add claude-session-mngr/README.md
git commit -m "docs(claude-session-mngr): add capability README"
```

---

### Task 14: Update the digital-life capabilities tracker

**Files:**
- Modify: `assistant/brain/projects/digital-life.md`

`claude-session-mngr` isn't an *external-service* capability like the ones in the "Capabilities
backlog" list (Drive, Gmail, YouTube, …) — it's introspection into Claude Code itself. Record it
as an adjacent, same-pattern tool rather than folding it into that list's own stated scope.

- [ ] **Step 1: Add a new section**

In `assistant/brain/projects/digital-life.md`, after the `## Links` section at the end of the
file, add:

```markdown

## Adjacent tooling (same repo pattern, not an external-service capability)

- **`claude-session-mngr`** (built 2026-07-28) — read-only report of Claude Code sessions
  touched today (running, incl. cmux-delegated tabs, or closed) + per-session/daily token
  totals. Not a "digital-life" external-service integration like the list above — it's
  introspection into Claude Code's own usage, raised after a day running 5 concurrent
  delegated cmux sessions made session/token sprawl a real pain point. Spec:
  `docs/superpowers/specs/2026-07-28-claude-session-mngr-design.md`. Skill:
  `ai/skills/claude/claude-session-mngr/SKILL.md`. Overlaps partly with the pre-existing
  `session-awareness` skill; that skill's fate (retire/keep/merge) is deliberately undecided
  until `claude-session-mngr` has been used for a while.
```

- [ ] **Step 2: Commit**

```bash
git add assistant/brain/projects/digital-life.md
git commit -m "docs(digital-life): record claude-session-mngr capability"
```

---

### Task 14.5: Post-build amendment — final comprehensive review findings

> **Added after Task 14**, once every individual task had already passed its own two-stage
> review. A final, whole-capability review (reading `_sessions.py` top-to-bottom, cross-
> checking the design spec against the finished code) found two integration-level gaps that
> no single task's review could see. Discussed with Tiago; decided to implement both now.

**Files:**
- Modify: `claude-session-mngr/scripts/_sessions.py`
- Modify: `claude-session-mngr/scripts/tests/test_sessions.py`

#### Fix 1: `gather_report` can hard-crash on a non-UTF-8 transcript byte

`path.read_text(encoding="utf-8").splitlines()` was wrapped in `except OSError: continue` —
but `UnicodeDecodeError` is a `ValueError` subclass, NOT an `OSError`, so it was never caught.
One bad byte in any transcript would crash the entire report for every session, directly
contradicting the design spec's explicit "nothing here should ever hard-crash" guarantee.

In `gather_report`, change:
```python
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
```
to:
```python
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
```

#### Fix 2: implement the `~` "best-guess" marker the design spec promised but the plan never built

The spec's "Error handling & edge cases" section says a session matched only by the
cwd+newest-active heuristic (no `--session-id`/`--resume` in its process's argv — only
happens for a manually-typed `claude`, never a cmux-delegated one) should get the same `~`
marker `active-sessions` already uses for uncertain matches. No task's code ever threaded
this through. Fix: add a `certain` flag to `match_live_processes`'s output (`True` for
explicit-id matches, `False` for cwd-fallback matches), read defensively (`.get(...,
True)`) by `build_report` and `format_report_table` so existing hand-built test fixtures
that predate this field don't need to change unless they're testing the new behavior itself.

In `match_live_processes`, change both `matched[...] = {"pid": ..., "tty": ...}` assignments:
```python
            matched[sid] = {"pid": proc["pid"], "tty": proc["tty"], "certain": True}
```
(pass 1, explicit id) and
```python
        matched[best_id] = {"pid": proc["pid"], "tty": proc["tty"], "certain": False}
```
(pass 2, cwd fallback).

In `build_report`, inside the `if running:` block, add:
```python
            certain = matched[sid].get("certain", True)
```
and add `"certain": certain,` to the row dict (alongside the other row fields; when not
running, `certain` stays `True` — the default set before the `if running:` block).

In `format_report_table`, prepend `~` when uncertain, matching `active-sessions`' own
convention. Change:
```python
        lines.append(
            f"{row['session_id'][:8]:10}  {row['status']:8}  {workspace:22}  "
```
to:
```python
        certainty = "" if row.get("certain", True) else "~"
        lines.append(
            f"{certainty + row['session_id'][:8]:10}  {row['status']:8}  {workspace:22}  "
```

**Test updates** — the 3 existing `MatchLiveProcessesTests` methods that assert exact
dict equality on `match_live_processes`'s return value need `"certain": True`/`"certain":
False` added to their expected dicts (`test_matches_by_explicit_session_id` → `True`;
`test_falls_back_to_newest_by_cwd_when_no_id` → `False`; `test_explicit_id_preempts_
fallback_target_for_another_process` → `True` for `"newest"`, `False` for `"older"`).
Existing `BuildReportTests`/`FormatReportTableTests` fixtures that omit `"certain"` entirely
keep passing unchanged (the `.get(..., True)` default), but add these new tests:

```python
# in BuildReportTests
    def test_uncertain_match_is_marked_in_row(self):
        zero = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
        sessions = {"a": self._session("/repo", zero, datetime(2026, 7, 28, 8, tzinfo=timezone.utc))}
        matched = {"a": {"pid": "1", "tty": "ttys001", "certain": False}}
        report = s.build_report(sessions, matched, cmux_map={})
        self.assertEqual(report["rows"][0]["certain"], False)

# in FormatReportTableTests
    def test_uncertain_row_gets_tilde_prefix(self):
        report = {
            "rows": [{
                "session_id": "6fd0cd9d-4c9d-40bc-baa9-9ccad36956a6",
                "cwd": "/repo", "title": "My Session", "status": "running",
                "workspace": None, "certain": False,
                "tokens": {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0},
                "last_active": datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc),
            }],
            "totals": {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0},
            "session_count": 1, "running_count": 1,
        }
        table = s.format_report_table(report)
        self.assertIn("~6fd0cd9d", table)
```

Also add, to the existing `test_closed_session_has_no_workspace` (Task 7), one more line:
`self.assertTrue(row["certain"])` — locking in that closed sessions default to certain.

Also add, to the existing SKILL.md's "How it works" section, a bullet: `- Sessions matched
only by heuristic (no --session-id/--resume in their process — a manually-typed claude, not
a cmux-delegated one) are shown with a ~ prefix, same convention as active-sessions.`

#### Fix 3 (Minor, doc-only): record the accepted `SESSION_ID_FLAG_RE` trade-off

Two separate reviews (Task 4's and the final review) independently noticed
`SESSION_ID_FLAG_RE` scans a process's full, unanchored command-line text — including
whatever free-text prompt Claude Code appends to argv — so a delegated task whose prompt
happens to contain literal `--session-id <token>`/`--resume <token>` text could
theoretically be misattributed. Both reviews accepted this as low-risk (narrow collision
window, read-only tool) but nothing recorded that acceptance anywhere. Add a one-line
comment directly above `SESSION_ID_FLAG_RE` in `_sessions.py`:
```python
# Scans the full command line unanchored — a delegated task's prompt text containing a
# literal "--session-id <uuid>"/"--resume <uuid>" substring could in theory be misread as
# the flag. Accepted as low-risk (narrow collision window; read-only tool) during review.
```

- [ ] **Run the full test suite**

Run: `python3 claude-session-mngr/scripts/tests/test_sessions.py -v`
Expected: `OK` — 46 tests pass (44 prior + 2 new: `test_uncertain_match_is_marked_in_row`,
`test_uncertain_row_gets_tilde_prefix`).

> **Amended after code-quality review, via mutation testing**: flipping either `.get(...,
> True)` default to `.get(..., False)` in `build_report`/`format_report_table` left all 46
> tests green — the "missing key defaults to certain" guarantee had zero regression
> protection. Added two more tests using a `matched`/row dict that OMITS the `"certain"` key
> entirely (not just sets it `True`), confirmed each catches the corresponding mutation:
>
> ```python
> # in BuildReportTests
>     def test_missing_certain_key_defaults_to_true(self):
>         zero = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
>         sessions = {"a": self._session("/repo", zero, datetime(2026, 7, 28, 8, tzinfo=timezone.utc))}
>         matched = {"a": {"pid": "1", "tty": "ttys001"}}  # no "certain" key at all
>         report = s.build_report(sessions, matched, cmux_map={})
>         self.assertTrue(report["rows"][0]["certain"])
>
> # in FormatReportTableTests
>     def test_row_missing_certain_key_has_no_tilde_prefix(self):
>         report = {
>             "rows": [{
>                 "session_id": "6fd0cd9d-4c9d-40bc-baa9-9ccad36956a6",
>                 "cwd": "/repo", "title": "My Session", "status": "running",
>                 "workspace": None,  # no "certain" key at all
>                 "tokens": {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0},
>                 "last_active": datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc),
>             }],
>             "totals": {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0},
>             "session_count": 1, "running_count": 1,
>         }
>         table = s.format_report_table(report)
>         self.assertIn("6fd0cd9d", table)
>         self.assertNotIn("~6fd0cd9d", table)
> ```
> Committed separately as `test(claude-session-mngr): cover the certain-key-missing default
> path`. Final count: 48 tests.

- [ ] **Manual smoke test**

Run `session-report` for real; confirm no crash, confirm any session matched only by
heuristic (if one exists right now) shows the `~` prefix.

- [ ] **Commit** (as 3 separate commits, matching this amendment's 3 fixes)

```bash
git add claude-session-mngr/scripts/_sessions.py
git commit -m "fix(claude-session-mngr): catch UnicodeDecodeError in gather_report's file read"

git add claude-session-mngr/scripts/_sessions.py claude-session-mngr/scripts/tests/test_sessions.py ai/skills/claude/claude-session-mngr/SKILL.md
git commit -m "feat(claude-session-mngr): mark heuristically-matched sessions with a ~ prefix"

git add claude-session-mngr/scripts/_sessions.py
git commit -m "docs(claude-session-mngr): record the accepted SESSION_ID_FLAG_RE trade-off"
```

---

### Task 15: Full verification pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite one more time**

Run: `python3 claude-session-mngr/scripts/tests/test_sessions.py -v`
Expected: `OK` — all tests pass (48 from the plan, after the Task 14.5 post-build amendment;
more if you added any while implementing).

- [ ] **Step 2: Run the real CLI one more time from a fresh shell**

Open a new terminal (so `$PATH` and the `bin/` symlink are picked up exactly as a real
invocation would), `cd` to the repo, and run:
```bash
session-report
```
Expected: a real, current table — including this very build session as one of the rows,
tagged `running` with today's actual token counts.

- [ ] **Step 3: Confirm git status is clean**

Run: `git status --short`
Expected: no output (everything from this plan was committed task-by-task).

- [ ] **Step 4: Report completion**

Summarize for Tiago: what was built, the exact command (`session-report` / `session-report
--json`), and remind him the `session-awareness` skill's fate is still an open, deliberately
deferred decision.
