# Topic-aware inbox: design

Approved 2026-11-25 in brainstorming. This is spec 2 of 3. Spec 1, topic awareness, is shipped: `modules/registry/docs/superpowers/specs/2026-11-25-topic-awareness-design.md`. Spec 3, the topic graph view, builds on the events added here.

## Goal

Every inbox question and report carries the discussion it belongs to: the asking session's intent and topic, back to the root intent across forks. In the feed, Tiago can see which discussion an entry belongs to at a glance, and he can group the feed by discussion. The link also runs the other way. A topic's history records the questions asked under it and the answers given, so looking back at a topic shows what was decided, not only that it ended.

## Decisions taken

| Question | Decision |
|---|---|
| Feed presentation | A context line on every row, plus "Group by" options (none, intent, topic tree), remembered per viewer. |
| Direction | Two-way. Entries carry their topic path, and the topic log records `asked`, `posted` and `answered`. |
| Freshness | The path is a snapshot taken when the entry is created. The feed and entry pages never read the registry to render. The Topics tab (spec 3) is the one page that does. |
| Failure | A failed registry lookup or write never blocks an ask, a post or an answer. The entry or the history just lacks that link. |

## Out of scope

- The graph view (spec 3).
- Renaming or closing topics from the inbox.
- Backfilling entries created before this ships. They show as "No topic".

## 1. The topic path on each entry

**What's stored.** A new nullable column `entries.topic_path jsonb`. It holds a list of `{id, title, kind}` from the root intent down to the topic that was current when the entry was created. `kind` is `intent` for a topic that some session holds as its intent (the root, and each forked session's adopted topic), and `topic` otherwise. A session forked from another has its parent's path first. Example: `[{tp-wcrj, "Topic awareness"}, {tp-zkzb, "Manual check: Cursor fork"}, {tp-q3m8, "Check window targeting"}]`. A session with an intent but no current topic ends its path at its intent. A session with no intent gets `null`.

It's added with `ALTER TABLE entries ADD COLUMN IF NOT EXISTS topic_path jsonb` in `db.py`'s migration step, next to the existing `delivery` migration, plus an index on `(topic_path->-1->>'id')` for "same topic" lookups.

**How it's filled.**
- An `ask` or `post` with `--engine` and `--session-id` runs `agt registry topic-path --type <engine> --session-id <id>`. It prints the path as JSON, or `null`.
- A request may name a topic with `"topic": "tp-xxxx"`. The inbox then runs `agt registry topic-path --topic tp-xxxx`, which builds the path up from that topic. A named topic wins over the session's own path; it is how a `--script` asker joins a discussion, and any asker may use it.
- An unknown topic id is a validation error (exit 1), because the asker named it on purpose.
- A registry that's missing, too slow (2 s timeout) or failing is not an error. The entry is created with `topic_path = null`, and a one-line warning goes to stderr.

## 2. Topic history records inbox activity

**New registry event kinds,** appended to a topic log with `agt registry topic-note`:

| `event` | Extra fields |
|---|---|
| `asked` | `entry` (ib-id), `title` (the question) |
| `posted` | `entry`, `title` |
| `answered` | `entry`, `value` (short, capped at 200 chars), `via` (web, telegram, chat or cli) |

All three carry `topic` (`{id, title}`) like every other event. They never change a topic's status. `_replay` and `tree` ignore them for status and record them for history.

**Which log.** The note goes into the log of the session that asked, when the inbox knows it and that session's state contains the topic. Otherwise, for script askers and adopted topics, it goes into the log of the session that owns the topic (`find_topic`).

**When.**
- `ask` and `post` write `asked` or `posted` after the entry commits.
- `answer` (`store.answer`, which the web, Telegram and chat paths all go through) writes `answered` after the answer commits.

All three are best effort. A failure is logged to stderr and the inbox operation still succeeds. They run inline, after the commit, with the same 2 s timeout; nothing needs a retry queue.

**Open questions at done.**
- `agt registry topic --done` still succeeds when the topic has `asked` events with no matching `answered`. It adds `"open_questions": ["ib-…"]` to its JSON output.
- The topic-awareness skill tells the agent: if `open_questions` isn't empty, withdraw each question that's no longer needed (`agt inbox withdraw`), or say in chat that it's still waiting.
- Withdrawn, expired and superseded asks are not "open". So the inbox also writes a `closed` note (`entry`, `state`: `withdrawn`, `expired` or `superseded`) when an ask leaves `open` without an answer. Then the registry can tell an ask that's still waiting from one that's gone.

