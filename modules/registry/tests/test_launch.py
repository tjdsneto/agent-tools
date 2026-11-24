import os

from agent_registry import launch, lifecycle
from agent_registry.transport import resume_argv, wake

NARROW = [
    "claude", "-p", "--output-format", "json", "--session-id", "s1",
    "--allowedTools", "Read", "Grep", "Edit(.ana/**)", "Bash(git -C repo log:*)",
    "--model", "opus",
]
IDE = [
    "claude", "--output-format", "stream-json", "--permission-prompt-tool=stdio",
    "--permission-mode=bypassPermissions", "--allow-dangerously-skip-permissions",
]


def test_permission_args_keeps_only_permission_flags():
    assert launch.permission_args(NARROW[1:]) == [
        "--allowedTools", "Read", "Grep", "Edit(.ana/**)", "Bash(git -C repo log:*)",
    ]
    assert launch.permission_args(IDE[1:]) == [
        "--permission-mode", "bypassPermissions", "--allow-dangerously-skip-permissions",
    ]


def test_permission_args_inline_and_spaced_forms():
    argv = ["--permission-mode", "plan", "--disallowed-tools=Bash", "--add-dir", "/a", "/b", "-p"]
    assert launch.permission_args(argv) == [
        "--permission-mode", "plan", "--disallowed-tools", "Bash", "--add-dir", "/a", "/b",
    ]


def test_permission_args_default_launch_is_empty():
    assert launch.permission_args(["--resume", "s1", "-p", "hi"]) == []


def test_process_argv_reads_this_process():
    argv = launch.process_argv(os.getpid())
    assert argv and "python" in argv[0].lower()


def test_record_and_load(tmp_registry):
    assert launch.load("s1") is None
    assert launch.record("s1", 7, argv_of=lambda pid: NARROW) == launch.permission_args(NARROW[1:])
    assert launch.load("s1")[0] == "--allowedTools"


def test_record_default_launch_is_known_and_empty(tmp_registry):
    launch.record("s1", 7, argv_of=lambda pid: ["claude"])
    assert launch.load("s1") == []


def test_record_unreadable_argv_saves_nothing(tmp_registry):
    assert launch.record("s1", 7, argv_of=lambda pid: None) is None
    assert launch.load("s1") is None


def test_record_survives_session_end(tmp_registry, monkeypatch):
    monkeypatch.setattr(launch, "process_argv", lambda pid: NARROW)
    lifecycle.ensure("claude", "s1", "/proj", pid=7, record_launch=True)
    lifecycle.end("claude", "s1")
    assert launch.load("s1")[0] == "--allowedTools"


def test_ensure_records_only_when_asked(tmp_registry, monkeypatch):
    monkeypatch.setattr(launch, "process_argv", lambda pid: NARROW)
    lifecycle.ensure("claude", "s1", "/proj", pid=7)
    assert launch.load("s1") is None
    lifecycle.ensure("codex", "s2", "/proj", pid=7, record_launch=True)
    assert launch.load("s2") is None


def test_resume_replays_recorded_flags_before_settings():
    argv = resume_argv("s1", "the answer", claude="claude", permissions=["--allowedTools", "Read", "Grep"])
    assert "--dangerously-skip-permissions" not in argv
    i = argv.index("--allowedTools")
    assert argv[i:i + 3] == ["--allowedTools", "Read", "Grep"]
    # A variadic flag would swallow the message unless another flag ends it.
    assert argv[i + 3] == "--settings"
    assert argv[-1] == "the answer"


def test_resume_with_default_launch_adds_nothing():
    argv = resume_argv("s1", "m", claude="claude", permissions=[])
    assert argv == ["claude", "-p", "--resume", "s1", "--settings", argv[5], "m"]


def test_resume_unknown_bypasses_by_default(monkeypatch):
    monkeypatch.delenv("AGENT_REGISTRY_RESUME_BYPASS_UNKNOWN", raising=False)
    assert "--dangerously-skip-permissions" in resume_argv("s1", "m")


def test_resume_unknown_bypass_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("AGENT_REGISTRY_RESUME_BYPASS_UNKNOWN", "0")
    assert "--dangerously-skip-permissions" not in resume_argv("s1", "m")


def test_wake_resume_uses_recorded_flags(tmp_registry, monkeypatch):
    monkeypatch.setattr(launch, "process_argv", lambda pid: NARROW)
    lifecycle.ensure("claude", "s1", "/proj", peer_name="n", pid=3, record_launch=True)
    calls = []

    def runner(argv, cwd):
        calls.append(argv)
        return "", 0

    wake("s1", "m", alive_check=lambda pid: False, runner=runner)
    assert "--dangerously-skip-permissions" not in calls[0]
    assert "Bash(git -C repo log:*)" in calls[0]
