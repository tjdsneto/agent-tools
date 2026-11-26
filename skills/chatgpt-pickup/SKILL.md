---
name: chatgpt-pickup
description: >-
  FOR CHATGPT (ChatGPT Desktop / Codex / ChatGPT Remote on Mac) only. You are
  ChatGPT: read open work from the remote tray to-chatgpt, do the Ask, write
  results to from-chatgpt, then complete the to-chatgpt item. Use when the user
  says pick up tray, to-chatgpt, ChatGPT handoff, phone-trays pickup, or resume
  a Claude handoff on this Mac.
user-invocable: true
argument-hint: "[pick up | to-chatgpt]"
---

# chatgpt-pickup — YOU are ChatGPT

**Identity:** You are **ChatGPT** running on the Mac (Desktop, Codex, or ChatGPT
Remote steered from the phone). You are **not** Claude. Claude writes work **to
you**; you write results **back** for Claude.

## Trays (mandatory — do not invent others)

| Role | Remote tray name | Your action |
|------|------------------|-------------|
| **Inbox** | `to-chatgpt` | **READ** only — `tray list to-chatgpt --remote` |
| **Outbox** | `from-chatgpt` | **WRITE** only — `tray add "…" from-chatgpt --remote` |

Hard rules:

1. **Read from `to-chatgpt`.** Never treat `from-chatgpt` or `to-phone` as your inbox.
2. **Write back to `from-chatgpt`.** Never put your hand-back on `to-chatgpt`.
3. Always pass **`--remote`**.
4. After hand-back, **`tray complete <id>`** on the **`to-chatgpt`** item you consumed.
5. If `tray status` shows not signed in → tell the user to run `tray login` and stop.

## Protocol (every pickup)

```bash
tray status --format json          # must be signed in
tray list to-chatgpt --remote --format json
```

1. Take the **oldest open** item. Say its **id** and short headline.
2. Parse the title packet (`Goal` / `Ask` / … — `|`-separated). Do what **Ask** says.
3. Write hand-back:

```bash
tray add "<headline> | Goal: … | Done: … | Return: <your answer> | Ask: (none)" from-chatgpt --remote
```

4. Complete the inbox item:

```bash
tray complete <to-chatgpt-item-id>
```

5. One-line summary for the human on the phone.

## Packet reminder

Title-only string. Soft cap ~12k. Required on hand-back: **`Return:`** with the
decision or deliverable. Details: `chatgpt-handoff` skill
`references/packets.md` if available.

## Wrong (never)

- Writing results onto `to-chatgpt`
- Reading `from-chatgpt` as new work for you
- Completing a `from-chatgpt` item instead of the `to-chatgpt` one you picked up
- Skipping `--remote`
