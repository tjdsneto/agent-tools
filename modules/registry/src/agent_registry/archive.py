from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from agent_registry import store
from agent_registry.constants import ARCHIVE_REASONS
from agent_registry.models import Session, now_iso

ArchiveStatus = Literal["ok", "missing", "corrupt"]


class ValidationError(Exception):
    pass


class ArchiveIOError(Exception):
    pass


class ArchiveCorruptError(ArchiveIOError):
    pass


def archive_path() -> Path:
    return store.registry_path().with_name("archive.jsonl")


def append_session(session: Session, *, reason: str) -> dict[str, Any]:
    """Append a session snapshot to archive.jsonl.

    Callers must already hold the live registry lock (via store.hold_lock /
    store.transact). This function does not take the lock — flock is
    non-reentrant and would deadlock.
    """
    if reason not in ARCHIVE_REASONS:
        raise ValidationError(f"invalid archive reason: {reason}")
    path = archive_path()
    _, status = read_events_result()
    if status == "corrupt":
        raise ArchiveCorruptError(
            f"archive is corrupt; refuse append: {path}"
        )
    event = {
        "archived_at": now_iso(),
        "reason": reason,
        "session": session.to_dict(),  # includes registry_id
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, separators=(",", ":")) + "\n"
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
    except OSError as e:
        raise ArchiveIOError(str(e)) from e
    return event


def read_events_result() -> tuple[list[dict[str, Any]], ArchiveStatus]:
    """Strict-aware read: returns (events, status).

    status is "ok" | "missing" | "corrupt". Soft callers can ignore status;
    mutate paths must refuse when status == "corrupt".
    """
    path = archive_path()
    if not path.exists():
        return [], "missing"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return [], "corrupt"
    if not text.strip():
        return [], "missing"
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            return [], "corrupt"
        if not isinstance(obj, dict) or "reason" not in obj or "session" not in obj:
            return [], "corrupt"
        out.append(obj)
    return out, "ok"


def read_events() -> list[dict[str, Any]]:
    """Soft read for list/dashboard: corrupt → []."""
    events, _ = read_events_result()
    return events


def is_corrupt() -> bool:
    _, status = read_events_result()
    return status == "corrupt"


def list_events(
    *, reason: str | None = None, limit: int | None = 100
) -> list[dict[str, Any]]:
    if limit is not None and limit < 0:
        raise ValidationError("limit must be >= 0")
    events = read_events()
    if reason is not None:
        if reason not in ARCHIVE_REASONS:
            raise ValidationError(f"invalid archive reason: {reason}")
        events = [e for e in events if e.get("reason") == reason]
    events = list(reversed(events))  # newest first
    if limit is not None:
        events = events[:limit]
    return events


def public_event(event: dict[str, Any]) -> dict[str, Any]:
    sess = dict(event.get("session") or {})
    sess.pop("registry_id", None)
    return {
        "archived_at": event.get("archived_at"),
        "reason": event.get("reason"),
        "session": sess,
    }


def purge_older_than(*, days: int, yes: bool = False) -> list[dict[str, Any]]:
    if days < 1:
        raise ValidationError("days must be >= 1")
    if not yes:
        raise ValidationError("purge requires --yes")
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400

    def _parse(ts: str) -> float:
        s = ts[:-1] + "+00:00" if ts.endswith("Z") else ts
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()

    with store.hold_lock():
        events, status = read_events_result()
        if status == "corrupt":
            raise ArchiveCorruptError(
                f"archive is corrupt; refuse purge: {archive_path()}"
            )
        keep: list[dict[str, Any]] = []
        removed: list[dict[str, Any]] = []
        for e in events:
            try:
                age_ok = _parse(e["archived_at"]) >= cutoff
            except (KeyError, TypeError, ValueError):
                removed.append(e)
                continue
            if age_ok:
                keep.append(e)
            else:
                removed.append(e)
        _write_all_atomic(keep)
        return [public_event(e) for e in removed]


def _write_all_atomic(events: list[dict[str, Any]]) -> None:
    path = archive_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(e, separators=(",", ":")) + "\n" for e in events)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=".archive.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            tmp.write(payload)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
