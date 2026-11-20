from __future__ import annotations

import os
from datetime import datetime, timezone

from agent_registry import ops, session_state, store, usage
from agent_registry.constants import HEARTBEAT_SECONDS
from agent_registry.models import normalize_text, now_iso


def _heartbeat_seconds() -> int:
    raw = os.environ.get("AGENT_REGISTRY_HEARTBEAT_SECONDS")
    if raw:
        try:
            return max(60, int(raw))
        except ValueError:
            pass
    return HEARTBEAT_SECONDS


def _session_meta(registry_id: str) -> dict | None:
    """Current recorded fields, without refreshing last_ping. None if missing."""
    for s in store.load().sessions:
        if s.registry_id == registry_id:
            return {
                "model": normalize_text(s.model),
                "title": normalize_text(s.title),
                "peer_name": normalize_text(s.peer_name),
                "socket": normalize_text(s.socket),
                "pid": s.pid,
                "peer_status": normalize_text(s.peer_status),
                "status": normalize_text(s.status),
            }
    return None


def _ping_kwargs(
    *,
    model: str | None,
    title: str | None,
    peer_name: str | None = None,
    socket: str | None = None,
    pid: int | None = None,
    peer_status: str | None = None,
    status: str | None = None,
) -> dict:
    kw: dict = {}
    if model is not None:
        kw["model"] = model
    if title is not None:
        kw["title"] = title
    if peer_name is not None:
        kw["peer_name"] = peer_name
    if socket is not None:
        kw["socket"] = socket
    if pid is not None:
        kw["pid"] = pid
    if peer_status is not None:
        kw["peer_status"] = peer_status
    if status is not None:
        kw["status"] = status
    return kw


def _cursor_harness_title(session_id: str) -> str | None:
    """Composer display name from Cursor state.vscdb, or None if missing."""
    try:
        return usage.cursor_composer_names({session_id}).get(session_id)
    except Exception:
        return None


def _resolve_title(agent_type: str, session_id: str, title: str | None) -> str | None:
    """Prefer an explicit title; for Cursor, fall back to the composer name.

    Cursor hooks omit the chat title. The composer name is the harness display
    title — distinct from summary — and is re-read on ensure and heartbeat so
    renames stick without waiting for a board poll.
    """
    title = normalize_text(title)
    if title is not None or agent_type != "cursor":
        return title
    return _cursor_harness_title(session_id)


def ensure(
    agent_type: str,
    session_id: str,
    directory: str,
    *,
    parent_session: str | None = None,
    model: str | None = None,
    title: str | None = None,
    peer_name: str | None = None,
    socket: str | None = None,
    pid: int | None = None,
    peer_status: str | None = None,
    replace: bool = True,
) -> dict:
    """Register if needed; always refresh sidecar. Default replace=True for resume/crash.

    When replace=False, an existing sidecar must reference a live registry row; stale or
    missing registry_id raises UnknownRegistryIdError instead of re-registering.
    Optional model/title are recorded on register and refreshed when provided.
    """
    model = normalize_text(model)
    title = _resolve_title(agent_type, session_id, title)
    peer_name = normalize_text(peer_name)
    socket = normalize_text(socket)
    peer_status = normalize_text(peer_status)
    pid = ops.require_pid(pid)
    address = dict(
        peer_name=peer_name, socket=socket, pid=pid, peer_status=peer_status,
    )
    existing = session_state.read_state(agent_type, session_id)

    if existing:
        registry_id = existing.get("registry_id")
        if registry_id:
            try:
                sess = ops.ping(
                    registry_id, **_ping_kwargs(model=model, title=title, **address)
                )
                if replace and sess.directory != directory:
                    sess = ops.update(registry_id, directory=directory)
                if (
                    replace
                    and parent_session is not None
                    and sess.parent_session_id != parent_session
                ):
                    sess = ops.update(registry_id, parent_session_id=parent_session)
                ts = now_iso()
                session_state.write_state(
                    agent_type,
                    session_id,
                    registry_id=sess.registry_id,
                    last_heartbeat_at=ts,
                )
                return {"created": False, "session": sess.to_dict()}
            except ops.UnknownRegistryIdError:
                if not replace:
                    raise
        elif not replace:
            raise ops.UnknownRegistryIdError("missing sidecar registry_id")

    sess = ops.register(
        agent_type=agent_type,
        session_id=session_id,
        directory=directory,
        parent_session_id=parent_session,
        model=model,
        title=title,
        replace=True,
        **address,
    )
    ts = now_iso()
    session_state.write_state(
        agent_type, session_id, registry_id=sess.registry_id, last_heartbeat_at=ts
    )
    return {"created": True, "session": sess.to_dict()}


