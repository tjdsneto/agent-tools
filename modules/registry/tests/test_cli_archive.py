import json
from agent_registry.cli import main
from agent_registry import ops, archive
from agent_registry.constants import EXIT_NOT_FOUND


def test_archive_list_json(tmp_registry, capsys, daemon_port):
    s = ops.register(agent_type="cursor", session_id="a", directory="/p")
    ops.unregister(s.registry_id)
    assert main(["archive", "list", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["events"][0]["reason"] == "unregister"
    assert "registry_id" not in data["events"][0]["session"]


def test_archive_show_and_full(tmp_registry, capsys, daemon_port):
    s = ops.register(agent_type="cursor", session_id="a", directory="/p")
    ops.unregister(s.registry_id)
    assert main(["archive", "show", "a"]) == 0
    pub = json.loads(capsys.readouterr().out)
    assert "registry_id" not in pub["session"]
    assert main(["archive", "show", "a", "--full"]) == 0
    full = json.loads(capsys.readouterr().out)
    assert full["session"]["registry_id"] == s.registry_id


def test_archive_show_missing(tmp_registry, capsys, daemon_port):
    assert main(["archive", "show", "nope"]) == EXIT_NOT_FOUND


def test_archive_purge_yes(tmp_registry, capsys, daemon_port):
    s = ops.register(agent_type="cursor", session_id="a", directory="/p")
    archive.append_session(s, reason="unregister")
    import json as J
    p = archive.archive_path()
    obj = J.loads(p.read_text().strip())
    obj["archived_at"] = "2020-01-01T00:00:00+00:00"
    p.write_text(J.dumps(obj) + "\n")
    assert main(["archive", "purge", "--older-than", "30d", "--yes"]) == 0
    assert archive.read_events() == []


def test_doctor_ok(tmp_registry, capsys, daemon_port):
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "registry" in out.lower()
    assert "archive" in out.lower()


def test_status_counts(tmp_registry, capsys, daemon_port):
    s = ops.register(agent_type="cursor", session_id="a", directory="/p")
    ops.unregister(s.registry_id)
    assert main(["status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["archived"] == 1
    assert data["active"] + data["stale"] == 0
