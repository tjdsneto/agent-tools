# Agent Registry Dashboard & Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace destructive prune/unregister/replace with append-only `archive.jsonl`, and ship a localhost tabbed dashboard (Live | Archive) plus `archive`/`doctor`/`status` CLI.

**Architecture:** Archive writes happen only inside `ops` (same flock as live `registry.json`). A small `archive` module owns JSONL path/read/append/purge. Dashboard is stdlib `http.server` serving one static page + `/api/live` and `/api/archive`. Hooks (`ensure`/`end`) need no changes because they already call `ops`.

**Tech Stack:** Python 3 stdlib only (existing), pytest, argparse CLI. Spec: `docs/superpowers/specs/2026-09-25-agent-registry-dashboard-design.md`.

---

## File map

| File | Responsibility |
|------|----------------|
| `agent_registry/archive.py` | `archive_path`, `ArchiveEvent`, append/read/list/purge |
| `agent_registry/project.py` | `project_key(directory)` for grouping |
| `agent_registry/dashboard.py` | HTTP server + API handlers |
| `agent_registry/static/dashboard.html` | Single-page Live/Archive UI |
| `agent_registry/store.py` | Add `hold_lock()` context manager (shared flock) |
| `agent_registry/ops.py` | Archive on unregister/replace/prune; `live_views()` for API |
| `agent_registry/cli.py` | `archive`, `dashboard`, `doctor`, `status` subcommands |
| `agent_registry/constants.py` | Archive reasons, dashboard defaults |
| `agent_registry/format.py` | Human archive list formatting |
| `tests/test_archive.py` | Archive store tests |
| `tests/test_ops_archive.py` | Ops → archive integration |
| `tests/test_project.py` | Project key |
| `tests/test_dashboard.py` | API shapes / bind |
| `tests/test_cli_archive.py` | CLI archive/doctor/status |
| `tests/test_prune.py` | Update expectations (archive not delete) |
| `README.md` + skill in tjdsneto-setup | Docs |

---

### Task 1: Archive module + lock helper

**Files:**
- Create: `agent_registry/archive.py`
- Modify: `agent_registry/store.py`
- Modify: `agent_registry/constants.py`
- Test: `tests/test_archive.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_archive.py
from datetime import datetime, timezone, timedelta
from agent_registry import archive, ops, store
from agent_registry.models import Session


def test_archive_path_sibling_of_registry(tmp_registry):
    assert archive.archive_path() == tmp_registry.with_name("archive.jsonl")


def test_append_and_read_event(tmp_registry):
    s = ops.register(agent_type="cursor", session_id="a", directory="/p")
    archive.append_session(s, reason="unregister")
    events = archive.read_events()
    assert len(events) == 1
    assert events[0]["reason"] == "unregister"
    assert events[0]["session"]["registry_id"] == s.registry_id
    assert "archived_at" in events[0]


def test_read_events_missing_file_empty(tmp_registry):
    assert archive.read_events() == []


def test_read_events_corrupt_returns_empty(tmp_registry):
    archive.archive_path().write_text("not-json\n", encoding="utf-8")
    assert archive.read_events() == []


def test_purge_older_than(tmp_registry):
    s = ops.register(agent_type="cursor", session_id="old", directory="/p")
    archive.append_session(s, reason="unregister")
    path = archive.archive_path()
    # Rewrite first line with old timestamp
    line = path.read_text(encoding="utf-8").strip()
    import json
    obj = json.loads(line)
    obj["archived_at"] = "2020-01-01T00:00:00+00:00"
    path.write_text(json.dumps(obj) + "\n", encoding="utf-8")
    s2 = ops.register(agent_type="cursor", session_id="new", directory="/p2")
    archive.append_session(s2, reason="prune")
    removed = archive.purge_older_than(days=30, yes=True)
    assert len(removed) == 1
    assert removed[0]["session"]["session_id"] == "old"
    kept = archive.read_events()
    assert [e["session"]["session_id"] for e in kept] == ["new"]


def test_purge_requires_yes(tmp_registry):
    import pytest
    with pytest.raises(archive.ValidationError):
        archive.purge_older_than(days=1, yes=False)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/projects/agent-registry && source .venv/bin/activate && pytest tests/test_archive.py -v`  
