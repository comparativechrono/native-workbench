#!/usr/bin/env node
/* The local runner: the workbench's programs run on this computer, with the files of an analysis in a folder on
   disk – so that neither the size of the input nor the memory of a browser tab limits the analysis. It serves the
   workbench itself, at http://127.0.0.1:PORT, and the page runs its programs here (the local backend:
   assets/js/exec-local.js). The programs are the same WebAssembly builds as in the browser, run under Node.js with
   a file system that is the folder on disk (diskfs.mjs, tool-host.mjs) – or, for the programs that native/bin has
   (SAMtools, BCFtools, minimap2, BWA …), the programs built for this computer itself (native.mjs).

     node runner/runner.mjs --workspace ~/my-analysis [--port 8780] [--no-native]

   then open the address it prints (it carries the key of the session). The folder is the terminal's home folder (~):
   what is in it is there, and what the programs write is written there. The runner keeps its own things in a folder
   .workbench inside it (the page's /tmp and /galaxy, the pipes between programs, a log of the runs).

   Safety: it answers on 127.0.0.1 only, to requests for its own address (not to another name that points there), and
   no request about files or programs without the key of the session. The files it reads and writes are those of the
   folder, of .workbench and of the example data (read-only). Nothing else on the computer is reached through it.
   Node.js 18 or later; nothing to install. */
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import os from 'node:os';
import { Worker } from 'node:worker_threads';
import { fileURLToPath } from 'node:url';
import { pipeline } from 'node:stream/promises';
import { loadNative, describe, runNative, killNative, syncExamples } from './native.mjs';

const VERSION = '0.1.0';
const PROTOCOL = 1;
const HERE = path.dirname(fileURLToPath(import.meta.url));
const SITE = path.resolve(HERE, '..');

// ---------------------------------------------------------------- settings
const argv = process.argv.slice(2);
const opt = (name, dflt) => {
  const i = argv.indexOf('--' + name);
  return i >= 0 && i + 1 < argv.length ? argv[i + 1] : dflt;
};
if (argv.includes('--help') || argv.includes('-h')) {
  console.log('usage: node runner/runner.mjs --workspace FOLDER [--port PORT] [--no-native]\n\nFOLDER becomes the terminal\'s home folder (~); it is made if it is not there.\n--no-native: run every program as its WebAssembly build, as in the browser.');
  process.exit(0);
}
const WS = path.resolve(opt('workspace', path.join(os.homedir(), 'workbench')).replace(/^~(?=$|\/)/, os.homedir()));
const PORT = Number(opt('port', 8780));
const TOKEN = opt('token', process.env.WORKBENCH_RUNNER_TOKEN || crypto.randomBytes(24).toString('base64url'));
const STATE = path.join(WS, '.workbench');
if (WS === SITE || WS.startsWith(SITE + path.sep)) {
  console.error(`The workspace must not be inside the workbench's own folder (${SITE}): choose another folder.`);
  process.exit(2);
}
for (const d of [WS, STATE, path.join(STATE, 'tmp'), path.join(STATE, 'galaxy'), path.join(STATE, 'keep'), path.join(STATE, 'top', 'shared'), path.join(STATE, 'root', 'home', 'user'), path.join(STATE, 'root', 'data', 'examples'), path.join(STATE, 'root', 'tmp'), path.join(STATE, 'root', 'galaxy')])
  fs.mkdirSync(d, { recursive: true });

/* The programs' file system (the page's names, under /shared/vfs – exec-engine.js) and the folders on disk it is:
   the longest prefix decides. The example data is the site's own (read-only); the rest of /data is the runner's, as
   in the page: a program may write there, and the page undoes it ("nothing new can be written into the example data").
   Anything else – the folders above those (/shared) – is a folder of the runner's own. */
const ROOT = '/shared/vfs';
const MOUNTS = [
  { at: ROOT + '/home/user', dir: WS, hide: ['.workbench'] },
  { at: ROOT + '/data/examples', dir: path.join(SITE, 'data', 'examples'), readOnly: true },
  { at: ROOT + '/tmp', dir: path.join(STATE, 'tmp') },
  { at: ROOT + '/galaxy', dir: path.join(STATE, 'galaxy') },
  { at: ROOT, dir: path.join(STATE, 'root') },
  { at: '/keep', dir: path.join(STATE, 'keep') },
  { at: '/', dir: path.join(STATE, 'top') }
].sort((a, b) => b.at.length - a.at.length);

