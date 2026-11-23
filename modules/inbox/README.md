# agent-inbox

Persistent inbox for AI agents to ask Tiago questions or leave him information. Answers are delivered back to the session that asked, even after it has exited (delivery lands in slice 2; this slice stores questions and answers and supports blocking waits).

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

## Tests

    cd modules/inbox && .venv/bin/python -m pytest -q

Tests need a `agent_inbox_test` database (`createdb -h localhost -p 5433 agent_inbox_test`) and drop its tables on every test. Override with `AGENT_INBOX_TEST_DSN`.
