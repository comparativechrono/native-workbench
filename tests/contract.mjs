#!/usr/bin/env node
/* Checks of MG.exec (assets/js/exec.js) and of the local backend's connection (assets/js/exec-local.js), in headless
   Chromium:
     - a backend that lacks a member of the contract is refused; the members a backend may leave out have defaults;
     - the browser backend is the default;
     - ?backend=local where no runner answers (an ordinary web server): the page says so and runs the programs itself;
     - ?backend=local served by a (mock) local runner: the token of the session reaches the runner and leaves the
       address; a runner that answers is used, and says in words what it cannot do yet; a wrong token, or a runner of
       another protocol version, is refused – the page runs the programs itself.
   node contract.mjs → exit status 1 when a check fails */
import { openWorkbench, freePort, runStep } from './lib/harness.mjs';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
let failed = 0, passed = 0;
const check = (name, ok, detail) => {
  if (ok) passed++;
  else failed++;
  console.log(`${ok ? '✓' : '✗'} ${name}${!ok && detail !== undefined ? '\n    ' + JSON.stringify(detail).slice(0, 400) : ''}`);
};

/* a stand-in for the local runner: serves the workbench as serve.py does, and answers /api/v1/hello */
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.wasm': 'application/wasm', '.svg': 'image/svg+xml', '.png': 'image/png' };
async function mockRunner({ token, protocol = 1 }) {
  const port = await freePort();
  const seen = [];
  const server = http.createServer((req, res) => {
    const headers = { 'Cross-Origin-Opener-Policy': 'same-origin', 'Cross-Origin-Embedder-Policy': 'require-corp', 'Cross-Origin-Resource-Policy': 'same-origin' };
    const url = new URL(req.url, 'http://x');
    if (url.pathname.startsWith('/api/')) {
      seen.push({ path: url.pathname, auth: req.headers.authorization || null });
      if (req.headers.authorization !== 'Bearer ' + token) {
        res.writeHead(401, { ...headers, 'Content-Type': 'application/json' });
        return res.end('{"error":"no session"}');
      }
      if (url.pathname === '/api/v1/hello') {
        res.writeHead(200, { ...headers, 'Content-Type': 'application/json' });
        return res.end(JSON.stringify({ protocol, runner: 'mock-runner', version: '0.0', programs: { samtools: '1.17' }, workspace: { root: '/tmp/ws' } }));
      }
      res.writeHead(404, headers);
      return res.end();
    }
    let p = path.join(ROOT, decodeURIComponent(url.pathname));
    if (!p.startsWith(ROOT)) {
      res.writeHead(403, headers);
      return res.end();
    }
    if (fs.existsSync(p) && fs.statSync(p).isDirectory()) p = path.join(p, 'index.html');
    if (!fs.existsSync(p)) {
      res.writeHead(404, headers);
      return res.end();
    }
    res.writeHead(200, { ...headers, 'Content-Type': TYPES[path.extname(p)] || 'application/octet-stream' });
    fs.createReadStream(p).pipe(res);
  });
  await new Promise((r) => server.listen(port, '127.0.0.1', r));
  return { port, seen, close: () => new Promise((r) => server.close(r)) };
}

// ---- 1. the contract, in a page served as usual
{
  const wb = await openWorkbench(ROOT);
  const r = await wb.page.evaluate(async () => {
    const out = {};
    out.default = [MG.exec.id, MG.exec.wanted, MG.exec.fallback, typeof MG.wasm];
    try {
      MG.exec.register({ id: 'broken', run() {} });
      out.refused = null;
    } catch (e) {
      out.refused = e.message;
    }
    // a backend with every required member and none of the optional ones
    const b = {};
    for (const [k, how] of Object.entries(MG.exec.CONTRACT)) b[k] = how === 'fn' ? () => null : null;
    Object.assign(b, { id: 'minimal', label: 'a test', entryKind: 'minimal-entry', versions: {}, holds: (e) => !!e && e.kind === 'minimal-entry' });
    MG.exec.register(b);
    MG.exec.use('minimal');
    out.defaults = { gen: MG.exec.gen, lastKill: MG.exec.lastKill, lostTimes: MG.exec.lostTimes instanceof Map, lostEntries: MG.exec.lostEntries instanceof Map, keep: await MG.exec.keep([]), putBack: await MG.exec.putBack('/x', { kind: 'minimal-entry' }, 0), running: MG.exec.running };
    // an entry of the browser backend is still read by it while another backend is active
    out.holdsOther = MG.exec.holds({ kind: 'aioli', apath: '/nowhere' });
    MG.exec.use('browser');
    out.back = MG.exec.id;
    return out;
  });
  check('the browser backend is the default; MG.wasm is gone', JSON.stringify(r.default) === JSON.stringify(['browser', 'browser', null, 'undefined']), r.default);
  check('a backend without the members of the contract is refused, and they are named', /missing .*label.*entryKind.*ensure/.test(r.refused || ''), r.refused);
  check('the optional members have safe defaults', JSON.stringify(r.defaults) === JSON.stringify({ gen: 0, lastKill: '', lostTimes: true, lostEntries: true, keep: 0, putBack: false, running: null }), r.defaults);
  check('an entry is read by the backend that holds it, whichever is active', r.holdsOther === true, r.holdsOther);
  check('use() switches back', r.back === 'browser', r.back);

  // what the AI agent does around each of its commands (assistant.js: outsideSnapshot, keep, undoOutside): a copy of
  // a program-written file is kept, a command overwrites it, the old entry is put back and its bytes with it
  const a = await wb.page.evaluate(async () => {
    const T = MG.app.term, fs = T.fs, abs = fs.home + '/held.txt', copy = fs.home + '/held2.txt';
    await T.exec('cd ~ && seq 1 100000 > held.txt');
    const e = fs.get(abs), size = (await fs.readBytes(abs)).length;
    const out = { held: MG.exec.holds(e), kept: await MG.exec.keep([[abs, e]]), gen: MG.exec.gen };
    const since = Date.now();
    await T.exec('seq 1 5 > held.txt && cp held.txt held2.txt');
    out.changed = (await fs.readBytes(abs)).length;
    await MG.exec.settle(fs);
    fs.entries.set(abs, e);
    out.putBack = await MG.exec.putBack(abs, e, since);
    out.back = (await fs.readBytes(abs)).length === size;
    out.text = (await fs.readText(abs)).split('\n')[99999];
    out.copy = (await fs.readText(copy)) === '1\n2\n3\n4\n5\n';
    await MG.exec.dropKept();
    out.after = (await T.exec('wc -l < held.txt')) === 0;
    return out;
  });
  check("the AI agent's copies: kept, put back with their bytes, dropped", a.held && a.kept === 1 && a.gen === 0 && a.changed === 10 && a.putBack === true && a.back && a.text === '100000' && a.copy && a.after, a);
  await wb.close();
}

