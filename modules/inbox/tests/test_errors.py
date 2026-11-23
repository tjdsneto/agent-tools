from agent_inbox.constants import EXIT_CONFLICT, EXIT_IO, EXIT_NOT_FOUND, EXIT_USAGE
from agent_inbox.errors import ConflictError, NotFoundError, StoreError, ValidationError


def test_each_error_carries_its_exit_code():
    assert ValidationError("x").exit_code == EXIT_USAGE
    assert NotFoundError("x").exit_code == EXIT_NOT_FOUND
    assert ConflictError("x").exit_code == EXIT_CONFLICT
    assert StoreError("x").exit_code == EXIT_IO
