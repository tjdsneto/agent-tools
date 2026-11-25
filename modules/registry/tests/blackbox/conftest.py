"""Black-box harness: only agt, the hook script and files on disk. Never imports agent_registry."""
import json
import os
import signal
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

REGISTRY = Path(__file__).resolve().parents[2]
REPO = REGISTRY.parents[1]
AGT = REPO / "agt" / "agt"
HOOK = REGISTRY / "plugin" / "scripts" / "registry-hook"
SESSION_VARS = ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CURSOR_CONVERSATION_ID", "HERDR_ENV")


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

    def hook(self, host, event, payload, timeout=60, shell=None, env=None):
        cmd = [str(HOOK), host, event]
        if shell:
            cmd = [shell, *cmd]
        return subprocess.run(
            cmd, input=json.dumps(payload), env=env or self.env,
            capture_output=True, text=True, timeout=timeout,
        )

    def log(self, agent_type, session_id) -> list[dict]:
        path = self.data / "topics" / agent_type / f"{session_id}.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture
def box(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in SESSION_VARS}
    env.update({
        "AGENT_REGISTRY_PATH": str(tmp_path / "registry" / "registry.json"),
        "AGENT_REGISTRY_DAEMON_PORT": str(_free_port()),
        "AGENT_REGISTRY_DAEMON_START_TIMEOUT": "5",
        "AGENT_REGISTRY_SUMMARY_PROVIDER": "off",
        "AGENT_REGISTRY_BIN": str(REGISTRY / "bin" / "agent-registry"),
    })
    b = Box(root=tmp_path, env=env)
    yield b
    # A command may have started a private daemon on the temp registry; stop it.
    # The client creates daemon.log just before spawning a daemon, which may still be writing its
    # pid file; wait up to 3s, but only when one was started.
    pid_file = b.data / "daemon.pid"
    deadline = time.monotonic() + (3 if (b.data / "daemon.log").exists() else 0)
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    if pid_file.exists():
        try:
            os.kill(int(pid_file.read_text().strip()), signal.SIGTERM)
        except (OSError, ValueError):
            pass
