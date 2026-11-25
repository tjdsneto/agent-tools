# Topic-Aware Inbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every inbox question and report carries a snapshot of the asking session's topic path (root intent down to its topic), the feed shows and groups by that path, and the registry's topic log records `asked`, `posted`, `answered` and `closed` so `topic --done` can name the questions still waiting.

**Architecture:** The registry gains two in-process commands, `topic-path` (walks parent links across every session's log) and `topic-note` (appends an inbox note to the right log), and its replay treats notes as history only. The inbox talks to the registry through one function, `agent_inbox.topics.registry`, which runs `agt registry …` with a 2 s timeout, returns parsed JSON (or a `NOT_FOUND` sentinel, or None) and never raises. The path is stored in a new `entries.topic_path jsonb` column when the entry is created; pages render from that column and never call the registry. A pure `grouping` module does the context line, the intent filter and Group by, and `web.py` renders them.

**Tech Stack:** Python 3.14, Postgres 17 (psycopg 3), stdlib `http.server`, pytest, headless Chrome for the visual check. Spec: `modules/inbox/docs/superpowers/specs/2026-11-25-topic-aware-inbox-design.md`. Spec 1 (shipped): `modules/registry/docs/superpowers/specs/2026-11-25-topic-awareness-design.md`.

**Spec refinements this plan makes** (Task 12 writes them back into the spec):
- A request's `"topic"` is accepted from any asker, not only `--script`, and wins over the session's own path. The asker named it on purpose.
- Notes are sent inline, after the commit, with the same 2 s timeout. No background process. Measured while writing this plan: one `agt registry` CLI call takes 0.11 to 0.13 s on this machine (`agt registry topics --open`, three runs), so an ask or post adds about 0.25 s (path, then note). Task 10 re-measures with the real commands.
- `closed` carries `state` = `withdrawn`, `expired` or `superseded`.
- `topic-path` builds one index of minted topics per call instead of calling `find_topic` per step. Same rule as `find_topic`: the first minting event for an id wins.
- Notes land in their topic's `notes` list in `_replay` (when that log already knows the topic) and in each `topics --tree` node. A note never creates, closes or re-dates a topic.
- Topic tree nests one level: forked intents become sub-sections of their root, even a fork of a fork.
- Group by also applies in History, where its sections replace the day headings.
- "On this topic" sits at the end of the entry page, after the follow-up form, so the thread and its reply box stay together.
- The context line reads `… › Intent › Topic` when the path is longer than two.
- `AGENT_INBOX_AGT` overrides the `agt` binary the inbox runs, so the black-box suite can point it at the checkout under test or at a missing file.
- `db.ensure_schema` takes the schema advisory lock on every connect, because the new `CREATE INDEX IF NOT EXISTS` can race with itself on the first connect after deploy.

**Conventions:**
- Python: 4-space indents, `from __future__ import annotations` in source modules, docstrings only where the surrounding code has them.
- Markdown: no hard-wrapped prose.
- Each commit message ends with the co-author trailer your session's system reminder gives. Add files by explicit path. Never `git add -A`, never `git stash`.
- Unit tests: `.venv/bin/python -m pytest -q`, run from the module directory. Before this work: registry 272 passed, inbox 143 passed.
- The inbox tests use the shared `agent_inbox_test` database and drop its tables on every test. Don't run two inbox suites at once (another checkout's included), and don't run them while Task 11's screenshot server is up.

