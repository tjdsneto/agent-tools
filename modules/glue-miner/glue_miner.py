#!/usr/bin/env python3
"""Mine AI coding-agent transcripts for recurring glue code and tool friction.

Scans three sources and reports three things, ranked by how many sessions and
projects they recur in:

  - claude  ~/.claude/projects/**/*.jsonl              (calls + results + hooks)
  - cursor  ~/.cursor/projects/**/agent-transcripts/**/*.jsonl  (calls only)
  - codex   ~/.codex/sessions/**/rollout-*.jsonl        (JS-wrapped shell calls)

Each source is read by its own adapter into one normalized shape
(calls, results, hook_errors, project, session_id); everything downstream —
extraction, grouping, ranking, rendering — is source-agnostic. Identical
patterns seen under more than one tool merge into one group tagged with the
tools it came from. Caveats baked into the data, not the code:

  - Cursor records no tool outputs, so its calls feed section 1 (glue) only;
    retries and denials/hooks need results it does not keep.
  - Codex wraps every shell command inside a JS `exec` tool and its outputs
    carry no clean error flag, so its shell extraction and retry detection are
    best-effort, and writing JS to run shell is its normal path, not a smell.

The three reported sections:

1. Glue: inline interpreter snippets (python3 -c, python3 - <<EOF, node -e, ...),
   scratch scripts written and then run, and long jq/awk programs. Each recurring
   group is a candidate for a real tool, a better flag on an existing tool, or a
   fixed instruction.
2. Retries: a Bash command that failed and was re-run with the same command head
   within the next few calls — a sign of a missing flag, a bad --help, or unclear
   usage.
3. Blocks: tool calls the user denied and hook errors, grouped by tool/hook.

The scan is deterministic counting only. Deciding what a group means and what to
build is the glue-miner skill's review step.

Usage:
  glue_miner.py [--days 7] [--top 25] [--min-sessions 2] [--out PATH] [--json]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import pathlib
import re
import shlex
import sys
from collections import defaultdict

PROJECTS_DIR = pathlib.Path.home() / ".claude" / "projects"
CURSOR_PROJECTS_DIR = pathlib.Path.home() / ".cursor" / "projects"
CODEX_SESSIONS_DIR = pathlib.Path.home() / ".codex" / "sessions"
ALL_SOURCES = ("claude", "cursor", "codex")
SKILL_DIR = pathlib.Path(__file__).resolve().parent
REPORTS_DIR = SKILL_DIR / "reports"
LEDGER = REPORTS_DIR / "reviewed.json"

INTERPRETER_RE = re.compile(
	r"(?:^|[\s|;&(`$])(python3?|node|ruby|perl|php)(?:\s+-[A-Za-z]*)*\s+(-c|-e|-r|-)(?=\s|$|['\"])"
)
SCRIPT_RUN_RE = re.compile(r"(?:^|[\s|;&(])(?:python3?|node|ruby|perl|php|bash|sh)\s+(\S+\.(?:py|js|mjs|rb|pl|php|sh))\b")
LONG_PROGRAM_RE = re.compile(r"(?:^|[\s|;&(])(jq|awk)\s+(?:-[A-Za-z]+\s+)*('([^']*)')")
LONG_PROGRAM_MIN = 120
RETRY_WINDOW = 3
# Shell builtins and plain readers: a failed retry of these says nothing about tooling.
NOISE_HEADS = {"cd", "echo", "cat", "ls", "grep", "rg", "test", "[", "for", "while", "if", "export", "set", "sleep", "true", "false", "head", "tail", "wc", "printf", "{", "("}

# (pattern, keep group 1 as a visible prefix)
SECRET_PATTERNS = [
	(re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), False),
	(re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), False),
	(re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}"), False),
	(re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{16,}"), True),
	(re.compile(r"(?i)((?:password|passwd|token|secret|api[_-]?key)\s*[=:]\s*)['\"]?[^\s'\"$]{8,}"), True),
	(re.compile(r"\b[A-Fa-f0-9]{40,}\b"), False),
]

OP_TAGS = [
	("json-read", re.compile(r"json\.loads?\(|JSON\.parse|JSONDecoder")),
	("json-write", re.compile(r"json\.dumps?\(|JSON\.stringify")),
	("regex", re.compile(r"\bre\.(?:sub|match|search|findall|finditer|split|compile)\(")),
	("text-replace", re.compile(r"\.replace\(")),
	("file-write", re.compile(r"open\([^)]*['\"][wa]['\"]|write_text\(|writeFileSync")),
	("file-read", re.compile(r"open\(|read_text\(|readFileSync")),
	("subprocess", re.compile(r"subprocess\.|os\.system\(|execSync|child_process")),
	("http", re.compile(r"urllib|requests\.|http\.client|fetch\(")),
	("csv", re.compile(r"\bcsv\.")),
	("dates", re.compile(r"datetime|strptime|strftime")),
	("aggregate", re.compile(r"Counter\(|setdefault\(|defaultdict\(|sorted\(|len\(")),
	("stdin", re.compile(r"sys\.stdin|process\.stdin")),
]

FAILURE_SIGNATURES = [
	("unknown-flag", re.compile(r"(?i)unknown (?:flag|option|shorthand flag)|unrecognized (?:option|arguments)|invalid option|illegal option")),
	("not-found", re.compile(r"(?i)command not found|No such file or directory|not recognized as")),
	("usage", re.compile(r"(?i)^usage:|\nusage:")),
	("python-traceback", re.compile(r"Traceback \(most recent call last\)")),
	("json-error", re.compile(r"(?i)jq: error|JSONDecodeError|Expecting value|parse error")),
	("auth", re.compile(r"(?i)\b401\b|unauthori[sz]ed|authentication|permission denied")),
	("graphql", re.compile(r"(?i)graphql|Variable \$\w+ of type")),
]

DENIAL_RE = re.compile(r"(?i)doesn't want to proceed|user (?:rejected|denied)|permission to use \w+ (?:was|has been) denied")
# A blocking hook's message replaces the tool result: "PreToolUse:Bash hook error: [<script>]: <msg>"
BLOCKING_HOOK_RE = re.compile(r"^(\w+:\w+|\w+) hook error: \[([^\]]+)\]:?\s*(.{0,120})", re.S)


# ── helpers ──────────────────────────────────────────────────────────────────

def redact(text: str) -> str:
	for pat, keep_prefix in SECRET_PATTERNS:
		text = pat.sub((lambda m: m.group(1) + "[REDACTED]") if keep_prefix else "[REDACTED]", text)
	return text


def normalize_token(tok: str) -> str:
	"""Collapse the variable parts of a command word so equal jobs group together."""
	tok = tok.strip("'\"")
	if "/" in tok:
		tok = tok.rstrip("/").split("/")[-1] or tok
	return tok


def command_head(cmd: str, words: int = 2) -> str:
	"""First program (plus subcommand) of the first real segment, e.g. 'gh pr', 'gtr list'."""
	cmd = re.sub(r"^\s*(?:cd\s+\S+\s*(?:&&|;)\s*|(?:export\s+)?[A-Za-z_][A-Za-z0-9_]*=(?:\$\([^)]*\)|\S)*\s*(?:&&|;)?\s*)+", "", cmd.strip())
	first = re.split(r"\s*(?:\|\||&&|;|\||\n)\s*", cmd, maxsplit=1)[0]
	try:
		parts = shlex.split(first, posix=True)
	except ValueError:
		parts = first.split()
	parts = [p for p in parts if p and p != "\\"]
	if not parts:
		return ""
	head = [normalize_token(parts[0])]
	for p in parts[1:]:
		if len(head) >= words or p.startswith("-") or "=" in p:
			break
		if re.match(r"^[a-z][a-z0-9:_-]*$", p):
			head.append(p)
		else:
			break
	return " ".join(head)


def feeder_of(cmd: str, match_start: int) -> str:
	"""The command whose output is piped into the snippet, or 'files' when it reads none."""
	before = cmd[:match_start]
	if "|" in before:
		seg = before.rsplit("|", 1)[0]
		seg = re.split(r"\s*(?:&&|;|\n|\$\()\s*", seg)[-1]
		return command_head(seg) or "pipe"
	return "-"


def op_tags(body: str) -> list[str]:
	tags = [name for name, pat in OP_TAGS if pat.search(body)]
	if "file-write" in tags and "file-read" in tags:
		tags.remove("file-read")
	return tags


def input_files(body: str) -> list[str]:
	found = re.findall(r"open\(\s*f?['\"]([^'\"]+)['\"]", body)
	return sorted({re.sub(r"\d+", "N", pathlib.Path(p).name) for p in found})


def file_family(name: str) -> str:
	"""conventions-judgment-jd-feat-N-x.json → conventions-judgment-*.json; holes.json stays."""
	if name.startswith("$") or "{" in name:
		return ""
	stem, dot, ext = name.partition(".")
	words = stem.split("-")
	fam = "-".join(words[:2]) + ("-*" if len(words) > 2 else "")
	return fam + (dot + ext if dot else "")


def failure_signature(text: str) -> str:
	for name, pat in FAILURE_SIGNATURES:
		if pat.search(text):
			return name
	return "exit-nonzero"


def result_text(content) -> str:
	if isinstance(content, str):
		return content
	if isinstance(content, list):
		return "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
	return ""


def is_failure(res: dict) -> bool:
	if res.get("is_error"):
		return True
	m = re.match(r"Exit code (\d+)", res.get("text", ""))
	return bool(m and m.group(1) != "0")


# ── transcript parsing ───────────────────────────────────────────────────────

def session_key(path: pathlib.Path) -> str:
	"""Subagent transcripts count toward their parent session."""
	if path.parent.name == "subagents":
		return path.parent.parent.name
	return path.stem


def iter_events(path: pathlib.Path):
	"""Yield ('call', tool_use) and ('result', tool_result) plus the session cwd."""
	with path.open(encoding="utf-8", errors="replace") as fh:
		for line in fh:
			if '"tool_use"' not in line and '"tool_result"' not in line and "hook_non_blocking_error" not in line:
				continue
			try:
				entry = json.loads(line)
			except json.JSONDecodeError:
				continue
			yield entry


HOME_PROJECTS = pathlib.Path.home() / "projects"
_PROJECT_NAMES: list[str] | None = None


def _project_names() -> list[str]:
	global _PROJECT_NAMES
	if _PROJECT_NAMES is None:
		try:
			_PROJECT_NAMES = sorted((p.name for p in HOME_PROJECTS.iterdir() if p.is_dir()), key=len, reverse=True)
		except OSError:
			_PROJECT_NAMES = []
	return _PROJECT_NAMES


def strip_worktree(name: str) -> str:
	"""lindris-monorepo-wt-eval643-575a48ea9 → lindris-monorepo."""
	return re.split(r"-wt-|-worktree", name, maxsplit=1)[0]


def project_from_cwd(cwd: str) -> str:
	"""The ~/projects/<name> a cwd sits in, worktrees folded into their repo, else ''."""
	parts = pathlib.Path(cwd or "").parts
	if cwd and cwd.startswith(str(HOME_PROJECTS) + "/") and len(parts) > len(HOME_PROJECTS.parts):
		return strip_worktree(parts[len(HOME_PROJECTS.parts)])
	return ""


def project_from_marker(folder: str, marker: str = "-projects-") -> str:
	"""Resolve a flattened launch-cwd folder ('…-projects-lindris-monorepo-local-…') to a repo.

	Cursor flattens with a leading segment ('Users-me-projects-<repo>-…'), so the marker is
	given with or without its leading dash depending on the source.
	"""
	if marker not in folder:
		return folder.lstrip("-") or "?"
	rest = folder.split(marker, 1)[1]
	for name in _project_names():
		if rest == name or rest.startswith(name + "-"):
			return strip_worktree(name)
	return strip_worktree(rest.split("-", 1)[0])


def project_of(entry: dict, path: pathlib.Path) -> str:
	"""Project = the ~/projects/<name> the session ran in, worktrees folded into their repo.

	The transcript's folder encodes the launch cwd ('-Users-me-projects-lindris-monorepo-local-…');
	that is used when the recorded cwd is outside ~/projects (scratchpads, /tmp clones).
	"""
	from_cwd = project_from_cwd(entry.get("cwd") or "")
	if from_cwd:
		return from_cwd
	folder = path.parent.parent.name if path.parent.name == "subagents" else path.parent.name
	return project_from_marker(folder)


def scan_file(path: pathlib.Path):
	"""Return (calls, results, hook_errors, project) for one transcript."""
	calls = []  # ordered tool_use dicts
	results = {}
	hook_errors = []
	project = None
	for entry in iter_events(path):
		if project is None and entry.get("cwd"):
			project = project_of(entry, path)
		msg = entry.get("message") or {}
		content = msg.get("content")
		if isinstance(content, list):
			for c in content:
				if not isinstance(c, dict):
					continue
				if c.get("type") == "tool_use":
					calls.append({"id": c.get("id"), "name": c.get("name"), "input": c.get("input") or {}})
				elif c.get("type") == "tool_result":
					results[c.get("tool_use_id")] = {"is_error": bool(c.get("is_error")), "text": result_text(c.get("content"))[:2000]}
		att = entry.get("attachment") or {}
		if att.get("type") == "hook_non_blocking_error":
			stderr = (att.get("stderr") or "").replace("Failed with non-blocking status code: ", "")
			hook_errors.append((att.get("hookName") or att.get("hookEvent") or "?", stderr.strip()[:160]))
	return calls, results, hook_errors, project or project_of({}, path)


# ── cursor adapter ───────────────────────────────────────────────────────────
# Cursor: ~/.cursor/projects/<flattened-cwd>/agent-transcripts/<id>/<id>.jsonl.
# Role-tagged lines whose message.content holds Anthropic-style tool_use blocks —
# but with no tool_result blocks and no call ids, so calls only (glue section).

CURSOR_TOOL_MAP = {"Shell": "Bash"}  # Cursor's shell tool; input is command+description like Bash


def cursor_project(path: pathlib.Path) -> str:
	parts = path.parts
	if "projects" in parts:
		i = parts.index("projects")
		if i + 1 < len(parts):
			return project_from_marker(parts[i + 1], marker="projects-")
	return "?"


def _cursor_call(block: dict, idx: int) -> dict:
	name = block.get("name", "")
	raw = block.get("input")
	inp = dict(raw) if isinstance(raw, dict) else {}  # some tools (ApplyPatch) carry a raw string
	if name == "Write":  # Cursor uses contents/path where Claude uses content/file_path
		if "contents" in inp and "content" not in inp:
			inp["content"] = inp.pop("contents")
		if "path" in inp and "file_path" not in inp:
			inp["file_path"] = inp.get("path")
	return {"id": f"c{idx}", "name": CURSOR_TOOL_MAP.get(name, name), "input": inp}


def scan_cursor_file(path: pathlib.Path):
	calls, idx = [], 0
	with path.open(encoding="utf-8", errors="replace") as fh:
		for line in fh:
			if '"tool_use"' not in line:
				continue
			try:
				entry = json.loads(line)
			except json.JSONDecodeError:
				continue
			content = (entry.get("message") or {}).get("content")
			if not isinstance(content, list):
				continue
			for b in content:
				if isinstance(b, dict) and b.get("type") == "tool_use":
					calls.append(_cursor_call(b, idx))
					idx += 1
	return calls, {}, [], cursor_project(path)


# ── codex adapter ────────────────────────────────────────────────────────────
# Codex: ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl. Shell runs inside a JS
# `exec` tool as tools.exec_command({cmd:"…"}); we lift the cmd strings out of
# the JS. Outputs exist but carry no error flag, so results are best-effort.

CMD_IN_OBJ_RE = re.compile(r"""cmd\s*:\s*("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`)""")
CMD_STR_RE = re.compile(r"""exec_command\(\s*("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')""")


