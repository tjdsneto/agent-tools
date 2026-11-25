# agent-tools — Unified public agent tooling suite (Design Spec)

**Date:** 2026-11-19  
**Status:** Approved design — awaiting implementation plan  
**New repo:** `~/projects/agent-tools` → public `github.com/tjdsneto/agent-tools`  
**CLI name:** `agt`  
**Related:** session-waker PATH fix (`tjdsneto-setup` `10c68d6`); existing private repos `agent-registry`, `agent-read`, `agent-say`; tools currently in `tjdsneto-setup`

## 1. Summary

Create one public monorepo that owns the laptop-local agent tooling suite: a single CLI **`agt`** with subcommands, companion skills, and an installer that keeps PATH shims, skill links, and launchd agents working through the cutover. Existing private tool repos are archived after a smoke-tested install. Cross-session keyword/tool search (`session-search`) is roadmap only for v1.

## 2. Goals

- Public source of truth for agent lifecycle + human I/O tools and their skills.
- One CLI (`agt`) for discoverability; **same old binary names on PATH** via shims so nothing breaks day one.
- Installer bakes **absolute paths** into launchd env (lesson from session-waker / `agent-registry` PATH failure).
- Zero-breakage cutover: working skills, daemons, and PATH entries continue to work; wiring is updated, not abandoned.
- Archive private `agent-registry`, `agent-read`, `agent-say` after cutover (README → moved here).
- Leave Cockpit (personas) and tjdsneto-setup (machine setup) as separate concerns; setup stops carrying tool bodies.

## 3. Non-goals (v1)

- Git submodules / multi-remote umbrella.
- Rewriting registry / say / read internals into one language or shared framework.
- Shipping `session-search` (keyword/tool transcript lookup) — track as roadmap only.
- Merging Cockpit personas or Hermes into this repo.
- Making tools multi-user SaaS or non-macOS first-class.
- Shipping the agent-registry `desktop/` tree (multi-GB) or local `.venv`s / personal glue reports.

## 4. Boundaries

| In (v1) | Out / elsewhere |
|---|---|
| agent-registry (CLI + plugins; no desktop blob) | Cockpit personas |
| session-waker, claude-budget | tjdsneto-setup machine/dotfiles (keeps pointer + may call `agent-tools` install) |
| session-report / claude-session-mngr, rename-session, active-sessions | session-search (roadmap issue) |
| agent-say, agent-read | |
| glue-miner (scanner + skill + launchd) | |
| Companion skills (session-waker, agent-say, agent-read, glue-miner, session-awareness, …) | |

## 5. Architecture

```
skills / scripts / launchd
        │
        ▼
   shims on PATH          agt (dispatcher)
   agent-registry ──┐        │
   session-waker  ──┼──► agt <module> <args…>
   claude-budget  ──┤        │
   …                │        ▼
                    │   modules/<name>/  (existing working code)
                    └── exec; preserve exit codes
```

Day-1 preference: **dispatcher + existing binaries in `modules/`**, not a full rewrite. Flatten the UX; keep proven code behind the door.

### 5.1 Repo layout

```
agent-tools/
  README.md
  install.sh
  agt/                         # CLI entry / dispatcher
  lib/                         # shared helpers (paths, launchd, later transcript adapters)
  modules/
    registry/
    waker/                     # session-waker + claude-budget
    sessions/                  # session-report, active-sessions, rename-session
    say/
    read/
    glue-miner/
  skills/                      # companion skills shipped with the suite
  shims/                       # old names → exec agt …
```

### 5.2 CLI ↔ shim map

| Shim (old PATH name) | `agt` |
|---|---|
| `agent-registry …` | `agt registry …` |
| `session-waker …` | `agt waker …` |
| `claude-budget …` | `agt budget …` |
| `session-report …` | `agt sessions report …` |
| `active-sessions …` | `agt sessions active …` |
| `rename-session …` | `agt sessions rename …` |
| `agent-say …` | `agt say …` |
| `agent-read …` | `agt read …` |
| glue-miner scan | `agt glue scan …` |

Shims `exec` through so exit codes and signals are preserved. Old names may remain indefinitely; docs/skills migrate to `agt …` gradually.

**say vs read:** v1 keeps both modules as they exist today (separate repos/codepaths). Do not merge `agent-say`'s optional read path with `agent-read` in this pass — only relocate and dispatch. Any consolidation is a later roadmap item.

## 6. Cutover (zero breakage)

Order of operations in one reversible window:

1. **Create** public `tjdsneto/agent-tools` and copy modules in (scrub: no `.venv`, `desktop/`, `tmp/`, personal `reports/`, secrets).
2. **Run `./install.sh` on this machine before deleting anything:**
   - Install `agt` + shims into `~/.local/bin`.
   - Relink skills from `agent-tools/skills/` (replace setup / private-repo links).
   - Regenerate launchd plists (session-waker monitor, glue-miner weekly) with absolute paths + env bins; write new plist, then bootout/bootstrap.
3. **Smoke** (see §7) before touching old homes.
4. **tjdsneto-setup:** remove moved tool bodies; leave a short pointer; fix broken `bin/session-report` symlink as part of the move.
5. **Archive** private repos only after smoke passes (final README → agent-tools).

**Rollback:** keep previous install targets / known-good plists (or setup git checkout) available for one re-install if smoke fails.

## 7. Verification

- Each shim and matching `agt <cmd> --help` / one read-only call: `registry list`, `budget check`, `sessions active`, `waker status`.
- Skill links under Claude/Cursor resolve into `agent-tools/skills/`.
- Launchd plists reference `agent-tools` paths; tick/kickstart must not log `agent-registry not on PATH`; glue-miner plist loads.
- Existing module tests still runnable from new `modules/` homes where they already exist.

## 8. Public scrub

Before first public push:

- Exclude build artifacts, venvs, the registry `desktop/` tree, personal reports, tokens, machine-only secrets.
- Inventory and rewrite hardcoded `~/projects/tjdsneto-setup/...` and `~/projects/agent-{registry,read,say}/...` paths in moved skills/scripts/plugins.
- README states macOS / laptop-local assumptions.

## 9. Risks

- Hardcoded absolute paths in skills, plugins, and launchd — must be inventoried during move.
- Registry / say / read plugin installers must target new paths.
- A buggy dispatcher that wraps instead of `exec` could swallow exit codes — shims must `exec`.
- Scope creep into rewriting tools instead of relocating them — v1 is relocate + dispatch + install.

## 10. Roadmap (explicitly not v1)

- **`session-search`:** cross-session transcript lookup by keyword / tool / host. Distinct from glue-miner (recurring-pattern aggregation). Can reuse transcript adapters once they live under `lib/`.
- Optional later removal of PATH shims once nothing calls old names.
- Optional tighter integration (shared Python package, unified test harness) after cutover is boring.

## 11. Decisions locked (brainstorming)

- Suite name / repo: `agent-tools` (public GitHub).
- CLI: `agt` (not `agent`, not `agx`).
- Membership: lifecycle + say/read + glue-miner + session-awareness/skills.
- session-search: roadmap only (option A).
- No git submodules.
- Flatten to one CLI with subcommands; day-1 = dispatcher over existing modules.
- Private repos: ended/archived after cutover (with shim continuity).
- Hard requirement: do not kill PATH, skills, or running launchd agents during migration.
