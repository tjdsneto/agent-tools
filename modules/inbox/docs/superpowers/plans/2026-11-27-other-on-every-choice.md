# Other on every choice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A choice question on the web page offers one more radio, Other, and sending it with a comment closes the question, the comment being the reply.

**Architecture:** The rule lives in `validate_answer` and `validate_control`, which the store, the CLI, and the web form already share. The page adds the radio at render time and does not write it into the stored control. Telegram is not modified.

**Tech Stack:** Python 3, pytest, stdlib `http.server`. Spec: `modules/inbox/docs/superpowers/specs/2026-11-27-other-on-every-choice-design.md`.

Run every command from `modules/inbox` in the checkout you are implementing in. Tests: `.venv/bin/python -m pytest …`

---

## File map

- Modify `modules/inbox/src/agent_inbox/validate.py` — reject option id `other`; accept answer value `other` only with a comment, and only when that id is not already stored.
- Modify `modules/inbox/src/agent_inbox/web.py` — render the radio, the placeholder, and the receipt label.
- Modify `modules/inbox/tests/test_validate.py`, `tests/test_store_answer.py`, `tests/test_store_topics.py`, `tests/test_cli.py`, `tests/test_web.py` — the tests below.
- Modify `modules/inbox/PRODUCT.md`, `modules/inbox/DESIGN.md`, `modules/inbox/README.md`, `skills/agent-inbox/SKILL.md` — the sentences in Task 3.
- Do not modify `modules/inbox/src/agent_inbox/notify.py`. Telegram buttons stay the asker's options.

`store.answer` already strips the comment and calls `validate_answer`. No store change.

## Task 1: The answer rule

**Files:**
- Modify: `modules/inbox/src/agent_inbox/validate.py` (`_options` around line 34, `validate_answer` around line 69)
- Test: `modules/inbox/tests/test_validate.py`, `tests/test_store_answer.py`, `tests/test_store_topics.py`, `tests/test_cli.py`, `tests/test_web.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_validate.py`:

```python
def test_other_is_a_reserved_option_id():
    for ctype in ("choice", "multi"):
        opts = [{"id": "other", "label": "Else"}, {"id": "a", "label": "A"}]
        with pytest.raises(ValidationError, match="reserved"):
            validate_control({"type": ctype, "options": opts})


def test_an_id_that_only_differs_by_case_is_not_reserved():
    out = validate_control({"type": "choice", "options": [{"id": "Other", "label": "Else"}, {"id": "a", "label": "A"}]})
    assert [o["id"] for o in out["options"]] == ["Other", "a"]


def test_other_answer_needs_a_comment_and_a_stored_other_does_not():
    ctl = validate_control(CHOICE)
    assert validate_answer(ctl, "other", "because this") == "other"
    for blank in (None, "", "  "):
        with pytest.raises(ValidationError, match="other needs a comment"):
            validate_answer(ctl, "other", blank)
    stored = {"type": "choice", "options": [{"id": "other", "label": "Something else"}, {"id": "a", "label": "A"}]}
    assert validate_answer(stored, "other", None) == "other"
    assert validate_answer(ctl, "b", "a note") == "b"
```

Append to `tests/test_store_answer.py`:

```python
def test_other_answer_stores_the_stripped_comment_and_a_blank_one_stays_open(conn):
    e = make_ask(conn)
    out = store.answer(conn, e["id"], "other", comment="  because this  ", via="web")
    assert out["value"] == "other"
    got = store.get_entry(conn, e["id"])
    assert got["state"] == "answered"
    assert got["answer"]["value"] == "other"
    assert got["answer"]["comment"] == "because this"
    still = make_ask(conn)
    with pytest.raises(ValidationError, match="other needs a comment"):
        store.answer(conn, still["id"], "other", comment="  ", via="web")
    assert store.get_entry(conn, still["id"])["state"] == "open"
```

Append to `tests/test_store_topics.py`:

```python
def test_an_other_answer_notes_the_value_and_not_the_comment(conn, fake_registry):
    fake_registry.replies["topic-path"] = PATH
    q = ask(conn)
    store.answer(conn, q["id"], "other", comment="because this", via="web")
    note = fake_registry.notes()[-1]
    assert "--value=other" in note
    assert "because this" not in note
```

Append to `tests/test_cli.py`:

```python
def test_cli_other_answer_needs_a_comment(inbox_db, monkeypatch, capsys):
    stdin(monkeypatch, {"title": "Which split?", "control": CHOICE})
    assert main(["ask", *ASKER]) == EXIT_OK
    eid = out(capsys)["entry"]
    assert main(["answer", eid, "--value", "other"]) == EXIT_USAGE
    assert "other needs a comment" in capsys.readouterr().err
    assert main(["answer", eid, "--value", "other", "--comment", "because this"]) == EXIT_OK
    assert out(capsys)["value"] == "other"
    assert main(["get", eid]) == EXIT_OK
    assert out(capsys)["answer"]["comment"] == "because this"
```

Append to `tests/test_web.py`:

```python
def test_posting_other_with_a_comment_answers_and_a_blank_comment_does_not(conn, http):
    e = store.create_entry(conn, "ask", validate_request({"title": "Q", "control": CHOICE}, "ask"), engine="claude", session_id="s-1")
    status, _, page = _post(http, f"/e/{e['id']}/answer", "value=other&comment=%20%20")
    assert status == 400 and "other needs a comment" in page
    assert store.get_entry(conn, e["id"])["state"] == "open"
    status, location, _ = _post(http, f"/e/{e['id']}/answer", "value=other&comment=because+this")
    assert status == 303 and location == f"/e/{e['id']}"
    got = store.get_entry(conn, e["id"])
    assert got["state"] == "answered"
    assert got["answer"]["value"] == "other" and got["answer"]["comment"] == "because this"
    assert [o["id"] for o in got["control"]["options"]] == ["a", "b"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_validate.py::test_other_is_a_reserved_option_id tests/test_validate.py::test_other_answer_needs_a_comment_and_a_stored_other_does_not tests/test_store_answer.py::test_other_answer_stores_the_stripped_comment_and_a_blank_one_stays_open tests/test_store_topics.py::test_an_other_answer_notes_the_value_and_not_the_comment tests/test_cli.py::test_cli_other_answer_needs_a_comment tests/test_web.py::test_posting_other_with_a_comment_answers_and_a_blank_comment_does_not -q`

Expected: FAIL. `validate_answer` raises `value must be one of a, b` for value `other`. The reserved-id test fails because `validate_control` accepts that id.

- [ ] **Step 3: Implement the rule**

In `validate.py`, after the duplicate-id check inside `_options` (`if oid in seen: ...`), add:

```python
        if oid == "other":
            raise ValidationError("option id 'other' is reserved")
```

Replace the choice branch of `validate_answer` with:

```python
    if ctype == "choice":
        if value == "other" and "other" not in ids:
            if not (comment or "").strip():
                raise ValidationError("other needs a comment")
            return "other"
        if not isinstance(value, str) or value not in ids:
            raise ValidationError(f"value must be one of {', '.join(ids)}")
        return value
```

- [ ] **Step 4: Run the tests to verify they pass**

Run the same pytest command as Step 2.

Expected: PASS.

Then: `.venv/bin/python -m pytest tests/test_validate.py tests/test_store_answer.py tests/test_cli.py tests/test_notify.py -q`

Expected: PASS. `test_notify.py` stays green because buttons still come from the stored options.

- [ ] **Step 5: Commit**

```bash
git add modules/inbox/src/agent_inbox/validate.py modules/inbox/tests/test_validate.py modules/inbox/tests/test_store_answer.py modules/inbox/tests/test_store_topics.py modules/inbox/tests/test_cli.py modules/inbox/tests/test_web.py
git commit -m "$(cat <<'EOF'
feat(inbox): accept other as a choice answer when a comment is sent

A comment can close a choice question when none of the offered options fit. The id other is reserved so an asker cannot define that option.

EOF
)"
```

## Task 2: The radio, the placeholder, and the receipt

**Files:**
- Modify: `modules/inbox/src/agent_inbox/web.py` (`_control_fields` around line 891, `_shown` around line 932, the hint in `_entry_page` around line 1080)
- Test: `modules/inbox/tests/test_web.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web.py`:

```python
def test_a_choice_page_offers_other_and_a_stored_other_is_not_duplicated(conn, http):
    e = store.create_entry(conn, "ask", validate_request({"title": "Q", "control": CHOICE}, "ask"), engine="claude", session_id="s-1")
    _, body = _get(http, f"/e/{e['id']}")
    assert 'value="other"' in body
    assert "None of these. The comment is the reply." in body
    assert 'placeholder="Comment (required for Other)"' in body
    assert body.index('value="b"') < body.index('value="other"')
    assert body.index('value="other"') < body.index("</fieldset>")
    conn.execute(
        """UPDATE entries SET control = '{"type":"choice","options":[{"id":"other","label":"Something else"},{"id":"a","label":"A"}]}'::jsonb WHERE id = %s""",
        (e["id"],),
    )
    _, body = _get(http, f"/e/{e['id']}")
    assert body.count('value="other"') == 1
    assert "Something else" in body
    assert "None of these. The comment is the reply." not in body
    assert 'placeholder="Comment (optional)"' in body


def test_an_id_that_only_differs_by_case_still_gets_the_reserved_radio(conn, http):
    opts = [{"id": "Other", "label": "Else"}, {"id": "a", "label": "A"}]
    e = store.create_entry(
        conn, "ask", validate_request({"title": "Q", "control": {"type": "choice", "options": opts}}, "ask"),
        engine="claude", session_id="s-1",
    )
    _, body = _get(http, f"/e/{e['id']}")
    assert 'value="Other"' in body and 'value="other"' in body


def test_other_controls_do_not_gain_the_radio(conn, http):
    multi = {"type": "multi", "options": [{"id": "x", "label": "X"}, {"id": "y", "label": "Y"}]}
    text = {"type": "text", "size": "short"}
    approve = {"type": "approve"}
    for control in (multi, text, approve):
        e = store.create_entry(conn, "ask", validate_request({"title": "Q", "control": control}, "ask"), script="cron")
        _, body = _get(http, f"/e/{e['id']}")
        assert 'value="other"' not in body
        assert "Comment (required for Other)" not in body


def test_the_receipt_says_other_and_shows_the_comment(conn, http):
    e = store.create_entry(conn, "ask", validate_request({"title": "Q", "control": CHOICE}, "ask"), script="cron")
    store.answer(conn, e["id"], "other", comment="because this", via="web")
    _, body = _get(http, f"/e/{e['id']}")
    assert "<b>Other</b>" in body and "because this" in body
    stored = store.create_entry(conn, "ask", validate_request({"title": "Q2", "control": CHOICE}, "ask"), script="cron")
    conn.execute(
        """UPDATE entries SET control = '{"type":"choice","options":[{"id":"other","label":"Something else"},{"id":"a","label":"A"}]}'::jsonb WHERE id = %s""",
        (stored["id"],),
    )
    store.answer(conn, stored["id"], "other", via="web")
    _, body = _get(http, f"/e/{stored['id']}")
    assert "<b>Something else</b>" in body


def test_a_held_choice_disables_other_with_the_other_radios(conn, http):
    e = store.create_entry(conn, "ask", validate_request({"title": "Q", "control": CHOICE}, "ask"), engine="claude", session_id="s-1")
    conn.execute(
        """UPDATE entries SET delivery = delivery || '{"reachability": "held", "reachable_at": "2026-11-24T02:10:00"}' WHERE id = %s""",
        (e["id"],),
    )
    _, body = _get(http, f"/e/{e['id']}")
    assert "<fieldset disabled>" in body
    assert body.index('value="other"') < body.index("</fieldset>")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_web.py::test_a_choice_page_offers_other_and_a_stored_other_is_not_duplicated tests/test_web.py::test_an_id_that_only_differs_by_case_still_gets_the_reserved_radio tests/test_web.py::test_the_receipt_says_other_and_shows_the_comment tests/test_web.py::test_a_held_choice_disables_other_with_the_other_radios tests/test_web.py::test_other_controls_do_not_gain_the_radio -q`

Expected: the first four FAIL because the page has no `value="other"` radio and the receipt prints `other`. `test_other_controls_do_not_gain_the_radio` PASSes already. Keep it.

- [ ] **Step 3: Render the radio and the label**

At the end of the choice/multi loop in `_control_fields`, after the `for opt` loop and before `return "".join(fields)`, add:

```python
        if ctype == "choice" and not any(opt.get("id") == "other" for opt in control.get("options") or []):
            fields.append(
                '<label class="opt"><input type="radio" name="value" value="other">'
                "<span>Other<small>None of these. The comment is the reply.</small></span></label>"
            )
```

Replace `_shown` with:

```python
def _shown(entry: dict, value) -> str:
    labels = {opt["id"]: opt["label"] for opt in (entry.get("control") or {}).get("options") or []}
    if "other" not in labels:
        labels["other"] = "Other"
    values = value if isinstance(value, list) else [value]
    return ", ".join(labels.get(item, str(item)) for item in values)
```

Replace the hint line in `_entry_page`:

```python
        hint = "Comment (a reason is required to revise)" if control.get("type") == "approve" else "Comment (optional)"
```

with:

```python
        ids = [opt.get("id") for opt in control.get("options") or []]
        if control.get("type") == "approve":
            hint = "Comment (a reason is required to revise)"
        elif control.get("type") == "choice" and "other" not in ids:
            hint = "Comment (required for Other)"
        else:
            hint = "Comment (optional)"
```

The radio is inside the string `_control_fields` returns, and that string is already inside the `<fieldset>`. Do not move it outside.

- [ ] **Step 4: Run the tests to verify they pass**

Run the Step 2 command, then `.venv/bin/python -m pytest tests/test_web.py -q`.

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add modules/inbox/src/agent_inbox/web.py modules/inbox/tests/test_web.py
git commit -m "$(cat <<'EOF'
feat(inbox): offer Other on a choice question

The page adds the radio, requires the comment in the placeholder, and the receipt shows Other plus the comment.

EOF
)"
```

## Task 3: Docs

**Files:**
- Modify: `modules/inbox/PRODUCT.md` (the answer-controls bullet), `modules/inbox/DESIGN.md` (Option rows), `modules/inbox/README.md` (the Controls line), `skills/agent-inbox/SKILL.md` (the choice bullet)

- [ ] **Step 1: Update the four sentences**

In `PRODUCT.md`, replace:

```markdown
- Answer controls: choice (one option, one may be recommended), multi (several), text (short or long), approve (approve or revise with a reason).
```

with:

```markdown
- Answer controls: choice (one of the asker's options, one may be recommended; the page adds Other, and a comment is required to send it), multi (several), text (short or long), approve (approve or revise with a reason).
```

In `DESIGN.md`, under `### Option rows`, after the Disabled bullet, add:

```markdown
- **Other:** a choice question gets one more radio after the asker's options, inside the same fieldset, label Other, description "None of these. The comment is the reply." It is omitted when an option id is already `other`. The comment placeholder on a page that shows it is "Comment (required for Other)". A comment on one of the asker's options stays optional.
```

In `README.md`, replace:

```markdown
Controls: `choice` (2–6 options), `multi`, `text` (`size`: short|long), `approve` (approve, or revise with a required `--comment`).
```

with:

```markdown
Controls: `choice` (2–6 options; the page adds Other, which needs a `--comment`), `multi`, `text` (`size`: short|long), `approve` (approve, or revise with a required `--comment`). An answer value of `other` means the comment on the entry is the reply. Do not use `other` as an option id. The topic log records the value and not the comment.
```

In `skills/agent-inbox/SKILL.md`, replace the choice bullet:

```markdown
- `{"type": "choice", "options": [...]}`: pick one. 2 to 6 options, each `{"id", "label"}`, optional `"description"`, `"recommended": true`, `"default": true` (one at most). Telegram shows these as buttons.
```

with:

```markdown
- `{"type": "choice", "options": [...]}`: pick one. 2 to 6 options, each `{"id", "label"}`, optional `"description"`, `"recommended": true`, `"default": true` (one at most). Do not use `other` as an option id. The web page adds an Other radio; sending it requires a comment, closes the question, and the answer value is `other`. The comment on the entry is the reply. Read it from the entry (`agt inbox get`), not from the topic log, which records the value only. Telegram shows the asker's options as buttons and does not add Other.
```

- [ ] **Step 2: Run the suite**

Run: `.venv/bin/python -m pytest -q`

Expected: PASS. The docs change no behavior. This run is the check that Task 1 and Task 2 left the suite green.

- [ ] **Step 3: Commit**

```bash
git add modules/inbox/PRODUCT.md modules/inbox/DESIGN.md modules/inbox/README.md skills/agent-inbox/SKILL.md
git commit -m "$(cat <<'EOF'
docs(inbox): describe Other as a choice answer

The page offers it, the comment is the reply, and the topic log does not carry that comment.

EOF
)"
```

## Out of scope

- `notify.py`, Telegram buttons, and the numbered reply list.
- Teaching the autopilot what to do when it reads `other`.
- A follow-up that leaves the question open.
- More info and Simplify.
