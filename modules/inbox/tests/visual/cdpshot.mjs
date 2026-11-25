// One screenshot through the Chrome DevTools Protocol, at an exact viewport and colour scheme.
//
//   node cdpshot.mjs <out.png> <url> <width> <height> <light|dark>
//
// Why not `chrome --headless --window-size=W,H --screenshot`: on macOS Chrome won't make a
// window narrower than 500px, so a 390px request lays the page out at 500px and crops the PNG.
// `--virtual-time-budget` hangs on the inbox's live-polling pages, and `--force-dark-mode`
// doesn't flip `prefers-color-scheme` (headless follows the Mac's own appearance).
// Here the viewport and the scheme are emulated, then checked before the shot.
//
// Env: PROBE=<js expression> is evaluated after load and printed (it may change the page, e.g.
// open a <details>); NOSHOT=1 skips the PNG. Uses Node's built-in WebSocket (Node 22+), no deps.
// Exit 0 on a good shot, 3 when the page doesn't match the viewport or scheme asked for.
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";

const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const [out, url, w, h, scheme = "light"] = process.argv.slice(2);
if (!out || !url || !w || !h || !["light", "dark"].includes(scheme)) {
	console.error("usage: node cdpshot.mjs <out.png> <url> <width> <height> <light|dark>");
	process.exit(2);
}
const width = Number(w);
const height = Number(h);
const mobile = width < 600;

// A throwaway profile, so headless Chrome never attaches to the browser you are using.
const profile = mkdtempSync(join(tmpdir(), "cdpshot-"));
const chrome = spawn(CHROME, [
	"--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
	`--user-data-dir=${profile}`, "--remote-debugging-port=0", "--window-size=1280,1400", "about:blank",
], { stdio: "ignore" });
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function finish(code) {
	clearTimeout(killer);
	chrome.kill("SIGTERM");
	await sleep(300);
	rmSync(profile, { recursive: true, force: true });
	process.exit(code);
}

const killer = setTimeout(() => {
	console.error(`${basename(out)}: timed out`);
	chrome.kill("SIGKILL");
	rmSync(profile, { recursive: true, force: true });
	process.exit(2);
}, 40000);

let port;
for (let i = 0; i < 100 && !port; i++) {
	const file = join(profile, "DevToolsActivePort");
	if (existsSync(file)) port = readFileSync(file, "utf8").split("\n")[0].trim();
	else await sleep(100);
}
if (!port) {
	console.error("Chrome never opened its debugging port");
	await finish(2);
}
const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const ws = new WebSocket(targets.find((t) => t.type === "page").webSocketDebuggerUrl);
await new Promise((resolve) => ws.addEventListener("open", resolve));

let nextId = 0;
const pending = new Map();
const waiters = [];
ws.addEventListener("message", (ev) => {
	const msg = JSON.parse(ev.data);
	if (msg.id && pending.has(msg.id)) {
		pending.get(msg.id)(msg);
		pending.delete(msg.id);
	} else if (msg.method) {
		waiters.filter((x) => x.method === msg.method).forEach((x) => x.resolve(msg));
	}
});
const send = (method, params = {}) => new Promise((resolve) => {
	const id = ++nextId;
	pending.set(id, resolve);
	ws.send(JSON.stringify({ id, method, params }));
});
const once = (method) => new Promise((resolve) => waiters.push({ method, resolve }));
const evaluate = async (expression) => {
	const reply = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
	return reply.result.result.value;
};

await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile });
await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: scheme }] });
const loaded = once("Page.loadEventFired");
await send("Page.navigate", { url });
await loaded;
await sleep(500);

const info = JSON.parse(await evaluate(
	"JSON.stringify({w: innerWidth, sw: document.documentElement.scrollWidth, h: document.documentElement.scrollHeight,"
	+ " dark: matchMedia('(prefers-color-scheme: dark)').matches})",
));
if (process.env.PROBE) console.log("PROBE", JSON.stringify(await evaluate(process.env.PROBE)));

const problems = [];
if (info.w !== width) problems.push(`viewport is ${info.w}px, not ${width}px`);
if (info.sw > info.w) problems.push(`page scrolls sideways (${info.sw}px wide)`);
if (info.dark !== (scheme === "dark")) problems.push(`colour scheme is not ${scheme}`);

if (!process.env.NOSHOT) {
	// Grow the viewport to the page's height so the PNG holds the whole page.
	await send("Emulation.setDeviceMetricsOverride", { width, height: Math.max(height, info.h), deviceScaleFactor: 1, mobile });
	await sleep(200);
	const shot = await send("Page.captureScreenshot", { format: "png" });
	writeFileSync(out, Buffer.from(shot.result.data, "base64"));
}
console.log(`${basename(out)} ${JSON.stringify(info)}${problems.length ? " FAIL: " + problems.join("; ") : ""}`);
ws.close();
await finish(problems.length ? 3 : 0);
