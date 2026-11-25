# claude-session-mngr — capability design

**Date:** 2026-07-28
**Status:** approved (design) → next: implementation plan

## Overview

Give Tiago visibility into his own Claude Code usage: which sessions are running right now
(including ones spawned as delegated cmux tabs), which sessions were touched today (even if
already closed), and how many tokens were consumed today across all of them. Read-only —
this capability never mutates cmux, Claude Code, or any transcript.

Motivation: a day running 5 concurrent delegated cmux sessions surfaced "session/token sprawl"
as a real pain point — no single view answers "what's going on across all my Claude Code work
right now" or "how much did today cost me in tokens."

There is a pre-existing but incomplete attempt at part of this: the `session-awareness` skill
(`active-sessions` / `list-sessions` scripts under `ai/claude/scripts/`). It lists live
processes (ps + lsof, no cmux, no tokens) and separately browses historical transcripts (size/
message counts, no tokens). Per discussion with Tiago, `claude-session-mngr` is a **new,
standalone capability** — the fate of `session-awareness` (retire vs. keep vs. decide later) is
deferred until the new tool has been used for a while.

## Goals

- **Unified report**: one command shows every session touched **today**, whether it's still
  running or already closed, with per-session token totals and a daily grand total.
- **cmux-aware**: sessions running inside a cmux workspace/pane are tagged with the workspace
  name; sessions in a plain terminal (or Cursor) are tagged as such. cmux is a soft dependency —
  if cmux isn't running or the socket call fails, everything still works, just without workspace
  labels.
- **On-demand, callable by anyone**: primarily a command Tiago runs himself (or asks Claude to
  run) whenever he wants the picture. Not wired into any automatic hook today, but nothing
  prevents Karen or another skill from shelling out to it later (e.g. an end-of-day check-in) —
  `--json` output exists for that.
- **Raw tokens, not dollars**: report input / cache-write / cache-read / output token counts.
  No pricing table — Anthropic's rates change and a hardcoded table would silently drift stale.

## Non-goals (YAGNI — cut from v1)

- No dollar-cost estimation (see above).
- No automatic hooks, alerts, or thresholds triggered by session count or token volume.
- No mutation of cmux state, Claude Code processes, or transcript files.
- No historical (non-"today") reporting — that's what `list-sessions` already does; this tool's
  job is "what happened today," not a general transcript browser.
- No retirement of `session-awareness` as part of this work.

## Components

```
claude-session-mngr/
  scripts/
    _sessions.py          Pure/testable library: transcript parsing, process discovery,
                           cmux correlation, today-filtering, merge logic
    session-report        Thin CLI: calls _sessions.py, renders the table + totals, --json
    tests/
      test_sessions.py    Unit tests against fixtures (inline Python literals: fabricated
                           JSONL lines, ps-output strings, cmux-tree dicts — no fixture
                           files needed, since every pure function takes plain data in)
  README.md               Workflow + data-source notes
bin/
  session-report -> ../claude-session-mngr/scripts/session-report   (global command)
ai/skills/claude/claude-session-mngr/SKILL.md   Claude-facing usage doc (Claude Code only —
                                                  matches session-awareness's bucket choice)
```

### `_sessions.py` responsibilities

