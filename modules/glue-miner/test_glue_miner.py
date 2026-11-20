"""Tests for the glue-miner scanner's grouping, retry detection, and redaction.

Run: python3 -m pytest test_glue_miner.py  (or: python3 test_glue_miner.py)

Grouping is what decides which tool candidates surface, so the fingerprint inputs
(command head, feeder, file family, op tags) are pinned here, plus one end-to-end
scan over a synthetic transcript. Nothing reads the real ~/.claude/projects.
"""

import importlib.util
import json
import pathlib
import tempfile

_spec = importlib.util.spec_from_file_location("glue_miner", pathlib.Path(__file__).with_name("glue_miner.py"))
gm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gm)


def bash(cid, command, description=""):
	return {"id": cid, "name": "Bash", "input": {"command": command, "description": description}}


def test_command_head_skips_cd_and_env_prefixes():
	assert gm.command_head("cd /x && gh pr view 12 --json title") == "gh pr"
	assert gm.command_head('export T=$(op read "op://a/b") && curl -s https://x') == "curl"
	assert gm.command_head("./bin/monorepo/gh-fetch-review-threads.sh 2392 --json") == "gh-fetch-review-threads.sh"
	assert gm.command_head("python3 -c 'print(1)'") == "python3"


def test_file_family_collapses_slugs_but_keeps_short_names():
	assert gm.file_family("conventions-judgment-jd-feat-N-campaign.json") == "conventions-judgment-*.json"
	assert gm.file_family("commentable-lines.json") == "commentable-lines.json"
	assert gm.file_family("$RUN_DIR") == ""


def test_redact_masks_tokens_and_keeps_prefix():
	out = gm.redact("curl -H 'Authorization: Bearer abcdefghijklmnopqrstuv' ghp_" + "a" * 30 + " token=supersecret123")
	assert "abcdefghijklmnop" not in out and "ghp_" not in out and "supersecret" not in out
	assert "Bearer [REDACTED]" in out and "token=[REDACTED]" in out


def test_inline_snippet_fingerprint_uses_feeder_and_ops():
	calls = [bash("1", "gtr list --json | python3 -c \"import json,sys;print(json.load(sys.stdin)[0]['note'])\"", "Read timer note")]
	[g] = gm.extract_glue(calls)
	assert g["kind"] == "inline-python"
	assert g["feeder"] == "gtr list"
	assert g["fingerprint"] == "inline-python · gtr list · json-read+stdin"


def test_scratch_script_counts_the_written_file():
	calls = [
		{"id": "w", "name": "Write", "input": {"file_path": "/tmp/s/post.py", "content": "import subprocess\nfor x in R:\n    subprocess.run(x)\n"}},
		bash("b", "python3 /tmp/s/post.py 2>&1"),
	]
	[g] = gm.extract_glue(calls)
	assert g["kind"] == "scratch-script" and g["lines"] == 4 and "subprocess" in g["ops"]


def test_short_jq_is_not_glue_but_long_jq_is():
	assert gm.extract_glue([bash("1", "gh pr view 1 --json title | jq '.title'")]) == []
	prog = ".[] | select(.type==\"review_thread\") | " + " | ".join(["{a: .x, b: .y}"] * 8)
	[g] = gm.extract_glue([bash("1", f"jq -r '{prog}' f.json")])
	assert g["kind"] == "long-jq"


def test_retry_detected_only_when_same_head_reruns():
	calls = [bash("1", "gh api repos/o/r/pulls --paginatex"), bash("2", "ls"), bash("3", "gh api repos/o/r/pulls --paginate")]
	results = {"1": {"is_error": True, "text": "Exit code 1\nunknown flag: --paginatex"}, "3": {"is_error": False, "text": "[]"}}
	[r] = gm.extract_retries(calls, results)
	assert r["head"] == "gh api" and r["signature"] == "unknown-flag"
	assert gm.extract_retries(calls[:2], results) == []


def test_blocking_hook_result_is_a_block_not_a_denial():
	calls = [bash("1", "gh pr create --title x")]
	results = {"1": {"is_error": True, "text": "PreToolUse:Bash hook error: [$CLAUDE_PROJECT_DIR/bin/require-skills.sh]: BLOCKED: use create-pr"}}
	[b] = gm.extract_blocks(calls, results, [])
	assert b["kind"] == "hook-block" and b["key"] == "PreToolUse:Bash require-skills.sh"


def test_project_of_folds_worktrees_and_scratchpads():
	home = gm.HOME_PROJECTS
	p = pathlib.Path("/x/-Users-me-projects-zzz-proj-sub/s.jsonl")
	assert gm.project_of({"cwd": f"{home}/lindris-monorepo-wt-eval643-abc/tmp"}, p) == "lindris-monorepo"
	assert gm.project_of({"cwd": "/private/tmp/claude-501/x/scratchpad"}, p) == "zzz"


def test_reviewed_group_resurfaces_only_after_doubling():
	per = {f"s{i}": {"project": "p", "glue": [{"fingerprint": "k", "lines": 3, "kind": "inline-python", "inputs": [], "desc": "", "cmd": "c"}], "retries": [], "blocks": []} for i in range(4)}
	ledger = {"glue:k": {"decision": "skip", "date": "2026-10-01", "sessions_at_review": 2}}
	assert gm.aggregate(per, ledger, 2)["glue"][0]["reviewed"]["grew"] is True
	ledger["glue:k"]["sessions_at_review"] = 3
	assert gm.aggregate(per, ledger, 2)["glue"][0]["reviewed"]["grew"] is False


