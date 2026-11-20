# Agent Registry Dashboard — UX Review

**Reviewer:** Claude (senior UI/UX pass) · **Date:** 2026-09-25
**Reviewed:** live board at `http://127.0.0.1:18765/`, `agent_registry/static/dashboard.html`, `/api/live` + `/api/archive` responses, `dashboard.py`, `ops.py`, `archive.py`.
**Method:** read full HTML/CSS/JS source; read the serving Python (`dashboard.py`, `ops.live_views`, `archive.py`) to check claims against actual behavior, not just the spec; hit the live API with seeded data; opened the board in a real (headless) browser and screenshotted both tabs, toggled group-by-project, and inspected the DOM/accessibility tree. Dark theme was reviewed from the CSS custom properties and verified by contrast-ratio calculation, not screenshotted (headless Chrome defaulted to light `prefers-color-scheme`).

## 1. Executive verdict

This is a solid, honest v1 that hits its stated constraints: single file, no build step, dark-mode-aware, loopback-only, and it correctly does the boring-but-critical things — HTML-escaping all agent-controlled text before `innerHTML` injection, deduping blocked+stale into one attention band, pausing polling on a hidden tab. Visually it reads as a utilitarian ops board, not a marketing page, which matches the brief. The two things holding it back from "actually useful during a busy multi-project day" are (1) everything in the attention band and everything in the active list looks the same regardless of how urgent it is, so scanning still means reading every line, and (2) the live registry has no corruption handling at the API layer even though the archive does — a corrupt `registry.json` will currently surface as a confusing JS parse error instead of the clean banner the archive path already has. Neither is hard to fix; both matter more than any visual polish item.

## 2. What's working

- **Attention-first structure matches the goal.** Blocked ∪ stale, deduped, rendered above Active — the core "what needs me" promise from the spec is implemented correctly (verified against `ops.live_views` and the live JSON).
- **XSS-safe rendering.** `esc()` is applied to every field pulled from session/archive data before it's spliced into `innerHTML` (`summary`, `directory`, `issue`, `pr.title`, `branch`, `session_id`). This matters here specifically because session content is agent-authored, not user-authored — a compromised or buggy agent could write anything into `summary`. Good discipline.
- **Client backoff and localStorage preferences are implemented as specced** — polling stops on `document.hidden`, tab/group/reason choices persist across reloads.
- **Archive corruption is handled gracefully** — `is_corrupt()` flag, dedicated banner copy, empty list instead of a crash. This is the bar the live side should also meet (see Issue #1).
- **Dark mode via `prefers-color-scheme` with a real token set** (not just inverted colors) — checked contrast math for `--muted` against `--bg` in both themes: light is ~5.3:1, dark is ~6.5:1, both clear WCAG AA for body-size text. No contrast fix needed here.
- **Restrained visual language** — no gradients, no card shadows, no icon-as-decoration; it looks like a tool, which was an explicit goal.

## 3. Issues

### Critical

None. Nothing observed is broken or actively misleading for the tool's current single-user, sighted-desktop-operator use case. The item below is the closest to Critical and would move up if this tool ever gets a second consumer (a screen-reader user, or headless polling by another script) or if `registry.json` corruption becomes a realistic occurrence.

### Important

**1. Live registry corruption is unhandled — inconsistent with archive's own bar.**
`dashboard.py:29` calls `ops.live_views()` directly inside `do_GET` with no try/except. `live_views()` calls `store.load()`, which raises `CorruptRegistryError` on a bad `registry.json` (`store.py:45`). That exception is never caught, so `/api/live` returns Python's default unhandled-exception response (not JSON) instead of a 200 with an empty payload. The dashboard's `fetchJson` then fails `res.json()` parsing and falls into the generic catch block, showing `"Fetch failed — showing last good data. SyntaxError: Unexpected token..."` — a confusing, implementation-leaking message, right next to the archive path which handles the identical failure class (corrupt JSON) cleanly with a purpose-built banner. **Fix:** wrap the `/api/live` handler the same way `_serve_archive` wraps archive reads — catch `CorruptRegistryError`, return `{"active": [], "stale": [], "attention": [], "corrupt": true}` with 200, and give the JS a `live.corrupt` banner parallel to the archive one.

**2. Attention band doesn't distinguish "needs a decision" from "just old."**
Per spec, `attention = blocked ∪ stale`, and that's implemented — but blocked (a session waiting on you right now) and stale (an abandoned session nobody's watching) render as visually identical cards, differing only in the small muted `status` word. On a busy day with several attention items across projects, the operator has to read every status word to find the one thing that's actually blocking on them. This directly undercuts the board's stated #1 goal ("see what needs attention"). **Fix:** something cheap and non-decorative — a left-edge color tick or a small text tag (`blocked` vs `stale`) styled distinctly, or two sub-headings inside the attention band ("Blocked" / "Stale") instead of one flat list.

