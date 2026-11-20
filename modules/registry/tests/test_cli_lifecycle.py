import json
from agent_registry.cli import main
from agent_registry.constants import EXIT_NOT_FOUND, EXIT_OK


def test_cli_ensure_heartbeat_end(tmp_registry, capsys, daemon_port):
    assert main([
        "ensure", "--type", "claude", "--session-id", "s1", "--directory", "/p"
    ]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "registry_id" in out["session"]

    assert main(["heartbeat", "--type", "claude", "--session-id", "s1"]) == 0
    hb = json.loads(capsys.readouterr().out)
    assert "skipped" in hb

    assert main(["end", "--type", "claude", "--session-id", "s1"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_cli_self_success(tmp_registry, capsys, daemon_port):
    assert main([
        "ensure", "--type", "cursor", "--session-id", "c1", "--directory", "/p"
    ]) == EXIT_OK
    ensured = json.loads(capsys.readouterr().out)
    rid = ensured["session"]["registry_id"]

    assert main(["self", "--type", "cursor", "--session-id", "c1"]) == EXIT_OK
    view = json.loads(capsys.readouterr().out)
    assert view["registry_id"] == rid
    assert view["session_id"] == "c1"


def test_cli_self_not_found(tmp_registry, capsys, daemon_port):
    assert main(["self", "--type", "claude", "--session-id", "gone"]) == EXIT_NOT_FOUND
    err = capsys.readouterr().err
    assert "not found" in err.lower()
