# Topic Awareness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sessions record a fixed intent and a changing topic in a per-session log that the registry owns. A prompt hook reminds the agent of both on every turn, a skill tells it to fork, park or keep a drifting thread, and `agt registry fork` starts the forked thread as a visible session.

**Architecture:** A new `topics` module appends events to `<registry dir>/topics/<type>/<session_id>.jsonl` and replays them into state. A `forking` module writes the brief and launches a Cursor tab or a Herdr pane through an injectable runner. The topic commands run in the CLI process (they never go through the registry daemon), so a stale daemon cannot reject them. The live row's intent and topic are derived from the log when the daemon lists sessions, not stored in `registry.json`. The existing `registry-hook` prints the reminder line.

**Tech Stack:** Python 3 (stdlib only), bash hook, pytest. Spec: `modules/registry/docs/superpowers/specs/2026-11-25-topic-awareness-design.md`.

**Spec refinements this plan makes** (Task 10 writes them back into the spec):
- The live row's `intent` and `topic` are derived from the log at list time, not stored in `registry.json`. Same visible result, and an old daemon can't erase them.
- The `forked` event carries `mode: "side" | "new_intent"`.
- The tier-1 black-box suite is two files: `test_topics_cli.py` and `test_topics_hook.py`.

**Conventions:** Python files use 4-space indents, `from __future__ import annotations`, and module-level docstrings only where the existing code has them. Run every command from `modules/registry` unless a step says otherwise. Unit tests: `.venv/bin/python -m pytest -q`.

---

## File map

| File | Responsibility |
|---|---|
| `src/agent_registry/constants.py` (modify) | `EXIT_CONFLICT`, topic id alphabet, session env var names |
| `src/agent_registry/topics.py` (create) | Topic log: paths, append under lock, replay, mint ids, intent/adopt/topic/close/fork records, views, reminder line |
| `src/agent_registry/forking.py` (create) | `agt registry fork`: backends (cursor, herdr, none), child prompt, launch |
| `src/agent_registry/topic_cli.py` (create) | Argparse parsers and in-process handlers for `intent`, `topic`, `topics`, `fork`, `topic-context` |
| `src/agent_registry/cli.py` (modify) | Register the topic parsers; route those commands to `topic_cli.run` before the daemon path |
| `src/agent_registry/ops.py` (modify) | `list_split` / `live_views` add `intent` and `topic` to each view |
| `src/agent_registry/format.py` (modify) | `list` text shows `intent:` and `topic:` |
| `plugin/scripts/registry-hook` (modify) | Prompt reminder (Claude, Codex), SessionStart line (Claude, Cursor) |
| `../../skills/topic-awareness/SKILL.md` (create) | The agent's rules: set intent, declare topics, drift check, fork/park/keep |
| `../../install.sh` (modify) | Link the skill into Claude Code, Cursor and Codex |
| `tests/test_topics.py`, `tests/test_forking.py`, `tests/test_topic_cli.py`, `tests/test_topics_list.py` (create) | Unit tests |
| `tests/blackbox/conftest.py`, `test_topics_cli.py`, `test_topics_hook.py`, `test_topics_agent.py`, `MANUAL.md` (create) | Black-box suite |
| `README.md`, `docs/specs/plugin.md`, the spec (modify) | Docs |

---

### Task 1: Topic log core

**Files:**
- Modify: `src/agent_registry/constants.py`
- Create: `src/agent_registry/topics.py`
- Test: `tests/test_topics.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_topics.py`:

```python
import json

import pytest

from agent_registry import topics


def test_intent_then_topic_then_done(tmp_registry):
    intent = topics.set_intent("claude", "s1", "Ship topic awareness")
    assert intent["event"] == "intent"
    assert intent["topic"]["id"].startswith("tp-")
    assert len(intent["topic"]["id"]) == 7
    opened = topics.open_topic("claude", "s1", "Write the plan")
    assert opened["parent"] == intent["topic"]["id"]
    st = topics.state("claude", "s1")
    assert st["intent"] == {"id": intent["topic"]["id"], "title": "Ship topic awareness"}
    assert st["topic"]["id"] == opened["topic"]["id"]
    topics.close_topic("claude", "s1", "done")
    st = topics.state("claude", "s1")
    assert st["topic"] is None
    assert [t["status"] for t in st["topics"]] == ["open", "done"]


def test_second_intent_conflicts(tmp_registry):
    topics.set_intent("claude", "s1", "A")
    with pytest.raises(topics.TopicConflictError):
        topics.set_intent("claude", "s1", "B")


def test_topic_needs_intent(tmp_registry):
    with pytest.raises(topics.NoIntentError):
        topics.open_topic("claude", "s1", "x")


def test_blank_title_is_usage_error(tmp_registry):
    with pytest.raises(topics.TopicUsageError):
        topics.set_intent("claude", "s1", "   ")


def test_close_unknown_topic(tmp_registry):
    topics.set_intent("claude", "s1", "A")
    with pytest.raises(topics.TopicNotFoundError):
        topics.close_topic("claude", "s1", "done", "tp-zzzz")
    with pytest.raises(topics.TopicNotFoundError):
        topics.close_topic("claude", "s1", "done")


def test_park_records_ref(tmp_registry):
    topics.set_intent("claude", "s1", "A")
    side = topics.open_topic("claude", "s1", "side")
    ev = topics.close_topic("claude", "s1", "parked", side["topic"]["id"], ref="pk-12")
    assert ev["ref"] == "pk-12"
    assert topics.state("claude", "s1")["topics"][1]["status"] == "parked"


def test_log_lives_beside_registry(tmp_registry):
    topics.set_intent("claude", "s1", "A")
    path = tmp_registry.parent / "topics" / "claude" / "s1.jsonl"
    assert json.loads(path.read_text().splitlines()[0])["event"] == "intent"


def test_torn_line_is_skipped(tmp_registry):
    topics.set_intent("claude", "s1", "A")
    with open(topics.log_path("claude", "s1"), "a") as f:
        f.write('{"event": "topic", "topi\n')
    assert topics.state("claude", "s1")["intent"]["title"] == "A"


def test_adopt_binds_existing_topic(tmp_registry):
    root = topics.set_intent("claude", "parent", "A")
    ev = topics.adopt("claude", "child", root["topic"]["id"])
    assert ev["from_session"] == "parent"
    assert topics.state("claude", "child")["intent"]["id"] == root["topic"]["id"]
    with pytest.raises(topics.TopicConflictError):
        topics.adopt("claude", "child", root["topic"]["id"])


def test_adopt_unknown(tmp_registry):
    with pytest.raises(topics.TopicNotFoundError):
        topics.adopt("claude", "child", "tp-zzzz")


def test_mint_skips_taken_ids(tmp_registry, monkeypatch):
    picks = iter("aaaa" + "aaaa" + "bbbb")
    monkeypatch.setattr(topics.secrets, "choice", lambda _alphabet: next(picks))
    assert topics.set_intent("claude", "s1", "A")["topic"]["id"] == "tp-aaaa"
    assert topics.set_intent("claude", "s2", "B")["topic"]["id"] == "tp-bbbb"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_topics.py -q`
Expected: FAIL with `ImportError: cannot import name 'topics'`.

- [ ] **Step 3: Add the constants**

Append to `src/agent_registry/constants.py`:

```python
EXIT_CONFLICT = 4
# Same alphabet as inbox ids (no 0/1/i/l/o): topic ids are read and typed by a person.
TOPIC_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
TOPIC_ID_PREFIX = "tp-"
TOPIC_ID_LEN = 4
# Where each engine puts the session's own id in its shell environment.
SESSION_ENV = {
    "claude": "CLAUDE_CODE_SESSION_ID",
    "codex": "CODEX_THREAD_ID",
    "cursor": "CURSOR_CONVERSATION_ID",
}
```

- [ ] **Step 4: Write `topics.py`**

Create `src/agent_registry/topics.py`:

```python
"""Per-session topic log: a session's intent and the topics it opened under it."""
from __future__ import annotations

import fcntl
import json
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
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue  # a torn line never hides the rest of the log
        if isinstance(event, dict) and isinstance(event.get("topic"), dict):
            events.append(event)
    return events


def _append(agent_type: str, session_id: str, event: dict) -> dict:
    path = log_path(agent_type, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_topics.py -q`
Expected: `11 passed`.

- [ ] **Step 6: Commit**

```bash
git add src/agent_registry/constants.py src/agent_registry/topics.py tests/test_topics.py
git commit -m "feat(registry): a per-session topic log records intent and topics"
```

---

### Task 2: Fork records and topic views

**Files:**
- Modify: `src/agent_registry/topics.py`
- Test: `tests/test_topics.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_topics.py`:

```python
from pathlib import Path


def test_record_fork_writes_brief_and_event(tmp_registry):
    topics.set_intent("claude", "p", "A")
    main = topics.open_topic("claude", "p", "main")
    ev = topics.record_fork("claude", "p", "Side", mode="new_intent", backend="none", brief_text="# Brief\n")
    assert ev["event"] == "forked"
    assert ev["parent"] == main["topic"]["id"]
    assert ev["mode"] == "new_intent"
    assert ev["backend"] == "none"
    assert Path(ev["brief"]).read_text() == "# Brief\n"
    assert Path(ev["brief"]).parent == tmp_registry.parent / "briefs"
    # Forking a side thread does not close the topic the session is on.
    assert topics.state("claude", "p")["topic"]["id"] == main["topic"]["id"]


def test_record_fork_parent_is_intent_without_topic(tmp_registry):
    intent = topics.set_intent("claude", "p", "A")
    ev = topics.record_fork("claude", "p", "Side", mode="side", backend="none", brief_text="b")
    assert ev["parent"] == intent["topic"]["id"]


def test_record_fork_rules(tmp_registry):
    with pytest.raises(topics.NoIntentError):
        topics.record_fork("claude", "p", "x", mode="side", backend="none", brief_text="b")
    topics.set_intent("claude", "p", "A")
    with pytest.raises(topics.TopicUsageError):
        topics.record_fork("claude", "p", "x", mode="side", backend="none", brief_text="   ")
    with pytest.raises(topics.TopicUsageError):
        topics.record_fork("claude", "p", "x", mode="sideways", backend="none", brief_text="b")


def test_tree_links_forked_child(tmp_registry):
    root = topics.set_intent("claude", "p", "Parent intent")
    fork = topics.record_fork("claude", "p", "Side quest", mode="side", backend="none", brief_text="b")
    topics.adopt("claude", "c", fork["topic"]["id"])
    tree = topics.tree()
    assert [n["id"] for n in tree] == [root["topic"]["id"]]
    child = tree[0]["children"][0]
    assert child["id"] == fork["topic"]["id"]
    assert child["status"] == "open"
    assert {(s["session_id"], s["role"]) for s in child["sessions"]} == {("p", "forked"), ("c", "intent")}


def test_open_topics_across_sessions(tmp_registry):
    topics.set_intent("claude", "a", "A")
    topics.open_topic("claude", "a", "a1")
    topics.close_topic("claude", "a", "done")
    topics.set_intent("codex", "b", "B")
    rows = topics.open_topics()
    assert {(r["agent_type"], r["session_id"], r["title"]) for r in rows} == {
        ("claude", "a", "A"), ("codex", "b", "B"),
    }


def test_current_and_context_line(tmp_registry):
    assert topics.current("claude", "s") == {"intent": None, "topic": None}
    assert topics.context_line("claude", "s").startswith("No intent set for this session.")
    intent = topics.set_intent("claude", "s", "Ship it")
    opened = topics.open_topic("claude", "s", "Plan")
    line = topics.context_line("claude", "s")
    assert line == (
        f"Intent: Ship it ({intent['topic']['id']}) · Topic: Plan ({opened['topic']['id']}). "
        "If this prompt opens a new thread, run the topic-awareness drift check."
    )
    topics.close_topic("claude", "s", "done")
    assert "· Topic: none." in topics.context_line("claude", "s")


def test_current_survives_unreadable_log(tmp_registry):
    topics.set_intent("claude", "s", "A")
    path = topics.log_path("claude", "s")
    path.chmod(0)
    try:
        assert topics.current("claude", "s") == {"intent": None, "topic": None}
    finally:
        path.chmod(0o600)


def test_session_type(tmp_registry):
    topics.set_intent("codex", "b", "B")
    assert topics.session_type("b") == "codex"
    assert topics.session_type("nope") is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_topics.py -q`
Expected: the 8 new tests FAIL with `AttributeError: module 'agent_registry.topics' has no attribute 'record_fork'` (and `tree`, `open_topics`, `current`, `context_line`, `session_type`).

- [ ] **Step 3: Implement**

Append to `src/agent_registry/topics.py`:

```python
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
        "If this prompt opens a new thread, run the topic-awareness drift check."
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_topics.py -q`
Expected: `19 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/agent_registry/topics.py tests/test_topics.py
git commit -m "feat(registry): topics record forks and show history, open topics and the tree"
```

---

### Task 3: Fork launcher

**Files:**
- Create: `src/agent_registry/forking.py`
- Test: `tests/test_forking.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_forking.py`:

```python
import json
import subprocess
import urllib.parse

import pytest

from agent_registry import forking, topics


class FakeRun:
    """Records each command; returns canned stdout keyed by the command's first three words."""

    def __init__(self, outputs=None, codes=None):
        self.calls = []
        self.outputs = outputs or {}
        self.codes = codes or {}

    def __call__(self, cmd):
        self.calls.append(list(cmd))
        key = tuple(cmd[:3])
        return subprocess.CompletedProcess(cmd, self.codes.get(key, 0), stdout=self.outputs.get(key, ""), stderr="")


def test_cursor_backend_focuses_window_then_opens_tab(tmp_registry):
    topics.set_intent("claude", "p", "A")
    run = FakeRun()
    res = forking.fork("claude", "p", "Side", mode="side", brief_text="b", backend="cursor", directory="/proj", run=run)
    assert run.calls[0] == ["cursor", "/proj"]
    assert run.calls[1][0] == "open"
    url = run.calls[1][1]
    assert url.startswith("cursor://anthropic.claude-code/open?prompt=")
    prompt = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["prompt"][0]
    assert prompt == res["prompt"]
    assert f"agt registry intent --adopt {res['topic']['id']}" in prompt
    assert res["brief"] in prompt
    assert res["launched"] is True


def test_herdr_backend_splits_starts_and_prompts(tmp_registry):
    topics.set_intent("codex", "p", "A")
    run = FakeRun({("herdr", "pane", "split"): json.dumps({"result": {"pane": {"id": "p-9"}}})})
    res = forking.fork("codex", "p", "Side", mode="side", brief_text="b", backend="herdr", directory="/proj", run=run)
    name = f"fork-{res['topic']['id']}"
    assert run.calls[0] == [
        "herdr", "pane", "split", "--current", "--direction", "right", "--cwd", "/proj", "--no-focus",
    ]
    assert run.calls[1] == ["herdr", "agent", "start", name, "--kind", "codex", "--pane", "p-9"]
    assert run.calls[2] == ["herdr", "agent", "prompt", name, res["prompt"]]
    assert res["launched"] is True


def test_herdr_split_without_pane_id(tmp_registry):
    topics.set_intent("claude", "p", "A")
    run = FakeRun({("herdr", "pane", "split"): "{}"})
    res = forking.fork("claude", "p", "Side", mode="side", brief_text="b", backend="herdr", directory="/proj", run=run)
    assert res["launched"] is False
    assert "pane id" in res["error"]
    assert len(run.calls) == 1


def test_none_backend_runs_nothing(tmp_registry):
    topics.set_intent("claude", "p", "A")
    run = FakeRun()
    res = forking.fork("claude", "p", "Side", mode="side", brief_text="b", backend="none", directory="/proj", run=run)
    assert run.calls == []
    assert res["launched"] is False
    assert res["backend"] == "none"


def test_unknown_backend_writes_nothing(tmp_registry):
    topics.set_intent("claude", "p", "A")
    with pytest.raises(topics.TopicUsageError):
        forking.fork("claude", "p", "Side", mode="side", brief_text="b", backend="tmux", run=FakeRun())
    assert [e["event"] for e in topics.read_events("claude", "p")] == ["intent"]


def test_default_backend():
    assert forking.default_backend({"HERDR_ENV": "1"}) == "herdr"
    assert forking.default_backend({}) == "cursor"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_forking.py -q`