def _js_unescape(s: str) -> str:
	return (s.replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "")
	        .replace('\\"', '"').replace("\\'", "'").replace("\\/", "/").replace("\\\\", "\\"))


def extract_codex_cmds(js: str) -> list[str]:
	"""Shell commands lifted from a Codex `exec` JS body, in order, de-duplicated."""
	raw = [m.group(1)[1:-1] for m in CMD_IN_OBJ_RE.finditer(js or "")]
	raw += [m.group(1)[1:-1] for m in CMD_STR_RE.finditer(js or "")]
	seen, out = set(), []
	for c in map(_js_unescape, raw):
		if c and c not in seen:
			seen.add(c)
			out.append(c)
	return out


def _codex_output_text(output) -> str:
	if isinstance(output, str):
		return output
	if isinstance(output, list):
		return "\n".join(c.get("text", "") for c in output if isinstance(c, dict))
	return ""


def scan_codex_file(path: pathlib.Path):
	calls, results, project, sid = [], {}, "", path.stem
	with path.open(encoding="utf-8", errors="replace") as fh:
		for line in fh:
			if '"type"' not in line:
				continue
			try:
				entry = json.loads(line)
			except json.JSONDecodeError:
				continue
			t, p = entry.get("type"), entry.get("payload") or {}
			if t == "session_meta":
				project = project or project_from_cwd(p.get("cwd") or "")
				sid = p.get("session_id") or sid
			elif t == "turn_context" and not project:
				project = project_from_cwd(p.get("cwd") or "")
			elif t == "response_item":
				pt = p.get("type")
				if pt in ("custom_tool_call", "function_call"):
					body = p.get("input") if isinstance(p.get("input"), str) else (p.get("arguments") or "")
					cid = p.get("call_id") or p.get("id") or f"x{len(calls)}"
					for j, cmd in enumerate(extract_codex_cmds(body)):
						calls.append({"id": f"{cid}#{j}", "name": "Bash", "input": {"command": cmd, "description": ""}})
				elif pt in ("custom_tool_call_output", "function_call_output"):
					cid = p.get("call_id")
					if cid:
						results[f"{cid}#0"] = {"is_error": False, "text": _codex_output_text(p.get("output"))[:2000]}
	return calls, results, [], project or "?", sid


