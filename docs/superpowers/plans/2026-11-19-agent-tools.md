# agent-tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create public `tjdsneto/agent-tools` with CLI `agt`, relocate existing agent tools into `modules/`, install PATH shims + skills + launchd without breaking the live machine, then archive the private tool repos.

**Architecture:** Thin `agt` dispatcher `exec`s into per-module binaries under `modules/`. Same-named shims on `~/.local/bin` forward to `agt <subcommand> …`. `install.sh` links bins/skills and regenerates launchd plists with absolute paths. Day-1 is relocate + dispatch, not a rewrite of registry/say/read.

**Tech Stack:** bash (dispatcher, shims, install, session-waker, claude-budget), Python 3 + per-module `.venv` (registry, say, read, glue-miner, session-report), launchd, GitHub (`gh`).

**Reference spec:** `docs/superpowers/specs/2026-11-19-agent-tools-design.md`

---

## Before you start

- Spec is authoritative for membership, shim map, cutover order, and non-goals (`session-search` is roadmap only).
- **Do not delete or archive** `~/projects/agent-registry`, `agent-read`, `agent-say`, or setup tool paths until Task 9 smoke passes.
- `tjdsneto-setup` commits go to `master`. New `agent-tools` repo uses `main`.
- On this Mac today: `~/.local/bin/agent-registry` → `~/projects/agent-registry/bin/agent-registry`; setup `bin/` is on PATH; glue-miner launchd label `com.tjdsneto.glue-miner` is loaded.

### File map (create / move)

| Path | Responsibility |
|---|---|
| `~/projects/agent-tools/agt/agt` | Dispatcher CLI |
| `~/projects/agent-tools/shims/*` | Old binary names → `exec agt …` |
| `~/projects/agent-tools/install.sh` | Link bins/skills; rewrite launchd |
| `~/projects/agent-tools/modules/registry/` | From `agent-registry` (no `desktop/`, `.venv`, `tmp`) |
| `~/projects/agent-tools/modules/waker/` | `session-waker`, `claude-budget` |
| `~/projects/agent-tools/modules/sessions/` | session-mngr scripts, `active-sessions`, `rename-session` |
| `~/projects/agent-tools/modules/say/` | From `agent-say` |
| `~/projects/agent-tools/modules/read/` | From `agent-read` |
| `~/projects/agent-tools/modules/glue-miner/` | From setup `ai/skills/shared/glue-miner/` (code + launchd template; no personal `reports/`) |
| `~/projects/agent-tools/skills/` | Companion skills |
| `~/projects/agent-tools/tests/test_agt_dispatch.sh` | Dispatcher/shim contract tests |
| setup cleanup | Remove moved bodies; pointer README; fix `bin/session-report` |

---

### Task 1: Scaffold public repo

**Files:**
- Create: `~/projects/agent-tools/` (new git repo)
- Create: `~/projects/agent-tools/.gitignore`
- Create: `~/projects/agent-tools/README.md`

- [ ] **Step 1: Create directory and git repo**

```bash
mkdir -p ~/projects/agent-tools
cd ~/projects/agent-tools
git init -b main
```

- [ ] **Step 2: Write `.gitignore`**

```gitignore
.venv/
**/__pycache__/
*.py[cod]
.pytest_cache/
.DS_Store
tmp/
modules/**/tmp/
modules/**/reports/
modules/registry/desktop/
*.egg-info/
dist/
build/
.ana/
.superpowers/
```

- [ ] **Step 3: Write minimal README**

```markdown
# agent-tools

Laptop-local suite for AI agent session lifecycle and human I/O on macOS.

CLI: **`agt`** (shims keep old names like `agent-registry` on PATH).

```bash
git clone https://github.com/tjdsneto/agent-tools.git ~/projects/agent-tools
cd ~/projects/agent-tools && ./install.sh
```

See `docs/` (or the design spec in tjdsneto-setup until docs are copied) for architecture.
```

- [ ] **Step 4: Initial commit**

```bash
cd ~/projects/agent-tools
git add .gitignore README.md
git commit -m "chore: scaffold agent-tools repo"
```

- [ ] **Step 5: Create public GitHub repo and push**

```bash
cd ~/projects/agent-tools
gh repo create tjdsneto/agent-tools --public --source=. --remote=origin --push
```

Expected: repo at `https://github.com/tjdsneto/agent-tools`, visibility public, `main` pushed.

