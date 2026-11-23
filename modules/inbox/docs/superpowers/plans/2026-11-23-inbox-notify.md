# Agent Inbox — Slice 4: Notifications, skills, and ops — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tell Tiago when something needs him, teach Hermes and agents how to call the CLI, and keep backups plus the HTML retention rule.

**Architecture:** The notifier runs inside slice 2's `serve` loop, after each sweep. It reads entries; it does not open Postgres on its own beyond the connection `serve` already holds. Telegram goes out through `hermes send`. Numbered replies are the v1 control rendering. Buttons stay parked in the spec; do not build a Hermes plugin in this plan.

**Tech Stack:** Python 3.14, `hermes send`, `osascript`, `agt say`, `pg_dump` from `/opt/homebrew/opt/postgresql@17/bin/pg_dump`, launchd.

**Spec:** [`../specs/2026-11-23-agent-inbox-design.md`](../specs/2026-11-23-agent-inbox-design.md) sections Notifications, Hermes and Telegram, Store and operations, Relationship to existing tools. Depends on slices 2 and 3.

**Work on:** `/Users/tjdsneto/projects/agent-tools` branch `main`. Do not commit unrelated `modules/registry/**` dirt.

---

## Decisions this plan locks

- Telegram target is `AGENT_INBOX_TELEGRAM_TO` (for example `telegram:9255…`). Unset → log `telegram target unset` and skip the send. Do not hard-code a chat id.
- `agt say` runs only when `AGENT_INBOX_SAY=1` and the entry is `urgent`.
- Quiet hours are local time 22:00–08:00. Only `urgent` is sent inside them.
- `normal` pushes batch: at most one Telegram message per 15 minutes, and only outside quiet hours. The batch lists every entry that became pending since the last push.
- `low` never pushes.
- Urgent use is the entry itself. The per-agent count is `count(*)` of `entries` where `priority = 'urgent'` grouped by `asker.engine`. No new event type.
- "Answerable again" is one `normal` (or `urgent`, if any of the entries is urgent) batch line: `3 entries are answerable again`. Slice 2 already clears `held` when the budget drops. This slice notices the transition.
- HTML is cleared 90 days after the entry closes. Closed states: `delivered`, `expired`, `withdrawn`, `superseded`, `undelivered`, `archived`.

---

### Task 1: What to say

**Files:**
- Create: `modules/inbox/src/agent_inbox/notify.py`
- Test: `modules/inbox/tests/test_notify.py`

- [ ] **Step 1: Failing tests**

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from agent_inbox.notify import card, due, quiet

LOCAL = ZoneInfo("America/Sao_Paulo")


def test_choice_card_is_numbered():
    text = card({
        "id": "ib-7k3q", "title": "Which split?", "priority": "normal",
        "asker": {"project": "/tmp/agent-tools"},
        "control": {"type": "choice", "options": [{"id": "a", "label": "Tauri"}, {"id": "b", "label": "Go", "recommended": True}]},
    }, ui="https://mbp.tailnet/e/ib-7k3q")
    assert "Which split?" in text
    assert "1. Tauri" in text and "2. Go (recommended)" in text
    assert "https://mbp.tailnet/e/ib-7k3q" in text
    assert "reply 1" in text


def test_approve_card_tells_him_the_words():
    text = card({
        "id": "ib-7k3q", "title": "Ship it?", "priority": "urgent",
        "asker": {"project": None},
        "control": {"type": "approve"},
    }, ui="https://x/e/ib-7k3q")
    assert 'reply "approve"' in text and 'revise: reason' in text


def test_quiet_hours():
    assert quiet(datetime(2026, 11, 23, 22, 0, tzinfo=LOCAL))
    assert quiet(datetime(2026, 11, 23, 7, 59, tzinfo=LOCAL))
    assert not quiet(datetime(2026, 11, 23, 8, 0, tzinfo=LOCAL))
    assert not quiet(datetime(2026, 11, 23, 21, 59, tzinfo=LOCAL))


def test_due_batches_normal_and_always_sends_urgent():
    entries = [
        {"id": "a", "priority": "normal", "created_at": "t"},
        {"id": "b", "priority": "low", "created_at": "t"},
        {"id": "c", "priority": "urgent", "created_at": "t"},
    ]
    night = datetime(2026, 11, 23, 23, 0, tzinfo=LOCAL)
    assert [e["id"] for e in due(entries, now=night, last_normal_at=None)] == ["c"]
    day = datetime(2026, 11, 23, 12, 0, tzinfo=LOCAL)
    recent = datetime(2026, 11, 23, 11, 50, tzinfo=LOCAL)
    assert [e["id"] for e in due(entries, now=day, last_normal_at=recent)] == ["c"]
    assert [e["id"] for e in due(entries, now=day, last_normal_at=None)] == ["c", "a"]
