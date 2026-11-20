# agent-registry hooks (Claude + Cursor) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make agent-registry **liveness** (register / throttled heartbeat / unregister) automatic via Claude Code and Cursor hooks, while agents keep owning semantic `update` + list-before-claim.

**Architecture:** Add three host-agnostic CLI verbs (`ensure`, `heartbeat`, `end`) that store the private `registry_id` in a sidecar keyed by `(agent_type, session_id)`. Thin host wrappers map hook stdin → those verbs. Fail open (exit 0 on errors) so a broken registry never blocks the agent.

**Tech Stack:** Existing `agent-registry` Python CLI + pytest; shell wrappers; Claude `~/.claude/settings.json` hooks; Cursor user hooks `~/.cursor/hooks.json`.

**Spec baseline:** `docs/superpowers/specs/2026-09-24-agent-registry-design.md`  
**Relates:** this plan amends the integration model (hooks own liveness; skill owns semantics). Codex deferred.

**Locked decisions:**

| Topic | Decision |
|-------|----------|
| Split | Hooks: ensure / heartbeat / end. Skill: update + list-before-claim. |
| Sidecar | `~/.local/share/agent-registry/by-session/<agent_type>/<session_id>.json` holding `{registry_id, last_heartbeat_at}` |
| Heartbeat min interval | 1200s (20m); env `AGENT_REGISTRY_HEARTBEAT_SECONDS` |
| Fail mode | Fail open: wrappers always exit 0; log to stderr only |
| Claude events | `SessionStart` → ensure; `Stop` → heartbeat; `SessionEnd` → end |
| Cursor events | `sessionStart` → ensure; `stop` → heartbeat; `sessionEnd` → end |
| Subagents (v1) | Cursor `subagentStart`/`subagentStop` only; Claude subagents deferred |
| SessionStart context | Inject one-line “registered” + optional truncated `list` (active only, max ~20 lines) |
| Install | Claude via `ai/claude/scripts/install` HOOKS_JSON; Cursor via new `ai/cursor/hooks/` + `install.sh` merge |
| Non-goals v1 | Codex hooks; semantic `update` from hooks; agent-ping; auto-prune |

---

## File Structure

**In `~/projects/agent-registry/`:**

| Path | Responsibility |
|------|----------------|
| `agent_registry/constants.py` | Add `HEARTBEAT_SECONDS = 1200`, sidecar helpers path constants |
| `agent_registry/session_state.py` | Sidecar read/write/delete (atomic), path resolve |
| `agent_registry/lifecycle.py` | `ensure`, `heartbeat`, `end` ops |
| `agent_registry/cli.py` | Subcommands `ensure` / `heartbeat` / `end` |
| `tests/test_session_state.py` | Sidecar path + roundtrip |
| `tests/test_lifecycle.py` | ensure idempotent, heartbeat throttle, end cleanup |
| `tests/test_cli_lifecycle.py` | CLI wiring |
| `README.md` | Document lifecycle verbs + hook model |

**In `tjdsneto-setup`:**

| Path | Responsibility |
|------|----------------|
| `ai/claude/scripts/agent-registry-hook` | Read stdin JSON → `ensure`/`heartbeat`/`end` for `--event` |
| `ai/claude/hooks/hooks.json` | Align with install (SessionStart / Stop / SessionEnd) |
| `ai/claude/scripts/install` | Wire registry hook into HOOKS_JSON; keep existing Stop hooks |
| `ai/cursor/hooks/hooks.json` | User-hook template |
| `ai/cursor/hooks/agent-registry.sh` | Cursor stdin → lifecycle verbs |
| `install.sh` | Install/merge Cursor user hooks |
| `ai/skills/shared/agent-registry/SKILL.md` | Hooks own ping; agents still update/list |
| `ai/instructions/claude/CLAUDE.md` | Shorten presence rule |
| `ai/instructions/cursor/user-rules.md` | Same |
| `docs/superpowers/specs/2026-09-24-agent-registry-design.md` | § amendment: hooks for liveness |

---

### Task 1: Sidecar session state

