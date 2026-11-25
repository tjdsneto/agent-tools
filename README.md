# agent-tools

Laptop-local suite for AI agent session lifecycle and human I/O on macOS.

CLI: **`agt`** (shims keep old names like `agent-registry` on PATH).

```bash
git clone https://github.com/tjdsneto/agent-tools.git ~/projects/agent-tools
cd ~/projects/agent-tools && ./install.sh
```

Architecture: [`docs/superpowers/specs/2026-11-19-agent-tools-design.md`](docs/superpowers/specs/2026-11-19-agent-tools-design.md). Each module keeps its own design docs under `modules/<name>/docs/`.