Expected: FAIL with `ImportError: cannot import name 'forking'`.

- [ ] **Step 3: Write `forking.py`**

Create `src/agent_registry/forking.py`:

```python
"""agt registry fork: hand a thread to a new session that Tiago can see."""
from __future__ import annotations

import json
import os
import subprocess
import urllib.parse
from collections.abc import Callable, Mapping, Sequence

from agent_registry import topics

BACKENDS = ("cursor", "herdr", "none")
HERDR_KINDS = ("claude", "codex")

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


def _run(cmd: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True, timeout=60)


def default_backend(env: Mapping[str, str] = os.environ) -> str:
    return "herdr" if env.get("HERDR_ENV") == "1" else "cursor"


def child_prompt(topic_id: str, brief: str) -> str:
    return f"Read {brief}, run agt registry intent --adopt {topic_id}, then continue."


def cursor_url(prompt: str) -> str:
    query = urllib.parse.urlencode({"prompt": prompt}, quote_via=urllib.parse.quote)
    return f"cursor://anthropic.claude-code/open?{query}"


def launch_cursor(directory: str, prompt: str, run: Runner) -> dict:
    # The link opens in the last-focused window, so bring the project's window forward first.
    run(["cursor", directory])
    opened = run(["open", cursor_url(prompt)])
    return {"launched": opened.returncode == 0}


def _pane_id(stdout: str) -> str | None:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    pane = (data.get("result") or {}).get("pane") if isinstance(data, dict) else None
    if isinstance(pane, dict):
        pane = pane.get("id") or pane.get("pane_id")
    return pane if isinstance(pane, str) and pane else None


def launch_herdr(directory: str, prompt: str, engine: str, name: str, run: Runner) -> dict:
    split = run(["herdr", "pane", "split", "--current", "--direction", "right", "--cwd", directory, "--no-focus"])
    if split.returncode != 0:
        return {"launched": False, "error": split.stderr.strip() or "herdr pane split failed"}
    pane = _pane_id(split.stdout)
    if not pane:
        return {"launched": False, "error": "herdr pane split returned no pane id"}
    started = run(["herdr", "agent", "start", name, "--kind", engine, "--pane", pane])
    if started.returncode != 0:
        return {"launched": False, "pane": pane, "error": started.stderr.strip() or "herdr agent start failed"}
    sent = run(["herdr", "agent", "prompt", name, prompt])
    return {"launched": sent.returncode == 0, "pane": pane, "agent": name}


def fork(
    agent_type: str,
    session_id: str,
    title: str,
    *,
    mode: str,
    brief_text: str,
    backend: str | None = None,
    directory: str | None = None,
    run: Runner = _run,
) -> dict:
    backend = backend or default_backend()
    if backend not in BACKENDS:
        raise topics.TopicUsageError(f"backend must be one of {', '.join(BACKENDS)}")
    event = topics.record_fork(agent_type, session_id, title, mode=mode, backend=backend, brief_text=brief_text)
    tid = event["topic"]["id"]
    prompt = child_prompt(tid, event["brief"])
    directory = directory or os.getcwd()
    result = {"topic": event["topic"], "brief": event["brief"], "backend": backend, "prompt": prompt, "launched": False}
    if backend == "cursor":
        result.update(launch_cursor(directory, prompt, run))
    elif backend == "herdr":
        engine = agent_type if agent_type in HERDR_KINDS else "claude"
        result.update(launch_herdr(directory, prompt, engine, f"fork-{tid}", run))
    return result
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_forking.py -q`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/agent_registry/forking.py tests/test_forking.py
git commit -m "feat(registry): fork launches a thread as a Cursor tab or a Herdr pane"
```

---

### Task 4: Topic commands in the CLI

**Files:**
- Create: `src/agent_registry/topic_cli.py`
- Modify: `src/agent_registry/cli.py` (imports; `main` before `args = parser.parse_args(argv)` and right after it)
- Test: `tests/test_topic_cli.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_topic_cli.py`:

```python
import json

import pytest

from agent_registry import topics
from agent_registry.cli import main
from agent_registry.constants import EXIT_CONFLICT, EXIT_NOT_FOUND, EXIT_OK, EXIT_USAGE

WHO = ["--type", "claude", "--session-id", "s1"]


@pytest.fixture(autouse=True)
def no_session_env(monkeypatch):
    for var in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CURSOR_CONVERSATION_ID"):
        monkeypatch.delenv(var, raising=False)


def _run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_intent_topic_done_history(tmp_registry, capsys):
    code, out, _ = _run(capsys, "intent", "Ship it", *WHO)
    assert code == EXIT_OK
    tid = json.loads(out)["topic"]["id"]
    code, out, _ = _run(capsys, "topic", "Plan", *WHO)
    assert code == EXIT_OK and json.loads(out)["parent"] == tid
    code, out, _ = _run(capsys, "topic", "--done", *WHO)
    assert code == EXIT_OK and json.loads(out)["event"] == "done"
    code, out, _ = _run(capsys, "topics", *WHO)
    data = json.loads(out)
    assert [e["event"] for e in data["events"]] == ["intent", "topic", "done"]
    assert data["intent"]["id"] == tid
    assert data["topic"] is None


def test_exit_codes(tmp_registry, capsys):
    assert _run(capsys, "topic", "Plan", *WHO)[0] == EXIT_USAGE
    assert _run(capsys, "intent", "A", *WHO)[0] == EXIT_OK
    assert _run(capsys, "intent", "B", *WHO)[0] == EXIT_CONFLICT
    assert _run(capsys, "topic", "--done", "tp-zzzz", *WHO)[0] == EXIT_NOT_FOUND
    assert _run(capsys, "topic", *WHO)[0] == EXIT_USAGE
    assert _run(capsys, "intent", *WHO)[0] == EXIT_USAGE
    assert _run(capsys, "intent", "A", "--adopt", "tp-zzzz", *WHO)[0] == EXIT_USAGE


