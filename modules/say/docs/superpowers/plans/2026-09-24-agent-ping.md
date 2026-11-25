# agent-ping Implementation Plan

> **Superseded** by `2026-09-25-agent-say.md` / spec `2026-09-25-agent-say-design.md`.


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a blocking `agent-ping` CLI + SwiftUI modal + optional Kokoro speech + shared skill so any agent can interrupt the human with dynamic options/text and get a JSON answer back on stdout.

**Architecture:** Python CLI owns schema validation, wait/timeout/default policy, exit codes, and orchestration. A small SwiftUI helper (`agent-ping-ui`) shows the modal and writes a response JSON file. Optional speak invokes Kokoro ONNX from `$KOKORO_HOME` (same layout as `pr-tts-kokoro`: `~/.local/share/kokoro-onnx`) and plays the WAV; failures are stderr-only. Skill lives in `tjdsneto-setup` and is linked by `install.sh`.

**Tech Stack:** Python 3.11+ (stdlib + pytest), SwiftUI macOS app (swiftc / `swift package` or xcodebuild), `kokoro-onnx` + `soundfile` when speaking, `afplay` for playback.

**Spec:** `docs/superpowers/specs/2026-09-24-agent-ping-design.md`

---

## File Structure

**New project** `~/projects/agent-ping/` (own git repo):

| Path | Responsibility |
|------|----------------|
| `bin/agent-ping` | Executable entry → `python -m agent_ping.cli` |
| `agent_ping/__init__.py` | Package version |
| `agent_ping/models.py` | Pydantic (or dataclasses) request/response types |
| `agent_ping/validate.py` | `validate_request`, wait-flag resolution |
| `agent_ping/result.py` | Build response dict + exit code mapping |
| `agent_ping/ui_runner.py` | Protocol: launch Swift UI, wait for response file, timeout |
| `agent_ping/speak.py` | Best-effort Kokoro → WAV → `afplay` |
| `agent_ping/cli.py` | `main(argv) -> int` |
| `ui/Package.swift` + `ui/Sources/AgentPingUI/` | SwiftUI helper target `agent-ping-ui` |
| `tests/test_validate.py` | Schema + wait flags |
| `tests/test_result.py` | Exit codes / timeout+default |
| `tests/test_cli_contract.py` | End-to-end with mocked UI runner |
| `README.md` | Install, JSON contract, Kokoro, skill pointer |
| `requirements.txt` | `pydantic`, `pytest` (Kokoro stays in `$KOKORO_HOME/venv`) |

**In `tjdsneto-setup`:**

| Path | Responsibility |
|------|----------------|
| `ai/skills/shared/agent-ping/SKILL.md` | When/how to call; parse stdout |
| (optional) `bin/agent-ping` symlink docs in README only — PATH via project `bin/` or `install.sh` note |

**Public Python API (must stay stable across tasks):**

```python
# validate.py
class SpecError(ValueError): ...
def validate_request(raw: dict) -> dict: ...
def resolve_wait(argv_flags: dict) -> dict:  # {mode: wait|timeout, timeout_sec: int|None, default: str|None}

# result.py
def make_result(status: str, choice: str|None, text: str|None, elapsed_ms: int) -> dict: ...
def exit_code(status: str) -> int: ...

# ui_runner.py
def run_ui(request: dict, *, timeout_sec: float|None) -> dict: ...  # returns response fields or raises TimeoutError

# speak.py
def speak_best_effort(title: str, body: str) -> None: ...  # never raises to caller for Kokoro failures
```

**UI file protocol:**

```
agent-ping writes  /tmp/agent-ping-<pid>/request.json
agent-ping launches agent-ping-ui --request <path> --response <path>
agent-ping-ui writes response.json then exits 0
# response.json: {"status":"ok"|"cancelled","choice":"..."|null,"text":"..."|null}
```

---

### Task 1: Scaffold project + models

**Files:**
- Create: `/Users/tjdsneto/projects/agent-ping/` (git init)
- Create: `agent_ping/__init__.py`, `models.py`, `requirements.txt`, `README.md` (stub), `bin/agent-ping`
- Create: `tests/test_models_smoke.py`

