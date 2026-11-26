# Conversation skill: design

Drafted 2026-11-26 with Tiago. This is spec 4 of the topic-awareness work. It builds on spec 1 (the topic log and the per-turn hook, `modules/registry/docs/superpowers/specs/2026-11-25-topic-awareness-design.md`), spec 2 (inbox entries carry their topic, `modules/inbox/docs/superpowers/specs/2026-11-25-topic-aware-inbox-design.md`) and spec 3 (the Topics tab, `modules/inbox/docs/superpowers/specs/2026-11-25-topic-graph-design.md`).

## Problem

A session's replies often end with a list of things for Tiago to decide. Each one is a short ask, and the context that explains it sits somewhere above it in the chat, or nowhere. With four or five items he has to scroll up, item by item, to rebuild what each one is about. His density rule makes this worse by design: it says a footer decision is "the terse ask itself (the reasoning stays in the body)".

The rules for how an agent talks to him are also spread out and partly in conflict:
- **The global instructions** hold "Response density" and "Technical altitude", in three copies: Claude, Codex and Cursor, which have already drifted apart.
- **The `topic-awareness` skill** holds the session intent, the topics under it, and forking.
- **The `conduct` skill** of Justin Sternberg's `maestro` plugin holds a `Next for you:` line ("one action, never a menu") and a decisions ledger, which conflict with the F-numbered footer. agent-tools used to keep a stale copy of it; since 77c5ee5 Claude uses the plugin itself, and Cursor links the plugin's files.

## Goal

One skill, `conversation`, owns how an agent talks to Tiago. Every decision it asks him carries its own context. Chat shows at most two decisions per turn, and the rest wait in the inbox under their topic, so nothing is forgotten and nothing piles up. The global instructions keep only how agents work.

## Decisions taken

| Question | Decision |
|---|---|
| One skill or several | One skill, `conversation`. It absorbs `topic-awareness` and the density rules from the global instructions, and it adopts the ideas of conduct's "The human" section and decisions ledger. |
| maestro's conduct | Used as Justin ships it, never edited. `conversation` overrides its rules for talking to Tiago (section 6). Its orchestration rules apply unchanged. |
| What stays global | "Don't claim untested properties" and "Review before handoff". They govern code comments, commits and PR text too, not only chat. Everything else listed in section 4 moves. |
| Decisions per turn | At most **two** in chat, each self-contained. More than two: the rest go to the inbox, and chat says how many are waiting. Tiago chose two to try; revisit after real use. |
| Where the ledger lives | In the inbox. Maestro's ledger section becomes the standard shape of an inbox question. The `/tmp/maestro/` file goes away. |
| How it loads | Injected at session start by the agent-tools hook, so it is in context from the first turn on every engine, like the global instructions are today. |

## 1. The decision card

Every decision the agent asks is a card. It reads correctly on its own, with no scrollback:

- **Where:** the `Intent › Topic` it belongs to.
- **The question,** as a question.
- **Why it matters:** one or two sentences, plain language. Ids are spelled out ("PR #92, which fixes the exit code…"), never bare.
- **Options:** the exact words to answer with, each with a one-letter alias: `` `merge` (m) ``. A card that bundles numbered recommendations also accepts `N: <change>`.
- **Recommendation:** one option and one sentence of why.
- **Next either way:** what the agent does with the answer.

This is maestro's ledger section, shortened for chat. The inbox entry holds the long form (section 2).

A card never says "see above". If context is needed, the card carries it.

## 2. Pacing: two in chat, the rest in the inbox

Each decision is also an inbox question. The card's long form is the entry's `summary` and `detail`, and the inbox files it under the session's topic by itself (spec 2). Then:

- **Two or fewer decisions:** both go in the reply's ending (section 3), each with its inbox link. This replaces agent-inbox's "Ask in both places" message format for these questions; the answer rules stay (answered in chat → `agt inbox answer --via chat`).
- **More than two:** merge the related ones first. If more than two remain, chat shows the two most consequential. The others are asked in the inbox only, and chat adds one line: `+3 more waiting under this topic: <Topics link>`.
- **After Tiago answers,** the agent brings up the next waiting decision in its next reply, until none are left.
- **Decisions the agent can make itself** are not asked. It decides, says so in one line, and posts it to the inbox as "decided, veto here", as spec 3 did.
- **Not through the inbox:** the fork / park / keep drift question from topic-awareness stays chat-only. It is quick, and its answer changes the very next step.
- **Inbox unavailable:** the card goes in chat in full, and the overflow line lists the extra cards' questions instead of a link.

