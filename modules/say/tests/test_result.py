from agent_say.result import exit_code, make_result


def test_exit_codes():
    assert exit_code("ok") == 0
    assert exit_code("timeout") == 2
    assert exit_code("cancelled") == 130
    assert exit_code("error") == 1


def test_make_result_shape():
    r = make_result("ok", "done", None, 12)
    assert r == {"status": "ok", "choice": "done", "text": None, "elapsed_ms": 12}