def test_park_with_ref(tmp_registry, capsys):
    _run(capsys, "intent", "A", *WHO)
    _run(capsys, "topic", "Side", *WHO)
    code, out, _ = _run(capsys, "topic", "--park", "--ref", "pk-1", *WHO)
    assert code == EXIT_OK
    assert json.loads(out)["ref"] == "pk-1"


def test_identity_from_env(tmp_registry, capsys, monkeypatch):
    monkeypatch.setenv("CODEX_THREAD_ID", "t-1")
    assert _run(capsys, "intent", "From env")[0] == EXIT_OK
    assert topics.state("codex", "t-1")["intent"]["title"] == "From env"


def test_no_identity_is_usage(tmp_registry, capsys):
    code, _, err = _run(capsys, "intent", "x")
    assert code == EXIT_USAGE
    assert "--type" in err


def test_session_id_needs_type(tmp_registry, capsys):
    assert _run(capsys, "intent", "x", "--session-id", "s1")[0] == EXIT_USAGE


def test_topic_context_is_a_plain_line(tmp_registry, capsys):
    code, out, _ = _run(capsys, "topic-context", *WHO)
    assert code == EXIT_OK
    assert out.startswith("No intent set for this session.")


def test_topics_other_session_open_and_tree(tmp_registry, capsys):
    _run(capsys, "intent", "A", *WHO)
    code, out, _ = _run(capsys, "topics", "--session", "s1")
    assert code == EXIT_OK and json.loads(out)["agent_type"] == "claude"
    assert _run(capsys, "topics", "--session", "nope")[0] == EXIT_NOT_FOUND
    code, out, _ = _run(capsys, "topics", "--open")
    assert [t["title"] for t in json.loads(out)["topics"]] == ["A"]
    code, out, _ = _run(capsys, "topics", "--tree")
    assert [n["title"] for n in json.loads(out)["tree"]] == ["A"]


def test_fork_reads_brief_file(tmp_registry, capsys, tmp_path):
    _run(capsys, "intent", "A", *WHO)
    brief = tmp_path / "brief.md"
    brief.write_text("# Why\nSplit off.\n")
    code, out, _ = _run(capsys, "fork", "Side", "--side", "--backend", "none", "--brief-file", str(brief), *WHO)
    assert code == EXIT_OK
    data = json.loads(out)
    assert data["launched"] is False
    assert open(data["brief"]).read() == "# Why\nSplit off.\n"
    assert f"--adopt {data['topic']['id']}" in data["prompt"]


