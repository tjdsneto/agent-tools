# Other on every choice: design

Approved 2026-11-27. Tiago answered `ship` on the inbox question "Add an Other option on every choice so a comment can be the answer?" (`ib-4r4a`).

## Goal

A choice question on the web page always offers one more radio, Other, so a comment can be sent when none of the asker's options fit. Picking Other and writing a comment closes the question. The comment is the reply.

## Decisions

| Question | Decision |
|---|---|
| Where the radio comes from | The page adds it. It is not stored in the asker's control, so the 2–6 option limit stays and questions already open gain it immediately. |
| What submitting it does | Closes the question. The answer value is `other`. The comment is required, and it is the reply. |
| Who accepts it | `validate_answer`, so the web form, the CLI, and a chat recording share one rule. |
| Telegram | Unchanged. Buttons and the numbered card stay the asker's options. A button cannot carry the comment. |
| Other controls | Multi, text, and approve are unchanged. Approve already requires a comment to revise. |
| Reserved id | A new ask cannot use `other` as an option id. No stored question uses that id today (checked 2026-11-27). If one already has it, the page does not add a second radio, and that id keeps the asker's meaning: the comment stays optional. |
| Where the comment lives | On the entry's answer. The topic log records the value `other` and not the comment. An asker reads the comment from the entry. |
| Autopilot | The inbox delivers `other` and the comment the same way it delivers any other answer. The next autopilot run is told, in ana's preamble, that a value of `other` means the comment is the decision. |

## 1. The page

On a choice question, after the asker's radios and inside the same fieldset, one more radio:

- `name="value"`, `value="other"`, label `Other`
- description `None of these. The comment is the reply.`

It sits inside the fieldset, so a held or unreachable question disables it with the other radios. It is not added when an option id is already `other`.

The comment field's placeholder on a page that shows this radio is `Comment (required for Other)`. A comment on any of the asker's options stays optional. The server is what enforces the requirement. No new JavaScript. The form still posts to `/e/<id>/answer`.

A page that already has an option id `other` keeps today's placeholder, `Comment (optional)`.

## 2. Validation

`validate_answer` for a choice:

- Accept `other` only when that id is not already one of the stored options and the comment, after stripping, is non-empty.
- A missing or whitespace-only comment is `other needs a comment`. The question stays open.
- When the stored options already include `other`, that value is the asker's option and the comment stays optional.
- A comment on any stored option stays optional, as it is today.

`validate_control` rejects a new choice or multi option whose id is the exact string `other`. Option ids stay case-sensitive, so an id such as `Other` is a different option and the page still adds the reserved radio.

The stored control is not rewritten. `agt inbox get` still lists only the asker's options. The answer payload is the same shape as any other answer: `value` is `other`, `comment` is the stripped text.

`agt inbox answer <id> --value other --comment "..."` uses the same rule. Without the comment it fails.

## 3. The receipt and delivery

When `other` is not one of the stored options, the answered card shows the label `Other`, then the comment. Today the card prints a value that has no stored label as the raw id, so this mapping is new. When the stored options already include `other`, the card shows that option's own label.

Delivery is the path every answer already takes. A session asker is woken with value `other` and the comment. A script asker finds both the next time it reads the entry. The question leaves the open feed. The topic log's `answered` note carries the value `other` and does not carry the comment.

## 4. Docs updated with the change

- `modules/inbox/PRODUCT.md`: the answer-controls line names Other.
- `modules/inbox/DESIGN.md`: the option rows describe the extra radio, and the comment placeholder.
- `modules/inbox/README.md`: the controls line names Other.
- `skills/agent-inbox/SKILL.md`: a choice answer may be `other`, the comment on the entry is the reply, do not use `other` as an option id, and read the comment from the entry rather than from the topic log.

## 5. Tests

- The choice page renders Other after the asker's options, and does not render a second one when the id is already present.
- Posting Other with a comment answers the question, and the receipt shows Other plus the comment.
- Posting Other with an empty or whitespace comment returns 400 and leaves the question open.
- A new ask whose option id is `other` is rejected. A multi option with that id is rejected too.
- A stored option that is already id `other` still answers with an optional comment, and its page has one radio for it.
- A held question's fieldset stays disabled, and the Other radio is inside it.
- Multi, text, and approve pages do not gain the radio.
- `agt inbox answer --value other --comment ...` succeeds. The same command without a comment fails.

## Out of scope

- Telegram buttons and the numbered reply list.
- Any asker other than the autopilot. The autopilot's preamble now says a value of `other` means the comment is the decision.
- A follow-up that leaves the question open. Other closes it.
- More info and Simplify. They stay for questions that have a session to wake.
