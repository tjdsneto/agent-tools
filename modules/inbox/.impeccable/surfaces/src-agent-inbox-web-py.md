---
version: 1
slug: "src-agent-inbox-web-py"
primary_target: "src/agent_inbox/web.py"
related_targets: []
---

# Surface: inbox web pages (feed and entry)

Scope: `src/agent_inbox/web.py`, the feed (`/`) and the entry page (`/e/<id>`). Mode: Operate. Phone and desktop used about equally; the phone lands on one entry from a Telegram link.

Audience and job: one person answering agent questions fast, then reading reports and triaging the feed. Constraints: server-rendered Python, inline CSS, a few lines of JS, forms work without JS, nothing loaded from the internet, agent HTML stays in the sandboxed frame, 44px touch targets.

## Direction contract

THESIS: The category standard, played straight: a clean light inbox that reads like Telegram's own screens. It refuses themed worlds and the debug-page look of the current build (bordered boxes, a pipe-joined id line, default blue links).

OWN-WORLD: White ground, near-black ink #111827, grey meta #6b7280, cool grey surfaces #f3f4f6 and hairlines #e5e7eb, one blue #2563eb for actions, links and selection. System font stack, one family. Soft 10-12px radii, pill status chips (green live, blue resumable, amber held, red unreachable), round initial avatars per engine. Dark mode follows the system with the same roles.

STORY: He sees what is asked, which agent asked and whether it can hear him, picks an answer and sends it in one move; afterwards the page says it was sent and delivered.

FIRST VIEWPORT: Entry on a 390px phone: a 56px bar with "← Inbox" on the left and the waiting count on the right; the title at 22px semibold; an avatar plus "project · engine · time" line; a status chip plus priority and id; the summary in a grey rounded panel; "Your answer" options as 48px hairline rows with Recommended in blue; a comment field; a full-width blue Send answer at the bottom of the first screen. Feed: the same bar, filter chips, then rows (avatar, title, meta line, status chip) with open questions first.

FORM: canon (the standing exit, chosen by the user over re-roll round 1); seed: seed:1f5d34aae5095768. Signature interaction: status chips that tell the session's reachability at a glance, and the reload that keeps a typed answer instead of wiping it.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
