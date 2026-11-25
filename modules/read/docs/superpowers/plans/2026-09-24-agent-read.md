# agent-read Implementation Plan

> **Superseded** by `2026-09-25-agent-say.md` — use `agent-say read`; no separate agent-read project.


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a blocking `agent-read` CLI + SwiftAV playback helper (play/pause/stop) + hard-fail Kokoro synth + shared skill so any agent can hand text/file to the human as spoken audio and get a JSON result on stdout.

**Architecture:** Python CLI owns text-source selection, Kokoro synthesis to a temp WAV, job records for background mode, exit codes, and orchestration. A small SwiftUI helper (`agent-read-ui`) plays the WAV with AVFoundation (real pause) and reports finished vs stopped. Skill lives in `tjdsneto-setup` and is linked by `install.sh`. Kokoro stays in `$KOKORO_HOME` (same layout as agent-ping).

**Tech Stack:** Python 3.11+ (stdlib + pytest), SwiftUI + AVFoundation macOS helper (SwiftPM), `kokoro-onnx` + `soundfile` in `$KOKORO_HOME/venv`.

**Spec:** `docs/superpowers/specs/2026-09-24-agent-read-design.md`

---

## File Structure

**New project** `~/projects/agent-read/` (own git repo):

| Path | Responsibility |
|------|----------------|
| `bin/agent-read` | Executable entry → `.venv/bin/python -m agent_read.cli` |
| `bin/agent-read-ui` | Built Swift binary (or wrapper) |
| `agent_read/__init__.py` | Package version |
| `agent_read/result.py` | Build response dict + exit code mapping |
| `agent_read/text_source.py` | Resolve stdin / `--file` / `--text` (exactly one) |
| `agent_read/kokoro.py` | Hard-fail Kokoro → WAV path |
| `agent_read/job.py` | Background job record (pid, wav, title) under cache dir |
| `agent_read/player.py` | Launch Swift UI foreground or background; map exit → status |
| `agent_read/cli.py` | `main(argv) -> int` including `stop` subcommand |
| `ui/Package.swift` + `ui/Sources/AgentReadUI/` | SwiftUI + AVAudioPlayer helper |
| `tests/test_result.py` | Exit codes / result shape |
| `tests/test_text_source.py` | Source mutual exclusion + empty |
| `tests/test_kokoro.py` | Missing home → error; ready path mocked |
| `tests/test_job.py` | Write/read/clear job; stop with no job |
| `tests/test_cli_contract.py` | End-to-end with mocked kokoro + player |
| `README.md` | Install, contract, Kokoro, skill pointer |
| `requirements.txt` | `pytest` (no pydantic required for v1) |
| `scripts/build-ui.sh` | `swift build -c release` + copy to `bin/agent-read-ui` |

**In `tjdsneto-setup`:**

| Path | Responsibility |
|------|----------------|
| `ai/skills/shared/agent-read/SKILL.md` | When/how to call; parse stdout |
| (optional) note in README that `install.sh` links shared skills |

**Public Python API (stable across tasks):**

```python
# result.py
def make_result(
    status: str,
    *,
    mode: str,
    title: str | None,
    chars: int,
    voice: str,
    elapsed_ms: int,
) -> dict: ...
def exit_code(status: str) -> int: ...  # ok→0, stopped→130, error→1

# text_source.py
class TextSourceError(ValueError): ...
def load_text(*, file: str | None, text: str | None, stdin_data: str | None) -> str: ...

# kokoro.py
class KokoroError(RuntimeError): ...
def synthesize(text: str, *, voice: str, speed: float, out_wav: Path) -> None: ...
def kokoro_ready(home: Path | None = None) -> bool: ...

# job.py
def job_dir() -> Path: ...
def write_job(pid: int, wav: Path, title: str | None) -> Path: ...
def read_job() -> dict | None: ...
def clear_job() -> None: ...
def stop_background() -> str:  # returns "stopped" | "ok" (nothing playing)

# player.py
def run_player(
    wav: Path,
    *,
    title: str | None,
    background: bool,
) -> str:  # returns "ok" | "stopped"; raises on launch failure
```

**UI protocol:**

```
agent-read launches:
  agent-read-ui --wav <path> --title <str> --status <path>
agent-read-ui writes status.json {"status":"ok"|"stopped"} then exits
  exit 0 after write; CLI trusts status.json when present
Foreground: wait for process; read status.json
Background: detach; write job.json {pid, wav, title, status_path}
stop: SIGTERM pid (or kill); clear job; remove wav; return stopped|ok
```