**Where the work happens (spec 1's rules):**
- All implementation runs in a git worktree on branch `tn/feat/topic-aware-inbox`: `/Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox` (Task 0). Another session works in the main checkout; don't edit files there.
- Black-box tests touch only public surfaces: `agt` commands, files on disk, and the Postgres store. They never import `agent_inbox` or `agent_registry`.
- Deploy only from the main checkout, after the merge (Task 14). Never run `./install.sh` from the worktree: it would relink `agt` and rewrite the LaunchAgent to point at the worktree.

Below, `WT` means `/Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox`. Commands spell it out in full because each shell starts fresh.

---

## File map

| File | Responsibility |
|---|---|
| `modules/registry/src/agent_registry/topics.py` (modify) | `path_from`, `session_path`; note kinds, `add_note`, `open_questions`; `_replay` and `tree` treat notes as history |
| `modules/registry/src/agent_registry/topic_cli.py` (modify) | `topic-path` and `topic-note` commands; `topic --done` adds `open_questions` |
| `modules/registry/tests/test_topic_paths.py` (create) | Path walking: session, fork, missing parent, cycle |
| `modules/registry/tests/test_topic_notes.py` (create) | Note kinds, which log, replay and tree ignore notes for status, open questions |
| `modules/registry/tests/test_topic_cli.py` (modify) | The two commands and `open_questions` through `main()` |
| `modules/inbox/src/agent_inbox/topics.py` (create) | The inbox's one door into the registry: `registry()`, `path_for()`, `note()` |
| `modules/inbox/src/agent_inbox/grouping.py` (create) | Pure: context line, intent of a path, intent filter, Group by sections |
| `modules/inbox/src/agent_inbox/db.py`, `schema.sql` (modify) | `topic_path` column and `entries_topic` index |
| `modules/inbox/src/agent_inbox/validate.py` (modify) | Optional `topic` in a request |
| `modules/inbox/src/agent_inbox/store.py` (modify) | Store the path; notes after commit; `note_closed`; `same_topic` |
| `modules/inbox/src/agent_inbox/serve.py` (modify) | Expiry sends `closed` |
| `modules/inbox/src/agent_inbox/web.py` (modify) | Context line, intent filter, Group by and its cookie, grouped rendering, breadcrumb, "On this topic" |
| `modules/inbox/tests/conftest.py` (modify) | Autouse `fake_registry`; collect `tests/blackbox` only on request |
| `modules/inbox/tests/test_topics.py`, `test_store_topics.py`, `test_grouping.py` (create) | Unit tests |
| `modules/inbox/tests/test_db.py`, `test_validate.py`, `test_web.py` (modify) | Unit tests |
| `modules/inbox/tests/blackbox/conftest.py`, `test_topic_inbox.py` (create) | Black-box suite: temp registry plus the test database |
| `modules/inbox/tests/visual/seed_topics.py` (create) | Seeds the test database for the screenshot check |
| `modules/inbox/README.md`, `modules/inbox/DESIGN.md`, `modules/registry/README.md`, the spec (modify) | Docs |
| `skills/topic-awareness/SKILL.md`, `skills/agent-inbox/SKILL.md` (modify) | Agent rules for `open_questions` and `"topic"` |

---

### Task 0: Worktree

**Files:** none.

- [ ] **Step 1: Create the worktree and branch**

```bash
cd /Users/tjdsneto/projects/agent-tools
git worktree add .worktrees/topic-aware-inbox -b tn/feat/topic-aware-inbox main
git -C .worktrees/topic-aware-inbox log --oneline -1
```

Expected: the worktree is created and its HEAD is the same commit as `main`. `.worktrees/` is already in `.gitignore`.

- [ ] **Step 2: Give each module its own venv**

`.venv` is untracked, so the worktree has none. Create them the way `install.sh` does:

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox
for mod in registry inbox; do
  python3 -m venv "modules/$mod/.venv"
  "modules/$mod/.venv/bin/pip" install -q -r "modules/$mod/requirements.txt"
done
```

Expected: no errors. (If pip has no network, symlink the main checkout's venvs instead: `ln -s /Users/tjdsneto/projects/agent-tools/modules/$mod/.venv modules/$mod/.venv`. A symlink is not matched by the `.venv/` ignore rule, so never commit it.)

- [ ] **Step 3: Baseline both suites**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/registry && .venv/bin/python -m pytest -q | tail -1
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/inbox && .venv/bin/python -m pytest -q | tail -1
```

Expected: `272 passed` and `143 passed`.

---

### Task 1: Registry topic paths

**Files:**
- Modify: `modules/registry/src/agent_registry/topics.py` (after `find_topic`)
- Test: `modules/registry/tests/test_topic_paths.py`

- [ ] **Step 1: Write the failing tests**

Create `modules/registry/tests/test_topic_paths.py`:

```python
import json

from agent_registry import topics


def _node(ev, kind):
    return {"id": ev["topic"]["id"], "title": ev["topic"]["title"], "kind": kind}


def _write(agent_type, session_id, *events):
    path = topics.log_path(agent_type, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")


def test_session_path_runs_from_the_intent_to_the_current_topic(tmp_registry):
    intent = topics.set_intent("claude", "s1", "Ship it")
    plan = topics.open_topic("claude", "s1", "Plan")
    assert topics.session_path("claude", "s1") == [_node(intent, "intent"), _node(plan, "topic")]


def test_session_path_ends_at_the_intent_when_no_topic_is_open(tmp_registry):
    intent = topics.set_intent("claude", "s1", "Ship it")
    assert topics.session_path("claude", "s1") == [_node(intent, "intent")]
    topics.open_topic("claude", "s1", "Plan")
    topics.close_topic("claude", "s1", "done")
    assert topics.session_path("claude", "s1") == [_node(intent, "intent")]


def test_a_session_without_an_intent_has_no_path(tmp_registry):
    assert topics.session_path("claude", "nobody") is None


def test_the_path_crosses_a_fork(tmp_registry):
    root = topics.set_intent("claude", "p", "Parent")
    main = topics.open_topic("claude", "p", "Main line")
    fork = topics.record_fork("claude", "p", "Side quest", mode="side", backend="none", brief_text="b")
    topics.adopt("claude", "c", fork["topic"]["id"])
    check = topics.open_topic("claude", "c", "Check it")
    assert topics.session_path("claude", "c") == [
        _node(root, "intent"), _node(main, "topic"), _node(fork, "intent"), _node(check, "topic"),
    ]


def test_path_from_a_topic_id(tmp_registry):
    intent = topics.set_intent("claude", "s1", "Ship it")
    plan = topics.open_topic("claude", "s1", "Plan")
    assert topics.path_from(plan["topic"]["id"]) == [_node(intent, "intent"), _node(plan, "topic")]
    assert topics.path_from("tp-zzzz") is None


def test_an_unadopted_fork_is_a_topic(tmp_registry):
    root = topics.set_intent("claude", "p", "Parent")
    fork = topics.record_fork("claude", "p", "Side quest", mode="side", backend="none", brief_text="b")
    assert topics.path_from(fork["topic"]["id"]) == [_node(root, "intent"), _node(fork, "topic")]


def test_a_missing_parent_ends_the_walk(tmp_registry):
    _write("claude", "s1", {"event": "topic", "topic": {"id": "tp-kid", "title": "Kid"}, "parent": "tp-gone"})
    assert topics.path_from("tp-kid") == [{"id": "tp-kid", "title": "Kid", "kind": "topic"}]


def test_a_cycle_ends_the_walk(tmp_registry):
    _write("claude", "a", {"event": "topic", "topic": {"id": "tp-a", "title": "A"}, "parent": "tp-b"})
    _write("claude", "b", {"event": "topic", "topic": {"id": "tp-b", "title": "B"}, "parent": "tp-a"})
    assert [n["id"] for n in topics.path_from("tp-a")] == ["tp-b", "tp-a"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/registry && .venv/bin/python -m pytest tests/test_topic_paths.py -q`
Expected: 8 failed, `AttributeError: module 'agent_registry.topics' has no attribute 'session_path'` (and `path_from`).

- [ ] **Step 3: Implement**

In `modules/registry/src/agent_registry/topics.py`, add right after `find_topic`:

```python
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
```

- [ ] **Step 4: Run them to see them pass**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/registry && .venv/bin/python -m pytest tests/test_topic_paths.py -q`
Expected: `8 passed`.

- [ ] **Step 5: Commit**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/registry
git add src/agent_registry/topics.py tests/test_topic_paths.py
git commit -m "feat(registry): a topic's path walks parent links across session logs"
```

---

### Task 2: Registry inbox notes

**Files:**
- Modify: `modules/registry/src/agent_registry/topics.py`
- Test: `modules/registry/tests/test_topic_notes.py`

- [ ] **Step 1: Write the failing tests**

Create `modules/registry/tests/test_topic_notes.py`:

```python
import json

import pytest

from agent_registry import topics


def _write(agent_type, session_id, *events):
    path = topics.log_path(agent_type, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")


def _notes(agent_type, session_id):
    return [e for e in topics.read_events(agent_type, session_id) if e["event"] in topics.NOTE_KINDS]


def test_a_note_goes_to_the_asking_session_when_it_holds_the_topic(tmp_registry):
    topics.set_intent("claude", "s1", "Ship it")
    plan = topics.open_topic("claude", "s1", "Plan")["topic"]["id"]
    ev = topics.add_note("asked", plan, "ib-1", agent_type="claude", session_id="s1", title="Which order?")
    assert ev == {
        "event": "asked", "at": ev["at"], "topic": {"id": plan, "title": "Plan"}, "entry": "ib-1", "title": "Which order?",
    }
    assert _notes("claude", "s1") == [ev]


def test_a_note_falls_back_to_the_topic_owner(tmp_registry):
    root = topics.set_intent("claude", "p", "Parent")["topic"]["id"]
    topics.add_note("posted", root, "ib-2", title="Backup done")  # a script asker: no session
    topics.add_note("asked", root, "ib-3", agent_type="codex", session_id="other", title="Q")  # doesn't hold it
    assert [n["entry"] for n in _notes("claude", "p")] == ["ib-2", "ib-3"]
    assert topics.read_events("codex", "other") == []


def test_an_adopted_topic_note_goes_to_the_adopter(tmp_registry):
    topics.set_intent("claude", "p", "Parent")
    fork = topics.record_fork("claude", "p", "Side", mode="side", backend="none", brief_text="b")["topic"]["id"]
    topics.adopt("claude", "c", fork)
    topics.add_note("asked", fork, "ib-4", agent_type="claude", session_id="c", title="Q")
    assert [n["entry"] for n in _notes("claude", "c")] == ["ib-4"]
    assert _notes("claude", "p") == []


def test_note_kinds_and_their_fields(tmp_registry):
    tid = topics.set_intent("claude", "s1", "Ship it")["topic"]["id"]
    answered = topics.add_note("answered", tid, "ib-1", value="x" * 300, via="web")
    assert answered["value"] == "x" * 200 and answered["via"] == "web"
    closed = topics.add_note("closed", tid, "ib-2", closed_as="withdrawn")
    assert closed["state"] == "withdrawn"
    bad = [
        ("asked", {}),
        ("answered", {"value": "a", "via": "pigeon"}),
        ("answered", {"via": "web"}),
        ("closed", {"closed_as": "open"}),
        ("shrugged", {}),
    ]
    for kind, kw in bad:
        with pytest.raises(topics.TopicUsageError):
            topics.add_note(kind, tid, "ib-9", **kw)
    with pytest.raises(topics.TopicUsageError):
        topics.add_note("asked", tid, "  ", title="t")
    with pytest.raises(topics.TopicNotFoundError):
        topics.add_note("asked", "tp-zzzz", "ib-9", title="t")


def test_replay_ignores_notes_for_status(tmp_registry):
    topics.set_intent("claude", "s1", "Ship it")
    plan = topics.open_topic("claude", "s1", "Plan")["topic"]["id"]
    topics.close_topic("claude", "s1", "done")
    before = {t["id"]: (t["status"], t["at"]) for t in topics.state("claude", "s1")["topics"]}
    topics.add_note("answered", plan, "ib-1", agent_type="claude", session_id="s1", value="a", via="chat")
    st = topics.state("claude", "s1")
    assert {t["id"]: (t["status"], t["at"]) for t in st["topics"]} == before
    assert st["topic"] is None
    held = next(t for t in st["topics"] if t["id"] == plan)
    assert [(n["event"], n["entry"]) for n in held["notes"]] == [("answered", "ib-1")]


def test_a_note_never_creates_a_topic(tmp_registry):
    _write("claude", "s1", {"event": "asked", "topic": {"id": "tp-else", "title": "x"}, "entry": "ib-1", "title": "Q"})
    assert topics.state("claude", "s1")["topics"] == []
    assert topics.open_topics() == [] and topics.tree() == []


def test_a_late_note_does_not_re_date_a_forked_topic_in_the_tree(tmp_registry):
    topics.set_intent("claude", "p", "Parent")
    fork = topics.record_fork("claude", "p", "Side", mode="side", backend="none", brief_text="b")["topic"]["id"]
    topics.adopt("claude", "c", fork)
    topics.add_note("asked", fork, "ib-5", title="Script Q")  # owner is p, which logged the fork
    child = topics.tree()[0]["children"][0]
    assert child["status"] == "open"
    assert [n["entry"] for n in child["notes"]] == ["ib-5"]


def test_open_questions_are_asks_with_no_answer_or_close(tmp_registry):
    tid = topics.set_intent("claude", "s1", "Ship it")["topic"]["id"]
    for entry in ("ib-1", "ib-2", "ib-3"):
        topics.add_note("asked", tid, entry, title="Q")
    topics.add_note("posted", tid, "ib-4", title="R")
    topics.add_note("answered", tid, "ib-1", value="a", via="web")
    topics.add_note("closed", tid, "ib-3", closed_as="withdrawn")
    assert topics.open_questions(tid) == ["ib-2"]
    assert topics.open_questions("tp-zzzz") == []


def test_a_note_without_an_entry_is_skipped(tmp_registry):
    _write(
        "claude", "s1",
        {"event": "intent", "topic": {"id": "tp-root", "title": "R"}},
        {"event": "asked", "topic": {"id": "tp-root", "title": "R"}, "entry": 5, "title": "Q"},
    )
    assert [e["event"] for e in topics.read_events("claude", "s1")] == ["intent"]
    assert topics.open_questions("tp-root") == []
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/registry && .venv/bin/python -m pytest tests/test_topic_notes.py -q`
Expected: 9 failed with `AttributeError: module 'agent_registry.topics' has no attribute 'add_note'` (or `NOTE_KINDS`).

- [ ] **Step 3: Implement the note constants and the read filter**

In `topics.py`, below `CLOSING = ("done", "parked", "forked")`, add:

```python
# Inbox activity a topic's history records. A note never opens, closes or re-dates a topic.
NOTE_KINDS = ("asked", "posted", "answered", "closed")
NOTE_VIAS = ("web", "telegram", "chat", "cli")
NOTE_CLOSED_STATES = ("withdrawn", "expired", "superseded")
NOTE_VALUE_MAX = 200
NOTE_FIELDS = ("entry", "title", "value", "via", "state")
```

In `read_events`, just before `events.append(event)`, add:

```python
        if event.get("event") in NOTE_KINDS and not (isinstance(event.get("entry"), str) and event["entry"]):
            continue  # a note must name its inbox entry
```

- [ ] **Step 4: Make `_replay` and `tree` treat notes as history**

Replace `_replay` with:

```python
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
```

In `tree()`, change the node literal and collect the notes:

```python
            node = nodes.setdefault(t["id"], {
                "id": t["id"], "title": t["title"], "parent": None, "status": t["status"],
                "sessions": [], "children": [], "notes": [],
            })
            node["notes"].extend(t["notes"])
```

and replace the final roots loop with:

```python
    roots = []
    for node in nodes.values():
        node["notes"].sort(key=lambda n: n.get("at") or "")
        parent = nodes.get(node["parent"]) if node["parent"] else None
        (parent["children"] if parent else roots).append(node)
    return roots
```

- [ ] **Step 5: Add `add_note` and `open_questions`**

Add after `session_path` (from Task 1):

```python
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
```

- [ ] **Step 6: Run the new tests, then the whole suite**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/registry && .venv/bin/python -m pytest tests/test_topic_notes.py -q && .venv/bin/python -m pytest -q | tail -1`
Expected: `9 passed`, then `289 passed` (272 + 8 + 9). A failure in an older test that compares a topic dict means it now has a `notes` key; fix the test's expectation, not the code.

- [ ] **Step 7: Commit**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/registry
git add src/agent_registry/topics.py tests/test_topic_notes.py
git commit -m "feat(registry): topic logs record inbox notes as history and list open questions"
```

---

### Task 3: Registry commands

**Files:**
- Modify: `modules/registry/src/agent_registry/topic_cli.py`
- Test: `modules/registry/tests/test_topic_cli.py`

- [ ] **Step 1: Write the failing tests**

Append to `modules/registry/tests/test_topic_cli.py`:

```python
def test_topic_path_for_a_session_and_a_topic(tmp_registry, capsys):
    code, out, _ = _run(capsys, "topic-path", *WHO)
    assert code == EXIT_OK and out.strip() == "null"
    _run(capsys, "intent", "Ship it", *WHO)
    _, out, _ = _run(capsys, "topic", "Plan", *WHO)
    plan = json.loads(out)["topic"]["id"]
    code, out, _ = _run(capsys, "topic-path", *WHO)
    assert code == EXIT_OK
    path = json.loads(out)
    assert [(n["title"], n["kind"]) for n in path] == [("Ship it", "intent"), ("Plan", "topic")]
    code, out, _ = _run(capsys, "topic-path", "--topic", plan)
    assert code == EXIT_OK and json.loads(out) == path
    code, _, err = _run(capsys, "topic-path", "--topic", "tp-zzzz")
    assert code == EXIT_NOT_FOUND and "topic not found" in err


def test_topic_note_each_kind(tmp_registry, capsys):
    _, out, _ = _run(capsys, "intent", "Ship it", *WHO)
    tid = json.loads(out)["topic"]["id"]
    cases = [
        (["asked", "--title", "Which?"], {"title": "Which?"}),
        (["posted", "--title", "Done"], {"title": "Done"}),
        (["answered", "--value", "b", "--via", "web"], {"value": "b", "via": "web"}),
        (["closed", "--state", "expired"], {"state": "expired"}),
    ]
    for argv, extra in cases:
        code, out, _ = _run(capsys, "topic-note", argv[0], "--topic", tid, "--entry", "ib-1", *argv[1:], *WHO)
        assert code == EXIT_OK
        ev = json.loads(out)
        assert (ev["event"], ev["entry"], ev["topic"]["id"]) == (argv[0], "ib-1", tid)
        assert {k: ev[k] for k in extra} == extra
    assert [e["event"] for e in topics.read_events("claude", "s1")] == ["intent", "asked", "posted", "answered", "closed"]


def test_topic_note_errors(tmp_registry, capsys):
    _, out, _ = _run(capsys, "intent", "Ship it", *WHO)
    tid = json.loads(out)["topic"]["id"]
    assert _run(capsys, "topic-note", "shrugged", "--topic", tid, "--entry", "ib-1")[0] == EXIT_USAGE
    assert _run(capsys, "topic-note", "answered", "--topic", tid, "--entry", "ib-1", "--value", "a", "--via", "fax")[0] == EXIT_USAGE
    assert _run(capsys, "topic-note", "asked", "--topic", tid, "--entry", "ib-1", "--title", "t", "--type", "claude")[0] == EXIT_USAGE
    assert _run(capsys, "topic-note", "asked", "--topic", "tp-zzzz", "--entry", "ib-1", "--title", "t")[0] == EXIT_NOT_FOUND


def test_done_lists_the_questions_still_open(tmp_registry, capsys):
    _run(capsys, "intent", "Ship it", *WHO)
    _, out, _ = _run(capsys, "topic", "Plan", *WHO)
    tid = json.loads(out)["topic"]["id"]
    for entry in ("ib-1", "ib-2", "ib-3"):
        _run(capsys, "topic-note", "asked", "--topic", tid, "--entry", entry, "--title", "Q", *WHO)
    _run(capsys, "topic-note", "answered", "--topic", tid, "--entry", "ib-1", "--value", "a", "--via", "chat", *WHO)
    _run(capsys, "topic-note", "closed", "--topic", tid, "--entry", "ib-3", "--state", "withdrawn", *WHO)
    code, out, _ = _run(capsys, "topic", "--done", *WHO)
    assert code == EXIT_OK
    done = json.loads(out)
    assert done["event"] == "done" and done["open_questions"] == ["ib-2"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/registry && .venv/bin/python -m pytest tests/test_topic_cli.py -q`
Expected: the 4 new tests fail. argparse rejects `topic-path` and `topic-note` as invalid choices (`SystemExit: 2`), and `open_questions` is a `KeyError`.

- [ ] **Step 3: Implement**

In `topic_cli.py`, replace the `COMMANDS` line:

```python
COMMANDS = frozenset({"intent", "topic", "topics", "fork", "topic-context", "topic-path", "topic-note"})
```

At the end of `add_parsers`, after the `topic-context` parser, add:

```python
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
```

In `_dispatch`, right after the `if cmd == "topics":` block and before the function-level `agent_type, session_id = _identity(args)` (not the indented one inside the `topics` block), add:

```python
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
```

In the `topic` branch, replace

```python
        if args.done is not None:
            return topics.close_topic(agent_type, session_id, "done", args.done or None)
```

with

```python
        if args.done is not None:
            done = topics.close_topic(agent_type, session_id, "done", args.done or None)
            return {**done, "open_questions": topics.open_questions(done["topic"]["id"])}
```

`run()` already prints `json.dumps(None)` as `null` for a session with no intent.

- [ ] **Step 4: Run the CLI tests, then the whole suite and the tier-1 black-box suite**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/registry && .venv/bin/python -m pytest tests/test_topic_cli.py -q && .venv/bin/python -m pytest -q | tail -1 && .venv/bin/python -m pytest tests/blackbox/test_topics_cli.py tests/blackbox/test_topics_hook.py -q | tail -1`
Expected: the CLI file passes, the full suite reports `293 passed`, tier 1 passes.

- [ ] **Step 5: Try it by hand on a temp registry**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox
export AGENT_REGISTRY_PATH="$(mktemp -d)/registry/registry.json"
agt/agt registry intent "Hand check" --type claude --session-id h1 >/dev/null
agt/agt registry topic-path --type claude --session-id h1
agt/agt registry topic-note asked --topic "$(agt/agt registry topic-path --type claude --session-id h1 | python3 -c 'import json,sys; print(json.load(sys.stdin)[-1]["id"])')" --entry ib-test --title "Hand check?" --type claude --session-id h1
agt/agt registry topic --done --type claude --session-id h1 || true
```

Expected: a one-node path with `"kind": "intent"`; the asked event; the last command exits 2 (`no current topic`), since only the intent exists. That is spec 1's behaviour, unchanged.

- [ ] **Step 6: Commit**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/registry
git add src/agent_registry/topic_cli.py tests/test_topic_cli.py
git commit -m "feat(registry): topic-path and topic-note commands; done lists open questions"
```

---

### Task 4: The inbox's registry door

**Files:**
- Create: `modules/inbox/src/agent_inbox/topics.py`
- Modify: `modules/inbox/tests/conftest.py`
- Test: `modules/inbox/tests/test_topics.py`

- [ ] **Step 1: Add the autouse fake to the test conftest**

In `modules/inbox/tests/conftest.py`, after the `no_telegram` fixture, add:

```python
class FakeRegistry:
    """Stands in for agent_inbox.topics.registry. replies maps a registry command to its
    result, or to a callable that gets the args. Unset commands return None, like a
    registry that is down."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.replies: dict = {}

    def __call__(self, *args):
        self.calls.append(list(args))
        reply = self.replies.get(args[0])
        return reply(*args) if callable(reply) else reply

    def notes(self) -> list[list[str]]:
        return [call[1:] for call in self.calls if call[0] == "topic-note"]


@pytest.fixture(autouse=True)
def fake_registry(monkeypatch):
    """Tests never shell out to the agent registry."""
    fake = FakeRegistry()
    monkeypatch.setattr("agent_inbox.topics.registry", fake)
    return fake
```

- [ ] **Step 2: Write the failing tests**

Create `modules/inbox/tests/test_topics.py`. `real_registry` is bound at import time, before the autouse fake replaces the module attribute, so these tests exercise the real subprocess call against a stand-in `agt` script:

```python
import stat
import time

import pytest

from agent_inbox import topics
from agent_inbox.errors import ValidationError
from agent_inbox.topics import registry as real_registry

PATH = [{"id": "tp-root", "title": "Ship it", "kind": "intent"}, {"id": "tp-plan", "title": "Plan", "kind": "topic"}]


def fake_agt(tmp_path, monkeypatch, body):
    """A stand-in `agt` that writes its args to calls.txt, one per line, then runs body."""
    script = tmp_path / "agt"
    script.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{tmp_path}/calls.txt"\n{body}\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("AGENT_INBOX_AGT", str(script))
    return tmp_path / "calls.txt"


def test_registry_returns_parsed_json_and_passes_the_args(tmp_path, monkeypatch):
    calls = fake_agt(tmp_path, monkeypatch, "echo '[1, 2]'")
    assert real_registry("topic-path", "--topic=tp-a") == [1, 2]
    assert calls.read_text().splitlines() == ["registry", "topic-path", "--topic=tp-a"]


def test_registry_reports_an_unknown_topic(tmp_path, monkeypatch):
    fake_agt(tmp_path, monkeypatch, "echo 'agent-registry: topic not found: tp-x' >&2; exit 2")
    assert real_registry("topic-path", "--topic=tp-x") is topics.NOT_FOUND


@pytest.mark.parametrize("body", [
    "echo boom >&2; exit 1",
    "echo 'not json'",
    "echo 'usage: agent-registry ...' >&2; exit 2",  # argparse also exits 2; that is not "not found"
])
def test_registry_failures_are_none_with_a_warning(tmp_path, monkeypatch, capsys, body):
    fake_agt(tmp_path, monkeypatch, body)
    assert real_registry("topic-path", "--topic=tp-x") is None
    assert "continuing without the topic link" in capsys.readouterr().err


def test_a_missing_registry_is_none(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENT_INBOX_AGT", str(tmp_path / "no-such-agt"))
    assert real_registry("topic-path") is None
    assert "continuing without the topic link" in capsys.readouterr().err


def test_a_slow_registry_times_out(tmp_path, monkeypatch):
    fake_agt(tmp_path, monkeypatch, "exec sleep 5")
    monkeypatch.setattr(topics, "TIMEOUT_SEC", 0.3)
    start = time.monotonic()
    assert real_registry("topic-path") is None
    assert time.monotonic() - start < 2


def test_path_for_a_session_and_a_named_topic(fake_registry):
    fake_registry.replies["topic-path"] = PATH
    assert topics.path_for(engine="claude", session_id="s-1", topic=None) == PATH
    assert topics.path_for(engine="claude", session_id="s-1", topic="tp-plan") == PATH
    assert topics.path_for(engine=None, session_id=None, topic=None) is None
    assert fake_registry.calls == [
        ["topic-path", "--type=claude", "--session-id=s-1"],
        ["topic-path", "--topic=tp-plan"],
    ]


def test_path_for_an_unknown_topic_is_a_validation_error(fake_registry):
    fake_registry.replies["topic-path"] = topics.NOT_FOUND
    with pytest.raises(ValidationError, match="unknown topic tp-nope"):
        topics.path_for(engine=None, session_id=None, topic="tp-nope")


@pytest.mark.parametrize("reply", [None, [], {"id": "tp-a"}, [{"title": "no id"}], ["tp-a"]])
def test_path_for_drops_a_malformed_path(fake_registry, reply):
    fake_registry.replies["topic-path"] = reply
    assert topics.path_for(engine="claude", session_id="s-1", topic=None) is None


def test_path_for_normalises_nodes(fake_registry):
    fake_registry.replies["topic-path"] = [{"id": "tp-a", "title": 7, "kind": "weird", "extra": 1}]
    assert topics.path_for(engine="claude", session_id="s-1", topic=None) == [{"id": "tp-a", "title": None, "kind": "topic"}]


def test_note_names_the_last_topic_and_the_asker(fake_registry):
    topics.note("answered", "ib-1", PATH, engine="claude", session_id="s-1", value=["a", "b"], via="web", title=None)
    assert fake_registry.notes() == [[
        "answered", "--topic=tp-plan", "--entry=ib-1", "--value=a, b", "--via=web", "--type=claude", "--session-id=s-1",
    ]]


def test_note_without_a_path_does_nothing_and_without_an_asker_sends_none(fake_registry):
    topics.note("asked", "ib-1", None, title="Q")
    topics.note("asked", "ib-1", [], title="Q")
    assert fake_registry.calls == []
    topics.note("posted", "ib-2", PATH, title="R")
    assert fake_registry.notes() == [["posted", "--topic=tp-plan", "--entry=ib-2", "--title=R"]]
```

- [ ] **Step 3: Run them to see them fail**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/inbox && .venv/bin/python -m pytest tests/test_topics.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'agent_inbox.topics'`.

- [ ] **Step 4: Implement**

Create `modules/inbox/src/agent_inbox/topics.py`:

```python
"""The inbox's one door into the agent registry's topic log.

Every call runs `agt registry …` with a short timeout. A missing, slow or failing registry
never blocks an ask, a post or an answer: the entry or the topic history just lacks the link."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

from agent_inbox.errors import ValidationError

TIMEOUT_SEC = 2.0
# registry() returns this when the registry says the named topic does not exist.
NOT_FOUND = object()


def _agt() -> str:
    return os.environ.get("AGENT_INBOX_AGT") or "agt"


def _warn(args: tuple[str, ...], detail: object) -> None:
    what = args[0] if args else "call"
    print(f"agent-inbox: registry {what} failed, continuing without the topic link: {detail}", file=sys.stderr)


def registry(*args: str) -> Any:
    """Run `agt registry <args>`. Returns the parsed JSON stdout, NOT_FOUND for an unknown
    topic, or None on any other failure. Never raises."""
    try:
        proc = subprocess.run(
            [_agt(), "registry", *args],
            capture_output=True, text=True, timeout=TIMEOUT_SEC, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _warn(args, exc)
        return None
    # argparse also exits 2, so the registry's own message decides.
    if proc.returncode == 2 and "topic not found" in proc.stderr:
        return NOT_FOUND
    if proc.returncode != 0:
        _warn(args, proc.stderr.strip() or f"exit {proc.returncode}")
        return None
    try:
        return json.loads(proc.stdout)
    except ValueError as exc:
        _warn(args, exc)
        return None


def _clean(data: Any) -> list[dict] | None:
    """Keep a path only if every node has an id: it is stored and rendered as is."""
    if not isinstance(data, list) or not data:
        return None
    path = []
    for node in data:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"]:
            return None
        title = node.get("title")
        path.append({
            "id": node["id"],
            "title": title if isinstance(title, str) else None,
            "kind": "intent" if node.get("kind") == "intent" else "topic",
        })
    return path


def path_for(*, engine: str | None, session_id: str | None, topic: str | None) -> list[dict] | None:
    """The new entry's topic path. A named topic wins over the session's own path. An unknown
    named topic is the asker's mistake, so it is a validation error; a registry failure is not."""
    if topic:
        data = registry("topic-path", f"--topic={topic}")
        if data is NOT_FOUND:
            raise ValidationError(f"unknown topic {topic}")
    elif engine and session_id:
        data = registry("topic-path", f"--type={engine}", f"--session-id={session_id}")
    else:
        return None
    return None if data is NOT_FOUND else _clean(data)


def note(
    kind: str, entry_id: str, path: Any, *, engine: str | None = None, session_id: str | None = None,
    **fields: Any,
) -> None:
    """Record inbox activity in the history of the entry's topic (the path's last node). Best
    effort, never raises. `--key=value` keeps a value that starts with a dash from reading as a flag."""
    last = path[-1] if isinstance(path, list) and path else None
    topic = last.get("id") if isinstance(last, dict) else None
    if not topic:
        return
    args = ["topic-note", kind, f"--topic={topic}", f"--entry={entry_id}"]
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value)
        args.append(f"--{key}={value}")
    if engine and session_id:
        args += [f"--type={engine}", f"--session-id={session_id}"]
    registry(*args)
```

- [ ] **Step 5: Run the new tests, then the whole suite**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/inbox && .venv/bin/python -m pytest tests/test_topics.py -q && .venv/bin/python -m pytest -q | tail -1`
Expected: `17 passed`, then `160 passed`.

- [ ] **Step 6: Commit**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/inbox
git add src/agent_inbox/topics.py tests/test_topics.py tests/conftest.py
git commit -m "feat(inbox): one bounded, never-raising door into the registry's topic log"
```

---

### Task 5: The path on each entry

**Files:**
- Modify: `modules/inbox/src/agent_inbox/db.py`, `modules/inbox/src/agent_inbox/schema.sql`, `modules/inbox/src/agent_inbox/validate.py`, `modules/inbox/src/agent_inbox/store.py`
- Test: `modules/inbox/tests/test_db.py`, `modules/inbox/tests/test_validate.py`, `modules/inbox/tests/test_store_topics.py`

- [ ] **Step 1: Write the failing tests**

Append to `modules/inbox/tests/test_db.py`:

```python
def test_existing_database_gains_topic_path_and_its_index(conn):
    conn.execute("ALTER TABLE entries DROP COLUMN IF EXISTS topic_path")  # drops the index with it
    assert conn.execute("SELECT to_regclass('entries_topic') AS t").fetchone()["t"] is None
    db.ensure_schema(conn)
    col = conn.execute(
        "SELECT data_type FROM information_schema.columns WHERE table_name = 'entries' AND column_name = 'topic_path'"
    ).fetchone()
    assert col is not None and col["data_type"] == "jsonb"
    assert conn.execute("SELECT to_regclass('entries_topic') AS t").fetchone()["t"] is not None
```

Append to `modules/inbox/tests/test_validate.py`:

```python
def test_topic_is_an_optional_topic_id():
    assert validate_request({"title": "t"}, "post")["topic"] is None
    assert validate_request({"title": "t", "topic": "tp-7k3q"}, "post")["topic"] == "tp-7k3q"
    for bad in ("7k3q", "tp-", "tp-7k 3q", 7, ["tp-7k3q"]):
        with pytest.raises(ValidationError, match="topic must be a topic id"):
            validate_request({"title": "t", "topic": bad}, "post")
```

Create `modules/inbox/tests/test_store_topics.py`:

```python
import psycopg
import pytest

from agent_inbox import store, topics
from agent_inbox.errors import ValidationError
from agent_inbox.validate import validate_request

CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}
PATH = [{"id": "tp-root", "title": "Ship it", "kind": "intent"}, {"id": "tp-plan", "title": "Plan", "kind": "topic"}]


