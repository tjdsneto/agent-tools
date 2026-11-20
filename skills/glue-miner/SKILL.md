---
name: glue-miner
description: Mine Claude Code, Cursor, and Codex session transcripts for recurring glue code (inline python3 -c / heredoc scripts, scratch scripts, long jq/awk), commands that fail and get retried, and denials/hook errors — then judge which recurring groups deserve a new tool, a better existing tool, or a fixed instruction, and route each to an issue, the tray, or an app backlog. Use when Tiago says "mine my sessions", "what glue keeps getting written", "find tool opportunities", "glue report", "/glue-miner", or when Karen's plan mode finds an unreviewed weekly report.
user-invocable: true
argument-hint: "[scan [--days N] | review [report-path]]"
---

# Glue Miner

Agents write throwaway Python, long `jq`, and retry loops when a tool is missing, a flag is undocumented, or an instruction is stale. Each one is cheap; the same one in 40 sessions is a tool waiting to be built. This skill finds those and turns them into decisions.

It reads three transcript sources, each via its own adapter into one normalized shape, so a pattern that recurs under more than one tool merges into a single group tagged with the tools it came from:

| Source | Root | What it yields |
|---|---|---|
| `claude` | `~/.claude/projects/**/*.jsonl` | calls + results + hooks → all three sections |
| `cursor` | `~/.cursor/projects/**/agent-transcripts/**/*.jsonl` | calls only — **glue section only** (Cursor records no tool outputs) |
| `codex` | `~/.codex/sessions/**/rollout-*.jsonl` | shell lifted from its JS `exec` wrapper; outputs lack an error flag, so **retries are best-effort** |

**Full per-source spec** — each format, *why* every limit exists, how to choose `--source`, and how to read a `[Claude+Cursor]`-style tag (including which instruction file it routes a fix to) — is in [`references/sources.md`](references/sources.md). Read it once; the summary above is the at-a-glance version.

Two layers, kept apart on purpose:

- **Scan** (`glue_miner.py`) — deterministic counting. Groups snippets by what they did and ranks by recurrence. No judgment.
- **Review** (this skill) — Claude reads the top groups, checks what already exists, and decides what each one is.

## Modes

### scan

```bash
agt glue scan --days 7                              # all 3 sources → reports/<ISO-week>.md
agt glue scan --days 30 --stdout                     # one-off, print instead
agt glue scan --days 30 --json                       # machine-readable groups
agt glue scan --source cursor,codex --days 30 --stdout
# equiv: python3 ~/projects/agent-tools/modules/glue-miner/glue_miner.py …
```

All three sources scan by default; `--source` takes a comma list (`claude`, `cursor`, `codex`). Pass `--exclude-session <this session id>` so the scan doesn't count itself (claude only). A weekly scan runs automatically (launchd `com.tjdsneto.glue-miner`, Mondays 07:30 + on login; installed by agent-tools `./install.sh`), so `reports/` usually already has this week's file.

**Reading the report.** Three sections:

Every group carries a **source tag** — `[Claude]`, `[Cursor]`, `[Codex]`, or a combination like `[Claude+Cursor]`. A multi-tool tag is the strongest signal: the same missing tool is being papered over regardless of which agent is driving. The tag also tells you *which instruction file* a "fix instruction" lands in (see routing below).

1. **Recurring glue** — groups keyed `kind · feeder · files:<family> · ops`. *feeder* is the command piped into the snippet (`gtr list`, `gh pr`, `-` = none). *files* is the artifact family it opened. Score = sessions × projects × √avg-lines, so recurrence across sessions outranks one giant script. Each group lists the agent's own Bash `description`s — the fastest way to see the job.
2. **Failed, then retried** — a command head that errored and was re-run within 3 calls. Failure kinds: `unknown-flag`, `graphql`, `json-error`, `not-found`, `usage`, `auth`, `python-traceback`, `exit-nonzero`.
3. **Denials and hook errors** — blocking hooks (`hook-block`), non-blocking hook failures (`hook-error`), user denials. Approved permission prompts aren't in transcripts, so this cannot see them.

Reports live in `reports/` (gitignored — they quote raw commands; secrets are redacted best-effort, not guaranteed).

### review

Work the report top-down. **Budget: the top ~10 glue groups plus any retry/block row with ≥5 sessions.** Skip groups already marked in the ledger unless flagged **grew since**.

For each group:

1. **Read the job.** Descriptions + representative snippet. If unclear, open one listed session transcript at that call.
2. **Check what exists before proposing anything.** Run `python3 ~/projects/tjdsneto-setup/ai/skills/shared/tool-registry/registry.py --search <term>` (still lives in setup) and `<tool> --help` for the feeder. Half the value is finding the tool that already does it — e.g. 66 sessions read a GoFlow note through `gtr list --json | python3` because CLAUDE.md said to, while `gtr edit --append-note` already existed.
3. **Classify** into exactly one:

   | Class | When | Fix |
   |---|---|---|
   | **fix instruction** | A tool already does it; agents don't know or were told otherwise | Edit the instruction/skill that misled them (`tjdsneto-setup` → `./install.sh`; repo docs via a PR). The source tag picks the global-instruction file — mapping and multi-tool handling in [`references/sources.md`](references/sources.md#how-to-read-the-source-tag). |
   | **improve existing tool** | The feeder tool is right but lacks a flag/output mode, or its `--help` is broken/undocumented | Issue on that tool's repo, or a backlog item for a self-built app |
   | **new tool** | No tool covers the job and it recurs across projects | Issue / tray item describing the job, inputs, and the snippet it replaces |
   | **skip** | Inherent one-off-ish work (ad-hoc data spelunking, slide edits), or the snippet is the right tool | Mark it so it stops resurfacing |

4. **Route** by where the fix lives:
   - Lindris repos (`lindris-monorepo`, frontend, backend, …) → draft via the `monorepo-create-issue` skill (never raw `gh issue create`).
   - Self-built apps (GoFlow, Tray) → a line on that project's `.ana/todo.md`, via the `ana-project` skill.
   - Personal tooling / `tjdsneto-setup` → fix directly if small (commit to master), else `tray add "<job>" inbox`.
   - Third-party tools → note only; fix the instruction that steers around them.
5. **Mark it** so next week's report doesn't re-propose it:

   ```bash
   agt glue scan --mark 'glue:inline-python · gtr list · json-read+stdin' --decision 'fix instruction: CLAUDE.md now says --append-note (ceb08b3)' --sessions 66
   ```

   The key is the heading/key-column text verbatim. A marked group resurfaces once its session count doubles.

**Deliver** a short ranked list (≤5 items) of decisions taken and proposals awaiting Tiago — one line each with class, sessions, and where it was routed. Never file an issue or edit an instruction outside `tjdsneto-setup` without his OK on that item.

## Notes

- Grouping is heuristic. Two jobs can share a fingerprint (`json-read` of different artifacts) and one job can split across several (python vs `jq`). Merge or split by judgment during review, not by tuning the scanner mid-review.
- Retry rows for `python3` mostly mean a snippet guessed a schema wrong — check whether the input's schema is documented anywhere; that's usually the real fix.
- A Cursor-only or Codex-only pattern **never** shows retries/blocks — that is the format, not a clean run. Only `[Claude]`-tagged (or `…+Claude`) groups carry those signals. Codex's own `exec`-wrapped JS is its normal shell path, so don't flag "writes JS to run a command" as glue on its own; judge the `cmd` inside it like any other shell.
- Tests: `python3 test_glue_miner.py` (covers the claude path plus the cursor and codex adapters and the cross-source merge).
