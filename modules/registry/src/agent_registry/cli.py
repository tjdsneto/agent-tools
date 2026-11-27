from __future__ import annotations
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
# The client spawns this file (`python cli.py daemon run`). That puts this
# directory on sys.path[0], so the import needs `src/`, which contains the package.
if __name__ == "__main__" and __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent_registry import archive, client, doctor, topic_cli
from agent_registry.constants import (
    DASHBOARD_DEFAULT_PORT,
    EXIT_IO,
    EXIT_OK,
    EXIT_USAGE,
    WAKE_ENV,
)
from agent_registry.format import format_archive_list, format_list

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _fail(error: object, code: int) -> int:
    print(f"agent-registry: {error}", file=sys.stderr)
    return code


def _address(args: argparse.Namespace) -> dict:
    return {
        "peer_name": args.peer_name,
        "socket": args.socket,
        "pid": args.pid,
        "peer_status": args.peer_status,
    }

def _add_address_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--peer-name", default=None)
    p.add_argument("--socket", default=None)
    p.add_argument("--pid", type=int, default=None)
    p.add_argument("--peer-status", default=None)

def _parse_older_than(value: str) -> int:
    s = value.strip().lower()
    if s.endswith("d"):
        s = s[:-1]
    try:
        days = int(s)
    except ValueError as e:
        raise archive.ValidationError(f"invalid --older-than: {value}") from e
    if days < 1:
        raise archive.ValidationError("days must be >= 1")
    return days

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-registry")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_reg = sub.add_parser("register")
    p_reg.add_argument("--type", required=True, dest="agent_type")
    p_reg.add_argument("--session-id", required=True)
    p_reg.add_argument("--directory", required=True)
    p_reg.add_argument("--parent-session", default=None)
    p_reg.add_argument("--model", default=None)
    p_reg.add_argument("--title", default=None)
    _add_address_args(p_reg)
    p_reg.add_argument("--replace", action="store_true")

    p_up = sub.add_parser("update")
    p_up.add_argument("registry_id")
    p_up.add_argument("--status")
    p_up.add_argument("--summary")
    p_up.add_argument("--title")
    p_up.add_argument("--issue")
    p_up.add_argument("--pr-title")
    p_up.add_argument("--pr-url")
    p_up.add_argument("--branch")
    p_up.add_argument("--directory")
    p_up.add_argument("--model")
    p_up.add_argument("--goflow-timer", dest="goflow_timer_id")
    p_up.add_argument("--parent-session", dest="parent_session_id")
    p_up.add_argument("--clear-issue", action="store_true")
    p_up.add_argument("--clear-pr", action="store_true")
    p_up.add_argument("--clear-branch", action="store_true")
    p_up.add_argument("--clear-goflow-timer", action="store_true")
    p_up.add_argument("--clear-summary", action="store_true")
    p_up.add_argument("--clear-parent-session", action="store_true")
    p_up.add_argument("--clear-model", action="store_true")
    p_up.add_argument("--clear-title", action="store_true")

    p_ping = sub.add_parser("ping")
    p_ping.add_argument("registry_id")
    p_ping.add_argument("--model", default=None)
    p_ping.add_argument("--title", default=None)
    p_un = sub.add_parser("unregister")
    p_un.add_argument("registry_id")
    p_list = sub.add_parser("list")
    p_list.add_argument("--json", action="store_true")
    p_poll = sub.add_parser("poll")
    p_poll.add_argument("--rev", type=int, default=None)
    p_poll.add_argument("--timeout", type=float, default=20)
    p_poll.add_argument("--follow", action="store_true")
    p_prune = sub.add_parser("prune")
    p_prune.add_argument("--dry-run", action="store_true")
    p_prune.add_argument("--yes", action="store_true")

    p_ens = sub.add_parser("ensure")
    p_ens.add_argument("--type", required=True, dest="agent_type")
    p_ens.add_argument("--session-id", required=True)
    p_ens.add_argument("--directory", required=True)
    p_ens.add_argument("--parent-session", default=None)
    p_ens.add_argument("--model", default=None)
    p_ens.add_argument("--title", default=None)
    _add_address_args(p_ens)
    p_ens.add_argument("--no-replace", action="store_true")

    p_hb = sub.add_parser("heartbeat")
    p_hb.add_argument("--type", required=True, dest="agent_type")
    p_hb.add_argument("--session-id", required=True)
    p_hb.add_argument("--model", default=None)
    p_hb.add_argument("--title", default=None)
    p_hb.add_argument("--status", default=None)
    _add_address_args(p_hb)

    p_end = sub.add_parser("end")
    p_end.add_argument("--type", required=True, dest="agent_type")
    p_end.add_argument("--session-id", required=True)

    p_self = sub.add_parser("self")
    p_self.add_argument("--type", required=True, dest="agent_type")
    p_self.add_argument("--session-id", required=True)

    p_sum = sub.add_parser("summarize")
    p_sum.add_argument("--type", required=True, dest="agent_type")
    p_sum.add_argument("--session-id", required=True)
    p_sum.add_argument("--transcript", default=None, help="path to session transcript JSONL")
    p_sum.add_argument("--force", action="store_true", help="overwrite non-empty summary")

    p_arch = sub.add_parser("archive")
    arch_sub = p_arch.add_subparsers(dest="archive_cmd", required=True)
    p_al = arch_sub.add_parser("list")
    p_al.add_argument("--json", action="store_true")
    p_al.add_argument("--reason")
    p_al.add_argument("--limit", type=int, default=100)
    p_as = arch_sub.add_parser("show")
    p_as.add_argument("session_id")
    p_as.add_argument("--full", action="store_true")
    p_ap = arch_sub.add_parser("purge")
    p_ap.add_argument("--older-than", required=True)
    p_ap.add_argument("--yes", action="store_true")

    p_dash = sub.add_parser("dashboard")
    p_dash.add_argument("--port", type=int, default=None)
    p_dash.add_argument("--host", default="127.0.0.1")
    p_dash.add_argument("--no-open", action="store_true")

    sub.add_parser("doctor")

    p_resolve = sub.add_parser("resolve")
    p_resolve.add_argument("session_id")

    p_wake = sub.add_parser("wake")
    p_wake.add_argument("session_id")
    p_wake.add_argument("--message", required=True, help="path to the continue-prompt file")

    p_status = sub.add_parser("status")
    p_status.add_argument("--json", action="store_true")

    p_daemon = sub.add_parser("daemon")
    daemon_sub = p_daemon.add_subparsers(dest="daemon_cmd", required=True)
    p_run = daemon_sub.add_parser("run")
    p_run.add_argument("--port", type=int, default=None)
    daemon_sub.add_parser("install")
    daemon_sub.add_parser("uninstall")
    daemon_sub.add_parser("start")
    daemon_sub.add_parser("stop")

    topic_cli.add_parsers(sub)
    args = parser.parse_args(argv)
    if args.cmd in topic_cli.COMMANDS:
        return topic_cli.run(args)
    try:
        if args.cmd == "daemon":
            return _daemon(args)
        if args.cmd == "dashboard":
            return _dashboard(args)
        if args.cmd == "poll":
            return _poll(args)

        op, params = _build_command(args)
        result = client.call(op, params)
        error = result.get("error")
        code = result.get("exit_code", EXIT_IO)
        if error:
            return _fail(error, code)
        data = result.get("data")
        _print_result(args, data)
        return code
    except OSError as e:
        return _fail(e, EXIT_IO)


