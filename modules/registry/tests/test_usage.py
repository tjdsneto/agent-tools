import json
import urllib.request

from agent_registry.daemon import serve_in_thread, stop_server


def test_ps_sample_omits_dead_pid(monkeypatch):
    from agent_registry.usage import sample_process
    monkeypatch.setattr("agent_registry.usage._ps", lambda pid: None)
    assert sample_process(999999) is None

def test_ps_sample_parses(monkeypatch):
    from agent_registry.usage import sample_process
    monkeypatch.setattr("agent_registry.usage._ps", lambda pid: "12.5 4096\n")
    assert sample_process(4) == {"cpu_percent": 12.5, "memory_bytes": 4096 * 1024}

def test_claude_tokens_sum_usage(tmp_path, monkeypatch):
    projects = tmp_path / "projects" / "abc"
    projects.mkdir(parents=True)
    sid = "sess-1"
    (projects / f"{sid}.jsonl").write_text(
        json.dumps({"message": {"usage": {
            "input_tokens": 10, "output_tokens": 2,
            "cache_read_input_tokens": 1, "cache_creation_input_tokens": 4,
        }}}) + "\n" +
        json.dumps({"message": {"usage": {
            "input_tokens": 3, "output_tokens": 5,
            "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
        }}}) + "\n",
        encoding="utf-8",
    )
    from agent_registry.usage import claude_tokens
    assert claude_tokens(sid, projects_root=tmp_path / "projects") == {
        "input_tokens": 13,
        "output_tokens": 7,
        "cache_read_input_tokens": 1,
        "cache_creation_input_tokens": 4,
    }

def test_codex_tokens_use_total(tmp_path):
    root = tmp_path / "sessions" / "2026" / "11" / "17"
    root.mkdir(parents=True)
    sid = "thread-1"
    line = json.dumps({"payload": {"info": {"total_token_usage": {
        "input_tokens": 8, "output_tokens": 1,
        "cached_input_tokens": 2, "cache_write_input_tokens": 0,
        "total_tokens": 9,
    }}}})
    (root / f"rollout-x-{sid}.jsonl").write_text(line + "\n", encoding="utf-8")
    from agent_registry.usage import codex_tokens
    assert codex_tokens(sid, sessions_root=tmp_path / "sessions")["total_tokens"] == 9

def test_codex_tokens_reject_shorter_session_id(tmp_path):
    root = tmp_path / "sessions" / "2026" / "11" / "17"
    root.mkdir(parents=True)
    full_id = "01a1e66c-34e0-74a2-8006-d48332cc1ebc"
    real_name = f"rollout-2026-11-16T19-13-33-{full_id}.jsonl"
    (root / real_name).write_text(
        json.dumps({"payload": {"info": {"total_token_usage": {"total_tokens": 4}}}}) + "\n",
        encoding="utf-8",
    )
    (root / "rollout-x-thread-1.jsonl").write_text(
        json.dumps({"payload": {"info": {"total_token_usage": {"total_tokens": 9}}}}) + "\n",
        encoding="utf-8",
    )
    from agent_registry.usage import codex_tokens
    sessions = tmp_path / "sessions"
    assert codex_tokens("1", sessions_root=sessions) is None
    assert codex_tokens("34e0-74a2-8006-d48332cc1ebc", sessions_root=sessions) is None
    assert codex_tokens("thread-1", sessions_root=sessions)["total_tokens"] == 9
    assert codex_tokens(full_id, sessions_root=sessions)["total_tokens"] == 4

def test_codex_tokens_drop_extra_keys(tmp_path):
    root = tmp_path / "sessions" / "2026" / "11" / "17"
    root.mkdir(parents=True)
    line = json.dumps({"payload": {"info": {"total_token_usage": {
        "input_tokens": 8,
        "output_tokens": "nope",
        "cached_input_tokens": 2,
        "total_tokens": 9,
        "extra": "drop-me",
        "model": "gpt",
    }}}})
    (root / "rollout-x-thread-1.jsonl").write_text(line + "\n", encoding="utf-8")
    from agent_registry.usage import codex_tokens
    assert codex_tokens("thread-1", sessions_root=tmp_path / "sessions") == {
        "input_tokens": 8,
        "cached_input_tokens": 2,
        "total_tokens": 9,
    }

