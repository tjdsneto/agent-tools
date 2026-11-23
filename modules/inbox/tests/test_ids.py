from agent_inbox.ids import ALPHABET, ID_LEN, ID_PREFIX, new_id


def test_id_shape():
    eid = new_id()
    assert eid.startswith(ID_PREFIX)
    body = eid[len(ID_PREFIX):]
    assert len(body) == ID_LEN
    assert set(body) <= set(ALPHABET)


def test_alphabet_has_no_lookalikes():
    for ch in "01ilo":
        assert ch not in ALPHABET


def test_ids_vary():
    assert len({new_id() for _ in range(200)}) > 190
