from agent_registry import session_state


def test_sidecar_path_under_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_REGISTRY_PATH", str(tmp_path / "registry.json"))
    p = session_state.sidecar_path("claude", "sess-1")
    assert p == tmp_path / "by-session" / "claude" / "sess-1.json"


def test_write_read_delete_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_REGISTRY_PATH", str(tmp_path / "registry.json"))
    session_state.write_state("cursor", "abc", registry_id="rid-1", last_heartbeat_at="2026-09-25T12:00:00+00:00")
    st = session_state.read_state("cursor", "abc")
    assert st == {"registry_id": "rid-1", "last_heartbeat_at": "2026-09-25T12:00:00+00:00"}
    session_state.delete_state("cursor", "abc")
    assert session_state.read_state("cursor", "abc") is None
