from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from agent_inbox import db, poll, store, waiting
from agent_inbox.constants import (
    ENGINES,
    EXIT_CONFLICT,
    EXIT_OK,
    EXIT_TIMEOUT,
    EXIT_USAGE,
    KINDS,
    VIAS,
    WAIT_TIMEOUT_SEC,
)
from agent_inbox.errors import InboxError, ValidationError
from agent_inbox.links import entry_url
from agent_inbox.validate import validate_request, validate_update

WAIT_EXIT = {"answer": EXIT_OK, "followup": EXIT_OK, "timeout": EXIT_TIMEOUT}


class _Parser(argparse.ArgumentParser):
    """argparse exits 2 on bad flags, which would read as not-found; raise a usage error instead."""

    def error(self, message: str) -> None:  # type: ignore[override]
        raise ValidationError(message)


def _add_request_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--file", help="request JSON path (default: stdin)")
    p.add_argument("--html-file", help="HTML part, overrides `html` in the request")


def _add_asker_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--engine", choices=ENGINES)
    p.add_argument("--model")
    p.add_argument("--session-id")
    p.add_argument("--cwd", default=None, help="asker working directory (default: current)")


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="agent-inbox")
    sub = p.add_subparsers(dest="cmd", required=True)

    ask = sub.add_parser("ask")
    _add_request_args(ask)
    _add_asker_args(ask)
    ask.add_argument("--wait", action="store_true")
    ask.add_argument("--script", help="ask with no session: never woken, read the answer with `get`")
    ask.add_argument("--timeout", type=float, default=WAIT_TIMEOUT_SEC)

    post = sub.add_parser("post")
    _add_request_args(post)
    _add_asker_args(post)
    post.add_argument("--script", help="name shown as the sender when there is no session")

    wait = sub.add_parser("wait")
    wait.add_argument("id")
    wait.add_argument("--after", type=int, default=0, help="return only follow-ups newer than this seq")
    wait.add_argument("--timeout", type=float, default=WAIT_TIMEOUT_SEC)

    sub.add_parser("serve")

    get = sub.add_parser("get")
    get.add_argument("id")

    ls = sub.add_parser("list")
    ls.add_argument("--kind", choices=KINDS)
    ls.add_argument("--state", action="append", dest="states")
    ls.add_argument("--project")
    ls.add_argument("--engine", choices=ENGINES)
    ls.add_argument("--session-id")
    ls.add_argument("--limit", type=int, default=50)
    ls.add_argument("--json", action="store_true")

    poll = sub.add_parser("poll")
    poll.add_argument("--kind", choices=KINDS)
    poll.add_argument("--state", action="append", dest="states")
    poll.add_argument("--project")
    poll.add_argument("--engine", choices=ENGINES)
    poll.add_argument("--session-id")
    poll.add_argument("--limit", type=int, default=50)
    poll.add_argument("--rev", default=None)
    poll.add_argument("--timeout", type=float, default=20)
    poll.add_argument("--follow", action="store_true")

    ans = sub.add_parser("answer")
    ans.add_argument("id")
    ans.add_argument("--value", action="append", required=True, help="repeat for multi")
    ans.add_argument("--comment")
    ans.add_argument("--via", choices=VIAS, default="cli")

    fu = sub.add_parser("followup")
    fu.add_argument("id")
    fu.add_argument("--text", required=True)
    fu.add_argument("--via", choices=VIAS, default="cli")

    rep = sub.add_parser("reply")
    rep.add_argument("id")
    rep.add_argument("--text", required=True)
    rep.add_argument("--html-file")

    upd = sub.add_parser("update")
    upd.add_argument("id")
    _add_request_args(upd)

    rev = sub.add_parser("revise")
    rev.add_argument("id")
    src = rev.add_mutually_exclusive_group(required=True)
    src.add_argument("--control", help="control JSON")
    src.add_argument("--control-file")

    for name in ("withdraw", "read", "archive"):
        sub.add_parser(name).add_argument("id")

    sup = sub.add_parser("supersede")
    sup.add_argument("id")
    sup.add_argument("--by", required=True)
    return p


def _read_request(args: argparse.Namespace) -> Any:
    raw = Path(args.file).read_text() if args.file else sys.stdin.read()
    data = json.loads(raw) if raw.strip() else {}
    if args.html_file and isinstance(data, dict):
        data["html"] = Path(args.html_file).read_text()
    return data


def _asker(args: argparse.Namespace) -> dict:
    return {
        "engine": args.engine,
        "model": args.model,
        "session_id": args.session_id,
        "cwd": args.cwd or os.getcwd(),
    }


def _waited(event: dict) -> tuple[Any, int]:
    return event, WAIT_EXIT.get(event["event"], EXIT_CONFLICT)


