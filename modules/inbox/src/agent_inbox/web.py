from __future__ import annotations

import html
import os
import re
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse
from zoneinfo import ZoneInfo

from markdown_it import MarkdownIt
from psycopg.types.json import Jsonb

from agent_inbox import db, grouping, store
from agent_inbox.constants import FRAME_PORT, HTTP_PORT, NOTIFY_CHANNEL
from agent_inbox.errors import ConflictError, NotFoundError, StoreError, ValidationError

HISTORY_STATES = ("answered", "delivered", "read", "expired", "withdrawn", "superseded", "undelivered", "archived")
# Answered questions and read reports are done from the visitor's side; the
# default view leaves them to History.
DONE_STATES = {"answered", "delivered", "read"}
HIDDEN_STATES = {"archived", "withdrawn", "superseded"}
FRAME_ORIGIN = f"http://127.0.0.1:{FRAME_PORT}"
GROUP_LABELS = (("none", "None"), ("intent", "Intent"), ("tree", "Topic tree"))
GROUP_COOKIE = "ib_group"
GROUP_MAX_AGE = 365 * 24 * 3600

_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{title}</title>
<style>
:root {{
  --bg: #ffffff; --ink: #111827; --mute: #6b7280; --surf: #f3f4f6; --line: #e5e7eb; --field: #d1d5db;
  --accent: #2563eb; --accent-press: #1d4ed8; --link: #2563eb;
  --blue-t: #dbeafe; --blue-i: #1d4ed8; --green-t: #dcfce7; --green-i: #166534; --green-d: #16a34a;
  --amber-t: #fef3c7; --amber-i: #92400e; --amber-d: #d97706; --red-t: #fee2e2; --red-i: #991b1b; --red-d: #dc2626;
  --grey-t: #f3f4f6; --grey-i: #4b5563; --me: #dbeafe; --code: #ffffff; --pop: #ffffff;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #111418; --ink: #e5e7eb; --mute: #9ca3af; --surf: #1c2027; --line: #2a2f37; --field: #3d434d;
    --link: #60a5fa;
    --blue-t: #1e3a5f; --blue-i: #bfdbfe; --green-t: #14351f; --green-i: #86efac; --green-d: #22c55e;
    --amber-t: #3a2a0a; --amber-i: #fcd34d; --amber-d: #f59e0b; --red-t: #3b1414; --red-i: #fca5a5; --red-d: #ef4444;
    --grey-t: #23272e; --grey-i: #c3c8cf; --me: #1e3a5f; --code: #111418; --pop: #1c2027;
  }}
}}
* {{ box-sizing: border-box; }}
html {{ -webkit-text-size-adjust: 100%; scrollbar-color: var(--field) transparent; }}
body {{ margin: 0; background: var(--bg); color: var(--ink); font: 16px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  -webkit-font-smoothing: antialiased; overflow-wrap: anywhere; }}
::selection {{ background: var(--blue-t); color: var(--ink); }}
a {{ color: var(--link); text-underline-offset: 2px; }}
:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
input, textarea, select, button {{ font: inherit; color: inherit; caret-color: var(--accent); }}
.bar {{ position: sticky; top: 0; z-index: 2; background: var(--bg); border-bottom: 1px solid var(--line); }}
.bar-in {{ max-width: 720px; margin: 0 auto; height: 56px; display: flex; align-items: center; justify-content: space-between; padding: 0 16px; }}
.bar h1 {{ margin: 0; font-size: 20px; line-height: 1.2; font-weight: 650; }}
.back {{ display: inline-flex; align-items: center; gap: 4px; min-height: 44px; margin-left: -10px; padding: 0 10px;
  border-radius: 10px; font-weight: 550; text-decoration: none; }}
.back svg {{ width: 20px; height: 20px; }}
.back:hover {{ background: var(--surf); }}
.count {{ color: var(--mute); font-size: 15px; font-variant-numeric: tabular-nums; }}
main {{ max-width: 720px; margin: 0 auto; padding: 20px 16px 48px; }}
.notice {{ margin: 0 0 16px; padding: 12px 14px; border-radius: 12px; background: var(--blue-t); color: var(--blue-i); }}
.notice.err {{ background: var(--red-t); color: var(--red-i); }}
.notice.warn {{ background: var(--amber-t); color: var(--amber-i); }}
.notice a {{ color: inherit; font-weight: 600; }}
.chip {{ display: inline-flex; align-items: center; gap: 6px; min-height: 26px; padding: 0 10px; border-radius: 13px;
  font-size: 13px; font-weight: 600; line-height: 1; white-space: nowrap; background: var(--grey-t); color: var(--grey-i); }}
.chip i {{ width: 7px; height: 7px; border-radius: 50%; background: currentColor; }}
.chip.green {{ background: var(--green-t); color: var(--green-i); }} .chip.green i {{ background: var(--green-d); }}
.chip.blue {{ background: var(--blue-t); color: var(--blue-i); }}
.chip.amber {{ background: var(--amber-t); color: var(--amber-i); }} .chip.amber i {{ background: var(--amber-d); }}
.chip.red {{ background: var(--red-t); color: var(--red-i); }} .chip.red i {{ background: var(--red-d); }}
.chip .ticks {{ width: 15px; height: 14px; margin-left: -2px; }}
.av {{ flex: none; display: grid; place-items: center; width: 40px; height: 40px; border-radius: 50%; font-size: 16px; font-weight: 650; }}
.av {{ position: relative; }}
.kb {{ position: absolute; right: -3px; bottom: -3px; display: grid; place-items: center; width: 18px; height: 18px; border-radius: 50%;
  box-shadow: 0 0 0 2px var(--bg); }}
