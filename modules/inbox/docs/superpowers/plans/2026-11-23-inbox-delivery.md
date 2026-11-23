# Agent Inbox — Slice 2: Delivery — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `agt inbox serve` delivers answers and follow-ups to the asking session through `agt registry wake`, holds delivery when the session cannot hear it, and refuses answers that cannot be delivered.

**Architecture:** Slice 1 already wakes a blocked `wait` via `LISTEN/NOTIFY` and stores `waiter_pid`. This slice adds a long-running dispatcher on the same channel. It does not send Telegram, macOS notifications, or HTML. Those are slices 3 and 4. `serve` is one process; later slices add HTTP and the notifier onto the loop this plan creates.

**Tech Stack:** Python 3.14, psycopg 3.3, Postgres 17 on `localhost:5433`, `agt registry resolve` / `agt registry wake`, `claude-budget`.

**Spec:** [`../specs/2026-11-23-agent-inbox-design.md`](../specs/2026-11-23-agent-inbox-design.md) sections Reachability, Delivery, Failure rules. Slice 1 plan: [`2026-11-23-inbox-core.md`](2026-11-23-inbox-core.md).

**Work on:** `/Users/tjdsneto/projects/agent-tools` branch `main`. Do not commit the unrelated dirty files under `modules/registry/`.

---

## What this slice leaves out

- No web UI, no SSE, no Tailscale (slice 3).
- No Telegram, macOS notification, `agt say`, quiet hours, or backups (slice 4).
- The "3 entries are answerable again" push is slice 4. This slice only flips held entries back to deliverable and records that on the entry.
- Telegram buttons stay parked. Nothing here renders a keyboard.

## Reachability, as the code actually is

`agt registry resolve <id>` prints JSON with `alive`, `agent_type`, `peer_name`. `agt registry wake <id> --message <file>` prints JSON with `result` (`landed`, `already_awake`, `held`, `undelivered`, `refused`) and `mode` (`nudge` or `resume`). Cursor wake is always a headless resume; that is already inside `agent_registry.transport.wake`. Claude resume already passes `--dangerously-skip-permissions` there. Do not reimplement either.

Token checks:

- **Claude.** `claude-budget check` prints a session-usage percent, or nothing when `/usage` is unreadable. `claude-budget reset-at` prints `<epoch> <YYYY-MM-DD HH:MM>` or nothing. Percent `>= 88` means held (the same threshold `claude-budget wait` uses). An empty check is **not** held: a failed poll must not block answers.
- **Codex and Cursor.** The registry has no pre-wake rate-limit function for them. `usage.claude_interrupt_reason` is Claude-only. Held for these engines means the previous wake on this entry returned `held`. A later wake that returns `landed` or `already_awake` clears it. There is no "answerable at HH:MM" for them unless that previous result included nothing — so `reachable_at` stays null and `serve` retries them on its normal poll.

## File structure

| File | Responsibility |
|---|---|
| `modules/inbox/src/agent_inbox/schema.sql` | add `delivery jsonb` on `entries` |
| `modules/inbox/src/agent_inbox/db.py` | always apply the additive migration |
| `modules/inbox/src/agent_inbox/reach.py` | resolve + budget → 🟢🔵🟡🔴 |
| `modules/inbox/src/agent_inbox/dispatch.py` | message file, one wake, attempt accounting |
| `modules/inbox/src/agent_inbox/serve.py` | LISTEN loop, expiry, dead-waiter fallback |
| `modules/inbox/src/agent_inbox/store.py` | expose `delivery`; answer refuses 🟡/🔴 |
| `modules/inbox/src/agent_inbox/cli.py` | `serve` subcommand |
| `modules/inbox/launchd/com.tjdsneto.agent-inbox.plist` | login agent |
| `install.sh` | install and boot that agent |

`delivery` JSON shape:

```json
{
  "attempts": 0,
  "results": [],
  "reachability": "live",
  "reachable_at": null,
  "delivered_seq": 0,
  "headless": false
}
```

`results[]` items are `{"at", "result", "mode"}`. `delivered_seq` is the last follow-up seq already sent. `headless` is true when the successful wake was a Cursor resume.

---

### Task 1: Delivery column

