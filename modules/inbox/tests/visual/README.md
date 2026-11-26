# Visual check: feed, entry page and Topics

Screenshots of the inbox's feed (in each Group by mode), its entry page and its Topics tab, at phone width (390px) and desktop width (1280px), in light and dark. The unit tests assert the HTML; this check is how you see the layout: the context line, the grouped sections, the breadcrumb, "On this topic", the filter panel and the topic outline.

It is not a test and pytest doesn't collect it. A green run only proves each page rendered at the size and colour scheme asked for, with no sideways scroll. You still have to open every PNG and look.

## Files

| File | What it does |
|---|---|
| `seed_topics.py` | Drops and recreates the tables in a test DB and fills them with ten topic-aware entries, then prints `{title: id}` as JSON. It refuses any DSN that doesn't name `agent_inbox_test`. |
| `seed_registry.py` | Writes a scratch agent registry (topic logs, `registry.json`, `archive.jsonl`) into the runner's temp dir for the Topics shots, with notes that link to the seeded entries. It refuses the live registry directory. |
| `shots.sh` | The runner: seed the DB and a scratch registry, start a web-only server on the port you give it, take the nineteen shots, stop the server. |
| `cdpshot.mjs` | One screenshot through the Chrome DevTools Protocol at an exact viewport and colour scheme. |

## Running it

You need Google Chrome in `/Applications` (or set `CHROME` to its binary), Node 22 or newer, and the module's `.venv`. Use a scratch test DB of your own, not the shared `agent_inbox_test`, because the seed drops its tables and another checkout may be running tests on it.

```bash
createdb -h localhost -p 5433 agent_inbox_test_visual
cd modules/inbox
AGENT_INBOX_DSN="host=localhost port=5433 dbname=agent_inbox_test_visual" tests/visual/shots.sh tmp/shots 8897
dropdb -h localhost -p 5433 agent_inbox_test_visual
```

The runner refuses ports 8797 and 8798 (the live inbox), a port that is already in use, the live `agent_inbox` DB, and any DB whose name doesn't contain `agent_inbox_test`. It starts only the web handler, not `agt inbox serve`, because the full service also sweeps, which wakes sessions. It never touches the live agent registry. The feed's topic paths are written into the DB directly. The Topics page reads a scratch registry that `seed_registry.py` writes in the runner's temp dir, through this checkout's `agt` (`AGENT_INBOX_AGT`). `PROBE` runs before the page is measured, so a probe that opens branches is measured and checked at the opened size.

Each shot prints one line with what the page measured: `w` (viewport width), `sw` (page scroll width), `h` (page height) and `dark`. A shot whose width, scroll width or scheme is wrong prints `FAIL`, and the runner exits non-zero. At phone widths, content that is too wide shows up as a wider viewport (`viewport is 600px, not 390px`), because a mobile browser zooms out to fit the page rather than scrolling sideways. The two filter-panel shots also print the height of each select.

## Why it drives Chrome over CDP

The obvious command, `chrome --headless=new --window-size=390,1400 --screenshot=…`, gives wrong pictures on macOS:

- Chrome won't make a window narrower than 500px. A 390px request lays the page out at 500px and crops the PNG to 390, so the page looks as if it runs off the right edge.
- `--virtual-time-budget` hangs on these pages and never writes the PNG.
- `--force-dark-mode` doesn't flip `prefers-color-scheme`. Headless Chrome follows the Mac's own appearance, so on a Mac in dark mode every shot is dark, including the ones meant to be light.

`cdpshot.mjs` launches a throwaway headless Chrome with a fresh profile (so it never attaches to the browser you are using) and connects to its debugging port. It then emulates the exact viewport (`Emulation.setDeviceMetricsOverride`, as a mobile device below 600px) and the colour scheme (`Emulation.setEmulatedMedia`), loads the page, and checks `innerWidth`, the scroll width and `matchMedia('(prefers-color-scheme: dark)')` before capturing the full page height. `PROBE=<js>` evaluates an expression after load and prints its result; the runner uses it to open the filter panel.

## What to look for

Open each PNG and check it against its line. Write down what you saw; don't tick a line you didn't look at.

| Shot | Check |
|---|---|
| `feed-none-390` | Rows with a topic path have a small muted context line above the title. The four-node row reads `… › Manual check: t… › Check window targeting`: the middle name is cut, never the topic. The Lindris row shows the literal text `<img src=x onerror="alert(1)">`. The backup and am-videos rows have no context line. Nothing runs past the right edge. |
| `feed-intent-390` | One-line section headings, ellipsized when long. The first section holds an open question, and "No topic" is last. Each heading names the project after the intent (a long intent can hide it behind the ellipsis). Rows inside look like the ungrouped rows. |
| `feed-tree-390` | "Topic awareness for AI sessions" holds its own rows, then an indented "Manual check…" sub-heading with the fork's rows under it. |
| `feed-none-1280`, `feed-intent-1280`, `feed-tree-1280` | The context line sits over the title and shows the full names. The time stays on the title's line, and chips stay right-aligned on the meta line. |
| `entry-390` | The breadcrumb wraps onto several lines with `›` separators, above the title. "On this topic" closes the page; each line has a title, a state chip and an age, and is tall enough to tap. |
| `entry-1280` | The left pane's rows keep their layout, and their context lines cut the middle name, not the topic. The breadcrumb and "On this topic" sit in the main column. |
| `feed-tree-390-dark`, `entry-390-dark` | Dark background, and muted text (context lines, headings, meta) is still readable. |
| `filter-open-390-light`, `filter-open-390-dark` | The filter panel is open and fits inside the viewport. Its Intent and Group by selects show, and each select measures 44px (printed in the PROBE line). |
| `topics-390`, `topics-1280` | Tabs end with Topics, current; at 390 the PROBE line says it ends inside the viewport. "Topic awareness for AI sessions" comes first with a green Live chip, a blue "2 to answer" and "agent-tools · claude · 3 open topics · 2 questions waiting"; then "Lindris production page…" (grey Idle, "1 fork not picked up", and its amber "Not picked up" fork inside); then the literal `<img src=x onerror="alert(1)">` intent with "1 parked". The open branches show timelines on a grey rail and the nested fork indented. "Show finished (4)" closes the list. Rows are at least 48px; nothing runs past the right edge. |
| `topics-390-dark`, `topics-1280-dark` | Same layout on the dark ground; muted meta, the rail and the chips stay readable. |
| `topics-open-390`, `topics-open-1280`, `topics-open-390-dark` | Every branch open. "Retry the Herdr pane split" shows `↳ 4` and "Read the pane ids…" `↳ 5`, at the same indent as level 3. Timeline lines for entries are 44px links in link blue. Each idle or ended session shows its resume command in a grey mono box that scrolls inside itself, not the page. "Inbox restyle" and the three older intents come last (opened too, by the probe), with "Hide finished" under them. |
