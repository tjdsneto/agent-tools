# Topic Graph View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A **Topics** tab in the inbox that shows every session's intent as a collapsible outline: its topics, the forks nested under the topic they came from, each topic's timeline of inbox questions and answers, and each session's state with a resume command. It is read live from the agent registry on each load.

**Architecture:** The registry gains `agt registry topics --tree --events`, which runs in the CLI process like every topic command. Each tree node gets `events`, the topic's events merged from every log, oldest first. Each `sessions` entry gets `live`, `state` and `directory`, read from `registry.json` in the same process. The logs are read through an on-disk cache keyed by modification time and size. On the inbox side, `topics.graph()` runs that command through the existing never-raises registry client. A pure module, `topic_graph.py`, checks the reply and folds it into intents, topics and timelines, and it orders them. `web.py` renders the outline at `/topics` and looks up the asked entries' real state in one query.

**Tech Stack:** Python 3.14, Postgres 17 (psycopg 3), stdlib `http.server`, pytest, Node 22 with headless Chrome over CDP for the visual check. Spec: `modules/inbox/docs/superpowers/specs/2026-11-25-topic-graph-design.md` (spec 3). Spec 1: `modules/registry/docs/superpowers/specs/2026-11-25-topic-awareness-design.md`. Spec 2: `modules/inbox/docs/superpowers/specs/2026-11-25-topic-aware-inbox-design.md`. All shipped.

---

## Decisions this plan makes

The spec is a draft whose decisions were made on Tiago's behalf, and this plan builds it as written. The points below are where the spec left room. Task 9 writes them back into the spec.