// ---- 2. ?backend=local, where no runner answers (serve.py: an ordinary web server)
{
  const wb = await openWorkbench(ROOT, { query: '?backend=local' });
  const r = await wb.page.evaluate(async () => {
    await MG.exec.whenChosen();
    return { id: MG.exec.id, wanted: MG.exec.wanted, fallback: MG.exec.fallback };
  });
  check('?backend=local without a runner: the browser backend runs the programs', r.id === 'browser' && r.wanted === 'local', r);
  check('… and the reason is given', /no local runner answered at http:\/\/127\.0\.0\.1:\d+ \(this page comes from an ordinary web server\)/.test((r.fallback && r.fallback.reason) || ''), r.fallback);
  await wb.page.waitForTimeout(300);
  const screen = await wb.page.evaluate(() => MG.app.term.outEl.textContent);
  check('… the terminal says so', screen.includes('The programs were to run in the local runner, but no local runner answered'), screen.slice(-400));
  const s = await runStep(wb, { cmd: 'echo ok && samtools --version | head -1', noSnapshot: true });
  check('… and programs run', s.code === 0 && s.stdout === 'ok\nsamtools 1.17\n', s);
  await wb.close();
}

// ---- 3. a local runner that answers
{
  const runner = await mockRunner({ token: 'S3CRET' });
  const wb = await openWorkbench(ROOT, { query: '?backend=local#runner-token=S3CRET', port: runner.port, server: true });
  const r = await wb.page.evaluate(async () => {
    await MG.exec.whenChosen();
    return { id: MG.exec.id, label: MG.exec.label, versions: MG.exec.versions, ready: MG.exec.ready, hash: location.hash, kept: sessionStorage.getItem((window.MG_CONFIG.storePrefix || 'biowb') + '.runnerToken'), fallback: MG.exec.fallback };
  });
  check('a runner that answers is used', r.id === 'local' && r.ready === true && !r.fallback, r);
  check('… it says who it is and what it runs', r.label === 'the local runner (mock-runner 0.0)' && r.versions.samtools === '1.17', r);
  check('… the token reached it, as a bearer token', runner.seen.length >= 1 && runner.seen.every((x) => x.auth === 'Bearer S3CRET'), runner.seen);
  check('… and left the address (kept for this tab only)', r.hash === '' && r.kept === 'S3CRET', r);
  const s = await runStep(wb, { cmd: 'samtools --version', noSnapshot: true });
  check('a program it cannot run yet: said in words, with a failing status', s.code !== 0 && /samtools: the local runner answered, but this version of the workbench cannot use it for that yet/.test(s.stderr || ''), s);
  const e = await runStep(wb, { cmd: 'echo still here', noSnapshot: true });
  check("the shell's own commands still work", e.code === 0 && e.stdout === 'still here\n', e);
  check('no page errors', wb.errors.length === 0, wb.errors);
  await wb.close();
  await runner.close();
}

// ---- 4. the wrong token, and a runner of another protocol version
for (const [what, opts, query, re] of [
  ['a page without the key of the session is refused', { token: 'S3CRET' }, '?backend=local#runner-token=WRONG', /did not accept this page: open the workbench with the link the runner gives/],
  ['a runner of another protocol version is refused', { token: 'K', protocol: 2 }, '?backend=local#runner-token=K', /speaks version 2 of the protocol, and this page version 1/]
]) {
  const runner = await mockRunner(opts);
  const wb = await openWorkbench(ROOT, { query, port: runner.port, server: true });
  const r = await wb.page.evaluate(async () => {
    await MG.exec.whenChosen();
    return { id: MG.exec.id, reason: MG.exec.fallback && MG.exec.fallback.reason };
  });
  check(what + ' – the browser backend runs the programs', r.id === 'browser' && re.test(r.reason || ''), r);
  await wb.close();
  await runner.close();
}

console.log(`${passed + failed} checks: ${failed ? failed + ' FAILED' : 'all passed'}`);
process.exit(failed ? 1 : 0);
