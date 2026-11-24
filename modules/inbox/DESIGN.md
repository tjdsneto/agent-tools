---
name: Agent Inbox
description: A clean light inbox where AI agents ask one person questions and he answers them fast, on phone or desktop.
colors:
  bg: "#ffffff"
  ink: "#111827"
  mute: "#6b7280"
  surf: "#f3f4f6"
  line: "#e5e7eb"
  field: "#d1d5db"
  accent: "#2563eb"
  accent-press: "#1d4ed8"
  link: "#2563eb"
  on-accent: "#ffffff"
  blue-t: "#dbeafe"
  blue-i: "#1d4ed8"
  green-t: "#dcfce7"
  green-i: "#166534"
  green-d: "#16a34a"
  amber-t: "#fef3c7"
  amber-i: "#92400e"
  amber-d: "#d97706"
  red-t: "#fee2e2"
  red-i: "#991b1b"
  red-d: "#dc2626"
  grey-t: "#f3f4f6"
  grey-i: "#4b5563"
  me: "#dbeafe"
  code: "#ffffff"
  frame-bg: "#ffffff"
  bg-dark: "#111418"
  ink-dark: "#e5e7eb"
  mute-dark: "#9ca3af"
  surf-dark: "#1c2027"
  line-dark: "#2a2f37"
  field-dark: "#3d434d"
  link-dark: "#60a5fa"
  blue-t-dark: "#1e3a5f"
  blue-i-dark: "#bfdbfe"
  green-t-dark: "#14351f"
  green-i-dark: "#86efac"
  green-d-dark: "#22c55e"
  amber-t-dark: "#3a2a0a"
  amber-i-dark: "#fcd34d"
  amber-d-dark: "#f59e0b"
  red-t-dark: "#3b1414"
  red-i-dark: "#fca5a5"
  red-d-dark: "#ef4444"
  grey-t-dark: "#23272e"
  grey-i-dark: "#c3c8cf"
  me-dark: "#1e3a5f"
  code-dark: "#111418"
  av0-t: "#fde2e1"
  av0-i: "#9f1c1c"
  av1-t: "#feebc8"
  av1-i: "#8a4b08"
  av2-t: "#dcfce7"
  av2-i: "#166534"
  av3-t: "#dbeafe"
  av3-i: "#1d4ed8"
  av4-t: "#e0f2fe"
  av4-i: "#075985"
  av5-t: "#ccfbf1"
  av5-i: "#115e59"
  av6-t: "#fce7f3"
  av6-i: "#9d174d"
  av0-t-dark: "#4a1d1f"
  av0-i-dark: "#fecaca"
  av1-t-dark: "#45290d"
  av1-i-dark: "#fed7aa"
  av2-t-dark: "#14351f"
  av2-i-dark: "#bbf7d0"
  av3-t-dark: "#1e3a5f"
  av3-i-dark: "#bfdbfe"
  av4-t-dark: "#0c3448"
  av4-i-dark: "#bae6fd"
  av5-t-dark: "#0f3a36"
  av5-i-dark: "#99f6e4"
  av6-t-dark: "#46162f"
  av6-i-dark: "#fbcfe8"
typography:
  page-title:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"
    fontSize: "22px"
    fontWeight: 650
    lineHeight: 1.3
    letterSpacing: "-0.01em"
  page-title-wide:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"
    fontSize: "26px"
    fontWeight: 650
    lineHeight: 1.3
    letterSpacing: "-0.01em"
  bar-title:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"
    fontSize: "20px"
    fontWeight: 650
    lineHeight: 1.2
  heading:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"
    fontSize: "17px"
    fontWeight: 650
    lineHeight: 1.35
  body:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.5
  body-strong:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"
    fontSize: "16px"
    fontWeight: 600
    lineHeight: 1.5
  secondary:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
  tab:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"
    fontSize: "15px"
    fontWeight: 550
    lineHeight: 1.5
  meta:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"
    fontSize: "13px"
    fontWeight: 600
    lineHeight: 1
  caption:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.5
  mono-id:
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "13px"
    fontWeight: 400
  mono-code:
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "14px"
    fontWeight: 400
rounded:
  tail: "4px"
  control: "10px"
  panel: "12px"
  chip: "13px"
  bubble: "16px"
  tab: "18px"
  toast: "20px"
  round: "50%"
