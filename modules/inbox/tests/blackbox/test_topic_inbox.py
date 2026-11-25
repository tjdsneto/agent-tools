import json

WHO = ["--type", "claude", "--session-id", "s1"]
ASKER = ["--engine", "claude", "--session-id", "s1"]
CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}


def ask(box, *args, topic=None, env=None):
    body = {"title": "Which order?", "control": CHOICE}
    if topic:
        body["topic"] = topic
    return box.agt("inbox", "ask", *args, stdin=json.dumps(body), env=env)


def asked(box, *args, **kw):
    proc = ask(box, *args, **kw)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["entry"]


def test_a_session_ask_carries_its_path_and_the_log_records_it(box):
    intent = box.agt_json("registry", "intent", "Ship the inbox", *WHO)
    plan = box.agt_json("registry", "topic", "Write the plan", *WHO)
    entry = asked(box, *ASKER)
    got = box.agt_json("inbox", "get", entry)
    assert got["topic_path"] == [
        {"id": intent["topic"]["id"], "title": "Ship the inbox", "kind": "intent"},
        {"id": plan["topic"]["id"], "title": "Write the plan", "kind": "topic"},
    ]
    assert [(n["event"], n["entry"], n["topic"]["id"], n["title"]) for n in box.notes("claude", "s1")] == [
        ("asked", entry, plan["topic"]["id"], "Which order?"),
    ]


def test_a_chat_answer_is_logged_and_done_finds_nothing_open(box):
    box.agt_json("registry", "intent", "Ship the inbox", *WHO)
    box.agt_json("registry", "topic", "Write the plan", *WHO)
    entry = asked(box, *ASKER)
    box.agt_json("inbox", "answer", entry, "--value", "b", "--via", "chat")
    last = box.notes("claude", "s1")[-1]
    assert (last["event"], last["entry"], last["value"], last["via"]) == ("answered", entry, "b", "chat")
    assert box.agt_json("registry", "topic", "--done", *WHO)["open_questions"] == []


def test_done_reports_a_question_still_waiting_but_not_a_withdrawn_one(box):
    box.agt_json("registry", "intent", "Ship the inbox", *WHO)
    box.agt_json("registry", "topic", "Write the plan", *WHO)
    waiting = asked(box, *ASKER)
    gone = asked(box, *ASKER)
    box.agt_json("inbox", "withdraw", gone)
    last = box.notes("claude", "s1")[-1]
    assert (last["event"], last["entry"], last["state"]) == ("closed", gone, "withdrawn")
    assert box.agt_json("registry", "topic", "--done", *WHO)["open_questions"] == [waiting]


def test_a_script_ask_names_a_forked_topic(box):
    box.agt_json("registry", "intent", "Parent", *WHO)
    fork = box.agt_json("registry", "fork", "Side quest", "--side", "--backend", "none", *WHO, stdin="# Side quest\n")
    box.agt_json("registry", "intent", "--adopt", fork["topic"]["id"], "--type", "claude", "--session-id", "s2")
    entry = asked(box, "--script", "autopilot", topic=fork["topic"]["id"])
    got = box.agt_json("inbox", "get", entry)
    assert [(n["title"], n["kind"]) for n in got["topic_path"]] == [("Parent", "intent"), ("Side quest", "intent")]
    # No session asked, so the note goes to the session that minted the topic: the parent, which forked it.
    assert [n["entry"] for n in box.notes("claude", "s1")] == [entry]
    assert box.notes("claude", "s2") == []


def test_a_script_ask_with_an_unknown_topic_is_refused(box):
    proc = ask(box, "--script", "autopilot", topic="tp-zzzz")
    assert proc.returncode == 1 and "unknown topic tp-zzzz" in proc.stderr
    assert box.agt_json("inbox", "list", "--json") == []


def test_an_ask_succeeds_without_the_registry(box):
    box.agt_json("registry", "intent", "Ship the inbox", *WHO)
    env = dict(box.env, AGENT_INBOX_AGT=str(box.root / "no-such-agt"))
    proc = ask(box, *ASKER, env=env)
    assert proc.returncode == 0, proc.stderr
    assert "continuing without the topic link" in proc.stderr
    assert box.agt_json("inbox", "get", json.loads(proc.stdout)["entry"])["topic_path"] is None


def test_a_post_is_logged_as_posted(box):
    box.agt_json("registry", "intent", "Ship the inbox", *WHO)
    proc = box.agt("inbox", "post", *ASKER, stdin=json.dumps({"title": "Plan written"}))
    assert proc.returncode == 0, proc.stderr
    last = box.notes("claude", "s1")[-1]
    assert (last["event"], last["title"]) == ("posted", "Plan written")