def _build_command(args: argparse.Namespace) -> tuple[str, dict]:
    cmd = args.cmd
    if cmd == "register":
        return "register", {
            "agent_type": args.agent_type,
            "session_id": args.session_id,
            "directory": args.directory,
            "parent_session": args.parent_session,
            "model": args.model,
            "title": args.title,
            "replace": args.replace,
            **_address(args),
        }
    if cmd == "update":
        return "update", {
            "registry_id": args.registry_id,
            "status": args.status,
            "summary": args.summary,
            "title": args.title,
            "issue": args.issue,
            "pr_title": args.pr_title,
            "pr_url": args.pr_url,
            "branch": args.branch,
            "directory": args.directory,
            "model": args.model,
            "goflow_timer_id": args.goflow_timer_id,
            "parent_session_id": args.parent_session_id,
            "clear_issue": args.clear_issue,
            "clear_pr": args.clear_pr,
            "clear_branch": args.clear_branch,
            "clear_goflow_timer": args.clear_goflow_timer,
            "clear_summary": args.clear_summary,
            "clear_parent_session": args.clear_parent_session,
            "clear_model": args.clear_model,
            "clear_title": args.clear_title,
        }
    if cmd == "ping":
        return "ping", {
            "registry_id": args.registry_id,
            "model": args.model,
            "title": args.title,
        }
    if cmd == "unregister":
        return "unregister", {"registry_id": args.registry_id}
    if cmd == "list":
        return "list", {}
    if cmd == "prune":
        return "prune", {"dry_run": args.dry_run or not args.yes, "yes": args.yes}
    if cmd == "ensure":
        return "ensure", {
            "agent_type": args.agent_type,
            "session_id": args.session_id,
            "directory": args.directory,
            "parent_session": args.parent_session,
            "model": args.model,
            "title": args.title,
            "no_replace": args.no_replace,
            # The hook runs inside the agent's process tree, so a session wake started carries WAKE_ENV.
            "record_launch": os.environ.get(WAKE_ENV) != "1",
            **_address(args),
        }
    if cmd == "heartbeat":
        return "heartbeat", {
            "agent_type": args.agent_type,
            "session_id": args.session_id,
            "model": args.model,
            "title": args.title,
            "status": args.status,
            **_address(args),
        }
    if cmd == "end":
        return "end", {"agent_type": args.agent_type, "session_id": args.session_id}
    if cmd == "self":
        return "self", {"agent_type": args.agent_type, "session_id": args.session_id}
    if cmd == "summarize":
        return "summarize", {
            "agent_type": args.agent_type,
            "session_id": args.session_id,
            "transcript": args.transcript,
            "force": args.force,
        }
    if cmd == "archive":
        if args.archive_cmd == "list":
            return "archive_list", {"reason": args.reason, "limit": args.limit}
        if args.archive_cmd == "show":
            return "archive_show", {"session_id": args.session_id, "full": args.full}
        return "archive_purge", {"older_than": args.older_than, "yes": args.yes}
    if cmd == "resolve":
        return "resolve", {"session_id": args.session_id}
    if cmd == "wake":
        message = Path(args.message).read_text()
        return "wake", {"session_id": args.session_id, "message": message}
    if cmd == "doctor":
        return "doctor", {}
    return "status", {}


