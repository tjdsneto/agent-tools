# Host plugin

> **Scope:** `plugin/`, `.claude-plugin/marketplace.json`, and the `PYTHONPATH` line in `bin/agent-registry`.
> **Baseline:** main @ 3c95360

Claude Code, Codex, and Cursor presence hooks, plus the skill those agents follow. Each line below states what the code does and ends with the file that does it.

## Layout

- The Python package is `src/agent_registry`. The launcher puts `src/` on `PYTHONPATH` and runs `python -m agent_registry.cli`. — `bin/agent-registry`
- The marketplace name is `agent-registry` and its only plugin is `plugin/`. — `.claude-plugin/marketplace.json`

## Hooks

- Claude Code runs `ensure` on SessionStart, `ping` on UserPromptSubmit and PreToolUse, `heartbeat` on Stop, and `end` on SessionEnd. The hook file sits under `.claude-plugin/` so Codex does not treat it as its own. — `plugin/.claude-plugin/hooks/hooks.json`, `plugin/.claude-plugin/plugin.json`
- Codex runs `ensure` on SessionStart, `ping` on UserPromptSubmit, `heartbeat` on Stop, and `end` on SessionEnd from `~/.codex/hooks.json` and from `plugin/.codex-plugin/hooks.json`. Those commands pass `codex`. — `plugin/.codex-plugin/hooks.json`, `plugin/install`
- Cursor runs `ensure` on sessionStart and subagentStart, `ping` on beforeSubmitPrompt, `heartbeat` on stop, and `end` on sessionEnd and subagentStop. A Cursor `ping` prints `{"continue":true}`; Cursor `ensure` prints `{"additional_context": …}` when the session has a topic line; other Cursor events print `{}`. A payload with `cursor_version` or a lowercase hook event name is registered as cursor, and the directory is the first workspace root when `cwd` is absent. — `plugin/cursor/hooks.json`, `plugin/scripts/registry-hook`
- Cursor hook payloads do not carry a chat title. When `ensure` or `heartbeat` receives no `--title` for a cursor session, it reads the composer `name` from Cursor's `state.vscdb` and records that as `title` (not as `summary`). A changed name bypasses the heartbeat throttle. — `plugin/scripts/registry-hook`, `lifecycle._resolve_title`, `usage.cursor_composer_names`
- Claude hooks often omit `session_title` even when the jsonl has `customTitle` / `aiTitle`. When `ensure` or `heartbeat` receives no `--title` for a claude session, it reads the latest of those from `~/.claude/projects/*/<session_id>.jsonl`. — `lifecycle._resolve_title`, `usage.claude_session_title`
- On a Claude Code or Codex `UserPromptSubmit`, `ping` prints `hookSpecificOutput.additionalContext` with the session's topic line from `topic-context`, before it sends the heartbeat so a slow daemon start cannot cut it off. A Claude `PreToolUse` ping prints nothing. — `plugin/scripts/registry-hook`
- Claude `ensure` appends the topic line to the SessionStart context. Cursor `ensure` prints it as `additional_context`; Cursor `ping` still prints only `{"continue":true}`, because `beforeSubmitPrompt` can't add context. — `plugin/scripts/registry-hook`
- `ping` sends `heartbeat --status working` (and `--model` when the payload has a model slug, including Cursor's `default`) and then exits. — `plugin/scripts/registry-hook`
- `heartbeat` sends `heartbeat --status idle` and then runs `summarize`. — `plugin/scripts/registry-hook`
- `ensure`, `heartbeat`, and `end` call the CLI with `--type` set to the host. Claude also reads `~/.claude/sessions/<pid>.json` for the peer address and prints SessionStart context. — `plugin/scripts/registry-hook`
- `heartbeat` and `end` also run `summarize` for that session. The hook exits 0 when the CLI is missing or the command fails. — `plugin/scripts/registry-hook`

## Install

- `plugin/install` links `bin/agent-registry` into `~/.local/bin`, links the skill into `~/.claude/skills/agent-registry` and `~/.codex/skills/agent-registry`, and removes a `tjdsneto-setup/bin/agent-registry` symlink when that symlink points at this repo. — `plugin/install`
- It enables the Claude Code plugin `agent-registry@agent-registry`, removes registry commands from `~/.claude/settings.json`, and records the marketplace. — `plugin/install`
- It points the six Cursor events at `plugin/scripts/registry-hook` and deletes `~/.cursor/hooks/agent-registry.sh`. — `plugin/install`
- It adds the Codex marketplace and enables `agent-registry@agent-registry` in `~/.codex/config.toml`, and writes the four Codex events into `~/.codex/hooks.json`. It does not write `com.tjdsneto.agent-registry.plist`. — `plugin/install`

## Skill

- Agents list before claiming work and update on a focus change. Hooks own ensure, heartbeat, and end. `registry_id` stays out of shared artifacts. — `plugin/skills/agent-registry/SKILL.md`

## Notes outside the behavior-line rule

- A trusted Codex session runs SessionStart, UserPromptSubmit, and Stop. SessionEnd clears the live row. Codex skips hooks until they are trusted, or the invocation passes `--dangerously-bypass-hook-trust`.
- Claude Code loads the plugin from `plugin/`. Codex and Cursor also read their user `hooks.json` files. Codex runs `.codex-plugin/hooks.json` from its plugin cache and does not run the Claude hook file.
