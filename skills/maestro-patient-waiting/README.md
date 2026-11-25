# Patient Waiting — wait without burning tokens

A zero-token discipline for waiting on **anything** — a file or status change, a
review submit, a PR, a CI run, a deploy, or a human's approval. Load it *before*
setting up any poll, watch loop, recurring check-in, or scheduled-wakeup loop.

It exists to prevent one specific runaway: the main agent — often the scarcest,
most expensive model in the session — waking itself on a schedule just to read a
status file that hasn't changed. One real incident spent ~140 full-context
premium-model turns over a week confirming that nothing had happened.

## Use it when

- You're about to "check in on X", "watch for Y", "tell me when Z", "poll", or
  "monitor this".
- A background watcher got killed and you're tempted to work around it by
  rescheduling the model.
- Anytime the cost of *how* you wait matters as much as the waiting.

## What it enforces

- **A waiting ladder, taken in order.** Prefer a background `until` loop (zero
  tokens idle, one notification when the condition flips); then a shell-side
  monitor that wakes the model only on a real signal, used only when the event
  fits inside the deadline that monitor reports back — a harness can accept a
  "persistent" request and still cap the task; and only if both keep dying,
  stop and hand the loop to the human.
- **Never machine-poll a human.** A human-triggered event (a review, an
  approval, "when I'm ready") is closed by the human speaking. A scheduled model
  wake adds cost and nothing else.
- **Scheduled wakes are for machine-paced state only** — and even then carry
  mandatory backstops: max three quiet polls, no off-hours polling, and a
  visible quiet-poll count in every reschedule's reason.
- **A killed watcher is a blocker, not a license to escalate.** The failure of a
  cheap mechanism never justifies substituting an expensive one of the same
  shape. Name the problem, offer options (including "do nothing — you nudge me"),
  and wait.

## Pairs with

- **`conduct`** — the boss-not-doer stance for orchestrating an
  implement → review → address pipeline, which relies on this discipline for the
  waits between phases. Find the set under the **`maestro`** tag.
- **`session-waker`** — for a wait that outlives the session itself (token
  exhaustion, machine sleep, terminal close): an external monitor wakes the
  session when its token window resets.
- **[until](https://skills.awesomemotive.com/skills/delayed-work-until/)** — this
  ladder with the clock as the watched condition, for when the thing you're
  waiting on is a wall-clock time rather than a change in state.
