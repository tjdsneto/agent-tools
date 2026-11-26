# agent-tools

One person, many AI coding sessions at once: Claude Code, Cursor, Codex, on one Mac. These are the tools around the work itself, so that person can **see** what each session is doing, **talk** with it, **keep it going** when it runs out of tokens or context, **wrap it up** cleanly, and **learn** from how sessions went.

CLI: **`agt`**. Shims keep the older command names (`agent-registry`, `session-waker`, …) working on `PATH`.

```bash
git clone https://github.com/tjdsneto/agent-tools.git ~/projects/agent-tools
cd ~/projects/agent-tools && ./install.sh
```

macOS only. `install.sh` links `agt` and the shims into `~/.local/bin`, links each skill into the engines it works in, builds the Python modules' virtualenvs, and loads the launchd agents.

## The tools

**Works in** lists the engines whose agents can use the tool: **C** Claude Code, **Cu** Cursor, **Cx** Codex, **H** Hermes. A tool's skill tells agents when and how to use it. Bringing the Claude-only ones to Cursor is [#11](https://github.com/tjdsneto/agent-tools/issues/11).

### See — what's running and what each session is on

| Tool | What it does | CLI | Skill | Works in |
|---|---|---|---|---|
| registry | Presence for every session: where it runs, its intent and topics, forks, and waking a session by id. Engine hooks keep it current. | `agt registry` | `session-awareness` | C Cu Cx |
| sessions | List, report on, rename and auto-title sessions; find which session worked on a path, branch or commit. | `agt sessions` | `session-awareness`, `claude-session-mngr`, `session-locate` | C |

### Talk — between the person and their sessions

| Tool | What it does | CLI | Skill | Works in |
|---|---|---|---|---|
| conversation | How every session talks to the person: one intent per session, named topics, self-contained decision cards, one reply ending. Its core is injected at session start. | — | `conversation` | C Cu Cx |
| inbox | Questions and reports that wait for an answer, reach the phone (web and Telegram), and wake the asking session with the answer. | `agt inbox` | `agent-inbox`, `inbox` (Hermes replies) | C Cu Cx H |
| say | A macOS prompt for attention, a choice or short text; can speak. | `agt say` | `agent-say` | C Cu |
| read | Reads text or a file aloud (Kokoro). | `agt read` | `agent-read` | C Cu |
| visual-ask | Asks with a page to look at: mockups, diagrams, comparisons. Moving into the inbox ([#10](https://github.com/tjdsneto/agent-tools/issues/10)). | — | `visual-ask` | C Cu |
| recover-pasted-files | Saves an image or file pasted into the chat as a real file. | — | `recover-pasted-files` | C |

### Keep going — across token limits, sleep and full context

| Tool | What it does | CLI | Skill | Works in |
|---|---|---|---|---|
| waker | Wakes registered long-running sessions when the token window resets; survives sleep and closed terminals. | `agt waker` | `session-waker` | C |
| budget | Reads the account's 5-hour and weekly usage windows. | `agt budget` | `check-usage` | C Cu |
| fresh-continuation | Banks a slim continuation and prints the command to resume in a fresh session. | — | `fresh-continuation` | C Cu |
| chatgpt-handoff | Hands work to ChatGPT on the phone through Tray, and picks the answer back up. | — | `chatgpt-handoff`, `chatgpt-pickup` | C Cu (pickup: Cx) |

### Wrap up — close a session without losing anything

| Tool | What it does | CLI | Skill | Works in |
|---|---|---|---|---|
| closing-session-sweep | Lists loose ends before stopping: unpushed work, running timers, held locks, open topics. | — | `closing-session-sweep` | C Cu |
| end-session | Ends the Claude Code process, on an explicit request only. | — | `end-session` | C |
| session hooks | Titles the session and plays a sound when a turn ends; deregisters from the waker on exit. | `agt sessions autorename`, `stop-sound`; `agt waker-deregister` | — | C |

### Learn — improve the tools from how sessions went

| Tool | What it does | CLI | Skill | Works in |
|---|---|---|---|---|
| glue-miner | Mines transcripts for glue code that keeps being rewritten and commands that keep failing; weekly report. | `agt glue` | `glue-miner` | C Cu (reads Cx transcripts too) |
| session-review | Finds redundant reads, excess tool calls and bloated context in a transcript. | `agt sessions review` | `session-review` | C |
| tool-registry | What CLIs, models and skills are actually available in this environment. | `agt tools` | `tool-registry` | C Cu |

## How it fits together

- **`agt/agt`** dispatches each subcommand to its module. **`shims/`** keep the old names on `PATH`.
- **`modules/<name>/`** holds a tool's code, tests and design docs (`docs/`). The Python modules have their own `.venv`.
- **`skills/<name>/SKILL.md`** is what an agent reads; `install.sh` links each into `~/.claude/skills`, `~/.cursor/skills`, `~/.codex/skills` or `~/.hermes/skills`, depending on the engines it works in.
- **Engine hooks:** the registry ships Claude Code, Cursor and Codex plugins (`modules/registry/plugin/`) that keep presence current and inject the conversation core at session start. The Claude Code session hooks are wired from the machine-setup repo, pointing at `shims/`.
- **launchd agents:** inbox delivery and backup, the weekly glue-miner, and the waker's monitor (loaded only while a session is registered).

Architecture: [`docs/superpowers/specs/2026-11-19-agent-tools-design.md`](docs/superpowers/specs/2026-11-19-agent-tools-design.md).

## Not here

- Machine setup, dotfiles and personal workflow skills live in a private setup repo.
- Assistant personas live in a separate repo.
- Orchestration rules come from the upstream [maestro](https://github.com/jtsternberg/claude-plugins/tree/main/plugins/maestro) plugin. `conversation` overrides only its parts about talking to the person.
