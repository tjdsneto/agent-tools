from agent_registry.format import format_list


def _view(**kw):
    base = dict(
        agent_type="claude", session_id="sid-1", status="working",
        directory="/proj", active_seconds=0.0,
    )
    base.update(kw)
    return base


def test_active_duration_shown_in_minutes():
    out = format_list([_view(active_seconds=125.0)], [])
    assert "active:2m" in out


def test_active_duration_shown_in_hours_and_minutes():
    out = format_list([_view(active_seconds=3900.0)], [])  # 1h05m
    assert "active:1h05m" in out


def test_active_duration_hidden_when_under_a_minute():
    out = format_list([_view(active_seconds=30.0)], [])
    assert "active:" not in out
