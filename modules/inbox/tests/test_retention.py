from agent_inbox import serve, store
from agent_inbox.validate import validate_request

CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}


def test_old_closed_html_is_cleared(conn):
    e = store.create_entry(
        conn, "post",
        validate_request({"title": "t", "html": "<p>x</p>"}, "post"),
        script="cron",
    )
    store.archive(conn, e["id"])
    conn.execute("UPDATE entries SET updated_at = now() - interval '91 days' WHERE id = %s", (e["id"],))
    assert serve.purge_html(conn) == 1
    assert store.get_entry(conn, e["id"])["html"] is None


def test_fresh_and_open_html_stays(conn):
    fresh = store.create_entry(
        conn, "post",
        validate_request({"title": "today", "html": "<p>keep</p>"}, "post"),
        script="cron",
    )
    store.archive(conn, fresh["id"])
    open_q = store.create_entry(
        conn, "ask",
        validate_request({"title": "still open", "html": "<p>ask</p>", "control": CHOICE}, "ask"),
        engine="claude", session_id="s-1",
    )
    conn.execute("UPDATE entries SET updated_at = now() - interval '91 days' WHERE id = %s", (open_q["id"],))
    assert serve.purge_html(conn) == 0
    assert store.get_entry(conn, fresh["id"])["html"] == "<p>keep</p>"
    assert store.get_entry(conn, open_q["id"])["html"] == "<p>ask</p>"
