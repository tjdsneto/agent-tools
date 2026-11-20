# Board sidebar-first nav + status vocabulary — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the registry board sidebar-first with Open/Closed/Archive vocabulary, nested worktrees, and canvas group-by modes per the approved design.

**Architecture:** Keep lifecycle detection (`processOpen` / archive events) and turn status (`sess.status`) as two axes. Restructure `dashboard.html` rendering: sidebar selection drives the canvas; lifecycle tabs appear only for a project; group-by is a canvas control. Worktree nesting is presentation-only (do not change `project_key()` in this pass). Smoke-test via existing `tests/test_dashboard.py` string/behavior assertions.

**Tech Stack:** Static board HTML/JS (`modules/registry/src/agent_registry/static/dashboard.html`), pytest (`modules/registry/tests/test_dashboard.py`), optional tiny pure helpers in `project.py` only if extracting worktree heuristics for unit tests proves cleaner than HTML-only.

**Spec:** `modules/registry/docs/superpowers/specs/2026-11-19-board-sidebar-status-design.md`  
**Issue:** https://github.com/tjdsneto/agent-tools/issues/2  
**Repo root for commands:** `~/projects/agent-tools` (this Cursor path may be a symlink to `modules/registry`)

---

## File map

| File | Responsibility |
|------|----------------|
| `modules/registry/src/agent_registry/static/dashboard.html` | Sidebar, tabs, group-by UI, bands, vocabulary strings |
| `modules/registry/tests/test_dashboard.py` | Assert new labels, absence of Live/Stopped/Running, sidebar/group-by hooks |
| `modules/registry/tests/test_project.py` | Only if a small pure helper is extracted for worktree parent inference |
| `modules/registry/src/agent_registry/project.py` | Touch **only** if extracting `is_worktree_leaf` / `worktree_parent_key` helpers; otherwise leave alone |