def _table(rows: list[dict]) -> str:
    if not rows:
        return "(no entries)"
    lines = []
    for r in rows:
        project = os.path.basename(r["asker"]["project"] or "") or "-"
        lines.append(
            f"{r['id']}  {r['kind']:<4}  {r['state']:<11}  {r['priority']:<6}  {project:<16.16}  {r['title'][:60]}"
        )
    return "\n".join(lines)


def _dispatch(args: argparse.Namespace) -> tuple[Any, int]:
    cmd = args.cmd
    if cmd == "wait":
        return _waited(waiting.wait_for(args.id, after=args.after, timeout=args.timeout))
    if cmd == "serve":
        from agent_inbox.serve import run
        run()
        return {"ok": True}, EXIT_OK

    with db.connect() as conn:
        if cmd == "ask":
            req = validate_request(_read_request(args), "ask")
            entry = store.create_entry(
                conn, "ask", req, mode="wait" if args.wait else "resume", script=args.script, **_asker(args),
            )
            url = entry_url(entry["id"])
            if not args.wait:
                return {"entry": entry["id"], "state": entry["state"], "url": url}, EXIT_OK
            # The answer is the only stdout in wait mode; the link goes to stderr now.
            print(json.dumps({"entry": entry["id"], "url": url}), file=sys.stderr, flush=True)
        elif cmd == "post":
            req = validate_request(_read_request(args), "post")
            entry = store.create_entry(conn, "post", req, script=args.script, **_asker(args))
            return {"entry": entry["id"], "state": entry["state"], "url": entry_url(entry["id"])}, EXIT_OK
        elif cmd == "get":
            return store.get_entry(conn, args.id), EXIT_OK
        elif cmd == "list":
            rows = store.list_entries(
                conn, kind=args.kind, states=args.states, project=args.project,
                engine=args.engine, session_id=args.session_id, limit=args.limit,
            )
            return (rows if args.json else _table(rows)), EXIT_OK
        elif cmd == "answer":
            value = args.value[0] if len(args.value) == 1 else args.value
            return store.answer(conn, args.id, value, comment=args.comment, via=args.via), EXIT_OK
        elif cmd == "followup":
            return store.add_followup(conn, args.id, args.text, via=args.via), EXIT_OK
        elif cmd == "reply":
            html = Path(args.html_file).read_text() if args.html_file else None
            return store.add_reply(conn, args.id, args.text, html=html), EXIT_OK
        elif cmd == "update":
            return store.update_entry(conn, args.id, validate_update(_read_request(args))), EXIT_OK
        elif cmd == "revise":
            raw = args.control if args.control is not None else Path(args.control_file).read_text()
            return store.revise(conn, args.id, json.loads(raw)), EXIT_OK
        elif cmd == "withdraw":
            return store.withdraw(conn, args.id), EXIT_OK
        elif cmd == "supersede":
            return store.supersede(conn, args.id, by=args.by), EXIT_OK
        elif cmd == "read":
            return store.mark_read(conn, args.id), EXIT_OK
        elif cmd == "archive":
            return store.archive(conn, args.id), EXIT_OK

    # Only `ask --wait` reaches here: the entry is created and committed, so the waiter can see it.
    return _waited(waiting.wait_for(entry["id"], timeout=args.timeout))


def _filters(args: argparse.Namespace) -> dict:
    return {
        "kind": args.kind,
        "states": args.states,
        "project": args.project,
        "engine": args.engine,
        "session_id": args.session_id,
        "limit": args.limit,
    }


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


def _poll(args: argparse.Namespace) -> int:
    if args.timeout < 0:
        raise ValidationError("timeout must be >= 0")
    if args.follow and args.rev is not None:
        raise ValidationError("poll --follow does not take --rev")
    filters = _filters(args)
    try:
        if args.follow:
            for snap in poll.follow(**filters):
                if not _print_line(snap):
                    return EXIT_OK
            return EXIT_OK
        snap = poll.poll_snapshot(since=args.rev, timeout=args.timeout, **filters)
    except BrokenPipeError:
        _silence_stdout()
        return EXIT_OK
    if not _print_line(snap):
        return EXIT_OK
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.cmd == "poll":
            return _poll(args)
        out, code = _dispatch(args)
    except InboxError as e:
        print(f"agent-inbox: {e}", file=sys.stderr)
        return e.exit_code
    except (OSError, json.JSONDecodeError) as e:
        print(f"agent-inbox: {e}", file=sys.stderr)
        return EXIT_USAGE
    print(out if isinstance(out, str) else json.dumps(out))
    return code


if __name__ == "__main__":
    sys.exit(main())
