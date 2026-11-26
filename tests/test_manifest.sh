#!/usr/bin/env bash
# manifest.toml must match skills/, agt/agt and the README; each kind of drift must fail the check.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

"$ROOT/scripts/manifest" check || { echo "FAIL manifest check"; exit 1; }
"$ROOT/scripts/manifest" readme --check || { echo "FAIL README tables stale"; exit 1; }

COPY="$(mktemp -d)"
trap 'rm -rf "$COPY"' EXIT
fresh() {
  rm -rf "${COPY:?}"/*
  cp -R "$ROOT/manifest.toml" "$ROOT/README.md" "$ROOT/scripts" "$ROOT/skills" "$ROOT/agt" "$COPY/"
}
must_fail() {
  local what="$1"; shift
  if "$@" 2>/dev/null; then echo "FAIL drift not caught: $what"; exit 1; fi
}

fresh; mkdir "$COPY/skills/new-skill"; touch "$COPY/skills/new-skill/SKILL.md"
must_fail "skill folder missing from the manifest" "$COPY/scripts/manifest" check

fresh; rm -rf "${COPY:?}/skills/end-session"
must_fail "manifest skill with no folder" "$COPY/scripts/manifest" check

fresh; sed -i '' 's/^  say)$/  speak)/' "$COPY/agt/agt"
must_fail "agt command not in the manifest" "$COPY/scripts/manifest" check

fresh; sed -i '' 's/^  agt glue scan/  agt glu scan/' "$COPY/agt/agt"
must_fail "agt command missing from agt help" "$COPY/scripts/manifest" check

fresh; sed -i '' 's/Reads text or a file aloud/Reads text aloud/' "$COPY/README.md"
must_fail "README edited by hand" "$COPY/scripts/manifest" readme --check

echo "OK test_manifest"
