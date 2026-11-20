#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AGT="$ROOT/agt/agt"
FIX="$ROOT/tests/fixtures/fake-bin.sh"
chmod +x "$FIX"

export AGT_TEST_REGISTRY_BIN="$FIX"
export AGT_TEST_MODE=1

out="$("$AGT" registry wake abc --message /tmp/x)"
[[ "$out" == "fake:wake abc --message /tmp/x" ]] || { echo "FAIL registry args: $out"; exit 1; }

export FAKE_EXIT=7
set +e
"$AGT" registry list
code=$?
set -e
[[ "$code" -eq 7 ]] || { echo "FAIL exit code: $code"; exit 1; }

set +e
"$AGT" nosuch
code=$?
set -e
[[ "$code" -eq 2 ]] || { echo "FAIL unknown cmd exit: $code"; exit 1; }

unset FAKE_EXIT
export AGT_TEST_MODE=1
export AGT_TEST_REGISTRY_BIN="$FIX"
out="$(AGT_TEST_MODE=1 AGT_TEST_REGISTRY_BIN="$FIX" "$ROOT/shims/agent-registry" list --json)"
[[ "$out" == "fake:list --json" ]] || { echo "FAIL shim: $out"; exit 1; }

# Simulates install.sh: shim reachable only via symlink (e.g. ~/.local/bin).
SYMLINK_BIN="$(mktemp -d)"
trap 'rm -rf "$SYMLINK_BIN"' EXIT
ln -sf "$ROOT/shims/agent-registry" "$SYMLINK_BIN/agent-registry"
out="$(AGT_TEST_MODE=1 AGT_TEST_REGISTRY_BIN="$FIX" "$SYMLINK_BIN/agent-registry" list --json)"
[[ "$out" == "fake:list --json" ]] || { echo "FAIL symlink shim: $out"; exit 1; }

echo "OK test_agt_dispatch"