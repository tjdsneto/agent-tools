import pytest

@pytest.fixture(autouse=True)
def fast_wake_settle(monkeypatch):
    """Don't poll the real dialer transcript during unit tests."""
    monkeypatch.setenv("AGENT_REGISTRY_WAKE_SETTLE_SECONDS", "0")

@pytest.fixture
def tmp_registry(tmp_path, monkeypatch):
    path = tmp_path / "registry.json"
    monkeypatch.setenv("AGENT_REGISTRY_PATH", str(path))
    return path


@pytest.fixture
def daemon_port(tmp_registry, monkeypatch):
    import socket
    from agent_registry.client import stop_if_ours
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    monkeypatch.setenv("AGENT_REGISTRY_DAEMON_PORT", str(port))
    monkeypatch.setenv("AGENT_REGISTRY_DAEMON_START_TIMEOUT", "5")
    yield port
    stop_if_ours()


def pytest_ignore_collect(collection_path, config):
    """Collect tests/blackbox only when that path was requested."""
    parts = getattr(collection_path, "parts", ())
    if "blackbox" not in parts:
        return False
    return not any("blackbox" in str(arg) for arg in config.args)