# ── extraction ───────────────────────────────────────────────────────────────

def extract_glue(calls: list[dict]) -> list[dict]:
	"""Find glue snippets in one session's calls."""
	written = {}
	for c in calls:
		if c["name"] == "Write":
			fp = c["input"].get("file_path", "")
			if re.search(r"\.(py|js|mjs|rb|pl|php|sh)$", fp):
				written[fp] = c["input"].get("content", "")
	out = []
	for c in calls:
		if c["name"] != "Bash":
			continue
		cmd = c["input"].get("command", "") or ""
		desc = c["input"].get("description", "") or ""
		m = INTERPRETER_RE.search(cmd)
		if m:
			lang = "python" if m.group(1).startswith("python") else m.group(1)
			body = cmd[m.start():]
			out.append({"kind": f"inline-{lang}", "feeder": feeder_of(cmd, m.start()), "body": body, "cmd": cmd, "desc": desc})
			continue
		m = SCRIPT_RUN_RE.search(cmd)
		if m and m.group(1) in written:
			body = written[m.group(1)]
			out.append({"kind": "scratch-script", "feeder": feeder_of(cmd, m.start()), "body": body, "cmd": cmd, "desc": desc})
			continue
		for pm in LONG_PROGRAM_RE.finditer(cmd):
			prog = pm.group(3) or ""
			if len(prog) >= LONG_PROGRAM_MIN:
				out.append({"kind": f"long-{pm.group(1)}", "feeder": feeder_of(cmd, pm.start()), "body": prog, "cmd": cmd, "desc": desc})
				break
	for g in out:
		g["ops"] = op_tags(g["body"])
		g["inputs"] = input_files(g["body"])
		g["lines"] = max(1, g["body"].count("\n") + 1)
		fams = sorted({f for f in map(file_family, g["inputs"]) if f})[:2]
		parts = [g["kind"], g["feeder"]]
		if fams:
			parts.append("files:" + ",".join(fams))
		parts.append("+".join(o for o in g["ops"] if o != "file-read") or "plain")
		g["fingerprint"] = " · ".join(parts)
	return out


