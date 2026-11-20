from __future__ import annotations

def _fmt_active(seconds: float) -> str:
    """Human active duration; empty under a minute so idle rows stay clean."""
    total = int(seconds or 0)
    if total < 60:
        return ""
    minutes = total // 60
    if minutes < 60:
        return f"{minutes}m"
    return f"{minutes // 60}h{minutes % 60:02d}m"

def _line(s: dict, *, indent: str = "") -> str:
    bits = [s.get("agent_type") or "?", s.get("session_id") or "?", s.get("status") or "?"]
    if s.get("model"):
        bits.append(s["model"])
    if (s.get("title") or "").strip():
        bits.append(s["title"].strip())
    elif (s.get("summary") or "").strip():
        bits.append(s["summary"].strip())
    pr = s.get("pr") or {}
    if pr.get("title"):
        bits.append(f'PR:"{pr["title"]}"')
    if s.get("issue"):
        bits.append(f'issue:{s["issue"]}')
    if s.get("branch"):
        bits.append(f'branch:{s["branch"]}')
    if s.get("goflow_timer_id"):
        bits.append(f'goflow:{s["goflow_timer_id"]}')
    active = _fmt_active(s.get("active_seconds") or 0)
    if active:
        bits.append(f"active:{active}")
    if s.get("peer_name"):
        bits.append(f'peer:{s["peer_name"]}')
    if s.get("directory"):
        bits.append(s["directory"])
    return indent + " · ".join(str(b) for b in bits)

def _ordered_roots(sessions: list[dict]) -> list[tuple[dict, list[dict]]]:
    by_sid = {s["session_id"]: s for s in sessions}
    children: dict[str, list[dict]] = {}
    for s in sessions:
        parent = s.get("parent_session_id")
        if parent and parent in by_sid:
            children.setdefault(parent, []).append(s)
    ordered: list[tuple[dict, list[dict]]] = []
    seen: set[str] = set()
    for s in sessions:
        sid = s["session_id"]
        if sid in seen:
            continue
        parent = s.get("parent_session_id")
        if parent and parent in by_sid:
            continue
        if parent and parent not in by_sid:
            annotated = dict(s)
            annotated["_orphan_parent"] = parent
            ordered.append((annotated, []))
            seen.add(sid)
            continue
        kids = children.get(sid, [])
        ordered.append((s, kids))
        seen.add(sid)
        for k in kids:
            seen.add(k["session_id"])
            # mark nested grandchildren as seen when flattening recursively below
            stack = list(children.get(k["session_id"], []))
            while stack:
                n = stack.pop()
                if n["session_id"] in seen:
                    continue
                seen.add(n["session_id"])
                stack.extend(children.get(n["session_id"], []))
    return ordered, children


def _section(title: str, sessions: list[dict]) -> list[str]:
    lines = [title]
    if not sessions:
        lines.append("  (none)")
        return lines
    roots, children = _ordered_roots(sessions)

    def walk(node: dict, depth: int) -> None:
        indent = "  " * depth
        if depth == 0 and node.get("_orphan_parent"):
            lines.append(_line(node, indent=indent) + f"  parent:{node['_orphan_parent']}")
        else:
            lines.append(_line(node, indent=indent))
        for kid in children.get(node["session_id"], []):
            walk(kid, depth + 1)

    for root, _kids in roots:
        walk(root, 0)
    return lines

def format_list(active: list[dict], stale: list[dict]) -> str:
    lines = _section("Active", active) + [""] + _section("Stale", stale)
    return "\n".join(lines) + "\n"

def format_archive_list(events: list[dict]) -> str:
    if not events:
        return "(none)\n"
    lines: list[str] = []
    for e in events:
        sess = e.get("session") or {}
        bits = [
            e.get("archived_at") or "?",
            e.get("reason") or "?",
            sess.get("agent_type") or "?",
            sess.get("session_id") or "?",
            sess.get("directory") or "?",
        ]
        lines.append(" · ".join(str(b) for b in bits))
    return "\n".join(lines) + "\n"
