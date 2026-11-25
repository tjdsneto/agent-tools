from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from agent_inbox import topics
from agent_inbox.constants import ASK_LIVE_STATES, CLOSED_STATES, HTML_MAX_BYTES, VIAS
from agent_inbox.errors import ConflictError, NotFoundError, StoreError, ValidationError
from agent_inbox.ids import new_id
from agent_inbox.validate import validate_answer, validate_control

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
        "delivery": row.get("delivery") or {},
        "topic_path": row.get("topic_path"),
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
        # A script asker has no session: it is never woken and reads its answer with `get`.
        if not script and (not engine or not session_id):
            raise ValidationError("ask needs --engine and --session-id, or --script for an asker that reads its own answer")
        mode, state = mode or "resume", "open"
    else:
        if not session_id and not script:
            raise ValidationError("post needs --session-id or --script")
        if session_id and not engine:
            raise ValidationError("--session-id needs --engine")
        mode, state = None, "unread"
    # Resolved before the insert: an unknown named topic must not leave an entry behind.
    path = topics.path_for(engine=engine, session_id=session_id, topic=req.get("topic"))
    params = {
        "kind": kind, "engine": engine, "model": model, "session_id": session_id,
        "cwd": cwd, "project": project_root(cwd), "script": script,
        "priority": req["priority"], "mode": mode, "title": req["title"],
        "summary": req.get("summary"), "detail": req.get("detail"), "html": req.get("html"),
        "control": _jsonb(req.get("control")), "source": _jsonb(req.get("source")),
        "expires_at": req.get("expires_at"), "state": state, "topic_path": _jsonb(path),
    }
    for _ in range(ID_ATTEMPTS):
        params["id"] = new_id()
        row = conn.execute(
            """
            INSERT INTO entries (id, kind, engine, model, session_id, cwd, project, script, priority, mode,
                                 title, summary, detail, html, control, source, expires_at, state, topic_path)
            VALUES (%(id)s, %(kind)s, %(engine)s, %(model)s, %(session_id)s, %(cwd)s, %(project)s, %(script)s,
                    %(priority)s, %(mode)s, %(title)s, %(summary)s, %(detail)s, %(html)s, %(control)s,
                    %(source)s, %(expires_at)s, %(state)s, %(topic_path)s)
            ON CONFLICT (id) DO NOTHING
            RETURNING id
            """,
            params,
        ).fetchone()
        if row:
            entry = get_entry(conn, row["id"])
            # The connection autocommits, so the insert is committed before the note names it.
            topics.note(
                "asked" if kind == "ask" else "posted", entry["id"], path,
                engine=engine, session_id=session_id, title=entry["title"],
            )
            return entry
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
    newest: bool = False,
) -> list[dict]:
    """Urgent first, then oldest first; newest=True is plain newest first, for history."""
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
    order = "created_at DESC, id DESC" if newest else f"{PRIORITY_ORDER}, created_at, id"
    sql += f" ORDER BY {order} LIMIT %s"
    params.append(limit)
    return [
        {k: v for k, v in _shape(r).items() if k not in LIST_HIDDEN}
        for r in conn.execute(sql, params).fetchall()
    ]


def list_projects(conn: psycopg.Connection) -> list[str]:
    """Every project that has an entry, most recently active first."""
    rows = conn.execute(
        "SELECT project FROM entries WHERE project IS NOT NULL GROUP BY project ORDER BY max(created_at) DESC"
    ).fetchall()
    return [row["project"] for row in rows]


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
        # A chat answer is recorded by the asker itself: it is running and already
        # has the answer, so there is no reachability to check and nothing to deliver.
        if via != "chat" and row["session_id"]:
            from agent_inbox.reach import for_entry
            asker = {k: row[k] for k in ("engine", "model", "session_id", "cwd", "project", "script")}
            reach = for_entry({"asker": asker, "delivery": row.get("delivery") or {}})
            if reach.status in ("held", "unreachable"):
                when = f" until {reach.reachable_at}" if reach.reachable_at else ""
                raise ConflictError(f"{entry_id} is {reach.status}{when}")
        clean = validate_answer(row["control"], value, comment)
        payload = {"value": clean, "comment": (comment or "").strip() or None, "via": via, "at": _now_iso()}
        state = "delivered" if via == "chat" else "answered"
        conn.execute(
            "UPDATE entries SET state = %s, answer = %s, updated_at = now() WHERE id = %s",
            (state, Jsonb(payload), entry_id),
        )
        _event(conn, entry_id, "answer", via, payload)
    topics.note(
        "answered", entry_id, row["topic_path"], engine=row["engine"], session_id=row["session_id"],
        value=clean, via=via,
    )
    if via != "telegram":
        try:
            from agent_inbox.notify import note_answered
            note_answered(entry_id, via, clean, row["priority"])
        except OSError as exc:
            print(f"telegram note failed: {exc}", file=sys.stderr)
    return {"entry": entry_id, "state": state, **payload}


def _set_state(conn: psycopg.Connection, row: dict, to: str, **extra: Any) -> None:
    sets = ["state = %s", "updated_at = now()"] + [f"{k} = %s" for k in extra]
    conn.execute(f"UPDATE entries SET {', '.join(sets)} WHERE id = %s", (to, *extra.values(), row["id"]))
    _event(conn, row["id"], "state", None, {"from": row["state"], "to": to})


def note_closed(row: dict, state: str) -> None:
    """An ask left open without an answer; tell its topic, so it stops counting as waiting."""
    topics.note(
        "closed", row["id"], row.get("topic_path"), engine=row.get("engine"), session_id=row.get("session_id"),
        state=state,
    )


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


def withdraw(conn: psycopg.Connection, entry_id: str) -> dict:
    with conn.transaction():
        row = _row(conn, entry_id, lock=True)
        if row["kind"] != "ask":
            raise ValidationError(f"{entry_id} is not a question")
        if row["state"] != "open":
            raise ConflictError(_closed_message(row))
        _set_state(conn, row, "withdrawn")
    note_closed(row, "withdrawn")
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
    note_closed(row, "superseded")
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
