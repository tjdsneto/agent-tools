import pytest
from agent_registry import store
from agent_registry.models import RegistryFile, Session


def test_load_missing_file_returns_empty(tmp_registry):
    reg = store.load()
    assert reg.version == 1
    assert reg.sessions == []


def test_save_roundtrip(tmp_registry):
    reg = RegistryFile(sessions=[
        Session(
            registry_id="r1", session_id="s1", agent_type="claude",
            directory="/a", parent_session_id=None, status="idle",
            summary="", issue=None, pr=None, branch=None, goflow_timer_id=None,
            registered_at="2026-09-24T12:00:00+00:00",
            last_ping="2026-09-24T12:00:00+00:00",
            updated_at="2026-09-24T12:00:00+00:00",
        )
    ])
    store.save(reg)
    loaded = store.load()
    assert len(loaded.sessions) == 1
    assert loaded.sessions[0].registry_id == "r1"


def test_corrupt_nonempty_fails_closed(tmp_registry):
    tmp_registry.write_text("{not-json", encoding="utf-8")
    with pytest.raises(store.CorruptRegistryError):
        store.load()
    assert tmp_registry.read_text(encoding="utf-8") == "{not-json"


def test_schema_invalid_json_fails_closed(tmp_registry):
    payload = '{"version":1,"sessions":[{}]}'
    tmp_registry.write_text(payload, encoding="utf-8")
    with pytest.raises(store.CorruptRegistryError):
        store.load()
    assert tmp_registry.read_text(encoding="utf-8") == payload


def test_empty_file_treated_as_empty_registry(tmp_registry):
    tmp_registry.write_text("", encoding="utf-8")
    assert store.load().sessions == []


def test_transact_exists_and_mutates(tmp_registry):
    assert hasattr(store, "transact")

    def bump_version(reg):
        reg.version = 2
        return reg.version

    assert store.transact(bump_version) == 2
    assert store.load().version == 2