**Cache / job path:** `~/Library/Caches/agent-read/job.json` (override with `$AGENT_READ_CACHE`).

---

### Task 1: Scaffold project + result helpers

**Files:**
- Create: `/Users/tjdsneto/projects/agent-read/` (git init)
- Create: `agent_read/__init__.py`, `agent_read/result.py`, `requirements.txt`, `README.md` (stub), `bin/agent-read`, `.gitignore`
- Create: `tests/test_result.py`

- [ ] **Step 1: Create dirs and venv**

```bash
mkdir -p ~/projects/agent-read/{agent_read,tests,ui/Sources/AgentReadUI,bin,scripts}
cd ~/projects/agent-read
git init
python3 -m venv .venv
.venv/bin/pip install pytest
printf 'pytest>=8\n' > requirements.txt
cat > .gitignore <<'EOF'
.venv/
__pycache__/
.pytest_cache/
*.pyc
/dist/
ui/.build/
*.wav
EOF
```

- [ ] **Step 2: Write failing tests**

```python
# tests/test_result.py
from agent_read.result import make_result, exit_code


def test_make_result_shape():
    r = make_result(
        "ok",
        mode="foreground",
        title="Hi",
        chars=2,
        voice="am_michael",
        elapsed_ms=10,
    )
    assert r == {
        "status": "ok",
        "mode": "foreground",
        "title": "Hi",
        "chars": 2,
        "voice": "am_michael",
        "elapsed_ms": 10,
    }


def test_exit_codes():
    assert exit_code("ok") == 0
    assert exit_code("stopped") == 130
    assert exit_code("error") == 1
```

- [ ] **Step 3: Run — expect fail**

```bash
cd ~/projects/agent-read && .venv/bin/pytest tests/test_result.py -v
```

Expected: `ModuleNotFoundError` or import error.

- [ ] **Step 4: Implement result + package stub**

```python
# agent_read/__init__.py
__version__ = "0.1.0"
```

```python
# agent_read/result.py
from __future__ import annotations


def make_result(
    status: str,
    *,
    mode: str,
    title: str | None,
    chars: int,
    voice: str,
    elapsed_ms: int,
) -> dict:
    return {
        "status": status,
        "mode": mode,
        "title": title,
        "chars": chars,
        "voice": voice,
        "elapsed_ms": elapsed_ms,
    }


def exit_code(status: str) -> int:
    if status == "ok":
        return 0
    if status == "stopped":
        return 130
    return 1
```

```bash
# bin/agent-read
#!/usr/bin/env bash
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/.venv/bin/python" -m agent_read.cli "$@"
```

```bash
chmod +x bin/agent-read
printf '# agent-read\n\nKokoro read-aloud CLI for agents. See design spec in tjdsneto-setup.\n' > README.md
```

- [ ] **Step 5: Run tests — expect pass**

```bash
cd ~/projects/agent-read && .venv/bin/pytest tests/test_result.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd ~/projects/agent-read
git add -A
git commit -m "feat: scaffold agent-read + result helpers"
```

---

### Task 2: Text source loading

**Files:**
- Create: `agent_read/text_source.py`
- Create: `tests/test_text_source.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_text_source.py
import pytest
from agent_read.text_source import TextSourceError, load_text


def test_text_flag():
    assert load_text(file=None, text=" hello ", stdin_data=None) == "hello"


def test_file(tmp_path):
    p = tmp_path / "n.md"
    p.write_text("from file\n")
    assert load_text(file=str(p), text=None, stdin_data=None) == "from file"


def test_stdin():
    assert load_text(file=None, text=None, stdin_data="piped") == "piped"


def test_empty_raises():
    with pytest.raises(TextSourceError):
        load_text(file=None, text="  ", stdin_data=None)


def test_dual_sources_raise(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("x")
    with pytest.raises(TextSourceError):
        load_text(file=str(p), text="y", stdin_data=None)


def test_no_source_raises():
    with pytest.raises(TextSourceError):
        load_text(file=None, text=None, stdin_data=None)


def test_file_and_stdin_raise(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("x")
    with pytest.raises(TextSourceError):
        load_text(file=str(p), text=None, stdin_data="also")
```

- [ ] **Step 2: Run — expect fail**

```bash
cd ~/projects/agent-read && .venv/bin/pytest tests/test_text_source.py -v
```

Expected: import error.

- [ ] **Step 3: Implement**

