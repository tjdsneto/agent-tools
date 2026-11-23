from __future__ import annotations

from agent_inbox.constants import EXIT_CONFLICT, EXIT_IO, EXIT_NOT_FOUND, EXIT_USAGE


class InboxError(Exception):
    exit_code = EXIT_USAGE


class ValidationError(InboxError):
    exit_code = EXIT_USAGE


class NotFoundError(InboxError):
    exit_code = EXIT_NOT_FOUND


class ConflictError(InboxError):
    exit_code = EXIT_CONFLICT


class StoreError(InboxError):
    exit_code = EXIT_IO