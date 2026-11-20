import pytest
from agent_read.text_source import TextSourceError, load_text


def test_text_flag():
    assert load_text(file=None, text=" hello ", stdin_data=None) == "hello"


def test_file(tmp_path):
    p = tmp_path / "n.md"
    p.write_text("from file\n")
    assert load_text(file=str(p), text=None, stdin_data=None) == "from file"


def test_stdin():
    assert load_text(file=None, text=None, stdin_data="piped") == "piped"


def test_empty_raises():
    with pytest.raises(TextSourceError):
        load_text(file=None, text="  ", stdin_data=None)


def test_dual_sources_raise(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("x")
    with pytest.raises(TextSourceError):
        load_text(file=str(p), text="y", stdin_data=None)


def test_no_source_raises():
    with pytest.raises(TextSourceError):
        load_text(file=None, text=None, stdin_data=None)


def test_file_and_stdin_raise(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("x")
    with pytest.raises(TextSourceError):
        load_text(file=str(p), text=None, stdin_data="also")
