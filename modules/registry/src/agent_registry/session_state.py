from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from agent_registry.store import registry_path


def data_dir() -> Path:
    return registry_path().parent


def sidecar_path(agent_type: str, session_id: str) -> Path:
    safe_type = agent_type.strip().replace("/", "_")
    safe_sid = session_id.strip().replace("/", "_")
    return data_dir() / "by-session" / safe_type / f"{safe_sid}.json"


def read_state(agent_type: str, session_id: str) -> dict | None:
    path = sidecar_path(agent_type, session_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def write_state(
    agent_type: str,
    session_id: str,
    *,
    registry_id: str,
    last_heartbeat_at: str,
) -> None:
    path = sidecar_path(agent_type, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"registry_id": registry_id, "last_heartbeat_at": last_heartbeat_at}
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def delete_state(agent_type: str, session_id: str) -> None:
    path = sidecar_path(agent_type, session_id)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
