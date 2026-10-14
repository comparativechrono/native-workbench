#!/usr/bin/env node
/* Checks of the local runner (runner/runner.mjs) with the page (assets/js/exec-local.js), in headless Chromium:
     - what is in the folder when the runner starts is in the terminal: files, folders, a text file as text, a link
       to data kept elsewhere – and the programs read them where they are;
     - what the programs write, and what the page writes itself (echo, rm, mv), is in the folder: a reload of the page
       finds it all again;
     - a run that is still going when the page is reloaded goes on, the page says so, and takes its files when it ends;
     - a forced stop ends that program only: what it wrote so far and every other file stay;
     - the runner answers only with the key of the session, only at its own address, only to its own page, and only
       about its own files.
   node local-runner.mjs → exit status 1 when a check fails */
import { openWorkbench, runStep, freePort } from './lib/harness.mjs';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
let failed = 0, passed = 0;
const check = (name, ok, detail) => {
  if (ok) passed++;
  else failed++;
  console.log(`${ok ? '✓' : '✗'} ${name}${!ok && detail !== undefined ? '\n    ' + JSON.stringify(detail).slice(0, 500) : ''}`);
};
const run = async (wb, cmd) => runStep(wb, { cmd, noSnapshot: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---- a folder with files in it before the runner starts
const ws = fs.mkdtempSync(path.join(os.tmpdir(), 'wb-ws-'));
const elsewhere = fs.mkdtempSync(path.join(os.tmpdir(), 'wb-data-'));
fs.mkdirSync(path.join(ws, 'project', 'reads'), { recursive: true });
fs.writeFileSync(path.join(ws, 'project', 'notes.txt'), 'first line\nsecond line\n');
fs.copyFileSync(path.join(ROOT, 'data', 'examples', 'somatic', 'tumor.bam'), path.join(ws, 'project', 'reads', 'tumor.bam'));
fs.copyFileSync(path.join(ROOT, 'data', 'examples', 'somatic', 'normal.bam'), path.join(elsewhere, 'normal.bam'));
fs.symlinkSync(elsewhere, path.join(ws, 'project', 'linked'));

const wb = await openWorkbench(ROOT, { runner: true, workspace: ws });
{
  const id = await wb.page.evaluate(async () => (await MG.exec.whenChosen(), MG.exec.id));
  check('the page uses the local runner', id === 'local', id);
  const screen = await wb.page.evaluate(() => MG.app.term.outEl.textContent);
  check('… and says where the files are', screen.includes(`your files (~) are the folder ${ws}`), screen.slice(0, 600));
  const r = await run(wb, 'ls project project/reads project/linked');
  check('the files in the folder are in the terminal (and a link to a folder elsewhere)', r.code === 0 && /notes\.txt/.test(r.stdout) && /tumor\.bam/.test(r.stdout) && /normal\.bam/.test(r.stdout), r);
  const k = await wb.page.evaluate(() => {
    const e = MG.app.term.fs.get(MG.app.term.fs.home + '/project/notes.txt'), b = MG.app.term.fs.get(MG.app.term.fs.home + '/project/reads/tumor.bam');
    return [e && e.kind, e && e.text, b && b.kind, b && b.size];
  });
  check('a small text file is text in the page; a BAM file stays on disk', k[0] === 'text' && k[1] === 'first line\nsecond line\n' && k[2] === 'local' && k[3] === fs.statSync(path.join(ws, 'project', 'reads', 'tumor.bam')).size, k);
  const c = await run(wb, 'samtools view -c project/reads/tumor.bam; samtools view -c project/linked/normal.bam');
  check('programs read files in the folder, and through the link', c.code === 0 && /^13130\n\d+\n$/.test(c.stdout), c);
}
// ---- what the programs and the page write is in the folder
{
  await run(wb, 'cd ~/project && samtools sort -o reads/sorted.bam reads/tumor.bam && samtools index reads/sorted.bam && echo "an edit" >> notes.txt && mkdir -p results && mv notes.txt results/notes.txt && touch empty.txt && rm empty.txt');
  await sleep(1200); // (what the page changes itself goes to the folder within a moment: see watch in exec-engine.js)
  const disk = (p) => fs.existsSync(path.join(ws, p));
  check('what a program wrote is in the folder', disk('project/reads/sorted.bam') && disk('project/reads/sorted.bam.bai'), fs.readdirSync(path.join(ws, 'project', 'reads')));
  check('what the page wrote, moved and removed is so in the folder', disk('project/results/notes.txt') && !disk('project/notes.txt') && !disk('project/empty.txt') && fs.readFileSync(path.join(ws, 'project/results/notes.txt'), 'utf8') === 'first line\nsecond line\nan edit\n', fs.readdirSync(path.join(ws, 'project')));
  check("the runner's own folder is not among the files", !(await run(wb, 'ls -a ~')).stdout.includes('.workbench'));
  // a file of the page that no program has touched: written by the page, then the page is reloaded
  await run(wb, 'echo "kept without a program" > ~/project/only-page.txt');
  await sleep(1200);
  await wb.page.reload();
  await wb.page.waitForFunction(() => !!(window.MG && MG.app && MG.app.term), null, { timeout: 60000 });
  const id = await wb.page.evaluate(async () => (await MG.exec.whenChosen(), MG.exec.id));
  const r = await run(wb, 'cd ~/project && cat only-page.txt results/notes.txt && samtools view -c reads/sorted.bam && ls reads');
  check('after a reload: the same runner, the same files, and the programs read them', id === 'local' && r.code === 0 && r.stdout.startsWith('kept without a program\nfirst line\nsecond line\nan edit\n13130\n') && /sorted\.bam\.bai/.test(r.stdout), { id, r });
}
// ---- a run that the page leaves while it runs
{
  await run(wb, 'cd ~/project');
  await wb.page.evaluate(() => {
    window.__long = MG.app.term.exec(`awk 'BEGIN { for (i = 0; i < 1e8; i++) x += i; print "finished" > "long.txt" }'`);
  });
  await sleep(1500);
  await wb.page.reload();
  await wb.page.waitForFunction(() => !!(window.MG && MG.app && MG.app.term), null, { timeout: 60000 });
  await sleep(500);
  const first = await wb.page.evaluate(() => MG.app.term.outEl.textContent);
  check('a run that goes on after a reload: the page says so', /gawk is still running in the local runner/.test(first), first.slice(-500));
  let done = '';
  for (let i = 0; i < 90 && !/which was still running, has finished/.test(done); i++) {
    await sleep(1000);
    done = await wb.page.evaluate(() => MG.app.term.outEl.textContent);
  }
  const has = await wb.page.evaluate(() => !!MG.app.term.fs.get(MG.app.term.fs.home + '/project/long.txt'));
  check('… and when it has ended, the page has its file', /gawk, which was still running, has finished \(exit status 0\)/.test(done) && has && fs.readFileSync(path.join(ws, 'project', 'long.txt'), 'utf8') === 'finished\n', { has, tail: done.slice(-300) });
}
// ---- a forced stop: only that program ends; what it wrote so far, and every other file, stays
{
  await run(wb, 'cd ~/project');
  const r = await runStep(wb, { kill: `awk 'BEGIN { print "started" > "partial.txt"; fflush("partial.txt"); for (i = 0; i < 1e12; i++) x += i }'`, afterMs: 2500, noSnapshot: true });
  const after = await run(wb, 'cat partial.txt && samtools view -c reads/sorted.bam && cat only-page.txt');
  const s = await wb.page.evaluate(() => ({ lastKill: MG.exec.lastKill, gen: MG.exec.gen, partial: !!MG.app.term.fs.get(MG.app.term.fs.home + '/project/partial.txt') }));
  const log = fs.readFileSync(path.join(ws, '.workbench', 'runs.jsonl'), 'utf8').trim().split('\n').map((l) => JSON.parse(l));
  check('a forced stop ends that program only: nothing is lost', r.code !== 0 && r.lost.length === 0 && s.lastKill === 'threads' && s.gen === 0 && /Killed/.test(r.screen), { r, s });
  check('… what it wrote so far is in the folder and in the page, the other files are as they were, and programs run again', s.partial && fs.readFileSync(path.join(ws, 'project', 'partial.txt'), 'utf8') === 'started\n' && after.code === 0 && after.stdout === 'started\n13130\nkept without a program\n', after);
  check('… and the runner logged the run as stopped', log.some((x) => x.program === 'gawk' && x.error === 'Killed'), log.slice(-2));
}
check('no page errors', wb.errors.length === 0, wb.errors);
const port = Number(new URL(wb.url).port);
await wb.close();

// ---- the runner's safety: its own runner, with a known key
{
  const key = 'K3Y' + Date.now();
  const p2 = await freePort();
  const srv = spawn('node', [path.join(ROOT, 'runner', 'runner.mjs'), '--workspace', ws, '--port', String(p2), '--token', key], { stdio: 'ignore' });
  await sleep(800);
  const req = (method, p, { headers = {}, body } = {}) =>
    new Promise((resolve) => {
      const r = http.request({ host: '127.0.0.1', port: p2, method, path: p, headers: Object.assign({ Host: `127.0.0.1:${p2}` }, headers) }, (res) => {
        let d = '';
        res.on('data', (c) => (d += c));
        res.on('end', () => resolve({ status: res.statusCode, body: d }));
      });
      r.on('error', (e) => resolve({ status: 0, body: String(e) }));
      if (body) r.write(body);
      r.end();
    });
  const auth = { Authorization: 'Bearer ' + key, 'Content-Type': 'application/json' };
  check('without the key: refused', (await req('GET', '/api/v1/hello')).status === 401);
  check('with a wrong key: refused', (await req('GET', '/api/v1/hello', { headers: { Authorization: 'Bearer nope' } })).status === 401);
  check('with the key: answered', (await req('GET', '/api/v1/hello', { headers: auth })).status === 200);
  check('at another name for this computer (DNS rebinding): refused', (await req('GET', '/api/v1/hello', { headers: Object.assign({}, auth, { Host: `evil.example:${p2}` }) })).status === 421);
  check('from another web page: refused', (await req('POST', '/api/v1/fs', { headers: Object.assign({ Origin: 'https://evil.example' }, auth), body: JSON.stringify({ op: 'lstat', path: '/shared/vfs/home/user' }) })).status === 403);
  const out = await req('POST', '/api/v1/fs', { headers: auth, body: JSON.stringify({ op: 'lstat', path: '/shared/vfs/home/user/../../../../etc/passwd' }) });
  check("a path out of the folders is not the computer's file", out.status === 200 && JSON.parse(out.body).ok === null, out);
  const st = await req('POST', '/api/v1/fs', { headers: auth, body: JSON.stringify({ op: 'readdir', path: '/shared/vfs/home/user' }) });
  check("the runner's own folder is hidden from the page", st.status === 200 && !JSON.parse(st.body).ok.includes('.workbench'), st);
  const ro = await req('POST', '/api/v1/fs', { headers: auth, body: JSON.stringify({ op: 'unlink', path: '/shared/vfs/data/examples/README.md' }) });
  check('the example data cannot be changed', ro.status === 403 && fs.existsSync(path.join(ROOT, 'data', 'examples', 'README.md')), ro);
  const prog = await req('POST', '/api/v1/exec', { headers: auth, body: JSON.stringify({ spec: ['..', '..', 'runner'], args: [], io: {}, cwd: '/shared/vfs/home/user' }) });
  check('only the programs of the workbench run', prog.status === 400, prog);
  srv.kill('SIGKILL');
}
fs.rmSync(ws, { recursive: true, force: true });
fs.rmSync(elsewhere, { recursive: true, force: true });
console.log(`${passed + failed} checks: ${failed ? failed + ' FAILED' : 'all passed'}`);
process.exit(failed ? 1 : 0);
