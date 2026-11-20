import json
from agent_say import cli
from agent_say.read import load_text, ReadError
import pytest


def test_load_text_from_flag():
    assert load_text(text="  hi  ", file=None, stdin="") == "hi"


def test_load_text_rejects_empty():
    with pytest.raises(ReadError, match="empty"):
        load_text(text="   ", file=None, stdin="")


def test_load_text_exactly_one_source():
    with pytest.raises(ReadError, match="exactly one"):
        load_text(text="a", file="/tmp/x", stdin="")
    with pytest.raises(ReadError, match="exactly one"):
        load_text(text=None, file=None, stdin="")


def test_load_text_stdin():
    assert load_text(text=None, file=None, stdin="  hello\n") == "hello"


def test_read_missing_kokoro(monkeypatch, capsys):
    monkeypatch.setenv("KOKORO_HOME", "/tmp/missing-kokoro-agent-say")

    def boom(*a, **k):
        raise RuntimeError("Kokoro not ready")

    monkeypatch.setattr("agent_say.read.speak_kokoro_required", boom)
    code = cli.main(["read", "--text", "Hello"])
    out = json.loads(capsys.readouterr().out)
    assert code == 1
    assert out["status"] == "error"
    assert out["mode"] == "foreground"


def test_read_ok(monkeypatch, capsys):
    monkeypatch.setattr(
        "agent_say.read.speak_kokoro_required",
        lambda text, voice=None, speed=1.0: "pf_dora",
    )
    code = cli.main(["read", "--text", "Olá mundo", "--title", "T"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["status"] == "ok"
    assert out["voice"] == "pf_dora"
    assert out["chars"] == len("Olá mundo")
    assert out["title"] == "T"
