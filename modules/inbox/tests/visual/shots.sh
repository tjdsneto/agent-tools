#!/usr/bin/env bash
# The inbox's visual check: seed a scratch test DB and a scratch registry, serve them web-only, take the shots, stop.
#
#   AGENT_INBOX_DSN="host=localhost port=5433 dbname=agent_inbox_test_visual" \
#     modules/inbox/tests/visual/shots.sh <out-dir> <port>
#
# The DB must be a test DB (its name contains agent_inbox_test): the seed drops its tables.
# See README.md in this directory for what to look for in each shot.
set -euo pipefail

die() { echo "shots.sh: $*" >&2; exit 2; }

[ $# -eq 2 ] || die "usage: AGENT_INBOX_DSN=... shots.sh <out-dir> <port>"
OUT="$1"
PORT="$2"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INBOX="$(cd "$HERE/../.." && pwd)"
REPO="$(cd "$INBOX/../.." && pwd)"

[[ "$PORT" =~ ^[0-9]+$ ]] || die "port must be a number: $PORT"
case "$PORT" in
	8797|8798) die "refusing port $PORT: that is the live inbox" ;;
esac
if lsof -ti "tcp:$PORT" >/dev/null 2>&1; then
	die "port $PORT is already in use; pick a free one"
fi

DSN="${AGENT_INBOX_DSN:-}"
[ -n "$DSN" ] || die "set AGENT_INBOX_DSN to a scratch test DB (its name must contain agent_inbox_test)"
if [[ "$DSN" =~ dbname=([^[:space:]]+) ]]; then
	DB="${BASH_REMATCH[1]}"
elif [[ "$DSN" =~ ^postgres(ql)?://[^/]*/([^?[:space:]]+) ]]; then
	DB="${BASH_REMATCH[2]}"
else
	die "can't find the database name in AGENT_INBOX_DSN"
fi
[ "$DB" != "agent_inbox" ] || die "refusing the live agent_inbox DB"
[[ "$DB" == *agent_inbox_test* ]] || die "refusing $DB: the seed drops tables, so use a DB whose name contains agent_inbox_test"

command -v node >/dev/null || die "needs node 22+ (cdpshot.mjs uses its built-in WebSocket)"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
WORK="$(mktemp -d)"
SERVER=""
cleanup() {
	[ -n "$SERVER" ] && kill "$SERVER" 2>/dev/null || true
	rm -rf "$WORK"
}
trap cleanup EXIT

cd "$INBOX"
echo "seeding $DB"
AGENT_INBOX_DSN="$DSN" AGENT_INBOX_TELEGRAM_TO= PYTHONPATH=src .venv/bin/python tests/visual/seed_topics.py > "$WORK/seed.json"
# The Topics page reads the registry live; give it a scratch one, never the real one.
REG="$WORK/registry"
.venv/bin/python tests/visual/seed_registry.py "$REG" "$WORK/seed.json"

# Only the web handler: `agt inbox serve` would also sweep, which wakes sessions.
AGENT_INBOX_DSN="$DSN" AGENT_INBOX_TELEGRAM_TO= INBOX_HTTP_PORT="$PORT" INBOX_ALLOW_INSECURE=1 PYTHONPATH=src \
	AGENT_REGISTRY_PATH="$REG/registry.json" AGENT_INBOX_AGT="$REPO/agt/agt" \
	.venv/bin/python -c 'from agent_inbox.web import make_server; make_server().serve_forever()' > "$WORK/server.log" 2>&1 &
SERVER=$!
BASE="http://127.0.0.1:$PORT"
code=$(curl --retry 10 --retry-connrefused --retry-delay 1 -s -o /dev/null -w '%{http_code}' "$BASE/" || true)
[ "$code" = 200 ] || { cat "$WORK/server.log" >&2; die "server on $PORT answered '$code', not 200"; }

# The four-node ask: its breadcrumb is the longest, and "Window targeting notes" shares its topic.
ASK=$(.venv/bin/python -c 'import json, sys; print(json.load(open(sys.argv[1]))["Is the Cursor tab opening in the right project window?"])' "$WORK/seed.json")

failed=0
shot() { # <name> <path> <width> <scheme> [PROBE expression]
	PROBE="${5:-}" node "$HERE/cdpshot.mjs" "$OUT/$1.png" "$BASE$2" "$3" 844 "$4" || failed=1
}
for w in 390 1280; do
	for g in none intent tree; do shot "feed-$g-$w" "/?group=$g" "$w" light; done
	shot "entry-$w" "/e/$ASK" "$w" light
done
shot feed-tree-390-dark "/?group=tree" 390 dark
shot entry-390-dark "/e/$ASK" 390 dark
OPEN='(() => { const f = document.querySelector(".filt"); f.open = true; return [...f.querySelectorAll("select")].map((s) => s.name + ":" + Math.round(s.getBoundingClientRect().height) + "px"); })()'
shot filter-open-390-light "/?group=tree" 390 light "$OPEN"
shot filter-open-390-dark "/?group=tree" 390 dark "$OPEN"
# Topics: the last tab must end inside a 390px screen; the open shots expand every branch.
TABS='(() => { const a = document.querySelector(".tabs").lastElementChild; return a.textContent + " ends at " + Math.round(a.getBoundingClientRect().right) + "px of " + innerWidth + "px"; })()'
EXPAND='(() => { const all = document.querySelectorAll(".tree details"); all.forEach((d) => { d.open = true; }); return all.length + " branches open"; })()'
for w in 390 1280; do
	shot "topics-$w" /topics "$w" light "$TABS"
	shot "topics-$w-dark" /topics "$w" dark
	shot "topics-open-$w" "/topics?finished=1" "$w" light "$EXPAND"
done
shot topics-open-390-dark "/topics?finished=1" 390 dark "$EXPAND"

echo "shots in $OUT"
[ "$failed" = 0 ] || die "some shots failed their viewport or scheme check (FAIL lines above)"
