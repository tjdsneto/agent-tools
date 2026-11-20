from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import TypeVar

from agent_registry.models import RegistryFile

T = TypeVar("T")


class CorruptRegistryError(Exception):
    pass


def registry_path() -> Path:
    override = os.environ.get("AGENT_REGISTRY_PATH")
    if override:
        return Path(override)
    return Path.home() / ".local" / "share" / "agent-registry" / "registry.json"


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _lock_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".lock")


def _read_registry(path: Path) -> RegistryFile:
    if not path.exists():
        return RegistryFile()
    raw = path.read_text(encoding="utf-8")
    if raw.strip() == "":
        return RegistryFile()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise CorruptRegistryError(f"corrupt registry at {path}: {e}") from e
    if not isinstance(data, dict):
        raise CorruptRegistryError(f"corrupt registry at {path}: root must be object")
    try:
        return RegistryFile.from_dict(data)
    except (AttributeError, KeyError, TypeError, ValueError) as e:
        raise CorruptRegistryError(f"corrupt registry at {path}: {e}") from e


def _write_registry(path: Path, reg: RegistryFile) -> None:
    _ensure_parent(path)
    payload = json.dumps(reg.to_dict(), indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=".registry.", suffix=".tmp"
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


@contextmanager
def hold_lock():
    """Exclusive flock on the live registry lock file (serializes live + archive writes)."""
    path = registry_path()
    lock_path = _lock_path(path)
    _ensure_parent(lock_path)
    with open(lock_path, "a+", encoding="utf-8") as lock_f:
        fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)


def load() -> RegistryFile:
    return _read_registry(registry_path())


def save(reg: RegistryFile) -> None:
    with hold_lock():
        _write_registry(registry_path(), reg)


def transact(fn: Callable[[RegistryFile], T]) -> T:
    with hold_lock():
        reg = _read_registry(registry_path())
        result = fn(reg)
        _write_registry(registry_path(), reg)
        return result
