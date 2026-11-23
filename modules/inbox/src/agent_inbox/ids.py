from __future__ import annotations

import secrets

# No 0/1/i/l/o: ids are read off a phone and typed into Telegram.
ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
ID_PREFIX = "ib-"
ID_LEN = 4


def new_id() -> str:
    return ID_PREFIX + "".join(secrets.choice(ALPHABET) for _ in range(ID_LEN))
