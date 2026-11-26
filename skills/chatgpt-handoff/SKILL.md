---
name: chatgpt-handoff
description: >-
  Hand work to ChatGPT Remote via Tray and pick it back up in Claude/Cursor.
  Use for chatgpt-handoff, hand off to ChatGPT, continue on phone, ChatGPT
  Remote pickup, from-chatgpt, to-chatgpt, or resume after phone ChatGPT.
user-invocable: true
argument-hint: "[out|in|pickup] [args]"
---

# chatgpt-handoff — ChatGPT Remote via Tray

Directional remote trays only (always `--remote`):

| Direction | Tray | Who writes | Who reads |
|-----------|------|------------|-----------|
| **Out** | `to-chatgpt` | This skill (`out`) | ChatGPT on Mac (`pickup`) |
| **In** | `from-chatgpt` | ChatGPT (`pickup`) | This skill (`in`) |

For phone-readable **docs** (not ChatGPT work), use **`phone-trays`** / `publish` → `to-phone`.

Packets = item **title** (`|`-separated). See [references/packets.md](references/packets.md).

**Need:** `tray` on PATH, `tray login`, Mac awake + ChatGPT Remote paired.

## In / out flow

```
 OUT                                              IN
 Claude/Cursor ──tray add──► to-chatgpt           from-chatgpt ◄──tray add── ChatGPT
        │                         │                      ▲                      │
        │                         ▼                      │                      │
        │              Phone: ChatGPT Remote             │                      │
        │              “pick up to-chatgpt”              │                      │
        │                         │                      │                      │
        │                         ▼                      │                      │
        │                   do Ask / decide ─────────────┘                      │
        │                   complete to-chatgpt item                            │
        ▼                                                                       │
 Claude/Cursor ◄── list/complete from-chatgpt ──────────────────────────────────┘
```

## First run

```bash
bash "${CLAUDE_SKILL_DIR:-$HOME/.claude/skills/chatgpt-handoff}/scripts/ensure-trays.sh"
```

Not signed in → stop; user runs `tray login`.

## Modes

### `out` (default) — agent → ChatGPT

Triggers: chatgpt-handoff, hand off to ChatGPT, continue on phone.

1. `tray status --format json` — must be signed in.
2. Ensure trays if needed.
3. Build packet (`Goal` + `Ask` required).
4. **Only** `tray add "<packet>" to-chatgpt --remote` (never write out to `from-chatgpt`).
5. Tell user: ChatGPT Remote → pick up `to-chatgpt`.
6. Report item id when present.

### `pickup` — **ChatGPT only** (not Claude)

When **you are ChatGPT** (Desktop / Codex / Remote on Mac), follow skill
**`chatgpt-pickup`** — full protocol lives there. Short form:

1. You are **ChatGPT**. Inbox = **`to-chatgpt`**. Outbox = **`from-chatgpt`**.
2. `tray list to-chatgpt --remote` → oldest open → do **Ask**.
3. `tray add "… | Return: …" from-chatgpt --remote` (hand-back **only** here).
4. `tray complete <id>` on the **`to-chatgpt`** item — never write hand-back to `to-chatgpt`.

Claude/Cursor must **not** run `pickup` as themselves; they use `out` / `in`.

### `in` — agent resumes after ChatGPT

Triggers: from-chatgpt, resume after phone, pick up ChatGPT hand-back.

1. `tray list from-chatgpt --remote`.
2. Oldest open → apply **Return**.
3. `tray complete <id>` when incorporated.

Not the `handoff` plugin's `/handoff` (Claude→Claude handoff/`HANDOFF*.md`).

## Hard rules

- Always `--remote`.
- Refuse wrong-direction writes.
- No side `HANDOFF.md` — title is the packet headline.
- Soft cap ~12k chars on **title**; truncate title with `…[truncated]`. Put full artifacts in **`--body`** / **`--body-file`** (≤100k); read with `tray list --json`.

## Codex / ChatGPT Desktop

If this skill isn’t loaded, Codex reads the ChatGPT tray handoff section of `~/.codex/AGENTS.md`.
