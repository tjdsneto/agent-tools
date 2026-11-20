# agent-registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Python `agent-registry` CLI + shared skill + global rule so any AI agent host can register session presence, list peers (without seeing mutate tokens), ping/update/unregister, and prune stale entries.

**Architecture:** Single JSON file at `~/.local/share/agent-registry/registry.json` (override via `AGENT_REGISTRY_PATH`), mutated under exclusive flock + atomic replace. `registry_id` is a capability token returned only by owner mutate commands; `list` never emits it. Parent/child links use public `session_id`. Skill + short global rule live in `tjdsneto-setup`.

**Tech Stack:** Python 3.11+ (stdlib + pytest), argparse, fcntl flock, uuid, dataclasses.

**Spec:** `docs/superpowers/specs/2026-09-24-agent-registry-design.md`

**Locked decisions (from spec §10):**
- Human `list`: sections **Active** then **Stale**; children indented under matching parent `session_id`; orphans annotated `parent:<session_id>`.
- `update` with no field flags → exit `1` (use `ping` for heartbeat-only).
- Install: symlink `tjdsneto-setup/bin/agent-registry` → `~/projects/agent-registry/bin/agent-registry`; skill via existing `install.sh` shared-skills path.

---

## File Structure

**New project** `~/projects/agent-registry/` (own git repo):

| Path | Responsibility |
|------|----------------|
| `bin/agent-registry` | Executable → `.venv/bin/python -m agent_registry.cli` |
| `agent_registry/__init__.py` | `__version__ = "0.1.0"` |
| `agent_registry/constants.py` | `STALE_SECONDS = 3600`, `STATUSES`, exit codes |
| `agent_registry/models.py` | `Session`, `RegistryFile`, `public_view()`, `is_stale()`, `now_iso()` |
| `agent_registry/store.py` | Path resolve, flock, load, atomic save, corrupt fail-closed |
| `agent_registry/ops.py` | register / update / ping / unregister / list_split / prune |
| `agent_registry/format.py` | Human-readable list text |
| `agent_registry/cli.py` | argparse + exit codes |
| `tests/conftest.py` | `tmp_registry` fixture (`AGENT_REGISTRY_PATH`) |
| `tests/test_models.py` | stale + public_view redaction |
| `tests/test_store.py` | load empty / corrupt / roundtrip |
| `tests/test_ops.py` | register, replace, update, ping, unregister |
| `tests/test_list.py` | Active/Stale, no registry_id, parent grouping |
| `tests/test_prune.py` | dry-run / --yes |
| `tests/test_cli.py` | End-to-end via `main([...])` |
| `requirements.txt` | `pytest>=8` |
| `README.md` | Install, CLI, skill pointer |
| `.gitignore` | `.venv/`, caches |

**In `tjdsneto-setup`:**

| Path | Responsibility |
|------|----------------|
| `ai/skills/shared/agent-registry/SKILL.md` | When/how to call CLI |
| `ai/instructions/claude/CLAUDE.md` | Short global presence rule |
| `ai/instructions/cursor/user-rules.md` | Same rule mirrored |
| `bin/agent-registry` | Symlink → `~/projects/agent-registry/bin/agent-registry` |

**Public Python API:**

```python
# constants.py
STALE_SECONDS = 3600
STATUSES = frozenset({"idle", "working", "reviewing", "blocked"})
EXIT_OK, EXIT_USAGE, EXIT_NOT_FOUND, EXIT_IO = 0, 1, 2, 3

# models.py
@dataclass
class Session: ...  # all fields from spec §5
@dataclass
class RegistryFile:
    version: int
    sessions: list[Session]

def now_iso() -> str: ...
def is_stale(session: Session, *, now: datetime | None = None) -> bool: ...
def public_view(session: Session) -> dict: ...  # no registry_id

# store.py
class CorruptRegistryError(Exception): ...
def registry_path() -> Path: ...
def load() -> RegistryFile: ...
def save(reg: RegistryFile) -> None: ...

# ops.py
class DuplicateSessionError(Exception): ...
class UnknownRegistryIdError(Exception): ...
class ValidationError(Exception): ...
def register(*, agent_type, session_id, directory, parent_session_id=None, replace=False) -> Session: ...
def update(registry_id: str, **patches) -> Session: ...
def ping(registry_id: str) -> Session: ...
def unregister(registry_id: str) -> None: ...
def list_split(*, now=None) -> tuple[list[dict], list[dict]]: ...
def prune(*, dry_run: bool, yes: bool, now=None) -> list[dict]: ...

# format.py
def format_list(active: list[dict], stale: list[dict]) -> str: ...

# cli.py
def main(argv: list[str] | None = None) -> int: ...
```

---

### Task 1: Scaffold project + models

**Files:**
- Create: `/Users/tjdsneto/projects/agent-registry/` (git init)
- Create: `agent_registry/__init__.py`, `constants.py`, `models.py`
- Create: `requirements.txt`, `.gitignore`, `README.md` (stub), `bin/agent-registry`
- Create: `tests/test_models.py`, `tests/conftest.py`

- [ ] **Step 1: Create dirs, venv, git**

