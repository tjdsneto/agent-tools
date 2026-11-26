import pytest
from topic_tree_helpers import ev, node, sess

from agent_inbox import topic_graph


def views(*roots, states=None):
    return topic_graph.build(topic_graph.clean({"tree": list(roots)}), states or {})


def intent(nid, minutes, *children, state="ended"):
    return node(nid, nid, sessions=[sess(f"s-{nid}", state=state)], events=[ev("intent", minutes)], children=list(children))


def topic(nid, minutes, status="open", *more):
    closed = [ev(status, minutes - 1)] if status != "open" else []
    return node(nid, nid, status=status, sessions=[sess("x", role="topic")], events=[ev("topic", minutes), *closed, *more])


@pytest.mark.parametrize("reply", [None, [], {"tree": "x"}, {"nodes": []}])
def test_clean_refuses_what_isnt_a_tree(reply):
    assert topic_graph.clean(reply) is None


def test_clean_drops_bad_nodes_sessions_and_events():
    raw = {"tree": [
        "junk",
        {"id": ""},
        {
            "id": "tp-a", "title": 7, "status": "weird",
            "sessions": [
                {"agent_type": "claude"},
                {"agent_type": "claude", "session_id": "s", "role": "boss", "live": "yes", "state": "zombie", "directory": 3},
            ],
            "events": [{"at": "x"}, {"event": "asked", "at": 5, "entry": ["ib-1"], "title": "Q"}],
            "children": [{"id": "tp-b"}, None],
        },
    ]}
    assert topic_graph.clean(raw) == [{
        "id": "tp-a", "title": None, "status": "open",
        "sessions": [{"agent_type": "claude", "session_id": "s", "role": "topic", "live": False, "state": "unknown", "directory": None}],
        "events": [{"event": "asked", "at": None, "entry": None, "title": "Q", "value": None, "via": None, "state": None, "ref": None}],
        "children": [{"id": "tp-b", "title": None, "status": "open", "sessions": [], "events": [], "children": []}],
    }]


def test_build_sets_kind_depth_owners_and_lines():
    fork = node("tp-f", "Side", sessions=[sess("p", role="forked"), sess("c", state="idle"), sess("c2", state="live")],
                events=[ev("forked", 50, session_id="p"), ev("adopt", 40, session_id="c")])
    plan = node("tp-p", "Plan", sessions=[sess("p", role="topic")], children=[fork], events=[
        ev("topic", 90), ev("asked", 80, entry="ib-1", title="Which?"), ev("answered", 30, entry="ib-1", value="b", via="chat"),
    ])
    early = node("tp-e", None, status="done", sessions=[sess("p", role="topic")], events=[ev("topic", 95), ev("done", 92)])
    (root,) = views(node("tp-r", "Root", sessions=[sess("p")], events=[ev("intent", 100)], children=[plan, early]))
    assert (root.kind, root.depth, [c.id for c in root.children]) == ("intent", 0, ["tp-e", "tp-p"])
    early_v, plan_v = root.children
    assert (early_v.kind, early_v.title, early_v.status) == ("topic", "tp-e", "done")
    assert [(l.event, l.text, l.entry, l.via) for l in plan_v.lines] == [
        ("topic", None, None, None), ("asked", "Which?", "ib-1", None),
        ("fork", "Side", None, None), ("answered", "b", "ib-1", "chat"),
    ]
    (fork_v,) = plan_v.children
    assert (fork_v.kind, fork_v.depth) == ("intent", 2)
    assert [s["session_id"] for s in fork_v.owners] == ["c2", "c"]
    assert [l.event for l in fork_v.lines] == ["forked", "adopt"]


def test_the_inbox_state_wins_over_the_notes():
    plan = node("tp-p", "Plan", sessions=[sess("p", role="topic")], events=[
        ev("asked", 50, entry="ib-answered", title="A"),  # answered in the inbox; its note was lost
        ev("asked", 40, entry="ib-open", title="B"),  # a note says answered, but the inbox has it open
        ev("answered", 30, entry="ib-open", value="x", via="web"),
        ev("asked", 20, entry="ib-gone", title="C"),  # the inbox no longer has it: the notes decide
        ev("asked", 10, entry="ib-settled", title="D"),
        ev("closed", 5, entry="ib-settled", state="withdrawn"),
    ])
    (root,) = views(node("tp-r", "Root", sessions=[sess("p")], events=[ev("intent", 60)], children=[plan]),
                    states={"ib-answered": "answered", "ib-open": "open"})
    assert root.children[0].waiting == ["ib-open", "ib-gone"]
    assert root.questions() == 2 and root.needs_you()


def test_order_puts_what_needs_you_first_and_holds_back_the_finished():
    done = intent("tp-done", 10, topic("tp-d1", 9, "done"))  # the newest, but finished
    rest = intent("tp-rest", 20, topic("tp-r1", 19, "parked"))  # parked is not finished
    busy_old = intent("tp-busy-old", 300, topic("tp-b1", 299))
    busy_new = intent("tp-busy-new", 30, topic("tp-b2", 29))
    asks = intent("tp-asks", 500, topic("tp-a1", 499, "open", ev("asked", 400, entry="ib-q", title="Q")))
    stray = intent("tp-stray", 200, node("tp-fork", "Fork", status="forked",
                                         sessions=[sess("s-tp-stray", role="forked")], events=[ev("forked", 199)]))
    shown, finished = topic_graph.order(views(done, rest, busy_old, busy_new, asks, stray))
    assert [v.id for v in shown] == ["tp-stray", "tp-asks", "tp-busy-new", "tp-busy-old", "tp-rest"]
    assert [v.id for v in finished] == ["tp-done"]


def test_live_or_parked_is_not_finished_and_an_empty_ended_intent_is():
    (live,) = views(intent("tp-l", 10, state="live"))
    (parked,) = views(intent("tp-p", 10, topic("tp-p1", 9, "parked")))
    (empty,) = views(intent("tp-e", 10))
    assert (live.finished(), parked.finished(), empty.finished()) == (False, False, True)
    assert live.live() and parked.parked() == 1


def test_resume_command_per_engine_with_every_part_quoted():
    assert topic_graph.resume_command(sess("abc", directory="/x/my project")) == "cd '/x/my project' && claude --resume abc"
    assert topic_graph.resume_command(sess("t-1", agent="codex", directory=None)) == "codex resume t-1"
    assert topic_graph.resume_command(sess("c-1", agent="cursor", directory="/x/a")) == "cd /x/a && cursor-agent --resume c-1"
    assert topic_graph.resume_command(sess("x", agent="gemini")) is None
    assert topic_graph.resume_command(sess("$(rm -rf ~)", directory=None)) == "claude --resume '$(rm -rf ~)'"


def test_asked_entries_lists_each_once_across_the_tree():
    child = node("tp-c", "C", events=[ev("asked", 5, entry="ib-2", title="Q"), ev("asked", 4, entry="ib-1", title="Q")])
    root = node("tp-r", "R", children=[child], events=[
        ev("asked", 9, entry="ib-1", title="Q"), ev("posted", 8, entry="ib-9", title="P"),
    ])
    assert sorted(topic_graph.asked_entries(topic_graph.clean({"tree": [root]}))) == ["ib-1", "ib-2"]
