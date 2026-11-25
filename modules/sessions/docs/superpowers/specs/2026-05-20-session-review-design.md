# Session Review — Design Spec

**Date:** 2026-05-20
**Status:** Approved

## Problem

Claude sessions accumulate tool calls and context injections that are invisible to the user mid-session. There's no easy way to spot redundant reads, bloated hook payloads, or excessive Bash calls without manually parsing JSONL.

## Goal

A `session-review` script + skill pair that lets a user (or Claude itself) analyse a session transcript for tool usage and context injection events, with emphasis on spotting waste and redundancy.

## Scope

- Python script: parses a transcript JSONL and outputs a summary or timeline
- Skill: teaches Claude to invoke the script and interpret the output
- No changes to existing hooks or session infrastructure

---

## Script

**Location:** `claude-tools/scripts/session-review`

**Interface:**

```
session-review <transcript.jsonl>             # summary (default)
session-review <transcript.jsonl> --timeline  # full chronological view
```

The transcript path is always passed explicitly — no ambient session detection in the binary. This keeps it testable and usable for both live and archived sessions.

### Summary Output

Sections printed in order:

**Header**
```
Session Review: <session-id-prefix>  (<N> turns, <N> tool calls)
```

**TOOL USAGE**
Tool call counts by name, sorted descending, with an ASCII bar (max width 20).

**BASH COMMANDS**
Top Bash invocations grouped by leading command word (e.g. `grep`, `gtr`, `find`). Shows count per group plus the most-used full invocation.

**READ FILES**
Files passed to the `Read` tool, with repeat counts. Any file read more than once is flagged with `⚠`.

**SKILLS INVOKED**
Names of skills loaded via the `Skill` tool, in order of first invocation.

**CONTEXT INJECTIONS**
Attachment event counts by subtype: `hook_success`, `hook_additional_context`, `skill_listing`, `mcp_instructions_delta`, `deferred_tools_delta`, `command_permissions`, `task_reminder`.

**WARNINGS**
Auto-generated flags:
- `Read` called N>1 times on the same file path
- Any hook with a recorded error or non-zero exit code
- (Future: hooks with duration >N ms)

### Timeline Output (`--timeline`)

Chronological list of every event:
```
[turn  1 | 14:52:33]  tool_use     Skill  goflow-cli
[turn  1 | 14:52:35]  tool_use     Bash   gtr projects list --json
[turn  1 | 14:52:35]  attachment   hook_success  UserPromptSubmit (486ms)
...
```

Fields: turn number, timestamp (HH:MM:SS), event kind, name/subtype, brief detail.

### Parsed Event Types

The script processes these JSONL entry types:

| Entry type | What is extracted |
|------------|-------------------|
| `assistant` with `tool_use` content | tool name + key input fields |
| `attachment` (any subtype) | attachment type + metadata |
| `system/turn_duration` | turn number + duration |
| `system/stop_hook_summary` | hook name + exit code |
| `system/away_summary` | idle gap |
| `user` (non-meta) | turn boundary marker |

Entries of type `file-history-snapshot`, `custom-title`, `last-prompt` are silently ignored.

---

## Skill

**Location:** `claude-tools/skills/session-review/SKILL.md`

**Bucket:** `claude` (not shared with Cursor)

**Invocation:** `/session-review` or when the user asks to review what Claude has been doing.

### Behaviour

1. **Current session** — extract the transcript path from the `system-reminder` context (the `session-context` UserPromptSubmit hook always injects: `"The transcript for this session is stored at: <path>"`).
2. Run `session-review <path>` (default summary) or with `--timeline` if the user asked for a detailed view.
3. Read the output and surface any warnings with a one-line suggestion per warning (e.g., "Read `.claude/settings.json` 3× — consider assigning its content to a variable on first read").
4. **Past sessions** — use `list-sessions` to find the transcript path by date or title keyword, then pass it to the script.

The skill does not attempt to fix inefficiencies automatically; it only reports and suggests.

---

## File Locations

| File | Purpose |
|------|---------|
| `claude-tools/scripts/session-review` | Executable Python script |
| `claude-tools/skills/session-review/SKILL.md` | Claude skill |

The script is added to the `SCRIPTS` list in `claude-tools/scripts/install` so it is `chmod +x`'d by `./install.sh`. It is invoked by full path (`~/projects/tjdsneto-setup/claude-tools/scripts/session-review`) — consistent with how hooks reference scripts in the same directory.

---

## Out of Scope

- Token count estimation (requires model-specific tokeniser)
- Automatic de-duplication or session patching
- Cursor / shared skill variant
