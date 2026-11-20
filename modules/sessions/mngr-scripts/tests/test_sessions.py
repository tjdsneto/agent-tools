"""Tests for _sessions.py. Run: python3 claude-session-mngr/scripts/tests/test_sessions.py -v"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
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


class MatchLiveProcessesTests(unittest.TestCase):
    def _session(self, cwd, last_active):
        return {"cwd": cwd, "branch": None, "title": None,
                "tokens": {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0},
                "last_active": last_active}

    def test_matches_by_explicit_session_id(self):
        sessions = {"abc": self._session("/repo", datetime(2026, 7, 28, 9, tzinfo=timezone.utc))}
        processes = [{"pid": "1", "tty": "ttys001", "session_id": "abc", "cwd": "/repo"}]
        matched = s.match_live_processes(processes, sessions)
        self.assertEqual(matched, {"abc": {"pid": "1", "tty": "ttys001", "certain": True}})

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
        self.assertEqual(matched, {"newer": {"pid": "1", "tty": "ttys001", "certain": False}})

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
            "newest": {"pid": "1", "tty": "ttys001", "certain": True},
            "older": {"pid": "2", "tty": "ttys002", "certain": False},
        })

    def test_no_cwd_match_is_ignored(self):
        sessions = {"a": self._session("/repo", datetime(2026, 7, 28, 9, tzinfo=timezone.utc))}
        processes = [{"pid": "1", "tty": "ttys001", "session_id": None, "cwd": "/other"}]
        self.assertEqual(s.match_live_processes(processes, sessions), {})


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
        self.assertTrue(row["certain"])

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

    def test_uncertain_match_is_marked_in_row(self):
        zero = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
        sessions = {"a": self._session("/repo", zero, datetime(2026, 7, 28, 8, tzinfo=timezone.utc))}
        matched = {"a": {"pid": "1", "tty": "ttys001", "certain": False}}
        report = s.build_report(sessions, matched, cmux_map={})
        self.assertEqual(report["rows"][0]["certain"], False)

    def test_missing_certain_key_defaults_to_true(self):
        zero = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
        sessions = {"a": self._session("/repo", zero, datetime(2026, 7, 28, 8, tzinfo=timezone.utc))}
        matched = {"a": {"pid": "1", "tty": "ttys001"}}  # no "certain" key at all
        report = s.build_report(sessions, matched, cmux_map={})
        self.assertTrue(report["rows"][0]["certain"])


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

    def test_row_missing_certain_key_has_no_tilde_prefix(self):
        report = {
            "rows": [{
                "session_id": "6fd0cd9d-4c9d-40bc-baa9-9ccad36956a6",
                "cwd": "/repo", "title": "My Session", "status": "running",
                "workspace": None,  # no "certain" key at all
                "tokens": {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0},
                "last_active": datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc),
            }],
            "totals": {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0},
            "session_count": 1, "running_count": 1,
        }
        table = s.format_report_table(report)
        self.assertIn("6fd0cd9d", table)
        self.assertNotIn("~6fd0cd9d", table)


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


if __name__ == "__main__":
    unittest.main()
