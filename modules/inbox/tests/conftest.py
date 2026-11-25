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
    monkeypatch.setattr("agent_inbox.notify.hermes_card", lambda to, text, pairs: False)
    # Urgent pushes also notify the Mac; a test run must not pop real notifications.
    monkeypatch.setattr("agent_inbox.notify.notify_mac", lambda title, body: None)


class FakeRegistry:
    """Stands in for agent_inbox.topics.registry. replies maps a registry command to its
    result, or to a callable that gets the args. Unset commands return None, like a
    registry that is down."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.replies: dict = {}

    def __call__(self, *args):
        self.calls.append(list(args))
        reply = self.replies.get(args[0])
        return reply(*args) if callable(reply) else reply

    def notes(self) -> list[list[str]]:
        return [call[1:] for call in self.calls if call[0] == "topic-note"]


@pytest.fixture(autouse=True)
def fake_registry(monkeypatch):
    """Tests never shell out to the agent registry."""
    fake = FakeRegistry()
    monkeypatch.setattr("agent_inbox.topics.registry", fake)
    return fake

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


def pytest_ignore_collect(collection_path, config):
    """Collect tests/blackbox only when that path was requested."""
    parts = getattr(collection_path, "parts", ())
    if "blackbox" not in parts:
        return False
    return not any("blackbox" in str(arg) for arg in config.args)
