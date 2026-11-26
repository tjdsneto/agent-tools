import json

import pytest

from agent_registry import topics


def _cache():
    return json.loads((topics.topics_dir() / topics.CACHE_NAME).read_text())


def test_an_unchanged_log_is_not_read_again(tmp_registry, monkeypatch):
    topics.set_intent("claude", "a", "A")
    topics.set_intent("claude", "b", "B")
    first = topics.cached_logs()
    assert [(t, s, [e["event"] for e in ev]) for t, s, ev in first] == [
        ("claude", "a", ["intent"]), ("claude", "b", ["intent"]),
    ]
    reads = []
    real = topics.read_events
    monkeypatch.setattr(topics, "read_events", lambda t, s: reads.append(s) or real(t, s))
    assert topics.cached_logs() == first
    assert reads == []
    topics.open_topic("claude", "b", "Plan")
    reads.clear()  # open_topic read the logs itself
    after = topics.cached_logs()
    assert reads == ["b"]
    assert [e["event"] for e in after[1][2]] == ["intent", "topic"]


def test_new_and_removed_logs_are_followed(tmp_registry):
    topics.set_intent("claude", "a", "A")
    topics.cached_logs()
    topics.set_intent("codex", "c", "C")
    topics.log_path("claude", "a").unlink()
    assert [(t, s) for t, s, _ in topics.cached_logs()] == [("codex", "c")]
    assert list(_cache()["logs"]) == ["codex/c.jsonl"]


@pytest.mark.parametrize("junk", [
    "not json",
    "[]",
    '{"version": 0, "logs": {}}',
    '{"version": 1, "logs": {"claude/a.jsonl": {"sig": "x", "events": []}}}',
    '{"version": 1, "logs": {"claude/a.jsonl": {"sig": [1, 2], "events": [1]}}}',
    '{"version": 1, "logs": {"claude/a.jsonl": {"sig": [1, 2], "events": []',  # truncated mid-write
])
def test_a_bad_cache_is_ignored_and_rebuilt(tmp_registry, junk):
    topics.set_intent("claude", "a", "A")
    (topics.topics_dir() / topics.CACHE_NAME).write_text(junk)
    assert [e["event"] for _, _, ev in topics.cached_logs() for e in ev] == ["intent"]
    assert _cache()["version"] == topics.CACHE_VERSION


def test_an_unwritable_topics_dir_still_reads(tmp_registry):
    topics.set_intent("claude", "a", "A")
    root = topics.topics_dir()
    root.chmod(0o555)
    try:
        assert [s for _, s, _ in topics.cached_logs()] == ["a"]
    finally:
        root.chmod(0o755)
    assert not (root / topics.CACHE_NAME).exists()


def test_the_per_row_readers_never_touch_the_cache(tmp_registry):
    """The daemon's list and board read one log per row (tjdsneto/agent-tools#9); they stay as they were."""
    topics.set_intent("claude", "a", "A")
    topics.current("claude", "a")
    topics.state("claude", "a")
    topics.tree()
    assert not (topics.topics_dir() / topics.CACHE_NAME).exists()
