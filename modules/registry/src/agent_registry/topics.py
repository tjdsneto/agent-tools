"""Per-session topic log: a session's intent and the topics it opened under it."""
from __future__ import annotations

import fcntl
import json
import os
import secrets
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from agent_registry.constants import TOPIC_ALPHABET, TOPIC_ID_LEN, TOPIC_ID_PREFIX
from agent_registry.models import now_iso
from agent_registry.store import registry_path

# Events that create a topic id; the session whose log holds one owns that topic.
MINTING = ("intent", "topic", "forked")
CLOSING = ("done", "parked", "forked")
# Inbox activity a topic's history records. A note never opens, closes or re-dates a topic.
NOTE_KINDS = ("asked", "posted", "answered", "closed")
NOTE_VIAS = ("web", "telegram", "chat", "cli")
NOTE_CLOSED_STATES = ("withdrawn", "expired", "superseded")
NOTE_VALUE_MAX = 200
NOTE_FIELDS = ("entry", "title", "value", "via", "state")

# Parsed logs for `topics --tree`, kept beside them. Bump the version when read_events changes what it keeps.
CACHE_NAME = ".parsed.json"
CACHE_VERSION = 1


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
        if "parent" in event and not (isinstance(event["parent"], str) and event["parent"]):
            del event["parent"]
        if "at" in event and not isinstance(event["at"], str):
            event["at"] = None
        if event.get("event") in NOTE_KINDS and not (isinstance(event.get("entry"), str) and event["entry"]):
            continue  # a note must name its inbox entry
        if event.get("event") in NOTE_KINDS:
            for key in ("title", "value", "via", "state"):
                if key in event and not isinstance(event[key], str):
                    event[key] = None
            if event.get("value") is not None:
                event["value"] = event["value"][:NOTE_VALUE_MAX]
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


def _load_cache() -> dict[str, dict]:
    try:
        data = json.loads((topics_dir() / CACHE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION or not isinstance(data.get("logs"), dict):
        return {}
    return {
        key: hit for key, hit in data["logs"].items()
        if isinstance(hit, dict) and isinstance(hit.get("sig"), list) and isinstance(hit.get("events"), list)
        and all(isinstance(e, dict) for e in hit["events"])
    }


def _save_cache(logs: dict[str, dict]) -> None:
    """Replace the cache atomically. A failure is ignored: the cache only saves work."""
    root = topics_dir()
    try:
        fd, tmp = tempfile.mkstemp(dir=root, prefix=".parsed.", suffix=".tmp")
    except OSError:
        return
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"version": CACHE_VERSION, "logs": logs}, f)
        os.replace(tmp, root / CACHE_NAME)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def cached_logs() -> list[tuple[str, str, list[dict]]]:
    """Every log's events, like _all_logs, but a log whose modification time and size match the
    cache isn't read again. Each CLI call is a new process, so the cache is a file. Each log is
    stat'ed before it's read, so one that changes mid-read is read again next time."""
    root = topics_dir()
    if not root.exists():
        return []
    cache = _load_cache()
    fresh: dict[str, dict] = {}
    out: list[tuple[str, str, list[dict]]] = []
    changed = False
    for path in sorted(root.glob("*/*.jsonl")):
        key = f"{path.parent.name}/{path.name}"
        try:
            st = path.stat()
        except FileNotFoundError:
            continue
        sig = [st.st_mtime_ns, st.st_size]
        hit = cache.get(key)
        if hit and hit["sig"] == sig:
            events = hit["events"]
        else:
            events = read_events(path.parent.name, path.stem)
            changed = True
        fresh[key] = {"sig": sig, "events": events}
        out.append((path.parent.name, path.stem, events))
    if changed or fresh.keys() != cache.keys():
        _save_cache(fresh)
    return out


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


def _note_view(ev: dict) -> dict:
    return {"event": ev["event"], "at": ev.get("at"), **{k: ev[k] for k in NOTE_FIELDS if k in ev}}


