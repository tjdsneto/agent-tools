from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Any

from agent_registry import archive, store, topics
from agent_registry.constants import ACTIVE_GAP_SECONDS, STATUSES
from agent_registry.models import (
    RegistryFile,
    Session,
    accumulate_active_seconds,
    is_stale,
    normalize_text,
    now_iso,
    parse_pid,
    public_view,
)
from agent_registry.project import project_key


def _active_gap_seconds() -> int:
    raw = os.environ.get("AGENT_REGISTRY_ACTIVE_GAP_SECONDS")
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return ACTIVE_GAP_SECONDS


def _advance_active(sess: Session, ts: str) -> None:
    """Fold the gap since the last ping into active_seconds, then stamp last_ping."""
    sess.active_seconds = accumulate_active_seconds(
        sess.last_ping, ts, sess.active_seconds, gap_limit=_active_gap_seconds()
    )
    sess.last_ping = ts
    sess.updated_at = ts


class DuplicateSessionError(Exception):
    pass


class UnknownRegistryIdError(Exception):
    pass


class ValidationError(Exception):
    pass


def require_pid(pid: Any) -> int | None:
    """None stays None. Anything else must be a positive int."""
    if pid is None:
        return None
    parsed = parse_pid(pid)
    if parsed is None:
        raise ValidationError(f"invalid pid: {pid}")
    return parsed


def _find_by_session_id(reg: RegistryFile, session_id: str) -> Session | None:
    for s in reg.sessions:
        if s.session_id == session_id:
            return s
    return None


def _find_by_registry_id(reg: RegistryFile, registry_id: str) -> Session | None:
    for s in reg.sessions:
        if s.registry_id == registry_id:
            return s
    return None


def register(
    *,
    agent_type: str,
    session_id: str,
    directory: str,
    parent_session_id: str | None = None,
    model: str | None = None,
    title: str | None = None,
    peer_name: str | None = None,
    socket: str | None = None,
    pid: int | None = None,
    peer_status: str | None = None,
    replace: bool = False,
) -> Session:
    if not agent_type.strip() or not session_id.strip() or not directory.strip():
        raise ValidationError("agent_type, session_id, and directory are required")
    model = normalize_text(model)
    title = normalize_text(title)
    peer_name = normalize_text(peer_name)
    socket = normalize_text(socket)
    peer_status = normalize_text(peer_status)
    pid = require_pid(pid)

    replace_summary: str | None = None
    if replace:
        try:
            from agent_registry.summarize import ARCHIVE_TIMEOUT, prepare_for_archive

            for s in store.load().sessions:
                if s.session_id == session_id:
                    replace_summary = prepare_for_archive(s, timeout=ARCHIVE_TIMEOUT)
                    break
        except Exception:
            replace_summary = None

    def _do_register(reg: RegistryFile) -> Session:
        existing = _find_by_session_id(reg, session_id)
        if existing and not replace:
            raise DuplicateSessionError(f"session_id already registered: {session_id}")
        if existing and replace:
            if replace_summary and not (existing.summary or "").strip():
                existing.summary = replace_summary
            archive.append_session(existing, reason="replace")
            reg.sessions = [s for s in reg.sessions if s.session_id != session_id]
        ts = now_iso()
        sess = Session(
            registry_id=str(uuid.uuid4()),
            session_id=session_id,
            agent_type=agent_type,
            directory=directory,
            parent_session_id=parent_session_id,
            status="idle",
            summary="",
            issue=None,
            pr=None,
            branch=None,
            goflow_timer_id=None,
            registered_at=ts,
            last_ping=ts,
            updated_at=ts,
            model=model,
            title=title,
            peer_name=peer_name,
            socket=socket,
            pid=pid,
            peer_status=peer_status,
        )
        reg.sessions.append(sess)
        return sess

    return store.transact(_do_register)


