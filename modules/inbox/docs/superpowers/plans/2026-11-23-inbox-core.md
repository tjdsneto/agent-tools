# Agent Inbox — Slice 1: Store and CLI Core — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A working `agt inbox` CLI over a Postgres store: agents can ask questions (wait or resume mode) and post info, Tiago (or any caller) can answer, follow up, and manage entries, with first-answer-wins and `LISTEN/NOTIFY`-driven waiting.

**Architecture:** New module `modules/inbox`, laid out like `modules/registry` (`src/agent_inbox`, `bin/agent-inbox`, pytest). The CLI is the only door to the store. Every write fires `pg_notify('agent_inbox', …)` from a trigger, so `wait` (and, in later slices, `serve`) wakes on change instead of polling.

**Tech Stack:** Python 3.14, `psycopg` 3.3 (binary wheel), PostgreSQL 17 (Homebrew), pytest.

**Spec:** [`../specs/2026-11-23-agent-inbox-design.md`](../specs/2026-11-23-agent-inbox-design.md)

---

## Slices

The spec is built in four plans, in order. Each produces working software on its own.

1. **Store and CLI core** — this plan.
2. **Delivery** — `agt inbox serve` as a LaunchAgent: the dispatcher (LISTEN → `agt registry wake`), the wake message format, reachability (🟢🔵🟡🔴) with token checks, retries / `undelivered`, held-entry re-push, expiry sweep, and blocking `answer` on 🟡/🔴.
3. **Web UI** — server-rendered feed and entry pages, SSE refresh, the sandboxed HTML frame on a separate origin, `tailscale serve` and login-header auth.
4. **Surfaces and ops** — notifier (Telegram via `hermes send`, macOS notification, opt-in `agt say`, quiet hours, batching, urgent log), the Hermes `inbox` skill, the agent-facing `agent-inbox` skill, the `visual-ask` wrapper, nightly backups, HTML retention purge.

## What slice 1 deliberately leaves out