**Files:**
- Modify: `modules/inbox/src/agent_inbox/schema.sql`
- Modify: `modules/inbox/src/agent_inbox/db.py`
- Modify: `modules/inbox/src/agent_inbox/store.py` (`_shape` only)
- Test: `modules/inbox/tests/test_db.py`

- [ ] **Step 1: Failing test**

Append to `tests/test_db.py`:

```python
def test_existing_database_gains_delivery_column(conn):
    conn.execute("ALTER TABLE entries DROP COLUMN IF EXISTS delivery")
    db.ensure_schema(conn)
    row = conn.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'entries' AND column_name = 'delivery'
        """
    ).fetchone()
    assert row is not None
```

The current `ensure_schema` returns as soon as `events` exists, so this fails.

- [ ] **Step 2: Schema**

In `schema.sql`, add this column to `entries` (after `waiter_pid`):

```sql
    delivery      jsonb NOT NULL DEFAULT '{}'::jsonb
```

- [ ] **Step 3: Migration that runs on databases slice 1 already created**

Replace `ensure_schema` with:

```python
MIGRATION = "ALTER TABLE entries ADD COLUMN IF NOT EXISTS delivery jsonb NOT NULL DEFAULT '{}'::jsonb"


def ensure_schema(conn: psycopg.Connection) -> None:
    missing = conn.execute("SELECT to_regclass('events') AS t").fetchone()["t"] is None
    if not missing:
        conn.execute(MIGRATION)
        return
    conn.execute("SELECT pg_advisory_lock(%s)", (SCHEMA_LOCK,))
    try:
        if conn.execute("SELECT to_regclass('events') AS t").fetchone()["t"] is None:
            conn.execute(schema_sql())
        conn.execute(MIGRATION)
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (SCHEMA_LOCK,))
```

`schema.sql` already contains the column, so the migration is a no-op on a fresh database and the fix on a slice-1 database.

- [ ] **Step 4: Show it on get**

In `_shape`, add `"delivery": row.get("delivery") or {}` next to `waiter_pid`. `row.get` matters because a test that selects before the migration is not the path here; every read goes through a connection that migrated.

- [ ] **Step 5: Tests**

Run: `modules/inbox/.venv/bin/python -m pytest modules/inbox/tests/test_db.py modules/inbox/tests/test_store_entries.py -q`

Expected: all passed.

- [ ] **Step 6: Commit**

```bash
git add modules/inbox/src/agent_inbox/schema.sql modules/inbox/src/agent_inbox/db.py modules/inbox/src/agent_inbox/store.py modules/inbox/tests/test_db.py
git commit -m "feat(inbox): store a delivery record on each entry"
```

Do not stage `modules/registry/**`.

---

### Task 2: Reachability

**Files:**
- Create: `modules/inbox/src/agent_inbox/reach.py`
- Test: `modules/inbox/tests/test_reach.py`

- [ ] **Step 1: Failing tests**

```python
from agent_inbox.reach import Reach, classify


def test_live_resumable_and_missing():
    assert classify({"alive": True, "agent_type": "claude", "peer_name": "p"}, budget=None, last=None).status == "live"
    assert classify({"alive": False, "agent_type": "codex"}, budget=None, last=None).status == "resumable"
    assert classify(None, budget=None, last=None).status == "unreachable"


def test_claude_without_an_address_is_unreachable():
    view = {"alive": True, "agent_type": "claude", "peer_name": None}
    assert classify(view, budget=None, last=None).status == "unreachable"


def test_claude_budget_holds_with_reset():
    got = classify({"alive": True, "agent_type": "claude", "peer_name": "p"}, budget=(90, "2026-11-23T19:00:00-03:00"), last=None)
    assert got.status == "held" and got.reachable_at == "2026-11-23T19:00:00-03:00"


def test_unreadable_budget_does_not_hold():
    view = {"alive": True, "agent_type": "claude", "peer_name": "p"}
    assert classify(view, budget=(None, None), last=None).status == "live"


def test_cursor_is_resumable_even_when_alive_flag_is_false():
    assert classify({"alive": False, "agent_type": "cursor"}, budget=None, last=None).status == "resumable"


def test_previous_held_wake_holds_codex():
    got = classify({"alive": False, "agent_type": "codex"}, budget=None, last="held")
    assert got.status == "held" and got.reachable_at is None
```

- [ ] **Step 2: Implement**