def extract_retries(calls: list[dict], results: dict) -> list[dict]:
	bash = [c for c in calls if c["name"] == "Bash"]
	out = []
	for i, c in enumerate(bash):
		res = results.get(c["id"])
		if not res or not is_failure(res):
			continue
		cmd = c["input"].get("command", "") or ""
		head = command_head(cmd)
		if not head or head.split()[0] in NOISE_HEADS:
			continue
		for nxt in bash[i + 1 : i + 1 + RETRY_WINDOW]:
			if command_head(nxt["input"].get("command", "") or "") == head:
				text = res["text"]
				first = next((ln for ln in text.splitlines()[1:] if ln.strip()), text.splitlines()[0] if text else "")
				out.append({
					"head": head,
					"signature": failure_signature(text),
					"help": bool(re.search(r"(?:^|\s)(--help|-h)(?:\s|$)", cmd)),
					"error": first.strip()[:160],
					"cmd": cmd,
				})
				break
	return out


def extract_blocks(calls: list[dict], results: dict, hook_errors: list) -> list[dict]:
	out = []
	for c in calls:
		res = results.get(c["id"])
		if not res:
			continue
		target = command_head(c["input"].get("command", "")) if c["name"] == "Bash" else ""
		hm = BLOCKING_HOOK_RE.match(res["text"])
		if hm:
			script = pathlib.Path(hm.group(2).split()[0]).name
			out.append({"kind": "hook-block", "key": f"{hm.group(1)} {script}", "detail": f"{target}: {hm.group(3)}".strip(": ")})
		elif DENIAL_RE.search(res["text"]):
			out.append({"kind": "denied", "key": f"{c['name']} {target}".strip(), "detail": res["text"][:160]})
	for hook, detail in hook_errors:
		key = re.sub(r"\d+", "N", re.split(r"[:\n]", detail, maxsplit=1)[0])[:70]
		out.append({"kind": "hook-error", "key": f"{hook} — {key}", "detail": detail})
	return out