class Refused extends Error {
  constructor(msg, code = 'EACCES', status = 403) {
    super(msg);
    this.code = code;
    this.status = status;
  }
}
/** a path of the programs' file system → { disk, m (the mount), rel } – or Refused */
function where(v) {
  if (typeof v !== 'string' || !v.startsWith('/') || v.includes('\0')) throw new Refused(`not a path: ${v}`, 'EINVAL', 400);
  v = path.posix.normalize(v);
  if (v.length > 1 && v.endsWith('/')) v = v.slice(0, -1);
  const m = MOUNTS.find((x) => x.at === '/' || v === x.at || v.startsWith(x.at + '/'));
  if (!m) throw new Refused(`outside the workspace: ${v}`);
  const rel = (m.at === '/' ? v.slice(1) : v.slice(m.at.length)).replace(/^\//, '');
  if (m.hide && m.hide.includes(rel.split('/')[0])) throw new Refused(`no such file: ${v}`, 'ENOENT', 404);
  return { disk: rel ? path.join(m.dir, ...rel.split('/')) : m.dir, m, rel, v };
}
const writable = (w) => {
  if (w.m.readOnly) throw new Refused(`read-only: ${w.v}`, 'EACCES', 403);
  return w.disk;
};

/* The native programs (native/bin, checked against their SHA-256 now), and the copy of the example data they see:
   a native program reads and writes real files, so the example data it is given is a copy of its own, made the same
   as the site's again after every run (native.mjs). */
const NATIVE = loadNative(SITE, { disabled: argv.includes('--no-native') });
const EXAMPLES = { at: ROOT + '/data/examples', src: path.join(SITE, 'data', 'examples'), copy: path.join(STATE, 'examples') };
if (NATIVE.enabled) syncExamples(EXAMPLES.src, EXAMPLES.copy, { first: true });
const nativeCtx = { where, ROOT, STATE, home: WS, examples: EXAMPLES, mounts: MOUNTS };

// ---------------------------------------------------------------- the programs
/* the Biowasm builds that the page knows ([tool, version, program] – exec-engine.js SPECS); a program is only run
   from these files */
const BIOWASM = path.join(SITE, 'assets', 'vendor', 'biowasm');
const compiled = new Map();
function programFiles(spec) {
  if (!Array.isArray(spec) || spec.length !== 3 || !spec.every((s) => typeof s === 'string' && /^[A-Za-z0-9_+-][A-Za-z0-9._+-]*$/.test(s))) throw new Refused('not a program', 'EINVAL', 400);
  const [tool, version, program] = spec;
  const dir = path.join(BIOWASM, tool, version);
  if (!dir.startsWith(BIOWASM + path.sep)) throw new Refused('not a program', 'EINVAL', 400);
  const js = path.join(dir, program + '.js');
  if (!fs.existsSync(js)) throw new Refused(`no program ${program} (${tool} ${version})`, 'ENOENT', 404);
  return { js, wasm: path.join(dir, program + '.wasm'), data: path.join(dir, program + '.data'), program };
}
function moduleOf(file) {
  let m = compiled.get(file);
  if (!m) {
    m = WebAssembly.compile(fs.readFileSync(file));
    compiled.set(file, m);
    m.catch(() => compiled.delete(file));
  }
  return m;
}
/* One program at a time, each in a worker of its own. A run goes on when the page that started it is closed or
   reloaded; its result is kept (last) and written to the log. */
const runs = { queue: Promise.resolve(), current: null, last: null, n: 0 };
const LOG = path.join(STATE, 'runs.jsonl');
function execute(req) {
  const job = { id: ++runs.n, program: Array.isArray(req.spec) ? req.spec[2] : null, args: req.args, cwd: req.cwd, queued: Date.now() };
  const p = runs.queue.then(() => runOne(job, req));
  runs.queue = p.catch(() => {});
  return p;
}
async function runOne(job, req) {
  // (only the workbench's programs: the page names one of its WebAssembly builds; its native build runs if there is one)
  const files = programFiles(req.spec);
  // (a command of the AI agent runs confined – io.confined: the WebAssembly build, whose files are only the runner's
  // folders – until native programs can be confined too)
  const native = !(req.io && req.io.confined) && NATIVE.programs.get(files.program);
  if (native) return runOneNative(job, req, native);
  const wasmModule = await moduleOf(files.wasm);
  job.started = Date.now();
  runs.current = job;
  const mounts = MOUNTS.filter((m) => m.at.startsWith(ROOT)).sort((a, b) => a.at.length - b.at.length);
  const worker = new Worker(path.join(HERE, 'tool-host.mjs'), {
    workerData: { jsPath: files.js, dataPath: files.data, wasmModule, thisProgram: files.program, args: req.args, io: req.io || {}, cwd: req.cwd || ROOT, mounts }
  });
  job.worker = worker;
  let result;
  try {
    result = await new Promise((resolve) => {
      worker.once('message', (m) => resolve(m.ok ? m.result : { code: null, error: m.error }));
      worker.once('error', (e) => resolve({ code: null, error: String((e && e.message) || e) }));
      worker.once('exit', (c) => resolve({ code: null, error: job.killed ? 'Killed' : `the program's worker ended (${c})` }));
    });
  } finally {
    worker.terminate().catch(() => {});
    job.worker = null;
    runs.current = null;
  }
  return finished(job, result);
}
/** a native program: a process of its own (native.mjs) */
async function runOneNative(job, req, native) {
  job.started = Date.now();
  job.native = native.version;
  runs.current = job;
  let result;
  try {
    result = await runNative(native, req, job, nativeCtx);
  } finally {
    runs.current = null;
  }
  return finished(job, result);
}
function finished(job, result) {
  job.secs = (Date.now() - job.started) / 1000;
  job.code = result.code;
  job.memory = result.memory || null;
  job.maxRSS = process.resourceUsage().maxRSS * 1024;
  runs.last = { id: job.id, program: job.program, args: job.args, code: job.code, error: result.error || null, started: job.started, secs: job.secs, memory: job.memory, native: job.native || null };
  try {
    fs.appendFileSync(LOG, JSON.stringify({ ...runs.last, cwd: job.cwd, maxRSS: job.maxRSS }) + '\n');
  } catch (e) {
    /* (no log) */
  }
  return Object.assign({ stdout: '', stderr: '' }, result, { secs: job.secs });
}
function kill() {
  const job = runs.current;
  if (!job) return false;
  if (job.child) {
    job.killed = true;
    return killNative(job);
  }
  // (a native program that is about to start: it does not)
  if (job.native) return (job.killed = true);
  if (!job.worker) return false;
  job.killed = true;
  job.worker.terminate().catch(() => {});
  return true;
}

// ---------------------------------------------------------------- files
const S_IFDIR = 0o040000;
const statOf = (s) => ({ size: s.isDirectory() ? 4096 : s.size, mtime: Math.floor(s.mtimeMs), mode: s.isDirectory() ? (s.mode & 0o7777) | S_IFDIR : s.mode, isDir: s.isDirectory() });
/** everything below a folder: [[path, size, mtime, isDir]] – the programs' paths; a name `skip` is left out, and a
    folder that is reached twice (a link to a folder above it) once */
function tree(root, skip) {
  const out = [], seen = new Set();
  const walk = (v) => {
    let w, names;
    try {
      w = where(v);
      const s = fs.statSync(w.disk);
      const id = s.dev + ':' + s.ino;
      if (seen.has(id)) return;
      seen.add(id);
      names = fs.readdirSync(w.disk);
    } catch (e) {
      return;
    }
    for (const n of names.sort()) {
      if (n === skip) continue;
      const cv = v === '/' ? '/' + n : v + '/' + n;
      let cw, s;
      try {
        cw = where(cv);
        s = fs.statSync(cw.disk);
      } catch (e) {
        continue;
      }
      if (!s.isDirectory() && !s.isFile()) continue;
      const st = statOf(s);
      out.push([cv, st.size, st.mtime, st.isDir]);
      if (st.isDir) walk(cv);
    }
  };
  walk(root);
  return out;
}
/** text, if these bytes are UTF-8 with no NUL in them (as the page decides what is a text file) */
function textOf(buf) {
  try {
    const t = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(buf);
    return t.indexOf('\u0000') < 0 ? t : null;
  } catch (e) {
    return null;
  }
}
function readPart(file, start, length) {
  const fd = fs.openSync(file, 'r');
  try {
    const b = Buffer.alloc(length);
    const n = fs.readSync(fd, b, 0, length, start);
    return b.subarray(0, n);
  } finally {
    fs.closeSync(fd);
  }
}
function human(n) {
  const u = ['bytes', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) {
    n /= 1024;
    i++;
  }
  return (i ? n.toFixed(1) : n) + ' ' + u[i];
}
async function appendFrom(src, dest) {
  await pipeline(fs.createReadStream(src), fs.createWriteStream(dest, { flags: 'a' }));
}

/* the operations of the page's machine (exec-local.js: RemoteCli) */
const OPS = {
  lstat: ({ path: p }) => {
    try {
      return statOf(fs.statSync(where(p).disk));
    } catch (e) {
      if (e.code === 'ENOENT' || e.code === 'ENOTDIR') return null;
      throw e;
    }
  },
  readdir: ({ path: p }) => {
    const w = where(p);
    const names = fs.readdirSync(w.disk);
    return ['.', '..', ...(w.m.hide && !w.rel ? names.filter((n) => !w.m.hide.includes(n)) : names)];
  },
  mkdir: ({ path: p }) => (fs.mkdirSync(writable(where(p))), true),
  unlink: ({ path: p }) => (fs.unlinkSync(writable(where(p))), true),
  rmdir: ({ path: p }) => (fs.rmdirSync(writable(where(p))), true),
  chmod: ({ path: p, mode }) => (fs.chmodSync(writable(where(p)), mode & 0o7777), true),
  utime: ({ path: p, atime, mtime }) => (fs.utimesSync(writable(where(p)), atime / 1000, mtime / 1000), true),
  rename: ({ from, to }) => {
    const a = writable(where(from)), b = writable(where(to));
    try {
      fs.renameSync(a, b);
    } catch (e) {
      if (e.code !== 'EXDEV') throw e;
      fs.copyFileSync(a, b);
      fs.unlinkSync(a);
    }
    return true;
  },
  copy: ({ from, to }) => (fs.copyFileSync(where(from).disk, writable(where(to)), fs.constants.COPYFILE_FICLONE), true),
  /* what a program printed (from) becomes the file `to`, or is added to its end; tail: bytes after it (base64) */
  redirect: async ({ from, to, append, tail }) => {
    const a = writable(where(from)), b = writable(where(to));
    if (append && fs.existsSync(b)) {
      await appendFrom(a, b);
      fs.unlinkSync(a);
    } else
      try {
        fs.renameSync(a, b);
      } catch (e) {
        if (e.code !== 'EXDEV') throw e;
        fs.copyFileSync(a, b);
        fs.unlinkSync(a);
      }
    if (tail) fs.appendFileSync(b, Buffer.from(tail, 'base64'));
    return { size: fs.statSync(b).size };
  },
  tree: ({ root, skip }) => tree(root, skip),
  /* the beginning and the end of a long output (for the screen: the terminal shows the first 2,000 lines and the last
     1,000 of what a command prints) */
  peek: ({ path: p, head, tail }) => {
    const file = where(p).disk, size = fs.statSync(file).size;
    const dec = (b) => new TextDecoder('utf-8', { ignoreBOM: true }).decode(b);
    if (size <= head + tail) return { text: dec(fs.readFileSync(file)), size, cut: 0 };
    const cut = size - head - tail;
    return { text: dec(readPart(file, 0, head)) + `\n… ${human(cut)} of this output are not shown here (it has ${human(size)} in all): write it to a file with >, and look at it with head, tail, less or grep …\n` + dec(readPart(file, size - tail, tail)), size, cut };
  },
  /* the small text files among these (for the page at its start: text files are text in the page) → { path: text } */
  readSmall: ({ paths, max }) => {
    const out = {};
    let total = 0;
    for (const p of paths || []) {
      try {
        const file = where(p).disk, s = fs.statSync(file);
        if (!s.isFile() || s.size > max || total + s.size > 64 * 2 ** 20) continue;
        const t = textOf(fs.readFileSync(file));
        if (t != null) {
          out[p] = t;
          total += s.size;
        }
      } catch (e) {
        /* (left as it is) */
      }
    }
    return out;
  }
};

// ---------------------------------------------------------------- the web server
const ORIGINS = new Set([`http://127.0.0.1:${PORT}`, `http://localhost:${PORT}`]);
const HOSTS = new Set([`127.0.0.1:${PORT}`, `localhost:${PORT}`]);
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.wasm': 'application/wasm', '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.gif': 'image/gif', '.ico': 'image/x-icon', '.txt': 'text/plain; charset=utf-8', '.md': 'text/plain; charset=utf-8', '.ipynb': 'application/json', '.data': 'application/octet-stream', '.woff2': 'font/woff2', '.pdf': 'application/pdf' };
const ISOLATION = { 'Cross-Origin-Opener-Policy': 'same-origin', 'Cross-Origin-Embedder-Policy': 'require-corp', 'Cross-Origin-Resource-Policy': 'same-origin' };
function send(res, status, body, headers = {}) {
  res.writeHead(status, { ...ISOLATION, 'Cache-Control': 'no-store', ...headers });
  res.end(body);
}
const json = (res, status, obj) => send(res, status, JSON.stringify(obj), { 'Content-Type': 'application/json' });
const sameKey = (a, b) => {
  const x = Buffer.from(String(a || '')), y = Buffer.from(String(b || ''));
  return x.length === y.length && crypto.timingSafeEqual(x, y);
};
async function body(req, limit = 512 * 2 ** 20) {
  const chunks = [];
  let n = 0;
  for await (const c of req) {
    n += c.length;
    if (n > limit) throw new Refused('too large', 'EFBIG', 413);
    chunks.push(c);
  }
  return Buffer.concat(chunks);
}
/** a file of the site or of the workspace, with ranges (BAM indexes, viewers) */
function serveFile(req, res, file, type) {
  const st = fs.statSync(file);
  const headers = { 'Content-Type': type || 'application/octet-stream', 'Accept-Ranges': 'bytes' };
  const m = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range || '');
  if (m && (m[1] || m[2])) {
    let a = m[1] ? Number(m[1]) : Math.max(0, st.size - Number(m[2])), b = m[1] && m[2] ? Math.min(Number(m[2]), st.size - 1) : st.size - 1;
    if (a >= st.size || a > b) return send(res, 416, '', { 'Content-Range': `bytes */${st.size}` });
    res.writeHead(206, { ...ISOLATION, 'Cache-Control': 'no-store', ...headers, 'Content-Range': `bytes ${a}-${b}/${st.size}`, 'Content-Length': b - a + 1 });
    if (req.method === 'HEAD') return res.end();
    return fs.createReadStream(file, { start: a, end: b }).pipe(res);
  }
  res.writeHead(200, { ...ISOLATION, 'Cache-Control': 'no-store', ...headers, 'Content-Length': st.size });
  if (req.method === 'HEAD') return res.end();
  fs.createReadStream(file).pipe(res);
}
async function api(req, res, url) {
  const auth = /^Bearer (.+)$/.exec(req.headers.authorization || '');
  if (!auth || !sameKey(auth[1], TOKEN)) return json(res, 401, { error: 'this page does not have the key of the session' });
  if (req.headers.origin && !ORIGINS.has(req.headers.origin)) return json(res, 403, { error: 'not from the runner\'s own page' });
  const route = req.method + ' ' + url.pathname;
  if (route === 'GET /api/v1/hello')
    return json(res, 200, { protocol: PROTOCOL, runner: 'native-workbench-runner', version: VERSION, node: process.versions.node, workspace: { root: WS }, busy: runs.current ? { program: runs.current.program, args: runs.current.args, started: runs.current.started } : null, last: runs.last, programs: describe(NATIVE), native: { enabled: NATIVE.enabled, why: NATIVE.why || null, platform: `${process.platform}-${process.arch}` } });
  if (route === 'GET /api/v1/run') return json(res, 200, { busy: runs.current ? { id: runs.current.id, program: runs.current.program, args: runs.current.args, started: runs.current.started } : null, last: runs.last });
  if (route === 'POST /api/v1/fs') {
    const b = JSON.parse((await body(req, 16 * 2 ** 20)).toString('utf8'));
    const f = OPS[b.op];
    if (!f) return json(res, 400, { error: `no operation ${b.op}` });
    return json(res, 200, { ok: await f(b) });
  }
  if (route === 'GET /api/v1/file' || route === 'HEAD /api/v1/file') {
    const file = where(url.searchParams.get('path')).disk;
    if (!fs.statSync(file).isFile()) throw new Refused('not a file', 'EISDIR', 400);
    return serveFile(req, res, file);
  }
  if (route === 'PUT /api/v1/file') {
    const file = writable(where(url.searchParams.get('path')));
    // (into a file of its own first, then renamed: a reader never sees half of it)
    const part = file + '.part-' + process.pid + '-' + Date.now();
    try {
      await pipeline(req, fs.createWriteStream(part));
      fs.renameSync(part, file);
    } catch (e) {
      try {
        fs.unlinkSync(part);
      } catch (x) {
        /* (gone) */
      }
      throw e;
    }
    return json(res, 200, { ok: true });
  }
  if (route === 'POST /api/v1/exec') {
    const b = JSON.parse((await body(req, 16 * 2 ** 20)).toString('utf8'));
    return json(res, 200, { ok: await execute(b) });
  }
  if (route === 'POST /api/v1/kill') return json(res, 200, { ok: kill() });
  return json(res, 404, { error: 'no such request' });
}
const server = http.createServer(async (req, res) => {
  try {
    if (!HOSTS.has(req.headers.host || '')) return send(res, 421, 'This runner answers only at its own address.', { 'Content-Type': 'text/plain' });
    const url = new URL(req.url, `http://${req.headers.host}`);
    if (url.pathname.startsWith('/api/')) return await api(req, res, url);
    if (req.method !== 'GET' && req.method !== 'HEAD') return send(res, 405, '');
    // the workbench itself
    let rel = decodeURIComponent(url.pathname);
    if (rel.endsWith('/')) rel += 'index.html';
    const file = path.join(SITE, path.posix.normalize(rel));
    if (!(file === SITE || file.startsWith(SITE + path.sep)) || rel.split('/').some((s) => s.startsWith('.') && s.length > 1)) return send(res, 404, '');
    if (!fs.existsSync(file) || !fs.statSync(file).isFile()) return send(res, 404, 'Not found', { 'Content-Type': 'text/plain' });
    return serveFile(req, res, file, TYPES[path.extname(file)]);
  } catch (e) {
    const status = e instanceof Refused ? e.status : e && e.code === 'ENOENT' ? 404 : e instanceof SyntaxError ? 400 : 500;
    if (!res.headersSent) json(res, status, { error: String((e && e.message) || e), code: (e && e.code) || null });
    else res.destroy();
  }
});
server.requestTimeout = 0;
server.listen(PORT, '127.0.0.1', () => {
  const link = `http://127.0.0.1:${PORT}/?backend=local#runner-token=${TOKEN}`;
  console.log(`The workbench's local runner ${VERSION} (Node ${process.versions.node})`);
  console.log(`  your files (~ in the terminal): ${WS}`);
  console.log(NATIVE.enabled ? `  native programs: ${Array.from(NATIVE.programs.values()).map((p) => p.name + ' ' + p.version).join(', ')}` : `  native programs: none – ${NATIVE.why}; the WebAssembly builds run`);
  for (const p of NATIVE.problems) console.log(`  (not used: ${p})`);
  console.log(`  open: ${link}`);
  console.log('  (the link carries the key of this session; stop the runner with Ctrl+C)');
});
server.on('error', (e) => {
  console.error(e.code === 'EADDRINUSE' ? `Port ${PORT} is in use: start the runner with --port and another number.` : String(e));
  process.exit(1);
});