- Nothing delivers answers to an exited session yet. `ask` without `--wait` stores the question; the answer sits in the store until slice 2.
- `answer` does not check reachability yet (slice 2 adds the 🟡/🔴 block).
- No `expired` transitions (slice 2's sweep), no UI, no notifications.

## File structure

| File | Responsibility |
|---|---|
| `modules/inbox/requirements.txt` | `psycopg[binary]`, `pytest` |
| `modules/inbox/pytest.ini` | `pythonpath = src` |
| `modules/inbox/bin/agent-inbox` | venv launcher (same shape as `modules/registry/bin/agent-registry`) |
| `modules/inbox/src/agent_inbox/__init__.py` | package marker |
| `modules/inbox/src/agent_inbox/constants.py` | exit codes, enums, limits, defaults |
| `modules/inbox/src/agent_inbox/errors.py` | error types, each carrying its exit code |
| `modules/inbox/src/agent_inbox/ids.py` | short typeable ids (`ib-7k3q`) |
| `modules/inbox/src/agent_inbox/validate.py` | request, control, and answer validation (pure, no DB) |
| `modules/inbox/src/agent_inbox/schema.sql` | tables, indexes, notify trigger |
| `modules/inbox/src/agent_inbox/db.py` | DSN, connect, ensure schema |
| `modules/inbox/src/agent_inbox/store.py` | every read and write of entries and events |
| `modules/inbox/src/agent_inbox/waiting.py` | blocking wait on LISTEN/NOTIFY |
| `modules/inbox/src/agent_inbox/cli.py` | argparse front end, JSON out, exit codes |
| `modules/inbox/tests/conftest.py` | test-database fixtures |
| `modules/inbox/tests/test_*.py` | one test file per source file |
| `modules/inbox/README.md` | install, store setup, usage |
| `agt/agt`, `shims/agent-inbox`, `install.sh` | wiring into the `agt` dispatcher |

Python style follows `modules/registry`: 4-space indents, `from __future__ import annotations`, `main(argv) -> int`.

---

### Task 0: Postgres on the laptop

Tiago approved Homebrew `postgresql@17` as a native service (spec: Store and operations). It is keg-only, so its client tools are not on `PATH`; use the full path.

Port decision (2026-11-23): 5432 stays Docker `am-video-db` (postgres:16). This server listens on **5433**. Every inbox connection sets `port=5433`, because libpq's default port is the Docker database.

- [x] **Step 1: Install and start**

Confirm 5433 is free (if it is taken, stop and report; do not pick another port), install, set the port before the first start, then start:

```bash
lsof -nP -iTCP:5433 -sTCP:LISTEN
HOMEBREW_NO_AUTO_UPDATE=1 brew install postgresql@17
sed -i '' 's/^#port = 5432/port = 5433/' /opt/homebrew/var/postgresql@17/postgresql.conf
grep -n '^port' /opt/homebrew/var/postgresql@17/postgresql.conf
brew services start postgresql@17
```

- [x] **Step 2: Create the live and test databases**

```bash
/opt/homebrew/opt/postgresql@17/bin/createdb -h localhost -p 5433 agent_inbox
/opt/homebrew/opt/postgresql@17/bin/createdb -h localhost -p 5433 agent_inbox_test
```

- [x] **Step 3: Verify**

Run: `/opt/homebrew/opt/postgresql@17/bin/psql -h localhost -p 5433 -d agent_inbox -Atc 'select 1'`
Expected: `1`

Also check that 5432 is still Docker: `lsof -nP -iTCP:5432 -sTCP:LISTEN` shows `com.docker`, and `lsof -nP -iTCP:5433 -sTCP:LISTEN` shows `postgres`.

Note: two other Postgres instances already run on this laptop (`am-video-db` in Docker on port 5432, Paperclip's embedded one on port 54329). Do not use them. 5432 stays Docker `am-video-db`; the Homebrew server is port 5433, and every inbox connection sets `port=5433`.

---

### Task 1: Module scaffold

**Files:**
- Create: `modules/inbox/requirements.txt`, `modules/inbox/pytest.ini`, `modules/inbox/bin/agent-inbox`, `modules/inbox/src/agent_inbox/__init__.py`, `modules/inbox/src/agent_inbox/constants.py`, `modules/inbox/src/agent_inbox/errors.py`
- Test: `modules/inbox/tests/test_errors.py`

- [x] **Step 1: Create the scaffold files**

`modules/inbox/requirements.txt`:

```
psycopg[binary]>=3.3
pytest>=8
```

`modules/inbox/pytest.ini`:

```ini
[pytest]
pythonpath = src
```

`modules/inbox/bin/agent-inbox` (then `chmod +x`):

```bash
#!/usr/bin/env bash
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
	DIR="$(cd "$(dirname "$SOURCE")" && pwd)"
	SOURCE="$(readlink "$SOURCE")"
	[[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
ROOT="$(cd "$(dirname "$SOURCE")/.." && pwd)"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$ROOT/.venv/bin/python" -m agent_inbox.cli "$@"
```

`modules/inbox/src/agent_inbox/__init__.py`: empty file.

`modules/inbox/src/agent_inbox/constants.py`:

```python
from __future__ import annotations

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_NOT_FOUND = 2
EXIT_IO = 3
EXIT_CONFLICT = 4
EXIT_TIMEOUT = 5

DEFAULT_DSN = "host=localhost port=5433 dbname=agent_inbox"
NOTIFY_CHANNEL = "agent_inbox"

KINDS = ("ask", "post")
ENGINES = ("claude", "codex", "cursor")
PRIORITIES = ("urgent", "normal", "low")
CONTROL_TYPES = ("choice", "multi", "text", "approve")
TEXT_SIZES = ("short", "long")
VIAS = ("web", "telegram", "cli")

# Question states in which a follow-up or reply still makes sense.
ASK_LIVE_STATES = ("open", "answered", "delivered")
CLOSED_STATES = ("expired", "withdrawn", "superseded", "archived")

MIN_OPTIONS = 2
MAX_OPTIONS = 6
HTML_MAX_BYTES = 2 * 1024 * 1024
WAIT_TIMEOUT_SEC = 30 * 60
WAIT_POLL_SEC = 5.0
```

`modules/inbox/src/agent_inbox/errors.py`:

```python
from __future__ import annotations

from agent_inbox.constants import EXIT_CONFLICT, EXIT_IO, EXIT_NOT_FOUND, EXIT_USAGE


class InboxError(Exception):
    exit_code = EXIT_USAGE


class ValidationError(InboxError):
    exit_code = EXIT_USAGE


class NotFoundError(InboxError):
    exit_code = EXIT_NOT_FOUND


class ConflictError(InboxError):
    exit_code = EXIT_CONFLICT


class StoreError(InboxError):
    exit_code = EXIT_IO
```

- [x] **Step 2: Write the test**

`modules/inbox/tests/test_errors.py`:

```python
from agent_inbox.constants import EXIT_CONFLICT, EXIT_IO, EXIT_NOT_FOUND, EXIT_USAGE
from agent_inbox.errors import ConflictError, NotFoundError, StoreError, ValidationError


def test_each_error_carries_its_exit_code():
    assert ValidationError("x").exit_code == EXIT_USAGE
    assert NotFoundError("x").exit_code == EXIT_NOT_FOUND
    assert ConflictError("x").exit_code == EXIT_CONFLICT
    assert StoreError("x").exit_code == EXIT_IO
```

- [x] **Step 3: Create the venv and run the test**

```bash
cd modules/inbox
python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python -m pytest tests/test_errors.py -v
```

Expected: 1 passed.

- [x] **Step 4: Commit**

Check `git status` first: `.venv/` must not appear (the root `.gitignore` should cover it; if it does not, add `modules/inbox/.venv/` to it in this commit).

```bash
git add modules/inbox/requirements.txt modules/inbox/pytest.ini modules/inbox/bin/agent-inbox modules/inbox/src modules/inbox/tests
git commit -m "feat(inbox): module scaffold, constants and error types"
```

---

### Task 2: Short ids

**Files:**
- Create: `modules/inbox/src/agent_inbox/ids.py`
- Test: `modules/inbox/tests/test_ids.py`

- [x] **Step 1: Write the failing test**

```python
from agent_inbox.ids import ALPHABET, ID_LEN, ID_PREFIX, new_id


def test_id_shape():
    eid = new_id()
    assert eid.startswith(ID_PREFIX)
    body = eid[len(ID_PREFIX):]
    assert len(body) == ID_LEN
    assert set(body) <= set(ALPHABET)


def test_alphabet_has_no_lookalikes():
    for ch in "01ilo":
        assert ch not in ALPHABET


def test_ids_vary():
    assert len({new_id() for _ in range(200)}) > 190
```

- [x] **Step 2: Run it to make sure it fails**

Run: `.venv/bin/python -m pytest tests/test_ids.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_inbox.ids'`

- [x] **Step 3: Implement**

`modules/inbox/src/agent_inbox/ids.py`:

```python
from __future__ import annotations

import secrets

# No 0/1/i/l/o: ids are read off a phone and typed into Telegram.
ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
ID_PREFIX = "ib-"
ID_LEN = 4


def new_id() -> str:
    return ID_PREFIX + "".join(secrets.choice(ALPHABET) for _ in range(ID_LEN))
```

- [x] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_ids.py -v`
Expected: 3 passed.

- [x] **Step 5: Commit**

```bash
git add modules/inbox/src/agent_inbox/ids.py modules/inbox/tests/test_ids.py
git commit -m "feat(inbox): short typeable entry ids"
```

---

### Task 3: Validation

Pure functions, no database. Covers the request (`ask` / `post` JSON), the control, and an answer against its control.

**Files:**
- Create: `modules/inbox/src/agent_inbox/validate.py`
- Test: `modules/inbox/tests/test_validate.py`

- [x] **Step 1: Write the failing tests**

```python
from datetime import datetime

import pytest

from agent_inbox.errors import ValidationError
from agent_inbox.validate import validate_answer, validate_control, validate_request

CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B", "recommended": True}]}
MULTI = {"type": "multi", "options": [{"id": "x", "label": "X"}, {"id": "y", "label": "Y"}, {"id": "z", "label": "Z"}]}


def test_choice_control_is_normalised():
    out = validate_control(CHOICE)
    assert out == {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B", "recommended": True}]}


@pytest.mark.parametrize("n", [1, 7])
def test_option_count_bounds(n):
    opts = [{"id": str(i), "label": str(i)} for i in range(n)]
    with pytest.raises(ValidationError, match="2-6 options"):
        validate_control({"type": "choice", "options": opts})


def test_duplicate_option_ids_rejected():
    with pytest.raises(ValidationError, match="duplicate"):
        validate_control({"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "a", "label": "B"}]})


def test_choice_allows_one_default():
    opts = [{"id": "a", "label": "A", "default": True}, {"id": "b", "label": "B", "default": True}]
    with pytest.raises(ValidationError, match="at most one default"):
        validate_control({"type": "choice", "options": opts})


def test_text_and_approve_controls():
    assert validate_control({"type": "text"}) == {"type": "text", "size": "short"}
    assert validate_control({"type": "text", "size": "long"}) == {"type": "text", "size": "long"}
    assert validate_control({"type": "approve"}) == {"type": "approve"}
    with pytest.raises(ValidationError):
        validate_control({"type": "text", "size": "huge"})
    with pytest.raises(ValidationError, match="control.type"):
        validate_control({"type": "number"})


def test_answer_choice():
    ctl = validate_control(CHOICE)
    assert validate_answer(ctl, "b", None) == "b"
    with pytest.raises(ValidationError, match="one of a, b"):
        validate_answer(ctl, "c", None)
    with pytest.raises(ValidationError):
        validate_answer(ctl, ["a", "b"], None)


def test_answer_multi_accepts_single_and_dedupes():
    ctl = validate_control(MULTI)
    assert validate_answer(ctl, "x", None) == ["x"]
    assert validate_answer(ctl, ["z", "x", "z"], None) == ["z", "x"]
    with pytest.raises(ValidationError):
        validate_answer(ctl, [], None)
    with pytest.raises(ValidationError):
        validate_answer(ctl, ["x", "nope"], None)


def test_answer_text_and_approve():
    assert validate_answer({"type": "text", "size": "short"}, "hi", None) == "hi"
    with pytest.raises(ValidationError, match="empty"):
        validate_answer({"type": "text", "size": "short"}, "  ", None)
    assert validate_answer({"type": "approve"}, "approve", None) == "approve"
    with pytest.raises(ValidationError, match="reason"):
        validate_answer({"type": "approve"}, "revise", "")
    assert validate_answer({"type": "approve"}, "revise", "too wide") == "revise"


def test_request_ask_defaults_and_required():
    out = validate_request({"title": "Which split?", "control": CHOICE}, "ask")
    assert out["priority"] == "normal"
    assert out["control"]["type"] == "choice"
    with pytest.raises(ValidationError, match="needs a control"):
        validate_request({"title": "t"}, "ask")
    with pytest.raises(ValidationError, match="title"):
        validate_request({"control": CHOICE}, "ask")
    with pytest.raises(ValidationError, match="one line"):
        validate_request({"title": "a\nb", "control": CHOICE}, "ask")


def test_request_post_rules():
    out = validate_request({"title": "Nightly run done"}, "post")
    assert out["priority"] == "low"
    assert "control" not in out
    with pytest.raises(ValidationError, match="no control"):
        validate_request({"title": "t", "control": CHOICE}, "post")


def test_request_html_cap_source_and_expiry():
    with pytest.raises(ValidationError, match="2 MB"):
        validate_request({"title": "t", "html": "x" * (2 * 1024 * 1024 + 1)}, "post")
    with pytest.raises(ValidationError, match="source"):
        validate_request({"title": "t", "source": {"kind": "k", "extra": 1}}, "post")
    out = validate_request({"title": "t", "expires_at": "2026-12-01T09:00:00-03:00"}, "post")
    assert isinstance(out["expires_at"], datetime)
    with pytest.raises(ValidationError, match="timezone"):
        validate_request({"title": "t", "expires_at": "2026-12-01T09:00:00"}, "post")
    with pytest.raises(ValidationError, match="priority"):
        validate_request({"title": "t", "priority": "meh"}, "post")
```

- [x] **Step 2: Run them to make sure they fail**

Run: `.venv/bin/python -m pytest tests/test_validate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_inbox.validate'`

- [x] **Step 3: Implement**

`modules/inbox/src/agent_inbox/validate.py`:

```python
from __future__ import annotations

from datetime import datetime
from typing import Any

from agent_inbox.constants import (
    CONTROL_TYPES,
    HTML_MAX_BYTES,
    MAX_OPTIONS,
    MIN_OPTIONS,
    PRIORITIES,
    TEXT_SIZES,
)
from agent_inbox.errors import ValidationError

SOURCE_KEYS = {"kind", "ref", "url"}


def _options(ctype: str, options: Any) -> list[dict]:
    if not isinstance(options, list) or not (MIN_OPTIONS <= len(options) <= MAX_OPTIONS):
        raise ValidationError(f"{ctype} needs {MIN_OPTIONS}-{MAX_OPTIONS} options")
    seen: set[str] = set()
    clean: list[dict] = []
    for opt in options:
        if not isinstance(opt, dict):
            raise ValidationError("each option needs an id and a label")
        oid = str(opt.get("id") or "").strip()
        label = str(opt.get("label") or "").strip()
        if not oid or not label:
            raise ValidationError("each option needs an id and a label")
        if oid in seen:
            raise ValidationError(f"duplicate option id {oid!r}")
        seen.add(oid)
        item: dict[str, Any] = {"id": oid, "label": label}
        if opt.get("description"):
            item["description"] = str(opt["description"])
        if opt.get("recommended"):
            item["recommended"] = True
        if opt.get("default"):
            item["default"] = True
        clean.append(item)
    return clean


def validate_control(control: Any) -> dict:
    if not isinstance(control, dict):
        raise ValidationError("control must be an object")
    ctype = control.get("type")
    if ctype not in CONTROL_TYPES:
        raise ValidationError(f"control.type must be one of {', '.join(CONTROL_TYPES)}")
    if ctype in ("choice", "multi"):
        options = _options(ctype, control.get("options"))
        if ctype == "choice" and sum(1 for o in options if o.get("default")) > 1:
            raise ValidationError("choice allows at most one default option")
        return {"type": ctype, "options": options}
    if ctype == "text":
        size = control.get("size", "short")
        if size not in TEXT_SIZES:
            raise ValidationError(f"text size must be one of {', '.join(TEXT_SIZES)}")
        return {"type": "text", "size": size}
    return {"type": "approve"}


def validate_answer(control: dict, value: Any, comment: str | None) -> Any:
    ctype = control["type"]
    ids = [o["id"] for o in control.get("options", [])]
    if ctype == "choice":
        if not isinstance(value, str) or value not in ids:
            raise ValidationError(f"value must be one of {', '.join(ids)}")
        return value
    if ctype == "multi":
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list) or not value or any(v not in ids for v in value):
            raise ValidationError(f"values must be among {', '.join(ids)}")
        return list(dict.fromkeys(value))
    if ctype == "text":
        if not isinstance(value, str) or not value.strip():
            raise ValidationError("text answer is empty")
        return value
    if value not in ("approve", "revise"):
        raise ValidationError("value must be approve or revise")
    if value == "revise" and not (comment or "").strip():
        raise ValidationError("revise needs a reason in --comment")
    return value


def _expires(raw: Any) -> datetime | None:
    if raw is None:
        return None
    try:
        when = datetime.fromisoformat(str(raw))
    except ValueError as e:
        raise ValidationError(f"expires_at is not an ISO timestamp: {raw!r}") from e
    if when.tzinfo is None:
        raise ValidationError("expires_at needs a timezone offset")
    return when


def validate_request(raw: Any, kind: str) -> dict:
    if not isinstance(raw, dict):
        raise ValidationError("request must be a JSON object")
    title = str(raw.get("title") or "").strip()
    if not title:
        raise ValidationError("title is required")
    if "\n" in title:
        raise ValidationError("title must be one line")
    priority = raw.get("priority") or ("normal" if kind == "ask" else "low")
    if priority not in PRIORITIES:
        raise ValidationError(f"priority must be one of {', '.join(PRIORITIES)}")
    html = raw.get("html")
    if html is not None:
        if not isinstance(html, str):
            raise ValidationError("html must be a string")
        if len(html.encode()) > HTML_MAX_BYTES:
            raise ValidationError("html exceeds 2 MB")
    source = raw.get("source")
    if source is not None and (not isinstance(source, dict) or not set(source) <= SOURCE_KEYS):
        raise ValidationError("source takes only kind, ref, url")
    out = {
        "title": title,
        "summary": raw.get("summary"),
        "detail": raw.get("detail"),
        "html": html,
        "priority": priority,
        "source": source,
        "expires_at": _expires(raw.get("expires_at")),
    }
    if kind == "ask":
        if "control" not in raw:
            raise ValidationError("ask needs a control")
        out["control"] = validate_control(raw["control"])
    elif "control" in raw:
        raise ValidationError("post takes no control")
    return out
```

- [x] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_validate.py -v`
Expected: all passed.

- [x] **Step 5: Commit**

```bash
git add modules/inbox/src/agent_inbox/validate.py modules/inbox/tests/test_validate.py
git commit -m "feat(inbox): validate requests, controls and answers"
```

---

### Task 4: Schema and connection

**Files:**
- Create: `modules/inbox/src/agent_inbox/schema.sql`, `modules/inbox/src/agent_inbox/db.py`, `modules/inbox/tests/conftest.py`
- Test: `modules/inbox/tests/test_db.py`

- [x] **Step 1: Write the schema**

`modules/inbox/src/agent_inbox/schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS entries (
    id            text PRIMARY KEY,
    kind          text NOT NULL CHECK (kind IN ('ask', 'post')),
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    engine        text,
    model         text,
    session_id    text,
    cwd           text,
    project       text,
    script        text,
    priority      text NOT NULL CHECK (priority IN ('urgent', 'normal', 'low')),
    mode          text CHECK (mode IN ('wait', 'resume')),
    title         text NOT NULL,
    summary       text,
    detail        text,
    html          text,
    control       jsonb,
    source        jsonb,
    expires_at    timestamptz,
    state         text NOT NULL CHECK (state IN (
                      'open', 'answered', 'delivered', 'expired', 'withdrawn', 'superseded', 'undelivered',
                      'unread', 'read', 'archived')),
    answer        jsonb,
    waiter_pid    integer,
    superseded_by text REFERENCES entries (id)
);

CREATE INDEX IF NOT EXISTS entries_state ON entries (state);
CREATE INDEX IF NOT EXISTS entries_project ON entries (project);
CREATE INDEX IF NOT EXISTS entries_session ON entries (session_id);

CREATE TABLE IF NOT EXISTS events (
    seq      bigserial PRIMARY KEY,
    entry_id text NOT NULL REFERENCES entries (id) ON DELETE CASCADE,
    at       timestamptz NOT NULL DEFAULT now(),
    type     text NOT NULL CHECK (type IN ('answer', 'followup', 'reply', 'revise', 'state')),
    via      text,
    body     jsonb NOT NULL
);

CREATE INDEX IF NOT EXISTS events_entry ON events (entry_id, seq);

-- One channel for every change. TG_ARGV[0] names the column holding the entry id,
-- so one function serves both tables without referencing a field the row lacks.
CREATE OR REPLACE FUNCTION agent_inbox_notify() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify(
        'agent_inbox',
        json_build_object('table', TG_TABLE_NAME, 'id', to_jsonb(NEW) ->> TG_ARGV[0])::text
    );
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER entries_notify AFTER INSERT OR UPDATE ON entries
    FOR EACH ROW EXECUTE FUNCTION agent_inbox_notify('id');

CREATE OR REPLACE TRIGGER events_notify AFTER INSERT ON events
    FOR EACH ROW EXECUTE FUNCTION agent_inbox_notify('entry_id');
```

- [x] **Step 2: Write the test fixtures**

`modules/inbox/tests/conftest.py`:

```python
from __future__ import annotations

import os

import psycopg
import pytest

from agent_inbox import db

TEST_DSN = os.environ.get("AGENT_INBOX_TEST_DSN", "host=localhost port=5433 dbname=agent_inbox_test")


@pytest.fixture
def inbox_db(monkeypatch):
    """Point the module at the test database and start from an empty schema."""
    monkeypatch.setenv("AGENT_INBOX_DSN", TEST_DSN)
    try:
        conn = psycopg.connect(TEST_DSN, autocommit=True)
    except psycopg.OperationalError as e:
        pytest.fail(f"test store unreachable ({TEST_DSN}): {e}. Run Task 0 of the plan.")
    conn.execute("DROP TABLE IF EXISTS events, entries CASCADE")
    conn.close()
    return TEST_DSN


@pytest.fixture
def conn(inbox_db):
    c = db.connect()
    yield c
    c.close()
```

- [x] **Step 3: Write the failing tests**

`modules/inbox/tests/test_db.py`:

```python
import json

import psycopg
import pytest

from agent_inbox import db
from agent_inbox.errors import StoreError


def test_connect_creates_schema(conn):
    names = {r["table_name"] for r in conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    ).fetchall()}
    assert {"entries", "events"} <= names


def test_ensure_schema_is_repeatable(conn):
    db.ensure_schema(conn)
    db.ensure_schema(conn)


def test_insert_notifies(inbox_db, conn):
    listener = psycopg.connect(inbox_db, autocommit=True)
    listener.execute("LISTEN agent_inbox")
    conn.execute(
        "INSERT INTO entries (id, kind, priority, title, state) VALUES ('ib-test', 'post', 'low', 't', 'unread')"
    )
    got = [json.loads(n.payload) for n in listener.notifies(timeout=2, stop_after=1)]
    listener.close()
    assert got == [{"table": "entries", "id": "ib-test"}]


def test_unreachable_store_is_a_store_error(monkeypatch):
    monkeypatch.setenv("AGENT_INBOX_DSN", "host=127.0.0.1 port=1 dbname=nope connect_timeout=1")
    with pytest.raises(StoreError, match="cannot reach the inbox store"):
        db.connect()
```

- [x] **Step 4: Run them to make sure they fail**

Run: `.venv/bin/python -m pytest tests/test_db.py -v`
Expected: FAIL with `ImportError: cannot import name 'db'`

- [x] **Step 5: Implement**

`modules/inbox/src/agent_inbox/db.py`:

```python
from __future__ import annotations

import os
from importlib import resources

import psycopg
from psycopg.rows import dict_row

from agent_inbox.constants import DEFAULT_DSN
from agent_inbox.errors import StoreError

SCHEMA_LOCK = 7_204_811  # arbitrary advisory-lock key for schema setup


def dsn() -> str:
    return os.environ.get("AGENT_INBOX_DSN") or DEFAULT_DSN


def schema_sql() -> str:
    return resources.files("agent_inbox").joinpath("schema.sql").read_text()


def connect() -> psycopg.Connection:
    """Autocommit connection with dict rows. Multi-statement writes use conn.transaction()."""
    try:
        conn = psycopg.connect(dsn(), row_factory=dict_row, autocommit=True)
    except psycopg.OperationalError as e:
        raise StoreError(f"cannot reach the inbox store ({dsn()}): {e}") from e
    ensure_schema(conn)
    return conn


def ensure_schema(conn: psycopg.Connection) -> None:
    if conn.execute("SELECT to_regclass('events') AS t").fetchone()["t"] is not None:
        return
    conn.execute("SELECT pg_advisory_lock(%s)", (SCHEMA_LOCK,))
    try:
        conn.execute(schema_sql())
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (SCHEMA_LOCK,))
```

- [x] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_db.py -v`
Expected: 4 passed.

- [x] **Step 7: Commit**

```bash
git add modules/inbox/src/agent_inbox/schema.sql modules/inbox/src/agent_inbox/db.py modules/inbox/tests/conftest.py modules/inbox/tests/test_db.py
git commit -m "feat(inbox): Postgres schema with change notifications"
```

---

### Task 5: Store — create, get, list

**Files:**
- Create: `modules/inbox/src/agent_inbox/store.py`
- Test: `modules/inbox/tests/test_store_entries.py`

- [x] **Step 1: Write the failing tests**

```python
import subprocess

import pytest

from agent_inbox import store
from agent_inbox.errors import NotFoundError, ValidationError
from agent_inbox.validate import validate_request

CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}


def make_ask(conn, cwd=None, **over):
    req = validate_request({"title": "Which split?", "control": CHOICE, **over}, "ask")
    return store.create_entry(conn, "ask", req, engine="claude", model="opus", session_id="s-1", cwd=cwd)


def test_create_ask_records_asker_and_opens(conn, tmp_path):
    e = make_ask(conn, cwd=str(tmp_path))
    assert e["id"].startswith("ib-")
    assert e["state"] == "open"
    assert e["mode"] == "resume"
    assert e["asker"] == {"engine": "claude", "model": "opus", "session_id": "s-1",
                          "cwd": str(tmp_path), "project": str(tmp_path), "script": None}
    assert e["thread"] == [] and e["revisions"] == []


def test_project_is_git_root(conn, tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    sub = tmp_path / "deep" / "dir"
    sub.mkdir(parents=True)
    e = make_ask(conn, cwd=str(sub))
    assert e["asker"]["project"] == str(tmp_path.resolve())


def test_ask_needs_engine_and_session(conn):
    req = validate_request({"title": "t", "control": CHOICE}, "ask")
    with pytest.raises(ValidationError, match="--engine and --session-id"):
        store.create_entry(conn, "ask", req, engine="claude", session_id=None)
    with pytest.raises(ValidationError, match="--engine and --session-id"):
        store.create_entry(conn, "ask", req, engine=None, session_id="s")


def test_post_from_script_or_session(conn):
    req = validate_request({"title": "Nightly run done"}, "post")
    e = store.create_entry(conn, "post", req, script="nightly-backup")
    assert e["state"] == "unread" and e["mode"] is None and e["asker"]["script"] == "nightly-backup"
    with pytest.raises(ValidationError, match="--session-id or --script"):
        store.create_entry(conn, "post", req)
    with pytest.raises(ValidationError, match="needs --engine"):
        store.create_entry(conn, "post", req, session_id="s")


def test_get_unknown_raises(conn):
    with pytest.raises(NotFoundError):
        store.get_entry(conn, "ib-zzzz")


def test_list_orders_urgent_first_then_oldest_and_filters(conn):
    first = make_ask(conn)
    second = make_ask(conn, priority="urgent")
    third = make_ask(conn)
    post = store.create_entry(conn, "post", validate_request({"title": "info"}, "post"), script="x")
    ids = [e["id"] for e in store.list_entries(conn)]
    assert ids == [second["id"], first["id"], third["id"], post["id"]]
    assert [e["id"] for e in store.list_entries(conn, kind="post")] == [post["id"]]
    assert [e["id"] for e in store.list_entries(conn, states=["unread"])] == [post["id"]]
    assert len(store.list_entries(conn, limit=2)) == 2
    assert "html" not in store.list_entries(conn)[0]
```

- [x] **Step 2: Run them to make sure they fail**

Run: `.venv/bin/python -m pytest tests/test_store_entries.py -v`
Expected: FAIL with `ImportError: cannot import name 'store'`

- [x] **Step 3: Implement**

`modules/inbox/src/agent_inbox/store.py`:

```python
from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from agent_inbox.errors import NotFoundError, StoreError, ValidationError
from agent_inbox.ids import new_id

ID_ATTEMPTS = 10
LIST_HIDDEN = ("html", "summary", "detail")
PRIORITY_ORDER = "CASE priority WHEN 'urgent' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _jsonb(value: Any) -> Jsonb | None:
    return None if value is None else Jsonb(value)


def project_root(cwd: str | None) -> str | None:
    if not cwd:
        return None
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return cwd
    root = out.stdout.strip()
    return root if out.returncode == 0 and root else cwd


def _row(conn: psycopg.Connection, entry_id: str, *, lock: bool = False) -> dict:
    sql = "SELECT * FROM entries WHERE id = %s" + (" FOR UPDATE" if lock else "")
    row = conn.execute(sql, (entry_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"no entry {entry_id}")
    return row


def _event(conn: psycopg.Connection, entry_id: str, etype: str, via: str | None, body: dict) -> int:
    row = conn.execute(
        "INSERT INTO events (entry_id, type, via, body) VALUES (%s, %s, %s, %s) RETURNING seq",
        (entry_id, etype, via, Jsonb(body)),
    ).fetchone()
    conn.execute("UPDATE entries SET updated_at = now() WHERE id = %s", (entry_id,))
    return row["seq"]


def _shape_event(ev: dict) -> dict:
    out = {"seq": ev["seq"], "at": _iso(ev["at"]), "type": ev["type"], "via": ev["via"]}
    out.update(ev["body"])
    return out


def _shape(row: dict, events: list[dict] | None = None) -> dict:
    entry = {
        "id": row["id"],
        "kind": row["kind"],
        "created_at": _iso(row["created_at"]),
        "updated_at": _iso(row["updated_at"]),
        "asker": {k: row[k] for k in ("engine", "model", "session_id", "cwd", "project", "script")},
        "priority": row["priority"],
        "mode": row["mode"],
        "title": row["title"],
        "summary": row["summary"],
        "detail": row["detail"],
        "html": row["html"],
        "control": row["control"],
        "source": row["source"],
        "expires_at": _iso(row["expires_at"]),
        "state": row["state"],
        "answer": row["answer"],
        "superseded_by": row["superseded_by"],
        "waiter_pid": row["waiter_pid"],
    }
    if events is not None:
        entry["thread"] = [_shape_event(e) for e in events if e["type"] in ("followup", "reply")]
        entry["revisions"] = [_shape_event(e) for e in events if e["type"] == "revise"]
    return entry


def create_entry(
    conn: psycopg.Connection,
    kind: str,
    req: dict,
    *,
    engine: str | None = None,
    model: str | None = None,
    session_id: str | None = None,
    cwd: str | None = None,
    script: str | None = None,
    mode: str | None = None,
) -> dict:
    """Insert a validated request (see validate.validate_request) and return the full entry."""
    if kind == "ask":
        if not engine or not session_id:
            raise ValidationError("ask needs --engine and --session-id")
        mode, state = mode or "resume", "open"
    else:
        if not session_id and not script:
            raise ValidationError("post needs --session-id or --script")
        if session_id and not engine:
            raise ValidationError("--session-id needs --engine")
        mode, state = None, "unread"
    params = {
        "kind": kind, "engine": engine, "model": model, "session_id": session_id,
        "cwd": cwd, "project": project_root(cwd), "script": script,
        "priority": req["priority"], "mode": mode, "title": req["title"],
        "summary": req.get("summary"), "detail": req.get("detail"), "html": req.get("html"),
        "control": _jsonb(req.get("control")), "source": _jsonb(req.get("source")),
        "expires_at": req.get("expires_at"), "state": state,
    }
    for _ in range(ID_ATTEMPTS):
        params["id"] = new_id()
        row = conn.execute(
            """
            INSERT INTO entries (id, kind, engine, model, session_id, cwd, project, script, priority, mode,
                                 title, summary, detail, html, control, source, expires_at, state)
            VALUES (%(id)s, %(kind)s, %(engine)s, %(model)s, %(session_id)s, %(cwd)s, %(project)s, %(script)s,
                    %(priority)s, %(mode)s, %(title)s, %(summary)s, %(detail)s, %(html)s, %(control)s,
                    %(source)s, %(expires_at)s, %(state)s)
            ON CONFLICT (id) DO NOTHING
            RETURNING id
            """,
            params,
        ).fetchone()
        if row:
            return get_entry(conn, row["id"])
    raise StoreError("could not allocate an entry id")


def get_entry(conn: psycopg.Connection, entry_id: str) -> dict:
    row = _row(conn, entry_id)
    events = conn.execute("SELECT * FROM events WHERE entry_id = %s ORDER BY seq", (entry_id,)).fetchall()
    return _shape(row, events)


def list_entries(
    conn: psycopg.Connection,
    *,
    kind: str | None = None,
    states: list[str] | None = None,
    project: str | None = None,
    engine: str | None = None,
    session_id: str | None = None,
    limit: int = 50,
) -> list[dict]:
    where: list[str] = []
    params: list[Any] = []
    for col, val in (("kind", kind), ("project", project), ("engine", engine), ("session_id", session_id)):
        if val is not None:
            where.append(f"{col} = %s")
            params.append(val)
    if states:
        where.append("state = ANY(%s)")
        params.append(list(states))
    sql = "SELECT * FROM entries"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY {PRIORITY_ORDER}, created_at, id LIMIT %s"
    params.append(limit)
    return [
        {k: v for k, v in _shape(r).items() if k not in LIST_HIDDEN}
        for r in conn.execute(sql, params).fetchall()
    ]
```

- [x] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_store_entries.py -v`
Expected: all passed. If `test_project_is_git_root` fails on `/private/var` vs `/var`, compare against `str(tmp_path.resolve())` on both sides — the test already resolves the expected side; `git rev-parse` returns the resolved path.

- [x] **Step 5: Commit**

```bash
git add modules/inbox/src/agent_inbox/store.py modules/inbox/tests/test_store_entries.py
git commit -m "feat(inbox): create, get and list entries"
```

---

### Task 6: Store — answer, first one wins

**Files:**
- Modify: `modules/inbox/src/agent_inbox/store.py` (append)
- Test: `modules/inbox/tests/test_store_answer.py`

- [x] **Step 1: Write the failing tests**

```python
import threading

import pytest

from agent_inbox import db, store
from agent_inbox.errors import ConflictError, ValidationError
from agent_inbox.validate import validate_request

CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}


def make_ask(conn, control=CHOICE):
    req = validate_request({"title": "Which split?", "control": control}, "ask")
    return store.create_entry(conn, "ask", req, engine="claude", session_id="s-1")


def test_answer_records_value_comment_via(conn):
    e = make_ask(conn)
    out = store.answer(conn, e["id"], "b", comment="keep it thin", via="web")
    assert out["state"] == "answered" and out["value"] == "b"
    got = store.get_entry(conn, e["id"])
    assert got["state"] == "answered"
    assert got["answer"]["value"] == "b"
    assert got["answer"]["comment"] == "keep it thin"
    assert got["answer"]["via"] == "web"
    assert got["answer"]["at"]


def test_second_answer_conflicts_and_names_the_first(conn):
    e = make_ask(conn)
    store.answer(conn, e["id"], "a", via="telegram")
    with pytest.raises(ConflictError, match="already answered via telegram: a"):
        store.answer(conn, e["id"], "b", via="web")


def test_invalid_answer_leaves_entry_open(conn):
    e = make_ask(conn)
    with pytest.raises(ValidationError):
        store.answer(conn, e["id"], "zzz", via="web")
    assert store.get_entry(conn, e["id"])["state"] == "open"


def test_bad_via_rejected(conn):
    e = make_ask(conn)
    with pytest.raises(ValidationError, match="via"):
        store.answer(conn, e["id"], "a", via="slack")


def test_post_takes_no_answer(conn):
    p = store.create_entry(conn, "post", validate_request({"title": "info"}, "post"), script="x")
    with pytest.raises(ValidationError, match="not a question"):
        store.answer(conn, p["id"], "a", via="web")


def test_concurrent_answers_exactly_one_wins(inbox_db, conn):
    e = make_ask(conn)
    results: list[str] = []
    barrier = threading.Barrier(2)

    def attempt(value):
        c = db.connect()
        barrier.wait()
        try:
            store.answer(c, e["id"], value, via="web")
            results.append("won")
        except ConflictError:
            results.append("lost")
        finally:
            c.close()

    threads = [threading.Thread(target=attempt, args=(v,)) for v in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["lost", "won"]
```

- [x] **Step 2: Run them to make sure they fail**

Run: `.venv/bin/python -m pytest tests/test_store_answer.py -v`
Expected: FAIL with `AttributeError: module 'agent_inbox.store' has no attribute 'answer'`

- [x] **Step 3: Implement**

Add to the imports at the top of `store.py`:

```python
from agent_inbox.constants import VIAS
from agent_inbox.errors import ConflictError
from agent_inbox.validate import validate_answer
```

Append to `store.py`:

```python
def _check_via(via: str) -> None:
    if via not in VIAS:
        raise ValidationError(f"via must be one of {', '.join(VIAS)}")


def _closed_message(row: dict) -> str:
    if row["answer"]:
        return f"{row['id']} already answered via {row['answer']['via']}: {row['answer']['value']}"
    return f"{row['id']} is {row['state']}"


def answer(
    conn: psycopg.Connection,
    entry_id: str,
    value: Any,
    *,
    comment: str | None = None,
    via: str = "cli",
) -> dict:
    """First answer wins: the row lock makes a concurrent second answer see the first and conflict."""
    _check_via(via)
    with conn.transaction():
        row = _row(conn, entry_id, lock=True)
        if row["kind"] != "ask":
            raise ValidationError(f"{entry_id} is not a question")
        if row["state"] != "open":
            raise ConflictError(_closed_message(row))
        clean = validate_answer(row["control"], value, comment)
        payload = {"value": clean, "comment": (comment or "").strip() or None, "via": via, "at": _now_iso()}
        conn.execute(
            "UPDATE entries SET state = 'answered', answer = %s, updated_at = now() WHERE id = %s",
            (Jsonb(payload), entry_id),
        )
        _event(conn, entry_id, "answer", via, payload)
    return {"entry": entry_id, "state": "answered", **payload}
```

- [x] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_store_answer.py -v`
Expected: all passed. Run the concurrency test 5 times (`-k concurrent --count` is not available; loop it: `for i in 1 2 3 4 5; do .venv/bin/python -m pytest tests/test_store_answer.py -k concurrent -q || break; done`) and report how many runs passed.

- [x] **Step 5: Commit**

```bash
git add modules/inbox/src/agent_inbox/store.py modules/inbox/tests/test_store_answer.py
git commit -m "feat(inbox): answers with first-answer-wins"
```

---

### Task 7: Store — follow-ups, replies, revisions

**Files:**
- Modify: `modules/inbox/src/agent_inbox/store.py` (append)
- Test: `modules/inbox/tests/test_store_thread.py`

- [x] **Step 1: Write the failing tests**

```python
import pytest

from agent_inbox import store
from agent_inbox.errors import ConflictError, ValidationError
from agent_inbox.validate import validate_request

CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}


def make_ask(conn):
    req = validate_request({"title": "Which split?", "control": CHOICE}, "ask")
    return store.create_entry(conn, "ask", req, engine="claude", session_id="s-1")


def test_followup_and_reply_build_the_thread_in_order(conn):
    e = make_ask(conn)
    f = store.add_followup(conn, e["id"], "why not C?", via="telegram")
    r = store.add_reply(conn, e["id"], "C breaks the tray", html="<p>diagram</p>")
    assert f["event"] == "followup" and r["event"] == "reply" and r["seq"] > f["seq"]
    thread = store.get_entry(conn, e["id"])["thread"]
    assert [(t["type"], t["text"]) for t in thread] == [("followup", "why not C?"), ("reply", "C breaks the tray")]
    assert thread[0]["via"] == "telegram" and thread[1]["via"] == "agent"
    assert thread[1]["html"] == "<p>diagram</p>"
    assert store.get_entry(conn, e["id"])["state"] == "open"


def test_followup_allowed_after_answer(conn):
    e = make_ask(conn)
    store.answer(conn, e["id"], "a", via="web")
    store.add_followup(conn, e["id"], "one more thing", via="web")


def test_empty_texts_rejected(conn):
    e = make_ask(conn)
    with pytest.raises(ValidationError, match="empty"):
        store.add_followup(conn, e["id"], "  ", via="web")
    with pytest.raises(ValidationError, match="empty"):
        store.add_reply(conn, e["id"], "")


def test_post_followup_needs_a_session_and_marks_read(conn):
    scripted = store.create_entry(conn, "post", validate_request({"title": "x"}, "post"), script="cron")
    with pytest.raises(ValidationError, match="no session"):
        store.add_followup(conn, scripted["id"], "why?", via="web")
    agent_post = store.create_entry(conn, "post", validate_request({"title": "y"}, "post"),
                                    engine="codex", session_id="s-2")
    store.add_followup(conn, agent_post["id"], "why?", via="web")
    assert store.get_entry(conn, agent_post["id"])["state"] == "read"


def test_revise_replaces_control_and_logs(conn):
    e = make_ask(conn)
    new = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}, {"id": "c", "label": "C"}]}
    store.revise(conn, e["id"], new)
    got = store.get_entry(conn, e["id"])
    assert [o["id"] for o in got["control"]["options"]] == ["a", "b", "c"]
    assert len(got["revisions"]) == 1
    assert [o["id"] for o in got["revisions"][0]["old"]["options"]] == ["a", "b"]


def test_revise_only_while_open(conn):
    e = make_ask(conn)
    store.answer(conn, e["id"], "a", via="web")
    with pytest.raises(ConflictError):
        store.revise(conn, e["id"], CHOICE)
```

- [x] **Step 2: Run them to make sure they fail**

Run: `.venv/bin/python -m pytest tests/test_store_thread.py -v`
Expected: FAIL with `AttributeError: module 'agent_inbox.store' has no attribute 'add_followup'`

- [x] **Step 3: Implement**

Add to the imports at the top of `store.py`:

```python
from agent_inbox.constants import ASK_LIVE_STATES, CLOSED_STATES, HTML_MAX_BYTES
from agent_inbox.validate import validate_control
```

Append to `store.py`:

```python
def _set_state(conn: psycopg.Connection, row: dict, to: str, **extra: Any) -> None:
    sets = ["state = %s", "updated_at = now()"] + [f"{k} = %s" for k in extra]
    conn.execute(f"UPDATE entries SET {', '.join(sets)} WHERE id = %s", (to, *extra.values(), row["id"]))
    _event(conn, row["id"], "state", None, {"from": row["state"], "to": to})


def add_followup(conn: psycopg.Connection, entry_id: str, text: str, *, via: str = "cli") -> dict:
    _check_via(via)
    if not text.strip():
        raise ValidationError("follow-up text is empty")
    with conn.transaction():
        row = _row(conn, entry_id, lock=True)
        if row["kind"] == "ask" and row["state"] not in ASK_LIVE_STATES:
            raise ConflictError(_closed_message(row))
        if row["kind"] == "post":
            if not row["session_id"]:
                raise ValidationError(f"{entry_id} has no session to ask")
            if row["state"] == "archived":
                raise ConflictError(f"{entry_id} is archived")
        seq = _event(conn, entry_id, "followup", via, {"text": text})
        if row["kind"] == "post" and row["state"] == "unread":
            _set_state(conn, row, "read")
    return {"entry": entry_id, "event": "followup", "seq": seq}


def add_reply(conn: psycopg.Connection, entry_id: str, text: str, *, html: str | None = None) -> dict:
    if not text.strip():
        raise ValidationError("reply text is empty")
    if html is not None and len(html.encode()) > HTML_MAX_BYTES:
        raise ValidationError("html exceeds 2 MB")
    with conn.transaction():
        row = _row(conn, entry_id, lock=True)
        if row["state"] in CLOSED_STATES:
            raise ConflictError(f"{entry_id} is {row['state']}")
        body: dict[str, Any] = {"text": text}
        if html is not None:
            body["html"] = html
        seq = _event(conn, entry_id, "reply", "agent", body)
    return {"entry": entry_id, "event": "reply", "seq": seq}


def revise(conn: psycopg.Connection, entry_id: str, control: Any) -> dict:
    new = validate_control(control)
    with conn.transaction():
        row = _row(conn, entry_id, lock=True)
        if row["kind"] != "ask":
            raise ValidationError(f"{entry_id} is not a question")
        if row["state"] != "open":
            raise ConflictError(_closed_message(row))
        conn.execute("UPDATE entries SET control = %s, updated_at = now() WHERE id = %s", (Jsonb(new), entry_id))
        seq = _event(conn, entry_id, "revise", "agent", {"old": row["control"], "new": new})
    return {"entry": entry_id, "event": "revise", "seq": seq}
```

- [x] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_store_thread.py -v`
Expected: all passed.

- [x] **Step 5: Commit**

```bash
git add modules/inbox/src/agent_inbox/store.py modules/inbox/tests/test_store_thread.py
git commit -m "feat(inbox): follow-up thread, agent replies and control revisions"
```

---

### Task 8: Store — withdraw, supersede, read, archive

**Files:**
- Modify: `modules/inbox/src/agent_inbox/store.py` (append)
- Test: `modules/inbox/tests/test_store_states.py`

- [x] **Step 1: Write the failing tests**

```python
import pytest

from agent_inbox import store
from agent_inbox.errors import ConflictError, ValidationError
from agent_inbox.validate import validate_request

CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}


def make_ask(conn):
    req = validate_request({"title": "Which split?", "control": CHOICE}, "ask")
    return store.create_entry(conn, "ask", req, engine="claude", session_id="s-1")


def make_post(conn):
    return store.create_entry(conn, "post", validate_request({"title": "info"}, "post"), script="cron")


def test_withdraw_open_question(conn):
    e = make_ask(conn)
    assert store.withdraw(conn, e["id"])["state"] == "withdrawn"
    with pytest.raises(ConflictError):
        store.withdraw(conn, e["id"])
    with pytest.raises(ConflictError):
        store.answer(conn, e["id"], "a", via="web")


def test_followup_on_withdrawn_conflicts(conn):
    e = make_ask(conn)
    store.withdraw(conn, e["id"])
    with pytest.raises(ConflictError):
        store.add_followup(conn, e["id"], "hello?", via="web")


def test_supersede_links_the_newer_entry(conn):
    old, new = make_ask(conn), make_ask(conn)
    store.supersede(conn, old["id"], by=new["id"])
    got = store.get_entry(conn, old["id"])
    assert got["state"] == "superseded" and got["superseded_by"] == new["id"]


def test_supersede_rules(conn):
    a = make_ask(conn)
    with pytest.raises(ValidationError, match="itself"):
        store.supersede(conn, a["id"], by=a["id"])
    with pytest.raises(ValidationError, match="not a question"):
        store.supersede(conn, a["id"], by=make_post(conn)["id"])


def test_read_and_archive_posts(conn):
    p = make_post(conn)
    assert store.mark_read(conn, p["id"])["state"] == "read"
    assert store.mark_read(conn, p["id"])["state"] == "read"
    assert store.archive(conn, p["id"])["state"] == "archived"
    assert store.archive(conn, p["id"])["state"] == "archived"
    with pytest.raises(ValidationError, match="not an info entry"):
        store.mark_read(conn, make_ask(conn)["id"])


def test_state_changes_are_logged(conn):
    e = make_ask(conn)
    store.withdraw(conn, e["id"])
    types = [r["type"] for r in conn.execute("SELECT type FROM events WHERE entry_id = %s", (e["id"],)).fetchall()]
    assert types == ["state"]
```

- [x] **Step 2: Run them to make sure they fail**

Run: `.venv/bin/python -m pytest tests/test_store_states.py -v`
Expected: FAIL with `AttributeError: module 'agent_inbox.store' has no attribute 'withdraw'`

- [x] **Step 3: Implement**

Append to `store.py`:

```python
def withdraw(conn: psycopg.Connection, entry_id: str) -> dict:
    with conn.transaction():
        row = _row(conn, entry_id, lock=True)
        if row["kind"] != "ask":
            raise ValidationError(f"{entry_id} is not a question")
        if row["state"] != "open":
            raise ConflictError(_closed_message(row))
        _set_state(conn, row, "withdrawn")
    return {"entry": entry_id, "state": "withdrawn"}


def supersede(conn: psycopg.Connection, entry_id: str, *, by: str) -> dict:
    if by == entry_id:
        raise ValidationError("an entry cannot supersede itself")
    with conn.transaction():
        newer = _row(conn, by)
        if newer["kind"] != "ask":
            raise ValidationError(f"{by} is not a question")
        row = _row(conn, entry_id, lock=True)
        if row["kind"] != "ask":
            raise ValidationError(f"{entry_id} is not a question")
        if row["state"] != "open":
            raise ConflictError(_closed_message(row))
        _set_state(conn, row, "superseded", superseded_by=by)
    return {"entry": entry_id, "state": "superseded", "superseded_by": by}


def _post_transition(conn: psycopg.Connection, entry_id: str, allowed_from: tuple[str, ...], to: str) -> dict:
    with conn.transaction():
        row = _row(conn, entry_id, lock=True)
        if row["kind"] != "post":
            raise ValidationError(f"{entry_id} is not an info entry")
        if row["state"] in allowed_from:
            _set_state(conn, row, to)
    return {"entry": entry_id, "state": to if row["state"] in allowed_from else row["state"]}


def mark_read(conn: psycopg.Connection, entry_id: str) -> dict:
    return _post_transition(conn, entry_id, ("unread",), "read")


def archive(conn: psycopg.Connection, entry_id: str) -> dict:
    return _post_transition(conn, entry_id, ("unread", "read"), "archived")
```

- [x] **Step 4: Run the full store suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: all passed.

- [x] **Step 5: Commit**

```bash
git add modules/inbox/src/agent_inbox/store.py modules/inbox/tests/test_store_states.py
git commit -m "feat(inbox): withdraw, supersede, read and archive"
```

---

### Task 9: Waiting

`wait` blocks on `LISTEN agent_inbox` and re-checks the entry on every notification, with a short poll as a safety net. While it blocks, the entry records the waiting process id (`waiter_pid`), so slice 2's dispatcher knows not to wake the session. On timeout the entry switches to `resume`.

**Files:**
- Modify: `modules/inbox/src/agent_inbox/store.py` (append)
- Create: `modules/inbox/src/agent_inbox/waiting.py`
- Test: `modules/inbox/tests/test_waiting.py`

- [ ] **Step 1: Write the failing tests**

```python
import threading
import time

from agent_inbox import db, store, waiting
from agent_inbox.validate import validate_request

CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}


def make_ask(conn):
    req = validate_request({"title": "Which split?", "control": CHOICE}, "ask")
    return store.create_entry(conn, "ask", req, engine="claude", session_id="s-1", mode="wait")


def later(delay, fn):
    def run():
        time.sleep(delay)
        c = db.connect()
        try:
            fn(c)
        finally:
            c.close()
    t = threading.Thread(target=run)
    t.start()
    return t


def test_answer_wakes_the_waiter_and_marks_delivered(conn):
    e = make_ask(conn)
    t = later(0.3, lambda c: store.answer(c, e["id"], "b", via="web"))
    started = time.monotonic()
    ev = waiting.wait_for(e["id"], timeout=10, poll=30)
    t.join()
    assert time.monotonic() - started < 3, "woke by NOTIFY, not by the 30s poll"
    assert ev["event"] == "answer" and ev["value"] == "b" and ev["via"] == "web"
    got = store.get_entry(conn, e["id"])
    assert got["state"] == "delivered"
    assert got["waiter_pid"] is None


def test_answer_before_wait_returns_immediately(conn):
    e = make_ask(conn)
    store.answer(conn, e["id"], "a", via="cli")
    assert waiting.wait_for(e["id"], timeout=5)["value"] == "a"


def test_followup_returns_with_seq_then_wait_after_it(conn):
    e = make_ask(conn)
    t = later(0.2, lambda c: store.add_followup(c, e["id"], "why not C?", via="telegram"))
    ev = waiting.wait_for(e["id"], timeout=10, poll=30)
    t.join()
    assert ev["event"] == "followup" and ev["text"] == "why not C?"
    t = later(0.2, lambda c: store.answer(c, e["id"], "a", via="web"))
    ev2 = waiting.wait_for(e["id"], after=ev["seq"], timeout=10, poll=30)
    t.join()
    assert ev2["event"] == "answer"


def test_timeout_switches_to_resume(conn):
    e = make_ask(conn)
    ev = waiting.wait_for(e["id"], timeout=0.5, poll=0.2)
    assert ev == {"entry": e["id"], "event": "timeout"}
    got = store.get_entry(conn, e["id"])
    assert got["mode"] == "resume" and got["state"] == "open" and got["waiter_pid"] is None


def test_withdrawn_entry_returns_its_state(conn):
    e = make_ask(conn)
    store.withdraw(conn, e["id"])
    assert waiting.wait_for(e["id"], timeout=5)["event"] == "withdrawn"


def test_waiter_pid_set_while_blocking(conn):
    e = make_ask(conn)
    seen = {}
    t = later(0.3, lambda c: seen.setdefault("pid", store.get_entry(c, e["id"])["waiter_pid"]))
    waiting.wait_for(e["id"], timeout=0.8, poll=0.2)
    t.join()
    assert seen["pid"] is not None
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `.venv/bin/python -m pytest tests/test_waiting.py -v`
Expected: FAIL with `ImportError: cannot import name 'waiting'`

- [ ] **Step 3: Implement the store helpers**

Append to `store.py`:

```python
def set_waiter(conn: psycopg.Connection, entry_id: str, pid: int) -> None:
    conn.execute("UPDATE entries SET waiter_pid = %s, mode = 'wait' WHERE id = %s", (pid, entry_id))


def clear_waiter(conn: psycopg.Connection, entry_id: str, pid: int) -> None:
    conn.execute("UPDATE entries SET waiter_pid = NULL WHERE id = %s AND waiter_pid = %s", (entry_id, pid))


def switch_to_resume(conn: psycopg.Connection, entry_id: str) -> None:
    conn.execute("UPDATE entries SET mode = 'resume', waiter_pid = NULL WHERE id = %s", (entry_id,))


def take_waiter_event(conn: psycopg.Connection, entry_id: str, after: int) -> dict | None:
    """What a blocked waiter should return now, or None to keep waiting.

    Returning an answer to a waiter is its delivery, so the entry moves to delivered.
    """
    with conn.transaction():
        row = _row(conn, entry_id, lock=True)
        if row["state"] in ("answered", "delivered"):
            if row["state"] == "answered":
                conn.execute("UPDATE entries SET state = 'delivered', updated_at = now() WHERE id = %s", (entry_id,))
            return {"entry": entry_id, "event": "answer", **row["answer"]}
        if row["state"] != "open":
            return {"entry": entry_id, "event": row["state"]}
        ev = conn.execute(
            "SELECT * FROM events WHERE entry_id = %s AND type = 'followup' AND seq > %s ORDER BY seq LIMIT 1",
            (entry_id, after),
        ).fetchone()
    if ev is None:
        return None
    shaped = _shape_event(ev)
    shaped.pop("type")
    return {"entry": entry_id, "event": "followup", **shaped}
```

- [ ] **Step 4: Implement the wait loop**

`modules/inbox/src/agent_inbox/waiting.py`:

```python
from __future__ import annotations

import os
import time
from typing import Callable

import psycopg

from agent_inbox import db, store
from agent_inbox.constants import NOTIFY_CHANNEL, WAIT_POLL_SEC, WAIT_TIMEOUT_SEC
from agent_inbox.errors import ValidationError


def wait_for(
    entry_id: str,
    *,
    after: int = 0,
    timeout: float = WAIT_TIMEOUT_SEC,
    poll: float = WAIT_POLL_SEC,
    connect: Callable[[], psycopg.Connection] = db.connect,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    """Block until an answer, a follow-up newer than `after`, a closed state, or the timeout."""
    conn = connect()
    pid = os.getpid()
    try:
        if store.get_entry(conn, entry_id)["kind"] != "ask":
            raise ValidationError(f"{entry_id} is not a question")
        # LISTEN before the first check, so a change between check and sleep still wakes us.
        conn.execute(f"LISTEN {NOTIFY_CHANNEL}")
        store.set_waiter(conn, entry_id, pid)
        deadline = clock() + timeout
        while True:
            event = store.take_waiter_event(conn, entry_id, after)
            if event is not None:
                return event
            remaining = deadline - clock()
            if remaining <= 0:
                store.switch_to_resume(conn, entry_id)
                return {"entry": entry_id, "event": "timeout"}
            for _ in conn.notifies(timeout=min(remaining, poll), stop_after=1):
                pass
    finally:
        try:
            store.clear_waiter(conn, entry_id, pid)
        finally:
            conn.close()
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_waiting.py -v`
Expected: all passed. `test_answer_wakes_the_waiter_and_marks_delivered` is the one that proves NOTIFY works (poll is 30s, so a pass under 3s can only come from the notification).

- [ ] **Step 6: Commit**

```bash
git add modules/inbox/src/agent_inbox/store.py modules/inbox/src/agent_inbox/waiting.py modules/inbox/tests/test_waiting.py
git commit -m "feat(inbox): blocking wait on LISTEN/NOTIFY with resume on timeout"
```

---

### Task 10: CLI

JSON on stdout, diagnostics on stderr, exit codes from `constants.py`. `ask` and `post` read their request JSON from stdin or `--file`, like `agt say`.

**Files:**
- Create: `modules/inbox/src/agent_inbox/cli.py`
- Test: `modules/inbox/tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

```python
import io
import json
import threading
import time

from agent_inbox import db, store
from agent_inbox.cli import main
from agent_inbox.constants import EXIT_CONFLICT, EXIT_IO, EXIT_NOT_FOUND, EXIT_OK, EXIT_TIMEOUT, EXIT_USAGE

CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}
ASKER = ["--engine", "claude", "--session-id", "s-1"]


