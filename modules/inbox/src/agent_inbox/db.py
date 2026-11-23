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
