import json
import threading
from pathlib import Path

WHO = ["--type", "claude", "--session-id", "s1"]


def test_history_in_order_with_statuses(box):
    intent = box.agt_json("registry", "intent", "Ship it", *WHO)
    plan = box.agt_json("registry", "topic", "Plan", *WHO)
    box.agt_json("registry", "topic", "--done", *WHO)
    side = box.agt_json("registry", "topic", "Side", *WHO)
    box.agt_json("registry", "topic", "--park", side["topic"]["id"], "--ref", "pk-7", *WHO)
    data = box.agt_json("registry", "topics", *WHO)
    assert [e["event"] for e in data["events"]] == ["intent", "topic", "done", "topic", "parked"]
    statuses = {t["id"]: t["status"] for t in data["topics"]}
    assert statuses == {intent["topic"]["id"]: "open", plan["topic"]["id"]: "done", side["topic"]["id"]: "parked"}
    assert box.log("claude", "s1")[-1]["ref"] == "pk-7"


def test_exit_codes(box):
    assert box.agt("registry", "topic", "Plan", *WHO).returncode == 1
    assert box.agt("registry", "intent", "A", *WHO).returncode == 0
    assert box.agt("registry", "intent", "B", *WHO).returncode == 4
    assert box.agt("registry", "topic", "--done", "tp-zzzz", *WHO).returncode == 2
    assert box.agt("registry", "intent", "--adopt", "tp-zzzz", "--type", "claude", "--session-id", "s2").returncode == 2


def test_identity_from_engine_env(box):
    env = dict(box.env, CLAUDE_CODE_SESSION_ID="env-1")
    assert box.agt("registry", "intent", "From env", env=env).returncode == 0
    assert box.log("claude", "env-1")[0]["topic"]["title"] == "From env"


def test_fork_then_adopt_builds_the_tree(box):
    root = box.agt_json("registry", "intent", "Parent", *WHO)
    fork = box.agt_json(
        "registry", "fork", "Side quest", "--side", "--backend", "none", *WHO,
        stdin="# Side quest\nDone when: decided.\n",
    )
    assert fork["launched"] is False
    assert Path(fork["brief"]).read_text() == "# Side quest\nDone when: decided.\n"
    assert f"agt registry intent --adopt {fork['topic']['id']}" in fork["prompt"]
    adopted = box.agt_json("registry", "intent", "--adopt", fork["topic"]["id"], "--type", "claude", "--session-id", "s2")
    assert adopted["from_session"] == "s1"

    tree = box.agt_json("registry", "topics", "--tree")["tree"]
    assert [n["id"] for n in tree] == [root["topic"]["id"]]
    child = tree[0]["children"][0]
    assert child["id"] == fork["topic"]["id"]
    assert {(s["session_id"], s["role"]) for s in child["sessions"]} == {("s1", "forked"), ("s2", "intent")}

    open_rows = box.agt_json("registry", "topics", "--open")["topics"]
    assert {(r["session_id"], r["title"]) for r in open_rows} == {("s1", "Parent"), ("s2", "Side quest")}


def test_fork_without_brief_is_usage(box):
    box.agt_json("registry", "intent", "Parent", *WHO)
    r = box.agt("registry", "fork", "Side", "--side", "--backend", "none", *WHO, stdin="")
    assert r.returncode == 1
    assert [e["event"] for e in box.log("claude", "s1")] == ["intent"]


def test_concurrent_writers_lose_nothing(box):
    box.agt_json("registry", "intent", "Busy", *WHO)

    failures = []

    def writer(n):
        for i in range(10):
            proc = box.agt("registry", "topic", f"w{n}-{i}", *WHO)
            if proc.returncode != 0:
                failures.append(proc.stderr)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert failures == []
    raw = (box.data / "topics" / "claude" / "s1.jsonl").read_text().splitlines()
    events = [json.loads(line) for line in raw]          # every line is whole JSON
    opened = [e for e in events if e["event"] == "topic"]
    assert len(opened) == 30
    assert len({e["topic"]["id"] for e in opened}) == 30  # no id minted twice


def test_list_shows_intent_and_topic(box):
    reg = box.agt_json("registry", "register", "--type", "claude", "--session-id", "s1", "--directory", str(box.root))
    box.agt_json("registry", "intent", "Ship it", *WHO)
    box.agt_json("registry", "topic", "Plan", *WHO)
    rows = box.agt_json("registry", "list", "--json")["active"]
    row = next(r for r in rows if r["session_id"] == "s1")
    assert row["intent"]["title"] == "Ship it" and row["topic"]["title"] == "Plan"
    text = box.agt("registry", "list").stdout
    assert "intent:Ship it" in text and "topic:Plan" in text
    assert reg["registry_id"]


def test_unregister_and_prune_keep_the_log(box):
    reg = box.agt_json("registry", "register", "--type", "claude", "--session-id", "s1", "--directory", str(box.root))
    box.agt_json("registry", "intent", "Ship it", *WHO)
    assert box.agt("registry", "unregister", reg["registry_id"]).returncode == 0
    assert box.agt("registry", "prune", "--yes").returncode == 0
    assert box.log("claude", "s1")[0]["topic"]["title"] == "Ship it"
