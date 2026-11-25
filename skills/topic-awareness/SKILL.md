---
name: topic-awareness
description: Use in every session. Keep one intent per session and name the topic you are on under it. When a thread drifts off the intent, or is a side quest that can be split off, ask Tiago in one line whether to fork it into its own visible session, park it, or keep it here. The prompt hook reminds you of both on every turn.
---

# topic-awareness

Tiago runs many sessions at once. A session that drifts through several threads makes him lose track when he comes back to it. Each session therefore has one **intent**, fixed for its life, and one current **topic** under it. Threads that don't belong are forked into their own sessions or parked.

Each prompt starts with a line from the hook:

```
Intent: Make inbox entries topic-aware (tp-7k3q) · Topic: Decide where topic records live (tp-9m2c). If this prompt changes the subject, run the topic-awareness drift check.
```

or, in a new session, `No intent set for this session. …`.

Subagents don't use this skill. They share the parent session's id, so their topic commands would write to the parent's log. Only the main session sets the intent, opens topics and forks.

Session identity comes from your environment (`CLAUDE_CODE_SESSION_ID`, `CODEX_THREAD_ID`, `CURSOR_CONVERSATION_ID`), so these commands need no flags.

## Set the intent once

As soon as the first prompt makes clear what the session is for, set the intent: one line, the outcome the session exists for.

```bash
agt registry intent "Make inbox entries topic-aware"
```

A session has one intent. If the work turns into something else, that is a new session, not a new intent. If the hook line already shows an intent, leave it alone.

A session started by a fork reads its brief and adopts its topic first, as its prompt says:

```bash
agt registry intent --adopt tp-xxxx
```

## Name the topic you're on

When the main line moves to a new step, open it as a topic. When it is finished, mark it done. Open and close topics silently; they're for the registry, not the chat.

```bash
agt registry topic "Decide where topic records live"
agt registry topic --done
```

## Drift check

Run it only when the work changes subject, not when it takes another step toward the same goal. A bug found along the way, a follow-up question, or a retry is the same thread. When you can't tell, treat it as the main line: open a topic and don't ask.

| The new thread is… | Then |
|---|---|
| on the intent's main line | `agt registry topic "…"`, keep going |
| on-intent, but a side quest that can be split off (independent of the main line and likely more than a few turns) | ask: fork / park / keep here |
| off-intent | ask: fork as a new intent / park / keep here |

If the work would still make sense without the rest of the intent, it's a side quest. If it moves the intent forward, it's the main line.

Ask in one line of plain chat text, with fork as the default. Then end your turn. Don't start the new thread, fork, park or open a topic until he answers. If the same prompt also asked for main-line work, do only that part. Do not use a blocking question tool.

```
Side quest: retry policy for wake. Fork / park / keep here? (fork)
```

A bare ok or go means the default, fork. If the reply is unclear, ask once more.

A drift ask is the exception to agent-inbox: ask it in chat only, never through the inbox. It's a quick steer, and a late inbox answer would resume you on a thread that has already moved on.

Then do what he chose:

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

  It opens a visible session: a Cursor tab with the prompt filled in (Tiago presses Enter), or a Herdr pane that starts on its own when you run inside Herdr. Tell him which, then go back to the main line and leave the forked thread alone. If the result says `launched: false`, give Tiago the printed `prompt` and brief path in one line so he can start it himself.
- **Park.** Park the idea with the `parked-ideas` skill (`park add` prints `Parked <id>: <title>`), then record it with that id: `agt registry topic --park --ref <id park add printed>`. If the thread was not yet a topic, open it first (`agt registry topic "…"`) so the park has something to close.
- **Keep here.** Open it as a topic and work on it.

## When the intent is done

When the outcome the intent names is met, mark the current topic done, then say so in one line and suggest ending or clearing the session. Don't start new work in it.

## Look around

```bash
agt registry topics           # this session's history
agt registry topics --open    # every open topic, every session
agt registry topics --tree    # the topic tree across sessions, forks included
```
