from agent_registry import topics


def test_tree_events_merge_every_log_oldest_first(tmp_registry):
    root = topics.set_intent("claude", "p", "Parent")["topic"]["id"]
    plan = topics.open_topic("claude", "p", "Plan")["topic"]["id"]
    topics.add_note("asked", plan, "ib-1", agent_type="claude", session_id="p", title="Which?")
    fork = topics.record_fork("claude", "p", "Side", mode="side", backend="none", brief_text="b")["topic"]["id"]
    topics.adopt("codex", "c", fork)
    topics.add_note("answered", plan, "ib-1", value="a", via="web")
    (node,) = topics.tree(events=True)
    assert node["id"] == root
    assert [(e["event"], e["session_id"]) for e in node["events"]] == [("intent", "p")]
    assert "topic" not in node["events"][0] and node["events"][0]["agent_type"] == "claude"
    (plan_node,) = node["children"]
    assert [(e["event"], e.get("entry")) for e in plan_node["events"]] == [
        ("topic", None), ("asked", "ib-1"), ("answered", "ib-1"),
    ]
    (fork_node,) = plan_node["children"]
    assert [(e["event"], e["agent_type"], e["session_id"]) for e in fork_node["events"]] == [
        ("forked", "claude", "p"), ("adopt", "codex", "c"),
    ]
    assert "events" not in topics.tree()[0]


def test_a_tree_from_cached_logs_matches_a_fresh_read(tmp_registry):
    topics.set_intent("claude", "p", "Parent")
    topics.open_topic("claude", "p", "Plan")
    topics.cached_logs()  # warm the cache, so the next call serves from it
    assert topics.tree(events=True, logs=topics.cached_logs()) == topics.tree(events=True)
    assert topics.tree(logs=topics.cached_logs()) == topics.tree()
