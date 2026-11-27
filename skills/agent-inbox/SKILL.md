---
name: agent-inbox
description: Use whenever you need a decision, approval or answer from Tiago, or want to leave him a report. Ask through `agt inbox` and ask the same question in the chat; whichever way he answers, record it so both sides agree. The inbox delivers its answers back to this session, even after it exits.
---

# agent-inbox

The inbox is where agents leave Tiago questions and reports. He answers on its web page (or by Telegram, for urgent ones), and the inbox delivers the answer back to the session that asked: a message into a live session, or a resume of one that exited.

## When to use it

- Every question that needs Tiago's decision goes through the inbox, whether or not he is watching this chat. He may answer from his phone instead. The one exception is the `conversation` skill's drift ask (fork / park / keep here), which stays a plain chat line.
- Use a post for a result he should read later: a run summary, what you found, what is blocked.
- Do not ask about something you can decide yourself or look up.

## Ask in both places

1. Ask through the inbox (below) and keep the `entry` id and the `url` it prints.
2. Ask the same question in the chat as a decision card, the short form the `conversation` skill defines: its topic, the question, why it matters, the option ids with one-letter aliases, your recommendation, what you do next, and the link to its page, so he can answer either way. At most two cards per reply; any more are asked in the inbox only (see `conversation`). Do not use a blocking question tool (such as AskUserQuestion) for it: an inbox answer cannot close that dialog.

   ```
   - F1. *Registry refactor › Deploy order.* Merge the registry refactor before the inbox restart? CI is green; restarting first keeps the old board until the next deploy. Answer `merge` (m) or `restart` (r). Recommended: `merge`, because one restart picks up both. Next: merge, then restart the inbox. https://…:8444/e/ib-xxxx
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
- `topic`: a topic id (`tp-xxxx`, from `agt registry topics`). You rarely need it: with `--engine` and `--session-id` the inbox records your session's intent and topic by itself, and shows them on the entry. Any asker can pass it to file the question under that discussion, and it wins over your session's own topic. An unknown id is exit 1.

Write for a phone, and for a page that is all he has. The title is the question. The summary is two or three sentences on what happened and why it matters. The thing he is judging — the prompt, the diff, the wording, the list — goes in `detail`, in full. A file path, a backup, an issue number, or a one-line note about a changelog is not that thing: he cannot open them from the inbox. Spell an id out so he knows what it is, and still include the part the decision turns on. Every option label stands on its own. Together, the summary and detail are the card's long form (what happened, why it matters, the material, the options, the recommendation, what happens next either way), as the `conversation` skill describes.

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

Tiago can add a follow-up to an open question. It arrives the same way, as `"event": "followup"` with its `text` and `seq`. Answer an ordinary follow-up with a reply.

A follow-up that says he cannot answer from the page, or that asks for the missing material or a simpler version, means the entry failed. Update this same entry (below). Put the missing material in `detail`, and rewrite `summary` when he asked for a simpler version. Do not point at a file, and do not open a second question. `revise` only changes the choices. A thread reply does not change the page he is looking at.

```bash
agt inbox reply ib-xxxx --text "Yes, CI ran on the merge commit."
agt inbox wait ib-xxxx --after <seq>    # only if you are waiting in the foreground
```

## Unattended agents

An unattended agent runs with no chat and must never be woken by the inbox: for example, an agent the ana autopilot starts with `claude -p`. A wake resumes the session with its saved launch flags, or with `--dangerously-skip-permissions` when none were saved, which can drop the tool limits its launcher gave it. So it asks differently:

- Ask with `--script <name>` (ana uses `--script autopilot`) and pass neither `--engine` nor `--session-id`. The inbox wakes any ask that carries a session id, even with `--script`.
- Skip "Ask in both places": there is no chat to ask in, so ask only in the inbox.
- **The task cannot go on without the answer:** add `--wait`. Exit 0 with `"event": "answer"` is the answer. Exit 0 with `"event": "followup"` is a follow-up: if it asks for the missing material or a simpler version, `agt inbox update` (see "Update a question"), otherwise `agt inbox reply`, then `agt inbox wait <id> --after <seq>`. Exit 4 means the question closed (expired, withdrawn or superseded). Exit 5 is the timeout: the question stays open. Write the entry id in your report and end; whoever launched you resumes you once `agt inbox get <id>` shows `answered`.
- **The task can go on without it:** ask without `--wait`, write the entry id in your report and carry on. A later run reads the answer, and any follow-up left in the thread, with `agt inbox get <id>`.

A good question is the same either way: one decision per question, the thing being judged in the entry (see "Write for a phone" above), the options with their ids, your recommendation marked `recommended`, and the reason in the summary.

## Update a question

More info and Simplify on the question page send a follow-up and leave the question open. The page he is reading changes only when you update the entry. Send the new text as JSON on stdin. A field you omit stays as it is. Title, summary, and detail must be text; title is one line. Html is the sandboxed attachment, from the JSON or from `--html-file`.

```bash
cat <<'JSON' | agt inbox update ib-xxxx
{"detail": "the text he is judging, in full", "summary": "the short version, rewritten"}
JSON
```

It prints `{"entry", "event": "update", "fields"}`. The question stays open. A closed question is a conflict: the page he would have read is already gone.

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
