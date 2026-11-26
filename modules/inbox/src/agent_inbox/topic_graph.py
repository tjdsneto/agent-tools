"""The Topics page's model: the registry's topic tree checked, then folded into intents, topics
and their timelines, and ordered. No I/O. The outline page renders it; a drawn graph could
render the same views."""
from __future__ import annotations

import shlex
from collections.abc import Iterator
from dataclasses import dataclass, field

STATUSES = ("open", "done", "parked", "forked")
ROLES = ("intent", "topic", "forked")
SESSION_STATES = ("live", "idle", "ended", "unknown")
EVENT_FIELDS = ("entry", "title", "value", "via", "state", "ref")
NOTE_EVENTS = ("asked", "posted", "answered", "closed")
# The text a timeline line shows for each event: a question or report title, an answer, a state, a park ref.
TEXT_OF = {"asked": "title", "posted": "title", "answered": "value", "closed": "state", "parked": "ref"}
# The page indents this many levels; deeper nodes keep this indent and show their depth.
MAX_INDENT = 3
RESUME = {
    "claude": "claude --resume {sid}",
    "codex": "codex resume {sid}",
    "cursor": "cursor-agent --resume {sid}",
}


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _session(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    agent_type, session_id = _text(raw.get("agent_type")), _text(raw.get("session_id"))
    if not agent_type or not session_id:
        return None
    return {
        "agent_type": agent_type,
        "session_id": session_id,
        "role": raw["role"] if raw.get("role") in ROLES else "topic",
        "live": raw.get("live") is True,
        "state": raw["state"] if raw.get("state") in SESSION_STATES else "unknown",
        "directory": _text(raw.get("directory")),
    }


def _event(raw: object) -> dict | None:
    if not isinstance(raw, dict) or not _text(raw.get("event")):
        return None
    return {"event": raw["event"], "at": _text(raw.get("at")), **{key: _text(raw.get(key)) for key in EVENT_FIELDS}}


def _node(raw: object) -> dict | None:
    if not isinstance(raw, dict) or not _text(raw.get("id")):
        return None

    def each(key, check):
        values = raw.get(key)
        return [item for item in map(check, values) if item] if isinstance(values, list) else []

    return {
        "id": raw["id"],
        "title": _text(raw.get("title")),
        "status": raw["status"] if raw.get("status") in STATUSES else "open",
        "sessions": each("sessions", _session),
        "events": each("events", _event),
        "children": each("children", _node),
    }


def clean(data: object) -> list[dict] | None:
    """The tree from `agt registry topics --tree --events` with every field checked, or None when
    the reply isn't one. Agent text stays as written; the page escapes it."""
    if not isinstance(data, dict) or not isinstance(data.get("tree"), list):
        return None
    return [node for node in map(_node, data["tree"]) if node]


def asked_entries(tree: list[dict]) -> list[str]:
    """Every entry asked anywhere in the tree, once each, for one state lookup in the inbox."""
    found: dict[str, None] = {}
    stack = list(tree)
    while stack:
        node = stack.pop()
        for ev in node["events"]:
            if ev["event"] == "asked" and ev["entry"]:
                found.setdefault(ev["entry"])
        stack.extend(node["children"])
    return list(found)


@dataclass
class Line:
    """One timeline line: a log event, or "fork" for a fork opened from this node."""
    event: str
    at: str | None
    text: str | None = None
    entry: str | None = None
    via: str | None = None


@dataclass
class View:
    id: str
    title: str
    kind: str  # "intent" or "topic"
    status: str
    depth: int
    opened_at: str | None
    owners: list[dict]  # the sessions that hold this node as their intent, live first
    lines: list[Line]
    waiting: list[str]  # entries asked on this node that still wait for an answer
    children: list[View] = field(default_factory=list)

    def walk(self) -> Iterator[View]:
        yield self
        for child in self.children:
            yield from child.walk()

    def questions(self) -> int:
        return sum(len(v.waiting) for v in self.walk())

    def open_topics(self) -> int:
        return sum(1 for v in self.walk() if v.kind == "topic" and v.status == "open")

    def parked(self) -> int:
        return sum(1 for v in self.walk() if v.kind == "topic" and v.status == "parked")

    def stray_forks(self) -> int:
        """Forks no session picked up."""
        return sum(1 for v in self.walk() if v.status == "forked")

    def live(self) -> bool:
        return any(s["live"] for v in self.walk() for s in v.owners)

    def needs_you(self) -> bool:
        return self.questions() > 0 or self.stray_forks() > 0

    def finished(self) -> bool:
        return not (self.needs_you() or self.open_topics() or self.parked() or self.live())

    def latest(self) -> str:
        """The newest moment anywhere under this node, for newest-first ordering."""
        return max((line.at for v in self.walk() for line in v.lines if line.at), default="")


def _line(ev: dict) -> Line:
    key = TEXT_OF.get(ev["event"])
    entry = ev["entry"] if ev["event"] in NOTE_EVENTS else None
    return Line(ev["event"], ev["at"], ev[key] if key else None, entry, ev["via"])


def _waiting(events: list[dict], states: dict[str, str]) -> list[str]:
    """Entries asked here with no answer yet. The inbox's own state wins, because the log's notes
    are best effort; an entry the inbox no longer has falls back to the notes."""
    settled = {ev["entry"] for ev in events if ev["event"] in ("answered", "closed") and ev["entry"]}
    asked = dict.fromkeys(ev["entry"] for ev in events if ev["event"] == "asked" and ev["entry"])
    return [entry for entry in asked if (states[entry] == "open" if entry in states else entry not in settled)]


def _view(node: dict, depth: int, states: dict[str, str]) -> View:
    children = sorted(
        (_view(child, depth + 1, states) for child in node["children"]),
        key=lambda v: (v.opened_at is None, v.opened_at or ""),
    )
    lines = [_line(ev) for ev in node["events"]]
    for child in children:
        forked = next((line for line in child.lines if line.event == "forked"), None)
        if forked:
            lines.append(Line("fork", forked.at, child.title))
    lines.sort(key=lambda line: (line.at is None, line.at or ""))
    owners = sorted(
        {(s["agent_type"], s["session_id"]): s for s in node["sessions"] if s["role"] == "intent"}.values(),
        key=lambda s: not s["live"],
    )
    intent = depth == 0 or any(s["role"] in ("intent", "forked") for s in node["sessions"])
    return View(
        id=node["id"],
        title=node["title"] or node["id"],
        kind="intent" if intent else "topic",
        status=node["status"],
        depth=depth,
        opened_at=node["events"][0]["at"] if node["events"] else None,
        owners=owners,
        lines=lines,
        waiting=_waiting(node["events"], states),
        children=children,
    )


def build(tree: list[dict], states: dict[str, str]) -> list[View]:
    """One view per root. states maps an entry id to its state in the inbox."""
    return [_view(node, 0, states) for node in tree]


def order(views: list[View]) -> tuple[list[View], list[View]]:
    """(shown, finished). Shown: intents that need Tiago first (a question waiting, or a fork no
    session picked up), then those with open topics, then the rest. Newest activity first in each,
    and in finished."""
    newest = sorted(views, key=View.latest, reverse=True)
    shown = [v for v in newest if not v.finished()]
    shown.sort(key=lambda v: 0 if v.needs_you() else 1 if v.open_topics() else 2)
    return shown, [v for v in newest if v.finished()]


def resume_command(session: dict) -> str | None:
    """The shell line that resumes this session where it ran, or None for an engine without one."""
    template = RESUME.get(session["agent_type"])
    if not template:
        return None
    command = template.format(sid=shlex.quote(session["session_id"]))
    directory = session.get("directory")
    return f"cd {shlex.quote(directory)} && {command}" if directory else command
