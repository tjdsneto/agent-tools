# Agent Inbox — Design

**Date:** 2026-11-23
**Status:** Approved for planning
**Repo:** `agent-tools` (new module `modules/inbox`, CLI `agt inbox`)
**Approach:** One Postgres store, one CLI as the only door to it, one long-running `serve` process for the web UI and answer delivery. Hermes and every other surface are thin callers of the CLI.

## Problem

Agents need Tiago's input, and today they only get it while they are still running: `visual-ask` serves a local page while the session waits, and `agt say` shows a blocking macOS dialog. When the asking agent has exited, or Tiago is away from the laptop, the question is lost. Agents also have no shared place to leave information for him (a summary, a run result) that he can read later and ask about.

The inbox is a standalone, persistent place where any agent can ask Tiago anything or leave him information, and where his answer gets back to the agent that asked, even after that agent has exited.

## Goals

1. **Standalone.** Any agent or script can use it. It knows nothing about its clients (the ana backlog system is one client among others).
2. **Answers reach the asker.** Every question records the asking session's engine, model and session id. The answer is delivered to that session: into the live session when it is running, by resuming it when it is not.
3. **Structured answers.** The inbox draws the controls itself, and the answer returns in a fixed, machine-readable shape. The same question renders as a web form or a Telegram message.
4. **Visual and layered.** A card readable in seconds, then the argument and evidence, then full detail. Usable from the phone.
5. **Conversation.** Tiago can ask follow-ups on any entry, and the asking agent answers them.
6. **Live.** The UI updates and delivery happens on change, without polling (Postgres `LISTEN/NOTIFY`).

## Non-goals

- Extending `agt say`. It is the agent's voice and stays separate.
- Slack.
- Multi-field forms. One question per entry.
- Number, date, or file-upload controls.
- Inferring the asking session from process or working directory.
- Writing answers back into a client's own files. The inbox only messages the origin session; the agent does the rest.
- Starting a fresh session when the original cannot be reached.
- Batch answering.
- Public exposure. Never Tailscale Funnel.
- A store or UI host other than this laptop. The store is reached through a database URL, so moving it later is a config change.

## Architecture

```
agents / scripts ──► agt inbox (CLI) ──► Postgres (agent_inbox)
Hermes (inbox skill) ──►     ▲                  │ NOTIFY
                             │                  ▼
                    agt inbox serve ── web UI (tailscale serve, tailnet only)
                         │   ├─ dispatcher ──► agt registry wake <session>
                         │   └─ notifier ───► hermes send (Telegram), macOS notification, agt read voice (opt-in)
                         └─ reachability ◄── claude-budget, registry usage (rate-limit detection)
```

- **Store:** Postgres, owned by the inbox. The CLI is the only code that opens it. `serve` uses the same library code as the CLI.
- **`agt inbox serve`:** one process started at login (LaunchAgent). It serves the UI, listens for changes, delivers answers and follow-ups, and sends notifications.
- **Delivery:** reuses `agt registry wake`, which already sends a message into a live session or resumes an exited one for Claude Code, Codex and Cursor.
- **Token availability:** reuses `claude-budget` (Claude account windows) and the registry's per-session rate-limit detection (Codex, Cursor).
- **Hermes:** runs on this laptop and calls the CLI directly.

## Entry kinds

| Kind | Command | Has a control | Needs a session | Ends when |
|---|---|---|---|---|
| Question | `agt inbox ask` | yes | yes | answered and delivered, or expired / withdrawn / superseded |
| Info | `agt inbox post` | no | optional | archived |

Info entries cover anything an agent or script wants Tiago to see without a question: summaries, run results, alerts. The UI does not name them "reports"; its filter is **Needs answer / Info / All**.

## Entry fields

| Field | Notes |
|---|---|
| `id` | Short and typeable, e.g. `ib-7k3q`. |
| `kind` | `ask` or `post`. |
| `created_at`, `updated_at` | |
| `asker` | `engine`, `model`, `session_id`, `cwd`, `project` (git root of `cwd`). For `post` without a session: `script` name instead. |
| `priority` | `urgent`, `normal`, `low`. Default `normal` for `ask`, `low` for `post`. |
| `mode` | `wait` or `resume` (`ask` only). |
| `title` | One line. The card. |
| `summary` | Markdown. Layer 2: the argument and evidence. |
| `detail` | Markdown. Layer 3: files, diffs, links. |
| `html` | Optional, at most 2 MB. Layer 2 visual reference. |
| `control` | `ask` only. See Controls. |
| `source` | Optional opaque `{kind, ref, url}`, for display and grouping only. |
| `expires_at` | Optional. |
| `state` | See Lifecycle. |
| `answer` | `{value, comment, via, at}`. |
| `thread` | Follow-ups and agent replies, in order. |
| `revisions` | Log of `revise` changes to the control. |
| `delivery` | Attempts, results, last reachability. |

