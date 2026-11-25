import json

from agent_registry import topics


def _node(ev, kind):
    return {"id": ev["topic"]["id"], "title": ev["topic"]["title"], "kind": kind}


def _write(agent_type, session_id, *events):
    path = topics.log_path(agent_type, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")


def test_session_path_runs_from_the_intent_to_the_current_topic(tmp_registry):
    intent = topics.set_intent("claude", "s1", "Ship it")
    plan = topics.open_topic("claude", "s1", "Plan")
    assert topics.session_path("claude", "s1") == [_node(intent, "intent"), _node(plan, "topic")]


def test_session_path_ends_at_the_intent_when_no_topic_is_open(tmp_registry):
    intent = topics.set_intent("claude", "s1", "Ship it")
    assert topics.session_path("claude", "s1") == [_node(intent, "intent")]
    topics.open_topic("claude", "s1", "Plan")
    topics.close_topic("claude", "s1", "done")
    assert topics.session_path("claude", "s1") == [_node(intent, "intent")]


def test_a_session_without_an_intent_has_no_path(tmp_registry):
    assert topics.session_path("claude", "nobody") is None


def test_the_path_crosses_a_fork(tmp_registry):
    root = topics.set_intent("claude", "p", "Parent")
    main = topics.open_topic("claude", "p", "Main line")
    fork = topics.record_fork("claude", "p", "Side quest", mode="side", backend="none", brief_text="b")
    topics.adopt("claude", "c", fork["topic"]["id"])
    check = topics.open_topic("claude", "c", "Check it")
    assert topics.session_path("claude", "c") == [
        _node(root, "intent"), _node(main, "topic"), _node(fork, "intent"), _node(check, "topic"),
    ]


def test_path_from_a_topic_id(tmp_registry):
    intent = topics.set_intent("claude", "s1", "Ship it")
    plan = topics.open_topic("claude", "s1", "Plan")
    assert topics.path_from(plan["topic"]["id"]) == [_node(intent, "intent"), _node(plan, "topic")]
    assert topics.path_from("tp-zzzz") is None


def test_an_unadopted_fork_is_a_topic(tmp_registry):
    root = topics.set_intent("claude", "p", "Parent")
    fork = topics.record_fork("claude", "p", "Side quest", mode="side", backend="none", brief_text="b")
    assert topics.path_from(fork["topic"]["id"]) == [_node(root, "intent"), _node(fork, "topic")]


def test_a_missing_parent_ends_the_walk(tmp_registry):
    _write("claude", "s1", {"event": "topic", "topic": {"id": "tp-kid", "title": "Kid"}, "parent": "tp-gone"})
    assert topics.path_from("tp-kid") == [{"id": "tp-kid", "title": "Kid", "kind": "topic"}]


def test_a_cycle_ends_the_walk(tmp_registry):
    _write("claude", "a", {"event": "topic", "topic": {"id": "tp-a", "title": "A"}, "parent": "tp-b"})
    _write("claude", "b", {"event": "topic", "topic": {"id": "tp-b", "title": "B"}, "parent": "tp-a"})
    assert [n["id"] for n in topics.path_from("tp-a")] == ["tp-b", "tp-a"]