# ── aggregation ──────────────────────────────────────────────────────────────

def load_ledger() -> dict:
	try:
		return json.loads(LEDGER.read_text())
	except (OSError, json.JSONDecodeError):
		return {}


def score(sessions: int, projects: int, avg_lines: float) -> float:
	return round(sessions * projects * math.sqrt(max(avg_lines, 1)), 1)


def aggregate(per_session: dict, ledger: dict, min_sessions: int) -> dict:
	glue = defaultdict(lambda: {"sessions": set(), "projects": set(), "sources": set(), "count": 0, "lines": 0, "descs": [], "examples": [], "kinds": set(), "inputs": set()})
	retries = defaultdict(lambda: {"sessions": set(), "projects": set(), "sources": set(), "count": 0, "signatures": defaultdict(int), "help": 0, "errors": [], "examples": []})
	blocks = defaultdict(lambda: {"sessions": set(), "projects": set(), "sources": set(), "count": 0, "kind": "", "details": []})

	for sid, data in per_session.items():
		proj = data["project"]
		src = data.get("source", "claude")
		for g in data["glue"]:
			a = glue[g["fingerprint"]]
			a["sessions"].add(sid); a["projects"].add(proj); a["sources"].add(src); a["count"] += 1; a["lines"] += g["lines"]
			a["kinds"].add(g["kind"]); a["inputs"].update(g["inputs"])
			if g["desc"] and g["desc"] not in a["descs"]:
				a["descs"].append(g["desc"])
			a["examples"].append((g["lines"], sid, g["cmd"]))
		for r in data["retries"]:
			a = retries[r["head"]]
			a["sessions"].add(sid); a["projects"].add(proj); a["sources"].add(src); a["count"] += 1
			a["signatures"][r["signature"]] += 1; a["help"] += int(r["help"])
			if r["error"] and r["error"] not in a["errors"]:
				a["errors"].append(r["error"])
			a["examples"].append((len(r["cmd"]), sid, r["cmd"]))
		for b in data["blocks"]:
			a = blocks[b["key"]]
			a["sessions"].add(sid); a["projects"].add(proj); a["sources"].add(src); a["count"] += 1; a["kind"] = b["kind"]
			if b["detail"] not in a["details"]:
				a["details"].append(b["detail"])

	def finish(groups, kind):
		rows, singles = [], 0
		for key, a in groups.items():
			n_s, n_p = len(a["sessions"]), len(a["projects"])
			if n_s < min_sessions:
				singles += 1
				continue
			avg = a["lines"] / a["count"] if kind == "glue" else 1
			row = {
				"key": key,
				"score": score(n_s, n_p, avg),
				"sessions": n_s,
				"projects": sorted(a["projects"]),
				"sources": sorted(a["sources"]),
				"count": a["count"],
				"session_ids": sorted(a["sessions"])[:6],
			}
			reviewed = ledger.get(f"{kind}:{key}")
			if reviewed:
				grew = n_s >= 2 * int(reviewed.get("sessions_at_review", 0) or 1)
				row["reviewed"] = {**reviewed, "grew": grew}
			if kind == "glue":
				row.update({
					"avg_lines": round(avg, 1),
					"kinds": sorted(a["kinds"]),
					"inputs": sorted(a["inputs"])[:8],
					"descriptions": a["descs"][:8],
					"example": redact(sorted(a["examples"], key=lambda e: abs(e[0] - avg))[0][2])[:1500],
				})
			elif kind == "retry":
				row.update({
					"signatures": dict(a["signatures"]),
					"help_failures": a["help"],
					"errors": [redact(e) for e in a["errors"][:5]],
					"example": redact(sorted(a["examples"])[0][2])[:600],
				})
			else:
				row.update({"kind": a["kind"], "details": [redact(d) for d in a["details"][:3]]})
			rows.append(row)
		rows.sort(key=lambda r: (-r["score"], -r["count"]))
		return rows, singles

	glue_rows, glue_singles = finish(glue, "glue")
	retry_rows, retry_singles = finish(retries, "retry")
	block_rows, _ = finish(blocks, "block")
	return {"glue": glue_rows, "glue_singletons": glue_singles, "retries": retry_rows, "retry_singletons": retry_singles, "blocks": block_rows}