```

- [ ] **Step 2: Implement `card`, `quiet`, `due`**

```python
from __future__ import annotations

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

LOCAL = ZoneInfo("America/Sao_Paulo")
QUIET = (22, 8)
NORMAL_GAP = timedelta(minutes=15)


def quiet(now: datetime) -> bool:
    hour = now.astimezone(LOCAL).hour
    return hour >= QUIET[0] or hour < QUIET[1]


def due(entries: list[dict], *, now: datetime, last_normal_at: datetime | None) -> list[dict]:
    out = []
    send_normal = not quiet(now) and (last_normal_at is None or now - last_normal_at >= NORMAL_GAP)
    for entry in entries:
        if entry["priority"] == "urgent":
            out.append(entry)
        elif entry["priority"] == "normal" and send_normal:
            out.append(entry)
    return out


def card(entry: dict, *, ui: str) -> str:
    project = os.path.basename((entry.get("asker") or {}).get("project") or "") or "-"
    lines = [f"{entry['priority']}  {project}", entry["title"]]
    control = entry.get("control") or {}
    ctype = control.get("type")
    if ctype in ("choice", "multi"):
        for i, opt in enumerate(control.get("options") or [], start=1):
            mark = " (recommended)" if opt.get("recommended") else ""
            lines.append(f"{i}. {opt['label']}{mark}")
        lines.append("reply 1" if ctype == "choice" else "reply the numbers")
    elif ctype == "text":
        lines.append("reply with the text")
    elif ctype == "approve":
        lines.append('reply "approve" or "revise: reason"')
    lines.append(ui)
    return "\n".join(lines)
```

- [ ] **Step 3: Run and commit**

`modules/inbox/.venv/bin/python -m pytest modules/inbox/tests/test_notify.py -q`

```bash
git add modules/inbox/src/agent_inbox/notify.py modules/inbox/tests/test_notify.py
git commit -m "feat(inbox): decide which entries are worth a push"
```

---

### Task 2: Send, and remember the last batch

**Files:**
- Modify: `modules/inbox/src/agent_inbox/notify.py`
- Modify: `modules/inbox/src/agent_inbox/serve.py`
- Modify: `modules/inbox/src/agent_inbox/schema.sql` and `db.py`
- Test: `modules/inbox/tests/test_notify.py`

- [ ] **Step 1: ops table**

Add to `schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS ops (
    key   text PRIMARY KEY,
    value jsonb NOT NULL
);
```

And in `db.py`, next to the delivery migration:

```python
OPS = """
CREATE TABLE IF NOT EXISTS ops (
    key   text PRIMARY KEY,
    value jsonb NOT NULL
)
"""
```

Call `conn.execute(OPS)` from `ensure_schema` on both the fresh and the already-migrated path.

- [ ] **Step 2: Failing test**

```python
def test_push_uses_hermes_and_records_the_batch(conn, monkeypatch):
    sent = []
    monkeypatch.setenv("AGENT_INBOX_TELEGRAM_TO", "telegram:1")
    monkeypatch.setattr("agent_inbox.notify.hermes_send", lambda to, text: sent.append((to, text)))
    monkeypatch.setattr("agent_inbox.notify.notify_mac", lambda title, body: None)
    monkeypatch.setattr("agent_inbox.notify.say", lambda text: None)
    entry = {"id": "ib-7k3q", "title": "Which split?", "priority": "urgent", "kind": "ask",
             "asker": {"engine": "claude", "project": "/tmp/x"}, "control": {"type": "approve"},
             "state": "open", "created_at": "t"}
    from agent_inbox.notify import push_new
    push_new(conn, [entry], now=datetime(2026, 11, 23, 23, 0, tzinfo=LOCAL), ui="https://x/e/ib-7k3q")
    assert sent and sent[0][0] == "telegram:1"
    assert "Which split?" in sent[0][1]
```

- [ ] **Step 3: Senders**

```python
def hermes_send(to: str, text: str) -> None:
    import subprocess
    subprocess.run(["hermes", "send", "--to", to, text], check=False, timeout=60)


def notify_mac(title: str, body: str) -> None:
    import subprocess
    safe = body.replace('"', "'")[:180]
    subprocess.run(["osascript", "-e", f'display notification "{safe}" with title "{title}"'], check=False, timeout=10)


