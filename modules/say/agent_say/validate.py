from __future__ import annotations
from agent_say.models import PingRequest

class SpecError(ValueError):
    pass

def validate_request(raw: dict) -> dict:
    try:
        req = PingRequest.model_validate(raw)
    except Exception as e:
        raise SpecError(str(e)) from e
    data = req.model_dump()
    if not data["options"] and not (data.get("input") and data["input"].get("enabled")):
        data["options"] = [{"id": "ok", "label": "OK"}]
    ids = [o["id"] for o in data["options"]]
    if len(ids) != len(set(ids)):
        raise SpecError("option ids must be unique")
    return data

def resolve_wait(flags: dict, *, options: list) -> dict:
    wait = bool(flags.get("wait"))
    timeout = flags.get("timeout")  # None = use default 180 unless wait
    default = flags.get("default")
    if wait and timeout is not None:
        raise SpecError("--wait and --timeout are mutually exclusive")
    if default is not None:
        ids = {o["id"] if isinstance(o, dict) else o.id for o in options}
        if default not in ids:
            raise SpecError(f"--default id not in options: {default}")
        if not options:
            raise SpecError("--default requires options")
    if wait:
        return {"mode": "wait", "timeout_sec": None, "default": default}
    sec = 180 if timeout is None else int(timeout)
    if sec < 1:
        raise SpecError("--timeout must be >= 1")
    return {"mode": "timeout", "timeout_sec": sec, "default": default}
