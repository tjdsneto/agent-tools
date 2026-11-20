from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from agent_registry import ops, session_state, store
from agent_registry.models import Session, normalize_text

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "gemma4:12b-mlx"
DEFAULT_TIMEOUT = 25.0
ARCHIVE_TIMEOUT = 8.0
PRUNE_PER_SESSION_TIMEOUT = 5.0
PRUNE_MAX_SUMMARIES = 3
MAX_SUMMARY_CHARS = 120
MAX_TRANSCRIPT_CHARS = 3000
MAX_FIRST_USER_CHARS = 300
MAX_PROMPT_CHARS = 6000

SYSTEM_PROMPT = (
    "One line: what this agent session is working on right now. "
    "Prefer concrete nouns (repo, PR, bug, file). No filler. "
    "Output ONLY that line — no quotes, no 'Summary:' prefix."
)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return max(1.0, float(raw))
    except ValueError:
        return default


def _provider_pref() -> str:
    return (os.environ.get("AGENT_REGISTRY_SUMMARY_PROVIDER") or "auto").strip().lower()


def _ollama_url() -> str:
    return (os.environ.get("AGENT_REGISTRY_SUMMARY_OLLAMA") or DEFAULT_OLLAMA_URL).rstrip("/")


def _ollama_model() -> str:
    return (
        os.environ.get("AGENT_REGISTRY_SUMMARY_MODEL")
        or os.environ.get("TRANSLATE_MODEL")
        or DEFAULT_OLLAMA_MODEL
    )


def _timeout(default: float | None = None) -> float:
    return _env_float("AGENT_REGISTRY_SUMMARY_TIMEOUT", default or DEFAULT_TIMEOUT)


