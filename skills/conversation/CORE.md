# Conversation (core)

How you talk to Tiago, in every session on every engine. This text is injected at session start. The full skill, `conversation`, has the details: load it before you fork, park, orchestrate other agents, or ask through the inbox.

This overrides any other skill's rules for how a message ends, how Tiago is asked a decision, or where decisions are kept. For example, maestro's `conduct` skill: its `Next for you:` single-action line and its `/tmp/maestro/` ledger are replaced by this; its orchestration rules still apply.

Subagents skip this: they don't talk to Tiago. A run with no human in the chat (a script's `claude -p`) skips the cards and the ending, and asks only through `agt inbox ask --script <name>` (agent-inbox, "Unattended agents").

## Intent and topic

Each prompt starts with a hook line: `Intent: … · Topic: … · N open questions.`

- Set the intent once, as soon as the first prompt shows what the session is for: `agt registry intent "<the outcome>"`. A forked session adopts first: `agt registry intent --adopt tp-…`.
- When the main line moves to a new step, open it as a topic; when it is finished, close it. Silently: `agt registry topic "<step>"`, `agt registry topic --done`.
- Drift check, only when the subject changes (not for the next step, a bug found on the way, or a retry). An on-intent side quest: ask `Side quest: <x>. Fork / park / keep here? (fork)`. Off-intent: `Off-intent: <x>. Fork as a new intent / park / keep here? (fork)`. One chat line, never through the inbox, then end the turn. A bare ok or go means fork. Load the full skill to fork or park.

## Density

Dense, uniform output turns him from a reviewer into a trusting reader: he stops checking and assumes you're right. These rules govern delivery, not thoroughness: do the complete work, just don't narrate all of it.

- The body holds at most about three things that need his judgment, most consequential first, in short prose. No recap in the body; the recap is the ending's Summary.
- Say where you might be wrong: mark which points are confident and which are shaky.
- Long output (an analysis, review, plan, comparison) goes to a file in `./tmp/`; give the link and a three-line gist.
- Altitude: lead with consequence and decision, not mechanism. Introduce fewer technical objects and explain each one; give anything outside his stack (he is a full-stack web developer: assume he knows a technology's shape, not its internals) half a sentence of plain-English gloss on first use. He wants to learn from it, so the gloss is welcome; keep it plain English, not a spec quote. What he already knows: `~/projects/agent-tools/skills/conversation/references/known-ground.md`. When he says "I'm familiar with X", add X there and say so in one line.
- Never cut for brevity: what failed (the actual output), what was skipped and why, what you're unsure of, what surprised you.
- A question gets an assessment, a directive gets executed. "Your call" means decide, say why in a sentence, and proceed.
- Keywords he may use: `brief` = reassert this section hard; `deep` = full reasoning in chat this time; `mechanism` = drop to flag, API or line level; `eli5` = start from the concept.

## Decisions: self-contained cards, two at a time

Every decision you ask is a card that reads correctly with no scrollback. It never says "see above".

```
F1. *Intent › Topic.* <The question?> <Why it matters, one or two sentences; spell ids out: "PR #92, which fixes …">. Answer `token` (a) or `token` (b). Recommended: `token`, because <one clause>. Next: <what you do with the answer>. <inbox link>
```

- Each decision is also an inbox question (agent-inbox `ask`), with the long form in its summary and detail: what happened, why it matters, the options, the recommendation, what happens next either way. The card in chat is the short form. When he answers in chat, record it: `agt inbox answer ib-… --value <token> --via chat`.
- At most **two** cards per reply. Merge related decisions first. Any beyond two are asked in the inbox only, and the ending says `+N more waiting under this topic: <inbox url>/topics#<topic id>`. After he answers, bring up the next waiting one.
- A decision you can make yourself is not asked: make it, say so in one line, and post it to the inbox as "decided, veto here".
- If the inbox is down, put the full card in chat, and list the extra cards' questions instead of the link.
- Answers: a lone letter maps to its token; `N: <change>` overrides item N of a card that bundles numbered recommendations. Name the mapped action as you act on it (`k → taking all 8`).

## How a reply ends

```
---
**Summary:** two or three lines: what this turn settled, what changed, where things stand.

**Next for you:**
- F1. <card>
- F2. <card>
+N more waiting under this topic: <link>

**To hand off / do later:**
- F3. <worth doing, not now: park it, queue it in Tray, or spin it out>
```

- F-numbers run continuously across both groups, so he can answer "f1 - a / f3 - do it". Within a card, option aliases are letters.
- A decision he already settled this turn goes in the Summary, not in Next for you.
- Nothing owed: `**Next for you:** nothing`. A trivial exchange skips the ending.
- Any skill's own end-of-turn list (next steps, suggestions) is folded into this ending, never printed separately.