def ask(conn, **over):
    req = validate_request({"title": "Which split?", "control": CHOICE, **over}, "ask")
    return store.create_entry(conn, "ask", req, engine="claude", session_id="s-1")


def committed(dsn, entry_id):
    """The entry's state as another connection sees it: committed rows only."""
    with psycopg.connect(dsn) as other:
        row = other.execute("SELECT state FROM entries WHERE id = %s", (entry_id,)).fetchone()
    return row[0] if row else None


def test_an_ask_stores_the_session_path(conn, fake_registry):
    fake_registry.replies["topic-path"] = PATH
    e = ask(conn)
    assert e["topic_path"] == PATH
    assert store.get_entry(conn, e["id"])["topic_path"] == PATH
    assert fake_registry.calls[0] == ["topic-path", "--type=claude", "--session-id=s-1"]


def test_a_script_ask_resolves_its_named_topic(conn, fake_registry):
    fake_registry.replies["topic-path"] = PATH
    req = validate_request({"title": "Q", "control": CHOICE, "topic": "tp-plan"}, "ask")
    e = store.create_entry(conn, "ask", req, script="autopilot")
    assert e["topic_path"] == PATH
    assert fake_registry.calls[0] == ["topic-path", "--topic=tp-plan"]


def test_an_unknown_named_topic_is_rejected_and_nothing_is_stored(conn, fake_registry):
    fake_registry.replies["topic-path"] = topics.NOT_FOUND
    req = validate_request({"title": "Q", "control": CHOICE, "topic": "tp-nope"}, "ask")
    with pytest.raises(ValidationError, match="unknown topic tp-nope"):
        store.create_entry(conn, "ask", req, script="autopilot")
    assert conn.execute("SELECT count(*) AS n FROM entries").fetchone()["n"] == 0
    assert fake_registry.notes() == []


def test_a_registry_failure_still_creates_the_entry(conn, fake_registry):
    e = ask(conn)  # the fake answers None, like a registry that is down
    assert e["state"] == "open" and e["topic_path"] is None
    assert fake_registry.notes() == []


