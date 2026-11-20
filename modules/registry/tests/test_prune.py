from datetime import datetime, timezone
import pytest
from agent_registry import ops, store

def _age(session_id: str, last_ping: str) -> None:
    reg = store.load()
    for s in reg.sessions:
        if s.session_id == session_id:
            s.last_ping = last_ping
    store.save(reg)

def test_prune_dry_run_does_not_delete(tmp_registry):
    ops.register(agent_type="cursor", session_id="old", directory="/a")
    _age("old", "2026-09-24T10:00:00+00:00")
    now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    would = ops.prune(dry_run=True, yes=False, now=now)
    assert [x["session_id"] for x in would] == ["old"]
    assert all("registry_id" not in x for x in would)
    assert len(store.load().sessions) == 1

def test_prune_yes_deletes_stale(tmp_registry):
    ops.register(agent_type="cursor", session_id="old", directory="/a")
    ops.register(agent_type="cursor", session_id="live", directory="/b")
    _age("old", "2026-09-24T10:00:00+00:00")
    now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    removed = ops.prune(dry_run=False, yes=True, now=now)
    assert [x["session_id"] for x in removed] == ["old"]
    assert [s.session_id for s in store.load().sessions] == ["live"]

def test_prune_without_yes_raises(tmp_registry):
    with pytest.raises(ops.ValidationError):
        ops.prune(dry_run=False, yes=False)