### The per-turn reminder counts the queue

The per-turn hook line from spec 1 gains a count when the current topic has open questions: `Intent: X (tp-…) · Topic: Y (tp-…) · 3 open questions.` The registry already computes `open_questions` per topic from the inbox notes (spec 2), in-process. No count when it is zero.

### The Topics link opens the right branch

The overflow link is `https://<inbox>/topics#tp-xxxx`. The Topics page gains an `id` on each topic node, and opening the page with a fragment opens that branch and its parents and scrolls to it. A fragment that matches nothing is ignored.

## 3. How a reply ends

One ending for every session, replacing both the F-numbered footer and maestro's `Next for you:` line:

```
---
**Summary:** two or three lines recapping what this turn settled.

**Next for you:**
- F1. *Intent › Topic.* <the card, compact>. `token` (a) or `token` (b). Recommended: … — <inbox link>
- F2. …
+N more waiting under this topic: <Topics link>

**To hand off / do later:**
- F3. …
```

- F-numbers stay, continuous across both groups, so Tiago can answer "f1 - k / f3 - do it". Within a decision, the option aliases are letters.
- `Next for you: nothing` when nothing is owed. A message that is only a short answer skips the ending entirely.
- The body above the ending keeps the density rule: at most about three things that need his judgment, the confident ones and the shaky ones marked.

## 4. What moves where

**Into `skills/conversation/`:**

| From | What |
|---|---|
| `skills/topic-awareness/SKILL.md` | All of it: the intent, topics, forks, the drift check. `topic-awareness` is removed, and `install.sh` stops linking it. |
| maestro's conduct, "The human" (copied as ideas, not edited) | The single-ending rule, answer aliases, "questions get assessments, directives get execution", "never cut for brevity". |
| maestro's `references/decisions-ledger.md` (same) | The section shape and the rules, rewritten as the card and its inbox long form. |
| Global instructions, "Response density" | The ~3-item budget, saying where it might be wrong, the ending, long output to `./tmp/`, the `brief` / `deep` keywords. |
| Global instructions, "Technical altitude" | The altitude rule, glossing on first use, the `mechanism` / `eli5` keywords. |
| Global instructions, "Known ground" list | A reference file, `skills/conversation/references/known-ground.md`. "I'm familiar with X" now edits that file. |

**Stays global:** About me, "Don't claim untested properties" (today inside Response density; it moves to its own section), Review before handoff, and every section about how to work (git, PRs, 1Password, Watts, and so on). Each global file gets one line in place of the removed sections: "How you talk to me is owned by the `conversation` skill, which the session-start hook loads."

The three instruction files live in `~/projects/tjdsneto-setup/ai/instructions/` (Claude `claude/CLAUDE.md`, Codex `codex/AGENTS.md`, Cursor `cursor/user-rules.md`). They change in that repo, committed to its master, deployed with its `./install.sh`.

## 5. Loading: the session-start hook

The skill is split so the always-on part stays small:

- **`skills/conversation/CORE.md`,** at most about 900 words: the card, the pacing, the ending, the density and altitude rules, and the topic rules in short form (set the intent, open and close topics silently, the drift check). This is what is injected.
- **`skills/conversation/SKILL.md`:** the full skill, loaded on demand: fork mechanics and backends, `open_questions` handling, the inbox long form, edge cases.
- **`references/known-ground.md`:** read when deciding how much to gloss.

The registry hook (`modules/registry/plugin/scripts/registry-hook`) already prints session-start context on Claude and Cursor. Its `ensure` step appends `CORE.md` to that context, on all three engines:

- **Claude:** `SessionStart` `additionalContext` (already printed today).
- **Cursor:** `sessionStart` `additional_context` (already printed today). Not on `subagentStart`: subagents don't talk to Tiago.
- **Codex:** `SessionStart`, which prints nothing today. Unverified whether Codex accepts `additionalContext` there; the plan checks this first. If it doesn't, Codex keeps the one global pointer line plus the skill link, and loads the skill on demand.

A missing or unreadable `CORE.md` is not an error: the hook prints what it printed before. The Claude plugin's version is bumped so the cached hook updates (see the plugin-cache note in `.ana/learnings.md`).

