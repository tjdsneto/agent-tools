from __future__ import annotations
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from agent_registry.constants import STALE_SECONDS

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def parse_pid(value: Any) -> int | None:
    """Positive int, or None. Lenient: bad values do not crash a registry load."""
    if value is None or value == "":
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def normalize_text(value: str | None) -> str | None:
    """Empty / whitespace → None; otherwise stripped text."""
    if value is None:
        return None
    s = str(value).strip()
    return s or None

# Back-compat alias used by older call sites / docs.
normalize_model = normalize_text

@dataclass
class Session:
    registry_id: str
    session_id: str
    agent_type: str
    directory: str
    parent_session_id: str | None
    status: str
    summary: str
    issue: str | None
    pr: dict[str, str] | None
    branch: str | None
    goflow_timer_id: str | None
    registered_at: str
    last_ping: str
    updated_at: str
    model: str | None = None
    title: str | None = None
    active_seconds: float = 0.0
    # Harness address, harvested by the hook. Distinct from `title` (topic)
    # and from `status` (work state: idle/working/reviewing/blocked).
    peer_name: str | None = None
    socket: str | None = None
    pid: int | None = None
    peer_status: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Session:
        return cls(
            registry_id=d["registry_id"],
            session_id=d["session_id"],
            agent_type=d["agent_type"],
            directory=d["directory"],
            parent_session_id=d.get("parent_session_id"),
            status=d.get("status", "idle"),
            summary=d.get("summary") or "",
            issue=d.get("issue"),
            pr=d.get("pr"),
            branch=d.get("branch"),
            goflow_timer_id=d.get("goflow_timer_id"),
            registered_at=d["registered_at"],
            last_ping=d["last_ping"],
            updated_at=d["updated_at"],
            model=normalize_text(d.get("model")),
            title=normalize_text(d.get("title")),
            active_seconds=float(d.get("active_seconds") or 0.0),
            peer_name=normalize_text(d.get("peer_name")),
            socket=normalize_text(d.get("socket")),
            pid=parse_pid(d.get("pid")),
            peer_status=normalize_text(d.get("peer_status")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

@dataclass
class RegistryFile:
    version: int = 1
    sessions: list[Session] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "sessions": [s.to_dict() for s in self.sessions]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RegistryFile:
        return cls(
            version=int(d.get("version", 1)),
            sessions=[Session.from_dict(s) for s in d.get("sessions", [])],
        )

def _parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)

def is_stale(session: Session, *, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    ping = _parse_iso(session.last_ping)
    if ping.tzinfo is None:
        ping = ping.replace(tzinfo=timezone.utc)
    return (now - ping).total_seconds() > STALE_SECONDS


def accumulate_active_seconds(
    prev_last_ping: str, now_ts: str, active_seconds: float, *, gap_limit: int
) -> float:
    """Add the gap since the previous ping to the running active total.

    A gap within ``gap_limit`` is a continuation and counts. A larger gap is a
    resume (the session went idle), so it starts a new active segment and adds
    nothing. Non-positive gaps (clock skew / identical timestamps) add nothing.
    """
    prev = _parse_iso(prev_last_ping)
    now = _parse_iso(now_ts)
    if prev.tzinfo is None:
        prev = prev.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    gap = (now - prev).total_seconds()
    if 0 < gap <= gap_limit:
        return active_seconds + gap
    return active_seconds

def public_view(session: Session) -> dict[str, Any]:
    d = session.to_dict()
    d.pop("registry_id", None)
    return d
