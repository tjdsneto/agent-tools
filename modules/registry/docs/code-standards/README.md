# Code standards

> **Scope:** navigation — governs no code path directly.

**Core Principle:** docs here say how code in this repo should be written, one layer or concern at a time. Read the relevant doc before designing, implementing, or reviewing that layer. Feature behavior belongs in `docs/specs/`, not here.

No layer doc exists yet. Rules are added when a layer has a rule worth enforcing, checked against the code at that time. They are not copied out of `docs/superpowers/`.

## How to read a rule

**The invariant: a violation of a rule here is always flagged.** The marker sets how hard the finding pushes. It does not decide whether the finding is raised.

| Marker | Means | Reviewer behaviour |
|---|---|---|
| *(unmarked)* | The standard, believed to hold; not independently proven. | **Flag; enforce with flexibility** — block a clear or severe violation, suggest otherwise |
| **Verified:** + the proving command | Proven against the code, with the command that reproduces the check shown inline. | **Flag; lean to block** — it is demonstrated |
| **Known offenders:** + named sites | The named existing sites don't conform. The rule still governs new code. | **Flag *new* violations**; the named sites are cleanup work, not re-flagged |
| **Target:** | An agreed direction the code has not reached. Not yet required. | **Flag as a suggestion; never block** |

`Verified:` strengthens a rule. It is not required for the rule to count. A claim is still checked against the code when it is written.

Start at [overview.md](overview.md).

## Index

| Doc | What it covers |
|---|---|
| [overview.md](overview.md) | **REF.** Where the code lives today, and which layer a change belongs in. No prescriptive rules yet. |

## Consumers

None found as of 2026-11-16. This repo has no `CLAUDE.md`, no `docs/compounding/review-conventions.md`, and no conventions router skill. A later change that adds one of those points it here in the same change.

## Related doc families

- Living component specs: `docs/specs/`.
- Historical designs and plans: `docs/superpowers/specs/`, `docs/superpowers/plans/`.
- Family definitions and the marker law: `~/projects/tjdsneto-setup/ai/pr-review-standards/docs-taxonomy.md`.