Expected: FAIL (module/import errors)

- [ ] **Step 3: Add constants**

```python
# agent_registry/constants.py — append
ARCHIVE_REASONS = frozenset({"unregister", "prune", "replace"})
DASHBOARD_DEFAULT_PORT = 8765
```

- [ ] **Step 4: Add `hold_lock` to store.py**

```python
# agent_registry/store.py — add near top of imports if needed
from contextlib import contextmanager

@contextmanager
def hold_lock():
    """Exclusive flock on the live registry lock file (serializes live + archive writes)."""
    path = registry_path()
    lock_path = _lock_path(path)
    _ensure_parent(lock_path)
    with open(lock_path, "a+", encoding="utf-8") as lock_f:
        fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
```

Refactor `transact` / `save` to use `hold_lock()` internally so there is one lock implementation (optional cleanup; if refactor is risky, duplicate flock body once and note follow-up — prefer refactoring `transact` to:

```python
def transact(fn: Callable[[RegistryFile], T]) -> T:
    with hold_lock():
        reg = _read_registry(registry_path())
        result = fn(reg)
        _write_registry(registry_path(), reg)
        return result
```

- [ ] **Step 5: Implement `agent_registry/archive.py`**

```python
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_registry.constants import ARCHIVE_REASONS
from agent_registry.models import Session, now_iso
from agent_registry import store


class ValidationError(Exception):
    pass


class ArchiveIOError(Exception):
    pass


def archive_path() -> Path:
    return store.registry_path().with_name("archive.jsonl")


def append_session(session: Session, *, reason: str) -> dict[str, Any]:
    if reason not in ARCHIVE_REASONS:
        raise ValidationError(f"invalid archive reason: {reason}")
    event = {
        "archived_at": now_iso(),
        "reason": reason,
        "session": session.to_dict(),  # includes registry_id
    }
    path = archive_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, separators=(",", ":")) + "\n"
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
    except OSError as e:
        raise ArchiveIOError(str(e)) from e
    return event


def read_events() -> list[dict[str, Any]]:
    path = archive_path()
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    if not text.strip():
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            return []  # corrupt → empty per spec
        if not isinstance(obj, dict) or "reason" not in obj or "session" not in obj:
            return []
        out.append(obj)
    return out


def list_events(
    *, reason: str | None = None, limit: int | None = 100
) -> list[dict[str, Any]]:
    events = read_events()
    if reason is not None:
        if reason not in ARCHIVE_REASONS:
            raise ValidationError(f"invalid archive reason: {reason}")
        events = [e for e in events if e.get("reason") == reason]
    events = list(reversed(events))  # newest first
    if limit is not None:
        events = events[:limit]
    return events


def public_event(event: dict[str, Any]) -> dict[str, Any]:
    sess = dict(event.get("session") or {})
    sess.pop("registry_id", None)
    return {
        "archived_at": event.get("archived_at"),
        "reason": event.get("reason"),
        "session": sess,
    }


def purge_older_than(*, days: int, yes: bool = False) -> list[dict[str, Any]]:
    if days < 1:
        raise ValidationError("days must be >= 1")
    if not yes:
        raise ValidationError("purge requires --yes")
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400

    def _parse(ts: str) -> float:
        s = ts[:-1] + "+00:00" if ts.endswith("Z") else ts
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()

    with store.hold_lock():
        events = read_events()
        # If corrupt, read_events returned []; treat as nothing to purge
        keep: list[dict[str, Any]] = []
        removed: list[dict[str, Any]] = []
        for e in events:
            try:
                age_ok = _parse(e["archived_at"]) >= cutoff
            except (KeyError, TypeError, ValueError):
                removed.append(e)
                continue
            if age_ok:
                keep.append(e)
            else:
                removed.append(e)
        _write_all_atomic(keep)
        return [public_event(e) for e in removed]


def _write_all_atomic(events: list[dict[str, Any]]) -> None:
    path = archive_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(e, separators=(",", ":")) + "\n" for e in events)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".archive.", suffix=".tmp")
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
```

Note: `append_session` is called **inside** `ops` while `hold_lock`/`transact` is already held — do not take the lock again inside `append_session` (would deadlock on non-reentrant flock). Document that callers must hold the live lock.

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_archive.py -v`  
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add agent_registry/archive.py agent_registry/store.py agent_registry/constants.py tests/test_archive.py
git commit -m "feat: add archive.jsonl store with purge"
```

---

### Task 2: Wire archive into ops (unregister / replace / prune)

**Files:**
- Modify: `agent_registry/ops.py`
- Create: `tests/test_ops_archive.py`
- Modify: `tests/test_prune.py`

- [ ] **Step 1: Write failing ops archive tests**

```python
# tests/test_ops_archive.py
from datetime import datetime, timezone
from agent_registry import archive, ops, store


def test_unregister_appends_archive(tmp_registry):
    s = ops.register(agent_type="cursor", session_id="a", directory="/p")
    ops.unregister(s.registry_id)
    events = archive.read_events()
    assert len(events) == 1
    assert events[0]["reason"] == "unregister"
    assert events[0]["session"]["session_id"] == "a"
    assert store.load().sessions == []


def test_replace_archives_displaced(tmp_registry):
    first = ops.register(agent_type="cursor", session_id="a", directory="/old")
    ops.register(agent_type="cursor", session_id="a", directory="/new", replace=True)
    events = archive.read_events()
    assert len(events) == 1
    assert events[0]["reason"] == "replace"
    assert events[0]["session"]["registry_id"] == first.registry_id
    assert events[0]["session"]["directory"] == "/old"
    assert [x.directory for x in store.load().sessions] == ["/new"]


def test_prune_yes_archives_stale(tmp_registry):
    ops.register(agent_type="cursor", session_id="old", directory="/a")
    ops.register(agent_type="cursor", session_id="live", directory="/b")
    reg = store.load()
    for s in reg.sessions:
        if s.session_id == "old":
            s.last_ping = "2026-09-24T10:00:00+00:00"
    store.save(reg)
    now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    removed = ops.prune(dry_run=False, yes=True, now=now)
    assert [x["session_id"] for x in removed] == ["old"]
    assert "registry_id" not in removed[0]
    events = archive.read_events()
    assert len(events) == 1
    assert events[0]["reason"] == "prune"
    assert [s.session_id for s in store.load().sessions] == ["live"]


def test_prune_dry_run_does_not_archive(tmp_registry):
    ops.register(agent_type="cursor", session_id="old", directory="/a")
    reg = store.load()
    reg.sessions[0].last_ping = "2026-09-24T10:00:00+00:00"
    store.save(reg)
    now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    ops.prune(dry_run=True, yes=False, now=now)
    assert archive.read_events() == []
    assert len(store.load().sessions) == 1
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_ops_archive.py -v`  
Expected: FAIL (no archive lines yet)

- [ ] **Step 3: Patch `ops.register` replace branch**

Inside `_do_register`, when `existing and replace`:

```python
if existing and replace:
    from agent_registry import archive
    archive.append_session(existing, reason="replace")
    reg.sessions = [s for s in reg.sessions if s.session_id != session_id]
```

- [ ] **Step 4: Patch `ops.unregister`**

```python
def unregister(registry_id: str) -> None:
    def _do_unregister(reg: RegistryFile) -> None:
        sess = _find_by_registry_id(reg, registry_id)
        if not sess:
            raise UnknownRegistryIdError(registry_id)
        from agent_registry import archive
        archive.append_session(sess, reason="unregister")
        reg.sessions = [s for s in reg.sessions if s.registry_id != registry_id]

    store.transact(_do_unregister)
```

- [ ] **Step 5: Patch `ops.prune` yes path**

```python
def _do_prune(reg: RegistryFile) -> list[dict]:
    from agent_registry import archive
    removed_sessions = [s for s in reg.sessions if is_stale(s, now=now)]
    for s in removed_sessions:
        archive.append_session(s, reason="prune")
    removed = [public_view(s) for s in removed_sessions]
    reg.sessions = [s for s in reg.sessions if not is_stale(s, now=now)]
    return removed
```

- [ ] **Step 6: Map `ArchiveIOError` in CLI later; for now let it surface as OSError/IO — or re-raise as CorruptRegistryError-like. Prefer ops wrapping:**

```python
# in each append call site
try:
    archive.append_session(...)
except archive.ArchiveIOError as e:
    raise  # transact will not write if we raise before _write_registry — IMPORTANT
```

Critical: `store.transact` writes registry **after** `fn` returns. If append fails mid-fn before return, live file is not written — good. Order must be: append first, then mutate `reg.sessions`.

- [ ] **Step 7: Update `tests/test_prune.py` docstring/comments if they say “delete”; behavior of assertions on live registry stays the same**

- [ ] **Step 8: Run tests**

Run: `pytest tests/test_ops_archive.py tests/test_prune.py tests/test_ops.py -v`  
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add agent_registry/ops.py tests/test_ops_archive.py tests/test_prune.py
git commit -m "feat: archive sessions on unregister, replace, and prune"
```

---

### Task 3: `live_views` + project key helper

**Files:**
- Create: `agent_registry/project.py`
- Modify: `agent_registry/ops.py` (add `live_views`)
- Test: `tests/test_project.py`, `tests/test_ops_archive.py` (or `tests/test_list.py`)

- [ ] **Step 1: Failing tests**

```python
# tests/test_project.py
from agent_registry.project import project_key

def test_project_key_basename_fallback(tmp_path):
    d = tmp_path / "lindris"
    d.mkdir()
    assert project_key(str(d)) == "lindris"

def test_project_key_prefers_git_root(tmp_path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    nested = root / "packages" / "api"
    nested.mkdir(parents=True)
    assert project_key(str(nested)) == "repo"
```

```python
# add to tests/test_list.py or new test
def test_live_views_attention(tmp_registry):
    from datetime import datetime, timezone
    from agent_registry import ops, store
    a = ops.register(agent_type="cursor", session_id="ok", directory="/p/ok")
    ops.update(a.registry_id, status="working")
    b = ops.register(agent_type="cursor", session_id="blk", directory="/p/blk")
    ops.update(b.registry_id, status="blocked")
    c = ops.register(agent_type="cursor", session_id="old", directory="/p/old")
    reg = store.load()
    for s in reg.sessions:
        if s.session_id == "old":
            s.last_ping = "2026-09-24T10:00:00+00:00"
    store.save(reg)
    now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    views = ops.live_views(now=now)
    ids_att = {x["session_id"] for x in views["attention"]}
    ids_act = {x["session_id"] for x in views["active"]}
    ids_stale = {x["session_id"] for x in views["stale"]}
    assert ids_att == {"blk", "old"}
    assert "blk" not in ids_act
    assert "old" in ids_stale
    assert "ok" in ids_act
```

- [ ] **Step 2: Implement project.py**

```python
from __future__ import annotations
from pathlib import Path

KNOWN_ROOT_NAMES = frozenset({
    "projects", "Projects", "dev", "src", "Sites", "Local Sites", "work",
})

def project_key(directory: str) -> str:
    try:
        path = Path(directory).expanduser().resolve()
    except OSError:
        return Path(directory).name or directory
    cur = path if path.is_dir() else path.parent
    for p in [cur, *cur.parents]:
        if (p / ".git").exists():
            return p.name
    # if parent is a known roots folder, use basename
    if cur.parent.name in KNOWN_ROOT_NAMES:
        return cur.name
    return cur.name or str(path)
```

- [ ] **Step 3: Implement `ops.live_views`**

```python
def live_views(*, now: datetime | None = None) -> dict[str, list[dict]]:
    reg = store.load()
    active, stale, attention = [], [], []
    seen_attention: set[str] = set()
    for s in reg.sessions:
        view = public_view(s)
        view["project"] = project_key(s.directory)  # optional enrichment
        stale_flag = is_stale(s, now=now)
        blocked = s.status == "blocked"
        if blocked or stale_flag:
            if s.session_id not in seen_attention:
                attention.append(view)
                seen_attention.add(s.session_id)
        if stale_flag:
            stale.append(view)
        elif not blocked:
            active.append(view)
        # blocked+fresh: attention only, not active
    return {"active": active, "stale": stale, "attention": attention}
```

Keep `list_split` unchanged for CLI `list` (active/stale only, no project field required — or add project for consistency; prefer leave `list_split` as-is and use `live_views` for dashboard only).

- [ ] **Step 4: Run tests & commit**

```bash
pytest tests/test_project.py tests/test_list.py -v
git add agent_registry/project.py agent_registry/ops.py tests/test_project.py tests/test_list.py
git commit -m "feat: live_views attention band and project_key"
```

---

### Task 4: CLI `archive list|show|purge`

**Files:**
- Modify: `agent_registry/cli.py`
- Modify: `agent_registry/format.py`
- Test: `tests/test_cli_archive.py`

- [ ] **Step 1: Failing CLI tests** (use `main([...])` like existing `tests/test_cli.py`)

```python
# tests/test_cli_archive.py
import json
from agent_registry.cli import main
from agent_registry import ops, archive


def test_archive_list_json(tmp_registry, capsys):
    s = ops.register(agent_type="cursor", session_id="a", directory="/p")
    ops.unregister(s.registry_id)
    assert main(["archive", "list", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["events"][0]["reason"] == "unregister"
    assert "registry_id" not in data["events"][0]["session"]


def test_archive_show_and_full(tmp_registry, capsys):
    s = ops.register(agent_type="cursor", session_id="a", directory="/p")
    ops.unregister(s.registry_id)
    assert main(["archive", "show", "a"]) == 0
    pub = json.loads(capsys.readouterr().out)
    assert "registry_id" not in pub["session"]
    assert main(["archive", "show", "a", "--full"]) == 0
    full = json.loads(capsys.readouterr().out)
    assert full["session"]["registry_id"] == s.registry_id


def test_archive_purge_yes(tmp_registry, capsys):
    s = ops.register(agent_type="cursor", session_id="a", directory="/p")
    archive.append_session(s, reason="unregister")
    # force old timestamp
    import json as J
    p = archive.archive_path()
    obj = J.loads(p.read_text().strip())
    obj["archived_at"] = "2020-01-01T00:00:00+00:00"
    p.write_text(J.dumps(obj) + "\n")
    assert main(["archive", "purge", "--older-than", "30d", "--yes"]) == 0
    assert archive.read_events() == []
```

- [ ] **Step 2: Wire argparse**

Under `main` subparsers, add nested `archive` parser with subcommands `list`, `show`, `purge`. Parse `--older-than` as `30d` / `7d` → int days (reject bare numbers without `d` or accept both `30` and `30d`).

```python
p_arch = sub.add_parser("archive")
arch_sub = p_arch.add_subparsers(dest="archive_cmd", required=True)
p_al = arch_sub.add_parser("list")
p_al.add_argument("--json", action="store_true")
p_al.add_argument("--reason")
p_al.add_argument("--limit", type=int, default=100)
p_as = arch_sub.add_parser("show")
p_as.add_argument("session_id")
p_as.add_argument("--full", action="store_true")
p_ap = arch_sub.add_parser("purge")
p_ap.add_argument("--older-than", required=True)
p_ap.add_argument("--yes", action="store_true")
```

Handlers:

- `list`: `events = [archive.public_event(e) for e in archive.list_events(...)]`; JSON or `format_archive_list`
- `show`: find newest matching `session_id` in `read_events()`; exit 2 if missing; strip or full
- `purge`: parse days; `archive.purge_older_than(days=..., yes=args.yes)`

Catch `archive.ValidationError` → EXIT_USAGE; `archive.ArchiveIOError` → EXIT_IO.

- [ ] **Step 3: `format_archive_list` in format.py** — one line per event: `archived_at · reason · type · session_id · directory`

- [ ] **Step 4: pytest + commit**

```bash
pytest tests/test_cli_archive.py -v
git add agent_registry/cli.py agent_registry/format.py tests/test_cli_archive.py
git commit -m "feat(cli): archive list, show, and purge"
```

---

### Task 5: Dashboard HTTP API + static page

**Files:**
- Create: `agent_registry/dashboard.py`
- Create: `agent_registry/static/dashboard.html`
- Test: `tests/test_dashboard.py`
- Modify: `agent_registry/cli.py`

- [ ] **Step 1: API tests with `HTTPServer` on ephemeral port**

```python
# tests/test_dashboard.py
import json
import threading
import urllib.request
from agent_registry import ops
from agent_registry.dashboard import make_server


def test_api_live_and_archive(tmp_registry):
    s = ops.register(agent_type="cursor", session_id="a", directory="/Users/x/projects/lindris")
    ops.update(s.registry_id, status="blocked", summary="need input")
    ops.unregister(s.registry_id)
    httpd = make_server("127.0.0.1", 0)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        live = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/live").read())
        assert "active" in live and "stale" in live and "attention" in live
        arch = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/archive").read())
        assert arch["events"][0]["reason"] == "unregister"
        assert "registry_id" not in arch["events"][0]["session"]
        home = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode()
        assert "agent-registry" in home
    finally:
        httpd.shutdown()
```

- [ ] **Step 2: Implement `dashboard.py`**

Use `http.server.BaseHTTPRequestHandler` subclass:

- `GET /` → read `Path(__file__).parent / "static" / "dashboard.html"`
- `GET /api/live` → `json.dumps(ops.live_views())`
- `GET /api/archive` → parse query `limit`, `reason`; public events
- Other → 404
- `make_server(host, port)` returns `HTTPServer`
- `run_dashboard(host, port, open_browser=True)` — if host not in `{"127.0.0.1", "localhost", "::1"}`, print loud warning to stderr

- [ ] **Step 3: Implement `static/dashboard.html`**

Single file, no CDN:

- Tabs Live | Archive; remember tab + “group by project” in `localStorage`
- Live: render `attention`, then `active` (grouped by `project` when enabled)
- Archive: reason chips, rows newest first
- Poll every 5s; `document.addEventListener('visibilitychange', ...)` pause when hidden
- Humanize ages client-side from ISO (`2m ago`, `yesterday`, etc. — simple JS helper)
- Banner on fetch errors; keep last good JSON in memory
- Minimal CSS (system fonts, dark-friendly neutrals — no purple gradients)

- [ ] **Step 4: CLI `dashboard`**

```python
p_dash = sub.add_parser("dashboard")
p_dash.add_argument("--port", type=int, default=None)  # None → DASHBOARD_DEFAULT_PORT
p_dash.add_argument("--host", default="127.0.0.1")
p_dash.add_argument("--no-open", action="store_true")
```

```python
if args.cmd == "dashboard":
    from agent_registry.dashboard import run_dashboard
    run_dashboard(
        host=args.host,
        port=args.port or DASHBOARD_DEFAULT_PORT,
        open_browser=not args.no_open,
    )
    return EXIT_OK
```

If port in use, try next ports up to +10 or exit EXIT_IO with message.

- [ ] **Step 5: pytest + manual smoke**

```bash
pytest tests/test_dashboard.py -v
# manual: AGENT_REGISTRY_PATH=/tmp/r.json agent-registry dashboard --no-open
```

- [ ] **Step 6: Commit**

```bash
git add agent_registry/dashboard.py agent_registry/static/dashboard.html agent_registry/cli.py tests/test_dashboard.py
git commit -m "feat: localhost dashboard with live and archive tabs"
```

---

### Task 6: `doctor` and `status`

**Files:**
- Create: `agent_registry/doctor.py` (or functions in a small module)
- Modify: `agent_registry/cli.py`
- Test: `tests/test_cli_archive.py` (extend) or `tests/test_doctor.py`

- [ ] **Step 1: Tests**

```python
def test_doctor_ok(tmp_registry, capsys):
    from agent_registry.cli import main
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "registry" in out.lower()
    assert "archive" in out.lower()

def test_status_counts(tmp_registry, capsys):
    from agent_registry.cli import main
    from agent_registry import ops
    s = ops.register(agent_type="cursor", session_id="a", directory="/p")
    ops.unregister(s.registry_id)
    assert main(["status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["archived"] == 1
    assert data["active"] + data["stale"] == 0
```

- [ ] **Step 2: Implement**

`doctor`: print checks — live path exists or creatable, lock acquirable via `hold_lock`, archive path sibling, sidecar dir under `data_dir()`, exit 0 if all ok else EXIT_IO.

`status`: `{active, stale, archived, registry_path, archive_path}` via `list_split` + `len(read_events())`; `--json` flag.

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(cli): doctor and status commands"
```

---

### Task 7: Docs + skill update

**Files:**
- Modify: `README.md` (agent-registry)
- Modify: `~/projects/tjdsneto-setup/ai/skills/shared/agent-registry/SKILL.md` (and Cursor mirror if separate)

- [ ] **Step 1: README** — document archive.jsonl, prune→archive, `archive` commands, `dashboard`, `doctor`, `status`; note hooks unchanged; loopback warning.

- [ ] **Step 2: Skill** — replace “humans clean up with prune” with archive semantics; mention dashboard for humans; keep agent protocol on ensure/heartbeat/end/update/list.

- [ ] **Step 3: Commit each repo**

```bash
# agent-registry
git commit -m "docs: archive and dashboard in README"

# tjdsneto-setup (master only)
git commit -m "docs(skill): agent-registry archive instead of prune delete"
```

---

### Task 8: Full regression

- [ ] **Step 1: Run full suite**

```bash
cd ~/projects/agent-registry && source .venv/bin/activate && pytest -v
```

Expected: all PASS

- [ ] **Step 2: Manual checklist**

1. `agent-registry ensure ...` / `end ...` → archive line with reason unregister  
2. `agent-registry prune --yes` with aged session → archive reason prune  
3. `agent-registry dashboard` opens UI; Live attention + Archive tabs work; hide tab pauses network in DevTools  
4. Non-loopback: `dashboard --host 0.0.0.0` prints warning  

- [ ] **Step 3: Final commit if any fixes**

---

## Spec coverage checklist

| Spec item | Task |
|-----------|------|
| archive.jsonl event shape | 1 |
| unregister/replace/prune append | 2 |
| fail op if append fails (before live write) | 2 |
| archive list/show/purge CLI | 4 |
| live_views attention + no duplicate blocked | 3 |
| project_key grouping | 3 + 5 UI |
| dashboard tabs + poll + visibility pause | 5 |
| loopback + HOST warning | 5 |
| doctor/status | 6 |
| README/skill | 7 |
| hooks unchanged | 2 (implicit) |
| no SQLite / no UI mutations | non-goals |

## Self-review notes

- No TBD placeholders.
- `append_session` must not call `hold_lock` (deadlock); only `purge` and live `transact` take the lock.
- `list_split` remains for CLI `list`; dashboard uses `live_views`.
- Corrupt archive read → `[]`; corrupt on append → `ArchiveIOError`, op aborts.
