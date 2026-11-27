from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from agent_inbox.constants import (
    CONTROL_TYPES,
    HTML_MAX_BYTES,
    MAX_OPTIONS,
    MIN_OPTIONS,
    PRIORITIES,
    TEXT_SIZES,
)
from agent_inbox.errors import ValidationError

SOURCE_KEYS = {"kind", "ref", "url"}
TOPIC_ID = re.compile(r"tp-[a-z0-9]+")


def _options(ctype: str, options: Any) -> list[dict]:
    if not isinstance(options, list) or not (MIN_OPTIONS <= len(options) <= MAX_OPTIONS):
        raise ValidationError(f"{ctype} needs {MIN_OPTIONS}-{MAX_OPTIONS} options")
    seen: set[str] = set()
    clean: list[dict] = []
    for opt in options:
        if not isinstance(opt, dict):
            raise ValidationError("each option needs an id and a label")
        oid = str(opt.get("id") or "").strip()
        label = str(opt.get("label") or "").strip()
        if not oid or not label:
            raise ValidationError("each option needs an id and a label")
        if oid in seen:
            raise ValidationError(f"duplicate option id {oid!r}")
        seen.add(oid)
        item: dict[str, Any] = {"id": oid, "label": label}
        if opt.get("description"):
            item["description"] = str(opt["description"])
        if opt.get("recommended"):
            item["recommended"] = True
        if opt.get("default"):
            item["default"] = True
        clean.append(item)
    return clean


def validate_control(control: Any) -> dict:
    if not isinstance(control, dict):
        raise ValidationError("control must be an object")
    ctype = control.get("type")
    if ctype not in CONTROL_TYPES:
        raise ValidationError(f"control.type must be one of {', '.join(CONTROL_TYPES)}")
    if ctype in ("choice", "multi"):
        options = _options(ctype, control.get("options"))
        if ctype == "choice" and sum(1 for o in options if o.get("default")) > 1:
            raise ValidationError("choice allows at most one default option")
        return {"type": ctype, "options": options}
    if ctype == "text":
        size = control.get("size", "short")
        if size not in TEXT_SIZES:
            raise ValidationError(f"text size must be one of {', '.join(TEXT_SIZES)}")
        return {"type": "text", "size": size}
    return {"type": "approve"}


def validate_answer(control: dict, value: Any, comment: str | None) -> Any:
    ctype = control["type"]
    ids = [o["id"] for o in control.get("options", [])]
    if ctype == "choice":
        if not isinstance(value, str) or value not in ids:
            raise ValidationError(f"value must be one of {', '.join(ids)}")
        return value
    if ctype == "multi":
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list) or not value or any(v not in ids for v in value):
            raise ValidationError(f"values must be among {', '.join(ids)}")
        return list(dict.fromkeys(value))
    if ctype == "text":
        if not isinstance(value, str) or not value.strip():
            raise ValidationError("text answer is empty")
        return value
    if value not in ("approve", "revise"):
        raise ValidationError("value must be approve or revise")
    if value == "revise" and not (comment or "").strip():
        raise ValidationError("revise needs a reason in --comment")
    return value


def _expires(raw: Any) -> datetime | None:
    if raw is None:
        return None
    try:
        when = datetime.fromisoformat(str(raw))
    except ValueError as e:
        raise ValidationError(f"expires_at is not an ISO timestamp: {raw!r}") from e
    if when.tzinfo is None:
        raise ValidationError("expires_at needs a timezone offset")
    return when


UPDATE_FIELDS = ("title", "summary", "detail", "html")


def validate_update(raw: Any) -> dict:
    """Fields to replace on an open question. Omitted fields stay as they are."""
    if not isinstance(raw, dict):
        raise ValidationError("request must be a JSON object")
    extra = set(raw) - set(UPDATE_FIELDS)
    if extra:
        raise ValidationError(f"update takes only {', '.join(UPDATE_FIELDS)}")
    if not any(key in raw for key in UPDATE_FIELDS):
        raise ValidationError("update needs title, summary, detail, or html")
    out: dict[str, str] = {}
    if "title" in raw:
        title = raw["title"]
        if not isinstance(title, str) or not title.strip() or "\n" in title:
            raise ValidationError("title must be one non-empty line")
        out["title"] = title.strip()
    for key in ("summary", "detail", "html"):
        if key not in raw:
            continue
        value = raw[key]
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"{key} must be text")
        if key == "html" and len(value.encode()) > HTML_MAX_BYTES:
            raise ValidationError("html exceeds 2 MB")
        out[key] = value
    return out


def validate_request(raw: Any, kind: str) -> dict:
    if not isinstance(raw, dict):
        raise ValidationError("request must be a JSON object")
    title = str(raw.get("title") or "").strip()
    if not title:
        raise ValidationError("title is required")
    if "\n" in title:
        raise ValidationError("title must be one line")
    priority = raw.get("priority") or ("normal" if kind == "ask" else "low")
    if priority not in PRIORITIES:
        raise ValidationError(f"priority must be one of {', '.join(PRIORITIES)}")
    html = raw.get("html")
    if html is not None:
        if not isinstance(html, str):
            raise ValidationError("html must be a string")
        if len(html.encode()) > HTML_MAX_BYTES:
            raise ValidationError("html exceeds 2 MB")
    source = raw.get("source")
    if source is not None and (not isinstance(source, dict) or not set(source) <= SOURCE_KEYS):
        raise ValidationError("source takes only kind, ref, url")
    topic = raw.get("topic")
    if topic is not None and not (isinstance(topic, str) and TOPIC_ID.fullmatch(topic)):
        raise ValidationError("topic must be a topic id like tp-7k3q")
    out = {
        "title": title,
        "summary": raw.get("summary"),
        "detail": raw.get("detail"),
        "html": html,
        "priority": priority,
        "source": source,
        "expires_at": _expires(raw.get("expires_at")),
        "topic": topic,
    }
    if kind == "ask":
        if "control" not in raw:
            raise ValidationError("ask needs a control")
        out["control"] = validate_control(raw["control"])
    elif "control" in raw:
        raise ValidationError("post takes no control")
    return out