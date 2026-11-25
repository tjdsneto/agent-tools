import os
import threading
from http.client import HTTPConnection

import pytest

from agent_inbox import store
from agent_inbox.validate import validate_request
from agent_inbox.web import make_server

CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}
os.environ["INBOX_ALLOW_INSECURE"] = "1"


@pytest.fixture
def http(conn):
    server = make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    yield host, port
    server.shutdown()
    server.server_close()


def _get(http, path, headers=None):
    conn = HTTPConnection(http[0], http[1], timeout=5)
    conn.request("GET", path, headers=headers or {})
    resp = conn.getresponse()
    return resp.status, resp.read().decode()


def _post(http, path, body, headers=None):
    conn = HTTPConnection(http[0], http[1], timeout=5)
    conn.request(
        "POST", path, body=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", **(headers or {})},
    )
    resp = conn.getresponse()
    return resp.status, resp.getheader("Location"), resp.read().decode()


def test_feed_pins_open_questions_above_unread_info(conn, http):
    q = store.create_entry(conn, "ask", validate_request({"title": "Q", "control": CHOICE}, "ask"), engine="claude", session_id="s-1")
    info = store.create_entry(conn, "post", validate_request({"title": "I"}, "post"), script="cron")
    old = store.create_entry(conn, "post", validate_request({"title": "Old"}, "post"), script="cron")
    store.archive(conn, old["id"])
    status, body = _get(http, "/")
    assert status == 200
    assert body.index(f'href="/e/{q["id"]}"') < body.index(f'href="/e/{info["id"]}"')
    assert "Old" not in body
    assert q["id"] in body and info["id"] in body
    # Live reload, except once a field was touched: then the page offers it.
    assert "if (dirty ||" in body and "location.reload()" in body
    # Leaving the page stops the stream, so a read mark cannot cancel the navigation.
    assert 'addEventListener("beforeunload", () => { leaving = true; es.close(); })' in body


def test_entry_layers(conn, http):
    e = store.create_entry(
        conn, "ask",
        validate_request({"title": "Which split?", "summary": "because", "html": "<p>diagram</p>", "control": CHOICE}, "ask"),
        engine="claude", session_id="s-1",
    )
    status, body = _get(http, f"/e/{e['id']}")
    assert status == 200
    assert "Which split?" in body and "because" in body
    assert 'sandbox="allow-scripts allow-popups"' in body
    assert "allow-same-origin" not in body and "allow-forms" not in body
    assert f"http://127.0.0.1:8798/h/{e['id']}" in body
    assert "Reference only. Answer below." in body


def test_a_foreign_tailscale_login_is_forbidden(conn, http, monkeypatch):
    monkeypatch.delenv("INBOX_ALLOW_INSECURE", raising=False)
    assert _get(http, "/")[0] == 200
    assert _get(http, "/", {"Tailscale-User-Login": "tjdsneto@example.com"})[0] == 200
    assert _get(http, "/", {"Tailscale-User-Login": "someone@example.com"})[0] == 403


def test_answer_posts_and_a_second_answer_conflicts(conn, http):
    e = store.create_entry(conn, "ask", validate_request({"title": "Q", "control": CHOICE}, "ask"), engine="claude", session_id="s-1")
    status, location, _ = _post(http, f"/e/{e['id']}/answer", "value=b&via=web")
    assert status == 303
    assert location == f"/e/{e['id']}"
    assert store.get_entry(conn, e["id"])["state"] == "answered"
    status, _, body = _post(http, f"/e/{e['id']}/answer", "value=a&via=web")
    assert status == 409
    assert "already answered" in body


def test_opening_info_marks_it_read(conn, http):
    info = store.create_entry(conn, "post", validate_request({"title": "note"}, "post"), script="cron")
    status, _ = _get(http, f"/e/{info['id']}")
    assert status == 200
    assert store.get_entry(conn, info["id"])["state"] == "read"


