from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path

_DEFAULT_CACHE = Path.home() / "Library" / "Caches" / "agent-read"


def job_dir() -> Path:
    return Path(os.environ.get("AGENT_READ_CACHE", _DEFAULT_CACHE)).expanduser()


def _job_path() -> Path:
    return job_dir() / "job.json"


def write_job(pid: int, wav: Path, title: str | None) -> Path:
    d = job_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = _job_path()
    path.write_text(
        json.dumps(
            {
                "pid": pid,
                "wav": str(wav),
                "title": title,
            }
        ),
        encoding="utf-8",
    )
    return path


def read_job() -> dict | None:
    path = _job_path()
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def clear_job() -> None:
    path = _job_path()
    try:
        path.unlink()
    except OSError:
        pass


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _unlink_wav(wav: str | Path) -> None:
    try:
        Path(wav).unlink()
    except OSError:
        pass


def stop_background() -> str:
    """Return 'stopped' if a live job was signaled, else 'ok' (nothing playing)."""
    data = read_job()
    if not data:
        return "ok"
    pid = int(data["pid"])
    wav = data.get("wav")
    if not _pid_alive(pid):
        if wav:
            _unlink_wav(wav)
        clear_job()
        return "ok"
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        if wav:
            _unlink_wav(wav)
        clear_job()
        return "ok"
    for _ in range(50):
        if not _pid_alive(pid):
            break
        time.sleep(0.05)
    if _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    if wav:
        _unlink_wav(wav)
    clear_job()
    return "stopped"
