import os
import threading
from http.client import HTTPConnection

import pytest
from topic_tree_helpers import ev, nesting, node, sess

from agent_inbox import store
from agent_inbox.validate import validate_request
from agent_inbox.web import make_server

CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}
EVIL = '<img src=x onerror="alert(1)">'
os.environ["INBOX_ALLOW_INSECURE"] = "1"


@pytest.fixture
def http(conn):
    server = make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address
    server.shutdown()
    server.server_close()


def get(http, path, headers=None):
    c = HTTPConnection(http[0], http[1], timeout=5)
    c.request("GET", path, headers=headers or {})
    resp = c.getresponse()
    return resp.status, resp.getheader("Set-Cookie"), resp.read().decode()


def serve(fake_registry, *roots):
    fake_registry.replies["topics"] = {"tree": list(roots)}


def ask(conn, title):
    req = validate_request({"title": title, "control": CHOICE}, "ask")
    return store.create_entry(conn, "ask", req, engine="claude", session_id="s-1")


def test_the_topics_tab_follows_history(conn, http, fake_registry):
    serve(fake_registry)
    _, _, feed = get(http, "/")
    assert '<a href="/?history=1">History</a><a href="/topics">Topics</a></nav>' in feed
    status, _, page = get(http, "/topics")
    assert status == 200 and '<a href="/topics" aria-current="page">Topics</a>' in page
    assert fake_registry.calls == [["topics", "--tree", "--events"]]
    assert "No topics yet" in page


def test_the_tree_nests_intents_topics_and_forks(conn, http, fake_registry):
    q = ask(conn, "Which order?")
    check = node("tp-c", "Check windows", sessions=[sess("s-2", role="topic")], events=[ev("topic", 40, session_id="s-2")])
    fork = node("tp-f", "Side quest", sessions=[sess("s-1", role="forked"), sess("s-2", state="live")],
                events=[ev("forked", 50), ev("adopt", 45, session_id="s-2")], children=[check])
    plan = node("tp-p", "Write the plan", sessions=[sess("s-1", role="topic")], children=[fork], events=[
        ev("topic", 90), ev("asked", 80, entry=q["id"], title="Which order?"),
        ev("posted", 70, entry="ib-post", title="Plan written"),
    ])
    later = node("tp-k", "Later idea", status="parked", sessions=[sess("s-1", role="topic")],
                 events=[ev("topic", 30), ev("parked", 20, ref="pk-1")])
    serve(fake_registry, node("tp-r", "Ship the inbox", sessions=[sess("s-1", state="idle")],
                              events=[ev("intent", 100)], children=[plan, later]))
    status, _, page = get(http, "/topics")
    assert status == 200
    tree = nesting(page)
    assert tree.parent == {"tp-r": None, "tp-p": "tp-r", "tp-f": "tp-p", "tp-c": "tp-f", "tp-k": "tp-r"}
    assert f'/e/{q["id"]}' in tree.links["tp-p"] and "/e/ib-post" in tree.links["tp-p"]
    assert "Asked Which order?" in tree.text["tp-p"] and "Forked Side quest" in tree.text["tp-p"]
    assert "agent-tools · claude · 2 open topics · 1 question waiting · 1 parked" in tree.text["tp-r"]
    assert "Idle" in tree.text["tp-r"] and "Live" in tree.text["tp-f"]
    assert "Parked pk-1" in tree.text["tp-k"]
    # The intent and the topic with a question waiting start open; the parked topic starts closed.
    assert '<li class="node intent" data-topic="tp-r" data-depth="0" id="tp-r"><details open>' in page
    assert '<li class="node topic" data-topic="tp-p" data-depth="1" id="tp-p"><details open>' in page
    assert '<li class="node topic" data-topic="tp-k" data-depth="1" id="tp-k"><details>' in page
    assert '<span class="chip blue">1 to answer</span>' in page


def test_intents_needing_you_come_first_and_finished_ones_wait_behind_a_button(conn, http, fake_registry):
    done = node("tp-done", "Done one", sessions=[sess("a")], events=[ev("intent", 5)], children=[
        node("tp-d1", "Finished", status="done", sessions=[sess("a", role="topic")], events=[ev("topic", 4), ev("done", 3)]),
    ])
    busy = node("tp-busy", "Busy", sessions=[sess("b")], events=[ev("intent", 10)], children=[
        node("tp-b1", "Going", sessions=[sess("b", role="topic")], events=[ev("topic", 9)]),
    ])
    stray = node("tp-stray", "Stray", sessions=[sess("c")], events=[ev("intent", 300)], children=[
        node("tp-f", "Never started", status="forked", sessions=[sess("c", role="forked")], events=[ev("forked", 299)]),
    ])
    serve(fake_registry, done, busy, stray)
    _, cookie, page = get(http, "/topics")
    assert cookie is None
    assert page.index('data-topic="tp-stray"') < page.index('data-topic="tp-busy"')
    assert 'data-topic="tp-done"' not in page
    assert '<a class="btn" href="/topics?finished=1">Show finished (1)</a>' in page
    assert "1 fork not picked up" in page and '<span class="chip amber"><i></i>Not picked up</span>' in page


def test_show_finished_is_remembered_in_a_cookie(conn, http, fake_registry):
    serve(fake_registry, node("tp-done", "Done one", sessions=[sess("a")], events=[ev("intent", 5)]))
    _, cookie, page = get(http, "/topics?finished=1")
    assert cookie.startswith("ib_finished=1;") and "SameSite=Lax" in cookie
    assert '<li class="node intent" data-topic="tp-done" data-depth="0" id="tp-done"><details>' in page
    assert '<a class="btn" href="/topics?finished=0">Hide finished</a>' in page
    _, cookie, remembered = get(http, "/topics", headers={"Cookie": 'a={"x":1}; ib_finished=1'})
    assert cookie is None and 'data-topic="tp-done"' in remembered
    _, cookie, hidden = get(http, "/topics?finished=0", headers={"Cookie": "ib_finished=1"})
    assert cookie.startswith("ib_finished=0;") and 'data-topic="tp-done"' not in hidden
    assert "Nothing in flight" in hidden