def scan(projects_dir: pathlib.Path, days: int, exclude_session: str | None = None) -> tuple[dict, int]:
	cutoff = dt.datetime.now().timestamp() - days * 86400
	per_session: dict = {}
	files = 0
	for path in projects_dir.rglob("*.jsonl"):
		try:
			if path.stat().st_mtime < cutoff:
				continue
		except OSError:
			continue
		sid = session_key(path)
		if exclude_session and sid == exclude_session:
			continue
		files += 1
		calls, results, hook_errors, project = scan_file(path)
		data = per_session.setdefault(sid, {"project": project, "source": "claude", "glue": [], "retries": [], "blocks": []})
		data["glue"] += extract_glue(calls)
		data["retries"] += extract_retries(calls, results)
		data["blocks"] += extract_blocks(calls, results, hook_errors)
	return per_session, files


# Per-source file enumeration + adapter. Each adapter returns the normalized
# (calls, results, hook_errors, project[, session_id]); downstream is identical.
SOURCE_SPECS = {
	"cursor": (CURSOR_PROJECTS_DIR, "**/agent-transcripts/**/*.jsonl", scan_cursor_file),
	"codex": (CODEX_SESSIONS_DIR, "**/rollout-*.jsonl", scan_codex_file),
}


def scan_source(source: str, days: int) -> tuple[dict, int]:
	"""Scan cursor/codex into the same per_session shape scan() builds for claude."""
	root, pattern, adapter = SOURCE_SPECS[source]
	cutoff = dt.datetime.now().timestamp() - days * 86400
	per_session: dict = {}
	files = 0
	if not root.exists():
		return per_session, files
	for path in root.glob(pattern):
		try:
			if path.stat().st_mtime < cutoff:
				continue
		except OSError:
			continue
		out = adapter(path)
		calls, results, hook_errors, project = out[:4]
		sid = out[4] if len(out) > 4 else path.stem
		files += 1
		key = f"{source}:{sid}"
		data = per_session.setdefault(key, {"project": project, "source": source, "glue": [], "retries": [], "blocks": []})
		data["glue"] += extract_glue(calls)
		data["retries"] += extract_retries(calls, results)
		data["blocks"] += extract_blocks(calls, results, hook_errors)
	return per_session, files