def test_ask_and_post_note_after_the_insert_commits(conn, inbox_db, fake_registry):
    fake_registry.replies["topic-path"] = PATH
    seen = []
    fake_registry.replies["topic-note"] = lambda *args: seen.append(committed(inbox_db, args[3].split("=", 1)[1]))
    q = ask(conn)
    p = store.create_entry(conn, "post", validate_request({"title": "Backup done"}, "post"), engine="claude", session_id="s-1")
    assert fake_registry.notes() == [
        ["asked", "--topic=tp-plan", f"--entry={q['id']}", "--title=Which split?", "--type=claude", "--session-id=s-1"],
        ["posted", "--topic=tp-plan", f"--entry={p['id']}", "--title=Backup done", "--type=claude", "--session-id=s-1"],
    ]
    assert seen == ["open", "unread"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/inbox && .venv/bin/python -m pytest tests/test_db.py tests/test_validate.py tests/test_store_topics.py -q`
Expected: the migration test fails (`col is not None`), the validate test fails with `KeyError: 'topic'`, and the store tests fail with `KeyError: 'topic_path'` or a missing call.

- [ ] **Step 3: Migrate the schema**

Replace `modules/inbox/src/agent_inbox/db.py` from the `MIGRATION = …` line through the end of `ensure_schema` with:

```python
MIGRATIONS = (
    "ALTER TABLE entries ADD COLUMN IF NOT EXISTS delivery jsonb NOT NULL DEFAULT '{}'::jsonb",
    # The asking session's topic path, root intent first, as it was when the entry was created.
    "ALTER TABLE entries ADD COLUMN IF NOT EXISTS topic_path jsonb",
    "CREATE INDEX IF NOT EXISTS entries_topic ON entries ((topic_path->-1->>'id'))",
)
OPS = """
CREATE TABLE IF NOT EXISTS ops (
    key   text PRIMARY KEY,
    value jsonb NOT NULL
)
"""


def dsn() -> str:
    return os.environ.get("AGENT_INBOX_DSN") or DEFAULT_DSN


def schema_sql() -> str:
    return resources.files("agent_inbox").joinpath("schema.sql").read_text()


def connect() -> psycopg.Connection:
    """Autocommit connection with dict rows. Multi-statement writes use conn.transaction()."""
    try:
        conn = psycopg.connect(dsn(), row_factory=dict_row, autocommit=True)
    except psycopg.OperationalError as e:
        raise StoreError(f"cannot reach the inbox store ({dsn()}): {e}") from e
    ensure_schema(conn)
    return conn


def ensure_schema(conn: psycopg.Connection) -> None:
    # Always under the lock: two first connects after a deploy would otherwise race on CREATE INDEX.
    conn.execute("SELECT pg_advisory_lock(%s)", (SCHEMA_LOCK,))
    try:
        if conn.execute("SELECT to_regclass('events') AS t").fetchone()["t"] is None:
            conn.execute(schema_sql())
        for sql in MIGRATIONS:
            conn.execute(sql)
        conn.execute(OPS)
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (SCHEMA_LOCK,))
```

In `schema.sql`, after the line `delivery      jsonb NOT NULL DEFAULT '{}'::jsonb,` add:

```sql
    topic_path    jsonb,
