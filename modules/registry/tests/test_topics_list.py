from agent_registry import ops, topics
from agent_registry.format import format_list


def test_list_split_adds_intent_and_topic(tmp_registry):
    ops.register(agent_type="claude", session_id="s1", directory="/proj")
    ops.register(agent_type="claude", session_id="s2", directory="/proj")
    intent = topics.set_intent("claude", "s1", "Ship it")
    opened = topics.open_topic("claude", "s1", "Plan")
    active, _stale = ops.list_split()
    by_sid = {v["session_id"]: v for v in active}
    assert by_sid["s1"]["intent"] == {"id": intent["topic"]["id"], "title": "Ship it"}
    assert by_sid["s1"]["topic"] == {"id": opened["topic"]["id"], "title": "Plan"}
    assert by_sid["s2"]["intent"] is None and by_sid["s2"]["topic"] is None


def test_live_views_add_intent(tmp_registry):
    ops.register(agent_type="codex", session_id="t1", directory="/proj")
    topics.set_intent("codex", "t1", "Ship it")
    views = ops.live_views()
    assert views["active"][0]["intent"]["title"] == "Ship it"


def test_list_text_shows_intent_and_topic():
    row = {
        "agent_type": "claude", "session_id": "s", "status": "idle",
        "intent": {"id": "tp-a", "title": "Ship"}, "topic": {"id": "tp-b", "title": "Plan"},
    }
    text = format_list([row], [])
    assert "intent:Ship" in text and "topic:Plan" in text
