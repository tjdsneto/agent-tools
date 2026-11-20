import os
import subprocess
import sys

import pytest


@pytest.fixture(autouse=True)
def forbid_real_launchctl(monkeypatch):
    """Unit tests must never bootstrap or bootout the user's LaunchAgent."""
    real_run = subprocess.run

    def _run(args, *a, **k):
        argv = list(args) if isinstance(args, (list, tuple)) else [args]
        if argv and (argv[0] == "launchctl" or "launchctl" in argv):
            raise AssertionError(f"real launchctl invoked: {argv}")
        return real_run(args, *a, **k)

    monkeypatch.setattr(subprocess, "run", _run)


def test_install_writes_plist(tmp_path):
    from agent_registry.client import install_launchd, plist_text

    agents = tmp_path / "LaunchAgents"
    program = "/usr/local/bin/agent-registry"
    path = install_launchd(agents, program, bootstrap=lambda *a: None)
    text = path.read_text()
    assert "com.tjdsneto.agent-registry" in text
    assert "<key>RunAtLoad</key>" in text
    assert "<key>KeepAlive</key>" in text
    assert program in text
    assert "daemon" in text and "run" in text
    assert path == agents / "com.tjdsneto.agent-registry.plist"
    assert plist_text(program) == text


def test_install_bootstraps_gui_domain(tmp_path):
    from agent_registry.client import install_launchd

    agents = tmp_path / "LaunchAgents"
    seen = []
    path = install_launchd(
        agents,
        "/usr/local/bin/agent-registry",
        bootstrap=lambda *args: seen.append(args),
    )
    assert seen == [(f"gui/{os.getuid()}", str(path))]


def test_plist_logs_under_registry_dir(tmp_registry):
    from agent_registry.client import plist_text

    program = "/usr/local/bin/agent-registry"
    text = plist_text(program)
    log = str(tmp_registry.parent / "daemon.log")
    assert f"<string>{program}</string>" in text
    assert "<string>daemon</string>" in text
    assert "<string>run</string>" in text
    assert text.count(f"<string>{log}</string>") == 2
    assert not tmp_registry.exists()


def test_install_rejects_non_darwin(monkeypatch, capsys, tmp_path):
    import sys

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("non-darwin install must not start a daemon")

    monkeypatch.setattr("agent_registry.client.ensure_daemon", _forbidden)
    monkeypatch.setattr("agent_registry.client._spawn", _forbidden)
    monkeypatch.setattr("agent_registry.daemon.run_foreground", _forbidden)
    monkeypatch.setattr("agent_registry.client.registry_path", _forbidden)
    from agent_registry.cli import main

    assert main(["daemon", "install"]) == 1
    assert capsys.readouterr().err == "agent-registry: daemon install is macOS only\n"
    assert list(tmp_path.rglob("*")) == []


def test_uninstall_missing_plist_skips_bootout(tmp_path):
    from agent_registry.client import uninstall_launchd

    agents = tmp_path / "LaunchAgents"
    agents.mkdir()

    def bootout(*_args):
        raise AssertionError("bootout is not required when the plist is absent")

    assert uninstall_launchd(agents, bootout) == 0


def test_uninstall_bootout_then_deletes(tmp_path):
    from agent_registry.client import uninstall_launchd

    agents = tmp_path / "LaunchAgents"
    agents.mkdir()
    plist = agents / "com.tjdsneto.agent-registry.plist"
    plist.write_text("placeholder", encoding="utf-8")
    seen = []

    def bootout(domain, path):
        assert plist.is_file()
        seen.append((domain, path))

    assert uninstall_launchd(agents, bootout) == 0
    assert seen == [(f"gui/{os.getuid()}", str(plist))]
    assert not plist.exists()


def test_start_bootstraps_when_plist_exists(tmp_path, monkeypatch):
    from agent_registry.client import start_daemon

    agents = tmp_path / "LaunchAgents"
    agents.mkdir()
    plist = agents / "com.tjdsneto.agent-registry.plist"
    plist.write_text("placeholder", encoding="utf-8")
    seen = []
    monkeypatch.setattr(
        "agent_registry.client._spawn",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("spawn")),
    )
    assert start_daemon(agents, bootstrap=lambda *args: seen.append(args)) == 0
    assert seen == [(f"gui/{os.getuid()}", str(plist))]


def test_start_without_plist_uses_existing_spawn(tmp_registry, tmp_path, monkeypatch):
    from agent_registry.client import start_daemon, stop_if_ours

    agents = tmp_path / "LaunchAgents"
    agents.mkdir()
    spawned = []
    monkeypatch.setattr("agent_registry.client._spawn", lambda port: spawned.append(port))
    try:
        code = start_daemon(
            agents,
            bootstrap=lambda *_a: (_ for _ in ()).throw(AssertionError("bootstrap")),
            port=0,
        )
    finally:
        stop_if_ours()
    assert code == 0
    assert spawned == [0]
    assert not (tmp_registry.parent / "daemon.pid").exists()


def test_stop_signals_then_bootout(tmp_registry, monkeypatch):
    import signal

    from agent_registry.client import stop_daemon

    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    agents = tmp_registry.parent / "LaunchAgents"
    plist = agents / "com.tjdsneto.agent-registry.plist"
    try:
        (tmp_registry.parent / "daemon.pid").write_text(str(proc.pid), encoding="utf-8")
        agents.mkdir()
        plist.write_text("placeholder", encoding="utf-8")
        order = []
        real_kill = os.kill

        def kill(pid, sig):
            if pid == proc.pid and sig == signal.SIGTERM:
                order.append("signal")
            return real_kill(pid, sig)

        monkeypatch.setattr(os, "kill", kill)

        def bootout(domain, path):
            assert order == ["signal"]
            order.append("bootout")
            assert domain == f"gui/{os.getuid()}"
            assert path == str(plist)

        assert stop_daemon(agents, bootout) == 0
        assert order == ["signal", "bootout"]
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)


def test_stop_dead_pid_does_not_signal(tmp_registry, monkeypatch):
    from agent_registry.client import stop_daemon

    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    proc.kill()
    proc.wait(timeout=5)
    (tmp_registry.parent / "daemon.pid").write_text(str(proc.pid), encoding="utf-8")
    agents = tmp_registry.parent / "LaunchAgents"
    agents.mkdir()
    plist = agents / "com.tjdsneto.agent-registry.plist"
    plist.write_text("placeholder", encoding="utf-8")
    signaled = []
    real_kill = os.kill

    def kill(pid, sig):
        if sig != 0:
            signaled.append((pid, sig))
        return real_kill(pid, sig)

    monkeypatch.setattr(os, "kill", kill)
    seen = []
    assert stop_daemon(agents, lambda *args: seen.append(args)) == 0
    assert signaled == []
    assert seen == [(f"gui/{os.getuid()}", str(plist))]
