"""Seed agent_inbox_test with topic-aware entries for the screenshot check. Not a test.

Run from modules/inbox:
    AGENT_INBOX_DSN="host=localhost port=5433 dbname=agent_inbox_test" AGENT_INBOX_TELEGRAM_TO= \
        PYTHONPATH=src .venv/bin/python tests/visual/seed_topics.py
It drops and recreates the test tables, then prints {title: id} as JSON."""
from __future__ import annotations

import json
import os
import re
import sys

import psycopg
from psycopg.types.json import Jsonb

from agent_inbox import db, store, topics
from agent_inbox.validate import validate_request

ROOT = {"id": "tp-r00t", "title": "Topic awareness for AI sessions", "kind": "intent"}
PLAN = {"id": "tp-p1an", "title": "Write the inbox plan", "kind": "topic"}
FORK = {"id": "tp-f0rk", "title": "Manual check: the Cursor fork targets the right project window", "kind": "intent"}
CHECK = {"id": "tp-chk2", "title": "Check window targeting", "kind": "topic"}
STYLE = {"id": "tp-sty1", "title": "Inbox restyle", "kind": "intent"}
EVIL = {"id": "tp-ev1l", "title": '<img src=x onerror="alert(1)">', "kind": "intent"}
CHOICE = {"type": "choice", "options": [
    {"id": "a", "label": "Merge now", "recommended": True}, {"id": "b", "label": "Wait for the restart"},
]}

# (kind, title, path, cwd, then)
SEED = [
    ("ask", "Merge the registry refactor before the inbox restart?", [ROOT, PLAN], "/x/agent-tools", None),
    ("ask", "Is the Cursor tab opening in the right project window?", [ROOT, PLAN, FORK, CHECK], "/x/agent-tools", None),
    ("post", "Plan written, registry tasks first", [ROOT, PLAN], "/x/agent-tools", None),
    ("post", "Fork brief saved", [ROOT, PLAN, FORK], "/x/agent-tools", None),
    ("post", "Window targeting notes", [ROOT, PLAN, FORK, CHECK], "/x/agent-tools", None),
    ("ask", "Keep the 12px context line or go to 13px?", [STYLE], "/x/agent-tools", "answer"),
    ("post", "Restyle screenshots ready", [STYLE], "/x/agent-tools", None),
    ("post", "Escaping check", [EVIL], "/x/lindris", None),
    ("post", "Nightly backup finished", None, None, "script"),
    ("ask", "Old question from before topics", None, "/x/am-videos", None),
]


def main() -> None:
    dsn = os.environ.get("AGENT_INBOX_DSN", "")
    # The database name, not the whole string: a host or user could contain the words too.
    named = re.search(r"dbname=(\S+)", dsn) or re.match(r"postgres(?:ql)?://[^/]*/([^?\s]+)", dsn)
    if not named or "agent_inbox_test" not in named.group(1):
        sys.exit("refusing: AGENT_INBOX_DSN must name a database containing agent_inbox_test")
    topics.registry = lambda *args: None  # never touch the real registry; paths are set below
    with psycopg.connect(dsn, autocommit=True) as raw:
        raw.execute("DROP TABLE IF EXISTS events, entries, ops CASCADE")
    made = {}
    with db.connect() as conn:
        for kind, title, path, cwd, then in SEED:
            body = {"title": title, "summary": "Seeded for the topic-aware screenshot check."}
            if kind == "ask":
                body["control"] = CHOICE
            req = validate_request(body, kind)
            if then == "script":
                entry = store.create_entry(conn, kind, req, script="nightly-backup")
            else:
                entry = store.create_entry(conn, kind, req, engine="claude", session_id="seed-1", cwd=cwd)
            if path:
                conn.execute("UPDATE entries SET topic_path = %s WHERE id = %s", (Jsonb(path), entry["id"]))
            if then == "answer":
                store.answer(conn, entry["id"], "a", via="chat")
            made[title] = entry["id"]
    print(json.dumps(made, indent=2))


if __name__ == "__main__":
    main()
