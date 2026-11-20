from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

_DEFAULT_KOKORO_HOME = Path.home() / ".local" / "share" / "kokoro-onnx"

_KOKORO_SCRIPT = """\
import os
import soundfile as sf
from kokoro_onnx import Kokoro

kokoro = Kokoro(os.environ["KOKORO_MODEL"], os.environ["KOKORO_VOICES"])
with open(os.environ["KOKORO_TEXT"], encoding="utf-8") as fh:
    text = fh.read().strip()
samples, sample_rate = kokoro.create(
    text,
    voice=os.environ["KOKORO_VOICE"],
    speed=float(os.environ.get("KOKORO_SPEED", "1.0")),
    lang="en-us",
)
sf.write(os.environ["KOKORO_OUT"], samples, sample_rate)
"""


class KokoroError(RuntimeError):
    pass


def _kokoro_home(home: Path | None = None) -> Path:
    if home is not None:
        return home
    return Path(os.environ.get("KOKORO_HOME", _DEFAULT_KOKORO_HOME)).expanduser()


def kokoro_ready(home: Path | None = None) -> bool:
    h = _kokoro_home(home)
    py = h / "venv" / "bin" / "python"
    model = h / "kokoro-v1.0.onnx"
    voices = h / "voices-v1.0.bin"
    return py.is_file() and os.access(py, os.X_OK) and model.is_file() and voices.is_file()


def synthesize(
    text: str,
    *,
    voice: str,
    speed: float,
    out_wav: Path,
    home: Path | None = None,
) -> None:
    if not text.strip():
        raise KokoroError("empty text")
    h = _kokoro_home(home)
    if not kokoro_ready(h):
        raise KokoroError(
            f"Kokoro not ready at {h}; need venv/bin/python, "
            "kokoro-v1.0.onnx, voices-v1.0.bin"
        )
    py = h / "venv" / "bin" / "python"
    model = h / "kokoro-v1.0.onnx"
    voices = h / "voices-v1.0.bin"
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".txt", delete=False
    ) as text_fh:
        text_fh.write(text)
        text_path = text_fh.name
    try:
        env = os.environ.copy()
        env.update(
            {
                "KOKORO_MODEL": str(model),
                "KOKORO_VOICES": str(voices),
                "KOKORO_VOICE": voice,
                "KOKORO_SPEED": str(speed),
                "KOKORO_TEXT": text_path,
                "KOKORO_OUT": str(out_wav),
            }
        )
        proc = subprocess.run(
            [str(py), "-c", _KOKORO_SCRIPT],
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if proc.returncode != 0:
            raise KokoroError(proc.stderr.strip() or f"kokoro exit {proc.returncode}")
        if not out_wav.is_file() or out_wav.stat().st_size == 0:
            raise KokoroError("kokoro produced no WAV")
    except KokoroError:
        raise
    except Exception as exc:
        raise KokoroError(str(exc)) from exc
    finally:
        try:
            os.unlink(text_path)
        except OSError:
            pass
