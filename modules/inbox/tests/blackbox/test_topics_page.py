"""The Topics page against a temp registry: agt writes the logs, the web handler serves the page."""
import json
import re
import urllib.request
from datetime import datetime, timezone

from topic_tree_helpers import nesting

S1 = ["--type", "claude", "--session-id", "s1"]
S2 = ["--type", "claude", "--session-id", "s2"]
CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}


def page(base, path="/topics"):
    with urllib.request.urlopen(base + path, timeout=10) as resp:
        assert resp.status == 200
        return resp.read().decode()


def live_row(box, session_id, directory):
    """A registry row that pinged just now, in the registry's own file format."""
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "registry_id": f"r-{session_id}", "session_id": session_id, "agent_type": "claude", "directory": directory,
        "parent_session_id": None, "status": "working", "summary": "", "issue": None, "pr": None, "branch": None,
        "goflow_timer_id": None, "registered_at": now, "last_ping": now, "updated_at": now,
    }
    path = box.data / "registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "sessions": [row]}))


def test_the_topics_page_holds_each_piece_in_place(box, web):
    intent = box.agt_json("registry", "intent", "Ship the inbox", *S1)["topic"]["id"]
    plan = box.agt_json("registry", "topic", "Write the plan", *S1)["topic"]["id"]
    asked = box.agt("inbox", "ask", "--engine", "claude", "--session-id", "s1",
                    stdin=json.dumps({"title": "Which order?", "control": CHOICE}))
    assert asked.returncode == 0, asked.stderr
    entry = json.loads(asked.stdout)["entry"]
    box.agt_json("inbox", "answer", entry, "--value", "b", "--via", "chat")
    fork = box.agt_json("registry", "fork", "Side quest", "--side", "--backend", "none", *S1, stdin="# Side quest\n")["topic"]["id"]
    box.agt_json("registry", "intent", "--adopt", fork, *S2)
    check = box.agt_json("registry", "topic", "Check the windows", *S2)["topic"]["id"]
    later = box.agt_json("registry", "topic", "Later idea", *S1)["topic"]["id"]
    box.agt_json("registry", "topic", "--park", "--ref", "pk-1", *S1)
    live_row(box, "s2", str(box.root / "agent-tools"))

    html = page(web)
    tree = nesting(html)
    assert tree.parent == {intent: None, plan: intent, fork: plan, check: fork, later: intent}
    assert "Asked Which order?" in tree.text[plan] and "Answered b via the chat" in tree.text[plan]
    assert f"/e/{entry}" in tree.links[plan]
    assert "Forked Side quest" in tree.text[plan]
    assert "Parked pk-1" in tree.text[later]
    assert "Live" in tree.text[fork] and "Ended" in tree.text[intent]
    assert "claude --resume s1" in tree.text[intent] and "--resume s2" not in html
    assert not re.search(r"\d+ to answer", html)
    # The page read the logs through the registry's cache.
    assert (box.data / "topics" / ".parsed.json").exists()
