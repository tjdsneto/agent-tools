import pytest
from agent_registry import ops, store


def test_register_returns_session_with_registry_id(tmp_registry):
    s = ops.register(agent_type="cursor", session_id="abc", directory="/proj")
    assert s.registry_id
    assert s.session_id == "abc"
    assert s.status == "idle"
    assert store.load().sessions[0].registry_id == s.registry_id


def test_register_duplicate_session_id_errors(tmp_registry):
    ops.register(agent_type="cursor", session_id="abc", directory="/proj")
    with pytest.raises(ops.DuplicateSessionError):
        ops.register(agent_type="claude", session_id="abc", directory="/other")


def test_register_replace_overwrites(tmp_registry):
    first = ops.register(agent_type="cursor", session_id="abc", directory="/old")
    second = ops.register(
        agent_type="cursor", session_id="abc", directory="/new", replace=True
    )
    assert second.directory == "/new"
    assert second.registry_id != first.registry_id
    assert len(store.load().sessions) == 1


def test_register_with_parent(tmp_registry):
    s = ops.register(
        agent_type="cursor",
        session_id="child",
        directory="/proj",
        parent_session_id="parent-sid",
    )
    assert s.parent_session_id == "parent-sid"


def test_update_patches_and_refreshes_ping(tmp_registry):
    s = ops.register(agent_type="cursor", session_id="abc", directory="/proj")
    updated = ops.update(
        s.registry_id,
        status="reviewing",
        summary="Review PR 123",
        pr_title="Fix flaky test",
        pr_url="https://github.com/org/repo/pull/123",
        branch="tn/fix/flake",
        issue="https://github.com/org/repo/issues/99",
        goflow_timer_id="timer-1",
    )
    assert updated.status == "reviewing"
    assert updated.pr == {
        "title": "Fix flaky test",
        "url": "https://github.com/org/repo/pull/123",
    }
    assert updated.goflow_timer_id == "timer-1"
    assert updated.last_ping >= s.last_ping


def test_update_no_patches_raises(tmp_registry):
    s = ops.register(agent_type="cursor", session_id="abc", directory="/proj")
    with pytest.raises(ops.ValidationError):
        ops.update(s.registry_id)


def test_update_bad_id_raises(tmp_registry):
    with pytest.raises(ops.UnknownRegistryIdError):
        ops.update("nope", status="working")


def test_update_bad_status_raises(tmp_registry):
    s = ops.register(agent_type="cursor", session_id="abc", directory="/proj")
    with pytest.raises(ops.ValidationError):
        ops.update(s.registry_id, status="flying")


def test_update_clear_flags(tmp_registry):
    s = ops.register(agent_type="cursor", session_id="abc", directory="/proj")
    ops.update(
        s.registry_id, issue="x", branch="b", goflow_timer_id="t",
        pr_title="T", pr_url="http://u", summary="hi",
    )
    cleared = ops.update(
        s.registry_id,
        clear_issue=True, clear_branch=True, clear_goflow_timer=True,
        clear_pr=True, clear_summary=True,
    )
    assert cleared.issue is None and cleared.pr is None
    assert cleared.branch is None and cleared.goflow_timer_id is None
    assert cleared.summary == ""


def test_ping_refreshes_last_ping(tmp_registry):
    s = ops.register(agent_type="cursor", session_id="abc", directory="/proj")
    assert ops.ping(s.registry_id).last_ping >= s.last_ping


def test_ping_with_model(tmp_registry):
    s = ops.register(agent_type="cursor", session_id="abc", directory="/proj")
    assert s.model is None
    updated = ops.ping(s.registry_id, model="claude-opus-4")
    assert updated.model == "claude-opus-4"
    # omitting model leaves it alone
    again = ops.ping(s.registry_id)
    assert again.model == "claude-opus-4"


def test_update_model_and_clear(tmp_registry):
    s = ops.register(agent_type="cursor", session_id="abc", directory="/proj", model="gpt-5")
    assert s.model == "gpt-5"
    cleared = ops.update(s.registry_id, clear_model=True)
    assert cleared.model is None
    set_again = ops.update(s.registry_id, model=" sonnet-4 ")
    assert set_again.model == "sonnet-4"


def test_title_on_ping_and_update(tmp_registry):
    s = ops.register(agent_type="claude", session_id="abc", directory="/proj", title="boot")
    assert s.title == "boot"
    pinged = ops.ping(s.registry_id, title="renamed")
    assert pinged.title == "renamed"
    cleared = ops.update(s.registry_id, clear_title=True)
    assert cleared.title is None


def test_register_replace_preserves_ability_to_set_model(tmp_registry):
    ops.register(agent_type="cursor", session_id="abc", directory="/old")
    second = ops.register(
        agent_type="cursor", session_id="abc", directory="/new",
        model="composer-2", replace=True,
    )
    assert second.model == "composer-2"


def test_unregister_removes(tmp_registry):
    s = ops.register(agent_type="cursor", session_id="abc", directory="/proj")
    ops.unregister(s.registry_id)
    assert store.load().sessions == []


def test_unregister_bad_id(tmp_registry):
    with pytest.raises(ops.UnknownRegistryIdError):
        ops.unregister("missing")


def test_delete_removes_without_archive(tmp_registry):
    from agent_registry import archive

    s = ops.register(agent_type="cursor", session_id="del-1", directory="/proj")
    ops.delete(s.registry_id)
    assert store.load().sessions == []
    events, status = archive.read_events_result()
    assert status in ("ok", "missing")
    assert events == []


def test_delete_bad_id(tmp_registry):
    with pytest.raises(ops.UnknownRegistryIdError):
        ops.delete("missing")


def _backdate_last_ping(registry_id: str, seconds_ago: int) -> None:
    """Rewind a session's last_ping to simulate time passing between pings."""
    from datetime import datetime, timedelta, timezone
    past = (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()
    reg = store.load()
    for s in reg.sessions:
        if s.registry_id == registry_id:
            s.last_ping = past
    store.save(reg)


def test_register_initializes_active_seconds_zero(tmp_registry):
    s = ops.register(agent_type="cursor", session_id="abc", directory="/proj")
    assert s.active_seconds == 0.0


def test_ping_accumulates_active_within_gap(tmp_registry):
    s = ops.register(agent_type="cursor", session_id="abc", directory="/proj")
    _backdate_last_ping(s.registry_id, 120)  # 2 min < 5 min limit -> counted
    out = ops.ping(s.registry_id)
    assert 115 <= out.active_seconds <= 125


def test_ping_resume_gap_not_counted(tmp_registry):
    s = ops.register(agent_type="cursor", session_id="abc", directory="/proj")
    _backdate_last_ping(s.registry_id, 3600)  # 1h idle > limit -> resume, add 0
    out = ops.ping(s.registry_id)
    assert out.active_seconds == 0.0


def test_update_accumulates_active_within_gap(tmp_registry):
    s = ops.register(agent_type="cursor", session_id="abc", directory="/proj")
    _backdate_last_ping(s.registry_id, 90)  # 90s < limit -> counted
    out = ops.update(s.registry_id, status="working")
    assert 85 <= out.active_seconds <= 95
