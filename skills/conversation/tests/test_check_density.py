import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "check-density"
FIXTURES = HERE / "fixtures"

CARD_REPLY = """Body.

---
**Summary:** Done.

**Next for you:**
- F1. *A › B.* Pick one? Answer `yes` (y) or `no` (n). Recommended: `yes`. https://inbox/e/ib-abcd
"""


def run(text, *args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], input=text, capture_output=True, text=True)


def over(result):
    """The names of the measures over their limit."""
    return {line.split()[1].rstrip(":") for line in result.stdout.splitlines() if line.startswith("OVER")}


def fixture(name):
    return (FIXTURES / name).read_text()


# The two dense replies are real ones, from a session that had the rules and still wrote this way.
def test_status_report_reply_fails():
    r = run(fixture("dense-status.md"))
    assert r.returncode == 1
    assert {"body_items", "body_words", "ids", "id_mentions", "card_extra_lines"} <= over(r)


def test_what_i_did_reply_fails():
    r = run(fixture("dense-actions.md"))
    assert r.returncode == 1
    assert {"body_items", "body_code", "ids", "card_extra_lines"} <= over(r)


def test_the_same_reply_rewritten_passes():
    r = run(fixture("actions-rewritten.md"))
    assert r.returncode == 0, r.stdout


def test_a_card_repeated_from_the_last_reply_fails(tmp_path):
    previous = tmp_path / "previous.md"
    previous.write_text(fixture("dense-status.md"))
    r = run(fixture("dense-actions.md"), "--previous", str(previous))
    assert "repeated_cards" in over(r)


def test_a_new_card_is_not_a_repeat(tmp_path):
    previous = tmp_path / "previous.md"
    previous.write_text(fixture("dense-status.md"))
    assert "repeated_cards" not in over(run(fixture("actions-rewritten.md"), "--previous", str(previous)))


def test_a_second_paragraph_under_a_card_counts():
    text = CARD_REPLY + "\n  More about it.\n"
    assert "card_extra_lines" in over(run(text))


def test_answer_tokens_are_not_code():
    assert "ok   body_code: 0 " in run(CARD_REPLY).stdout


def test_ids_inside_links_are_not_counted_but_link_text_is():
    text = "See [the canon prompts](https://x/e/0182), https://x/commit/abc1234def and [0195](https://x/0196).\n"
    assert "ok   ids: 1 " in run(text + CARD_REPLY).stdout


def test_ids_before_punctuation_are_counted_and_versions_are_not():
    text = "Shipped 0178. Then 0194: the bug, (0195), and v0.4.0 or 1.0182.5.\n"
    assert "ok   ids: 3 " in run(text + CARD_REPLY).stdout