- [ ] **Step 1: Create dirs and venv**

```bash
mkdir -p ~/projects/agent-ping/{agent_ping,tests,ui,bin}
cd ~/projects/agent-ping
git init
python3 -m venv .venv
.venv/bin/pip install pydantic pytest
printf 'pydantic>=2\npytest>=8\n' > requirements.txt
echo -e '.venv/\n__pycache__/\n.pytest_cache/\n*.pyc\n/dist/\nui/.build/' > .gitignore
```

- [ ] **Step 2: Write failing smoke test**

```python
# tests/test_models_smoke.py
from agent_ping.models import PingRequest

def test_minimal_title_ok():
    r = PingRequest.model_validate({"title": "Hi"})
    assert r.title == "Hi"
    assert r.speak is False
```

- [ ] **Step 3: Run — expect fail (no module)**

```bash
cd ~/projects/agent-ping && .venv/bin/pytest tests/test_models_smoke.py -v
```

Expected: `ModuleNotFoundError` or import error.

- [ ] **Step 4: Implement models**

```python
# agent_ping/models.py
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field

class Option(BaseModel):
    id: str
    label: str

class InputSpec(BaseModel):
    enabled: bool = True
    placeholder: str = ""
    required: bool = False

class PingRequest(BaseModel):
    title: str = Field(min_length=1)
    body: str = ""
    options: list[Option] = Field(default_factory=list)
    input: InputSpec | None = None
    speak: bool = False
    level: Literal["info", "warn", "critical"] = "info"

class PingResponse(BaseModel):
    status: Literal["ok", "timeout", "cancelled", "error"]
    choice: str | None = None
    text: str | None = None
    elapsed_ms: int = 0
```

```python
# agent_ping/__init__.py
__version__ = "0.1.0"
```

```bash
# bin/agent-ping
#!/usr/bin/env bash
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/.venv/bin/python" -m agent_ping.cli "$@"
```

`chmod +x bin/agent-ping`

- [ ] **Step 5: pytest passes**

```bash
.venv/bin/pytest tests/test_models_smoke.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "chore: scaffold agent-ping package + models"
```

---

### Task 2: validate_request + resolve_wait (TDD)

**Files:**
- Create: `agent_ping/validate.py`
- Create: `tests/test_validate.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_validate.py
import pytest
from agent_ping.validate import SpecError, validate_request, resolve_wait

def test_requires_title():
    with pytest.raises(SpecError):
        validate_request({})

def test_implicit_ok_when_no_options_no_input():
    r = validate_request({"title": "Ping"})
    assert r["options"] == [{"id": "ok", "label": "OK"}]

def test_unique_option_ids():
    with pytest.raises(SpecError):
        validate_request({"title": "t", "options": [{"id": "a", "label": "A"}, {"id": "a", "label": "B"}]})

def test_default_requires_matching_option():
    with pytest.raises(SpecError):
        resolve_wait({"wait": False, "timeout": 10, "default": "nope"}, options=[{"id": "ok"}])

def test_wait_and_timeout_mutex():
    with pytest.raises(SpecError):
        resolve_wait({"wait": True, "timeout": 5, "default": None}, options=[])

def test_default_timeout_180():
    w = resolve_wait({"wait": False, "timeout": None, "default": None}, options=[])
    assert w == {"mode": "timeout", "timeout_sec": 180, "default": None}
```

- [ ] **Step 2: Run — fail**

```bash
.venv/bin/pytest tests/test_validate.py -v
```

- [ ] **Step 3: Implement `validate.py`**

