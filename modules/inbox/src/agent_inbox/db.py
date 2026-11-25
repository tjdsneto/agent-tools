from __future__ import annotations

import os
from importlib import resources

import psycopg
from psycopg.rows import dict_row

from agent_inbox.constants import DEFAULT_DSN
from agent_inbox.errors import StoreError

SCHEMA_LOCK = 7_204_811  # arbitrary advisory-lock key for schema setup
# (sql, catalog check that is true once it has been applied). ALTER TABLE and CREATE INDEX take
# table locks even when IF NOT EXISTS makes them a no-op, so they only run when the catalog says
# they are needed; otherwise every connect would queue behind any open read on entries.
MIGRATIONS = (
    (
        "ALTER TABLE entries ADD COLUMN IF NOT EXISTS delivery jsonb NOT NULL DEFAULT '{}'::jsonb",
        "SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() "
        "AND table_name = 'entries' AND column_name = 'delivery'",
    ),
    # The asking session's topic path, root intent first, as it was when the entry was created.
    (
        "ALTER TABLE entries ADD COLUMN IF NOT EXISTS topic_path jsonb",
        "SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() "
        "AND table_name = 'entries' AND column_name = 'topic_path'",
    ),
    (
        "CREATE INDEX IF NOT EXISTS entries_topic ON entries ((topic_path->-1->>'id'))",
        "SELECT 1 FROM pg_indexes WHERE schemaname = current_schema() AND indexname = 'entries_topic'",
    ),
)
OPS = """
CREATE TABLE IF NOT EXISTS ops (
    key   text PRIMARY KEY,
    value jsonb NOT NULL
)
"""


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
    # Always under the lock: two first connects after a deploy would otherwise race on CREATE INDEX.
    conn.execute("SELECT pg_advisory_lock(%s)", (SCHEMA_LOCK,))
    try:
        if conn.execute("SELECT to_regclass('events') AS t").fetchone()["t"] is None:
            conn.execute(schema_sql())
        for sql, applied in MIGRATIONS:
            if conn.execute(applied).fetchone() is None:
                conn.execute(sql)
        conn.execute(OPS)
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (SCHEMA_LOCK,))