def scan_all(sources, days: int, exclude_session: str | None = None, claude_dir: pathlib.Path = PROJECTS_DIR):
	"""Merge every enabled source into one per_session map, keyed <source>:<sid>."""
	per_session: dict = {}
	by_source: dict = {}
	for source in sources:
		if source == "claude":
			ps, n = scan(claude_dir, days, exclude_session)
			ps = {f"claude:{k}": v for k, v in ps.items()}
		else:
			ps, n = scan_source(source, days)
		per_session.update(ps)
		by_source[source] = n
	return per_session, by_source


# ── rendering ────────────────────────────────────────────────────────────────

def fence(text: str) -> str:
	ticks = "````" if "```" in text else "```"
	return f"{ticks}bash\n{text}\n{ticks}"


def src_tag(sources: list[str]) -> str:
	return "[" + "+".join(s[0].upper() + s[1:] for s in sources) + "]" if sources else ""


def render_markdown(agg: dict, meta: dict, top: int) -> str:
	L = [f"# Glue-miner report — {meta['week']}", ""]
	by_src = meta.get("by_source") or {}
	src_line = ", ".join(f"{s} {n}" for s, n in by_src.items()) if by_src else ""
	L.append(f"Window: last {meta['days']} days (to {meta['generated']}). Transcripts scanned: {meta['files']}" + (f" ({src_line})" if src_line else "") + f" across {meta['sessions']} sessions. Groups shown recur in ≥{meta['min_sessions']} sessions; score = sessions × projects × √avg-lines.")
	L.append("")
	L.append("Source tag on each group — `[Claude]`, `[Cursor]`, `[Codex]`, or a combination — says which tools the pattern recurs under. Cursor transcripts record no tool outputs, so Cursor appears in section 1 only; Codex shell is lifted from its JS `exec` wrapper, so its retries are best-effort.")
	L.append("")
	L.append("Headings and key columns are ledger keys: `glue_miner.py --mark '<key>' --decision '…' --sessions N` hides a group until its session count doubles.")
	L.append("")
	L.append("Next step: run the `glue-miner` skill's **review** mode — it reads this report, checks `tool-registry` for tools that already exist, and sorts each group into new tool / improve existing tool / fix instruction.")
	L.append("")

	L.append(f"## 1. Recurring glue ({len(agg['glue'])} groups; {agg['glue_singletons']} one-session groups hidden)")
	L.append("")
	for i, r in enumerate(agg["glue"][:top], 1):
		flag = ""
		if r.get("reviewed"):
			rv = r["reviewed"]
			flag = f" — reviewed {rv.get('date','?')}: {rv.get('decision','?')}" + (" (**grew since**)" if rv.get("grew") else "")
		L.append(f"### G{i}. {src_tag(r.get('sources', []))} `glue:{r['key']}` — score {r['score']}{flag}")
		L.append(f"- {r['sessions']} sessions, {len(r['projects'])} projects ({', '.join(r['projects'][:5])}), {r['count']} snippets, avg {r['avg_lines']} lines")
		if r["inputs"]:
			L.append(f"- Files read: {', '.join(r['inputs'])}")
		if r["descriptions"]:
			L.append("- What the agent said it was doing: " + "; ".join(f"“{d}”" for d in r["descriptions"][:6]))
		L.append(f"- Sessions: {', '.join(r['session_ids'])}")
		L.append("")
		L.append("<details><summary>Representative snippet</summary>")
		L.append("")
		L.append(fence(r["example"]))
		L.append("")
		L.append("</details>")
		L.append("")

	L.append(f"## 2. Failed, then retried ({len(agg['retries'])} command heads; {agg['retry_singletons']} one-session heads hidden)")
	L.append("")
	if agg["retries"]:
		L.append("| # | Source | Command head | Sessions | Projects | Retries | Failure kinds | --help failures | Sample error |")
		L.append("|---|---|---|---|---|---|---|---|---|")
		for i, r in enumerate(agg["retries"][:top], 1):
			sig = ", ".join(f"{k} {v}" for k, v in sorted(r["signatures"].items(), key=lambda kv: -kv[1]))
			err = (r["errors"][0] if r["errors"] else "").replace("|", "\\|").replace("`", "'")
			L.append(f"| R{i} | {src_tag(r.get('sources', []))} | `retry:{r['key']}` | {r['sessions']} | {len(r['projects'])} | {r['count']} | {sig} | {r['help_failures']} | {err[:110]} |")
	else:
		L.append("None recurring.")
	L.append("")

	L.append(f"## 3. Denials and hook errors ({len(agg['blocks'])} groups)")
	L.append("")
	L.append("Approved permission prompts are not recorded in transcripts (and bypass mode skips them), so this section sees only denials and hook errors.")
	L.append("")
	if agg["blocks"]:
		L.append("| # | Source | Kind | Key | Sessions | Count | Sample |")
		L.append("|---|---|---|---|---|---|---|")
		for i, r in enumerate(agg["blocks"][:top], 1):
			d = (r["details"][0] if r["details"] else "").replace("|", "\\|").replace("`", "'").replace("\n", " ")
			L.append(f"| B{i} | {src_tag(r.get('sources', []))} | {r['kind']} | `block:{r['key'].replace('|', '/')}` | {r['sessions']} | {r['count']} | {d[:110]} |")
	else:
		L.append("None recurring.")
	L.append("")
	return "\n".join(L)


