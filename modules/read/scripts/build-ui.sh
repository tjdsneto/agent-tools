#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/ui"
swift build -c release
BIN="$(swift build -c release --show-bin-path)/AgentReadUI"
mkdir -p "$ROOT/bin"
cp -f "$BIN" "$ROOT/bin/agent-read-ui"
chmod +x "$ROOT/bin/agent-read-ui"
echo "built $ROOT/bin/agent-read-ui"