spacing:
  hair: "2px"
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "20px"
  2xl: "24px"
  3xl: "48px"
  gutter: "16px"
  column: "720px"
  bar: "56px"
  touch: "44px"
components:
  bar:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.ink}"
    typography: "{typography.bar-title}"
    height: "56px"
    padding: "0 16px"
  back-link:
    textColor: "{colors.link}"
    typography: "{typography.body-strong}"
    rounded: "{rounded.control}"
    height: "44px"
    padding: "0 10px"
  back-link-hover:
    backgroundColor: "{colors.surf}"
  count:
    textColor: "{colors.mute}"
    typography: "{typography.secondary}"
  tab:
    backgroundColor: "{colors.surf}"
    textColor: "{colors.ink}"
    typography: "{typography.tab}"
    rounded: "{rounded.tab}"
    height: "36px"
    padding: "0 14px"
  tab-hover:
    backgroundColor: "{colors.line}"
  tab-active:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.on-accent}"
  chip-grey:
    backgroundColor: "{colors.grey-t}"
    textColor: "{colors.grey-i}"
    typography: "{typography.label}"
    rounded: "{rounded.chip}"
    height: "26px"
    padding: "0 10px"
  chip-green:
    backgroundColor: "{colors.green-t}"
    textColor: "{colors.green-i}"
    typography: "{typography.label}"
    rounded: "{rounded.chip}"
    height: "26px"
    padding: "0 10px"
  chip-blue:
    backgroundColor: "{colors.blue-t}"
    textColor: "{colors.blue-i}"
    typography: "{typography.label}"
    rounded: "{rounded.chip}"
    height: "26px"
    padding: "0 10px"
  chip-amber:
    backgroundColor: "{colors.amber-t}"
    textColor: "{colors.amber-i}"
    typography: "{typography.label}"
    rounded: "{rounded.chip}"
    height: "26px"
    padding: "0 10px"
  chip-red:
    backgroundColor: "{colors.red-t}"
    textColor: "{colors.red-i}"
    typography: "{typography.label}"
    rounded: "{rounded.chip}"
    height: "26px"
    padding: "0 10px"
  chip-dot:
    size: "7px"
    rounded: "{rounded.round}"
  avatar:
    backgroundColor: "{colors.av3-t}"
    textColor: "{colors.av3-i}"
    rounded: "{rounded.round}"
    size: "40px"
  avatar-sm:
    rounded: "{rounded.round}"
    size: "28px"
  list-row:
    textColor: "{colors.ink}"
    typography: "{typography.body-strong}"
    height: "72px"
    padding: "12px 16px 12px 4px"
  list-row-hover:
    backgroundColor: "{colors.surf}"
  list-row-meta:
    textColor: "{colors.mute}"
    typography: "{typography.meta}"
  unread-dot:
    backgroundColor: "{colors.accent}"
    rounded: "{rounded.round}"
    size: "8px"
  option-row:
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    height: "52px"
    padding: "8px 0"
  option-recommended:
    textColor: "{colors.blue-i}"
    typography: "{typography.meta}"
  field:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    height: "48px"
    padding: "12px 14px"
  field-long:
    height: "112px"
  field-disabled:
    backgroundColor: "{colors.surf}"
    textColor: "{colors.mute}"
  select:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    height: "44px"
    padding: "0 12px"
  button:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.ink}"
    typography: "{typography.body-strong}"
    rounded: "{rounded.control}"
    height: "44px"
    padding: "0 16px"
  button-hover:
    backgroundColor: "{colors.surf}"
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.on-accent}"
    typography: "{typography.body-strong}"
    rounded: "{rounded.control}"
    height: "50px"
    width: "100%"
  button-primary-hover:
    backgroundColor: "{colors.accent-press}"
  button-danger:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.red-i}"
    rounded: "{rounded.control}"
    height: "44px"
    padding: "0 16px"
  notice-info:
    backgroundColor: "{colors.blue-t}"
    textColor: "{colors.blue-i}"
    rounded: "{rounded.panel}"
    padding: "12px 14px"
  notice-warn:
    backgroundColor: "{colors.amber-t}"
    textColor: "{colors.amber-i}"
    rounded: "{rounded.panel}"
    padding: "12px 14px"
  notice-error:
    backgroundColor: "{colors.red-t}"
    textColor: "{colors.red-i}"
    rounded: "{rounded.panel}"
    padding: "12px 14px"
  summary-panel:
    backgroundColor: "{colors.surf}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.panel}"
    padding: "14px 16px"
  answered-card:
    backgroundColor: "{colors.surf}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
    padding: "14px 16px"
  bubble-agent:
    backgroundColor: "{colors.surf}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.bubble}"
    padding: "8px 12px"
  bubble-me:
    backgroundColor: "{colors.me}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.bubble}"
    padding: "8px 12px"
  batch-actions:
    backgroundColor: "{colors.bg}"
    padding: "12px 16px"
  stale-toast:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.bg}"
    typography: "{typography.body}"
    rounded: "{rounded.toast}"
    padding: "10px 16px"
