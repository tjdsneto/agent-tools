# Feature specs

> **Scope:** navigation — governs no code path directly.

Living component specs for this repo. A spec here is kept true: the change that alters a component updates its spec in the same change. A spec that has drifted from the code is a bug.

These are not the design notes in `docs/superpowers/`. Those stay where they are. They are point-in-time records and are not edited to match later code.

## File convention

One kebab-case markdown file per component, in this directory. `daemon.md` is a component spec. A component that grows past one file becomes a directory with its own `README.md`.

A file is added when that component is implemented or changed, not ahead of the work. This index gains a row in that same change.

## Index

| Spec | What it covers |
|---|---|
| [daemon.md](daemon.md) | Loopback daemon, CLI client, live usage, and board session actions. |
| [menu-bar.md](menu-bar.md) | macOS menu-bar client of the registry daemon. |
| [plugin.md](plugin.md) | Claude Code, Codex, and Cursor presence hooks and skill. |

## Related

- Historical designs and plans: `docs/superpowers/specs/`, `docs/superpowers/plans/`.
- How code in a layer should be written: `docs/code-standards/`.
- The family definitions: `~/projects/tjdsneto-setup/ai/pr-review-standards/docs-taxonomy.md`.
