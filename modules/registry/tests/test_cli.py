import json
from agent_registry.cli import main
from agent_registry.constants import EXIT_OK, EXIT_USAGE, EXIT_NOT_FOUND

def test_register_list_ping_update_unregister(tmp_registry, capsys, daemon_port):
    code = main([
        "register", "--type", "cursor", "--session-id", "s1", "--directory", "/proj",
    ])
    assert code == EXIT_OK
    rid = json.loads(capsys.readouterr().out)["registry_id"]

    assert main(["list", "--json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert all("registry_id" not in s for s in payload["active"] + payload["stale"])

    assert main(["ping", rid]) == EXIT_OK
    capsys.readouterr()
    assert main(["update", rid, "--status", "working", "--summary", "doing stuff"]) == EXIT_OK
    capsys.readouterr()
    assert main(["update", rid]) == EXIT_USAGE
    capsys.readouterr()
    assert main(["unregister", rid]) == EXIT_OK
    capsys.readouterr()
    assert main(["ping", rid]) == EXIT_NOT_FOUND

def test_list_human_has_sections(tmp_registry, capsys, daemon_port):
    main(["register", "--type", "claude", "--session-id", "x", "--directory", "/d"])
    capsys.readouterr()
    assert main(["list"]) == EXIT_OK
    text = capsys.readouterr().out
    assert "Active" in text and "Stale" in text
    assert "registry_id" not in text