---

# Design System: Agent Inbox

## Overview

**Creative North Star: "The Clean Light Inbox"**

The inbox plays the category standard straight. It should read like Telegram's own screens, where its cards already land: a white ground, near-black ink, cool grey surfaces separated by hairlines, and a single blue that means "do this". Nothing in the system is themed; the craft lives in spacing, touch size, type weight and the small status signals that tell one person, at a glance, which agent asked and whether it can hear him.

Density is a phone list's density: 56px bar, 72px rows, 48-52px controls, one 720px column that never grows a second column on desktop. Hierarchy comes from size and weight inside one system font family, never from boxes. Content panels (summary, answered card, notices) are filled grey or tinted surfaces with no border; lists and option rows are separated by 1px hairlines. Dark mode follows the system and keeps every role; only the values change.

The build explicitly rejects the debug-page look it replaced: bordered boxes around every block, a pipe-joined id line, and default blue underlined links standing in for navigation. It also rejects any themed or "distinctive" world; the user chose the conventional inbox on 2026-11-24.

**Key Characteristics:**
- White ground, near-black ink, one action blue.
- Pale tint plus deep ink for every status colour, in pill chips.
- One system font family; monospace only for ids and code.
- Flat: hairlines and filled surfaces, a single shadow in the whole system.
- Every control at least 44px tall.

## Colors

A cool, nearly colourless neutral set carrying one blue for action, with four status hues that only ever appear as tint-and-ink pairs. Each light token has a dark counterpart (suffix `-dark`) that follows `prefers-color-scheme: dark`; the role never changes.

### Primary
- **Action Blue** (`accent`): the primary button, the active tab, checked radios and checkboxes, the focus ring, the caret and the unread dot. It is not redefined for dark mode; it sits on the dark ground unchanged.
- **Pressed Blue** (`accent-press`): the primary button's hover fill.
- **Link Blue** (`link` / `link-dark`): links and the "Inbox" back link. Identical to Action Blue in light; brightens in dark so text links stay legible on the near-black ground.

### Status tones
Each tone is a triplet: a pale tint (`-t`) for the chip or notice background, a deep ink (`-i`) for its text, and, for green, amber and red, a stronger dot colour (`-d`).
- **Live Green** (`green-t` / `green-i` / `green-d`): Live reachability, Delivered.
- **Resumable Blue** (`blue-t` / `blue-i`): Resumable, Needs answer, Answered, Unread, waiting to deliver or delivering, and the base (info) notice. Its ink also colours the "Recommended" tag on an option.
- **Held Amber** (`amber-t` / `amber-i` / `amber-d`): Held (out of tokens, with the time it becomes answerable) and the warn notice, including the urgent-and-waiting banner on the feed.
- **Unreachable Red** (`red-t` / `red-i` / `red-d`): Unreachable, Not delivered, Urgent, the error notice and the danger button's text.
- **Quiet Grey** (`grey-t` / `grey-i`): finished states (Read, Expired, Withdrawn, Superseded, Archived) and secondary text inside the answered card and bubble timestamps.

### Project avatars
Seven fixed tint-and-ink pairs (`av0` to `av6`: rose, orange, green, blue, sky, teal, pink), each with a dark counterpart. A project's tone is the sum of its name's bytes mod 7, so the same project always gets the same colour.

