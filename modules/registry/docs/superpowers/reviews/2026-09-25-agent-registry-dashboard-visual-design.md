# Agent Registry Dashboard: Visual Design Critique

**Reviewer:** Claude (visual design pass) · **Date:** 2026-09-25
**Input:** screenshot of the Live tab (light theme, 5 sessions over 3 projects) and `agent_registry/static/dashboard.html` (CSS and render functions).
**Builds on:** `2026-09-25-agent-registry-dashboard-ux-review.md`. That review covered structure, ARIA and data handling, and I don't repeat it here. This document covers only the look.

---

## 1. Gut reaction

It looks like an unstyled admin page from 2012: a Bootstrap `alert-warning` box on top of a `<ul>`. Nothing is broken, but nothing looks designed. Every line of text has the same size and weight, so you have to read the board to use it. An ops board should let you see the state at a glance. The one colored element, the cream box with a tan border, reads as a "notice" and not as a warning, so the most important section on the page feels decorative.

The bones are good: a restrained palette, no gradients, and the attention band sits first. The ugliness is almost entirely hierarchy, alignment and chrome. The fix is not to add decoration. The fix is to give each piece of information a role and a place.

## 2. Why it reads as ugly

Most damaging first.

1. **No type hierarchy.** Everything is 14px, or 0.85 × 14 ≈ 12px. The only contrast is "black" or "grey". The summary line ("Need decision on archive retention") is the most useful text on the card. It sits in slot 3 of 5 at body size, with the same weight as a raw path. The agent type (`claude`) is the only bold text, and it is the least useful field because there are just three possible values.
2. **Each card is a 5-line stack with no columns.** Type+status, path, summary, meta and session id each get their own full-width line, left-aligned and ragged. Nothing lines up across cards except the age, which floats alone at the far right, about 600px from the text it describes. The eye zig-zags.
3. **Absolute paths dominate the visual mass.** `/Users/tjdsneto/projects/...` repeats on every card and is the longest string on the card. Inside a project group, the path is mostly redundant with the group header. The session UUID adds another long, meaningless line. About 40% of the ink on the page is noise.
4. **Status has no visual weight.** `blocked`, `idle` and `working` are the same grey word. The page has no color that carries meaning. The cream band only says "this box is different", not what state anything is in.
5. **The attention band uses a parchment palette.** `#faf6f0` with `#c9a66b` is low saturation and warm. It reads as "vintage" or "sticky note", not "needs you". It is also close to the cream-and-terracotta cliché we want to avoid.
6. **Too many hairlines, boxes inside boxes.** There is a band border, then a group-title rule, then a card rule, then another group-title rule. In a 5-item list there are about 9 horizontal grey lines, each the same weight. Line weight is not used to show hierarchy, so the lines just add texture.
7. **Default form chrome.** The "Group by project" control is a native checkbox inside a bordered, grey-filled pseudo-button, floating by itself above the content. It is the most "HTML form" element on the page, and it has the most prominent position after the header. The Live/Archive tabs are two heavy separate buttons, and the active one is solid black, which is the heaviest element on the screen.
8. **Dead header, dead gutters.** The header is a full-width white bar that holds only a 16px wordmark and the tabs, pushed to opposite corners. The content is a 960px column with about 180px of empty warm-grey on each side. The header and content don't share edges, so the page feels unanchored.
9. **Warm-grey plus pure white plus warm border is the default-template palette.** `#f6f6f4`, `#fff` and `#d0d0cc` together have no temperature decision behind them. The result is slightly beige and slightly dull.
10. **No numerals treatment.** Ages ("13m ago", "7h ago") are proportional text with a word suffix. They don't align and they take up width.

## 3. Recommended direction: a quiet instrument panel

**One sentence:** a cool, neutral graphite surface; rows instead of cards; a status dot as the only saturated color; the summary as the headline; identifiers in monospace; counts everywhere.

