# Session Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `session-review` Python script and companion Claude skill that parse a Claude Code session transcript JSONL and report tool usage, context injections, redundant reads, and a --timeline view.

**Architecture:** A single executable Python script (`claude-tools/scripts/session-review`) reads a JSONL transcript, extracts tool calls and attachment events, and renders either a grouped summary or a chronological timeline. A skill (`claude-tools/skills/session-review/SKILL.md`) teaches Claude how to find the current transcript path and invoke the script. No external dependencies — stdlib only.

**Tech Stack:** Python 3 (stdlib: json, argparse, sys, collections, datetime, pathlib)

---

## File Map

| Action | Path |
|--------|------|
| Create | `claude-tools/scripts/session-review` |
| Create | `claude-tools/skills/session-review/SKILL.md` |
| Modify | `claude-tools/scripts/install` — add `session-review` to `SCRIPTS` array |

---

### Task 1: Script skeleton — argparse, JSONL loader, entry point

**Files:**
- Create: `claude-tools/scripts/session-review`

- [ ] **Step 1: Create the file with shebang, argparse, and stub main**

`claude-tools/scripts/session-review`:
```python
#!/usr/bin/env python3
"""session-review — analyse a Claude Code session transcript for tool usage and context events."""

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


def parse_transcript(path: Path) -> dict:
    """Parse JSONL transcript and return structured data."""
    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return _extract(events)


def _extract(events: list) -> dict:
    tool_calls = []
    attachments = []
    timeline = []
    seen_prompts: list[str] = []
    turn = 0

    for event in events:
        t = event.get("type", "")
        ts = event.get("timestamp", "")

        if t == "user" and not event.get("isMeta"):
            msg = event.get("message", {})
            content = msg.get("content", "")
            if isinstance(content, str) and content and not content.startswith("<"):
                prompt_id = event.get("promptId", "")
                if prompt_id not in seen_prompts:
                    seen_prompts.append(prompt_id)
                    turn += 1
                    timeline.append({
                        "turn": turn, "ts": ts, "kind": "user_message",
                        "name": "user", "detail": content[:60].replace("\n", " "),
                    })

        elif t == "assistant":
            msg = event.get("message", {})
            for block in msg.get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    name = block.get("name", "")
                    inp = block.get("input", {})
                    detail = _tool_detail(name, inp)
                    call = {"name": name, "input": inp, "turn": turn, "ts": ts, "detail": detail}
                    tool_calls.append(call)
                    timeline.append({"turn": turn, "ts": ts, "kind": "tool_use", "name": name, "detail": detail})

        elif t == "attachment":
            att = event.get("attachment", {})
            att_type = att.get("type", "?")
            detail = _attachment_detail(att)
            attachments.append({"type": att_type, "detail": att, "turn": turn, "ts": ts})
            timeline.append({"turn": turn, "ts": ts, "kind": "attachment", "name": att_type, "detail": detail})

        elif t == "system" and event.get("subtype") in ("turn_duration", "stop_hook_summary", "away_summary"):
            sub = event.get("subtype", "")
            detail = _system_detail(event)
            timeline.append({"turn": turn, "ts": ts, "kind": f"system/{sub}", "name": sub, "detail": detail})

    return {"tool_calls": tool_calls, "attachments": attachments, "timeline": timeline, "total_turns": turn}


def _tool_detail(name: str, inp: dict) -> str:
    if name == "Bash":
        return (inp.get("description") or inp.get("command", ""))[:60]
    if name in ("Read", "Edit", "Write"):
        return inp.get("file_path", "")
    if name == "Skill":
        return inp.get("skill", "")
    if name == "Agent":
        return inp.get("description", "")[:60]
    return ""


def _attachment_detail(att: dict) -> str:
    att_type = att.get("type", "")
    if att_type == "hook_success":
        s = att.get("hookName", "")
        dur = att.get("durationMs")
        code = att.get("exitCode")
        if dur is not None:
            s += f" ({dur}ms)"
        if code not in (None, "", 0):
            s += f" exit={code}"
        return s
    if att_type == "deferred_tools_delta":
        return f"+{len(att.get('addedNames', []))} tools"
    return ""


def _system_detail(event: dict) -> str:
    sub = event.get("subtype", "")
    if sub == "turn_duration":
        return f"{event.get('durationMs', 0)}ms"
    if sub == "stop_hook_summary":
        return f"{event.get('hookCount', 0)} hooks"
    return ""


def _bar(n: int, max_n: int, width: int = 20) -> str:
    if max_n == 0:
        return ""
    return "█" * round(n / max_n * width)


def _fmt_ts(ts: str) -> str:
    if not ts:
        return "??:??:??"
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%H:%M:%S")
    except Exception:
        return ts[11:19] if len(ts) >= 19 else ts


def render_summary(data: dict, session_id: str) -> None:
    tool_calls = data["tool_calls"]
    attachments = data["attachments"]
    turns = data["total_turns"]

    print(f"\nSession Review: {session_id[:8]}  ({turns} turns, {len(tool_calls)} tool calls)")
    print("━" * 60)

    counts = Counter(c["name"] for c in tool_calls)
    if counts:
        print("\nTOOL USAGE")
        max_c = max(counts.values())
        for name, n in counts.most_common():
            print(f"  {name:<14} {n:>3}  {_bar(n, max_c)}")

    bash_calls = [c for c in tool_calls if c["name"] == "Bash"]
    if bash_calls:
        print("\nBASH COMMANDS")
        groups: dict[str, list[str]] = defaultdict(list)
        for c in bash_calls:
            cmd = c["input"].get("command", "").strip()
            leading = cmd.split()[0] if cmd.split() else cmd
            groups[leading].append(cmd)
        for leading, cmds in sorted(groups.items(), key=lambda x: -len(x[1]))[:8]:
            top = Counter(cmds).most_common(1)[0][0]
            print(f"  {leading:<14} {len(cmds):>3}x   {top[:50]}")

    read_calls = [c for c in tool_calls if c["name"] == "Read"]
    if read_calls:
        print("\nREAD FILES")
        file_counts = Counter(c["input"].get("file_path", "?") for c in read_calls)
        for path, n in file_counts.most_common():
            flag = "⚠ " if n > 1 else "  "
            print(f"  {flag}{n}x  {path}")

    skill_calls = [c for c in tool_calls if c["name"] == "Skill"]
    if skill_calls:
        print("\nSKILLS INVOKED")
        seen: list[str] = []
        for c in skill_calls:
            s = c["input"].get("skill", "?")
            if s not in seen:
                seen.append(s)
        for s in seen:
            print(f"  {s}")

    if attachments:
        print("\nCONTEXT INJECTIONS")
        att_counts = Counter(a["type"] for a in attachments)
        for att_type, n in att_counts.most_common():
            print(f"  {att_type:<32} {n:>3}x")

    warnings: list[str] = []
    file_counts = Counter(c["input"].get("file_path", "?") for c in tool_calls if c["name"] == "Read")
    for p, n in file_counts.items():
        if n > 1:
            warnings.append(f"Read `{p}` called {n}x — consider caching the content")
    for a in attachments:
        att = a["detail"]
        code = att.get("exitCode")
        if code not in (None, "", 0):
            hook = att.get("hookName", "unknown hook")
            warnings.append(f"Hook `{hook}` exited with code {code}")

    if warnings:
        print("\nWARNINGS")
        for w in warnings:
            print(f"  ⚠ {w}")

    print()


def render_timeline(data: dict, session_id: str) -> None:
    print(f"\nTimeline: {session_id[:8]}")
    print("━" * 80)
    for ev in data["timeline"]:
        line = (
            f"[turn {ev['turn']:>2} | {_fmt_ts(ev['ts'])}]"
            f"  {ev['kind']:<22}  {ev['name']:<25}  {ev['detail']}"
        )
        print(line[:130])
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyse a Claude Code session transcript.")
    parser.add_argument("transcript", type=Path, help="Path to the session .jsonl transcript")
    parser.add_argument("--timeline", action="store_true", help="Show full chronological event list")
    args = parser.parse_args()

    if not args.transcript.exists():
        print(f"Error: file not found: {args.transcript}", file=sys.stderr)
        sys.exit(1)

    session_id = args.transcript.stem
    data = parse_transcript(args.transcript)

    if args.timeline:
        render_timeline(data, session_id)
    else:
        render_summary(data, session_id)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make executable**

```bash
chmod +x ~/projects/tjdsneto-setup/claude-tools/scripts/session-review
```

- [ ] **Step 3: Quick smoke test — run against the current session**

```bash
~/projects/tjdsneto-setup/claude-tools/scripts/session-review \
  ~/.claude/projects/-Users-tjdsneto-projects-tjdsneto-setup/a1d68411-95c9-47d1-84d3-28ce3fe7b123.jsonl