def stdin(monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))


def out(capsys):
    return json.loads(capsys.readouterr().out)


def test_ask_answer_get_roundtrip(inbox_db, monkeypatch, capsys):
    stdin(monkeypatch, {"title": "Which split?", "control": CHOICE})
    assert main(["ask", *ASKER]) == EXIT_OK
    eid = out(capsys)["entry"]
    assert main(["answer", eid, "--value", "b", "--comment", "thin", "--via", "web"]) == EXIT_OK
    capsys.readouterr()
    assert main(["answer", eid, "--value", "a"]) == EXIT_CONFLICT
    assert "already answered via web" in capsys.readouterr().err
    assert main(["get", eid]) == EXIT_OK
    got = out(capsys)
    assert got["answer"]["value"] == "b" and got["state"] == "answered"


def test_multi_answer_repeats_value(inbox_db, monkeypatch, capsys):
    multi = {"type": "multi", "options": [{"id": "x", "label": "X"}, {"id": "y", "label": "Y"}]}
    stdin(monkeypatch, {"title": "Which ones?", "control": multi})
    main(["ask", *ASKER])
    eid = out(capsys)["entry"]
    assert main(["answer", eid, "--value", "x", "--value", "y"]) == EXIT_OK
    assert out(capsys)["value"] == ["x", "y"]


