import pytest
from datetime import datetime, timedelta, timezone

from agent_registry import lifecycle, ops, session_state
from agent_registry.models import now_iso


def test_ensure_registers_and_writes_sidecar(tmp_registry):
    out = lifecycle.ensure("claude", "s1", str(tmp_registry.parent / "proj"))
    assert out["created"] is True
    assert out["session"]["session_id"] == "s1"
    st = session_state.read_state("claude", "s1")
    assert st["registry_id"] == out["session"]["registry_id"]


def test_ensure_idempotent_same_session(tmp_registry):
    a = lifecycle.ensure("claude", "s1", "/a")
    b = lifecycle.ensure("claude", "s1", "/a")
    assert a["session"]["registry_id"] == b["session"]["registry_id"]
    assert b["created"] is False


def test_ensure_replace_on_directory_change_uses_replace(tmp_registry):
    lifecycle.ensure("claude", "s1", "/old")
    out = lifecycle.ensure("claude", "s1", "/new", replace=True)
    assert out["session"]["directory"] == "/new"


def test_heartbeat_throttles(tmp_registry, monkeypatch):
    monkeypatch.setenv("AGENT_REGISTRY_HEARTBEAT_SECONDS", "3600")
    e = lifecycle.ensure("cursor", "c1", "/p")
    rid = e["session"]["registry_id"]
    session_state.write_state("cursor", "c1", registry_id=rid, last_heartbeat_at=now_iso())
    h1 = lifecycle.heartbeat("cursor", "c1")
    assert h1["skipped"] is True
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    session_state.write_state("cursor", "c1", registry_id=rid, last_heartbeat_at=old)
    h2 = lifecycle.heartbeat("cursor", "c1")
    assert h2["skipped"] is False
    assert h2["session"]["registry_id"] == rid


def test_heartbeat_model_change_bypasses_throttle(tmp_registry, monkeypatch):
    monkeypatch.setenv("AGENT_REGISTRY_HEARTBEAT_SECONDS", "3600")
    e = lifecycle.ensure("cursor", "c1", "/p", model="gpt-5")
    rid = e["session"]["registry_id"]
    session_state.write_state("cursor", "c1", registry_id=rid, last_heartbeat_at=now_iso())
    same = lifecycle.heartbeat("cursor", "c1", model="gpt-5")
    assert same["skipped"] is True
    changed = lifecycle.heartbeat("cursor", "c1", model="claude-opus-4")
    assert changed["skipped"] is False
    assert changed["meta_changed"] is True
    assert changed["session"]["model"] == "claude-opus-4"


def test_heartbeat_keeps_default_model(tmp_registry, monkeypatch):
    monkeypatch.setenv("AGENT_REGISTRY_HEARTBEAT_SECONDS", "3600")
    e = lifecycle.ensure("cursor", "c1", "/p", model="grok-4.7")
    rid = e["session"]["registry_id"]
    session_state.write_state("cursor", "c1", registry_id=rid, last_heartbeat_at=now_iso())
    changed = lifecycle.heartbeat("cursor", "c1", model="default", status="working")
    assert changed["skipped"] is False
    assert changed["session"]["model"] == "default"
    assert changed["session"]["status"] == "working"


def test_heartbeat_title_change_bypasses_throttle(tmp_registry, monkeypatch):
    monkeypatch.setenv("AGENT_REGISTRY_HEARTBEAT_SECONDS", "3600")
    e = lifecycle.ensure("claude", "s1", "/p", title="old-name")
    rid = e["session"]["registry_id"]
    session_state.write_state("claude", "s1", registry_id=rid, last_heartbeat_at=now_iso())
    changed = lifecycle.heartbeat("claude", "s1", title="auth-refactor")
    assert changed["skipped"] is False
    assert changed["meta_changed"] is True
    assert changed["session"]["title"] == "auth-refactor"


def test_heartbeat_status_sets_working_and_idle(tmp_registry, monkeypatch):
    monkeypatch.setenv("AGENT_REGISTRY_HEARTBEAT_SECONDS", "3600")
    e = lifecycle.ensure("cursor", "c1", "/p")
    rid = e["session"]["registry_id"]
    session_state.write_state("cursor", "c1", registry_id=rid, last_heartbeat_at=now_iso())
    working = lifecycle.heartbeat("cursor", "c1", status="working")
    assert working["skipped"] is False
    assert working["session"]["status"] == "working"
    session_state.write_state("cursor", "c1", registry_id=rid, last_heartbeat_at=now_iso())
    same = lifecycle.heartbeat("cursor", "c1", status="working")
    assert same["skipped"] is True
    idle = lifecycle.heartbeat("cursor", "c1", status="idle")
    assert idle["skipped"] is False
    assert idle["session"]["status"] == "idle"


