from __future__ import annotations
import json, os, subprocess, tempfile, time
from pathlib import Path

def _ui_bin() -> Path:
    env = os.environ.get("AGENT_SAY_UI")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[1] / "bin" / "agent-say-ui"

def run_ui(request: dict, *, timeout_sec: float | None = None) -> dict:
    bin_path = _ui_bin()
    if not bin_path.is_file():
        raise RuntimeError(f"agent-say-ui not found at {bin_path}; build ui/ first")
    with tempfile.TemporaryDirectory(prefix="agent-say-") as td:
        req_path = Path(td) / "request.json"
        resp_path = Path(td) / "response.json"
        req_path.write_text(json.dumps(request))
        proc = subprocess.Popen(
            [str(bin_path), "--request", str(req_path), "--response", str(resp_path)],
        )
        deadline = None if timeout_sec is None else time.monotonic() + float(timeout_sec)
        while True:
            if resp_path.is_file() and resp_path.stat().st_size > 0:
                proc.wait(timeout=2)
                return json.loads(resp_path.read_text())
            if proc.poll() is not None:
                if resp_path.is_file():
                    return json.loads(resp_path.read_text())
                raise RuntimeError(f"agent-say-ui exited {proc.returncode} without response")
            if deadline is not None and time.monotonic() > deadline:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise TimeoutError()
            time.sleep(0.05)
