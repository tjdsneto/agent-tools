from __future__ import annotations

from pathlib import Path

KNOWN_ROOT_NAMES = frozenset({
    "projects",
    "Projects",
    "dev",
    "src",
    "Sites",
    "Local Sites",
    "work",
})


def project_key(directory: str) -> str:
    try:
        path = Path(directory).expanduser().resolve()
    except OSError:
        return Path(directory).name or directory
    # Prefer the path itself unless it is an existing file (then use parent).
    # Missing paths that look like directories keep their leaf name.
    cur = path.parent if path.is_file() else path

    # Known roots beat .git — $HOME is often a git repo and would swallow
    # every ~/projects/<name> path into one group.
    if cur.parent.name in KNOWN_ROOT_NAMES:
        return cur.name

    if path.exists():
        home = Path.home().resolve()
        for p in [cur, *cur.parents]:
            if p == home:
                continue
            if (p / ".git").exists():
                return p.name

    return cur.name or str(path)