def test_ask_without_session_is_usage_error(inbox_db, monkeypatch, capsys):
    stdin(monkeypatch, {"title": "t", "control": CHOICE})
    assert main(["ask", "--engine", "claude"]) == EXIT_USAGE
    assert "--session-id" in capsys.readouterr().err


def test_bad_flags_are_usage_not_not_found(inbox_db, capsys):
    assert main(["answer"]) == EXIT_USAGE
    assert main(["ask", "--engine", "hermes", "--session-id", "x"]) == EXIT_USAGE


def test_unknown_entry_is_not_found(inbox_db, capsys):
    assert main(["get", "ib-zzzz"]) == EXIT_NOT_FOUND


def test_store_down_is_io(monkeypatch, capsys):
    monkeypatch.setenv("AGENT_INBOX_DSN", "host=127.0.0.1 port=1 dbname=nope connect_timeout=1")
    assert main(["list"]) == EXIT_IO


def test_post_list_read_archive(inbox_db, monkeypatch, capsys):
    stdin(monkeypatch, {"title": "Nightly run done", "summary": "3 projects, 0 failures"})
    assert main(["post", "--script", "nightly"]) == EXIT_OK
    eid = out(capsys)["entry"]
    assert main(["list", "--json", "--kind", "post"]) == EXIT_OK
    assert [e["id"] for e in out(capsys)] == [eid]
    assert main(["list"]) == EXIT_OK
    assert eid in capsys.readouterr().out
    assert main(["read", eid]) == EXIT_OK and out(capsys)["state"] == "read"
    assert main(["archive", eid]) == EXIT_OK and out(capsys)["state"] == "archived"


