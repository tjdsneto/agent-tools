from __future__ import annotations
from pathlib import Path


class TextSourceError(ValueError):
    pass


def load_text(
    *,
    file: str | None,
    text: str | None,
    stdin_data: str | None,
) -> str:
    sources = []
    if file is not None:
        sources.append("file")
    if text is not None:
        sources.append("text")
    if stdin_data is not None:
        sources.append("stdin")

    if len(sources) == 0:
        raise TextSourceError("provide exactly one of: --file, --text, or stdin")
    if len(sources) > 1:
        raise TextSourceError(f"multiple text sources: {', '.join(sources)}")

    if file is not None:
        raw = Path(file).expanduser().read_text(encoding="utf-8")
    elif text is not None:
        raw = text
    else:
        raw = stdin_data or ""

    out = raw.strip()
    if not out:
        raise TextSourceError("text is empty after trim")
    return out
