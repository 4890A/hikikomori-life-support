// Plays a video to her as if it were a shared window, in a throwaway Chrome, so prompts and timings
// can be compared without playing. Run through replay.ps1, which prints the session report after.
//   node replay.mjs --chrome PATH --profile DIR --video FILE [--minutes 3] [--chattiness normal] [--say "30=ねえ、これ何？"]...
import { spawn } from 'node:child_process';
import { createReadStream, statSync } from 'node:fs';
import http from 'node:http';

const args = { minutes: 3, chattiness: 'normal', say: [] };
for (let i = 2; i < process.argv.length; i += 2) {
  const key = process.argv[i].replace(/^--/, '');
  const value = process.argv[i + 1];
  if (key === 'say') args.say.push(value);
  else args[key] = value;
}
const VIDEO_PORT = 8766;
const DEBUG_PORT = 9334;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// The page loads the video from here, with CORS so it can be captured as a stream.
const size = statSync(args.video).size;
const server = http.createServer((req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  const range = /bytes=(\d+)-(\d*)/.exec(req.headers.range ?? '');
  if (range) {
    const start = Number(range[1]);
    const end = range[2] ? Number(range[2]) : size - 1;
    res.writeHead(206, { 'Content-Type': 'video/mp4', 'Content-Range': `bytes ${start}-${end}/${size}`, 'Content-Length': end - start + 1, 'Accept-Ranges': 'bytes' });
    createReadStream(args.video, { start, end }).pipe(res);
  } else {
    res.writeHead(200, { 'Content-Type': 'video/mp4', 'Content-Length': size, 'Accept-Ranges': 'bytes' });
    createReadStream(args.video).pipe(res);
  }
});
await new Promise((r) => server.listen(VIDEO_PORT, r));

const browser = spawn(args.chrome, [
  `--user-data-dir=${args.profile}`, `--remote-debugging-port=${DEBUG_PORT}`, '--no-first-run', '--no-default-browser-check',
  // Keeps it running at full speed when the window is covered or the screen is off.
  '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding', '--disable-background-timer-throttling',
  '--autoplay-policy=no-user-gesture-required', '--window-size=1100,1000', 'http://localhost:5179/',
], { stdio: 'ignore' });
await sleep(7000);
const targets = await (await fetch(`http://127.0.0.1:${DEBUG_PORT}/json`)).json();
const ws = new WebSocket(targets.find((t) => t.type === 'page').webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let id = 0;
const waiting = new Map();
const errors = [];
ws.onmessage = (e) => {
  const m = JSON.parse(e.data);
  if (waiting.has(m.id)) { waiting.get(m.id)(m); waiting.delete(m.id); }
  if (m.method === 'Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.exception?.description ?? m.params.exceptionDetails.text);
};
const send = (method, params) => new Promise((r) => { id += 1; waiting.set(id, r); ws.send(JSON.stringify({ id, method, params })); });
const run = async (expression) => {
  const r = await send('Runtime.evaluate', { expression, awaitPromise: true, userGesture: true, returnByValue: true });
  return r.result?.result?.value ?? JSON.stringify(r.result?.exceptionDetails ?? r);
};
await send('Runtime.enable');

console.log('session:', await run(`fetch('/speech/companion/session/start', { method: 'POST' }).then((r) => r.json()).then(JSON.stringify)`));
console.log('start:', await run(`(async () => {
  const video = document.createElement('video');
  video.crossOrigin = 'anonymous';
  video.src = 'http://localhost:${VIDEO_PORT}/clip.mp4';
  video.muted = true;
  video.loop = true;
  await video.play();
  director.chattiness = ${JSON.stringify(args.chattiness)};
  await director.start(video.captureStream(30));
  window.__replayVideo = video;
  return 'playing ' + video.duration.toFixed(0) + ' s clip at ' + director.chattiness;
})()`));

const lines = args.say.map((entry) => { const at = entry.indexOf('='); return { at: Number(entry.slice(0, at)), text: entry.slice(at + 1) }; });
const started = Date.now();
const total = Number(args.minutes) * 60 * 1000;
while (Date.now() - started < total) {
  const elapsed = (Date.now() - started) / 1000;
  for (const line of lines.filter((l) => !l.done && l.at <= elapsed)) {
    line.done = true;
    await run(`director.say(${JSON.stringify(line.text)})`);
    console.log(`${elapsed.toFixed(0)} s: you said ${line.text}`);
  }
  await sleep(500);
}
console.log('between lines:', await run(`JSON.stringify({ quickLooks: director.notesCount, stayedQuiet: director.declinedCount, aizuchi: director.aizuchiPlayed })`));
await run('director.stop()');
await sleep(1500);
console.log('page errors:', errors.length ? errors.slice(0, 5) : 'none');
ws.send(JSON.stringify({ id: 999999, method: 'Browser.close' }));
await sleep(500);
browser.kill();
server.close();
process.exit(0);