`modules/inbox/src/agent_inbox/reach.py`:

```python
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass

HELD_PCT = 88


@dataclass(frozen=True)
class Reach:
    status: str  # live, resumable, held, unreachable
    agent_type: str | None = None
    reachable_at: str | None = None
    headless: bool = False


def classify(view: dict | None, *, budget: tuple[int | None, str | None] | None, last: str | None) -> Reach:
    if not view or not view.get("agent_type"):
        return Reach("unreachable")
    agent = view["agent_type"]
    if agent == "claude" and view.get("alive") and not view.get("peer_name"):
        return Reach("unreachable", agent)
    if agent == "claude" and budget and budget[0] is not None and budget[0] >= HELD_PCT:
        return Reach("held", agent, reachable_at=budget[1])
    if agent != "claude" and last == "held":
        return Reach("held", agent)
    if agent == "cursor":
        return Reach("resumable", agent, headless=True)
    if view.get("alive"):
        return Reach("live", agent)
    return Reach("resumable", agent)


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, timeout=30)


def resolve(session_id: str) -> dict | None:
    proc = _run(["agt", "registry", "resolve", session_id])
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def claude_budget() -> tuple[int | None, str | None]:
    """Percent and ISO reset, or (None, None) when the poll cannot be read."""
    check = _run(["claude-budget", "check"])
    raw = check.stdout.strip()
    pct = int(raw) if raw.isdigit() else None
    reset = _run(["claude-budget", "reset-at"])
    parts = reset.stdout.split()
    when = None
    if len(parts) >= 3 and parts[0].isdigit():
        when = parts[1] + "T" + parts[2] + ":00"
    return pct, when


def for_entry(entry: dict) -> Reach:
    sid = (entry.get("asker") or {}).get("session_id")
    if not sid:
        return Reach("unreachable")
    view = resolve(sid)
    budget = claude_budget() if (view or {}).get("agent_type") == "claude" or entry["asker"].get("engine") == "claude" else None
    last = None
    results = (entry.get("delivery") or {}).get("results") or []
    if results:
        last = results[-1].get("result")
    return classify(view, budget=budget, last=last)
```

`reset-at` prints local `YYYY-MM-DD HH:MM` without a timezone. Store that clock time as written; slice 3 displays it as `~HH:MM`. Do not invent a UTC conversion.

- [ ] **Step 3: Tests and commit**

Run: `modules/inbox/.venv/bin/python -m pytest modules/inbox/tests/test_reach.py -q`

```bash
git add modules/inbox/src/agent_inbox/reach.py modules/inbox/tests/test_reach.py
git commit -m "feat(inbox): classify whether a session can hear a delivery"
```

---

### Task 3: Dispatch one entry

**Files:**
- Create: `modules/inbox/src/agent_inbox/dispatch.py`
- Test: `modules/inbox/tests/test_dispatch.py`

- [ ] **Step 1: Failing tests**

