from datetime import datetime
from zoneinfo import ZoneInfo

from agent_inbox.notify import card, due, quiet

LOCAL = ZoneInfo("America/Sao_Paulo")


def test_choice_card_is_numbered():
    text = card({
        "id": "ib-7k3q", "title": "Which split?", "priority": "normal",
        "asker": {"project": "/tmp/agent-tools"},
        "control": {"type": "choice", "options": [{"id": "a", "label": "Tauri"}, {"id": "b", "label": "Go", "recommended": True}]},
    }, ui="https://mbp.tailnet/e/ib-7k3q")
    assert "Which split?" in text
    assert "1. Tauri" in text and "2. Go (recommended)" in text
    assert "https://mbp.tailnet/e/ib-7k3q" in text
    assert "reply 1" in text


def test_approve_card_tells_him_the_words():
    text = card({
        "id": "ib-7k3q", "title": "Ship it?", "priority": "urgent",
        "asker": {"project": None},
        "control": {"type": "approve"},
    }, ui="https://x/e/ib-7k3q")
    assert 'reply "approve"' in text and "revise: reason" in text


def test_quiet_hours():
    assert quiet(datetime(2026, 11, 23, 22, 0, tzinfo=LOCAL))
    assert quiet(datetime(2026, 11, 23, 7, 59, tzinfo=LOCAL))
    assert not quiet(datetime(2026, 11, 23, 8, 0, tzinfo=LOCAL))
    assert not quiet(datetime(2026, 11, 23, 21, 59, tzinfo=LOCAL))


def test_due_batches_normal_and_always_sends_urgent():
    entries = [
        {"id": "a", "priority": "normal", "created_at": "t"},
        {"id": "b", "priority": "low", "created_at": "t"},
        {"id": "c", "priority": "urgent", "created_at": "t"},
    ]
    night = datetime(2026, 11, 23, 23, 0, tzinfo=LOCAL)
    assert [e["id"] for e in due(entries, now=night, last_normal_at=None)] == ["c"]
    day = datetime(2026, 11, 23, 12, 0, tzinfo=LOCAL)
    recent = datetime(2026, 11, 23, 11, 50, tzinfo=LOCAL)
    assert [e["id"] for e in due(entries, now=day, last_normal_at=recent)] == ["c"]
    assert [e["id"] for e in due(entries, now=day, last_normal_at=None)] == ["c", "a"]