def test_dismiss_hides_an_undelivered_question(conn, http):
    e = store.create_entry(conn, "ask", validate_request({"title": "stuck", "control": CHOICE}, "ask"), engine="claude", session_id="s-1")
    conn.execute("UPDATE entries SET state = 'undelivered' WHERE id = %s", (e["id"],))
    status, location, _ = _post(http, "/batch", f"action=dismiss&id={e['id']}")
    assert status == 303
    assert location == "/"
    assert store.get_entry(conn, e["id"])["delivery"]["dismissed"] is True
    assert store.get_entry(conn, e["id"])["state"] == "undelivered"
    _, body = _get(http, "/")
    assert "stuck" not in body


def _open_ask(conn):
    req = validate_request({"title": "Q", "control": CHOICE}, "ask")
    return store.create_entry(conn, "ask", req, engine="claude", session_id="s-1")


@pytest.mark.parametrize("headers", [
    {"Origin": "http://evil.example"},
    {"Origin": "null"},
    {"Sec-Fetch-Site": "cross-site"},
    {"Sec-Fetch-Site": "same-site"},
])
def test_a_post_from_another_site_is_refused(conn, http, headers):
    e = _open_ask(conn)
    status, _, _ = _post(http, f"/e/{e['id']}/answer", "value=b", headers)
    assert status == 403
    assert store.get_entry(conn, e["id"])["state"] == "open"


def test_a_post_from_the_ui_origin_is_accepted(conn, http):
    e = _open_ask(conn)
    origin = f"http://127.0.0.1:{http[1]}"
    status, _, _ = _post(http, f"/e/{e['id']}/answer", "value=b", {"Origin": origin, "Sec-Fetch-Site": "same-origin"})
    assert status == 303


def test_the_configured_tailnet_origin_is_accepted(conn, http, monkeypatch):
    monkeypatch.setenv("INBOX_UI_ORIGIN", "https://box.example.ts.net:8444")
    e = _open_ask(conn)
    status, _, _ = _post(
        http, f"/e/{e['id']}/answer", "value=b",
        {"Origin": "https://box.example.ts.net:8444", "Host": "box.example.ts.net:8444"},
    )
    assert status == 303


def test_a_rebound_host_is_refused(conn, http):
    assert _get(http, "/", {"Host": f"evil.example:{http[1]}"})[0] == 403


def test_the_form_cannot_choose_its_surface(conn, http):
    e = _open_ask(conn)
    _post(http, f"/e/{e['id']}/answer", "value=b&via=telegram")
    assert store.get_entry(conn, e["id"])["answer"]["via"] == "web"


def test_entry_page_fits_a_phone_and_puts_the_comment_before_submit(conn, http):
    opts = [{"id": "a", "label": "A", "description": "the safe one", "default": True}, {"id": "b", "label": "B"}]
    req = validate_request({"title": "Q", "detail": "x" * 300, "control": {"type": "choice", "options": opts}}, "ask")
    e = store.create_entry(conn, "ask", req, engine="claude", session_id="s-1")
    _, body = _get(http, f"/e/{e['id']}")
    assert "white-space: pre-wrap" in body
    assert body.index('name="comment"') < body.index('type="submit">Send answer')
    assert 'value="a" checked' in body and "the safe one" in body


def test_a_held_question_shows_when_and_cannot_be_answered(conn, http):
    e = store.create_entry(conn, "ask", validate_request({"title": "Q", "control": CHOICE}, "ask"), engine="claude", session_id="s-1")
    conn.execute(
        """UPDATE entries SET delivery = delivery || '{"reachability": "held", "reachable_at": "2026-11-24T02:10:00"}' WHERE id = %s""",
        (e["id"],),
    )
    _, body = _get(http, f"/e/{e['id']}")
    assert "Held, answerable at ~02:10" in body
    assert "out of tokens" in body
    assert "<fieldset disabled>" in body
    _, feed = _get(http, "/")
    assert "Held, answerable at ~02:10" in feed


def test_a_resumable_question_can_be_answered(conn, http):
    e = store.create_entry(conn, "ask", validate_request({"title": "Q", "control": CHOICE}, "ask"), engine="claude", session_id="s-1")
    conn.execute("""UPDATE entries SET delivery = delivery || '{"reachability": "resumable"}' WHERE id = %s""", (e["id"],))
    _, body = _get(http, f"/e/{e['id']}")
    assert '<span class="chip blue">Resumable</span>' in body
    assert "<fieldset>" in body


