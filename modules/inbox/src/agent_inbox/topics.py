"""The inbox's one door into the agent registry's topic log.

Every call runs `agt registry …` with a short timeout. A missing, slow or failing registry
never blocks an ask, a post or an answer: the entry or the topic history just lacks the link."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

from agent_inbox.errors import ValidationError

TIMEOUT_SEC = 2.0
# registry() returns this when the registry says the named topic does not exist.
NOT_FOUND = object()


def _agt() -> str:
    return os.environ.get("AGENT_INBOX_AGT") or "agt"


def _warn(args: tuple[str, ...], detail: object) -> None:
    what = args[0] if args else "call"
    print(f"agent-inbox: registry {what} failed, continuing without the topic link: {detail}", file=sys.stderr)


def registry(*args: str) -> Any:
    """Run `agt registry <args>`. Returns the parsed JSON stdout, NOT_FOUND for an unknown
    topic, or None on any other failure. Never raises."""
    try:
        proc = subprocess.run(
            [_agt(), "registry", *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=TIMEOUT_SEC, stdin=subprocess.DEVNULL,
        )
        # argparse also exits 2, so the registry's own message decides.
        if proc.returncode == 2 and "topic not found" in proc.stderr:
            return NOT_FOUND
        if proc.returncode != 0:
            _warn(args, proc.stderr.strip() or f"exit {proc.returncode}")
            return None
        return json.loads(proc.stdout)
    except Exception as exc:  # the contract is "never raises": a bad registry must not break an ask
        _warn(args, exc)
        return None


def _clean(data: Any) -> list[dict] | None:
    """Keep a path only if every node has an id: it is stored and rendered as is."""
    if not isinstance(data, list) or not data:
        return None
    path = []
    for node in data:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"]:
            return None
        title = node.get("title")
        path.append({
            "id": node["id"],
            "title": title if isinstance(title, str) else None,
            "kind": "intent" if node.get("kind") == "intent" else "topic",
        })
    return path


def path_for(*, engine: str | None, session_id: str | None, topic: str | None) -> list[dict] | None:
    """The new entry's topic path. A named topic wins over the session's own path. An unknown
    named topic is the asker's mistake, so it is a validation error; a registry failure is not."""
    if topic:
        data = registry("topic-path", f"--topic={topic}")
        if data is NOT_FOUND:
            raise ValidationError(f"unknown topic {topic}")
    elif engine and session_id:
        data = registry("topic-path", f"--type={engine}", f"--session-id={session_id}")
    else:
        return None
    return None if data is NOT_FOUND else _clean(data)


def note(
    kind: str, entry_id: str, path: Any, *, engine: str | None = None, session_id: str | None = None,
    **fields: Any,
) -> None:
    """Record inbox activity in the history of the entry's topic (the path's last node). Best
    effort, never raises. `--key=value` keeps a value that starts with a dash from reading as a flag."""
    last = path[-1] if isinstance(path, list) and path else None
    topic = last.get("id") if isinstance(last, dict) else None
    if not topic:
        return
    args = ["topic-note", kind, f"--topic={topic}", f"--entry={entry_id}"]
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value)
        args.append(f"--{key}={value}")
    if engine and session_id:
        args += [f"--type={engine}", f"--session-id={session_id}"]
    registry(*args)
