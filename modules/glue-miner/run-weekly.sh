#!/bin/bash
# Scheduled by launchd/com.tjdsneto.glue-miner.plist (Mondays 07:30 local, plus RunAtLoad so a
# missed Monday catches up on the next login/wake). Writes reports/<ISO-week>.md once per week;
# the judgment pass happens later, interactively, via the glue-miner skill (Karen's plan mode).
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEEK="$(date +%G-W%V)"
if [ -f "$DIR/reports/$WEEK.md" ]; then
	exit 0
fi

# launchd runs with a bare PATH; prefer Homebrew's python3, fall back to the system one.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
python3 "$DIR/glue_miner.py" --days 7 --out "$DIR/reports/$WEEK.md"
