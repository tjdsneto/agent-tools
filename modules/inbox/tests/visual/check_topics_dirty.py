"""Headless-Chrome check that the Topics page isn't "touched" until a branch is clicked.

    PYTHONPATH=src:tests .venv/bin/python tests/visual/check_topics_dirty.py

Renders the page with open branches to a temp file and loads it through cdpshot.mjs. After load
with no interaction the page's dirty flag must be false; after a click on a summary, true.
Needs node 22+ and Chrome. No server and no database."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from topic_tree_helpers import ev, node, sess

from agent_inbox import topic_graph, web

HERE = Path(__file__).parent
child = node("tp-c", "Child", sessions=[sess("s", role="topic")], events=[ev("topic", 5), ev("asked", 4, entry="ib-1", title="Q")])
root = node("tp-r", "Root", sessions=[sess("s", state="live")], events=[ev("intent", 9)], children=[child])
page = web._topics_page(topic_graph.build(topic_graph.clean({"tree": [root]}), {}), False, 1)
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "topics.html"
    path.write_text(page)
    probe = "(() => { const before = dirty, open = document.querySelectorAll('.tree details[open]').length; document.querySelector('.tree summary').click(); return {open, before, after: dirty}; })()"
    out = subprocess.run(
        ["node", str(HERE / "cdpshot.mjs"), str(Path(tmp) / "x.png"), path.as_uri(), "390", "844", "light"],
        env={**os.environ, "PROBE": probe, "NOSHOT": "1"}, capture_output=True, text=True, timeout=60,
    )
print(out.stdout, out.stderr)
line = next(l for l in out.stdout.splitlines() if l.startswith("PROBE"))
result = json.loads(line[len("PROBE "):])
ok = result["open"] >= 2 and result["before"] is False and result["after"] is True
print("OK" if ok else "FAIL", result)
sys.exit(0 if ok else 1)
