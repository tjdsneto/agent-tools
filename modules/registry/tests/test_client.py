def test_call_starts_daemon_and_lists(tmp_registry, monkeypatch):
    monkeypatch.setenv("AGENT_REGISTRY_DAEMON_PORT", "0")  # replaced below
    import socket
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    monkeypatch.setenv("AGENT_REGISTRY_DAEMON_PORT", str(port))
    monkeypatch.setenv("AGENT_REGISTRY_DAEMON_START_TIMEOUT", "5")
    from agent_registry.client import call, stop_if_ours
    try:
        result = call("ensure", {
            "agent_type": "cursor", "session_id": "s1", "directory": "/proj",
        })
        assert result["exit_code"] == 0
        listed = call("list", {})
        assert listed["data"]["active"][0]["session_id"] == "s1"
    finally:
        stop_if_ours()


def test_stranger_on_port_does_not_write_registry(tmp_registry, monkeypatch):
    import socket
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.listen(1)
    monkeypatch.setenv("AGENT_REGISTRY_DAEMON_PORT", str(port))
    monkeypatch.setenv("AGENT_REGISTRY_DAEMON_START_TIMEOUT", "0.2")
    from agent_registry.client import call
    try:
        result = call("list", {})
        assert result["exit_code"] == 3
        assert not tmp_registry.exists()
    finally:
        sock.close()


def test_malformed_health_reply_does_not_spawn(tmp_registry, monkeypatch):
    import socket
    import threading
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.listen(1)

    def serve_garbage():
        try:
            conn, _addr = sock.accept()
        except OSError:
            return
        try:
            conn.sendall(b"garbage\r\n\r\n")
        finally:
            conn.close()

    thread = threading.Thread(target=serve_garbage, daemon=True)
    thread.start()
    monkeypatch.setenv("AGENT_REGISTRY_DAEMON_PORT", str(port))
    monkeypatch.setenv("AGENT_REGISTRY_DAEMON_START_TIMEOUT", "0.2")
    from agent_registry.client import call
    try:
        result = call("list", {})
        assert result["exit_code"] == 3
        assert not tmp_registry.exists()
        assert not (tmp_registry.parent / "daemon.log").exists()
    finally:
        sock.close()
        thread.join(timeout=1)


def test_call_ignores_http_proxy(tmp_registry, monkeypatch):
    import socket
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    monkeypatch.setenv("AGENT_REGISTRY_DAEMON_PORT", str(port))
    monkeypatch.setenv("AGENT_REGISTRY_DAEMON_START_TIMEOUT", "5")
    from agent_registry.client import call, stop_if_ours
    try:
        result = call("ensure", {
            "agent_type": "cursor", "session_id": "s1", "directory": "/proj",
        })
        assert result["exit_code"] == 0
        listed = call("list", {})
        assert listed["exit_code"] == 0
        assert listed["data"]["active"][0]["session_id"] == "s1"
    finally:
        stop_if_ours()


def test_main_list_goes_through_the_daemon(tmp_registry, capsys, monkeypatch):
    import socket
    from agent_registry.cli import main
    from agent_registry.client import stop_if_ours
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    monkeypatch.setenv("AGENT_REGISTRY_DAEMON_PORT", str(port))
    monkeypatch.setenv("AGENT_REGISTRY_DAEMON_START_TIMEOUT", "5")
    try:
        assert main(["register", "--type", "cursor", "--session-id", "s1", "--directory", "/proj"]) == 0
        out = capsys.readouterr().out
        assert "registry_id" in out  # owner command
        assert main(["list"]) == 0
        text = capsys.readouterr().out
        assert "Active" in text and "registry_id" not in text
        pidfile = tmp_registry.parent / "daemon.pid"
        assert pidfile.exists()
    finally:
        stop_if_ours()


def test_dashboard_rejects_non_loopback_host_without_starting_daemon(
    tmp_registry, capsys, daemon_port
):
    from agent_registry.cli import main
    assert main(["dashboard", "--host", "0.0.0.0", "--no-open"]) == 1
    assert "dashboard host must be loopback" in capsys.readouterr().err
    assert not (tmp_registry.parent / "daemon.pid").exists()


def test_dashboard_uses_the_daemon_without_binding(tmp_registry, capsys, daemon_port):
    from agent_registry.cli import main
    assert main(["dashboard", "--no-open"]) == 0
    assert f"http://127.0.0.1:{daemon_port}/" in capsys.readouterr().out
    assert (tmp_registry.parent / "daemon.pid").exists()