```

Expected: prints header line, TOOL USAGE table, BASH COMMANDS, READ FILES, SKILLS INVOKED, CONTEXT INJECTIONS, optional WARNINGS. No Python errors.

- [ ] **Step 4: Test --timeline flag**

```bash
~/projects/tjdsneto-setup/claude-tools/scripts/session-review \
  ~/.claude/projects/-Users-tjdsneto-projects-tjdsneto-setup/a1d68411-95c9-47d1-84d3-28ce3fe7b123.jsonl \
  --timeline
```

Expected: chronological event list, one line per event.

- [ ] **Step 5: Test against the archived session f55d5aa5**

First, find the transcript path:
```bash
find ~/.claude/projects -name "f55d5aa5*" 2>/dev/null
```

Then run:
```bash
~/projects/tjdsneto-setup/claude-tools/scripts/session-review <path-found-above>
```

Expected: output with no errors, realistic tool counts.

- [ ] **Step 6: Commit**

```bash
git -C ~/projects/tjdsneto-setup add claude-tools/scripts/session-review
git -C ~/projects/tjdsneto-setup commit -m "feat: add session-review script"
```

---

### Task 2: Write the skill

**Files:**
- Create: `claude-tools/skills/session-review/SKILL.md`

- [ ] **Step 1: Create skill directory and file**

```bash
mkdir -p ~/projects/tjdsneto-setup/claude-tools/skills/session-review
```

`claude-tools/skills/session-review/SKILL.md`:
```markdown
---
name: session-review
description: Analyse a Claude Code session transcript for tool usage and context injection events. Surfaces redundant reads, excessive tool calls, and bloated context injections. Works on the current session or any archived session.
user-invocable: true
argument-hint: "[--timeline] [session-id-or-keyword]"
---