```python
# agent_ping/validate.py
from __future__ import annotations
from agent_ping.models import PingRequest

class SpecError(ValueError):
    pass

def validate_request(raw: dict) -> dict:
    try:
        req = PingRequest.model_validate(raw)
    except Exception as e:
        raise SpecError(str(e)) from e
    data = req.model_dump()
    if not data["options"] and not (data.get("input") and data["input"].get("enabled")):
        data["options"] = [{"id": "ok", "label": "OK"}]
    ids = [o["id"] for o in data["options"]]
    if len(ids) != len(set(ids)):
        raise SpecError("option ids must be unique")
    return data

def resolve_wait(flags: dict, *, options: list) -> dict:
    wait = bool(flags.get("wait"))
    timeout = flags.get("timeout")  # None = use default 180 unless wait
    default = flags.get("default")
    if wait and timeout is not None:
        raise SpecError("--wait and --timeout are mutually exclusive")
    if default is not None:
        ids = {o["id"] if isinstance(o, dict) else o.id for o in options}
        if default not in ids:
            raise SpecError(f"--default id not in options: {default}")
        if not options:
            raise SpecError("--default requires options")
    if wait:
        return {"mode": "wait", "timeout_sec": None, "default": default}
    sec = 180 if timeout is None else int(timeout)
    if sec < 1:
        raise SpecError("--timeout must be >= 1")
    return {"mode": "timeout", "timeout_sec": sec, "default": default}
```

- [ ] **Step 4: pytest PASS**

```bash
.venv/bin/pytest tests/test_validate.py -v
```

- [ ] **Step 5: Commit**

```bash
git add agent_ping/validate.py tests/test_validate.py
git commit -m "feat: validate ping request and wait flags"
```

---

### Task 3: result helpers + CLI with mocked UI

**Files:**
- Create: `agent_ping/result.py`, `agent_ping/cli.py`, `agent_ping/ui_runner.py` (stub raising `NotImplementedError`)
- Create: `tests/test_result.py`, `tests/test_cli_contract.py`

- [ ] **Step 1: Tests for result/exit codes**

```python
# tests/test_result.py
from agent_ping.result import exit_code, make_result

def test_exit_codes():
    assert exit_code("ok") == 0
    assert exit_code("timeout") == 2
    assert exit_code("cancelled") == 130
    assert exit_code("error") == 1

def test_make_result_shape():
    r = make_result("ok", "done", None, 12)
    assert r == {"status": "ok", "choice": "done", "text": None, "elapsed_ms": 12}
```

- [ ] **Step 2: Implement result.py**

```python
# agent_ping/result.py
def make_result(status, choice, text, elapsed_ms):
    return {"status": status, "choice": choice, "text": text, "elapsed_ms": int(elapsed_ms)}

def exit_code(status: str) -> int:
    return {"ok": 0, "timeout": 2, "cancelled": 130, "error": 1}.get(status, 1)
```

- [ ] **Step 3: CLI contract test with monkeypatched UI**

```python
# tests/test_cli_contract.py
import json, io
from agent_ping import cli

def test_ok_choice(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_ui", lambda req, timeout_sec=None: {"status": "ok", "choice": "done", "text": None})
    code = cli.main(["--file", "-"], stdin_text=json.dumps({"title": "T", "options": [{"id": "done", "label": "Done"}]}))
    # simpler: pass path
```

Prefer file-based:

```python
def test_timeout_with_default(monkeypatch, tmp_path, capsys):
    spec = tmp_path / "s.json"
    spec.write_text(json.dumps({
        "title": "T",
        "options": [{"id": "done", "label": "Done"}, {"id": "cancel", "label": "Cancel"}],
    }))
    def boom(req, timeout_sec=None):
        raise TimeoutError()
    monkeypatch.setattr("agent_ping.cli.run_ui", boom)
    code = cli.main(["--file", str(spec), "--timeout", "1", "--default", "cancel"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["status"] == "ok" and out["choice"] == "cancel"

def test_timeout_without_default(monkeypatch, tmp_path, capsys):
    spec = tmp_path / "s.json"
    spec.write_text(json.dumps({"title": "T", "options": [{"id": "ok", "label": "OK"}]}))
    monkeypatch.setattr("agent_ping.cli.run_ui", lambda *a, **k: (_ for _ in ()).throw(TimeoutError()))
    code = cli.main(["--file", str(spec), "--timeout", "1"])
    out = json.loads(capsys.readouterr().out)
    assert code == 2 and out["status"] == "timeout"
```

- [ ] **Step 4: Implement cli.py + stub ui_runner**

```python
# agent_ping/ui_runner.py
def run_ui(request: dict, *, timeout_sec: float | None = None) -> dict:
    raise NotImplementedError("Swift UI not wired yet")
```

