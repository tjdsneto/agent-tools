from pathlib import Path
import pytest
from agent_read.kokoro import KokoroError, kokoro_ready, synthesize


def test_kokoro_ready_false_for_missing(tmp_path):
    assert kokoro_ready(tmp_path) is False


def test_synthesize_missing_home_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("KOKORO_HOME", str(tmp_path / "missing"))
    with pytest.raises(KokoroError):
        synthesize("hello", voice="am_michael", speed=1.0, out_wav=tmp_path / "o.wav")