def say(text: str) -> None:
    if os.environ.get("AGENT_INBOX_SAY") != "1":
        return
    import subprocess
    subprocess.run(["agt", "say", "--text", text[:500]], check=False, timeout=30)
```

`push_new` selects entries that are open questions or unread info, passes them through `due`, sends one Telegram message (urgent entries each get their own card immediately; the normal ones share one message joined by a blank line). macOS notification and `say` only for urgent. Write `ops.value` key `last_normal_push` as `{"at": "<iso>"}` when a normal batch goes out.

Also `push_answerable(conn, ids, priority)` for the held→clear transition: one card `N entries are answerable again` plus the ids. Call it from `serve.sweep` after `dispatch_entry` when an entry's stored `reachability` was `held` and the new one is `live` or `resumable`. Slice 2's dispatch already writes `reachability`. Compare before and after.

When an entry is answered from the web or the CLI (`via != telegram`), send one short Telegram note if the target is set: `ib-7k3q answered via web: b`. Hook this in `store.answer` only when `via != "telegram"`, by calling `notify.note_answered(entry_id, via, value)`. Failures are swallowed: a missing `hermes` binary must not roll back the answer. Catch `OSError` and log to stderr.

On the feed page from slice 3, under the title, print `urgent: claude N, codex N, cursor N` from `SELECT engine, count(*) FROM entries WHERE priority = 'urgent' AND engine IS NOT NULL GROUP BY engine`. Omit engines with a zero count. If slice 3 is not on the branch yet, skip this line and leave a checkbox unchecked rather than inventing the page.

- [ ] **Step 4: Run and commit**

`modules/inbox/.venv/bin/python -m pytest modules/inbox/tests -q`

```bash
git add modules/inbox/src/agent_inbox/notify.py modules/inbox/src/agent_inbox/serve.py modules/inbox/src/agent_inbox/store.py modules/inbox/src/agent_inbox/schema.sql modules/inbox/src/agent_inbox/db.py modules/inbox/tests/test_notify.py
git commit -m "feat(inbox): push urgent and batched notices from the serve loop"
```

---

### Task 3: Skills

**Files:**
- Create: `skills/agent-inbox/SKILL.md`
- Create: `skills/inbox/SKILL.md`
- Modify: `install.sh`
- Modify: `/Users/tjdsneto/.claude/skills/visual-ask/SKILL.md` and the Cursor copy if it exists

- [ ] **Step 1: Agent skill**

`skills/agent-inbox/SKILL.md` tells an agent, in this order:

1. Find `--engine` and `--session-id` from the session you are in. Do not guess them from the working directory. Claude: the session UUID in the transcript path. Codex: the thread id. Cursor: the composer id.
2. `agt inbox ask` with the request JSON on stdin. Use `--wait` only when you can stay up for the answer. Otherwise exit; delivery resumes you.
3. On `{"event":"followup",...}`, answer with `agt inbox reply <id> --text ...`, then `agt inbox wait <id> --after <seq>` if you are still in wait mode.
4. `agt inbox post` for a summary or a run result. A script with no session passes `--script`.
5. Do not write the answer into the client's files yourself. The message you receive is the whole handoff.

- [ ] **Step 2: Hermes skill**

`skills/inbox/SKILL.md` is for the Hermes gateway. It says:

- A numbered reply `1` or `2` on the latest open question is `agt inbox answer <id> --value <option id> --via telegram`. Map the number through the card, not the option id the human did not see.
- `approve` and `revise: ...` are the approve control. The text after `revise:` is `--comment`.
- A line starting with `?` is `agt inbox followup <id> --text ... --via telegram`.
- `approve ib-7k3q` names the id. Without an id, use the latest open question.
- Call the CLI on this machine. Do not use the network.

- [ ] **Step 3: install.sh**

Link `agent-inbox` the same way the other skills are linked, into `~/.claude/skills` and `~/.cursor/skills`.

If `~/.hermes/skills` exists, link `skills/inbox` there as `inbox`. If it does not, print the repo path and do not create the Hermes directory.

- [ ] **Step 4: visual-ask**

Replace the loop in both visual-ask skill copies so it:

1. Writes the fragment to a temp file.
2. Runs `agt inbox ask --wait --engine <this engine> --session-id <this session> --html-file <fragment>` with the title and control on stdin. The CLI already copies `--html-file` into the request.
3. Opens the entry URL. The URL is `INBOX_UI_ORIGIN` plus `/e/<id>`, default `http://127.0.0.1:8787/e/<id>`.
4. Stops. The wait command returns the answer into the session. Delete the instruction to read `state/events`.

Do not delete `scripts/server.mjs`. Nothing in this plan proves it has no other caller.

