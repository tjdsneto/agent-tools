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
    assert json.loads(r.stdout)["additional_context"].startswith("No intent set")


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
