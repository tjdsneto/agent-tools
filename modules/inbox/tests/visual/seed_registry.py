"""Seed a scratch agent registry for the Topics screenshots. Not a test.

Run from modules/inbox, after seed_topics.py:
    .venv/bin/python tests/visual/seed_registry.py <registry-dir> <seed.json>
<registry-dir> must be new or empty. It gets registry.json, archive.jsonl and topics/ in the
registry's own file formats, with times relative to now. <seed.json> is seed_topics.py's
{title: id} output, so the notes link to the seeded entries. It never imports agent_registry,
and it refuses the live registry directory."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

NOW = datetime.now(timezone.utc)
LIVE = Path.home() / ".local" / "share" / "agent-registry"
TOOLS = str(Path.home() / "projects" / "agent-tools")
LINDRIS = str(Path.home() / "projects" / "lindris-monorepo")

# A is live; B and F are idle (no ping for over an hour); the rest have ended. D is in the archive.
A = "9f1c2d3e-0a4b-4c5d-8e6f-7a8b9c0d1e2f"
B = "4b7e9a1c-2d3f-4e5a-9b6c-1d2e3f4a5b6c"
C = "019a7c3e-5d4b-7f21-9e8d-3c2b1a0f9e8d"
D = "c3d4e5f6-a7b8-4c9d-8e0f-1a2b3c4d5e6f"
E = "e5f6a7b8-c9d0-4e1f-8a2b-3c4d5e6f7a8b"
F = "f6a7b8c9-d0e1-4f2a-9b3c-4d5e6f7a8b9c"
G = ("0b1c2d3e-4f5a-4b6c-8d7e-9f0a1b2c3d4e", "1c2d3e4f-5a6b-4c7d-9e8f-0a1b2c3d4e5f", "019a0000-1111-7222-8333-444455556666")
EVIL = '<img src=x onerror="alert(1)">'


def at(minutes: float) -> str:
    return (NOW - timedelta(minutes=minutes)).isoformat()


def ev(event: str, minutes: float, tid: str, name: str, **extra) -> dict:
    return {"event": event, "at": at(minutes), "topic": {"id": tid, "title": name}, **extra}


def row(agent_type: str, session_id: str, directory: str, minutes: float, status: str = "idle") -> dict:
    return {
        "registry_id": f"seed-{session_id[:8]}", "session_id": session_id, "agent_type": agent_type, "directory": directory,
        "parent_session_id": None, "status": status, "summary": "", "issue": None, "pr": None, "branch": None,
        "goflow_timer_id": None, "registered_at": at(minutes + 30), "last_ping": at(minutes), "updated_at": at(minutes),
    }


def logs(ids: dict[str, str]) -> dict[tuple[str, str], list[dict]]:
    def note(kind: str, minutes: float, tid: str, name: str, entry: str, **extra) -> dict:
        fields = {"title": entry} if kind in ("asked", "posted") else {}
        return ev(kind, minutes, tid, name, entry=ids[entry], **fields, **extra)

    root, spec, plan = "Topic awareness for AI sessions", "Spec 2: topic-aware inbox design", "Write the inbox plan"
    fork, check = "Manual check: the Cursor fork targets the right project window", "Check window targeting"
    deep, deeper = "Retry the Herdr pane split", "Read the pane ids from herdr list"
    style, size = "Inbox restyle", "Context line size"
    lindris, side = "Lindris production page: generated files", "Generated files section (design question)"
    merge = "Merge the registry refactor before the inbox restart?"
    cursor_q = "Is the Cursor tab opening in the right project window?"
    keep = "Keep the 12px context line or go to 13px?"
    return {
        ("claude", A): [
            ev("intent", 300, "tp-r00t", root),
            ev("topic", 290, "tp-d0ne", spec, parent="tp-r00t"),
            ev("done", 240, "tp-d0ne", spec),
            ev("topic", 200, "tp-p1an", plan, parent="tp-r00t"),
            note("asked", 150, "tp-p1an", plan, merge),
            note("posted", 120, "tp-p1an", plan, "Plan written, registry tasks first"),
            ev("forked", 100, "tp-f0rk", fork, parent="tp-p1an", mode="side", backend="cursor"),
        ],
        ("claude", B): [
            ev("adopt", 95, "tp-f0rk", fork, from_session=A),
            note("posted", 92, "tp-f0rk", fork, "Fork brief saved"),
            ev("topic", 90, "tp-chk2", check, parent="tp-f0rk"),
            note("asked", 80, "tp-chk2", check, cursor_q),
            note("posted", 70, "tp-chk2", check, "Window targeting notes"),
            ev("forked", 60, "tp-dp01", deep, parent="tp-chk2", mode="side", backend="herdr"),
        ],
        ("codex", C): [
            ev("adopt", 55, "tp-dp01", deep, from_session=B),
            ev("topic", 50, "tp-dp02", deeper, parent="tp-dp01"),
        ],
        ("claude", D): [
            ev("intent", 1500, "tp-sty1", style),
            ev("topic", 1490, "tp-sty2", size, parent="tp-sty1"),
            note("asked", 1480, "tp-sty2", size, keep),
            note("answered", 1400, "tp-sty2", size, keep, value="a", via="chat"),
            note("posted", 1390, "tp-sty2", size, "Restyle screenshots ready"),
            ev("done", 1380, "tp-sty2", size),
        ],
        ("claude", E): [
            ev("intent", 600, "tp-ev1l", EVIL),
            ev("topic", 590, "tp-ev2l", "Escaping check", parent="tp-ev1l"),
            note("posted", 585, "tp-ev2l", "Escaping check", "Escaping check"),
            ev("topic", 580, "tp-pk01", "Production page: generated files section", parent="tp-ev1l"),
            ev("parked", 570, "tp-pk01", "Production page: generated files section", ref="pk-7f3a"),
            ev("done", 560, "tp-ev2l", "Escaping check"),
        ],
        ("cursor", F): [
            ev("intent", 400, "tp-lnd1", lindris),
            ev("forked", 380, "tp-nf01", side, parent="tp-lnd1", mode="new_intent", backend="cursor"),
        ],
        ("claude", G[0]): [
            ev("intent", 3000, "tp-old1", "Registry daemon CPU snapshot"),
            ev("topic", 2990, "tp-old2", "Capture ps and sample", parent="tp-old1"),
            ev("done", 2900, "tp-old2", "Capture ps and sample"),
        ],
        ("claude", G[1]): [
            ev("intent", 4000, "tp-old3", "Hermes plugin buttons"),
            ev("topic", 3990, "tp-old4", "Wire the callback", parent="tp-old3"),
            ev("done", 3900, "tp-old4", "Wire the callback"),
        ],
        ("codex", G[2]): [
            ev("intent", 5000, "tp-old5", "Waker token gate"),
            ev("topic", 4990, "tp-old6", "Read the 5h window", parent="tp-old5"),
            ev("done", 4900, "tp-old6", "Read the 5h window"),
        ],
    }


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit("usage: seed_registry.py <registry-dir> <seed.json>")
    target = Path(sys.argv[1]).resolve()
    live = LIVE.resolve()
    if target == live or live in target.parents:
        sys.exit("refusing: that is the live agent registry")
    if target.exists() and any(target.iterdir()):
        sys.exit(f"refusing: {target} is not empty")
    ids = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    for (agent_type, session_id), events in logs(ids).items():
        path = target / "topics" / agent_type / f"{session_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
    rows = [row("claude", A, TOOLS, 1, status="working"), row("claude", B, TOOLS, 90), row("cursor", F, LINDRIS, 380)]
    (target / "registry.json").write_text(json.dumps({"version": 1, "sessions": rows}, indent=2) + "\n", encoding="utf-8")
    archived = {"archived_at": at(1380), "reason": "unregister", "session": row("claude", D, TOOLS, 1380)}
    (target / "archive.jsonl").write_text(json.dumps(archived) + "\n", encoding="utf-8")
    print(f"seeded {target}")


if __name__ == "__main__":
    main()