**Files:**
- Create: `~/projects/agent-registry/agent_registry/session_state.py`
- Modify: `~/projects/agent-registry/agent_registry/constants.py`
- Test: `~/projects/agent-registry/tests/test_session_state.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_session_state.py
import json
from pathlib import Path

from agent_registry import session_state


def test_sidecar_path_under_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_REGISTRY_PATH", str(tmp_path / "registry.json"))
    p = session_state.sidecar_path("claude", "sess-1")
    assert p == tmp_path / "by-session" / "claude" / "sess-1.json"


def test_write_read_delete_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_REGISTRY_PATH", str(tmp_path / "registry.json"))
    session_state.write_state("cursor", "abc", registry_id="rid-1", last_heartbeat_at="2026-09-25T12:00:00+00:00")
    st = session_state.read_state("cursor", "abc")
    assert st == {"registry_id": "rid-1", "last_heartbeat_at": "2026-09-25T12:00:00+00:00"}
    session_state.delete_state("cursor", "abc")
    assert session_state.read_state("cursor", "abc") is None
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd ~/projects/agent-registry && .venv/bin/pytest tests/test_session_state.py -v
```

Expected: import error / missing module.

- [ ] **Step 3: Implement**

```python
# agent_registry/constants.py — append:
HEARTBEAT_SECONDS = 1200  # 20 minutes; override via AGENT_REGISTRY_HEARTBEAT_SECONDS
```

```python
# agent_registry/session_state.py
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from agent_registry.store import registry_path


def data_dir() -> Path:
    return registry_path().parent


def sidecar_path(agent_type: str, session_id: str) -> Path:
    safe_type = agent_type.strip().replace("/", "_")
    safe_sid = session_id.strip().replace("/", "_")
    return data_dir() / "by-session" / safe_type / f"{safe_sid}.json"


def read_state(agent_type: str, session_id: str) -> dict | None:
    path = sidecar_path(agent_type, session_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def write_state(
    agent_type: str,
    session_id: str,
    *,
    registry_id: str,
    last_heartbeat_at: str,
) -> None:
    path = sidecar_path(agent_type, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"registry_id": registry_id, "last_heartbeat_at": last_heartbeat_at}
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def delete_state(agent_type: str, session_id: str) -> None:
    path = sidecar_path(agent_type, session_id)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd ~/projects/agent-registry && .venv/bin/pytest tests/test_session_state.py -v
```

- [ ] **Step 5: Commit (agent-registry repo)**

```bash
cd ~/projects/agent-registry
git add agent_registry/constants.py agent_registry/session_state.py tests/test_session_state.py
git commit -m "$(cat <<'EOF'
feat: add by-session sidecar for private registry_id

EOF
)"
```

---

### Task 2: lifecycle ensure / heartbeat / end

**Files:**
- Create: `~/projects/agent-registry/agent_registry/lifecycle.py`
- Test: `~/projects/agent-registry/tests/test_lifecycle.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_lifecycle.py
from datetime import datetime, timedelta, timezone

from agent_registry import lifecycle, ops, session_state
from agent_registry.models import now_iso


def test_ensure_registers_and_writes_sidecar(tmp_registry):
    out = lifecycle.ensure("claude", "s1", str(tmp_registry.parent / "proj"))
    assert out["created"] is True
    assert out["session"]["session_id"] == "s1"
    st = session_state.read_state("claude", "s1")
    assert st["registry_id"] == out["session"]["registry_id"]


def test_ensure_idempotent_same_session(tmp_registry):
    a = lifecycle.ensure("claude", "s1", "/a")
    b = lifecycle.ensure("claude", "s1", "/a")
    assert a["session"]["registry_id"] == b["session"]["registry_id"]
    assert b["created"] is False


def test_ensure_replace_on_directory_change_uses_replace(tmp_registry):
    lifecycle.ensure("claude", "s1", "/old")
    out = lifecycle.ensure("claude", "s1", "/new", replace=True)
    assert out["session"]["directory"] == "/new"


def test_heartbeat_throttles(tmp_registry, monkeypatch):
    monkeypatch.setenv("AGENT_REGISTRY_HEARTBEAT_SECONDS", "3600")
    e = lifecycle.ensure("cursor", "c1", "/p")
    rid = e["session"]["registry_id"]
    # Force last_heartbeat_at to now
    session_state.write_state("cursor", "c1", registry_id=rid, last_heartbeat_at=now_iso())
    h1 = lifecycle.heartbeat("cursor", "c1")
    assert h1["skipped"] is True
    # Age the sidecar
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    session_state.write_state("cursor", "c1", registry_id=rid, last_heartbeat_at=old)
    h2 = lifecycle.heartbeat("cursor", "c1")
    assert h2["skipped"] is False
    assert h2["session"]["registry_id"] == rid


def test_heartbeat_ensure_if_missing_sidecar(tmp_registry):
    # No prior ensure: heartbeat should no-op skipped with reason missing
    h = lifecycle.heartbeat("claude", "missing")
    assert h["skipped"] is True
    assert h.get("reason") == "no_sidecar"


def test_end_unregisters_and_deletes_sidecar(tmp_registry):
    e = lifecycle.ensure("claude", "s1", "/p")
    lifecycle.end("claude", "s1")
    assert session_state.read_state("claude", "s1") is None
    assert ops.list_split()["active"] == [] and ops.list_split()["stale"] == []
```