.kb svg {{ width: 12px; height: 12px; }}
.kb.q {{ background: var(--accent); color: #fff; }}
.kb.r {{ background: var(--grey-i); color: var(--bg); }}
.row:hover .kb {{ box-shadow: 0 0 0 2px var(--surf); }}
.av.sm {{ width: 28px; height: 28px; font-size: 13px; }}
.av0 {{ background: #fde2e1; color: #9f1c1c; }} .av1 {{ background: #feebc8; color: #8a4b08; }} .av2 {{ background: #dcfce7; color: #166534; }}
.av3 {{ background: #dbeafe; color: #1d4ed8; }} .av4 {{ background: #e0f2fe; color: #075985; }} .av5 {{ background: #ccfbf1; color: #115e59; }}
.av6 {{ background: #fce7f3; color: #9d174d; }}
@media (prefers-color-scheme: dark) {{
  .av0 {{ background: #4a1d1f; color: #fecaca; }} .av1 {{ background: #45290d; color: #fed7aa; }} .av2 {{ background: #14351f; color: #bbf7d0; }}
  .av3 {{ background: #1e3a5f; color: #bfdbfe; }} .av4 {{ background: #0c3448; color: #bae6fd; }} .av5 {{ background: #0f3a36; color: #99f6e4; }}
  .av6 {{ background: #46162f; color: #fbcfe8; }}
}}
.id {{ font: 13px ui-monospace, SFMono-Regular, Menlo, monospace; }}
.tabs {{ display: flex; gap: 8px; overflow-x: auto; margin: 0 -16px 12px; padding: 0 16px; scrollbar-width: none; }}
.tabs a {{ flex: none; display: inline-flex; align-items: center; min-height: 36px; padding: 0 14px; border-radius: 18px;
  background: var(--surf); color: var(--ink); font-size: 15px; font-weight: 550; text-decoration: none; }}
.tabs a:hover {{ background: var(--line); }}
.tabs a[aria-current="page"] {{ background: var(--accent); color: #fff; }}
.tabs a {{ position: relative; }}
.tabs a::after {{ content: ""; position: absolute; inset: -4px 0; }}
.tabs {{ padding-block: 4px; margin-top: -4px; mask-image: linear-gradient(to left, transparent, #000 16px);
  -webkit-mask-image: linear-gradient(to left, transparent, #000 16px); }}
.tabs .sm {{ display: none; }}
@media (max-width: 479px) {{ .tabs {{ gap: 6px; }} .tabs a {{ padding: 0 12px; }} .tabs .lg {{ display: none; }} .tabs .sm {{ display: inline; }} }}
@media (max-width: 379px) {{ .tabs a {{ padding: 0 9px; }} }}
.tools {{ display: flex; align-items: center; gap: 12px; }}
.step {{ position: relative; display: inline-flex; align-items: center; gap: 2px; height: 36px; padding: 0 10px 0 14px; border-radius: 18px;
  background: var(--surf); color: var(--ink); font-size: 15px; font-weight: 600; text-decoration: none; }}
.step::after {{ content: ""; position: absolute; inset: -4px 0; }}
.step svg {{ width: 18px; height: 18px; }}
a.step:hover {{ background: var(--line); }}
a.step:active {{ transform: translateY(1px); }}
.filt {{ position: relative; flex: none; }}
.filt summary {{ position: relative; display: grid; place-items: center; width: 44px; height: 36px; border-radius: 18px;
  background: var(--surf); list-style: none; cursor: pointer; }}
.filt summary::-webkit-details-marker {{ display: none; }}
.filt summary::after {{ content: ""; position: absolute; inset: -4px 0; }}
.filt summary:hover, .filt[open] summary {{ background: var(--line); }}
.filt.on summary {{ background: var(--blue-t); color: var(--blue-i); }}
.filt summary svg {{ width: 18px; height: 18px; }}
.filt summary b {{ position: absolute; top: -5px; right: -5px; display: grid; place-items: center; min-width: 20px; height: 20px; padding: 0 5px;
  border: 2px solid var(--bg); border-radius: 10px; background: var(--accent); color: #fff; font-size: 11px; font-weight: 700; line-height: 1; }}
.filt form {{ position: absolute; top: calc(100% + 8px); right: 0; z-index: 3; display: grid; gap: 14px; width: min(300px, calc(100vw - 32px));
  padding: 16px; border-radius: 14px; background: var(--pop); box-shadow: 0 10px 30px rgb(0 0 0 / .16), 0 2px 6px rgb(0 0 0 / .08); }}
.filt label {{ display: grid; gap: 6px; color: var(--mute); font-size: 13px; font-weight: 600; }}
.filt select {{ width: 100%; color: var(--ink); font-size: 16px; font-weight: 400; }}
.filt .pair .btn {{ min-height: 44px; color: var(--ink); }}
.js .filt .go {{ display: none; }}
.js .filt .pair:not(:has(a)) {{ display: none; }}
select {{ min-height: 44px; padding: 0 12px; border: 1px solid var(--field); border-radius: 10px; background: var(--bg); }}
.btn {{ display: inline-flex; align-items: center; justify-content: center; min-height: 44px; padding: 0 16px; border-radius: 10px;
  border: 1px solid var(--field); background: var(--bg); font-weight: 600; cursor: pointer; text-decoration: none; }}
.btn:hover {{ background: var(--surf); }}
.btn:active {{ transform: translateY(1px); }}
.btn.primary {{ width: 100%; min-height: 50px; border: 0; background: var(--accent); color: #fff; }}
.btn.primary:hover {{ background: var(--accent-press); }}
.btn.danger {{ color: var(--red-i); }}
.btn:disabled, fieldset:disabled .btn {{ opacity: .45; cursor: not-allowed; transform: none; }}
.list {{ list-style: none; margin: 0 -16px; padding: 0; }}
.item {{ display: flex; align-items: center; border-bottom: 1px solid var(--line); }}
.pick {{ flex: none; display: grid; place-items: center; width: 44px; min-height: 72px; padding-left: 8px; cursor: pointer; }}
.pick input {{ width: 18px; height: 18px; margin: 0; accent-color: var(--accent); }}
.row {{ flex: 1; min-width: 0; display: grid; grid-template-columns: 40px minmax(0, 1fr) auto; grid-template-areas: "av title time" "av meta meta" "av chips chips";
  column-gap: 12px; row-gap: 2px; align-items: center; min-height: 72px; padding: 12px 16px 12px 4px; color: inherit; text-decoration: none; }}
.row:hover {{ background: var(--surf); }}
.row .av {{ grid-area: av; align-self: center; }}
.row b {{ grid-area: title; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.row.unread b::before {{ content: ""; display: inline-block; width: 8px; height: 8px; margin: 0 8px 2px 0; border-radius: 50%; background: var(--accent); }}
.row small {{ grid-area: meta; color: var(--mute); font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.row time {{ grid-area: time; justify-self: end; color: var(--mute); font-size: 13px; font-variant-numeric: tabular-nums; }}
.row .ctx {{ grid-area: ctx; display: flex; min-width: 0; color: var(--mute); font-size: 12px; line-height: 1.3; white-space: nowrap; }}
.row .ctx-more {{ flex: none; }}
.row .ctx-lead {{ flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; }}
.row .ctx-last {{ flex: none; max-width: 100%; overflow: hidden; text-overflow: ellipsis; }}
/* A long last name still leaves the names before it room for an ellipsis. */
.row .ctx-lead + .ctx-last {{ max-width: calc(100% - 1.5em); }}
.row .ctx-more + .ctx-lead + .ctx-last {{ max-width: calc(100% - 3.5em); }}
.row.has-ctx {{ grid-template-areas: "av ctx ctx" "av title time" "av meta meta" "av chips chips"; }}
@media (max-width: 759px) {{
  .row b {{ white-space: normal; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }}
  .row .rid {{ display: none; }}
}}
.day h2 {{ position: sticky; top: 56px; z-index: 1; margin: 0 -16px; padding: 16px 16px 8px; background: var(--bg);
  color: var(--mute); font-size: 13px; font-weight: 650; line-height: 1.2; }}
.day:first-child h2 {{ padding-top: 4px; }}
.row .chips {{ grid-area: chips; display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }}
.grp h2 {{ position: sticky; top: 56px; z-index: 1; margin: 0 -16px; padding: 16px 16px 8px; background: var(--bg);
  color: var(--mute); font-size: 13px; font-weight: 650; line-height: 1.2; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.grp:first-child h2 {{ padding-top: 4px; }}
.grp h3 {{ margin: 0 -16px; padding: 12px 16px 6px 32px; color: var(--mute); font-size: 13px; font-weight: 600; line-height: 1.2;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.empty {{ padding: 48px 0; text-align: center; color: var(--mute); }}
.empty b {{ display: block; color: var(--ink); font-size: 17px; margin-bottom: 4px; }}
.actions {{ position: sticky; bottom: 0; display: none; gap: 8px; margin: 0 -16px; padding: 12px 16px calc(12px + env(safe-area-inset-bottom));
  background: var(--bg); border-top: 1px solid var(--line); }}
.actions .btn {{ flex: 1; }}
form:has(.pick input:checked) .actions {{ display: flex; }}
.title {{ margin: 0 0 12px; font-size: 22px; line-height: 1.3; font-weight: 650; letter-spacing: -0.01em; text-wrap: balance; }}
.meta {{ display: flex; align-items: center; flex-wrap: wrap; gap: 6px 10px; margin: 0 0 8px; color: var(--mute); font-size: 15px; }}
.meta.who {{ flex-wrap: nowrap; align-items: flex-start; }}
.meta.who > span:last-child {{ flex: 1; min-width: 0; padding-top: 3px; }}
.meta .nw {{ white-space: nowrap; }}
.meta.sub {{ margin-bottom: 16px; }}
.sum {{ margin: 0 0 20px; padding: 14px 16px; border-radius: 12px; background: var(--surf); }}
.sum > :first-child {{ margin-top: 0; }} .sum > :last-child {{ margin-bottom: 0; }}
.md > * {{ max-width: 68ch; }}
.md :is(h1, h2, h3, h4) {{ margin: 20px 0 6px; font-size: 17px; line-height: 1.35; font-weight: 650; }}
.md code {{ font: 14px ui-monospace, SFMono-Regular, Menlo, monospace; padding: 1px 5px; border-radius: 4px; background: var(--surf); }}
.sum code {{ background: var(--code); }}
.md pre {{ white-space: pre-wrap; padding: 12px; border-radius: 10px; background: var(--surf); }}
.md pre code {{ padding: 0; background: none; }}
.md table {{ border-collapse: collapse; display: block; overflow-x: auto; }}
.md th, .md td {{ border: 1px solid var(--line); padding: 6px 10px; text-align: left; }}
.detail {{ margin: 0 0 20px; }}
.frame {{ margin: 0 0 20px; }}
.frame iframe {{ display: block; width: 100%; min-height: 280px; border: 1px solid var(--line); border-radius: 12px; background: #fff; }}
.frame p {{ margin: 6px 0 0; color: var(--mute); font-size: 14px; }}
.source {{ margin: 0 0 20px; }}
fieldset {{ border: 0; margin: 0; padding: 0; min-width: 0; }}
legend {{ padding: 0; margin: 0 0 4px; font-weight: 600; }}
.opt {{ display: flex; align-items: center; gap: 12px; min-height: 52px; padding: 8px 0; border-bottom: 1px solid var(--line); cursor: pointer; }}
.opt:last-of-type {{ border-bottom: 0; }}
.opt input {{ flex: none; width: 20px; height: 20px; margin: 0; accent-color: var(--accent); }}
.opt span {{ flex: 1; }}
.opt small {{ display: block; color: var(--mute); font-size: 14px; }}
.opt em {{ flex: none; font-style: normal; font-size: 14px; font-weight: 600; color: var(--blue-i); }}
.field {{ display: block; width: 100%; min-height: 48px; margin: 8px 0 12px; padding: 12px 14px; border: 1px solid var(--field);
  border-radius: 10px; background: var(--bg); line-height: 1.4; }}
textarea.field {{ min-height: 112px; resize: vertical; }}
.field::placeholder {{ color: var(--mute); opacity: 1; }}
.field:focus {{ outline: 2px solid var(--accent); outline-offset: -1px; border-color: var(--accent); }}
fieldset:disabled .field {{ background: var(--surf); color: var(--mute); cursor: not-allowed; }}
fieldset:disabled .opt, fieldset:disabled legend {{ color: var(--mute); cursor: not-allowed; }}
.pair {{ display: flex; gap: 8px; }} .pair .btn {{ flex: 1; min-height: 50px; }}
.answered {{ margin: 0 0 20px; padding: 14px 16px; border-radius: 12px; background: var(--surf); }}
.answered h2 {{ margin: 0 0 2px; color: var(--grey-i); font-size: 14px; font-weight: 600; }}
.answered b {{ display: block; font-size: 17px; }}
.answered p {{ margin: 6px 0 0; color: var(--grey-i); font-size: 15px; }}
.answered .status {{ display: flex; flex-wrap: wrap; align-items: center; gap: 6px 10px; margin-top: 10px; }}
.answered .status .chip {{ white-space: normal; line-height: 1.3; padding-block: 4px; }}
.sent {{ display: inline-flex; align-items: center; gap: 6px; font-weight: 600; color: var(--grey-i); }}
.sent.delivered {{ color: var(--green-i); }}
.ticks {{ flex: none; width: 17px; height: 16px; }}
.ticks .t2 {{ stroke-dasharray: 12; stroke-dashoffset: 0; }}
.landed .ticks .t2 {{ animation: tick 420ms 120ms cubic-bezier(.16, 1, .3, 1) both; }}
.answered.landed {{ animation: landed 1400ms cubic-bezier(.16, 1, .3, 1); }}
@keyframes tick {{ from {{ stroke-dashoffset: 12; }} to {{ stroke-dashoffset: 0; }} }}
@keyframes landed {{ from {{ background: var(--green-t); }} to {{ background: var(--surf); }} }}
.thread {{ display: flex; flex-direction: column; gap: 8px; margin: 24px 0 0; padding-top: 16px; border-top: 1px solid var(--line); }}
.thread h2, .follow h2 {{ margin: 0 0 4px; font-size: 16px; }}
.msg {{ max-width: 85%; padding: 8px 12px; border-radius: 16px; background: var(--surf); }}
.msg.me {{ align-self: flex-end; background: var(--me); border-bottom-right-radius: 4px; }}
.msg.agent {{ align-self: flex-start; border-bottom-left-radius: 4px; }}
.msg time {{ display: block; margin-top: 2px; color: var(--grey-i); font-size: 12px; text-align: right; font-variant-numeric: tabular-nums; }}
.msg.me time {{ color: var(--blue-i); }}
.msg .when {{ display: flex; align-items: center; justify-content: flex-end; gap: 4px; margin-top: 2px; }}
.msg .when time {{ margin: 0; }}
.msg.me .ticks {{ color: var(--blue-i); width: 15px; height: 14px; }}
.follow {{ margin: 24px 0 0; padding-top: 16px; border-top: 1px solid var(--line); }}
.follow .pair {{ align-items: flex-start; }}
.follow .field {{ margin: 0; flex: 1; min-height: 48px; }}
.follow .btn {{ flex: none; min-height: 48px; }}
.crumbs ol {{ display: flex; flex-wrap: wrap; gap: 2px 6px; margin: 0 0 6px; padding: 0; list-style: none;
  color: var(--mute); font-size: 14px; line-height: 1.4; }}
.crumbs li + li::before {{ content: "›"; margin-right: 6px; }}
.ontopic {{ margin: 24px 0 0; padding-top: 16px; border-top: 1px solid var(--line); }}
.ontopic h2 {{ margin: 0 0 4px; font-size: 16px; }}
.ontopic ul {{ list-style: none; margin: 0; padding: 0; }}
.ontopic a {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 48px; padding: 8px 0;
  border-bottom: 1px solid var(--line); color: inherit; text-decoration: none; }}
.ontopic li:last-child a {{ border-bottom: 0; }}
.ontopic a:hover b {{ text-decoration: underline; }}
.ontopic b {{ min-width: 0; font-weight: 550; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.ontopic .end {{ flex: none; display: flex; align-items: center; gap: 8px; }}
.ontopic time {{ color: var(--mute); font-size: 13px; font-variant-numeric: tabular-nums; }}
#stale {{ position: fixed; left: 50%; bottom: 20px; z-index: 3; transform: translateX(-50%); margin: 0; padding: 10px 16px;
  border-radius: 20px; background: var(--ink); color: var(--bg); box-shadow: 0 4px 16px rgba(0,0,0,.18); white-space: nowrap; }}
#stale a {{ color: inherit; font-weight: 650; }}
@media (min-width: 760px) {{
  .row {{ grid-template-areas: "av title time" "av meta chips"; }}
  .row.has-ctx {{ grid-template-areas: "av ctx ctx" "av title time" "av meta chips"; }}
  .row .chips {{ justify-content: flex-end; margin-top: 0; }}
  .list {{ margin: 0; border-top: 1px solid var(--line); }}
  .day h2 {{ margin: 0; padding-inline: 0; }}
  .grp h2 {{ margin: 0; padding-inline: 0; }}
  .grp h3 {{ margin: 0; padding-inline: 16px 0; }}
  .actions {{ margin: 0; padding-inline: 0; }}
  .title {{ font-size: 26px; }}
}}
.pane {{ display: none; }}
@media (min-width: 1100px) {{
  .split .bar-in {{ max-width: 1240px; }}
  .split-body {{ display: grid; grid-template-columns: 380px minmax(0, 1fr); max-width: 1240px; margin: 0 auto; }}
  .pane {{ display: block; position: sticky; top: 57px; height: calc(100vh - 57px); overflow-y: auto; border-right: 1px solid var(--line); }}
  .pane .list {{ margin: 0; border-top: 0; }}
  .pane .row {{ grid-template-areas: "av title time" "av meta meta" "av chips chips"; padding-left: 16px; }}
  .pane .row.has-ctx {{ grid-template-areas: "av ctx ctx" "av title time" "av meta meta" "av chips chips"; }}
  .pane .row b {{ white-space: normal; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }}
  .pane .row .rid {{ display: none; }}
  .pane .row .chips {{ justify-content: flex-start; margin-top: 4px; }}
  .pane .row[aria-current="page"] {{ background: var(--line); }}
  .pane .row[aria-current="page"] .kb {{ box-shadow: 0 0 0 2px var(--line); }}
  .split-body main {{ max-width: 760px; margin: 0; padding: 24px 40px 48px; }}
}}
@media (prefers-reduced-motion: reduce) {{
  .btn:active {{ transform: none; }}
  .landed .ticks .t2, .answered.landed {{ animation: none; }}
}}
</style>
</head>
<body{body}>
"""

# A reload on every store change used to wipe a half-typed answer. Once the
# visitor has touched a field the page offers the reload instead of forcing it.
# Opening an unread post marks it read, which is a store change: the page being
# left must stop listening first, or its reload cancels the navigation.
_SCRIPT = """<p id="stale" role="status" hidden>This page changed. <a href="">Reload</a></p>
<script>
const es = new EventSource("/events");
let open = false, dirty = false, leaving = false;
document.documentElement.classList.add("js");
document.addEventListener("input", () => { dirty = true; });
// Filters apply as soon as one changes; the panel closes on Escape or a click outside it.
document.querySelectorAll(".filt select").forEach((el) => el.addEventListener("change", () => el.form.requestSubmit()));
const filt = document.querySelector(".filt");
// J presses Next (or Finish) and K goes back to the inbox, unless a field has the keys.
document.addEventListener("keydown", (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey || e.target.closest("input, textarea, select, [contenteditable]")) return;
  const to = e.key === "j" ? document.querySelector("a.step") : e.key === "k" ? document.querySelector("a.back") : null;
  if (to) { e.preventDefault(); to.click(); }
});
if (filt) {
  document.addEventListener("click", (e) => { if (filt.open && !filt.contains(e.target)) filt.open = false; });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && filt.open) { filt.open = false; filt.querySelector("summary").focus(); }
  });
}
addEventListener("beforeunload", () => { leaving = true; es.close(); });
// A mark that showed "sent" on the last visit and "delivered" now just landed.
document.querySelectorAll("[data-ticks]").forEach((el) => {
  const key = "ib-ticks:" + el.dataset.ticks, now = el.dataset.state;
  let before = null;
  try { before = sessionStorage.getItem(key); sessionStorage.setItem(key, now); } catch (e) {}
  if (before === "sent" && now === "delivered") el.classList.add("landed");
});
es.onmessage = () => {
  if (leaving) return;
  if (!open) { open = true; return; }
  if (dirty || (filt && filt.open)) { document.getElementById("stale").hidden = false; return; }
  location.reload();
};
</script>
</body></html>
"""

_FUNNEL = (
    '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'aria-hidden="true"><path d="M3.5 6h13M6 10h8M8.5 14h3"/></svg>'
)

_CHEVRON = (
    '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true"><path d="M7.5 4.5 13 10l-5.5 5.5"/></svg>'
)

_CHECK = (
    '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true"><path d="M4.5 10.5 8 14l7.5-8"/></svg>'
)

_BACK = (
    '<a class="back" href="/"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12.5 4.5 7 10l5.5 5.5"/></svg>Inbox</a>'
)


def _esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


# Agents write summary and detail as Markdown. Raw HTML stays escaped (html=False), and
# markdown-it drops javascript:, vbscript: and file: links. The sandboxed frame is the
# only place agent HTML runs.
_MD = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table").enable("strikethrough")


def _md(text: str) -> str:
    return _MD.render(text)


def _frame_origin(host_header: str | None = None) -> str:
    configured = os.environ.get("INBOX_FRAME_ORIGIN")
    if configured:
        return configured.rstrip("/")
    host = (host_header or "").split(":")[0]
    if host.endswith(".ts.net"):
        https_port = os.environ.get("INBOX_FRAME_HTTPS_PORT", "8445")
        return f"https://{host}:{https_port}"
    return FRAME_ORIGIN


def _authorized(handler: BaseHTTPRequestHandler) -> bool:
    """Direct localhost has no Tailscale header. The port is bound to 127.0.0.1,
    and Tailscale Serve adds the header on every proxied request."""
    if os.environ.get("INBOX_ALLOW_INSECURE") == "1":
        return True
    login = handler.headers.get("Tailscale-User-Login")
    if not login:
        return True
    return login.startswith("tjdsneto@")


def _allowed_origins(handler: BaseHTTPRequestHandler) -> set[str]:
    port = handler.server.server_address[1]
    origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    configured = os.environ.get("INBOX_UI_ORIGIN")
    if configured:
        origins.add(configured.rstrip("/"))
    return origins


def _same_site(handler: BaseHTTPRequestHandler) -> bool:
    """Refuse what a foreign page can make the browser send: a cross-site form post
    (including one from the sandboxed agent frame, whose origin is "null") and a
    DNS-rebound Host. Non-browser callers send neither Origin nor Sec-Fetch-Site."""
    origins = _allowed_origins(handler)
    host = (handler.headers.get("Host") or "").rsplit(":", 1)[0]
    if host and host not in {urlparse(o).hostname for o in origins}:
        return False
    if handler.command != "POST":
        return True
    site = handler.headers.get("Sec-Fetch-Site")
    if site and site != "same-origin":
        return False
    origin = handler.headers.get("Origin")
    return origin is None or origin in origins


def _query_value(qs: dict, key: str) -> str | None:
    values = qs.get(key)
    if not values or values[0] == "":
        return None
    return values[0]


def _dismissed(row: dict) -> bool:
    flag = (row.get("delivery") or {}).get("dismissed")
    return flag is True or flag == "true"


def _group_choice(qs: dict, cookie_header: str | None) -> tuple[str, str | None]:
    """The Group by mode and, when this request picked one, the Set-Cookie that remembers it.

    A cookie rather than the URL, so the choice survives the live reload, the tab links and the phone."""
    asked = _query_value(qs, "group")
    if asked in grouping.GROUPS:
        return asked, f"{GROUP_COOKIE}={asked}; Path=/; Max-Age={GROUP_MAX_AGE}; SameSite=Lax"
    # By hand: http.cookies gives up on every cookie after one that holds a space or JSON.
    for part in (cookie_header or "").split(";"):
        name, _, value = part.strip().partition("=")
        if name == GROUP_COOKIE:
            return (value if value in grouping.GROUPS else "none"), None
    return "none", None


def load_feed(conn, qs: dict) -> list[dict]:
    kind = _query_value(qs, "kind")
    engine = _query_value(qs, "engine")
    state = _query_value(qs, "state")
    project = _query_value(qs, "project")
    common = {"kind": kind, "engine": engine, "project": project, "limit": 200}
    if _query_value(qs, "history") == "1":
        states = [state] if state else list(HISTORY_STATES)
        return store.list_entries(conn, states=states, newest=True, **common)
    rows = store.list_entries(conn, states=[state] if state else None, **common)
    hidden = HIDDEN_STATES if state else HIDDEN_STATES | DONE_STATES
    visible = [row for row in rows if row["state"] not in hidden and not _dismissed(row)]
    opened = [row for row in visible if row["kind"] == "ask" and row["state"] == "open"]
    unread = [row for row in visible if row["kind"] == "post" and row["state"] == "unread"]
    seen = {row["id"] for row in opened + unread}
    rest = [row for row in visible if row["id"] not in seen]
    return opened + unread + rest


def next_entry(listed: list[dict], entry_id: str, after: str | None = None) -> str | None:
    """The entry to open after this one: the one the page was opened with, while it is still listed, else the next row."""
    ids = [row["id"] for row in listed]
    if after and after != entry_id and after in ids:
        return after
    at = ids.index(entry_id) if entry_id in ids else -1
    return ids[at + 1] if at + 1 < len(ids) else None


LOCAL = ZoneInfo("America/Sao_Paulo")
CLOSED_REACH = ("held", "unreachable")
REACH_CHIP = {"live": ("Live", "green"), "resumable": ("Resumable", "blue"), "held": ("Held", "amber"), "unreachable": ("Unreachable", "red")}
STATE_CHIP = {
    "answered": ("Answered", "blue"), "delivered": ("Answered", "green"), "undelivered": ("Answered, not delivered", "red"),
    "expired": ("Expired", "grey"), "withdrawn": ("Withdrawn", "grey"), "superseded": ("Superseded", "grey"),
    "unread": ("Unread", "blue"), "read": ("Read", "grey"), "archived": ("Archived", "grey"),
}


def _local(value) -> datetime | None:
    if not value:
        return None
    try:
        when = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return when.astimezone(LOCAL) if when.tzinfo else when


def _clock(value) -> str:
    """09:38 today, "Nov 23" before today."""
    when = _local(value)
    if when is None:
        return ""
    if when.date() == datetime.now(LOCAL).date():
        return when.strftime("%H:%M")
    return f"{when.strftime('%b')} {when.day}"


def _hour(value) -> str:
    when = _local(value)
    return when.strftime("%H:%M") if when else ""


def _day(value) -> str:
    """Today, Yesterday, "Mon, Nov 23", and the year once it is not this one."""
    when = _local(value)
    if when is None:
        return "Undated"
    today = datetime.now(LOCAL).date()
    gap = (today - when.date()).days
    if gap == 0:
        return "Today"
    if gap == 1:
        return "Yesterday"
    label = f"{when.strftime('%a')}, {when.strftime('%b')} {when.day}"
    return label if when.year == today.year else f"{label}, {when.year}"


def _by_day(rows: list[dict]) -> str:
    """History, one list per day under a heading that sticks below the bar."""
    groups: list[tuple[str, list[dict]]] = []
    for row in rows:
        label = _day(row.get("created_at"))
        if not groups or groups[-1][0] != label:
            groups.append((label, []))
        groups[-1][1].append(row)
    return "".join(
        f'<section class="day"><h2>{_esc(label)}</h2><ul class="list">'
        + "".join(_card(row, by_day=True) for row in items)
        + "</ul></section>"
        for label, items in groups
    )


def _grouped(groups: list[grouping.Group]) -> str:
    """Group by: one section per intent or root with a one-line heading; tree nests forked intents one level."""
    def rows(items: list[dict]) -> str:
        return ('<ul class="list">' + "".join(_card(row) for row in items) + "</ul>") if items else ""

    def heading(group: grouping.Group, tag: str) -> str:
        project = _who(group.lead) if group.key and tag == "h2" else ""
        text = " · ".join(bit for bit in (group.title, project) if bit)
        return f'<{tag} title="{_esc(text)}">{_esc(text)}</{tag}>'

    return "".join(
        f'<section class="grp">{heading(group, "h2")}{rows(group.rows)}'
        + "".join(f'<section class="grp sub">{heading(sub, "h3")}{rows(sub.rows)}</section>' for sub in group.subs)
        + "</section>"
        for group in groups
    )


def _ago(value) -> str:
    when = _local(value)
    if when is None:
        return ""
    minutes = int((datetime.now(LOCAL) - when).total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    if minutes < 60 * 24:
        return f"{minutes // 60} h ago"
    return f"{minutes // (60 * 24)} d ago"


def _reach(delivery: dict) -> str:
    word = delivery.get("reachability")
    if not word:
        return ""
    label = REACH_CHIP.get(word, (word.capitalize(), ""))[0]
    when = delivery.get("reachable_at")
    if word == "held" and when:
        raw = str(when)
        clock = raw.split("T", 1)[1][:5] if "T" in raw else raw
        return f"{label}, answerable at ~{clock}"
    return label


def _chip(row: dict) -> str:
    state = row["state"]
    delivery = row.get("delivery") or {}
    if row["kind"] == "ask" and state == "open":
        word = delivery.get("reachability")
        label, tone = (_reach(delivery), REACH_CHIP[word][1]) if word in REACH_CHIP else ("Needs answer", "blue")
    else:
        label, tone = STATE_CHIP.get(state, (state.capitalize(), "grey"))
    if row["kind"] == "ask" and state in DONE_STATES:
        # The answer's own delivery mark: one tick sent, two once the session has it.
        return f'<span class="chip {tone}">{_ticks("delivered" if state == "delivered" else "sent")}{_esc(label)}</span>'
    dot = "<i></i>" if tone in ("green", "amber", "red") else ""
    return f'<span class="chip {tone}">{dot}{_esc(label)}</span>'


def _urgent(row: dict) -> str:
    return '<span class="chip red">Urgent</span>' if row.get("priority") == "urgent" else ""


def _who(row: dict) -> str:
    asker = row.get("asker") or {}
    project = asker.get("project")
    return Path(project).name if project else (asker.get("script") or "")


_KIND_BADGE = {
    "ask": ("q", "Question", '<path d="M4.3 4.5a1.75 1.75 0 1 1 2.5 1.6c-.5.3-.8.7-.8 1.2v.2" fill="none" stroke="currentColor" '
            'stroke-width="1.6" stroke-linecap="round"/><circle cx="6" cy="9.6" r=".9" fill="currentColor"/>'),
    "post": ("r", "Report", '<circle cx="6" cy="3.4" r=".95" fill="currentColor"/><path d="M6 5.6v3.6" fill="none" '
             'stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>'),
}


def _avatar(row: dict, small: bool = False, kind: bool = False) -> str:
    """The project's initial. kind adds a corner badge: a question mark for a question, an i for a report."""
    name = _who(row) or (row.get("asker") or {}).get("engine") or "?"
    tone = sum(name.encode()) % 7
    size = " sm" if small else ""
    initial = _esc(name[:1].upper())
    if not kind or row.get("kind") not in _KIND_BADGE:
        return f'<span class="av av{tone}{size}" aria-hidden="true">{initial}</span>'
    cls, label, icon = _KIND_BADGE[row["kind"]]
    return (
        f'<span class="av av{tone}{size}" role="img" aria-label="{label}">{initial}'
        f'<i class="kb {cls}"><svg viewBox="0 0 12 12" aria-hidden="true">{icon}</svg></i></span>'
    )


def _bar(left: str, count: int | None, tools: str = "") -> str:
    right = f'<span class="count">{count} waiting</span>' if count else ""
    if tools:
        right = f'<div class="tools">{right}{tools}</div>'
    return f'<header class="bar"><div class="bar-in">{left}{right}</div></header>'


def _card(row: dict, *, pick: bool = True, current: bool = False, by_day: bool = False) -> str:
    engine = (row.get("asker") or {}).get("engine") or ""
    answer = row.get("answer") or {}
    said = f"You: {_shown(row, answer.get('value'))}" if row["kind"] == "ask" and answer else ""
    meta = " · ".join(_esc(bit) for bit in (_who(row), engine, said) if bit)
    unread = " unread" if row["kind"] == "post" and row["state"] == "unread" else ""
    # The discussion the row belongs to, above its title: the last two names of its topic path.
    path = grouping.path_of(row)
    ctx = grouping.context(path)
    line = ""
    if ctx:
        # One span per part, so a narrow row ellipsizes the name in the middle, never the topic.
        names = [grouping.name(node) for node in path]
        more = '<span class="ctx-more">…&nbsp;›&nbsp;</span>' if len(names) > 2 else ""
        lead = f'<span class="ctx-lead">{_esc(names[-2])}</span>' if len(names) > 1 else ""
        last = f'<span class="ctx-last">{"&nbsp;› " if lead else ""}{_esc(names[-1])}</span>'
        line = f'<span class="ctx" title="{_esc(ctx[1])}">{more}{lead}{last}</span>'
    has = " has-ctx" if ctx else ""
    box = (
        f'<label class="pick"><input type="checkbox" name="id" value="{_esc(row["id"])}" aria-label="Select {_esc(row["id"])}"></label>'
        if pick else ""
    )
    here = ' aria-current="page"' if current else ""
    return (
        f'<li class="item">{box}'
        f'<a class="row{unread}{has}" href="/e/{_esc(row["id"])}"{here}>{_avatar(row, kind=True)}<b>{_esc(row["title"])}</b>{line}'
        f'<time>{_esc(_hour(row.get("created_at")) if by_day else _clock(row.get("created_at")))}</time>'
        f'<small>{meta}<span class="rid"> · <span class="id">{_esc(row["id"])}</span></span></small>'
        f'<span class="chips">{_urgent(row)}{_chip(row)}</span></a>'
        "</li>"
    )


TABS = (("Active", "/", {}), ('<span class="lg">Needs answer</span><span class="sm">To answer</span>', "/?kind=ask&state=open", {"kind": "ask", "state": "open"}),
        ("Info", "/?kind=post", {"kind": "post"}), ("History", "/?history=1", {"history": "1"}))


def _tab(current: dict) -> tuple[str, dict]:
    """The tab a view belongs to. History holds any kind; otherwise the kind picks Info or Needs answer."""
    if current.get("history"):
        pick = 3
    elif current.get("kind") == "post":
        pick = 2
    elif current.get("kind") == "ask":
        pick = 1
    else:
        pick = 0
    return TABS[pick][1], TABS[pick][2]


def _group_select(group: str) -> str:
    opts = "".join(
        f'<option value="{value}"{" selected" if value == group else ""}>{label}</option>' for value, label in GROUP_LABELS
    )
    return f'<label>Group by<select name="group">{opts}</select></label>'


def _nav(
    qs: dict, projects: list[str] = (), intents: list[tuple[str, str]] = (), group: str = "none",
) -> tuple[str, str]:
    """The view tabs, and the filter button and panel that sit in the header bar."""
    current = {key: _query_value(qs, key) for key in ("kind", "state", "history") if _query_value(qs, key)}
    home, want = _tab(current)
    mark = ' aria-current="page"'
    tabs = "".join(f'<a href="{href}"{mark if href == home else ""}>{label}</a>' for label, href, _ in TABS)
    # The filter panel narrows the current tab: it keeps the tab's history, and counts
    # only what differs from the tab. Group by is a view, so it is never counted.
    hidden = '<input type="hidden" name="history" value="1">' if current.get("history") else ""
    on = sum(1 for key in ("kind", "project", "engine", "state", "intent") if _query_value(qs, key) != want.get(key))
    project = _query_value(qs, "project")
    if project and project not in projects:
        projects = [project, *projects]
    intent = _query_value(qs, "intent")
    if intent and intent not in {value for value, _ in intents}:
        intents = [(intent, intent), *intents]

    def options(label: str, key: str, names) -> str:
        """names are values, or (value, label) pairs."""
        chosen = _query_value(qs, key)
        pairs = [name if isinstance(name, tuple) else (name, name) for name in names]
        opts = "".join(
            f'<option value="{_esc(value)}"{" selected" if value == chosen else ""}>{_esc(text)}</option>' for value, text in pairs
        )
        return f'<label>{label}<select name="{key}"><option value="">Any {label.lower()}</option>{opts}</select></label>'

    badge = f"<b>{on}</b>" if on else ""
    said = f", {on} on" if on else ""
    clear = f'<a class="btn" href="{home}">Clear</a>' if on else ""
    filters = (
        f'<details class="filt{" on" if on else ""}"><summary aria-label="Filters{said}" title="Filters">{_FUNNEL}{badge}</summary>'
        '<form method="get" action="/">'
        + hidden
        + options("Type", "kind", (("ask", "Question"), ("post", "Report")))
        + options("Project", "project", [(path, Path(path).name) for path in projects])
        + options("Engine", "engine", ("claude", "codex", "cursor"))
        + options("State", "state", ("open", "unread", "answered", "delivered", "undelivered", "expired", "read"))
        + (options("Intent", "intent", intents) if intents else "")
        + _group_select(group)
        + f'<div class="pair">{clear}<button class="btn go" type="submit">Apply</button></div>'
        "</form></details>"
    )
    return f'<nav class="tabs" aria-label="Views">{tabs}</nav>', filters


def _waiting(rows: list[dict]) -> int:
    return sum(1 for row in rows if row["kind"] == "ask" and row["state"] == "open")


def _feed_page(
    rows: list[dict], qs: dict, error: str | None = None, banner: str = "", waiting: int | None = None,
    projects: list[str] = (), intents: list[tuple[str, str]] = (), group: str = "none",
) -> str:
    err = f'<p class="notice err" role="alert">{_esc(error)}</p>' if error else ""
    line = f'<p class="notice warn">{_esc(banner)}</p>' if banner else ""
    if rows:
        if group in ("intent", "tree"):
            listing = _grouped(grouping.group_rows(rows, group))
        elif _query_value(qs, "history") == "1":
            listing = _by_day(rows)
        else:
            listing = '<ul class="list">' + "".join(_card(row) for row in rows) + "</ul>"
        body = (
            '<form method="post" action="/batch">'
            + listing
            + '<div class="actions">'
            '<button class="btn danger" type="submit" name="action" value="withdraw">Withdraw</button>'
            '<button class="btn" type="submit" name="action" value="dismiss">Dismiss</button>'
            "</div></form>"
        )
    else:
        if any(key != "group" for key in qs):
            body = '<p class="empty"><b>Nothing here</b>Nothing matches this view.</p>'
        else:
            body = (
                '<p class="empty"><b>All caught up</b>New questions and reports land here. '
                'Answered questions and read reports are in <a href="/?history=1">History</a>.</p>'
            )
    count = _waiting(rows) if waiting is None else waiting
    tabs, filters = _nav(qs, projects, intents, group)
    return (
        _HEAD.format(title="Inbox", body="")
        + _bar("<h1>Inbox</h1>", count, filters)
        + "<main>"
        + tabs
        + line
        + err
        + body
        + "</main>"
        + _SCRIPT
    )


def _control_fields(control: dict) -> str:
    ctype = control.get("type")
    if ctype in ("choice", "multi"):
        kind = "radio" if ctype == "choice" else "checkbox"
        fields = []
        for opt in control.get("options") or []:
            rec = "<em>Recommended</em>" if opt.get("recommended") else ""
            checked = " checked" if opt.get("default") else ""
            desc = f"<small>{_esc(opt['description'])}</small>" if opt.get("description") else ""
            fields.append(
                f'<label class="opt"><input type="{kind}" name="value" value="{_esc(opt["id"])}"{checked}>'
                f'<span>{_esc(opt["label"])}{desc}</span>{rec}</label>'
            )
        return "".join(fields)
    if ctype == "text":
        if control.get("size") == "long":
            return '<textarea class="field" name="value" placeholder="Type your answer" aria-label="Your answer"></textarea>'
        return '<input class="field" name="value" placeholder="Type your answer" aria-label="Your answer">'
    return ""


def _control_buttons(control: dict) -> str:
    if control.get("type") == "approve":
        return (
            '<div class="pair"><button class="btn primary" type="submit" name="value" value="approve">Approve</button>'
            '<button class="btn" type="submit" name="value" value="revise">Revise</button></div>'
        )
    return '<button class="btn primary" type="submit">Send answer</button>' if control.get("type") else ""


def _closed_notice(delivery: dict) -> str:
    word = delivery.get("reachability")
    if word == "held":
        when = _reach(delivery).partition("answerable at ")[2]
        later = f" at {when}" if when else " later"
        return f'<p class="notice warn">This session is out of tokens. You can answer{_esc(later)}.</p>'
    if word == "unreachable":
        return '<p class="notice err">This session can\'t be reached, so an answer can\'t be delivered.</p>'
    return ""


def _shown(entry: dict, value) -> str:
    labels = {opt["id"]: opt["label"] for opt in (entry.get("control") or {}).get("options") or []}
    values = value if isinstance(value, list) else [value]
    return ", ".join(labels.get(item, str(item)) for item in values)


VIA = {"telegram": "Telegram", "web": "the web", "cli": "the CLI", "chat": "the chat", "say": "voice"}


def _ticks(state: str) -> str:
    """Telegram's marks: one tick when sent, two once the session has it.

    The second tick is its own path, so the page can draw it in when delivery lands.
    """
    second = '<path class="t2" d="M7.5 11 8.5 12 15 4.5"/>' if state == "delivered" else ""
    label = "Delivered" if state == "delivered" else "Sent"
    return (
        f'<svg class="ticks" viewBox="0 0 17 16" fill="none" stroke="currentColor" stroke-width="1.8" '
        f'stroke-linecap="round" stroke-linejoin="round" role="img" aria-label="{label}">'
        f'<path d="M1.5 8.5 5 12 11.5 4.5"/>{second}</svg>'
    )


def _answered(entry: dict) -> str:
    answer = entry.get("answer")
    if not answer:
        return ""
    delivery = entry.get("delivery") or {}
    if entry["state"] == "undelivered":
        mark, state = '<span class="chip red"><i></i>Not delivered: the session never picked it up</span>', "failed"
    elif entry["state"] == "delivered":
        words = "Delivered" + (", the session resumed to read it" if delivery.get("headless") else " to the session")
        mark, state = f'<span class="sent delivered">{_ticks("delivered")}{_esc(words)}</span>', "delivered"
    elif not (entry.get("asker") or {}).get("session_id"):
        words = f"Saved for {_who(entry) or 'the asker'} to pick up"
        mark, state = f'<span class="sent">{_ticks("sent")}{_esc(words)}</span>', "saved"
    else:
        words = "Delivering to the session" if delivery.get("inflight") else "Sent, waiting to deliver"
        mark, state = f'<span class="sent">{_ticks("sent")}{_esc(words)}</span>', "sent"
    comment = f"<p>{_esc(answer['comment'])}</p>" if answer.get("comment") else ""
    via = answer.get("via")
    sent = " · ".join(bit for bit in (f"From {VIA.get(via, via)}" if via else "", _clock(answer.get("at"))) if bit)
    return (
        f'<section class="answered" data-ticks="{_esc(entry["id"])}:answer" data-state="{state}">'
        f'<h2>Your answer</h2><b>{_esc(_shown(entry, answer.get("value")))}</b>{comment}'
        f'<p class="status">{mark}<span>{_esc(sent)}</span></p></section>'
    )


def _thread(entry: dict) -> str:
    events = entry.get("thread") or []
    if not events:
        return ""
    delivered = (entry.get("delivery") or {}).get("delivered_seq") or 0

    def bubble(event: dict) -> str:
        when = f'<time>{_esc(_clock(event.get("at")))}</time>'
        if event.get("type") != "followup":
            return f'<div class="msg agent">{_esc(event.get("text") or "")}<span class="when">{when}</span></div>'
        state = "delivered" if event["seq"] <= delivered else "sent"
        return (
            f'<div class="msg me" data-ticks="{_esc(entry["id"])}:f{event["seq"]}" data-state="{state}">'
            f'{_esc(event.get("text") or "")}<span class="when">{when}{_ticks(state)}</span></div>'
        )

    bubbles = "".join(bubble(event) for event in events)
    return f'<section class="thread" aria-label="Conversation"><h2>Conversation</h2>{bubbles}</section>'


def _crumbs(entry: dict) -> str:
    """The entry's topic path, root first, above the title."""
    path = grouping.path_of(entry)
    if not path:
        return ""
    items = "".join(f"<li>{_esc(grouping.name(node))}</li>" for node in path)
    return f'<nav class="crumbs" aria-label="Topic"><ol>{items}</ol></nav>'


def _on_topic(related: list[dict]) -> str:
    """The other entries on the same topic: title, state and age, each linking to its page."""
    if not related:
        return ""
    items = "".join(
        f'<li><a href="/e/{_esc(row["id"])}"><b>{_esc(row["title"])}</b>'
        f'<span class="end">{_chip(row)}<time>{_esc(_ago(row.get("created_at")))}</time></span></a></li>'
        for row in related
    )
    return f'<section class="ontopic" aria-label="On this topic"><h2>On this topic</h2><ul>{items}</ul></section>'


def _step(next_id: str | None) -> str:
    """The Next button: the entry after this one in the feed, or Finish, back to the inbox, at the end. J presses it."""
    if not next_id:
        return f'<a class="step" href="/" title="Finish (J)">Finish{_CHECK}</a>'
    return f'<a class="step" href="/e/{_esc(next_id)}" rel="next" title="Next (J)">Next{_CHEVRON}</a>'


def _entry_page(
    entry: dict, error: str | None = None, frame_origin: str | None = None, waiting: int | None = None,
    sidebar: list[dict] | None = None, next_id: str | None = None, related: list[dict] | None = None,
) -> str:
    """One entry. sidebar is the feed, shown beside the entry on wide screens only."""
    eid = _esc(entry["id"])
    # A form posts back with the next entry, so Next still points past this one once it is answered.
    then = f"?next={quote(next_id)}" if next_id else ""
    engine = (entry.get("asker") or {}).get("engine") or ""
    created = entry.get("created_at")
    # Each piece wraps as a unit, so a narrow screen never splits "3 min / ago".
    bits = (_who(entry), engine, _clock(created), _ago(created))
    meta = " · ".join(f'<span class="nw">{_esc(bit)}</span>' for bit in bits if bit)
    # An urgent entry already carries the Urgent chip.
    kind = "Report" if entry["kind"] == "post" else ("Question" if entry.get("priority") == "urgent" else "Normal priority")
    body = ' class="split"' if sidebar is not None else ""
    parts = [_HEAD.format(title=_esc(entry["title"]), body=body), _bar(_BACK, waiting, _step(next_id))]
    if sidebar is not None:
        # An answered entry has left the default feed; keep it in the pane so the page says where you are.
        listed = sidebar if any(row["id"] == entry["id"] for row in sidebar) else [entry, *sidebar]
        rows = "".join(_card(row, pick=False, current=row["id"] == entry["id"]) for row in listed)
        parts.append(f'<div class="split-body"><nav class="pane" aria-label="Inbox entries"><ul class="list">{rows}</ul></nav>')
    parts.append("<main>")
    if error:
        parts.append(f'<p class="notice err" role="alert">{_esc(error)}</p>')
    parts.append(
        _crumbs(entry)
        + f'<h1 class="title">{_esc(entry["title"])}</h1>'
        f'<p class="meta who">{_avatar(entry, small=True)}<span>{meta}</span></p>'
        f'<p class="meta sub">{_urgent(entry)}{_chip(entry)}<span>{_esc(kind)} · <span class="id">{eid}</span></span></p>'
    )
    if entry.get("summary"):
        parts.append(f'<div class="md sum">{_md(entry["summary"])}</div>')
    if entry.get("html"):
        src = f"{(frame_origin or _frame_origin()).rstrip('/')}/h/{eid}"
        parts.append(
            f'<div class="frame"><iframe sandbox="allow-scripts allow-popups" src="{src}" title="Agent attachment"></iframe>'
            "<p>Reference only. Answer below.</p></div>"
        )
    if entry.get("detail"):
        parts.append(f'<div class="md detail">{_md(entry["detail"])}</div>')
    source = entry.get("source") or {}
    if source.get("url"):
        parts.append(f'<p class="source"><a href="{_esc(source["url"])}" target="_blank" rel="noopener">Open source</a></p>')
    parts.append(_answered(entry))
    if entry["kind"] == "ask" and entry["state"] == "open":
        delivery = entry.get("delivery") or {}
        parts.append(_closed_notice(delivery))
        # The store refuses these answers anyway; the fieldset says so before a submit.
        closed = " disabled" if delivery.get("reachability") in CLOSED_REACH else ""
        control = entry.get("control") or {}
        hint = "Comment (a reason is required to revise)" if control.get("type") == "approve" else "Comment (optional)"
        parts.append(
            f'<form method="post" action="/e/{eid}/answer{then}"><fieldset{closed}><legend>Your answer</legend>'
            f"{_control_fields(control)}"
            f'<input class="field" name="comment" placeholder="{hint}" aria-label="Comment">'
            f"{_control_buttons(control)}</fieldset></form>"
        )
    parts.append(_thread(entry))
    if (entry.get("asker") or {}).get("session_id"):
        parts.append(
            f'<form class="follow" method="post" action="/e/{eid}/followup{then}"><h2>Follow up</h2><div class="pair">'
            '<textarea class="field" name="text" rows="1" placeholder="Message the agent" aria-label="Follow-up message"></textarea>'
            '<button class="btn" type="submit">Send</button></div></form>'
        )
    # After the follow-up form, so the thread and its reply box stay together.
    parts.append(_on_topic(related or []))
    parts.append("</main>" + ("</div>" if sidebar is not None else "") + _SCRIPT)
    return "".join(parts)


def open_count(conn) -> int:
    row = conn.execute("SELECT count(*) AS n FROM entries WHERE kind = 'ask' AND state = 'open'").fetchone()
    return row["n"]


def dismiss(conn, entry_id: str) -> None:
    row = conn.execute("SELECT id, kind, state FROM entries WHERE id = %s", (entry_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"no entry {entry_id}")
    if row["kind"] == "post":
        if row["state"] not in ("unread", "read"):
            raise ValidationError(f"{entry_id} cannot be dismissed")
        store.archive(conn, entry_id)
        return
    if row["kind"] != "ask" or row["state"] != "undelivered":
        raise ValidationError(f"{entry_id} cannot be dismissed")
    with conn.transaction():
        locked = conn.execute("SELECT delivery FROM entries WHERE id = %s FOR UPDATE", (entry_id,)).fetchone()
        delivery = dict(locked["delivery"] or {})
        delivery["dismissed"] = True
        conn.execute(
            "UPDATE entries SET delivery = %s, updated_at = now() WHERE id = %s",
            (Jsonb(delivery), entry_id),
        )


class InboxHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def do_GET(self) -> None:
        self._route("GET")

    def do_POST(self) -> None:
        self._route("POST")

    def _route(self, method: str) -> None:
        if not _authorized(self):
            self._bytes(403, b"tailnet login required", "text/plain; charset=utf-8")
            return
        if not _same_site(self):
            self._bytes(403, b"cross-site request refused", "text/plain; charset=utf-8")
            return
        try:
            self._dispatch(method)
        except NotFoundError as exc:
            self._bytes(404, _esc(exc).encode(), "text/plain; charset=utf-8")
        except StoreError:
            self._bytes(503, b"store unreachable", "text/plain; charset=utf-8")

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        if method == "GET" and path == "/events":
            self._events()
            return
        if method == "GET" and path == "/":
            group, cookie = _group_choice(qs, self.headers.get("Cookie"))
            with db.connect() as conn:
                from agent_inbox.notify import urgent_counts
                rows = load_feed(conn, qs)
                # The intent filter offers the intents in the view before it narrows it.
                intents = grouping.intents_in(rows)
                self._html(200, _feed_page(
                    grouping.only_intent(rows, _query_value(qs, "intent")), qs, banner=urgent_counts(conn),
                    waiting=open_count(conn), projects=store.list_projects(conn), intents=intents, group=group,
                ), cookie=cookie)
            return
        match = re.fullmatch(r"/e/([^/]+)", path)
        if method == "GET" and match:
            self._show(match.group(1), 200, None, _query_value(qs, "next"))
            return
        match = re.fullmatch(r"/e/([^/]+)/(answer|followup)", path)
        if method == "POST" and match:
            self._post_entry(match.group(1), match.group(2), _query_value(qs, "next"))
            return
        if method == "POST" and path == "/batch":
            self._batch()
            return
        self._bytes(404, b"not found", "text/plain; charset=utf-8")

    def _show(self, entry_id: str, status: int, error: str | None, after: str | None = None) -> None:
        with db.connect() as conn:
            # The feed is read before opening marks a report read, so the entry keeps its place in it.
            feed = load_feed(conn, {})
            entry = store.get_entry(conn, entry_id)
            if entry["kind"] == "post" and entry["state"] in ("unread", "read"):
                store.mark_read(conn, entry_id)
                entry = store.get_entry(conn, entry_id)
            listed = [entry if row["id"] == entry_id else row for row in feed]
            if not any(row["id"] == entry_id for row in listed):
                listed = [entry, *listed]
            self._html(status, _entry_page(
                entry, error, _frame_origin(self.headers.get("Host")), open_count(conn), sidebar=listed,
                next_id=next_entry(listed, entry_id, after), related=store.same_topic(conn, entry),
            ))

    def _post_entry(self, entry_id: str, action: str, after: str | None = None) -> None:
        form = self._form()
        try:
            with db.connect() as conn:
                if action == "answer":
                    entry = store.get_entry(conn, entry_id)
                    values = form.get("value") or []
                    control = entry.get("control") or {}
                    value = values if control.get("type") == "multi" else (values[0] if values else "")
                    store.answer(
                        conn, entry_id, value,
                        comment=(form.get("comment") or [""])[0],
                        via="web",
                    )
                else:
                    store.add_followup(
                        conn, entry_id, (form.get("text") or [""])[0],
                        via="web",
                    )
        except ConflictError as exc:
            self._show(entry_id, 409, str(exc), after)
            return
        except ValidationError as exc:
            self._show(entry_id, 400, str(exc), after)
            return
        self._redirect(f"/e/{quote(entry_id)}" + (f"?next={quote(after)}" if after else ""))

    def _batch(self) -> None:
        form = self._form()
        action = (form.get("action") or [""])[0]
        applied = 0
        errors: list[str] = []
        with db.connect() as conn:
            for entry_id in form.get("id") or []:
                try:
                    if action == "withdraw":
                        store.withdraw(conn, entry_id)
                    elif action == "dismiss":
                        dismiss(conn, entry_id)
                    else:
                        raise ValidationError("action must be withdraw or dismiss")
                    applied += 1
                except (ConflictError, ValidationError, NotFoundError) as exc:
                    errors.append(str(exc))
            if applied == 0:
                message = errors[0] if errors else "nothing selected"
                from agent_inbox.notify import urgent_counts
                group, _ = _group_choice({}, self.headers.get("Cookie"))
                rows = load_feed(conn, {})
                self._html(409, _feed_page(
                    rows, {}, message, banner=urgent_counts(conn), waiting=open_count(conn),
                    projects=store.list_projects(conn), intents=grouping.intents_in(rows), group=group,
                ))
                return
        self._redirect("/")

    def _events(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(b"data: refresh\n\n")
        self.wfile.flush()
        conn = db.connect()
        try:
            conn.execute(f"LISTEN {NOTIFY_CHANNEL}")
            while True:
                for _note in conn.notifies(timeout=25, stop_after=1):
                    self.wfile.write(b"data: refresh\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return
        finally:
            conn.close()

    def _form(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(min(length, 1_000_000)).decode()
        return parse_qs(raw, keep_blank_values=True)

    def _bytes(self, status: int, payload: bytes, content_type: str, cookie: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(payload)

    def _html(self, status: int, page: str, cookie: str | None = None) -> None:
        self._bytes(status, page.encode(), "text/html; charset=utf-8", cookie)

    def _redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()


def make_server(host: str = "127.0.0.1", port: int | None = None) -> ThreadingHTTPServer:
    if port is None:
        port = int(os.environ.get("INBOX_HTTP_PORT", str(HTTP_PORT)))
    return ThreadingHTTPServer((host, port), InboxHandler)
