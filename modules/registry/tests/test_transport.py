import json

import pytest

from agent_registry import lifecycle, ops
from agent_registry.cli import main
from agent_registry.constants import EXIT_NOT_FOUND, EXIT_OK, EXIT_USAGE
from agent_registry.format import format_list
from agent_registry.models import now_iso
from agent_registry import session_state
from agent_registry.transport import (
    SessionNotFoundError,
    UnsupportedTransportError,
    classify_delivery,
    notice_snippet,
    nudge_argv,
    read_dialer_notice,
    read_claude_address,
    read_codex_address,
    read_codex_rollout,
    read_cursor_address,
    resolve_session,
    resume_argv,
    wake,
)


@pytest.fixture
def inproc_daemon(tmp_registry, monkeypatch):
    """A real daemon on a thread of this process, so monkeypatched transport applies."""
    from agent_registry.daemon import serve_in_thread, stop_server

    httpd = serve_in_thread("127.0.0.1", 0)
    monkeypatch.setenv("AGENT_REGISTRY_DAEMON_PORT", str(httpd.server_address[1]))
    yield httpd
    stop_server(httpd)


HELD = (
    "[Cross-session delivery notice] Your message to another session was held "
    "by that session. NOT delivered: its Claude has not seen it."
)
EXPIRED = (
    "[Cross-session delivery notice] Your message to another session was not "
    "approved before expiry. Not delivered to that session's Claude."
)
REFUSED = (
    "[Cross-session delivery notice] Your message to another session was refused "
    "by that session. NOT delivered."
)


def _write_session(dirpath, pid, session_id, **extra):
    rec = {
        "pid": pid,
        "sessionId": session_id,
        "cwd": "/work",
        "messagingSocketPath": f"/tmp/cc-socks/{pid}.sock",
        "name": f"name-{pid}",
        "status": "idle",
    }
    rec.update(extra)
    (dirpath / f"{pid}.json").write_text(json.dumps(rec))


def test_ensure_records_address_separate_from_title(tmp_registry):
    out = lifecycle.ensure(
        "claude", "s1", "/p",
        title="topic title",
        peer_name="waker-t2",
        socket="/tmp/cc-socks/1.sock",
        pid=11,
        peer_status="idle",
    )
    sess = out["session"]
    assert sess["title"] == "topic title"
    assert sess["peer_name"] == "waker-t2"
    assert sess["socket"] == "/tmp/cc-socks/1.sock"
    assert sess["pid"] == 11
    assert sess["peer_status"] == "idle"
    assert sess["status"] == "idle"


def test_heartbeat_address_change_bypasses_throttle(tmp_registry, monkeypatch):
    monkeypatch.setenv("AGENT_REGISTRY_HEARTBEAT_SECONDS", "3600")
    e = lifecycle.ensure("claude", "s1", "/p", peer_name="old", pid=1)
    rid = e["session"]["registry_id"]
    session_state.write_state("claude", "s1", registry_id=rid, last_heartbeat_at=now_iso())
    same = lifecycle.heartbeat("claude", "s1", peer_name="old", pid=1)
    assert same["skipped"] is True
    changed = lifecycle.heartbeat(
        "claude", "s1", peer_name="new-name", socket="/tmp/s.sock", pid=9, peer_status="busy",
    )
    assert changed["skipped"] is False
    assert changed["session"]["peer_name"] == "new-name"
    assert changed["session"]["pid"] == 9
    assert changed["session"]["peer_status"] == "busy"


def test_list_shows_peer_name(tmp_registry):
    lifecycle.ensure("claude", "s1", "/p", peer_name="waker-t2")
    active, stale = ops.list_split()
    text = format_list(active, stale)
    assert "peer:waker-t2" in text
    assert active[0]["peer_name"] == "waker-t2"


def test_read_claude_address_matches_uuid(tmp_path):
    _write_session(tmp_path, 1, "other")
    _write_session(tmp_path, 2, "target-uuid", name="exact-name", status="busy")
    found = read_claude_address("target-uuid", tmp_path)
    assert found["peer_name"] == "exact-name"
    assert found["socket"] == "/tmp/cc-socks/2.sock"
    assert found["pid"] == 2
    assert found["peer_status"] == "busy"
    assert read_claude_address("missing", tmp_path) is None