Note: if `list_split` is not the public name, use whatever `ops` already exports for list (check `ops.py`); adapt the assertion to call the existing list helper.

- [ ] **Step 2: Run — expect FAIL**

```bash
cd ~/projects/agent-registry && .venv/bin/pytest tests/test_lifecycle.py -v
```

- [ ] **Step 3: Implement `lifecycle.py`**

```python
# agent_registry/lifecycle.py
from __future__ import annotations

import os
from datetime import datetime, timezone

from agent_registry.constants import HEARTBEAT_SECONDS
from agent_registry import ops, session_state
from agent_registry.models import now_iso


def _heartbeat_seconds() -> int:
    raw = os.environ.get("AGENT_REGISTRY_HEARTBEAT_SECONDS")
    if raw:
        try:
            return max(60, int(raw))
        except ValueError:
            pass
    return HEARTBEAT_SECONDS


def ensure(
    agent_type: str,
    session_id: str,
    directory: str,
    *,
    parent_session: str | None = None,
    replace: bool = True,
) -> dict:
    """Register if needed; always refresh sidecar. Default replace=True for resume/crash."""
    existing = session_state.read_state(agent_type, session_id)
    if existing and not replace:
        try:
            sess = ops.ping(existing["registry_id"])
            ts = now_iso()
            session_state.write_state(
                agent_type, session_id, registry_id=sess.registry_id, last_heartbeat_at=ts
            )
            return {"created": False, "session": sess.to_dict()}
        except Exception:
            pass  # fall through to register

    sess = ops.register(
        agent_type=agent_type,
        session_id=session_id,
        directory=directory,
        parent_session_id=parent_session,
        replace=True,
    )
    ts = now_iso()
    session_state.write_state(
        agent_type, session_id, registry_id=sess.registry_id, last_heartbeat_at=ts
    )
    created = existing is None
    return {"created": created, "session": sess.to_dict()}


def heartbeat(agent_type: str, session_id: str) -> dict:
    st = session_state.read_state(agent_type, session_id)
    if not st:
        return {"skipped": True, "reason": "no_sidecar"}
    last = st.get("last_heartbeat_at")
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
            age = (datetime.now(timezone.utc) - last_dt).total_seconds()
            if age < _heartbeat_seconds():
                return {"skipped": True, "reason": "throttled", "age_seconds": age}
        except ValueError:
            pass
    sess = ops.ping(st["registry_id"])
    ts = now_iso()
    session_state.write_state(
        agent_type, session_id, registry_id=sess.registry_id, last_heartbeat_at=ts
    )
    return {"skipped": False, "session": sess.to_dict()}


def end(agent_type: str, session_id: str) -> dict:
    st = session_state.read_state(agent_type, session_id)
    if not st:
        return {"ok": True, "reason": "no_sidecar"}
    try:
        ops.unregister(st["registry_id"])
    except Exception:
        pass  # still drop sidecar
    session_state.delete_state(agent_type, session_id)
    return {"ok": True}
```

Adapt `ops.register(...)` kwarg names to match existing `ops.py` (`replace`, `parent_session_id`, etc.).

- [ ] **Step 4: Run — expect PASS**

```bash
cd ~/projects/agent-registry && .venv/bin/pytest tests/test_lifecycle.py -v
```

- [ ] **Step 5: Commit**

```bash
cd ~/projects/agent-registry
git add agent_registry/lifecycle.py tests/test_lifecycle.py
git commit -m "$(cat <<'EOF'
feat: ensure/heartbeat/end lifecycle over sidecar

EOF
)"
```

---

### Task 3: CLI subcommands

