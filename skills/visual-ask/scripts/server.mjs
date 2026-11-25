#!/usr/bin/env node
// Serves the newest HTML fragment in a session directory.
// Fragments are wrapped in frame.html. Full documents are served as-is.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));

function arg(name) {
  const i = process.argv.indexOf(name);
  if (i === -1 || !process.argv[i + 1]) {
    console.error(`missing ${name}`);
    process.exit(1);
  }
  return process.argv[i + 1];
}

const session = path.resolve(arg('--session'));
const contentDir = path.join(session, 'content');
const stateDir = path.join(session, 'state');
fs.mkdirSync(contentDir, { recursive: true });
fs.mkdirSync(stateDir, { recursive: true });

const frame = fs.readFileSync(path.join(here, 'frame.html'), 'utf8');
let servedFile = null;

function newestHtml() {
  let best = null;
  let bestMtime = -1;
  let names = [];
  try {
    names = fs.readdirSync(contentDir);
  } catch {
    return null;
  }
  for (const name of names) {
    if (!name.endsWith('.html')) continue;
    const mtime = fs.statSync(path.join(contentDir, name)).mtimeMs;
    if (mtime >= bestMtime) {
      best = name;
      bestMtime = mtime;
    }
  }
  return best ? { name: best, mtime: bestMtime } : null;
}

function page() {
  const current = newestHtml();
  if (!current) {
    return frame.replace('<!-- CONTENT -->', '<p class="subtitle">Waiting for a page.</p>');
  }
  if (servedFile && servedFile !== current.name) {
    const events = path.join(stateDir, 'events');
    if (fs.existsSync(events)) fs.unlinkSync(events);
  }
  servedFile = current.name;
  const raw = fs.readFileSync(path.join(contentDir, current.name), 'utf8');
  const trimmed = raw.trimStart();
  if (trimmed.startsWith('<!DOCTYPE') || trimmed.startsWith('<html')) return raw;
  let html = frame.replace('<!-- CONTENT -->', raw);
  const title = (raw.match(/<h2[^>]*>([^<]+)<\/h2>/i) || [])[1];
  if (title) html = html.replace('<title>Question</title>', `<title>${title.trim()}</title>`);
  return html;
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url || '/', 'http://127.0.0.1');
  if (req.method === 'GET' && url.pathname === '/version') {
    const current = newestHtml();
    res.writeHead(200, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
    res.end(JSON.stringify({ file: current?.name || null, mtime: current?.mtime || 0 }));
    return;
  }
  if (req.method === 'POST' && url.pathname === '/event') {
    const chunks = [];
    req.on('data', (chunk) => {
      chunks.push(chunk);
      if (Buffer.concat(chunks).length > 100_000) req.destroy();
    });
    req.on('end', () => {
      try {
        const event = JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}');
        event.timestamp = Date.now();
        fs.appendFileSync(path.join(stateDir, 'events'), JSON.stringify(event) + '\n');
        res.writeHead(204);
        res.end();
      } catch {
        res.writeHead(400);
        res.end();
      }
    });
    return;
  }
  if (req.method === 'GET' && (url.pathname === '/' || url.pathname === '/index.html')) {
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
    res.end(page());
    return;
  }
  res.writeHead(404);
  res.end('not found');
});

server.listen(0, '127.0.0.1', () => {
  const { port } = server.address();
  const info = {
    type: 'server-started',
    port,
    url: `http://localhost:${port}`,
    screen_dir: contentDir,
    state_dir: stateDir,
  };
  fs.writeFileSync(path.join(stateDir, 'server-info'), JSON.stringify(info) + '\n');
  fs.writeFileSync(path.join(stateDir, 'server.pid'), String(process.pid) + '\n');
  console.log(JSON.stringify(info));
});
