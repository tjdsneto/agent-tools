import agent_say.speak as speak_mod
from agent_say.speak import detect_lang, resolve_voice, speak_best_effort


def test_detect_lang_portuguese():
    assert detect_lang("Olá. Preciso da sua atenção.") == "pt-br"
    assert detect_lang("Tudo bem? Nao precisa responder.") == "pt-br"
    assert detect_lang("Por favor, confirme o deploy.") == "pt-br"


def test_detect_lang_english():
    assert detect_lang("Heads up. Review the diff.") == "en-us"
    assert detect_lang("Are you there?") == "en-us"


def test_detect_lang_env_override(monkeypatch):
    monkeypatch.setenv("AGENT_SAY_LANG", "pt-br")
    assert detect_lang("Hello world") == "pt-br"
    monkeypatch.setenv("AGENT_SAY_LANG", "en-us")
    assert detect_lang("Olá amigo") == "en-us"


def test_resolve_voice_defaults(monkeypatch):
    monkeypatch.delenv("AGENT_SAY_VOICE", raising=False)
    monkeypatch.delenv("AGENT_SAY_VOICE_PT", raising=False)
    assert resolve_voice("en-us") == "am_michael"
    assert resolve_voice("pt-br") == "pf_dora"


def test_resolve_voice_env(monkeypatch):
    monkeypatch.setenv("AGENT_SAY_VOICE", "am_adam")
    monkeypatch.setenv("AGENT_SAY_VOICE_PT", "pm_alex")
    assert resolve_voice("en-us") == "am_adam"
    assert resolve_voice("pt-br") == "pm_alex"


def test_speak_missing_home_ok(monkeypatch, tmp_path):
    monkeypatch.setenv("KOKORO_HOME", str(tmp_path / "missing"))
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs.get("timeout")))

        class R:
            returncode = 0

        return R()

    monkeypatch.setattr(speak_mod.subprocess, "run", fake_run)
    speak_best_effort("Hi", "There")  # must not raise
    assert calls == [(["say", "Hi. There"], 60)]


def test_speak_portuguese_falls_back_to_luciana(monkeypatch, tmp_path):
    monkeypatch.setenv("KOKORO_HOME", str(tmp_path / "missing"))
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)

        class R:
            returncode = 0

        return R()

    monkeypatch.setattr(speak_mod.subprocess, "run", fake_run)
    speak_best_effort("Olá", "Preciso da sua atenção.")
    assert calls == [["say", "-v", "Luciana", "Olá. Preciso da sua atenção."]]


def test_speak_kokoro_gets_pt_lang_and_voice(monkeypatch, tmp_path):
    home = tmp_path / "kokoro"
    (home / "venv" / "bin").mkdir(parents=True)
    py = home / "venv" / "bin" / "python"
    py.write_text("#!/bin/sh\n")
    py.chmod(0o755)
    (home / "kokoro-v1.0.onnx").write_bytes(b"x")
    (home / "voices-v1.0.bin").write_bytes(b"x")
    monkeypatch.setenv("KOKORO_HOME", str(home))

    envs = []

    def fake_run(cmd, **kwargs):
        if kwargs.get("env"):
            envs.append(kwargs["env"])

        class R:
            returncode = 0

        return R()

    monkeypatch.setattr(speak_mod.subprocess, "run", fake_run)
    speak_best_effort("Olá", "Tudo bem?")
    assert envs, "expected Kokoro subprocess"
    assert envs[0]["KOKORO_LANG"] == "pt-br"
    assert envs[0]["KOKORO_VOICE"] == "pf_dora"


def test_speak_empty_no_subprocess(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs.get("timeout")))

        class R:
            returncode = 0

        return R()

    monkeypatch.setattr(speak_mod.subprocess, "run", fake_run)
    speak_best_effort("", "")
    assert calls == []