def update(registry_id: str, **patches: Any) -> Session:
    clear_keys = {
        "clear_issue",
        "clear_pr",
        "clear_branch",
        "clear_goflow_timer",
        "clear_summary",
        "clear_parent_session",
        "clear_model",
        "clear_title",
    }
    set_keys = {
        "status",
        "summary",
        "issue",
        "branch",
        "directory",
        "goflow_timer_id",
        "pr_title",
        "pr_url",
        "parent_session_id",
        "model",
        "title",
    }
    meaningful = False
    for k, v in patches.items():
        if k in clear_keys and v:
            meaningful = True
        elif k in set_keys and v is not None:
            meaningful = True
    if not meaningful:
        raise ValidationError("update requires at least one field flag")

    def _do_update(reg: RegistryFile) -> Session:
        sess = _find_by_registry_id(reg, registry_id)
        if not sess:
            raise UnknownRegistryIdError(registry_id)

        if patches.get("status") is not None:
            if patches["status"] not in STATUSES:
                raise ValidationError(f"invalid status: {patches['status']}")
            sess.status = patches["status"]
        if patches.get("summary") is not None:
            sess.summary = patches["summary"]
        if patches.get("directory") is not None:
            sess.directory = patches["directory"]
        if patches.get("issue") is not None:
            sess.issue = patches["issue"]
        if patches.get("branch") is not None:
            sess.branch = patches["branch"]
        if patches.get("goflow_timer_id") is not None:
            sess.goflow_timer_id = patches["goflow_timer_id"]
        if patches.get("parent_session_id") is not None:
            sess.parent_session_id = patches["parent_session_id"]
        if patches.get("model") is not None:
            sess.model = normalize_text(patches["model"])
        if patches.get("title") is not None:
            sess.title = normalize_text(patches["title"])

        if patches.get("pr_title") is not None or patches.get("pr_url") is not None:
            pr = dict(sess.pr) if sess.pr else {"title": "", "url": ""}
            if patches.get("pr_title") is not None:
                pr["title"] = patches["pr_title"]
            if patches.get("pr_url") is not None:
                pr["url"] = patches["pr_url"]
            sess.pr = pr

        if patches.get("clear_issue"):
            sess.issue = None
        if patches.get("clear_pr"):
            sess.pr = None
        if patches.get("clear_branch"):
            sess.branch = None
        if patches.get("clear_goflow_timer"):
            sess.goflow_timer_id = None
        if patches.get("clear_summary"):
            sess.summary = ""
        if patches.get("clear_parent_session"):
            sess.parent_session_id = None
        if patches.get("clear_model"):
            sess.model = None
        if patches.get("clear_title"):
            sess.title = None

        _advance_active(sess, now_iso())
        return sess

    return store.transact(_do_update)


def ping(
    registry_id: str,
    *,
    model: str | None = None,
    title: str | None = None,
    peer_name: str | None = None,
    socket: str | None = None,
    pid: int | None = None,
    peer_status: str | None = None,
    status: str | None = None,
) -> Session:
    """Refresh last_ping. Optional fields update only when explicitly passed."""
    model_provided = model is not None
    title_provided = title is not None
    peer_name_provided = peer_name is not None
    socket_provided = socket is not None
    pid_provided = pid is not None
    peer_status_provided = peer_status is not None
    status_provided = status is not None
    model_norm = normalize_text(model) if model_provided else None
    title_norm = normalize_text(title) if title_provided else None
    peer_name_norm = normalize_text(peer_name) if peer_name_provided else None
    socket_norm = normalize_text(socket) if socket_provided else None
    peer_status_norm = normalize_text(peer_status) if peer_status_provided else None
    pid_norm = require_pid(pid) if pid_provided else None
    status_norm = normalize_text(status) if status_provided else None
    if status_provided and status_norm not in STATUSES:
        raise ValidationError(f"invalid status: {status}")

    def _do_ping(reg: RegistryFile) -> Session:
        sess = _find_by_registry_id(reg, registry_id)
        if not sess:
            raise UnknownRegistryIdError(registry_id)
        _advance_active(sess, now_iso())
        if model_provided:
            sess.model = model_norm
        if title_provided:
            sess.title = title_norm
        if peer_name_provided:
            sess.peer_name = peer_name_norm
        if socket_provided:
            sess.socket = socket_norm
        if pid_provided:
            sess.pid = pid_norm
        if peer_status_provided:
            sess.peer_status = peer_status_norm
        if status_provided:
            sess.status = status_norm
        return sess

    return store.transact(_do_ping)