def test_codex_tokens_scan_earlier_chunks(tmp_path, monkeypatch):
    def _no_slurp(self, *args, **kwargs):
        raise AssertionError("full file read")

    monkeypatch.setattr("pathlib.Path.read_bytes", _no_slurp)
    monkeypatch.setattr("agent_registry.usage._CODEX_READ_CHUNK", 48)
    root = tmp_path / "sessions" / "2026" / "11" / "17"
    root.mkdir(parents=True)
    line = json.dumps({"payload": {"info": {"total_token_usage": {"total_tokens": 9}}}})
    (root / "rollout-x-early.jsonl").write_text(
        line + "\n" + ("not-json\n" * 20),
        encoding="utf-8",
    )
    from agent_registry.usage import codex_tokens
    assert codex_tokens("early", sessions_root=tmp_path / "sessions")["total_tokens"] == 9

def test_live_token_error_omits_one_row(tmp_registry, monkeypatch):
    from agent_registry import ops
    ops.register(agent_type="codex", session_id="good", directory="/p")
    ops.register(agent_type="codex", session_id="bad", directory="/p")

    def flaky(session_id, sessions_root=None):
        if session_id == "bad":
            raise ValueError("bad token line")
        return {"total_tokens": 9}

    monkeypatch.setattr("agent_registry.usage.codex_tokens", flaky)
    httpd = serve_in_thread("127.0.0.1", 0)
    try:
        live = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{httpd.server_address[1]}/api/live"
        ).read())
        rows = {row["session_id"]: row for row in live["active"]}
        assert rows["good"]["tokens"]["total_tokens"] == 9
        assert "tokens" not in rows["bad"]
    finally:
        stop_server(httpd)

def test_live_attaches_usage_and_does_not_write_registry(tmp_registry, monkeypatch):
    from agent_registry import ops

    # Isolate from the real Cursor machine: open-chat discovery and title sync
    # may persist rows; this test only checks that attach_usage is read-only.
    monkeypatch.setattr("agent_registry.usage.open_cursor_chats", lambda: {})
    monkeypatch.setattr(
        "agent_registry.usage.cursor_composer_names",
        lambda session_ids, db_path=None: {},
    )
    ops.register(agent_type="claude", session_id="s1", directory="/p", pid=1)
    before = tmp_registry.read_text()
    httpd = serve_in_thread("127.0.0.1", 0)
    try:
        live = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{httpd.server_address[1]}/api/live"
        ).read())
        row = live["active"][0]
        assert "registry_id" not in row
        assert "cpu_percent" not in row or isinstance(row["cpu_percent"], float)
        assert tmp_registry.read_text() == before
    finally:
        stop_server(httpd)


def test_open_cursor_ids_are_the_selected_chats_of_open_windows(tmp_path, monkeypatch):
    import sqlite3

    from agent_registry.usage import open_cursor_session_ids

    monkeypatch.setattr(
        "agent_registry.usage.cursor_window_projects", lambda: {"demo"}
    )
    root = tmp_path / "workspaceStorage"
    open_ws = root / "aaa"
    open_ws.mkdir(parents=True)
    (open_ws / "workspace.json").write_text(
        json.dumps({"folder": "file:///Users/x/projects/demo"}),
        encoding="utf-8",
    )
    closed = root / "bbb"
    closed.mkdir()
    (closed / "workspace.json").write_text(
        json.dumps({"folder": "file:///Users/x/projects/other"}),
        encoding="utf-8",
    )

    def write_db(folder, ids):
        con = sqlite3.connect(folder / "state.vscdb")
        con.execute("CREATE TABLE ItemTable (key TEXT, value TEXT)")
        con.execute(
            "INSERT INTO ItemTable VALUES (?, ?)",
            ("composer.composerData", json.dumps({"selectedComposerIds": ids})),
        )
        con.commit()
        con.close()

    write_db(open_ws, ["chat-open"])
    write_db(closed, ["chat-closed"])
    assert open_cursor_session_ids(root) == {"chat-open"}


