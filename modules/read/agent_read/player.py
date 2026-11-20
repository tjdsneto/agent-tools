from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from agent_read import job


class PlayerError(RuntimeError):
    pass


def _ui_bin() -> Path:
    env = os.environ.get("AGENT_READ_UI")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[1] / "bin" / "agent-read-ui"


def run_player(
    wav: Path,
    *,
    title: str | None,
    background: bool,
) -> str:
    bin_path = _ui_bin()
    if not bin_path.is_file() or not os.access(bin_path, os.X_OK):
        raise PlayerError(
            f"agent-read-ui not found at {bin_path}; run scripts/build-ui.sh"
        )
    wav = Path(wav)
    if not wav.is_file():
        raise PlayerError(f"WAV missing: {wav}")

    status_dir = Path(tempfile.mkdtemp(prefix="agent-read-"))
    status_path = status_dir / "status.json"
    cmd = [
        str(bin_path),
        "--wav",
        str(wav),
        "--status",
        str(status_path),
    ]
    if title:
        cmd.extend(["--title", title])

    if background:
        job.stop_background()
        proc = subprocess.Popen(
            cmd,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        job.write_job(proc.pid, wav, title)
        return "ok"

    proc = subprocess.Popen(cmd)
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
        return "stopped"

    if status_path.is_file():
        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
            st = data.get("status", "ok")
            if st == "error":
                raise PlayerError("agent-read-ui reported status error")
            if st in ("ok", "stopped"):
                return st
        except (json.JSONDecodeError, OSError):
            pass
    if proc.returncode == 0:
        return "ok"
    if proc.returncode in (2, 130):
        return "stopped"
    raise PlayerError(f"agent-read-ui exited {proc.returncode} without status")
