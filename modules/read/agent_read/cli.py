from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from agent_read.job import stop_background
from agent_read.kokoro import KokoroError, kokoro_ready, synthesize
from agent_read.player import PlayerError, run_player
from agent_read.result import exit_code, make_result
from agent_read.text_source import TextSourceError, load_text

_DEFAULT_VOICE = "am_michael"


def _voice_default() -> str:
    return os.environ.get("AGENT_READ_VOICE", _DEFAULT_VOICE)


def _emit(result: dict) -> int:
    print(json.dumps(result))
    return exit_code(result["status"])


def _cmd_stop() -> int:
    t0 = time.monotonic()
    status = stop_background()
    elapsed = int((time.monotonic() - t0) * 1000)
    if status == "ok":
        print("agent-read: nothing playing", file=sys.stderr)
    return _emit(
        make_result(
            status,
            mode="background",
            title=None,
            chars=0,
            voice=_voice_default(),
            elapsed_ms=elapsed,
        )
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "stop":
        return _cmd_stop()

    p = argparse.ArgumentParser(prog="agent-read")
    p.add_argument("--file", default=None)
    p.add_argument("--text", default=None)
    p.add_argument("--title", default=None)
    p.add_argument("--voice", default=None)
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--background", action="store_true")
    args = p.parse_args(argv)

    voice = args.voice or _voice_default()
    mode = "background" if args.background else "foreground"
    t0 = time.monotonic()

    def err(msg: str) -> int:
        print(f"agent-read: {msg}", file=sys.stderr)
        return _emit(
            make_result(
                "error",
                mode=mode,
                title=args.title,
                chars=0,
                voice=voice,
                elapsed_ms=int((time.monotonic() - t0) * 1000),
            )
        )

    stdin_data = None
    if args.file is None and args.text is None:
        if not sys.stdin.isatty():
            try:
                stdin_data = sys.stdin.read()
            except OSError:
                stdin_data = None

    try:
        text = load_text(file=args.file, text=args.text, stdin_data=stdin_data)
    except (TextSourceError, OSError) as e:
        return err(str(e))

    if not kokoro_ready():
        return err(
            "Kokoro not ready; set KOKORO_HOME (need venv + onnx + voices)"
        )

    fd, name = tempfile.mkstemp(prefix="agent-read-", suffix=".wav")
    os.close(fd)
    wav_path = Path(name)
    keep_wav = False
    try:
        try:
            synthesize(text, voice=voice, speed=args.speed, out_wav=wav_path)
        except KokoroError as e:
            return err(str(e))

        try:
            status = run_player(
                wav_path, title=args.title, background=args.background
            )
        except PlayerError as e:
            return err(str(e))
        except KeyboardInterrupt:
            status = "stopped"

        if args.background and status == "ok":
            keep_wav = True

        elapsed = int((time.monotonic() - t0) * 1000)
        return _emit(
            make_result(
                status,
                mode=mode,
                title=args.title,
                chars=len(text),
                voice=voice,
                elapsed_ms=elapsed,
            )
        )
    except Exception as e:
        return err(str(e))
    finally:
        if not keep_wav:
            try:
                wav_path.unlink()
            except OSError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