```python
import json

from agent_inbox import store
from agent_inbox.dispatch import dispatch_entry, render_message
from agent_inbox.validate import validate_request

CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}


def _ask(conn):
    req = validate_request({"title": "Which split?", "control": CHOICE}, "ask")
    return store.create_entry(conn, "ask", req, engine="claude", session_id="s-1")


def test_message_shape():
    text = render_message(
        {"id": "ib-7k3q", "title": "Which split?", "answer": {"value": "b", "comment": "thin", "via": "web", "at": "t"}},
        {"event": "answer", "value": "b", "comment": "thin", "via": "web", "at": "t"},
    )
    assert 'Inbox answer for ib-7k3q ("Which split?")' in text
    assert "Comment: thin" in text
    payload = json.loads(text.strip().splitlines()[-2])
    assert payload["entry"] == "ib-7k3q" and payload["value"] == "b"
    assert text.strip().endswith("Full entry: agt inbox get ib-7k3q")


def test_skips_a_live_waiter(conn, monkeypatch):
    e = _ask(conn)
    store.answer(conn, e["id"], "b", via="web")
    store.set_waiter(conn, e["id"], 1)
    monkeypatch.setattr("agent_inbox.dispatch.pid_alive", lambda pid: True)
    called = {}
    monkeypatch.setattr("agent_inbox.dispatch.wake", lambda *a, **k: called.setdefault("n", 1))
    assert dispatch_entry(conn, e["id"]) is None
    assert called == {}


def test_dead_waiter_falls_through_to_wake(conn, monkeypatch, tmp_path):
    e = _ask(conn)
    store.answer(conn, e["id"], "a", via="cli")
    store.set_waiter(conn, e["id"], 999999)
    monkeypatch.setattr("agent_inbox.dispatch.pid_alive", lambda pid: False)
    monkeypatch.setattr("agent_inbox.dispatch.reach_for", lambda entry: type("R", (), {"status": "resumable", "reachable_at": None, "headless": False})())
    monkeypatch.setattr("agent_inbox.dispatch.wake", lambda sid, message: {"result": "landed", "mode": "resume"})
    out = dispatch_entry(conn, e["id"])
    assert out == "delivered"
    got = store.get_entry(conn, e["id"])
    assert got["state"] == "delivered"
    assert got["waiter_pid"] is None
    assert got["delivery"]["attempts"] == 1


def test_third_failure_marks_undelivered(conn, monkeypatch):
    e = _ask(conn)
    store.answer(conn, e["id"], "a", via="cli")
    monkeypatch.setattr("agent_inbox.dispatch.reach_for", lambda entry: type("R", (), {"status": "resumable", "reachable_at": None, "headless": False})())
    monkeypatch.setattr("agent_inbox.dispatch.wake", lambda sid, message: {"result": "undelivered", "mode": "resume"})
    for _ in range(3):
        dispatch_entry(conn, e["id"])
    assert store.get_entry(conn, e["id"])["state"] == "undelivered"


def test_held_does_not_burn_an_attempt(conn, monkeypatch):
    e = _ask(conn)
    store.answer(conn, e["id"], "a", via="cli")
    monkeypatch.setattr(
        "agent_inbox.dispatch.reach_for",
        lambda entry: type("R", (), {"status": "held", "reachable_at": "2026-11-23T19:00:00", "headless": False})(),
    )
    assert dispatch_entry(conn, e["id"]) == "held"
    got = store.get_entry(conn, e["id"])
    assert got["state"] == "answered"
    assert got["delivery"]["attempts"] == 0
    assert got["delivery"]["reachability"] == "held"
```

- [ ] **Step 2: Implement**

`modules/inbox/src/agent_inbox/dispatch.py`:

