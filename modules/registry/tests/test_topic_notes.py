import json

import pytest

from agent_registry import topics


def _write(agent_type, session_id, *events):
    path = topics.log_path(agent_type, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")


def _notes(agent_type, session_id):
    return [e for e in topics.read_events(agent_type, session_id) if e["event"] in topics.NOTE_KINDS]


def test_a_note_goes_to_the_asking_session_when_it_holds_the_topic(tmp_registry):
    topics.set_intent("claude", "s1", "Ship it")
    plan = topics.open_topic("claude", "s1", "Plan")["topic"]["id"]
    ev = topics.add_note("asked", plan, "ib-1", agent_type="claude", session_id="s1", title="Which order?")
    assert ev == {
        "event": "asked", "at": ev["at"], "topic": {"id": plan, "title": "Plan"}, "entry": "ib-1", "title": "Which order?",
    }
    assert _notes("claude", "s1") == [ev]


def test_a_note_falls_back_to_the_topic_owner(tmp_registry):
    root = topics.set_intent("claude", "p", "Parent")["topic"]["id"]
    topics.add_note("posted", root, "ib-2", title="Backup done")  # a script asker: no session
    topics.add_note("asked", root, "ib-3", agent_type="codex", session_id="other", title="Q")  # doesn't hold it
    assert [n["entry"] for n in _notes("claude", "p")] == ["ib-2", "ib-3"]
    assert topics.read_events("codex", "other") == []


def test_an_adopted_topic_note_goes_to_the_adopter(tmp_registry):
    topics.set_intent("claude", "p", "Parent")
    fork = topics.record_fork("claude", "p", "Side", mode="side", backend="none", brief_text="b")["topic"]["id"]
    topics.adopt("claude", "c", fork)
    topics.add_note("asked", fork, "ib-4", agent_type="claude", session_id="c", title="Q")
    assert [n["entry"] for n in _notes("claude", "c")] == ["ib-4"]
    assert _notes("claude", "p") == []


def test_note_kinds_and_their_fields(tmp_registry):
    tid = topics.set_intent("claude", "s1", "Ship it")["topic"]["id"]
    answered = topics.add_note("answered", tid, "ib-1", value="x" * 300, via="web")
    assert answered["value"] == "x" * 200 and answered["via"] == "web"
    closed = topics.add_note("closed", tid, "ib-2", closed_as="withdrawn")
    assert closed["state"] == "withdrawn"
    bad = [
        ("asked", {}),
        ("answered", {"value": "a", "via": "pigeon"}),
        ("answered", {"via": "web"}),
        ("closed", {"closed_as": "open"}),
        ("shrugged", {}),
    ]
    for kind, kw in bad:
        with pytest.raises(topics.TopicUsageError):
            topics.add_note(kind, tid, "ib-9", **kw)
    with pytest.raises(topics.TopicUsageError):
        topics.add_note("asked", tid, "  ", title="t")
    with pytest.raises(topics.TopicNotFoundError):
        topics.add_note("asked", "tp-zzzz", "ib-9", title="t")


def test_replay_ignores_notes_for_status(tmp_registry):
    topics.set_intent("claude", "s1", "Ship it")
    plan = topics.open_topic("claude", "s1", "Plan")["topic"]["id"]
    topics.close_topic("claude", "s1", "done")
    before = {t["id"]: (t["status"], t["at"]) for t in topics.state("claude", "s1")["topics"]}
    topics.add_note("answered", plan, "ib-1", agent_type="claude", session_id="s1", value="a", via="chat")
    st = topics.state("claude", "s1")
    assert {t["id"]: (t["status"], t["at"]) for t in st["topics"]} == before
    assert st["topic"] is None
    held = next(t for t in st["topics"] if t["id"] == plan)
    assert [(n["event"], n["entry"]) for n in held["notes"]] == [("answered", "ib-1")]


def test_a_note_never_creates_a_topic(tmp_registry):
    _write("claude", "s1", {"event": "asked", "topic": {"id": "tp-else", "title": "x"}, "entry": "ib-1", "title": "Q"})
    assert topics.state("claude", "s1")["topics"] == []
    assert topics.open_topics() == [] and topics.tree() == []


def test_a_late_note_does_not_re_date_a_forked_topic_in_the_tree(tmp_registry):
    topics.set_intent("claude", "p", "Parent")
    fork = topics.record_fork("claude", "p", "Side", mode="side", backend="none", brief_text="b")["topic"]["id"]
    topics.adopt("claude", "c", fork)
    topics.add_note("asked", fork, "ib-5", title="Script Q")  # owner is p, which logged the fork
    child = topics.tree()[0]["children"][0]
    assert child["status"] == "open"
    assert [n["entry"] for n in child["notes"]] == ["ib-5"]


def test_open_questions_are_asks_with_no_answer_or_close(tmp_registry):
    tid = topics.set_intent("claude", "s1", "Ship it")["topic"]["id"]
    for entry in ("ib-1", "ib-2", "ib-3"):
        topics.add_note("asked", tid, entry, title="Q")
    topics.add_note("posted", tid, "ib-4", title="R")
    topics.add_note("answered", tid, "ib-1", value="a", via="web")
    topics.add_note("closed", tid, "ib-3", closed_as="withdrawn")
    assert topics.open_questions(tid) == ["ib-2"]
    assert topics.open_questions("tp-zzzz") == []


def test_a_note_without_an_entry_is_skipped(tmp_registry):
    _write(
        "claude", "s1",
        {"event": "intent", "topic": {"id": "tp-root", "title": "R"}},
        {"event": "asked", "topic": {"id": "tp-root", "title": "R"}, "entry": 5, "title": "Q"},
    )
    assert [e["event"] for e in topics.read_events("claude", "s1")] == ["intent"]
    assert topics.open_questions("tp-root") == []
