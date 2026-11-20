---
name: session-waker
description: Keep a long-running autonomous Claude Code session making progress across rate-limit windows, machine sleep, and terminal-close — the gap ScheduleWakeup can't cover because it is in-process. A session about to run a long task registers ITSELF; a single external monitor watches the account's token windows (5h + weekly) and wakes every registered session on the token-reset edge (when a saturated window frees up again), and the session unregisters itself when done. Use when setting up an unattended/overnight run that must survive token exhaustion, or to register/check/unregister a session. Backed by `session-waker` / `agt waker` (one macOS LaunchAgent monitor + a per-session registry + token gate + dialer). Not the cloud `schedule` skill (can't reach local resources) and not ScheduleWakeup (dies with the session).
---

# session-waker

An **external, token-aware monitor** that keeps registered long-running Claude sessions making
progress. A session about to do long autonomous work **registers itself**; one per-user macOS
LaunchAgent (the monitor) fires on an interval — surviving terminal-close and machine sleep —
reads the account token state once, and wakes every registered session **on the token-reset
edge** (when a window that had been saturated frees up). The session **unregisters itself** when
its work is done.

**Why it exists:** `ScheduleWakeup` (the `/loop` timer) is in-process — it only fires inside a
live turn of the same session, so a rate-limited or backgrounded session stalls. launchd is the
only truly session-independent local trigger. Full design + locked decisions live in
`~/projects/tjdsneto-setup/docs/session-waker-design.md` until copied into this repo.

## If you are a session about to run a long unattended task — register yourself

```bash
# From your working directory, with your OWN session id (ask the hotline:caller-id skill if unsure):
session-waker register --session <your-session-id> --prompt-file ./continue.txt \
    [--model <family>] [--done-sentinel ./run.done] [--interval 15m] [--threshold 88]
```

- `--cwd` defaults to `$PWD` — **run `register` from your project directory** so the `--resume`
  fallback turn runs *in* your project dir. (`--resume` itself finds the session by id regardless
  of cwd — verified 2026-11-14 — so this is about the resumed turn's working directory, not lookup.)
- `--prompt-file` is the continue-message sent to you on each wake (and reused for the `--resume`
  fallback). Keep it short and self-contained: "do one unit of work, then go idle."
- `--model <family>` records (per session) the model family your run uses (e.g. `opus`, `fable`).
  It controls the **weekly** gate: the weekly window binds your session only if your model is the
  family `/usage` reports a weekly for (currently `Fable` — not every model has a weekly cap).
  A session on another model gates on the 5h window alone. Unset → gated on both (conservative).
- **You MUST de-register yourself when your long task is finished:**

  ```bash
  session-waker unregister <your-session-id>     # or: touch the done-sentinel you registered
  ```

## The monitor tick (what happens on each fire)

1. **Empty registry** → the monitor unloads itself.
2. **Done-sentinel sweep** (cheap, every tick) → de-register any session whose sentinel exists.
3. **Token read** — one `claude-budget snapshot` (or `agt budget snapshot`) call: the 5h session window AND the weekly
   model-family window (account-wide, so one read covers all sessions). The **5h window binds every
   session**; the **weekly window binds only sessions on its model family** (see `--model`). A
   session is *blocked* if the 5h window is saturated, or its weekly applies and is saturated.
4. **Reset-edge wake** — wake a session **only on its own transition** from blocked to available
   (block-state is tracked per session). A session that was never blocked is left alone. If
   `/usage` is unreadable for several ticks (likely rate-limited), it holds, then force-wakes as a
   fail-safe so it can't stall forever.
5. **Wake** — a one-shot `claude -p` dialer resolves the session via `ListAgents` and
   `SendMessage`s the continue-prompt, prefixed with a **wake-ack**: *"if your work is already
   complete, run `session-waker unregister <id>` instead of continuing."* Process gone → fall back
   to `claude -p --resume <id>` run from the session's own cwd.

## De-registration — four self-healing layers

1. **Explicit (primary):** the session unregisters itself when done, or touches its done-sentinel.
2. **Wake-ack self-eviction:** if an explicit de-register is missed, the next wake tells the
   already-finished session to unregister itself.
3. **Dead-process reaper:** a session whose wake fails (unreachable + `--resume` fails)
   `MAX_RESUME_FAILS` times (3) is reaped as dead — this, not the SessionEnd hook, is what cleans
   up crashed/closed sessions.
4. **SessionEnd backstop:** the `session-waker-deregister` hook de-registers **only** on
   `reason` `logout` or `prompt_input_exit` (unambiguous user exits). It deliberately ignores
   `clear`/`resume`/`other`, because the docs don't confirm `SessionEnd` stays silent on a
   rate-limit pause and `other` is a catch-all — so it never risks de-registering a session that
   was merely token-interrupted. (A `Stop` hook was impossible — it fires every turn.)

## Commands

```bash
session-waker register --session <id> --prompt-file <path> [--cwd <dir>] [--model <family>] \
                       [--done-sentinel <path>] [--interval 15m] [--threshold 88]
session-waker unregister <id>   # drop a session (aliases: done, remove); unloads monitor if registry empties
session-waker list              # monitor state + registry + last token read + log tail
session-waker status [<id>]     # detail for one session
session-waker fire              # force one tick now (launchctl kickstart) — for testing
session-waker tick              # the monitor's per-fire logic (hand-runnable)
session-waker start / stop      # manually load / unload the monitor LaunchAgent
```

## Setup notes (the traps)

- **`claude` is not on launchd's PATH.** The tool resolves the binary via `CLAUDE_BIN`, else
  `~/.nvm/versions/node/v20.20.2/bin/claude`. The resolved path is baked into the monitor plist.
- **`agent-registry` is not on launchd's PATH either.** Same trap: resolved via `AGENT_REGISTRY_BIN`,
  else `~/.local/bin/agent-registry`, and baked into the monitor plist — without that, every wake
  logs `agent-registry not on PATH — wake skipped` under launchd even though a terminal tick works.
- **Caffeine:** while any session is registered, the monitor keeps the Mac awake with
  `caffeinate -ims` (no idle/disk/system sleep; display may still sleep — and, unlike the `caffeine`
  alias, it does NOT lock the screen). It is released when the registry empties. It tracks its own
  pid (`~/.session-waker/caffeinate.pid`) so it won't kill a `caffeinate` you started by hand. Opt
  out with `SESSION_WAKER_NO_CAFFEINE=1`.
- State: `~/.session-waker/sessions/<id>.conf` (the registry — one file per session, incl.
  per-session `MODEL` and `WAS_BLOCKED`), `~/.session-waker/monitor.conf` (interval/threshold),
  `~/.session-waker/monitor.state` (unreadable-/usage streak), `~/.session-waker/log/monitor.log`.
  Override the root with `SESSION_WAKER_HOME`. Monitor agent:
  `~/Library/LaunchAgents/com.tjdsneto.session-waker.monitor.plist`.
- Reuses `claude-budget snapshot` / `agt budget snapshot` for the `/usage` read and the Watts dev-env dialer pattern.

## Known limits

- **`/usage` exposes only one weekly window.** Triple-verified 2026-11-14 (default, `haiku`,
  `opus`/`sonnet`, full ids like `claude-opus-4-8`): `/usage` reports the 5h window plus **one**
  weekly family (currently `Fable`), and the invoking model does not change it. Only models with a
  weekly cap are gated on it (via `--model`); there is no per-model weekly data for other families,
  so a run on a model with its own (unreported) weekly cap would not be gated on that cap.
- **Sleep-dormancy is covered by caffeine, not by the waker's logic.** Reset-edge waking only acts
  on token transitions, so a stall caused purely by sleep (tokens fine) isn't woken — but the
  caffeine integration keeps the box awake while sessions are registered, which prevents that
  stall. (If you opt out of caffeine, that gap returns.)

## Assumption status (verified / deferred — 2026-11-14)

Mechanically tested end-to-end with a stub claude. Live-verified against real claude:
- ✅ `claude -p "/usage"` **returns** and its format (5h + weekly, incl. bare-hour resets) is parsed.
- ✅ `claude -p --resume <id>` **attaches to a closed (process-exited) session with full context** —
  regardless of the cwd it's invoked from.
- ✅ `--model` does **not** change the weekly family `/usage` reports (see Known limits).
- ✅ **RESOLVED (2026-11-19): wake-by-UUID works via `agent-registry wake`.** The earlier blocker
  was that a raw `claude -p` dialer's `ListAgents` addresses peers by **name + short ref**, not
  UUID, so a hand-rolled "match by id" returned `unreachable`. This is moot: the waker does **not**
  hand-roll the dial — it calls `agent-registry wake <uuid> --message <file>` (`agt registry wake`,
  session-waker ~line 324). The registry records **both** uuid and name, so `agent-registry resolve <uuid>`
  returns the live `peer_name`/socket/pid and `wake` delivers to it. Verified live 2026-11-19
  against a real session: an external process SendMessage-by-name landed, and
  `agent-registry wake <uuid> --message <file>` returned `{"mode":"nudge","result":"landed"}` and
  the target session received the turn. (`register`/`wake` still take a UUID, not a name — a minor
  nicety, not a blocker.)
- ✅ **An inbound `SendMessage` gives an idle agent a turn and it acts.** Tested with an idle agent
  told to create a file only on wake: it created nothing while idle, then created it after the
  `SendMessage`. (Tested with an in-process subagent woken directly; the separate-process
  `ListAgents→SendMessage` dialer is the Watts-proven variant.)

Still unverified against real claude (can't force on demand):
1. That `claude -p "/usage"` still **returns** when the account is *actually* rate-limited (if not,
   the gate reads unreadable and the fail-safe force-wakes after a few ticks).
2. That launchd fires **promptly once** after a missed `StartInterval` across machine sleep.
3. The **long-dormant / post-sleep** variant of the wake (idle was verified; multi-hour-dormant was not).
