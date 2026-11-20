from datetime import datetime, timezone
from agent_registry import archive, ops, store


def test_unregister_appends_archive(tmp_registry):
    s = ops.register(agent_type="cursor", session_id="a", directory="/p")
    ops.unregister(s.registry_id)
    events = archive.read_events()
    assert len(events) == 1
    assert events[0]["reason"] == "unregister"
    assert events[0]["session"]["session_id"] == "a"
    assert store.load().sessions == []


def test_replace_archives_displaced(tmp_registry):
    first = ops.register(agent_type="cursor", session_id="a", directory="/old")
    ops.register(agent_type="cursor", session_id="a", directory="/new", replace=True)
    events = archive.read_events()
    assert len(events) == 1
    assert events[0]["reason"] == "replace"
    assert events[0]["session"]["registry_id"] == first.registry_id
    assert events[0]["session"]["directory"] == "/old"
    assert [x.directory for x in store.load().sessions] == ["/new"]


def test_prune_yes_archives_stale(tmp_registry):
    ops.register(agent_type="cursor", session_id="old", directory="/a")
    ops.register(agent_type="cursor", session_id="live", directory="/b")
    reg = store.load()
    for s in reg.sessions:
        if s.session_id == "old":
            s.last_ping = "2026-09-24T10:00:00+00:00"
    store.save(reg)
    now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    removed = ops.prune(dry_run=False, yes=True, now=now)
    assert [x["session_id"] for x in removed] == ["old"]
    assert "registry_id" not in removed[0]
    events = archive.read_events()
    assert len(events) == 1
    assert events[0]["reason"] == "prune"
    assert [s.session_id for s in store.load().sessions] == ["live"]


def test_prune_dry_run_does_not_archive(tmp_registry):
    ops.register(agent_type="cursor", session_id="old", directory="/a")
    reg = store.load()
    reg.sessions[0].last_ping = "2026-09-24T10:00:00+00:00"
    store.save(reg)
    now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    ops.prune(dry_run=True, yes=False, now=now)
    assert archive.read_events() == []
    assert len(store.load().sessions) == 1
