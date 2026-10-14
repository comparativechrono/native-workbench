/* Drives the workbench in headless Chromium: serves a checkout with its own serve.py (which sends the headers of
   cross-origin isolation, as GitHub Pages' service worker does), opens the page, and runs steps in the real terminal
   (MG.app.term.exec – exactly as if typed). After each step it records the exit status, what was printed and a hash
   of every file in the home folder, so that two runs (before and after a change) can be compared. */
import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import net from 'node:net';
import path from 'node:path';

export async function freePort() {
  return new Promise((resolve, reject) => {
    const s = net.createServer();
    s.unref();
    s.on('error', reject);
    s.listen(0, '127.0.0.1', () => {
      const { port } = s.address();
      s.close(() => resolve(port));
    });
  });
}

async function waitForPort(port, ms = 15000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const ok = await new Promise((resolve) => {
      const c = net.connect(port, '127.0.0.1', () => { c.end(); resolve(true); });
      c.on('error', () => resolve(false));
    });
    if (ok) return;
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error(`nothing listens on port ${port}`);
}

/** Serve `root` (a checkout of the workbench) and open it. → { page, browser, close, url, errors } */
export async function openWorkbench(root, { query = '', port, headless = true, server } = {}) {
  port = port || (await freePort());
  // (a test may bring its own server – a mock local runner that also serves the page)
  const srv = server ? null : spawn('python3', [path.join(root, 'serve.py'), String(port)], { stdio: 'ignore' });
  await waitForPort(port);
  const browser = await chromium.launch({ headless });
  const context = await browser.newContext();
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + (e && e.message)));
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push('console: ' + m.text().slice(0, 300));
  });
  const url = `http://127.0.0.1:${port}/${query}`;
  await page.goto(url);
  await page.waitForFunction(() => !!(window.MG && MG.app && MG.app.term), null, { timeout: 60000 });
  const close = async () => {
    try {
      await Promise.race([browser.close(), new Promise((r) => setTimeout(r, 10000))]);
    } catch (e) { /* already closed */ }
    if (srv) srv.kill('SIGKILL');
  };
  return { page, browser, close, url, errors };
}

/** every file and folder below the home folder: path, kind, size, permissions and a hash of the bytes */
export async function snapshot(page) {
  return page.evaluate(async () => {
    const fs = MG.app.term.fs;
    const cache = window.__hashCache || (window.__hashCache = new WeakMap());
    const out = [];
    for (const [p, e] of Array.from(fs.entries)) {
      if (!(p === fs.home || p.startsWith(fs.home + '/'))) continue;
      const rec = { p, k: e.kind, s: fs.size(e) };
      if (e.mode) rec.mode = e.mode;
      if (e.readonly) rec.ro = true;
      if (e.perm != null) rec.perm = e.perm;
      if (e.protected) rec.prot = true;
      if (e.kind !== 'dir') {
        let h = cache.get(e);
        if (!h) {
          try {
            const b = await fs.readBytes(p);
            const d = new Uint8Array(await crypto.subtle.digest('SHA-256', b));
            h = Array.from(d.slice(0, 12)).map((x) => x.toString(16).padStart(2, '0')).join('') + ':' + b.length;
          } catch (err) {
            h = 'ERR:' + (err && err.message);
          }
          cache.set(e, h);
        }
        rec.h = h;
      }
      out.push(rec);
    }
    return out.sort((a, b) => (a.p < b.p ? -1 : a.p > b.p ? 1 : 0));
  });
}

const withTimeout = (p, ms, what) => Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error(`timeout after ${ms} ms: ${what}`)), ms))]);

/** Run one step. Step kinds:
      { cmd }                  a command line, typed into the terminal
      { kill, afterMs }        start a command, press Ctrl+C twice after afterMs (a forced stop), wait for it to end
      { js }                   the body of an async function, run in the page; its result is recorded */
export async function runStep(wb, step, { timeoutMs = 300000 } = {}) {
  const { page } = wb;
  const errs0 = wb.errors.length;
  const t0 = Date.now();
  let res;
  try {
    if (step.cmd != null) {
      res = await withTimeout(
        page.evaluate(async (line) => {
          const T = MG.app.term, n0 = T.transcript.length;
          const code = await T.exec(line);
          const rec = T.transcript.length > n0 ? T.transcript[T.transcript.length - 1] : null;
          return { code, stdout: rec ? rec.stdout : null, stderr: rec ? rec.stderr : null, cwd: T.fs.cwd };
        }, step.cmd),
        timeoutMs,
        step.cmd
      );
    } else if (step.kill != null) {
      await page.evaluate((line) => {
        const T = MG.app.term;
        window.__killMark = T.outEl.children.length;
        window.__run = T.exec(line);
      }, step.kill);
      await page.waitForTimeout(step.afterMs || 2000);
      const lost = await page.evaluate(() => MG.app.term.stop(true));
      const r = await withTimeout(page.evaluate(() => window.__run), timeoutMs, 'the stopped command');
      // (the notes about lost files come a moment later: see stop() in terminal.js)
      await page.waitForTimeout(step.settleMs || 2500);
      const screen = await page.evaluate(() => {
        const T = MG.app.term;
        return Array.from(T.outEl.children).slice(window.__killMark).map((e) => `[${e.dataset.cls || ''}] ${e.textContent}`).join('\n');
      });
      res = { code: r, lost: (lost || []).slice().sort(), screen };
    } else if (step.js != null) {
      res = { value: await withTimeout(page.evaluate(`(async () => { ${step.js} })()`), timeoutMs, 'js step') };
    } else throw new Error('unknown step ' + JSON.stringify(step));
  } catch (e) {
    res = { failure: String(e && e.message ? e.message : e) };
    // (a command that does not end: stop it by force, so that the next step can run)
    try {
      await page.evaluate(() => MG.app.term.stop(true));
    } catch (x) { /* the page is gone */ }
  }
  res.ms = Date.now() - t0;
  res.errors = wb.errors.slice(errs0);
  if (!step.noSnapshot) res.files = await snapshot(page);
  return res;
}
