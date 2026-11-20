from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

_DEFAULT_KOKORO_HOME = Path.home() / ".local" / "share" / "kokoro-onnx"
_DEFAULT_VOICE_EN = "am_michael"
_DEFAULT_VOICE_PT = "pf_dora"
_DEFAULT_SAY_VOICE_PT = "Luciana"

# Strong PT orthography (ã/õ) plus common accented/ASCII Portuguese cues.
_PT_RE = re.compile(
    r"[ãõÃÕ]"
    r"|ç[ãaãeéiíoóuú]"
    r"|ção\b|ções\b"
    r"|\b("
    r"não|nao|você|voce|vocês|voces|está|esta|estão|estao|"
    r"também|tambem|obrigado|obrigada|preciso|atenção|atencao|"
    r"olá|ola|por\s+favor|momento|aqui|agora|então|entao|"
    r"tudo\s+bem|bom\s+dia|boa\s+tarde|boa\s+noite"
    r")\b",
    re.IGNORECASE | re.UNICODE,
)

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
    lang=os.environ.get("KOKORO_LANG", "en-us"),
)
sf.write(os.environ["KOKORO_OUT"], samples, sample_rate)
"""


def _compose_text(title: str, body: str) -> str:
    if not title.strip() and not body.strip():
        return ""
    return f"{title}. {body}".strip()


def detect_lang(text: str) -> str:
    """Return Kokoro/espeak lang code: ``pt-br`` or ``en-us``.

    Override with ``AGENT_SAY_LANG`` (e.g. ``pt-br``, ``pt``, ``en-us``).
    """
    forced = (os.environ.get("AGENT_SAY_LANG") or "").strip().lower()
    if forced in ("pt-br", "pt", "pt_br"):
        return "pt-br"
    if forced in ("en-us", "en", "en_us", "en-gb"):
        return "en-us" if forced != "en-gb" else "en-gb"
    if forced:
        return forced
    return "pt-br" if _PT_RE.search(text) else "en-us"


def resolve_voice(lang: str) -> str:
    """Pick Kokoro voice for ``lang``, respecting env overrides."""
    if lang.startswith("pt"):
        return os.environ.get("AGENT_SAY_VOICE_PT", _DEFAULT_VOICE_PT)
    return os.environ.get("AGENT_SAY_VOICE", _DEFAULT_VOICE_EN)


def _kokoro_home() -> Path:
    return Path(os.environ.get("KOKORO_HOME", _DEFAULT_KOKORO_HOME)).expanduser()


def _kokoro_ready(home: Path) -> bool:
    py = home / "venv" / "bin" / "python"
    model = home / "kokoro-v1.0.onnx"
    voices = home / "voices-v1.0.bin"
    return py.is_file() and os.access(py, os.X_OK) and model.is_file() and voices.is_file()


def _speak_kokoro(
    text: str, voice: str, lang: str, home: Path, *, speed: float = 1.0
) -> None:
    py = home / "venv" / "bin" / "python"
    model = home / "kokoro-v1.0.onnx"
    voices = home / "voices-v1.0.bin"

    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".txt", delete=False
    ) as text_fh:
        text_fh.write(text)
        text_path = text_fh.name

    wav_path = tempfile.mktemp(suffix=".wav")
    try:
        env = os.environ.copy()
        env.update(
            {
                "KOKORO_MODEL": str(model),
                "KOKORO_VOICES": str(voices),
                "KOKORO_VOICE": voice,
                "KOKORO_LANG": lang,
                "KOKORO_SPEED": str(speed),
                "KOKORO_TEXT": text_path,
                "KOKORO_OUT": wav_path,
            }
        )
        subprocess.run(
            [str(py), "-c", _KOKORO_SCRIPT],
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        subprocess.run(["afplay", wav_path], check=True, timeout=120)
    finally:
        for path in (text_path, wav_path):
            try:
                os.unlink(path)
            except OSError:
                pass


def speak_kokoro_required(
    text: str, *, voice: str | None = None, speed: float = 1.0
) -> str:
    """Synthesize and play via Kokoro. Raises on failure. Returns voice id used."""
    text = text.strip()
    if not text:
        raise ValueError("empty text")
    lang = detect_lang(text)
    voice_id = voice or resolve_voice(lang)
    home = _kokoro_home()
    if not _kokoro_ready(home):
        raise RuntimeError(
            f"Kokoro not ready under {home} "
            "(need venv/bin/python, kokoro-v1.0.onnx, voices-v1.0.bin)"
        )
    _speak_kokoro(text, voice_id, lang, home, speed=speed)
    return voice_id


def _speak_say(text: str, lang: str) -> None:
    if lang.startswith("pt"):
        voice = os.environ.get("AGENT_SAY_SAY_VOICE_PT", _DEFAULT_SAY_VOICE_PT)
        subprocess.run(["say", "-v", voice, text], check=True, timeout=60)
    else:
        subprocess.run(["say", text], check=True, timeout=60)


def speak_best_effort(title: str, body: str) -> None:
    text = _compose_text(title, body)
    if not text:
        return

    lang = detect_lang(text)
    voice = resolve_voice(lang)
    home = _kokoro_home()

    try:
        if _kokoro_ready(home):
            _speak_kokoro(text, voice, lang, home)
            return
    except Exception as exc:
        print(
            f"agent-say speak: Kokoro failed ({exc}), falling back to say",
            file=sys.stderr,
        )

    try:
        _speak_say(text, lang)
    except Exception as exc:
        print(f"agent-say speak: {exc}", file=sys.stderr)
