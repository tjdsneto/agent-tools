#!/usr/bin/env bash
# install.sh — link agt + shims into ~/.local/bin; symlink skills; refresh launchd templates.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="${AGENT_TOOLS_BIN_DIR:-$HOME/.local/bin}"
mkdir -p "$BIN_DIR"

link_bin() {
  local name="$1" src="$2"
  ln -sfn "$src" "$BIN_DIR/$name"
  echo "linked $BIN_DIR/$name -> $src"
}

link_bin agt "$ROOT/agt/agt"
for s in agent-registry session-waker claude-budget session-report active-sessions \
         rename-session list-sessions agent-say agent-read agent-inbox; do
  link_bin "$s" "$ROOT/shims/$s"
done

# Skills → Claude + Cursor shared skill dirs (match tjdsneto-setup install conventions).
link_skill() {
  local name="$1"
  local src="$ROOT/skills/$name"
  [ -d "$src" ] || return 0
  for dest_root in "$HOME/.claude/skills" "$HOME/.cursor/skills"; do
    mkdir -p "$dest_root/$name"
    ln -sfn "$src/SKILL.md" "$dest_root/$name/SKILL.md"
    # Bundle refs/scripts if present
    for bundled in references scripts; do
      [ -e "$src/$bundled" ] && ln -sfn "$src/$bundled" "$dest_root/$name/$bundled"
    done
    echo "skill $name -> $dest_root/$name"
  done
}

for sk in session-waker agent-say agent-read glue-miner session-awareness; do
  link_skill "$sk"
done

# Ensure module venvs exist (idempotent).
for mod in registry say read inbox; do
  if [ -f "$ROOT/modules/$mod/requirements.txt" ] && [ ! -x "$ROOT/modules/$mod/.venv/bin/python" ]; then
    python3 -m venv "$ROOT/modules/$mod/.venv"
    "$ROOT/modules/$mod/.venv/bin/pip" install -r "$ROOT/modules/$mod/requirements.txt"
  fi
done

# glue-miner launchd: replace __ROOT__ with absolute repo path, then reload.
PLIST_SRC="$ROOT/modules/glue-miner/launchd/com.tjdsneto.glue-miner.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.tjdsneto.glue-miner.plist"
if [ -f "$PLIST_SRC" ]; then
  mkdir -p "$ROOT/modules/glue-miner/reports"
  mkdir -p "$(dirname "$PLIST_DST")"
  if [ -f "$PLIST_DST" ]; then
    cp -f "$PLIST_DST" "${PLIST_DST}.bak-pre-agent-tools"
    echo "backed up $PLIST_DST -> ${PLIST_DST}.bak-pre-agent-tools"
  fi
  sed "s|__ROOT__|$ROOT|g" "$PLIST_SRC" > "$PLIST_DST"
  uid="$(id -u)"
  launchctl bootout "gui/$uid/com.tjdsneto.glue-miner" 2>/dev/null || true
  launchctl bootstrap "gui/$uid" "$PLIST_DST"
  echo "reloaded com.tjdsneto.glue-miner"
fi

# session-waker: if any sessions registered, start monitor via PATH shim
if command -v session-waker >/dev/null && [ -d "$HOME/.session-waker/sessions" ] \
   && [ -n "$(ls -A "$HOME/.session-waker/sessions" 2>/dev/null || true)" ]; then
  session-waker start || true
fi

echo "agent-tools install complete. Try: agt help && agent-registry --help"
