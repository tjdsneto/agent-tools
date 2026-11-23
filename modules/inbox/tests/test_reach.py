from agent_inbox.reach import classify


def test_live_resumable_and_missing():
    assert classify({"alive": True, "agent_type": "claude", "peer_name": "p"}, budget=None, last=None).status == "live"
    assert classify({"alive": False, "agent_type": "codex"}, budget=None, last=None).status == "resumable"
    assert classify(None, budget=None, last=None).status == "unreachable"


def test_claude_without_an_address_is_unreachable():
    view = {"alive": True, "agent_type": "claude", "peer_name": None}
    assert classify(view, budget=None, last=None).status == "unreachable"


def test_claude_budget_holds_with_reset():
    got = classify(
        {"alive": True, "agent_type": "claude", "peer_name": "p"},
        budget=(90, "2026-11-23T19:00:00-03:00"),
        last=None,
    )
    assert got.status == "held" and got.reachable_at == "2026-11-23T19:00:00-03:00"


def test_unreadable_budget_does_not_hold():
    view = {"alive": True, "agent_type": "claude", "peer_name": "p"}
    assert classify(view, budget=(None, None), last=None).status == "live"


def test_cursor_is_resumable_even_when_alive_flag_is_false():
    assert classify({"alive": False, "agent_type": "cursor"}, budget=None, last=None).status == "resumable"
    assert classify({"alive": False, "agent_type": "cursor"}, budget=None, last=None).headless is True


def test_previous_held_wake_holds_codex():
    got = classify({"alive": False, "agent_type": "codex"}, budget=None, last="held")
    assert got.status == "held" and got.reachable_at is None


def test_snapshot_parses_percent_and_reset():
    from datetime import datetime
    from agent_inbox.reach import parse_snapshot
    epoch = int(datetime(2026, 11, 23, 19, 5).timestamp())
    text = f"session_pct=91\nsession_reset={epoch}\nweek_pct=40\nweek_reset=\nweek_family=Fable\n"
    assert parse_snapshot(text) == (91, "2026-11-23T19:05:00")
    assert parse_snapshot("session_pct=\nsession_reset=\n") == (None, None)


def test_budget_is_read_once_per_ttl(monkeypatch):
    from agent_inbox import reach
    calls = []

    class Proc:
        stdout = "session_pct=10\nsession_reset=\n"

    monkeypatch.setattr(reach, "_budget_cache", None)
    monkeypatch.setattr(reach, "_run", lambda argv: calls.append(argv) or Proc())
    clock = [100.0]
    for _ in range(5):
        assert reach.claude_budget(now=lambda: clock[0]) == (10, None)
    assert calls == [["claude-budget", "snapshot"]]
    clock[0] += reach.BUDGET_TTL + 1
    reach.claude_budget(now=lambda: clock[0])
    assert len(calls) == 2
