from agent_read.result import make_result, exit_code


def test_make_result_shape():
    r = make_result(
        "ok",
        mode="foreground",
        title="Hi",
        chars=2,
        voice="am_michael",
        elapsed_ms=10,
    )
    assert r == {
        "status": "ok",
        "mode": "foreground",
        "title": "Hi",
        "chars": 2,
        "voice": "am_michael",
        "elapsed_ms": 10,
    }


def test_exit_codes():
    assert exit_code("ok") == 0
    assert exit_code("stopped") == 130
    assert exit_code("error") == 1