def test_summary_and_detail_render_markdown_without_raw_html(conn, http):
    detail = "## Why\n\n- **fast**\n- `agt inbox`\n\n[docs](https://example.com) [bad](javascript:alert(1))\n\n<script>alert(1)</script>"
    e = store.create_entry(conn, "post", validate_request({"title": "I", "summary": "Run **done**", "detail": detail}, "post"), script="cron")
    _, body = _get(http, f"/e/{e['id']}")
    assert "Run <strong>done</strong>" in body
    assert "<h2>Why</h2>" in body and "<li><strong>fast</strong></li>" in body and "<code>agt inbox</code>" in body
    assert '<a href="https://example.com">docs</a>' in body
    assert 'href="javascript:' not in body
    assert "<script>alert(1)</script>" not in body and "&lt;script&gt;alert(1)&lt;/script&gt;" in body


def test_answer_card_shows_one_tick_when_sent_and_two_when_delivered(conn, http):
    e = store.create_entry(conn, "ask", validate_request({"title": "Q", "control": CHOICE}, "ask"), engine="claude", session_id="s-1")
    conn.execute(
        """UPDATE entries SET state = 'answered', answer = '{"value": "a", "via": "telegram", "at": "2026-11-24T10:00:00-03:00"}' WHERE id = %s""",
        (e["id"],),
    )
    _, body = _get(http, f"/e/{e['id']}")
    assert 'data-state="sent"' in body and 'aria-label="Sent"' in body and 'class="t2"' not in body
    assert "From Telegram" in body
    conn.execute("UPDATE entries SET state = 'delivered' WHERE id = %s", (e["id"],))
    _, body = _get(http, f"/e/{e['id']}")
    assert 'data-state="delivered"' in body and 'aria-label="Delivered"' in body and 'class="t2"' in body


def test_follow_up_bubbles_tick_by_delivered_seq(conn, http):
    e = store.create_entry(conn, "ask", validate_request({"title": "Q", "control": CHOICE}, "ask"), engine="claude", session_id="s-1")
    first = store.add_followup(conn, e["id"], "one", via="web")
    store.add_followup(conn, e["id"], "two", via="web")
    seq = first.get("seq") or store.get_entry(conn, e["id"])["thread"][0]["seq"]
    conn.execute("UPDATE entries SET delivery = delivery || jsonb_build_object('delivered_seq', %s::int) WHERE id = %s", (seq, e["id"]))
    _, body = _get(http, f"/e/{e['id']}")
    assert body.count('class="msg me"') == 2
    assert body.count('aria-label="Delivered"') == 1 and body.count('aria-label="Sent"') == 1


def test_entry_page_lists_the_feed_beside_it_and_marks_the_current_one(conn, http):
    a = store.create_entry(conn, "ask", validate_request({"title": "First", "control": CHOICE}, "ask"), engine="claude", session_id="s-1")
    b = store.create_entry(conn, "ask", validate_request({"title": "Second", "control": CHOICE}, "ask"), engine="claude", session_id="s-2")
    _, body = _get(http, f"/e/{b['id']}")
    assert '<body class="split">' in body and 'class="pane"' in body
    assert f'href="/e/{b["id"]}" aria-current="page"' in body
    assert f'href="/e/{a["id"]}">' in body
    # The pane is navigation only: batch checkboxes stay on the feed.
    pane = body[body.index('class="pane"'):body.index("<main>")]
    assert 'type="checkbox"' not in pane


