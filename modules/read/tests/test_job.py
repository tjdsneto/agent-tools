import os
from pathlib import Path
from agent_read import job


def test_write_read_clear(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_READ_CACHE", str(tmp_path))
    p = job.write_job(12345, tmp_path / "a.wav", "T")
    assert p.is_file()
    data = job.read_job()
    assert data["pid"] == 12345
    assert data["title"] == "T"
    job.clear_job()
    assert job.read_job() is None


def test_stop_nothing_playing(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_READ_CACHE", str(tmp_path))
    assert job.stop_background() == "ok"


def test_stop_dead_pid_clears(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_READ_CACHE", str(tmp_path))
    wav = tmp_path / "x.wav"
    wav.write_bytes(b"RIFF")
    job.write_job(99999999, wav, None)  # almost certainly dead
    status = job.stop_background()
    assert status in ("ok", "stopped")
    assert job.read_job() is None
