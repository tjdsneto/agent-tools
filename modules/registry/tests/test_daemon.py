import json
import os
import signal
import urllib.request
from pathlib import Path

from agent_registry.daemon import serve_in_thread, stop_server


def test_health_and_pid_files(tmp_registry):
    httpd = serve_in_thread("127.0.0.1", 0)
    port = httpd.server_address[1]
    try:
        body = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health").read())
        assert body == {"ok": True, "service": "agent-registry"}
        reg_dir = Path(os.environ["AGENT_REGISTRY_PATH"]).parent
        assert (reg_dir / "daemon.port").read_text().strip() == str(port)
        pid = int((reg_dir / "daemon.pid").read_text().strip())
        assert pid == os.getpid()
    finally:
        stop_server(httpd)
        reg_dir = Path(os.environ["AGENT_REGISTRY_PATH"]).parent
        assert not (reg_dir / "daemon.pid").exists()
        assert not (reg_dir / "daemon.port").exists()


def test_command_ensure_list_end_strips_registry_id_on_list(tmp_registry):
    httpd = serve_in_thread("127.0.0.1", 0)
    port = httpd.server_address[1]
    url = f"http://127.0.0.1:{port}/api/command"

    def post(op, params):
        req = urllib.request.Request(
            url,
            data=json.dumps({"op": op, "params": params}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return json.loads(urllib.request.urlopen(req).read())

    try:
        ensured = post("ensure", {
            "agent_type": "cursor",
            "session_id": "s1",
            "directory": "/proj",
            "parent_session": "parent-1",
        })
        assert ensured["exit_code"] == 0
        assert ensured["data"]["session"]["registry_id"]
        assert ensured["data"]["session"]["parent_session_id"] == "parent-1"
        listed = post("list", {})
        assert listed["exit_code"] == 0
        assert "registry_id" not in listed["data"]["active"][0]
        assert listed["data"]["active"][0]["parent_session_id"] == "parent-1"
        ended = post("end", {"agent_type": "cursor", "session_id": "s1"})
        assert ended["exit_code"] == 0
        again = post("list", {})
        assert again["data"]["active"] == []
    finally:
        stop_server(httpd)


def test_command_ensure_missing_params_is_exit_1(tmp_registry):
    httpd = serve_in_thread("127.0.0.1", 0)
    port = httpd.server_address[1]
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/command",
        data=json.dumps({"op": "ensure", "params": {}}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            body = json.loads(resp.read())
        assert body["exit_code"] == 1
        assert body["data"] is None
        assert body["error"]
    finally:
        stop_server(httpd)


def _command_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/api/command"


def _post_command(port: int, payload: dict, headers: dict[str, str]):
    req = urllib.request.Request(
        _command_url(port),
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        return json.loads(resp.read())


def post(port: int, op: str, params: dict):
    return _post_command(
        port,
        {"op": op, "params": params},
        {"Content-Type": "application/json"},
    )


def test_command_ensure_non_string_agent_type_is_exit_1(tmp_registry):
    httpd = serve_in_thread("127.0.0.1", 0)
    port = httpd.server_address[1]
    try:
        body = _post_command(
            port,
            {
                "op": "ensure",
                "params": {"agent_type": 1, "session_id": "s1", "directory": "/proj"},
            },
            {"Content-Type": "application/json"},
        )
        assert body["exit_code"] == 1
        assert body["data"] is None
    finally:
        stop_server(httpd)


def test_command_rejects_non_json_content_type_before_ensure(tmp_registry):
    httpd = serve_in_thread("127.0.0.1", 0)
    port = httpd.server_address[1]
    try:
        rejected = _post_command(
            port,
            {
                "op": "ensure",
                "params": {
                    "agent_type": "cursor",
                    "session_id": "s1",
                    "directory": "/proj",
                },
            },
            {"Content-Type": "text/plain"},
        )
        assert rejected["exit_code"] == 1
        listed = _post_command(port, {"op": "list", "params": {}}, {"Content-Type": "application/json"})
        assert listed["exit_code"] == 0
        assert listed["data"]["active"] == []
    finally:
        stop_server(httpd)


def test_command_rejects_non_loopback_host_before_ensure(tmp_registry):
    httpd = serve_in_thread("127.0.0.1", 0)
    port = httpd.server_address[1]
    try:
        rejected = _post_command(
            port,
            {
                "op": "ensure",
                "params": {
                    "agent_type": "cursor",
                    "session_id": "s1",
                    "directory": "/proj",
                },
            },
            {"Content-Type": "application/json", "Host": "evil.example"},
        )
        assert rejected["exit_code"] == 1
        listed = _post_command(port, {"op": "list", "params": {}}, {"Content-Type": "application/json"})
        assert listed["exit_code"] == 0
        assert listed["data"]["active"] == []
    finally:
        stop_server(httpd)


def test_remaining_ops(tmp_registry, monkeypatch):
    monkeypatch.setenv("AGENT_REGISTRY_SUMMARY_PROVIDER", "off")
    httpd = serve_in_thread("127.0.0.1", 0)
    port = httpd.server_address[1]
    headers = {"Content-Type": "application/json"}

    def post(op, params):
        return _post_command(port, {"op": op, "params": params}, headers)

    try:
        registered = post("register", {
            "agent_type": "cursor",
            "session_id": "reg-1",
            "directory": "/proj",
        })
        assert registered["exit_code"] == 0
        registry_id = registered["data"]["registry_id"]
        assert registry_id

        updated = post("update", {"registry_id": registry_id})
        assert updated["exit_code"] == 1
        assert updated["data"] is None

        pinged = post("ping", {"registry_id": "missing-registry-id"})
        assert pinged["exit_code"] == 2

        removed = post("unregister", {"registry_id": registry_id})
        assert removed["exit_code"] == 0
        assert removed["data"] == {"ok": True}

        listed = post("archive_list", {})
        assert listed["exit_code"] == 0
        event = listed["data"][0]
        assert event["reason"] == "unregister"
        assert "registry_id" not in event["session"]

        shown = post("archive_show", {"session_id": "reg-1"})
        assert shown["exit_code"] == 0
        assert "registry_id" not in shown["data"]["session"]
        full = post("archive_show", {"session_id": "reg-1", "full": True})
        assert full["exit_code"] == 0
        assert full["data"]["session"]["registry_id"] == registry_id

        pruned = post("prune", {})
        assert pruned["exit_code"] == 1

        ensured = post("ensure", {
            "agent_type": "cursor",
            "session_id": "self-1",
            "directory": "/proj",
        })
        assert ensured["exit_code"] == 0
        owner = post("self", {"agent_type": "cursor", "session_id": "self-1"})
        assert owner["exit_code"] == 0
        assert owner["data"]["registry_id"] == ensured["data"]["session"]["registry_id"]
        missing_self = post("self", {"agent_type": "cursor", "session_id": "never-ensured"})
        assert missing_self["exit_code"] == 2
        assert missing_self["error"] == "session not found"

        status = post("status", {})
        assert status["exit_code"] == 0
        assert status["data"]["registry_path"] == os.environ["AGENT_REGISTRY_PATH"]
        for key in ("active", "stale", "archived", "registry_path", "archive_path"):
            assert key in status["data"]

        doctor = post("doctor", {})
        assert doctor["exit_code"] == 0
        assert doctor["data"]["ok"] is True
        assert doctor["data"]["lines"]
        assert all(isinstance(line, str) for line in doctor["data"]["lines"])

        resolved = post("resolve", {"session_id": "daemon-test-missing-session"})
        assert resolved["exit_code"] == 2

        summary = post("summarize", {"agent_type": "cursor", "session_id": "self-1"})
        assert summary["exit_code"] == 0
        assert summary["data"]["ok"] is False or summary["data"].get("skipped")
    finally:
        stop_server(httpd)


def test_archive_parent_leaves_child(tmp_registry):
    httpd = serve_in_thread("127.0.0.1", 0)
    port = httpd.server_address[1]
    try:
        post(port, "ensure", {"agent_type": "claude", "session_id": "parent", "directory": "/p", "pid": os.getpid()})
        post(port, "ensure", {
            "agent_type": "claude", "session_id": "child", "directory": "/p",
            "parent_session": "parent",
        })
        archived = post(port, "archive_session", {"session_id": "parent", "registry_id": "ignore-me"})
        assert archived["exit_code"] == 0
        live = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/live").read())
        ids = [s["session_id"] for s in live["active"] + live["stale"] + live["attention"]]
        assert "parent" not in ids
        child = next(s for s in live["active"] if s["session_id"] == "child")
        assert child["parent_session_id"] == "parent"
        assert "registry_id" not in archived["data"]
        assert archived["data"]["session_id"] == "parent"
    finally:
        stop_server(httpd)


def test_archive_missing_session_is_not_found(tmp_registry):
    httpd = serve_in_thread("127.0.0.1", 0)
    port = httpd.server_address[1]
    try:
        missing = post(port, "archive_session", {"session_id": "nobody"})
        assert missing["exit_code"] == 2
    finally:
        stop_server(httpd)


def test_archive_unregister_race_hides_registry_id(tmp_registry, monkeypatch):
    from agent_registry.ops import UnknownRegistryIdError

    httpd = serve_in_thread("127.0.0.1", 0)
    port = httpd.server_address[1]
    try:
        ensured = post(port, "ensure", {
            "agent_type": "claude", "session_id": "s", "directory": "/p",
        })
        registry_id = ensured["data"]["session"]["registry_id"]
        assert registry_id

        def gone(rid):
            raise UnknownRegistryIdError(registry_id)

        monkeypatch.setattr("agent_registry.daemon.ops.unregister", gone)
        archived = post(port, "archive_session", {"session_id": "s"})
        assert archived["exit_code"] == 2
        assert archived["data"] is None
        assert archived["error"] == "session not found"
        assert registry_id not in json.dumps(archived)
    finally:
        stop_server(httpd)


def test_kill_unregister_race_stays_ok_without_registry_id(tmp_registry, monkeypatch):
    from agent_registry.ops import UnknownRegistryIdError

    monkeypatch.setattr("agent_registry.daemon.os.kill", lambda pid, sig: None)
    monkeypatch.setattr(
        "agent_registry.usage.sample_process",
        lambda pid: {"cpu_percent": 1.0, "memory_bytes": 1},
    )
    httpd = serve_in_thread("127.0.0.1", 0)
    port = httpd.server_address[1]
    try:
        ensured = post(port, "ensure", {
            "agent_type": "claude", "session_id": "s", "directory": "/p", "pid": 4242,
        })
        registry_id = ensured["data"]["session"]["registry_id"]

        def gone(rid):
            raise UnknownRegistryIdError(registry_id)

        monkeypatch.setattr("agent_registry.daemon.ops.unregister", gone)
        killed = post(port, "kill_session", {"session_id": "s"})
        assert killed["exit_code"] == 0
        assert killed["data"] == {"ok": True, "session_id": "s"}
        assert killed["error"] is None
        assert registry_id not in json.dumps(killed)
    finally:
        stop_server(httpd)


def test_kill_signals_only_that_pid(tmp_registry, monkeypatch):
    signaled = []
    monkeypatch.setattr("agent_registry.daemon.os.kill", lambda pid, sig: signaled.append((pid, sig)))
    monkeypatch.setattr(
        "agent_registry.usage.sample_process",
        lambda pid: {"cpu_percent": 1.0, "memory_bytes": 1} if pid == 4242 else None,
    )
    httpd = serve_in_thread("127.0.0.1", 0)
    try:
        post(httpd.server_address[1], "ensure", {
            "agent_type": "claude", "session_id": "s", "directory": "/p", "pid": 4242,
        })
        killed = post(httpd.server_address[1], "kill_session", {"session_id": "s"})
        assert killed["exit_code"] == 0
        assert signaled == [(4242, signal.SIGTERM)]
        assert "registry_id" not in (killed["data"] or {})
        live = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{httpd.server_address[1]}/api/live"
        ).read())
        assert live["active"] == []
    finally:
        stop_server(httpd)


def test_kill_without_pid_is_usage(tmp_registry):
    httpd = serve_in_thread("127.0.0.1", 0)
    try:
        post(httpd.server_address[1], "ensure", {
            "agent_type": "codex", "session_id": "s", "directory": "/p",
        })
        killed = post(httpd.server_address[1], "kill_session", {"session_id": "s"})
        assert killed["exit_code"] == 1
        assert "no live pid" in killed["error"]
    finally:
        stop_server(httpd)


def test_kill_dead_pid_does_not_signal(tmp_registry, monkeypatch):
    signaled = []
    monkeypatch.setattr("agent_registry.daemon.os.kill", lambda pid, sig: signaled.append((pid, sig)))
    monkeypatch.setattr("agent_registry.usage.sample_process", lambda pid: None)
    httpd = serve_in_thread("127.0.0.1", 0)
    port = httpd.server_address[1]
    try:
        post(port, "ensure", {
            "agent_type": "claude", "session_id": "s", "directory": "/p", "pid": 4242,
        })
        killed = post(port, "kill_session", {"session_id": "s"})
        assert killed["exit_code"] == 1
        assert "no live pid" in killed["error"]
        assert signaled == []
        live = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/live").read())
        assert [s["session_id"] for s in live["active"]] == ["s"]
    finally:
        stop_server(httpd)


def test_kill_process_gone_does_not_unregister(tmp_registry, monkeypatch):
    def gone(pid, sig):
        raise ProcessLookupError(pid)

    monkeypatch.setattr("agent_registry.daemon.os.kill", gone)
    monkeypatch.setattr(
        "agent_registry.usage.sample_process",
        lambda pid: {"cpu_percent": 1.0, "memory_bytes": 1},
    )
    httpd = serve_in_thread("127.0.0.1", 0)
    port = httpd.server_address[1]
    try:
        post(port, "ensure", {
            "agent_type": "claude", "session_id": "s", "directory": "/p", "pid": 4242,
        })
        killed = post(port, "kill_session", {"session_id": "s"})
        assert killed["exit_code"] == 1
        live = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/live").read())
        assert [s["session_id"] for s in live["active"]] == ["s"]
    finally:
        stop_server(httpd)


def test_send_session_wakes_and_rejects_empty(tmp_registry, monkeypatch):
    arrived = {}
    results = [
        {"result": "landed", "session_id": "s"},
        {"result": "already_awake", "session_id": "s"},
        {"result": "undelivered", "session_id": "s"},
    ]

    def fake_wake(sid, msg, **k):
        arrived["session_id"] = sid
        arrived["message"] = msg
        return results.pop(0)

    monkeypatch.setattr("agent_registry.transport.wake", fake_wake)
    httpd = serve_in_thread("127.0.0.1", 0)
    port = httpd.server_address[1]
    try:
        sent = post(port, "send_session", {"session_id": "s", "message": "hello"})
        assert sent["exit_code"] == 0
        assert arrived == {"session_id": "s", "message": "hello"}
        assert sent["data"]["result"] == "landed"
        awake = post(port, "send_session", {"session_id": "s", "message": "again"})
        assert awake["exit_code"] == 0
        assert arrived["message"] == "again"
        missed = post(port, "send_session", {"session_id": "s", "message": "nope"})
        assert missed["exit_code"] == 1
        assert missed["data"]["result"] == "undelivered"
        calls_before_empty = dict(arrived)
        empty = post(port, "send_session", {"session_id": "s", "message": ""})
        assert empty["exit_code"] == 1
        assert arrived == calls_before_empty
    finally:
        stop_server(httpd)
