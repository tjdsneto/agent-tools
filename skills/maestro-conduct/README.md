# Conduct — orchestrate the work, don't do it

An operating stance for a main agent that is **overseeing** delegated work
rather than doing it — an implement → review → address pipeline running across
one or more repos or workspaces. Load it when the session's job is to conduct
other agents: choose what happens next, write the work orders, verify the
results, and talk to the human.

Most of orchestration is judgment a capable agent already has. This skill is
deliberately trimmed to the rules agents get *wrong* without being told.

## Use it when

- You're running a multi-agent workstream — "boss mode" — and want the boss to
  spend its cycles on judgment, not edits.
- Work spans phases (implement, review, address-review) that must not bleed into
  one another's context.
- Work spans more than one repo or workspace and someone has to route fixes,
  merge order, and cross-references correctly.

## What it enforces

- **Boss/doer split.** Edits, searches, test runs, and reviews all happen in
  delegated agents. The conductor's cycles go to decisions and verification.
- **Fresh context per phase.** Implement, review, and address-review are
  separate agents in fresh sessions — an implementer never reviews its own work,
  a reviewer never addresses its own review. "Fresh" means also defeating any
  session-routing cache — dispatch the next phase with `--fresh` — so the
  reviewer isn't silently the implementer resumed.
- **Work orders that carry the traps forward.** Every dispatch ships the task,
  the verified facts the callee can't cheaply rediscover, hard constraints as
  behaviors (minimal diff, worktree ownership, every environment trap
  predecessors hit), armed tripwires (what to halt on *plus* the evidence to
  self-settle), and a fixed report format demanding actual test output.
- **Verify before relaying.** A callee's report is a claim; check the artifact —
  diff shape, PR state, CI — before telling the human a phase succeeded — and
  triage its caveats (resolve, state in one clause with who clears it, or drop
  when by-design) instead of forwarding them verbatim.
- **The batch drains its own triage.** A finished batch leaves the tracker
  smaller than it found it: dispatched agents get an explicit findings channel
  for out-of-scope discoveries, and the conductor sweeps what came back —
  executing what's cheap, taking the human's verdict on the rest — before
  calling the batch closed. A survivor gets parked only with a pointer planted
  where a future editor will trip over it; a comment at the edit site outlives a
  tracker entry nobody re-reads.
- **A clean human contract.** Every message ends with a single
  `Next for you: <action>` (or `Next for you: nothing`) — never a menu.
  Every answer token carries a one-letter alias (`` `ok` (k) ``) so the human
  answers with one keystroke, and a decision bundling numbered recommendations
  also accepts `N: <change>` to override item N alone.
  Questions get assessments; directives get execution.
- **A decisions ledger the human can act on hours later.** Every decision put
  to the human gets a plain-language section on disk *before* the message that
  asks it — what happened, why it matters, the options as the exact tokens to
  type, the recommendation, what happens next either way — and the
  `Next for you:` line carries the answer tokens, a clause naming the subject,
  and the ledger path with its anchor as a separate token — a path fused to an
  anchor opens nothing, it offers to create a file. Answer tokens alone
  (`still owe "fold" or "defer"`) are unanswerable once the scrollback is gone. Answered decisions
  move to a dated `Decided` list, which doubles as the audit trail and as the
  decisions half of a handoff.

## Pairs with

- **`patient-waiting`** — the zero-token discipline for waiting on a callee, CI,
  or the human between phases. Conduct points at it directly; install both.
  Find the set under the **`maestro`** tag.

The stance is tool-agnostic, but it binds to a multi-workspace dispatch
transport and a terminal multiplexer when those are present, so phases become
visible, resumable surfaces the human can step into. Without them it falls back
to in-process subagents for quick tasks and headless sessions for substantial
phases.
