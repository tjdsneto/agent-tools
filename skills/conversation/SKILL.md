---
name: conversation
description: How to talk to Tiago, in every session. Its core (intent and topics, decision cards two at a time, the reply ending, density) is injected at session start. Load this full skill before forking or parking a thread, asking through the inbox, orchestrating other agents, or when a hook line names the conversation drift check.
---

# conversation

Tiago runs many sessions at once and comes back to each one after hours away. Everything here exists so he can pick a session up without scrolling: one intent per session, a named topic under it, and decisions that carry their own context.

`CORE.md`, in this skill's directory, is the always-on part. The agent-tools session-start hook injects it into every session. If it is not in your context (an engine that couldn't inject it), read `CORE.md` now. Everything below is the detail it points to.

## Intent and topics in detail

Each prompt starts with a line from the hook:

```
Intent: Make inbox entries topic-aware (tp-7k3q) · Topic: Decide where topic records live (tp-9m2c) · 1 open question. If this prompt changes the subject, run the conversation drift check.
```

or, in a new session, `No intent set for this session. …`. The open-question count appears only when inbox questions asked under the current topic are still waiting.

Subagents don't use this skill. They share the parent session's id, so their topic commands would write to the parent's log. Only the main session sets the intent, opens topics and forks.

Session identity comes from your environment (`CLAUDE_CODE_SESSION_ID`, `CODEX_THREAD_ID`, `CURSOR_CONVERSATION_ID`), so these commands need no flags.

### Set the intent once

As soon as the first prompt makes clear what the session is for, set the intent: one line, the outcome the session exists for.

```bash
agt registry intent "Make inbox entries topic-aware"
```

A session has one intent. If the work turns into something else, that is a new session, not a new intent. If the hook line already shows an intent, leave it alone.

A session started by a fork reads its brief and adopts its topic first, as its prompt says:

```bash
agt registry intent --adopt tp-xxxx
```

### Name the topic you're on

When the main line moves to a new step, open it as a topic. When it is finished, mark it done. Open and close topics silently; they're for the registry, not the chat.

```bash
agt registry topic "Decide where topic records live"
agt registry topic --done
```

`topic --done` also prints `open_questions`: the ids of inbox questions you asked under that topic that are still waiting for Tiago. If the list isn't empty, withdraw each one you no longer need (`agt inbox withdraw ib-…`), or say in one line of chat which ones are still waiting and why. Answered, withdrawn, superseded and expired questions normally don't show up there, but the note is best effort, so a question can still be listed after it was answered. If `agt inbox withdraw` fails with "already answered" or a conflict, it was already settled: move on.

### Drift check

Run it only when the work changes subject, not when it takes another step toward the same goal. A bug found along the way, a follow-up question, or a retry is the same thread. When you can't tell, treat it as the main line: open a topic and don't ask.

| The new thread is… | Then |
|---|---|
| on the intent's main line | `agt registry topic "…"`, keep going |
| on-intent, but a side quest that can be split off (independent of the main line and likely more than a few turns) | ask: fork / park / keep here |
| off-intent | ask: fork as a new intent / park / keep here |

If the work would still make sense without the rest of the intent, it's a side quest. If it moves the intent forward, it's the main line.

Ask in one line of plain chat text, with fork as the default. Then end your turn. Don't start the new thread, fork, park or open a topic until he answers. If the same prompt also asked for main-line work, do only that part. Do not use a blocking question tool.

Copy the intent title from the hook line. Don't paraphrase it. That title is the fact he checks the call against. Follow it with one clause of why, which is your read and can be wrong. No second sentence.

A side quest:

```
Side quest: retry policy for wake, under Make inbox entries topic-aware. It can be decided without the rest of that work. Fork / park / keep here? (fork)
```

Off the intent:

```
This session is for Make inbox entries topic-aware. A retry policy for wake doesn't serve that: it's a separate outcome. Fork as a new intent / park / keep here? (fork)
```

A bare ok or go means the default, fork. If the reply is unclear, ask once more.

A drift ask is the exception to the inbox rule below: ask it in chat only, never through the inbox. It's a quick steer, and a late inbox answer would resume you on a thread that has already moved on.

### When the intent is done

When the outcome the intent names is met, mark the current topic done, then say so in one line and suggest ending or clearing the session. Don't start new work in it.

### Look around

```bash
agt registry topics           # this session's history
agt registry topics --open    # every open topic, every session
agt registry topics --tree    # the topic tree across sessions, forks included
```

Tiago reads the same tree on the inbox's Topics tab, with each topic's questions and each session's state, so a short, specific intent and topic title is what he scans there.

## Density in detail

The density rules in `CORE.md` came from replies that followed every structural rule and were still status reports: a body of six "here's what I did" bullets, 20 bare issue numbers, field names in code formatting, and a card with a nested list, repeated unchanged from the reply before. `tests/fixtures/` keeps two of those replies and the same reply rewritten to the rules.

To measure a draft, or a reply from another session, run `scripts/check-density < reply.md` (add `--previous last.md` to catch a repeated card). It counts list items, words and code spans above the ending, distinct ids, and lines under cards, and exits 1 when one is over its limit. The limits are rough: a pass means none of those habits showed up, not that the reply reads well.