def unregister(registry_id: str) -> None:
    suggested = _suggest_summary_outside(registry_id)

    def _do_unregister(reg: RegistryFile) -> None:
        sess = _find_by_registry_id(reg, registry_id)
        if not sess:
            raise UnknownRegistryIdError(registry_id)
        if suggested and not (sess.summary or "").strip():
            sess.summary = suggested
        archive.append_session(sess, reason="unregister")
        reg.sessions = [s for s in reg.sessions if s.registry_id != registry_id]

    store.transact(_do_unregister)


def delete(registry_id: str) -> None:
    """Remove a session from the live board with no archive record."""

    def _do_delete(reg: RegistryFile) -> None:
        sess = _find_by_registry_id(reg, registry_id)
        if not sess:
            raise UnknownRegistryIdError(registry_id)
        reg.sessions = [s for s in reg.sessions if s.registry_id != registry_id]

    store.transact(_do_delete)


def list_split(*, now: datetime | None = None) -> tuple[list[dict], list[dict]]:
    reg = store.load()
    active, stale = [], []
    for s in reg.sessions:
        view = public_view(s)
        view.update(topics.current(s.agent_type, s.session_id))
        (stale if is_stale(s, now=now) else active).append(view)
    return active, stale


def live_views(*, now: datetime | None = None) -> dict[str, list[dict]]:
    reg = store.load()
    active, stale, attention = [], [], []
    seen_attention: set[str] = set()
    for s in reg.sessions:
        view = public_view(s)
        view["project"] = project_key(s.directory)
        view.update(topics.current(s.agent_type, s.session_id))
        stale_flag = is_stale(s, now=now)
        blocked = s.status == "blocked"
        if blocked or stale_flag:
            if s.session_id not in seen_attention:
                attention.append(view)
                seen_attention.add(s.session_id)
        if stale_flag:
            stale.append(view)
        elif not blocked:
            active.append(view)
    return {"active": active, "stale": stale, "attention": attention}


def prune(*, dry_run: bool = False, yes: bool = False, now: datetime | None = None) -> list[dict]:
    if not dry_run and not yes:
        raise ValidationError("prune requires --yes or --dry-run")

    if dry_run:
        reg = store.load()
        return [public_view(s) for s in reg.sessions if is_stale(s, now=now)]

    # Suggest summaries outside the flock (LLM must not hold the lock).
    from agent_registry.summarize import (
        PRUNE_MAX_SUMMARIES,
        PRUNE_PER_SESSION_TIMEOUT,
        prepare_for_archive,
    )

    reg_peek = store.load()
    suggestions: dict[str, str] = {}
    budget = PRUNE_MAX_SUMMARIES
    for s in reg_peek.sessions:
        if not is_stale(s, now=now):
            continue
        if budget <= 0:
            break
        if (s.summary or "").strip():
            continue
        try:
            line = prepare_for_archive(s, timeout=PRUNE_PER_SESSION_TIMEOUT)
        except Exception:
            line = None
        if line:
            suggestions[s.registry_id] = line
            budget -= 1

    def _do_prune(reg: RegistryFile) -> list[dict]:
        removed_sessions = [s for s in reg.sessions if is_stale(s, now=now)]
        for s in removed_sessions:
            line = suggestions.get(s.registry_id)
            if line and not (s.summary or "").strip():
                s.summary = line
            archive.append_session(s, reason="prune")
        removed = [public_view(s) for s in removed_sessions]
        reg.sessions = [s for s in reg.sessions if not is_stale(s, now=now)]
        return removed

    return store.transact(_do_prune)


def _suggest_summary_outside(registry_id: str) -> str | None:
    """Generate a summary suggestion without holding the registry lock."""
    try:
        from agent_registry.summarize import ARCHIVE_TIMEOUT, prepare_for_archive

        for s in store.load().sessions:
            if s.registry_id == registry_id:
                return prepare_for_archive(s, timeout=ARCHIVE_TIMEOUT)
    except Exception:
        return None
    return None