---

### Task 2: `agt` dispatcher (TDD)

**Files:**
- Create: `~/projects/agent-tools/agt/agt`
- Create: `~/projects/agent-tools/tests/test_agt_dispatch.sh`
- Create: `~/projects/agent-tools/tests/fixtures/fake-bin.sh` (fixture “module” binary)

- [ ] **Step 1: Write failing dispatch tests**

Create `tests/fixtures/fake-bin.sh`:

```bash
#!/usr/bin/env bash
# Prints args and exits with code from FAKE_EXIT (default 0).
echo "fake:$*"
exit "${FAKE_EXIT:-0}"
```

Create `tests/test_agt_dispatch.sh`:

```bash
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

FAKE_EXIT=7
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

echo "OK test_agt_dispatch"
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
chmod +x ~/projects/agent-tools/tests/test_agt_dispatch.sh
~/projects/agent-tools/tests/test_agt_dispatch.sh
```

Expected: FAIL (missing `agt/agt` or not executable).

- [ ] **Step 3: Implement `agt/agt`**

```bash
#!/usr/bin/env bash
# agt — agent-tools dispatcher. Exec into module binaries; preserve exit codes.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cmd="${1:-}"
[ $# -gt 0 ] && shift || true

die() { echo "agt: $*" >&2; exit 2; }

# Test harness overrides (see tests/test_agt_dispatch.sh).
if [ "${AGT_TEST_MODE:-}" = 1 ]; then
  case "$cmd" in
    registry) exec "${AGT_TEST_REGISTRY_BIN:?}" "$@" ;;
    *) die "unknown command '$cmd'" ;;
  esac
fi

case "$cmd" in
  registry)
    exec "$ROOT/modules/registry/bin/agent-registry" "$@"
    ;;
  waker)
    exec "$ROOT/modules/waker/session-waker" "$@"
    ;;
  budget)
    exec "$ROOT/modules/waker/claude-budget" "$@"
    ;;
  sessions)
    sub="${1:-}"; [ $# -gt 0 ] && shift || true
    case "$sub" in
      report) exec "$ROOT/modules/sessions/session-report" "$@" ;;
      active) exec "$ROOT/modules/sessions/active-sessions" "$@" ;;
      rename) exec "$ROOT/modules/sessions/rename-session" "$@" ;;
      *) die "sessions: need report|active|rename" ;;
    esac
    ;;
  say)
    exec "$ROOT/modules/say/bin/agent-say" "$@"
    ;;
  read)
    exec "$ROOT/modules/read/bin/agent-read" "$@"
    ;;
  glue)
    sub="${1:-}"; [ $# -gt 0 ] && shift || true
    case "$sub" in
      scan) exec python3 "$ROOT/modules/glue-miner/glue_miner.py" "$@" ;;
      *) die "glue: need scan" ;;
    esac
    ;;
  ""|-h|--help|help)
    cat <<'EOF'
agt — agent-tools
  agt registry …          agent-registry
  agt waker …             session-waker
  agt budget …            claude-budget
  agt sessions report|active|rename …
  agt say …               agent-say
  agt read …              agent-read
  agt glue scan …         glue-miner
EOF
    exit 0
    ;;
  *) die "unknown command '$cmd' (try: agt help)" ;;
esac
```

```bash
chmod +x ~/projects/agent-tools/agt/agt ~/projects/agent-tools/tests/fixtures/fake-bin.sh
```

- [ ] **Step 4: Re-run tests — expect PASS**

```bash
~/projects/agent-tools/tests/test_agt_dispatch.sh
```

Expected: `OK test_agt_dispatch`

- [ ] **Step 5: Commit**

```bash
cd ~/projects/agent-tools
git add agt/agt tests/
git commit -m "feat: add agt dispatcher with exec semantics"
```

---

### Task 3: PATH shims

**Files:**
- Create: `~/projects/agent-tools/shims/agent-registry`
- Create: `~/projects/agent-tools/shims/session-waker`
- Create: `~/projects/agent-tools/shims/claude-budget`
- Create: `~/projects/agent-tools/shims/session-report`
- Create: `~/projects/agent-tools/shims/active-sessions`
- Create: `~/projects/agent-tools/shims/rename-session`
- Create: `~/projects/agent-tools/shims/agent-say`
- Create: `~/projects/agent-tools/shims/agent-read`
- Modify: `~/projects/agent-tools/tests/test_agt_dispatch.sh` (add shim test)

