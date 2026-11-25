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


def test_unreachable_store_is_a_store_error(monkeypatch):
    monkeypatch.setenv("AGENT_INBOX_DSN", "host=127.0.0.1 port=1 dbname=nope connect_timeout=1")
    with pytest.raises(StoreError, match="cannot reach the inbox store"):
        db.connect()


def test_existing_database_gains_topic_path_and_its_index(conn):
    conn.execute("ALTER TABLE entries DROP COLUMN IF EXISTS topic_path")  # drops the index with it
    assert conn.execute("SELECT to_regclass('entries_topic') AS t").fetchone()["t"] is None
    db.ensure_schema(conn)
    col = conn.execute(
        "SELECT data_type FROM information_schema.columns WHERE table_name = 'entries' AND column_name = 'topic_path'"
    ).fetchone()
    assert col is not None and col["data_type"] == "jsonb"
    assert conn.execute("SELECT to_regclass('entries_topic') AS t").fetchone()["t"] is not None


def test_connect_on_a_migrated_database_does_not_queue_behind_a_reader(conn, inbox_db):
    import threading
    import time

    reader = psycopg.connect(inbox_db)  # BEGIN implicitly; holds a lock on entries until closed
    reader.execute("SELECT 1 FROM entries LIMIT 1")
    done = []

    def connect():
        c = db.connect()
        c.close()
        done.append(True)

    t = threading.Thread(target=connect, daemon=True)
    start = time.monotonic()
    t.start()
    t.join(2)
    elapsed = time.monotonic() - start
    reader.rollback()  # unblocks a connect that queued, so the thread can finish either way
    reader.close()
    t.join(5)
    assert done and elapsed < 1, f"connect took {elapsed:.1f}s behind an open reader"