def main(argv=None) -> int:
	ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
	ap.add_argument("--days", type=int, default=7, help="scan transcripts modified in the last N days (default 7)")
	ap.add_argument("--top", type=int, default=25, help="rows per section (default 25)")
	ap.add_argument("--min-sessions", type=int, default=2, help="hide groups seen in fewer sessions (default 2)")
	ap.add_argument("--projects-dir", type=pathlib.Path, default=PROJECTS_DIR, help="Claude transcript root (default ~/.claude/projects)")
	ap.add_argument("--source", help=f"comma list of sources to scan (default all: {','.join(ALL_SOURCES)})")
	ap.add_argument("--out", type=pathlib.Path, help="write the Markdown report here (default: reports/<ISO-week>.md)")
	ap.add_argument("--stdout", action="store_true", help="print the report instead of writing a file")
	ap.add_argument("--json", action="store_true", help="print the aggregated groups as JSON")
	ap.add_argument("--exclude-session", help="skip this session id (e.g. the one running the scan)")
	ap.add_argument("--mark", metavar="LEDGER_KEY", help="record a review decision for a group (key as printed in the report, e.g. 'glue:inline-python · gtr list · json-read+stdin') and exit")
	ap.add_argument("--decision", help="with --mark: what was decided, e.g. 'fixed instruction: CLAUDE.md --append-note' or 'skip: one-off'")
	ap.add_argument("--sessions", type=int, default=0, help="with --mark: the group's session count at review time; the group resurfaces once it doubles")
	args = ap.parse_args(argv)

	if args.mark:
		if not args.decision:
			ap.error("--mark needs --decision")
		ledger = load_ledger()
		ledger[args.mark] = {"decision": args.decision, "date": dt.date.today().isoformat(), "sessions_at_review": args.sessions}
		LEDGER.parent.mkdir(parents=True, exist_ok=True)
		LEDGER.write_text(json.dumps(ledger, indent=1, ensure_ascii=False) + "\n")
		print(f"marked {args.mark}")
		return 0

	sources = [s.strip() for s in args.source.split(",") if s.strip()] if args.source else list(ALL_SOURCES)
	unknown = [s for s in sources if s not in ALL_SOURCES]
	if unknown:
		ap.error(f"unknown source(s): {', '.join(unknown)} (choose from {', '.join(ALL_SOURCES)})")
	per_session, by_source = scan_all(sources, args.days, args.exclude_session, args.projects_dir)
	files = sum(by_source.values())
	agg = aggregate(per_session, load_ledger(), args.min_sessions)
	now = dt.datetime.now()
	meta = {
		"week": now.strftime("%G-W%V"),
		"generated": now.strftime("%Y-%m-%d %H:%M"),
		"days": args.days,
		"files": files,
		"by_source": by_source,
		"sessions": len(per_session),
		"min_sessions": args.min_sessions,
	}
	if args.json:
		json.dump({"meta": meta, **agg}, sys.stdout, indent=1, default=list)
		print()
		return 0
	md = render_markdown(agg, meta, args.top)
	if args.stdout:
		print(md)
		return 0
	out = args.out or REPORTS_DIR / f"{meta['week']}.md"
	out.parent.mkdir(parents=True, exist_ok=True)
	out.write_text(md)
	print(out)
	return 0


if __name__ == "__main__":
	sys.exit(main())
