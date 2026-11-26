import json

WHO = ["--type", "claude", "--session-id", "s1"]


def _prompt(box, host="claude", sid="s1", event="UserPromptSubmit"):
    return box.hook(host, "ping", {"session_id": sid, "hook_event_name": event, "cwd": str(box.root)})


def test_claude_prompt_without_intent(box):
    r = _prompt(box)
    assert r.returncode == 0
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "UserPromptSubmit"
    assert out["additionalContext"].startswith("No intent set for this session.")


def test_claude_prompt_with_intent_and_topic(box):
    tid = box.agt_json("registry", "intent", "Ship it", *WHO)["topic"]["id"]
    box.agt_json("registry", "topic", "Plan", *WHO)
    ctx = json.loads(_prompt(box).stdout)["hookSpecificOutput"]["additionalContext"]
    assert ctx.startswith(f"Intent: Ship it ({tid}) · Topic: Plan (tp-")
    assert ctx.endswith("run the conversation drift check.")


def test_pretooluse_ping_prints_nothing(box):
    r = _prompt(box, event="PreToolUse")
    assert r.returncode == 0
    assert r.stdout == ""


def test_codex_prompt(box):
    box.agt_json("registry", "intent", "Codex work", "--type", "codex", "--session-id", "t1")
    r = _prompt(box, host="codex", sid="t1")
    assert "Intent: Codex work" in json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]


def test_cursor_prompt_only_continues(box):
    r = box.hook("cursor", "ping", {
        "conversation_id": "c1", "hook_event_name": "beforeSubmitPrompt", "cursor_version": "3",
    })
    assert r.returncode == 0
    assert r.stdout.strip() == '{"continue":true}'


def test_cursor_session_start_carries_line(box):
    r = box.hook("cursor", "ensure", {
        "conversation_id": "c1", "hook_event_name": "sessionStart", "cursor_version": "3",
        "workspace_roots": [str(box.root)],
    })
    assert r.returncode == 0
    assert "No intent set" in json.loads(r.stdout)["additional_context"]


def test_claude_session_start_carries_line(box):
    r = box.hook("claude", "ensure", {"session_id": "s9", "hook_event_name": "SessionStart", "cwd": str(box.root)})
    assert r.returncode == 0
    assert "No intent set for this session." in json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]


def test_unreadable_log_fails_open(box):
    box.agt_json("registry", "intent", "Ship it", *WHO)
    log = box.data / "topics" / "claude" / "s1.jsonl"
    log.chmod(0)
    try:
        r = _prompt(box)
        assert r.returncode == 0
        assert r.stdout == ""
    finally:
        log.chmod(0o600)


def test_hook_runs_under_macos_bash(box):
    # /bin/bash is 3.2 on macOS, where expanding an empty array under set -u is an error.
    env = dict(box.env, PATH="/usr/bin:/bin")
    r = box.hook(
        "codex", "ping",
        {"session_id": "t1", "hook_event_name": "UserPromptSubmit", "cwd": str(box.root)},
        shell="/bin/bash", env=env,
    )
    assert r.returncode == 0, r.stderr
    assert "No intent set" in json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]


MARKER = "CORE MARKER 7f3a"


def _with_core(box, text=MARKER):
    core = box.root / "core.md"
    core.write_text(text, encoding="utf-8")
    return dict(box.env, AGENT_REGISTRY_CONVERSATION_CORE=str(core))


def test_claude_session_start_carries_the_core(box):
    r = box.hook(
        "claude", "ensure", {"session_id": "s9", "hook_event_name": "SessionStart", "cwd": str(box.root)},
        env=_with_core(box),
    )
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert MARKER in ctx and "No intent set for this session." in ctx


def test_claude_session_start_without_core_file_keeps_the_line(box):
    env = dict(box.env, AGENT_REGISTRY_CONVERSATION_CORE=str(box.root / "missing.md"))
    r = box.hook(
        "claude", "ensure", {"session_id": "s9", "hook_event_name": "SessionStart", "cwd": str(box.root)}, env=env,
    )
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "No intent set" in ctx and MARKER not in ctx


def test_cursor_session_start_carries_the_core(box):
    r = box.hook("cursor", "ensure", {
        "conversation_id": "c1", "hook_event_name": "sessionStart", "cursor_version": "3",
        "workspace_roots": [str(box.root)],
    }, env=_with_core(box))
    assert MARKER in json.loads(r.stdout)["additional_context"]


def test_cursor_subagent_start_prints_nothing_to_add(box):
    r = box.hook("cursor", "ensure", {
        "conversation_id": "c2", "hook_event_name": "subagentStart", "cursor_version": "3",
        "workspace_roots": [str(box.root)],
    }, env=_with_core(box))
    assert r.returncode == 0
    assert r.stdout.strip() == "{}"


def test_codex_session_start_carries_the_core(box):
    r = box.hook(
        "codex", "ensure", {"session_id": "t9", "hook_event_name": "SessionStart", "cwd": str(box.root)},
        env=_with_core(box),
    )
    assert r.returncode == 0
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "SessionStart"
    assert MARKER in out["additionalContext"]


def _failing_ensure_bin(box):
    # A registry whose ensure fails (say the daemon won't start) while its file-only commands still work.
    real = box.env["AGENT_REGISTRY_BIN"]
    fake = box.root / "agent-registry-ensure-fails"
    fake.write_text(f'#!/bin/bash\n[[ "$1" == "ensure" ]] && exit 1\nexec "{real}" "$@"\n')
    fake.chmod(0o755)
    return dict(box.env, AGENT_REGISTRY_BIN=str(fake))


def test_core_is_injected_when_registration_fails(box, tmp_path):
    core = tmp_path / "core.md"
    core.write_text("CORE MARKER 7f3a")
    env = dict(_failing_ensure_bin(box), AGENT_REGISTRY_CONVERSATION_CORE=str(core))
    claude = box.hook("claude", "ensure", {"session_id": "s9", "hook_event_name": "SessionStart", "cwd": str(box.root)}, env=env)
    ctx = json.loads(claude.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "registration failed" in ctx and "CORE MARKER 7f3a" in ctx
    codex = box.hook("codex", "ensure", {"session_id": "t9", "hook_event_name": "SessionStart", "cwd": str(box.root)}, env=env)
    assert "CORE MARKER 7f3a" in json.loads(codex.stdout)["hookSpecificOutput"]["additionalContext"]
    cursor = box.hook("cursor", "ensure", {
        "conversation_id": "c9", "hook_event_name": "sessionStart", "cursor_version": "3",
        "workspace_roots": [str(box.root)],
    }, env=env)
    assert "CORE MARKER 7f3a" in json.loads(cursor.stdout)["additional_context"]