def test_deep_levels_stop_indenting_and_show_their_depth(conn, http, fake_registry):
    chain = None
    for depth in range(5, 0, -1):
        chain = node(f"tp-d{depth}", f"Level {depth}", sessions=[sess("a", role="topic")],
                     events=[ev("topic", 50 - depth)], children=[chain] if chain else [])
    serve(fake_registry, node("tp-d0", "Root", sessions=[sess("a", state="live")], events=[ev("intent", 60)], children=[chain]))
    _, _, page = get(http, "/topics")
    assert '<span class="deep" title="Level 4">↳ 4</span>Level 4' in page
    assert '<span class="deep" title="Level 5">↳ 5</span>Level 5' in page
    assert "↳ 3" not in page
    # Levels 1 to 3 indent; the lists holding levels 4 and 5 keep level 3's indent.
    assert page.count('<ul class="kids">') == 3 and page.count('<ul class="kids flat">') == 2


def test_every_agent_string_is_escaped(conn, http, fake_registry):
    topic = node(EVIL, EVIL, status="parked", sessions=[sess(EVIL, role="topic", agent=EVIL, directory=EVIL)], events=[
        ev("topic", 30), ev("asked", 25, entry=EVIL, title=EVIL), ev("answered", 20, entry=EVIL, value=EVIL, via=EVIL),
        ev("closed", 15, entry=EVIL, state=EVIL), ev("parked", 10, ref=EVIL), ev(EVIL, 5),
    ])
    owners = [sess(EVIL, state="idle", directory=EVIL), sess(EVIL + "2", agent=EVIL)]
    serve(fake_registry, node("tp-r", EVIL, sessions=owners, events=[ev("intent", 40)], children=[topic]))
    _, _, page = get(http, "/topics?finished=1")
    assert "<img" not in page
    assert page.count("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;") >= 8


def test_a_registry_that_doesnt_answer_shows_a_notice(conn, http, fake_registry):
    status, _, page = get(http, "/topics")
    assert status == 200
    assert "<p class=\"notice warn\">The agent registry didn't answer" in page
    assert '<a href="/topics" aria-current="page">Topics</a>' in page


def test_the_inbox_state_decides_what_waits(conn, http, fake_registry):
    done = ask(conn, "Answered already")
    store.answer(conn, done["id"], "a", via="web")
    serve(fake_registry, node("tp-r", "Root", sessions=[sess("s-1", state="live")],
                              events=[ev("intent", 60), ev("asked", 50, entry=done["id"], title="Answered already")]))
    _, _, page = get(http, "/topics")
    assert "question waiting" not in page and "to answer</span>" not in page


def test_resume_shows_only_for_sessions_that_are_not_live(conn, http, fake_registry):
    serve(fake_registry, node("tp-r", "Root", sessions=[sess("live-1", state="live"), sess("idle-1", state="idle")],
                              events=[ev("intent", 60)]))
    _, _, page = get(http, "/topics")
    assert '<code class="cmd">cd -- /x/agent-tools &amp;&amp; claude --resume idle-1</code>' in page
    assert "--resume live-1" not in page


def test_opening_a_branch_offers_the_reload_instead_of_folding_it_back(conn, http, fake_registry):
    serve(fake_registry)
    _, _, page = get(http, "/topics")
    assert 'document.addEventListener("click", (e) => { if (e.target.closest(".tree summary")) dirty = true; });' in page
    assert '"toggle"' not in page  # browsers fire toggle for every open branch on load


def test_a_timestamp_without_a_timezone_is_read_as_utc(conn, http, fake_registry):
    naive = ev("intent", 60) | {"at": "2026-11-20T10:00:00"}
    serve(fake_registry, node("tp-r", "Root", sessions=[sess("s-1", state="live")], events=[naive]))
    status, _, page = get(http, "/topics")
    assert status == 200 and 'data-topic="tp-r"' in page and " d ago" in page


def test_a_link_with_a_topic_id_can_open_that_branch(conn, http, fake_registry):
    check = node("tp-c", "Check windows", sessions=[sess("s-2", role="topic")], events=[ev("topic", 40, session_id="s-2")])
    plan = node("tp-p", "Write the plan", sessions=[sess("s-1", role="topic")], children=[check], events=[ev("topic", 90)])
    serve(fake_registry, node("tp-r", "Ship the inbox", sessions=[sess("s-1", state="idle")], events=[ev("intent", 100)], children=[plan]))
    _, _, page = get(http, "/topics")
    for tid in ("tp-r", "tp-p", "tp-c"):
        assert page.count(f'id="{tid}"') == 1
    assert "location.hash" in page
    assert "history.replaceState" in page  # a live reload must not jump back to the anchor


def test_a_topic_shown_twice_keeps_its_id_unique(conn, http, fake_registry):
    def twin():
        return node("tp-x", "Shared", sessions=[sess("s-1", role="topic")], events=[ev("topic", 50)])
    a = node("tp-a", "A", sessions=[sess("s-1", role="topic")], children=[twin()], events=[ev("topic", 90)])
    serve(fake_registry, node("tp-r", "Root", sessions=[sess("s-1", state="idle")], events=[ev("intent", 100)], children=[a, twin()]))
    _, _, page = get(http, "/topics")
    assert page.count('data-topic="tp-x"') == 2
    assert page.count('id="tp-x"') == 1