**Files:**
- Modify: `~/projects/agent-registry/agent_registry/cli.py`
- Test: `~/projects/agent-registry/tests/test_cli_lifecycle.py`

- [ ] **Step 1: Failing CLI tests**

```python
# tests/test_cli_lifecycle.py
import json
from agent_registry.cli import main


def test_cli_ensure_heartbeat_end(tmp_registry, capsys):
    assert main([
        "ensure", "--type", "claude", "--session-id", "s1", "--directory", "/p"
    ]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "registry_id" in out["session"]

    assert main(["heartbeat", "--type", "claude", "--session-id", "s1"]) == 0
    hb = json.loads(capsys.readouterr().out)
    assert "skipped" in hb

    assert main(["end", "--type", "claude", "--session-id", "s1"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
```

- [ ] **Step 2: Run — expect FAIL** (unknown subcommand)

- [ ] **Step 3: Wire CLI**

Add parsers:

```python
p_ens = sub.add_parser("ensure")
p_ens.add_argument("--type", required=True, dest="agent_type")
p_ens.add_argument("--session-id", required=True)
p_ens.add_argument("--directory", required=True)
p_ens.add_argument("--parent-session", default=None)
p_ens.add_argument("--no-replace", action="store_true")

p_hb = sub.add_parser("heartbeat")
p_hb.add_argument("--type", required=True, dest="agent_type")
p_hb.add_argument("--session-id", required=True)

p_end = sub.add_parser("end")
p_end.add_argument("--type", required=True, dest="agent_type")
p_end.add_argument("--session-id", required=True)
```

Dispatch:

```python
from agent_registry import lifecycle

if args.cmd == "ensure":
    print(json.dumps(lifecycle.ensure(
        args.agent_type, args.session_id, args.directory,
        parent_session=args.parent_session,
        replace=not args.no_replace,
    )))
    return EXIT_OK
if args.cmd == "heartbeat":
    print(json.dumps(lifecycle.heartbeat(args.agent_type, args.session_id)))
    return EXIT_OK
if args.cmd == "end":
    print(json.dumps(lifecycle.end(args.agent_type, args.session_id)))
    return EXIT_OK
```

Lifecycle CLI should catch exceptions and return EXIT_IO / EXIT_NOT_FOUND consistently with existing handlers — but host wrappers will still fail open.

- [ ] **Step 4: pytest PASS + commit**

```bash
cd ~/projects/agent-registry
.venv/bin/pytest tests/test_cli_lifecycle.py -v
git add agent_registry/cli.py tests/test_cli_lifecycle.py
git commit -m "$(cat <<'EOF'
feat(cli): expose ensure/heartbeat/end for host hooks

EOF
)"
```

---

### Task 4: Claude hook wrapper

**Files:**
- Create: `/Users/tjdsneto/projects/tjdsneto-setup/ai/claude/scripts/agent-registry-hook`
- Modify: `/Users/tjdsneto/projects/tjdsneto-setup/ai/claude/hooks/hooks.json`
- Modify: `/Users/tjdsneto/projects/tjdsneto-setup/ai/claude/scripts/install`

- [ ] **Step 1: Create wrapper**

```bash
#!/usr/bin/env bash
# agent-registry-hook — Claude Code stdin JSON → agent-registry lifecycle
# Usage: agent-registry-hook ensure|heartbeat|end
set -u
EVENT="${1:-}"
BIN="${AGENT_REGISTRY_BIN:-$(command -v agent-registry || true)}"
if [[ -z "$BIN" || -z "$EVENT" ]]; then
  exit 0
fi

INPUT=$(cat || true)
SESSION_ID=$(printf '%s' "$INPUT" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("session_id",""))' 2>/dev/null || true)
CWD=$(printf '%s' "$INPUT" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("cwd") or "")' 2>/dev/null || true)
[[ -z "$SESSION_ID" ]] && exit 0
[[ -z "$CWD" ]] && CWD="$PWD"

case "$EVENT" in
  ensure)
    OUT=$("$BIN" ensure --type claude --session-id "$SESSION_ID" --directory "$CWD" 2>/dev/null) || exit 0
    # Inject brief context for SessionStart
    LIST=$("$BIN" list 2>/dev/null | head -n 25 || true)
    python3 - <<PY
import json, os
print(json.dumps({
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "agent-registry: session registered (type=claude). Keep registry_id private; hooks own heartbeat. Active peers:\\n" + os.environ.get("LIST","(none)")[:1500]
  }
}))
PY
    ;;
  heartbeat)
    "$BIN" heartbeat --type claude --session-id "$SESSION_ID" >/dev/null 2>&1 || true
    ;;
  end)
    "$BIN" end --type claude --session-id "$SESSION_ID" >/dev/null 2>&1 || true
    ;;
esac
exit 0
```