Unattended runs (`claude -p` started by a script, with no human) get the same text. The skill says: no human in the chat means skip the ending and the cards; ask through `agt inbox --script` as the agent-inbox skill's "Unattended agents" section says.

## 6. Living with upstream maestro

Conduct is Justin's and is not edited here. Three layers keep his updates from silently overriding `conversation`:

1. **The override is by role, not by quoted text.** `CORE.md` says: any other skill's rules for how to end a message, how to ask Tiago a decision, or where to keep decisions yield to this skill, for example conduct's `Next for you:` line and its `/tmp/maestro/` ledger. Its orchestration rules still apply. A reworded or renamed upstream section is still covered, because the rule names what it does, not its words.
2. **A fingerprint check.** `skills/conversation/scripts/check-maestro` compares conduct's human-facing parts (its "The human" section and its ledger reference) with a baseline saved in `skills/conversation/references/maestro-baseline/`. A change prints the diff and exits 1. It runs in the conversation black-box suite and, as a warning only, in `install.sh`. A change means: reread it, decide whether the override still holds or there's something worth taking, then refresh the baseline in a commit.
3. **A behaviour test.** A real Claude run with conduct loaded, asked for two decisions, must end the reply the `conversation` way, not with conduct's single `Next for you:` line. Rerun after any maestro update.

Updates only arrive when the marketplace is updated (`claude plugin marketplace update jtsternberg`; no auto-update is set for it in `~/.claude/settings.json`). Cursor's links point into the same clone, so both engines change at the same moment.

Local additions to conduct, carried over from the retired Oslo persona, live in the full `SKILL.md` (loaded on demand, not in `CORE.md`), under "When you orchestrate":
- **Approve before spawning.** Work out the split of work with Tiago first; nothing is spawned until he approves it.
- **Every worker brief carries the dev-env claim rule:** a worker that runs tests in a main dir claims it first (`dev-env claim … --pid $$`), as the global instructions say.
- **Check what's running with the registry:** `agt sessions` and the Topics tab, not a separate log.
- **Close out at wrap:** finished workers' topics are closed, carry-overs are named in the summary. Conduct's triage sweep covers the rest.

Proposed upstream, optional: a sentence in conduct that the human's own instructions about how replies end take precedence. That would make the override official instead of a conflict resolved by precedence.

## Out of scope

- Moving "Clickable file links" and "Showing refs TO me" into the skill. They are about chat output too, but they are editor- and GitHub-specific; they can move later.
- Changing the inbox's own UI beyond the Topics anchors.
- Measuring whether two per turn is the right number. Tiago will judge it in use.

## Testing

- **Registry hook (black-box, `modules/registry/tests/blackbox/`):** `ensure` on Claude and Cursor includes `CORE.md`'s text; Cursor `subagentStart` doesn't; a missing `CORE.md` gives today's output; the per-turn line shows the open-question count only when it is above zero.
- **Codex:** a real `codex exec` run in a temp registry where the injected text includes a marker sentence, checked by asking the agent to repeat the marker. This settles the unverified Codex point.
- **Real Claude run:** a scripted session that produces three decisions. The reply shows at most two cards, each with an `Intent › Topic` and aliases, plus a `+1 more waiting` line, and the inbox has three open entries under the topic. Wording varies, so the check looks for the structure, not sentences.
- **Inbox:** the Topics page renders an `id` per topic, and a fragment opens that branch (unit test plus a screenshot at 390 px).
- **Upstream maestro:** `check-maestro` passes against today's baseline and fails on an edited copy; the behaviour test in section 6.
- **Instruction files:** after the move, a check that each removed heading is gone from all three files and that each moved rule appears in `CORE.md` or `SKILL.md`, so nothing is dropped in the move. Then read the three files end to end.

## Risks

- **Context cost.** `CORE.md` is injected in every session. It replaces the density sections it removes from the global files, so the net change should be small; the plan measures both.
- **Inbox noise.** Every decision becomes an inbox entry, including ones Tiago answers in chat seconds later. They are marked answered at once, so they leave the feed, but History grows faster. If it's too much, raise the threshold: only overflow decisions go to the inbox.
- **Withholding.** Showing two at a time means the agent chooses what Tiago sees first. The `+N more waiting` line keeps the rest visible.
- **Upstream changes.** Justin can change conduct at any time. Section 6 covers how that is caught.
