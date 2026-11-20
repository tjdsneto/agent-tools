from datetime import datetime, timezone
from agent_registry import ops, store
from agent_registry.format import format_list

def test_list_split_active_and_stale(tmp_registry):
    ops.register(agent_type="cursor", session_id="live", directory="/a")
    ops.register(agent_type="claude", session_id="old", directory="/b")
    reg = store.load()
    for s in reg.sessions:
        if s.session_id == "old":
            s.last_ping = "2026-09-24T10:00:00+00:00"
    store.save(reg)
    now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    active, stale = ops.list_split(now=now)
    assert [x["session_id"] for x in active] == ["live"]
    assert [x["session_id"] for x in stale] == ["old"]
    assert all("registry_id" not in x for x in active + stale)

def test_format_groups_children(tmp_registry):
    ops.register(agent_type="cursor", session_id="parent", directory="/p")
    ops.register(
        agent_type="cursor", session_id="child", directory="/c",
        parent_session_id="parent",
    )
    text = format_list(*ops.list_split())
    assert "Active" in text
    assert text.index("parent") < text.index("child")
    child_line = [ln for ln in text.splitlines() if "child" in ln][0]
    assert child_line.startswith("  ")
    assert "registry_id" not in text

def test_format_orphan_annotates_parent(tmp_registry):
    ops.register(
        agent_type="cursor", session_id="orphan", directory="/o",
        parent_session_id="missing-parent",
    )
    text = format_list(*ops.list_split())
    assert "parent:missing-parent" in text.replace(" ", "")


def test_live_views_attention(tmp_registry):
    from datetime import datetime, timezone
    from agent_registry import ops, store
    a = ops.register(agent_type="cursor", session_id="ok", directory="/p/ok")
    ops.update(a.registry_id, status="working")
    b = ops.register(agent_type="cursor", session_id="blk", directory="/p/blk")
    ops.update(b.registry_id, status="blocked")
    c = ops.register(agent_type="cursor", session_id="old", directory="/p/old")
    reg = store.load()
    for s in reg.sessions:
        if s.session_id == "old":
            s.last_ping = "2026-09-24T10:00:00+00:00"
    store.save(reg)
    now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    views = ops.live_views(now=now)
    ids_att = {x["session_id"] for x in views["attention"]}
    ids_act = {x["session_id"] for x in views["active"]}
    ids_stale = {x["session_id"] for x in views["stale"]}
    assert ids_att == {"blk", "old"}
    assert "blk" not in ids_act
    assert "old" in ids_stale
    assert "ok" in ids_act
    # project field present
    assert all("project" in x for x in views["active"] + views["stale"] + views["attention"])