def test_open_cursor_chats_match_multi_root_code_workspace(tmp_path, monkeypatch):
    """Cursor titles multi-root windows as '<name> (Workspace)' and stores a
    workspace.json `workspace` URI to the .code-workspace file — not `folder`.
    """
    import sqlite3

    from agent_registry.usage import open_cursor_chats

    monkeypatch.setattr(
        "agent_registry.usage.cursor_window_projects",
        lambda: {"obra-manager"},  # normalized; raw title ends with " (Workspace)"
    )
    root = tmp_path / "workspaceStorage"
    ws = root / "multi"
    ws.mkdir(parents=True)
    code_ws = tmp_path / "obra-manager" / "obra-manager.code-workspace"
    code_ws.parent.mkdir(parents=True)
    code_ws.write_text(
        json.dumps({"folders": [{"path": "obra-records"}, {"path": "obra-saas"}]}),
        encoding="utf-8",
    )
    (ws / "workspace.json").write_text(
        json.dumps({"workspace": code_ws.as_uri()}),
        encoding="utf-8",
    )
    con = sqlite3.connect(ws / "state.vscdb")
    con.execute("CREATE TABLE ItemTable (key TEXT, value TEXT)")
    con.execute(
        "INSERT INTO ItemTable VALUES (?, ?)",
        (
            "composer.composerData",
            json.dumps({"selectedComposerIds": ["chat-multi"]}),
        ),
    )
    con.commit()
    con.close()

    found = open_cursor_chats(root)
    assert found == {"chat-multi": str(code_ws.parent)}


def test_cursor_window_projects_strip_workspace_suffix(monkeypatch):
    from agent_registry.usage import cursor_window_projects

    monkeypatch.setattr(
        "agent_registry.usage._cursor_window_titles",
        lambda: [
            "notes.md — obra-manager (Workspace)",
            "README — agent-tools",
            "Focus Proxy",
            "Item-0",
        ],
    )
    assert cursor_window_projects() == {"obra-manager", "agent-tools"}


def test_claude_session_title_prefers_custom_over_ai(tmp_path):
    from agent_registry.usage import claude_session_title

    projects = tmp_path / "projects" / "demo"
    projects.mkdir(parents=True)
    sid = "claude-title-1"
    (projects / f"{sid}.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"type": "ai-title", "aiTitle": "AI guess", "sessionId": sid}),
                json.dumps(
                    {
                        "type": "custom-title",
                        "customTitle": "User rename",
                        "sessionId": sid,
                    }
                ),
                json.dumps({"type": "ai-title", "aiTitle": "Later AI", "sessionId": sid}),
                json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    assert claude_session_title(sid, projects_root=tmp_path / "projects") == "User rename"


def test_claude_session_title_falls_back_to_ai_title(tmp_path):
    from agent_registry.usage import claude_session_title

    projects = tmp_path / "projects" / "demo"
    projects.mkdir(parents=True)
    sid = "claude-title-2"
    (projects / f"{sid}.jsonl").write_text(
        json.dumps({"type": "ai-title", "aiTitle": "MCP server over Tailscale", "sessionId": sid})
        + "\n",
        encoding="utf-8",
    )
    assert (
        claude_session_title(sid, projects_root=tmp_path / "projects")
        == "MCP server over Tailscale"
    )


def test_live_fills_null_claude_title_from_jsonl(tmp_registry, monkeypatch, tmp_path):
    from agent_registry import ops

    projects = tmp_path / "projects" / "am"
    projects.mkdir(parents=True)
    sid = "claude-live-title"
    (projects / f"{sid}.jsonl").write_text(
        json.dumps(
            {
                "type": "custom-title",
                "customTitle": "Validate engine improvements",
                "sessionId": sid,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("agent_registry.usage.open_cursor_chats", lambda: {})
    monkeypatch.setattr(
        "agent_registry.usage.claude_session_title",
        lambda session_id, projects_root=None: (
            "Validate engine improvements" if session_id == sid else None
        ),
    )
    ops.register(agent_type="claude", session_id=sid, directory="/am-videos", pid=None)
    httpd = serve_in_thread("127.0.0.1", 0)
    try:
        live = json.loads(
            urllib.request.urlopen(
                f"http://127.0.0.1:{httpd.server_address[1]}/api/live"
            ).read()
        )
        rows = {
            s["session_id"]: s
            for s in live["active"] + live["stale"] + live["attention"]
        }
        assert rows[sid]["title"] == "Validate engine improvements"
    finally:
        stop_server(httpd)


def test_cursor_composer_names_fall_back_to_composer_data(tmp_path):
    """Older chats often have name only on composerData, not composerHeaders."""
    import sqlite3

    from agent_registry.usage import cursor_composer_names

    db = tmp_path / "state.vscdb"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE composerHeaders (composerId TEXT, value TEXT)")
    con.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)")
    con.execute(
        "INSERT INTO composerHeaders VALUES (?, ?)",
        ("with-header", json.dumps({"name": "From header"})),
    )
    con.execute(
        "INSERT INTO cursorDiskKV VALUES (?, ?)",
        (
            "composerData:data-only",
            json.dumps({"composerId": "data-only", "name": "From composerData"}),
        ),
    )
    con.execute(
        "INSERT INTO cursorDiskKV VALUES (?, ?)",
        (
            "composerData:with-header",
            json.dumps({"composerId": "with-header", "name": "Should not win"}),
        ),
    )
    con.commit()
    con.close()

    names = cursor_composer_names({"with-header", "data-only", "missing"}, db)
    assert names == {
        "with-header": "From header",
        "data-only": "From composerData",
    }


def test_live_marks_an_open_cursor_chat(tmp_registry, monkeypatch):
    from agent_registry import ops

    monkeypatch.setattr(
        "agent_registry.usage.open_cursor_chats", lambda: {"chat-open": "/demo"}
    )
    ops.register(agent_type="cursor", session_id="chat-open", directory="/demo")
    ops.register(agent_type="cursor", session_id="chat-old", directory="/old")
    httpd = serve_in_thread("127.0.0.1", 0)
    try:
        live = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{httpd.server_address[1]}/api/live"
        ).read())
        rows = {s["session_id"]: s for s in live["active"] + live["attention"] + live["stale"]}
        assert rows["chat-open"]["cursor_open"] is True
        assert "cursor_open" not in rows["chat-old"]
    finally:
        stop_server(httpd)


def test_live_registers_an_open_cursor_chat_the_hooks_missed(tmp_registry, monkeypatch):
    monkeypatch.setattr(
        "agent_registry.usage.open_cursor_chats",
        lambda: {"chat-new": "/work/demo"},
    )
    monkeypatch.setattr(
        "agent_registry.usage.cursor_composer_names",
        lambda session_ids, db_path=None: {"chat-new": "Tauri app"},
    )
    httpd = serve_in_thread("127.0.0.1", 0)
    try:
        live = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{httpd.server_address[1]}/api/live"
        ).read())
        rows = [s for s in live["active"] if s["session_id"] == "chat-new"]
        assert len(rows) == 1
        assert rows[0]["cursor_open"] is True
        assert rows[0]["title"] == "Tauri app"
        assert rows[0]["directory"] == "/work/demo"
        again = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{httpd.server_address[1]}/api/live"
        ).read())
        assert len([s for s in again["active"] if s["session_id"] == "chat-new"]) == 1
    finally:
        stop_server(httpd)