def test_cursor_adapter_maps_shell_and_write_keys():
	with tempfile.TemporaryDirectory() as d:
		# path must contain .../projects/<flattened-cwd>/... so the project resolves
		p = pathlib.Path(d) / "projects" / "Users-me-projects-tray-x" / "agent-transcripts" / "s1" / "s1.jsonl"
		p.parent.mkdir(parents=True)
		lines = [
			{"role": "assistant", "message": {"content": [
				{"type": "tool_use", "name": "Shell", "input": {"command": "python3 -c 'import json;print(1)'", "description": "parse"}},
				{"type": "tool_use", "name": "Write", "input": {"path": "/tmp/s/go.py", "contents": "import os\nos.getcwd()\n"}},
				{"type": "tool_use", "name": "Bash", "input": {"command": "python3 /tmp/s/go.py"}},
				{"type": "tool_use", "name": "ApplyPatch", "input": "*** Begin Patch\n*** Update File: x\n"},  # raw-string input must not crash
			]}},
		]
		p.write_text("\n".join(json.dumps(x) for x in lines))
		calls, results, hooks, project = gm.scan_cursor_file(p)
		assert project == "tray" and results == {} and hooks == []
		glue = gm.extract_glue(calls)
		kinds = sorted(g["kind"] for g in glue)
		assert kinds == ["inline-python", "scratch-script"]  # Shell→Bash inline + Write(contents/path)→run


def test_codex_adapter_lifts_shell_from_js_exec():
	with tempfile.TemporaryDirectory() as d:
		p = pathlib.Path(d) / "rollout-x.jsonl"
		snippet = "gh pr view 1 | python3 -c \\\"import json,sys;print(json.load(sys.stdin))\\\""
		lines = [
			{"type": "session_meta", "payload": {"cwd": f"{gm.HOME_PROJECTS}/am-videos", "session_id": "sess-abc"}},
			{"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec", "call_id": "call_1",
				"input": "const r = await tools.exec_command({cmd:\"" + snippet + "\",max_output_tokens:2000}); text(r.output);"}},
			{"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "call_1",
				"output": [{"type": "input_text", "text": "Wall time 0.1s\nOutput:\n{}"}]}},
		]
		p.write_text("\n".join(json.dumps(x) for x in lines))
		calls, results, hooks, project, sid = gm.scan_codex_file(p)
		assert project == "am-videos" and sid == "sess-abc"
		[g] = gm.extract_glue(calls)
		assert g["kind"] == "inline-python" and g["feeder"] == "gh pr"
		assert "call_1#0" in results  # output attached for best-effort retry/denial detection


def test_aggregate_tags_group_with_every_source_it_recurs_in():
	g = lambda: [{"fingerprint": "k", "lines": 3, "kind": "inline-python", "inputs": [], "desc": "", "cmd": "c"}]
	per = {
		"claude:a": {"project": "p", "source": "claude", "glue": g(), "retries": [], "blocks": []},
		"cursor:b": {"project": "q", "source": "cursor", "glue": g(), "retries": [], "blocks": []},
	}
	row = gm.aggregate(per, {}, 2)["glue"][0]
	assert row["sources"] == ["claude", "cursor"] and gm.src_tag(row["sources"]) == "[Claude+Cursor]"


def test_end_to_end_scan_groups_across_sessions_and_hides_singletons():
	with tempfile.TemporaryDirectory() as d:
		root = pathlib.Path(d) / "-Users-me-projects-demo"
		root.mkdir()
		snippet = "gh pr view 1 --json title | python3 -c \"import json,sys;print(json.load(sys.stdin)['title'])\""
		for sid in ("a", "b"):
			lines = [
				{"type": "assistant", "cwd": "/Users/me/projects/demo", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": snippet, "description": "Read PR title"}}]}},
				{"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "x"}]}},
			]
			(root / f"{sid}.jsonl").write_text("\n".join(json.dumps(x) for x in lines))
		(root / "c.jsonl").write_text(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t", "name": "Bash", "input": {"command": "node -e 'console.log(1)'"}}]}}))
		per, files = gm.scan(pathlib.Path(d), days=1)
		agg = gm.aggregate(per, {}, 2)
		assert files == 3
		assert [g["key"] for g in agg["glue"]] == ["inline-python · gh pr · json-read+stdin"]
		assert agg["glue"][0]["sessions"] == 2 and agg["glue_singletons"] == 1
		assert "Read PR title" in gm.render_markdown(agg, {"week": "W", "generated": "g", "days": 1, "files": 3, "sessions": 3, "min_sessions": 2}, 5)


if __name__ == "__main__":
	import sys
	fails = 0
	for name, fn in list(globals().items()):
		if name.startswith("test_") and callable(fn):
			try:
				fn()
				print(f"ok   {name}")
			except Exception as e:  # noqa: BLE001
				fails += 1
				print(f"FAIL {name}: {e!r}")
	sys.exit(1 if fails else 0)