**3. Status word carries no visual weight anywhere.** `working`, `idle`, `blocked`, `reviewing` all render as the same muted gray text at the same weight as the directory path underneath. Status is arguably the second most important field on a card (after project/type) and currently has zero visual priority — it's competing with metadata for attention instead of standing out from it.

**4. Tab buttons break the ARIA tablist pattern they declare.** The `<nav role="tablist">` wraps two `<button>`s with none of `role="tab"`, `aria-selected`, or `aria-controls`. A half-implemented ARIA pattern is worse than none: assistive tech announces "tab list" but then finds children with no tab semantics, which is a known AT confusion case. Since the buttons are real `<button>` elements, keyboard operation (Tab + Enter/Space) already works fine without any ARIA — the fix here is just to either complete the pattern (`role="tab"`, `aria-selected="true/false"`, `aria-controls` pointing at the panel `id`) or drop `role="tablist"` from the `<nav>` and let it be a plain toolbar.

**5. No counts anywhere.** Tab labels (`Live`/`Archive`), the attention/active band headers, and per-project group titles all show zero indication of how many items are inside. On a multi-project day this means scrolling/reading to find out "how many things are blocked" instead of glancing at a number. Cheap, high-value fix: `Needs attention (2)`, `tjdsneto-setup (1)`.

### Nice-to-have

**6. Empty state copy is just "None."** Terse to the point of reading like a bug rather than a deliberate "nothing here" state, especially in the attention band where "None" for attention is actually good news. A one-line contextual empty state per band (`"Nothing needs attention"` / `"No active sessions"` / `"No archived events"`) would read as intentional.

**7. Archive filter chips convey active state by background color only, with no `aria-pressed`.** Sighted users get it instantly from the black/white swap; anything relying on the accessibility tree cannot tell which reason filter is currently applied. Add `aria-pressed="true/false"` to the chip buttons and toggle it alongside the `active` class.

**8. Raw `session_id` is always shown as its own full-width meta line**, even for short human labels like `sess-live-1`. For long UUIDs (the common case for real Claude sessions) this adds a full line of low-scannability noise to every single card. Consider de-emphasizing it further (smaller/lighter, or collapsed until hover) rather than giving it equal visual weight to the summary line above it.

**9. Single centered column at `max-width: 960px` on what is explicitly a desktop tool.** On a wide monitor this leaves most of the width empty while, on a day with several projects, the operator scrolls a long single column. A two-column card grid per band (or a denser table-row layout) would use the desktop canvas the tool is designed for.

**10. Fetch-failure banner text embeds the raw JS error and URL** (`"Fetch failed — showing last good data. " + err.message`). Fine for a solo technical user, but if this tool is ever shared or the error text is ever screenshotted/reported, it's leaking implementation detail unnecessarily.

## 4. Priority fix order (top 5)

1. **Live corruption handling (#1)** — closes a real gap against the archive's own bar; cheap, same pattern already exists to copy.
2. **Attention band blocked/stale distinction (#2)** — the single change most likely to make the board faster to scan on a real busy day.
3. **Status visual weight (#3)** — small CSS change, meaningfully improves scanability, pairs naturally with fix #2.
4. **Counts on tabs/bands/groups (#5)** — cheap, no new markup patterns, immediate scanability win for multi-project days.
5. **Tab ARIA semantics (#4)** — either complete the pattern or remove it; low effort, correctness issue either way.

## 5. Out of scope / later (heavier redesigns)

- Two-column / grid card layout for wide desktops (#9) — worth doing, but is a genuine layout redesign, not a tweak.
- Any move toward a component framework, live-updating diff highlighting (flash-on-change), or richer archive search/filtering beyond the existing reason chips — explicitly a later phase per the spec's non-goals (SQLite index, richer UI).
- Sound/desktop notifications for new attention items — explicitly a non-goal for v1.
- A dedicated "last updated" / connection-freshness indicator beyond the error banner — worth having but is a small feature, not a fix, and wasn't asked for in the spec's v1 behavior section.
