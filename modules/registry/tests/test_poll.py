import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from agent_registry.cli import main
from agent_registry.client import changed_snapshots, poll_snapshot
from agent_registry.constants import EXIT_OK


def test_same_revision_yields_one_snapshot():
    fetches = {"n": 0}

    def fetch():
        fetches["n"] += 1
        return {"active": [], "stale": []}

    out = list(changed_snapshots([4, 4, 4], fetch))
    assert out == [{"rev": 4, "active": [], "stale": []}]
    assert fetches["n"] == 1


def test_a_later_revision_yields_the_new_list():
    lists = [
        {"active": [], "stale": []},
        {"active": [{"session_id": "s1"}], "stale": []},
    ]

    def fetch():
        return lists.pop(0)

    out = list(changed_snapshots([1, 2], fetch))
    assert [snap["rev"] for snap in out] == [1, 2]
    assert out[1]["active"][0]["session_id"] == "s1"


def test_an_unchanged_list_is_not_repeated():
    def fetch():
        return {"active": [{"session_id": "s1"}], "stale": []}

    out = list(changed_snapshots([1, 2], fetch))
    assert len(out) == 1


def test_poll_prints_the_current_list(tmp_registry, daemon_port, capsys):
    from agent_registry import ops

    ops.register(agent_type="cursor", session_id="s1", directory="/proj")
    assert main(["poll"]) == EXIT_OK
    line = json.loads(capsys.readouterr().out)
    assert line["rev"] >= 0
    assert any(row["session_id"] == "s1" for row in line["active"])
    assert "registry_id" not in json.dumps(line)


def test_poll_waits_until_the_registry_changes(tmp_registry, daemon_port):
    from agent_registry import ops

    first = poll_snapshot(daemon_port, since=None, timeout=1)
    found = {}

    def wait():
        found["snap"] = poll_snapshot(daemon_port, since=first["rev"], timeout=5)

    thread = threading.Thread(target=wait)
    thread.start()
    time.sleep(0.2)
    assert thread.is_alive()
    ops.register(agent_type="claude", session_id="s2", directory="/other")
    thread.join(5)
    assert not thread.is_alive()
    assert any(row["session_id"] == "s2" for row in found["snap"]["active"])
    assert found["snap"]["rev"] > first["rev"]


def test_poll_returns_the_same_list_when_the_wait_times_out(tmp_registry, daemon_port):
    first = poll_snapshot(daemon_port, since=None, timeout=1)
    started = time.monotonic()
    again = poll_snapshot(daemon_port, since=first["rev"], timeout=0.4)
    elapsed = time.monotonic() - started
    assert 0.3 <= elapsed < 2
    assert again["rev"] == first["rev"]
    assert again["active"] == first["active"]
    assert again["stale"] == first["stale"]


def test_follow_exits_when_the_reader_goes_away(tmp_registry, daemon_port):
    from agent_registry import ops

    env = os.environ.copy()
    src = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = src + ((":" + env["PYTHONPATH"]) if env.get("PYTHONPATH") else "")
    proc = subprocess.Popen(
        [sys.executable, "-m", "agent_registry.cli", "poll", "--follow"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    assert proc.stdout.readline()
    proc.stdout.close()
    ops.register(agent_type="cursor", session_id="gone", directory="/proj")
    code = proc.wait(timeout=5)
    err = proc.stderr.read().decode()
    assert code == EXIT_OK
    assert "Traceback" not in err


def test_follow_rejects_rev(tmp_registry, capsys):
    assert main(["poll", "--follow", "--rev", "1"]) != EXIT_OK
    assert "does not take --rev" in capsys.readouterr().err


def test_follow_prints_a_line_when_the_list_changes(tmp_registry, daemon_port, capsys, monkeypatch):
    monkeypatch.setattr(
        "agent_registry.client.iter_revisions",
        lambda port: iter([1, 1, 2]),
    )
    bodies = [
        {"active": [], "stale": []},
        {"active": [{"session_id": "s9"}], "stale": []},
    ]

    def call(op, params, port=None):
        return {"exit_code": 0, "data": bodies.pop(0), "error": None}

    monkeypatch.setattr("agent_registry.client.call", call)
    assert main(["poll", "--follow"]) == EXIT_OK
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [line["rev"] for line in lines] == [1, 2]
    assert lines[1]["active"][0]["session_id"] == "s9"


def test_cli_poll_prints_one_line_for_rev_and_timeout(tmp_registry, daemon_port, capsys, monkeypatch):
    seen = {}

    def fake(port, since, timeout):
        seen["port"] = port
        seen["since"] = since
        seen["timeout"] = timeout
        return {"rev": 7, "active": [], "stale": []}

    monkeypatch.setattr("agent_registry.client.poll_snapshot", fake)
    assert main(["poll", "--rev", "3", "--timeout", "9"]) == EXIT_OK
    assert seen["port"] == daemon_port
    assert seen["since"] == 3
    assert seen["timeout"] == 9
    assert json.loads(capsys.readouterr().out)["rev"] == 7