def test_fork_needs_a_mode(tmp_registry, capsys):
    with pytest.raises(SystemExit):
        main(["fork", "Side", "--backend", "none", *WHO])
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_topic_cli.py -q`
Expected: FAIL. argparse exits with `invalid choice: 'intent'`.

- [ ] **Step 3: Write `topic_cli.py`**

Create `src/agent_registry/topic_cli.py`:

```python
"""Topic commands. They run in this process and never go through the daemon."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from agent_registry import forking, topics
from agent_registry.constants import (
    EXIT_CONFLICT,
    EXIT_IO,
    EXIT_NOT_FOUND,
    EXIT_OK,
    EXIT_USAGE,
    SESSION_ENV,
)

COMMANDS = frozenset({"intent", "topic", "topics", "fork", "topic-context"})


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
        if args.open:
            return {"topics": topics.open_topics()}
        if args.tree:
            return {"tree": topics.tree()}
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
            return topics.close_topic(agent_type, session_id, "done", args.done or None)
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
    return topics.context_line(agent_type, session_id)


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
```

- [ ] **Step 4: Wire it into `cli.py`**

In `src/agent_registry/cli.py`, change the import line

```python
from agent_registry import archive, client, doctor
```

to

```python
from agent_registry import archive, client, doctor, topic_cli
```

In `main`, just before `args = parser.parse_args(argv)`, add:

```python
    topic_cli.add_parsers(sub)
```

and right after `args = parser.parse_args(argv)`, add:

```python
    if args.cmd in topic_cli.COMMANDS:
        return topic_cli.run(args)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_topic_cli.py tests/test_cli.py -q`
Expected: all pass. `test_cli.py` passing shows the other commands are unchanged.

- [ ] **Step 6: Commit**

```bash
git add src/agent_registry/topic_cli.py src/agent_registry/cli.py tests/test_topic_cli.py
git commit -m "feat(registry): intent, topic, topics, fork and topic-context commands"
```

---

### Task 5: List shows intent and topic

**Files:**
- Modify: `src/agent_registry/ops.py` (`list_split`, `live_views`, imports)
- Modify: `src/agent_registry/format.py` (`_line`)
- Test: `tests/test_topics_list.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_topics_list.py`:

```python
from agent_registry import ops, topics
from agent_registry.format import format_list


def test_list_split_adds_intent_and_topic(tmp_registry):
    ops.register(agent_type="claude", session_id="s1", directory="/proj")
    ops.register(agent_type="claude", session_id="s2", directory="/proj")
    intent = topics.set_intent("claude", "s1", "Ship it")
    opened = topics.open_topic("claude", "s1", "Plan")
    active, _stale = ops.list_split()
    by_sid = {v["session_id"]: v for v in active}
    assert by_sid["s1"]["intent"] == {"id": intent["topic"]["id"], "title": "Ship it"}
    assert by_sid["s1"]["topic"] == {"id": opened["topic"]["id"], "title": "Plan"}
    assert by_sid["s2"]["intent"] is None and by_sid["s2"]["topic"] is None


def test_live_views_add_intent(tmp_registry):
    ops.register(agent_type="codex", session_id="t1", directory="/proj")
    topics.set_intent("codex", "t1", "Ship it")
    views = ops.live_views()
    assert views["active"][0]["intent"]["title"] == "Ship it"


def test_list_text_shows_intent_and_topic():
    row = {
        "agent_type": "claude", "session_id": "s", "status": "idle",
        "intent": {"id": "tp-a", "title": "Ship"}, "topic": {"id": "tp-b", "title": "Plan"},
    }
    text = format_list([row], [])
    assert "intent:Ship" in text and "topic:Plan" in text
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_topics_list.py -q`
Expected: FAIL with `KeyError: 'intent'` and an assertion error on the text.

- [ ] **Step 3: Implement**

In `src/agent_registry/ops.py`, change `from agent_registry import archive, store` to `from agent_registry import archive, store, topics`. In `list_split`, after `view = public_view(s)` add:

```python
        view.update(topics.current(s.agent_type, s.session_id))
```

In `live_views`, after `view["project"] = project_key(s.directory)` add the same line:

```python
        view.update(topics.current(s.agent_type, s.session_id))
```

In `src/agent_registry/format.py` `_line`, after the `title` / `summary` `if`/`elif` block, add:

```python
    if s.get("intent"):
        bits.append(f'intent:{s["intent"]["title"]}')
    if s.get("topic"):
        bits.append(f'topic:{s["topic"]["title"]}')
```

- [ ] **Step 4: Run the whole unit suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass. The board and list tests still pass with the two new keys on every view.

- [ ] **Step 5: Commit**

```bash
git add src/agent_registry/ops.py src/agent_registry/format.py tests/test_topics_list.py
git commit -m "feat(registry): list shows each session's intent and topic"
```

---

### Task 6: Black-box harness and hook reminder

**Files:**
- Create: `tests/blackbox/conftest.py`
- Create: `tests/blackbox/test_topics_hook.py`
- Modify: `plugin/scripts/registry-hook`

- [ ] **Step 1: Write the black-box harness**

Create `tests/blackbox/conftest.py`:

```python
"""Black-box harness: only agt, the hook script and files on disk. Never imports agent_registry."""
import json
import os
import signal
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REGISTRY = Path(__file__).resolve().parents[2]
REPO = REGISTRY.parents[1]
AGT = REPO / "agt" / "agt"
HOOK = REGISTRY / "plugin" / "scripts" / "registry-hook"
SESSION_VARS = ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CURSOR_CONVERSATION_ID", "HERDR_ENV")


@dataclass
class Box:
    root: Path
    env: dict

    @property
    def data(self) -> Path:
        return self.root / "registry"

    def agt(self, *args, stdin=None, env=None, timeout=60):
        return subprocess.run(
            [str(AGT), *args], input=stdin, env=env or self.env, capture_output=True, text=True, timeout=timeout,
        )

    def agt_json(self, *args, **kw):
        proc = self.agt(*args, **kw)
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)

    def hook(self, host, event, payload, timeout=60):
        return subprocess.run(
            [str(HOOK), host, event], input=json.dumps(payload), env=self.env,
            capture_output=True, text=True, timeout=timeout,
        )

    def log(self, agent_type, session_id) -> list[dict]:
        path = self.data / "topics" / agent_type / f"{session_id}.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture
def box(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in SESSION_VARS}
    env.update({
        "AGENT_REGISTRY_PATH": str(tmp_path / "registry" / "registry.json"),
        "AGENT_REGISTRY_DAEMON_PORT": str(_free_port()),
        "AGENT_REGISTRY_DAEMON_START_TIMEOUT": "5",
        "AGENT_REGISTRY_SUMMARY_PROVIDER": "off",
        "AGENT_REGISTRY_BIN": str(REGISTRY / "bin" / "agent-registry"),
    })
    b = Box(root=tmp_path, env=env)
    yield b
    # A command may have started a private daemon on the temp registry; stop it.
    pid_file = b.data / "daemon.pid"
    if pid_file.exists():
        try:
            os.kill(int(pid_file.read_text().strip()), signal.SIGTERM)
        except (OSError, ValueError):
            pass
```

- [ ] **Step 2: Write the failing hook tests**

Create `tests/blackbox/test_topics_hook.py`:

```python
import json

WHO = ["--type", "claude", "--session-id", "s1"]


def _prompt(box, host="claude", sid="s1", event="UserPromptSubmit"):
    return box.hook(host, "ping", {"session_id": sid, "hook_event_name": event, "cwd": str(box.root)})


def test_claude_prompt_without_intent(box):
    r = _prompt(box)
    assert r.returncode == 0
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "UserPromptSubmit"
    assert out["additionalContext"].startswith("No intent set for this session.")


def test_claude_prompt_with_intent_and_topic(box):
    tid = box.agt_json("registry", "intent", "Ship it", *WHO)["topic"]["id"]
    box.agt_json("registry", "topic", "Plan", *WHO)
    ctx = json.loads(_prompt(box).stdout)["hookSpecificOutput"]["additionalContext"]
    assert ctx.startswith(f"Intent: Ship it ({tid}) · Topic: Plan (tp-")
    assert ctx.endswith("run the topic-awareness drift check.")


def test_pretooluse_ping_prints_nothing(box):
    r = _prompt(box, event="PreToolUse")
    assert r.returncode == 0
    assert r.stdout == ""


def test_codex_prompt(box):
    box.agt_json("registry", "intent", "Codex work", "--type", "codex", "--session-id", "t1")
    r = _prompt(box, host="codex", sid="t1")
    assert "Intent: Codex work" in json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]


def test_cursor_prompt_only_continues(box):
    r = box.hook("cursor", "ping", {
        "conversation_id": "c1", "hook_event_name": "beforeSubmitPrompt", "cursor_version": "3",
    })
    assert r.returncode == 0
    assert r.stdout.strip() == '{"continue":true}'


def test_cursor_session_start_carries_line(box):
    r = box.hook("cursor", "ensure", {
        "conversation_id": "c1", "hook_event_name": "sessionStart", "cursor_version": "3",
        "workspace_roots": [str(box.root)],
    })
    assert r.returncode == 0
    assert json.loads(r.stdout)["additional_context"].startswith("No intent set")


def test_claude_session_start_carries_line(box):
    r = box.hook("claude", "ensure", {"session_id": "s9", "hook_event_name": "SessionStart", "cwd": str(box.root)})
    assert r.returncode == 0
    assert "No intent set for this session." in json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]


def test_unreadable_log_fails_open(box):
    box.agt_json("registry", "intent", "Ship it", *WHO)
    log = box.data / "topics" / "claude" / "s1.jsonl"
    log.chmod(0)
    try:
        r = _prompt(box)
        assert r.returncode == 0
        assert r.stdout == ""
    finally:
        log.chmod(0o600)
```

- [ ] **Step 3: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/blackbox/test_topics_hook.py -q`
Expected: `test_claude_prompt_*`, `test_codex_prompt`, and both session-start tests FAIL (`json.decoder.JSONDecodeError` on empty stdout, or the line is missing). `test_pretooluse_ping_prints_nothing`, `test_cursor_prompt_only_continues` and `test_unreadable_log_fails_open` already pass.

- [ ] **Step 4: Change the hook**

In `plugin/scripts/registry-hook`:

(a) Replace the header comment's second line with:

```bash
# Fail open. Cursor prints {"continue":true} on ping and {} or its session-start line otherwise.
# Claude ensure prints SessionStart context. Claude and Codex prompts print the topic line.
```

(b) Replace `cursor_reply` with:

```bash
cursor_reply() {
  if [[ "$EVENT" == "ping" ]]; then
    echo '{"continue":true}'
  elif [[ -n "${CURSOR_CONTEXT:-}" ]]; then
    CTX="$CURSOR_CONTEXT" python3 -c 'import json, os; print(json.dumps({"additional_context": os.environ["CTX"]}))'
  else
    echo '{}'
  fi
}
```

(c) After the `TRANSCRIPT=$(read_field …)` block, add:

```bash
HOOK_EVENT=$(read_field 'import sys,json
d=json.load(sys.stdin)
print(str(d.get("hook_event_name") or "").strip())')

# This session's intent and topic as one line. Empty when the topic log can't be read.
topic_line() {
  "$BIN" topic-context --type "$HOST" --session-id "$SESSION_ID" 2>/dev/null || true
}

emit_prompt_context() {
  local line
  line=$(topic_line)
  [[ -z "$line" ]] && return 0
  LINE="$line" python3 - <<'PY'
import json, os
print(json.dumps({
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": os.environ["LINE"],
  }
}))
PY
}
```

(d) Replace `emit_ensure_context` with a version that takes the topic line as a third argument:

```bash
emit_ensure_context() {
  local list_text="${1:-(none)}"
  local status="${2:-agent-registry: session registered (type=$HOST).}"
  local topic="${3:-}"
  LIST="$list_text" STATUS="$status" TOPIC="$topic" python3 - <<'PY'
import json, os
list_text = (os.environ.get("LIST") or "(none)")[:1500]
status = os.environ.get("STATUS") or "agent-registry: session registered."
topic = os.environ.get("TOPIC") or ""
print(json.dumps({
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": (
      status + " Keep registry_id private; hooks own heartbeat. Active peers:\n"
      + list_text + ("\n" + topic if topic else "")
    ),
  }
}))
PY
}
```

(e) In the `ping` branch, between the heartbeat line and `exit 0`, add:

```bash
  if [[ "$HOST" != "cursor" && "$HOOK_EVENT" == "UserPromptSubmit" ]]; then
    emit_prompt_context
  fi
```

(f) In the `ensure)` branch, replace the closing block

```bash
    if [[ "$HOST" == "claude" ]]; then
      LIST=$("$BIN" list 2>/dev/null | head -n 25 || true)
      [[ -z "$LIST" ]] && LIST="(none)"
      emit_ensure_context "$LIST" \
        "agent-registry: session registered (type=claude)."
    fi
```

with

```bash
    if [[ "$HOST" == "claude" ]]; then
      LIST=$("$BIN" list 2>/dev/null | head -n 25 || true)
      [[ -z "$LIST" ]] && LIST="(none)"
      emit_ensure_context "$LIST" \
        "agent-registry: session registered (type=claude)." "$(topic_line)"
    elif [[ "$HOST" == "cursor" ]]; then
      CURSOR_CONTEXT=$(topic_line)
    fi
```

- [ ] **Step 5: Run the hook tests and the unit suite**

Run: `.venv/bin/python -m pytest tests/blackbox/test_topics_hook.py -q && .venv/bin/python -m pytest -q`
Expected: `8 passed`, then the unit suite all passes.

- [ ] **Step 6: Commit**

```bash
git add plugin/scripts/registry-hook tests/blackbox/conftest.py tests/blackbox/test_topics_hook.py
git commit -m "feat(registry): the prompt hook reminds the agent of its intent and topic"
```

---

### Task 7: The `topic-awareness` skill

**Files:**
- Create: `../../skills/topic-awareness/SKILL.md` (repo root `skills/`)
- Modify: `../../install.sh`

- [ ] **Step 1: Write the skill**

Create `skills/topic-awareness/SKILL.md` at the repo root:

````markdown
---
name: topic-awareness
description: Use in every session. Keep one intent per session and name the topic you are on under it. When a thread drifts off the intent, or is a side quest that can be split off, ask Tiago in one line whether to fork it into its own visible session, park it, or keep it here. The prompt hook reminds you of both on every turn.
---

# topic-awareness

Tiago runs many sessions at once. A session that drifts through several threads makes him lose track when he comes back to it. Each session therefore has one **intent**, fixed for its life, and one current **topic** under it. Threads that don't belong are forked into their own sessions or parked.

Each prompt starts with a line from the hook:

```
Intent: Make inbox entries topic-aware (tp-7k3q) · Topic: Decide where topic records live (tp-9m2c). If this prompt opens a new thread, run the topic-awareness drift check.
```

or, in a new session, `No intent set for this session. …`.

Session identity comes from your environment (`CLAUDE_CODE_SESSION_ID`, `CODEX_THREAD_ID`, `CURSOR_CONVERSATION_ID`), so these commands need no flags.

## Set the intent once

As soon as the first prompt makes clear what the session is for, set the intent: one line, the outcome the session exists for.

```bash
agt registry intent "Make inbox entries topic-aware"
```

A session has one intent. If the work turns into something else, that is a new session, not a new intent.

A session started by a fork reads its brief and adopts its topic first, as its prompt says:

```bash
agt registry intent --adopt tp-xxxx
```

## Name the topic you're on

When the main line moves to a new step, open it as a topic. When it is finished, mark it done.

```bash
agt registry topic "Decide where topic records live"
agt registry topic --done
```

## Drift check

Run it whenever a prompt, or your own work, opens a new thread:

| The new thread is… | Then |
|---|---|
| on the intent's main line | `agt registry topic "…"`, keep going |
| on-intent, but a side quest that can be split off (independent of the main line and likely more than a few turns) | ask: fork / park / keep here |
| off-intent | ask: fork as a new intent / park / keep here |

Ask in one line of plain chat text, with fork as the default, and wait for the answer. Do not use a blocking question tool.

```
Side quest: retry policy for wake. Fork / park / keep here? (fork)
```

Then do what he chose:

- **Fork.** Write a brief and hand it off. The brief covers the parent intent, why the thread was split off, what is known so far, and what done looks like. Use `--side` for a side quest and `--new-intent` for an off-intent thread.

  ```bash
  cat <<'MD' | agt registry fork "Retry policy for wake" --side
  # Retry policy for wake
  Parent intent: Make inbox entries topic-aware (tp-7k3q).
  Why forked: independent of the inbox work; needs its own investigation.
  Known: three failed wakes mark an entry undelivered (modules/inbox/src/agent_inbox/dispatch.py).
  Done when: a retry policy is decided and written into the inbox spec.
  MD
  ```

  It opens a visible session: a Cursor tab with the prompt filled in (Tiago presses Enter), or a Herdr pane that starts on its own when you run inside Herdr. Tell him which, then go back to the main line and leave the forked thread alone.
- **Park.** Park the idea with the `parked-ideas` skill, then record it with the park id: `agt registry topic --park --ref <park-id>`. If the thread was not yet a topic, open it first (`agt registry topic "…"`) so the park has something to close.
- **Keep here.** Open it as a topic and work on it.

## When the intent is done

When every topic under the intent is done, say so in one line and suggest ending or clearing the session. Don't start new work in it.

## Look around

```bash
agt registry topics           # this session's history
agt registry topics --open    # every open topic, every session
agt registry topics --tree    # the topic tree across sessions, forks included
```
````

- [ ] **Step 2: Link it in `install.sh`**

In the repo root `install.sh`, after the `link_skill agent-inbox …` line, add:

```bash
# Every engine follows the topic rules, so Codex gets this one too.
link_skill topic-awareness "$HOME/.claude/skills" "$HOME/.cursor/skills" "$HOME/.codex/skills"
```

- [ ] **Step 3: Install and check the links**

Run from the repo root: `./install.sh && ls -l ~/.claude/skills/topic-awareness/SKILL.md ~/.codex/skills/topic-awareness/SKILL.md ~/.cursor/skills/topic-awareness/SKILL.md`
Expected: three symlinks pointing at `skills/topic-awareness/SKILL.md`.

- [ ] **Step 4: Commit**

```bash
git add skills/topic-awareness/SKILL.md install.sh
git commit -m "feat(skills): topic-awareness keeps one intent per session and forks side quests"
```

---

### Task 8: Black-box CLI suite (tier 1)

**Files:**
- Create: `tests/blackbox/test_topics_cli.py`

- [ ] **Step 1: Write the tests**

Create `tests/blackbox/test_topics_cli.py`:

```python
import json
import threading
from pathlib import Path

WHO = ["--type", "claude", "--session-id", "s1"]


def test_history_in_order_with_statuses(box):
    intent = box.agt_json("registry", "intent", "Ship it", *WHO)
    plan = box.agt_json("registry", "topic", "Plan", *WHO)
    box.agt_json("registry", "topic", "--done", *WHO)
    side = box.agt_json("registry", "topic", "Side", *WHO)
    box.agt_json("registry", "topic", "--park", side["topic"]["id"], "--ref", "pk-7", *WHO)
    data = box.agt_json("registry", "topics", *WHO)
    assert [e["event"] for e in data["events"]] == ["intent", "topic", "done", "topic", "parked"]
    statuses = {t["id"]: t["status"] for t in data["topics"]}
    assert statuses == {intent["topic"]["id"]: "open", plan["topic"]["id"]: "done", side["topic"]["id"]: "parked"}
    assert box.log("claude", "s1")[-1]["ref"] == "pk-7"


def test_exit_codes(box):
    assert box.agt("registry", "topic", "Plan", *WHO).returncode == 1
    assert box.agt("registry", "intent", "A", *WHO).returncode == 0
    assert box.agt("registry", "intent", "B", *WHO).returncode == 4
    assert box.agt("registry", "topic", "--done", "tp-zzzz", *WHO).returncode == 2
    assert box.agt("registry", "intent", "--adopt", "tp-zzzz", "--type", "claude", "--session-id", "s2").returncode == 2


def test_identity_from_engine_env(box):
    env = dict(box.env, CLAUDE_CODE_SESSION_ID="env-1")
    assert box.agt("registry", "intent", "From env", env=env).returncode == 0
    assert box.log("claude", "env-1")[0]["topic"]["title"] == "From env"


def test_fork_then_adopt_builds_the_tree(box):
    root = box.agt_json("registry", "intent", "Parent", *WHO)
    fork = box.agt_json(
        "registry", "fork", "Side quest", "--side", "--backend", "none", *WHO,
        stdin="# Side quest\nDone when: decided.\n",
    )
    assert fork["launched"] is False
    assert Path(fork["brief"]).read_text() == "# Side quest\nDone when: decided.\n"
    assert f"agt registry intent --adopt {fork['topic']['id']}" in fork["prompt"]
    adopted = box.agt_json("registry", "intent", "--adopt", fork["topic"]["id"], "--type", "claude", "--session-id", "s2")
    assert adopted["from_session"] == "s1"

    tree = box.agt_json("registry", "topics", "--tree")["tree"]
    assert [n["id"] for n in tree] == [root["topic"]["id"]]
    child = tree[0]["children"][0]
    assert child["id"] == fork["topic"]["id"]
    assert {(s["session_id"], s["role"]) for s in child["sessions"]} == {("s1", "forked"), ("s2", "intent")}

    open_rows = box.agt_json("registry", "topics", "--open")["topics"]
    assert {(r["session_id"], r["title"]) for r in open_rows} == {("s1", "Parent"), ("s2", "Side quest")}


def test_fork_without_brief_is_usage(box):
    box.agt_json("registry", "intent", "Parent", *WHO)
    r = box.agt("registry", "fork", "Side", "--side", "--backend", "none", *WHO, stdin="")
    assert r.returncode == 1
    assert [e["event"] for e in box.log("claude", "s1")] == ["intent"]


def test_concurrent_writers_lose_nothing(box):
    box.agt_json("registry", "intent", "Busy", *WHO)

    failures = []

    def writer(n):
        for i in range(10):
            proc = box.agt("registry", "topic", f"w{n}-{i}", *WHO)
            if proc.returncode != 0:
                failures.append(proc.stderr)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert failures == []
    raw = (box.data / "topics" / "claude" / "s1.jsonl").read_text().splitlines()
    events = [json.loads(line) for line in raw]          # every line is whole JSON
    opened = [e for e in events if e["event"] == "topic"]
    assert len(opened) == 30
    assert len({e["topic"]["id"] for e in opened}) == 30  # no id minted twice


def test_list_shows_intent_and_topic(box):
    reg = box.agt_json("registry", "register", "--type", "claude", "--session-id", "s1", "--directory", str(box.root))
    box.agt_json("registry", "intent", "Ship it", *WHO)
    box.agt_json("registry", "topic", "Plan", *WHO)
    rows = box.agt_json("registry", "list", "--json")["active"]
    row = next(r for r in rows if r["session_id"] == "s1")
    assert row["intent"]["title"] == "Ship it" and row["topic"]["title"] == "Plan"
    text = box.agt("registry", "list").stdout
    assert "intent:Ship it" in text and "topic:Plan" in text
    assert reg["registry_id"]


def test_unregister_and_prune_keep_the_log(box):
    reg = box.agt_json("registry", "register", "--type", "claude", "--session-id", "s1", "--directory", str(box.root))
    box.agt_json("registry", "intent", "Ship it", *WHO)
    assert box.agt("registry", "unregister", reg["registry_id"]).returncode == 0
    assert box.agt("registry", "prune", "--yes").returncode == 0
    assert box.log("claude", "s1")[0]["topic"]["title"] == "Ship it"
```

- [ ] **Step 2: Run the suite**

Run: `.venv/bin/python -m pytest tests/blackbox/test_topics_cli.py tests/blackbox/test_topics_hook.py -q`
Expected: `16 passed`. If `test_list_shows_intent_and_topic` fails with `daemon already listening`, a daemon from an earlier run on this temp path is still alive. That points at a leak in the `box` teardown, so fix the teardown rather than the test.

- [ ] **Step 3: Commit**

```bash
git add tests/blackbox/test_topics_cli.py
git commit -m "test(registry): black-box suite for the topic commands"
```

---

### Task 9: Real-agent tier and manual checklist

**Files:**
- Create: `tests/blackbox/test_topics_agent.py`
- Create: `tests/blackbox/MANUAL.md`

- [ ] **Step 1: Write the agent tests**

Create `tests/blackbox/test_topics_agent.py`:

```python
"""Real agents on a temp registry. Needs install.sh (skill links) and the updated Claude plugin.