```python
# agent_ping/cli.py
from __future__ import annotations
import argparse, json, sys, time
from agent_ping.validate import SpecError, validate_request, resolve_wait
from agent_ping.result import make_result, exit_code
from agent_ping.ui_runner import run_ui
from agent_ping.speak import speak_best_effort

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="agent-ping")
    p.add_argument("--file", help="request JSON path (default: stdin)")
    p.add_argument("--wait", action="store_true")
    p.add_argument("--timeout", type=int, default=None)
    p.add_argument("--default", default=None)
    p.add_argument("--speak", action="store_true")
    args = p.parse_args(argv)
    try:
        raw = open(args.file).read() if args.file else sys.stdin.read()
        req = validate_request(json.loads(raw))
        if args.speak:
            req["speak"] = True
        wait = resolve_wait(
            {"wait": args.wait, "timeout": args.timeout, "default": args.default},
            options=req["options"],
        )
    except (SpecError, json.JSONDecodeError) as e:
        print(make_result("error", None, None, 0) | {}, file=sys.stderr)  # fix: print error result on stdout per spec
        err = make_result("error", None, None, 0)
        print(json.dumps(err))
        print(f"agent-ping: {e}", file=sys.stderr)
        return 1

    if req.get("speak"):
        speak_best_effort(req["title"], req.get("body") or "")

    t0 = time.monotonic()
    try:
        ui = run_ui(req, timeout_sec=wait["timeout_sec"])
        status = ui.get("status", "ok")
        choice = ui.get("choice")
        text = ui.get("text")
        if status not in ("ok", "cancelled", "error"):
            status = "ok"
    except TimeoutError:
        if wait.get("default"):
            status, choice, text = "ok", wait["default"], None
        else:
            status, choice, text = "timeout", None, None
    except Exception as e:
        print(f"agent-ping: {e}", file=sys.stderr)
        status, choice, text = "error", None, None

    elapsed = int((time.monotonic() - t0) * 1000)
    result = make_result(status, choice, text, elapsed)
    print(json.dumps(result))
    return exit_code(status)

if __name__ == "__main__":
    raise SystemExit(main())
```

Also add stub:

```python
# agent_ping/speak.py
def speak_best_effort(title: str, body: str) -> None:
    return
```

Fix error path: on SpecError, stdout still gets `{"status":"error",...}` then exit 1 (as above).

- [ ] **Step 5: pytest PASS for result + cli_contract**

- [ ] **Step 6: Commit**

```bash
git commit -am "feat: CLI contract with timeout/default and mocked UI"
```

---

### Task 4: SwiftUI `agent-ping-ui` helper

**Files:**
- Create: `ui/Package.swift`
- Create: `ui/Sources/AgentPingUI/main.swift` (or App + views)
- Build: `.build/release/agent-ping-ui` (or `ui/.build/...`)

- [ ] **Step 1: Scaffold Swift package executable**

```bash
cd ~/projects/agent-ping/ui
swift package init --type executable --name AgentPingUI
# rename product to agent-ping-ui in Package.swift
```

`Package.swift` product name: `agent-ping-ui`, platforms: `.macOS(.v14)`.

- [ ] **Step 2: Implement CLI args + JSON I/O**

Parse `--request PATH --response PATH`. Decode:

```swift
struct Option: Codable { var id: String; var label: String }
struct InputSpec: Codable { var enabled: Bool; var placeholder: String?; var required: Bool? }
struct Request: Codable {
  var title: String; var body: String?; var options: [Option]
  var input: InputSpec?; var level: String?
}
struct Response: Codable {
  var status: String; var choice: String?; var text: String?
}
```

- [ ] **Step 3: SwiftUI window**

- `Window` / `NSPanel` floating, `.floating` level, activate on `critical` / always bring forward.
- Show title, body, ForEach options as buttons.
- Optional `TextField` when `input.enabled`.
- If `input.required == true`, disable option buttons while text trimmed is empty.
- Esc / close → write `{status:cancelled}` and exit.
- Option click → write `{status:ok, choice:id, text:fieldOrNull}` and exit.
- Play `NSSound(named: "Glass")` or `NSSound.beep()` on appear.

- [ ] **Step 4: Build release binary**

