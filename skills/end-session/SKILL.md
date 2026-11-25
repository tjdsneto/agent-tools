---
name: end-session
description: Terminate the current Claude Code process (and optionally the terminal) with SIGTERM. Destructive and unrecoverable — use ONLY on an unambiguous request to close/quit/exit the session ("end the session", "close this", "kill this session", "/end-session"). Do NOT use for "wrap up", "we're done", "that's all", or "goodbye" — those mean save state, not kill the process; route them to handoff, journal, karen wrap, or work-management instead.
user-invocable: true
argument-hint: "[--terminal]"
---

# End Session

Ends the current Claude Code session by killing its process. If `--terminal` is passed, also kills the terminal session.

## How it works

The current Claude Code PID is the parent of the bash subprocess. Find it and send SIGTERM:

```bash
# Find claude PID (parent of this bash process)
CLAUDE_PID=$(ps -o ppid= -p $$ | tr -d ' ')
kill -TERM $CLAUDE_PID
```

To also kill the terminal (the parent of the claude process):

```bash
CLAUDE_PID=$(ps -o ppid= -p $$ | tr -d ' ')
TERMINAL_PID=$(ps -o ppid= -p $CLAUDE_PID | tr -d ' ')
kill -TERM $CLAUDE_PID $TERMINAL_PID
```

## When to use

Only on an **unambiguous request to terminate the process** — the user wants this window gone:

- "end the session", "close this", "kill this session", "quit", "exit", "/end-session"

This is destructive and unrecoverable: the transcript stops mid-turn and anything unsaved is
lost. Never use it speculatively, and never as the closing move of a task unless asked.

## When NOT to use — "wrapping up" is not "kill the process"

Several phrases *sound* terminal but mean **save state**, not exit. They belong elsewhere:

| The user says | They want | Use instead |
|---|---|---|
| "wrap up", "wrap this up" | day/week close-out over Tray + GoFlow | `karen` (wrap mode) / `work-management` |
| "we're done", "that's all", "goodbye" | acknowledgement, maybe a timer stop | offer `gtr stop` (`goflow-work-session`); do nothing else |
| "hand this off", "save context for later", "wrap up for the next agent" | rich resumable boot for later / next agent | `/handoff:handoff` |
| "fresh continuation", "continue in a fresh session", "context full keep going" | slim boot + resume cmd for immediate clean continue | `fresh-continuation` |
| "log what we did", "journal this" | durable dated record | `journal` |
| "park this" | step away from a thread without losing it | `parked-ideas` |

If the phrasing is one of those, do **not** kill anything — even when the user also sounds
finished. When both readings are live ("ok we're done here, close it out"), ask which they mean
in one line. A wrong guess here destroys the session; a wrong guess the other way costs a
sentence.

## Steps

1. Confirm intent if there's **any** doubt — see the table above.
2. Offer to stop a running GoFlow timer first (`gtr list --json`); a killed process leaves it running.
3. Run the appropriate kill command via Bash.
4. (No response needed after — the process will be gone.)
