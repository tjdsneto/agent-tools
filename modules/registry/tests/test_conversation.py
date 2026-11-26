from pathlib import Path

from agent_registry import conversation


def test_core_text_reads_the_env_override(tmp_path, monkeypatch):
    core = tmp_path / "core.md"
    core.write_text("\n  Be brief.\n\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_REGISTRY_CONVERSATION_CORE", str(core))
    assert conversation.core_text() == "Be brief."


def test_core_text_is_none_for_a_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_REGISTRY_CONVERSATION_CORE", str(tmp_path / "nope.md"))
    assert conversation.core_text() is None


def test_core_text_is_none_for_invalid_utf8(tmp_path, monkeypatch):
    core = tmp_path / "core.md"
    core.write_bytes(b"\xff\xfe\x00bad")
    monkeypatch.setenv("AGENT_REGISTRY_CONVERSATION_CORE", str(core))
    assert conversation.core_text() is None


def test_default_path_is_the_skill_core(monkeypatch):
    monkeypatch.delenv("AGENT_REGISTRY_CONVERSATION_CORE", raising=False)
    path = conversation.default_path()
    assert path.parts[-3:] == ("skills", "conversation", "CORE.md")
    assert path.exists()
    assert conversation.core_text() == path.read_text(encoding="utf-8").strip()