```bash
cd ~/projects/agent-ping/ui
swift build -c release --product agent-ping-ui
# copy or symlink to ~/projects/agent-ping/bin/agent-ping-ui
cp .build/release/agent-ping-ui ../bin/agent-ping-ui
```

- [ ] **Step 5: Manual smoke (no Python yet)**

```bash
mkdir -p /tmp/ap && cat > /tmp/ap/request.json <<'EOF'
{"title":"Test","body":"Pick one","options":[{"id":"a","label":"A"},{"id":"b","label":"B"}],"level":"info"}
EOF
~/projects/agent-ping/bin/agent-ping-ui --request /tmp/ap/request.json --response /tmp/ap/response.json
cat /tmp/ap/response.json
```

Expected: modal appears; after click, JSON on disk.

- [ ] **Step 6: Commit**

```bash
git add ui bin/agent-ping-ui
git commit -m "feat: SwiftUI agent-ping-ui modal helper"
```

---

### Task 5: Wire `ui_runner.py` to Swift helper

**Files:**
- Modify: `agent_ping/ui_runner.py`
- Modify: `tests/test_cli_contract.py` (keep mocks; add optional integration mark)

- [ ] **Step 1: Implement runner**

```python
# agent_ping/ui_runner.py
from __future__ import annotations
import json, os, subprocess, tempfile, time
from pathlib import Path

def _ui_bin() -> Path:
    env = os.environ.get("AGENT_PING_UI")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[1] / "bin" / "agent-ping-ui"

def run_ui(request: dict, *, timeout_sec: float | None = None) -> dict:
    bin_path = _ui_bin()
    if not bin_path.is_file():
        raise RuntimeError(f"agent-ping-ui not found at {bin_path}; build ui/ first")
    with tempfile.TemporaryDirectory(prefix="agent-ping-") as td:
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
                raise RuntimeError(f"agent-ping-ui exited {proc.returncode} without response")
            if deadline is not None and time.monotonic() > deadline:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise TimeoutError()
            time.sleep(0.05)
```

- [ ] **Step 2: Manual E2E**

```bash
cd ~/projects/agent-ping
printf '%s' '{"title":"Hello","body":"From CLI","options":[{"id":"ok","label":"OK"}]}' \
  | ./bin/agent-ping --timeout 60
```

Expected: modal; stdout JSON `status=ok`; exit 0.

- [ ] **Step 3: Commit**

```bash
git commit -am "feat: wire CLI to agent-ping-ui with timeout kill"
```

---

### Task 6: Kokoro speak (best-effort)

**Files:**
- Modify: `agent_ping/speak.py`
- Create: `tests/test_speak.py` (mock subprocess / missing home)

Reuse layout from `pr-tts-kokoro`:

- `$KOKORO_HOME` default `~/.local/share/kokoro-onnx`
- `venv/bin/python`, `kokoro-v1.0.onnx`, `voices-v1.0.bin`
- Voice default `am_michael` (or `AGENT_PING_VOICE`)

- [ ] **Step 1: Test that missing Kokoro does not raise**

```python
def test_speak_missing_home_ok(monkeypatch, tmp_path):
    monkeypatch.setenv("KOKORO_HOME", str(tmp_path / "missing"))
    from agent_ping.speak import speak_best_effort
    speak_best_effort("Hi", "There")  # must not raise
```

- [ ] **Step 2: Implement speak.py**

```python
def speak_best_effort(title: str, body: str) -> None:
    text = f"{title}. {body}".strip()
    if not text:
        return
    home = Path(os.environ.get("KOKORO_HOME", Path.home() / ".local/share/kokoro-onnx"))
    py = home / "venv/bin/python"
    model = home / "kokoro-v1.0.onnx"
    voices = home / "voices-v1.0.bin"
    try:
        if not (py.is_file() and model.is_file() and voices.is_file()):
            # fallback: macOS say (still best-effort)
            subprocess.run(["say", text], check=False, timeout=60)
            return
        with tempfile.TemporaryDirectory() as td:
            wav = Path(td) / "out.wav"
            txt = Path(td) / "in.txt"
            txt.write_text(text)
            # inline python same as pr-tts-kokoro OR subprocess to a small script
            ...
            subprocess.run(["afplay", str(wav)], check=False, timeout=120)
    except Exception as e:
        print(f"agent-ping: speak failed ({e}); continuing", file=sys.stderr)
```

