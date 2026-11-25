"""agt registry fork: hand a thread to a new session that Tiago can see."""
from __future__ import annotations

import json
import os
import subprocess
import urllib.parse
from collections.abc import Callable, Mapping, Sequence

from agent_registry import topics

BACKENDS = ("cursor", "herdr", "none")
HERDR_KINDS = ("claude", "codex")

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


def _run(cmd: Sequence[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(list(cmd), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        reason = f"{cmd[0]}: {exc.strerror or exc}" if isinstance(exc, OSError) else f"{cmd[0]}: timed out"
        return subprocess.CompletedProcess(list(cmd), 127, stdout="", stderr=reason)


def default_backend(env: Mapping[str, str] = os.environ) -> str:
    return "herdr" if env.get("HERDR_ENV") == "1" else "cursor"


def child_prompt(topic_id: str, brief: str) -> str:
    return f"Read {brief}, run agt registry intent --adopt {topic_id}, then continue."


def cursor_url(prompt: str) -> str:
    query = urllib.parse.urlencode({"prompt": prompt}, quote_via=urllib.parse.quote)
    return f"cursor://anthropic.claude-code/open?{query}"


def launch_cursor(directory: str, prompt: str, run: Runner) -> dict:
    # The link opens in the last-focused window, so bring the project's window forward first.
    run(["cursor", directory])
    opened = run(["open", cursor_url(prompt)])
    return {"launched": opened.returncode == 0}


def _pane_id(stdout: str) -> str | None:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    pane = (data.get("result") or {}).get("pane") if isinstance(data, dict) else None
    if isinstance(pane, dict):
        pane = pane.get("id") or pane.get("pane_id")
    return pane if isinstance(pane, str) and pane else None


def launch_herdr(directory: str, prompt: str, engine: str, name: str, run: Runner) -> dict:
    split = run(["herdr", "pane", "split", "--current", "--direction", "right", "--cwd", directory, "--no-focus"])
    if split.returncode != 0:
        return {"launched": False, "error": split.stderr.strip() or "herdr pane split failed"}
    pane = _pane_id(split.stdout)
    if not pane:
        return {"launched": False, "error": "herdr pane split returned no pane id"}
    started = run(["herdr", "agent", "start", name, "--kind", engine, "--pane", pane])
    if started.returncode != 0:
        return {"launched": False, "pane": pane, "error": started.stderr.strip() or "herdr agent start failed"}
    sent = run(["herdr", "agent", "prompt", name, prompt])
    if sent.returncode != 0:
        return {
            "launched": False, "pane": pane, "agent": name,
            "error": sent.stderr.strip() or "herdr agent prompt failed",
        }
    return {"launched": True, "pane": pane, "agent": name}


def fork(
    agent_type: str,
    session_id: str,
    title: str,
    *,
    mode: str,
    brief_text: str,
    backend: str | None = None,
    directory: str | None = None,
    run: Runner = _run,
) -> dict:
    backend = backend or default_backend()
    if backend not in BACKENDS:
        raise topics.TopicUsageError(f"backend must be one of {', '.join(BACKENDS)}")
    event = topics.record_fork(agent_type, session_id, title, mode=mode, backend=backend, brief_text=brief_text)
    tid = event["topic"]["id"]
    prompt = child_prompt(tid, event["brief"])
    directory = directory or os.getcwd()
    result = {"topic": event["topic"], "brief": event["brief"], "backend": backend, "prompt": prompt, "launched": False}
    if backend == "cursor":
        result.update(launch_cursor(directory, prompt, run))
    elif backend == "herdr":
        engine = agent_type if agent_type in HERDR_KINDS else "claude"
        result.update(launch_herdr(directory, prompt, engine, f"fork-{tid}", run))
    return result