### Neutral
- **Paper White** (`bg` / `bg-dark` near-black): page ground, bar, fields, secondary buttons, the batch action tray.
- **Ink** (`ink` / `ink-dark`): all primary text; also the stale toast's fill.
- **Grey Meta** (`mute` / `mute-dark`): meta lines, the waiting count, row times, placeholders, disabled text.
- **Cool Surface** (`surf` / `surf-dark`): summary panel, answered card, agent bubble, unselected tabs, hover fills, inline code.
- **Hairline** (`line` / `line-dark`): the bar's bottom edge, row and option separators, section dividers, table cells, the frame border; also the tab hover fill.
- **Field Stroke** (`field` / `field-dark`): the 1px border of fields, selects and secondary buttons; the scrollbar thumb.
- **My Bubble** (`me` / `me-dark`): the person's own follow-up bubbles.
- **Code Inset** (`code` / `code-dark`): inline code inside the grey summary panel, so it reads against the panel instead of vanishing into it.
- **Frame White** (`frame-bg`): the sandboxed agent frame keeps a white background in both modes, because agent HTML assumes one.

### Named Rules
**The One Blue Rule.** Action Blue is the only colour that means "act". Status hues never fill a button, and no second accent exists.

**The Tint-and-Ink Rule.** A status colour always appears as a pale tint with a deep ink of the same hue. Never a saturated fill with white text, and never colour alone: every chip carries its word.

## Typography

**Body Font:** system-ui (with -apple-system, "Segoe UI", Roboto, sans-serif)
**Label/Mono Font:** ui-monospace (with SFMono-Regular, Menlo, monospace), for entry ids and code only

**Character:** The platform's own face at the platform's own sizes, so the page feels native on the phone and the Mac. Weight carries hierarchy in three steps above regular (550, 600, 650).

### Hierarchy
- **Page title** (650, 22px, 1.3, -0.01em; 26px from 760px up): the entry's question. Balanced wrapping.
- **Bar title** (650, 20px, 1.2): "Inbox" on the feed.
- **Heading** (650, 17px, 1.35): Markdown headings inside summary and detail; the answered value and the empty-state title use 17px too.
- **Body** (400, 16px, 1.5): everything readable. Markdown blocks cap at 68ch. Row titles, legends and buttons use the 600 weight of the same size.
- **Secondary** (400, 15px): the meta lines, the waiting count, the answered comment. Tabs use it at 550.
- **Meta** (400, 14px): row meta, option descriptions, the frame caption; "Recommended" at 600.
- **Label** (600, 13px, line-height 1): chips. Row times use 13px regular with tabular figures.
- **Caption** (400, 12px): bubble timestamps.
- **Mono id** (13px) and **mono code** (14px): entry ids and code.

### Named Rules
**The One Family Rule.** One system family for everything; hierarchy is size and weight. The only second face is monospace, and it is reserved for ids and code.

**The Tabular Clock Rule.** Numbers that stack or update in place (the waiting count, feed row times, bubble times) use tabular figures so they do not jitter.

## Layout

A single centred column, 720px wide, with a 16px gutter on every screen size; the bar's inner row shares the same width. The bar is 56px and sticky at the top. The main area pads 20px top and 48px bottom. Vertical rhythm is built from 4, 8, 12, 16, 20 and 24px steps: 8px between chips and tabs, 12px under the title, 16px under the chip line, 20px between content blocks, 24px above the conversation and follow-up sections.

The feed list bleeds to the screen edges on a phone (the 16px gutter is cancelled) and gains a top hairline and stays inside the column from 760px up. Feed rows are a three-area grid: avatar on the left spanning, title and time on top, meta below, chips below that. From 760px the chips move up beside the meta and align right, the title holds one line with an ellipsis, and the id appears in the meta line; below 760px the title clamps to two lines and the id is hidden. The tabs scroll sideways at narrow widths rather than wrapping.

When any feed row is selected, a batch tray (Withdraw, Dismiss) appears sticky at the bottom, above the safe-area inset, with a top hairline.

### Named Rules
**The 44px Floor Rule.** Every interactive target is at least 44px tall. Where the visual is smaller (36px tabs, the 18px row checkbox), an invisible hit area makes up the difference.

**The One Column Rule.** The feed is one 720px column at every width. Entry pages are too, up to 1099px; from 1100px they add the feed as a pane beside the entry (see Entry pane). Nothing else gets a second column.

## Elevation & Depth

The system is flat. Depth comes from tonal layering (white ground, grey surface panels) and 1px hairlines, not shadows. The one shadow belongs to the stale-page toast, the only element that floats above the page.

### Shadow Vocabulary
- **Toast lift** (`box-shadow: 0 4px 16px rgba(0,0,0,.18)`): the stale-page toast only.

### Named Rules
**The Flat Inbox Rule.** Nothing at rest casts a shadow. A shadow means "this floats over the page and will go away".