def test_resolve_prefers_registry_row(tmp_registry, tmp_path):
    lifecycle.ensure(
        "claude", "uuid-1", "/proj",
        peer_name="from-row", socket="/row.sock", pid=4, peer_status="idle",
    )
    _write_session(tmp_path, 4, "uuid-1", name="from-file")
    view = resolve_session("uuid-1", sessions_dir=tmp_path, alive_check=lambda pid: pid == 4)
    assert view["peer_name"] == "from-row"
    assert view["alive"] is True
    assert view["source"] == "registry"


def test_resolve_falls_back_when_row_has_no_address(tmp_registry, tmp_path):
    lifecycle.ensure("claude", "uuid-1", "/proj")
    _write_session(tmp_path, 7, "uuid-1", name="harvested")
    view = resolve_session("uuid-1", sessions_dir=tmp_path, alive_check=lambda pid: False)
    assert view["peer_name"] == "harvested"
    assert view["pid"] == 7
    assert view["alive"] is False
    assert view["source"] == "sessions_file"
    assert view["directory"] == "/proj"


def test_resolve_missing_raises(tmp_registry, tmp_path):
    with pytest.raises(SessionNotFoundError):
        resolve_session("nope", sessions_dir=tmp_path)


def test_classify_notice_overrides_landed_token():
    assert classify_delivery("wake_result: landed\n" + HELD) == "held"
    assert classify_delivery("wake_result: landed\n" + EXPIRED) == "undelivered"
    assert classify_delivery(REFUSED) == "refused"


def test_classify_ignores_sendmessage_boilerplate():
    boilerplate = (
        "in that session's inbox, not yet read — a [Cross-session delivery notice] "
        "follows if that session holds it or refuses it"
    )
    assert notice_snippet(boilerplate) is None
    assert classify_delivery("wake_result: landed\n" + boilerplate) == "landed"


def test_notice_snippet_reads_held_text():
    text = 'noise "content":"' + HELD + ' more'
    snippet = notice_snippet(text)
    assert snippet is not None
    assert classify_delivery(snippet) == "held"


def test_read_dialer_notice_from_transcript(tmp_path):
    proj = tmp_path / "projects" / "-some-cwd"
    proj.mkdir(parents=True)
    sid = "11111111-1111-4111-8111-111111111111"
    (proj / f"{sid}.jsonl").write_text(
        json.dumps({"type": "queue-operation", "content": HELD}) + "\n"
    )
    assert classify_delivery(read_dialer_notice(sid, tmp_path / "projects")) == "held"
    assert read_dialer_notice("missing", tmp_path / "projects") is None


def test_wake_held_notice_in_transcript_overrides_submitted(tmp_registry, tmp_path):
    lifecycle.ensure("claude", "uuid-1", "/proj", peer_name="exact-name", pid=3)
    proj = tmp_path / "projects" / "-proj"
    proj.mkdir(parents=True)

    def runner(argv, cwd):
        sid = argv[argv.index("--session-id") + 1]
        (proj / f"{sid}.jsonl").write_text(json.dumps({"content": HELD}) + "\n")
        return "wake_result: submitted", 0

    out = wake(
        "uuid-1", "continue",
        alive_check=lambda pid: True,
        runner=runner,
        projects_dir=tmp_path / "projects",
    )
    assert out["mode"] == "nudge"
    assert out["result"] == "held"


def test_classify_requires_explicit_landed():
    assert classify_delivery("wake_result: landed") == "landed"
    assert classify_delivery("SendMessage success true") == "undelivered"
    assert classify_delivery("wake_result: unreachable") == "undelivered"
    assert classify_delivery("") == "undelivered"