Out of scope (issue #3): Cursor tokens/CPU, PID display, broken-pipe, false-Open audit.

---

### Task 1: Lock failing assertions for vocabulary + navigation shape

**Files:**
- Modify: `modules/registry/tests/test_dashboard.py`

- [ ] **Step 1: Add / update assertions that encode the design**

In the existing dashboard HTML smoke test (the one that already asserts `processOpen`, `renderProjects`, `"No process open"`, etc.), replace obsolete expectations and add:

```python
# Vocabulary: no old lifecycle words in the served board
for banned in (">Live<", ">Stopped<", ">Running<", "No process open"):
    assert banned not in home and banned not in script

assert ">Open<" in home or ">Open<" in script
assert ">Closed<" in home or ">Closed<" in script
assert "All Open" in home or "All Open" in script

# Navigation hooks
assert "All Open" in script or 'navRow("all-open"' in script or "all-open" in script
assert "Other worktrees" in script
assert "group-by" in home.lower() or "groupby" in script.lower() or "LS_GROUP" in script
```

Adjust exact strings to match the identifiers you will use in Task 2–4 (keep this test as the contract; if an identifier differs, update both together in the same commit series).

Also change any assertion that currently requires `"No process open"` or `"function processOpen"` remains OK (`processOpen` can stay as the internal helper name).

- [ ] **Step 2: Run the test and confirm it fails for the right reasons**

```bash
cd ~/projects/agent-tools
python -m pytest modules/registry/tests/test_dashboard.py -v
```

Expected: FAIL on missing `All Open` / `Open` / banned-string checks (not import errors).

- [ ] **Step 3: Commit**

```bash
git add modules/registry/tests/test_dashboard.py
git commit -m "$(cat <<'EOF'
test: lock board Open/Closed vocabulary and sidebar-first nav

EOF
)"
```

---

### Task 2: Rename lifecycle vocabulary in the board UI

**Files:**
- Modify: `modules/registry/src/agent_registry/static/dashboard.html`

- [ ] **Step 1: Rename user-visible lifecycle labels**

- Tab labels: `Live` → `Open`, `Stopped` → `Closed` (Archive stays).
- Band headers: remove `Running` / `No process`; use `Open` / `Closed` (or omit band title when redundant).
- Empty-state copy: replace “No process open” / similar with Open/Closed wording.
- Keep internal JS ids if churn is high (`tab-live` → prefer renaming to `tab-open` / `data-tab="open"` for consistency; update `setTab`, panel ids, and tests together).
- Keep `processOpen()` as the boolean helper (or rename to `isOpen()` and update call sites + tests).

- [ ] **Step 2: Run dashboard tests**

```bash
python -m pytest modules/registry/tests/test_dashboard.py -v
```

Expected: banned-string assertions pass; nav assertions may still fail until Task 3–4.

- [ ] **Step 3: Commit**

```bash
git add modules/registry/src/agent_registry/static/dashboard.html modules/registry/tests/test_dashboard.py
git commit -m "$(cat <<'EOF'
fix(board): rename Live/Stopped/Running to Open/Closed

EOF
)"
```

---

### Task 3: Sidebar-first selection (All Open + project tree)

**Files:**
- Modify: `modules/registry/src/agent_registry/static/dashboard.html`
- Modify: `modules/registry/tests/test_dashboard.py`

- [ ] **Step 1: Replace sidebar “All” with “All Open”**

Selection model:

- `selectedProject === "all-open"` (or keep `"all"` but label **All Open** and treat as open-only) — prefer explicit `"all-open"`.
- Persist in `localStorage` (migrate old `"all"` → `"all-open"` on read).

When `all-open` is selected:

- Canvas lists **open** sessions only (`processOpen`).
- **Hide** lifecycle tab strip entirely.

When a concrete project key is selected:

- Show lifecycle tabs Open / Closed / Archive.
- Default tab: Open.
- Filter rows to that project (existing `inProject` / `projectOf`).

- [ ] **Step 2: Render sidebar structure**

`renderProjects()` builds:

1. Sticky **All Open** (badge = count of open sessions globally).
2. Main projects: keys that are **not** worktree leaves (Task 4 defines helper).
3. Under each main project: nested worktree children (indent / child class).
4. Bottom section **Other worktrees** for leaves with no inferred parent.

Badge on a main project = open sessions for that project **plus** open sessions in nested worktrees shown under it.

- [ ] **Step 3: Update tests for All Open + hidden tabs**

Assert script contains the all-open selection branch and that tab markup is toggled (e.g. a `tabs` container gets `hidden` class when all-open).

- [ ] **Step 4: Run tests**

```bash
python -m pytest modules/registry/tests/test_dashboard.py -v
```

- [ ] **Step 5: Commit**

```bash
git add modules/registry/src/agent_registry/static/dashboard.html modules/registry/tests/test_dashboard.py
git commit -m "$(cat <<'EOF'
feat(board): sidebar All Open; lifecycle tabs only for a project

EOF
)"
```

---

### Task 4: Worktree nesting heuristic (presentation-only)

**Files:**
- Modify: `modules/registry/src/agent_registry/static/dashboard.html`
- Optional Create/Modify: helpers in `modules/registry/src/agent_registry/project.py` + `tests/test_project.py` if extracting pure functions

- [ ] **Step 1: Implement heuristic helpers (JS is enough)**

```javascript
function isWorktreeLeaf(key, directory) {
  const leaf = key || basename(directory);
  if (/^\.wt/.test(leaf)) return true;
  const d = String(directory || "");
  return d.indexOf("/.worktrees/") !== -1 || /\/\.wt-/.test(d);
}

function worktreeParentKey(directory) {
  // If leaf is .wt* under a parent dir, parent project key = projectOf({directory: parentPath})
  // If path has /.worktrees/<name>, parent is the dir above .worktrees
  // Return null when unknown → "Other worktrees"
}
```

Do **not** change `project_key()` Python behavior in this pass (spec: presentation-only).

- [ ] **Step 2: Wire helpers into `renderProjects()`**

Nest matching leaves under parent; orphans under **Other worktrees**. Selecting a nested worktree row sets `selectedProject` to that leaf’s project key (sessions still keyed by `projectOf(sess)`).

- [ ] **Step 3: Unit-test helpers if extracted to Python; otherwise assert strings in `test_dashboard.py`**

```bash
python -m pytest modules/registry/tests/test_dashboard.py modules/registry/tests/test_project.py -v
```

- [ ] **Step 4: Commit**

```bash
git add modules/registry/src/agent_registry/static/dashboard.html modules/registry/tests/test_dashboard.py
# plus project.py / test_project.py if used
git commit -m "$(cat <<'EOF'
feat(board): nest worktree projects under parents in the sidebar

EOF
)"
```

---

### Task 5: Canvas group-by modes

**Files:**
- Modify: `modules/registry/src/agent_registry/static/dashboard.html`
- Modify: `modules/registry/tests/test_dashboard.py`

- [ ] **Step 1: Add group-by control to the canvas header**

Options by selection:

| Selection | Modes |
|-----------|--------|
| All Open | `latest` \| `project` \| `status` |
| One project | `latest` \| `status` |

Labels: **Latest activity**, **By project**, **By turn status**.

Defaults: `latest`. Persist `localStorage` keys separately for all-open vs project contexts (e.g. `agent-registry.groupBy.allOpen`, `agent-registry.groupBy.project`).

- [ ] **Step 2: Implement grouping in render**

- `latest`: sort by `last_ping` / `updated_at` descending; single band.
- `project`: section per `projectOf(sess)` (All Open only).
- `status`: section per turn status (`working`, `idle`, `reviewing`, `blocked`); stable section order.

Reuse `renderForest` inside each section when parent/child session links matter.

- [ ] **Step 3: Assert control + mode keys in `test_dashboard.py`**

- [ ] **Step 4: Run tests**

```bash
python -m pytest modules/registry/tests/test_dashboard.py -v
```

- [ ] **Step 5: Commit**

```bash
git add modules/registry/src/agent_registry/static/dashboard.html modules/registry/tests/test_dashboard.py
git commit -m "$(cat <<'EOF'
feat(board): canvas group-by for All Open and per-project views

EOF
)"
```

---

### Task 6: Manual board pass + issue checklist

**Files:** none (verification)

- [ ] **Step 1: Open the board against the local daemon**

```bash
cd ~/projects/agent-tools
agt registry dashboard
# or: agent-registry dashboard
```

Manual checks:

1. Sidebar top = All Open; no lifecycle tabs; open sessions only; group-by has three modes.
2. Select a main project → Open/Closed/Archive tabs appear; group-by has two modes.
3. `.wt*` rows nest under parent or sit in Other worktrees — not peers of main projects.
4. No visible Live / Stopped / Running.
5. Row still shows turn status (`idle` / `working` / …).

- [ ] **Step 2: Mark issue #2 checklist items done**

```bash
gh issue edit 2 --repo tjdsneto/agent-tools --add-label ""  # optional
# Comment with verification notes, check off boxes via web or gh
```

- [ ] **Step 3: Commit any leftover test/doc nits; do not commit `.ana/`**

---

## Done when

- Spec acceptance criteria all met.
- `pytest modules/registry/tests/test_dashboard.py` green.
- Issue https://github.com/tjdsneto/agent-tools/issues/2 checklist complete.
- Desktop source lives under `modules/registry/desktop/` and is tracked (separate cutover commit OK before Task 1).