## Shapes

Softly rounded rectangles for anything you type into or press (10px), slightly softer panels (12px), and true pills for chips (13px on a 26px height), tabs (18px on 36px) and the toast (20px). Avatars and dots are circles. Chat bubbles round at 16px with the corner nearest their sender pinched to 4px, the Telegram tail. Borders are 1px only: field stroke on controls, hairline on separators and the frame. Panels never carry a border.

**The Hairline-Not-Box Rule.** Lists and option rows separate with a single 1px hairline under each item; they are never wrapped in a bordered card.

## Components

### Bar
- **Character:** a quiet header that names where you are and how much is waiting.
- **Style:** Paper White, sticky, 56px, bottom hairline. Left is "Inbox" (bar title) on the feed, or the back link on an entry; right is "N waiting" in Grey Meta, hidden at zero.
- **Back link:** a chevron SVG plus "Inbox" in Link Blue, 550 weight, 44px tall, 10px radius; it fills with Cool Surface on hover. The negative left margin lines the chevron up with the column edge.

### Tabs
- **Style:** pills on Cool Surface, ink text, 15px/550, 36px tall with a 44px hit area.
- **State:** hover fills with Hairline grey; the current view is Action Blue with white text. Views are Active (the default: everything not yet done; answered questions and read reports leave it), Needs answer, Info, History (answered, delivered, read and closed entries).
- **Filters:** below the tabs, engine and state selects (44px, 10px radius, field stroke) and a secondary Filter button, wrapping on narrow screens.

### Chips
- **Style:** 26px pills, 13px/600, 10px side padding, tint background and ink text per tone.
- **Tones:** green Live, and Answered once delivered; blue Resumable / Needs answer / Unread, and Answered while sending; amber Held; red Unreachable / Answered, not delivered / Urgent; grey finished states.
- **Answered:** an answered question's chip carries delivery ticks in place of the dot: one tick while sending (blue), two once the session has it (green).
- **Dot:** a 7px dot in the tone's `-d` colour precedes the label on green, amber and red chips that report a state. Blue and grey chips, and the Urgent label, carry no dot.
- **The Dot Means State Rule.** The dot marks a session's or a delivery's live state. A label that is not a state (Urgent) never gets one.

### Avatars
- **Style:** a circle with the project's initial, 40px (16px/650) in feed rows, 28px (13px) in the entry's meta line, in the project's fixed tint-and-ink pair. Decorative: hidden from assistive tech, because the meta line names the project.

### Feed rows
- **Style:** a 44px checkbox column, then the row: avatar, 600-weight title, right-aligned 13px time, a 14px Grey Meta line "project · engine · You: <answer> · id" (the answer part only once answered, like a chat preview), and the chips. 72px minimum, hairline below.
- **States:** hover fills with Cool Surface. An unread post shows an 8px Action Blue dot before the title. Order is open questions, then unread posts, then the rest.
- **Empty:** centred Grey Meta text under a 17px ink "Nothing here".

### Entry header
- Title, then the meta line (small avatar plus "project · engine · time · ago"), then a chip line (Urgent if any, the state chip, then "priority · id" in Grey Meta with the id in mono), then the summary in a Cool Surface panel (12px radius, 14px 16px padding).

### Option rows
- **Style:** 52px rows of a 20px radio or checkbox (Action Blue when checked), the label, an optional 14px description under it, and an optional "Recommended" tag right-aligned in Resumable Blue ink at 600. Hairline between rows, none after the last.
- **Disabled:** when the session is held or unreachable the whole fieldset disables: option text and the legend turn Grey Meta, the cursor says not-allowed, and the primary button drops to 45% opacity. A warn or error notice above the form says why.

### Fields
- **Style:** 48px minimum, 12px 14px padding, 1px field stroke, 10px radius, Paper White fill, Grey Meta placeholder. Long text answers are 112px textareas resizable vertically.
- **Focus:** a 2px Action Blue outline drawn inside the edge (offset -1px) and the border turns blue. Everything else focuses with a 2px Action Blue outline offset 2px.
- **Disabled:** Cool Surface fill, Grey Meta text.