## Controls

One control per question, plus an optional comment box on every question.

| Type | Value returned | Telegram |
|---|---|---|
| `choice` | one option id (2–6 options) | one button per option (⭐ marks the recommended one) |
| `multi` | list of option ids | numbered list, reply with numbers |
| `text` | string (`short` or `long`) | reply with the text |
| `approve` | `approve`, or `revise` plus a required reason | an Approve button; reply "revise: …" |

Each option has `id`, `label`, optional `description`, and may be marked `recommended` or `default`.

## Lifecycle

**Question:** `open → answered → delivered`. Also `expired` (past `expires_at`), `withdrawn` (the agent cancels it), `superseded` (the agent replaces it with a newer entry), and `undelivered` (answered, delivery gave up).

**Info:** `unread → read → archived`. Opening it marks it read; nothing is sent to the agent.

**One answer per question.** The first answer from any surface wins. The entry is marked answered, and every other surface shows it as answered, with the value and where it came from.

## Asking

`agt inbox ask` requires `--engine` and `--session-id`, and records `--model` when given; it fails when either required flag is missing. The skill tells agents where to find them.

- **wait:** block until an answer, a follow-up, or a timeout (default 30 min). A follow-up returns `{"event":"followup",…}`; the agent replies, then calls `agt inbox wait <id>` again. On timeout the command returns `timeout`, and the entry stays open and switches to `resume`, so a late answer still reaches the agent.
- **resume:** the agent exits. The answer arrives through delivery. No expiry unless `--expires` is set.

## Reachability

Each question shows whether its session can hear a message now:

| Status | Meaning | Answering |
|---|---|---|
| 🟢 live | The session is running and can take a message. | allowed |
| 🔵 resumable | The session has exited and can be resumed. | allowed |
| 🟡 held | The session has no tokens: the Claude window is saturated (`claude-budget`). Codex and Cursor have no token reader (the registry's rate-limit detection reads Claude transcripts only), so they count as held only when their last wake came back held. Shows "answerable at ~HH:MM" when the reset time is known. | disabled |
| 🔴 unreachable | No transport, the session is gone, or delivery gave up. | disabled; dismiss only |

When the window resets, entries that were 🟡 become answerable again, and one batched push says so ("3 entries are answerable again"), at the entries' priority and within quiet hours.

## Delivery

The dispatcher wakes on `NOTIFY` and calls `agt registry wake <session_id> --message <file>`.

- While an `ask --wait` or `wait` command is attached to the entry, delivery is that command returning. The dispatcher does not wake the session. If the waiting command dies (the agent was killed), the entry falls back to resume delivery.
- A live session gets the message in place. An exited one is resumed.
- **Cursor** has no way to take a message into a live chat. Its delivery is always a separate headless run, shown as "delivered (headless)".
- An exited Claude session resumes with `--dangerously-skip-permissions`, as waker already does. The resumed agent acts on the answer unattended. Accepted risk.
- Before a resume, the dispatcher checks token availability. With no tokens, delivery is held and retried at the reset.
- On failure: retry up to 3 times, then mark `undelivered` and show it in the UI. The answer stays readable with `agt inbox get <id>`.

Message shape (answers and follow-ups alike):

```
Inbox answer for ib-7k3q ("Which split?"): b — "Tauri plus tray api"
Comment: keep the menu bar thin
{"entry":"ib-7k3q","event":"answer","value":"b","comment":"…","via":"web","at":"…"}
Full entry: agt inbox get ib-7k3q
```

## Follow-up conversation

Every entry has a thread, questions and info alike.

- Tiago posts a follow-up. It is delivered to the origin session like an answer, under the same reachability rules.
- The agent replies with `agt inbox reply <id> --text … [--html …]`.
- The agent may `agt inbox revise <id>` the control, for example adding the option Tiago asked about. The entry stays the same, and the change is logged.
- A follow-up never closes a question. Only an answer does.
- An info entry posted without a session has no follow-up box.

## Notifications

| Priority | Push | Channels |
|---|---|---|
| `urgent` | immediate, at any hour | Telegram, macOS notification; `agt read` voice if opted in (`AGENT_INBOX_SAY=1`) |
| `normal` | batched, at most one push per 15 min, daytime only | Telegram |
| `low` | none | UI only |

Quiet hours are 22:00–08:00: only `urgent` gets through. Any agent may set `urgent`. Every use is logged, and the UI shows a per-agent count.

## Web UI

- Served with `tailscale serve`, on the tailnet only. The server accepts only requests whose Tailscale login header is `tjdsneto@`.
- Server-rendered pages, with a small script that refreshes the page on change (server-sent events). Built to load fast on the phone.
- One feed per project (the git root of the asker's `cwd`). Open questions are pinned on top, unread info below, then the rest. Within a group: urgent first, then oldest first.
- Filters: kind (Needs answer / Info / All), engine, agent, state. A separate history tab for closed entries.
- Batch actions: withdraw and dismiss only.
- Each entry opens in layers: card → summary and HTML frame → detail and source link.

### HTML frame

- Served from a separate origin, inside a sandboxed iframe that allows scripts but not same-origin access, top-level navigation, or forms that post to the inbox.
- Network access is allowed (external assets, fonts, charts).
- Links open in a new tab.
- Labelled "Reference only. Answer below." The frame cannot record an answer; only the inbox's own controls can.
- Known risk: a page could draw a fake form and send what is typed to the internet. Accepted, because entries come only from Tiago's own agents.

## Hermes and Telegram

- The notifier pushes the card with `hermes send`: the title, priority, project, numbered options, and a link to the entry in the UI.
- Choice and approve cards go out instead through `hermes inbox-card`, from the `inbox-buttons` Hermes plugin (`modules/inbox/hermes-plugin/`), one message per question with inline buttons. The plugin sends with the gateway's own bot token, so the inbox never holds it. A tap with callback data `ib:<id>:<value>` runs `agt inbox answer … --via telegram` without a model call, after the plugin checks the sender against the gateway's allowlist. The store's answer rules still apply: a refused tap shows the reason, and a held question keeps its buttons. When the plugin send fails, the card falls back to `hermes send` with a numbered list.
- Tiago replies in the Hermes chat ("1", "approve ib-7k3q", "? why not C"). A Hermes `inbox` skill turns the reply into `agt inbox answer … --via telegram` or `agt inbox followup … --via telegram`.
- When an entry is answered on another surface, Telegram gets a short note: "ib-7k3q answered via web: b".
- Hermes runs on this laptop and calls the CLI directly, with no network auth.

## Store and operations

- Homebrew `postgresql@17`, run as a login service (`brew services`) on port 5433. Database `agent_inbox`. Default URL `host=localhost port=5433 dbname=agent_inbox`. Port 5432 is Docker `am-video-db` and is not used.
- This is the repo's first non-stdlib runtime dependency: the `psycopg` driver.
- Nightly `pg_dump` to `~/.local/share/agent-inbox/backups/`, keeping the last 14.
- Retention: entries, threads and answers are kept forever. The HTML part is deleted 90 days after an entry closes.
- The laptop is treated as always on.

## CLI

| Command | Who calls it | Does |
|---|---|---|
| `ask` | agent | Create a question. `--wait` blocks; otherwise it returns the id. |
| `wait <id>` | agent | Block again after a follow-up or a timeout. |
| `post` | agent, script | Create an info entry. |
| `get <id>` | anyone | Print the full entry as JSON. |
| `list` | anyone | Filtered list, as JSON or a table. |
| `answer <id>` | UI, Hermes | Record the answer (`--via`). |
| `followup <id>` | UI, Hermes | Add Tiago's follow-up to the thread (`--via`). |
| `reply <id>` | agent | Add the agent's reply to the thread. |
| `revise <id>` | agent | Change the control; logged. |
| `withdraw <id>` | agent, UI | Cancel a question. |
| `supersede <id> --by <id>` | agent | Replace a question with a newer one. |
| `read` / `archive <id>` | UI | Info entry state. |
| `serve` | LaunchAgent | UI, dispatcher, notifier. |

Exit codes and JSON output follow the conventions of `agt registry` and `agt say`.

## Relationship to existing tools

- **`visual-ask`** becomes a thin wrapper: `agt inbox ask --wait --html <fragment>`, then it opens the entry's URL. Its "when to use" guidance stays. Its local server goes away.
- **`agt say`** stays separate. The optional voice channel for `urgent` is `agt read --background`, because `agt say` is a blocking dialog.
- **`agt registry wake`** and **`claude-budget`** are reused for delivery and token availability.

## Failure rules

- Postgres down: `ask` and `post` fail loudly with a non-zero exit. No fallback file.
- `serve` down: entries are still created. Delivery and notifications catch up when it starts, because pending work lives in the store.
- Delivery failure: up to 3 retries, then `undelivered`.
- Missing `--engine` or `--session-id` on `ask`: an error, never a guess.

## Parked

- Moving the store and UI to an always-on host.

## Defaults this design locks

| Default | Value |
|---|---|
| wait timeout | 30 min, then the entry switches to resume |
| options per `choice` | 2–6 |
| HTML size cap | 2 MB |
| HTML retention after close | 90 days |
| delivery retries | 3 |
| `normal` push batching | at most one per 15 min |
| quiet hours | 22:00–08:00 |
| backups kept | 14 nightly |
