"""Topic paths on feed rows: the context line, the intent filter and Group by. No I/O."""
from __future__ import annotations

from dataclasses import dataclass, field

GROUPS = ("none", "intent", "tree")
NO_TOPIC = "No topic"


def path_of(row: dict) -> list[dict]:
    path = row.get("topic_path")
    if not isinstance(path, list):
        return []
    return [node for node in path if isinstance(node, dict) and node.get("id")]


def name(node: dict) -> str:
    return node.get("title") or node["id"]


def context(path: list[dict]) -> tuple[str, str] | None:
    """The row's context line (the last two names) and the full path for its title attribute."""
    if not path:
        return None
    names = [name(node) for node in path]
    shown = " › ".join(names[-2:])
    return ("… › " + shown if len(names) > 2 else shown), " › ".join(names)


def intent_of(path: list[dict]) -> dict | None:
    """The asking session's own intent: the last node some session holds as its intent."""
    for node in reversed(path):
        if node.get("kind") == "intent":
            return node
    return path[0] if path else None


def intents_in(rows: list[dict]) -> list[tuple[str, str]]:
    """(id, title) of every intent in these rows, in feed order."""
    found: dict[str, str] = {}
    for row in rows:
        node = intent_of(path_of(row))
        if node and node["id"] not in found:
            found[node["id"]] = name(node)
    return list(found.items())


def only_intent(rows: list[dict], intent_id: str | None) -> list[dict]:
    if not intent_id:
        return rows
    return [row for row in rows if (intent_of(path_of(row)) or {}).get("id") == intent_id]


@dataclass
class Group:
    key: str | None  # the intent or root topic id; None for the No topic section
    title: str
    lead: dict  # the first row that landed here; the heading names its project
    rows: list[dict] = field(default_factory=list)
    subs: list[Group] = field(default_factory=list)

    def has_question(self) -> bool:
        mine = any(row["kind"] == "ask" and row["state"] == "open" for row in self.rows)
        return mine or any(sub.has_question() for sub in self.subs)


def _ordered(groups: list[Group]) -> list[Group]:
    """Feed order, except that sections holding an open question lead and No topic comes last."""
    return sorted(groups, key=lambda g: (g.key is None, not g.has_question()))


def group_rows(rows: list[dict], mode: str) -> list[Group]:
    """intent: one section per asking intent. tree: one per root, forked intents nested one level."""
    top: dict[str | None, Group] = {}
    for row in rows:
        path = path_of(row)
        if not path:
            top.setdefault(None, Group(None, NO_TOPIC, row)).rows.append(row)
            continue
        intent = intent_of(path)
        if mode != "tree":
            top.setdefault(intent["id"], Group(intent["id"], name(intent), row)).rows.append(row)
            continue
        root = path[0]
        section = top.setdefault(root["id"], Group(root["id"], name(root), row))
        if intent["id"] == root["id"]:
            section.rows.append(row)
            continue
        sub = next((s for s in section.subs if s.key == intent["id"]), None)
        if sub is None:
            sub = Group(intent["id"], name(intent), row)
            section.subs.append(sub)
        sub.rows.append(row)
    for section in top.values():
        section.subs = _ordered(section.subs)
    return _ordered(list(top.values()))