```bash
mkdir -p ~/projects/agent-registry/{agent_registry,tests,bin}
cd ~/projects/agent-registry
git init
python3 -m venv .venv
.venv/bin/pip install pytest
printf 'pytest>=8\n' > requirements.txt
cat > .gitignore <<'EOF'
.venv/
__pycache__/
.pytest_cache/
*.pyc
*.egg-info/
dist/
EOF
```

- [ ] **Step 2: Write failing model tests**

```python
# tests/test_models.py
from datetime import datetime, timezone
from agent_registry.models import Session, is_stale, public_view, now_iso

def _sess(**kw):
    base = dict(
        registry_id="rid-1", session_id="sid-1", agent_type="cursor",
        directory="/tmp/x", parent_session_id=None, status="idle", summary="",
        issue=None, pr=None, branch=None, goflow_timer_id=None,
        registered_at="2026-09-24T12:00:00+00:00",
        last_ping="2026-09-24T12:00:00+00:00",
        updated_at="2026-09-24T12:00:00+00:00",
    )
    base.update(kw)
    return Session(**base)

def test_not_stale_within_60m():
    now = datetime(2026, 9, 24, 12, 30, tzinfo=timezone.utc)
    assert is_stale(_sess(), now=now) is False

def test_stale_after_60m():
    now = datetime(2026, 9, 24, 13, 1, tzinfo=timezone.utc)
    assert is_stale(_sess(), now=now) is True

def test_public_view_hides_registry_id():
    view = public_view(_sess())
    assert "registry_id" not in view
    assert view["session_id"] == "sid-1"

def test_now_iso_has_timezone():
    s = now_iso()
    assert "+" in s or s.endswith("Z")
```

- [ ] **Step 3: Run — expect fail**

```bash
cd ~/projects/agent-registry && .venv/bin/pytest tests/test_models.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 4: Implement constants + models**

```python
# agent_registry/__init__.py
__version__ = "0.1.0"

# agent_registry/constants.py
STALE_SECONDS = 3600
STATUSES = frozenset({"idle", "working", "reviewing", "blocked"})
EXIT_OK = 0
EXIT_USAGE = 1
EXIT_NOT_FOUND = 2
EXIT_IO = 3

# agent_registry/models.py
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from agent_registry.constants import STALE_SECONDS

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

@dataclass
class Session:
    registry_id: str
    session_id: str
    agent_type: str
    directory: str
    parent_session_id: str | None
    status: str
    summary: str
    issue: str | None
    pr: dict[str, str] | None
    branch: str | None
    goflow_timer_id: str | None
    registered_at: str
    last_ping: str
    updated_at: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Session:
        return cls(
            registry_id=d["registry_id"],
            session_id=d["session_id"],
            agent_type=d["agent_type"],
            directory=d["directory"],
            parent_session_id=d.get("parent_session_id"),
            status=d.get("status", "idle"),
            summary=d.get("summary") or "",
            issue=d.get("issue"),
            pr=d.get("pr"),
            branch=d.get("branch"),
            goflow_timer_id=d.get("goflow_timer_id"),
            registered_at=d["registered_at"],
            last_ping=d["last_ping"],
            updated_at=d["updated_at"],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

@dataclass
class RegistryFile:
    version: int = 1
    sessions: list[Session] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "sessions": [s.to_dict() for s in self.sessions]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RegistryFile:
        return cls(
            version=int(d.get("version", 1)),
            sessions=[Session.from_dict(s) for s in d.get("sessions", [])],
        )

def _parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)