**Liveness: in-process, from the registry file, with no daemon call.** `agt registry list --json` goes through the daemon. The daemon's `list` op is `ops.list_split()`, which is `store.load()` on `registry.json` plus `is_stale()` per row. The topic command therefore does the same read itself:
- one `store.load()` per command (3.4 ms with today's 968 rows, measured while writing this plan);
- `is_stale()` per row;
- `archive.jsonl` only when some session in the tree has no row (8 ms for today's 2596 records), to find an ended session's directory.

That gives no daemon round trip, no call per node, and nothing that touches the daemon's CPU problem (tjdsneto/agent-tools#9). Each session entry carries `live` (bool, as the spec asks), `state` and `directory`:
- `live`: a row that pinged within the stale window (`STALE_SECONDS`, 1 h);
- `idle`: an older row;
- `ended`: no row;
- `unknown`: `registry.json` unreadable.

The page shows these as Live, Idle and Ended. The project is `Path(directory).name`, the same rule the inbox already uses for an asker's project. It is not `project_key()`, because that function stats parent directories per call.

**The mtime cache is a file, and only `topics --tree` uses it.** Every `agt registry` call is a new process, so a cache held in memory would save nothing between page loads.
- **Where it lives:** `cached_logs()` keeps `topics/.parsed.json`, which holds each log's `[st_mtime_ns, st_size]` and its parsed events.
- **When a log is read:** only when that pair changed. The file is stat'ed before it is read, so a log that changes during the read is read again on the next call.
- **Writes:** a write failure is ignored, and the file is replaced atomically.
- **Measured at 1000 synthetic sessions of 31 events:** parsing the logs takes 101 ms, loading a cache of them 19 ms, and stat'ing every log 3 ms.

The per-row readers behind `list` and the board (`topics.current`, `state`, `read_events`) are untouched, and Task 1 has a test that they never create the file. Plain `--tree` also reads through the cache. Its output is unchanged.

**Which questions are waiting comes from the inbox, not only the log.** Notes are best effort, so a lost `answered` note would leave a question looking open forever. The page collects every asked entry id in the tree and reads their states in one query. An entry the inbox has is waiting only while its state is `open`. An entry the inbox no longer has falls back to the notes.

**What "finished" means.** The spec says "intents whose topics are all done". This plan makes it strict: nothing waiting (no open question and no fork left unadopted), no open or parked topic, and no live session anywhere under the intent. A parked topic is not done. An intent whose session is still live is in flight even with no topics yet.

Finished intents are not rendered by default. A "Show finished (N)" button at the end shows them, last and closed, and the `ib_finished` cookie remembers the choice. Not rendering them handles the Clutter risk, since hundreds of `<details>` would still cost bytes.

**Ordering details.** The spec's three buckets stay. "Newest first" means the most recent event anywhere under the intent, and it also breaks ties inside the first two buckets. Children keep the order they were opened in.

**What starts open.**
- An intent starts open unless it is finished.
- A topic starts open only when something under it needs Tiago.

The live reload still runs, but once a branch has been opened or closed it offers the stale toast instead of reloading, so it doesn't fold the tree back.

**Resume command.** Shown only for a session that isn't live:
- `claude --resume <id>`;
- `codex resume <id>`;
- `cursor-agent --resume <id>`.

It gets a `cd <dir> &&` prefix when the directory is known, and every part is `shlex.quote`d. It renders in a mono box that a tap selects whole. That needs no JS.

**Timelines.**
- A topic's timeline is its own events plus one "Forked" line for each fork opened from it.
- Event labels: Intent set, Picked up (adopt), Opened, Forked off (on the fork itself), Forked, Asked, Posted, Answered, Closed, Done, Parked.
- Asked, posted, answered and closed lines link to their entry.

**Depth.** The root intent is level 0. Levels 1 to 3 indent 16 px each. A node at level 4 or deeper keeps level 3's indent and shows "↳ N".

**The fifth tab.** "Topics" goes after History. Five tabs don't fit 390 px at today's spacing: a dry run of this plan measured 401 px. So below 480 px, the gap drops from 6 to 4 px and the side padding from 12 to 10 px. That measured 373 px, 1 px inside the edge fade. Task 8 re-measures it.

**Dry run.** While this plan was written, every code step was applied to a scratch copy of `main`. Results:
- registry: 311 passed;
- inbox: 222 passed, on a throwaway database;
- inbox black-box: 8 passed;
- the visual runner took all 19 shots, and they were looked at.

Two defects found that way are fixed in the steps below: the cut tab, and the "Show finished" button's link-blue text.

## If Tiago overrules the outline shape

Only the renderer is outline-specific. Tasks 1–3 (the registry command), Task 4 (`topic_graph`: checking, waiting, ordering, finished) and Task 5 (the client and the entry-state query) don't depend on the page's shape. A drawn node-and-edge graph would be a second renderer over the same `topic_graph.View` list. The outline-only parts are:
- `_tree_node`, `_owners`, `_timeline` and the `.tree` CSS in Task 6;
- the Topics shots in Task 8;
- the "Topic outline" section of `DESIGN.md` in Task 9.

The black-box test (Task 7) asserts nesting through `data-topic` attributes, which any renderer can keep. Showing finished intents as closed rows instead of hiding them is a change inside `_topics_page` only.

---

**Conventions:**
- Python: 4-space indents (this repo's pattern), `from __future__ import annotations` in source modules, docstrings where the surrounding code has them.
- Markdown: no hard-wrapped prose.
- Each commit message ends with the co-author trailer your session's system reminder gives. Add files by explicit path. Never `git add -A`, never `git stash`.
- Unit tests: `.venv/bin/python -m pytest -q`, run from the module directory. When this plan was written, main collected 295 registry tests and 198 inbox tests, plus 7 inbox black-box tests and 17 registry topic black-box tests. If main has moved, take Task 0's counts as the baseline and add each task's delta.
- The inbox tests use the shared `agent_inbox_test` database and drop its tables on every test. Don't run two inbox suites at once (another checkout's included), and don't run them while a screenshot or latency server is up.
- `CHROME` defaults to `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`. The visual check needs Node 22 or newer.

**Where the work happens:**
- All implementation runs in the git worktree `/Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph` on branch `tn/feat/topic-graph`, which has its own venvs (Task 0). Other sessions work in the main checkout, so don't edit files there.
- Black-box tests touch only public surfaces: `agt` commands, files on disk, the web handler over HTTP, and the Postgres store. They never import `agent_inbox` or `agent_registry`.
- Never read from or write to `~/.local/share/agent-registry/` before the merge, except to copy it (Tasks 3 and 7). The new command writes `.parsed.json` next to the logs it reads, so measurements run on a copy.
- Deploy only from the main checkout, after the merge (Task 11). Never run `./install.sh` from the worktree: it would relink `agt` and rewrite the LaunchAgent to point at the worktree.

Below, `WT` means `/Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph`. Commands spell it out in full because each shell starts fresh.

---

## File map

| File | Responsibility |
|---|---|
| `modules/registry/src/agent_registry/topics.py` (modify) | `cached_logs()` and its cache file; `tree(events=, logs=)` |
| `modules/registry/src/agent_registry/liveness.py` (create) | `lookup()` and `annotate()`: live, idle or ended per session, from `registry.json` and `archive.jsonl` |
| `modules/registry/src/agent_registry/topic_cli.py` (modify) | `topics --tree --events` |
| `modules/registry/tests/test_topic_cache.py` (create) | Changed logs are re-read, unchanged ones aren't; a bad cache is rebuilt; per-row readers never touch it |
| `modules/registry/tests/test_topic_tree_events.py` (create) | Merged events per node; a cached tree equals a fresh one |
| `modules/registry/tests/test_liveness.py` (create) | Live, idle, ended, unknown; the archive is read only when needed |
| `modules/registry/tests/test_topic_cli.py` (modify) | The flag through `main()` |
| `modules/inbox/src/agent_inbox/topic_graph.py` (create) | Pure: check the registry's tree, fold it into views, order them, resume commands |
| `modules/inbox/src/agent_inbox/topics.py` (modify) | `graph()` |
| `modules/inbox/src/agent_inbox/store.py` (modify) | `entry_states()` |
| `modules/inbox/src/agent_inbox/web.py` (modify) | Topics tab, `/topics` route, outline rendering and CSS, `ib_finished` cookie, toggle-aware reload |
| `modules/inbox/tests/topic_tree_helpers.py` (create) | Tree builders and the HTML nesting reader, shared by unit and black-box tests |
| `modules/inbox/tests/test_topic_graph.py`, `test_topics_page.py` (create) | Unit tests |
| `modules/inbox/tests/test_topics.py`, `test_store_topics.py` (modify) | Unit tests |
| `modules/inbox/tests/blackbox/conftest.py` (modify), `test_topics_page.py` (create) | The page against a temp registry |
| `modules/inbox/tests/visual/cdpshot.mjs`, `shots.sh`, `README.md` (modify), `seed_registry.py` (create) | Topics shots |
| `modules/inbox/README.md`, `DESIGN.md`, `PRODUCT.md`, `modules/registry/README.md`, the spec (modify) | Docs |
| `skills/topic-awareness/SKILL.md` (modify) | One line: Tiago reads the same tree on the Topics tab |

---

### Task 0: Worktree

**Files:** none.

- [ ] **Step 1: Create the worktree and branch**

```bash
cd /Users/tjdsneto/projects/agent-tools
git worktree add .worktrees/topic-graph -b tn/feat/topic-graph main
git -C .worktrees/topic-graph log --oneline -1
```

Expected: the worktree is created and its HEAD is the same commit as `main`. `.worktrees/` is already in `.gitignore`.

- [ ] **Step 2: Give each module its own venv**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph
for mod in registry inbox; do
  python3 -m venv "modules/$mod/.venv"
  "modules/$mod/.venv/bin/pip" install -q -r "modules/$mod/requirements.txt"
done
```

Expected: no errors. If pip has no network, symlink the main checkout's venvs instead (`ln -s /Users/tjdsneto/projects/agent-tools/modules/$mod/.venv modules/$mod/.venv`). A symlink isn't matched by the `.venv/` ignore rule, so never commit it.

- [ ] **Step 3: Baseline every suite**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph/modules/registry && .venv/bin/python -m pytest -q | tail -1
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph/modules/registry && .venv/bin/python -m pytest tests/blackbox/test_topics_cli.py tests/blackbox/test_topics_hook.py -q | tail -1
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph/modules/inbox && .venv/bin/python -m pytest -q | tail -1
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph/modules/inbox && .venv/bin/python -m pytest tests/blackbox -q | tail -1
```

Expected: `295 passed`, `17 passed`, `198 passed`, `7 passed`. Write down what you see; later tasks give deltas from these.

---

### Task 1: Registry log cache

**Files:**
- Modify: `modules/registry/src/agent_registry/topics.py` (imports, constants after `NOTE_FIELDS`, new functions after `_all_logs`)
- Test: `modules/registry/tests/test_topic_cache.py`

- [ ] **Step 1: Write the failing tests**

Create `modules/registry/tests/test_topic_cache.py`:

```python
import json

import pytest

from agent_registry import topics


def _cache():
    return json.loads((topics.topics_dir() / topics.CACHE_NAME).read_text())


def test_an_unchanged_log_is_not_read_again(tmp_registry, monkeypatch):
    topics.set_intent("claude", "a", "A")
    topics.set_intent("claude", "b", "B")
    first = topics.cached_logs()
    assert [(t, s, [e["event"] for e in ev]) for t, s, ev in first] == [
        ("claude", "a", ["intent"]), ("claude", "b", ["intent"]),
    ]
    reads = []
    real = topics.read_events
    monkeypatch.setattr(topics, "read_events", lambda t, s: reads.append(s) or real(t, s))
    assert topics.cached_logs() == first
    assert reads == []
    topics.open_topic("claude", "b", "Plan")
    reads.clear()  # open_topic read the logs itself
    after = topics.cached_logs()
    assert reads == ["b"]
    assert [e["event"] for e in after[1][2]] == ["intent", "topic"]


def test_new_and_removed_logs_are_followed(tmp_registry):
    topics.set_intent("claude", "a", "A")
    topics.cached_logs()
    topics.set_intent("codex", "c", "C")
    topics.log_path("claude", "a").unlink()
    assert [(t, s) for t, s, _ in topics.cached_logs()] == [("codex", "c")]
    assert list(_cache()["logs"]) == ["codex/c.jsonl"]


@pytest.mark.parametrize("junk", [
    "not json",
    "[]",
    '{"version": 0, "logs": {}}',
    '{"version": 1, "logs": {"claude/a.jsonl": {"sig": "x", "events": []}}}',
])
def test_a_bad_cache_is_ignored_and_rebuilt(tmp_registry, junk):
    topics.set_intent("claude", "a", "A")
    (topics.topics_dir() / topics.CACHE_NAME).write_text(junk)
    assert [e["event"] for _, _, ev in topics.cached_logs() for e in ev] == ["intent"]
    assert _cache()["version"] == topics.CACHE_VERSION


def test_an_unwritable_topics_dir_still_reads(tmp_registry):
    topics.set_intent("claude", "a", "A")
    root = topics.topics_dir()
    root.chmod(0o555)
    try:
        assert [s for _, s, _ in topics.cached_logs()] == ["a"]
    finally:
        root.chmod(0o755)
    assert not (root / topics.CACHE_NAME).exists()


def test_the_per_row_readers_never_touch_the_cache(tmp_registry):
    """The daemon's list and board read one log per row (tjdsneto/agent-tools#9); they stay as they were."""
    topics.set_intent("claude", "a", "A")
    topics.current("claude", "a")
    topics.state("claude", "a")
    topics.tree()
    assert not (topics.topics_dir() / topics.CACHE_NAME).exists()
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph/modules/registry && .venv/bin/python -m pytest tests/test_topic_cache.py -q`
Expected: FAIL with `AttributeError: module 'agent_registry.topics' has no attribute 'cached_logs'` (and `CACHE_NAME`).

- [ ] **Step 3: Implement the cache**

In `modules/registry/src/agent_registry/topics.py`, add `import tempfile` to the imports, after `import secrets`:

```python
import secrets
import tempfile
```

After the line `NOTE_FIELDS = ("entry", "title", "value", "via", "state")`, add:

```python
# Parsed logs for `topics --tree`, kept beside them. Bump the version when read_events changes what it keeps.
CACHE_NAME = ".parsed.json"
CACHE_VERSION = 1
```

After the `_all_logs` function, add:

```python
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
```

- [ ] **Step 4: Run the tests**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph/modules/registry && .venv/bin/python -m pytest tests/test_topic_cache.py -q`
Expected: `8 passed`.

Run the whole suite: `.venv/bin/python -m pytest -q | tail -1`
Expected: `303 passed` (baseline + 8).

- [ ] **Step 5: Commit**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph
git add modules/registry/src/agent_registry/topics.py modules/registry/tests/test_topic_cache.py
git commit -m "feat(registry): cache parsed topic logs by modification time and size"
```

---

### Task 2: Registry tree events

**Files:**
- Modify: `modules/registry/src/agent_registry/topics.py` (`tree`)
- Test: `modules/registry/tests/test_topic_tree_events.py`

- [ ] **Step 1: Write the failing tests**

Create `modules/registry/tests/test_topic_tree_events.py`:

```python
from agent_registry import topics


def test_tree_events_merge_every_log_oldest_first(tmp_registry):
    root = topics.set_intent("claude", "p", "Parent")["topic"]["id"]
    plan = topics.open_topic("claude", "p", "Plan")["topic"]["id"]
    topics.add_note("asked", plan, "ib-1", agent_type="claude", session_id="p", title="Which?")
    fork = topics.record_fork("claude", "p", "Side", mode="side", backend="none", brief_text="b")["topic"]["id"]
    topics.adopt("codex", "c", fork)
    topics.add_note("answered", plan, "ib-1", value="a", via="web")
    (node,) = topics.tree(events=True)
    assert node["id"] == root
    assert [(e["event"], e["session_id"]) for e in node["events"]] == [("intent", "p")]
    assert "topic" not in node["events"][0] and node["events"][0]["agent_type"] == "claude"
    (plan_node,) = node["children"]
    assert [(e["event"], e.get("entry")) for e in plan_node["events"]] == [
        ("topic", None), ("asked", "ib-1"), ("answered", "ib-1"),
    ]
    (fork_node,) = plan_node["children"]
    assert [(e["event"], e["agent_type"], e["session_id"]) for e in fork_node["events"]] == [
        ("forked", "claude", "p"), ("adopt", "codex", "c"),
    ]
    assert "events" not in topics.tree()[0]


def test_a_tree_from_cached_logs_matches_a_fresh_read(tmp_registry):
    topics.set_intent("claude", "p", "Parent")
    topics.open_topic("claude", "p", "Plan")
    topics.cached_logs()  # warm the cache, so the next call serves from it
    assert topics.tree(events=True, logs=topics.cached_logs()) == topics.tree(events=True)
    assert topics.tree(logs=topics.cached_logs()) == topics.tree()
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph/modules/registry && .venv/bin/python -m pytest tests/test_topic_tree_events.py -q`
Expected: FAIL with `TypeError: tree() got an unexpected keyword argument 'events'`.

- [ ] **Step 3: Replace `tree`**

In `modules/registry/src/agent_registry/topics.py`, replace the whole `tree` function with:

```python
def tree(*, events: bool = False, logs: list[tuple[str, str, list[dict]]] | None = None) -> list[dict]:
    """Every topic across sessions as nested nodes. A topic's status is its latest event's.

    events adds each node's `events`: every log's events for that topic, oldest first, each
    without its `topic` and with the agent_type and session_id of the log it came from. logs
    stands in for reading every log; `topics --tree` passes cached_logs()."""
    nodes: dict[str, dict] = {}
    latest: dict[str, str] = {}
    history: dict[str, list[dict]] = {}
    for agent_type, session_id, log in (_all_logs() if logs is None else logs):
        st = _replay(log)
        if events:
            for ev in log:
                history.setdefault(ev["topic"]["id"], []).append(
                    {**{k: v for k, v in ev.items() if k != "topic"}, "agent_type": agent_type, "session_id": session_id}
                )
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
        if events:
            node["events"] = sorted(history.get(node["id"], []), key=lambda e: (e.get("at") is None, e.get("at") or ""))
        parent = nodes.get(node["parent"]) if node["parent"] else None
        (parent["children"] if parent else roots).append(node)
    return roots
```

Only three things changed from the old body: the loop variable is `log` (it was `events`), the `history` collection, and the `node["events"]` line.

- [ ] **Step 4: Run the tests**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph/modules/registry && .venv/bin/python -m pytest tests/test_topic_tree_events.py tests/test_topic_notes.py tests/test_topics_list.py -q | tail -1`
Expected: all pass.

Run the whole suite: `.venv/bin/python -m pytest -q | tail -1`
Expected: `305 passed`.

- [ ] **Step 5: Commit**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph
git add modules/registry/src/agent_registry/topics.py modules/registry/tests/test_topic_tree_events.py
git commit -m "feat(registry): tree nodes can carry their merged events"
```

---

### Task 3: Liveness and `topics --tree --events`

**Files:**
- Create: `modules/registry/src/agent_registry/liveness.py`
- Modify: `modules/registry/src/agent_registry/topic_cli.py`
- Test: `modules/registry/tests/test_liveness.py`, `modules/registry/tests/test_topic_cli.py`

- [ ] **Step 1: Write the failing liveness tests**

Create `modules/registry/tests/test_liveness.py`:

```python
import json
from datetime import datetime, timedelta, timezone

import pytest

from agent_registry import archive, liveness, topics

NOW = datetime(2026, 11, 25, 20, 0, tzinfo=timezone.utc)


def _row(agent_type, session_id, directory, minutes_ago):
    ping = (NOW - timedelta(minutes=minutes_ago)).isoformat()
    return {
        "registry_id": f"r-{session_id}", "session_id": session_id, "agent_type": agent_type, "directory": directory,
        "parent_session_id": None, "status": "idle", "summary": "", "issue": None, "pr": None, "branch": None,
        "goflow_timer_id": None, "registered_at": ping, "last_ping": ping, "updated_at": ping,
    }


def _registry(path, *rows):
    path.write_text(json.dumps({"version": 1, "sessions": list(rows)}))


def _archive(path, *rows):
    path.with_name("archive.jsonl").write_text("".join(
        json.dumps({"archived_at": NOW.isoformat(), "reason": "unregister", "session": row}) + "\n" for row in rows
    ))


def test_rows_and_the_archive_say_who_is_live_idle_or_ended(tmp_registry):
    _registry(tmp_registry, _row("claude", "on", "/p/a", 5), _row("claude", "old", "/p/b", 180))
    _archive(tmp_registry, _row("codex", "gone", "/p/old", 900), _row("codex", "gone", "/p/c", 600))
    got = liveness.lookup({("claude", "on"), ("claude", "old"), ("codex", "gone"), ("cursor", "never")}, now=NOW)
    assert got == {
        ("claude", "on"): {"live": True, "state": "live", "directory": "/p/a"},
        ("claude", "old"): {"live": False, "state": "idle", "directory": "/p/b"},
        ("codex", "gone"): {"live": False, "state": "ended", "directory": "/p/c"},
        ("cursor", "never"): {"live": False, "state": "ended", "directory": None},
    }


def test_the_archive_is_read_only_for_sessions_without_a_row(tmp_registry, monkeypatch):
    _registry(tmp_registry, _row("claude", "on", "/p/a", 5))
    monkeypatch.setattr(archive, "read_events", lambda: pytest.fail("read the archive"))
    assert liveness.lookup({("claude", "on")}, now=NOW)[("claude", "on")]["live"] is True
    assert liveness.lookup(set(), now=NOW) == {}


def test_a_corrupt_registry_leaves_every_session_unknown(tmp_registry):
    tmp_registry.write_text("{not json")
    assert liveness.lookup({("claude", "x")}, now=NOW) == {
        ("claude", "x"): {"live": False, "state": "unknown", "directory": None},
    }


def test_annotate_marks_every_session_in_the_tree(tmp_registry):
    topics.set_intent("claude", "p", "Parent")
    fork = topics.record_fork("claude", "p", "Side", mode="side", backend="none", brief_text="b")["topic"]["id"]
    topics.adopt("claude", "c", fork)
    _registry(tmp_registry, _row("claude", "c", "/p/side", 1))
    (root,) = liveness.annotate(topics.tree(), now=NOW)
    sessions = root["sessions"] + root["children"][0]["sessions"]
    # Logs are read in path order, so the adopter's log (c) comes before the parent's (p).
    assert [(s["session_id"], s["role"], s["state"], s["directory"]) for s in sessions] == [
        ("p", "intent", "ended", None), ("c", "intent", "live", "/p/side"), ("p", "forked", "ended", None),
    ]
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph/modules/registry && .venv/bin/python -m pytest tests/test_liveness.py -q`
Expected: FAIL with `ImportError: cannot import name 'liveness'`.

- [ ] **Step 3: Write the module**

Create `modules/registry/src/agent_registry/liveness.py`:

```python
"""Which sessions are live, for the topic tree. Read from the registry file in this process, as
the daemon's own `list` does, so it adds no daemon call."""
from __future__ import annotations

from datetime import datetime

from agent_registry import archive, store
from agent_registry.models import is_stale

UNKNOWN = {"live": False, "state": "unknown", "directory": None}


def lookup(keys: set[tuple[str, str]], *, now: datetime | None = None) -> dict[tuple[str, str], dict]:
    """(agent_type, session_id) -> {live, state, directory}. A row that pinged within the stale
    window is live and an older one idle. A session with no row has ended; its directory comes
    from its latest archive record, and the archive is read only when some session has no row."""
    if not keys:
        return {}
    try:
        rows = store.load().sessions
    except (store.CorruptRegistryError, OSError):
        return {key: dict(UNKNOWN) for key in keys}
    found: dict[tuple[str, str], dict] = {}
    for session in rows:
        key = (session.agent_type, session.session_id)
        if key not in keys or (key in found and found[key]["live"]):
            continue
        try:
            stale = is_stale(session, now=now)
        except (TypeError, ValueError, AttributeError):
            stale = True
        found[key] = {"live": not stale, "state": "idle" if stale else "live", "directory": session.directory}
    missing = keys - found.keys()
    if missing:
        ended: dict[tuple[str, str], str] = {}
        for event in archive.read_events():
            row = event.get("session")
            if not isinstance(row, dict):
                continue
            key = (row.get("agent_type"), row.get("session_id"))
            if key in missing and isinstance(row.get("directory"), str):
                ended[key] = row["directory"]
        for key in missing:
            found[key] = {"live": False, "state": "ended", "directory": ended.get(key)}
    return found


def annotate(roots: list[dict], *, now: datetime | None = None) -> list[dict]:
    """Give every session entry in the tree its live, state and directory, in place."""
    nodes: list[dict] = []
    stack = list(roots)
    while stack:
        node = stack.pop()
        nodes.append(node)
        stack.extend(node["children"])
    seen = lookup({(s["agent_type"], s["session_id"]) for node in nodes for s in node["sessions"]}, now=now)
    for node in nodes:
        for session in node["sessions"]:
            session.update(seen.get((session["agent_type"], session["session_id"]), UNKNOWN))
    return roots
```

- [ ] **Step 4: Run the liveness tests**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph/modules/registry && .venv/bin/python -m pytest tests/test_liveness.py -q`
Expected: `4 passed`.

- [ ] **Step 5: Write the failing CLI tests**

Append to `modules/registry/tests/test_topic_cli.py`:

```python
def test_topics_tree_events_adds_history_and_liveness(tmp_registry, capsys):
    _run(capsys, "intent", "Ship it", *WHO)
    _run(capsys, "topic", "Plan", *WHO)
    code, out, _ = _run(capsys, "topics", "--tree", "--events")
    assert code == EXIT_OK
    (root,) = json.loads(out)["tree"]
    assert [(e["event"], e["session_id"]) for e in root["events"]] == [("intent", "s1")]
    assert root["sessions"] == [
        {"agent_type": "claude", "session_id": "s1", "role": "intent", "live": False, "state": "ended", "directory": None},
    ]
    assert [e["event"] for e in root["children"][0]["events"]] == ["topic"]
    code, out, _ = _run(capsys, "topics", "--tree")
    plain = json.loads(out)["tree"][0]
    assert "events" not in plain and "live" not in plain["sessions"][0]


def test_events_goes_with_tree(tmp_registry, capsys):
    assert _run(capsys, "topics", "--events", *WHO)[0] == EXIT_USAGE
    assert _run(capsys, "topics", "--open", "--events")[0] == EXIT_USAGE
```

Run: `.venv/bin/python -m pytest tests/test_topic_cli.py -q -k "events"`
Expected: FAIL. argparse rejects `--events` (`unrecognized arguments`, exit 2).

- [ ] **Step 6: Add the flag**

In `modules/registry/src/agent_registry/topic_cli.py`, change the import line to:

```python
from agent_registry import forking, liveness, topics
```

In `add_parsers`, after `which.add_argument("--tree", action="store_true")`, add:

```python
    p.add_argument("--events", action="store_true")
```

In `_dispatch`, replace:

```python
    if cmd == "topics":
        if args.open:
            return {"topics": topics.open_topics()}
        if args.tree:
            return {"tree": topics.tree()}
```

with:

```python
    if cmd == "topics":
        if args.events and not args.tree:
            raise topics.TopicUsageError("--events goes with --tree")
        if args.open:
            return {"topics": topics.open_topics()}
        if args.tree:
            roots = topics.tree(events=args.events, logs=topics.cached_logs())
            return {"tree": liveness.annotate(roots) if args.events else roots}
```

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_topic_cli.py -q | tail -1`
Expected: all pass.

Run the whole suite and the topic black-box checks:

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph/modules/registry
.venv/bin/python -m pytest -q | tail -1
.venv/bin/python -m pytest tests/blackbox/test_topics_cli.py tests/blackbox/test_topics_hook.py -q | tail -1
```

Expected: `311 passed` and `17 passed`.

- [ ] **Step 8: Measure the command on a copy of the real logs**

The command writes `.parsed.json` beside the logs it reads, so it runs on a copy. Never point it at `~/.local/share/agent-registry/` before the merge.

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph/modules/registry
rm -rf tmp/live-copy && mkdir -p tmp/live-copy
cp -R ~/.local/share/agent-registry/topics tmp/live-copy/topics
cp ~/.local/share/agent-registry/registry.json ~/.local/share/agent-registry/archive.jsonl tmp/live-copy/
rm -f tmp/live-copy/topics/.parsed.json
find tmp/live-copy/topics -name '*.jsonl' | wc -l
for i in 1 2 3 4 5 6; do
  /usr/bin/time -p env AGENT_REGISTRY_PATH="$PWD/tmp/live-copy/registry.json" ../../agt/agt registry topics --tree --events 2>&1 >/dev/null | grep '^real'
done
echo "main's --tree, for comparison:"
/usr/bin/time -p env AGENT_REGISTRY_PATH="$PWD/tmp/live-copy/registry.json" /Users/tjdsneto/projects/agent-tools/agt/agt registry topics --tree 2>&1 >/dev/null | grep '^real'
AGENT_REGISTRY_PATH="$PWD/tmp/live-copy/registry.json" ../../agt/agt registry topics --tree --events \
  | .venv/bin/python -c 'import json,sys; t=json.load(sys.stdin)["tree"]; s=[x for n in t for x in n["sessions"]]; print(len(t), "roots;", sorted({x["state"] for x in s}))'
test ! -e ~/.local/share/agent-registry/topics/.parsed.json && echo "live topics dir untouched"
```

Expected:
- the log count (7 when this plan was written);
- six `real` lines: the first builds the cache, and runs 2 to 6 are warm;
- main's time (0.08 to 0.09 s when this plan was written);
- a roots count with states drawn from `live`, `idle` and `ended`;
- `live topics dir untouched`.

Write down the warm median and main's time. If the warm median is above 0.5 s, stop and report before going on.

Then measure growth on synthetic logs, at 1000 sessions of 31 events each:

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph/modules/registry
rm -rf tmp/bench && mkdir -p tmp/bench/topics/claude
.venv/bin/python - <<'PY'
import json
from pathlib import Path

root = Path("tmp/bench/topics/claude")
for s in range(1000):
    lines = [{"event": "intent", "at": "2026-11-25T10:00:00+00:00", "topic": {"id": f"tp-i{s}", "title": "An intent of ordinary length"}}]
    for t in range(10):
        topic = {"id": f"tp-t{s}x{t}", "title": "A topic title"}
        lines += [
            {"event": "topic", "at": "2026-11-25T10:01:00+00:00", "topic": topic, "parent": f"tp-i{s}"},
            {"event": "asked", "at": "2026-11-25T10:02:00+00:00", "topic": topic, "entry": f"ib-{s}x{t}", "title": "A question"},
            {"event": "done", "at": "2026-11-25T10:03:00+00:00", "topic": topic},
        ]
    (root / f"s{s}.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))
PY
for i in 1 2 3 4; do
  /usr/bin/time -p env AGENT_REGISTRY_PATH="$PWD/tmp/bench/registry.json" ../../agt/agt registry topics --tree --events 2>&1 >/dev/null | grep '^real'
done
```

Expected: four `real` lines, the first cold. While this plan was written, main's uncached `--tree` took 0.22 s on the same shape. Write down the cold time and the warm median. If the warm median is above 1.0 s (half the inbox's 2 s timeout), stop and report: the Topics page would time out first as logs grow. `tmp/` is ignored by git.

- [ ] **Step 9: Commit**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph
git add modules/registry/src/agent_registry/liveness.py modules/registry/src/agent_registry/topic_cli.py \
  modules/registry/tests/test_liveness.py modules/registry/tests/test_topic_cli.py
git commit -m "feat(registry): topics --tree --events with each session's liveness"
```

---

### Task 4: The Topics model

**Files:**
- Create: `modules/inbox/src/agent_inbox/topic_graph.py`
- Create: `modules/inbox/tests/topic_tree_helpers.py`
- Test: `modules/inbox/tests/test_topic_graph.py`

- [ ] **Step 1: Write the shared test helpers**

Create `modules/inbox/tests/topic_tree_helpers.py`:

```python
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
```

- [ ] **Step 2: Write the failing tests**

Create `modules/inbox/tests/test_topic_graph.py`:

```python
import pytest
from topic_tree_helpers import ev, node, sess

from agent_inbox import topic_graph


def views(*roots, states=None):
    return topic_graph.build(topic_graph.clean({"tree": list(roots)}), states or {})


def intent(nid, minutes, *children, state="ended"):
    return node(nid, nid, sessions=[sess(f"s-{nid}", state=state)], events=[ev("intent", minutes)], children=list(children))


def topic(nid, minutes, status="open", *more):
    closed = [ev(status, minutes - 1)] if status != "open" else []
    return node(nid, nid, status=status, sessions=[sess("x", role="topic")], events=[ev("topic", minutes), *closed, *more])


@pytest.mark.parametrize("reply", [None, [], {"tree": "x"}, {"nodes": []}])
def test_clean_refuses_what_isnt_a_tree(reply):
    assert topic_graph.clean(reply) is None


def test_clean_drops_bad_nodes_sessions_and_events():
    raw = {"tree": [
        "junk",
        {"id": ""},
        {
            "id": "tp-a", "title": 7, "status": "weird",
            "sessions": [
                {"agent_type": "claude"},
                {"agent_type": "claude", "session_id": "s", "role": "boss", "live": "yes", "state": "zombie", "directory": 3},
            ],
            "events": [{"at": "x"}, {"event": "asked", "at": 5, "entry": ["ib-1"], "title": "Q"}],
            "children": [{"id": "tp-b"}, None],
        },
    ]}
    assert topic_graph.clean(raw) == [{
        "id": "tp-a", "title": None, "status": "open",
        "sessions": [{"agent_type": "claude", "session_id": "s", "role": "topic", "live": False, "state": "unknown", "directory": None}],
        "events": [{"event": "asked", "at": None, "entry": None, "title": "Q", "value": None, "via": None, "state": None, "ref": None}],
        "children": [{"id": "tp-b", "title": None, "status": "open", "sessions": [], "events": [], "children": []}],
    }]


def test_build_sets_kind_depth_owners_and_lines():
    fork = node("tp-f", "Side", sessions=[sess("p", role="forked"), sess("c", state="idle"), sess("c2", state="live")],
                events=[ev("forked", 50, session_id="p"), ev("adopt", 40, session_id="c")])
    plan = node("tp-p", "Plan", sessions=[sess("p", role="topic")], children=[fork], events=[
        ev("topic", 90), ev("asked", 80, entry="ib-1", title="Which?"), ev("answered", 30, entry="ib-1", value="b", via="chat"),
    ])
    early = node("tp-e", None, status="done", sessions=[sess("p", role="topic")], events=[ev("topic", 95), ev("done", 92)])
    (root,) = views(node("tp-r", "Root", sessions=[sess("p")], events=[ev("intent", 100)], children=[plan, early]))
    assert (root.kind, root.depth, [c.id for c in root.children]) == ("intent", 0, ["tp-e", "tp-p"])
    early_v, plan_v = root.children
    assert (early_v.kind, early_v.title, early_v.status) == ("topic", "tp-e", "done")
    assert [(l.event, l.text, l.entry, l.via) for l in plan_v.lines] == [
        ("topic", None, None, None), ("asked", "Which?", "ib-1", None),
        ("fork", "Side", None, None), ("answered", "b", "ib-1", "chat"),
    ]
    (fork_v,) = plan_v.children
    assert (fork_v.kind, fork_v.depth) == ("intent", 2)
    assert [s["session_id"] for s in fork_v.owners] == ["c2", "c"]
    assert [l.event for l in fork_v.lines] == ["forked", "adopt"]


def test_the_inbox_state_wins_over_the_notes():
    plan = node("tp-p", "Plan", sessions=[sess("p", role="topic")], events=[
        ev("asked", 50, entry="ib-answered", title="A"),  # answered in the inbox; its note was lost
        ev("asked", 40, entry="ib-open", title="B"),  # a note says answered, but the inbox has it open
        ev("answered", 30, entry="ib-open", value="x", via="web"),
        ev("asked", 20, entry="ib-gone", title="C"),  # the inbox no longer has it: the notes decide
        ev("asked", 10, entry="ib-settled", title="D"),
        ev("closed", 5, entry="ib-settled", state="withdrawn"),
    ])
    (root,) = views(node("tp-r", "Root", sessions=[sess("p")], events=[ev("intent", 60)], children=[plan]),
                    states={"ib-answered": "answered", "ib-open": "open"})
    assert root.children[0].waiting == ["ib-open", "ib-gone"]
    assert root.questions() == 2 and root.needs_you()


def test_order_puts_what_needs_you_first_and_holds_back_the_finished():
    done = intent("tp-done", 10, topic("tp-d1", 9, "done"))  # the newest, but finished
    rest = intent("tp-rest", 20, topic("tp-r1", 19, "parked"))  # parked is not finished
    busy_old = intent("tp-busy-old", 300, topic("tp-b1", 299))
    busy_new = intent("tp-busy-new", 30, topic("tp-b2", 29))
    asks = intent("tp-asks", 500, topic("tp-a1", 499, "open", ev("asked", 400, entry="ib-q", title="Q")))
    stray = intent("tp-stray", 200, node("tp-fork", "Fork", status="forked",
                                         sessions=[sess("s-tp-stray", role="forked")], events=[ev("forked", 199)]))
    shown, finished = topic_graph.order(views(done, rest, busy_old, busy_new, asks, stray))
    assert [v.id for v in shown] == ["tp-stray", "tp-asks", "tp-busy-new", "tp-busy-old", "tp-rest"]
    assert [v.id for v in finished] == ["tp-done"]


def test_live_or_parked_is_not_finished_and_an_empty_ended_intent_is():
    (live,) = views(intent("tp-l", 10, state="live"))
    (parked,) = views(intent("tp-p", 10, topic("tp-p1", 9, "parked")))
    (empty,) = views(intent("tp-e", 10))
    assert (live.finished(), parked.finished(), empty.finished()) == (False, False, True)
    assert live.live() and parked.parked() == 1


def test_resume_command_per_engine_with_every_part_quoted():
    assert topic_graph.resume_command(sess("abc", directory="/x/my project")) == "cd '/x/my project' && claude --resume abc"
    assert topic_graph.resume_command(sess("t-1", agent="codex", directory=None)) == "codex resume t-1"
    assert topic_graph.resume_command(sess("c-1", agent="cursor", directory="/x/a")) == "cd /x/a && cursor-agent --resume c-1"
    assert topic_graph.resume_command(sess("x", agent="gemini")) is None
    assert topic_graph.resume_command(sess("$(rm -rf ~)", directory=None)) == "claude --resume '$(rm -rf ~)'"


def test_asked_entries_lists_each_once_across_the_tree():
    child = node("tp-c", "C", events=[ev("asked", 5, entry="ib-2", title="Q"), ev("asked", 4, entry="ib-1", title="Q")])
    root = node("tp-r", "R", children=[child], events=[
        ev("asked", 9, entry="ib-1", title="Q"), ev("posted", 8, entry="ib-9", title="P"),
    ])
    assert sorted(topic_graph.asked_entries(topic_graph.clean({"tree": [root]}))) == ["ib-1", "ib-2"]
```

- [ ] **Step 3: Run them to see them fail**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph/modules/inbox && .venv/bin/python -m pytest tests/test_topic_graph.py -q`
Expected: FAIL with `ImportError: cannot import name 'topic_graph'`.

- [ ] **Step 4: Write the module**

Create `modules/inbox/src/agent_inbox/topic_graph.py`:

```python
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
```

- [ ] **Step 5: Run the tests**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph/modules/inbox && .venv/bin/python -m pytest tests/test_topic_graph.py -q`
Expected: `11 passed`.

Run the whole suite: `.venv/bin/python -m pytest -q | tail -1`
Expected: `209 passed` (baseline + 11).

- [ ] **Step 6: Commit**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph
git add modules/inbox/src/agent_inbox/topic_graph.py modules/inbox/tests/topic_tree_helpers.py modules/inbox/tests/test_topic_graph.py
git commit -m "feat(inbox): topic_graph folds the registry tree into ordered intents and timelines"
```

---

### Task 5: The registry call and the entry states

**Files:**
- Modify: `modules/inbox/src/agent_inbox/topics.py`, `modules/inbox/src/agent_inbox/store.py` (after `same_topic`)
- Test: `modules/inbox/tests/test_topics.py`, `modules/inbox/tests/test_store_topics.py`

- [ ] **Step 1: Write the failing tests**

Append to `modules/inbox/tests/test_topics.py`:

```python
def test_graph_asks_for_the_tree_with_events_and_cleans_it(fake_registry):
    good = {"id": "tp-a", "title": "A", "status": "open", "sessions": [], "events": [], "children": []}
    fake_registry.replies["topics"] = {"tree": [good, "junk"]}
    assert topics.graph() == [good]
    assert fake_registry.calls == [["topics", "--tree", "--events"]]


def test_graph_is_none_when_the_registry_fails(fake_registry):
    assert topics.graph() is None  # an unset command answers None, like a registry that is down
    fake_registry.replies["topics"] = topics.NOT_FOUND
    assert topics.graph() is None
```

Append to `modules/inbox/tests/test_store_topics.py`:

```python
def test_entry_states_reads_each_known_entry(conn):
    a = ask(conn)
    b = ask(conn)
    store.answer(conn, b["id"], "a", via="web")
    assert store.entry_states(conn, [a["id"], b["id"], "ib-gone"]) == {a["id"]: "open", b["id"]: "answered"}
    assert store.entry_states(conn, []) == {}
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph/modules/inbox && .venv/bin/python -m pytest tests/test_topics.py tests/test_store_topics.py -q -k "graph or entry_states"`
Expected: FAIL with `AttributeError: module 'agent_inbox.topics' has no attribute 'graph'` and `... 'agent_inbox.store' has no attribute 'entry_states'`.

- [ ] **Step 3: Implement both**

In `modules/inbox/src/agent_inbox/topics.py`, replace the module docstring with:

```python
"""The inbox's one door into the agent registry's topic log.

Every call runs `agt registry …` with a short timeout. A missing, slow or failing registry
never blocks an ask, a post or an answer: the entry or the topic history just lacks the link,
and the Topics page shows a notice."""
```

Change the import block's last line from `from agent_inbox.errors import ValidationError` to:

```python
from agent_inbox import topic_graph
from agent_inbox.errors import ValidationError
```

Append to the end of the file:

```python
def graph() -> list[dict] | None:
    """Every intent and topic for the Topics page: each node with its events and its sessions'
    liveness, checked by topic_graph.clean. None when the registry fails or answers with
    something else."""
    return topic_graph.clean(registry("topics", "--tree", "--events"))
```

In `modules/inbox/src/agent_inbox/store.py`, after the `same_topic` function, add:

```python
def entry_states(conn: psycopg.Connection, ids: list[str]) -> dict[str, str]:
    """The current state of each entry the inbox still has, by id. Unknown ids are left out."""
    if not ids:
        return {}
    rows = conn.execute("SELECT id, state FROM entries WHERE id = ANY(%s)", (list(ids),)).fetchall()
    return {row["id"]: row["state"] for row in rows}
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_topics.py tests/test_store_topics.py -q | tail -1`
Expected: all pass.

Run the whole suite: `.venv/bin/python -m pytest -q | tail -1`
Expected: `212 passed`.

- [ ] **Step 5: Commit**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph
git add modules/inbox/src/agent_inbox/topics.py modules/inbox/src/agent_inbox/store.py \
  modules/inbox/tests/test_topics.py modules/inbox/tests/test_store_topics.py
git commit -m "feat(inbox): read the topic graph from the registry and entry states from the store"
```

---

### Task 6: The Topics page

**Files:**
- Modify: `modules/inbox/src/agent_inbox/web.py`
- Test: `modules/inbox/tests/test_topics_page.py`

- [ ] **Step 1: Write the failing tests**

Create `modules/inbox/tests/test_topics_page.py`:

```python
import os
import threading
from http.client import HTTPConnection

import pytest
from topic_tree_helpers import ev, nesting, node, sess

from agent_inbox import store
from agent_inbox.validate import validate_request
from agent_inbox.web import make_server

CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}
EVIL = '<img src=x onerror="alert(1)">'
os.environ["INBOX_ALLOW_INSECURE"] = "1"


@pytest.fixture
def http(conn):
    server = make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address
    server.shutdown()
    server.server_close()


def get(http, path, headers=None):
    c = HTTPConnection(http[0], http[1], timeout=5)
    c.request("GET", path, headers=headers or {})
    resp = c.getresponse()
    return resp.status, resp.getheader("Set-Cookie"), resp.read().decode()


def serve(fake_registry, *roots):
    fake_registry.replies["topics"] = {"tree": list(roots)}


def ask(conn, title):
    req = validate_request({"title": title, "control": CHOICE}, "ask")
    return store.create_entry(conn, "ask", req, engine="claude", session_id="s-1")


def test_the_topics_tab_follows_history(conn, http, fake_registry):
    serve(fake_registry)
    _, _, feed = get(http, "/")
    assert '<a href="/?history=1">History</a><a href="/topics">Topics</a></nav>' in feed
    status, _, page = get(http, "/topics")
    assert status == 200 and '<a href="/topics" aria-current="page">Topics</a>' in page
    assert fake_registry.calls == [["topics", "--tree", "--events"]]
    assert "No topics yet" in page


def test_the_tree_nests_intents_topics_and_forks(conn, http, fake_registry):
    q = ask(conn, "Which order?")
    check = node("tp-c", "Check windows", sessions=[sess("s-2", role="topic")], events=[ev("topic", 40, session_id="s-2")])
    fork = node("tp-f", "Side quest", sessions=[sess("s-1", role="forked"), sess("s-2", state="live")],
                events=[ev("forked", 50), ev("adopt", 45, session_id="s-2")], children=[check])
    plan = node("tp-p", "Write the plan", sessions=[sess("s-1", role="topic")], children=[fork], events=[
        ev("topic", 90), ev("asked", 80, entry=q["id"], title="Which order?"),
        ev("posted", 70, entry="ib-post", title="Plan written"),
    ])
    later = node("tp-k", "Later idea", status="parked", sessions=[sess("s-1", role="topic")],
                 events=[ev("topic", 30), ev("parked", 20, ref="pk-1")])
    serve(fake_registry, node("tp-r", "Ship the inbox", sessions=[sess("s-1", state="idle")],
                              events=[ev("intent", 100)], children=[plan, later]))
    status, _, page = get(http, "/topics")
    assert status == 200
    tree = nesting(page)
    assert tree.parent == {"tp-r": None, "tp-p": "tp-r", "tp-f": "tp-p", "tp-c": "tp-f", "tp-k": "tp-r"}
    assert f'/e/{q["id"]}' in tree.links["tp-p"] and "/e/ib-post" in tree.links["tp-p"]
    assert "Asked Which order?" in tree.text["tp-p"] and "Forked Side quest" in tree.text["tp-p"]
    assert "agent-tools · claude · 2 open topics · 1 question waiting · 1 parked" in tree.text["tp-r"]
    assert "Idle" in tree.text["tp-r"] and "Live" in tree.text["tp-f"]
    assert "Parked pk-1" in tree.text["tp-k"]
    # The intent and the topic with a question waiting start open; the parked topic starts closed.
    assert '<li class="node intent" data-topic="tp-r" data-depth="0"><details open>' in page
    assert '<li class="node topic" data-topic="tp-p" data-depth="1"><details open>' in page
    assert '<li class="node topic" data-topic="tp-k" data-depth="1"><details>' in page
    assert '<span class="chip blue">1 to answer</span>' in page


def test_intents_needing_you_come_first_and_finished_ones_wait_behind_a_button(conn, http, fake_registry):
    done = node("tp-done", "Done one", sessions=[sess("a")], events=[ev("intent", 5)], children=[
        node("tp-d1", "Finished", status="done", sessions=[sess("a", role="topic")], events=[ev("topic", 4), ev("done", 3)]),
    ])
    busy = node("tp-busy", "Busy", sessions=[sess("b")], events=[ev("intent", 10)], children=[
        node("tp-b1", "Going", sessions=[sess("b", role="topic")], events=[ev("topic", 9)]),
    ])
    stray = node("tp-stray", "Stray", sessions=[sess("c")], events=[ev("intent", 300)], children=[
        node("tp-f", "Never started", status="forked", sessions=[sess("c", role="forked")], events=[ev("forked", 299)]),
    ])
    serve(fake_registry, done, busy, stray)
    _, cookie, page = get(http, "/topics")
    assert cookie is None
    assert page.index('data-topic="tp-stray"') < page.index('data-topic="tp-busy"')
    assert 'data-topic="tp-done"' not in page
    assert '<a class="btn" href="/topics?finished=1">Show finished (1)</a>' in page
    assert "1 fork not picked up" in page and '<span class="chip amber"><i></i>Not picked up</span>' in page


def test_show_finished_is_remembered_in_a_cookie(conn, http, fake_registry):
    serve(fake_registry, node("tp-done", "Done one", sessions=[sess("a")], events=[ev("intent", 5)]))
    _, cookie, page = get(http, "/topics?finished=1")
    assert cookie.startswith("ib_finished=1;") and "SameSite=Lax" in cookie
    assert '<li class="node intent" data-topic="tp-done" data-depth="0"><details>' in page
    assert '<a class="btn" href="/topics?finished=0">Hide finished</a>' in page
    _, cookie, remembered = get(http, "/topics", headers={"Cookie": 'a={"x":1}; ib_finished=1'})
    assert cookie is None and 'data-topic="tp-done"' in remembered
    _, cookie, hidden = get(http, "/topics?finished=0", headers={"Cookie": "ib_finished=1"})
    assert cookie.startswith("ib_finished=0;") and 'data-topic="tp-done"' not in hidden
    assert "Nothing in flight" in hidden


def test_deep_levels_stop_indenting_and_show_their_depth(conn, http, fake_registry):
    chain = None
    for depth in range(5, 0, -1):
        chain = node(f"tp-d{depth}", f"Level {depth}", sessions=[sess("a", role="topic")],
                     events=[ev("topic", 50 - depth)], children=[chain] if chain else [])
    serve(fake_registry, node("tp-d0", "Root", sessions=[sess("a", state="live")], events=[ev("intent", 60)], children=[chain]))
    _, _, page = get(http, "/topics")
    assert '<span class="deep" title="Level 4">↳ 4</span>Level 4' in page
    assert '<span class="deep" title="Level 5">↳ 5</span>Level 5' in page
    assert "↳ 3" not in page
    # Levels 1 to 3 indent; the lists holding levels 4 and 5 keep level 3's indent.
    assert page.count('<ul class="kids">') == 3 and page.count('<ul class="kids flat">') == 2


def test_every_agent_string_is_escaped(conn, http, fake_registry):
    topic = node(EVIL, EVIL, status="parked", sessions=[sess(EVIL, role="topic", agent=EVIL, directory=EVIL)], events=[
        ev("topic", 30), ev("asked", 25, entry=EVIL, title=EVIL), ev("answered", 20, entry=EVIL, value=EVIL, via=EVIL),
        ev("closed", 15, entry=EVIL, state=EVIL), ev("parked", 10, ref=EVIL), ev(EVIL, 5),
    ])
    owners = [sess(EVIL, state="idle", directory=EVIL), sess(EVIL + "2", agent=EVIL)]
    serve(fake_registry, node("tp-r", EVIL, sessions=owners, events=[ev("intent", 40)], children=[topic]))
    _, _, page = get(http, "/topics?finished=1")
    assert "<img" not in page
    assert page.count("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;") >= 8


def test_a_registry_that_doesnt_answer_shows_a_notice(conn, http, fake_registry):
    status, _, page = get(http, "/topics")
    assert status == 200
    assert "<p class=\"notice warn\">The agent registry didn't answer" in page
    assert '<a href="/topics" aria-current="page">Topics</a>' in page


def test_the_inbox_state_decides_what_waits(conn, http, fake_registry):
    done = ask(conn, "Answered already")
    store.answer(conn, done["id"], "a", via="web")
    serve(fake_registry, node("tp-r", "Root", sessions=[sess("s-1", state="live")],
                              events=[ev("intent", 60), ev("asked", 50, entry=done["id"], title="Answered already")]))
    _, _, page = get(http, "/topics")
    assert "question waiting" not in page and "to answer</span>" not in page


def test_resume_shows_only_for_sessions_that_are_not_live(conn, http, fake_registry):
    serve(fake_registry, node("tp-r", "Root", sessions=[sess("live-1", state="live"), sess("idle-1", state="idle")],
                              events=[ev("intent", 60)]))
    _, _, page = get(http, "/topics")
    assert '<code class="cmd">cd /x/agent-tools &amp;&amp; claude --resume idle-1</code>' in page
    assert "--resume live-1" not in page


def test_opening_a_branch_offers_the_reload_instead_of_folding_it_back(conn, http, fake_registry):
    serve(fake_registry)
    _, _, page = get(http, "/topics")
    assert 'document.addEventListener("toggle", (e) => { if (e.target.closest(".tree")) dirty = true; }, true);' in page
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph/modules/inbox && .venv/bin/python -m pytest tests/test_topics_page.py -q`
Expected: FAIL. The feed has no Topics tab, and `/topics` is `404 not found`.

- [ ] **Step 3: Imports and the cookie constant**

In `modules/inbox/src/agent_inbox/web.py`, change `from agent_inbox import db, grouping, store` to:

```python
from agent_inbox import db, grouping, store, topic_graph, topics
```

After `GROUP_MAX_AGE = 365 * 24 * 3600`, add:

```python
FINISHED_COOKIE = "ib_finished"
```

- [ ] **Step 4: The outline's CSS**

In `_HEAD`, insert this block just before the line that starts `#stale {{ position: fixed;`. The braces are doubled because `_HEAD` goes through `.format`:

```css
.tree {{ list-style: none; margin: 0 -16px; padding: 0; }}
.tree ul, .tree ol {{ list-style: none; margin: 0; padding: 0; }}
.tree > .node {{ border-bottom: 1px solid var(--line); }}
.node summary {{ display: grid; grid-template-columns: 20px minmax(0, 1fr) auto; grid-template-areas: "tw title time" ". meta meta" ". chips chips";
  column-gap: 8px; row-gap: 2px; align-items: center; min-height: 56px; padding: 10px 16px; list-style: none; cursor: pointer; }}
.node summary::-webkit-details-marker {{ display: none; }}
.node summary:hover {{ background: var(--surf); }}
.node .tw {{ grid-area: tw; width: 18px; height: 18px; color: var(--mute); transition: transform 120ms ease-out; }}
.node details[open] > summary .tw {{ transform: rotate(90deg); }}
.node summary b {{ grid-area: title; min-width: 0; font-weight: 600; overflow: hidden;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }}
.node.topic > details > summary {{ min-height: 48px; }}
.node.topic > details > summary b {{ font-weight: 550; }}
.node summary time {{ grid-area: time; color: var(--mute); font-size: 13px; font-variant-numeric: tabular-nums; white-space: nowrap; }}
.node summary small {{ grid-area: meta; min-width: 0; color: var(--mute); font-size: 14px; }}
.node summary .chips {{ grid-area: chips; display: flex; flex-wrap: wrap; gap: 6px; margin-top: 2px; }}
.node summary .chips:empty {{ display: none; }}
.deep {{ margin-right: 6px; color: var(--mute); font-size: 13px; font-weight: 600; }}
.nbody {{ padding-bottom: 8px; }}
.tree .kids {{ padding-left: 16px; }}
.tree .kids.flat {{ padding-left: 0; }}
.tree .sess {{ margin: 0 16px 8px 44px; }}
.sess li {{ display: flex; flex-wrap: wrap; align-items: center; gap: 6px 8px; padding: 4px 0; color: var(--mute); font-size: 14px; }}
.cmd {{ flex: 1 1 100%; min-width: 0; overflow-x: auto; padding: 8px 10px; border-radius: 8px; background: var(--surf); color: var(--ink);
  font: 13px ui-monospace, SFMono-Regular, Menlo, monospace; white-space: nowrap; -webkit-user-select: all; user-select: all; }}
.tree .tl {{ margin: 0 16px 8px 44px; border-left: 2px solid var(--line); }}
.tl li {{ display: flex; align-items: baseline; justify-content: space-between; gap: 12px; min-height: 32px; padding: 6px 0 6px 12px; font-size: 14px; }}
.tl li.go {{ padding-block: 0; }}
.tl li > span, .tl a > span {{ min-width: 0; }}
.tl a {{ flex: 1; display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 44px; color: inherit; text-decoration: none; }}
.tl a .tx {{ color: var(--link); }}
.tl a:hover .tx {{ text-decoration: underline; }}
.tl b {{ font-weight: 600; }}
.tl .via {{ color: var(--mute); }}
.tl time {{ flex: none; color: var(--mute); font-size: 13px; font-variant-numeric: tabular-nums; }}
.more {{ margin: 16px 0 0; }}
.more .btn {{ color: var(--ink); }}
@media (min-width: 760px) {{ .tree {{ margin: 0; border-top: 1px solid var(--line); }} }}
```

In the `@media (prefers-reduced-motion: reduce)` block of `_HEAD`, after the line `  .landed .ticks .t2, .answered.landed {{ animation: none; }}`, add:

```css
  .node .tw {{ transition: none; }}
```

- [ ] **Step 5: The toggle-aware reload**

In `_SCRIPT`, after the line `document.addEventListener("input", () => { dirty = true; });`, add:

```js
// Opening or closing a branch of the Topics tree counts as touching the page: a reload would fold it back.
document.addEventListener("toggle", (e) => { if (e.target.closest(".tree")) dirty = true; }, true);
```

`toggle` doesn't bubble, so the listener is on the capture phase.

- [ ] **Step 6: One cookie reader for both cookies**

Replace the whole `_group_choice` function with:

```python
def _cookie(header: str | None, name: str) -> str | None:
    """One cookie's value, by hand: http.cookies gives up on every cookie after one that holds a space or JSON."""
    for part in (header or "").split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            return value
    return None


def _group_choice(qs: dict, cookie_header: str | None) -> tuple[str, str | None]:
    """The Group by mode and, when this request picked one, the Set-Cookie that remembers it.

    A cookie rather than the URL, so the choice survives the live reload, the tab links and the phone."""
    asked = _query_value(qs, "group")
    if asked in grouping.GROUPS:
        return asked, f"{GROUP_COOKIE}={asked}; Path=/; Max-Age={GROUP_MAX_AGE}; SameSite=Lax"
    value = _cookie(cookie_header, GROUP_COOKIE)
    return (value if value in grouping.GROUPS else "none"), None


def _finished_choice(qs: dict, cookie_header: str | None) -> tuple[bool, str | None]:
    """Whether the Topics page shows finished intents and, when this request set it, the Set-Cookie that remembers it."""
    asked = _query_value(qs, "finished")
    if asked in ("0", "1"):
        return asked == "1", f"{FINISHED_COOKIE}={asked}; Path=/; Max-Age={GROUP_MAX_AGE}; SameSite=Lax"
    return _cookie(cookie_header, FINISHED_COOKIE) == "1", None
```

- [ ] **Step 7: The fifth tab**

Replace the `TABS` assignment with:

```python
TABS = (("Active", "/", {}), ('<span class="lg">Needs answer</span><span class="sm">To answer</span>', "/?kind=ask&state=open", {"kind": "ask", "state": "open"}),
        ("Info", "/?kind=post", {"kind": "post"}), ("History", "/?history=1", {"history": "1"}), ("Topics", "/topics", {}))
```

After the `_tab` function, add:

```python
def _tabs(home: str) -> str:
    """The view tabs, with the one at home marked current."""
    mark = ' aria-current="page"'
    tabs = "".join(f'<a href="{href}"{mark if href == home else ""}>{label}</a>' for label, href, _ in TABS)
    return f'<nav class="tabs" aria-label="Views">{tabs}</nav>'
```

In `_nav`, replace these three lines. The first one anchors the edit, because `_tabs` now holds the other two as well:

```python
    home, want = _tab(current)
    mark = ' aria-current="page"'
    tabs = "".join(f'<a href="{href}"{mark if href == home else ""}>{label}</a>' for label, href, _ in TABS)
```

with:

```python
    home, want = _tab(current)
```

and change its last line from `return f'<nav class="tabs" aria-label="Views">{tabs}</nav>', filters` to:

```python
    return _tabs(home), filters
```

Five tabs don't fit a 390 px phone at today's spacing. A dry run of this plan measured the Topics tab ending at 401 px. In `_HEAD`, replace:

```css
@media (max-width: 479px) {{ .tabs {{ gap: 6px; }} .tabs a {{ padding: 0 12px; }} .tabs .lg {{ display: none; }} .tabs .sm {{ display: inline; }} }}
```

with:

```css
@media (max-width: 479px) {{ .tabs {{ gap: 4px; }} .tabs a {{ padding: 0 10px; }} .tabs .lg {{ display: none; }} .tabs .sm {{ display: inline; }} }}
```

That measured 373 px, which is inside the 374 px left before the 16 px right-edge fade. Task 8 re-measures it.

- [ ] **Step 8: The outline**

Insert this just before `def open_count(conn) -> int:`:

```python
TOPIC_CHIP = {"open": ("Open", "blue"), "done": ("Done", "grey"), "parked": ("Parked", "grey"), "forked": ("Not picked up", "amber")}
SESSION_CHIP = {"live": ("Live", "green"), "idle": ("Idle", "grey"), "ended": ("Ended", "grey"), "unknown": ("Unknown", "grey")}
LINE_LABEL = {
    "intent": "Intent set", "adopt": "Picked up", "topic": "Opened", "forked": "Forked off", "fork": "Forked",
    "asked": "Asked", "posted": "Posted", "answered": "Answered", "closed": "Closed", "done": "Done", "parked": "Parked",
}
_TWISTY = (
    '<svg class="tw" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true"><path d="M7.5 4.5 13 10l-5.5 5.5"/></svg>'
)


def _pill(label: str, tone: str) -> str:
    """A chip in one tone. Green, amber and red report a state, so they carry the dot."""
    dot = "<i></i>" if tone in ("green", "amber", "red") else ""
    return f'<span class="chip {tone}">{dot}{_esc(label)}</span>'


def _many(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _counts(view: topic_graph.View) -> str:
    """What's open under an intent, e.g. "2 open topics · 1 question waiting"."""
    bits = []
    if view.open_topics():
        bits.append(_many(view.open_topics(), "open topic"))
    if view.questions():
        bits.append(_many(view.questions(), "question") + " waiting")
    if view.stray_forks():
        bits.append(_many(view.stray_forks(), "fork") + " not picked up")
    if view.parked():
        bits.append(f"{view.parked()} parked")
    return " · ".join(bits)


def _owners(view: topic_graph.View) -> str:
    """The sessions that hold this intent: engine, short id, state, and how to resume one that isn't live."""
    items = []
    for session in view.owners:
        command = None if session["live"] else topic_graph.resume_command(session)
        code = f'<code class="cmd">{_esc(command)}</code>' if command else ""
        items.append(
            f'<li><span>{_esc(session["agent_type"])} · <span class="id" title="{_esc(session["session_id"])}">'
            f'{_esc(session["session_id"][:8])}</span></span>{_pill(*SESSION_CHIP[session["state"]])}{code}</li>'
        )
    return f'<ul class="sess" aria-label="Sessions">{"".join(items)}</ul>' if items else ""


def _timeline(view: topic_graph.View) -> str:
    """The node's events in order. A line about an inbox entry links to its page."""
    items = []
    for line in view.lines:
        label = _esc(LINE_LABEL.get(line.event, line.event.capitalize()))
        text = f' <span class="tx">{_esc(line.text)}</span>' if line.text else ""
        via = f' <span class="via">via {_esc(VIA.get(line.via, line.via))}</span>' if line.via else ""
        inner = f"<span><b>{label}</b>{text}{via}</span><time>{_esc(_clock(line.at))}</time>"
        if line.entry:
            items.append(f'<li class="go"><a href="/e/{_esc(quote(line.entry, safe=""))}">{inner}</a></li>')
        else:
            items.append(f"<li>{inner}</li>")
    return f'<ol class="tl" aria-label="Timeline">{"".join(items)}</ol>' if items else ""


def _tree_node(view: topic_graph.View) -> str:
    """One intent or topic: a summary row that opens to its sessions, its timeline and the nodes under it."""
    intent = view.kind == "intent"
    deep = (
        f'<span class="deep" title="Level {view.depth}">↳ {view.depth}</span>'
        if view.depth > topic_graph.MAX_INDENT else ""
    )
    if intent:
        owner = view.owners[0] if view.owners else None
        if view.status == "forked":
            chips = _pill(*TOPIC_CHIP["forked"])
        else:
            chips = _pill(*SESSION_CHIP[owner["state"]]) if owner else ""
        project = Path(owner["directory"]).name if owner and owner["directory"] else ""
        bits = [project, owner["agent_type"] if owner else "", _counts(view)]
        waiting = view.questions()
        opened = not view.finished()
    else:
        chips = _pill(*TOPIC_CHIP[view.status])
        bits = []
        waiting = len(view.waiting)
        opened = view.needs_you()
    if waiting:
        chips += _pill(f"{waiting} to answer", "blue")
    meta = " · ".join(_esc(bit) for bit in bits if bit)
    summary = (
        f"<summary>{_TWISTY}<b>{deep}{_esc(view.title)}</b><time>{_esc(_ago(view.opened_at))}</time>"
        + (f"<small>{meta}</small>" if meta else "")
        + f'<span class="chips">{chips}</span></summary>'
    )
    inside = (_owners(view) if intent else "") + _timeline(view)
    if view.children:
        flat = " flat" if view.depth + 1 > topic_graph.MAX_INDENT else ""
        inside += f'<ul class="kids{flat}">' + "".join(_tree_node(child) for child in view.children) + "</ul>"
    return (
        f'<li class="node {view.kind}" data-topic="{_esc(view.id)}" data-depth="{view.depth}">'
        f'<details{" open" if opened else ""}>{summary}<div class="nbody">{inside}</div></details></li>'
    )


def _topics_page(views: list[topic_graph.View] | None, finished: bool, waiting: int | None = None) -> str:
    """The Topics tab: every intent and what's under it, as an outline. views is None when the registry didn't answer."""
    if views is None:
        body = '<p class="notice warn">The agent registry didn\'t answer, so the topics can\'t be shown. Reload to try again.</p>'
    else:
        shown, done = topic_graph.order(views)
        listed = shown + done if finished else shown
        body = ('<ul class="tree">' + "".join(_tree_node(view) for view in listed) + "</ul>") if listed else ""
        if done:
            href, label = ("/topics?finished=0", "Hide finished") if finished else ("/topics?finished=1", f"Show finished ({len(done)})")
            body += f'<p class="more"><a class="btn" href="{href}">{label}</a></p>'
        if not listed:
            empty = "Nothing in flight</b>Every intent here is finished." if done else "No topics yet</b>Sessions that set an intent show up here."
            body = f'<p class="empty"><b>{empty}</p>' + body
    return (
        _HEAD.format(title="Topics", body="")
        + _bar("<h1>Inbox</h1>", waiting)
        + "<main>"
        + _tabs("/topics")
        + body
        + "</main>"
        + _SCRIPT
    )
```

- [ ] **Step 9: The route**

In `InboxHandler._dispatch`, insert this block just before the line `match = re.fullmatch(r"/e/([^/]+)", path)`:

```python
        if method == "GET" and path == "/topics":
            finished, cookie = _finished_choice(qs, self.headers.get("Cookie"))
            # The registry call runs before the store connection opens, so a slow registry never holds one.
            tree = topics.graph()
            with db.connect() as conn:
                views = None
                if tree is not None:
                    views = topic_graph.build(tree, store.entry_states(conn, topic_graph.asked_entries(tree)))
                self._html(200, _topics_page(views, finished, waiting=open_count(conn)), cookie=cookie)
            return
```

- [ ] **Step 10: Run the tests**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph/modules/inbox && .venv/bin/python -m pytest tests/test_topics_page.py -q`
Expected: `10 passed`.

Run the whole suite, which includes the Group by cookie tests that now go through `_cookie`: `.venv/bin/python -m pytest -q | tail -1`
Expected: `222 passed`.

- [ ] **Step 11: Read the rendered page once**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph/modules/inbox
.venv/bin/python -m pytest tests/test_topics_page.py -q -k nests -s 2>/dev/null | tail -1
```

Then read `_tree_node`'s output for one intent by eye. Add `print(page)` to `test_the_tree_nests_intents_topics_and_forks` temporarily, run it with `-s`, read the HTML, and remove the print. Check:
- every `<li>` closes;
- each `<details>` holds exactly one `<summary>`;
- no agent text sits outside an escaped span.

- [ ] **Step 12: Commit**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph
git add modules/inbox/src/agent_inbox/web.py modules/inbox/tests/test_topics_page.py
git commit -m "feat(inbox): Topics tab with every intent, topic and fork as an outline"
```

---

### Task 7: Black-box check and page latency

**Files:**
- Modify: `modules/inbox/tests/blackbox/conftest.py`
- Create: `modules/inbox/tests/blackbox/test_topics_page.py`

- [ ] **Step 1: A web fixture in the harness**

In `modules/inbox/tests/blackbox/conftest.py`, add `import urllib.request` after `import time`, then append:

```python
@pytest.fixture
def web(box):
    """The inbox's web handler alone, on a free port, with the box's registry and database.
    Not `agt inbox serve`: that also sweeps, which wakes sessions."""
    port = _free_port()
    env = dict(box.env, INBOX_HTTP_PORT=str(port), INBOX_ALLOW_INSECURE="1", PYTHONPATH=str(INBOX / "src"))
    log_path = box.root / "web.log"
    log = open(log_path, "w")
    proc = subprocess.Popen(
        [str(INBOX / ".venv" / "bin" / "python"), "-c", "from agent_inbox.web import make_server; make_server().serve_forever()"],
        env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 10
    while True:
        try:
            urllib.request.urlopen(base + "/", timeout=2).close()
            break
        except OSError:
            if proc.poll() is not None or time.monotonic() > deadline:
                proc.kill()
                log.close()
                pytest.fail(f"web handler didn't start: {log_path.read_text()}")
            time.sleep(0.1)
    yield base
    proc.terminate()
    proc.wait(timeout=5)
    log.close()
```

- [ ] **Step 2: Write the test**

Create `modules/inbox/tests/blackbox/test_topics_page.py`:

```python
"""The Topics page against a temp registry: agt writes the logs, the web handler serves the page."""
import json
import re
import urllib.request
from datetime import datetime, timezone

from topic_tree_helpers import nesting

S1 = ["--type", "claude", "--session-id", "s1"]
S2 = ["--type", "claude", "--session-id", "s2"]
CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}


def page(base, path="/topics"):
    with urllib.request.urlopen(base + path, timeout=10) as resp:
        assert resp.status == 200
        return resp.read().decode()


def live_row(box, session_id, directory):
    """A registry row that pinged just now, in the registry's own file format."""
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "registry_id": f"r-{session_id}", "session_id": session_id, "agent_type": "claude", "directory": directory,
        "parent_session_id": None, "status": "working", "summary": "", "issue": None, "pr": None, "branch": None,
        "goflow_timer_id": None, "registered_at": now, "last_ping": now, "updated_at": now,
    }
    path = box.data / "registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "sessions": [row]}))


def test_the_topics_page_holds_each_piece_in_place(box, web):
    intent = box.agt_json("registry", "intent", "Ship the inbox", *S1)["topic"]["id"]
    plan = box.agt_json("registry", "topic", "Write the plan", *S1)["topic"]["id"]
    asked = box.agt("inbox", "ask", "--engine", "claude", "--session-id", "s1",
                    stdin=json.dumps({"title": "Which order?", "control": CHOICE}))
    assert asked.returncode == 0, asked.stderr
    entry = json.loads(asked.stdout)["entry"]
    box.agt_json("inbox", "answer", entry, "--value", "b", "--via", "chat")
    fork = box.agt_json("registry", "fork", "Side quest", "--side", "--backend", "none", *S1, stdin="# Side quest\n")["topic"]["id"]
    box.agt_json("registry", "intent", "--adopt", fork, *S2)
    check = box.agt_json("registry", "topic", "Check the windows", *S2)["topic"]["id"]
    later = box.agt_json("registry", "topic", "Later idea", *S1)["topic"]["id"]
    box.agt_json("registry", "topic", "--park", "--ref", "pk-1", *S1)
    live_row(box, "s2", str(box.root / "agent-tools"))

    html = page(web)
    tree = nesting(html)
    assert tree.parent == {intent: None, plan: intent, fork: plan, check: fork, later: intent}
    assert "Asked Which order?" in tree.text[plan] and "Answered b via the chat" in tree.text[plan]
    assert f"/e/{entry}" in tree.links[plan]
    assert "Forked Side quest" in tree.text[plan]
    assert "Parked pk-1" in tree.text[later]
    assert "Live" in tree.text[fork] and "Ended" in tree.text[intent]
    assert "claude --resume s1" in tree.text[intent] and "--resume s2" not in html
    assert not re.search(r"\d+ to answer", html)
    # The page read the logs through the registry's cache.
    assert (box.data / "topics" / ".parsed.json").exists()
```

- [ ] **Step 3: Run the black-box suite**

Run: `cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph/modules/inbox && .venv/bin/python -m pytest tests/blackbox -q`
Expected: `8 passed`. If the new test sees the registry notice in place of the tree, read `web.log` in the test's tmp dir: the server's stderr names the failing registry call. Check that `AGENT_INBOX_AGT` and `AGENT_REGISTRY_PATH` reach the server.

Run the unit suite too, to confirm `tests/blackbox` stays out of it: `.venv/bin/python -m pytest -q | tail -1`
Expected: `222 passed`.

- [ ] **Step 4: Measure the page with a copy of the real logs**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph/modules/inbox
rm -rf tmp/latency && mkdir -p tmp/latency
cp -R ~/.local/share/agent-registry/topics tmp/latency/topics
cp ~/.local/share/agent-registry/registry.json ~/.local/share/agent-registry/archive.jsonl tmp/latency/
rm -f tmp/latency/topics/.parsed.json
createdb -h localhost -p 5433 agent_inbox_test_latency
```

Start the web handler with the Bash tool's `run_in_background`:

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph/modules/inbox
AGENT_INBOX_DSN="host=localhost port=5433 dbname=agent_inbox_test_latency" AGENT_INBOX_TELEGRAM_TO= \
  AGENT_REGISTRY_PATH="$PWD/tmp/latency/registry.json" \
  AGENT_INBOX_AGT=/Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph/agt/agt \
  INBOX_HTTP_PORT=8899 INBOX_ALLOW_INSECURE=1 PYTHONPATH=src \
  .venv/bin/python -c 'from agent_inbox.web import make_server; make_server().serve_forever()'
```

Then:

```bash
curl --retry 10 --retry-connrefused --retry-delay 1 -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8899/
for i in 1 2 3 4 5 6; do curl -s -o /dev/null -w '%{time_total}\n' http://127.0.0.1:8899/topics; done
curl -s http://127.0.0.1:8899/topics | grep -o 'class="node intent"' | wc -l
test ! -e ~/.local/share/agent-registry/topics/.parsed.json && echo "live topics dir untouched"
lsof -ti tcp:8899 | xargs kill
dropdb -h localhost -p 5433 agent_inbox_test_latency
```

Expected:
- `200`;
- six times: the first builds the registry cache, and runs 2 to 6 are warm;
- a count of intents greater than 0 (the copy's sessions);
- `live topics dir untouched`.

Write down the warm median, which goes into the Task 9 docs and the Task 11 report. If it is above 0.5 s, stop and report before going on.

- [ ] **Step 5: Commit**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph
git add modules/inbox/tests/blackbox/conftest.py modules/inbox/tests/blackbox/test_topics_page.py
git commit -m "test(inbox): black-box Topics page against a temp registry"
```

---

### Task 8: Visual check

**Files:**
- Modify: `modules/inbox/tests/visual/cdpshot.mjs`, `modules/inbox/tests/visual/shots.sh`, `modules/inbox/tests/visual/README.md`
- Create: `modules/inbox/tests/visual/seed_registry.py`

- [ ] **Step 1: Run the probe before measuring**

Today `cdpshot.mjs` measures the page, then runs `PROBE`. A probe that opens every branch would then be cropped to the closed height, and its sideways scroll would never be checked. In `modules/inbox/tests/visual/cdpshot.mjs`, replace:

```js
const info = JSON.parse(await evaluate(
	"JSON.stringify({w: innerWidth, sw: document.documentElement.scrollWidth, h: document.documentElement.scrollHeight,"
	+ " dark: matchMedia('(prefers-color-scheme: dark)').matches})",
));
if (process.env.PROBE) console.log("PROBE", JSON.stringify(await evaluate(process.env.PROBE)));
```

with:

```js
// The probe runs first, so a page it opens up is measured and checked at its opened size.
if (process.env.PROBE) {
	console.log("PROBE", JSON.stringify(await evaluate(process.env.PROBE)));
	await sleep(200);
}
const info = JSON.parse(await evaluate(
	"JSON.stringify({w: innerWidth, sw: document.documentElement.scrollWidth, h: document.documentElement.scrollHeight,"
	+ " dark: matchMedia('(prefers-color-scheme: dark)').matches})",
));
```

- [ ] **Step 2: Write the registry seed**

Create `modules/inbox/tests/visual/seed_registry.py`:

```python
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
```

Here is what this tree should render as, which Step 6 checks.

Shown, in this order:
1. "Topic awareness for AI sessions": Live, "2 to answer", "agent-tools · claude · 3 open topics · 2 questions waiting". Its fork chain runs to level 5, so "Retry the Herdr pane split" shows "↳ 4" and "Read the pane ids…" shows "↳ 5".
2. "Lindris production page: generated files": Idle, "1 fork not picked up".
3. The `<img …>` intent, shown as literal text, with "1 parked".

Behind "Show finished (4)": Inbox restyle and three older intents.

- [ ] **Step 3: Extend the runner**

In `modules/inbox/tests/visual/shots.sh`:

1. Replace the header's second comment line, `# The inbox's visual check: seed a scratch test DB, serve it web-only, take the shots, stop.`, with:

```bash
# The inbox's visual check: seed a scratch test DB and a scratch registry, serve them web-only, take the shots, stop.
```

2. After the line `INBOX="$(cd "$HERE/../.." && pwd)"`, add:

```bash
REPO="$(cd "$INBOX/../.." && pwd)"
```

3. After the line that runs `seed_topics.py` (`... tests/visual/seed_topics.py > "$WORK/seed.json"`), add:

```bash
# The Topics page reads the registry live; give it a scratch one, never the real one.
REG="$WORK/registry"
.venv/bin/python tests/visual/seed_registry.py "$REG" "$WORK/seed.json"
```

4. Replace the server start line:

```bash
AGENT_INBOX_DSN="$DSN" AGENT_INBOX_TELEGRAM_TO= INBOX_HTTP_PORT="$PORT" INBOX_ALLOW_INSECURE=1 PYTHONPATH=src \
```

with:

```bash
AGENT_INBOX_DSN="$DSN" AGENT_INBOX_TELEGRAM_TO= INBOX_HTTP_PORT="$PORT" INBOX_ALLOW_INSECURE=1 PYTHONPATH=src \
	AGENT_REGISTRY_PATH="$REG/registry.json" AGENT_INBOX_AGT="$REPO/agt/agt" \
```

5. After the two `shot filter-open-390-…` lines, add:

```bash
# Topics: the last tab must end inside a 390px screen; the open shots expand every branch.
TABS='(() => { const a = document.querySelector(".tabs").lastElementChild; return a.textContent + " ends at " + Math.round(a.getBoundingClientRect().right) + "px of " + innerWidth + "px"; })()'
EXPAND='(() => { const all = document.querySelectorAll(".tree details"); all.forEach((d) => { d.open = true; }); return all.length + " branches open"; })()'
for w in 390 1280; do
	shot "topics-$w" /topics "$w" light "$TABS"
	shot "topics-$w-dark" /topics "$w" dark
	shot "topics-open-$w" "/topics?finished=1" "$w" light "$EXPAND"
done
shot topics-open-390-dark "/topics?finished=1" 390 dark "$EXPAND"
```

- [ ] **Step 4: Update the visual README**

In `modules/inbox/tests/visual/README.md`:

1. Replace the title and first paragraph with:

```markdown
# Visual check: feed, entry page and Topics

Screenshots of the inbox's feed (in each Group by mode), its entry page and its Topics tab, at phone width (390px) and desktop width (1280px), in light and dark. The unit tests assert the HTML; this check is how you see the layout: the context line, the grouped sections, the breadcrumb, "On this topic", the filter panel and the topic outline.
```

2. In the Files table, after the `seed_topics.py` row, add:

```markdown
| `seed_registry.py` | Writes a scratch agent registry (topic logs, `registry.json`, `archive.jsonl`) into the runner's temp dir for the Topics shots, with notes that link to the seeded entries. It refuses the live registry directory. |
```

3. Replace `It never touches the agent registry: the seed writes topic paths into the DB directly.` with:

```markdown
It never touches the live agent registry. The feed's topic paths are written into the DB directly. The Topics page reads a scratch registry that `seed_registry.py` writes in the runner's temp dir, through this checkout's `agt` (`AGENT_INBOX_AGT`). `PROBE` runs before the page is measured, so a probe that opens branches is measured and checked at the opened size.
```

4. At the end of the "What to look for" table, add:

```markdown
| `topics-390`, `topics-1280` | Tabs end with Topics, current; at 390 the PROBE line says it ends inside the viewport. "Topic awareness for AI sessions" comes first with a green Live chip, a blue "2 to answer" and "agent-tools · claude · 3 open topics · 2 questions waiting"; then "Lindris production page…" (grey Idle, "1 fork not picked up", and its amber "Not picked up" fork inside); then the literal `<img src=x onerror="alert(1)">` intent with "1 parked". The open branches show timelines on a grey rail and the nested fork indented. "Show finished (4)" closes the list. Rows are at least 48px; nothing runs past the right edge. |
| `topics-390-dark`, `topics-1280-dark` | Same layout on the dark ground; muted meta, the rail and the chips stay readable. |
| `topics-open-390`, `topics-open-1280`, `topics-open-390-dark` | Every branch open. "Retry the Herdr pane split" shows `↳ 4` and "Read the pane ids…" `↳ 5`, at the same indent as level 3. Timeline lines for entries are 44px links in link blue. Each idle or ended session shows its resume command in a grey mono box that scrolls inside itself, not the page. "Inbox restyle" and the three older intents come last, closed, with "Hide finished" under them. |
```

- [ ] **Step 5: Take the shots**

```bash
createdb -h localhost -p 5433 agent_inbox_test_visual
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph/modules/inbox
AGENT_INBOX_DSN="host=localhost port=5433 dbname=agent_inbox_test_visual" tests/visual/shots.sh tmp/shots 8897
dropdb -h localhost -p 5433 agent_inbox_test_visual
```

Expected: 19 PNGs (the 12 from before plus 7 Topics shots), one line per shot with no `FAIL`, a `PROBE` line for `topics-390` naming where Topics ends, and exit 0.

- [ ] **Step 6: Look at every screenshot**

Open each PNG with the Read tool and check it against the README's "What to look for" rows, the new Topics rows and the old ones. The feed shots changed too, because every page now has five tabs. Write down what each shot shows, and don't tick a row you didn't look at.

The `topics-390` PROBE line must say Topics ends at or before 374px (the 390px viewport less the 16px fade). The dry run of this plan measured 373px with Task 6's tightened tabs. If it ends later, the fifth tab is cut on Tiago's phone. Stop and report the number rather than shrinking the tabs further on your own: the next step down (shorter labels, or one fewer tab on a phone) is his call.

- [ ] **Step 7: Fix what the shots show, then re-check the whole set**

For each defect:
1. Fix it in `web.py`, and add a test when the defect can be asserted in HTML.
2. Run `.venv/bin/python -m pytest -q` with no screenshot server running, since the tests drop tables.
3. Run `shots.sh` again and look at all 19 shots again, not just the one that was wrong.
4. Commit each fix on its own: `fix(inbox): <what the shot showed>`.

- [ ] **Step 8: Commit the check**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph
git add modules/inbox/tests/visual/cdpshot.mjs modules/inbox/tests/visual/shots.sh \
  modules/inbox/tests/visual/README.md modules/inbox/tests/visual/seed_registry.py
git commit -m "test(inbox): Topics screenshots at 390 and 1280, light and dark, over a scratch registry"
```

The PNGs stay in the ignored `tmp/shots/`. Keep them for the Task 11 report.

---

### Task 9: Docs

**Files:**
- Modify: `modules/inbox/README.md`, `modules/inbox/DESIGN.md`, `modules/inbox/PRODUCT.md`, `modules/registry/README.md`, `modules/inbox/docs/superpowers/specs/2026-11-25-topic-graph-design.md`

- [ ] **Step 1: Inbox README**

In `modules/inbox/README.md`, in `## Topics`, change `It's a snapshot taken when the entry is created, so pages never call the registry, and a topic renamed later keeps its old name here.` to `It's a snapshot taken when the entry is created, so the feed and entry pages never call the registry, and a topic renamed later keeps its old name here.`

Insert this paragraph before the paragraph that starts `` `AGENT_INBOX_AGT` overrides``:

```markdown
The **Topics** tab (`/topics`) is the one page that reads the registry live. Each load runs `agt registry topics --tree --events` with the same 2 s timeout and renders every intent as an outline: its topics in the order they were opened, forks nested as their own intents under the topic they forked from, each topic's timeline (opened, asked, answered, closed, forked, parked, done, with links to the entries), and each session's state, with a resume command for one that isn't live. Intents with a question waiting or a fork no session picked up come first, then intents with open topics, then the rest, most recent activity first. Finished intents (nothing waiting, no open or parked topic, no live session) wait behind "Show finished", which the `ib_finished` cookie remembers. Whether a question still waits comes from the inbox's own entry state, in one query per load, because the log's notes are best effort. A registry that fails or times out shows a notice in place of the outline. The page is read-only apart from its links.
```

End that paragraph with one sentence giving Task 7 Step 4's warm median, in this form: `On this machine, with the real logs of 2026-11-25, a load took 0.12 s (median of five warm loads).` Use the number you measured.

In the same file, change `The visual check (screenshots of the feed and entry page, phone and desktop, light and dark)` to `The visual check (screenshots of the feed, the entry page and the Topics tab, phone and desktop, light and dark)`.

- [ ] **Step 2: DESIGN.md**

In `modules/inbox/DESIGN.md`:

1. In the Tabs component, change `History (answered, delivered, read and closed entries).` to `History (answered, delivered, read and closed entries) and Topics (the topic outline, below).`
2. In Layout, change `The tabs sit on one row. Below 480px "Needs answer" shortens to "To answer" and the gap and padding tighten (again below 380px), so all four fit down to 320px; anything narrower scrolls sideways under a right-edge fade rather than wrapping.` to `The five tabs sit on one row. Below 480px "Needs answer" shortens to "To answer" and the gap and padding tighten (again below 380px), so all five fit at 390px; a narrower screen scrolls them sideways under a right-edge fade rather than wrapping.`
3. Insert this section just before `### Delivery ticks`:

```markdown
### Topic outline
- **Where:** the Topics tab. One row per intent, read live from the agent registry on each load. Read-only apart from links.
- **Intent row:** a `<details>` summary, 56px minimum: an 18px Grey Meta chevron that turns down when open, the 600-weight title (two lines, then an ellipsis), the age right-aligned in 13px tabular Grey Meta, a 14px Grey Meta line "project · engine · counts" (counts like "2 open topics · 1 question waiting"), and chips: the owning session's state (green Live with its dot, grey Idle or Ended), or amber "Not picked up" for a fork no session adopted, plus a blue "N to answer" when questions wait. A hairline separates intents; on a phone the list bleeds to the screen edges like the feed.
- **Topic row:** the same grid at 48px, with a 550-weight title and its status chip (blue Open, grey Done, grey Parked).
- **Order:** intents with a question waiting or a fork not picked up come first, then those with open topics, then the rest, each most recent activity first. Finished intents (nothing waiting, no open or parked topic, no live session) are left out behind a secondary "Show finished (N)" button at the end. Once shown, they come last and start closed. The `ib_finished` cookie keeps the choice.
- **Open by default:** intents that aren't finished, and topics with something waiting under them.
- **Inside:** an intent first lists its sessions: engine, short mono id, state chip and, for a session that isn't live, a 13px mono resume command on Cool Surface that one tap selects whole and that scrolls inside itself. Then come its timeline and its children. A timeline is a 2px Hairline rail, 44px in from the row's edge, of 14px lines ("Label text via …") with a 13px clock on the right. Lines about an inbox entry are 44px links whose text is Link Blue.
- **Nesting:** each level indents 16px, up to three levels. Deeper levels keep the third level's indent and put a 13px/600 Grey Meta "↳ N" before the title.
- **Live reload:** the page reloads on store changes like the feed until a branch is opened or closed; after that it offers the stale toast instead.
```

- [ ] **Step 3: PRODUCT.md**

In `modules/inbox/PRODUCT.md`, change `a follow-up box, and the thread of follow-ups and replies).` to `a follow-up box, and the thread of follow-ups and replies), and the Topics page (every session's intent with its topics, forks, questions and sessions, as a read-only outline read live from the agent registry).`

- [ ] **Step 4: Registry README**

In `modules/registry/README.md`, change the line `agent-registry topics [--session S | --open | --tree]` to:

```bash
agent-registry topics [--session S | --open | --tree [--events]]
```

After the paragraph that starts `` `topics` skips malformed events``, add:

```markdown
`topics --tree --events` adds each node's `events` (every log's events for that topic, oldest first, each with the `agent_type` and `session_id` of the log it came from, without its `topic`) and gives each `sessions` entry `live`, `state` and `directory`. `state` is `live` for a row that pinged within the stale window, `idle` for an older row, `ended` for a session with no row, and `unknown` when `registry.json` can't be read. `directory` comes from the row, or for an ended session from its latest `archive.jsonl` record. Liveness is read from `registry.json` in the CLI process, the same file the daemon's `list` reads, so it makes no daemon call; the archive is read only when some session has no row. `--tree` reads the logs through `topics/.parsed.json`, a cache keyed by each log's modification time and size, so an unchanged log isn't parsed again. Deleting that file is always safe. The per-row topic reads behind `list` and the board don't use it. The inbox's Topics tab runs this command on each load.
```

- [ ] **Step 5: Write the refinements back into the spec**

Append to `modules/inbox/docs/superpowers/specs/2026-11-25-topic-graph-design.md`:

```markdown
## Plan refinements (2026-11-25)

The plan (`modules/inbox/docs/superpowers/plans/2026-11-25-topic-graph.md`) built this spec as written and settled these open points. All of them can still be overturned.

- **Liveness** is read in the CLI process from `registry.json`, the file the daemon's `list` reads, with no daemon call and none per node. `archive.jsonl` is read only to find an ended session's directory. Each session entry carries `live`, `state` (`live`, `idle`, `ended`, `unknown`) and `directory`. The project shown is the directory's last name, as for an asker.
- **The cache** is one file, `topics/.parsed.json`, keyed by each log's modification time and size, because each `agt registry` call is a new process. Only `topics --tree` uses it; the daemon's per-row reads are unchanged (tjdsneto/agent-tools#9).
- **Node events** come from every log, oldest first, each with the session it came from.
- **Waiting questions** use the inbox's own entry state, in one query per load. The log's notes are the fallback for entries the inbox no longer has.
- **Finished** means nothing waiting, no open or parked topic, and no live session under the intent. Finished intents aren't rendered until "Show finished"; then they come last and closed.
- **Newest first** means the most recent event anywhere under the intent. It also orders the first two groups.
- **Open by default:** unfinished intents, and topics with something waiting under them. Opening or closing a branch turns the live reload into the stale toast.
- **Resume commands** appear only for sessions that aren't live, with `cd <dir> &&` when the directory is known.
- **A topic's timeline** also lists each fork opened from it.
- **Measured:** <the Task 3 Step 8 and Task 7 Step 4 numbers: command warm median on the real logs, at 1000 synthetic sessions, and the page's warm median>.
```

Replace the angle-bracket line with the numbers you measured before committing, and don't commit the angle brackets.

- [ ] **Step 6: Read every changed doc end to end**

Read each changed file in full. Check that the new text doesn't contradict what surrounds it. In particular, the README's `## Web` section and the spec 2 statements about the feed not calling the registry must still be true.

- [ ] **Step 7: Commit**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph
git add modules/inbox/README.md modules/inbox/DESIGN.md modules/inbox/PRODUCT.md modules/registry/README.md \
  modules/inbox/docs/superpowers/specs/2026-11-25-topic-graph-design.md
git commit -m "docs(inbox): Topics tab in the READMEs, design system, product doc and spec"
```

---

### Task 10: Skills

**Files:**
- Modify: `skills/topic-awareness/SKILL.md`

`agent-inbox` needs no change: asking and posting work as before. `topic-awareness` gets one line, because topic titles now appear on a page Tiago reads.

- [ ] **Step 1: topic-awareness**

In `skills/topic-awareness/SKILL.md`, in `## Look around`, after the code block, add:

```markdown
Tiago reads the same tree on the inbox's Topics tab, with each topic's questions and each session's state, so a short, specific intent and topic title is what he scans there.
```

- [ ] **Step 2: Read the file end to end**

Read it in full and check that the new line sits well with the rest. The drift-ask rule, that drift questions never go through the inbox, stays as it is.

- [ ] **Step 3: Commit**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph
git add skills/topic-awareness/SKILL.md
git commit -m "docs(skills): topic titles show on the inbox's Topics tab"
```

The skills are symlinked from `~/.claude/skills`, `~/.cursor/skills` and `~/.codex/skills` into the main checkout, so they go live when the branch merges.

---

### Task 11: Back up, merge, deploy and verify

No new files. Run every step in order and report each result as you observed it.

- [ ] **Step 1: Every suite, in the worktree**

```bash
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph/modules/registry
.venv/bin/python -m pytest -q | tail -1
.venv/bin/python -m pytest tests/blackbox/test_topics_cli.py tests/blackbox/test_topics_hook.py -q | tail -1
cd /Users/tjdsneto/projects/agent-tools/.worktrees/topic-graph/modules/inbox
.venv/bin/python -m pytest -q | tail -1
.venv/bin/python -m pytest tests/blackbox -q | tail -1
```

Expected: all pass. That is registry `311 passed`, registry black-box `17 passed`, inbox `222 passed` plus any tests Task 8 added, and inbox black-box `8 passed`, or Task 0's baselines plus the same deltas. If anything fails, stop.

- [ ] **Step 2: Back up the live inbox DB, under its own name, before the merge**

The schema doesn't change, but take a dump anyway. Its name is distinct, so the nightly `bin/backup` (`agent_inbox-<YYYYMMDD>.sql`) can't overwrite it:

```bash
/opt/homebrew/opt/postgresql@17/bin/pg_dump -h localhost -p 5433 -d agent_inbox \
  -f ~/.local/share/agent-inbox/backups/agent_inbox-pre-topic-graph.sql
ls -l ~/.local/share/agent-inbox/backups/agent_inbox-pre-topic-graph.sql
```

Expected: a file of non-zero size. Like `agent_inbox-pre-topic-aware.sql`, it matches `bin/backup`'s rotation glob, so it rotates out once 14 newer dumps exist.

- [ ] **Step 3: Merge from the main checkout, after a dirty-file check**

Other sessions work in the main checkout. Check that none of the branch's files are dirty there:

```bash
cd /Users/tjdsneto/projects/agent-tools
git status --short
git diff --name-only main...tn/feat/topic-graph
```

If any file in the second list appears in the first, stop and ask Tiago. Otherwise merge with a merge commit, never a squash:

```bash
git merge --no-ff tn/feat/topic-graph -m "Merge branch 'tn/feat/topic-graph': topic graph view"
git log --oneline -1
```

If the merge conflicts, run `git merge --abort` and report. Don't resolve a conflict in a file another session is editing.

- [ ] **Step 4: Restart the inbox LaunchAgent right away**

`com.tjdsneto.agent-inbox` runs `agt inbox serve` from the main checkout and keeps its old code until it restarts. Until then, the live feed has no Topics tab. Don't run `./install.sh`: nothing it links changed.

```bash
launchctl kickstart -k "gui/$(id -u)/com.tjdsneto.agent-inbox"
curl --retry 10 --retry-connrefused --retry-delay 1 -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8797/
launchctl print "gui/$(id -u)/com.tjdsneto.agent-inbox" | grep -E '^\s*(state|pid) ='
tail -n 20 /Users/tjdsneto/projects/agent-tools/modules/inbox/tmp/serve.log
```

Expected: `200`, `state = running` with a new pid, and no traceback in the log tail.

The registry daemon needs no restart. `topics --tree --events` runs in the CLI process, which loads the merged code on each call, and nothing the daemon runs changed.

- [ ] **Step 5: Verify the live page**

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8797/topics
curl -s http://127.0.0.1:8797/topics | grep -o 'aria-current="page">Topics</a>\|class="tree"\|No topics yet\|notice warn' | sort | uniq -c
curl -s http://127.0.0.1:8797/ | grep -c '<a href="/topics">Topics</a>'
for i in 1 2 3 4 5 6; do curl -s -o /dev/null -w '%{time_total}\n' http://127.0.0.1:8797/topics; done
ls -l ~/.local/share/agent-registry/topics/.parsed.json
agt registry topics --tree --events | python3 -c 'import json,sys; t=json.load(sys.stdin)["tree"]; print(len(t), "roots;", sorted({s["state"] for n in t for s in n["sessions"]}))'
```

Expected:
- `200`;
- the Topics tab marked current and either `class="tree"` or `No topics yet`, with no `notice warn`;
- `1` for the feed's tab link;
- six times, with the first building the live cache;
- the cache file now exists in the live topics dir, which is expected from here on;
- a roots count with the states seen.

Each GET of `/topics` only reads; it never marks an entry read.

- [ ] **Step 6: Screenshot the live Topics page, and only that page**

A GET of an entry page can mark a report read, so shoot `/topics` and nothing else:

```bash
cd /Users/tjdsneto/projects/agent-tools/modules/inbox
mkdir -p tmp/live-shots
for w in 390 1280; do
  for scheme in light dark; do
    node tests/visual/cdpshot.mjs "tmp/live-shots/topics-$w-$scheme.png" http://127.0.0.1:8797/topics "$w" 844 "$scheme"
  done
done
```

Expected: four lines with no `FAIL`. Open all four PNGs with the Read tool and check them against the README's `topics-*` rows, adjusted for the real data: real intents in the right order, chips readable, nothing past the right edge, and the dark ground in the dark shots. Write down what you saw.

- [ ] **Step 7: Ask Tiago to look**

In chat, ask him to open the Topics tab on his phone (`https://<machine>.ts.net:8444/topics`) and check four things:
- whether the order puts what's waiting on him first;
- whether a tap opens and closes a branch;
- whether a resume command selects in one tap;
- whether "Show finished" sticks after a reload.

Record what he reports, and don't claim the phone check passed until he says so.

- [ ] **Step 8: Report and clean up**

Report:
- Step 1's suite results;
- the measurements from Task 3 Step 8, Task 7 Step 4 and Step 5;
- what each screenshot showed in Task 8 Step 6 and here, and any fix that led to;
- Steps 2 to 5 as observed;
- Tiago's phone check.

Then remove the worktree and the merged branch:

```bash
cd /Users/tjdsneto/projects/agent-tools
git worktree remove .worktrees/topic-graph
git branch -d tn/feat/topic-graph
```