Run explicitly: .venv/bin/python -m pytest tests/blackbox/test_topics_agent.py -v
The agent's wording varies, so the off-intent check looks for the fork / park words, not a sentence.
"""
import json
import shutil
import subprocess

import pytest

FIRST = (
    "This session's goal: write a haiku about autumn leaves into haiku.txt in this directory. "
    "Before anything else, follow the topic-awareness skill. Then write the haiku."
)
OFF_INTENT = (
    "Unrelated: I also need to design a retry policy for a payment webhook. "
    "Follow the topic-awareness skill for this new thread."
)
ALLOWED = "Bash(agt registry:*) Write Read"


def _claude(box, *args):
    return subprocess.run(
        [shutil.which("claude"), "-p", *args, "--output-format", "json", "--allowedTools", ALLOWED],
        cwd=box.root, env=box.env, capture_output=True, text=True, timeout=300,
    )


@pytest.mark.skipif(not shutil.which("claude"), reason="claude is not on PATH")
def test_claude_sets_intent_then_asks_on_drift(box):
    first = _claude(box, FIRST)
    assert first.returncode == 0, first.stderr
    sid = json.loads(first.stdout)["session_id"]
    events = box.log("claude", sid)
    assert any(e["event"] == "intent" for e in events), f"no intent recorded: {events}"

    second = _claude(box, "--resume", sid, OFF_INTENT)
    assert second.returncode == 0, second.stderr
    reply = json.loads(second.stdout)["result"].lower()
    assert "fork" in reply and "park" in reply, reply
    after = box.log("claude", sid)
    assert not any(e["event"] == "topic" and "retry" in e["topic"]["title"].lower() for e in after), after


@pytest.mark.skipif(not shutil.which("codex"), reason="codex is not on PATH")
def test_codex_sets_intent(box):
    proc = subprocess.run(
        [shutil.which("codex"), "exec", "--dangerously-bypass-hook-trust", "-s", "workspace-write",
         "-C", str(box.root), "--json", FIRST],
        env=box.env, capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    logs = list((box.data / "topics" / "codex").glob("*.jsonl")) if (box.data / "topics" / "codex").exists() else []
    assert logs, f"codex wrote no topic log; stdout tail: {proc.stdout[-2000:]}"
    events = [json.loads(line) for line in logs[0].read_text().splitlines() if line.strip()]
    assert any(e["event"] == "intent" for e in events)
```

- [ ] **Step 2: Write the manual checklist**

Create `tests/blackbox/MANUAL.md`:

```markdown
# Topic awareness — manual checks

What a test can't see. Run after any change to forking or the hook. Record the date and the result of each check at the bottom.

## Setup

- `./install.sh` from the repo root.
- `claude plugin update agent-registry@agent-registry`, then restart Claude Code. Confirm the cache matches the repo: `diff ~/.claude/plugins/cache/agent-registry/agent-registry/*/scripts/registry-hook modules/registry/plugin/scripts/registry-hook` prints nothing.

## Checks

1. **Reminder in Claude Code (Cursor extension).** Open a new Claude tab and send any prompt. The agent sets an intent, and `agt registry topics` from a terminal shows it.
2. **Drift ask.** In that session, send something off-intent. The agent asks fork / park / keep in one line and doesn't start on it.
3. **Cursor fork.** Answer "fork". A new Claude tab opens **in the same project window**, with the prompt filled in and not sent. Press Enter. The child runs `agt registry intent --adopt …`, and `agt registry topics --tree` shows it under the parent.
4. **Cursor fork with two windows open.** Focus another project's window, then trigger a fork from the first session. The tab must open in the first session's project. Record which window got it.
5. **Herdr fork.** Inside a Herdr pane (`HERDR_ENV=1`), start Claude Code and set an intent, then fork. A new pane opens on the right, the agent starts, and the prompt is sent without anything from you.
6. **Codex reminder.** In Codex, send a prompt. The first turn mentions the intent line, or sets one.
7. **Cursor agent.** In Cursor's own agent, start a chat. The session-start context includes the "No intent set" line (known to be unreliable in Cursor; record what happened).

## Results

| Date | Check | Result |
|---|---|---|
```

- [ ] **Step 3: Commit**

```bash
git add tests/blackbox/test_topics_agent.py tests/blackbox/MANUAL.md
git commit -m "test(registry): real-agent topic checks and a manual checklist"
```

---

### Task 10: Docs

**Files:**
- Modify: `README.md` (registry)
- Modify: `docs/specs/plugin.md`
- Modify: `docs/superpowers/specs/2026-11-25-topic-awareness-design.md`

- [ ] **Step 1: README section**

In `modules/registry/README.md`, add after the `### self` section:

````markdown
### intent / topic / topics / fork

A session's intent (fixed) and its current topic (changes under the intent), kept in a per-session log at `topics/<type>/<session_id>.jsonl` next to the registry file. Prune and unregister never touch it. These commands run in the CLI process, not through the daemon. The session comes from `--type` and `--session-id`, or from the engine's env (`CLAUDE_CODE_SESSION_ID`, `CODEX_THREAD_ID`, `CURSOR_CONVERSATION_ID`).

```bash
agent-registry intent "Make inbox entries topic-aware"   # once per session; exit 4 if set
agent-registry intent --adopt tp-7k3q                     # a forked child binds to its topic
agent-registry topic "Decide where topic records live"    # exit 1 without an intent
agent-registry topic --done [tp-…]                        # or --park [tp-…] --ref <park id>
agent-registry topics [--session S | --open | --tree]
agent-registry fork "Retry policy" --side --brief-file brief.md [--backend cursor|herdr|none]
agent-registry topic-context                              # the hook's one-line reminder
```

`fork` writes the brief to `briefs/<tp-id>.md` and opens a visible session. `cursor` brings the project window forward, then opens a Claude Code tab with the prompt filled in; you press Enter. `herdr` (the default inside Herdr) splits a pane and starts the agent. `none` only prints the prompt. `list` shows each row's `intent:` and `topic:`. The rules agents follow live in the `topic-awareness` skill.

Black-box checks: `.venv/bin/python -m pytest tests/blackbox/test_topics_cli.py tests/blackbox/test_topics_hook.py`; with real agents, `tests/blackbox/test_topics_agent.py`; by hand, `tests/blackbox/MANUAL.md`.
````

- [ ] **Step 2: Plugin spec lines**

In `docs/specs/plugin.md` under `## Hooks`, add:

```markdown
- On a Claude Code or Codex `UserPromptSubmit`, `ping` also prints `hookSpecificOutput.additionalContext` with the session's topic line from `topic-context`. A Claude `PreToolUse` ping prints nothing. — `plugin/scripts/registry-hook`
- Claude `ensure` appends the topic line to the SessionStart context. Cursor `ensure` prints it as `additional_context`; Cursor `ping` still prints only `{"continue":true}`, because `beforeSubmitPrompt` can't add context. — `plugin/scripts/registry-hook`
```

- [ ] **Step 3: Write the refinements back into the spec**

In `docs/superpowers/specs/2026-11-25-topic-awareness-design.md`:
- In the events table, change the `forked` row's extra fields to `` `parent`, `mode` (`side` or `new_intent`), `backend`, `brief` (path) ``.
- Replace the **Live entry** paragraph with: `**Live entry.** \`list\` and the board add \`intent\` and \`topic\` (each \`{id, title}\` or null) to every row, derived from the session's log when the list is built. They are not stored in \`registry.json\`, so a daemon running older code can't drop them. \`summary\` stays as it is.`
- In Testing, change the tier-1 file to `` `tests/blackbox/test_topics_cli.py` and `tests/blackbox/test_topics_hook.py` ``.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/specs/plugin.md docs/superpowers/specs/2026-11-25-topic-awareness-design.md
git commit -m "docs(registry): topic awareness in the README, plugin spec and design"
```

---

### Task 11: Deploy and verify end to end

No new files. Do the deploy, then run every tier. Report each result as observed.

- [ ] **Step 1: Full unit and tier-1 suites**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m pytest tests/blackbox/test_topics_cli.py tests/blackbox/test_topics_hook.py -q`
Expected: all pass.

- [ ] **Step 2: Update the Claude Code plugin**

The Claude hooks run from `~/.claude/plugins/cache/agent-registry/agent-registry/<version>/`, which is a copy, not the repo. Bump `"version"` in `plugin/.claude-plugin/plugin.json` from `0.2.0` to `0.3.0`, commit it (`chore(registry): plugin 0.3.0 for the topic hook`), then run:

```bash
claude plugin marketplace update agent-registry
claude plugin update agent-registry@agent-registry
diff ~/.claude/plugins/cache/agent-registry/agent-registry/0.3.0/scripts/registry-hook plugin/scripts/registry-hook && echo SAME
```

Expected: `SAME`. If `marketplace update` isn't a valid subcommand, check `claude plugin --help` for the marketplace refresh command and use it. Codex and Cursor read the hook straight from the repo (`~/.codex/hooks.json`, `~/.cursor/hooks.json`), so they need no update.

- [ ] **Step 3: Restart the registry daemon**

The daemon caches code, so `list` won't show topics until it restarts:

```bash
kill "$(cat ~/.local/share/agent-registry/daemon.pid)"
agt registry status
```

Expected: `status` starts a fresh daemon and reports it healthy.

- [ ] **Step 4: Real-agent tier**

Run: `.venv/bin/python -m pytest tests/blackbox/test_topics_agent.py -v`
Expected: the Claude test passes, and the Codex test passes or reports exactly what Codex did. Run the Claude test three times. Report the pass count rather than claiming it is stable.

- [ ] **Step 5: Manual checklist**

Run the `tests/blackbox/MANUAL.md` checks that can be driven from here (1, 2, 3 and 6). Ask Tiago to confirm what shows on screen for 3, 4, 5 and 7. Fill the results table and commit it (`test(registry): manual topic checks, <date>`).
