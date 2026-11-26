STALE_SECONDS = 3600
EVICT_SECONDS = 60  # how often the daemon archives hour-old rows; override via AGENT_REGISTRY_EVICT_SECONDS
HEARTBEAT_SECONDS = 60  # min seconds between registry writes; override via AGENT_REGISTRY_HEARTBEAT_SECONDS
ACTIVE_GAP_SECONDS = 300  # max gap still counted as active continuation; override via AGENT_REGISTRY_ACTIVE_GAP_SECONDS
STATUSES = frozenset({"idle", "working", "reviewing", "blocked"})
ARCHIVE_REASONS = frozenset({"unregister", "prune", "replace"})
DASHBOARD_DEFAULT_PORT = 8765
WAKE_ENV = "AGENT_REGISTRY_WAKE"  # set on sessions wake starts; their launch flags are not recorded
DAEMON_SERVICE = "agent-registry"
DAEMON_START_TIMEOUT = 5.0
EXIT_OK = 0
EXIT_USAGE = 1
EXIT_NOT_FOUND = 2
EXIT_IO = 3
EXIT_CONFLICT = 4
# Same alphabet as inbox ids (no 0/1/i/l/o): topic ids are read and typed by a person.
TOPIC_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
TOPIC_ID_PREFIX = "tp-"
TOPIC_ID_LEN = 4
# Where each engine puts the session's own id in its shell environment.
SESSION_ENV = {
    "claude": "CLAUDE_CODE_SESSION_ID",
    "codex": "CODEX_THREAD_ID",
    "cursor": "CURSOR_CONVERSATION_ID",
}
