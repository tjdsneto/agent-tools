from datetime import datetime

import pytest

from agent_inbox.errors import ValidationError
from agent_inbox.validate import validate_answer, validate_control, validate_request

CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B", "recommended": True}]}
MULTI = {"type": "multi", "options": [{"id": "x", "label": "X"}, {"id": "y", "label": "Y"}, {"id": "z", "label": "Z"}]}


def test_choice_control_is_normalised():
    out = validate_control(CHOICE)
    assert out == {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B", "recommended": True}]}


@pytest.mark.parametrize("n", [1, 7])
def test_option_count_bounds(n):
    opts = [{"id": str(i), "label": str(i)} for i in range(n)]
    with pytest.raises(ValidationError, match="2-6 options"):
        validate_control({"type": "choice", "options": opts})


def test_duplicate_option_ids_rejected():
    with pytest.raises(ValidationError, match="duplicate"):
        validate_control({"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "a", "label": "B"}]})


def test_choice_allows_one_default():
    opts = [{"id": "a", "label": "A", "default": True}, {"id": "b", "label": "B", "default": True}]
    with pytest.raises(ValidationError, match="at most one default"):
        validate_control({"type": "choice", "options": opts})


def test_text_and_approve_controls():
    assert validate_control({"type": "text"}) == {"type": "text", "size": "short"}
    assert validate_control({"type": "text", "size": "long"}) == {"type": "text", "size": "long"}
    assert validate_control({"type": "approve"}) == {"type": "approve"}
    with pytest.raises(ValidationError):
        validate_control({"type": "text", "size": "huge"})
    with pytest.raises(ValidationError, match="control.type"):
        validate_control({"type": "number"})


def test_answer_choice():
    ctl = validate_control(CHOICE)
    assert validate_answer(ctl, "b", None) == "b"
    with pytest.raises(ValidationError, match="one of a, b"):
        validate_answer(ctl, "c", None)
    with pytest.raises(ValidationError):
        validate_answer(ctl, ["a", "b"], None)


def test_answer_multi_accepts_single_and_dedupes():
    ctl = validate_control(MULTI)
    assert validate_answer(ctl, "x", None) == ["x"]
    assert validate_answer(ctl, ["z", "x", "z"], None) == ["z", "x"]
    with pytest.raises(ValidationError):
        validate_answer(ctl, [], None)
    with pytest.raises(ValidationError):
        validate_answer(ctl, ["x", "nope"], None)


def test_answer_text_and_approve():
    assert validate_answer({"type": "text", "size": "short"}, "hi", None) == "hi"
    with pytest.raises(ValidationError, match="empty"):
        validate_answer({"type": "text", "size": "short"}, "  ", None)
    assert validate_answer({"type": "approve"}, "approve", None) == "approve"
    with pytest.raises(ValidationError, match="reason"):
        validate_answer({"type": "approve"}, "revise", "")
    assert validate_answer({"type": "approve"}, "revise", "too wide") == "revise"


def test_request_ask_defaults_and_required():
    out = validate_request({"title": "Which split?", "control": CHOICE}, "ask")
    assert out["priority"] == "normal"
    assert out["control"]["type"] == "choice"
    with pytest.raises(ValidationError, match="needs a control"):
        validate_request({"title": "t"}, "ask")
    with pytest.raises(ValidationError, match="title"):
        validate_request({"control": CHOICE}, "ask")
    with pytest.raises(ValidationError, match="one line"):
        validate_request({"title": "a\nb", "control": CHOICE}, "ask")


def test_request_post_rules():
    out = validate_request({"title": "Nightly run done"}, "post")
    assert out["priority"] == "low"
    assert "control" not in out
    with pytest.raises(ValidationError, match="no control"):
        validate_request({"title": "t", "control": CHOICE}, "post")


def test_request_html_cap_source_and_expiry():
    with pytest.raises(ValidationError, match="2 MB"):
        validate_request({"title": "t", "html": "x" * (2 * 1024 * 1024 + 1)}, "post")
    with pytest.raises(ValidationError, match="source"):
        validate_request({"title": "t", "source": {"kind": "k", "extra": 1}}, "post")
    out = validate_request({"title": "t", "expires_at": "2026-12-01T09:00:00-03:00"}, "post")
    assert isinstance(out["expires_at"], datetime)
    with pytest.raises(ValidationError, match="timezone"):
        validate_request({"title": "t", "expires_at": "2026-12-01T09:00:00"}, "post")
    with pytest.raises(ValidationError, match="priority"):
        validate_request({"title": "t", "priority": "meh"}, "post")