```python
from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from agent_inbox import store
from agent_inbox.reach import Reach, for_entry

MAX_ATTEMPTS = 3


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def reach_for(entry: dict) -> Reach:
    return for_entry(entry)


def render_message(entry: dict, event: dict) -> str:
    label = "answer" if event["event"] == "answer" else "follow-up"
    value = event.get("value", event.get("text", ""))
    lines = [f'Inbox {label} for {entry["id"]} ("{entry["title"]}"): {value}']
    if event.get("comment"):
        lines.append(f"Comment: {event['comment']}")
    lines.append(json.dumps({"entry": entry["id"], **event}, default=str))
    lines.append(f"Full entry: agt inbox get {entry['id']}")
    return "\n".join(lines) + "\n"


def wake(session_id: str, message: str) -> dict:
    path = Path(os.environ.get("TMPDIR", "/tmp")) / f"inbox-{session_id}.txt"
    path.write_text(message)
    import subprocess
    proc = subprocess.run(
        ["agt", "registry", "wake", session_id, "--message", str(path)],
        capture_output=True, text=True, timeout=120,
    )
    try:
        return json.loads(proc.stdout) if proc.stdout.strip() else {"result": "undelivered", "mode": None}
    except json.JSONDecodeError:
        return {"result": "undelivered", "mode": None, "error": proc.stderr[-400:]}


def _save(conn, entry_id: str, delivery: dict, *, state: str | None = None) -> None:
    if state:
        conn.execute(
            "UPDATE entries SET delivery = %s, state = %s, waiter_pid = NULL, updated_at = now() WHERE id = %s",
            (Jsonb(delivery), state, entry_id),
        )
    else:
        conn.execute(
            "UPDATE entries SET delivery = %s, updated_at = now() WHERE id = %s",
            (Jsonb(delivery), entry_id),
        )


def dispatch_entry(conn: psycopg.Connection, entry_id: str) -> str | None:
    """Deliver the pending answer or follow-up. Return the outcome, or None when a live waiter owns it."""
    entry = store.get_entry(conn, entry_id)
    if entry["kind"] != "ask":
        return None
    pid = entry.get("waiter_pid")
    if pid and pid_alive(pid):
        return None
    if pid:
        store.clear_waiter(conn, entry_id, pid)
        entry = store.get_entry(conn, entry_id)
    delivery = dict(entry.get("delivery") or {})
    delivery.setdefault("attempts", 0)
    delivery.setdefault("results", [])
    delivery.setdefault("delivered_seq", 0)
    reach = reach_for(entry)
    delivery["reachability"] = reach.status
    delivery["reachable_at"] = reach.reachable_at
    if reach.status in ("held", "unreachable"):
        _save(conn, entry_id, delivery)
        return reach.status
    event = _pending(entry, delivery)
    if event is None:
        return None
    result = wake(entry["asker"]["session_id"], render_message(entry, event))
    ok = result.get("result") in {"landed", "already_awake"}
    delivery["results"] = [*delivery["results"], {"at": store._now_iso(), "result": result.get("result"), "mode": result.get("mode")}]
    if ok:
        if event["event"] == "followup":
            delivery["delivered_seq"] = event["seq"]
        delivery["headless"] = bool(reach.headless)
        _save(conn, entry_id, delivery, state="delivered" if event["event"] == "answer" else None)
        return "delivered"
    delivery["attempts"] = delivery["attempts"] + 1
    state = "undelivered" if delivery["attempts"] >= MAX_ATTEMPTS else None
    _save(conn, entry_id, delivery, state=state)
    return "undelivered" if state else "retry"


def _pending(entry: dict, delivery: dict) -> dict | None:
    if entry["state"] == "answered" and entry.get("answer"):
        return {"event": "answer", **entry["answer"]}
    after = delivery.get("delivered_seq") or 0
    for item in entry.get("thread") or []:
        if item["type"] == "followup" and item["seq"] > after:
            return {"event": "followup", "seq": item["seq"], "text": item.get("text"), "via": item.get("via")}
    return None
```

A follow-up on an already `delivered` question stays `delivered` and only advances `delivered_seq`. An answer moves `answered` → `delivered`.

- [ ] **Step 3: Run and commit**

Run: `modules/inbox/.venv/bin/python -m pytest modules/inbox/tests/test_dispatch.py -q`

```bash
git add modules/inbox/src/agent_inbox/dispatch.py modules/inbox/tests/test_dispatch.py
git commit -m "feat(inbox): deliver an answer or follow-up through registry wake"
```

---

### Task 4: Answer gate

**Files:**
- Modify: `modules/inbox/src/agent_inbox/store.py` (`answer`)
- Test: `modules/inbox/tests/test_store_answer.py`

- [ ] **Step 1: Failing test**

```python
def test_answer_refuses_when_the_session_cannot_hear(conn, monkeypatch):
    e = make_ask(conn)
    monkeypatch.setattr(
        "agent_inbox.reach.for_entry",
        lambda entry: type("R", (), {"status": "held", "reachable_at": "19:00"})(),
    )
    with pytest.raises(ConflictError, match="held"):
        store.answer(conn, e["id"], "a", via="web")
    assert store.get_entry(conn, e["id"])["state"] == "open"
```

Inside `answer`, import `for_entry` at the call (`from agent_inbox.reach import for_entry`) so the patch path above is the one that runs. Pass `{"asker": {...}, "delivery": row.get("delivery") or {}}`.

- [ ] **Step 2: Gate**

At the top of the transaction in `answer`, after the open-state check and before `validate_answer`:

```python
        from agent_inbox.reach import for_entry as reach_for
        asker = {k: row[k] for k in ("engine", "model", "session_id", "cwd", "project", "script")}
        reach = reach_for({"asker": asker, "delivery": row.get("delivery") or {}})
        if reach.status in ("held", "unreachable"):
            when = f" until {reach.reachable_at}" if reach.reachable_at else ""
            raise ConflictError(f"{entry_id} is {reach.status}{when}")
```

`cli` already maps `ConflictError` to exit 4.

- [ ] **Step 3: Keep the existing answer tests on a session that can hear**

