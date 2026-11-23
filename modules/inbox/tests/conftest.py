from __future__ import annotations

import os

import psycopg
import pytest

from agent_inbox import db
from agent_inbox.reach import Reach


@pytest.fixture(autouse=True)
def reachable(monkeypatch):
    """Answers in tests must not shell out to registry or claude-budget."""
    monkeypatch.setattr("agent_inbox.reach.for_entry", lambda entry: Reach("resumable"))


@pytest.fixture(autouse=True)
def no_telegram(monkeypatch):
    """The default target is the real Hermes home channel; tests opt in with their own."""
    monkeypatch.setenv("AGENT_INBOX_TELEGRAM_TO", "")

TEST_DSN = os.environ.get("AGENT_INBOX_TEST_DSN", "host=localhost port=5433 dbname=agent_inbox_test")


@pytest.fixture
def inbox_db(monkeypatch):
    """Point the module at the test database and start from an empty schema."""
    monkeypatch.setenv("AGENT_INBOX_DSN", TEST_DSN)
    try:
        conn = psycopg.connect(TEST_DSN, autocommit=True)
    except psycopg.OperationalError as e:
        pytest.fail(f"test store unreachable ({TEST_DSN}): {e}. Run Task 0 of the plan.")
    conn.execute("DROP TABLE IF EXISTS events, entries, ops CASCADE")
    conn.close()
    return TEST_DSN


@pytest.fixture
def conn(inbox_db):
    c = db.connect()
    yield c
    c.close()