Reference feel: the Linear issue list or the GitHub Actions run list. It is not Grafana, and it is not a SaaS landing page. The board is dense, calm and aligned. Color appears only where state lives.

### 3.1 Tokens

Use a cool neutral. Define both themes and let `prefers-color-scheme` pick. The status hues are close to GitHub Primer values, so they are familiar and already contrast-checked in both themes.

```css
:root {
	/* surfaces */
	--bg:        #f6f7f9;
	--surface:   #ffffff;
	--surface-2: #f1f3f5;   /* group headers, hover */
	--line:      #e4e7eb;   /* the ONLY divider color */
	--line-strong: #d3d8de; /* section outline */

	/* text: three steps, no more */
	--text:   #16191d;
	--text-2: #5a636e;
	--text-3: #8b939d;

	/* state: the only saturated colors on the page */
	--ok:      #1a7f37;  /* working */
	--info:    #0969da;  /* reviewing / other active */
	--warn:    #9a6700;  /* stale */
	--danger:  #cf222e;  /* blocked */
	--idle:    #8b939d;  /* idle */

	--radius: 8px;
	--row-x: 16px;
	--mono: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, monospace;
	--sans: system-ui, -apple-system, "Segoe UI", sans-serif;
}
@media (prefers-color-scheme: dark) {
	:root {
		--bg:        #0d0f12;
		--surface:   #14171b;
		--surface-2: #1a1e23;
		--line:      rgba(255,255,255,.06);
		--line-strong: rgba(255,255,255,.10);
		--text:   #e6e8eb;
		--text-2: #9aa3ad;
		--text-3: #6b7480;
		--ok:     #3fb950;
		--info:   #58a6ff;
		--warn:   #d29922;
		--danger: #f85149;
		--idle:   #6b7480;
	}
}
```

Rules: use no other colors. No shadows, except perhaps `0 1px 0 var(--line)` under a sticky header. Borders are always 1px `--line`. Section outlines use `--line-strong`.

### 3.2 Type scale

Keep the system font; it's a localhost tool, so no webfonts. Use four sizes, each with a job:

| Role | Size / weight | Font |
|---|---|---|
| Row headline (summary) | 14px / 500, `--text` | sans |
| Section header ("Needs attention") | 13px / 600, `--text` + count | sans |
| Meta line (agent · status · path · PR) | 12px / 400, `--text-2` | sans; paths/branch/issue in mono |
| Micro (group header, age, session id) | 11px / 500, `--text-3` | group header sans uppercase +0.04em; age and id in mono, `tabular-nums` |

Kill the tiny, muted, uppercase "NEEDS ATTENTION" label. Section headers should be the loudest labels on the page, not the quietest.

### 3.3 Row anatomy (replaces the card)

```
 ┌─────────────────────────────────────────────────────────────────────────┐
 │ ●  Need decision on archive retention                              13m │
 │    claude · blocked   ~/projects/tjdsneto-setup   ⎇ docs: agent-reg…   │
 └─────────────────────────────────────────────────────────────────────────┘
   ^16px dot column     ^ meta: 12px, text-2; path/branch mono           ^ age: mono 11px, right, tabular
```

- **Grid:** `grid-template-columns: 16px 1fr auto; column-gap: 10px; padding: 10px var(--row-x);`
- **Column 1:** an 8px status dot, colored by status and vertically centered on the headline.
- **Line 1:** the summary as the headline, on one line with `text-overflow: ellipsis`. **Fallback when there is no summary:** show the directory basename in `--text-2` (for example "agent-registry"), so idle rows still have a headline and don't collapse to metadata.
- **Line 2:** one meta line. Agent type (sans, `--text-2`), then the status word colored with its state token, then `~`-shortened path in mono, then issue/branch/PR. Separate the fields with a `·` in `--text-3`, or with 12px gaps. Drop the path when it equals the group's project name.
- **Age:** a compact form (`13m`, `7h`, `2d`) with no "ago", in mono `tabular-nums`, `--text-3`. Put the full ISO timestamp in `title`.
- **Session ID:** remove it from the visible row. Put it in the `title` attribute of the row, or show it on `:hover` or `:focus-within` as a line 3 in 11px mono `--text-3`. This single change removes about 20% of the vertical height.
- **Dividers:** `border-top: 1px solid var(--line)` on rows, **inset** so they start at the text column, not the dot (`margin-left: calc(var(--row-x) + 26px)`, or use a pseudo-element). Inset dividers are the cheapest "designed" signal.
- **Hover:** `background: var(--surface-2)`. That's all.

