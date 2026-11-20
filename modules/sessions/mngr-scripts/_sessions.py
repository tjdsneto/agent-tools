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


def _extract_user_text(obj):
    content = (obj.get("message") or {}).get("content", [])
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


# Scans the full command line unanchored — a delegated task's prompt text containing a
# literal "--session-id <uuid>"/"--resume <uuid>" substring could in theory be misread as
# the flag. Accepted as low-risk (narrow collision window; read-only tool) during review.
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


def match_live_processes(processes, sessions):
    """Correlate live claude processes to today's sessions. See Task 6 docstring in the
    plan for the matching contract (explicit id first, then newest-in-cwd fallback)."""
    matched = {}
    claimed = set()

    for proc in processes:
        sid = proc.get("session_id")
        if sid and sid in sessions and sid not in claimed:
            matched[sid] = {"pid": proc["pid"], "tty": proc["tty"], "certain": True}
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
        matched[best_id] = {"pid": proc["pid"], "tty": proc["tty"], "certain": False}
        claimed.add(best_id)

    return matched


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


def build_report(sessions, matched, cmux_map):
    """Assemble the final report: rows (one per today's session) + daily totals."""
    rows = []
    totals = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
    running_count = 0

    for sid, data in sessions.items():
        running = sid in matched
        workspace = None
        certain = True
        if running:
            running_count += 1
            workspace = cmux_map.get(matched[sid]["tty"])
            certain = matched[sid].get("certain", True)
        for key in totals:
            totals[key] += data["tokens"][key]
        rows.append({
            "session_id": sid,
            "cwd": data["cwd"],
            "title": data["title"],
            "status": "running" if running else "closed",
            "workspace": workspace,
            "certain": certain,
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
        certainty = "" if row.get("certain", True) else "~"
        lines.append(
            f"{certainty + row['session_id'][:8]:10}  {row['status']:8}  {workspace:22}  "
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
        except (OSError, UnicodeDecodeError):
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