```python
# agent_read/text_source.py
from __future__ import annotations
from pathlib import Path


class TextSourceError(ValueError):
    pass


def load_text(
    *,
    file: str | None,
    text: str | None,
    stdin_data: str | None,
) -> str:
    sources = []
    if file is not None:
        sources.append("file")
    if text is not None:
        sources.append("text")
    if stdin_data is not None:
        sources.append("stdin")

    if len(sources) == 0:
        raise TextSourceError("provide exactly one of: --file, --text, or stdin")
    if len(sources) > 1:
        raise TextSourceError(f"multiple text sources: {', '.join(sources)}")

    if file is not None:
        raw = Path(file).expanduser().read_text(encoding="utf-8")
    elif text is not None:
        raw = text
    else:
        raw = stdin_data or ""

    out = raw.strip()
    if not out:
        raise TextSourceError("text is empty after trim")
    return out
```

**CLI note (for Task 6):** treat stdin as provided only when `not sys.stdin.isatty()` — read it then; if TTY and no `--file`/`--text`, pass `stdin_data=None` so `load_text` errors. If both `--file` and non-TTY stdin, pass both and let mutual exclusion fail (or prefer: if `--file` or `--text` set, ignore stdin — **choose ignore stdin when flag present** to match agent ergonomics):

Update `load_text` callers: if `file` or `text` is set, pass `stdin_data=None` even if piped. Tests above already cover dual; CLI will avoid dual by ignoring stdin when flags set.

- [ ] **Step 4: Run tests — expect pass**

```bash
cd ~/projects/agent-read && .venv/bin/pytest tests/test_text_source.py tests/test_result.py -v
```

- [ ] **Step 5: Commit**

```bash
cd ~/projects/agent-read
git add agent_read/text_source.py tests/test_text_source.py
git commit -m "feat: load text from file, --text, or stdin"
```

---

### Task 3: Kokoro synthesize (hard-fail)

**Files:**
- Create: `agent_read/kokoro.py`
- Create: `tests/test_kokoro.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_kokoro.py
from pathlib import Path
import pytest
from agent_read.kokoro import KokoroError, kokoro_ready, synthesize


def test_kokoro_ready_false_for_missing(tmp_path):
    assert kokoro_ready(tmp_path) is False


def test_synthesize_missing_home_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("KOKORO_HOME", str(tmp_path / "missing"))
    with pytest.raises(KokoroError):
        synthesize("hello", voice="am_michael", speed=1.0, out_wav=tmp_path / "o.wav")
```

- [ ] **Step 2: Run — expect fail**

```bash
cd ~/projects/agent-read && .venv/bin/pytest tests/test_kokoro.py -v
```

- [ ] **Step 3: Implement (adapt from agent-ping `speak.py`, hard-fail, no `say`)**

```python
# agent_read/kokoro.py
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

_DEFAULT_KOKORO_HOME = Path.home() / ".local" / "share" / "kokoro-onnx"

_KOKORO_SCRIPT = """\
import os
import soundfile as sf
from kokoro_onnx import Kokoro

kokoro = Kokoro(os.environ["KOKORO_MODEL"], os.environ["KOKORO_VOICES"])
with open(os.environ["KOKORO_TEXT"], encoding="utf-8") as fh:
    text = fh.read().strip()
samples, sample_rate = kokoro.create(
    text,
    voice=os.environ["KOKORO_VOICE"],
    speed=float(os.environ.get("KOKORO_SPEED", "1.0")),
    lang="en-us",
)
sf.write(os.environ["KOKORO_OUT"], samples, sample_rate)
"""


class KokoroError(RuntimeError):
    pass


def _kokoro_home(home: Path | None = None) -> Path:
    if home is not None:
        return home
    return Path(os.environ.get("KOKORO_HOME", _DEFAULT_KOKORO_HOME)).expanduser()


def kokoro_ready(home: Path | None = None) -> bool:
    h = _kokoro_home(home)
    py = h / "venv" / "bin" / "python"
    model = h / "kokoro-v1.0.onnx"
    voices = h / "voices-v1.0.bin"
    return py.is_file() and os.access(py, os.X_OK) and model.is_file() and voices.is_file()


def synthesize(
    text: str,
    *,
    voice: str,
    speed: float,
    out_wav: Path,
    home: Path | None = None,
) -> None:
    if not text.strip():
        raise KokoroError("empty text")
    h = _kokoro_home(home)
    if not kokoro_ready(h):
        raise KokoroError(
            f"Kokoro not ready at {h}; need venv/bin/python, "
            "kokoro-v1.0.onnx, voices-v1.0.bin"
        )
    py = h / "venv" / "bin" / "python"
    model = h / "kokoro-v1.0.onnx"
    voices = h / "voices-v1.0.bin"
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".txt", delete=False
    ) as text_fh:
        text_fh.write(text)
        text_path = text_fh.name
    try:
        env = os.environ.copy()
        env.update(
            {
                "KOKORO_MODEL": str(model),
                "KOKORO_VOICES": str(voices),
                "KOKORO_VOICE": voice,
                "KOKORO_SPEED": str(speed),
                "KOKORO_TEXT": text_path,
                "KOKORO_OUT": str(out_wav),
            }
        )
        proc = subprocess.run(
            [str(py), "-c", _KOKORO_SCRIPT],
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if proc.returncode != 0:
            raise KokoroError(proc.stderr.strip() or f"kokoro exit {proc.returncode}")
        if not out_wav.is_file() or out_wav.stat().st_size == 0:
            raise KokoroError("kokoro produced no WAV")
    except KokoroError:
        raise
    except Exception as exc:
        raise KokoroError(str(exc)) from exc
    finally:
        try:
            os.unlink(text_path)
        except OSError:
            pass
```

