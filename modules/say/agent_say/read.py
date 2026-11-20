from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from agent_say.speak import speak_kokoro_required


class ReadError(Exception):
    pass


def load_text(*, text: str | None, file: str | None, stdin: str) -> str:
    has_text = text is not None
    has_file = file is not None
    has_stdin = bool(stdin.strip())
    provided = []
    if has_text:
        provided.append("text")
    if has_file:
        provided.append("file")
    if has_stdin and not has_text and not has_file:
        provided.append("stdin")
    if len(provided) != 1:
        raise ReadError(
            "provide exactly one of: stdin, --text, or --file "
            f"(got: {provided or 'none'})"
        )
    if has_text:
        body = text or ""
    elif has_file:
        body = Path(file).read_text(encoding="utf-8")
    else:
        body = stdin
    body = body.strip()
    if not body:
        raise ReadError("empty text")
    return body


def make_read_result(
    status: str,
    *,
    title: str | None,
    chars: int,
    voice: str | None,
    elapsed_ms: int,
) -> dict:
    return {
        "status": status,
        "mode": "foreground",
        "title": title,
        "chars": chars,
        "voice": voice,
        "elapsed_ms": elapsed_ms,
    }


def main_read(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="agent-say read")
    p.add_argument("--text", default=None)
    p.add_argument("--file", default=None)
    p.add_argument("--title", default=None)
    p.add_argument("--voice", default=None)
    p.add_argument("--speed", type=float, default=1.0)
    args = p.parse_args(argv)

    t0 = time.monotonic()
    try:
        # If --text or --file set, ignore stdin for source selection
        stdin = "" if (args.text is not None or args.file is not None) else sys.stdin.read()
        body = load_text(text=args.text, file=args.file, stdin=stdin)
        voice = speak_kokoro_required(body, voice=args.voice, speed=args.speed)
        elapsed = int((time.monotonic() - t0) * 1000)
        print(
            json.dumps(
                make_read_result(
                    "ok",
                    title=args.title,
                    chars=len(body),
                    voice=voice,
                    elapsed_ms=elapsed,
                )
            )
        )
        return 0
    except (ReadError, OSError, ValueError, RuntimeError) as e:
        elapsed = int((time.monotonic() - t0) * 1000)
        print(
            json.dumps(
                make_read_result(
                    "error",
                    title=args.title,
                    chars=0,
                    voice=None,
                    elapsed_ms=elapsed,
                )
            )
        )
        print(f"agent-say read: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        elapsed = int((time.monotonic() - t0) * 1000)
        print(
            json.dumps(
                make_read_result(
                    "error",
                    title=args.title,
                    chars=0,
                    voice=None,
                    elapsed_ms=elapsed,
                )
            )
        )
        print(f"agent-say read: {e}", file=sys.stderr)
        return 1