def test_thread_commands(inbox_db, monkeypatch, capsys, tmp_path):
    stdin(monkeypatch, {"title": "Which split?", "control": CHOICE})
    main(["ask", *ASKER])
    eid = out(capsys)["entry"]
    assert main(["followup", eid, "--text", "why not C?", "--via", "telegram"]) == EXIT_OK
    capsys.readouterr()
    html = tmp_path / "r.html"
    html.write_text("<p>why</p>")
    assert main(["reply", eid, "--text", "C breaks the tray", "--html-file", str(html)]) == EXIT_OK
    capsys.readouterr()
    new = {"type": "choice", "options": [*CHOICE["options"], {"id": "c", "label": "C"}]}
    assert main(["revise", eid, "--control", json.dumps(new)]) == EXIT_OK
    capsys.readouterr()
    main(["get", eid])
    got = out(capsys)
    assert len(got["thread"]) == 2 and got["thread"][1]["html"] == "<p>why</p>"
    assert len(got["control"]["options"]) == 3


def test_withdraw_and_supersede(inbox_db, monkeypatch, capsys):
    ids = []
    for _ in range(3):
        stdin(monkeypatch, {"title": "q", "control": CHOICE})
        main(["ask", *ASKER])
        ids.append(out(capsys)["entry"])
    assert main(["withdraw", ids[0]]) == EXIT_OK
    capsys.readouterr()
    assert main(["supersede", ids[1], "--by", ids[2]]) == EXIT_OK
    assert out(capsys)["superseded_by"] == ids[2]


