from pathlib import Path
import pytest
from agent_read.player import PlayerError, run_player


def test_missing_ui_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_READ_UI", str(tmp_path / "nope"))
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")
    with pytest.raises(PlayerError):
        run_player(wav, title="t", background=False)


def test_foreground_reads_status(tmp_path, monkeypatch):
    ui = tmp_path / "fake-ui"
    # Working fake UI: parse --status PATH and write {"status":"ok"}
    ui.write_text(
        '''#!/bin/bash
status=""
while [ $# -gt 0 ]; do
  case "$1" in
    --status) status="$2"; shift 2;;
    *) shift;;
  esac
done
printf '%s' '{"status":"ok"}' > "$status"
'''
    )
    ui.chmod(0o755)
    monkeypatch.setenv("AGENT_READ_UI", str(ui))
    monkeypatch.setenv("AGENT_READ_CACHE", str(tmp_path / "cache"))
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")
    assert run_player(wav, title="Hi", background=False) == "ok"


def test_foreground_error_status_raises(tmp_path, monkeypatch):
    ui = tmp_path / "fake-ui"
    ui.write_text(
        '''#!/bin/bash
status=""
while [ $# -gt 0 ]; do
  case "$1" in
    --status) status="$2"; shift 2;;
    *) shift;;
  esac
done
printf '%s' '{"status":"error"}' > "$status"
exit 1
'''
    )
    ui.chmod(0o755)
    monkeypatch.setenv("AGENT_READ_UI", str(ui))
    monkeypatch.setenv("AGENT_READ_CACHE", str(tmp_path / "cache"))
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")
    with pytest.raises(PlayerError, match="status error"):
        run_player(wav, title="Hi", background=False)
