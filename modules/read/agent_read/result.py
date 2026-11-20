from __future__ import annotations


def make_result(
    status: str,
    *,
    mode: str,
    title: str | None,
    chars: int,
    voice: str,
    elapsed_ms: int,
) -> dict:
    return {
        "status": status,
        "mode": mode,
        "title": title,
        "chars": chars,
        "voice": voice,
        "elapsed_ms": elapsed_ms,
    }


def exit_code(status: str) -> int:
    if status == "ok":
        return 0
    if status == "stopped":
        return 130
    return 1