## 3. The feed

- **Context line.** Each row shows the last two elements of the path, small and muted, above the title: `Intent › Topic`, or just `Intent`. If the path is longer than two, the line starts with `…`. Rows without a path show no line. The full path goes in a `title` attribute. Text is escaped like every other agent-written string.
- **Group by.** The filter menu gets "Group by: none | intent | topic tree". The choice is remembered in a cookie, so it works without JS, survives the page's server-sent-event reloads, and works on the phone. None is today's feed, unchanged.
  - **Intent:** one section per intent (the last path element whose `kind` is `intent`, which is the asking session's own intent), titled with the intent and its project. Rows inside keep the current order.
  - **Topic tree:** sections by root (`path[0]`), with forked intents nested under it as sub-sections. Nesting is one level: a fork of a fork is also a sub-section of the root. Group by applies in History too, where its sections replace the day headings.
  - Sections follow the feed's existing priority: a section holding an open question comes before one holding only reports.
  - Entries without a path go into a last "No topic" section.
- **Filter.** An intent filter lists the intents present in the current view, next to the existing filters.
- The question still comes first. Grouped headers are one line each, and the row layout doesn't change.

## 4. The entry page

- The full path shows as a breadcrumb above the title.
- At the end of the page, after the follow-up form, "On this topic" lists the other entries whose path ends in the same topic (title, state, age), newest first, up to 10. Each one links to its page.

## 5. Registry additions

These extend `modules/registry`. They follow spec 1's rules: they run in-process, never through the daemon, and print JSON.

```
agt registry topic-path --type T --session-id S     # the session's path, or null
agt registry topic-path --topic tp-xxxx             # path from that topic up to its root
agt registry topic-note asked|posted --topic tp-x --entry ib-y --title "…" [--type T --session-id S]
agt registry topic-note answered --topic tp-x --entry ib-y --value "…" --via web [--type T --session-id S]
agt registry topic-note closed --topic tp-x --entry ib-y --state withdrawn [--type T --session-id S]
```

- `topic-path` walks parent links through `find_topic`, across logs. A cycle or a missing parent ends the walk, so it never fails.
- `topic --done` gains `open_questions` as described in section 2.

## 6. Testing

- **Inbox unit tests:**
  - the registry calls go through one small function that tests fake;
  - the path is stored;
  - a script `topic` is resolved, and an unknown one rejected;
  - a registry failure still creates the entry;
  - notes are sent after commit, for ask, post, answer and close;
  - the grouping logic for the three modes;
  - escaping in the context line.
- **Registry unit tests:**
  - `topic-path` across a fork, a missing parent and a cycle;
  - `topic-note` for each kind;
  - replay ignores notes for status;
  - `open_questions` on done, including after a `closed` note.
- **Black-box suite** (`modules/inbox/tests/blackbox/`, the same rules as spec 1: public surfaces only). It runs a temp registry plus the `agent_inbox_test` database:
  - real `agt registry intent` and `topic`, then a real `agt inbox ask` from that session: the entry shows the path in `agt inbox get`, and the topic log has `asked`;
  - `agt inbox answer --via chat`: the log has `answered`;
  - `agt registry topic --done` reports no open questions afterwards, and does report one when the ask is still open;
  - a script ask with `"topic"`: the path is resolved;
  - the registry binary unavailable: the ask still succeeds.
- **Visual check:** screenshots of the feed in each Group-by mode, and of the entry page, on a phone-width viewport (390 px) and a desktop viewport. Look at them before handing off.

## Risks

- **Stale titles.** A snapshot keeps the old name if a topic is renamed later. Nothing in spec 1 renames topics today, so this is accepted.
- **Silent gaps.** A best-effort note that fails leaves the history without that event. The feed is unaffected. Spec 3 must tolerate an `answered` with no `asked`, and the reverse.
- **Latency.** Each `agt inbox ask` and `post` makes two registry calls (path, then note), each bounded by the 2 s timeout. Measured on this machine: median 0.38 s with the registry against 0.20 s without, about 0.18 s more.
