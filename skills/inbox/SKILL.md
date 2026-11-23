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

Map the number through the card. The human did not see the option id.

`approve` and `revise: ...` are the approve control. The text after `revise:` is `--comment`.

A line starting with `?` is:

```bash
agt inbox followup "$ID" --text "..." --via telegram
```

`approve ib-7k3q` names the id. Without an id, use the latest open question.
