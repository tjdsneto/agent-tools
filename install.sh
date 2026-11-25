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

reload_agent() {
  local label="$1" plist="$2" uid
  uid="$(id -u)"
  launchctl bootout "gui/$uid/$label" 2>/dev/null || true
  if ! launchctl bootstrap "gui/$uid" "$plist"; then
    sleep 0.5
    launchctl bootout "gui/$uid/$label" 2>/dev/null || true
    launchctl bootstrap "gui/$uid" "$plist"
  fi
  echo "reloaded $label"
}

link_bin agt "$ROOT/agt/agt"
for s in agent-registry session-waker claude-budget session-report active-sessions \
         rename-session list-sessions rename-claude-sessions session-context session-review \
         session-waker-deregister agent-say agent-read agent-inbox; do
  link_bin "$s" "$ROOT/shims/$s"
done

# Skills → Claude + Cursor shared skill dirs (match tjdsneto-setup install conventions).
# link_skill <name> [dest roots...]; default roots are Claude and Cursor.
link_skill() {
  local name="$1"; shift
  local src="$ROOT/skills/$name"
  [ -d "$src" ] || return 0
  local roots=("$@")
  [ ${#roots[@]} -gt 0 ] || roots=("$HOME/.claude/skills" "$HOME/.cursor/skills")
  for dest_root in "${roots[@]}"; do
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
# Claude-only: it reads Claude Code transcripts.
link_skill session-review "$HOME/.claude/skills"
# Any agent can ask Tiago through the inbox, so Codex gets this one too.
link_skill agent-inbox "$HOME/.claude/skills" "$HOME/.cursor/skills" "$HOME/.codex/skills"
# Every engine follows the topic rules, so Codex gets this one too.
link_skill topic-awareness "$HOME/.claude/skills" "$HOME/.cursor/skills" "$HOME/.codex/skills"

if [ -d "$HOME/.hermes/skills" ]; then
  mkdir -p "$HOME/.hermes/skills/inbox"
  ln -sfn "$ROOT/skills/inbox/SKILL.md" "$HOME/.hermes/skills/inbox/SKILL.md"
  echo "skill inbox -> $HOME/.hermes/skills/inbox"
  # Linked, not enabled: `hermes plugins enable inbox-buttons` writes Hermes config, which Cockpit owns.
  mkdir -p "$HOME/.hermes/plugins"
  ln -sfn "$ROOT/modules/inbox/hermes-plugin/inbox-buttons" "$HOME/.hermes/plugins/inbox-buttons"
  echo "plugin inbox-buttons -> $HOME/.hermes/plugins/inbox-buttons"
else
  echo "hermes skills dir missing; inbox skill is $ROOT/skills/inbox"
fi

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

# agent-inbox delivery loop.
INBOX_PLIST_SRC="$ROOT/modules/inbox/launchd/com.tjdsneto.agent-inbox.plist"
INBOX_PLIST_DST="$HOME/Library/LaunchAgents/com.tjdsneto.agent-inbox.plist"
if [ -f "$INBOX_PLIST_SRC" ]; then
  mkdir -p "$ROOT/modules/inbox/tmp"
  mkdir -p "$(dirname "$INBOX_PLIST_DST")"
  ui_origin="http://127.0.0.1:8797"
  frame_origin="http://127.0.0.1:8798"
  if command -v tailscale >/dev/null && command -v python3 >/dev/null; then
    ts_dns="$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null || true)"
    if [ -n "$ts_dns" ]; then
      ui_origin="https://${ts_dns}:8444"
      frame_origin="https://${ts_dns}:8445"
    fi
  fi
  sed -e "s|__ROOT__|$ROOT|g" -e "s|__HOME__|$HOME|g" \
      -e "s|__UI_ORIGIN__|$ui_origin|g" -e "s|__FRAME_ORIGIN__|$frame_origin|g" \
      "$INBOX_PLIST_SRC" > "$INBOX_PLIST_DST"
  reload_agent com.tjdsneto.agent-inbox "$INBOX_PLIST_DST"
fi

BACKUP_PLIST_SRC="$ROOT/modules/inbox/launchd/com.tjdsneto.agent-inbox-backup.plist"
BACKUP_PLIST_DST="$HOME/Library/LaunchAgents/com.tjdsneto.agent-inbox-backup.plist"
if [ -f "$BACKUP_PLIST_SRC" ]; then
  mkdir -p "$(dirname "$BACKUP_PLIST_DST")"
  sed "s|__ROOT__|$ROOT|g" "$BACKUP_PLIST_SRC" > "$BACKUP_PLIST_DST"
  reload_agent com.tjdsneto.agent-inbox-backup "$BACKUP_PLIST_DST"
fi

# Inbox UI on the tailnet. 443 stays the existing Funnel; these are extra ports.
if command -v tailscale >/dev/null; then
  tailscale serve --bg --yes --https=8444 http://127.0.0.1:8797
  tailscale serve --bg --yes --https=8445 http://127.0.0.1:8798
else
  echo "tailscale not on PATH; UI stays on 127.0.0.1"
fi

# session-waker: if any sessions registered, start monitor via PATH shim
if command -v session-waker >/dev/null && [ -d "$HOME/.session-waker/sessions" ] \
   && [ -n "$(ls -A "$HOME/.session-waker/sessions" 2>/dev/null || true)" ]; then
  session-waker start || true
fi

echo "agent-tools install complete. Try: agt help && agent-registry --help"