def test_ensure_records_model(tmp_registry):
    out = lifecycle.ensure("claude", "s1", "/p", model="claude-sonnet-4")
    assert out["session"]["model"] == "claude-sonnet-4"
    again = lifecycle.ensure("claude", "s1", "/p", model="claude-opus-4")
    assert again["created"] is False
    assert again["session"]["model"] == "claude-opus-4"


def test_ensure_records_title(tmp_registry):
    out = lifecycle.ensure("claude", "s1", "/p", title="fix-hpos")
    assert out["session"]["title"] == "fix-hpos"


def test_ensure_cursor_fills_title_from_composer_name(tmp_registry, monkeypatch):
    monkeypatch.setattr(
        "agent_registry.usage.cursor_composer_names",
        lambda session_ids, db_path=None: {"c1": "Orcamentos de audio"},
    )
    out = lifecycle.ensure("cursor", "c1", "/obra-records")
    assert out["session"]["title"] == "Orcamentos de audio"


def test_heartbeat_cursor_renamed_composer_bypasses_throttle(tmp_registry, monkeypatch):
    monkeypatch.setenv("AGENT_REGISTRY_HEARTBEAT_SECONDS", "3600")
    names = {"c1": "Old chat"}
    monkeypatch.setattr(
        "agent_registry.usage.cursor_composer_names",
        lambda session_ids, db_path=None: {
            sid: names[sid] for sid in session_ids if sid in names
        },
    )
    e = lifecycle.ensure("cursor", "c1", "/obra-records")
    assert e["session"]["title"] == "Old chat"
    rid = e["session"]["registry_id"]
    session_state.write_state("cursor", "c1", registry_id=rid, last_heartbeat_at=now_iso())
    names["c1"] = "Renamed chat"
    changed = lifecycle.heartbeat("cursor", "c1", status="idle")
    assert changed["skipped"] is False
    assert changed["meta_changed"] is True
    assert changed["session"]["title"] == "Renamed chat"


def test_heartbeat_ensure_if_missing_sidecar(tmp_registry):
    h = lifecycle.heartbeat("claude", "missing")
    assert h["skipped"] is True
    assert h.get("reason") == "no_sidecar"


def test_end_unregisters_and_deletes_sidecar(tmp_registry):
    lifecycle.ensure("claude", "s1", "/p")
    lifecycle.end("claude", "s1")
    assert session_state.read_state("claude", "s1") is None
    active, stale = ops.list_split()
    assert active == [] and stale == []


def test_ensure_stale_sidecar_reregisters_with_created_true(tmp_registry):
    lifecycle.ensure("claude", "s1", "/p")
    st = session_state.read_state("claude", "s1")
    old_rid = st["registry_id"]
    ops.unregister(old_rid)
    out = lifecycle.ensure("claude", "s1", "/p")
    assert out["created"] is True
    assert out["session"]["registry_id"] != old_rid


def test_ensure_replace_false_stale_sidecar_raises(tmp_registry):
    lifecycle.ensure("claude", "s1", "/p")
    st = session_state.read_state("claude", "s1")
    ops.unregister(st["registry_id"])
    with pytest.raises(ops.UnknownRegistryIdError):
        lifecycle.ensure("claude", "s1", "/p", replace=False)
    active, stale = ops.list_split()
    assert active == [] and stale == []


def test_self_view_returns_session_with_registry_id(tmp_registry):
    out = lifecycle.ensure("claude", "s1", "/p")
    rid = out["session"]["registry_id"]
    view = lifecycle.self_view("claude", "s1")
    assert view is not None
    assert view["registry_id"] == rid
    assert view["session_id"] == "s1"
    assert view["agent_type"] == "claude"


def test_self_view_none_without_sidecar(tmp_registry):
    assert lifecycle.self_view("claude", "missing") is None


def test_self_view_none_when_registry_entry_gone(tmp_registry):
    out = lifecycle.ensure("claude", "s1", "/p")
    ops.unregister(out["session"]["registry_id"])
    assert lifecycle.self_view("claude", "s1") is None
