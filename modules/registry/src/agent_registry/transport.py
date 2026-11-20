"""Resolve a session UUID to a live handle, and wake it.

Claude Code is the first transport. The address (name, socket, pid) is stored
on the registry row by the hook; resolve falls back to ~/.claude/sessions when
the row has none. Wake nudges a live process via SendMessage and resumes a
dead one from disk. A SendMessage tool success is not delivery — a
cross-session notice in the dialer output wins.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from agent_registry import store
from agent_registry.models import normalize_text, parse_pid
from agent_registry.ops import ValidationError

CLAUDE_INBOUND_ACCEPT = json.dumps(
    {"crossSessionInbound": "accept"}, separators=(",", ":")
)
# A real notice. The SendMessage tool result only mentions that a notice
# "follows if" the target holds the message, and that line is not one.
NOTICE_PREFIX = "[Cross-session delivery notice] Your message"


class SessionNotFoundError(Exception):
    pass


class UnsupportedTransportError(Exception):
    pass


def claude_sessions_dir() -> Path:
    return Path.home() / ".claude" / "sessions"


def codex_index_path() -> Path:
    return Path.home() / ".codex" / "session_index.jsonl"


def cursor_chats_dir() -> Path:
    return Path.home() / ".cursor" / "chats"


def pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def read_claude_address(session_id: str, sessions_dir: Path) -> dict | None:
    """Match ~/.claude/sessions/<pid>.json on sessionId. None if absent."""
    if not sessions_dir.is_dir():
        return None
    for path in sessions_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or data.get("sessionId") != session_id:
            continue
        return {
            "peer_name": normalize_text(data.get("name")),
            "socket": normalize_text(data.get("messagingSocketPath")),
            "pid": parse_pid(data.get("pid")),
            "peer_status": normalize_text(data.get("status")),
            "cwd": normalize_text(data.get("cwd")),
        }
    return None


def read_codex_address(session_id: str, index_path: Path) -> dict | None:
    """Last session_index.jsonl row for this thread id. Codex has no pid or socket."""
    if not index_path.is_file():
        return None
    found = None
    for line in index_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and rec.get("id") == session_id:
            found = rec
    if found is None:
        return None
    return {
        "peer_name": normalize_text(found.get("thread_name")),
        "socket": None,
        "pid": None,
        "peer_status": None,
        "cwd": None,
    }


def codex_sessions_dir() -> Path:
    return Path.home() / ".codex" / "sessions"


def read_codex_rollout(session_id: str, sessions_root: Path) -> dict | None:
    """exec threads land in a rollout file and may be absent from session_index."""
    if not sessions_root.is_dir():
        return None
    matches = sorted(sessions_root.glob(f"*/*/*/rollout-*-{session_id}.jsonl"))
    if not matches:
        return None
    try:
        first = matches[-1].open().readline()
        rec = json.loads(first) if first.strip() else None
    except (OSError, json.JSONDecodeError):
        return None
    payload = rec.get("payload") if isinstance(rec, dict) else None
    if not isinstance(payload, dict) or payload.get("session_id") != session_id:
        return None
    return {
        "peer_name": normalize_text(payload.get("thread_name")),
        "socket": None,
        "pid": None,
        "peer_status": None,
        "cwd": normalize_text(payload.get("cwd")),
    }


def read_cursor_address(session_id: str, chats_dir: Path) -> dict | None:
    """meta.json for chats/<workspace>/<chatId>. The chat id is the directory name."""
    if not chats_dir.is_dir():
        return None
    matches = sorted(chats_dir.glob(f"*/{session_id}/meta.json"))
    if not matches:
        return None
    try:
        data = json.loads(matches[-1].read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return {
        "peer_name": None,
        "socket": None,
        "pid": None,
        "peer_status": None,
        "cwd": normalize_text(data.get("cwd")),
    }


def codex_thread_live(session_id: str) -> bool:
    """True when `codex agents` output contains the thread id.

    The command is a TUI and often prints nothing without a terminal, so a
    headless caller should pass an explicit live set into resolve/wake.
    """
    try:
        proc = subprocess.run(
            ["codex", "agents"],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return session_id in ((proc.stdout or "") + (proc.stderr or ""))


def resolve_session(
    session_id: str,
    *,
    sessions_dir: Path | None = None,
    codex_index: Path | None = None,
    codex_sessions: Path | None = None,
    cursor_chats: Path | None = None,
    alive_check=None,
    codex_live=None,
) -> dict:
    """Address for a session UUID. Registry row first; harness files fill a missing name."""
    sessions_dir = sessions_dir if sessions_dir is not None else claude_sessions_dir()
    codex_index = codex_index if codex_index is not None else codex_index_path()
    codex_sessions = codex_sessions if codex_sessions is not None else codex_sessions_dir()
    cursor_chats = cursor_chats if cursor_chats is not None else cursor_chats_dir()
    if alive_check is None:
        alive_check = pid_alive
    if codex_live is None:
        codex_live = codex_thread_live

    sess = None
    for s in store.load().sessions:
        if s.session_id == session_id:
            sess = s
            break

    peer_name = sess.peer_name if sess else None
    socket = sess.socket if sess else None
    pid = sess.pid if sess else None
    peer_status = sess.peer_status if sess else None
    directory = sess.directory if sess else None
    agent_type = sess.agent_type if sess else None
    source = "registry" if sess is not None else None

    def _take(harvested: dict, source_name: str, default_agent: str) -> None:
        nonlocal peer_name, socket, pid, peer_status, directory, agent_type, source
        if peer_name is None:
            peer_name = harvested.get("peer_name")
        if socket is None:
            socket = harvested.get("socket")
        if pid is None:
            pid = harvested.get("pid")
        if peer_status is None:
            peer_status = harvested.get("peer_status")
        if directory is None:
            directory = harvested.get("cwd")
        agent_type = agent_type or default_agent
        if source != "registry" or peer_name == harvested.get("peer_name"):
            source = source_name
        if sess is not None and not sess.peer_name and harvested.get("peer_name"):
            source = source_name
        if sess is None:
            source = source_name

    looked = False
    if agent_type in (None, "claude") and (sess is None or not peer_name):
        looked = True
        harvested = read_claude_address(session_id, sessions_dir)
        if harvested is not None and (sess is None or not peer_name):
            _take(harvested, "sessions_file", "claude")
    if agent_type in (None, "codex") and (sess is None or (agent_type == "codex" and not peer_name)):
        looked = True
        harvested = read_codex_address(session_id, codex_index)
        source_name = "session_index"
        if harvested is None:
            harvested = read_codex_rollout(session_id, codex_sessions)
            source_name = "rollout"
        if harvested is not None and not peer_name:
            _take(harvested, source_name, "codex")
    if agent_type in (None, "cursor") and (sess is None or agent_type == "cursor"):
        looked = True
        harvested = read_cursor_address(session_id, cursor_chats)
        if harvested is not None and sess is None:
            _take(harvested, "cursor_meta", "cursor")
        elif harvested is not None and directory is None:
            directory = harvested.get("cwd")

    if sess is None and source is None:
        raise SessionNotFoundError(session_id)
    if sess is None and not looked:
        raise SessionNotFoundError(session_id)

    if agent_type == "codex":
        alive = bool(codex_live(session_id))
    elif agent_type == "cursor":
        alive = False
    else:
        alive = bool(alive_check(pid))

    return {
        "session_id": session_id,
        "agent_type": agent_type,
        "peer_name": peer_name,
        "socket": socket,
        "pid": pid,
        "peer_status": peer_status,
        "directory": directory,
        "alive": alive,
        "source": source,
    }


def notice_snippet(text: str) -> str | None:
    """Last real delivery notice in text, or None.

    The last one wins: a held message later expires, and the expiry notice
    is the outcome that matters.
    """
    if not text:
        return None
    i = text.rfind(NOTICE_PREFIX)
    if i < 0:
        return None
    return text[i:i + 700]


def claude_projects_dir() -> Path:
    return Path.home() / ".claude" / "projects"


def read_dialer_notice(session_id: str, projects_dir: Path | None = None) -> str | None:
    """Notice text queued into the dialer transcript, even if the model never saw it."""
    root = projects_dir if projects_dir is not None else claude_projects_dir()
    if not root.is_dir():
        return None
    matches = sorted(root.glob(f"*/{session_id}.jsonl"))
    if not matches:
        return None
    try:
        text = matches[-1].read_text(errors="replace")
    except OSError:
        return None
    return notice_snippet(text)


def _settle_seconds() -> float:
    raw = os.environ.get("AGENT_REGISTRY_WAKE_SETTLE_SECONDS")
    if raw is None or raw == "":
        return 2.0
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 2.0


def _wait_for_notice(session_id: str, projects_dir: Path | None, settle: float) -> str | None:
    deadline = time.monotonic() + settle
    while True:
        snippet = read_dialer_notice(session_id, projects_dir)
        if snippet or time.monotonic() >= deadline:
            return snippet
        time.sleep(0.2)


def classify_delivery(output: str) -> str:
    """landed only on an explicit token. A real delivery notice overrides that token."""
    text = output or ""
    if NOTICE_PREFIX in text:
        low = text.lower()
        if "was held" in low:
            return "held"
        if "refused" in low:
            return "refused"
        return "undelivered"
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("wake_result:"):
            continue
        token = stripped.split(":", 1)[1].strip().lower()
        if token == "landed":
            return "landed"
        if token == "held":
            return "held"
        if token == "refused":
            return "refused"
        return "undelivered"
    return "undelivered"


def nudge_argv(
    peer_name: str,
    message: str,
    claude: str = "claude",
    session_id: str | None = None,
) -> list[str]:
    """Send only. Delivery is judged from the dialer transcript, not this turn.

    The model is told to print `submitted`. A held target writes
    `[Cross-session delivery notice] Your message ... was held` into this
    session's jsonl after SendMessage returns, often after the model has
    already stopped. `--session-id` makes that file findable.
    """
    session_id = session_id or "00000000-0000-4000-8000-000000000001"
    prompt = (
        "You are a one-shot dialer. Steps, then stop: "
        "(1) Call ListAgents. "
        f'(2) Find the row whose name is exactly "{peer_name}". '
        "(3) If found, call SendMessage with `to` set to that exact name and "
        "`message` set to the text between <wake-message> and </wake-message>. "
        "Then print exactly: wake_result: submitted. "
        "Do not judge whether the message was delivered. "
        "If no row matches, print exactly: wake_result: unreachable. "
        "Use only ListAgents and SendMessage. Output no other prose.\n"
        f"<wake-message>\n{message}\n</wake-message>"
    )
    return [
        claude,
        "--session-id",
        session_id,
        "--dangerously-skip-permissions",
        "--allowedTools",
        "ListAgents,SendMessage",
        "-p",
        prompt,
    ]


def resume_argv(session_id: str, message: str, claude: str = "claude") -> list[str]:
    return [
        claude,
        "-p",
        "--resume",
        session_id,
        "--dangerously-skip-permissions",
        "--settings",
        CLAUDE_INBOUND_ACCEPT,
        message,
    ]


def codex_nudge_argv(session_id: str, message: str, codex: str = "codex") -> list[str]:
    """Live Codex nudge. No --resume: that flag is only for a thread off the daemon."""
    return [codex, "queue", "--thread", session_id, "--message", message]


def codex_resume_argv(
    session_id: str,
    message: str,
    codex: str = "codex",
    reply_path: str | None = None,
) -> list[str]:
    """Resume a thread that is off the daemon.

    The last message is the only text that counts. Codex echoes the prompt
    in its event stream, and that echo contains the token below.
    """
    prompt = (
        "If you are already awake and this wake would only duplicate work, "
        "print exactly this line and do nothing else:\n"
        "wake_result: already_awake\n"
        "Otherwise do the work in the message below and do not print that line.\n"
        f"<wake-message>\n{message}\n</wake-message>"
    )
    # Session cwd may be outside a trusted git repo (codex exec in /tmp).
    return [
        codex,
        "exec",
        "resume",
        "--skip-git-repo-check",
        "--output-last-message",
        reply_path or os.devnull,
        session_id,
        prompt,
    ]


def cursor_resume_argv(
    session_id: str, message: str, binary: str = "cursor-agent"
) -> list[str]:
    """Cursor has no inbound nudge. Both liveness branches are a new headless process."""
    return [binary, "--resume", session_id, "--force", "-p", message]


def run_claude(argv: list[str], cwd: str | None) -> tuple[str, int]:
    proc = subprocess.run(
        argv,
        cwd=cwd or None,
        capture_output=True,
        text=True,
    )
    return (proc.stdout or "") + (proc.stderr or ""), proc.returncode


def _exit_result(code: int) -> str:
    return "landed" if code == 0 else "undelivered"


def _codex_resume_result(reply_path: Path, code: int) -> str:
    """The last message decides. A redundant wake says so; otherwise the exit code does."""
    try:
        text = reply_path.read_text(errors="replace") if reply_path.is_file() else ""
    except OSError:
        text = ""
    if "wake_result: already_awake" in text:
        return "already_awake"
    return _exit_result(code)


def _claude_nudge_result(
    stdout: str,
    dialer_id: str,
    *,
    projects_dir: Path | None,
    code: int,
) -> str:
    """Held/refused/expired come from the dialer transcript. No notice means delivered."""
    snippet = notice_snippet(stdout) or _wait_for_notice(
        dialer_id, projects_dir, _settle_seconds()
    )
    if snippet:
        return classify_delivery(snippet)
    if "wake_result: unreachable" in (stdout or ""):
        return "undelivered"
    if code == 0 and (
        "wake_result: submitted" in (stdout or "")
        or "wake_result: landed" in (stdout or "")
    ):
        return "landed"
    return "undelivered"


def wake(
    session_id: str,
    message: str,
    *,
    sessions_dir: Path | None = None,
    codex_index: Path | None = None,
    codex_sessions: Path | None = None,
    cursor_chats: Path | None = None,
    alive_check=None,
    codex_live=None,
    runner=None,
    projects_dir: Path | None = None,
) -> dict:
    if not (message or "").strip():
        raise ValidationError("wake message is empty")
    view = resolve_session(
        session_id,
        sessions_dir=sessions_dir,
        codex_index=codex_index,
        codex_sessions=codex_sessions,
        cursor_chats=cursor_chats,
        alive_check=alive_check,
        codex_live=codex_live,
    )
    agent_type = view.get("agent_type") or ""
    if agent_type not in {"claude", "codex", "cursor"}:
        raise UnsupportedTransportError(
            f"no wake transport for {agent_type or 'unknown'}"
        )

    base = {
        "session_id": session_id,
        "agent_type": agent_type,
        "peer_name": view.get("peer_name"),
        "alive": view["alive"],
    }
    run = runner or run_claude
    if agent_type == "cursor":
        argv = cursor_resume_argv(session_id, message)
        stdout, code = run(argv, view.get("directory"))
        return {**base, "mode": "resume", "result": _exit_result(code)}

    if agent_type == "codex":
        if view["alive"]:
            argv = codex_nudge_argv(session_id, message)
            stdout, code = run(argv, view.get("directory"))
            return {**base, "mode": "nudge", "result": _exit_result(code)}
        fd, name = tempfile.mkstemp(prefix="ar-codex-reply-")
        os.close(fd)
        reply = Path(name)
        try:
            argv = codex_resume_argv(session_id, message, reply_path=str(reply))
            stdout, code = run(argv, view.get("directory"))
            result = _codex_resume_result(reply, code)
        finally:
            reply.unlink(missing_ok=True)
        return {**base, "mode": "resume", "result": result}

    if view["alive"] and not view.get("peer_name"):
        return {**base, "mode": "none", "result": "undelivered", "reason": "no_address"}
    if view["alive"]:
        dialer_id = str(uuid.uuid4())
        argv = nudge_argv(view["peer_name"], message, session_id=dialer_id)
        mode = "nudge"
        stdout, code = run(argv, view.get("directory"))
        result = _claude_nudge_result(
            stdout, dialer_id, projects_dir=projects_dir, code=code,
        )
    else:
        argv = resume_argv(session_id, message)
        mode = "resume"
        stdout, code = run(argv, view.get("directory"))
        result = _exit_result(code)
    return {**base, "mode": mode, "result": result}