def test_resume_argv_accepts_inbound_and_skips_prompts():
    argv = resume_argv("uuid-1", "continue", claude="claude")
    assert argv[:3] == ["claude", "-p", "--resume"]
    assert "uuid-1" in argv
    assert "--dangerously-skip-permissions" in argv
    settings = argv[argv.index("--settings") + 1]
    assert json.loads(settings)["crossSessionInbound"] == "accept"
    assert argv[-1] == "continue"


def test_nudge_argv_addresses_exact_name():
    argv = nudge_argv("exact-name", "keep going", claude="claude")
    assert "--allowedTools" in argv
    assert argv[argv.index("--allowedTools") + 1] == "ListAgents,SendMessage"
    assert "--dangerously-skip-permissions" in argv
    prompt = argv[argv.index("-p") + 1]
    assert "exact-name" in prompt
    assert "keep going" in prompt
    assert "wake_result: submitted" in prompt
    assert "--session-id" in argv


def test_wake_live_session_nudges(tmp_registry, tmp_path):
    lifecycle.ensure(
        "claude", "uuid-1", "/proj",
        peer_name="exact-name", socket="/s.sock", pid=3, peer_status="idle",
    )
    calls = []

    def runner(argv, cwd):
        calls.append((argv, cwd))
        return "wake_result: landed", 0

    out = wake(
        "uuid-1", "continue",
        sessions_dir=tmp_path, alive_check=lambda pid: True, runner=runner,
    )
    assert out["mode"] == "nudge"
    assert out["result"] == "landed"
    assert calls[0][1] == "/proj"
    assert "exact-name" in calls[0][0][calls[0][0].index("-p") + 1]


def test_wake_held_is_not_success(tmp_registry):
    lifecycle.ensure("claude", "uuid-1", "/proj", peer_name="exact-name", pid=3)

    def runner(argv, cwd):
        return "wake_result: landed\n" + HELD, 0

    out = wake("uuid-1", "continue", alive_check=lambda pid: True, runner=runner)
    assert out["result"] == "held"
    assert out["mode"] == "nudge"


def test_wake_dead_session_resumes(tmp_registry):
    lifecycle.ensure("claude", "uuid-1", "/proj", peer_name="exact-name", pid=3)
    calls = []

    def runner(argv, cwd):
        calls.append((argv, cwd))
        return "resumed", 0

    out = wake("uuid-1", "continue", alive_check=lambda pid: False, runner=runner)
    assert out["mode"] == "resume"
    assert out["result"] == "landed"
    assert calls[0][1] == "/proj"
    assert "--resume" in calls[0][0]
    assert "uuid-1" in calls[0][0]


def test_wake_live_without_name_does_not_resume(tmp_registry):
    lifecycle.ensure("claude", "uuid-1", "/proj", pid=3)
    calls = []

    def runner(argv, cwd):
        calls.append(argv)
        return "wake_result: landed", 0

    out = wake("uuid-1", "continue", alive_check=lambda pid: True, runner=runner)
    assert out["result"] == "undelivered"
    assert out["reason"] == "no_address"
    assert calls == []


def test_wake_unsupported_agent(tmp_registry):
    lifecycle.ensure("gemini", "chat-1", "/proj")
    with pytest.raises(UnsupportedTransportError):
        wake("chat-1", "continue", runner=lambda argv, cwd: ("", 0))


