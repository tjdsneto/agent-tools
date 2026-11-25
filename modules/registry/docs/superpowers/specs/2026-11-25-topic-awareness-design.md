# Topic awareness — design

Approved 2026-11-25 in brainstorming. First of three specs; the next two (topic-aware inbox, topic graph view) build on the log defined here.

## Goal

Every AI session knows its **intent** and its current **topic**. The intent is fixed for the session's life. The topic changes under it. When a new thread doesn't fit the intent, or fits it but is a side quest that can be split off, the agent asks Tiago in one line whether to fork it into its own visible session, park it, or keep it here. The registry keeps each session's topic history, so the registry gives an overview of what every session has handled.

Why: Tiago runs many sessions at once. A long session that drifts through several threads makes him lose track when he comes back to it. Splitting side threads into their own sessions keeps each context small and each session about one thing.

## Decisions taken

| Question | Decision |
|---|---|
| What a topic is | Its own record with a global id, a title, a parent and a status. The intent is the root topic; topics are its children. |
| On drift | The agent asks each time, one line, defaulting to fork. |
| Who owns the records | The agent registry. |
| Log layout | One append-only log per session. |
| How the agent keeps track | A hook reminds it on every prompt, plus a skill. The hook lives in this repo's registry plugin. |
| What fork does | The agent starts the child session itself, and the child must be visible to Tiago: a Cursor tab or a Herdr pane. |

## Out of scope

- Inbox entries carrying a topic, and the feed grouped by topic (spec 2).
- The graph view (spec 3).
- A local model classifying drift. That's the fallback if the hook reminder proves too weak.

## 1. Topic log

**Location.** Next to the live registry file: `<registry dir>/topics/<type>/<session_id>.jsonl`. With the default path that is `~/.local/share/agent-registry/topics/claude/<uuid>.jsonl`. Because it follows `AGENT_REGISTRY_PATH`, tests stay isolated. Prune, unregister and replace never touch it.

**Ids.** `tp-` plus 4 random characters from the inbox's alphabet, globally unique. The registry checks for a collision across all logs when it mints an id. A topic is found by its id by scanning the logs, which is fine at one person's scale.

**Events.** One JSON object per line. Every line has `event`, `at` (ISO time with offset), and `topic` (`{id, title}`):

| `event` | Extra fields | Meaning |
|---|---|---|
| `intent` | | Mints a root topic and binds the session to it. Allowed once per session (`intent` or `adopt`, not both). |
| `adopt` | `from_session` | Binds the session to an existing topic as its intent. A forked child does this on start. |
| `topic` | `parent` (the intent's id) | Opens a child topic. It becomes the current topic. |
| `done` | | Closes a topic. |
| `parked` | `ref` (the `park` id, when parked through `park`) | Sets a topic aside, unfinished. |
| `forked` | `side` or `new_intent`, `backend`, `brief` (path) | A topic handed to a new session. |

A topic's status is the last of `done`, `parked` or `forked` recorded for it. With none of those, it is open.

**Live entry.** The live registry row gains `intent` and `topic`, each `{id, title}` or null. `list` and the board show them. `summary` stays as it is: it is still the free-text focus line.

**Writes** take the registry's existing file lock, so two hooks or commands writing at once don't corrupt a log.

## 2. CLI (`agt registry …`)

The session comes from the hook sidecar, as with `self`: `--type` and `--session-id`, defaulting to the env ids the agent-inbox skill uses (`CLAUDE_CODE_SESSION_ID`, `CODEX_THREAD_ID`, `CURSOR_CONVERSATION_ID`).

```
agt registry intent "Make inbox entries topic-aware"     # exit 4 if this session already has one
agt registry intent --adopt tp-7k3q                       # forked child binds to its topic
agt registry topic "Decide where topic records live"      # opens a topic under the intent; exit 1 if no intent
agt registry topic --done [tp-…]                          # default: the current topic
agt registry topic --park [tp-…] [--ref park-id]
agt registry topics                                       # this session's history
agt registry topics --session <id> | --open | --tree      # one session, every open topic, the cross-session tree
agt registry fork "Retry policy for wake" (--side | --new-intent) [--backend cursor|herdr|none] [--dir D] [--brief-file F]
```

Every command prints JSON on stdout and diagnostics on stderr, like the rest of `agt registry`. Exit codes are the registry's existing 0 ok, 1 usage, 2 not found and 3 I/O, plus a new 4 for a conflict (`EXIT_CONFLICT`, same meaning as the inbox's 4).

## 3. Prompt hook

The reminder is added to the existing `plugin/scripts/registry-hook`, so `plugin/install` deploys it with the hooks already in place.

- **On prompt (Claude Code `UserPromptSubmit`, Codex `UserPromptSubmit`):** `ping` also prints the additional-context JSON, with one line:
  - with an intent: `Intent: <title> · Topic: <title or none>. If this prompt changes the subject, run the topic-awareness drift check.`
  - without one: `No intent set for this session. Once the first prompt makes it clear, set it: agt registry intent "<title>".`