```

and after `CREATE INDEX IF NOT EXISTS entries_session ON entries (session_id);` add:

```sql
CREATE INDEX IF NOT EXISTS entries_topic ON entries ((topic_path->-1->>'id'));
```

- [ ] **Step 4: Accept `topic` in a request**

In `validate.py`, add `import re` below `from datetime import datetime`, and below `SOURCE_KEYS = {"kind", "ref", "url"}` add:

```python
TOPIC_ID = re.compile(r"tp-[a-z0-9]+")
```

In `validate_request`, just before `out = {`, add:

```python
    topic = raw.get("topic")
    if topic is not None and not (isinstance(topic, str) and TOPIC_ID.fullmatch(topic)):
        raise ValidationError("topic must be a topic id like tp-7k3q")
```

and add `"topic": topic,` to the `out` dict after `"expires_at": …`.

- [ ] **Step 5: Store the path and send the note**

In `store.py`, add this import directly above `from agent_inbox.constants import …`:

```python
from agent_inbox import topics
```

In `_shape`, after `"delivery": row.get("delivery") or {},` add:

```python
        "topic_path": row.get("topic_path"),
```

Replace `create_entry` from `params = {` to the end of the function with:

```python
    # Resolved before the insert: an unknown named topic must not leave an entry behind.
    path = topics.path_for(engine=engine, session_id=session_id, topic=req.get("topic"))
    params = {
        "kind": kind, "engine": engine, "model": model, "session_id": session_id,
        "cwd": cwd, "project": project_root(cwd), "script": script,
        "priority": req["priority"], "mode": mode, "title": req["title"],
        "summary": req.get("summary"), "detail": req.get("detail"), "html": req.get("html"),
        "control": _jsonb(req.get("control")), "source": _jsonb(req.get("source")),
        "expires_at": req.get("expires_at"), "state": state, "topic_path": _jsonb(path),
    }
    for _ in range(ID_ATTEMPTS):
        params["id"] = new_id()
        row = conn.execute(
            """
            INSERT INTO entries (id, kind, engine, model, session_id, cwd, project, script, priority, mode,
                                 title, summary, detail, html, control, source, expires_at, state, topic_path)
            VALUES (%(id)s, %(kind)s, %(engine)s, %(model)s, %(session_id)s, %(cwd)s, %(project)s, %(script)s,
                    %(priority)s, %(mode)s, %(title)s, %(summary)s, %(detail)s, %(html)s, %(control)s,
                    %(source)s, %(expires_at)s, %(state)s, %(topic_path)s)
            ON CONFLICT (id) DO NOTHING
            RETURNING id
            """,
            params,
        ).fetchone()
        if row:
            entry = get_entry(conn, row["id"])
            # The connection autocommits, so the insert is committed before the note names it.
            topics.note(
                "asked" if kind == "ask" else "posted", entry["id"], path,
                engine=engine, session_id=session_id, title=entry["title"],
            )
            return entry
    raise StoreError("could not allocate an entry id")
```

- [ ] **Step 6: Run the tests, then the whole suite**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/inbox && .venv/bin/python -m pytest tests/test_db.py tests/test_validate.py tests/test_store_topics.py -q && .venv/bin/python -m pytest -q | tail -1`
Expected: all pass; full suite `167 passed`.

- [ ] **Step 7: Commit**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/inbox
git add src/agent_inbox/db.py src/agent_inbox/schema.sql src/agent_inbox/validate.py src/agent_inbox/store.py \
  tests/test_db.py tests/test_validate.py tests/test_store_topics.py
git commit -m "feat(inbox): entries store the asking session's topic path and note asked or posted"
```

---

### Task 6: Answered and closed notes

**Files:**
- Modify: `modules/inbox/src/agent_inbox/store.py`, `modules/inbox/src/agent_inbox/serve.py`
- Test: `modules/inbox/tests/test_store_topics.py`

- [ ] **Step 1: Write the failing tests**

In `modules/inbox/tests/test_store_topics.py`, change `from agent_inbox import store, topics` to `from agent_inbox import serve, store, topics`, then append:

```python
def test_an_answer_notes_after_it_commits(conn, inbox_db, fake_registry):
    fake_registry.replies["topic-path"] = PATH
    q = ask(conn)
    seen = []
    fake_registry.replies["topic-note"] = lambda *args: seen.append(committed(inbox_db, q["id"]))
    store.answer(conn, q["id"], "b", via="web")
    assert fake_registry.notes()[-1] == [
        "answered", "--topic=tp-plan", f"--entry={q['id']}", "--value=b", "--via=web", "--type=claude", "--session-id=s-1",
    ]
    assert seen == ["answered"]


def test_a_multi_answer_notes_its_values_joined(conn, fake_registry):
    fake_registry.replies["topic-path"] = PATH
    multi = {"type": "multi", "options": [{"id": "x", "label": "X"}, {"id": "y", "label": "Y"}]}
    q = ask(conn, control=multi)
    store.answer(conn, q["id"], ["x", "y"], via="chat")
    assert "--value=x, y" in fake_registry.notes()[-1]


@pytest.mark.parametrize("close, state", [
    (lambda conn, q, newer: store.withdraw(conn, q), "withdrawn"),
    (lambda conn, q, newer: store.supersede(conn, q, by=newer), "superseded"),
])
def test_closing_an_ask_notes_closed(conn, fake_registry, close, state):
    fake_registry.replies["topic-path"] = PATH
    q, newer = ask(conn), ask(conn)
    close(conn, q["id"], newer["id"])
    assert fake_registry.notes()[-1] == [
        "closed", "--topic=tp-plan", f"--entry={q['id']}", f"--state={state}", "--type=claude", "--session-id=s-1",
    ]


def test_expiry_notes_closed(conn, fake_registry):
    fake_registry.replies["topic-path"] = PATH
    q = ask(conn, expires_at="2020-01-01T00:00:00+00:00")
    assert serve.expire_due(conn) == 1
    assert fake_registry.notes()[-1] == [
        "closed", "--topic=tp-plan", f"--entry={q['id']}", "--state=expired", "--type=claude", "--session-id=s-1",
    ]


def test_no_path_means_no_notes(conn, fake_registry):
    store.answer(conn, ask(conn)["id"], "a", via="chat")
    store.withdraw(conn, ask(conn)["id"])
    assert fake_registry.notes() == []
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/inbox && .venv/bin/python -m pytest tests/test_store_topics.py -q`
Expected: the four new note tests fail (the last note is still `asked`); `test_no_path_means_no_notes` passes already.

- [ ] **Step 3: Implement in `store.py`**

In `answer`, right after the `with conn.transaction():` block ends (before `if via != "telegram":`), add:

```python
    topics.note(
        "answered", entry_id, row["topic_path"], engine=row["engine"], session_id=row["session_id"],
        value=clean, via=via,
    )
```

Add after `_set_state`:

```python
def note_closed(row: dict, state: str) -> None:
    """An ask left open without an answer; tell its topic, so it stops counting as waiting."""
    topics.note(
        "closed", row["id"], row.get("topic_path"), engine=row.get("engine"), session_id=row.get("session_id"),
        state=state,
    )
```

Replace `withdraw` and `supersede` with:

```python
def withdraw(conn: psycopg.Connection, entry_id: str) -> dict:
    with conn.transaction():
        row = _row(conn, entry_id, lock=True)
        if row["kind"] != "ask":
            raise ValidationError(f"{entry_id} is not a question")
        if row["state"] != "open":
            raise ConflictError(_closed_message(row))
        _set_state(conn, row, "withdrawn")
    note_closed(row, "withdrawn")
    return {"entry": entry_id, "state": "withdrawn"}


def supersede(conn: psycopg.Connection, entry_id: str, *, by: str) -> dict:
    if by == entry_id:
        raise ValidationError("an entry cannot supersede itself")
    with conn.transaction():
        newer = _row(conn, by)
        if newer["kind"] != "ask":
            raise ValidationError(f"{by} is not a question")
        row = _row(conn, entry_id, lock=True)
        if row["kind"] != "ask":
            raise ValidationError(f"{entry_id} is not a question")
        if row["state"] != "open":
            raise ConflictError(_closed_message(row))
        _set_state(conn, row, "superseded", superseded_by=by)
    note_closed(row, "superseded")
    return {"entry": entry_id, "state": "superseded", "superseded_by": by}
```

- [ ] **Step 4: Implement in `serve.py`**

Replace `expire_due` with:

```python
def expire_due(conn: psycopg.Connection) -> int:
    rows = conn.execute(
        """
        UPDATE entries SET state = 'expired', updated_at = now()
        WHERE kind = 'ask' AND state = 'open' AND expires_at IS NOT NULL AND expires_at <= now()
        RETURNING id, topic_path, engine, session_id
        """
    ).fetchall()
    for row in rows:
        conn.execute(
            "INSERT INTO events (entry_id, type, body) VALUES (%s, 'state', %s)",
            (row["id"], Jsonb({"from": "open", "to": "expired"})),
        )
    for row in rows:
        store.note_closed(row, "expired")
    return len(rows)
```

- [ ] **Step 5: Run the tests, then the whole suite**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/inbox && .venv/bin/python -m pytest tests/test_store_topics.py -q && .venv/bin/python -m pytest -q | tail -1`
Expected: `11 passed`, then `173 passed`.

- [ ] **Step 6: Commit**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/inbox
git add src/agent_inbox/store.py src/agent_inbox/serve.py tests/test_store_topics.py
git commit -m "feat(inbox): answers, withdrawals, supersedes and expiries note the topic log"
```

---

### Task 7: Grouping logic

**Files:**
- Create: `modules/inbox/src/agent_inbox/grouping.py`
- Test: `modules/inbox/tests/test_grouping.py`

- [ ] **Step 1: Write the failing tests**

Create `modules/inbox/tests/test_grouping.py`:

```python
from agent_inbox import grouping

ROOT = {"id": "tp-root", "title": "Topic awareness", "kind": "intent"}
PLAN = {"id": "tp-plan", "title": "Write the plan", "kind": "topic"}
FORK = {"id": "tp-fork", "title": "Manual check: Cursor fork", "kind": "intent"}
CHECK = {"id": "tp-chk", "title": "Check window targeting", "kind": "topic"}
OTHER = {"id": "tp-othr", "title": "Inbox restyle", "kind": "intent"}


def row(rid, path, kind="post", state="unread"):
    return {"id": rid, "kind": kind, "state": state, "topic_path": path}


def ids(group):
    return [r["id"] for r in group.rows]


def test_the_context_line_shows_the_last_two_names():
    assert grouping.context([]) is None
    assert grouping.context([ROOT]) == ("Topic awareness", "Topic awareness")
    assert grouping.context([ROOT, PLAN]) == ("Topic awareness › Write the plan", "Topic awareness › Write the plan")
    shown, full = grouping.context([ROOT, PLAN, FORK, CHECK])
    assert shown == "… › Manual check: Cursor fork › Check window targeting"
    assert full == "Topic awareness › Write the plan › Manual check: Cursor fork › Check window targeting"


def test_a_node_without_a_title_shows_its_id():
    assert grouping.context([{"id": "tp-x", "title": None, "kind": "intent"}]) == ("tp-x", "tp-x")


def test_the_intent_is_the_last_intent_in_the_path():
    assert grouping.intent_of([ROOT, PLAN]) == ROOT
    assert grouping.intent_of([ROOT, PLAN, FORK, CHECK]) == FORK
    assert grouping.intent_of([PLAN]) == PLAN
    assert grouping.intent_of([]) is None


def test_group_by_intent_leads_with_open_questions_and_ends_with_no_topic():
    rows = [
        row("ib-1", None, kind="ask", state="open"),
        row("ib-2", [ROOT, PLAN]),
        row("ib-3", [OTHER], kind="ask", state="open"),
        row("ib-4", [ROOT, PLAN, FORK, CHECK]),
        row("ib-5", [ROOT]),
    ]
    groups = grouping.group_rows(rows, "intent")
    assert [(g.title, ids(g)) for g in groups] == [
        ("Inbox restyle", ["ib-3"]),
        ("Topic awareness", ["ib-2", "ib-5"]),
        ("Manual check: Cursor fork", ["ib-4"]),
        ("No topic", ["ib-1"]),
    ]
    assert groups[1].lead["id"] == "ib-2"


def test_group_by_tree_nests_forked_intents_under_their_root():
    rows = [
        row("ib-3", [OTHER]),
        row("ib-2", [ROOT, PLAN]),
        row("ib-1", [ROOT, PLAN, FORK, CHECK], kind="ask", state="open"),
        row("ib-4", [ROOT, PLAN, FORK]),
        row("ib-5", []),
    ]
    groups = grouping.group_rows(rows, "tree")
    assert [(g.title, ids(g)) for g in groups] == [
        ("Topic awareness", ["ib-2"]), ("Inbox restyle", ["ib-3"]), ("No topic", ["ib-5"]),
    ]
    assert [(s.title, ids(s)) for s in groups[0].subs] == [("Manual check: Cursor fork", ["ib-1", "ib-4"])]
    assert groups[0].has_question() and not groups[1].has_question()


def test_the_intent_filter_lists_intents_in_feed_order_and_narrows():
    rows = [row("ib-1", [ROOT, PLAN]), row("ib-2", [OTHER]), row("ib-3", [ROOT]), row("ib-4", None)]
    assert grouping.intents_in(rows) == [("tp-root", "Topic awareness"), ("tp-othr", "Inbox restyle")]
    assert [r["id"] for r in grouping.only_intent(rows, "tp-root")] == ["ib-1", "ib-3"]
    assert grouping.only_intent(rows, None) == rows


def test_a_malformed_path_counts_as_no_topic():
    rows = [row("ib-1", "tp-root"), row("ib-2", [{"title": "no id"}])]
    assert [g.title for g in grouping.group_rows(rows, "intent")] == ["No topic"]
    assert grouping.context(grouping.path_of(rows[1])) is None
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/inbox && .venv/bin/python -m pytest tests/test_grouping.py -q`
Expected: collection error, `ImportError: cannot import name 'grouping'`.

- [ ] **Step 3: Implement**

Create `modules/inbox/src/agent_inbox/grouping.py`:

```python
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
```

- [ ] **Step 4: Run them to see them pass**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/inbox && .venv/bin/python -m pytest tests/test_grouping.py -q`
Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/inbox
git add src/agent_inbox/grouping.py tests/test_grouping.py
git commit -m "feat(inbox): context line, intent filter and Group by sections from topic paths"
```

---

### Task 8: The feed

**Files:**
- Modify: `modules/inbox/src/agent_inbox/web.py`
- Test: `modules/inbox/tests/test_web.py`

- [ ] **Step 1: Write the failing tests**

Append to `modules/inbox/tests/test_web.py`:

```python
ROOT = {"id": "tp-root", "title": "Topic awareness", "kind": "intent"}
PLAN = {"id": "tp-plan", "title": "Write the plan", "kind": "topic"}
FORK = {"id": "tp-fork", "title": "Manual check", "kind": "intent"}
OTHER = {"id": "tp-othr", "title": "Inbox restyle", "kind": "intent"}


def _get_resp(http, path, headers=None):
    conn = HTTPConnection(http[0], http[1], timeout=5)
    conn.request("GET", path, headers=headers or {})
    resp = conn.getresponse()
    return resp.status, resp.getheader("Set-Cookie"), resp.read().decode()


def _with_path(conn, fake_registry, path, title="Q", kind="ask"):
    """An entry from session s-1 in project agent-tools whose registry path is `path`."""
    fake_registry.replies["topic-path"] = path
    if kind == "ask":
        req = validate_request({"title": title, "control": CHOICE}, "ask")
    else:
        req = validate_request({"title": title}, "post")
    return store.create_entry(conn, kind, req, engine="claude", session_id="s-1", cwd="/x/agent-tools")


def test_rows_show_the_last_two_path_names_above_the_title(conn, http, fake_registry):
    deep = _with_path(conn, fake_registry, [ROOT, PLAN, FORK], title="Deep")
    flat = _with_path(conn, fake_registry, None, title="Flat")
    _, body = _get(http, "/")
    assert (
        '<span class="ctx" title="Topic awareness › Write the plan › Manual check">'
        "… › Write the plan › Manual check</span><b>Deep</b>"
    ) in body
    assert f'<a class="row has-ctx" href="/e/{deep["id"]}"' in body
    assert f'<a class="row" href="/e/{flat["id"]}"' in body


def test_the_context_line_is_escaped(conn, http, fake_registry):
    _with_path(conn, fake_registry, [{"id": "tp-x", "title": '<img src=x onerror="alert(1)">', "kind": "intent"}])
    _, body = _get(http, "/")
    assert "<img src=x" not in body
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in body


def test_group_by_is_remembered_in_a_cookie(conn, http, fake_registry):
    _with_path(conn, fake_registry, [ROOT, PLAN], title="On plan")
    status, cookie, body = _get_resp(http, "/?group=intent")
    assert status == 200 and cookie.startswith("ib_group=intent;") and "SameSite=Lax" in cookie
    assert '<section class="grp"><h2 title="Topic awareness · agent-tools">Topic awareness · agent-tools</h2>' in body
    assert '<option value="intent" selected>Intent</option>' in body
    _, cookie, remembered = _get_resp(http, "/", headers={"Cookie": "ib_group=intent"})
    assert cookie is None and 'class="grp"' in remembered
    # Group by is a view, not a filter: it doesn't light the filter badge.
    assert 'aria-label="Filters"' in remembered
    _, cookie, plain = _get_resp(http, "/?group=none", headers={"Cookie": "ib_group=intent"})
    assert cookie.startswith("ib_group=none;") and 'class="grp"' not in plain
    # A bad value, in the URL or the cookie, is today's feed.
    _, cookie, odd = _get_resp(http, "/?group=sideways", headers={"Cookie": "ib_group=sideways"})
    assert cookie is None and 'class="grp"' not in odd and '<option value="none" selected>None</option>' in odd


def test_group_by_tree_nests_forks_and_ends_with_no_topic(conn, http, fake_registry):
    fork_q = _with_path(conn, fake_registry, [ROOT, PLAN, FORK], title="Fork question")
    root_r = _with_path(conn, fake_registry, [ROOT, PLAN], title="Root report", kind="post")
    loose = _with_path(conn, fake_registry, None, title="Loose report", kind="post")
    _, _, body = _get_resp(http, "/?group=tree")
    root_at = body.index('<h2 title="Topic awareness · agent-tools">')
    sub_at = body.index('<section class="grp sub"><h3 title="Manual check">Manual check</h3>')
    none_at = body.index('<h2 title="No topic">No topic</h2>')
    assert root_at < body.index(root_r["id"]) < sub_at < body.index(fork_q["id"]) < none_at < body.index(loose["id"])


def test_the_intent_filter_lists_intents_in_view_and_narrows(conn, http, fake_registry):
    _, empty = _get(http, "/")
    assert 'name="intent"' not in empty
    mine = _with_path(conn, fake_registry, [ROOT, PLAN], title="Mine")
    theirs = _with_path(conn, fake_registry, [OTHER], title="Theirs", kind="post")
    _, body = _get(http, "/")
    assert (
        '<select name="intent"><option value="">Any intent</option>'
        '<option value="tp-root">Topic awareness</option><option value="tp-othr">Inbox restyle</option></select>'
    ) in body
    _, body = _get(http, "/?intent=tp-othr")
    assert theirs["id"] in body and mine["id"] not in body and "Filters, 1 on" in body
    assert '<option value="tp-othr" selected>Inbox restyle</option>' in body
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/inbox && .venv/bin/python -m pytest tests/test_web.py -q`
Expected: the five new tests fail (no `ctx` span, no `Set-Cookie`, no `grp` sections, no intent select).

- [ ] **Step 3: Imports and constants**

In `web.py`, add `from http.cookies import CookieError, SimpleCookie` above `from http.server import …`, and change `from agent_inbox import db, store` to:

```python
from agent_inbox import db, grouping, store
```

Below `FRAME_ORIGIN = f"http://127.0.0.1:{FRAME_PORT}"` add:

```python
GROUP_LABELS = (("none", "None"), ("intent", "Intent"), ("tree", "Topic tree"))
GROUP_COOKIE = "ib_group"
GROUP_MAX_AGE = 365 * 24 * 3600
```

- [ ] **Step 4: CSS**

All of these go inside the `_HEAD` string, so braces are doubled.

After the line `.row .chips {{ grid-area: chips; display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }}` add:

```css
.row .ctx {{ grid-area: ctx; min-width: 0; color: var(--mute); font-size: 12px; line-height: 1.3;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.row.has-ctx {{ grid-template-areas: "av ctx ctx" "av title time" "av meta meta" "av chips chips"; }}
```

After the line `.day:first-child h2 {{ padding-top: 4px; }}` add:

```css
.grp h2 {{ position: sticky; top: 56px; z-index: 1; margin: 0 -16px; padding: 16px 16px 8px; background: var(--bg);
  color: var(--mute); font-size: 13px; font-weight: 650; line-height: 1.2; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.grp:first-child h2 {{ padding-top: 4px; }}
.grp h3 {{ margin: 0 -16px; padding: 12px 16px 6px 32px; color: var(--mute); font-size: 13px; font-weight: 600; line-height: 1.2;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
```

Inside `@media (min-width: 760px) {{ … }}`, after `.row {{ grid-template-areas: "av title time" "av meta chips"; }}` add:

```css
  .row.has-ctx {{ grid-template-areas: "av ctx ctx" "av title time" "av meta chips"; }}
```

and after `.day h2 {{ margin: 0; padding-inline: 0; }}` add:

```css
  .grp h2 {{ margin: 0; padding-inline: 0; }}
  .grp h3 {{ margin: 0; padding-inline: 16px 0; }}
```

Inside `@media (min-width: 1100px) {{ … }}`, after the `.pane .row {{ grid-template-areas: …; padding-left: 16px; }}` line add:

```css
  .pane .row.has-ctx {{ grid-template-areas: "av ctx ctx" "av title time" "av meta meta" "av chips chips"; }}
```

(Each `.has-ctx` rule must follow the `.row` rule it overrides at the same width; the pane one needs the extra class to beat `.pane .row`.)

- [ ] **Step 5: The context line in `_card`**

Replace `_card` with:

```python
def _card(row: dict, *, pick: bool = True, current: bool = False, by_day: bool = False) -> str:
    engine = (row.get("asker") or {}).get("engine") or ""
    answer = row.get("answer") or {}
    said = f"You: {_shown(row, answer.get('value'))}" if row["kind"] == "ask" and answer else ""
    meta = " · ".join(_esc(bit) for bit in (_who(row), engine, said) if bit)
    unread = " unread" if row["kind"] == "post" and row["state"] == "unread" else ""
    # The discussion the row belongs to, above its title: the last two names of its topic path.
    ctx = grouping.context(grouping.path_of(row))
    line = f'<span class="ctx" title="{_esc(ctx[1])}">{_esc(ctx[0])}</span>' if ctx else ""
    has = " has-ctx" if ctx else ""
    box = (
        f'<label class="pick"><input type="checkbox" name="id" value="{_esc(row["id"])}" aria-label="Select {_esc(row["id"])}"></label>'
        if pick else ""
    )
    here = ' aria-current="page"' if current else ""
    return (
        f'<li class="item">{box}'
        f'<a class="row{unread}{has}" href="/e/{_esc(row["id"])}"{here}>{_avatar(row, kind=True)}{line}<b>{_esc(row["title"])}</b>'
        f'<time>{_esc(_hour(row.get("created_at")) if by_day else _clock(row.get("created_at")))}</time>'
        f'<small>{meta}<span class="rid"> · <span class="id">{_esc(row["id"])}</span></span></small>'
        f'<span class="chips">{_urgent(row)}{_chip(row)}</span></a>'
        "</li>"
    )
```

- [ ] **Step 6: Grouped rendering**

Add after `_by_day`:

```python
def _grouped(groups: list[grouping.Group]) -> str:
    """Group by: one section per intent or root with a one-line heading; tree nests forked intents one level."""
    def rows(items: list[dict]) -> str:
        return ('<ul class="list">' + "".join(_card(row) for row in items) + "</ul>") if items else ""

    def heading(group: grouping.Group, tag: str) -> str:
        project = _who(group.lead) if group.key and tag == "h2" else ""
        text = " · ".join(bit for bit in (group.title, project) if bit)
        return f'<{tag} title="{_esc(text)}">{_esc(text)}</{tag}>'

    return "".join(
        f'<section class="grp">{heading(group, "h2")}{rows(group.rows)}'
        + "".join(f'<section class="grp sub">{heading(sub, "h3")}{rows(sub.rows)}</section>' for sub in group.subs)
        + "</section>"
        for group in groups
    )
```

- [ ] **Step 7: The filter panel**

Add after `_tab`:

```python
def _group_select(group: str) -> str:
    opts = "".join(
        f'<option value="{value}"{" selected" if value == group else ""}>{label}</option>' for value, label in GROUP_LABELS
    )
    return f'<label>Group by<select name="group">{opts}</select></label>'
```

Replace `_nav` with:

```python
def _nav(
    qs: dict, projects: list[str] = (), intents: list[tuple[str, str]] = (), group: str = "none",
) -> tuple[str, str]:
    """The view tabs, and the filter button and panel that sit in the header bar."""
    current = {key: _query_value(qs, key) for key in ("kind", "state", "history") if _query_value(qs, key)}
    home, want = _tab(current)
    mark = ' aria-current="page"'
    tabs = "".join(f'<a href="{href}"{mark if href == home else ""}>{label}</a>' for label, href, _ in TABS)
    # The filter panel narrows the current tab: it keeps the tab's history, and counts
    # only what differs from the tab. Group by is a view, so it is never counted.
    hidden = '<input type="hidden" name="history" value="1">' if current.get("history") else ""
    on = sum(1 for key in ("kind", "project", "engine", "state", "intent") if _query_value(qs, key) != want.get(key))
    project = _query_value(qs, "project")
    if project and project not in projects:
        projects = [project, *projects]
    intent = _query_value(qs, "intent")
    if intent and intent not in {value for value, _ in intents}:
        intents = [(intent, intent), *intents]

    def options(label: str, key: str, names) -> str:
        """names are values, or (value, label) pairs."""
        chosen = _query_value(qs, key)
        pairs = [name if isinstance(name, tuple) else (name, name) for name in names]
        opts = "".join(
            f'<option value="{_esc(value)}"{" selected" if value == chosen else ""}>{_esc(text)}</option>' for value, text in pairs
        )
        return f'<label>{label}<select name="{key}"><option value="">Any {label.lower()}</option>{opts}</select></label>'

    badge = f"<b>{on}</b>" if on else ""
    said = f", {on} on" if on else ""
    clear = f'<a class="btn" href="{home}">Clear</a>' if on else ""
    filters = (
        f'<details class="filt{" on" if on else ""}"><summary aria-label="Filters{said}" title="Filters">{_FUNNEL}{badge}</summary>'
        '<form method="get" action="/">'
        + hidden
        + options("Type", "kind", (("ask", "Question"), ("post", "Report")))
        + options("Project", "project", [(path, Path(path).name) for path in projects])
        + options("Engine", "engine", ("claude", "codex", "cursor"))
        + options("State", "state", ("open", "unread", "answered", "delivered", "undelivered", "expired", "read"))
        + (options("Intent", "intent", intents) if intents else "")
        + _group_select(group)
        + f'<div class="pair">{clear}<button class="btn go" type="submit">Apply</button></div>'
        "</form></details>"
    )
    return f'<nav class="tabs" aria-label="Views">{tabs}</nav>', filters
```

- [ ] **Step 8: The feed page and the Group by choice**

Replace `_feed_page` with:

```python
def _feed_page(
    rows: list[dict], qs: dict, error: str | None = None, banner: str = "", waiting: int | None = None,
    projects: list[str] = (), intents: list[tuple[str, str]] = (), group: str = "none",
) -> str:
    err = f'<p class="notice err" role="alert">{_esc(error)}</p>' if error else ""
    line = f'<p class="notice warn">{_esc(banner)}</p>' if banner else ""
    if rows:
        if group in ("intent", "tree"):
            listing = _grouped(grouping.group_rows(rows, group))
        elif _query_value(qs, "history") == "1":
            listing = _by_day(rows)
        else:
            listing = '<ul class="list">' + "".join(_card(row) for row in rows) + "</ul>"
        body = (
            '<form method="post" action="/batch">'
            + listing
            + '<div class="actions">'
            '<button class="btn danger" type="submit" name="action" value="withdraw">Withdraw</button>'
            '<button class="btn" type="submit" name="action" value="dismiss">Dismiss</button>'
            "</div></form>"
        )
    else:
        if any(key != "group" for key in qs):
            body = '<p class="empty"><b>Nothing here</b>Nothing matches this view.</p>'
        else:
            body = (
                '<p class="empty"><b>All caught up</b>New questions and reports land here. '
                'Answered questions and read reports are in <a href="/?history=1">History</a>.</p>'
            )
    count = _waiting(rows) if waiting is None else waiting
    tabs, filters = _nav(qs, projects, intents, group)
    return (
        _HEAD.format(title="Inbox", body="")
        + _bar("<h1>Inbox</h1>", count, filters)
        + "<main>"
        + tabs
        + line
        + err
        + body
        + "</main>"
        + _SCRIPT
    )
```

Add after `_dismissed`:

```python
def _group_choice(qs: dict, cookie_header: str | None) -> tuple[str, str | None]:
    """The Group by mode and, when this request picked one, the Set-Cookie that remembers it.

    A cookie rather than the URL, so the choice survives the live reload, the tab links and the phone."""
    asked = _query_value(qs, "group")
    if asked in grouping.GROUPS:
        return asked, f"{GROUP_COOKIE}={asked}; Path=/; Max-Age={GROUP_MAX_AGE}; SameSite=Lax"
    jar = SimpleCookie()
    try:
        jar.load(cookie_header or "")
    except CookieError:
        return "none", None
    saved = jar.get(GROUP_COOKIE)
    return (saved.value if saved and saved.value in grouping.GROUPS else "none"), None
```

- [ ] **Step 9: The handler**

In `_dispatch`, replace the `GET /` branch with:

```python
        if method == "GET" and path == "/":
            group, cookie = _group_choice(qs, self.headers.get("Cookie"))
            with db.connect() as conn:
                from agent_inbox.notify import urgent_counts
                rows = load_feed(conn, qs)
                # The intent filter offers the intents in the view before it narrows it.
                intents = grouping.intents_in(rows)
                self._html(200, _feed_page(
                    grouping.only_intent(rows, _query_value(qs, "intent")), qs, banner=urgent_counts(conn),
                    waiting=open_count(conn), projects=store.list_projects(conn), intents=intents, group=group,
                ), cookie=cookie)
            return
```

In `_batch`, replace the `self._html(409, _feed_page(…))` call with:

```python
                group, _ = _group_choice({}, self.headers.get("Cookie"))
                self._html(409, _feed_page(
                    load_feed(conn, {}), {}, message, banner=urgent_counts(conn), waiting=open_count(conn),
                    projects=store.list_projects(conn), group=group,
                ))
```

Replace `_bytes` and `_html` with:

```python
    def _bytes(self, status: int, payload: bytes, content_type: str, cookie: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(payload)

    def _html(self, status: int, page: str, cookie: str | None = None) -> None:
        self._bytes(status, page.encode(), "text/html; charset=utf-8", cookie)
```

- [ ] **Step 10: Run the web tests, then the whole suite**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/inbox && .venv/bin/python -m pytest tests/test_web.py -q && .venv/bin/python -m pytest -q | tail -1`
Expected: `33 passed`, then `185 passed`. The older web tests must pass unchanged; a failure there means the default feed changed, which the spec forbids.

- [ ] **Step 11: Commit**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/inbox
git add src/agent_inbox/web.py tests/test_web.py
git commit -m "feat(inbox): the feed shows each row's discussion and groups by intent or topic tree"
```

---

### Task 9: The entry page

**Files:**
- Modify: `modules/inbox/src/agent_inbox/store.py`, `modules/inbox/src/agent_inbox/web.py`
- Test: `modules/inbox/tests/test_web.py`

- [ ] **Step 1: Write the failing tests**

Append to `modules/inbox/tests/test_web.py`:

```python
def test_entry_page_shows_the_full_path_as_a_breadcrumb(conn, http, fake_registry):
    e = _with_path(conn, fake_registry, [ROOT, PLAN, FORK], title="Deep")
    _, body = _get(http, f"/e/{e['id']}")
    crumbs = (
        '<nav class="crumbs" aria-label="Topic"><ol><li>Topic awareness</li><li>Write the plan</li>'
        "<li>Manual check</li></ol></nav>"
    )
    assert crumbs in body and body.index(crumbs) < body.index('<h1 class="title">')
    loose = _with_path(conn, fake_registry, None, title="Loose")
    _, body = _get(http, f"/e/{loose['id']}")
    assert 'class="crumbs"' not in body and 'class="ontopic"' not in body


def test_on_this_topic_lists_the_other_entries_newest_first(conn, http, fake_registry):
    older = _with_path(conn, fake_registry, [ROOT, PLAN], title="Older", kind="post")
    newer = _with_path(conn, fake_registry, [ROOT, PLAN], title="Newer")
    elsewhere = _with_path(conn, fake_registry, [ROOT], title="Elsewhere", kind="post")
    conn.execute("UPDATE entries SET created_at = now() - interval '2 hours' WHERE id = %s", (older["id"],))
    here = _with_path(conn, fake_registry, [ROOT, PLAN], title="Here")
    _, body = _get(http, f"/e/{here['id']}")
    section = body[body.index('<section class="ontopic"'):]
    assert section.index(f'href="/e/{newer["id"]}"') < section.index(f'href="/e/{older["id"]}"')
    assert elsewhere["id"] not in section and f'href="/e/{here["id"]}"' not in section
    assert "2 h ago" in section and "Needs answer" in section


def test_on_this_topic_stops_at_ten(conn, fake_registry):
    entries = [_with_path(conn, fake_registry, [ROOT, PLAN], title=f"E{i}", kind="post") for i in range(12)]
    assert len(store.same_topic(conn, entries[0])) == 10
    assert store.same_topic(conn, {"id": "ib-none", "topic_path": None}) == []
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/inbox && .venv/bin/python -m pytest tests/test_web.py -q -k "breadcrumb or on_this_topic"`
Expected: 3 failed (no crumbs, no `ontopic` section, `AttributeError: module 'agent_inbox.store' has no attribute 'same_topic'`).

- [ ] **Step 3: The store query**

In `store.py`, add after `list_projects`:

```python
def same_topic(conn: psycopg.Connection, entry: dict, limit: int = 10) -> list[dict]:
    """Other entries whose path ends in the same topic as this one, newest first."""
    path = entry.get("topic_path") or []
    if not path:
        return []
    rows = conn.execute(
        """
        SELECT * FROM entries WHERE topic_path->-1->>'id' = %s AND id <> %s
        ORDER BY created_at DESC, id DESC LIMIT %s
        """,
        (path[-1]["id"], entry["id"], limit),
    ).fetchall()
    return [{k: v for k, v in _shape(r).items() if k not in LIST_HIDDEN} for r in rows]
```

- [ ] **Step 4: CSS**

Inside `_HEAD`, after the line `.follow .btn {{ flex: none; min-height: 48px; }}` add:

```css
.crumbs ol {{ display: flex; flex-wrap: wrap; gap: 2px 6px; margin: 0 0 6px; padding: 0; list-style: none;
  color: var(--mute); font-size: 14px; line-height: 1.4; }}
.crumbs li + li::before {{ content: "›"; margin-right: 6px; }}
.ontopic {{ margin: 24px 0 0; padding-top: 16px; border-top: 1px solid var(--line); }}
.ontopic h2 {{ margin: 0 0 4px; font-size: 16px; }}
.ontopic ul {{ list-style: none; margin: 0; padding: 0; }}
.ontopic a {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 48px; padding: 8px 0;
  border-bottom: 1px solid var(--line); color: inherit; text-decoration: none; }}
.ontopic li:last-child a {{ border-bottom: 0; }}
.ontopic a:hover b {{ text-decoration: underline; }}
.ontopic b {{ min-width: 0; font-weight: 550; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.ontopic .end {{ flex: none; display: flex; align-items: center; gap: 8px; }}
.ontopic time {{ color: var(--mute); font-size: 13px; font-variant-numeric: tabular-nums; }}
```

- [ ] **Step 5: Render the breadcrumb and the list**

Add after `_thread`:

```python
def _crumbs(entry: dict) -> str:
    """The entry's topic path, root first, above the title."""
    path = grouping.path_of(entry)
    if not path:
        return ""
    items = "".join(f"<li>{_esc(grouping.name(node))}</li>" for node in path)
    return f'<nav class="crumbs" aria-label="Topic"><ol>{items}</ol></nav>'


def _on_topic(related: list[dict]) -> str:
    """The other entries on the same topic: title, state and age, each linking to its page."""
    if not related:
        return ""
    items = "".join(
        f'<li><a href="/e/{_esc(row["id"])}"><b>{_esc(row["title"])}</b>'
        f'<span class="end">{_chip(row)}<time>{_esc(_ago(row.get("created_at")))}</time></span></a></li>'
        for row in related
    )
    return f'<section class="ontopic" aria-label="On this topic"><h2>On this topic</h2><ul>{items}</ul></section>'
```

In `_entry_page`, add a parameter: change the signature's last line to

```python
    sidebar: list[dict] | None = None, next_id: str | None = None, related: list[dict] | None = None,
```

Change the header `parts.append(` that starts with `f'<h1 class="title">…` so the breadcrumb comes first:

```python
    parts.append(
        _crumbs(entry)
        + f'<h1 class="title">{_esc(entry["title"])}</h1>'
        f'<p class="meta who">{_avatar(entry, small=True)}<span>{meta}</span></p>'
        f'<p class="meta sub">{_urgent(entry)}{_chip(entry)}<span>{_esc(kind)} · <span class="id">{eid}</span></span></p>'
    )
```

and replace the closing line `parts.append("</main>" + ("</div>" if sidebar is not None else "") + _SCRIPT)` with:

```python
    # After the follow-up form, so the thread and its reply box stay together.
    parts.append(_on_topic(related or []))
    parts.append("</main>" + ("</div>" if sidebar is not None else "") + _SCRIPT)
```

In `InboxHandler._show`, pass the list:

```python
            self._html(status, _entry_page(
                entry, error, _frame_origin(self.headers.get("Host")), open_count(conn), sidebar=listed,
                next_id=next_entry(listed, entry_id, after), related=store.same_topic(conn, entry),
            ))
```

- [ ] **Step 6: Run the tests, then the whole suite**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/inbox && .venv/bin/python -m pytest tests/test_web.py -q && .venv/bin/python -m pytest -q | tail -1`
Expected: `36 passed`, then `188 passed`.

- [ ] **Step 7: Commit**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/inbox
git add src/agent_inbox/store.py src/agent_inbox/web.py tests/test_web.py
git commit -m "feat(inbox): the entry page shows its topic path and the other entries on that topic"
```

---

### Task 10: Black-box suite and latency

**Files:**
- Modify: `modules/inbox/tests/conftest.py`
- Create: `modules/inbox/tests/blackbox/conftest.py`, `modules/inbox/tests/blackbox/test_topic_inbox.py`

- [ ] **Step 1: Collect `tests/blackbox` only when asked**

Append to `modules/inbox/tests/conftest.py` (the registry module does the same):

```python
def pytest_ignore_collect(collection_path, config):
    """Collect tests/blackbox only when that path was requested."""
    parts = getattr(collection_path, "parts", ())
    if "blackbox" not in parts:
        return False
    return not any("blackbox" in str(arg) for arg in config.args)
```

- [ ] **Step 2: Write the harness**

Create `modules/inbox/tests/blackbox/conftest.py`:

```python
"""Black-box harness: agt, a temp registry and the agent_inbox_test database.

Never imports agent_inbox or agent_registry. The parent conftest's autouse fixtures patch the
package in this process only; every command here runs in a subprocess."""
import json
import os
import signal
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest

INBOX = Path(__file__).resolve().parents[2]
REPO = INBOX.parents[1]
AGT = REPO / "agt" / "agt"
REGISTRY_BIN = REPO / "modules" / "registry" / "bin" / "agent-registry"
SESSION_VARS = ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CURSOR_CONVERSATION_ID", "HERDR_ENV")
NOTE_KINDS = ("asked", "posted", "answered", "closed")
TEST_DSN = os.environ.get("AGENT_INBOX_TEST_DSN", "host=localhost port=5433 dbname=agent_inbox_test")


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

    def log(self, agent_type, session_id) -> list[dict]:
        path = self.data / "topics" / agent_type / f"{session_id}.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def notes(self, agent_type, session_id) -> list[dict]:
        return [e for e in self.log(agent_type, session_id) if e.get("event") in NOTE_KINDS]


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture
def box(tmp_path):
    with psycopg.connect(TEST_DSN, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS events, entries, ops CASCADE")
    env = {k: v for k, v in os.environ.items() if k not in SESSION_VARS}
    env.update({
        "AGENT_REGISTRY_PATH": str(tmp_path / "registry" / "registry.json"),
        "AGENT_REGISTRY_DAEMON_PORT": str(_free_port()),
        "AGENT_REGISTRY_DAEMON_START_TIMEOUT": "5",
        "AGENT_REGISTRY_SUMMARY_PROVIDER": "off",
        "AGENT_REGISTRY_FORK_BACKEND": "none",
        "AGENT_REGISTRY_BIN": str(REGISTRY_BIN),
        "AGENT_INBOX_DSN": TEST_DSN,
        "AGENT_INBOX_TELEGRAM_TO": "",
        # The inbox must call this checkout's registry, not the one on PATH.
        "AGENT_INBOX_AGT": str(AGT),
    })
    b = Box(root=tmp_path, env=env)
    yield b
    # Nothing here should start a registry daemon, but stop one if a command did.
    pid_file = b.data / "daemon.pid"
    deadline = time.monotonic() + (3 if (b.data / "daemon.log").exists() else 0)
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    if pid_file.exists():
        try:
            os.kill(int(pid_file.read_text().strip()), signal.SIGTERM)
        except (OSError, ValueError):
            pass
```

- [ ] **Step 3: Write the tests**

Create `modules/inbox/tests/blackbox/test_topic_inbox.py`:

```python
import json

WHO = ["--type", "claude", "--session-id", "s1"]
ASKER = ["--engine", "claude", "--session-id", "s1"]
CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}


def ask(box, *args, topic=None, env=None):
    body = {"title": "Which order?", "control": CHOICE}
    if topic:
        body["topic"] = topic
    return box.agt("inbox", "ask", *args, stdin=json.dumps(body), env=env)


def asked(box, *args, **kw):
    proc = ask(box, *args, **kw)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["entry"]


def test_a_session_ask_carries_its_path_and_the_log_records_it(box):
    intent = box.agt_json("registry", "intent", "Ship the inbox", *WHO)
    plan = box.agt_json("registry", "topic", "Write the plan", *WHO)
    entry = asked(box, *ASKER)
    got = box.agt_json("inbox", "get", entry)
    assert got["topic_path"] == [
        {"id": intent["topic"]["id"], "title": "Ship the inbox", "kind": "intent"},
        {"id": plan["topic"]["id"], "title": "Write the plan", "kind": "topic"},
    ]
    assert [(n["event"], n["entry"], n["topic"]["id"], n["title"]) for n in box.notes("claude", "s1")] == [
        ("asked", entry, plan["topic"]["id"], "Which order?"),
    ]


def test_a_chat_answer_is_logged_and_done_finds_nothing_open(box):
    box.agt_json("registry", "intent", "Ship the inbox", *WHO)
    box.agt_json("registry", "topic", "Write the plan", *WHO)
    entry = asked(box, *ASKER)
    box.agt_json("inbox", "answer", entry, "--value", "b", "--via", "chat")
    last = box.notes("claude", "s1")[-1]
    assert (last["event"], last["entry"], last["value"], last["via"]) == ("answered", entry, "b", "chat")
    assert box.agt_json("registry", "topic", "--done", *WHO)["open_questions"] == []


def test_done_reports_a_question_still_waiting_but_not_a_withdrawn_one(box):
    box.agt_json("registry", "intent", "Ship the inbox", *WHO)
    box.agt_json("registry", "topic", "Write the plan", *WHO)
    waiting = asked(box, *ASKER)
    gone = asked(box, *ASKER)
    box.agt_json("inbox", "withdraw", gone)
    last = box.notes("claude", "s1")[-1]
    assert (last["event"], last["entry"], last["state"]) == ("closed", gone, "withdrawn")
    assert box.agt_json("registry", "topic", "--done", *WHO)["open_questions"] == [waiting]


def test_a_script_ask_names_a_forked_topic(box):
    box.agt_json("registry", "intent", "Parent", *WHO)
    fork = box.agt_json("registry", "fork", "Side quest", "--side", "--backend", "none", *WHO, stdin="# Side quest\n")
    box.agt_json("registry", "intent", "--adopt", fork["topic"]["id"], "--type", "claude", "--session-id", "s2")
    entry = asked(box, "--script", "autopilot", topic=fork["topic"]["id"])
    got = box.agt_json("inbox", "get", entry)
    assert [(n["title"], n["kind"]) for n in got["topic_path"]] == [("Parent", "intent"), ("Side quest", "intent")]
    # No session asked, so the note goes to the session that minted the topic: the parent, which forked it.
    assert [n["entry"] for n in box.notes("claude", "s1")] == [entry]
    assert box.notes("claude", "s2") == []


def test_a_script_ask_with_an_unknown_topic_is_refused(box):
    proc = ask(box, "--script", "autopilot", topic="tp-zzzz")
    assert proc.returncode == 1 and "unknown topic tp-zzzz" in proc.stderr
    assert box.agt_json("inbox", "list", "--json") == []


def test_an_ask_succeeds_without_the_registry(box):
    box.agt_json("registry", "intent", "Ship the inbox", *WHO)
    env = dict(box.env, AGENT_INBOX_AGT=str(box.root / "no-such-agt"))
    proc = ask(box, *ASKER, env=env)
    assert proc.returncode == 0, proc.stderr
    assert "continuing without the topic link" in proc.stderr
    assert box.agt_json("inbox", "get", json.loads(proc.stdout)["entry"])["topic_path"] is None


def test_a_post_is_logged_as_posted(box):
    box.agt_json("registry", "intent", "Ship the inbox", *WHO)
    proc = box.agt("inbox", "post", *ASKER, stdin=json.dumps({"title": "Plan written"}))
    assert proc.returncode == 0, proc.stderr
    last = box.notes("claude", "s1")[-1]
    assert (last["event"], last["title"]) == ("posted", "Plan written")
```

- [ ] **Step 4: Run the black-box suite**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/inbox && .venv/bin/python -m pytest tests/blackbox -q`
Expected: `7 passed`. If the first test shows `topic_path: null`, check that `AGENT_INBOX_AGT` reaches the inbox process (the warning line on stderr names the failing registry call).

Run the unit suite too, to confirm `tests/blackbox` stays out of it: `.venv/bin/python -m pytest -q | tail -1`
Expected: `188 passed`.

- [ ] **Step 5: Measure the latency**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/inbox
mkdir -p tmp/latency
export AGENT_REGISTRY_PATH="$PWD/tmp/latency/registry/registry.json"
export AGENT_INBOX_DSN="host=localhost port=5433 dbname=agent_inbox_test" AGENT_INBOX_TELEGRAM_TO=""
../../agt/agt registry intent "Latency check" --type claude --session-id lat >/dev/null || true
for agt in "$PWD/../../agt/agt" /nonexistent; do
  echo "AGENT_INBOX_AGT=$agt"
  for i in 1 2 3 4 5; do
    /usr/bin/time -p env AGENT_INBOX_AGT="$agt" ../../agt/agt inbox post --engine claude --session-id lat \
      <<<'{"title": "latency"}' 2>&1 >/dev/null | grep '^real'
  done
done
```

Expected: five `real` lines per setting. Write down the median of each and their difference: the cost of the two registry calls (path, then note). The plan's estimate is about 0.25 s; if the difference is above 1 s, stop and report it before going on. Put both medians and the difference into the Task 14 report. `tmp/` is ignored by git.

- [ ] **Step 6: Commit**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/inbox
git add tests/conftest.py tests/blackbox/conftest.py tests/blackbox/test_topic_inbox.py
git commit -m "test(inbox): black-box suite for topic paths and topic notes"
```

---

### Task 11: Visual check

**Files:**
- Create: `modules/inbox/tests/visual/seed_topics.py`

- [ ] **Step 1: Write the seed script**

Create `modules/inbox/tests/visual/seed_topics.py`:

```python
"""Seed agent_inbox_test with topic-aware entries for the screenshot check. Not a test.

Run from modules/inbox:
    AGENT_INBOX_DSN="host=localhost port=5433 dbname=agent_inbox_test" AGENT_INBOX_TELEGRAM_TO= \
        PYTHONPATH=src .venv/bin/python tests/visual/seed_topics.py
It drops and recreates the test tables, then prints {title: id} as JSON."""
from __future__ import annotations

import json
import os
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
    if "agent_inbox_test" not in dsn:
        sys.exit("refusing: AGENT_INBOX_DSN must point at agent_inbox_test")
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
```

- [ ] **Step 2: Seed and start a web-only server on the test database**

Only the web handler runs: `agt inbox serve` would also sweep, which wakes sessions. Nothing here touches the live database.

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/inbox
mkdir -p tmp/shots
AGENT_INBOX_DSN="host=localhost port=5433 dbname=agent_inbox_test" AGENT_INBOX_TELEGRAM_TO= \
  PYTHONPATH=src .venv/bin/python tests/visual/seed_topics.py > tmp/seed.json && cat tmp/seed.json
```

Expected: ten titles with `ib-` ids.

Start the server with the Bash tool's `run_in_background`:

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/inbox
AGENT_INBOX_DSN="host=localhost port=5433 dbname=agent_inbox_test" INBOX_HTTP_PORT=8897 INBOX_ALLOW_INSECURE=1 \
  PYTHONPATH=src .venv/bin/python -c 'from agent_inbox.web import make_server; make_server().serve_forever()'
```

Check: `curl --retry 10 --retry-connrefused --retry-delay 1 -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8897/`
Expected: `200`.

- [ ] **Step 3: Take the screenshots**

Each run gets a throwaway profile, so headless Chrome never attaches to Tiago's running browser.

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/inbox
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
# The four-node ask: its breadcrumb is the longest, and "Window targeting notes" shares its topic.
ASK=$(.venv/bin/python -c 'import json; print(json.load(open("tmp/seed.json"))["Is the Cursor tab opening in the right project window?"])')
shot() {
  local size="$1" name="$2" url="$3"; shift 3
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --no-first-run --user-data-dir="$(mktemp -d)" \
    --window-size="$size" --screenshot="tmp/shots/$name.png" "$@" "$url" 2>/dev/null
}
for size in 390,1400 1280,1000; do
  w=${size%,*}
  for g in none intent tree; do shot "$size" "feed-$g-$w" "http://127.0.0.1:8897/?group=$g"; done
  shot "$size" "entry-$w" "http://127.0.0.1:8897/e/$ASK"
done
shot 390,1400 feed-tree-390-dark "http://127.0.0.1:8897/?group=tree" --force-dark-mode
ls tmp/shots
```

Expected: nine PNGs: `feed-{none,intent,tree}-{390,1280}.png`, `entry-{390,1280}.png`, `feed-tree-390-dark.png`.

- [ ] **Step 4: Look at every screenshot**

Open each PNG with the Read tool and check it against this list. Write down what each one shows; don't tick a line you didn't see.

1. `feed-none-390`: rows with a path have a small muted line above the title; the four-node row reads `… › Manual check: … › Check window targeting`, cut with an ellipsis, not wrapped; the Lindris row shows the literal text `<img src=x onerror="alert(1)">`; the backup and am-videos rows look as they did before this work; nothing runs past the right edge.
2. `feed-intent-390`: one-line section headings, ellipsized when long; the first section holds an open question; "No topic" is last; each heading shows the project after the intent; rows inside look exactly like the ungrouped rows.
3. `feed-tree-390`: "Topic awareness for AI sessions" holds its own rows, then an indented "Manual check…" sub-heading with the fork's rows under it.
4. `feed-*-1280`: the context line sits over the title, the time stays on the title's line, chips stay right-aligned on the meta line.
5. `entry-390`: the breadcrumb wraps onto more lines with `›` separators, above the title; "On this topic" closes the page with title, state chip and age on each line, and the rows are tall enough to tap.
6. `entry-1280`: the pane shows the context lines without breaking the pane's row layout; the breadcrumb and "On this topic" sit in the main column.
7. `feed-tree-390-dark`: muted text is readable on the dark background. If the page is still light, the flag didn't take: say so and don't claim dark mode was checked.

Not covered by these shots: the filter panel (it opens on a click). Its markup is covered by Task 8's tests; Task 14 asks Tiago to look at it on his phone.

- [ ] **Step 5: Fix what the shots show, then re-check the whole set**

For each defect: fix it in `web.py`, add a test when the defect can be asserted in HTML, run `.venv/bin/python -m pytest -q` (stop the screenshot server first, since tests drop the tables), re-seed, restart the server, retake all nine shots, and look at all nine again, not just the one that was wrong. Commit each fix on its own (`fix(inbox): <what the shot showed>`).

- [ ] **Step 6: Stop the server and commit the seed script**

```bash
lsof -ti tcp:8897 | xargs kill
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/inbox
git add tests/visual/seed_topics.py
git commit -m "test(inbox): seed script for the topic-aware screenshot check"
```

The PNGs stay in the ignored `tmp/shots/`. Keep them for the Task 14 report.

---

### Task 12: Docs

**Files:**
- Modify: `modules/inbox/README.md`, `modules/inbox/DESIGN.md`, `modules/registry/README.md`, `modules/inbox/docs/superpowers/specs/2026-11-25-topic-aware-inbox-design.md`

- [ ] **Step 1: Inbox README**

In `modules/inbox/README.md`, add this section before `## Tests`:

````markdown
## Topics

Each entry carries `topic_path`: the asking session's intent and topic from the agent registry, root intent first, as a list of `{id, title, kind}` (`kind` is `intent` or `topic`). It's a snapshot taken when the entry is created, so pages never call the registry, and a topic renamed later keeps its old name here. An ask or post with `--engine` and `--session-id` gets the session's path. A request may name a topic instead, `"topic": "tp-xxxx"`, which wins over the session's path; that's how a `--script` asker files a question under a discussion. An unknown named topic is exit 1. A missing, failing or slow registry (2 s timeout) is not an error: the entry is created with `topic_path: null` and one warning line on stderr.

The link runs the other way too. After the entry commits, the inbox appends a note to the topic's log with `agt registry topic-note`: `asked` or `posted` when it's created, `answered` when it's answered (web, Telegram, CLI or chat), and `closed` when an ask is withdrawn, superseded or expires unanswered. Notes are best effort and never fail the inbox operation. `agt registry topic --done` then lists the questions still waiting as `open_questions`. Each ask or post makes two registry calls (path, then note), each bounded by the 2 s timeout.

The feed shows the last two names of each row's path above its title, with `…` in front when the path is longer. The filter menu adds an intent filter (the intents in the current view) and Group by: none (the plain feed), intent (one section per asking intent, with its project) or topic tree (one section per root, forked intents nested one level). Sections holding an open question come first, and rows without a path go last under "No topic". The `ib_group` cookie remembers the choice. An entry's page shows its full path above the title and, at the bottom, up to 10 other entries on the same topic, newest first. Entries from before this shipped show no path.

`AGENT_INBOX_AGT` overrides the `agt` the inbox runs; the black-box tests point it at the checkout under test. Black-box checks: `.venv/bin/python -m pytest tests/blackbox -q`. Screenshot seed for the visual check: `tests/visual/seed_topics.py`.
````

- [ ] **Step 2: DESIGN.md**

In `modules/inbox/DESIGN.md`, under `### Feed rows`, add two bullets after the `- **States:** …` bullet:

```markdown
- **Context line:** when the row's entry has a topic path, a 12px Grey Meta line above the title names its last two steps, "Intent › Topic", with "… ›" in front of a longer path. One line, cut with an ellipsis; the full path is its tooltip. Rows without a path have no line and keep their height.
- **Group by:** the filter panel's Group by (none, intent, topic tree) splits the feed into sections under 13px/650 Grey Meta headings that stick below the bar, one line each, "Intent · project". Topic tree nests forked intents one level under their root with a 13px/600 sub-heading indented 32px. Sections with an open question come first; "No topic" is last. Rows inside are unchanged.
```

Under `### Entry header`, add:

```markdown
- When the entry has a topic path, it shows first, above the title, as a 14px Grey Meta breadcrumb (root intent first, "›" between steps) that wraps on a phone.
```

After the `### Conversation bubbles` section's bullets, add a new section:

```markdown
### On this topic
- Closes the entry page when other entries share its topic: a 16px heading, then up to 10 rows, newest first, each a 48px link with the title (550, one line, ellipsis) on the left and the state chip plus a 13px Grey Meta age on the right. Hairline between rows, none after the last; hover underlines the title.
```

- [ ] **Step 3: Registry README**

In `modules/registry/README.md`, in the `### intent / topic / topics / fork` code block, add after the `topic-context` line:

```bash
agent-registry topic-path [--topic tp-…]                  # root-first path for the session, or from a topic; null without an intent
agent-registry topic-note asked|posted|answered|closed --topic tp-… --entry ib-… [--title|--value --via|--state] [--type T --session-id S]
```

and add this paragraph after the paragraph that starts `` `topics` skips malformed events``:

```markdown
`topic-path` prints `[{id, title, kind}, …]` from the root intent down to the session's current topic (or its intent), following parent links across sessions and forks; `kind` is `intent` when some session holds that topic as its intent. A missing parent or a cycle ends the walk. An unknown `--topic` exits 2. `topic-note` is how the inbox records its activity in a topic's history: `asked` and `posted` take `--title`, `answered` takes `--value` (kept to 200 characters) and `--via` (web, telegram, chat, cli), `closed` takes `--state` (withdrawn, expired, superseded). The note goes to the given session's log when that session holds the topic, otherwise to the log of the session that minted it. Notes never change a topic's status; `topics` shows them under each topic's `notes`, and `topic --done` adds `open_questions`, the asked entries with no `answered` or `closed` note.
```

- [ ] **Step 4: Write the refinements back into the spec**

In `modules/inbox/docs/superpowers/specs/2026-11-25-topic-aware-inbox-design.md`:
- In section 1, under **How it's filled**, change the `--script` bullet to: ``- A request may name a topic with `"topic": "tp-xxxx"`. The inbox then runs `agt registry topic-path --topic tp-xxxx`, which builds the path up from that topic. A named topic wins over the session's own path; it is how a `--script` asker joins a discussion.``
- In section 2, change `The plan picks between a background call and the inline 2 s timeout; nothing needs a retry queue.` to `They run inline, after the commit, with the same 2 s timeout; nothing needs a retry queue.`
- In section 2, change the `closed` sentence's `(\`entry\`, \`state\`)` to `` (`entry`, `state`: `withdrawn`, `expired` or `superseded`) ``.
- In section 3, under **Topic tree**, append: `Nesting is one level: a fork of a fork is also a sub-section of the root. Group by applies in History too, where its sections replace the day headings.`
- In section 4, change `Under the thread, "On this topic" lists` to `At the end of the page, after the follow-up form, "On this topic" lists`.
- In **Risks**, replace the **Latency** bullet with: ``- **Latency.** Each `agt inbox ask` and `post` makes two registry calls (path, then note), each bounded by the 2 s timeout. Measured on this machine: <the Task 10 Step 5 medians with and without the registry, and their difference>.`` Fill the numbers in from Task 10's measurement before committing; don't commit the angle brackets.

- [ ] **Step 5: Commit**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox
git add modules/inbox/README.md modules/inbox/DESIGN.md modules/registry/README.md \
  modules/inbox/docs/superpowers/specs/2026-11-25-topic-aware-inbox-design.md
git commit -m "docs(inbox): topic-aware inbox in the READMEs, design system and spec"
```

---

### Task 13: Skills

**Files:**
- Modify: `skills/topic-awareness/SKILL.md`, `skills/agent-inbox/SKILL.md`

- [ ] **Step 1: topic-awareness**

In `skills/topic-awareness/SKILL.md`, in `## Name the topic you're on`, after the code block, add:

```markdown
`topic --done` also prints `open_questions`: inbox questions you asked under that topic that are still waiting for Tiago. If the list isn't empty, withdraw each one you no longer need (`agt inbox withdraw ib-…`), or say in one line of chat which ones are still waiting and why. Answered, withdrawn, superseded and expired questions never show up there.
```

- [ ] **Step 2: agent-inbox**

In `skills/agent-inbox/SKILL.md`, in the `Optional fields:` list, add after the `expires_at` bullet:

```markdown
- `topic`: a topic id (`tp-xxxx`, from `agt registry topics`). You rarely need it: with `--engine` and `--session-id` the inbox records your session's intent and topic by itself, and shows them on the entry. A `--script` asker passes it to file the question under that discussion. An unknown id is exit 1.
```

- [ ] **Step 3: Read both files end to end**

Read each changed skill in full and check that the new text doesn't contradict anything around it (the drift-ask rule that drift questions never go through the inbox stays as it is).

- [ ] **Step 4: Commit**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox
git add skills/topic-awareness/SKILL.md skills/agent-inbox/SKILL.md
git commit -m "docs(skills): withdraw or mention open questions at done; a script asker can name a topic"
```

The skills are symlinked from `~/.claude/skills`, `~/.cursor/skills` and `~/.codex/skills` into the main checkout, so they go live when the branch merges. No `install.sh` run is needed.

---

### Task 14: Merge, deploy and verify

No new files. Run every step and report each result as observed.

- [ ] **Step 1: Every suite, in the worktree**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/registry
.venv/bin/python -m pytest -q | tail -1
.venv/bin/python -m pytest tests/blackbox/test_topics_cli.py tests/blackbox/test_topics_hook.py -q | tail -1
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox/modules/inbox
.venv/bin/python -m pytest -q | tail -1
.venv/bin/python -m pytest tests/blackbox -q | tail -1
```

Expected: all pass (registry `293 passed`, inbox `188 passed` plus any tests added in Task 11, black-box `7 passed`).

- [ ] **Step 2: Merge**

Use superpowers:finishing-a-development-branch and let Tiago choose. If he picks a local merge, merge with a merge commit (never squash) from the main checkout. Another session works there, so first check that none of the branch's files are dirty in it:

```bash
cd /Users/tjdsneto/projects/agent-tools
git status --short
git diff --name-only main...tn/feat/topic-aware-inbox
```

If any file in the second list appears in the first, stop and ask Tiago. Otherwise:

```bash
git merge --no-ff tn/feat/topic-aware-inbox -m "Merge branch 'tn/feat/topic-aware-inbox': topic-aware inbox"
```

- [ ] **Step 3: Back up the live inbox**

The first connect after the restart adds the column and the index. Both are additive, but take a dump first:

```bash
/Users/tjdsneto/projects/agent-tools/modules/inbox/bin/backup && ls -t ~/.local/share/agent-inbox/backups | head -1
```

Expected: today's `agent_inbox-<YYYYMMDD>.sql`.

- [ ] **Step 4: Restart the inbox LaunchAgent**

`com.tjdsneto.agent-inbox` runs `agt inbox serve` from the main checkout and caches its code until it restarts. Don't run `./install.sh` for this: nothing it links changed.

```bash
launchctl kickstart -k "gui/$(id -u)/com.tjdsneto.agent-inbox"
curl --retry 10 --retry-connrefused --retry-delay 1 -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8797/
launchctl print "gui/$(id -u)/com.tjdsneto.agent-inbox" | grep -E '^\s*(state|pid) ='
tail -n 20 /Users/tjdsneto/projects/agent-tools/modules/inbox/tmp/serve.log
```

Expected: `200`, `state = running` with a new pid, and no traceback in the log tail.

The registry daemon needs no restart: `topic-path` and `topic-note` run in the CLI process, and nothing the daemon serves changed.

- [ ] **Step 5: Check the live schema**

```bash
/opt/homebrew/opt/postgresql@17/bin/psql -h localhost -p 5433 -d agent_inbox -Atc \
  "SELECT column_name FROM information_schema.columns WHERE table_name = 'entries' AND column_name = 'topic_path'; SELECT to_regclass('entries_topic');"
```

Expected: `topic_path` and `entries_topic`.

- [ ] **Step 6: One live end-to-end report**

From this session (which has an intent and topic set, per the topic-awareness skill):

```bash
agt registry topic-path --type claude --session-id "$CLAUDE_CODE_SESSION_ID"
ENTRY=$(echo '{"title": "Topic-aware inbox is live", "summary": "This report should show its discussion above the title, and a breadcrumb on its page."}' \
  | agt inbox post --engine claude --session-id "$CLAUDE_CODE_SESSION_ID" | python3 -c 'import json,sys; print(json.load(sys.stdin)["entry"])')
agt inbox get "$ENTRY" | python3 -c 'import json,sys; print(json.load(sys.stdin)["topic_path"])'
agt registry topics --type claude --session-id "$CLAUDE_CODE_SESSION_ID" | python3 -c 'import json,sys; print([e for e in json.load(sys.stdin)["events"] if e["event"] == "posted"][-1])'
```

Expected: the same non-null path from both the registry and the entry, and a `posted` event naming `$ENTRY`.

- [ ] **Step 7: Ask Tiago to look**

In chat, give him the link `agt inbox post` printed and ask him to check on his phone: the context line on that row, Group by in the filter panel (each mode, and that it sticks after a reload), and the breadcrumb on the entry page. Record what he reports. Don't claim the phone check passed until he says so.

- [ ] **Step 8: Report**

Report: the suite results from Step 1, the latency medians from Task 10 Step 5, what each screenshot showed in Task 11 Step 4 (and any fix it led to), Steps 4 to 6 as observed, and Tiago's phone check. Then the worktree can go: `git worktree remove /Users/tjdsneto/projects/agent-tools/.worktrees/topic-aware-inbox` (finishing-a-development-branch handles it if he chose that path).
