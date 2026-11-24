---
name: agent-inbox
description: Use whenever you need a decision, approval or answer from Tiago, or want to leave him a report. Ask through `agt inbox` and ask the same question in the chat; whichever way he answers, record it so both sides agree. The inbox delivers its answers back to this session, even after it exits.
---

# agent-inbox

The inbox is where agents leave Tiago questions and reports. He answers on its web page (or by Telegram, for urgent ones), and the inbox delivers the answer back to the session that asked: a message into a live session, or a resume of one that exited.

## When to use it

- Every question that needs Tiago's decision goes through the inbox, whether or not he is watching this chat. He may answer from his phone instead.
- Use a post for a result he should read later: a run summary, what you found, what is blocked.
- Do not ask about something you can decide yourself or look up.

## Ask in both places

1. Ask through the inbox (below) and keep the `entry` id and the `url` it prints.
2. Ask the same question in the chat, in plain text: the question, the options with their ids, and the link to its page, so he can answer either way. Do not use a blocking question tool (such as AskUserQuestion) for it: an inbox answer cannot close that dialog.

   ```
   Merge the registry refactor before the inbox restart?
   - merge: Merge now, then restart (recommended)
   - restart: Restart first, merge after
   Answer here, or in the inbox: https://…:8444/e/ib-xxxx
   ```
3. End your turn.

Then exactly one of these happens:

- **He answers in the chat.** Record it, so the inbox, its page and Telegram show it as answered:

  ```bash
  agt inbox answer ib-xxxx --value <option id> --via chat          # --comment "..." for anything else he said
  ```

  A chat answer is marked delivered at once; nothing is sent back to you. If this fails with `already answered via telegram: ...` (or `via web`), he answered there first: that answer wins, so use it and tell him in the chat.
- **He answers in the inbox or on Telegram.** The answer arrives in this chat as a message (see "After asking"). Say in one line what he answered and carry on. Do not record it again.

For `multi`, repeat `--value` once per option. For `text`, `--value` is his words. For `approve`, `--value approve`, or `--value revise` with his reason in `--comment`.

Cursor: the inbox cannot reach an open Cursor chat. An inbox answer resumes the conversation as a separate headless run, so in Cursor the chat answer is the reliable path while he is at the IDE.

## Who is asking

Pass your engine and your own session id, so the answer can find you. Read the id from the environment, never guess it from the directory:

| Engine | `--engine` | `--session-id` |
|---|---|---|
| Claude Code | `claude` | `$CLAUDE_CODE_SESSION_ID` |
| Codex | `codex` | `$CODEX_THREAD_ID` |
| Cursor | `cursor` | `$CURSOR_CONVERSATION_ID` |

An ask needs `--engine` and `--session-id`. The one exception is an asker that should never be woken, such as a script or an orchestrator that resumes its own agents: it passes `--script <name>` instead, and either blocks with `--wait` or reads the answer later with `agt inbox get <id>`.

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

It prints `{"entry": "ib-xxxx", "state": "open", "url": "https://…/e/ib-xxxx"}`. Keep the id and the link.

Controls:

- `{"type": "choice", "options": [...]}`: pick one. 2 to 6 options, each `{"id", "label"}`, optional `"description"`, `"recommended": true`, `"default": true` (one at most). Telegram shows these as buttons.
- `{"type": "multi", "options": [...]}`: pick several. Same options.
- `{"type": "text", "size": "short"}` or `"long"`: free text.
- `{"type": "approve"}`: Approve, or Revise with a required reason in the comment. Telegram shows an Approve button.

Optional fields:

- `summary` and `detail` render as Markdown. Raw HTML in them is shown as text.
- `html` is an attachment shown in a sandboxed frame, as reference only. Pass a file with `--html-file`.
- `priority`: `normal` (default) waits in the inbox with no push. `urgent` pushes a Telegram card at once, day or night: Telegram is for emergencies, so use it only when something is broken or blocked and cannot wait for him to look. `low` is for posts nobody needs to see soon.
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

A post is information, with no answer. It takes the same `title`, `summary`, `detail`, `html` and `priority` (default `low`), and no control. Only an `urgent` post reaches Telegram.

```bash
echo '{"title": "Nightly run: 3 tasks done, 1 blocked", "summary": "..."}' \
  | agt inbox post --engine claude --session-id "$CLAUDE_CODE_SESSION_ID"
echo '{"title": "Backup finished", "summary": "..."}' | agt inbox post --script nightly-backup   # a script with no session
```
