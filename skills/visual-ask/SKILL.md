---
name: visual-ask
description: Use when asking Tiago a complicated question, comparison, or approval that is easier to judge by seeing it — architecture, layout, mockups, or a design to accept. Also use when he asks to see options in HTML or in the browser.
user-invocable: true
---

# Visual ask

Put the question on a local HTML page and open that page in the browser he is already using. Chat still gets one or two sentences and the URL. His reply in chat is the answer.

## When

Use this for a judgment that has structure: an architecture, a layout, a side-by-side, two to four real options, or approval of a design section.

Skip it for a simple fact, a one-line choice, or anything already settled. One question per page.

## Loop

1. Session directory: `<project>/.visual-questions/<pid>-<unix-seconds>/` with `content/` and `state/` inside it. If the project has a `.gitignore` and `.visual-questions/` is missing from it, append that line. Do not commit the session.
2. Reuse a live server when `state/server-info` exists and `curl` to its `url` returns 200. Otherwise start one and leave it running:

```bash
node <this-skill>/scripts/server.mjs --session <session-dir>
```

Run it in a persistent terminal. Wait until stdout prints one JSON line (`url`, `screen_dir`, `state_dir`). The process stays up until that terminal dies. A URL from an earlier turn is dead until `curl` says otherwise.
3. Write a **fragment** (no `<html>` or `<!DOCTYPE`) to a **new** file in `screen_dir`. Never reuse a filename. Use the Write tool, not a shell heredoc.
4. `curl` the URL and confirm the response contains the page title. Then open it:
   - **Cursor:** IDE browser `browser_navigate` with `position: "active"` so the panel is revealed. If the snapshot is `about:blank` or empty, navigate that view again and snapshot. Do not tell him it is open until the snapshot shows the page.
   - **Anywhere else on macOS:** `open <url>`.
5. In chat: where the tab is, the URL, and the decision in a sentence or two. Stop. Do not ask him to go find the page.
6. On his next message, read `state/events` if it exists (one JSON object per line). The last `choice` is the click. Chat text wins when they disagree.

A new file in `content/` reloads the open page within about a second. Serving a new file clears `events`.

## Page

The server wraps the fragment. Use a sentence as the title, not a label like "Question 3".

```html
<h2>Which split should the app use?</h2>
<p class="subtitle">The window and the menu bar share one snapshot.</p>

<div class="options">
  <div class="option" data-choice="a" onclick="toggleSelect(this)">
    <div class="letter">A</div>
    <div class="content">
      <h3>Tauri plus tray api</h3>
      <p>Go keeps the tray behavior. The app is the window and the menu bar.</p>
    </div>
  </div>
  <div class="option" data-choice="b" onclick="toggleSelect(this)">
    <div class="letter">B</div>
    <div class="content">
      <h3>Change it</h3>
      <p>Say what to move in the chat.</p>
    </div>
  </div>
</div>
```

Two to four options. Add `data-multiselect` on `.options` only when several can be true. For a picture, use `.mockup`, `.cards`, `.split`, `.label`.

An approval page shows the thing being approved, then two options: `data-choice="approve"` and `data-choice="revise"`.
