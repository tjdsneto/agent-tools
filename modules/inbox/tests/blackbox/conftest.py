"""Black-box harness: agt, a temp registry and the agent_inbox_test database.

Never imports agent_inbox or agent_registry. The parent conftest's autouse fixtures patch the
package in this process only; every command here runs in a subprocess."""
import json
import os
import signal
import socket
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest

INBOX = Path(__file__).resolve().parents[2]
REPO = INBOX.parents[1]
AGT = REPO / "agt" / "agt"
REGISTRY_BIN = REPO / "modules" / "registry" / "bin" / "agent-registry"
SESSION_VARS = ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CURSOR_CONVERSATION_ID", "HERDR_ENV")
NOTE_KINDS = ("asked", "posted", "answered", "closed")
TEST_DSN = os.environ.get("AGENT_INBOX_TEST_DSN", "host=localhost port=5433 dbname=agent_inbox_test")


@dataclass
class Box:
    root: Path
    env: dict

    @property
    def data(self) -> Path:
        return self.root / "registry"

    def agt(self, *args, stdin=None, env=None, timeout=60):
        return subprocess.run(
            [str(AGT), *args], input=stdin, env=env or self.env, capture_output=True, text=True, timeout=timeout,
        )

    def agt_json(self, *args, **kw):
        proc = self.agt(*args, **kw)
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)

    def log(self, agent_type, session_id) -> list[dict]:
        path = self.data / "topics" / agent_type / f"{session_id}.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def notes(self, agent_type, session_id) -> list[dict]:
        return [e for e in self.log(agent_type, session_id) if e.get("event") in NOTE_KINDS]


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture
def box(tmp_path):
    with psycopg.connect(TEST_DSN, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS events, entries, ops CASCADE")
    env = {k: v for k, v in os.environ.items() if k not in SESSION_VARS}
    env.update({
        "AGENT_REGISTRY_PATH": str(tmp_path / "registry" / "registry.json"),
        "AGENT_REGISTRY_DAEMON_PORT": str(_free_port()),
        "AGENT_REGISTRY_DAEMON_START_TIMEOUT": "5",
        "AGENT_REGISTRY_SUMMARY_PROVIDER": "off",
        "AGENT_REGISTRY_FORK_BACKEND": "none",
        "AGENT_REGISTRY_BIN": str(REGISTRY_BIN),
        "AGENT_INBOX_DSN": TEST_DSN,
        "AGENT_INBOX_TELEGRAM_TO": "",
        # The inbox must call this checkout's registry, not the one on PATH.
        "AGENT_INBOX_AGT": str(AGT),
    })
    b = Box(root=tmp_path, env=env)
    yield b
    # Nothing here should start a registry daemon, but stop one if a command did.
    pid_file = b.data / "daemon.pid"
    deadline = time.monotonic() + (3 if (b.data / "daemon.log").exists() else 0)
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    if pid_file.exists():
        try:
            os.kill(int(pid_file.read_text().strip()), signal.SIGTERM)
        except (OSError, ValueError):
            pass


@pytest.fixture
def web(box):
    """The inbox's web handler alone, on a free port, with the box's registry and database.
    Not `agt inbox serve`: that also sweeps, which wakes sessions."""
    port = _free_port()
    env = dict(box.env, INBOX_HTTP_PORT=str(port), INBOX_ALLOW_INSECURE="1", PYTHONPATH=str(INBOX / "src"))
    log_path = box.root / "web.log"
    log = open(log_path, "w")
    proc = subprocess.Popen(
        [str(INBOX / ".venv" / "bin" / "python"), "-c", "from agent_inbox.web import make_server; make_server().serve_forever()"],
        env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 10
    while True:
        try:
            urllib.request.urlopen(base + "/", timeout=2).close()
            break
        except OSError:
            if proc.poll() is not None or time.monotonic() > deadline:
                proc.kill()
                log.close()
                pytest.fail(f"web handler didn't start: {log_path.read_text()}")
            time.sleep(0.1)
    yield base
    proc.terminate()
    proc.wait(timeout=5)
    log.close()