- [ ] **Step 5: Commit** the repo files only.

```bash
git add skills/agent-inbox/SKILL.md skills/inbox/SKILL.md install.sh
git commit -m "docs(inbox): agent and Hermes skills for the inbox CLI"
```

The visual-ask edits are outside the repo. Say so in the commit body only if you also changed a tracked file; do not `git add` files under `~/.claude`.

---

### Task 4: Backups and HTML retention

**Files:**
- Create: `modules/inbox/bin/backup`
- Create: `modules/inbox/launchd/com.tjdsneto.agent-inbox-backup.plist`
- Modify: `modules/inbox/src/agent_inbox/serve.py` (retention on the sweep)
- Modify: `install.sh`
- Test: `modules/inbox/tests/test_retention.py`

- [ ] **Step 1: Retention test**

```python
def test_old_closed_html_is_cleared(conn):
    e = store.create_entry(
        conn, "post",
        validate_request({"title": "t", "html": "<p>x</p>"}, "post"),
        script="cron",
    )
    store.archive(conn, e["id"])
    conn.execute("UPDATE entries SET updated_at = now() - interval '91 days' WHERE id = %s", (e["id"],))
    from agent_inbox.serve import purge_html
    assert purge_html(conn) == 1
    assert store.get_entry(conn, e["id"])["html"] is None
```

An entry archived today keeps its HTML. An open question older than 90 days keeps its HTML.

`purge_html`:

```python
def purge_html(conn) -> int:
    rows = conn.execute(
        """
        UPDATE entries SET html = NULL
        WHERE html IS NOT NULL
          AND state IN ('delivered', 'expired', 'withdrawn', 'superseded', 'undelivered', 'archived')
          AND updated_at < now() - interval '90 days'
        RETURNING id
        """
    ).fetchall()
    return len(rows)
```

Call it at the end of `sweep`.

- [ ] **Step 2: Nightly dump**

`modules/inbox/bin/backup`:

```bash
#!/usr/bin/env bash
set -euo pipefail
DEST="${HOME}/.local/share/agent-inbox/backups"
mkdir -p "$DEST"
STAMP="$(date +%Y%m%d)"
/opt/homebrew/opt/postgresql@17/bin/pg_dump -h localhost -p 5433 -d agent_inbox -f "$DEST/agent_inbox-$STAMP.sql"
ls -1t "$DEST"/agent_inbox-*.sql | tail -n +15 | xargs -r rm -f
```

`tail -n +15` keeps 14 files. macOS `xargs` has no `-r`; use:

```bash
old="$(ls -1t "$DEST"/agent_inbox-*.sql 2>/dev/null | tail -n +15 || true)"
if [ -n "$old" ]; then
  printf '%s\n' "$old" | while IFS= read -r f; do rm -f "$f"; done
fi
```

Plist: `StartCalendarInterval` hour 3, minute 15, `RunAtLoad` false, program `__ROOT__/modules/inbox/bin/backup`. `install.sh` bootstraps `com.tjdsneto.agent-inbox-backup` the same way as the serve agent.

- [ ] **Step 3: Run a dump once**

```bash
chmod +x modules/inbox/bin/backup
modules/inbox/bin/backup
ls "$HOME/.local/share/agent-inbox/backups"
```

Expected: one `agent_inbox-YYYYMMDD.sql` that is non-empty. Do not commit the dump.

- [ ] **Step 4: Commit**

```bash
git add modules/inbox/bin/backup modules/inbox/launchd/com.tjdsneto.agent-inbox-backup.plist modules/inbox/src/agent_inbox/serve.py modules/inbox/tests/test_retention.py install.sh
git commit -m "feat(inbox): nightly pg_dump and 90-day HTML purge"
```

---

## Spec coverage

| Spec rule | Task |
|---|---|
| urgent immediate, any hour, Telegram + macOS + opt-in say | 1, 2 |
| normal batched, 15 min, daytime, Telegram only | 1, 2 |
| low is UI only | 1 |
| quiet hours 22:00–08:00 | 1 |
| urgent use visible as a per-agent count | the entries themselves; slice 3 feed can show it — add the count to the feed header in this slice's Task 2 by a one-line query on the feed page |
| numbered Telegram replies, not buttons | 1, 3 |
| Hermes skill turns a reply into the CLI | 3 |
| note when answered elsewhere | 2 |
| `hermes send`, no network auth | 2 |
| visual-ask becomes ask --wait and opens the entry URL | 3 |
| nightly pg_dump, 14 kept | 4 |
| HTML deleted 90 days after close | 4 |
| Buttons via a Hermes plugin | parked; not in this plan |
