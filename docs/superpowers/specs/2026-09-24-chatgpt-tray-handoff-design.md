# ChatGPT Tray Handoff — Design Spec

**Date:** 2026-09-24  
**Status:** Implemented — skill `phone-trays` (modes: handoff, pickup, from-chatgpt, publish)  
**Repo:** `tjdsneto-setup` at the time; the skills moved to agent-tools `skills/chatgpt-handoff` and `skills/chatgpt-pickup` on 2026-11-26. Trays live in the Tray remote backend.  
**Related:** Tray CLI local/remote model; the `handoff` plugin's `/handoff` (Claude→Claude only); Spec `2026-09-24-publish-for-phone-design.md` and Plan `docs/superpowers/plans/2026-09-24-phone-trays.md` (both in tjdsneto-setup)

## 1. Summary

Hand work between Claude/Cursor (and other agents) and **ChatGPT Remote on phone**
using two **owned remote trays** as directional lanes. Continuity is tray items, not
ChatGPT conversation IDs — there is no official API to spawn a ChatGPT-app chat that
syncs to classic voice history.

Packet is **tray-native**: the full structured text lives in the item **title** (Tray
has no separate body/notes field today — same pattern as existing long WIP items).
No side `HANDOFF.md` for this flow.

## 2. Goals

- Claude can hand off a self-contained ask to ChatGPT for phone steering (Remote).
- ChatGPT on the Mac (via Remote) can pick up, work/decide, and hand back.
- Direction is unambiguous: separate trays, not title prefixes on one inbox.
- Skills teach both sides the same packet format and tray commands.
- Survives Mac sleep / Remote disconnect: items remain on remote trays until completed.

## 3. Non-goals (v1)

- Seeding classic ChatGPT **voice** cloud chats via API/CLI (not available).
- Merging with the `handoff` plugin's `/handoff` (beads/`HANDOFF*.md`) — that remains Claude→Claude.
- Auto phone push beyond what ChatGPT Remote already provides.
- File payloads or gist links as the primary packet (see publish-for-phone for artifacts).
- Multi-user collaboration on these trays (owner-only self handoff).

## 4. Architecture

```
Claude / Cursor / agent
  → skill chatgpt-handoff
  → tray add "…" to-chatgpt --remote   (packet in title)
       │
       ▼
Phone: ChatGPT Remote (Mac awake, desktop app, tray on PATH)
  → skill/instructions chatgpt-pickup
  → tray list to-chatgpt --remote
  → work / decide (talk, shell, etc.)
  → tray add "…" from-chatgpt --remote
  → tray complete <to-chatgpt-id>
       │
       ▼
Claude / next agent
  → pickup from-chatgpt --remote
  → continue work
  → tray complete <from-chatgpt-id>
```

| Piece | Role |
|-------|------|
| Remote tray `to-chatgpt` | Outbound: agents → ChatGPT |
| Remote tray `from-chatgpt` | Inbound: ChatGPT → agents |
| Skill `chatgpt-handoff` | Claude/Cursor: write outbound packet; refuse wrong-direction writes |
| Instructions `chatgpt-pickup` | ChatGPT/Codex on Mac: list, pick FIFO, hand back, complete |
| Packet template | Fixed sections embedded in item title (plain text) |

**Prerequisite:** `tray login` on the Mac that runs ChatGPT Remote. Phone does not run
`tray`; it steers the host that does.

## 5. Trays

Create once (owner):

```bash
tray create to-chatgpt
tray create from-chatgpt
```

| Tray | Writer | Reader | On pickup |
|------|--------|--------|-----------|
| `to-chatgpt` | Claude/agents | ChatGPT Remote | Complete after hand-back written |
| `from-chatgpt` | ChatGPT | Claude/agents | Complete after agent resumes |

List / add always use `--remote`. Local trays are out of scope for this skill.

## 6. Packet format

Tray v1 stores a single **title** string per item (no body field). Put a short
headline first, then the sections — one string passed to `tray add "…"`.

Example shape:

```
Decide: Q3 rock wording | Goal: … | Context: … | Done: … | Open: … | Ask: … | Return: … | Paths: …
```

