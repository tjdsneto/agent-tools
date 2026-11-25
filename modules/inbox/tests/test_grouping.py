from agent_inbox import grouping

ROOT = {"id": "tp-root", "title": "Topic awareness", "kind": "intent"}
PLAN = {"id": "tp-plan", "title": "Write the plan", "kind": "topic"}
FORK = {"id": "tp-fork", "title": "Manual check: Cursor fork", "kind": "intent"}
CHECK = {"id": "tp-chk", "title": "Check window targeting", "kind": "topic"}
OTHER = {"id": "tp-othr", "title": "Inbox restyle", "kind": "intent"}


def row(rid, path, kind="post", state="unread"):
    return {"id": rid, "kind": kind, "state": state, "topic_path": path}


def ids(group):
    return [r["id"] for r in group.rows]


def test_the_context_line_shows_the_last_two_names():
    assert grouping.context([]) is None
    assert grouping.context([ROOT]) == ("Topic awareness", "Topic awareness")
    assert grouping.context([ROOT, PLAN]) == ("Topic awareness › Write the plan", "Topic awareness › Write the plan")
    shown, full = grouping.context([ROOT, PLAN, FORK, CHECK])
    assert shown == "… › Manual check: Cursor fork › Check window targeting"
    assert full == "Topic awareness › Write the plan › Manual check: Cursor fork › Check window targeting"


def test_a_node_without_a_title_shows_its_id():
    assert grouping.context([{"id": "tp-x", "title": None, "kind": "intent"}]) == ("tp-x", "tp-x")


def test_the_intent_is_the_last_intent_in_the_path():
    assert grouping.intent_of([ROOT, PLAN]) == ROOT
    assert grouping.intent_of([ROOT, PLAN, FORK, CHECK]) == FORK
    assert grouping.intent_of([PLAN]) == PLAN
    assert grouping.intent_of([]) is None


def test_group_by_intent_leads_with_open_questions_and_ends_with_no_topic():
    rows = [
        row("ib-1", None, kind="ask", state="open"),
        row("ib-2", [ROOT, PLAN]),
        row("ib-3", [OTHER], kind="ask", state="open"),
        row("ib-4", [ROOT, PLAN, FORK, CHECK]),
        row("ib-5", [ROOT]),
    ]
    groups = grouping.group_rows(rows, "intent")
    assert [(g.title, ids(g)) for g in groups] == [
        ("Inbox restyle", ["ib-3"]),
        ("Topic awareness", ["ib-2", "ib-5"]),
        ("Manual check: Cursor fork", ["ib-4"]),
        ("No topic", ["ib-1"]),
    ]
    assert groups[1].lead["id"] == "ib-2"


def test_group_by_tree_nests_forked_intents_under_their_root():
    rows = [
        row("ib-3", [OTHER]),
        row("ib-2", [ROOT, PLAN]),
        row("ib-1", [ROOT, PLAN, FORK, CHECK], kind="ask", state="open"),
        row("ib-4", [ROOT, PLAN, FORK]),
        row("ib-5", []),
    ]
    groups = grouping.group_rows(rows, "tree")
    assert [(g.title, ids(g)) for g in groups] == [
        ("Topic awareness", ["ib-2"]), ("Inbox restyle", ["ib-3"]), ("No topic", ["ib-5"]),
    ]
    assert [(s.title, ids(s)) for s in groups[0].subs] == [("Manual check: Cursor fork", ["ib-1", "ib-4"])]
    assert groups[0].has_question() and not groups[1].has_question()


def test_the_intent_filter_lists_intents_in_feed_order_and_narrows():
    rows = [row("ib-1", [ROOT, PLAN]), row("ib-2", [OTHER]), row("ib-3", [ROOT]), row("ib-4", None)]
    assert grouping.intents_in(rows) == [("tp-root", "Topic awareness"), ("tp-othr", "Inbox restyle")]
    assert [r["id"] for r in grouping.only_intent(rows, "tp-root")] == ["ib-1", "ib-3"]
    assert grouping.only_intent(rows, None) == rows


def test_a_malformed_path_counts_as_no_topic():
    rows = [row("ib-1", "tp-root"), row("ib-2", [{"title": "no id"}])]
    assert [g.title for g in grouping.group_rows(rows, "intent")] == ["No topic"]
    assert grouping.context(grouping.path_of(rows[1])) is None
