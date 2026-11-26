"""The conversation skill's core rules, injected at session start."""
from __future__ import annotations

import os
from pathlib import Path


def default_path() -> Path:
    return Path(__file__).resolve().parents[4] / "skills" / "conversation" / "CORE.md"


def core_text() -> str | None:
    """The core rules, stripped. None when the file is missing, unreadable or not UTF-8."""
    override = os.environ.get("AGENT_REGISTRY_CONVERSATION_CORE")
    path = Path(override) if override else default_path()
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