def _replay(events: list[dict]) -> dict:
    """Fold a log into the session's intent, its current topic, and every topic it touched.

    Inbox notes are history: each lands in its topic's `notes`, and none of them changes a
    status, an `at`, or which topics the session touched."""
    intent = None
    current = None
    seen: dict[str, dict] = {}
    for ev in events:
        kind = ev.get("event")
        tid = ev["topic"].get("id")
        if not tid:
            continue
        if kind in NOTE_KINDS:
            if tid in seen:
                seen[tid]["notes"].append(_note_view(ev))
            continue
        entry = seen.setdefault(tid, {
            "id": tid, "title": ev["topic"].get("title"), "parent": None, "status": "open", "at": None, "notes": [],
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


def _index() -> tuple[dict[str, dict], set[str]]:
    """One pass over every log: each minted topic (the first minting event wins, as in
    find_topic) and the ids some session holds as its intent."""
    minted: dict[str, dict] = {}
    intents: set[str] = set()
    for _agent_type, _session_id, events in _all_logs():
        for ev in events:
            tid = ev["topic"]["id"]
            if ev.get("event") in MINTING and tid not in minted:
                minted[tid] = {"title": ev["topic"].get("title"), "parent": ev.get("parent")}
        held = _replay(events)["intent"]
        if held:
            intents.add(held["id"])
    return minted, intents


def path_from(topic_id: str) -> list[dict] | None:
    """The topic and its ancestors, root first, as {id, title, kind}. A missing parent or a
    cycle ends the walk. None when the topic itself was never minted."""
    minted, intents = _index()
    chain: list[dict] = []
    seen: set[str] = set()
    tid: str | None = topic_id
    while tid and tid in minted and tid not in seen:
        seen.add(tid)
        node = minted[tid]
        chain.append({"id": tid, "title": node["title"], "kind": "intent" if tid in intents else "topic"})
        tid = node["parent"]
    return list(reversed(chain)) or None


def session_path(agent_type: str, session_id: str) -> list[dict] | None:
    """Root intent down to the session's current topic, or to its intent when it has none."""
    st = state(agent_type, session_id)
    if not st["intent"]:
        return None
    return path_from((st["topic"] or st["intent"])["id"])


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
                "sessions": [], "children": [], "notes": [],
            })
            node["notes"].extend(t["notes"])
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
        node["notes"].sort(key=lambda n: (n.get("at") is None, n.get("at") or ""))
        parent = nodes.get(node["parent"]) if node["parent"] else None
        (parent["children"] if parent else roots).append(node)
    return roots


def _note_log(topic_id: str, agent_type: str | None, session_id: str | None) -> tuple[str, str, str | None] | None:
    """The asking session's log when it holds the topic, else the log of the session that minted it."""
    if agent_type and session_id:
        held = next((t for t in state(agent_type, session_id)["topics"] if t["id"] == topic_id), None)
        if held:
            return agent_type, session_id, held["title"]
    found = find_topic(topic_id)
    if found:
        return found["agent_type"], found["session_id"], found["title"]
    return None


def add_note(
    kind: str, topic_id: str, entry: str, *, agent_type: str | None = None, session_id: str | None = None,
    title: str | None = None, value: str | None = None, via: str | None = None, closed_as: str | None = None,
) -> dict:
    """Record inbox activity on a topic: asked or posted (title), answered (value, via), closed (state)."""
    if kind not in NOTE_KINDS:
        raise TopicUsageError(f"note kind must be one of {', '.join(NOTE_KINDS)}")
    entry = (entry or "").strip()
    if not entry:
        raise TopicUsageError("a note needs --entry")
    fields: dict = {"entry": entry}
    if kind in ("asked", "posted"):
        fields["title"] = _title(title)
    elif kind == "answered":
        if value is None:
            raise TopicUsageError("an answered note needs --value")
        if via not in NOTE_VIAS:
            raise TopicUsageError(f"--via must be one of {', '.join(NOTE_VIAS)}")
        fields.update(value=value[:NOTE_VALUE_MAX], via=via)
    else:
        if closed_as not in NOTE_CLOSED_STATES:
            raise TopicUsageError(f"--state must be one of {', '.join(NOTE_CLOSED_STATES)}")
        fields["state"] = closed_as
    with _locked():
        where = _note_log(topic_id, agent_type, session_id)
        if where is None:
            raise TopicNotFoundError(topic_id)
        log_type, log_session, topic_title = where
        return _append(log_type, log_session, {
            "event": kind, "at": now_iso(), "topic": {"id": topic_id, "title": topic_title}, **fields,
        })


def open_questions(topic_id: str) -> list[str]:
    """Entries asked under the topic, in any log, with no answered or closed note yet."""
    asked: list[str] = []
    settled: set[str] = set()
    for _agent_type, _session_id, events in _all_logs():
        for ev in events:
            if ev["topic"]["id"] != topic_id:
                continue
            if ev.get("event") == "asked" and ev["entry"] not in asked:
                asked.append(ev["entry"])
            elif ev.get("event") in ("answered", "closed"):
                settled.add(ev["entry"])
    return [entry for entry in asked if entry not in settled]