def test_ask_wait_returns_the_answer(inbox_db, monkeypatch, capsys):
    def answer_when_open():
        c = db.connect()
        try:
            for _ in range(50):
                rows = store.list_entries(c, states=["open"])
                if rows:
                    store.answer(c, rows[0]["id"], "a", via="web")
                    return
                time.sleep(0.1)
        finally:
            c.close()

    t = threading.Thread(target=answer_when_open)
    t.start()
    stdin(monkeypatch, {"title": "Which split?", "control": CHOICE})
    code = main(["ask", *ASKER, "--wait", "--timeout", "10"])
    t.join()
    assert code == EXIT_OK
    assert out(capsys)["value"] == "a"


def test_wait_timeout_exit_code(inbox_db, monkeypatch, capsys):
    stdin(monkeypatch, {"title": "q", "control": CHOICE})
    main(["ask", *ASKER])
    eid = out(capsys)["entry"]
    assert main(["wait", eid, "--timeout", "1"]) == EXIT_TIMEOUT
    assert out(capsys)["event"] == "timeout"
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `.venv/bin/python -m pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_inbox.cli'`

- [ ] **Step 3: Implement**

`modules/inbox/src/agent_inbox/cli.py`:

```python
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from agent_inbox import db, store, waiting
from agent_inbox.constants import (
    ENGINES,
    EXIT_CONFLICT,
    EXIT_OK,
    EXIT_TIMEOUT,
    EXIT_USAGE,
    KINDS,
    VIAS,
    WAIT_TIMEOUT_SEC,
)
from agent_inbox.errors import InboxError, ValidationError
from agent_inbox.validate import validate_request

WAIT_EXIT = {"answer": EXIT_OK, "followup": EXIT_OK, "timeout": EXIT_TIMEOUT}


class _Parser(argparse.ArgumentParser):
    """argparse exits 2 on bad flags, which would read as not-found; raise a usage error instead."""

    def error(self, message: str) -> None:  # type: ignore[override]
        raise ValidationError(message)


def _add_request_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--file", help="request JSON path (default: stdin)")
    p.add_argument("--html-file", help="HTML part, overrides `html` in the request")


def _add_asker_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--engine", choices=ENGINES)
    p.add_argument("--model")
    p.add_argument("--session-id")
    p.add_argument("--cwd", default=None, help="asker working directory (default: current)")


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="agent-inbox")
    sub = p.add_subparsers(dest="cmd", required=True)

    ask = sub.add_parser("ask")
    _add_request_args(ask)
    _add_asker_args(ask)
    ask.add_argument("--wait", action="store_true")
    ask.add_argument("--timeout", type=float, default=WAIT_TIMEOUT_SEC)

    post = sub.add_parser("post")
    _add_request_args(post)
    _add_asker_args(post)
    post.add_argument("--script", help="name shown as the sender when there is no session")

    wait = sub.add_parser("wait")
    wait.add_argument("id")
    wait.add_argument("--after", type=int, default=0, help="return only follow-ups newer than this seq")
    wait.add_argument("--timeout", type=float, default=WAIT_TIMEOUT_SEC)

    get = sub.add_parser("get")
    get.add_argument("id")

    ls = sub.add_parser("list")
    ls.add_argument("--kind", choices=KINDS)
    ls.add_argument("--state", action="append", dest="states")
    ls.add_argument("--project")
    ls.add_argument("--engine", choices=ENGINES)
    ls.add_argument("--session-id")
    ls.add_argument("--limit", type=int, default=50)
    ls.add_argument("--json", action="store_true")

    ans = sub.add_parser("answer")
    ans.add_argument("id")
    ans.add_argument("--value", action="append", required=True, help="repeat for multi")
    ans.add_argument("--comment")
    ans.add_argument("--via", choices=VIAS, default="cli")

    fu = sub.add_parser("followup")
    fu.add_argument("id")
    fu.add_argument("--text", required=True)
    fu.add_argument("--via", choices=VIAS, default="cli")

    rep = sub.add_parser("reply")
    rep.add_argument("id")
    rep.add_argument("--text", required=True)
    rep.add_argument("--html-file")

    rev = sub.add_parser("revise")
    rev.add_argument("id")
    src = rev.add_mutually_exclusive_group(required=True)
    src.add_argument("--control", help="control JSON")
    src.add_argument("--control-file")

    for name in ("withdraw", "read", "archive"):
        sub.add_parser(name).add_argument("id")

    sup = sub.add_parser("supersede")
    sup.add_argument("id")
    sup.add_argument("--by", required=True)
    return p


def _read_request(args: argparse.Namespace) -> Any:
    raw = Path(args.file).read_text() if args.file else sys.stdin.read()
    data = json.loads(raw) if raw.strip() else {}
    if args.html_file and isinstance(data, dict):
        data["html"] = Path(args.html_file).read_text()
    return data


def _asker(args: argparse.Namespace) -> dict:
    return {
        "engine": args.engine,
        "model": args.model,
        "session_id": args.session_id,
        "cwd": args.cwd or os.getcwd(),
    }


def _waited(event: dict) -> tuple[Any, int]:
    return event, WAIT_EXIT.get(event["event"], EXIT_CONFLICT)


def _table(rows: list[dict]) -> str:
    if not rows:
        return "(no entries)"
    lines = []
    for r in rows:
        project = os.path.basename(r["asker"]["project"] or "") or "-"
        lines.append(
            f"{r['id']}  {r['kind']:<4}  {r['state']:<11}  {r['priority']:<6}  {project:<16.16}  {r['title'][:60]}"
        )
    return "\n".join(lines)


def _dispatch(args: argparse.Namespace) -> tuple[Any, int]:
    cmd = args.cmd
    if cmd == "wait":
        return _waited(waiting.wait_for(args.id, after=args.after, timeout=args.timeout))

    with db.connect() as conn:
        if cmd == "ask":
            req = validate_request(_read_request(args), "ask")
            entry = store.create_entry(conn, "ask", req, mode="wait" if args.wait else "resume", **_asker(args))
            if not args.wait:
                return {"entry": entry["id"], "state": entry["state"]}, EXIT_OK
        elif cmd == "post":
            req = validate_request(_read_request(args), "post")
            entry = store.create_entry(conn, "post", req, script=args.script, **_asker(args))
            return {"entry": entry["id"], "state": entry["state"]}, EXIT_OK
        elif cmd == "get":
            return store.get_entry(conn, args.id), EXIT_OK
        elif cmd == "list":
            rows = store.list_entries(
                conn, kind=args.kind, states=args.states, project=args.project,
                engine=args.engine, session_id=args.session_id, limit=args.limit,
            )
            return (rows if args.json else _table(rows)), EXIT_OK
        elif cmd == "answer":
            value = args.value[0] if len(args.value) == 1 else args.value
            return store.answer(conn, args.id, value, comment=args.comment, via=args.via), EXIT_OK
        elif cmd == "followup":
            return store.add_followup(conn, args.id, args.text, via=args.via), EXIT_OK
        elif cmd == "reply":
            html = Path(args.html_file).read_text() if args.html_file else None
            return store.add_reply(conn, args.id, args.text, html=html), EXIT_OK
        elif cmd == "revise":
            raw = args.control if args.control is not None else Path(args.control_file).read_text()
            return store.revise(conn, args.id, json.loads(raw)), EXIT_OK
        elif cmd == "withdraw":
            return store.withdraw(conn, args.id), EXIT_OK
        elif cmd == "supersede":
            return store.supersede(conn, args.id, by=args.by), EXIT_OK
        elif cmd == "read":
            return store.mark_read(conn, args.id), EXIT_OK
        elif cmd == "archive":
            return store.archive(conn, args.id), EXIT_OK

    # Only `ask --wait` reaches here: the entry is created and committed, so the waiter can see it.
    return _waited(waiting.wait_for(entry["id"], timeout=args.timeout))


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        out, code = _dispatch(args)
    except InboxError as e:
        print(f"agent-inbox: {e}", file=sys.stderr)
        return e.exit_code
    except (OSError, json.JSONDecodeError) as e:
        print(f"agent-inbox: {e}", file=sys.stderr)
        return EXIT_USAGE
    print(out if isinstance(out, str) else json.dumps(out))
    return code


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_cli.py -v`
Expected: all passed. If `argparse --help` or `-h` now raises instead of printing help: `--help` calls `exit`, not `error`, so it still works — confirm with `bin/agent-inbox --help` (exit 0).

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
git add modules/inbox/src/agent_inbox/cli.py modules/inbox/tests/test_cli.py
git commit -m "feat(inbox): agt inbox CLI"
```

---

### Task 11: Wire into `agt`, document, smoke test

**Files:**
- Modify: `agt/agt` (add the `inbox` route and help line)
- Create: `shims/agent-inbox`
- Modify: `install.sh` (link the shim, create the venv)
- Create: `modules/inbox/README.md`

- [ ] **Step 1: Add the route to `agt/agt`**

In the `case "$cmd" in` block, after the `read)` case:

```bash
  inbox)
    exec "$ROOT/modules/inbox/bin/agent-inbox" "$@"
    ;;