Each shim (example `shims/agent-registry` — others only change the `agt` args):

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/agt/agt" registry "$@"
```

| Shim file | `exec … agt` args |
|---|---|
| `agent-registry` | `registry "$@"` |
| `session-waker` | `waker "$@"` |
| `claude-budget` | `budget "$@"` |
| `session-report` | `sessions report "$@"` |
| `active-sessions` | `sessions active "$@"` |
| `rename-session` | `sessions rename "$@"` |
| `agent-say` | `say "$@"` |
| `agent-read` | `read "$@"` |

- [ ] **Step 1: Create all eight shims** (content as above; `chmod +x shims/*`)

- [ ] **Step 2: Extend test — shim forwards args**

Append to `tests/test_agt_dispatch.sh`:

```bash
export AGT_TEST_MODE=1
export AGT_TEST_REGISTRY_BIN="$FIX"
# Shim resolves ROOT to repo; override by putting a test shim that calls agt with test env.
out="$(AGT_TEST_MODE=1 AGT_TEST_REGISTRY_BIN="$FIX" "$ROOT/shims/agent-registry" list --json)"
[[ "$out" == "fake:list --json" ]] || { echo "FAIL shim: $out"; exit 1; }
```

Note: shim does not pass `AGT_TEST_*` unless exported — export them in the test invocation as shown.

- [ ] **Step 3: Run tests — expect PASS**

```bash
~/projects/agent-tools/tests/test_agt_dispatch.sh
```

- [ ] **Step 4: Commit**

```bash
cd ~/projects/agent-tools
git add shims/ tests/test_agt_dispatch.sh
git commit -m "feat: add PATH shims that exec agt subcommands"
```

---

### Task 4: Copy modules (no delete of sources)

**Files:** populate `modules/{registry,waker,sessions,say,read,glue-miner}/`

- [ ] **Step 1: Copy registry (scrub heavy/private noise)**

```bash
mkdir -p ~/projects/agent-tools/modules/registry
rsync -a --delete \
  --exclude '.venv' --exclude 'desktop' --exclude 'tmp' \
  --exclude '.git' --exclude '.pytest_cache' --exclude '.ana' \
  --exclude '.superpowers' \
  ~/projects/agent-registry/ ~/projects/agent-tools/modules/registry/
```

- [ ] **Step 2: Create module venv + install deps (registry)**

```bash
cd ~/projects/agent-tools/modules/registry
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./bin/agent-registry --help | head
```

Expected: help text; `.venv` stays local (gitignored).

- [ ] **Step 3: Copy say + read similarly**

```bash
rsync -a --exclude '.venv' --exclude '.git' --exclude '.pytest_cache' \
  ~/projects/agent-say/ ~/projects/agent-tools/modules/say/
rsync -a --exclude '.venv' --exclude '.git' --exclude '.pytest_cache' \
  ~/projects/agent-read/ ~/projects/agent-tools/modules/read/
cd ~/projects/agent-tools/modules/say && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd ~/projects/agent-tools/modules/read && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# Rebuild Swift UI helpers if bin/*-ui missing — follow each module's README (scripts/build-ui.sh / swift build).
```

- [ ] **Step 4: Copy waker + sessions from setup**

```bash
mkdir -p ~/projects/agent-tools/modules/waker ~/projects/agent-tools/modules/sessions
cp -f ~/projects/tjdsneto-setup/bin/session-waker ~/projects/agent-tools/modules/waker/session-waker
cp -f ~/projects/tjdsneto-setup/bin/claude-budget ~/projects/agent-tools/modules/waker/claude-budget
chmod +x ~/projects/agent-tools/modules/waker/*
# session-waker looks for claude-budget beside itself (SELF_DIR) — keep both in modules/waker/.

cp -f ~/projects/tjdsneto-setup/bin/rename-session ~/projects/agent-tools/modules/sessions/rename-session
cp -f ~/projects/tjdsneto-setup/ai/claude/scripts/active-sessions ~/projects/agent-tools/modules/sessions/active-sessions
rsync -a ~/projects/tjdsneto-setup/tools/claude-session-mngr/scripts/ \
  ~/projects/agent-tools/modules/sessions/mngr-scripts/
# Thin wrapper so `session-report` name resolves:
cat > ~/projects/agent-tools/modules/sessions/session-report <<'EOF'
#!/usr/bin/env bash
exec "$(cd "$(dirname "$0")" && pwd)/mngr-scripts/session-report" "$@"
EOF
chmod +x ~/projects/agent-tools/modules/sessions/session-report \
  ~/projects/agent-tools/modules/sessions/active-sessions \
  ~/projects/agent-tools/modules/sessions/rename-session \
  ~/projects/agent-tools/modules/sessions/mngr-scripts/session-report
```

- [ ] **Step 5: Copy glue-miner code (no personal reports)**

```bash
mkdir -p ~/projects/agent-tools/modules/glue-miner
rsync -a \
  --exclude 'reports' --exclude '__pycache__' \
  ~/projects/tjdsneto-setup/ai/skills/shared/glue-miner/ \
  ~/projects/agent-tools/modules/glue-miner/
# Skill markdown will live under skills/glue-miner — keep scanner + launchd + references here.
# Move SKILL.md out in Task 5; for now ok if duplicated briefly.
```

- [ ] **Step 6: Smoke module binaries via `agt` (after modules exist)**

```bash
~/projects/agent-tools/agt/agt help
~/projects/agent-tools/agt/agt registry --help | head
~/projects/agent-tools/agt/agt budget check; true  # may print empty if /usage unknown
~/projects/agent-tools/agt/agt waker status
~/projects/agent-tools/agt/agt sessions active | head
```

- [ ] **Step 7: Commit module trees (never commit `.venv`)**

```bash
cd ~/projects/agent-tools
git add modules/
git status  # confirm no .venv / desktop
git commit -m "feat: import registry, say, read, waker, sessions, glue-miner modules"
```

---

### Task 5: Skills into `skills/`

**Files:**
- Create: `skills/session-waker/SKILL.md` (from setup shared)
- Create: `skills/agent-say/SKILL.md` (+ any references)
- Create: `skills/glue-miner/` (SKILL + references; point scan path at `modules/glue-miner`)
- Create: `skills/session-awareness/SKILL.md` (update `active-sessions` → `agt sessions active` or shim name)
- Create: `skills/agent-read/SKILL.md` if present in setup/docs; else draft minimal from `modules/read/README.md`

Sources:

```bash
# Copy then edit hardcoded ~/projects/tjdsneto-setup and ~/projects/agent-* paths.
cp -R ~/projects/tjdsneto-setup/ai/skills/shared/session-waker ~/projects/agent-tools/skills/session-waker
cp -R ~/projects/tjdsneto-setup/ai/skills/shared/agent-say ~/projects/agent-tools/skills/agent-say
mkdir -p ~/projects/agent-tools/skills/glue-miner
cp ~/projects/tjdsneto-setup/ai/skills/shared/glue-miner/SKILL.md ~/projects/agent-tools/skills/glue-miner/
cp -R ~/projects/tjdsneto-setup/ai/skills/shared/glue-miner/references ~/projects/agent-tools/skills/glue-miner/ 2>/dev/null || true
cp -R ~/projects/tjdsneto-setup/ai/skills/claude/session-awareness ~/projects/agent-tools/skills/session-awareness
```

- [ ] **Step 1: Copy skills as above**

- [ ] **Step 2: Path rewrite inventory + fix**

```bash
rg -n 'tjdsneto-setup|projects/agent-registry|projects/agent-say|projects/agent-read|ai/skills/shared/glue-miner' \
  ~/projects/agent-tools/skills ~/projects/agent-tools/modules --glob '!.venv/**'
```

Replace with `agt …` commands or `$AGENT_TOOLS_ROOT` / paths under `~/projects/agent-tools/modules/...`.

Minimum required rewrites:
- glue-miner SKILL scan command → `agt glue scan` or `python3 ~/projects/agent-tools/modules/glue-miner/glue_miner.py`
- session-awareness → `agt sessions active` / `active-sessions` shim
- session-waker skill examples stay `session-waker` (shim) or `agt waker`

- [ ] **Step 3: Commit**

```bash
cd ~/projects/agent-tools
git add skills/
git commit -m "feat: add companion skills with paths pointed at agent-tools"
```

---

### Task 6: `install.sh` (bins, skills, launchd)

**Files:**
- Create: `~/projects/agent-tools/install.sh`

- [ ] **Step 1: Write installer**

```bash
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
         rename-session agent-say agent-read; do
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
for mod in registry say read; do
  if [ -f "$ROOT/modules/$mod/requirements.txt" ] && [ ! -x "$ROOT/modules/$mod/.venv/bin/python" ]; then
    python3 -m venv "$ROOT/modules/$mod/.venv"
    "$ROOT/modules/$mod/.venv/bin/pip" install -r "$ROOT/modules/$mod/requirements.txt"
  fi
done

# glue-miner launchd: write plist with absolute paths, then reload.
PLIST_SRC="$ROOT/modules/glue-miner/launchd/com.tjdsneto.glue-miner.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.tjdsneto.glue-miner.plist"
if [ -f "$PLIST_SRC" ]; then
  # Rewrite ProgramArguments to modules/glue-miner/run-weekly.sh absolute path if needed.
  # Prefer generating from a small template; minimum: copy then sed ROOT into place.
  sed "s|/Users/tjdsneto/projects/tjdsneto-setup/ai/skills/shared/glue-miner|$ROOT/modules/glue-miner|g" \
    "$PLIST_SRC" > "$PLIST_DST"
  uid="$(id -u)"
  launchctl bootout "gui/$uid/com.tjdsneto.glue-miner" 2>/dev/null || true
  launchctl bootstrap "gui/$uid" "$PLIST_DST"
  echo "reloaded com.tjdsneto.glue-miner"
fi

# session-waker: if any sessions registered, regenerate monitor via shim
if command -v session-waker >/dev/null && [ -d "$HOME/.session-waker/sessions" ] \
   && [ -n "$(ls -A "$HOME/.session-waker/sessions" 2>/dev/null || true)" ]; then
  session-waker start || true
fi

echo "agent-tools install complete. Try: agt help && agent-registry --help"
```

```bash
chmod +x ~/projects/agent-tools/install.sh
```

Adjust glue-miner plist `sed` after reading the real plist paths (`plutil -p` / `cat` the source) so every hardcoded setup path is replaced.

- [ ] **Step 2: Dry-run link logic mentally; then run install**

```bash
~/projects/agent-tools/install.sh
```

Expected: links under `~/.local/bin`; `which -a agent-registry` shows agent-tools shim first (or only).

- [ ] **Step 3: Commit**

```bash
cd ~/projects/agent-tools
git add install.sh
git commit -m "feat: add install.sh for bins, skills, and launchd reload"
git push -u origin main
```

---

### Task 7: Path inventory across modules + plugins

**Files:** modify any remaining hardcoded old roots under `modules/` and `skills/`.

- [ ] **Step 1: Full inventory**

```bash
rg -n 'tjdsneto-setup/bin/(session-waker|claude-budget)|projects/agent-registry|projects/agent-say|projects/agent-read|ai/skills/shared/glue-miner|ai/claude/scripts/active-sessions' \
  ~/projects/agent-tools --glob '!.venv/**' --glob '!modules/registry/desktop/**'
```

- [ ] **Step 2: Fix each hit** (prefer `agt` / shim names / `ROOT`-relative). Re-run inventory until empty (or only historical docs).

- [ ] **Step 3: Re-run registry plugin installer if present**

```bash
# If modules/registry/plugin/install exists:
~/projects/agent-tools/modules/registry/plugin/install
```

- [ ] **Step 4: Commit**

```bash
cd ~/projects/agent-tools
git add -u
git commit -m "fix: rewrite hardcoded paths after module import"
git push
```

---

### Task 8: Live-machine smoke (before deleting anything)

- [ ] **Step 1: PATH resolution**

```bash
which agt agent-registry session-waker claude-budget session-report active-sessions agent-say agent-read
# Each should be under ~/.local/bin → ~/projects/agent-tools/...
```

- [ ] **Step 2: Read-only commands**

```bash
agt help
agt registry list | head
agt waker status
agt budget check; true
agt sessions active | head
agt glue scan --days 1 --stdout | head
agt say --help | head
agt read --help | head
```

- [ ] **Step 3: Launchd**

```bash
launchctl print "gui/$(id -u)/com.tjdsneto.glue-miner" | head
# If session-waker monitor loaded:
# plutil -p ~/Library/LaunchAgents/com.tjdsneto.session-waker.monitor.plist | rg AGENT_REGISTRY|Program
```

- [ ] **Step 4: Skill links**

```bash
readlink ~/.claude/skills/session-waker/SKILL.md
readlink ~/.claude/skills/glue-miner/SKILL.md
# Must point into ~/projects/agent-tools/skills/...
```

Do **not** proceed to Task 9/10 until these pass.

---

### Task 9: tjdsneto-setup cleanup (pointer only)

**Files (in setup repo):**
- Remove or stub moved tool bodies (after smoke).
- Fix `bin/session-report` broken symlink.
- Add short pointer doc.
- Stop shipping glue-miner/session-waker skill bodies from setup (install.sh there should not overwrite agent-tools links).

- [ ] **Step 1: Add pointer**

Create `~/projects/tjdsneto-setup/docs/agent-tools.md`:

```markdown
# Agent tools moved

Runtime tools and companion skills live in **https://github.com/tjdsneto/agent-tools**
(`~/projects/agent-tools`). Install with `./install.sh` there.

This repo keeps machine setup only. Do not re-add session-waker / glue-miner / agent-say bodies here.
```

- [ ] **Step 2: Replace setup `bin/` tools with shims to `agt` OR remove from setup PATH reliance**

Preferred: delete copies once `~/.local/bin` shims own the names; remove `tjdsneto-setup/bin` from being the only provider for those names. If setup `bin/` remains on PATH **before** `~/.local/bin`, either:

```bash
# Option A — setup bin becomes wrappers:
# bin/session-waker → exec "$HOME/.local/bin/session-waker" "$@"
# (only if order would otherwise prefer setup's old copy)
```

Or remove the moved scripts from setup `bin/` and ensure `~/.local/bin` precedes setup `bin` on PATH.

- [ ] **Step 3: Update setup `install.sh`** so it does not re-link old skill paths over agent-tools links for moved skills (skip list: session-waker, agent-say, glue-miner, session-awareness, agent-read).

- [ ] **Step 4: Commit on setup master**

```bash
cd ~/projects/tjdsneto-setup
git add docs/agent-tools.md install.sh bin/ ai/skills/  # only what changed
git commit -m "chore: hand agent tooling to agent-tools repo"
git push origin master
```

---

### Task 10: Archive private repos

Only after Task 8 smoke + Task 9 setup push.

- [ ] **Step 1: Final README on each private repo**

```markdown
# Moved

This project now lives in **https://github.com/tjdsneto/agent-tools**
(`modules/registry` | `modules/say` | `modules/read`).

```bash
cd ~/projects/agent-tools && ./install.sh
```
```

Commit and push on each of `agent-registry`, `agent-say`, `agent-read`.

- [ ] **Step 2: Archive via GitHub**

```bash
gh repo archive tjdsneto/agent-registry --yes
gh repo archive tjdsneto/agent-say --yes
gh repo archive tjdsneto/agent-read --yes
```

- [ ] **Step 3: Optional local rename** (do not delete until a week of normal use):

```bash
mv ~/projects/agent-registry ~/projects/agent-registry.archived
mv ~/projects/agent-say ~/projects/agent-say.archived
mv ~/projects/agent-read ~/projects/agent-read.archived
```

---

### Task 11: Roadmap issue — session-search

- [ ] **Step 1: Open issue on agent-tools**

```bash
gh issue create -R tjdsneto/agent-tools \
  --title "Roadmap: session-search (keyword/tool transcript lookup)" \
  --body "$(cat <<'EOF'
## Summary
Cross-session transcript search by keyword / tool / host.

## Out of scope for v1 cutover
Distinct from glue-miner (recurring glue aggregation).

## Notes
Reuse transcript adapters once shared under lib/. Spec: tjdsneto-setup docs/superpowers/specs/2026-11-19-agent-tools-design.md §10.
EOF
)"
```

---

## Self-review (plan vs spec)

| Spec item | Task |
|---|---|
| Public repo + `agt` | 1–2 |
| Shims / old PATH names | 3, 6 |
| Modules membership | 4 |
| Skills | 5–6 |
| Absolute-path launchd | 6 |
| Zero-breakage order (install before delete) | 6→8→9→10 |
| Public scrub | 4 excludes, .gitignore |
| Archive private repos | 10 |
| session-search roadmap only | 11 |
| say/read not merged | 4 copies both; dispatcher separate |

No TBD placeholders. Dispatcher uses `exec`. Cutover forbids archive before smoke.
