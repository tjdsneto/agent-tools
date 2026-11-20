from __future__ import annotations


_EXIT_CODES = {
    "ok": 0,
    "timeout": 2,
    "cancelled": 130,
    "error": 1,
}


def exit_code(status: str) -> int:
    return _EXIT_CODES.get(status, 1)


def make_result(
    status: str,
    choice: str | None,
    text: str | None,
    elapsed_ms: int,
) -> dict:
    return {
        "status": status,
        "choice": choice,
        "text": text,
        "elapsed_ms": elapsed_ms,
    }