Or multiline if the shell/quoting allows (prefer `|`-separated single line for
reliable `tray add` quoting).

**Section headers** (exact labels, omit if empty — do not invent placeholders):

- `Goal:` — what success looks like
- `Context:` — minimal background
- `Done:` — already finished
- `Open:` — unresolved facts / blockers
- `Ask:` — what ChatGPT should do or decide
- `Return:` — what to put on `from-chatgpt`
- `Paths:` — optional host paths for Mac-side work (not phone-openable)

Soft size: keep under ~8–12 KB; if truncated, end with `…[truncated]` and note what
was dropped. **Future:** if Tray gains a notes/body field, move sections there and
keep the headline as title only — skills should isolate the packet serializer so
that swap is one change.

**Direction rules**

- Outbound handoff → only `to-chatgpt`.
- Hand-back → only `from-chatgpt`, with **Return** (and updated Done/Open) filled in the title packet.
- Claude must not write handoff-out to `from-chatgpt`.
- ChatGPT must not write pickup asks to `from-chatgpt` (use `to-chatgpt` only as consumer).

## 7. Skills

### 7.1 `chatgpt-handoff` (Claude / Cursor)

**Triggers:** “hand off to ChatGPT”, “continue on phone”, “ChatGPT Remote”, `/chatgpt-handoff`.

**Steps**

1. Confirm `tray status` (signed in); else stop with `tray login`.
2. Fill packet from current session; ask user only if Goal/Ask are unclear.
3. `tray add "<headline> | Goal: … | …" to-chatgpt --remote` (full packet in title).
4. Tell user: open ChatGPT Remote → ask host to run pickup on `to-chatgpt`.
5. Print item id from command output when available.

### 7.2 `chatgpt-pickup` (ChatGPT / Codex on Mac)

**Delivery:** skill file and/or `~/.codex/AGENTS.md` / ChatGPT project instructions so
Remote sessions know the protocol without Claude being present.

**Steps**

1. `tray list to-chatgpt --remote` (JSON if scripting).
2. Take oldest open item (FIFO / list order).
3. Do **Ask**; keep Mac paths for local tools if needed.
4. `tray add "<headline> | … | Return: …" from-chatgpt --remote` with Return filled.
5. `tray complete <id>` on the consumed `to-chatgpt` item.
6. Summarize for the user on phone.

### 7.3 Agent pickup of `from-chatgpt`

Same skill or a thin mode: list `from-chatgpt --remote`, resume from Return, complete
item when incorporated. Do not confuse with the `handoff` plugin's `/handoff`.

## 8. Error handling

| Condition | Behavior |
|-----------|----------|
| Not signed in | Stop; instruct `tray login` |
| Tray missing | Instruct `tray create <name>`; do not invent local fallback for v1 |
| Mac asleep / Remote down | Item stays queued; no data loss |
| Multiple open items | FIFO; announce which id is targeted |
| Oversized title/packet | Truncate with `…[truncated]`; no side file in v1 |
| Wrong-direction write | Refuse |

## 9. Testing

- Create trays; add a sample packet to `to-chatgpt`; list from a second shell.
- Complete round-trip manually with ChatGPT Remote once pairing works.
- Skill dry-run: refuse `from-chatgpt` as outbound from Claude.
- Confirm unsigned-in path fails clearly.

## 10. Implementation notes (for plan)

- Skills live under `ai/skills/shared/` (and Claude/Cursor install symlinks via
  `install.sh` / existing skill install).
- Document tray create + login in skill “first run”.
- Prefer `tray … --format json` for scripting.
- Optional later: hook on `item.pending` for `to-chatgpt` → macOS notification (Tray
  hooks already exist); not required for v1.

## 11. Open questions (resolved in brainstorm)

| Question | Decision |
|----------|----------|
| Local vs remote trays | Remote |
| One tray vs lanes | Two trays: `to-chatgpt`, `from-chatgpt` |
| Packet storage | Tray-native title string (no body field in Tray today) |
| Phone path | ChatGPT Remote on Mac + tray CLI |
| Classic ChatGPT voice API seed | Out of scope — not available |