### Buttons
- **Shape:** gently rounded (10px).
- **Primary:** full-width, 50px, Action Blue with white 600 text, no border; Pressed Blue on hover. "Send answer", or "Approve" beside a secondary "Revise" in a two-up pair.
- **Secondary:** 44px, Paper White with the field stroke, 600 ink text, Cool Surface on hover.
- **Danger:** the secondary button with Unreachable Red ink (Withdraw).
- **Press:** every button nudges down 1px while pressed, except under reduced motion.
- **Disabled:** 45% opacity, not-allowed cursor, no press nudge.

### Notices
- **Style:** 12px radius, 12px 14px padding, tint background with ink text. Warn is amber (held session, urgent-and-waiting banner); error is red (unreachable session; a failed action, with `role="alert"`). The base style is a blue info notice, but no page emits one today. A link inside inherits the notice ink at 600.

### Answered card
- **Character:** the receipt that closes the loop.
- **Style:** a Cool Surface panel: a 14px "Your answer" heading in Quiet Grey ink, the chosen value at 17px, the optional comment in 15px grey, then the delivery mark and "From Telegram · 06:20". The mark is a single tick with "Sent, waiting to deliver" (or "Delivering to the session") in Quiet Grey 600, two ticks with "Delivered to the session" in Live Green ink, or a red chip with a dot when not delivered.
- **Landing:** when a sent answer becomes delivered while the page is open, the second tick draws in (420ms, ease-out) and the card fades from Live Green tint back to Cool Surface (1.4s). The page remembers the last mark it showed per entry in sessionStorage, so a plain reload never replays it. Off under reduced motion.

### Conversation bubbles
- **Style:** up to 85% wide, 8px 12px padding, 16px radius with a 4px tail corner. The agent's replies sit left on Cool Surface; the person's follow-ups sit right on My Bubble blue. A 12px tabular timestamp sits right-aligned under the text, Quiet Grey ink for the agent, Resumable Blue ink for the person. The person's bubbles end with delivery ticks after the time: one while the follow-up waits, two once the session has it (its seq is at or below the entry's delivered_seq).
- **Follow up:** below the thread, a one-line textarea and a secondary "Send" button side by side, both 48px.

### Delivery ticks
- **Character:** Telegram's grammar for "it reached them".
- **Style:** a drawn SVG, 17x16 (15x14 in bubbles), 1.8px round stroke in the surrounding ink. One check means sent; two overlapping checks mean the session has it. Labelled "Sent" or "Delivered" for assistive tech. Never an emoji or a text glyph.

### Entry pane
- **Where:** entry pages from 1100px. The bar's inner row widens to 1240px; under it, a 380px pane holds the feed rows and the entry fills the rest (24px 40px padding, 760px max).
- **Style:** the pane is sticky under the bar, scrolls on its own, and has a right hairline. Its rows are feed rows without the checkbox, the title clamped to two lines, chips under the meta, no id. The current entry's row is marked `aria-current` with a Hairline grey fill, neutral so every chip tone stays readable on it. Batch actions stay on the feed.

### Agent frame
- A full-width sandboxed iframe, 280px minimum, hairline border, 12px radius, always white inside, captioned "Reference only. Answer below." in 14px Grey Meta.

### Stale-page toast
- **Character:** the signature interaction. The page reloads itself on every store change, unless the person has typed into any field; then it offers the reload instead of wiping the answer.
- **Style:** fixed, centred 20px above the bottom, an Ink pill (20px radius, 10px 16px padding) with Paper White text, the Toast lift shadow, and an underlined 650 "Reload" link. Announced as a status.

## Do's and Don'ts

### Do:
- **Do** use Action Blue for every action and selection, and for nothing else.
- **Do** pair every status hue as tint plus ink, with its word in the chip; add the dot only for a reported state.
- **Do** give each project its fixed avatar tone from the byte-sum rule, so the same project is always the same colour.
- **Do** keep every control at least 44px tall, extending small visuals with an invisible hit area.
- **Do** separate list items with a 1px hairline and group content in filled Cool Surface panels at 12px radius.
- **Do** decide every new colour token's dark value (or, like Action Blue, decide it stays), keeping its role.

### Don't:
- **Don't** wrap blocks in bordered boxes, join ids and meta with pipes, or use default blue underlined links as navigation; that is the debug-page look this build replaced.
- **Don't** introduce a themed world, a display face or a second accent colour.
- **Don't** add shadows to anything that rests on the page; the toast is the only floating element.
- **Don't** fill a chip or button with a saturated status colour and white text.
- **Don't** reload the page over a half-typed answer; offer the reload toast instead.