def ollama_available(timeout: float = 2.0) -> bool:
    try:
        req = urllib.request.Request(_ollama_url() + "/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def provider_enabled() -> bool:
    pref = _provider_pref()
    if pref in ("off", "none", "0", "false"):
        return False
    if pref in ("ollama", "auto", ""):
        return ollama_available()
    # gemini/claude not wired in v1 — treat as off unless ollama forced later
    return False


def _clean_line(text: str) -> str:
    line = (text or "").strip()
    line = line.splitlines()[0].strip() if line else ""
    line = re.sub(r"^(summary|title)\s*:\s*", "", line, flags=re.I).strip()
    line = re.sub(r'^[\'"`]+|[\'"`]+$', "", line).strip()
    if len(line) > MAX_SUMMARY_CHARS:
        line = line[: MAX_SUMMARY_CHARS - 1].rstrip() + "…"
    return line


def call_ollama(prompt: str, *, timeout: float | None = None) -> tuple[str, str]:
    """Return (summary_line, provider_label). Raises on failure."""
    model = _ollama_model()
    url = _ollama_url() + "/api/chat"
    body = json.dumps(
        {
            "model": model,
            "stream": False,
            "think": False,
            "options": {"temperature": 0.2},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST", headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout or _timeout()) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    err = payload.get("error")
    if err:
        raise RuntimeError(str(err))
    content = ((payload.get("message") or {}).get("content")) or ""
    line = _clean_line(content)
    if not line:
        raise RuntimeError("empty model output")
    return line, f"ollama:{model}"


def read_transcript_excerpt(path: str | Path) -> tuple[str, str | None]:
    """Return (excerpt, first_user_message) from a Claude/Cursor-ish JSONL transcript."""
    p = Path(path)
    if not p.is_file():
        return "", None
    messages: list[str] = []
    first_user: str | None = None
    try:
        with p.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg_type = d.get("type")
                if msg_type not in ("user", "assistant"):
                    # Cursor-style role field
                    role = (d.get("role") or "").lower()
                    if role in ("user", "assistant"):
                        msg_type = role
                    else:
                        continue
                msg = d.get("message") if isinstance(d.get("message"), dict) else d
                content = msg.get("content", "") if isinstance(msg, dict) else ""
                text = _content_to_text(content)
                if not text:
                    continue
                if msg_type == "user" and first_user is None:
                    first_user = text[:MAX_FIRST_USER_CHARS]
                messages.append(f"[{msg_type.upper()}]: {text[:800]}")
    except OSError:
        return "", None
    if len(messages) < 2:
        return "", first_user
    blob = "\n".join(messages)
    if len(blob) > MAX_TRANSCRIPT_CHARS:
        blob = blob[-MAX_TRANSCRIPT_CHARS:]
    return blob, first_user


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return re.sub(r"<[^>]+>", "", content).strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                t = (block.get("text") or "").strip()
                if t:
                    parts.append(t)
        return " ".join(parts).strip()
    return ""


def build_prompt(sess: Session, *, transcript_path: str | None = None) -> str | None:
    parts: list[str] = []
    if sess.title:
        parts.append(f"title: {sess.title}")
    if sess.directory:
        parts.append(f"directory: {sess.directory}")
    if sess.branch:
        parts.append(f"branch: {sess.branch}")
    if sess.issue:
        parts.append(f"issue: {sess.issue}")
    pr = sess.pr or {}
    if pr.get("title"):
        parts.append(f"pr: {pr['title']}")
    if sess.agent_type:
        parts.append(f"agent: {sess.agent_type}")
    if sess.model:
        parts.append(f"model: {sess.model}")

    excerpt = ""
    first_user = None
    if transcript_path:
        excerpt, first_user = read_transcript_excerpt(transcript_path)
    if first_user:
        parts.append(f"first_user: {first_user}")
    if excerpt:
        parts.append("transcript:\n" + excerpt)

    # Need a title/issue/PR/branch/transcript — bare directory+agent is too weak.
    has_signal = bool(
        sess.title
        or sess.branch
        or sess.issue
        or (sess.pr or {}).get("title")
        or excerpt
        or first_user
    )
    if not has_signal:
        return None

    prompt = "Context:\n" + "\n".join(parts)
    if len(prompt) > MAX_PROMPT_CHARS:
        prompt = prompt[:MAX_PROMPT_CHARS]
    return prompt


def generate_summary(
    sess: Session,
    *,
    transcript_path: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Generate a summary line without writing. Does not check empty-only."""
    if not provider_enabled():
        return {"ok": False, "skipped": True, "reason": "provider_off"}
    prompt = build_prompt(sess, transcript_path=transcript_path)
    if not prompt:
        return {"ok": False, "skipped": True, "reason": "insufficient_context"}
    try:
        line, provider = call_ollama(prompt, timeout=timeout)
    except Exception as e:
        return {"ok": False, "skipped": True, "reason": f"provider_error:{e}"}
    return {"ok": True, "summary": line, "provider": provider}


def set_summary_if_empty(registry_id: str, summary: str, *, force: bool = False) -> dict[str, Any]:
    """Empty-only write (or force). Returns session dict + skipped flag."""
    line = normalize_text(summary)
    if not line:
        return {"ok": False, "skipped": True, "reason": "empty_summary"}

    def _do(reg):
        sess = None
        for s in reg.sessions:
            if s.registry_id == registry_id:
                sess = s
                break
        if not sess:
            raise ops.UnknownRegistryIdError(registry_id)
        if not force and (sess.summary or "").strip():
            return {"ok": True, "skipped": True, "reason": "summary_present", "session": sess.to_dict()}
        sess.summary = line
        from agent_registry.models import now_iso

        ts = now_iso()
        sess.updated_at = ts
        # do not bump last_ping — this is metadata fill, not a liveness ping
        return {"ok": True, "skipped": False, "session": sess.to_dict(), "summary": line}

    return store.transact(_do)


def fill_session_summary(
    sess: Session,
    *,
    transcript_path: str | None = None,
    force: bool = False,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Generate + empty-only write for a live session. Mutates via store."""
    if not force and (sess.summary or "").strip():
        return {"ok": True, "skipped": True, "reason": "summary_present"}
    gen = generate_summary(sess, transcript_path=transcript_path, timeout=timeout)
    if not gen.get("ok"):
        return gen
    applied = set_summary_if_empty(sess.registry_id, gen["summary"], force=force)
    applied["provider"] = gen.get("provider")
    return applied


def summarize_sidecar(
    agent_type: str,
    session_id: str,
    *,
    transcript_path: str | None = None,
    force: bool = False,
    timeout: float | None = None,
) -> dict[str, Any]:
    st = session_state.read_state(agent_type, session_id)
    if not st or not st.get("registry_id"):
        return {"ok": False, "skipped": True, "reason": "no_sidecar"}
    registry_id = st["registry_id"]
    sess = None
    for s in store.load().sessions:
        if s.registry_id == registry_id:
            sess = s
            break
    if not sess:
        return {"ok": False, "skipped": True, "reason": "no_registry_id"}
    return fill_session_summary(
        sess, transcript_path=transcript_path, force=force, timeout=timeout
    )


def prepare_for_archive(sess: Session, *, timeout: float | None = None) -> str | None:
    """If summary empty, return a suggested one-line summary (or None). Does not write."""
    if (sess.summary or "").strip():
        return None
    if not provider_enabled():
        return None
    gen = generate_summary(sess, timeout=timeout or ARCHIVE_TIMEOUT)
    if not gen.get("ok"):
        return None
    return gen.get("summary")