`store.answer` now calls `for_entry`. Every current test uses `session_id="s-1"`, which does not resolve, so the gate would reject them. Add this autouse fixture to `tests/test_store_answer.py`, `tests/test_dispatch.py`, `tests/test_serve.py`, `tests/test_store_thread.py`, `tests/test_store_states.py`, `tests/test_cli.py`, and `tests/test_waiting.py`:

```python
import pytest

from agent_inbox.reach import Reach


@pytest.fixture(autouse=True)
def reachable(monkeypatch):
    monkeypatch.setattr("agent_inbox.reach.for_entry", lambda entry: Reach("resumable"))
```

The new refusal test overrides `agent_inbox.store`'s lookup. Because `answer` imports `for_entry` inside the function (`from agent_inbox.reach import for_entry`), patching `agent_inbox.reach.for_entry` is the one that works. The refusal test patches that same path with a held `Reach` and does not use the name `agent_inbox.store.reach_for`.

- [ ] **Step 4: Run and commit**

Run:

`modules/inbox/.venv/bin/python -m pytest modules/inbox/tests/test_store_answer.py modules/inbox/tests/test_dispatch.py -q`

```bash
git add modules/inbox/src/agent_inbox/store.py modules/inbox/tests/test_store_answer.py
git commit -m "feat(inbox): refuse an answer the session cannot hear"
```

---

### Task 5: Serve loop and expiry

**Files:**
- Create: `modules/inbox/src/agent_inbox/serve.py`
- Modify: `modules/inbox/src/agent_inbox/cli.py`
- Test: `modules/inbox/tests/test_serve.py`

- [ ] **Step 1: Failing tests**

```python
from datetime import datetime, timedelta, timezone

from agent_inbox import db, serve, store
from agent_inbox.validate import validate_request

CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}


def test_expiry_closes_open_questions_only(conn):
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    req = validate_request({"title": "t", "control": CHOICE, "expires_at": past}, "ask")
    e = store.create_entry(conn, "ask", req, engine="claude", session_id="s-1")
    info = store.create_entry(conn, "post", validate_request({"title": "i", "expires_at": past}, "post"), script="x")
    n = serve.expire_due(conn)
    assert n == 1
    assert store.get_entry(conn, e["id"])["state"] == "expired"
    assert store.get_entry(conn, info["id"])["state"] == "unread"


def test_sweep_dispatches_answered_entries(conn, monkeypatch):
    req = validate_request({"title": "t", "control": CHOICE}, "ask")
    e = store.create_entry(conn, "ask", req, engine="claude", session_id="s-1")
    store.answer(conn, e["id"], "a", via="cli")
    seen = []
    monkeypatch.setattr("agent_inbox.serve.dispatch_entry", lambda c, i: seen.append(i) or "delivered")
    serve.sweep(conn)
    assert seen == [e["id"]]
```

`store.answer` in this test calls the real reachability command. Point `AGENT_INBOX` tests at a fake by monkeypatching `agent_inbox.reach.for_entry` to `Reach("resumable")` at the start of the test, or the answer gate will shell out. Do that monkeypatch in the test before `store.answer`.

- [ ] **Step 2: Implement**

```python
from __future__ import annotations

import time

import psycopg

from agent_inbox import db
from agent_inbox.constants import NOTIFY_CHANNEL
from agent_inbox.dispatch import dispatch_entry


def expire_due(conn: psycopg.Connection) -> int:
    rows = conn.execute(
        """
        UPDATE entries SET state = 'expired', updated_at = now()
        WHERE kind = 'ask' AND state = 'open' AND expires_at IS NOT NULL AND expires_at <= now()
        RETURNING id
        """
    ).fetchall()
    for row in rows:
        conn.execute(
            "INSERT INTO events (entry_id, type, body) VALUES (%s, 'state', %s)",
            (row["id"], psycopg.types.json.Jsonb({"from": "open", "to": "expired"})),
        )
    return len(rows)


def sweep(conn: psycopg.Connection) -> None:
    expire_due(conn)
    rows = conn.execute(
        """
        SELECT id FROM entries
        WHERE kind = 'ask' AND state IN ('answered', 'delivered')
        ORDER BY updated_at
        """
    ).fetchall()
    for row in rows:
        dispatch_entry(conn, row["id"])


def run_once() -> None:
    with db.connect() as conn:
        sweep(conn)


def run(poll: float = 5.0) -> None:
    conn = db.connect()
    conn.execute(f"LISTEN {NOTIFY_CHANNEL}")
    try:
        while True:
            sweep(conn)
            for _ in conn.notifies(timeout=poll, stop_after=1):
                break
    finally:
        conn.close()
```

