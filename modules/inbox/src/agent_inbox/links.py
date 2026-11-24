from __future__ import annotations

import json
import os
import subprocess

from agent_inbox.constants import HTTP_PORT

# install.sh serves the UI over Tailscale on this port.
TAILNET_UI_PORT = 8444


def ui_origin() -> str:
    """Where Tiago opens the inbox: INBOX_UI_ORIGIN, else this Mac's tailnet name, else localhost.

    serve has INBOX_UI_ORIGIN from its LaunchAgent; an agent's shell usually does not,
    so the CLI asks Tailscale the way install.sh does.
    """
    configured = os.environ.get("INBOX_UI_ORIGIN")
    if configured:
        return configured.rstrip("/")
    try:
        proc = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=3)
        name = json.loads(proc.stdout)["Self"]["DNSName"].rstrip(".")
        if name:
            return f"https://{name}:{TAILNET_UI_PORT}"
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
        pass
    return f"http://127.0.0.1:{HTTP_PORT}"


def entry_url(entry_id: str) -> str:
    return f"{ui_origin()}/e/{entry_id}"