- [ ] **Step 4: Run unit tests — expect pass**

```bash
cd ~/projects/agent-read && .venv/bin/pytest tests/test_kokoro.py -v
```

- [ ] **Step 5 (optional manual):** if `$KOKORO_HOME` is ready, synthesize a short phrase to `/tmp/agent-read-smoke.wav` via a one-liner; skip if not installed.

- [ ] **Step 6: Commit**

```bash
cd ~/projects/agent-read
git add agent_read/kokoro.py tests/test_kokoro.py
git commit -m "feat: hard-fail Kokoro synthesize to WAV"
```

---

### Task 4: Background job store + stop

**Files:**
- Create: `agent_read/job.py`
- Create: `tests/test_job.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_job.py
import os
from pathlib import Path
from agent_read import job


def test_write_read_clear(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_READ_CACHE", str(tmp_path))
    p = job.write_job(12345, tmp_path / "a.wav", "T")
    assert p.is_file()
    data = job.read_job()
    assert data["pid"] == 12345
    assert data["title"] == "T"
    job.clear_job()
    assert job.read_job() is None


def test_stop_nothing_playing(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_READ_CACHE", str(tmp_path))
    assert job.stop_background() == "ok"


def test_stop_dead_pid_clears(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_READ_CACHE", str(tmp_path))
    wav = tmp_path / "x.wav"
    wav.write_bytes(b"RIFF")
    job.write_job(99999999, wav, None)  # almost certainly dead
    status = job.stop_background()
    assert status in ("ok", "stopped")
    assert job.read_job() is None
```

- [ ] **Step 2: Run — expect fail**

```bash
cd ~/projects/agent-read && .venv/bin/pytest tests/test_job.py -v
```

- [ ] **Step 3: Implement**

```python
# agent_read/job.py
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
    # wait briefly for death
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
```

- [ ] **Step 4: Run tests — expect pass**

```bash
cd ~/projects/agent-read && .venv/bin/pytest tests/test_job.py -v
```

- [ ] **Step 5: Commit**

```bash
cd ~/projects/agent-read
git add agent_read/job.py tests/test_job.py
git commit -m "feat: background job record and stop"
```

---

### Task 5: Player runner (mockable)

**Files:**
- Create: `agent_read/player.py`
- Create: `tests/test_player.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_player.py
import json
from pathlib import Path
import pytest
from agent_read.player import PlayerError, run_player


def test_missing_ui_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_READ_UI", str(tmp_path / "nope"))
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")
    with pytest.raises(PlayerError):
        run_player(wav, title="t", background=False)


def test_foreground_reads_status(tmp_path, monkeypatch):
    ui = tmp_path / "fake-ui"
    ui.write_text(
        "#!/bin/bash\n"
        "# args: --wav --title --status\n"
        "status=
while [ $# -gt 0 ]; do
  case \"$1\" in
    --status) status=\"$2\"; shift 2;;
    *) shift;;
  esac
done
printf '%s' '{\"status\":\"ok\"}' > \"$status\"
"
    )
    ui.chmod(0o755)
    monkeypatch.setenv("AGENT_READ_UI", str(ui))
    monkeypatch.setenv("AGENT_READ_CACHE", str(tmp_path / "cache"))
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")
    assert run_player(wav, title="Hi", background=False) == "ok"
```

