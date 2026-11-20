# Overview

> **Scope:** navigation — governs no code path directly.

Where the code lives today, so a change can be aimed at a layer. This file is a map. It does not yet say how a layer must be written. The Python package is `src/agent_registry/`. The menu-bar app is `desktop/`. Host hooks and the presence skill are `plugin/`.

Verified by listing `src/agent_registry/**/*.py` and `src/agent_registry/static/*.html` on 2026-11-17.

| Layer | Code | What lands here |
|---|---|---|
| Models and store | `models.py`, `store.py`, `constants.py` | Session shape, the registry file, the lock |
| Operations | `ops.py`, `archive.py`, `session_state.py` | Register, update, prune, archive, sidecars |
| Lifecycle | `lifecycle.py` | `ensure`, `heartbeat`, `end` for hooks |
| CLI | `cli.py`, `format.py`, `doctor.py` | Commands and human output |
| Board | `dashboard.py`, `static/dashboard.html` | The loopback Live and Archive page |
| Transport | `transport.py` | Resolve and wake for Claude, Codex, and Cursor |
| Summary and project | `summarize.py`, `project.py` | Empty-summary fill, project key from a directory |
| Tests | `tests/` | Pytest for the modules above |

A new prescriptive doc is added beside this file when a layer grows a rule, and this index plus `README.md` gain a row in that same change. The words are checked against the code then. A design note in `docs/superpowers/` can suggest a rule; it does not become one by being copied.
