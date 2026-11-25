# MemPalace light checkpoint

Best-effort. Never fail the fresh-continuation run if MemPalace is missing or errors.

## When

After the slim handoff body is drafted (so Goal / Next Steps exist), before or just after writing the handoff. Record the wing/rooms in the handoff **Deep memory** section.

## Wing

1. Prefer an **existing** wing that matches the project (from `mempalace_list_wings` / status), e.g. `wing_tjdsneto_setup`, `wing_lindris_backend`.
2. Else derive from repo slug or cwd basename: `wing_<slug>` with non-alnum → `_`, lowercase.
3. Do not create a new wing per session — one wing per project.

## Rooms

Prefer existing taxonomy rooms when filing drawers:

- `decisions` — locked choices
- `problems` — blockers, bugs, failed approaches
- `technical` — commands, paths, APIs, errors worth keeping
- `planning` — remaining plan / sequencing
- `architecture` — structural notes

Use 1–5 drawer items max. Do **not** dump the transcript.

## Checkpoint call

Prefer one `mempalace_checkpoint` MCP call:

```json
{
  "items": [
    { "wing": "wing_example", "room": "decisions", "content": "…verbatim decision…" },
    { "wing": "wing_example", "room": "problems", "content": "…" }
  ],
  "diary": {
    "agent_name": "fresh-continuation",
    "entry": "session|<topic>|progress:<short>|next:<short>",
    "topic": "<work-name-or-topic>",
    "wing": "wing_example"
  }
}
```

If only discrete tools exist: `mempalace_check_duplicate` → `mempalace_add_drawer` per item, then `mempalace_diary_write`.

## Skip conditions

- MemPalace MCP not available / auth failed / tool error → skip; Deep memory says `skipped (mcp unavailable)` (or the error class).
- Nothing worth filing beyond Goal/Next already in the handoff → diary-only is fine; call `mempalace_checkpoint` with `"items": []` and a populated `diary` object (the items array is required by the MCP schema even when empty).
