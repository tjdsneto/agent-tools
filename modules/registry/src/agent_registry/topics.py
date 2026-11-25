"""Per-session topic log: a session's intent and the topics it opened under it."""
from __future__ import annotations

import fcntl
import json
import os
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from agent_registry.constants import TOPIC_ALPHABET, TOPIC_ID_LEN, TOPIC_ID_PREFIX
from agent_registry.models import now_iso
from agent_registry.store import registry_path

# Events that create a topic id; the session whose log holds one owns that topic.
MINTING = ("intent", "topic", "forked")
CLOSING = ("done", "parked", "forked")


class TopicUsageError(Exception):
    pass


class NoIntentError(TopicUsageError):
    pass


class TopicConflictError(Exception):
    pass


class TopicNotFoundError(Exception):
    pass


def topics_dir() -> Path:
    return registry_path().parent / "topics"


def briefs_dir() -> Path:
    return registry_path().parent / "briefs"


def _safe(part: str) -> str:
    return part.strip().replace("/", "_")


def log_path(agent_type: str, session_id: str) -> Path:
    return topics_dir() / _safe(agent_type) / f"{_safe(session_id)}.jsonl"


@contextmanager
def _locked():
    """One lock for every topic log, so an id is minted and written before another mint reads."""
    lock = topics_dir() / ".lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a+", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def read_events(agent_type: str, session_id: str) -> list[dict]:
    path = log_path(agent_type, session_id)
    root = topics_dir()
    if root.exists() and not os.access(root, os.R_OK | os.X_OK):
        raise PermissionError(f"topics dir not readable: {root}")
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue  # a torn line never hides the rest of the log
        if not isinstance(event, dict) or not isinstance(event.get("topic"), dict):
            continue
        topic = event["topic"]
        tid = topic.get("id")
        if not isinstance(tid, str) or not tid:
            continue
        if topic.get("title") is not None and not isinstance(topic["title"], str):
            continue
        events.append(event)
    return events


def _append(agent_type: str, session_id: str, event: dict) -> dict:
    path = log_path(agent_type, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "ab+") as f:
        # A crash can leave a last line with no newline; start a fresh line so it can't swallow this event.
        f.seek(0, 2)
        if f.tell() > 0:
            f.seek(-1, 2)
            if f.read(1) != b"\n":
                f.write(b"\n")
        f.write((json.dumps(event) + "\n").encode("utf-8"))
    return event


def _all_logs() -> Iterator[tuple[str, str, list[dict]]]:
    root = topics_dir()
    if not root.exists():
        return
    for path in sorted(root.glob("*/*.jsonl")):
        yield path.parent.name, path.stem, read_events(path.parent.name, path.stem)


def _mint() -> str:
    taken = {ev["topic"].get("id") for _, _, events in _all_logs() for ev in events}
    while True:
        tid = TOPIC_ID_PREFIX + "".join(secrets.choice(TOPIC_ALPHABET) for _ in range(TOPIC_ID_LEN))
        if tid not in taken:
            return tid


def _title(value: str | None) -> str:
    title = (value or "").strip()
    if not title:
        raise TopicUsageError("a title is required")
    return title


def _replay(events: list[dict]) -> dict:
    """Fold a log into the session's intent, its current topic, and every topic it touched."""
    intent = None
    current = None
    seen: dict[str, dict] = {}
    for ev in events:
        kind = ev.get("event")
        tid = ev["topic"].get("id")
        if not tid:
            continue
        entry = seen.setdefault(tid, {
            "id": tid, "title": ev["topic"].get("title"), "parent": None, "status": "open", "at": None,
        })
        if ev.get("parent"):
            entry["parent"] = ev["parent"]
        entry["at"] = ev.get("at")
        if kind in ("intent", "adopt"):
            intent = {"id": tid, "title": entry["title"]}
        elif kind == "topic":
            current = {"id": tid, "title": entry["title"]}
        if kind in CLOSING:
            entry["status"] = kind
            if current and current["id"] == tid:
                current = None
    return {"intent": intent, "topic": current, "topics": list(seen.values())}


def state(agent_type: str, session_id: str) -> dict:
    return _replay(read_events(agent_type, session_id))


def find_topic(topic_id: str) -> dict | None:
    for agent_type, session_id, events in _all_logs():
        for ev in events:
            if ev["topic"].get("id") == topic_id and ev.get("event") in MINTING:
                return {
                    "id": topic_id,
                    "title": ev["topic"].get("title"),
                    "parent": ev.get("parent"),
                    "agent_type": agent_type,
                    "session_id": session_id,
                }
    return None


def set_intent(agent_type: str, session_id: str, title: str) -> dict:
    title = _title(title)
    with _locked():
        if state(agent_type, session_id)["intent"]:
            raise TopicConflictError("this session already has an intent")
        return _append(agent_type, session_id, {
            "event": "intent", "at": now_iso(), "topic": {"id": _mint(), "title": title},
        })


def adopt(agent_type: str, session_id: str, topic_id: str) -> dict:
    with _locked():
        if state(agent_type, session_id)["intent"]:
            raise TopicConflictError("this session already has an intent")
        found = find_topic(topic_id)
        if not found:
            raise TopicNotFoundError(topic_id)
        return _append(agent_type, session_id, {
            "event": "adopt",
            "at": now_iso(),
            "topic": {"id": found["id"], "title": found["title"]},
            "from_session": found["session_id"],
        })