def _write_codex_index(path, *rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_read_codex_address_uses_thread_id_not_pid(tmp_path):
    index = tmp_path / "session_index.jsonl"
    _write_codex_index(
        index,
        {"id": "other", "thread_name": "nope", "updated_at": "t1"},
        {"id": "thread-1", "thread_name": "Move boxes", "updated_at": "t2"},
    )
    found = read_codex_address("thread-1", index)
    assert found["peer_name"] == "Move boxes"
    assert found["pid"] is None
    assert found["socket"] is None
    assert read_codex_address("missing", index) is None


def test_codex_rollout_resolves_when_index_misses(tmp_path):
    root = tmp_path / "sessions" / "2026" / "11" / "15"
    root.mkdir(parents=True)
    rec = {"type": "session_meta", "payload": {"session_id": "thread-9", "cwd": "/work"}}
    (root / "rollout-2026-11-15T00-00-00-thread-9.jsonl").write_text(json.dumps(rec) + "\n")
    index = tmp_path / "session_index.jsonl"
    index.write_text("")
    view = resolve_session(
        "thread-9",
        sessions_dir=tmp_path / "no-claude",
        codex_index=index,
        codex_sessions=tmp_path / "sessions",
        cursor_chats=tmp_path / "no-cursor",
        codex_live=lambda sid: False,
    )
    assert view["agent_type"] == "codex"
    assert view["directory"] == "/work"
    assert view["peer_name"] is None
    assert view["source"] == "rollout"
    assert view["alive"] is False
    assert read_codex_rollout("missing", tmp_path / "sessions") is None


def test_resolve_codex_row_without_claude_fallback(tmp_registry, tmp_path):
    lifecycle.ensure("codex", "thread-1", "/proj")
    index = tmp_path / "session_index.jsonl"
    _write_codex_index(index, {"id": "thread-1", "thread_name": "Move boxes"})
    _write_session(tmp_path, 9, "thread-1", name="not-claude")
    view = resolve_session(
        "thread-1",
        sessions_dir=tmp_path,
        codex_index=index,
        codex_live=lambda sid: sid == "thread-1",
    )
    assert view["agent_type"] == "codex"
    assert view["peer_name"] == "Move boxes"
    assert view["pid"] is None
    assert view["alive"] is True
    assert view["source"] == "session_index"


def test_codex_live_queue_omits_resume(tmp_registry):
    lifecycle.ensure("codex", "thread-1", "/proj", peer_name="Move boxes")
    calls = []

    def runner(argv, cwd):
        calls.append(argv)
        return "queued", 0

    out = wake(
        "thread-1", "continue",
        codex_live=lambda sid: True,
        runner=runner,
    )
    assert out["mode"] == "nudge"
    assert out["result"] == "landed"
    assert calls[0][:4] == ["codex", "queue", "--thread", "thread-1"]
    assert "--resume" not in calls[0]
    assert calls[0][calls[0].index("--message") + 1] == "continue"


def test_codex_dead_session_exec_resumes(tmp_registry):
    lifecycle.ensure("codex", "thread-1", "/proj", peer_name="Move boxes")
    calls = []

    def runner(argv, cwd):
        calls.append((argv, cwd))
        return "resumed", 0

    out = wake(
        "thread-1", "continue",
        codex_live=lambda sid: False,
        runner=runner,
    )
    assert out["mode"] == "resume"
    assert out["result"] == "landed"
    assert calls[0][0][:3] == ["codex", "exec", "resume"]
    assert "--skip-git-repo-check" in calls[0][0]
    assert "thread-1" in calls[0][0]
    assert calls[0][1] == "/proj"
    prompt = calls[0][0][-1]
    assert "wake_result: already_awake" in prompt
    assert "continue" in prompt
    assert "--output-last-message" in calls[0][0]


def test_codex_resume_already_awake_is_success(tmp_registry):
    lifecycle.ensure("codex", "thread-1", "/proj", peer_name="Move boxes")

    def runner(argv, cwd):
        from pathlib import Path
        reply = Path(argv[argv.index("--output-last-message") + 1])
        reply.write_text("wake_result: already_awake\n")
        # The event stream echoes the prompt. That must not count.
        return "prompt said wake_result: already_awake", 7

    out = wake("thread-1", "continue", codex_live=lambda sid: False, runner=runner)
    assert out["mode"] == "resume"
    assert out["result"] == "already_awake"


def test_codex_resume_without_token_uses_exit_code(tmp_registry):
    lifecycle.ensure("codex", "thread-1", "/proj", peer_name="Move boxes")

    def runner(argv, cwd):
        from pathlib import Path
        reply = Path(argv[argv.index("--output-last-message") + 1])
        reply.write_text("did the work\n")
        return "prompt said wake_result: already_awake", 0

    out = wake("thread-1", "continue", codex_live=lambda sid: False, runner=runner)
    assert out["result"] == "landed"


def test_cli_codex_already_awake_exits_ok(
    tmp_registry, tmp_path, capsys, monkeypatch, inproc_daemon
):
    assert main([
        "ensure", "--type", "codex", "--session-id", "thread-1", "--directory", "/proj",
    ]) == EXIT_OK
    capsys.readouterr()

    def runner(argv, cwd):
        from pathlib import Path
        Path(argv[argv.index("--output-last-message") + 1]).write_text(
            "wake_result: already_awake\n"
        )
        return "", 0

    monkeypatch.setattr("agent_registry.transport.run_claude", runner)
    monkeypatch.setattr("agent_registry.transport.codex_thread_live", lambda sid: False)
    msg = tmp_path / "msg.txt"
    msg.write_text("continue please")
    assert main(["wake", "thread-1", "--message", str(msg)]) == EXIT_OK
    woke = json.loads(capsys.readouterr().out)
    assert woke["result"] == "already_awake"


def _write_cursor_meta(chats, chat_id, cwd, updated=1):
    d = chats / "ws" / chat_id
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({
        "cwd": cwd, "updatedAtMs": updated, "createdAtMs": 1,
    }))