A row is about 52px, down from the current card's roughly 90px. The Active band then fits about 12 sessions above the fold, not 5.

### 3.4 Sections and project groups

- Each section (Needs attention, Active) is **one** surface: `background: var(--surface); border: 1px solid var(--line-strong); border-radius: var(--radius); overflow: hidden`.
- The section header sits **inside** the surface as a 40px row: title plus count on the left, and optional secondary info on the right. It has a `--line` bottom border.
- A project group header is a slim 28px row with `background: var(--surface-2)`, 11px uppercase `--text-3`, project name plus count (`TJDSNETO-SETUP  1`). Don't put a rule under it; the background band does the separating. This removes about half of the hairlines.
- Leave 20px between sections. That gap is the only whitespace separation needed.

### 3.5 Attention treatment

Drop the cream tint on the whole section. Instead:

- **Section header:** "Needs attention" in `--text`, followed by a count pill. The pill has a background of `color-mix(in srgb, var(--danger) 14%, transparent)`, text in `--danger`, 11px, 600 weight, radius 999px. If only stale items are present, use `--warn` instead of `--danger`.
- **Per row:** a 2px left accent bar in the row's state color (`box-shadow: inset 2px 0 0 var(--danger)`), plus a very light wash only on blocked rows (`background: color-mix(in srgb, var(--danger) 5%, var(--surface))`). Stale rows get the bar in `--warn` and no wash.
- **Result:** "Blocked, needs a decision" and "stale, probably abandoned" look different at a glance. The section still reads as one urgent group, and the page's only strong color sits exactly where it should.
- **Empty state:** keep the section, collapsed to its header only, with "All clear" in `--text-3` on the right and an `--ok` dot. The empty band confirms that nothing is waiting. Hiding it removes that confirmation.

### 3.6 Header, tabs and controls

Merge the header and the toolbar into one 48px bar that shares the content's max-width and edges:

```
 agent-registry  ● live · 3s    [ Live 4 | Archive 12 ]            Group: [Project | None]
```

- **Wordmark:** 13px, 600 weight, mono. Mono signals that this is a dev tool without any logo.
- **Freshness:** after the wordmark, a 6px `--ok` dot plus "updated 3s" in 11px `--text-3`. It turns `--warn` when a poll fails. This also makes the error banner less load-bearing.
- **Tabs:** a **segmented control** placed next to the wordmark, not in the far corner. The container is `background: var(--surface-2); border-radius: 6px; padding: 2px`. The segments have no border. The active segment is `background: var(--surface)`, `--text`, with `box-shadow: 0 0 0 1px var(--line-strong)`, and inactive segments are `--text-2`. Put counts in `--text-3`. No solid black fill.
- **Group by project:** a second small segmented control on the right ("Group: Project | None") with the same component. Delete the checkbox-in-a-box. Reusing one control style for every toggle makes the chrome read as a system.
- **Archive reason chips:** the same segmented control (`All | Unregister | Prune | Replace`), placed in the Archive section header on its right side. Don't put it in a floating toolbar.
- **Header surface:** `background: var(--bg)` with only a bottom `--line`. Don't use a white slab on a grey page. `position: sticky; top: 0`.

### 3.7 Layout width

