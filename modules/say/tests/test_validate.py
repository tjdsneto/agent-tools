import pytest
from agent_say.validate import SpecError, validate_request, resolve_wait


def test_requires_title():
    with pytest.raises(SpecError):
        validate_request({})


def test_implicit_ok_when_no_options_no_input():
    r = validate_request({"title": "Ping"})
    assert r["options"] == [{"id": "ok", "label": "OK"}]


def test_unique_option_ids():
    with pytest.raises(SpecError):
        validate_request({"title": "t", "options": [{"id": "a", "label": "A"}, {"id": "a", "label": "B"}]})


def test_default_requires_matching_option():
    with pytest.raises(SpecError):
        resolve_wait({"wait": False, "timeout": 10, "default": "nope"}, options=[{"id": "ok"}])


def test_wait_and_timeout_mutex():
    with pytest.raises(SpecError):
        resolve_wait({"wait": True, "timeout": 5, "default": None}, options=[])


def test_default_timeout_180():
    w = resolve_wait({"wait": False, "timeout": None, "default": None}, options=[])
    assert w == {"mode": "timeout", "timeout_sec": 180, "default": None}