def test_read_cursor_address_by_chat_id(tmp_path):
    _write_cursor_meta(tmp_path, "chat-1", "/work/a", updated=10)
    found = read_cursor_address("chat-1", tmp_path)
    assert found["cwd"] == "/work/a"
    assert found["pid"] is None
    assert found["socket"] is None
    assert read_cursor_address("missing", tmp_path) is None


def test_cursor_wake_always_resumes(tmp_registry, tmp_path):
    lifecycle.ensure("cursor", "chat-1", "/proj")
    _write_cursor_meta(tmp_path, "chat-1", "/proj")
    view = resolve_session("chat-1", cursor_chats=tmp_path, codex_live=lambda sid: True)
    assert view["agent_type"] == "cursor"
    assert view["alive"] is False
    assert view["directory"] == "/proj"
    calls = []

    def runner(argv, cwd):
        calls.append((argv, cwd))
        return "ok", 0

    out = wake("chat-1", "continue", cursor_chats=tmp_path, runner=runner)
    assert out["mode"] == "resume"
    assert out["result"] == "landed"
    assert calls[0][0][:5] == ["cursor-agent", "--resume", "chat-1", "--force", "-p"]
    assert "--resume" in calls[0][0]
    assert calls[0][1] == "/proj"


def test_cli_resolve_and_wake(tmp_registry, tmp_path, capsys, monkeypatch, inproc_daemon):
    assert main([
        "ensure", "--type", "claude", "--session-id", "uuid-1", "--directory", "/proj",
        "--peer-name", "exact-name", "--socket", "/s.sock", "--pid", "3",
        "--peer-status", "busy",
    ]) == EXIT_OK
    capsys.readouterr()

    monkeypatch.setattr("agent_registry.transport.pid_alive", lambda pid: True)
    monkeypatch.setattr(
        "agent_registry.transport.run_claude",
        lambda argv, cwd: ("wake_result: landed", 0),
    )
    assert main(["resolve", "uuid-1"]) == EXIT_OK
    view = json.loads(capsys.readouterr().out)
    assert view["peer_name"] == "exact-name"
    assert view["alive"] is True

    msg = tmp_path / "msg.txt"
    msg.write_text("continue please")
    assert main(["wake", "uuid-1", "--message", str(msg)]) == EXIT_OK
    woke = json.loads(capsys.readouterr().out)
    assert woke["result"] == "landed"
    assert woke["mode"] == "nudge"

    monkeypatch.setattr(
        "agent_registry.transport.run_claude",
        lambda argv, cwd: (HELD, 0),
    )
    assert main(["wake", "uuid-1", "--message", str(msg)]) == EXIT_USAGE
    held = json.loads(capsys.readouterr().out)
    assert held["result"] == "held"

    assert main(["resolve", "missing"]) == EXIT_NOT_FOUND
