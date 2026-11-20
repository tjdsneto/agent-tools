from agent_say.models import PingRequest


def test_minimal_title_ok():
    r = PingRequest.model_validate({"title": "Hi"})
    assert r.title == "Hi"
    assert r.speak is False
