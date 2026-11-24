---
name: agent-inbox
description: Use when you need a decision, approval or answer from Tiago that he is not in the chat to give right now (an unattended, headless, background or overnight run, or he said he is away), when he asks you to ask through the inbox, or when you want to leave him a report. Asks and posts go through `agt inbox`; the answer comes back to this session, even after it exits.
---

# agent-inbox

The inbox is where agents leave Tiago questions and reports. He gets a Telegram card, answers from his phone or the web page, and the inbox delivers the answer back to the session that asked: a message into a live session, or a resume of one that exited.

## When to use it

- Use it when nobody is watching this chat: a headless run, a long background task, a scheduled job, or Tiago said he is away.
- Use it when he asks for it ("ask me in the inbox").
- Use a post for a result he should read later: a run summary, what you found, what is blocked.
- Do not use it when he is in the conversation with you. Ask him in the chat instead.
- Do not use it for something you can decide yourself or look up.

## Who is asking

Pass your engine and your own session id, so the answer can find you. Read the id from the environment, never guess it from the directory:

| Engine | `--engine` | `--session-id` |
|---|---|---|
| Claude Code | `claude` | `$CLAUDE_CODE_SESSION_ID` |
| Codex | `codex` | `$CODEX_THREAD_ID` |
| Cursor | `cursor` | `$CURSOR_CONVERSATION_ID` |

Without `--session-id`, nothing is ever delivered to you. Leave it out only when you, or the script that runs you, will read the answer later with `agt inbox get <id>`.

## Ask

Request JSON on stdin. `title` is the question, one line. `control` says how he answers.

```bash
cat <<'JSON' | agt inbox ask --engine claude --session-id "$CLAUDE_CODE_SESSION_ID"
{
  "title": "Merge the registry refactor before the inbox restart?",
  "summary": "CI is green. Restarting first keeps the old board until the next deploy.",
  "control": {"type": "choice", "options": [
    {"id": "merge", "label": "Merge now, then restart", "recommended": true},
    {"id": "restart", "label": "Restart first, merge after"}
  ]}
}
JSON
```

It prints `{"entry": "ib-xxxx", "state": "open"}`. Keep the id.

Controls:

- `{"type": "choice", "options": [...]}`: pick one. 2 to 6 options, each `{"id", "label"}`, optional `"description"`, `"recommended": true`, `"default": true` (one at most). Telegram shows these as buttons.
- `{"type": "multi", "options": [...]}`: pick several. Same options.
- `{"type": "text", "size": "short"}` or `"long"`: free text.
- `{"type": "approve"}`: Approve, or Revise with a required reason in the comment. Telegram shows an Approve button.

Optional fields:

- `summary` and `detail` render as Markdown. Raw HTML in them is shown as text.
- `html` is an attachment shown in a sandboxed frame, as reference only. Pass a file with `--html-file`.
- `priority`: `normal` (default) pushes at most every 15 minutes and holds pushes from 22:00 to 08:00; `urgent` pushes at once, day or night; `low` never pushes.
- `source`: `{"kind", "ref", "url"}`, a link back to what the question is about.
- `expires_at`: an ISO time with an offset, after which the question closes.

Write for a phone: the title is the question itself, the summary is two or three sentences, and every option label stands on its own.

## After asking

End your turn, or keep working on something that does not need the answer. Do not poll.

The answer arrives as a message like this:

```
Inbox answer for ib-xxxx ("Merge the registry refactor before the inbox restart?"): merge
{"entry": "ib-xxxx", "event": "answer", "value": "merge", "comment": null, "via": "telegram", ...}
```

If you exited, the inbox resumes you with that message (Claude Code comes back with the permissions it was launched with). Read `value`, and `comment` when there is one, then carry on.

`--wait` blocks until the answer comes instead, for up to 30 minutes (`--timeout` seconds). It exits 0 with the answer, or 5 on timeout. On timeout the question stays open and switches to the resume path, so stop and let delivery wake you.

## Follow-ups

Tiago can add a follow-up to an open question. It arrives the same way, as `"event": "followup"` with its `text` and `seq`. Answer it:

```bash
agt inbox reply ib-xxxx --text "Yes, CI ran on the merge commit."
agt inbox wait ib-xxxx --after <seq>    # only if you are waiting in the foreground
```

## Change or cancel a question

```bash
agt inbox revise ib-xxxx --control '{"type": "choice", "options": [...]}'   # new options
agt inbox withdraw ib-xxxx                  # no longer needed
agt inbox supersede ib-xxxx --by ib-yyyy    # a newer question replaces it
agt inbox get ib-xxxx                       # current state and answer, as JSON
```

## Post

A post is information, with no answer. It takes the same `title`, `summary`, `detail`, `html` and `priority` (default `low`, no push), and no control.

```bash
echo '{"title": "Nightly run: 3 tasks done, 1 blocked", "summary": "..."}' \
  | agt inbox post --engine claude --session-id "$CLAUDE_CODE_SESSION_ID"
echo '{"title": "Backup finished", "summary": "..."}' | agt inbox post --script nightly-backup   # a script with no session
```
