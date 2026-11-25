#!/usr/bin/env python3
"""Live, scope-aware inventory of the capabilities an AI agent has here.

Scans what is actually installed on disk RIGHT NOW — skills, subagents, MCP
servers, plugins — and classifies each by the scope it is valid in. Scope is
derived from where the file lives: a global skill is usable in any repo, a
project skill only inside its repo. Run from a repo to see global capabilities
plus that repo's; run from elsewhere and the repo-scoped tools correctly drop
away. Models have no on-disk source, so they come from the bundled models.tsv
(the one hand-maintained slice).

Usage:
  registry.py                      # everything usable from the current dir
  registry.py --kind skill|agent|mcp|plugin|model
  registry.py --search TERM        # match name or description
  registry.py --project PATH       # inspect another repo's inventory from here
  registry.py --json               # machine-readable
  registry.py --self-test          # sanity-check the scan (non-zero if empty)
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

HOME = Path.home()
GLOBAL_CLAUDE = HOME / ".claude"
GLOBAL_CURSOR = HOME / ".cursor" / "skills-cursor"


# ── pure helpers (unit-tested in test_registry.py) ──────────────────────────

def parse_frontmatter(text):
    """Return {'name','description'} from a SKILL.md/agent YAML frontmatter
    block. Only the leading `---`…`---` block is read, so a `description:` that
    appears later in the body is ignored. Handles YAML block scalars
    (`description: >-` with the text on indented lines below). Missing keys come
    back empty."""
    out = {"name": "", "description": ""}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return out
    i = 1
    while i < len(lines):
        line = lines[i]
        if line.strip() == "---":
            break
        advanced = False
        for key in ("name", "description"):
            prefix = key + ":"
            if not line.startswith(prefix):
                continue
            value = line[len(prefix):].strip()
            if value and value[0] in "|>":  # block scalar — text on indented lines below
                folded = []
                i += 1
                while i < len(lines) and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
                    folded.append(lines[i].strip())
                    i += 1
                out[key] = " ".join(w for w in folded if w).strip()
                advanced = True
            else:
                out[key] = value
            break
        if not advanced:
            i += 1
    return out


def current_runtime(env=None):
    """Which agent runtime is executing this scan. CLAUDECODE wins even when
    CURSOR_* is also set, because a Claude Code session hosted inside Cursor's
    IDE carries both — but the agent is still Claude. None = can't tell."""
    env = os.environ if env is None else env
    if "CLAUDECODE" in env:
        return "claude"
    if any(k.startswith("CURSOR") for k in env):
        return "cursor"
    return None


def skill_runnable(entry, current):
    """False only when we know the runtime AND the skill is a skill that does
    not deploy to it (e.g. a cursor-only skill seen from Claude Code)."""
    if current is None or entry["kind"] != "skill":
        return True
    return current in entry["runtime"].split("+")


def merge_runtimes(entries):
    """Collapse the same global skill deployed to multiple runtimes (Claude +
    Cursor share buckets) into one entry tagged `claude+cursor`, so the shared
    catalog isn't listed twice. Project-scoped and non-skill entries pass
    through unchanged."""
    merged = []
    index = {}
    for e in entries:
        if e["kind"] == "skill" and e["scope"] == "global":
            existing = index.get(e["name"])
            if existing is not None:
                runtimes = set(existing["runtime"].split("+")) | {e["runtime"]}
                existing["runtime"] = "+".join(sorted(runtimes))
                if not existing["description"] and e["description"]:
                    existing["description"] = e["description"]
                continue
            e = dict(e)
            index[e["name"]] = e
        merged.append(e)
    return merged


def is_within(cwd, root):
    """True if cwd is root or nested under it. Guards the string-prefix trap:
    /a/foobar is NOT within /a/foo."""
    cwd = os.path.normpath(cwd)
    root = os.path.normpath(root)
    if cwd == root:
        return True
    try:
        return os.path.commonpath([cwd, root]) == root
    except ValueError:  # different drives / relative-vs-absolute
        return False


# ── scanning ────────────────────────────────────────────────────────────────

def _entry(kind, name, scope, source, description="", runtime="claude", usable=True):
    return {
        "kind": kind,
        "name": name,
        "scope": scope,
        "runtime": runtime,
        "source": str(source),
        "description": description,
        "usable_here": usable,
    }