- **Transcript scan**: glob `~/.claude/projects/*/*.jsonl` **and**
  `~/.claude/projects/*/*/subagents/*.jsonl`, `stat`-filter both to `mtime >= local midnight`
  before opening anything (cheap file-level prefilter — a file untouched since before today
  can't contain any of today's lines, so skip it entirely without opening it). For each
  candidate that passes the prefilter, parse line-by-line and keep only lines whose own
  `timestamp` falls on today's local date (a session can span midnight — a file modified today
  may still hold yesterday's lines mixed with today's, so the file-level `mtime` check is only a
  candidate filter, never the token-counting boundary). From today's lines, sum `message.usage`
  fields (`input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`,
  `output_tokens`) across all `assistant` lines, and capture first/last timestamp, `cwd`,
  `gitBranch`, and any `custom-title` record. This extends the parsing already done in
  `list-sessions`.
  **Correction, found during implementation (Task 3's code-quality review), not during
  design:** the original assumption above — that subagent/Task-tool usage appears as
  `isSidechain: true` lines inline in the parent session's own file — is wrong. Verified live:
  subagent transcripts are **separate files** at `<project>/<session-id>/subagents/
  agent-<hash>.jsonl` (519 of them exist on this machine right now), invisible to a
  `*/*.jsonl`-only glob. Each subagent file's lines carry a `sessionId` field equal to the
  parent's, and the parent session-id is also recoverable cheaply from the path itself
  (`path.parent.parent.name`, since the file sits under `<session-id>/subagents/`) — no need to
  open the file just to find out which session it belongs to. `session_key_for_path` uses the
  path-based approach; `gather_report` folds a subagent file's parsed usage into its parent
  session's totals via `merge_parsed_sessions` rather than treating it as its own row. Left
  unfixed, this would have silently undercounted tokens on any day using subagent delegation —
  a routine occurrence, and precisely the "cmux/agent sprawl" scenario motivating this tool.
- **Live process discovery**: run `ps -eo pid=,tty=,command=` and keep lines whose first argv
  token's basename is exactly `claude`. **Correction from initial design-time assumption**:
  `active-sessions`' `"stream-json" in line` filter was verified (live, during planning) to miss
  every cmux-launched interactive session — none of four checked cmux `claude` processes had
  `stream-json` in their command line; that flag only appears on Cursor's headless-embedded
  invocation style. Matching on the binary name catches both styles. Extract the session id from
  `--session-id (\S+)` or `--resume (\S+)` (whichever is present — cmux always passes one or the
  other when it spawns a delegated session; a manually-typed `claude` with neither flag has no
  argv-visible id). Use `ps`'s `tty` column (via `-o tty`) directly for cwd/tty; **do not** use
  `ps aux`'s abbreviated `TT` column (`s001`) — verified `-o tty` returns the full device name
  (`ttys001`), which matches cmux's JSON `tty` field byte-for-byte, no normalization needed. Then
  `lsof -p <pid>` for cwd.
- **cmux correlation (soft dependency)**: shell out to `cmux tree --all --json` with a short
  timeout (~2s) — verified this flag exists and returns full structured JSON (not text), shape
  confirmed live: `{windows: [{workspaces: [{title, ref, panes: [{surfaces: [{tty, title, type,
  ref}]}]}]}]}`. Walk `windows[].workspaces[].panes[].surfaces[]`, keep `type == "terminal"`
  entries with a non-null `tty`, build a `tty → workspace title` map. If the `cmux` binary is
  missing, the call errors, or it times out, return an empty map — every session then falls back
  to "plain terminal." Never raises.
- **Match live process → transcript**: exact match via the `--session-id`/`--resume` id
  extracted above, when present; otherwise fall back to the newest-mtime transcript in that
  process's cwd's project dir, excluding ids already claimed by another live process (handles
  two concurrent sessions in the same repo, as observed live: this session and the sibling
  "GCal integration" cmux session both running against this same `tjdsneto-setup` clone during
  design).
- **Merge**: for every transcript in today's set, decide `running` (a live process matched it)
  vs `closed`; if running, look up that process's tty in the cmux map for a workspace label.

### `session-report` (CLI)

Calls `_sessions.py`, renders one table sorted by last-active desc:

| Session | Project/cwd | Status | cmux workspace | Input | Cache write | Cache read | Output | Last active |
|---|---|---|---|---|---|---|---|---|

Footer: daily total per token category, count of distinct sessions today, count currently
running. Supports `--json` for machine consumption (same convention as `active-sessions`/
`list-sessions`).

## Data flow

1. Compute local-midnight cutoff (timestamps in transcripts are UTC — convert using system tz).
2. Glob + `stat`-filter transcripts to today's candidates.
3. Parse each candidate, keeping only lines timestamped today, → per-session usage sums +
   metadata. This is the "touched today" set, independent of whether the process is still alive.
   A session with any line today qualifies, even if most of its history is from earlier days.
4. Enumerate live `claude` processes (ps + lsof), extracting PID, cwd, tty,
   `--session-id`/`--resume` id.
5. Match each live process to a transcript (id match first, else newest-in-cwd fallback with
   exclusion of claimed ids).
6. Fetch the cmux tree once; build the tty → workspace map.
7. Join: tag each of today's transcripts `running`/`closed`; if running, attach cmux workspace
   label via tty lookup, else "plain terminal."
8. Render table + totals footer.

## Error handling & edge cases

Nothing here should ever hard-crash the report — it's a read-only visibility tool, not a
critical path:

- `cmux` absent / socket error / timeout → empty tty→workspace map, silent degrade.
- A transcript file unreadable, or a line fails JSON parsing → skip that line/file (matches the
  existing `try/except: pass` style in `active-sessions`/`list-sessions`), keep scanning the rest.
- `lsof` fails for a PID (race: process died mid-scan, permissions) → cwd shows "unknown"; the
  session is still listed by PID/tty alone, just less labeled.
- No sessions touched today → a clear "No sessions today" message, not an empty/broken table.
- Session matched only by newest-mtime-in-cwd heuristic (no `--resume` id) is marked with the
  same `~` "best guess" convention `active-sessions` uses today — this ambiguity is inherent to
  how Claude Code sessions expose their identity to the OS and isn't solved by this tool.
- A session's model/effort can change mid-transcript (e.g. mixed model usage) — token sums are
  summed across all lines regardless of model; no per-model breakdown in v1 (YAGNI).

## Testing

Same fixture-based spirit as the bookmarks capability's tests, adapted to this module's
all-pure-functions-take-plain-data design: fixtures are inline Python literals in
`test_sessions.py` (fabricated JSONL lines, `ps`-output strings, `cmux`-tree dicts), not
external files — no test touches a real running cmux instance or real live processes:

- Fabricated JSONL lines (known `usage` blocks) → assert correct per-session and daily-total
  token sums, including a case that spans yesterday+today to verify the midnight cutoff.
- A `cmux tree --all --json`-shaped dict (mirroring the captured real sample) → assert correct
  tty→workspace parsing; a separate case with a fake `run` callable that raises/returns
  non-zero → assert graceful empty-map fallback (this is dependency-injected specifically so
  the "cmux missing/failed" contract is verifiable without touching real cmux).
- A `ps -eo pid=,tty=,command=`-shaped string (including a non-`claude` line, to assert it's
  excluded) → assert PID/tty/cwd/session-id extraction; plain-dict fixtures for the
  running/closed join, including the "two live processes in the same cwd" disambiguation case.
- `session-report --json` output shape is asserted directly (no snapshot/golden-file needed —
  the structure is simple enough for direct assertions).

## Scope

**In v1:** unified today-report (running + closed sessions), per-session token breakdown
(input/cache-write/cache-read/output) + daily totals, cmux workspace tagging with graceful
degradation, global `bin/session-report` command, `--json` output, unit tests via fixtures.

**Not in v1 (YAGNI):** dollar-cost estimation, automatic hooks/alerts on sprawl thresholds,
non-today historical reporting, per-model token breakdown, retiring/merging `session-awareness`.

## Implementation risks — resolved during design (verified live, not assumed)

1. **TTY matching** — RESOLVED. `ps -o tty` (full device name, e.g. `ttys001`) matches cmux's
   JSON `tty` field byte-for-byte; no normalization needed. (`ps aux`'s abbreviated `TT` column,
   `s001`, is a trap — do not use it.) Non-`claude`-tty processes (headless, e.g. Cursor's
   embedding) show `??`; handle as "no tty" → no cmux label, not an error.
2. **cmux structured output** — RESOLVED. `cmux tree --all --json` exists and returns full JSON:
   `{windows: [{workspaces: [{title, ref, panes: [{surfaces: [{tty, title, type, ref}]}]}]}]}`.
   No text/regex parsing needed.
3. **`active-sessions`' process filter is wrong for this tool** — DISCOVERED during design (not
   in the original risk list). Its `"stream-json" in line` filter matches zero cmux-launched
   interactive sessions in live testing; it only catches Cursor's headless embedding style. This
   tool must filter on `argv[0]` basename `== "claude"` instead. This is specific to
   `claude-session-mngr`'s own process-discovery code — `active-sessions` itself is untouched.
4. **Local timezone correctness** — still to apply carefully in implementation (not a design
   risk, just an easy-to-get-wrong detail): the midnight cutoff must use the system's local
   timezone, since transcript timestamps are UTC (`Z`-suffixed).

## Links

- Related existing capability: `ai/skills/claude/session-awareness/SKILL.md` (not modified by
  this work; its scripts live in `ai/claude/scripts/`)
- Pattern reference: `docs/superpowers/specs/2026-07-26-chrome-bookmarks-design.md`
- Digital-life capabilities tracker: `assistant/brain/projects/digital-life.md` (to be updated
  with this capability once the plan lands)
