import json
from agent_say import cli


def test_timeout_with_default(monkeypatch, tmp_path, capsys):
    spec = tmp_path / "s.json"
    spec.write_text(json.dumps({
        "title": "T",
        "options": [{"id": "done", "label": "Done"}, {"id": "cancel", "label": "Cancel"}],
    }))
    def boom(req, timeout_sec=None):
        raise TimeoutError()
    monkeypatch.setattr("agent_say.cli.run_ui", boom)
    code = cli.main(["--file", str(spec), "--timeout", "1", "--default", "cancel"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["status"] == "ok" and out["choice"] == "cancel"


def test_timeout_without_default(monkeypatch, tmp_path, capsys):
    spec = tmp_path / "s.json"
    spec.write_text(json.dumps({"title": "T", "options": [{"id": "ok", "label": "OK"}]}))
    def boom(req, timeout_sec=None):
        raise TimeoutError()
    monkeypatch.setattr("agent_say.cli.run_ui", boom)
    code = cli.main(["--file", str(spec), "--timeout", "1"])
    out = json.loads(capsys.readouterr().out)
    assert code == 2 and out["status"] == "timeout"


def test_keyboard_interrupt(monkeypatch, tmp_path, capsys):
    spec = tmp_path / "s.json"
    spec.write_text(json.dumps({
        "title": "T",
        "options": [{"id": "done", "label": "Done"}],
    }))

    def boom(req, timeout_sec=None):
        raise KeyboardInterrupt()

    monkeypatch.setattr("agent_say.cli.run_ui", boom)
    code = cli.main(["--file", str(spec), "--timeout", "30"])
    out = json.loads(capsys.readouterr().out)
    assert code == 130
    assert out["status"] == "cancelled"
    assert out["choice"] is None
    assert out["text"] is None
    assert "elapsed_ms" in out


def test_ok_choice(monkeypatch, tmp_path, capsys):
    spec = tmp_path / "s.json"
    spec.write_text(json.dumps({
        "title": "T",
        "options": [{"id": "done", "label": "Done"}],
    }))
    monkeypatch.setattr(
        "agent_say.cli.run_ui",
        lambda req, timeout_sec=None: {"status": "ok", "choice": "done", "text": None},
    )
    code = cli.main(["--file", str(spec), "--timeout", "30"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["status"] == "ok" and out["choice"] == "done"
    assert "elapsed_ms" in out
