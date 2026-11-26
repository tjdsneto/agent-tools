import json
from datetime import datetime, timedelta, timezone

import pytest

from agent_registry import archive, liveness, topics

NOW = datetime(2026, 11, 25, 20, 0, tzinfo=timezone.utc)


def _row(agent_type, session_id, directory, minutes_ago):
    ping = (NOW - timedelta(minutes=minutes_ago)).isoformat()
    return {
        "registry_id": f"r-{session_id}", "session_id": session_id, "agent_type": agent_type, "directory": directory,
        "parent_session_id": None, "status": "idle", "summary": "", "issue": None, "pr": None, "branch": None,
        "goflow_timer_id": None, "registered_at": ping, "last_ping": ping, "updated_at": ping,
    }


def _registry(path, *rows):
    path.write_text(json.dumps({"version": 1, "sessions": list(rows)}))


def _archive(path, *rows):
    path.with_name("archive.jsonl").write_text("".join(
        json.dumps({"archived_at": NOW.isoformat(), "reason": "unregister", "session": row}) + "\n" for row in rows
    ))


def test_rows_and_the_archive_say_who_is_live_idle_or_ended(tmp_registry):
    _registry(tmp_registry, _row("claude", "on", "/p/a", 5), _row("claude", "old", "/p/b", 180))
    _archive(tmp_registry, _row("codex", "gone", "/p/old", 900), _row("codex", "gone", "/p/c", 600))
    got = liveness.lookup({("claude", "on"), ("claude", "old"), ("codex", "gone"), ("cursor", "never")}, now=NOW)
    assert got == {
        ("claude", "on"): {"live": True, "state": "live", "directory": "/p/a"},
        ("claude", "old"): {"live": False, "state": "idle", "directory": "/p/b"},
        ("codex", "gone"): {"live": False, "state": "ended", "directory": "/p/c"},
        ("cursor", "never"): {"live": False, "state": "ended", "directory": None},
    }


def test_the_archive_is_read_only_for_sessions_without_a_row(tmp_registry, monkeypatch):
    _registry(tmp_registry, _row("claude", "on", "/p/a", 5))
    monkeypatch.setattr(archive, "read_events", lambda: pytest.fail("read the archive"))
    assert liveness.lookup({("claude", "on")}, now=NOW)[("claude", "on")]["live"] is True
    assert liveness.lookup(set(), now=NOW) == {}


def test_a_corrupt_registry_leaves_every_session_unknown(tmp_registry):
    tmp_registry.write_text("{not json")
    assert liveness.lookup({("claude", "x")}, now=NOW) == {
        ("claude", "x"): {"live": False, "state": "unknown", "directory": None},
    }


def test_annotate_marks_every_session_in_the_tree(tmp_registry):
    topics.set_intent("claude", "p", "Parent")
    fork = topics.record_fork("claude", "p", "Side", mode="side", backend="none", brief_text="b")["topic"]["id"]
    topics.adopt("claude", "c", fork)
    _registry(tmp_registry, _row("claude", "c", "/p/side", 1))
    (root,) = liveness.annotate(topics.tree(), now=NOW)
    sessions = root["sessions"] + root["children"][0]["sessions"]
    # Logs are read in path order, so the adopter's log (c) comes before the parent's (p).
    assert [(s["session_id"], s["role"], s["state"], s["directory"]) for s in sessions] == [
        ("p", "intent", "ended", None), ("c", "intent", "live", "/p/side"), ("p", "forked", "ended", None),
    ]
