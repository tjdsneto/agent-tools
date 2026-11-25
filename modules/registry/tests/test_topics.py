import json

import pytest

from agent_registry import topics


def test_intent_then_topic_then_done(tmp_registry):
    intent = topics.set_intent("claude", "s1", "Ship topic awareness")
    assert intent["event"] == "intent"
    assert intent["topic"]["id"].startswith("tp-")
    assert len(intent["topic"]["id"]) == 7
    opened = topics.open_topic("claude", "s1", "Write the plan")
    assert opened["parent"] == intent["topic"]["id"]
    st = topics.state("claude", "s1")
    assert st["intent"] == {"id": intent["topic"]["id"], "title": "Ship topic awareness"}
    assert st["topic"]["id"] == opened["topic"]["id"]
    topics.close_topic("claude", "s1", "done")
    st = topics.state("claude", "s1")
    assert st["topic"] is None
    assert [t["status"] for t in st["topics"]] == ["open", "done"]


def test_second_intent_conflicts(tmp_registry):
    topics.set_intent("claude", "s1", "A")
    with pytest.raises(topics.TopicConflictError):
        topics.set_intent("claude", "s1", "B")


def test_topic_needs_intent(tmp_registry):
    with pytest.raises(topics.NoIntentError):
        topics.open_topic("claude", "s1", "x")


def test_blank_title_is_usage_error(tmp_registry):
    with pytest.raises(topics.TopicUsageError):
        topics.set_intent("claude", "s1", "   ")


def test_close_unknown_topic(tmp_registry):
    topics.set_intent("claude", "s1", "A")
    with pytest.raises(topics.TopicNotFoundError):
        topics.close_topic("claude", "s1", "done", "tp-zzzz")
    with pytest.raises(topics.TopicNotFoundError):
        topics.close_topic("claude", "s1", "done")


def test_park_records_ref(tmp_registry):
    topics.set_intent("claude", "s1", "A")
    side = topics.open_topic("claude", "s1", "side")
    ev = topics.close_topic("claude", "s1", "parked", side["topic"]["id"], ref="pk-12")
    assert ev["ref"] == "pk-12"
    assert topics.state("claude", "s1")["topics"][1]["status"] == "parked"


def test_log_lives_beside_registry(tmp_registry):
    topics.set_intent("claude", "s1", "A")
    path = tmp_registry.parent / "topics" / "claude" / "s1.jsonl"
    assert json.loads(path.read_text().splitlines()[0])["event"] == "intent"


def test_torn_line_is_skipped(tmp_registry):
    topics.set_intent("claude", "s1", "A")
    with open(topics.log_path("claude", "s1"), "a") as f:
        f.write('{"event": "topic", "topi\n')
    assert topics.state("claude", "s1")["intent"]["title"] == "A"


def test_adopt_binds_existing_topic(tmp_registry):
    root = topics.set_intent("claude", "parent", "A")
    ev = topics.adopt("claude", "child", root["topic"]["id"])
    assert ev["from_session"] == "parent"
    assert topics.state("claude", "child")["intent"]["id"] == root["topic"]["id"]
    with pytest.raises(topics.TopicConflictError):
        topics.adopt("claude", "child", root["topic"]["id"])


def test_adopt_unknown(tmp_registry):
    with pytest.raises(topics.TopicNotFoundError):
        topics.adopt("claude", "child", "tp-zzzz")


def test_mint_skips_taken_ids(tmp_registry, monkeypatch):
    picks = iter("aaaa" + "aaaa" + "bbbb")
    monkeypatch.setattr(topics.secrets, "choice", lambda _alphabet: next(picks))
    assert topics.set_intent("claude", "s1", "A")["topic"]["id"] == "tp-aaaa"
    assert topics.set_intent("claude", "s2", "B")["topic"]["id"] == "tp-bbbb"


from pathlib import Path


def test_record_fork_writes_brief_and_event(tmp_registry):
    topics.set_intent("claude", "p", "A")
    main = topics.open_topic("claude", "p", "main")
    ev = topics.record_fork("claude", "p", "Side", mode="new_intent", backend="none", brief_text="# Brief\n")
    assert ev["event"] == "forked"
    assert ev["parent"] == main["topic"]["id"]
    assert ev["mode"] == "new_intent"
    assert ev["backend"] == "none"
    assert Path(ev["brief"]).read_text() == "# Brief\n"
    assert Path(ev["brief"]).parent == tmp_registry.parent / "briefs"
    # Forking a side thread does not close the topic the session is on.
    assert topics.state("claude", "p")["topic"]["id"] == main["topic"]["id"]


def test_record_fork_parent_is_intent_without_topic(tmp_registry):
    intent = topics.set_intent("claude", "p", "A")
    ev = topics.record_fork("claude", "p", "Side", mode="side", backend="none", brief_text="b")
    assert ev["parent"] == intent["topic"]["id"]


