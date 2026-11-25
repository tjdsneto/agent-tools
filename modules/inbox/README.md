# agent-inbox

Persistent inbox for AI agents to ask Tiago questions or leave him information. Answers are delivered back to the session that asked, even after it has exited.

**Design spec:** [docs/superpowers/specs/2026-11-23-agent-inbox-design.md](docs/superpowers/specs/2026-11-23-agent-inbox-design.md)

## Install

Postgres 17 from Homebrew, running as a service on port 5433 (5432 is Docker `am-video-db`, not used):

    HOMEBREW_NO_AUTO_UPDATE=1 brew install postgresql@17
    sed -i '' 's/^#port = 5432/port = 5433/' /opt/homebrew/var/postgresql@17/postgresql.conf
    brew services start postgresql@17
    /opt/homebrew/opt/postgresql@17/bin/createdb -h localhost -p 5433 agent_inbox

Then from the repo root: `./install.sh` (creates `modules/inbox/.venv`, links `agent-inbox` / `agt inbox`). The schema is created on first connect.

Store location: `AGENT_INBOX_DSN` (default `host=localhost port=5433 dbname=agent_inbox`).

## Usage

Request JSON on stdin (or `--file`). stdout is one JSON object; diagnostics go to stderr.

Ask and return at once (resume mode):

    printf '%s' '{"title":"Which split?","control":{"type":"choice","options":[{"id":"a","label":"Tauri"},{"id":"b","label":"Go tray","recommended":true}]}}' \
      | agt inbox ask --engine claude --session-id "$SESSION_ID"

Ask and block (wait mode, default 30 min; on timeout the entry switches to resume):

    … | agt inbox ask --engine claude --session-id "$SESSION_ID" --wait

A follow-up returns `{"event":"followup","seq":N,…}`. Reply, then keep waiting:

    agt inbox reply ib-7k3q --text "C breaks the tray"
    agt inbox wait ib-7k3q --after N

Leave information (no question):

    printf '%s' '{"title":"Nightly run done","summary":"3 projects, 0 failures"}' | agt inbox post --script nightly

Answer and manage:

    agt inbox answer ib-7k3q --value b --comment "keep it thin" --via web
    agt inbox followup ib-7k3q --text "why not C?"
    agt inbox list            # table; --json for machines
    agt inbox get ib-7k3q     # full entry, thread and revisions

Controls: `choice` (2–6 options), `multi`, `text` (`size`: short|long), `approve` (approve, or revise with a required `--comment`).

## Exit codes

| Code | Meaning |
|---|---|
| 0 | ok (including a returned answer or follow-up) |
| 1 | usage or validation error |
| 2 | entry not found |
| 3 | store unreachable |
| 4 | conflict: already answered, or closed |
| 5 | wait timed out |

## Web

`agt inbox serve` also listens on `127.0.0.1:8797` (the feed) and `127.0.0.1:8798` (the HTML frame). On the tailnet those are `https://<machine>.ts.net:8444` and `:8445`. Port 443 is not used: it is the existing public Funnel. `8787` is the chrome bridge and `8788` is another local service.

A browser on this machine can open the localhost URL directly. A request that carries `Tailscale-User-Login` must start with `tjdsneto@`, otherwise it is 403. The LaunchAgent does not set `INBOX_ALLOW_INSECURE`. The frame is a different origin, sandboxed to scripts and popups, and labelled reference only. Links in it open in a new tab. It cannot submit an answer: a POST must come from the feed's own origin (`Origin` / `Sec-Fetch-Site`), and the `Host` must be localhost or the tailnet name.

## Delivery

`agt inbox serve` starts at login as `com.tjdsneto.agent-inbox`. While `waiter_pid` is a live process, that process's return is the delivery and the dispatcher does not wake the session. A dead waiter falls through to `agt registry wake`. Three failed wakes move the entry to `undelivered`. A held Claude session waits until `claude-budget` drops below 88 percent. An answer is refused while the session is held or unreachable.

Open questions show 🟢 live, 🔵 resumable, 🟡 held (with the reset time when known) or 🔴 unreachable, and the answer form is disabled for the last two. Serve re-checks each open question every 5 minutes, every minute while held, and writes only on a change. Urgent questions that leave held are announced in one push.

Telegram is for emergencies: only urgent entries push, at once, day or night, and only urgent questions get an "answered via" note when answered elsewhere. Normal and low entries wait in the inbox. Pushes go through `hermes send` to Hermes's home Telegram channel (`telegram`). Set `AGENT_INBOX_TELEGRAM_TO` to another Hermes target, or to an empty string to turn pushes off.

Choice and approve cards carry tap-to-answer buttons through the `inbox-buttons` Hermes plugin in `hermes-plugin/`. `./install.sh` links it into `~/.hermes/plugins`; turn it on once with `hermes plugins enable inbox-buttons`. Without it, cards fall back to numbered text replies.

## Topics

Each entry carries `topic_path`: the asking session's intent and topic from the agent registry, root intent first, as a list of `{id, title, kind}` (`kind` is `intent` or `topic`). It's a snapshot taken when the entry is created, so pages never call the registry, and a topic renamed later keeps its old name here. An ask or post with `--engine` and `--session-id` gets the session's path. Any asker, not only a `--script` one, may instead name a topic in its request, `"topic": "tp-xxxx"`, which wins over the session's path; that's how an asker files a question under a discussion. An unknown named topic is exit 1. A missing, failing or slow registry (2 s timeout) is not an error: the entry is created with `topic_path: null` and one warning line on stderr. The registry client never raises, whatever `agt` prints.

The link runs the other way too. After the entry commits, the inbox appends a note to the topic's log with `agt registry topic-note`, inline and with the same 2 s timeout: `asked` or `posted` when it's created, `answered` when it's answered (web, Telegram, CLI or chat), and `closed` when an ask is withdrawn, superseded or expires unanswered. Notes are best effort and never fail the inbox operation. `agt registry topic --done` then lists the questions still waiting as `open_questions`. Each ask or post makes two registry calls (path, then note), each bounded by the 2 s timeout; on this machine that cost about 0.18 s (median 0.38 s against 0.20 s with no registry).

The feed shows the last two names of each row's path above its title, with `…` in front when the path is longer; on a narrow row the middle name is cut first, never the topic. The filter menu adds an intent filter (the intents in the current view) and Group by: none (the plain feed), intent (one section per asking intent, with its project) or topic tree (one section per root, forked intents nested one level). Sections holding an open question come first, and rows without a path go last under "No topic". The `ib_group` cookie remembers the choice, and it applies to History too, where the sections replace the day headings. An entry's page shows its full path above the title and, at the bottom, up to 10 other entries on the same topic, newest first. Entries from before this shipped show no path.

`AGENT_INBOX_AGT` overrides the `agt` the inbox runs; the black-box tests point it at the checkout under test. Black-box checks: `.venv/bin/python -m pytest tests/blackbox -q`. The visual check (screenshots of the feed and entry page, phone and desktop, light and dark) lives in `tests/visual/`; its README says how to run it.

## Tests

    cd modules/inbox && .venv/bin/python -m pytest -q

Tests need a `agent_inbox_test` database (`createdb -h localhost -p 5433 agent_inbox_test`) and drop its tables on every test. Override with `AGENT_INBOX_TEST_DSN`.
