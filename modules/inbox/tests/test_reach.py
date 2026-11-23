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
