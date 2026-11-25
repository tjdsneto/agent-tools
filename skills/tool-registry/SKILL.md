---
name: tool-registry
description: Use when you (or a subagent) need to know what capabilities are actually available in the current environment — which skills, subagents, MCP servers, plugins, or models can run here — or when picking the right tool for a task and unsure what exists or whether a tool is in scope for this repo. Also for "what tools do I have", "list my agents/skills/mcp", "is there a skill for X".
user-invocable: true
argument-hint: "[--kind skill|agent|cli|mcp|plugin|model] [--search TERM] [--project PATH] [--runtime claude|cursor] [--json] [--all]"
---

# Tool Registry

Live, scope-aware inventory of the capabilities an AI agent has **right now**. It scans what is actually installed on disk this moment — it does not trust a hand-maintained list, so it cannot drift.

**Do not answer capability questions from memory or from the session's skill/agent listing.** Run the scanner — it is authoritative and adds the one thing the session dump lacks: **scope**.

## Run it

```bash
agt tools
```

That prints everything usable from the current working directory. Run it from within a repo to see that repo's tools too. Pass `--help` for all flags; the common ones:

| Flag | Use |
|------|-----|
| `--kind skill\|agent\|cli\|mcp\|plugin\|model` | only that kind |
| `--search TERM` | match name or description (find a tool for a task) |
| `--project PATH` | resolve scope as if cwd were PATH (inspect another repo from here) |
| `--runtime claude\|cursor` | override the auto-detected runtime |
| `--json` | machine-readable, full untruncated descriptions |
| `--all` | include out-of-scope entries (default hides them) |

## Reading the output — scope is the point

Every capability is grouped by the scope it is valid in, derived from **where its file lives**:

- **global (usable anywhere)** — global skills (`~/.claude/skills`, `~/.cursor/skills-cursor`), user-scoped plugins, global MCP, models. A `[cursor]` / `[claude+cursor]` tag marks which runtime a skill deploys to.
- **project:&lt;repo&gt;** — skills/agents/MCP that live in that repo's `.claude/` or `.mcp.json`. These appear **only when your cwd is inside that repo**. A Lindris tool run from `~/projects/goflow` simply won't show — that's the "can't be useful outside Lindris" rule enforced by construction, not by a flag.

### Runtime — is this skill actually for me?

Skills deploy to Claude Code (`~/.claude/skills`), Cursor (`~/.cursor/skills-cursor`), or both (shared). A skill deployed to both is tagged `[claude+cursor]`; a Cursor-only one is tagged `[cursor]`. The scanner detects the runtime it's running under (`CLAUDECODE` → claude, else `CURSOR_*` → cursor) and flags any skill that does **not** deploy to it:

```
• canvas [cursor]  — …  ✗ NOT runnable from claude (cursor-only)
```

So a Claude agent knows at a glance that a `[cursor]`-tagged skill isn't its to run — even though most skills exist for both and either can be ported to the other. Use `--runtime cursor` to see it from Cursor's side.

### CLIs — external tools agents can call

The `cli` kind lists agent-callable command wrappers on PATH, from `~/projects/tjdsneto-setup/bin/` and the agent-tools shims in `~/.local/bin`. Currently that includes **`gemini-ask`** — a one-shot Google Gemini query with the API key auto-injected from 1Password (never on disk/argv):

```bash
gemini-ask "one-line summary of: ..."          # bare text → prompt (defaults to gemini-2.5-flash)
gemini-ask -p "prompt" -m gemini-2.5-pro       # any flag → passthrough to the gemini CLI
GEMINI_MODEL=gemini-2.5-pro gemini-ask "..."   # override the default model
```

The `cli` list is a curated registry — one row per command in `~/projects/agent-tools/modules/tool-registry/clis.tsv` (`command<TAB>description`). A listed command shows **only when it actually resolves on PATH**, so an uninstalled tool stays hidden (visible under `--all`, marked not-usable). Add a row to expose a new wrapper — `buddy`, `opc`, `op-ssh-cache`, `park`, `dev-env`, `agent-registry` are already listed.

## Two known gaps (by design)

- **MCP** lists servers configured on disk (`~/.claude.json` + `.mcp.json`). Account-level claude.ai connectors (Gmail, Asana, Stripe, …) are not on disk — the output says so and points to `/mcp`.
- **Models** have no disk source, so they come from `~/projects/agent-tools/modules/tool-registry/models.tsv` — the only hand-maintained slice. Update it when Anthropic ships or retires a model.

## Maintenance

Adding a skill/agent/plugin/MCP anywhere needs **no change here** — the next run picks it up. The two curated lists (no disk source to scan) are hand-maintained: **CLIs** in `clis.tsv`, **models** in `models.tsv`. Wrapper scripts themselves live in `~/projects/tjdsneto-setup/bin/` (already on PATH) or come from agent-tools as shims linked into `~/.local/bin` by its `install.sh`. Correctness of the scan's tricky parts (frontmatter parsing, cwd-scope resolution, runtime detection, marker parsing) is pinned in `modules/tool-registry/test_registry.py`; run `python3 test_registry.py` there after editing `registry.py`, and `agt tools --self-test` as a live smoke check.
