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
