"""Helpers for the Topics page tests: builders for registry-shaped tree nodes, and a reader for
the page's nesting. Standard library only, so the black-box suite uses the reader too."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser


def at(minutes: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def ev(event: str, minutes: float, **fields) -> dict:
    return {"event": event, "at": at(minutes), "agent_type": "claude", "session_id": "s-1", **fields}


def sess(session_id: str, state: str = "ended", role: str = "intent", agent: str = "claude",
         directory: str | None = "/x/agent-tools") -> dict:
    return {
        "agent_type": agent, "session_id": session_id, "role": role,
        "live": state == "live", "state": state, "directory": directory,
    }


def node(nid: str, title: str | None, *, status: str = "open", sessions=(), events=(), children=()) -> dict:
    return {
        "id": nid, "title": title, "status": status,
        "sessions": list(sessions), "events": list(events), "children": list(children),
    }


class Nesting(HTMLParser):
    """parent: the node each data-topic node sits in (None at the top). text and links: what each
    node holds itself, not counting the nodes nested in it."""

    def __init__(self):
        super().__init__()
        self.stack: list[str | None] = []  # one per open <li>; None for an li that isn't a node
        self.parent: dict[str, str | None] = {}
        self.text: dict[str, str] = {}
        self.links: dict[str, list[str]] = {}

    def _here(self) -> str | None:
        return next((nid for nid in reversed(self.stack) if nid), None)

    def handle_starttag(self, tag, attrs):
        here = self._here()
        if tag == "a" and here:
            self.links[here].append(dict(attrs).get("href") or "")
        if tag != "li":
            return
        nid = dict(attrs).get("data-topic")
        if nid:
            self.parent[nid] = here
            self.text[nid] = ""
            self.links[nid] = []
        self.stack.append(nid)

    def handle_endtag(self, tag):
        if tag == "li" and self.stack:
            self.stack.pop()

    def handle_data(self, data):
        here = self._here()
        if here:
            self.text[here] += data


def nesting(html: str) -> Nesting:
    reader = Nesting()
    reader.feed(html)
    return reader