- [ ] **Step 2: Run — expect fail**

```bash
cd ~/projects/agent-read && .venv/bin/pytest tests/test_player.py -v
```

- [ ] **Step 3: Implement**

```python
# agent_read/player.py
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
            if st in ("ok", "stopped"):
                return st
        except (json.JSONDecodeError, OSError):
            pass
    if proc.returncode == 0:
        return "ok"
    if proc.returncode in (2, 130):
        return "stopped"
    raise PlayerError(f"agent-read-ui exited {proc.returncode} without status")
```

- [ ] **Step 4: Run tests — expect pass**

```bash
cd ~/projects/agent-read && .venv/bin/pytest tests/test_player.py -v
```

- [ ] **Step 5: Commit**

```bash
cd ~/projects/agent-read
git add agent_read/player.py tests/test_player.py
git commit -m "feat: player runner foreground/background"
```

---

### Task 6: CLI (`read` + `stop`)

**Files:**
- Create: `agent_read/cli.py`
- Create: `tests/test_cli_contract.py`

- [ ] **Step 1: Write failing CLI contract tests**

```python
# tests/test_cli_contract.py
import json
from pathlib import Path
import agent_read.cli as cli


def test_error_no_source(capsys):
    code = cli.main([])
    assert code == 1
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "error"


def test_stop_noop(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENT_READ_CACHE", str(tmp_path))
    code = cli.main(["stop"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "ok"


def test_foreground_happy(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENT_READ_CACHE", str(tmp_path))

    def fake_synth(text, *, voice, speed, out_wav, home=None):
        Path(out_wav).write_bytes(b"RIFF")

    def fake_player(wav, *, title, background):
        assert background is False
        return "ok"

    monkeypatch.setattr(cli, "synthesize", fake_synth)
    monkeypatch.setattr(cli, "run_player", fake_player)
    monkeypatch.setattr(cli, "kokoro_ready", lambda home=None: True)

    code = cli.main(["--text", "hello world", "--title", "T"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "ok"
    assert out["mode"] == "foreground"
    assert out["chars"] == len("hello world")
    assert out["title"] == "T"


def test_stopped_exit(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENT_READ_CACHE", str(tmp_path))

    def fake_synth(text, *, voice, speed, out_wav, home=None):
        Path(out_wav).write_bytes(b"RIFF")

    monkeypatch.setattr(cli, "synthesize", fake_synth)
    monkeypatch.setattr(cli, "run_player", lambda *a, **k: "stopped")
    monkeypatch.setattr(cli, "kokoro_ready", lambda home=None: True)

    code = cli.main(["--text", "x"])
    assert code == 130
    assert json.loads(capsys.readouterr().out)["status"] == "stopped"
```

- [ ] **Step 2: Run — expect fail**

```bash
cd ~/projects/agent-read && .venv/bin/pytest tests/test_cli_contract.py -v
```

- [ ] **Step 3: Implement CLI**