Fix the `LIST` injection properly in the real script (export LIST before python, or pass as argv). Keep stdout JSON **only** for `ensure`; heartbeat/end must print nothing (or empty) so they don't pollute Stop/SessionEnd.

Make executable: `chmod +x ai/claude/scripts/agent-registry-hook`

- [ ] **Step 2: Update `ai/claude/hooks/hooks.json`**

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/scripts/session-context"
          },
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/scripts/agent-registry-hook ensure"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/scripts/agent-registry-hook heartbeat"
          }
        ]
      },
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/scripts/rename-claude-sessions --current-only"
          }
        ]
      },
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/scripts/extract-learnings"
          }
        ]
      },
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/scripts/play-stop-sound"
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/scripts/agent-registry-hook end",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 3: Update `ai/claude/scripts/install` HOOKS_JSON**

Mirror the same events with **absolute** `$REPO_DIR/scripts/...` paths (install already does this). Move `session-context` from `UserPromptSubmit` to `SessionStart` to match `hooks.json` (current drift). Keep existing Stop hooks; prepend registry heartbeat.

- [ ] **Step 4: Manual smoke**

```bash
echo '{"session_id":"hook-test-1","cwd":"/tmp"}' | \
  /Users/tjdsneto/projects/tjdsneto-setup/ai/claude/scripts/agent-registry-hook ensure
agent-registry list
echo '{"session_id":"hook-test-1","cwd":"/tmp"}' | \
  /Users/tjdsneto/projects/tjdsneto-setup/ai/claude/scripts/agent-registry-hook heartbeat
echo '{"session_id":"hook-test-1","cwd":"/tmp"}' | \
  /Users/tjdsneto/projects/tjdsneto-setup/ai/claude/scripts/agent-registry-hook end
agent-registry list
```

Expected: session appears then disappears; commands exit 0.

- [ ] **Step 5: Commit (tjdsneto-setup)**

```bash
cd /Users/tjdsneto/projects/tjdsneto-setup
git add ai/claude/scripts/agent-registry-hook ai/claude/hooks/hooks.json ai/claude/scripts/install
git commit -m "$(cat <<'EOF'
feat(claude): wire agent-registry ensure/heartbeat/end hooks

EOF
)"
```

---

### Task 5: Cursor user hooks

**Files:**
- Create: `/Users/tjdsneto/projects/tjdsneto-setup/ai/cursor/hooks/hooks.json`
- Create: `/Users/tjdsneto/projects/tjdsneto-setup/ai/cursor/hooks/agent-registry.sh`
- Modify: `/Users/tjdsneto/projects/tjdsneto-setup/install.sh`
- Modify: `/Users/tjdsneto/projects/tjdsneto-setup/ai/cursor/README.md`

- [ ] **Step 1: Wrapper**

```bash
#!/usr/bin/env bash
# ~/.cursor/hooks/agent-registry.sh  (installed from ai/cursor/hooks/)
# Args: ensure|heartbeat|end
set -u
EVENT="${1:-}"
BIN="$(command -v agent-registry || true)"
[[ -z "$BIN" || -z "$EVENT" ]] && exit 0

INPUT=$(cat || true)
# Cursor payloads use session_id / cwd; be defensive about nesting
SESSION_ID=$(printf '%s' "$INPUT" | python3 -c '
import sys,json
d=json.load(sys.stdin)
print(d.get("session_id") or d.get("sessionId") or "")
' 2>/dev/null || true)
CWD=$(printf '%s' "$INPUT" | python3 -c '
import sys,json
d=json.load(sys.stdin)
print(d.get("cwd") or d.get("working_directory") or "")
' 2>/dev/null || true)
PARENT=$(printf '%s' "$INPUT" | python3 -c '
import sys,json
d=json.load(sys.stdin)
print(d.get("parent_session_id") or d.get("parentSessionId") or "")
' 2>/dev/null || true)

[[ -z "$SESSION_ID" ]] && exit 0
[[ -z "$CWD" ]] && CWD="$PWD"

case "$EVENT" in
  ensure)
    ARGS=(ensure --type cursor --session-id "$SESSION_ID" --directory "$CWD")
    [[ -n "$PARENT" ]] && ARGS+=(--parent-session "$PARENT")
    "$BIN" "${ARGS[@]}" >/dev/null 2>&1 || true
    ;;
  heartbeat)
    "$BIN" heartbeat --type cursor --session-id "$SESSION_ID" >/dev/null 2>&1 || true
    ;;
  end)
    "$BIN" end --type cursor --session-id "$SESSION_ID" >/dev/null 2>&1 || true
    ;;
esac
# Fail open — empty JSON object is fine for Cursor command hooks
echo '{}'
exit 0
```

