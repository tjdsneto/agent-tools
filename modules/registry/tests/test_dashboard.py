import json
import os
import threading
import urllib.error
import urllib.request
from agent_registry import ops
from agent_registry.dashboard import _warn_if_non_loopback, make_server


def test_api_live_and_archive(tmp_registry):
    s = ops.register(agent_type="cursor", session_id="a", directory="/Users/x/projects/lindris")
    ops.update(s.registry_id, status="blocked", summary="need input")
    ops.unregister(s.registry_id)
    httpd = make_server("127.0.0.1", 0)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        live = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/live").read())
        assert "active" in live and "stale" in live and "attention" in live
        arch = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/archive").read())
        assert arch["events"][0]["reason"] == "unregister"
        assert "registry_id" not in arch["events"][0]["session"]
        assert arch["corrupt"] is False
        home = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode()
        assert "agent-registry" in home
        assert "Copy session id" in home
        assert "data-copy=" in home
    finally:
        httpd.shutdown()


def test_api_archive_corrupt_flag(tmp_registry):
    from agent_registry import archive

    archive.archive_path().write_text("not-json\n", encoding="utf-8")
    httpd = make_server("127.0.0.1", 0)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        arch = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/archive").read())
        assert arch["events"] == []
        assert arch["corrupt"] is True
    finally:
        httpd.shutdown()


def test_make_server_binds_loopback():
    httpd = make_server("127.0.0.1", 0)
    try:
        assert httpd.server_address[0] == "127.0.0.1"
        assert httpd.server_address[1] > 0
    finally:
        httpd.server_close()


def test_warn_if_non_loopback(capsys):
    _warn_if_non_loopback("0.0.0.0")
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "0.0.0.0" in err


def test_api_live_corrupt_flag(tmp_registry):
    tmp_registry.write_text("{not json", encoding="utf-8")
    httpd = make_server("127.0.0.1", 0)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        live = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/live").read())
        assert live["active"] == []
        assert live["stale"] == []
        assert live["attention"] == []
        assert live["corrupt"] is True
    finally:
        httpd.shutdown()


def test_archive_events_include_project(tmp_registry):
    s = ops.register(
        agent_type="cursor",
        session_id="a",
        directory="/Users/x/projects/lindris",
    )
    ops.unregister(s.registry_id)
    httpd = make_server("127.0.0.1", 0)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        arch = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/archive").read())
        assert arch["events"][0]["session"]["project"] == "lindris"
    finally:
        httpd.shutdown()

    httpd = make_server("127.0.0.1", 0)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/archive?limit=-1")
            raise AssertionError("expected HTTPError")
        except urllib.error.HTTPError as e:
            assert e.code == 400
            body = json.loads(e.read())
            assert "error" in body
    finally:
        httpd.shutdown()


def test_board_actions_in_script(tmp_registry):
    from agent_registry.daemon import make_daemon

    claude = ops.register(
        agent_type="claude", session_id="c1", directory="/Users/x/projects/lindris", pid=os.getpid()
    )
    ops.register(
        agent_type="codex",
        session_id="x1",
        directory="/Users/x/projects/lindris",
        parent_session_id="c1",
    )
    httpd = make_server("127.0.0.1", 0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    daemon = make_daemon("127.0.0.1", 0)
    daemon_port = daemon.server_address[1]
    threading.Thread(target=daemon.serve_forever, daemon=True).start()
    try:
        home = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode()
        script = home[home.index("<script"):]
        # Engine marks keyed by lowercase agent_type.
        assert 'class="engine engine-' in script
        assert "agent_type" in script
        for mark in ("claude:", "codex:", "cursor:"):
            assert mark in script
        assert "m4.7144 15.9555" in script
        assert "M22.2819 9.8211" in script
        assert "M11.503.131" in script
        assert "side-resize" in home
        assert "function dirsFor" in script
        assert "function processOpen" in script
        assert "cursor_open" in script
        assert "function dotStatus" in script
        # Vocabulary: no old lifecycle words in the served board
        for banned in (">Live<", ">Stopped<", ">Running<", "No process open"):
            assert banned not in home and banned not in script
        assert ">Open<" in home or ">Open<" in script
        assert ">Closed<" in home or ">Closed<" in script
        assert "All Open" in home or "All Open" in script
        # Navigation hooks
        assert "All Open" in script or 'navRow("all-open"' in script or "all-open" in script
        assert 'selectedProject === "all-open"' in script
        assert 'navRow("all-open", "All Open"' in script
        assert "Other worktrees" in script
        assert 'id="tabs"' in home
        assert 'getElementById("tabs")' in script
        assert 'classList.toggle("hidden", allOpen)' in script
        assert "group-by" in home.lower() or "groupby" in script.lower() or "LS_GROUP" in script
        # Usage rendered only when present.
        assert "if (sess.tokens)" in script
        assert "input_tokens" in script and "output_tokens" in script
        assert "total_tokens" in script
        assert "if (sess.cpu_percent != null)" in script
        assert "cpu_percent" in script and "memory_bytes" in script
        # Action buttons and ops.
        for label in ("Archive", "Kill", "Send"):
            assert f'actionBtn("{label}"' in script
        assert 'if (!sess.pid) return ""' in script
        assert "function killBtn" in script
        assert "archive_session" in script and "kill_session" in script
        assert "send_session" in script
        assert "confirm(" not in script
        assert "session_id: sess.session_id" in script
        assert "registry_id" not in script
        assert '"Content-Type": "application/json"' in script
        assert "/api/command" in script
        # Nesting stays on buildForest / parent_session_id.
        assert "function buildForest" in script
        assert "parent_session_id" in script
        assert "buildForest(items)" in script
        from agent_registry import __version__
        assert f'const APP_VERSION = "{__version__}"' in script
        assert "function renderProjects" in script
        assert "Loading" in home

        live = json.loads(
            urllib.request.urlopen(f"http://127.0.0.1:{daemon_port}/api/live").read()
        )
        rows = {s["session_id"]: s for s in live["active"]}
        assert rows["x1"]["parent_session_id"] == "c1"
        assert rows["c1"]["pid"] == os.getpid()
        for row in rows.values():
            assert "registry_id" not in row
            if "tokens" in row:
                assert isinstance(row["tokens"], dict)
    finally:
        httpd.shutdown()
        daemon.shutdown()
        daemon.server_close()
    assert claude.registry_id