```python
# agent_read/cli.py
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from agent_read.job import stop_background
from agent_read.kokoro import KokoroError, kokoro_ready, synthesize
from agent_read.player import PlayerError, run_player
from agent_read.result import exit_code, make_result
from agent_read.text_source import TextSourceError, load_text

_DEFAULT_VOICE = "am_michael"


def _voice_default() -> str:
    return os.environ.get("AGENT_READ_VOICE", _DEFAULT_VOICE)


def _emit(result: dict) -> int:
    print(json.dumps(result))
    return exit_code(result["status"])


def _cmd_stop() -> int:
    t0 = time.monotonic()
    status = stop_background()
    elapsed = int((time.monotonic() - t0) * 1000)
    if status == "ok":
        print("agent-read: nothing playing", file=sys.stderr)
    return _emit(
        make_result(
            status,
            mode="background",
            title=None,
            chars=0,
            voice=_voice_default(),
            elapsed_ms=elapsed,
        )
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "stop":
        return _cmd_stop()

    p = argparse.ArgumentParser(prog="agent-read")
    p.add_argument("--file", default=None)
    p.add_argument("--text", default=None)
    p.add_argument("--title", default=None)
    p.add_argument("--voice", default=None)
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--background", action="store_true")
    args = p.parse_args(argv)

    voice = args.voice or _voice_default()
    mode = "background" if args.background else "foreground"
    t0 = time.monotonic()

    def err(msg: str) -> int:
        print(f"agent-read: {msg}", file=sys.stderr)
        return _emit(
            make_result(
                "error",
                mode=mode,
                title=args.title,
                chars=0,
                voice=voice,
                elapsed_ms=int((time.monotonic() - t0) * 1000),
            )
        )

    stdin_data = None
    if args.file is None and args.text is None:
        if not sys.stdin.isatty():
            stdin_data = sys.stdin.read()
        else:
            stdin_data = None

    try:
        text = load_text(file=args.file, text=args.text, stdin_data=stdin_data)
    except (TextSourceError, OSError) as e:
        return err(str(e))

    if not kokoro_ready():
        return err(
            "Kokoro not ready; set KOKORO_HOME (need venv + onnx + voices)"
        )

    wav_path = Path(tempfile.mkstemp(prefix="agent-read-", suffix=".wav")[1])
    try:
        try:
            synthesize(text, voice=voice, speed=args.speed, out_wav=wav_path)
        except KokoroError as e:
            return err(str(e))

        try:
            status = run_player(
                wav_path, title=args.title, background=args.background
            )
        except PlayerError as e:
            return err(str(e))
        except KeyboardInterrupt:
            status = "stopped"

        if not args.background:
            try:
                wav_path.unlink()
            except OSError:
                pass

        elapsed = int((time.monotonic() - t0) * 1000)
        return _emit(
            make_result(
                status,
                mode=mode,
                title=args.title,
                chars=len(text),
                voice=voice,
                elapsed_ms=elapsed,
            )
        )
    except Exception as e:
        try:
            wav_path.unlink()
        except OSError:
            pass
        return err(str(e))


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run all tests — expect pass**

```bash
cd ~/projects/agent-read && .venv/bin/pytest -v
```

- [ ] **Step 5: Commit**

```bash
cd ~/projects/agent-read
git add agent_read/cli.py tests/test_cli_contract.py
git commit -m "feat: agent-read CLI with stop subcommand"
```

---

### Task 7: SwiftUI player (`agent-read-ui`)

**Files:**
- Create: `ui/Package.swift`
- Create: `ui/Sources/AgentReadUI/main.swift`
- Create: `scripts/build-ui.sh`

- [ ] **Step 1: Package.swift**

```swift
// ui/Package.swift
// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "AgentReadUI",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(
            name: "AgentReadUI",
            path: "Sources/AgentReadUI"
        )
    ]
)
```

- [ ] **Step 2: Implement `ui/Sources/AgentReadUI/main.swift` (full file)**

```swift
import AppKit
import AVFoundation
import Foundation
import SwiftUI

struct CLIArgs {
    let wavPath: String
    let statusPath: String
    let title: String
}

func parseArgs(_ args: [String]) -> CLIArgs? {
    var wav: String?
    var status: String?
    var title = "Reading"
    var i = 0
    while i < args.count {
        switch args[i] {
        case "--wav":
            i += 1
            guard i < args.count else { return nil }
            wav = args[i]
        case "--status":
            i += 1
            guard i < args.count else { return nil }
            status = args[i]
        case "--title":
            i += 1
            guard i < args.count else { return nil }
            title = args[i]
        default:
            break
        }
        i += 1
    }
    guard let wav, let status else { return nil }
    return CLIArgs(wavPath: wav, statusPath: status, title: title)
}

func writeStatus(_ path: String, status: String) {
    let obj: [String: String] = ["status": status]
    guard let data = try? JSONSerialization.data(withJSONObject: obj) else { return }
    try? data.write(to: URL(fileURLWithPath: path), options: .atomic)
}

func usageAndExit() -> Never {
    fputs("Usage: agent-read-ui --wav PATH --status PATH [--title STR]\n", stderr)
    exit(1)
}

final class PlayerModel: NSObject, ObservableObject, AVAudioPlayerDelegate {
    @Published var isPlaying = false
    let title: String
    let statusPath: String
    private var player: AVAudioPlayer?
    private var finished = false

    init(wavPath: String, title: String, statusPath: String) {
        self.title = title
        self.statusPath = statusPath
        super.init()
        let url = URL(fileURLWithPath: wavPath)
        do {
            player = try AVAudioPlayer(contentsOf: url)
        } catch {
            fputs("agent-read-ui: failed to load wav: \(error)\n", stderr)
            writeStatus(statusPath, status: "stopped")
            exit(1)
        }
        player?.delegate = self
        player?.prepareToPlay()
    }

