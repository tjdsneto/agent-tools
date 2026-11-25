# Design — `session-waker`: a token-aware external waker for long-running Claude sessions

**Status:** **BUILT 2026-11-14** — `bin/session-waker` + skill `ai/skills/shared/session-waker/`. Mechanically tested end-to-end with a stub claude (register → launchd RunAtLoad tick → gate/dial/resume branches → done-sentinel self-unload); the 5 real-claude assumptions below were **deferred** (decision: build on them as assumptions, verify opportunistically on the first real run). **Home:** this repo. Commits straight to master per the setup-repo convention. **Origin:** the 2026-11-13 am-videos overnight run, where the `/loop` `ScheduleWakeup` timer stalled 18:25→21:53 because it is in-process. **Decisions locked by Tiago 2026-11-13** (see "Decisions").

> **Build note (2026-11-14):** the `/usage` parser + token gate (Component 3) was **not** rewritten — the tick reuses `bin/claude-budget` (`check` / `reset-at`), which already parses the 5h session window. This avoids a second copy of the fragile `/usage` grep. The weekly window is therefore not gated (claude-budget reads only the session line).
>
> **v2 pivot (2026-11-14, Tiago):** the first build used one LaunchAgent **per target session**. Tiago's model — adopted — is a **central registry + one monitor**: token windows are account-wide, so a session **registers itself** (its id + cwd + continue-prompt) and a single monitor LaunchAgent reads `/usage` once per fire and wakes every registered session. Two changes fell out of this:
> - **cwd is now captured per session** (first build's bug: `claude --resume <id>` must run from the session's project dir, since transcripts are stored per-cwd — the fallback could not have found the session).
> - **De-registration is layered + self-healing** (replaces the single done-sentinel): (1) the session unregisters itself when done (its responsibility); (2) **wake-ack self-eviction** — every wake message tells an already-finished session to `unregister` itself, so a missed de-register corrects on the next wake; (3) a **`SessionEnd` backstop hook** (`ai/claude/scripts/session-waker-deregister`, wired in the installer + `hooks.json`) de-registers a session that truly exits. The hook is safe because `SessionEnd` fires only on a real exit, never on token-interruption (a rate-limited session stays alive/idle) — the exact constraint that ruled out a `Stop` hook; it also skips `reason="clear"`.
>
> Registry = a directory of per-session conf files under `~/.session-waker/sessions/` (pure-bash, launchd-safe, `unregister` = delete one file).
>
> **v3 (2026-11-14, Tiago) — reset-edge waking, two-window gate, model flag, reaper:**
> - **Reset-edge waking** (replaces wake-every-tick): the monitor keeps `WAS_BLOCKED` state and wakes sessions only on the transition saturated→available, not every tick. Consequence: a pure sleep-dormancy stall with tokens fine is NOT covered (keep the box awake with `caffeine`); the waker is now a token-exhaustion-recovery tool.
> - **Two-window gate:** `bin/claude-budget` gained a `snapshot` command (one `/usage` call → both the 5h session window and the weekly model-family window, parsed robustly incl. bare-hour resets like "6am"). A session is blocked if **either** window is ≥ threshold.
> - **`--model <family>` flag (advisory only).** Verified 2026-11-14: `/usage` reports the account's 5h window + **one** weekly family, and `--model` on the `/usage` call does **not** switch which family is shown — so the tool cannot read an arbitrary model's weekly window. `--model` records the expected family; the tick gates on whatever family `/usage` exposes and warns on mismatch. (Open: a per-model availability source if one is ever found.)
> - **Dead-process reaper:** a session whose wake fails `MAX_RESUME_FAILS` (3) times is reaped — this, not the SessionEnd hook, cleans up crashed/closed sessions.
> - **SessionEnd hook made conservative:** fires only on `reason` `logout`/`prompt_input_exit`. The guide (claude-code-guide, 2026-11-14) confirmed the reason set {clear, resume, logout, prompt_input_exit, other} but could NOT confirm SessionEnd stays silent on a rate-limit pause and flagged `other` as a catch-all — so to honor the "never de-register a token-interrupted session" constraint, only the two unambiguous user-exit reasons act; the reaper handles the rest.
>
> **Verification (2026-11-14, live against real claude):** ✅ `/usage` returns and parses (5h + weekly); ✅ `--resume <id>` attaches to a **closed** session with full context, **cwd-independent** (so the earlier "cwd needed to find the session" worry was wrong — cwd is kept only so the resumed turn runs in the project dir; the fallback's `cd` is now best-effort); ✅ `--model` does not switch the weekly family `/usage` reports (triple-checked incl. full model ids); ✅ **inbound `SendMessage` wakes an idle agent and it acts** (idle agent created a file only after the wake message; tested with an in-process subagent — the cross-process `ListAgents→SendMessage` dialer is the Watts-proven variant). **Still deferred:** does `/usage` return while actually rate-limited; launchd prompt-fire after sleep; the long-dormant/post-sleep wake variant.
>
> **v3.1 (2026-11-14):** `--model` is now stored **per session** (Tiago: "register that session with the model") rather than monitor-global.
>
> **v3.2 (2026-11-14, Tiago's correction):** the Fable weekly is **model-specific** — not every model has a weekly cap, so the weekly window is the *Fable* limit, not a generic one. Gating is now per-session and model-aware: the **5h window binds every session; the weekly window binds a session only if its `--model` is the family `/usage` reports a weekly for** (or `--model` is unset → both, conservative). A session on another model gates on the 5h window alone. Block-state (`WAS_BLOCKED`) therefore moved **into each session conf** (reset-edge is per session); only the unreadable-/usage streak stays global. Verified with a stub: a Fable session blocks on the Fable weekly while an Opus session ignores it, and both block on the 5h window. The earlier "mismatch warning" was dropped (a non-Fable model ignoring the Fable weekly is correct, not a mismatch).
>
> **⚠️ BLOCKING finding (F3, 2026-11-14): the dialer can't address a target by session id.** Running the real dialer (`claude -p … --allowedTools ListAgents,SendMessage --model haiku`) against this session's own uuid returned `unreachable`. Diagnosis: a separate `claude -p` process's `ListAgents` lists peers by **display name + a short opaque ref** (e.g. `739ba4`, `0ab4ac`), not by session UUID; the full uuid is not the key (SendMessage "addresses by the ListAgents handle, not the raw session uuid"). So the whole premise — a session registers its uuid and the dialer finds it by uuid — does not hold. The in-process `SendMessage` wake (F2 test) works, but that is the parent messaging its own subagent, not the cross-process dialer. `--resume` is not a substitute for a *live* session (two runtimes on one transcript diverge). **The wake transport needs rework:** candidates — (a) register the target's ListAgents *name* (but names are auto-renamed), (b) have the session rename itself to a stable unique token at register and match that, (c) drive wakes through agent-registry/hotline (which know the full uuid) instead of raw ListAgents. Decision pending Tiago.
>
> **Caffeine integration (F2, Tiago: "make caffeine the default unless there's no autonomous agent happening"):** while any session is registered, the monitor keeps the Mac awake with `caffeinate -ims` (no screen-lock, unlike the `caffeine` alias; tracked by its own pid so it never kills a manual caffeinate), released when the registry empties. `SESSION_WAKER_NO_CAFFEINE=1` opts out. This also closes the sleep-dormancy gap that reset-edge waking alone didn't cover — the box doesn't sleep while autonomous sessions are being watched.

## Problem

A long-running autonomous Claude Code session needs to keep making progress across two interruptions:
1. **Rate-limit windows** — the 5h session window / weekly model-family window empties; Claude can't run until it resets.
2. **Session dormancy** — the laptop sleeps or the terminal is backgrounded/closed; the session stops getting turns.

`ScheduleWakeup` (the `/loop` dynamic-mode timer) is **in-process**: it only fires inside a live turn of the same session. When the session isn't running, the wake sits queued until the human returns. We need a waker that does **not** live inside the session it's waking.

## Requirements

- R1 — the waker must not depend on the Claude session being alive / holding tokens.
- R2 — it must be aware of when Claude tokens are available again (and when they reset).
- R3 — it must keep retrying until the work actually resumes, then stop.

## Key constraint

The only truly session-independent trigger on this Mac is **launchd** (a per-user LaunchAgent): fires on its own schedule, survives terminal-close, runs on wake-from-sleep. ScheduleWakeup/bash-loops/the session itself all die with the session or machine sleep. Cloud cron (`/schedule`) is session-independent but **can't reach local resources** (local MCP servers, worktrees), so it's out for any local task.

## Architecture — layered

```
launchd LaunchAgent (external; every ~15 min; survives sleep + terminal close)
      │  on each fire → run `session-waker tick <id>`
      ▼
tick:
  1. TOKEN GATE  — claude -p "/usage" → parse the relevant window.
        ├─ exhausted → log "waiting, resets at <t>"; exit 0 (retry next fire)        ... R2
        └─ available → continue
  2. DONE CHECK  — if the task's done-sentinel exists → unload the LaunchAgent; exit 0  ... R3 stop
  3. WAKE        — spawn a one-shot dialer:  claude -p "<dialer prompt>"  whose only job is
        SendMessage(to: <target-session-id>, "<continue prompt>")          ... the Watts auto-dialer pattern
        ├─ delivered (target process alive, idle) → target gets a turn, does one work tick
        └─ fails (no live session / process gone) → FALLBACK: claude -p --resume <id> "<continue prompt>"
               (headless turn with the session's context; if --resume can't attach, re-brief a fresh worker from the prompt-file)
```

- **R1**: launchd + dialer are external to the target session.
- **R2**: step 1 reads `/usage` and respects reset times — never burns a dialer into a wall.
- **R3**: launchd keeps firing; each fire retries; loop ends only when the done-sentinel appears (step 2 unloads the agent).

## The alive-vs-dead-process fork

| Target session state | Wake path | Works? |
|---|---|---|
| Alive but idle (rate-limit-waiting, or quiet) | dialer `SendMessage` | Yes — inbound message gives it a turn. Common case. |
| Machine asleep | launchd fires on next interval after wake, then dialer | Yes, once awake |
| Process exited (terminal closed / crashed) | `SendMessage` has no recipient → fallback `claude -p --resume <id>` | Only if `--resume` attaches; else re-brief a fresh worker |

## Decisions (locked)

- **D1 — dead-process fallback = `claude -p --resume <id>`** (keep session context), with a fresh re-briefed worker from the prompt-file only if `--resume` can't attach to a closed session (verify assumption #4).
- **D2 — build generic**: any `--session <id>` + `--prompt-file <path>`, reusable across tasks (not engine-watch-specific).
- **D3 — hard-gate on `/usage`**: never fire a dialer while the window is exhausted (contingent on assumption #3 — if `/usage` is itself gated under rate-limit, fall back to fire-and-backoff).
- **D4 — RESOLVED (2026-11-14)**: default interval `15m`; gate the **5h session window** (the fastest-emptying in a loop, and what `claude-budget` reads). `--interval` and `--window` are flags; weekly-window gating is a documented gap.
- **D5 — RESOLVED (2026-11-14)**: name kept as **`session-waker`** (Tiago's call) — two-word kebab, fits alongside `dev-env` / `agent-registry`.

## Components to build

1. **`bin/session-waker`** — CLI:
   - `register --session <id> --prompt-file <path> [--interval 15m] [--window 5h|weekly] [--done-sentinel <path>]` → write per-task config + load a LaunchAgent.
   - `status` → agent loaded?, last fire, last `/usage` reading, next fire.
   - `stop <id>` / `unregister` → unload agent + clean up.
   - `tick <id>` → the per-fire logic launchd calls; also hand-runnable for testing.
2. **LaunchAgent plist** (`~/Library/LaunchAgents/com.tjdsneto.session-waker.<id>.plist`) — `StartInterval` + `RunAtLoad`; `StandardOut/ErrorPath` to a per-task log.
3. **`/usage` parser** — window %, reset time, available-vs-wait. Reuse the `check-usage` skill's `claude -p "/usage"` invocation + the nvm claude-bin resolution (`~/.nvm/versions/node/v20.20.2/bin/claude`) — plain `claude` is NOT on a non-interactive shell's PATH.
4. **Dialer** — one-shot `claude -p` → `SendMessage` to the target session id with the continue-prompt; detect delivery failure → fallback.
5. **Done-sentinel protocol** — the task `touch`es `<sentinel>` on its stop condition; the tick unloads the agent on seeing it.

## BUILD ORDER — spike the assumptions FIRST

These are unverified and they gate the design. Verify each (cheaply) before writing the tool; record findings back in this doc:

1. **Does an inbound `SendMessage` give an idle local session a turn?** (Expected yes; unconfirmed for a long-idle / post-sleep session.)
2. **Does `SendMessage` fail cleanly when the target process is gone** (so the fallback can trigger), vs hang/silently drop?
3. **Does `claude -p "/usage"` consume rate-limit tokens, and does it still return when the account is rate-limited?** If gated, D3 falls back to fire-and-backoff.
4. **Does `claude -p --resume <id>` attach to a session whose terminal has closed**, context intact? Decides whether the dead-process fallback is resume or fresh re-brief.
5. **launchd across sleep** — does a missed `StartInterval` fire once promptly on wake?

Then build components 1–5, test one real fire end-to-end (register → force a tick → confirm a wake), and document `session-waker` usage in a short SKILL or README.

## Relationship to existing toolkit

- **Reuses** the Watts dev-env auto-dialer pattern (one-shot `claude -p` that `SendMessage`s another session) — generalized + token-gated. See `dev-envs/` and the `watts` skill.
- **Could** resolve target session id / liveness from `agent-registry` instead of a hardcoded id.
- **Not** the cloud `schedule` skill (can't reach local resources) and **not** `ScheduleWakeup` (in-process). This is the missing middle: a local, session-independent, token-aware retry loop.