- [ ] **Step 2: `ai/cursor/hooks/hooks.json`**

```json
{
  "version": 1,
  "hooks": {
    "sessionStart": [
      { "command": "./hooks/agent-registry.sh ensure" }
    ],
    "stop": [
      { "command": "./hooks/agent-registry.sh heartbeat" }
    ],
    "sessionEnd": [
      { "command": "./hooks/agent-registry.sh end" }
    ],
    "subagentStart": [
      { "command": "./hooks/agent-registry.sh ensure" }
    ],
    "subagentStop": [
      { "command": "./hooks/agent-registry.sh end" }
    ]
  }
}
```

Paths are relative to `~/.cursor/` for user hooks.

- [ ] **Step 3: Install into `install.sh`**

After Cursor cli-config section, add:

```bash
header "Cursor user hooks (agent-registry)"
HOOKS_SRC="$REPO_DIR/ai/cursor/hooks"
HOOKS_DEST="$HOME/.cursor/hooks"
mkdir -p "$HOOKS_DEST"
cp -f "$HOOKS_SRC/agent-registry.sh" "$HOOKS_DEST/agent-registry.sh"
chmod +x "$HOOKS_DEST/agent-registry.sh"
# Merge hooks.json: if missing, copy; if present, jq-merge our keys without wiping others
if [[ ! -f "$HOME/.cursor/hooks.json" ]]; then
  cp -f "$HOOKS_SRC/hooks.json" "$HOME/.cursor/hooks.json"
else
  # Prefer a small Python merge that unions hook arrays for our five events
  python3 "$REPO_DIR/ai/cursor/hooks/merge_hooks.py" "$HOME/.cursor/hooks.json" "$HOOKS_SRC/hooks.json"
fi
```

Implement `merge_hooks.py` to union command entries that contain `agent-registry.sh`, leave unrelated hooks alone. Keep it <80 lines.

- [ ] **Step 4: Smoke with fake stdin**

```bash
chmod +x /Users/tjdsneto/projects/tjdsneto-setup/ai/cursor/hooks/agent-registry.sh
echo '{"session_id":"cursor-hook-1","cwd":"/tmp"}' | \
  /Users/tjdsneto/projects/tjdsneto-setup/ai/cursor/hooks/agent-registry.sh ensure
agent-registry list
echo '{"session_id":"cursor-hook-1"}' | \
  /Users/tjdsneto/projects/tjdsneto-setup/ai/cursor/hooks/agent-registry.sh end
```

- [ ] **Step 5: Commit**

```bash
cd /Users/tjdsneto/projects/tjdsneto-setup
git add ai/cursor/hooks install.sh ai/cursor/README.md
git commit -m "$(cat <<'EOF'
feat(cursor): install user hooks for agent-registry liveness

EOF
)"
```

---

### Task 6: Skill + global rules + design note

**Files:**
- Modify: `ai/skills/shared/agent-registry/SKILL.md`
- Modify: `ai/instructions/claude/CLAUDE.md`
- Modify: `ai/instructions/cursor/user-rules.md`
- Modify: `docs/superpowers/specs/2026-09-24-agent-registry-design.md`
- Modify: `~/projects/agent-registry/README.md`

- [ ] **Step 1: Skill rewrite (presence section)**

Replace periodic-ping / session-start register instructions with:

```markdown
## Ownership split

- **Hooks (Claude/Cursor):** `ensure` on session start, throttled `heartbeat`, `end` on session end.
  Agents should not manually ping for liveness when hooks are installed.
- **Agents (this skill):** `update` on focus change; `list` before claiming an issue/PR;
  children still pass `--parent-session` when hooks cannot (Claude subagents in v1).

## Manual fallback

If hooks are missing (Codex, broken install):

```bash
agent-registry ensure --type <host> --session-id "$SESSION_ID" --directory "$PWD"
agent-registry heartbeat --type <host> --session-id "$SESSION_ID"
agent-registry end --type <host> --session-id "$SESSION_ID"
```

Prefer `ensure`/`heartbeat`/`end` over raw `register`/`ping`/`unregister` so the sidecar stays consistent.
```

Keep the existing `update` / `list` examples.

- [ ] **Step 2: Global rule (both hosts) — shorten to:**

```markdown
## Agent session presence — agent-registry

Hooks own register/heartbeat/unregister. Agent responsibilities:
- `agent-registry list` before claiming an issue/PR; coordinate if another Active session is on it.
- `agent-registry update <registry_id>` when focus/status/PR/timer/branch changes
  (get registry_id only from your own ensure/register output or session-private store — never from list).
- Never invent a parallel presence store; never publish registry_id in shared artifacts.

Skill: `agent-registry`.
```

**Problem:** after hooks own ensure, the agent no longer sees `registry_id` in chat for `update`. Fix in same task:

- [ ] **Step 3: Add `agent-registry self --type X --session-id Y`** (quick CLI)

Returns JSON including `registry_id` from sidecar only (owner lookup). Agents call this before `update` when they did not register manually.

```python
# lifecycle.self_view(agent_type, session_id) -> dict | None
# cli: agent-registry self --type claude --session-id ...
# prints session.to_dict() including registry_id, or exit 2 if no sidecar
```

Add tests + commit in agent-registry, then document in skill:

```bash
RID=$(agent-registry self --type cursor --session-id "$SESSION_ID" | python3 -c '...')
agent-registry update "$RID" --status working --summary "..."
```

- [ ] **Step 4: Design spec amendment**

Add § under Architecture:

> **v1.1 hooks:** Host hooks call `ensure` / `heartbeat` / `end`. Sidecar stores `registry_id`. Skill retains semantic update + coordination list. Amends non-goal “auto-detect session_id” — hooks may read host-provided session_id.

- [ ] **Step 5: Commit both repos**

```bash
# agent-registry: self subcommand
# tjdsneto-setup: skill + instructions + spec
```

---

### Task 7: Install + live verify

- [ ] **Step 1: Run installs**

```bash
cd /Users/tjdsneto/projects/tjdsneto-setup
./ai/claude/scripts/install
./install.sh   # or the Cursor hooks section only if install is heavy
```

- [ ] **Step 2: Verify Claude settings contain registry hooks**

```bash
jq '.hooks | keys' ~/.claude/settings.json
jq '.hooks.SessionStart' ~/.claude/settings.json
jq '.hooks.SessionEnd' ~/.claude/settings.json
```

- [ ] **Step 3: Verify Cursor hooks**

```bash
jq '.hooks | keys' ~/.cursor/hooks.json
test -x ~/.cursor/hooks/agent-registry.sh && echo ok
```

- [ ] **Step 4: Live check**

Start a fresh Claude Code session and a Cursor agent chat; run `agent-registry list` from a third terminal; confirm Active rows for both; wait for a Stop/stop event and confirm `last_ping` advances only after throttle window (or force with `AGENT_REGISTRY_HEARTBEAT_SECONDS=1` for a one-off test); end sessions and confirm unregister (or stale after end).

- [ ] **Step 5: Final commits if install scripts needed tweaks**

---

## Out of scope / follow-ups

- Codex hooks (no stable equivalent yet — keep skill fallback)
- Claude `SubagentStart` / parent linking
- Auto-`update` from cwd/branch heuristics
- Injecting full `list` into every Cursor `sessionStart` (Claude only in v1)
- Changing stale threshold

## Self-review

| Spec / decision | Task |
|-----------------|------|
| Hooks own liveness | 4, 5 |
| Sidecar keeps registry_id private from list | 1, 2 |
| Agents can still update | 6 (`self`) |
| Fail open | 4, 5 wrappers |
| Claude SessionEnd fast path | 4 (`timeout: 5`) |
| Install wiring both hosts | 4, 5, 7 |
| Skill/rule no longer demand manual ping | 6 |