    func start() {
        player?.play()
        isPlaying = true
    }

    func toggle() {
        guard let player else { return }
        if player.isPlaying {
            player.pause()
            isPlaying = false
        } else {
            player.play()
            isPlaying = true
        }
    }

    func stopUser() {
        guard !finished else { return }
        finished = true
        player?.stop()
        isPlaying = false
        writeStatus(statusPath, status: "stopped")
        DispatchQueue.main.async { NSApp.terminate(nil) }
    }

    func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        guard !finished else { return }
        finished = true
        isPlaying = false
        writeStatus(statusPath, status: "ok")
        DispatchQueue.main.async { NSApp.terminate(nil) }
    }
}

struct RootView: View {
    @ObservedObject var model: PlayerModel
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(model.title)
                .font(.headline)
                .lineLimit(2)
            HStack {
                Button(model.isPlaying ? "Pause" : "Play") { model.toggle() }
                Button("Stop") { model.stopUser() }
                    .keyboardShortcut(.cancelAction)
            }
        }
        .padding(16)
        .frame(minWidth: 280)
        .onExitCommand { model.stopUser() }
    }
}

final class KeyableWindow: NSWindow {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow?
    var model: PlayerModel?

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }
}

let cliArgs = Array(CommandLine.arguments.dropFirst())
guard let args = parseArgs(cliArgs) else {
    usageAndExit()
}

let app = NSApplication.shared
app.setActivationPolicy(.regular)
let delegate = AppDelegate()
app.delegate = delegate

let model = PlayerModel(
    wavPath: args.wavPath,
    title: args.title,
    statusPath: args.statusPath
)
delegate.model = model

signal(SIGTERM) { _ in
    DispatchQueue.main.async {
        (NSApp.delegate as? AppDelegate)?.model?.stopUser()
    }
}

let hosting = NSHostingController(rootView: RootView(model: model))
let window = KeyableWindow(
    contentRect: NSRect(x: 0, y: 0, width: 320, height: 120),
    styleMask: [.titled, .closable, .fullSizeContentView],
    backing: .buffered,
    defer: false
)
window.title = args.title
window.titleVisibility = .hidden
window.titlebarAppearsTransparent = true
window.isReleasedWhenClosed = false
window.contentViewController = hosting
window.isMovableByWindowBackground = true
window.level = .floating
window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
window.center()
delegate.window = window

NotificationCenter.default.addObserver(
    forName: NSWindow.willCloseNotification,
    object: window,
    queue: .main
) { _ in
    model.stopUser()
}

NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
    if event.keyCode == 53 {
        model.stopUser()
        return nil
    }
    return event
}

window.makeKeyAndOrderFront(nil)
app.activate(ignoringOtherApps: true)
model.start()
app.run()
```

- [ ] **Step 3: build-ui.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/ui"
swift build -c release
BIN="$(swift build -c release --show-bin-path)/AgentReadUI"
mkdir -p "$ROOT/bin"
cp -f "$BIN" "$ROOT/bin/agent-read-ui"
chmod +x "$ROOT/bin/agent-read-ui"
echo "built $ROOT/bin/agent-read-ui"
```

```bash
chmod +x ~/projects/agent-read/scripts/build-ui.sh
~/projects/agent-read/scripts/build-ui.sh
```

Expected: binary at `bin/agent-read-ui`.

- [ ] **Step 4: Manual smoke (pre-recorded WAV)**

```bash
# generate a tiny wav with afplay-able content OR reuse a kokoro wav
printf '%s' '{"status":"ok"}' > /dev/null
STATUS=$(mktemp)
# If you have any short wav:
# ~/projects/agent-read/bin/agent-read-ui --wav /path/to.wav --title Test --status "$STATUS"
# cat "$STATUS"  # ok or stopped after interacting
```

- [ ] **Step 5: Commit**

```bash
cd ~/projects/agent-read
git add ui scripts/build-ui.sh bin/agent-read-ui  # binary optional; prefer build script only in git
# Prefer NOT committing the binary — add bin/agent-read-ui to .gitignore if built locally
echo 'bin/agent-read-ui' >> .gitignore
git add ui scripts/build-ui.sh .gitignore
git commit -m "feat: SwiftUI AVFoundation player with play/pause/stop"
```

---

### Task 8: Skill in tjdsneto-setup

**Files:**
- Create: `/Users/tjdsneto/projects/tjdsneto-setup/ai/skills/shared/agent-read/SKILL.md`