def heartbeat(
    agent_type: str,
    session_id: str,
    *,
    model: str | None = None,
    title: str | None = None,
    peer_name: str | None = None,
    socket: str | None = None,
    pid: int | None = None,
    peer_status: str | None = None,
    status: str | None = None,
) -> dict:
    """Throttled ping. Changed model, title, status, or harness address bypasses the throttle."""
    model = normalize_text(model)
    title = _resolve_title(agent_type, session_id, title)
    peer_name = normalize_text(peer_name)
    socket = normalize_text(socket)
    peer_status = normalize_text(peer_status)
    status = normalize_text(status)
    pid = ops.require_pid(pid)
    st = session_state.read_state(agent_type, session_id)
    if not st:
        return {"skipped": True, "reason": "no_sidecar"}
    registry_id = st.get("registry_id")
    if not registry_id:
        return {"skipped": True, "reason": "no_registry_id"}

    incoming = {
        "model": model,
        "title": title,
        "peer_name": peer_name,
        "socket": socket,
        "pid": pid,
        "peer_status": peer_status,
        "status": status,
    }
    meta_changed = False
    if any(v is not None for v in incoming.values()):
        current = _session_meta(registry_id)
        if current is None:
            return {"skipped": True, "reason": "no_registry_id"}
        for key, value in incoming.items():
            if value is not None and current[key] != value:
                meta_changed = True

    last = st.get("last_heartbeat_at")
    if last and not meta_changed:
        try:
            last_dt = datetime.fromisoformat(last)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - last_dt).total_seconds()
            if age < _heartbeat_seconds():
                return {"skipped": True, "reason": "throttled", "age_seconds": age}
        except ValueError:
            pass

    sess = ops.ping(registry_id, **_ping_kwargs(
        model=model, title=title, peer_name=peer_name, socket=socket,
        pid=pid, peer_status=peer_status, status=status,
    ))
    ts = now_iso()
    session_state.write_state(
        agent_type, session_id, registry_id=sess.registry_id, last_heartbeat_at=ts
    )
    return {"skipped": False, "session": sess.to_dict(), "meta_changed": meta_changed}


def end(agent_type: str, session_id: str) -> dict:
    st = session_state.read_state(agent_type, session_id)
    if not st:
        return {"ok": True, "reason": "no_sidecar"}
    registry_id = st.get("registry_id")
    if registry_id:
        try:
            ops.unregister(registry_id)
        except ops.UnknownRegistryIdError:
            pass
        except Exception:
            return {"ok": False, "reason": "unregister_failed"}
    session_state.delete_state(agent_type, session_id)
    return {"ok": True}


def self_view(agent_type: str, session_id: str) -> dict | None:
    """Owner lookup: sidecar registry_id → full session dict, or None.

    Returns None when there is no sidecar, no registry_id in the sidecar, or the
    registry entry is gone (UnknownRegistryIdError). Used by agents that need
    registry_id for update after hooks owned ensure.
    """
    st = session_state.read_state(agent_type, session_id)
    if not st:
        return None
    registry_id = st.get("registry_id")
    if not registry_id:
        return None
    try:
        return ops.ping(registry_id).to_dict()
    except ops.UnknownRegistryIdError:
        return None
