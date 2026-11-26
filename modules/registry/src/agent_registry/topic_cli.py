"""Topic commands. They run in this process and never go through the daemon."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from agent_registry import conversation, forking, liveness, topics
from agent_registry.constants import (
    EXIT_CONFLICT,
    EXIT_IO,
    EXIT_NOT_FOUND,
    EXIT_OK,
    EXIT_USAGE,
    SESSION_ENV,
)

COMMANDS = frozenset({"intent", "topic", "topics", "fork", "topic-context", "session-context", "topic-path", "topic-note"})


def _add_who(p: argparse.ArgumentParser) -> None:
    p.add_argument("--type", dest="agent_type", default=None)
    p.add_argument("--session-id", default=None)


def add_parsers(sub) -> None:
    p = sub.add_parser("intent")
    p.add_argument("title", nargs="?")
    p.add_argument("--adopt", metavar="TOPIC_ID", default=None)
    _add_who(p)

    p = sub.add_parser("topic")
    p.add_argument("title", nargs="?")
    p.add_argument("--done", nargs="?", const="", default=None, metavar="TOPIC_ID")
    p.add_argument("--park", nargs="?", const="", default=None, metavar="TOPIC_ID")
    p.add_argument("--ref", default=None)
    _add_who(p)

    p = sub.add_parser("topics")
    which = p.add_mutually_exclusive_group()
    which.add_argument("--session", default=None)
    which.add_argument("--open", action="store_true")
    which.add_argument("--tree", action="store_true")
    p.add_argument("--events", action="store_true")
    _add_who(p)

    p = sub.add_parser("fork")
    p.add_argument("title")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--side", action="store_true")
    mode.add_argument("--new-intent", action="store_true")
    p.add_argument("--backend", choices=forking.BACKENDS, default=None)
    p.add_argument("--dir", default=None)
    p.add_argument("--brief-file", default=None)
    _add_who(p)

    p = sub.add_parser("topic-context")
    _add_who(p)

    p = sub.add_parser("session-context")
    _add_who(p)

    p = sub.add_parser("topic-path")
    p.add_argument("--topic", default=None, metavar="TOPIC_ID")
    _add_who(p)

    p = sub.add_parser("topic-note")
    p.add_argument("kind", metavar="asked|posted|answered|closed")
    p.add_argument("--topic", required=True, metavar="TOPIC_ID")
    p.add_argument("--entry", required=True)
    p.add_argument("--title", default=None)
    p.add_argument("--value", default=None)
    p.add_argument("--via", default=None)
    p.add_argument("--state", dest="closed_as", default=None)
    _add_who(p)


def _identity(args: argparse.Namespace) -> tuple[str, str]:
    if args.agent_type and args.session_id:
        return args.agent_type, args.session_id
    if args.session_id:
        raise topics.TopicUsageError("--session-id needs --type")
    for engine, var in SESSION_ENV.items():
        if args.agent_type and engine != args.agent_type:
            continue
        sid = os.environ.get(var)
        if sid:
            return engine, sid
    raise topics.TopicUsageError(
        "no session: pass --type and --session-id, or run inside Claude Code, Codex or Cursor"
    )


def _one(*values: str | None) -> None:
    if sum(v is not None for v in values) != 1:
        raise topics.TopicUsageError("give exactly one of a title or a flag")


def _brief(args: argparse.Namespace) -> str:
    if args.brief_file:
        return Path(args.brief_file).read_text(encoding="utf-8")
    if sys.stdin.isatty():
        raise topics.TopicUsageError("a fork needs a brief: pass --brief-file or pipe it on stdin")
    return sys.stdin.read()


def _dispatch(args: argparse.Namespace):
    cmd = args.cmd
    if cmd == "topics":
        if args.events and not args.tree:
            raise topics.TopicUsageError("--events goes with --tree")
        if args.open:
            return {"topics": topics.open_topics()}
        if args.tree:
            roots = topics.tree(events=args.events, logs=topics.cached_logs())
            return {"tree": liveness.annotate(roots) if args.events else roots}
        if args.session:
            agent_type = args.agent_type or topics.session_type(args.session)
            if not agent_type:
                raise topics.TopicNotFoundError(f"no topic log for session {args.session}")
            session_id = args.session
        else:
            agent_type, session_id = _identity(args)
        return {
            "agent_type": agent_type,
            "session_id": session_id,
            **topics.state(agent_type, session_id),
            "events": topics.read_events(agent_type, session_id),
        }
    if cmd == "topic-path":
        if args.topic:
            path = topics.path_from(args.topic)
            if path is None:
                raise topics.TopicNotFoundError(args.topic)
            return path
        return topics.session_path(*_identity(args))
    if cmd == "topic-note":
        # The inbox passes the asker only when it has one; never guess it from the environment.
        if bool(args.agent_type) != bool(args.session_id):
            raise topics.TopicUsageError("--type and --session-id go together")
        return topics.add_note(
            args.kind, args.topic, args.entry, agent_type=args.agent_type, session_id=args.session_id,
            title=args.title, value=args.value, via=args.via, closed_as=args.closed_as,
        )
    agent_type, session_id = _identity(args)
    if cmd == "intent":
        _one(args.title, args.adopt)
        if args.adopt:
            return topics.adopt(agent_type, session_id, args.adopt)
        return topics.set_intent(agent_type, session_id, args.title)
    if cmd == "topic":
        _one(args.title, args.done, args.park)
        if args.title is not None:
            return topics.open_topic(agent_type, session_id, args.title)
        if args.done is not None:
            done = topics.close_topic(agent_type, session_id, "done", args.done or None)
            return {**done, "open_questions": topics.open_questions(done["topic"]["id"])}
        return topics.close_topic(agent_type, session_id, "parked", args.park or None, ref=args.ref)
    if cmd == "fork":
        return forking.fork(
            agent_type,
            session_id,
            args.title,
            mode="side" if args.side else "new_intent",
            brief_text=_brief(args),
            backend=args.backend,
            directory=args.dir,
        )
    line = topics.context_line(agent_type, session_id)
    if cmd == "session-context":
        core = conversation.core_text()
        return f"{core}\n\n{line}" if core else line
    return line


def _fail(error: object, code: int) -> int:
    print(f"agent-registry: {error}", file=sys.stderr)
    return code


def run(args: argparse.Namespace) -> int:
    try:
        data = _dispatch(args)
    except topics.TopicConflictError as e:
        return _fail(e, EXIT_CONFLICT)
    except topics.TopicNotFoundError as e:
        return _fail(f"topic not found: {e}", EXIT_NOT_FOUND)
    except topics.TopicUsageError as e:
        return _fail(e, EXIT_USAGE)
    except OSError as e:
        return _fail(e, EXIT_IO)
    print(data if isinstance(data, str) else json.dumps(data))
    return EXIT_OK