```

In the help heredoc, after the `agt read …` line:

```
  agt inbox …             agent-inbox
```

- [ ] **Step 2: Add the shim**

`shims/agent-inbox` (then `chmod +x`):

```bash
#!/usr/bin/env bash
set -euo pipefail
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
  DIR="$(cd "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
ROOT="$(cd "$(dirname "$SOURCE")/.." && pwd)"
exec "$ROOT/agt/agt" inbox "$@"
```

- [ ] **Step 3: Update `install.sh`**

Add `agent-inbox` to the shim loop:

```bash
for s in agent-registry session-waker claude-budget session-report active-sessions \
         rename-session list-sessions agent-say agent-read agent-inbox; do
```

Add `inbox` to the venv loop:

```bash
for mod in registry say read inbox; do
```

- [ ] **Step 4: Write `modules/inbox/README.md`**

```markdown
# agent-inbox

Persistent inbox for AI agents to ask Tiago questions or leave him information. Answers are delivered back to the session that asked, even after it has exited (delivery lands in slice 2; this slice stores questions and answers and supports blocking waits).

**Design spec:** [docs/superpowers/specs/2026-11-23-agent-inbox-design.md](docs/superpowers/specs/2026-11-23-agent-inbox-design.md)

## Install

Postgres 17 from Homebrew, running as a service on port 5433 (5432 is Docker `am-video-db`, not used):

    HOMEBREW_NO_AUTO_UPDATE=1 brew install postgresql@17
    sed -i '' 's/^#port = 5432/port = 5433/' /opt/homebrew/var/postgresql@17/postgresql.conf
    brew services start postgresql@17
    /opt/homebrew/opt/postgresql@17/bin/createdb -h localhost -p 5433 agent_inbox