- Set `max-width: 1080px`. Header and main share it, with `padding-inline: 24px`, so their left edges align.
- Stay with one column for v1. With rows at about 52px, density fixes the "wasted desktop" problem better than a grid of cards would. Keep the two-column idea parked.

## 4. Priority polish list

Order is by visual impact per unit of effort. Items 1 to 4 alone should move the board from "ugly" to "clean".

1. **Swap tokens and the palette (§3.1).** Replace the `:root` blocks with the cool-neutral set and the state colors. It's a pure CSS swap with no markup change, and it removes the beige and parchment feel immediately. It also puts `--danger`, `--warn`, `--ok` and `--idle` in place for the next items.
2. **Rebuild the card as a 3-column row (§3.3).** In `cardHtml()`, emit `.row > .dot + .body(.headline + .meta) + .age`. The summary becomes the headline, with the basename as a fallback. Collapse type, status, path and PR into one meta line. Move `session_id` into `title=""`. Add `data-status="{{status}}"` on the row so the CSS can color the dot and the status word through `[data-status=blocked] { --state: var(--danger) }` and so on. This is the single biggest change.
3. **Shorten paths and ages.** In JS, replace a leading `/Users/<name>` with `~` (the regex `^/Users/[^/]+` is enough). Skip the path when its basename equals the group key. Change `humanAge` output to `13m`, `7h`, `2d`, and put the full timestamp in `title`. Set the age to mono with `font-variant-numeric: tabular-nums`.
4. **Replace the attention band (§3.5).** Remove `.band.attention` background and border overrides. Add the header count pill, the per-row inset left bar through `--state`, and the 5% wash on blocked rows only.
5. **Consolidate sections and groups (§3.4).** Put the section header inside the surface with a count. Make group headers slim `--surface-2` rows with counts. Delete the group-title rule. Inset the row dividers. Result: about half as many lines, and each remaining line has a clear role.
6. **Merge header and toolbar; use a segmented control for everything (§3.6).** Write one `.seg` component and use it three times: tabs, group toggle, archive reasons. Delete the checkbox label. Place the tabs next to the wordmark. Align the header to the content width and make it sticky.
7. **Add a freshness indicator.** Put a dot plus "updated Ns" in the header, and update it on each successful poll and on a 1s tick. It's tiny, but a live board without a heartbeat looks dead. This also gives failure states a calm home, `--warn` dot and "stale 30s", before the red banner.
8. **Restyle the banner and empty states.** Make the banner a slim full-width strip under the header: `color-mix(--danger 10%)` background, a `--danger` left bar, 12px text, and the raw error behind a `title`. Empty states: "All clear" for attention, "No active sessions" for Active, and "Nothing archived for this filter" for Archive, all in `--text-3` inside the section surface.

The rough CSS delta is about 120 lines, replacing about 90. JS changes are limited to `cardHtml()`, the archive row template, `humanAge()`, one path helper and the freshness tick. Everything stays in the single file.

## 5. Non-goals: what not to do

- **No gradients, glow, glass or blur.** No purple anything. The only saturated pixels are the status colors.
- **No icon set, emoji or agent logos.** The agent type is a word. The status is a dot plus a word. If you ever want to distinguish agents visually, use a 2-letter mono tag (`CC`, `CU`, `CX`), not logos.
- **No card shadows, no big radii (keep it at 8px or less), no pill-shaped rows.** Rows are rows.
- **No webfonts.** System sans plus system mono. Offline localhost must render identically.
- **Don't color the whole section or the text by state.** Color lives in the dot, the status word, the left bar and the count pill. Tinted paragraphs are how you get the current parchment effect again.
- **No animation beyond a 120ms background transition on hover,** and optionally a one-time 600ms fade on a newly arrived attention row. No pulsing dots; a pulsing dot on an always-on board is noise.
- **Don't widen into a multi-column card grid for v1.** Density through rows first.
- **Don't add data to fill the space** (sparklines, charts, uptime). The board is a list of who needs you. Keep it that.
