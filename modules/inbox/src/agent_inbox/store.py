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