Then from the repo root: `./install.sh` (creates `modules/inbox/.venv`, links `agent-inbox` / `agt inbox`). The schema is created on first connect.

Store location: `AGENT_INBOX_DSN` (default `host=localhost port=5433 dbname=agent_inbox`).

## Usage

Request JSON on stdin (or `--file`). stdout is one JSON object; diagnostics go to stderr.

Ask and return at once (resume mode):

    printf '%s' '{"title":"Which split?","control":{"type":"choice","options":[{"id":"a","label":"Tauri"},{"id":"b","label":"Go tray","recommended":true}]}}' \
      | agt inbox ask --engine claude --session-id "$SESSION_ID"

Ask and block (wait mode, default 30 min; on timeout the entry switches to resume):

    … | agt inbox ask --engine claude --session-id "$SESSION_ID" --wait

A follow-up returns `{"event":"followup","seq":N,…}`. Reply, then keep waiting:

    agt inbox reply ib-7k3q --text "C breaks the tray"
    agt inbox wait ib-7k3q --after N

Leave information (no question):

    printf '%s' '{"title":"Nightly run done","summary":"3 projects, 0 failures"}' | agt inbox post --script nightly

Answer and manage:

    agt inbox answer ib-7k3q --value b --comment "keep it thin" --via web
    agt inbox followup ib-7k3q --text "why not C?"
    agt inbox list            # table; --json for machines
    agt inbox get ib-7k3q     # full entry, thread and revisions

Controls: `choice` (2–6 options), `multi`, `text` (`size`: short|long), `approve` (approve, or revise with a required `--comment`).

## Exit codes

| Code | Meaning |
|---|---|
| 0 | ok (including a returned answer or follow-up) |
| 1 | usage or validation error |
| 2 | entry not found |
| 3 | store unreachable |
| 4 | conflict: already answered, or closed |
| 5 | wait timed out |

## Tests

    cd modules/inbox && .venv/bin/python -m pytest -q

Tests need a `agent_inbox_test` database (`createdb -h localhost -p 5433 agent_inbox_test`) and drop its tables on every test. Override with `AGENT_INBOX_TEST_DSN`.
```

- [ ] **Step 5: Install and smoke-test through `agt`**

```bash
./install.sh
printf '%s' '{"title":"Smoke: pick one","control":{"type":"choice","options":[{"id":"a","label":"A"},{"id":"b","label":"B"}]}}' \
  | agt inbox ask --engine claude --session-id smoke-1
```

Expected: `{"entry": "ib-....", "state": "open"}`. Then, with that id:

```bash
agt inbox answer <id> --value a --via cli
agt inbox answer <id> --value b; echo "exit=$?"
agt inbox list
agt inbox withdraw <id>; echo "exit=$?"
```

Expected: the second answer prints `already answered via cli: a` on stderr and `exit=4`; `list` shows the entry as `answered`; withdraw prints a conflict and `exit=4`.

Wait-mode smoke, in two terminals: run `… | agt inbox ask --engine claude --session-id smoke-2 --wait` in one, then `agt inbox list --state open --json` and `agt inbox answer <id> --value b` in the other. Expected: the first terminal prints the answer JSON within about a second and exits 0.

Clean up the live store afterwards so smoke entries don't show up in slice 3's UI:

```bash
/opt/homebrew/opt/postgresql@17/bin/psql -h localhost -p 5433 -d agent_inbox -c "DELETE FROM entries WHERE session_id LIKE 'smoke-%'"
```

- [ ] **Step 6: Commit**

```bash
git add agt/agt shims/agent-inbox install.sh modules/inbox/README.md
git commit -m "feat(inbox): wire agt inbox into the dispatcher and installer"
```