- **On session start:** `ensure` adds the same line to the SessionStart context it already prints.
- **Cursor's own agent:** its `beforeSubmitPrompt` can only return `continue` and `user_message` (Cursor forum, 2026), so the line goes only in the `sessionStart` `additional_context`, which has reported bugs. This is a known limit. Claude Code running inside Cursor uses Claude Code's hooks and is not affected.
- The hook still fails open: if the registry or the log can't be read, it prints no line and exits 0.

## 4. Skill `topic-awareness`

`skills/topic-awareness/SKILL.md`, linked by `install.sh` into Claude Code, Cursor and Codex like `agent-inbox`.

- Set the intent once the first prompt makes it clear: one line, the outcome the session exists for.
- Open a new topic when the main line moves on. Mark a topic done when it is done.
- **Drift check**, run only when the work changes subject (a prompt, or the agent's own work):

| The new thread is… | Then |
|---|---|
| on-intent and on the main line | `agt registry topic …` and keep going |
| on-intent, but a side quest that can be split off (independent, likely more than a few turns) | ask: fork / park / keep here (default fork) |
| off-intent | ask: fork as a new intent / park / keep here (default fork) |

- The ask is one line of plain chat text, not a blocking question tool: `Side quest: retry policy for wake. Fork / park / keep here?`
- Fork means running `agt registry fork` with a brief. Park means running `park`, then `agt registry topic --park --ref`. Keep here means opening it as a topic in this session.
- When every topic under the intent is done, say so and suggest ending or clearing the session.
- A child session started by a fork begins with `agt registry intent --adopt <id>` and reads its brief.

## 5. Fork launcher

`agt registry fork`:

1. Mints the child topic and writes a `forked` event for it to the parent session's log. Its `parent` is the parent session's current topic (or its intent, when no topic is open). `--side` and `--new-intent` record whether the child continues the parent's intent or starts its own; the lineage link is the same either way. The child session later adopts this topic as its intent.
2. Writes the brief to `<registry dir>/briefs/<tp-id>.md`: the parent intent, why the thread was forked, what is known so far, and what done looks like. The text comes from `--brief-file` or stdin, which the agent writes.
3. Launches a visible session in `--dir` (default: the parent's directory). The prompt in every backend is: `Read <brief path>, run agt registry intent --adopt <id>, then continue.`
   - **`cursor`** (default outside Herdr): runs `cursor <dir>` to bring that project's window forward, then opens `cursor://anthropic.claude-code/open?prompt=<prompt>`. Tested 2026-11-25: the tab opens with the prompt filled in and is not sent. Tiago presses Enter. The first use asks him to allow the extension to open the link.
   - **`herdr`** (default when the parent runs inside a Herdr pane, which is detected from the pane's environment; the exact variable is confirmed while building, via `herdr pane current`): splits a pane, starts the same engine as the parent, and submits the prompt. Fully automatic.
   - **`none`**: prints the prompt and the brief path only. Used by tests, and when no visible backend is available.
4. Prints `{topic, brief, backend, launched}`. The child's session id is not known yet. The child's `adopt` event links the two once it starts.

## 6. Testing

Unit tests sit beside the existing ones in `modules/registry/tests/`. The **black-box suite** is the part left behind for re-checking this feature. It touches only the public surfaces: `agt` commands, the hook script fed hook JSON on stdin, and the files on disk. It never imports the package.

**Tier 1, `tests/blackbox/test_topics_cli.py`.** Fast, needs no agent, run with `pytest tests/blackbox/test_topics_cli.py`. Each test uses a temp `AGENT_REGISTRY_PATH`.

- intent → topic → done → topics: the history comes back in order, and the statuses are right.
- A second `intent` on the same session exits 4. `topic` with no intent exits 1. `--done` on an unknown id exits 2.
- `topics --open` and `--tree` across two sessions, one forked from the other with `--backend none`, followed by `--adopt` in the second.
- Two concurrent writers to one session's log: no lines lost and none corrupted.
- The hook: feed `registry-hook claude ping` and `codex ping` a prompt payload. With and without an intent, the context line matches. With an unreadable log, nothing is printed and the exit is 0. `cursor ping` still prints only `{"continue":true}`.
- Prune and unregister leave the topic log in place.

**Tier 2, `tests/blackbox/test_topics_agent.py`.** A real `claude -p` session on a temp registry with the plugin hooks, following the pattern of `test_claude_board.py`. Not collected by default; run it explicitly.

- First prompt with a clear goal: the session's log gets an `intent` event.
- A second prompt that is clearly off-intent: the reply contains the fork / park / keep ask, and no `topic` event is written for it.
- The same with `codex exec` when `codex` is on PATH; skipped otherwise.

**Manual checklist, `tests/blackbox/MANUAL.md`.** For what automation can't see: the Cursor tab opens in the right project window with the prompt filled in; the Herdr pane starts and runs the prompt; the child adopts its topic and shows up under its parent in `topics --tree`.

## Risks

- **Which Cursor window gets the tab.** Bringing the project window forward with `cursor <dir>` first is untested. If it doesn't work, a fork can land in another project's window. The manual checklist covers it.
- **Agents skipping the drift check** despite the reminder. Watch it in real use. The fallback is the local-model classifier.
- **Codex context injection** is going by the docs and third-party code; tier 2 is what confirms it.
