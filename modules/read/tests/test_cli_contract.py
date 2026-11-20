import json
from pathlib import Path
import agent_read.cli as cli


def test_error_no_source(capsys):
    code = cli.main([])
    assert code == 1
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "error"


def test_stop_noop(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENT_READ_CACHE", str(tmp_path))
    code = cli.main(["stop"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "ok"


def test_foreground_happy(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENT_READ_CACHE", str(tmp_path))

    def fake_synth(text, *, voice, speed, out_wav, home=None):
        Path(out_wav).write_bytes(b"RIFF")

    def fake_player(wav, *, title, background):
        assert background is False
        return "ok"

    monkeypatch.setattr(cli, "synthesize", fake_synth)
    monkeypatch.setattr(cli, "run_player", fake_player)
    monkeypatch.setattr(cli, "kokoro_ready", lambda home=None: True)

    code = cli.main(["--text", "hello world", "--title", "T"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "ok"
    assert out["mode"] == "foreground"
    assert out["chars"] == len("hello world")
    assert out["title"] == "T"


def test_stopped_exit(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENT_READ_CACHE", str(tmp_path))

    def fake_synth(text, *, voice, speed, out_wav, home=None):
        Path(out_wav).write_bytes(b"RIFF")

    monkeypatch.setattr(cli, "synthesize", fake_synth)
    monkeypatch.setattr(cli, "run_player", lambda *a, **k: "stopped")
    monkeypatch.setattr(cli, "kokoro_ready", lambda home=None: True)

    code = cli.main(["--text", "x"])
    assert code == 130
    assert json.loads(capsys.readouterr().out)["status"] == "stopped"