# Session Review

Analyse a transcript to spot excessive tool calls, redundant reads, and context injection bloat.

## Script

```
~/projects/tjdsneto-setup/claude-tools/scripts/session-review <transcript.jsonl>
~/projects/tjdsneto-setup/claude-tools/scripts/session-review <transcript.jsonl> --timeline
```

## Current session

The current transcript path is always available in the `system-reminder` context injected at the top of each turn:

```
The transcript for this session is stored at: /Users/tjdsneto/.claude/projects/.../<session-id>.jsonl
```

Extract it and run:

```bash
~/projects/tjdsneto-setup/claude-tools/scripts/session-review <transcript-path>
```

## Past session

Use `list-sessions` to find the path by date or keyword:

```bash
~/projects/tjdsneto-setup/claude-tools/scripts/list-sessions | grep <keyword>
```

Then pass the `.jsonl` path to the script.

## Interpreting output

After running the script, read the output and:

1. **WARNINGS** — surface each one with a one-line suggestion, e.g.:
   - "Read `.claude/settings.json` called 3x — assign its content to a variable on first read"
   - "Hook `rename-claude-sessions` exited 1 — check the script for errors"

2. **TOOL USAGE** — if Bash dominates (>50% of calls), check BASH COMMANDS for repeated patterns that could be collapsed.

3. **READ FILES** — any ⚠ file is a candidate for caching in a variable instead of re-reading.

4. **CONTEXT INJECTIONS** — high `hook_success` counts are normal; high `task_reminder` counts (>5) mean TodoWrite/TaskUpdate are firing frequently.

Do not attempt to fix inefficiencies automatically — only report and suggest.
```

- [ ] **Step 2: Commit**

```bash
git -C ~/projects/tjdsneto-setup add claude-tools/skills/session-review/
git -C ~/projects/tjdsneto-setup commit -m "feat: add session-review skill"
```

---

### Task 3: Update install script and deploy

**Files:**
- Modify: `claude-tools/scripts/install`

- [ ] **Step 1: Add `session-review` to the SCRIPTS array**

In `claude-tools/scripts/install`, find:
```bash
SCRIPTS=("session-context" "rename-claude-sessions" "extract-learnings" "play-stop-sound" "list-sessions" "active-sessions" "install")
```

Replace with:
```bash
SCRIPTS=("session-context" "rename-claude-sessions" "extract-learnings" "play-stop-sound" "list-sessions" "active-sessions" "session-review" "install")
```

- [ ] **Step 2: Also add to the verification loop**

Find:
```bash
for script in "session-context" "rename-claude-sessions" "extract-learnings" "play-stop-sound" "list-sessions"; do
```

Replace with:
```bash
for script in "session-context" "rename-claude-sessions" "extract-learnings" "play-stop-sound" "list-sessions" "session-review"; do
```

- [ ] **Step 3: Run install to verify**

```bash
cd ~/projects/tjdsneto-setup && ./install.sh
```

Expected: output includes `✓ session-review is executable`.

- [ ] **Step 4: Commit**

```bash
git -C ~/projects/tjdsneto-setup add claude-tools/scripts/install
git -C ~/projects/tjdsneto-setup commit -m "chore: add session-review to install script"
```
