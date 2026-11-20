from datetime import datetime, timezone
from agent_registry.models import (
    Session,
    accumulate_active_seconds,
    is_stale,
    public_view,
    now_iso,
)

def _sess(**kw):
    base = dict(
        registry_id="rid-1", session_id="sid-1", agent_type="cursor",
        directory="/tmp/x", parent_session_id=None, status="idle", summary="",
        issue=None, pr=None, branch=None, goflow_timer_id=None,
        registered_at="2026-09-24T12:00:00+00:00",
        last_ping="2026-09-24T12:00:00+00:00",
        updated_at="2026-09-24T12:00:00+00:00",
    )
    base.update(kw)
    return Session(**base)

def test_not_stale_within_60m():
    now = datetime(2026, 9, 24, 12, 30, tzinfo=timezone.utc)
    assert is_stale(_sess(), now=now) is False

def test_stale_after_60m():
    now = datetime(2026, 9, 24, 13, 1, tzinfo=timezone.utc)
    assert is_stale(_sess(), now=now) is True

def test_public_view_hides_registry_id():
    view = public_view(_sess())
    assert "registry_id" not in view
    assert view["session_id"] == "sid-1"

def test_from_dict_missing_model_defaults_none():
    s = Session.from_dict({
        "registry_id": "r", "session_id": "s", "agent_type": "cursor",
        "directory": "/p", "status": "idle",
        "registered_at": "2026-09-24T12:00:00+00:00",
        "last_ping": "2026-09-24T12:00:00+00:00",
        "updated_at": "2026-09-24T12:00:00+00:00",
    })
    assert s.model is None

def test_now_iso_has_timezone():
    s = now_iso()
    assert "+" in s or s.endswith("Z")

def test_accumulate_adds_gap_within_limit():
    # ping 2 minutes after the previous one, gap under the limit -> counted
    out = accumulate_active_seconds(
        "2026-09-24T12:00:00+00:00", "2026-09-24T12:02:00+00:00", 100.0, gap_limit=300
    )
    assert out == 220.0

def test_accumulate_counts_gap_equal_to_limit():
    # boundary: a gap exactly at the limit is still a continuation
    out = accumulate_active_seconds(
        "2026-09-24T12:00:00+00:00", "2026-09-24T12:05:00+00:00", 100.0, gap_limit=300
    )
    assert out == 400.0

def test_accumulate_drops_gap_over_limit_as_resume():
    # 10-minute idle gap past the limit -> resume, nothing added
    out = accumulate_active_seconds(
        "2026-09-24T12:00:00+00:00", "2026-09-24T12:10:00+00:00", 100.0, gap_limit=300
    )
    assert out == 100.0

def test_accumulate_ignores_non_positive_gap():
    # clock skew / identical timestamps add nothing
    out = accumulate_active_seconds(
        "2026-09-24T12:00:00+00:00", "2026-09-24T12:00:00+00:00", 100.0, gap_limit=300
    )
    assert out == 100.0

def test_from_dict_missing_active_seconds_defaults_zero():
    s = Session.from_dict({
        "registry_id": "r", "session_id": "s", "agent_type": "cursor",
        "directory": "/p", "status": "idle",
        "registered_at": "2026-09-24T12:00:00+00:00",
        "last_ping": "2026-09-24T12:00:00+00:00",
        "updated_at": "2026-09-24T12:00:00+00:00",
    })
    assert s.active_seconds == 0.0

def test_from_dict_reads_active_seconds():
    s = Session.from_dict({
        "registry_id": "r", "session_id": "s", "agent_type": "cursor",
        "directory": "/p", "status": "idle",
        "registered_at": "2026-09-24T12:00:00+00:00",
        "last_ping": "2026-09-24T12:00:00+00:00",
        "updated_at": "2026-09-24T12:00:00+00:00",
        "active_seconds": 42.5,
    })
    assert s.active_seconds == 42.5

def test_from_dict_address_defaults_none():
    s = Session.from_dict({
        "registry_id": "r", "session_id": "s", "agent_type": "claude",
        "directory": "/p", "status": "idle",
        "registered_at": "2026-09-24T12:00:00+00:00",
        "last_ping": "2026-09-24T12:00:00+00:00",
        "updated_at": "2026-09-24T12:00:00+00:00",
    })
    assert s.peer_name is None
    assert s.socket is None
    assert s.pid is None
    assert s.peer_status is None

def test_from_dict_reads_address():
    s = Session.from_dict({
        "registry_id": "r", "session_id": "s", "agent_type": "claude",
        "directory": "/p", "status": "working",
        "registered_at": "2026-09-24T12:00:00+00:00",
        "last_ping": "2026-09-24T12:00:00+00:00",
        "updated_at": "2026-09-24T12:00:00+00:00",
        "peer_name": "waker-t2-target",
        "socket": "/tmp/cc-socks/1.sock",
        "pid": "4529",
        "peer_status": "idle",
    })
    assert s.peer_name == "waker-t2-target"
    assert s.socket == "/tmp/cc-socks/1.sock"
    assert s.pid == 4529
    assert s.peer_status == "idle"
    assert s.status == "working"