def test_live_fills_null_cursor_title_from_composer_name(tmp_registry, monkeypatch):
    from agent_registry import ops, store

    monkeypatch.setattr("agent_registry.usage.open_cursor_chats", lambda: {})
    monkeypatch.setattr(
        "agent_registry.usage.cursor_composer_names",
        lambda session_ids, db_path=None: (
            {"hooked": "Cinema wall layout"}
            if "hooked" in session_ids
            else {}
        ),
    )
    ops.register(agent_type="cursor", session_id="hooked", directory="/obra-records")
    httpd = serve_in_thread("127.0.0.1", 0)
    try:
        live = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{httpd.server_address[1]}/api/live"
        ).read())
        rows = {s["session_id"]: s for s in live["active"] + live["stale"] + live["attention"]}
        assert rows["hooked"]["title"] == "Cinema wall layout"
        sess = next(s for s in store.load().sessions if s.session_id == "hooked")
        assert sess.title == "Cinema wall layout"
        assert not (sess.summary or "").strip()
    finally:
        stop_server(httpd)


def test_live_updates_cursor_title_when_composer_renamed(tmp_registry, monkeypatch):
    from agent_registry import ops, store

    monkeypatch.setattr("agent_registry.usage.open_cursor_chats", lambda: {})
    names = {"chat": "Old name"}
    monkeypatch.setattr(
        "agent_registry.usage.cursor_composer_names",
        lambda session_ids, db_path=None: {
            sid: names[sid] for sid in session_ids if sid in names
        },
    )
    ops.register(
        agent_type="cursor",
        session_id="chat",
        directory="/demo",
        title="Old name",
    )
    names["chat"] = "Renamed in Cursor"
    httpd = serve_in_thread("127.0.0.1", 0)
    try:
        live = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{httpd.server_address[1]}/api/live"
        ).read())
        rows = {s["session_id"]: s for s in live["active"] + live["stale"] + live["attention"]}
        assert rows["chat"]["title"] == "Renamed in Cursor"
        sess = next(s for s in store.load().sessions if s.session_id == "chat")
        assert sess.title == "Renamed in Cursor"
    finally:
        stop_server(httpd)