Sweeping `delivered` rows is what picks up a follow-up after the answer was already delivered. `dispatch_entry` returns immediately when nothing is pending.

- [ ] **Step 3: CLI**

Add a `serve` subparser with no arguments. In `_dispatch`, before the `with db.connect()` block:

```python
    if cmd == "serve":
        from agent_inbox.serve import run
        run()
        return {"ok": True}, EXIT_OK
```

`run` does not return. That is the LaunchAgent process.

- [ ] **Step 4: Run and commit**

`modules/inbox/.venv/bin/python -m pytest modules/inbox/tests -q`

```bash
git add modules/inbox/src/agent_inbox/serve.py modules/inbox/src/agent_inbox/cli.py modules/inbox/tests/test_serve.py
git commit -m "feat(inbox): serve loop delivers on notify and expires open questions"
```

---

### Task 6: LaunchAgent

**Files:**
- Create: `modules/inbox/launchd/com.tjdsneto.agent-inbox.plist`
- Modify: `install.sh`
- Modify: `modules/inbox/README.md` (one section, "Delivery")

- [ ] **Step 1: Plist**

Same shape as `modules/glue-miner/launchd/com.tjdsneto.glue-miner.plist`, with `__ROOT__` replaced by `install.sh`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>com.tjdsneto.agent-inbox</string>
	<key>ProgramArguments</key>
	<array>
		<string>__ROOT__/modules/inbox/bin/agent-inbox</string>
		<string>serve</string>
	</array>
	<key>RunAtLoad</key>
	<true/>
	<key>KeepAlive</key>
	<true/>
	<key>StandardOutPath</key>
	<string>__ROOT__/modules/inbox/tmp/serve.log</string>
	<key>StandardErrorPath</key>
	<string>__ROOT__/modules/inbox/tmp/serve.log</string>
	<key>WorkingDirectory</key>
	<string>__ROOT__</string>
</dict>
</plist>
```

`modules/inbox/tmp/` is already gitignored by `modules/**/tmp/`.

- [ ] **Step 2: install.sh**

After the glue-miner block, if the plist source exists: `mkdir -p` the log dir, `sed` `__ROOT__`, `launchctl bootout` the old label (ignore failure), `launchctl bootstrap gui/$uid`. Do not boot it twice in one install without the bootout.

- [ ] **Step 3: README**

Add a Delivery section: `agt inbox serve` is started at login by `com.tjdsneto.agent-inbox`. An answer while `waiter_pid` is a live process is that process's return value, not a second wake. Three failed wakes move the entry to `undelivered`. Held Claude sessions wait for `claude-budget reset-at`.

- [ ] **Step 4: Smoke, then commit**

```bash
./install.sh
launchctl print "gui/$(id -u)/com.tjdsneto.agent-inbox" | head -n 20
```

Expected: the agent is running and its program is `modules/inbox/bin/agent-inbox serve`.

```bash
git add modules/inbox/launchd/com.tjdsneto.agent-inbox.plist install.sh modules/inbox/README.md
git commit -m "feat(inbox): start the delivery loop at login"
```

---

## Spec coverage

| Spec rule | Task |
|---|---|
| Wake on NOTIFY via `agt registry wake` | 3, 5 |
| Skip wake while a live waiter is attached | 3 |
| Dead waiter falls back to resume delivery | 3 |
| Live nudge vs exited resume, Cursor headless | 2, 3 (delegated to registry) |
| Claude resume flags | registry already; not duplicated |
| Hold when Claude budget ≥ 88, retry at reset | 2, 3 |
| Codex/Cursor held only after a held wake | 2 |
| 3 failures → `undelivered` | 3 |
| Held does not consume a retry | 3 |
| Expire open questions past `expires_at` | 5 |
| Refuse answer on 🟡/🔴 | 4 |
| `serve` down: entries still created, catch up on start | 5 (`sweep` on loop entry) |
| Batched "answerable again" push | slice 4 |
