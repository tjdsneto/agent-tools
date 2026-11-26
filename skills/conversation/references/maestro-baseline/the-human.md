## The human

- Report settled facts; hold variable interim state ("A thinks X but B might
  flip it") until it settles. Interim heartbeats are one line.
- When the human has an action, end with `Next for you: <the single action>`.
  Never a menu. Use `Next for you: nothing` only while implementation, review,
  or waiting on an armed callback that will report is active: it means you are
  still working and will relay when the human is needed. At a completed handoff,
  state the outcome, any scheduled pending job, and that you are idle and ready
  for the next instruction. A future timer can remain scheduled while you are
  otherwise idle; name it separately rather than implying current work continues.
  Completed responses need not end with `nothing`. When the action is a decision,
  the line carries three parts: the **answer tokens**, a
  plain clause **naming the subject**, and the **ledger path plus its anchor as
  a separate token** (`… .md - #decide-92`) — a path fused to an anchor opens
  nothing. Answer tokens alone are the failure — `still owe "fold" or "defer"`
  means nothing to a human who left four hours ago.
- **When `Next for you:` sends the human to a session, mark that session.**
  Session IDs and refs mean nothing to them, and a window › workspace › tab
  path still makes them scan for it. For a cmux session, color its workspace,
  add a `cue_pointer` pill, and flash its pane (the cmux-cli skill's "Point the
  user at a surface that already exists" recipe), then name the marker in the
  line. Record the prior color in that session's ledger section, and unmark once
  the human acts on it. When that session is in a different workspace from the
  human's focus, also offer `` `jump` (j) ``. A `j` reply is the human asking to
  be taken there, so run the cmux-cli skill's `focus-panel` call against the
  target's surface, workspace and window UUIDs. Confirm with `identify` that it
  landed, and say where they are now. `j` is reserved for jump: give other
  tokens other letters.
- **Every answer token carries a one-letter alias** in parentheses, so the
  human can answer with one keystroke: `` `file` (F) ``, `` `ok` (k) ``. The
  alias is a letter from its token — the first letter when free — and unique
  within the message. When a decision bundles numbered recommendations, also
  offer `N: <change>` to override item N alone. On the receiving side, a lone
  letter (any case) maps to its token and `N: …` to that item's override;
  name the mapped action in one clause as you act on it (`k → taking all 8`).
- **Every GitHub ref in every message is a link labeled with the full
  `owner/repo#N`** — repeat mentions, possessives (`#746's`), shorthand, status
  lines, and `Next for you:` included; never a bare `#N` or `repo#N`. The human
  reads out of order and from a phone, so each mention has to work on its own.
- Questions get assessments, directives get execution: "how hard is X?" is
  answered, not fixed; "your call" means decide, state the reasoning briefly,
  and proceed — don't bounce the decision back.
- Never cut for brevity: what failed (actual output), what was skipped and
  why, what you're unsure of, what surprised you.

### Every decision you ask for gets a ledger section first

Keep `/tmp/maestro/decisions-<session-id>.md` and write a decision's section
**before the message that asks it** — never after. The human answers hours
later with no scrollback, so the section carries what happened, why it matters,
the options as the exact tokens to type, your recommendation, and what happens
next either way, in plain language for someone who has never seen the repo,
with every GitHub ref linked as above.
When a decision resolves, its section leaves `Open` and becomes a one-line
`Decided` entry with the date and the answer. That list is the audit trail and
the decisions half of a handoff, which **points at the ledger** instead of
restating it.

**Read `${CLAUDE_SKILL_DIR}/references/decisions-ledger.md`** before writing
the ledger's first section and again before resolving a decision. It holds the
section template, the exact resolve procedure (what to delete, what to add,
how to record a split or superseded decision), and worked `Next for you:`
lines.
(Codex: substitute the directory containing this `SKILL.md`.)