- [ ] **Step 1: Write skill**

```markdown
---
name: agent-read
description: Use when the human should hear text aloud (summary, notes, PR body, file contents) via Kokoro. Runs the agent-read CLI and continues from the JSON result on stdout. Not for interrupts or choices — use agent-ping for those.
---

# agent-read — read aloud with Kokoro

CLI: `~/projects/agent-read/bin/agent-read` (build UI with `~/projects/agent-read/scripts/build-ui.sh` first).

Requires `$KOKORO_HOME` (default `~/.local/share/kokoro-onnx`) with venv + ONNX model + voices.

## When

- User asks to hear something / "read this to me"
- Long summary, notes, or PR body better as audio than scroll
- Hand a file path for the agent to speak

## How

1. Prepare text (summarize if helpful) **or** choose a file path.
2. Run (foreground waits until finished or Stop):

```bash
~/projects/agent-read/bin/agent-read --title "PR summary" --text "$TEXT"
# or
~/projects/agent-read/bin/agent-read --title "Notes" --file /path/to/notes.md
# or
printf '%s' "$TEXT" | ~/projects/agent-read/bin/agent-read --title "…"
```

Background (return immediately; human can keep working):

```bash
~/projects/agent-read/bin/agent-read --background --file /path/to/notes.md
~/projects/agent-read/bin/agent-read stop   # later
```

3. Parse **stdout** JSON: `status`, `mode`, `title`, `chars`, `voice`, `elapsed_ms`.
4. Branch on exit code: `0` ok, `130` stopped, `1` error.

Do not put product-specific flows in this skill. Use **agent-ping** for attention / choices / short answers.
```

- [ ] **Step 2: Install links**

```bash
cd ~/projects/tjdsneto-setup && ./install.sh
# or only ensure ai/skills/shared/agent-read is picked up by existing install_skills
ls -la ~/.claude/skills/agent-read ~/.cursor/skills-cursor/agent-read
```

- [ ] **Step 3: Commit in tjdsneto-setup**

```bash
cd ~/projects/tjdsneto-setup
git add ai/skills/shared/agent-read/SKILL.md
git commit -m "feat(agent-read): add shared Kokoro read-aloud skill"
```

---

### Task 9: README + end-to-end manual check

**Files:**
- Modify: `~/projects/agent-read/README.md`

- [ ] **Step 1: Expand README**

Document:
- Prerequisites: macOS, Python 3.11+, Swift toolchain, Kokoro at `$KOKORO_HOME`
- `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
- `./scripts/build-ui.sh`
- Env vars: `KOKORO_HOME`, `AGENT_READ_VOICE`, `AGENT_READ_UI`, `AGENT_READ_CACHE`
- Examples for `--text`, `--file`, stdin, `--background`, `stop`
- Exit codes and JSON shape
- Link to design spec: `tjdsneto-setup/docs/superpowers/specs/2026-09-24-agent-read-design.md`
- Skill path

- [ ] **Step 2: Manual checklist**

```bash
cd ~/projects/agent-read
.venv/bin/pytest -v
./scripts/build-ui.sh

# short foreground
~/projects/agent-read/bin/agent-read --title "Smoke" --text "Hello from agent read."

# pause/stop in UI manually

# background
~/projects/agent-read/bin/agent-read --background --text "Background smoke test."
~/projects/agent-read/bin/agent-read stop

# file
echo "File smoke." > /tmp/agent-read-file.txt
~/projects/agent-read/bin/agent-read --file /tmp/agent-read-file.txt --title "File"
```

- [ ] **Step 3: Commit**

```bash
cd ~/projects/agent-read
git add README.md
git commit -m "docs: README for agent-read install and contract"
```

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| stdin / `--file` / `--text` exactly one | 2, 6 |
| Blocking default + `--background` | 5, 6 |
| Play / pause / stop (AVFoundation) | 7 |
| New repo `agent-read` | 1 |
| Hard-fail Kokoro, no `say` | 3 |
| JSON + exit codes | 1, 6 |
| `agent-read stop` idempotent | 4, 6 |
| Skill in tjdsneto-setup | 8 |
| Temp WAV cleanup | 6 (fg); 4 (bg stop) |
| `$AGENT_READ_UI` / `$KOKORO_HOME` | 3, 5 |

## Out of scope (do not implement in this plan)

- Shared Kokoro package with agent-ping
- Chunked skip / chapters
- `--save` WAV library
- Multi-job queue

---