def open_topic(agent_type: str, session_id: str, title: str) -> dict:
    title = _title(title)
    with _locked():
        st = state(agent_type, session_id)
        if not st["intent"]:
            raise NoIntentError('set an intent first: agt registry intent "<title>"')
        return _append(agent_type, session_id, {
            "event": "topic",
            "at": now_iso(),
            "topic": {"id": _mint(), "title": title},
            "parent": st["intent"]["id"],
        })


def close_topic(
    agent_type: str, session_id: str, kind: str, topic_id: str | None = None, *, ref: str | None = None,
) -> dict:
    if kind not in ("done", "parked"):
        raise TopicUsageError(f"unknown close kind {kind}")
    with _locked():
        st = state(agent_type, session_id)
        if topic_id is None:
            target = st["topic"]
            if not target:
                raise TopicNotFoundError("no current topic")
        else:
            target = next((t for t in st["topics"] if t["id"] == topic_id), None)
            if not target:
                raise TopicNotFoundError(topic_id)
        event = {"event": kind, "at": now_iso(), "topic": {"id": target["id"], "title": target["title"]}}
        if ref:
            event["ref"] = ref
        return _append(agent_type, session_id, event)


FORK_MODES = ("side", "new_intent")


def record_fork(
    agent_type: str, session_id: str, title: str, *, mode: str, backend: str, brief_text: str,
) -> dict:
    """Mint the child topic, write its brief, and log the hand-off in the parent session."""
    title = _title(title)
    if mode not in FORK_MODES:
        raise TopicUsageError(f"mode must be one of {', '.join(FORK_MODES)}")
    if not (brief_text or "").strip():
        raise TopicUsageError("a fork needs a brief: pass --brief-file or pipe it on stdin")
    with _locked():
        st = state(agent_type, session_id)
        if not st["intent"]:
            raise NoIntentError('set an intent first: agt registry intent "<title>"')
        parent = (st["topic"] or st["intent"])["id"]
        tid = _mint()
        brief = briefs_dir() / f"{tid}.md"
        brief.parent.mkdir(parents=True, exist_ok=True)
        brief.write_text(brief_text, encoding="utf-8")
        return _append(agent_type, session_id, {
            "event": "forked",
            "at": now_iso(),
            "topic": {"id": tid, "title": title},
            "parent": parent,
            "mode": mode,
            "backend": backend,
            "brief": str(brief),
        })


def current(agent_type: str, session_id: str) -> dict:
    """Intent and topic for a live row. An unreadable log shows as none, never as an error."""
    try:
        st = state(agent_type, session_id)
    except OSError:
        return {"intent": None, "topic": None}
    return {"intent": st["intent"], "topic": st["topic"]}


def context_line(agent_type: str, session_id: str) -> str:
    st = state(agent_type, session_id)
    if not st["intent"]:
        return (
            "No intent set for this session. Once the first prompt makes it clear, "
            'set it: agt registry intent "<title>".'
        )
    intent = st["intent"]
    topic = f"{st['topic']['title']} ({st['topic']['id']})" if st["topic"] else "none"
    return (
        f"Intent: {intent['title']} ({intent['id']}) · Topic: {topic}. "
        "If this prompt changes the subject, run the topic-awareness drift check."
    )


def session_type(session_id: str) -> str | None:
    root = topics_dir()
    if not root.exists():
        return None
    for path in sorted(root.glob(f"*/{_safe(session_id)}.jsonl")):
        return path.parent.name
    return None


def open_topics() -> list[dict]:
    rows = []
    for agent_type, session_id, events in _all_logs():
        st = _replay(events)
        for t in st["topics"]:
            if t["status"] == "open":
                rows.append({
                    "id": t["id"], "title": t["title"], "parent": t["parent"],
                    "agent_type": agent_type, "session_id": session_id,
                    "is_intent": bool(st["intent"] and st["intent"]["id"] == t["id"]),
                })
    return rows


def tree() -> list[dict]:
    """Every topic across sessions as nested nodes. A topic's status is its latest event's."""
    nodes: dict[str, dict] = {}
    latest: dict[str, str] = {}
    for agent_type, session_id, events in _all_logs():
        st = _replay(events)
        for t in st["topics"]:
            node = nodes.setdefault(t["id"], {
                "id": t["id"], "title": t["title"], "parent": None, "status": t["status"],
                "sessions": [], "children": [],
            })
            if t["parent"]:
                node["parent"] = t["parent"]
            if (t["at"] or "") >= latest.get(t["id"], ""):
                latest[t["id"]] = t["at"] or ""
                node["status"] = t["status"]
            if t["status"] == "forked":
                role = "forked"
            elif st["intent"] and st["intent"]["id"] == t["id"]:
                role = "intent"
            else:
                role = "topic"
            node["sessions"].append({"agent_type": agent_type, "session_id": session_id, "role": role})
    roots = []
    for node in nodes.values():
        parent = nodes.get(node["parent"]) if node["parent"] else None
        (parent["children"] if parent else roots).append(node)
    return roots