Prefer calling the same env vars as `pr-tts-kokoro` for the ONNX create step (copy the embedded Python snippet).

- [ ] **Step 3: Manual with `--speak`** (if Kokoro installed)

```bash
printf '%s' '{"title":"Attention","body":"Please confirm.","options":[{"id":"ok","label":"OK"}],"speak":true}' \
  | ./bin/agent-ping --timeout 60
```

- [ ] **Step 4: Commit**

```bash
git commit -am "feat: optional Kokoro/say speech best-effort"
```

---

### Task 7: Skill + install link in tjdsneto-setup

**Files:**
- Create: `/Users/tjdsneto/projects/tjdsneto-setup/ai/skills/shared/agent-ping/SKILL.md`
- Run: `./install.sh` (links Claude + Cursor)

- [ ] **Step 1: Write SKILL.md**

```markdown
---
name: agent-ping
description: Use when an agent needs the human's attention, a choice among dynamic options, or a short free-text answer. Runs the agent-ping CLI (blocking modal, optional speech) and continues from the JSON result on stdout.
---

# agent-ping — interrupt the human

CLI: `~/projects/agent-ping/bin/agent-ping` (or on PATH).

## When

- CAPTCHA / external UI handoff ("tell me when done")
- Confirm before irreversible action
- Pick among options the agent cannot decide alone
- Short free-text answer

## How

1. Build JSON per design spec (`title`, `body`, `options[]`, optional `input`, `speak`, `level`).
2. Run blocking:

```bash
printf '%s' "$JSON" | ~/projects/agent-ping/bin/agent-ping --timeout 180
# or --wait / --default <id> / --speak
```

3. Parse **stdout** JSON: `status`, `choice`, `text`, `elapsed_ms`.
4. Branch on exit code: `0` ok, `2` timeout, `130` cancelled, `1` error.

Do not put product-specific flows in this skill — only the interrupt protocol.
```

- [ ] **Step 2: install.sh**

```bash
cd ~/projects/tjdsneto-setup && ./install.sh 2>&1 | grep -i agent-ping
```

Expected: Linked agent-ping (claude) / (cursor)

- [ ] **Step 3: Commit in tjdsneto-setup**

```bash
git add ai/skills/shared/agent-ping/SKILL.md
git commit -m "feat(agent-ping): add shared skill for human interrupt CLI"
```

- [ ] **Step 4: Point agent-ping README at skill path**

Commit in agent-ping repo.

---

### Task 8: README polish + checklist

**Files:**
- Modify: `~/projects/agent-ping/README.md`

Document: build UI, venv, env vars (`AGENT_PING_UI`, `KOKORO_HOME`, `AGENT_PING_VOICE`), JSON examples, exit codes, phase-2 out of scope, link to design spec in tjdsneto-setup.

Manual checklist (tick in PR/commit message):

- [ ] options-only ask
- [ ] input.required
- [ ] `--timeout` → status timeout
- [ ] `--timeout --default`
- [ ] `--wait` (short manual)
- [ ] Esc → cancelled
- [ ] `--speak` with and without Kokoro
- [ ] `level=critical` brings app forward

- [ ] **Commit** both repos as needed.

---

## Spec coverage (self-review)

| Spec item | Task |
|-----------|------|
| Dynamic options + free text | 1–5 |
| stdout JSON + exit codes | 3 |
| `--wait` / `--timeout` / `--default` | 2–3, 5 |
| SwiftUI modal + focus + sound | 4 |
| Speak opt-in best-effort Kokoro | 6 |
| Skill domain-agnostic | 7 |
| Phase 2 channel | Explicitly out of plan (README only) |
| Tauri fallback | Not in v1 plan; README note only |

## Placeholder scan

None intentional — Swift UI view code is described structurally in Task 4; implementer writes full SwiftUI in that task (do not leave TODO stubs in committed UI).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-24-agent-ping.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — this session with executing-plans + checkpoints  

Which approach?
