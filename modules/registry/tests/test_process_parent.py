from agent_registry.process_parent import ancestor_pids, match_parent


def test_ancestor_pids_stop_at_launchd_and_cycles():
    parents = {10: 9, 9: 4, 4: 1}

    def ppid(pid):
        return parents.get(pid)

    assert ancestor_pids(10, ppid) == [9, 4]


def test_match_parent_picks_the_nearest_other_session():
    rows = [
        {"session_id": "self", "pid": 50},
        {"session_id": "spawner", "pid": 40},
        {"session_id": "older", "pid": 10},
    ]
    assert match_parent([50, 40, 10], rows, "self", own_pid=50) == "spawner"


def test_match_parent_ignores_this_session_and_a_missing_chain():
    rows = [{"session_id": "self", "pid": 50}]
    assert match_parent([50, 3], rows, "self", own_pid=50) is None
    assert match_parent([], rows, "other") is None