def test_answered_questions_leave_the_default_view_for_history(conn, http):
    done = store.create_entry(conn, "ask", validate_request({"title": "Done one", "control": CHOICE}, "ask"), engine="claude", session_id="s-1")
    sent = store.create_entry(conn, "ask", validate_request({"title": "Sent one", "control": CHOICE}, "ask"), engine="claude", session_id="s-2")
    waiting = store.create_entry(conn, "ask", validate_request({"title": "Waiting one", "control": CHOICE}, "ask"), engine="claude", session_id="s-3")
    conn.execute("""UPDATE entries SET state = 'delivered', answer = '{"value": "a", "via": "telegram"}' WHERE id = %s""", (done["id"],))
    conn.execute("""UPDATE entries SET state = 'answered', answer = '{"value": "a", "via": "web"}' WHERE id = %s""", (sent["id"],))
    _, feed = _get(http, "/")
    assert waiting["id"] in feed and done["id"] not in feed and sent["id"] not in feed
    _, history = _get(http, "/?history=1")
    assert done["id"] in history and sent["id"] in history
    # The row says it was answered, and what with, like a chat preview.
    label = next(o["label"] for o in CHOICE["options"] if o["id"] == "a")
    assert f"You: {label}" in history
    assert 'aria-label="Delivered"></svg>' not in history  # ticks are drawn, not empty
    assert '<span class="chip green"><svg class="ticks"' in history and "Answered</span>" in history
    # An explicit state filter still finds them.
    _, filtered = _get(http, "/?state=delivered")
    assert done["id"] in filtered


def test_an_answered_entry_still_marks_itself_in_the_pane(conn, http):
    e = store.create_entry(conn, "ask", validate_request({"title": "Done", "control": CHOICE}, "ask"), engine="claude", session_id="s-1")
    conn.execute("""UPDATE entries SET state = 'delivered', answer = '{"value": "a", "via": "web"}' WHERE id = %s""", (e["id"],))
    _, body = _get(http, f"/e/{e['id']}")
    pane = body[body.index('class="pane"'):body.index("<main>")]
    assert f'href="/e/{e["id"]}" aria-current="page"' in pane


def test_a_read_report_leaves_the_default_view_for_history(conn, http):
    fresh = store.create_entry(conn, "post", validate_request({"title": "Fresh"}, "post"), script="cron")
    seen = store.create_entry(conn, "post", validate_request({"title": "Seen"}, "post"), script="cron")
    store.mark_read(conn, seen["id"])
    _, feed = _get(http, "/")
    assert fresh["id"] in feed and seen["id"] not in feed
    _, history = _get(http, "/?history=1")
    assert seen["id"] in history
    _, info = _get(http, "/?kind=post&state=read")
    assert seen["id"] in info


def test_an_answered_script_ask_says_it_waits_for_the_script(conn, http):
    e = store.create_entry(conn, "ask", validate_request({"title": "Ship?", "control": CHOICE}, "ask"), script="autopilot")
    store.answer(conn, e["id"], "a", via="web")
    _, body = _get(http, f"/e/{e['id']}")
    assert "Saved for autopilot to pick up" in body and 'data-state="saved"' in body


def test_filters_narrow_the_current_tab_and_count_what_they_change(conn, http):
    _, plain = _get(http, "/")
    assert '<a href="/" aria-current="page">Active</a>' in plain
    assert 'class="filt"' in plain and 'aria-label="Filters"' in plain
    _, info = _get(http, "/?kind=post&engine=codex")
    assert '<a href="/?kind=post" aria-current="page">Info</a>' in info
    assert '<option value="post" selected>Report</option>' in info
    assert 'class="filt on"' in info and 'aria-label="Filters, 1 on"' in info
    assert '<a class="btn" href="/?kind=post">Clear</a>' in info
    # A tab's own state is not a filter; a different one is.
    _, needs = _get(http, "/?kind=ask&state=open")
    assert '<a href="/?kind=ask&state=open" aria-current="page"><span class="lg">Needs answer</span><span class="sm">To answer</span></a>' in needs and 'class="filt"' in needs
    _, other = _get(http, "/?kind=ask&state=expired")
    assert 'aria-current="page"><span class="lg">Needs answer</span><span class="sm">To answer</span></a>' in other and 'Filters, 1 on' in other