def _print_result(args: argparse.Namespace, data: object) -> None:
    if args.cmd == "list":
        if args.json:
            print(json.dumps(data))
        else:
            print(format_list(data["active"], data["stale"]), end="")
    elif args.cmd == "prune":
        dry_run = args.dry_run or not args.yes
        print(json.dumps({"dry_run": dry_run, "sessions": data}))
    elif args.cmd == "archive" and args.archive_cmd == "list":
        if args.json:
            print(json.dumps({"events": data}))
        else:
            print(format_archive_list(data), end="")
    elif args.cmd == "archive" and args.archive_cmd == "purge":
        print(json.dumps({"removed": data}))
    elif args.cmd == "doctor":
        print("\n".join(data["lines"]))
    elif args.cmd == "status":
        if args.json:
            print(json.dumps(data))
        else:
            print(doctor.format_status(data), end="")
    else:
        print(json.dumps(data))


def _launchctl_bootstrap(domain: str, plist: str) -> None:
    subprocess.run(["launchctl", "bootstrap", domain, plist], check=False)


def _launchctl_bootout(domain: str, plist: str) -> None:
    subprocess.run(["launchctl", "bootout", domain, plist], check=False)


def _installed_program() -> str:
    found = shutil.which("agent-registry")
    if found:
        return found
    argv0 = sys.argv[0]
    path = Path(argv0)
    if argv0 and path.is_file():
        return str(path.resolve())
    return argv0 or "agent-registry"