## Forking and parking

Do what he chose:

- **Fork.** Write a brief and hand it off. The brief covers the parent intent, why the thread was split off, what is known so far, and what done looks like. Use `--side` for a side quest and `--new-intent` for an off-intent thread.

  ```bash
  cat <<'MD' | agt registry fork "Retry policy for wake" --side
  # Retry policy for wake
  Parent intent: Make inbox entries topic-aware (tp-7k3q).
  Why forked: independent of the inbox work; needs its own investigation.
  Known: three failed wakes mark an entry undelivered (modules/inbox/src/agent_inbox/dispatch.py).
  Done when: a retry policy is decided and written into the inbox spec.
  MD
  ```

  It opens a visible session: a Claude Code tab in Cursor with the prompt filled in (Tiago presses Enter), or a Herdr pane that starts on its own when you run inside Herdr. Tell him which, then go back to the main line and leave the forked thread alone. If the result says `launched: false`, give Tiago the printed `prompt` and brief path in one line so he can start it himself.
- **Park.** Park the idea with the `parked-ideas` skill (`park add` prints `Parked <id>: <title>`), then record it with that id: `agt registry topic --park --ref <id park add printed>`. If the thread was not yet a topic, open it first (`agt registry topic "…"`) so the park has something to close.
- **Keep here.** Open it as a topic and work on it.

## Asking through the inbox

Every decision you ask Tiago, except the drift ask, is an inbox question (the `agent-inbox` skill has the commands), plus a card in chat. The inbox files it under your session's intent and topic by itself.

The inbox entry is the card's long form, written for someone who has never seen the repo and is reading on a phone hours later:

- `title`: the question itself, one line.
- `summary`: what happened and why it matters, in plain language. Spell out what an id refers to ("PR #92, which fixes the wrong exit code in …"), never just the number.
- `detail`: the options as the exact tokens he can type, each with its one-letter alias and what it does and costs; your recommendation with one sentence of why; what you do next either way.
- `control`: a `choice` whose option ids are the card's tokens, with your recommendation marked `recommended`.

He answers from the entry alone, on a phone, with no repo and no other file. If the decision is about a text, a prompt, a diff, or a wording, that material is in `detail`. A file path, a backup, an issue number, or a one-line note about a changelog does not count. Spell an id out so he knows what it is, and still include the part he has to judge. The summary stays short and does not replace the material. The chat card stays one paragraph and points at the entry; the material lives in the entry, not in the chat.

If he follows up that he cannot answer from the page, or that he wants it simpler, update this same entry with `agt inbox update` (the `agent-inbox` skill has the command). Put the missing material in `detail`, and rewrite `summary` when the short version is what's wrong. Do not send him to a file, and do not open a second question. `revise` only changes the choices.

Then:

- **Two or fewer decisions:** both go in the reply's `**Next for you:**` group as cards, each with its inbox link.
- **More than two:** merge related ones first. Show the two most consequential as cards; ask the others in the inbox only, and end the group with `+N more waiting under this topic: <inbox host>/topics#<topic id>`. The inbox host is the one in the `url` the ask printed. After he answers, bring up the next waiting one in your next reply.
- **He answers in chat:** record it (`agt inbox answer ib-… --value <token> --via chat`), so the inbox shows it answered. If that fails with `already answered via …`, his inbox answer came first and wins: use it and say so.
- **Decisions you can make yourself:** don't ask. Decide, say so in one line, and post it (`agt inbox post`) as "Decided: … Veto here if you disagree."
- **Inbox unavailable** (the ask fails): put the full card in chat, and in place of the `+N more waiting` link list the extra decisions' questions, one line each.

## When you orchestrate other agents

Maestro's `conduct` skill owns orchestration: you are the boss, not the doer; work orders that carry the traps forward; a fresh agent per phase; verify a callee's report before relaying it. Its rules for talking to Tiago (its `Next for you:` line, letter aliases, its `/tmp/maestro/` ledger) are replaced by this skill: cards, two at a time, the inbox as the ledger.

Local additions, carried over from the retired Oslo persona:

- **Approve before spawning.** Work out the split of work with Tiago first. Nothing is spawned until he approves it.
- **Every worker brief carries the dev-env claim rule.** A worker that runs tests in a main dir claims it first, `dev-env claim <main-dir> --who <session-id> --pid $$`, and releases it when done (the global instructions have the full rule).
- **Check what's running with the registry:** `agt sessions` and the inbox's Topics tab, not a separate log.
- **Close out at wrap.** Close finished workers' topics and name any carry-overs in the Summary. Conduct's triage sweep covers the rest.

## Upstream maestro

`conduct` is Justin Sternberg's plugin (`maestro@jtsternberg`) and is never edited here. `scripts/check-maestro` compares the parts of it this skill overrides (its "The human" section and its decisions-ledger reference) with the copies in `references/maestro-baseline/`. `install.sh` warns when they differ. When that happens: read the diff, decide whether the override above still holds or there's something worth adopting into this skill, then refresh the baseline with `scripts/check-maestro --update` in a commit.
