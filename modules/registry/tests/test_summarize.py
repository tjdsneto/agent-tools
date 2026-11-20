import json
from pathlib import Path

import pytest

from agent_registry import archive, lifecycle, ops, summarize
from agent_registry.models import Session


def test_clean_line_strips_prefix_and_quotes():
    assert summarize._clean_line('  Summary: "fix HPOS race"  ') == "fix HPOS race"
    assert len(summarize._clean_line("x" * 200)) == 120


def test_build_prompt_needs_signal():
    s = Session(
        registry_id="r", session_id="s", agent_type="claude", directory="/tmp",
        parent_session_id=None, status="idle", summary="", issue=None, pr=None,
        branch=None, goflow_timer_id=None,
        registered_at="t", last_ping="t", updated_at="t",
    )
    assert summarize.build_prompt(s) is None
    s.title = "auth-refactor"
    assert "auth-refactor" in (summarize.build_prompt(s) or "")


def test_read_transcript_excerpt(tmp_path):
    p = tmp_path / "t.jsonl"
    rows = [
        {"type": "user", "message": {"content": [{"type": "text", "text": "Fix the HPOS sync race"}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Looking at orders table"}]}},
        {"type": "user", "message": {"content": [{"type": "text", "text": "also check locks"}]}},
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    excerpt, first = summarize.read_transcript_excerpt(p)
    assert first and "HPOS" in first
    assert "USER" in excerpt and "ASSISTANT" in excerpt


def test_set_summary_if_empty_respects_policy(tmp_registry):
    s = ops.register(agent_type="claude", session_id="a", directory="/p", title="t")
    r1 = summarize.set_summary_if_empty(s.registry_id, "first line")
    assert r1["skipped"] is False
    assert r1["session"]["summary"] == "first line"
    r2 = summarize.set_summary_if_empty(s.registry_id, "second line")
    assert r2["skipped"] is True
    assert r2["reason"] == "summary_present"
    r3 = summarize.set_summary_if_empty(s.registry_id, "forced", force=True)
    assert r3["skipped"] is False
    assert r3["session"]["summary"] == "forced"


def test_summarize_sidecar_provider_off(tmp_registry, monkeypatch):
    lifecycle.ensure("claude", "s1", "/p", title="work")
    monkeypatch.setenv("AGENT_REGISTRY_SUMMARY_PROVIDER", "off")
    out = summarize.summarize_sidecar("claude", "s1")
    assert out["skipped"] is True
    assert out["reason"] == "provider_off"


def test_fill_with_mocked_ollama(tmp_registry, monkeypatch):
    lifecycle.ensure("claude", "s1", "/proj/lindris", title="hpos-race")
    monkeypatch.setenv("AGENT_REGISTRY_SUMMARY_PROVIDER", "ollama")
    monkeypatch.setattr(summarize, "ollama_available", lambda timeout=2.0: True)
    monkeypatch.setattr(
        summarize, "call_ollama",
        lambda prompt, timeout=None: ("Fix HPOS order sync race", "ollama:test"),
    )
    out = summarize.summarize_sidecar("claude", "s1")
    assert out["ok"] is True
    assert out["skipped"] is False
    assert out["summary"] == "Fix HPOS order sync race"
    # empty-only: second call skips
    out2 = summarize.summarize_sidecar("claude", "s1")
    assert out2["skipped"] is True


def test_unregister_applies_suggested_summary(tmp_registry, monkeypatch):
    s = ops.register(
        agent_type="claude", session_id="a", directory="/Users/x/projects/lindris",
        title="plugin-279",
    )
    monkeypatch.setattr(
        summarize, "prepare_for_archive",
        lambda sess, timeout=None: "Ship plugin 279 HPOS fix",
    )
    # unregister imports prepare via _suggest_summary_outside
    monkeypatch.setattr(
        ops, "_suggest_summary_outside",
        lambda rid: "Ship plugin 279 HPOS fix",
    )
    ops.unregister(s.registry_id)
    events = archive.list_events()
    assert events[0]["session"]["summary"] == "Ship plugin 279 HPOS fix"


def test_unregister_keeps_existing_summary(tmp_registry, monkeypatch):
    s = ops.register(agent_type="claude", session_id="a", directory="/p", title="t")
    ops.update(s.registry_id, summary="agent wrote this")
    monkeypatch.setattr(ops, "_suggest_summary_outside", lambda rid: "should not win")
    ops.unregister(s.registry_id)
    events = archive.list_events()
    assert events[0]["session"]["summary"] == "agent wrote this"