def _read_fm(path):
    try:
        return parse_frontmatter(Path(path).read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return {"name": "", "description": ""}


def _scan_skill_dir(base, scope, runtime, usable=True):
    entries = []
    if not base.is_dir():
        return entries
    for skill_md in sorted(base.glob("*/SKILL.md")):
        fm = _read_fm(skill_md)
        entries.append(_entry(
            "skill", fm["name"] or skill_md.parent.name, scope, skill_md,
            fm["description"], runtime, usable))
    return entries


def _scan_agent_dir(base, scope, runtime, usable=True):
    entries = []
    if not base.is_dir():
        return entries
    for agent_md in sorted(base.glob("*.md")):
        if agent_md.name.upper() == "README.MD":
            continue
        fm = _read_fm(agent_md)
        entries.append(_entry(
            "agent", fm["name"] or agent_md.stem, scope, agent_md,
            fm["description"], runtime, usable))
    return entries


def scan_global():
    entries = []
    entries += _scan_skill_dir(GLOBAL_CLAUDE / "skills", "global", "claude")
    entries += _scan_skill_dir(GLOBAL_CURSOR, "global", "cursor")
    entries += _scan_agent_dir(GLOBAL_CLAUDE / "agents", "global", "claude")
    return entries


def scan_plugins(cwd):
    """Plugins from installed_plugins.json. A user-scoped plugin is global; a
    project-scoped one is only usable under its projectPath."""
    entries = []
    manifest = GLOBAL_CLAUDE / "plugins" / "installed_plugins.json"
    try:
        data = json.loads(manifest.read_text())
    except (OSError, ValueError):
        return entries
    for plugin_key, installs in (data.get("plugins") or {}).items():
        for inst in installs or []:
            scope_kind = inst.get("scope", "user")
            install_path = Path(inst.get("installPath", ""))
            if scope_kind == "project":
                proj = inst.get("projectPath", "")
                scope = f"plugin:{plugin_key} (project:{Path(proj).name})"
                usable = bool(proj) and is_within(cwd, proj)
            else:
                scope = f"plugin:{plugin_key}"
                usable = True
            # count the plugin's own bundled skills/agents, if any
            child = []
            child += _scan_skill_dir(install_path / "skills", scope, "claude", usable)
            child += _scan_agent_dir(install_path / "agents", scope, "claude", usable)
            if child:
                entries += [dict(e, kind="plugin") for e in child]
            else:
                entries.append(_entry("plugin", plugin_key, scope, install_path,
                                      "", "claude", usable))
    return entries


def _ancestor_project_roots(cwd):
    """Every ancestor of cwd (and cwd itself) that holds a .claude dir, except
    $HOME/.claude which is the GLOBAL bucket, not a project."""
    roots = []
    p = Path(cwd).resolve()
    for cand in [p, *p.parents]:
        if cand == HOME:
            break
        if (cand / ".claude").is_dir():
            roots.append(cand)
    return roots


def scan_projects(cwd):
    entries = []
    for root in _ancestor_project_roots(cwd):
        label = f"project:{root.name}"
        entries += _scan_skill_dir(root / ".claude" / "skills", label, "claude")
        entries += _scan_agent_dir(root / ".claude" / "agents", label, "claude")
    return entries


def scan_mcp(cwd):
    """MCP servers configured on disk: global + per-project in ~/.claude.json,
    plus committed .mcp.json files up the tree. Account-level claude.ai
    connectors are NOT on disk — see the note in human output."""
    entries = []
    seen = set()

    def add(name, scope, source, usable):
        if (name, scope) in seen:
            return
        seen.add((name, scope))
        entries.append(_entry("mcp", name, scope, source, "", "claude", usable))

    cfg = GLOBAL_CLAUDE.parent / ".claude.json"
    try:
        data = json.loads(cfg.read_text())
    except (OSError, ValueError):
        data = {}
    for name in (data.get("mcpServers") or {}):
        add(name, "global", cfg, True)
    for proj_path, proj in (data.get("projects") or {}).items():
        for name in (proj.get("mcpServers") or {}):
            add(name, f"project:{Path(proj_path).name}", cfg, is_within(cwd, proj_path))

    for root in _ancestor_project_roots(cwd):
        mcp_json = root / ".mcp.json"
        try:
            j = json.loads(mcp_json.read_text())
        except (OSError, ValueError):
            continue
        for name in (j.get("mcpServers") or {}):
            add(name, f"project:{root.name}", mcp_json, True)
    return entries


def scan_clis():
    """Agent-callable CLI wrappers from the curated clis.tsv (this skill's
    source of truth). A listed command shows only when it actually resolves on
    PATH — an uninstalled one is marked not-usable-here (hidden unless --all)."""
    entries = []
    tsv = Path(__file__).with_name("clis.tsv")
    try:
        rows = tsv.read_text().splitlines()
    except OSError:
        return entries
    for row in rows:
        row = row.rstrip("\n")
        if not row.strip() or row.lstrip().startswith("#"):
            continue
        parts = row.split("\t")
        cmd = parts[0].strip()
        if not cmd:
            continue
        desc = parts[1].strip() if len(parts) > 1 else ""
        entries.append(_entry("cli", cmd, "global", tsv, desc,
                              usable=shutil.which(cmd) is not None))
    return entries


def scan_models():
    entries = []
    tsv = Path(__file__).with_name("models.tsv")
    try:
        rows = tsv.read_text().splitlines()
    except OSError:
        return entries
    for row in rows:
        row = row.strip()
        if not row or row.startswith("#"):
            continue
        parts = row.split("\t")
        name = parts[0]
        model_id = parts[1] if len(parts) > 1 else ""
        note = parts[2] if len(parts) > 2 else ""
        desc = f"id: {model_id}" + (f" — {note}" if note else "")
        entries.append(_entry("model", name, "global", tsv, desc))
    return entries


def scan_all(cwd):
    return (scan_global() + scan_plugins(cwd) + scan_projects(cwd)
            + scan_mcp(cwd) + scan_clis() + scan_models())


# ── rendering ─────────────────────────────────────────────────────────────

KIND_ORDER = ["skill", "agent", "cli", "mcp", "plugin", "model"]


def _truncate(s, n=96):
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def render_human(entries, cwd, current=None):
    rt = current or "unknown"
    out = [f"Capabilities usable from: {cwd}  (runtime: {rt})", ""]
    # scope bands: global first, then each project scope, plugins folded into global band
    def band(e):
        if e["scope"].startswith("project:"):
            return e["scope"]
        return "global (usable anywhere)"

    bands = {}
    for e in entries:
        bands.setdefault(band(e), []).append(e)

    ordered = ["global (usable anywhere)"] + sorted(
        b for b in bands if b != "global (usable anywhere)")
    for b in ordered:
        band_entries = bands.get(b)
        if not band_entries:
            continue
        out.append(f"── {b} " + "─" * max(0, 60 - len(b)))
        by_kind = {}
        for e in band_entries:
            by_kind.setdefault(e["kind"], []).append(e)
        for kind in KIND_ORDER:
            items = sorted(by_kind.get(kind, []), key=lambda e: e["name"].lower())
            if not items:
                continue
            out.append(f"  {kind}s ({len(items)}):")
            for e in items:
                desc = f"  — {_truncate(e['description'])}" if e["description"] else ""
                tag = "" if e["runtime"] == "claude" else f" [{e['runtime']}]"
                flag = ""
                if not skill_runnable(e, current):
                    flag = f"  ✗ NOT runnable from {current} ({e['runtime']}-only)"
                out.append(f"    • {e['name']}{tag}{desc}{flag}")
        out.append("")
    out.append("Notes: MCP list = servers configured on disk. Account-level "
               "claude.ai connectors (Gmail, Asana, Stripe…) are not on disk — "
               "run /mcp in an interactive session for those. Models are "
               "hand-maintained in models.tsv.")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Live scope-aware capability registry.")
    ap.add_argument("--kind", choices=KIND_ORDER)
    ap.add_argument("--search", metavar="TERM")
    ap.add_argument("--project", metavar="PATH", help="effective dir for scope resolution")
    ap.add_argument("--runtime", choices=["claude", "cursor"],
                    help="override detected runtime (flags wrong-runtime skills)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--all", action="store_true",
                    help="include out-of-scope entries (default hides them)")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    cwd = os.path.abspath(args.project or os.getcwd())
    current = args.runtime or current_runtime()
    entries = merge_runtimes(scan_all(cwd))
    for e in entries:
        e["runtime_ok"] = skill_runnable(e, current)

    if not args.all:
        entries = [e for e in entries if e["usable_here"]]
    if args.kind:
        entries = [e for e in entries if e["kind"] == args.kind]
    if args.search:
        t = args.search.lower()
        entries = [e for e in entries
                   if t in e["name"].lower() or t in e["description"].lower()]

    if args.self_test:
        counts = {k: sum(1 for e in entries if e["kind"] == k) for k in KIND_ORDER}
        print("self-test counts:", counts)
        empty = [k for k in ("skill", "cli", "mcp", "model") if counts[k] == 0]
        if empty:
            print("FAIL: expected non-empty:", empty)
            return 1
        print("ok")
        return 0

    if args.json:
        print(json.dumps(entries, indent=2))
    else:
        print(render_human(entries, cwd, current))
    return 0


if __name__ == "__main__":
    sys.exit(main())