def test_next_walks_the_feed_and_survives_reading_and_answering(conn, http):
    first = store.create_entry(conn, "post", validate_request({"title": "First"}, "post"), script="cron")
    second = store.create_entry(conn, "post", validate_request({"title": "Second"}, "post"), script="cron")
    third = store.create_entry(conn, "post", validate_request({"title": "Third"}, "post"), script="cron")
    _, feed = _get(http, "/")
    order = [e["id"] for e in (first, second, third)]
    order.sort(key=feed.index)
    top, middle, last = order
    # Opening the middle report marks it read, but Next still goes to the row below it, not the top.
    _, page = _get(http, f"/e/{middle}")
    assert f'<a class="step" href="/e/{last}" rel="next" title="Next (J)">' in page
    _, page = _get(http, f"/e/{last}")
    # The last one finishes: back to the inbox.
    assert '<a class="step" href="/" title="Finish (J)">Finish' in page
    # An answered question has left the feed; the answer form carries Next through the post.
    q = store.create_entry(conn, "ask", validate_request({"title": "Q", "control": CHOICE}, "ask"), engine="claude", session_id="s-1")
    conn.execute("UPDATE entries SET delivery = delivery || '{\"reachability\": \"live\"}' WHERE id = %s", (q["id"],))
    _, page = _get(http, f"/e/{q['id']}")
    assert f'action="/e/{q["id"]}/answer?next={top}"' in page
    status, location, _ = _post(http, f"/e/{q['id']}/answer?next={top}", "value=a")
    assert status == 303 and location == f"/e/{q['id']}?next={top}"
    _, page = _get(http, location)
    assert f'<a class="step" href="/e/{top}" rel="next" title="Next (J)">' in page


def test_history_lists_the_newest_first(conn, http):
    # The old one is urgent, so the feed's urgent-first order would list it first.
    old = store.create_entry(conn, "post", validate_request({"title": "Old", "priority": "urgent"}, "post"), script="cron")
    new = store.create_entry(conn, "post", validate_request({"title": "New"}, "post"), script="cron")
    conn.execute("UPDATE entries SET created_at = now() - interval '2 days' WHERE id = %s", (old["id"],))
    for e in (old, new):
        store.mark_read(conn, e["id"])
    _, body = _get(http, "/?history=1")
    assert body.index(new["id"]) < body.index(old["id"])


def test_filters_pick_a_type_and_a_project(conn, http):
    here = store.create_entry(conn, "post", validate_request({"title": "Here"}, "post"), script="cron", cwd="/x/agent-tools")
    there = store.create_entry(conn, "ask", validate_request({"title": "There", "control": CHOICE}, "ask"),
                               engine="claude", session_id="s-1", cwd="/x/am-videos")
    _, page = _get(http, "/")
    assert '<option value="/x/am-videos">am-videos</option>' in page and '<option value="ask">Question</option>' in page
    _, page = _get(http, "/?project=/x/agent-tools")
    assert here["id"] in page and there["id"] not in page and "Filters, 1 on" in page
    # In History, Type narrows the tab instead of switching to Info.
    store.mark_read(conn, here["id"])
    _, page = _get(http, "/?history=1&kind=post")
    assert 'aria-current="page">History</a>' in page and here["id"] in page and "Filters, 1 on" in page


def test_history_groups_entries_by_day(conn, http):
    today = store.create_entry(conn, "post", validate_request({"title": "Today"}, "post"), script="cron")
    before = store.create_entry(conn, "post", validate_request({"title": "Before"}, "post"), script="cron")
    conn.execute("UPDATE entries SET created_at = now() - interval '1 day' WHERE id = %s", (before["id"],))
    for e in (today, before):
        store.mark_read(conn, e["id"])
    _, body = _get(http, "/?history=1")
    assert body.index("<h2>Today</h2>") < body.index(today["id"]) < body.index("<h2>Yesterday</h2>") < body.index(before["id"])
    _, feed = _get(http, "/")
    assert 'class="day"' not in feed


def test_rows_mark_questions_and_reports_apart(conn, http):
    store.create_entry(conn, "ask", validate_request({"title": "Q", "control": CHOICE}, "ask"), engine="claude", session_id="s-1")
    store.create_entry(conn, "post", validate_request({"title": "R"}, "post"), script="cron")
    _, feed = _get(http, "/")
    assert 'role="img" aria-label="Question"' in feed and '<i class="kb q">' in feed
    assert 'role="img" aria-label="Report"' in feed and '<i class="kb r">' in feed
