# Glue-miner sources — formats, limits, and how to choose

Glue-miner reads three AI coding-agent transcript formats. Each has its own adapter in `glue_miner.py` that parses the raw lines into one normalized per-session shape — `(calls, results, hook_errors, project, session_id)` — after which every downstream step (glue extraction, retry/block detection, grouping, ranking, rendering) is identical and source-agnostic. The differences between sources are therefore entirely about **what each format records**, which decides **which of the three report sections that source can feed**. The limits below are properties of the formats, not gaps in the scanner — no amount of code recovers a signal the transcript never wrote down.

## What each report section needs

- **Section 1 — recurring glue:** needs only the *calls* (the Bash/Shell command text and any Write bodies). Every source has these.
- **Section 2 — failed, then retried:** needs *results* — a call's output and whether it errored — so the scanner can see a command fail and then be re-run with the same head within a few calls.
- **Section 3 — denials and hook errors:** needs *results* too (the blocking-hook message that replaced a tool result, or a recorded denial) plus, for Claude, the non-blocking hook-error attachments.

So a source that records calls but not results can only ever contribute to section 1.

## claude

- **Root / glob:** `~/.claude/projects/**/*.jsonl` (one file per session; `subagents/` transcripts fold into their parent session).
- **Format:** Anthropic message lines. Assistant messages carry `tool_use` blocks (`id`, `name`, `input`); user messages carry matching `tool_result` blocks keyed by `tool_use_id` with `is_error` and the output text. Non-blocking hook failures arrive as `attachment.type == "hook_non_blocking_error"`. The session `cwd` is on the entries; the project is that `~/projects/<name>`, worktrees folded into their repo, with the flattened folder name as a fallback.
- **Yields:** all three sections. This is the reference format the other two are normalized toward.
- **Limits:** approved permission prompts are not written to the transcript (and bypass mode skips them), so section 3 sees only *denials* and *hook* errors, never the full set of prompts. This predates multi-source support and applies to Claude alone.

## cursor

- **Root / glob:** `~/.cursor/projects/<flattened-cwd>/agent-transcripts/<id>/<id>.jsonl`.
- **Format:** role-tagged lines (`user` / `assistant` / `turn_ended`) whose `message.content` is a block list. Tool calls are Anthropic-style `tool_use` blocks — the adapter maps Cursor's names/keys onto Claude's: `Shell` → `Bash` (its input is already `command` + `description`), and `Write`'s `contents`/`path` → `content`/`file_path`. Tools with a raw-string input (e.g. `ApplyPatch`) are carried through untouched and simply never match glue extraction. The project is read from the `.cursor/projects/<dirname>`, which encodes the launch cwd.
- **Yields:** **section 1 only.**
- **Limit (hard, format-level):** Cursor transcripts record **no tool outputs** — there are zero `tool_result` blocks and the `tool_use` blocks carry no call id, so results cannot be recovered or even paired to calls. Retries and denials/hook errors are therefore impossible for Cursor. An empty sections 2/3 for a Cursor-only pattern is the format, not a clean run.

## codex

- **Root / glob:** `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`.
- **Format:** typed lines. `session_meta` carries the `cwd` and `session_id`; `turn_context` repeats the cwd. Tool calls are `response_item` payloads of type `custom_tool_call` / `function_call`. Shell does **not** appear as a dedicated tool — it runs inside a JavaScript `exec` tool whose body calls `tools.exec_command({cmd:"…"})`. The adapter lifts the `cmd` string(s) out of that JS (object form `{cmd:"…"}`, string form `exec_command("…")`, with JS-unescaping) and emits one normalized Bash call per command. Outputs come back as `custom_tool_call_output` / `function_call_output` keyed by `call_id`.
- **Yields:** section 1 reliably; sections 2/3 only weakly (see below).
- **Limits (format-level + judgment):**
  - Codex outputs carry **no error flag** (no `is_error`, no leading `Exit code N`) — just free text like `Wall time 0.1 seconds\nOutput:`. The adapter attaches the output text so denial/hook detection *can* fire, but failure-based retry detection mostly cannot, so treat Codex's sections 2/3 as best-effort, not authoritative.
  - Writing JS to run a shell command is Codex's **normal** execution path, not a missing-tool smell. Do not flag "wraps a command in `exec`" as glue on its own — judge the `cmd` inside the wrapper exactly as you would any other shell command.
  - Multiple commands can share one `exec` block (and thus one `call_id`); only the first is paired to the block's output. Fine for glue (which ignores results); another reason Codex retry detection is thin.

## Yield summary

| Source | 1. Glue | 2. Retries | 3. Denials/hooks | Why the gap |
|---|---|---|---|---|
| claude | ✅ | ✅ | ✅ (denials + hooks only) | approved prompts not logged |
| cursor | ✅ | ❌ | ❌ | format records no tool outputs at all |
| codex  | ✅ | ⚠️ best-effort | ⚠️ best-effort | outputs have no error flag; shell is JS-wrapped |

## How to choose `--source`

- **Default (no flag): all three.** This is what the weekly launchd scan runs and what you want for a routine review — recurrence *across* tools is the strongest signal.
- `--source claude` — when you only care about the full-fidelity signal (you need retries/blocks too, or you're chasing a Claude-specific instruction/hook issue).
- `--source cursor` or `--source cursor,codex` — when you specifically want to see what glue the *other* agents keep writing, e.g. before editing their instruction files (`AGENTS.md`, Cursor user-rules). Remember sections 2/3 will be empty or thin by format, not because those agents never fail.
- Combine freely (`--source claude,codex`). Unknown names are rejected with the valid list.

## How to read the source tag

Every group in the report is tagged with the tools it recurs under — `[Claude]`, `[Cursor]`, `[Codex]`, or a combination like `[Claude+Cursor]`. Identical patterns across tools **merge into one group** (they share a fingerprint), and the tag records which sources contributed.

- A **multi-tool tag** is the strongest buy-signal: the same job is being hand-rolled no matter which agent drives, so the missing tool or wrong instruction is real and tool-agnostic.
- The tag also **routes the fix** when the class is *fix instruction* — each tagged tool has its own global-instruction file, all sourced from `tjdsneto-setup` and deployed by `./install.sh`:
  - `[Claude]` → `ai/instructions/claude/CLAUDE.md`
  - `[Codex]` → `ai/instructions/codex/AGENTS.md`
  - `[Cursor]` → `ai/instructions/cursor/user-rules.md` (symlinked to `~/AGENTS.md` by install.sh, which Cursor auto-reads — no paste)
  A multi-tool group usually needs the fix in each tagged tool's file; a fix that lives in a `shared` skill covers all of them at once.
