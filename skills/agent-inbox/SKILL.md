---
name: agent-inbox
description: Use when this session needs a decision or a record from Tiago that should survive the session. Asks and posts go through `agt inbox`.
---

# agent-inbox

The inbox delivers an answer back to this session, including after it has exited. Do not write the answer into the client's files yourself. The message you receive is the whole handoff.

## Who is asking

Find `--engine` and `--session-id` from the session you are in. Do not guess them from the working directory.

- Claude: the session UUID in the transcript path.
- Codex: the thread id.
- Cursor: the composer id.

## Ask

Request JSON on stdin (`title`, `control`, optional `summary`, `detail`, `priority`).

```bash
printf '%s' "$JSON" | agt inbox ask --engine "$ENGINE" --session-id "$SESSION_ID"
```

Use `--wait` only when you can stay up for the answer. Otherwise exit. Delivery resumes you.

On `{"event":"followup",...}`, reply and, if you are still in wait mode, keep waiting:

```bash
agt inbox reply "$ID" --text "..."
agt inbox wait "$ID" --after "$SEQ"
```

## Post

A summary or a run result. A script with no session passes `--script`.

```bash
printf '%s' "$JSON" | agt inbox post --script nightly
```
