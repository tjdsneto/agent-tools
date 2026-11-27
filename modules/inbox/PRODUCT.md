# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

One person: Tiago, a senior full-stack developer who runs many AI coding agents (Claude Code, Codex, Cursor) at once across his projects. The agents are the askers; he is the only answerer. He opens the inbox about equally on his phone and in a desktop browser on his Mac; agents also put each question's link in their chat.

## Product Purpose

The agent inbox is where agents put the questions they need a human to answer and the reports they want a human to read, so he does not have to sit inside each agent's session. Its main job is to let him answer one question fast: read what the agent needs, choose, approve or write the answer, optionally add a comment, and send it. The answer is then delivered back to the asking session, which wakes or resumes it. Success is an answer sent in seconds, with no doubt about what was asked or whether it reached the agent.

## Positioning

It is not a chat and not a task manager. Every entry is either an ask (a typed question with a fixed answer control) or a post (information to read), and it belongs to one agent session. The inbox knows whether that session can hear an answer right now (live, resumable, held because it is out of tokens, or unreachable) and delivers the answer itself.

## Operating Context

- Entries arrive from `agt inbox ask` and `agt inbox post`. Telegram is for emergencies: only urgent entries push a card (decided 2026-11-24). Urgent choice and approve cards can be answered with Telegram buttons; anything else opens the web page. Agents also ask each question in their own chat, and an answer given there is recorded with `--via chat`.
- Web pages: the feed (open questions first, then unread posts, then the rest; filters by kind, engine and state; a history view; batch withdraw and dismiss) and the entry page (title, state, summary and detail as Markdown, an optional sandboxed agent HTML frame, the answer form, More info and Simplify buttons that ask the session to fill the same entry in, a follow-up box, and the thread of follow-ups and replies), and the Topics page (every session's intent with its topics, forks, questions and sessions, as a read-only outline read live from the agent registry).
- Answer controls: choice (one of the asker's options, one may be recommended; the page adds Other, and a comment is required to send it), multi (several), text (short or long), approve (approve or revise with a reason).
- Entry states: open, answered, delivered, undelivered, expired, withdrawn, superseded for asks; unread, read, archived for posts.
- Reachability per open ask: live, resumable, held (with the time it becomes answerable), unreachable. A held or unreachable ask cannot be answered yet.
- The page reloads itself whenever any entry changes (server-sent events).
- Served from the Mac on 127.0.0.1 and over Tailscale HTTPS to his devices only.

## Capabilities and Constraints

- Server-rendered HTML from Python (`src/agent_inbox/web.py`) with inline CSS and a few lines of JS. Today it has no build step, loads nothing from the internet, and its forms work without JS. These are how it is built now, not commitments the user made.
- Agent-written Markdown renders with raw HTML escaped; agent HTML runs only in a sandboxed iframe on a separate origin. This security boundary must be kept.
- Form posts are same-origin only (CSRF protection); keep the forms posting to their current routes.
- Every control is at least 44px tall for touch.
- Undecided: dark mode, a desktop-specific layout.

## Brand Commitments

- Look: the category standard, a clean conventional inbox executed at full craft. The user chose it over distinctive worlds on 2026-11-24; do not smuggle in a themed world.
- Craft bar: Telegram, where the inbox's cards already land. The web pages should feel as quick, light and finished as Telegram's own screens.

## Evidence on Hand

Real entries in the local Postgres store (`agent_inbox` database). No logo, brand mark or brand assets exist. No other users, testimonials or metrics.

## Product Principles

1. The question comes first: what is asked and how to answer it are visible without scrolling on a phone.
2. Trust the delivery: the page always says whether the session can hear an answer and what happened to a sent one.
3. One person, many agents: which agent and project asked is always clear, without crowding the question.
4. Safe by construction: agent content can never act as the inbox.
