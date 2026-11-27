---
name: inbox
description: Use when Tiago replies in the Hermes chat to an inbox card. Turns the reply into `agt inbox` on this machine.
---

# inbox

Call the CLI on this machine. Do not use the network.

A numbered reply `1` or `2` on the latest open question is:

```bash
agt inbox answer "$ID" --value "$OPTION_ID" --via telegram
```

First fetch the exact card with `agt inbox get "$ID"` and inspect its open state and option IDs. Map the number through the card; the human did not see the option ID. Natural-language agreement can also be an answer when the conversational referent is unambiguous: agreement that a card needs polish maps to the 'needs work' choice, not to the recommended positive choice. Preserve the agreed reasons with `--comment`; ask when the referent or choice remains ambiguous. After answering, fetch the same card again and verify its state, selected value and comment before claiming it was recorded. A recorded answer does not prove the asking agent has consumed it.

When designing or reviewing Telegram inbox cards for Tiago, prefer clear human-facing labels, real tappable choice buttons, and a short 'Open details' link. Hide raw priority/project tokens or label them clearly; do not expose a bare metadata header or a long raw URL as the polished card. Numbered replies remain a valid fallback for an existing card, not a reason to pretend that printed choices are interactive controls.

`approve` and `revise: ...` are the approve control. The text after `revise:` is `--comment`.

A line starting with `?` is:

```bash
agt inbox followup "$ID" --text "..." --via telegram
```

`approve ib-7k3q` names the id. Without an id, use the latest open question.