def test_record_fork_rules(tmp_registry):
    with pytest.raises(topics.NoIntentError):
        topics.record_fork("claude", "p", "x", mode="side", backend="none", brief_text="b")
    topics.set_intent("claude", "p", "A")
    with pytest.raises(topics.TopicUsageError):
        topics.record_fork("claude", "p", "x", mode="side", backend="none", brief_text="   ")
    with pytest.raises(topics.TopicUsageError):
        topics.record_fork("claude", "p", "x", mode="sideways", backend="none", brief_text="b")


def test_tree_links_forked_child(tmp_registry):
    root = topics.set_intent("claude", "p", "Parent intent")
    fork = topics.record_fork("claude", "p", "Side quest", mode="side", backend="none", brief_text="b")
    topics.adopt("claude", "c", fork["topic"]["id"])
    tree = topics.tree()
    assert [n["id"] for n in tree] == [root["topic"]["id"]]
    child = tree[0]["children"][0]
    assert child["id"] == fork["topic"]["id"]
    assert child["status"] == "open"
    assert {(s["session_id"], s["role"]) for s in child["sessions"]} == {("p", "forked"), ("c", "intent")}


def test_open_topics_across_sessions(tmp_registry):
    topics.set_intent("claude", "a", "A")
    topics.open_topic("claude", "a", "a1")
    topics.close_topic("claude", "a", "done")
    topics.set_intent("codex", "b", "B")
    rows = topics.open_topics()
    assert {(r["agent_type"], r["session_id"], r["title"]) for r in rows} == {
        ("claude", "a", "A"), ("codex", "b", "B"),
    }


def test_current_and_context_line(tmp_registry):
    assert topics.current("claude", "s") == {"intent": None, "topic": None}
    assert topics.context_line("claude", "s").startswith("No intent set for this session.")
    intent = topics.set_intent("claude", "s", "Ship it")
    opened = topics.open_topic("claude", "s", "Plan")
    line = topics.context_line("claude", "s")
    assert line == (
        f"Intent: Ship it ({intent['topic']['id']}) · Topic: Plan ({opened['topic']['id']}). "
        "If this prompt changes the subject, run the topic-awareness drift check."
    )
    topics.close_topic("claude", "s", "done")
    assert "· Topic: none." in topics.context_line("claude", "s")


def test_current_survives_unreadable_log(tmp_registry):
    topics.set_intent("claude", "s", "A")
    path = topics.log_path("claude", "s")
    path.chmod(0)
    try:
        assert topics.current("claude", "s") == {"intent": None, "topic": None}
    finally:
        path.chmod(0o600)


def test_session_type(tmp_registry):
    topics.set_intent("codex", "b", "B")
    assert topics.session_type("b") == "codex"
    assert topics.session_type("nope") is None


def test_append_after_torn_tail_keeps_next_event(tmp_registry):
    topics.set_intent("claude", "t", "A")
    with open(topics.log_path("claude", "t"), "a", encoding="utf-8") as f:
        f.write('{"event": "topic", "at": "2026-')  # crash mid-write, no newline
    opened = topics.open_topic("claude", "t", "After the crash")
    assert topics.state("claude", "t")["topic"]["id"] == opened["topic"]["id"]


def _write_garbage_log(agent_type, session_id):
    path = topics.log_path(agent_type, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    good = {"event": "intent", "topic": {"id": "tp-good", "title": "Valid"}}
    lines = [
        json.dumps({"event": "topic", "topic": {"id": ["x"], "title": "a"}}).encode(),
        json.dumps({"event": "topic", "topic": {"id": {"k": 1}, "title": "a"}}).encode(),
        json.dumps({"event": "topic", "topic": {"id": "tp-bad", "title": ["no"]}}).encode(),
        b'{"event": "topic", "topic": {"id": "tp-\xff\xfe", "title": "x"}}',
        json.dumps(good).encode(),
    ]
    path.write_bytes(b"\n".join(lines) + b"\n")


def test_bad_events_are_skipped(tmp_registry):
    _write_garbage_log("claude", "s1")
    assert topics.state("claude", "s1")["intent"] == {"id": "tp-good", "title": "Valid"}
    topics.current("claude", "s1")


def test_list_survives_garbage_log(tmp_registry):
    from agent_registry import ops
    ops.register(agent_type="claude", session_id="s1", directory="/proj")
    _write_garbage_log("claude", "s1")
    active, _ = ops.list_split()
    assert active[0]["intent"] == {"id": "tp-good", "title": "Valid"}


def test_unreadable_topics_dir_gives_no_reminder(tmp_registry):
    topics.set_intent("claude", "s1", "Ship it")
    root = topics.topics_dir()
    root.chmod(0)
    try:
        assert topics.current("claude", "s1") == {"intent": None, "topic": None}
        with pytest.raises(OSError):
            topics.context_line("claude", "s1")
    finally:
        root.chmod(0o700)
