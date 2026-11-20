#!/usr/bin/env bash
# Prints args and exits with code from FAKE_EXIT (default 0).
echo "fake:$*"
exit "${FAKE_EXIT:-0}"