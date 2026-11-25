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
