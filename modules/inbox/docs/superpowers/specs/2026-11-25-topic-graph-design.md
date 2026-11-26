# Topic graph view: design

Drafted 2026-11-25; no longer a draft, because it was built as written on Tiago's "keep going", with the outline-tree shape. This is spec 3 of 3. The decisions below were made on his behalf and are marked **[decided for you]**; he can still overturn any of them. It builds on spec 1 (the topic log, `modules/registry/docs/superpowers/specs/2026-11-25-topic-awareness-design.md`) and spec 2 (inbox activity written into the log, `2026-11-25-topic-aware-inbox-design.md`).

## Goal

One place to see every discussion the sessions are having. A discussion is an intent and the topics under it. Each topic shows the sessions forked from it, the questions asked and answered there, and what is still open. Tiago comes back after hours of context switching, opens one page, and sees what is in flight, what was decided, and what is waiting on him. He doesn't have to reconstruct it from chat windows.

## Decisions

| Question | Decision |
|---|---|
| Where it lives | **[decided for you]** A **Topics** tab in the inbox web app, next to the feed and History. Tiago already opens the inbox on his phone and desktop over Tailscale. The registry board is localhost-only, so it isn't the place. |
| Shape | **[decided for you]** A collapsible **outline tree**, not a free-form node-and-edge drawing. A node graph is hard to read at phone width, and the topic structure is a tree: forks only ever branch off. A drawn graph can come later, desktop-only, from the same data. |
| Data | **[decided for you]** The page reads the registry live on each request, through one new command: `agt registry topics --tree --events`. This is the one place the inbox reads the registry to render a page. Spec 2's no-live-read rule covered the feed, and this page is about topics themselves. |
| Actions | **[decided for you]** Read-only, apart from links. An inbox event links to its entry page, where Tiago can answer. A session shows its live or ended state and a copyable resume command. Closing or renaming topics from the page is out of scope. |

## 1. What the page shows

Each **intent** is a row with:
- its title and project;
- its owning session's engine and state (live, idle, ended), from the registry's live and stale rows;
- its age;
- a count of what's open under it, for example "2 open topics · 1 question waiting".

Its children are:
- **topics**, in the order they were opened, each with its status chip (open, done, parked, forked);
- **forks**, nested as their own intents, visually tied to the topic they forked from.

Expanding a topic shows its **timeline**: the events in order (opened, asked, answered, closed, forked, parked, done). Each event shows a short label and its time. Asked and answered events link to the inbox entry and show the question's title and the answer's value.

**Ordering.**
- Intents with something waiting on Tiago come first: an open inbox question under them, or a fork that never adopted.
- Then intents with open topics.
- Then everything else, newest first.
- Intents whose topics are all done collapse by default. A "Show finished" toggle reveals them, remembered in a cookie like Group-by.

**Phone first.**
- Rows and chips follow the inbox's existing 44 px touch targets and type scale.
- The tree indents at most 3 levels visually. Deeper levels keep the 3rd level's indent and show their depth as a number in a "↳ 4" marker.

## 2. Registry addition

`agt registry topics --tree --events` returns the tree spec 1 already builds. Each node also carries `events`: its log events, oldest first, with the note events from spec 2. Each node's `sessions` entries also carry `live`, a boolean taken from the registry's active rows.

It runs in-process like the other topic commands. To keep the page fast, it caches parsed logs by file modification time. See the CPU issue (tjdsneto/agent-tools#9), which this must not make worse.

## 3. Out of scope

- A drawn node-and-edge graph.
- Editing topics from the page.
- Search.
- Showing sessions that never set an intent. They have no topic log, so they have nothing to show.

## 4. Testing

- **Registry:** a unit test for `--events` and `live`, and for the modification-time cache: a changed log is re-read, an unchanged one isn't.
- **Inbox:**
  - the page renders from a faked registry call;
  - the ordering rules;
  - collapsed finished intents;
  - deep-nesting markers;
  - escaping of every agent-written string.
- **Black-box:** a temp registry with an intent, two topics, a fork that's adopted, an ask that's answered, and a topic that's parked. The Topics page HTML holds each piece in the right nesting.
- **Visual:** screenshots at 390 px and at desktop width, light and dark, with a real-looking tree. Look at them before handing off.

## Risks

- **Load.** Reading all logs on each request costs more as logs grow. The cache in section 2 bounds that. The plan must measure the page with today's real logs.
- **Clutter.** Hundreds of finished intents could bury the live ones. Collapsing them by default and the "Show finished" toggle handle that. If it isn't enough, add a date cutoff later.

## Plan refinements (2026-11-25)

The plan (`modules/inbox/docs/superpowers/plans/2026-11-25-topic-graph.md`) built this spec as written and settled these open points. All of them can still be overturned.

- **Liveness** is read in the CLI process from `registry.json`, the file the daemon's `list` reads, with no daemon call and none per node. `archive.jsonl` is read only to find an ended session's directory. Each session entry carries `live`, `state` (`live`, `idle`, `ended`, `unknown`) and `directory`. The project shown is the directory's last name, as for an asker.
- **The cache** is one file, `topics/.parsed.json`, keyed by each log's modification time and size, because each `agt registry` call is a new process. Only `topics --tree` uses it; the daemon's per-row reads are unchanged (tjdsneto/agent-tools#9).
- **Node events** come from every log, oldest first, each with the session it came from.
- **Waiting questions** use the inbox's own entry state, in one query per load. The log's notes are the fallback for entries the inbox no longer has.
- **Finished** means nothing waiting, no open or parked topic, and no live session under the intent. Finished intents aren't rendered until "Show finished"; then they come last and closed.
- **Newest first** means the most recent event anywhere under the intent. It also orders the first two groups.
- **Open by default:** unfinished intents, and topics with something waiting under them. Opening or closing a branch turns the live reload into the stale toast.
- **Resume commands** appear only for sessions that aren't live, with `cd <dir> &&` when the directory is known.
- **A topic's timeline** also lists each fork opened from it.
- **Measured:** on a copy of the 7 real logs of 2026-11-25, `topics --tree --events` took 0.10 s warm (median); with 1000 synthetic sessions, 0.22 to 0.24 s warm and 0.44 s cold; the page's warm median load was 0.130 s.
- **Known limit:** at 375px the fifth tab (Topics) ends about 4px inside the tab strip's fade and the strip scrolls by about 4px. Not fixed; Tiago hasn't decided whether to accept it.