def is_stale(session: Session, *, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    ping = _parse_iso(session.last_ping)
    if ping.tzinfo is None:
        ping = ping.replace(tzinfo=timezone.utc)
    return (now - ping).total_seconds() > STALE_SECONDS

def public_view(session: Session) -> dict[str, Any]:
    d = session.to_dict()
    d.pop("registry_id", None)
    return d
```

- [ ] **Step 5: bin + conftest + README stub**

```bash
cat > ~/projects/agent-registry/bin/agent-registry <<'EOF'
#!/usr/bin/env bash
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/.venv/bin/python" -m agent_registry.cli "$@"
EOF
chmod +x ~/projects/agent-registry/bin/agent-registry

cat > ~/projects/agent-registry/tests/conftest.py <<'EOF'
import pytest

@pytest.fixture
def tmp_registry(tmp_path, monkeypatch):
    path = tmp_path / "registry.json"
    monkeypatch.setenv("AGENT_REGISTRY_PATH", str(path))
    return path
EOF

printf '# agent-registry\n\nCLI TBD.\n' > ~/projects/agent-registry/README.md
```

- [ ] **Step 6: Run tests — expect pass**

```bash
cd ~/projects/agent-registry && .venv/bin/pytest tests/test_models.py -v
```

- [ ] **Step 7: Commit**

```bash
cd ~/projects/agent-registry
git add -A
git commit -m "feat: scaffold agent-registry with Session models"
```

---

### Task 2: Store — path, flock, load, atomic save

**Files:**
- Create: `agent_registry/store.py`
- Create: `tests/test_store.py`

- [ ] **Step 1: Write failing store tests**

```python
# tests/test_store.py
import pytest
from agent_registry import store
from agent_registry.models import RegistryFile, Session

def test_load_missing_file_returns_empty(tmp_registry):
    reg = store.load()
    assert reg.version == 1
    assert reg.sessions == []

def test_save_roundtrip(tmp_registry):
    reg = RegistryFile(sessions=[
        Session(
            registry_id="r1", session_id="s1", agent_type="claude",
            directory="/a", parent_session_id=None, status="idle",
            summary="", issue=None, pr=None, branch=None, goflow_timer_id=None,
            registered_at="2026-09-24T12:00:00+00:00",
            last_ping="2026-09-24T12:00:00+00:00",
            updated_at="2026-09-24T12:00:00+00:00",
        )
    ])
    store.save(reg)
    loaded = store.load()
    assert len(loaded.sessions) == 1
    assert loaded.sessions[0].registry_id == "r1"

def test_corrupt_nonempty_fails_closed(tmp_registry):
    tmp_registry.write_text("{not-json", encoding="utf-8")
    with pytest.raises(store.CorruptRegistryError):
        store.load()
    assert tmp_registry.read_text(encoding="utf-8") == "{not-json"

def test_empty_file_treated_as_empty_registry(tmp_registry):
    tmp_registry.write_text("", encoding="utf-8")
    assert store.load().sessions == []
```

- [ ] **Step 2: Run — expect fail** (`ModuleNotFoundError` for store)

```bash
cd ~/projects/agent-registry && .venv/bin/pytest tests/test_store.py -v
```

- [ ] **Step 3: Implement store**

```python
# agent_registry/store.py
from __future__ import annotations
import fcntl
import json
import os
import tempfile
from pathlib import Path
from agent_registry.models import RegistryFile

class CorruptRegistryError(Exception):
    pass

def registry_path() -> Path:
    override = os.environ.get("AGENT_REGISTRY_PATH")
    if override:
        return Path(override)
    return Path.home() / ".local" / "share" / "agent-registry" / "registry.json"

def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

def load() -> RegistryFile:
    path = registry_path()
    if not path.exists():
        return RegistryFile()
    raw = path.read_text(encoding="utf-8")
    if raw.strip() == "":
        return RegistryFile()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise CorruptRegistryError(f"corrupt registry at {path}: {e}") from e
    if not isinstance(data, dict):
        raise CorruptRegistryError(f"corrupt registry at {path}: root must be object")
    return RegistryFile.from_dict(data)

def save(reg: RegistryFile) -> None:
    path = registry_path()
    _ensure_parent(path)
    lock_path = path.with_suffix(path.suffix + ".lock")
    _ensure_parent(lock_path)
    payload = json.dumps(reg.to_dict(), indent=2) + "\n"
    with open(lock_path, "a+", encoding="utf-8") as lock_f:
        fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
        try:
            fd, tmp_name = tempfile.mkstemp(
                dir=str(path.parent), prefix=".registry.", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                    tmp.write(payload)
                    tmp.flush()
                    os.fsync(tmp.fileno())
                os.replace(tmp_name, path)
            except Exception:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
        finally:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
```

- [ ] **Step 4: Run — expect pass**

```bash
cd ~/projects/agent-registry && .venv/bin/pytest tests/test_store.py tests/test_models.py -v
```

- [ ] **Step 5: Commit**

```bash
cd ~/projects/agent-registry
git add agent_registry/store.py tests/test_store.py
git commit -m "feat: add flocked atomic registry store"
```

---

### Task 3: ops — register (+ replace, parent)

**Files:**
- Create: `agent_registry/ops.py`
- Create: `tests/test_ops.py`

- [ ] **Step 1: Write failing register tests**

```python
# tests/test_ops.py
import pytest
from agent_registry import ops, store

def test_register_returns_session_with_registry_id(tmp_registry):
    s = ops.register(agent_type="cursor", session_id="abc", directory="/proj")
    assert s.registry_id
    assert s.session_id == "abc"
    assert s.status == "idle"
    assert store.load().sessions[0].registry_id == s.registry_id

def test_register_duplicate_session_id_errors(tmp_registry):
    ops.register(agent_type="cursor", session_id="abc", directory="/proj")
    with pytest.raises(ops.DuplicateSessionError):
        ops.register(agent_type="claude", session_id="abc", directory="/other")

def test_register_replace_overwrites(tmp_registry):
    first = ops.register(agent_type="cursor", session_id="abc", directory="/old")
    second = ops.register(
        agent_type="cursor", session_id="abc", directory="/new", replace=True
    )
    assert second.directory == "/new"
    assert second.registry_id != first.registry_id
    assert len(store.load().sessions) == 1

def test_register_with_parent(tmp_registry):
    s = ops.register(
        agent_type="cursor", session_id="child", directory="/proj",
        parent_session_id="parent-sid",
    )
    assert s.parent_session_id == "parent-sid"
```

- [ ] **Step 2: Run — expect fail**

```bash
cd ~/projects/agent-registry && .venv/bin/pytest tests/test_ops.py -v
```

- [ ] **Step 3: Implement register**

```python
# agent_registry/ops.py
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any
from agent_registry import store
from agent_registry.constants import STATUSES
from agent_registry.models import RegistryFile, Session, is_stale, now_iso, public_view

class DuplicateSessionError(Exception):
    pass

class UnknownRegistryIdError(Exception):
    pass

class ValidationError(Exception):
    pass

def _find_by_session_id(reg: RegistryFile, session_id: str) -> Session | None:
    for s in reg.sessions:
        if s.session_id == session_id:
            return s
    return None

def _find_by_registry_id(reg: RegistryFile, registry_id: str) -> Session | None:
    for s in reg.sessions:
        if s.registry_id == registry_id:
            return s
    return None

def register(
    *,
    agent_type: str,
    session_id: str,
    directory: str,
    parent_session_id: str | None = None,
    replace: bool = False,
) -> Session:
    if not agent_type.strip() or not session_id.strip() or not directory.strip():
        raise ValidationError("agent_type, session_id, and directory are required")
    reg = store.load()
    existing = _find_by_session_id(reg, session_id)
    if existing and not replace:
        raise DuplicateSessionError(f"session_id already registered: {session_id}")
    if existing and replace:
        reg.sessions = [s for s in reg.sessions if s.session_id != session_id]
    ts = now_iso()
    sess = Session(
        registry_id=str(uuid.uuid4()),
        session_id=session_id,
        agent_type=agent_type,
        directory=directory,
        parent_session_id=parent_session_id,
        status="idle",
        summary="",
        issue=None,
        pr=None,
        branch=None,
        goflow_timer_id=None,
        registered_at=ts,
        last_ping=ts,
        updated_at=ts,
    )
    reg.sessions.append(sess)
    store.save(reg)
    return sess
```

- [ ] **Step 4: Run — expect pass**

```bash
cd ~/projects/agent-registry && .venv/bin/pytest tests/test_ops.py -v
```

- [ ] **Step 5: Commit**

```bash
cd ~/projects/agent-registry
git add agent_registry/ops.py tests/test_ops.py
git commit -m "feat: register sessions with replace and parent link"
```

---

### Task 4: ops — update, ping, unregister

**Files:**
- Modify: `agent_registry/ops.py`
- Modify: `tests/test_ops.py`

- [ ] **Step 1: Append failing tests to `tests/test_ops.py`**

```python
def test_update_patches_and_refreshes_ping(tmp_registry):
    s = ops.register(agent_type="cursor", session_id="abc", directory="/proj")
    updated = ops.update(
        s.registry_id,
        status="reviewing",
        summary="Review PR 123",
        pr_title="Fix flaky test",
        pr_url="https://github.com/org/repo/pull/123",
        branch="tn/fix/flake",
        issue="https://github.com/org/repo/issues/99",
        goflow_timer_id="timer-1",
    )
    assert updated.status == "reviewing"
    assert updated.pr == {
        "title": "Fix flaky test",
        "url": "https://github.com/org/repo/pull/123",
    }
    assert updated.goflow_timer_id == "timer-1"
    assert updated.last_ping >= s.last_ping

def test_update_no_patches_raises(tmp_registry):
    s = ops.register(agent_type="cursor", session_id="abc", directory="/proj")
    with pytest.raises(ops.ValidationError):
        ops.update(s.registry_id)

def test_update_bad_id_raises(tmp_registry):
    with pytest.raises(ops.UnknownRegistryIdError):
        ops.update("nope", status="working")

def test_update_bad_status_raises(tmp_registry):
    s = ops.register(agent_type="cursor", session_id="abc", directory="/proj")
    with pytest.raises(ops.ValidationError):
        ops.update(s.registry_id, status="flying")

def test_update_clear_flags(tmp_registry):
    s = ops.register(agent_type="cursor", session_id="abc", directory="/proj")
    ops.update(
        s.registry_id, issue="x", branch="b", goflow_timer_id="t",
        pr_title="T", pr_url="http://u", summary="hi",
    )
    cleared = ops.update(
        s.registry_id,
        clear_issue=True, clear_branch=True, clear_goflow_timer=True,
        clear_pr=True, clear_summary=True,
    )
    assert cleared.issue is None and cleared.pr is None
    assert cleared.branch is None and cleared.goflow_timer_id is None
    assert cleared.summary == ""

def test_ping_refreshes_last_ping(tmp_registry):
    s = ops.register(agent_type="cursor", session_id="abc", directory="/proj")
    assert ops.ping(s.registry_id).last_ping >= s.last_ping

def test_unregister_removes(tmp_registry):
    s = ops.register(agent_type="cursor", session_id="abc", directory="/proj")
    ops.unregister(s.registry_id)
    assert store.load().sessions == []

def test_unregister_bad_id(tmp_registry):
    with pytest.raises(ops.UnknownRegistryIdError):
        ops.unregister("missing")
```

- [ ] **Step 2: Run — expect fail on new tests**

```bash
cd ~/projects/agent-registry && .venv/bin/pytest tests/test_ops.py -v
```

- [ ] **Step 3: Append update / ping / unregister to `ops.py`**

```python
def update(registry_id: str, **patches: Any) -> Session:
    clear_keys = {
        "clear_issue", "clear_pr", "clear_branch", "clear_goflow_timer",
        "clear_summary", "clear_parent_session",
    }
    set_keys = {
        "status", "summary", "issue", "branch", "directory", "goflow_timer_id",
        "pr_title", "pr_url", "parent_session_id",
    }
    meaningful = False
    for k, v in patches.items():
        if k in clear_keys and v:
            meaningful = True
        elif k in set_keys and v is not None:
            meaningful = True
    if not meaningful:
        raise ValidationError("update requires at least one field flag")

    reg = store.load()
    sess = _find_by_registry_id(reg, registry_id)
    if not sess:
        raise UnknownRegistryIdError(registry_id)

    if patches.get("status") is not None:
        if patches["status"] not in STATUSES:
            raise ValidationError(f"invalid status: {patches['status']}")
        sess.status = patches["status"]
    if patches.get("summary") is not None:
        sess.summary = patches["summary"]
    if patches.get("directory") is not None:
        sess.directory = patches["directory"]
    if patches.get("issue") is not None:
        sess.issue = patches["issue"]
    if patches.get("branch") is not None:
        sess.branch = patches["branch"]
    if patches.get("goflow_timer_id") is not None:
        sess.goflow_timer_id = patches["goflow_timer_id"]
    if patches.get("parent_session_id") is not None:
        sess.parent_session_id = patches["parent_session_id"]

    if patches.get("pr_title") is not None or patches.get("pr_url") is not None:
        pr = dict(sess.pr) if sess.pr else {"title": "", "url": ""}
        if patches.get("pr_title") is not None:
            pr["title"] = patches["pr_title"]
        if patches.get("pr_url") is not None:
            pr["url"] = patches["pr_url"]
        sess.pr = pr

    if patches.get("clear_issue"):
        sess.issue = None
    if patches.get("clear_pr"):
        sess.pr = None
    if patches.get("clear_branch"):
        sess.branch = None
    if patches.get("clear_goflow_timer"):
        sess.goflow_timer_id = None
    if patches.get("clear_summary"):
        sess.summary = ""
    if patches.get("clear_parent_session"):
        sess.parent_session_id = None

    ts = now_iso()
    sess.last_ping = ts
    sess.updated_at = ts
    store.save(reg)
    return sess

def ping(registry_id: str) -> Session:
    reg = store.load()
    sess = _find_by_registry_id(reg, registry_id)
    if not sess:
        raise UnknownRegistryIdError(registry_id)
    ts = now_iso()
    sess.last_ping = ts
    sess.updated_at = ts
    store.save(reg)
    return sess

def unregister(registry_id: str) -> None:
    reg = store.load()
    if not _find_by_registry_id(reg, registry_id):
        raise UnknownRegistryIdError(registry_id)
    reg.sessions = [s for s in reg.sessions if s.registry_id != registry_id]
    store.save(reg)
```

- [ ] **Step 4: Run — expect pass**

```bash
cd ~/projects/agent-registry && .venv/bin/pytest tests/test_ops.py -v
```

- [ ] **Step 5: Commit**

```bash
cd ~/projects/agent-registry
git add agent_registry/ops.py tests/test_ops.py
git commit -m "feat: update, ping, and unregister by registry_id"
```

---

### Task 5: list_split + format

**Files:**
- Modify: `agent_registry/ops.py` (add `list_split` only)
- Create: `agent_registry/format.py`
- Create: `tests/test_list.py`

- [ ] **Step 1: Write failing list tests**

```python
# tests/test_list.py
from datetime import datetime, timezone
from agent_registry import ops, store
from agent_registry.format import format_list

def test_list_split_active_and_stale(tmp_registry):
    ops.register(agent_type="cursor", session_id="live", directory="/a")
    ops.register(agent_type="claude", session_id="old", directory="/b")
    reg = store.load()
    for s in reg.sessions:
        if s.session_id == "old":
            s.last_ping = "2026-09-24T10:00:00+00:00"
    store.save(reg)
    now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    active, stale = ops.list_split(now=now)
    assert [x["session_id"] for x in active] == ["live"]
    assert [x["session_id"] for x in stale] == ["old"]
    assert all("registry_id" not in x for x in active + stale)

def test_format_groups_children(tmp_registry):
    ops.register(agent_type="cursor", session_id="parent", directory="/p")
    ops.register(
        agent_type="cursor", session_id="child", directory="/c",
        parent_session_id="parent",
    )
    text = format_list(*ops.list_split())
    assert "Active" in text
    assert text.index("parent") < text.index("child")
    child_line = [ln for ln in text.splitlines() if "child" in ln][0]
    assert child_line.startswith("  ")
    assert "registry_id" not in text

def test_format_orphan_annotates_parent(tmp_registry):
    ops.register(
        agent_type="cursor", session_id="orphan", directory="/o",
        parent_session_id="missing-parent",
    )
    text = format_list(*ops.list_split())
    assert "parent:missing-parent" in text.replace(" ", "")
```

- [ ] **Step 2: Run — expect fail**

```bash
cd ~/projects/agent-registry && .venv/bin/pytest tests/test_list.py -v
```

- [ ] **Step 3: Implement `list_split` + `format.py`**

```python
# append to ops.py
def list_split(*, now: datetime | None = None) -> tuple[list[dict], list[dict]]:
    reg = store.load()
    active, stale = [], []
    for s in reg.sessions:
        view = public_view(s)
        (stale if is_stale(s, now=now) else active).append(view)
    return active, stale
```

```python
# agent_registry/format.py
from __future__ import annotations

def _line(s: dict, *, indent: str = "") -> str:
    bits = [s.get("agent_type") or "?", s.get("session_id") or "?", s.get("status") or "?"]
    if (s.get("summary") or "").strip():
        bits.append(s["summary"].strip())
    pr = s.get("pr") or {}
    if pr.get("title"):
        bits.append(f'PR:"{pr["title"]}"')
    if s.get("issue"):
        bits.append(f'issue:{s["issue"]}')
    if s.get("branch"):
        bits.append(f'branch:{s["branch"]}')
    if s.get("goflow_timer_id"):
        bits.append(f'goflow:{s["goflow_timer_id"]}')
    if s.get("directory"):
        bits.append(s["directory"])
    return indent + " · ".join(str(b) for b in bits)

def _ordered_roots(sessions: list[dict]) -> list[tuple[dict, list[dict]]]:
    by_sid = {s["session_id"]: s for s in sessions}
    children: dict[str, list[dict]] = {}
    for s in sessions:
        parent = s.get("parent_session_id")
        if parent and parent in by_sid:
            children.setdefault(parent, []).append(s)
    ordered: list[tuple[dict, list[dict]]] = []
    seen: set[str] = set()
    for s in sessions:
        sid = s["session_id"]
        if sid in seen:
            continue
        parent = s.get("parent_session_id")
        if parent and parent in by_sid:
            continue
        if parent and parent not in by_sid:
            annotated = dict(s)
            annotated["_orphan_parent"] = parent
            ordered.append((annotated, []))
            seen.add(sid)
            continue
        kids = children.get(sid, [])
        ordered.append((s, kids))
        seen.add(sid)
        for k in kids:
            seen.add(k["session_id"])
    return ordered

def _section(title: str, sessions: list[dict]) -> list[str]:
    lines = [title]
    if not sessions:
        lines.append("  (none)")
        return lines
    for root, kids in _ordered_roots(sessions):
        if root.get("_orphan_parent"):
            lines.append(_line(root) + f"  parent:{root['_orphan_parent']}")
        else:
            lines.append(_line(root))
        for k in kids:
            lines.append(_line(k, indent="  "))
    return lines

def format_list(active: list[dict], stale: list[dict]) -> str:
    lines = _section("Active", active) + [""] + _section("Stale", stale)
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run — expect pass**

```bash
cd ~/projects/agent-registry && .venv/bin/pytest tests/test_list.py -v
```

- [ ] **Step 5: Commit**

```bash
cd ~/projects/agent-registry
git add agent_registry/ops.py agent_registry/format.py tests/test_list.py
git commit -m "feat: list active/stale with parent grouping, no registry_id"
```

---

### Task 6: prune

**Files:**
- Modify: `agent_registry/ops.py`
- Create: `tests/test_prune.py`

- [ ] **Step 1: Write failing prune tests**

```python
# tests/test_prune.py
from datetime import datetime, timezone
import pytest
from agent_registry import ops, store

def _age(session_id: str, last_ping: str) -> None:
    reg = store.load()
    for s in reg.sessions:
        if s.session_id == session_id:
            s.last_ping = last_ping
    store.save(reg)

def test_prune_dry_run_does_not_delete(tmp_registry):
    ops.register(agent_type="cursor", session_id="old", directory="/a")
    _age("old", "2026-09-24T10:00:00+00:00")
    now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    would = ops.prune(dry_run=True, yes=False, now=now)
    assert [x["session_id"] for x in would] == ["old"]
    assert all("registry_id" not in x for x in would)
    assert len(store.load().sessions) == 1

def test_prune_yes_deletes_stale(tmp_registry):
    ops.register(agent_type="cursor", session_id="old", directory="/a")
    ops.register(agent_type="cursor", session_id="live", directory="/b")
    _age("old", "2026-09-24T10:00:00+00:00")
    now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    removed = ops.prune(dry_run=False, yes=True, now=now)
    assert [x["session_id"] for x in removed] == ["old"]
    assert [s.session_id for s in store.load().sessions] == ["live"]

def test_prune_without_yes_raises(tmp_registry):
    with pytest.raises(ops.ValidationError):
        ops.prune(dry_run=False, yes=False)
```

- [ ] **Step 2: Run — expect fail**

```bash
cd ~/projects/agent-registry && .venv/bin/pytest tests/test_prune.py -v
```

- [ ] **Step 3: Implement prune**

```python
# append to ops.py
def prune(
    *,
    dry_run: bool = True,
    yes: bool = False,
    now: datetime | None = None,
) -> list[dict]:
    if not dry_run and not yes:
        raise ValidationError("prune requires --yes to delete (or use dry-run preview)")
    reg = store.load()
    stale_sessions = [s for s in reg.sessions if is_stale(s, now=now)]
    views = [public_view(s) for s in stale_sessions]
    if dry_run or not yes:
        return views
    stale_ids = {s.registry_id for s in stale_sessions}
    reg.sessions = [s for s in reg.sessions if s.registry_id not in stale_ids]
    store.save(reg)
    return views
```

- [ ] **Step 4: Run — expect pass**

```bash
cd ~/projects/agent-registry && .venv/bin/pytest tests/test_prune.py -v
```

- [ ] **Step 5: Commit**

```bash
cd ~/projects/agent-registry
git add agent_registry/ops.py tests/test_prune.py
git commit -m "feat: prune stale sessions with dry-run and --yes"
```

---

### Task 7: CLI

**Files:**
- Create: `agent_registry/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

```python
# tests/test_cli.py
import json
from agent_registry.cli import main
from agent_registry.constants import EXIT_OK, EXIT_USAGE, EXIT_NOT_FOUND

def test_register_list_ping_update_unregister(tmp_registry, capsys):
    code = main([
        "register", "--type", "cursor", "--session-id", "s1", "--directory", "/proj",
    ])
    assert code == EXIT_OK
    rid = json.loads(capsys.readouterr().out)["registry_id"]

    assert main(["list", "--json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert all("registry_id" not in s for s in payload["active"] + payload["stale"])

    assert main(["ping", rid]) == EXIT_OK
    capsys.readouterr()
    assert main(["update", rid, "--status", "working", "--summary", "doing stuff"]) == EXIT_OK
    capsys.readouterr()
    assert main(["update", rid]) == EXIT_USAGE
    capsys.readouterr()
    assert main(["unregister", rid]) == EXIT_OK
    capsys.readouterr()
    assert main(["ping", rid]) == EXIT_NOT_FOUND

def test_list_human_has_sections(tmp_registry, capsys):
    main(["register", "--type", "claude", "--session-id", "x", "--directory", "/d"])
    assert main(["list"]) == EXIT_OK
    text = capsys.readouterr().out
    assert "Active" in text and "Stale" in text
    assert "registry_id" not in text
```

- [ ] **Step 2: Run — expect fail**

```bash
cd ~/projects/agent-registry && .venv/bin/pytest tests/test_cli.py -v
```

- [ ] **Step 3: Implement `cli.py`**

```python
# agent_registry/cli.py
from __future__ import annotations
import argparse
import json
import sys
from agent_registry import ops
from agent_registry.constants import EXIT_IO, EXIT_NOT_FOUND, EXIT_OK, EXIT_USAGE
from agent_registry.format import format_list
from agent_registry.models import Session
from agent_registry.store import CorruptRegistryError

def _session_out(s: Session) -> dict:
    return s.to_dict()

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-registry")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_reg = sub.add_parser("register")
    p_reg.add_argument("--type", required=True, dest="agent_type")
    p_reg.add_argument("--session-id", required=True)
    p_reg.add_argument("--directory", required=True)
    p_reg.add_argument("--parent-session", default=None)
    p_reg.add_argument("--replace", action="store_true")

    p_up = sub.add_parser("update")
    p_up.add_argument("registry_id")
    p_up.add_argument("--status")
    p_up.add_argument("--summary")
    p_up.add_argument("--issue")
    p_up.add_argument("--pr-title")
    p_up.add_argument("--pr-url")
    p_up.add_argument("--branch")
    p_up.add_argument("--directory")
    p_up.add_argument("--goflow-timer", dest="goflow_timer_id")
    p_up.add_argument("--parent-session", dest="parent_session_id")
    p_up.add_argument("--clear-issue", action="store_true")
    p_up.add_argument("--clear-pr", action="store_true")
    p_up.add_argument("--clear-branch", action="store_true")
    p_up.add_argument("--clear-goflow-timer", action="store_true")
    p_up.add_argument("--clear-summary", action="store_true")
    p_up.add_argument("--clear-parent-session", action="store_true")

    p_ping = sub.add_parser("ping")
    p_ping.add_argument("registry_id")
    p_un = sub.add_parser("unregister")
    p_un.add_argument("registry_id")
    p_list = sub.add_parser("list")
    p_list.add_argument("--json", action="store_true")
    p_prune = sub.add_parser("prune")
    p_prune.add_argument("--dry-run", action="store_true")
    p_prune.add_argument("--yes", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.cmd == "register":
            s = ops.register(
                agent_type=args.agent_type,
                session_id=args.session_id,
                directory=args.directory,
                parent_session_id=args.parent_session,
                replace=args.replace,
            )
            print(json.dumps(_session_out(s)))
            return EXIT_OK
        if args.cmd == "update":
            s = ops.update(
                args.registry_id,
                status=args.status,
                summary=args.summary,
                issue=args.issue,
                pr_title=args.pr_title,
                pr_url=args.pr_url,
                branch=args.branch,
                directory=args.directory,
                goflow_timer_id=args.goflow_timer_id,
                parent_session_id=args.parent_session_id,
                clear_issue=args.clear_issue,
                clear_pr=args.clear_pr,
                clear_branch=args.clear_branch,
                clear_goflow_timer=args.clear_goflow_timer,
                clear_summary=args.clear_summary,
                clear_parent_session=args.clear_parent_session,
            )
            print(json.dumps(_session_out(s)))
            return EXIT_OK
        if args.cmd == "ping":
            print(json.dumps(_session_out(ops.ping(args.registry_id))))
            return EXIT_OK
        if args.cmd == "unregister":
            ops.unregister(args.registry_id)
            print(json.dumps({"ok": True}))
            return EXIT_OK
        if args.cmd == "list":
            active, stale = ops.list_split()
            if args.json:
                print(json.dumps({"active": active, "stale": stale}))
            else:
                print(format_list(active, stale), end="")
            return EXIT_OK
        if args.cmd == "prune":
            dry_run = args.dry_run or not args.yes
            removed = ops.prune(dry_run=dry_run, yes=args.yes)
            print(json.dumps({"dry_run": dry_run, "sessions": removed}))
            return EXIT_OK
    except ops.ValidationError as e:
        print(f"agent-registry: {e}", file=sys.stderr)
        return EXIT_USAGE
    except ops.DuplicateSessionError as e:
        print(f"agent-registry: {e}", file=sys.stderr)
        return EXIT_USAGE
    except ops.UnknownRegistryIdError as e:
        print(f"agent-registry: unknown registry_id: {e}", file=sys.stderr)
        return EXIT_NOT_FOUND
    except CorruptRegistryError as e:
        print(f"agent-registry: {e}", file=sys.stderr)
        return EXIT_IO
    except OSError as e:
        print(f"agent-registry: {e}", file=sys.stderr)
        return EXIT_IO
    return EXIT_USAGE

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Full suite**

```bash
cd ~/projects/agent-registry && .venv/bin/pytest -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/projects/agent-registry
git add agent_registry/cli.py tests/test_cli.py
git commit -m "feat: wire agent-registry CLI subcommands"
```

---

### Task 8: README

**Files:**
- Modify: `~/projects/agent-registry/README.md`

- [ ] **Step 1: Write README** covering install (venv + setup bin symlink), `AGENT_REGISTRY_PATH`, all subcommands, note that `list` never prints `registry_id`, pointer to skill path in tjdsneto-setup.

- [ ] **Step 2: Commit**

```bash
cd ~/projects/agent-registry
git add README.md
git commit -m "docs: README for agent-registry CLI"
```

---

### Task 9: Shared skill in tjdsneto-setup

**Files:**
- Create: `ai/skills/shared/agent-registry/SKILL.md`

- [ ] **Step 1: Write SKILL.md** with frontmatter `name: agent-registry` and description covering register/list/update/ping/unregister. Body must include: register flags; keep `registry_id` private; list before claiming issue/PR; update fields including `--goflow-timer`; ping every ~20–30m; unregister on wrap; `--parent-session` for children; `prune` / `prune --yes` for humans.

- [ ] **Step 2: Install skill symlinks**

```bash
cd ~/projects/tjdsneto-setup && ./install.sh
```

- [ ] **Step 3: Commit**

```bash
cd ~/projects/tjdsneto-setup
git add ai/skills/shared/agent-registry/SKILL.md
git commit -m "feat(agent-registry): add shared presence skill"
```

---

### Task 10: Global rule + bin symlink

**Files:**
- Modify: `ai/instructions/claude/CLAUDE.md`
- Modify: `ai/instructions/cursor/user-rules.md`
- Create: `bin/agent-registry` (symlink)

- [ ] **Step 1: Add section to both instruction files**

```markdown
## Agent session presence — agent-registry

Every AI session (Claude Code, Cursor, Codex, …) must register in the shared presence
registry via the `agent-registry` CLI and skill:

- Register at session start; keep `registry_id` private; never put it in list-like shared text.
- `agent-registry list` before claiming an issue/PR; coordinate if another Active session is on it.
- Update when focus/status/PR/timer changes; ping every ~20–30m; unregister on wrap.
- Children pass the parent's **session_id** as `--parent-session` (not registry_id).

Do not invent a parallel presence store. Skill: `agent-registry`.
```

- [ ] **Step 2: Symlink + smoke**

```bash
ln -sf ~/projects/agent-registry/bin/agent-registry ~/projects/tjdsneto-setup/bin/agent-registry
cd ~/projects/tjdsneto-setup && ./ai/instructions/install.sh
AGENT_REGISTRY_PATH=/tmp/agent-registry-smoke.json
rm -f "$AGENT_REGISTRY_PATH"
export AGENT_REGISTRY_PATH
OUT=$(agent-registry register --type cursor --session-id smoke-1 --directory /tmp)
RID=$(printf '%s' "$OUT" | python3 -c 'import sys,json; print(json.load(sys.stdin)["registry_id"])')
agent-registry register --type claude --session-id smoke-2 --directory /tmp --parent-session smoke-1
agent-registry update "$RID" --status reviewing --pr-title "Demo" --pr-url "https://example.com/pr/1"
agent-registry list
agent-registry list --json | python3 -c 'import sys,json; d=json.load(sys.stdin); assert all("registry_id" not in x for x in d["active"]+d["stale"])'
agent-registry ping "$RID"
agent-registry prune
agent-registry unregister "$RID"
```

- [ ] **Step 3: Commit**

```bash
cd ~/projects/tjdsneto-setup
git add ai/instructions/claude/CLAUDE.md ai/instructions/cursor/user-rules.md bin/agent-registry
git commit -m "feat(agent-registry): global presence rule + bin symlink"
```

---

## Spec coverage self-check

| Spec requirement | Task |
|------------------|------|
| New repo + Python CLI | 1, 7, 8 |
| JSON store + flock + atomic | 2 |
| register / replace / parent_session | 3 |
| update fields + clear + ping + unregister | 4 |
| list Active/Stale, no registry_id, parent grouping | 5 |
| prune dry-run / --yes, 60m stale | 1 (constant), 6 |
| Exit codes 0/1/2/3, corrupt fail-closed | 2, 7 |
| AGENT_REGISTRY_PATH | 2, tests |
| Skill protocol | 9 |
| Global rule Claude + Cursor | 10 |
| bin symlink | 10 |
| GoFlow timer field | 4, 7 |
| update with no flags → error | 4, 7 |

**Placeholder scan:** none. Task 8/9 describe required README/skill content in prose where full paste would duplicate the CLI contract already in Tasks 3–7.

**Type consistency:** `registry_id` / `session_id` / `parent_session_id` / `goflow_timer_id` / `STATUSES` / exit constants aligned across tasks.
