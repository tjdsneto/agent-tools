from __future__ import annotations

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_NOT_FOUND = 2
EXIT_IO = 3
EXIT_CONFLICT = 4
EXIT_TIMEOUT = 5

DEFAULT_DSN = "host=localhost port=5433 dbname=agent_inbox"
NOTIFY_CHANNEL = "agent_inbox"

KINDS = ("ask", "post")
ENGINES = ("claude", "codex", "cursor")
PRIORITIES = ("urgent", "normal", "low")
CONTROL_TYPES = ("choice", "multi", "text", "approve")
TEXT_SIZES = ("short", "long")
VIAS = ("web", "telegram", "cli")

# Question states in which a follow-up or reply still makes sense.
ASK_LIVE_STATES = ("open", "answered", "delivered")
CLOSED_STATES = ("expired", "withdrawn", "superseded", "archived")

MIN_OPTIONS = 2
MAX_OPTIONS = 6
HTML_MAX_BYTES = 2 * 1024 * 1024
WAIT_TIMEOUT_SEC = 30 * 60
WAIT_POLL_SEC = 5.0