def _poll(args: argparse.Namespace) -> int:
    if args.timeout < 0:
        return _fail("timeout must be >= 0", EXIT_USAGE)
    if args.follow and args.rev is not None:
        return _fail("poll --follow does not take --rev", EXIT_USAGE)
    chosen = client.ensure_daemon(None)
    if isinstance(chosen, dict):
        return _fail(chosen.get("error"), chosen.get("exit_code", EXIT_IO))
    try:
        if args.follow:
            return _poll_follow(chosen)
        snap = client.poll_snapshot(chosen, args.rev, args.timeout)
    except BrokenPipeError:
        _silence_stdout()
        return EXIT_OK
    except OSError as e:
        return _fail(e, EXIT_IO)
    if not _print_line(snap):
        return EXIT_OK
    return EXIT_OK


def _print_line(snap: dict) -> bool:
    try:
        print(json.dumps(snap), flush=True)
    except BrokenPipeError:
        _silence_stdout()
        return False
    return True


def _silence_stdout() -> None:
    """Point stdout at /dev/null so Python's exit flush does not raise on a closed pipe."""
    try:
        null = os.open(os.devnull, os.O_WRONLY)
    except OSError:
        return
    try:
        os.dup2(null, sys.stdout.fileno())
    except (AttributeError, OSError, ValueError):
        pass
    finally:
        os.close(null)


def _poll_follow(port: int) -> int:
    def fetch():
        result = client.call("list", {})
        error = result.get("error")
        if error or result.get("exit_code"):
            raise OSError(error or "list failed")
        return result.get("data") or {"active": [], "stale": []}

    try:
        for snap in client.changed_snapshots(client.iter_revisions(port), fetch):
            if not _print_line(snap):
                return EXIT_OK
    except BrokenPipeError:
        _silence_stdout()
        return EXIT_OK
    except OSError as e:
        return _fail(e, EXIT_IO)
    return EXIT_OK


def _daemon(args: argparse.Namespace) -> int:
    # Platform before any registry read, spawn, or LaunchAgents write.
    if args.daemon_cmd == "install" and sys.platform != "darwin":
        return _fail("daemon install is macOS only", EXIT_USAGE)
    agents = Path.home() / "Library" / "LaunchAgents"
    if args.daemon_cmd == "install":
        client.install_launchd(agents, _installed_program(), _launchctl_bootstrap)
        return EXIT_OK
    if args.daemon_cmd == "uninstall":
        return client.uninstall_launchd(agents, _launchctl_bootout)
    if args.daemon_cmd == "start":
        result = client.start_daemon(agents, _launchctl_bootstrap)
        if isinstance(result, dict):
            return _fail(result.get("error"), result.get("exit_code", EXIT_IO))
        return result
    if args.daemon_cmd == "stop":
        return client.stop_daemon(agents, _launchctl_bootout)
    from agent_registry.daemon import run_foreground

    port = DASHBOARD_DEFAULT_PORT if args.port is None else args.port
    return run_foreground("127.0.0.1", port)


def _dashboard(args: argparse.Namespace) -> int:
    if args.host not in _LOOPBACK_HOSTS:
        return _fail("dashboard host must be loopback", EXIT_USAGE)
    chosen = client.ensure_daemon(args.port)
    if isinstance(chosen, dict):
        return _fail(chosen["error"], chosen["exit_code"])
    url = f"http://127.0.0.1:{chosen}/"
    print(f"agent-registry dashboard at {url}", flush=True)
    if not args.no_open:
        import webbrowser

        try:
            webbrowser.open(url)
        except Exception:
            pass
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
