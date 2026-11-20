from datetime import datetime, timezone, timedelta
from agent_registry import archive, ops, store
from agent_registry.models import Session


def test_archive_path_sibling_of_registry(tmp_registry):
    assert archive.archive_path() == tmp_registry.with_name("archive.jsonl")


def test_append_and_read_event(tmp_registry):
    s = ops.register(agent_type="cursor", session_id="a", directory="/p")
    archive.append_session(s, reason="unregister")
    events = archive.read_events()
    assert len(events) == 1
    assert events[0]["reason"] == "unregister"
    assert events[0]["session"]["registry_id"] == s.registry_id
    assert "archived_at" in events[0]


def test_read_events_missing_file_empty(tmp_registry):
    assert archive.read_events() == []


def test_read_events_corrupt_returns_empty(tmp_registry):
    archive.archive_path().write_text("not-json\n", encoding="utf-8")
    assert archive.read_events() == []


def test_is_corrupt_and_read_events_result(tmp_registry):
    assert archive.is_corrupt() is False
    events, status = archive.read_events_result()
    assert events == []
    assert status == "missing"

    archive.archive_path().write_text("", encoding="utf-8")
    events, status = archive.read_events_result()
    assert events == []
    assert status in ("ok", "missing")
    assert archive.is_corrupt() is False

    archive.archive_path().write_text("not-json\n", encoding="utf-8")
    events, status = archive.read_events_result()
    assert events == []
    assert status == "corrupt"
    assert archive.is_corrupt() is True


def test_purge_corrupt_raises_and_preserves_file(tmp_registry):
    import pytest

    path = archive.archive_path()
    path.write_text("not-json\n", encoding="utf-8")
    with pytest.raises((archive.ArchiveCorruptError, archive.ArchiveIOError)):
        archive.purge_older_than(days=30, yes=True)
    assert path.read_text(encoding="utf-8") == "not-json\n"


def test_append_corrupt_raises(tmp_registry):
    import pytest

    path = archive.archive_path()
    path.write_text("not-json\n", encoding="utf-8")
    s = ops.register(agent_type="cursor", session_id="a", directory="/p")
    with pytest.raises((archive.ArchiveCorruptError, archive.ArchiveIOError)):
        archive.append_session(s, reason="unregister")
    assert path.read_text(encoding="utf-8") == "not-json\n"


def test_list_events_negative_limit_raises(tmp_registry):
    import pytest

    with pytest.raises(archive.ValidationError):
        archive.list_events(limit=-1)


def test_purge_older_than(tmp_registry):
    s = ops.register(agent_type="cursor", session_id="old", directory="/p")
    archive.append_session(s, reason="unregister")
    path = archive.archive_path()
    import json
    line = path.read_text(encoding="utf-8").strip()
    obj = json.loads(line)
    obj["archived_at"] = "2020-01-01T00:00:00+00:00"
    path.write_text(json.dumps(obj) + "\n", encoding="utf-8")
    s2 = ops.register(agent_type="cursor", session_id="new", directory="/p2")
    archive.append_session(s2, reason="prune")
    removed = archive.purge_older_than(days=30, yes=True)
    assert len(removed) == 1
    assert removed[0]["session"]["session_id"] == "old"
    kept = archive.read_events()
    assert [e["session"]["session_id"] for e in kept] == ["new"]


def test_purge_requires_yes(tmp_registry):
    import pytest
    with pytest.raises(archive.ValidationError):
        archive.purge_older_than(days=1, yes=False)
