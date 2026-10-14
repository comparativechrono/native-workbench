/* Native programs in the local runner: the same terminal, with programs built for the computer itself in place of
   their WebAssembly builds – no memory limit of the browser's, the computer's own speed, and on Windows, Linux and
   macOS (Intel) alike. They are the Cosmopolitan builds taken over from Native Workbench (native/README.md): one
   executable per program that is a Windows program and, through a small loader, a Linux and a macOS one.

   native/bin/programs.json lists them (written by native/build.py): name, tool, version, file, SHA-256, whether it
   can use threads. The runner checks every file against its SHA-256 when it starts, and runs a program natively only
   when the page asks for a program of the workbench (spec) that this list has; everything else stays the browser's
   WebAssembly build, run by the runner as before.

   A native program sees the real folders, not the page's names for them, so the runner
   - gives it the folder on disk as its working directory, and the paths on disk for the page's absolute paths in its
     arguments (/home/user/…, /data/examples/…, /tmp/…; also glued to an option: -o/home/user/x.bam,
     --output=/home/user/x.bam), and for a relative path that leaves the page's folder (../..) the place the page's
     programs would reach. What it prints among its messages gets the page's names back.
   - gives it the example data as a copy of its own (.workbench/examples), read-only where the system allows; after the
     run, anything a program made, changed or removed there is undone, and the page says so, as it does in the browser.
   - binds its standard input, output and error to the files the page named, measures how far it read its input, and
     stops it – and anything it started – when the page asks.
   A native program is not a sandbox: it can reach whatever the user can. The page's names keep its paths inside the
   folders above; a program told to write elsewhere through a file of names, or by a path it makes up, is not stopped. */
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import { spawn, spawnSync } from 'node:child_process';

const isWin = process.platform === 'win32';
const sha256 = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');

/** The native programs of this checkout. → { enabled, why, programs: Map(name → program), loader, problems } */
export function loadNative(site, { disabled = false } = {}) {
  const dir = path.join(site, 'native', 'bin');
  const out = { enabled: false, why: '', programs: new Map(), dir, loader: null, problems: [] };
  if (disabled) {
    out.why = 'turned off (--no-native)';
    return out;
  }
  let m;
  try {
    m = JSON.parse(fs.readFileSync(path.join(dir, 'programs.json'), 'utf8'));
  } catch (e) {
    out.why = 'this checkout has no native programs (native/bin/programs.json)';
    return out;
  }
  // how a Cosmopolitan program starts here: on Windows by itself; elsewhere through the loader for this system
  let loader = null;
  if (!isWin) {
    const l = (m.loaders || {})[`${process.platform}-${process.arch}`];
    if (!l) {
      out.why = `no native programs for ${process.platform} on ${process.arch} (Windows, and Linux and macOS on x86-64)`;
      return out;
    }
    loader = path.join(dir, ...l.file.split('/'));
    try {
      if (sha256(loader) !== l.sha256) throw new Error('its SHA-256 is not the one in programs.json');
      // (a checkout without the execute bit – a copy, an archive – still starts it)
      if (!(fs.statSync(loader).mode & 0o100)) fs.chmodSync(loader, 0o755);
    } catch (e) {
      out.why = `the loader ${l.file}: ${e.code === 'ENOENT' ? 'not there' : e.message}`;
      return out;
    }
    out.loader = loader;
  }
  for (const p of m.programs || []) {
    if (p.kind !== 'cosmopolitan') continue;
    const exe = path.join(dir, ...p.file.split('/'));
    try {
      if (sha256(exe) !== p.sha256) throw new Error('its SHA-256 is not the one in programs.json');
    } catch (e) {
      out.problems.push(`${p.name}: ${e.code === 'ENOENT' ? 'not there' : e.message}`);
      continue;
    }
    out.programs.set(p.name, Object.assign({}, p, { exe, loader }));
  }
  out.enabled = out.programs.size > 0;
  if (!out.enabled) out.why = 'none of the native programs could be used: ' + out.problems.join('; ');
  return out;
}

/** What the page is told about them (GET /api/v1/hello): name → { tool, version, threads } */
export function describe(native) {
  const o = {};
  for (const [name, p] of native.programs) o[name] = { tool: p.tool, version: p.version, threads: !!p.threads, native: true };
  return o;
}

/* ------------------------------------------------------------------ the example data, as a copy of its own */
/** every file and folder below root: rel → { size, mtime, dir } */
function listTree(root) {
  const out = new Map();
  const walk = (dir, rel) => {
    let names;
    try {
      names = fs.readdirSync(dir);
    } catch (e) {
      return;
    }
    for (const n of names) {
      const full = path.join(dir, n), r = rel ? rel + '/' + n : n;
      let s;
      try {
        s = fs.lstatSync(full);
      } catch (e) {
        continue;
      }
      if (s.isDirectory()) {
        out.set(r, { dir: true });
        walk(full, r);
      } else out.set(r, { size: s.size, mtime: Math.floor(s.mtimeMs), dir: false, link: s.isSymbolicLink() });
    }
  };
  walk(root, '');
  return out;
}
const writable = (p) => {
  try {
    if (!fs.statSync(p).isDirectory()) fs.chmodSync(p, 0o644);
  } catch (e) {
    /* (gone) */
  }
};
// (files only, and not on Windows: a folder that cannot be written to could not be deleted with the workspace)
const readOnly = (p) => {
  if (isWin) return;
  try {
    fs.chmodSync(p, 0o444);
  } catch (e) {
    /* (the system does not allow it: the check after each run still undoes changes) */
  }
};
// (a time that was copied over can lose a fraction of a millisecond)
const sameTime = (a, b) => Math.abs(a - b) <= 2;
/** Make the copy (dst) the same as the example data (src). → { refused, denied }: the names (relative) of what a
    program made there (removed again), and of what it changed or removed (put back). first: a new copy (no report). */
export function syncExamples(src, dst, { first = false } = {}) {
  const a = listTree(src);
  if (!fs.existsSync(dst)) fs.mkdirSync(dst, { recursive: true });
  const b = listTree(dst);
  const refused = [], denied = [];
  // what is there and should not be: deepest first
  for (const r of Array.from(b.keys()).sort((x, y) => y.length - x.length)) {
    const want = a.get(r), have = b.get(r);
    if (want && want.dir === have.dir && !have.link) continue;
    const full = path.join(dst, ...r.split('/'));
    fs.rmSync(full, { recursive: true, force: true });
    if (!want) refused.push(r);
  }
  // what is missing or changed: folders first
  for (const [r, want] of Array.from(a).sort((x, y) => x[0].length - y[0].length)) {
    const full = path.join(dst, ...r.split('/')), have = b.get(r);
    if (want.dir) {
      if (!have || !have.dir) fs.mkdirSync(full, { recursive: true });
      continue;
    }
    if (have && !have.dir && !have.link && have.size === want.size && sameTime(have.mtime, want.mtime)) continue;
    if (fs.existsSync(full)) {
      writable(full);
      fs.rmSync(full, { force: true });
    }
    fs.copyFileSync(path.join(src, ...r.split('/')), full);
    const s = fs.statSync(path.join(src, ...r.split('/')));
    fs.utimesSync(full, s.atime, s.mtime);
    readOnly(full);
    if (!first) denied.push(r);
  }
  return { refused, denied };
}

/* ------------------------------------------------------------------ one run */
/** Start a native program for the page and wait for its end.
    ctx: { where (a path of the programs' file system → { disk, m }), ROOT, STATE, examples: { at, src, copy }, home }
    → { code, error, stdinPos, stdinMax, order, memory, native, refused, denied } (the result execIO gives) */
export function runNative(prog, req, job, ctx) {
  const io = req.io || {};
  const { where, ROOT } = ctx;
  const links = (Array.isArray(io.links) ? io.links : []).filter((l) => Array.isArray(l) && typeof l[0] === 'string' && typeof l[1] === 'string');
  // ---- the page's names → the paths on disk
  const fwd = (p) => (isWin ? p.replace(/\\/g, '/') : p);
  const ex = ctx.examples;
  /** an absolute path of the page (as typed: /home/user/x, /data/examples/x; or /shared/vfs/…) → on disk, or null
      when it is not one of the page's folders (/dev/null and the like stay as they are) */
  const toDisk = (v) => {
    for (const [target, link] of links)
      if (v === link || v.startsWith(link + '/')) {
        v = target + v.slice(link.length);
        break;
      }
    if (!(v === ROOT || v.startsWith(ROOT + '/'))) return null;
    v = path.posix.normalize(v);
    if (ex && (v === ex.at || v.startsWith(ex.at + '/'))) return fwd(path.join(ex.copy, ...v.slice(ex.at.length).split('/').filter(Boolean)));
    try {
      return fwd(where(v).disk);
    } catch (e) {
      // (a name the page's programs cannot see – the runner's own folder: a place that is not there)
      return fwd(path.join(ctx.STATE, 'no-such-folder', ...v.split('/').filter(Boolean)));
    }
  };
  const vcwd = path.posix.normalize(typeof req.cwd === 'string' && req.cwd.startsWith('/') ? req.cwd : ROOT);
  const cwd = toDisk(vcwd);
  /** the mount a path of the page is in (to tell whether ../ leaves it) */
  const mountOf = (v) => {
    try {
      return ex && (v === ex.at || v.startsWith(ex.at + '/')) ? 'examples' : where(v).m.at;
    } catch (e) {
      return null;
    }
  };
  const args = (req.args || []).map((a) => {
    if (typeof a !== 'string') return String(a);
    // a whole path, a path glued to a one-letter option (-o/home/user/x.bam), or after --option=
    const m = /^(-[A-Za-z]|--[^=]+=)?(\/.*)$/.exec(a);
    if (m) {
      const d = toDisk(m[2]);
      return d == null ? a : (m[1] || '') + d;
    }
    // a relative path that leaves the page's folder (../..), or names the runner's own: where the page's programs reach
    if (!a.startsWith('-') && /(^|\/)(\.\.|\.workbench)(\/|$)/.test(a)) {
      const v = path.posix.normalize(vcwd + '/' + a);
      if (mountOf(v) !== mountOf(vcwd) || /\/\.workbench(\/|$)/.test(v)) return toDisk(v) || a;
    }
    return a;
  });
  // ---- standard input, output and error: the files the page named
  const opened = [];
  const open = (v, flags) => {
    if (!v || v === '/dev/null') return 'ignore';
    const d = toDisk(v);
    if (d == null) return 'ignore';
    const fd = fs.openSync(d, flags);
    opened.push(fd);
    return fd;
  };
  let fd0, fd1, fd2;
  try {
    fd0 = open(io.stdin, 'r');
    fd1 = open(io.stdout, io.merge ? 'a' : 'w');
    fd2 = io.merge ? fd1 : open(io.stderr, 'w');
  } catch (e) {
    for (const fd of opened) fs.closeSync(fd);
    return Promise.resolve({ code: 1, error: `${prog.name}: ${e.message}`, stdinPos: 0, stdinMax: 0, order: [], memory: null, native: true });
  }
  // ---- the environment: what the shell exports, with paths on disk; a temporary folder and a home of its own
  const env = {};
  if (isWin)
    for (const k of ['SystemRoot', 'windir', 'SystemDrive', 'ComSpec', 'PATHEXT', 'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'PROCESSOR_IDENTIFIER', 'OS', 'USERPROFILE', 'LOCALAPPDATA', 'APPDATA', 'ProgramData'])
      if (process.env[k] != null) env[k] = process.env[k];
  for (const kv of io.env || []) {
    const i = typeof kv === 'string' ? kv.indexOf('=') : -1;
    if (i <= 0) continue;
    const k = kv.slice(0, i);
    let v = kv.slice(i + 1);
    if (v.startsWith('/')) v = toDisk(v) || v;
    env[k] = v;
  }
  const tmp = fwd(path.join(ctx.STATE, 'tmp'));
  if (!env.TMPDIR) env.TMPDIR = tmp;
  if (isWin) env.TMP = env.TEMP = env.TMPDIR;
  env.HOME = fwd(ctx.home);
  env.PWD = cwd;
  env.PATH = isWin ? [path.dirname(prog.exe), path.join(process.env.SystemRoot || 'C:\\Windows', 'System32')].join(';') : path.dirname(prog.exe);
  // ---- start it: on Windows the program itself (argv[0] its name); elsewhere the loader: ape - PROGRAM ARGV0 ARGV…
  const started = Date.now();
  let child;
  // (stopped before it started)
  if (job.killed) {
    for (const fd of opened) fs.closeSync(fd);
    return Promise.resolve({ code: null, error: 'Killed', stdinPos: 0, stdinMax: 0, order: [], memory: null, native: true });
  }
  try {
    child = isWin
      ? spawn(prog.exe, args, { cwd: cwd.replace(/\//g, '\\'), env, stdio: [fd0, fd1, fd2], windowsHide: true, argv0: prog.name })
      : spawn(prog.loader, ['-', prog.exe, prog.name, ...args], { cwd, env, stdio: [fd0, fd1, fd2], detached: true });
  } catch (e) {
    for (const fd of opened) fs.closeSync(fd);
    return Promise.resolve({ code: 127, error: `${prog.name}: the native program could not be started (${e.message})`, stdinPos: 0, stdinMax: 0, order: [], memory: null, native: true });
  }
  job.child = child;
  // (the program has its own copies of the output files; the input stays open here, to see how far it was read)
  for (const fd of [fd1, fd2]) if (typeof fd === 'number') {
    try {
      fs.closeSync(fd);
    } catch (e) {
      /* (closed: 2>&1) */
    }
  }
  return new Promise((resolve) => {
    let done = false;
    const finish = (code, signal, spawnError) => {
      if (done) return;
      done = true;
      job.child = null;
      // how far it read its input: what is left of it after the shared position (a file: the program moved the same
      // position as this descriptor; at most 64 MiB are counted, beyond that it is taken as read)
      let stdinPos = 0;
      if (typeof fd0 === 'number') {
        try {
          const size = fs.fstatSync(fd0).size, buf = Buffer.alloc(1 << 20);
          let left = 0, n;
          while (left <= 64 * 2 ** 20 && (n = fs.readSync(fd0, buf, 0, buf.length, null)) > 0) left += n;
          stdinPos = left > 64 * 2 ** 20 ? size : Math.max(0, size - left);
        } catch (e) {
          stdinPos = 0;
        }
        try {
          fs.closeSync(fd0);
        } catch (e) {
          /* (closed) */
        }
      }
      // what the program needs next to what it wrote (fastp's report: its plots' script)
      if (!signal && !spawnError && AFTER[prog.name]) {
        try {
          AFTER[prog.name](prog, args, cwd);
        } catch (e) {
          /* (without it) */
        }
      }
      // what it printed among its messages: the page's names for the folders
      if (!io.merge && io.stderr) unmapFile(toDisk(io.stderr), ctx, links);
      else if (io.merge && io.stdout) unmapFile(toDisk(io.stdout), ctx, links);
      // the example data: anything changed there is undone (and the page says so)
      let refused = [], denied = [];
      if (ex) {
        try {
          const r = syncExamples(ex.src, ex.copy);
          refused = r.refused.map((x) => ex.at + '/' + x);
          denied = r.denied.map((x) => ex.at + '/' + x);
        } catch (e) {
          /* (left as it is) */
        }
      }
      const sig = signal ? os.constants.signals[signal] || 9 : 0;
      let error = null;
      if (spawnError) error = `${prog.name}: the native program could not be started (${spawnError.message})`;
      else if (job.killed) error = 'Killed';
      else if (signal) error = SIGNAL_TEXT[signal] || `Terminated by signal ${signal}`;
      resolve({
        code: job.killed || spawnError ? null : signal ? 128 + sig : code,
        error,
        stdinPos,
        stdinMax: stdinPos,
        order: [],
        memory: null,
        native: true,
        secs: (Date.now() - started) / 1000,
        refused,
        denied
      });
    };
    child.once('error', (e) => finish(null, null, e));
    child.once('exit', (code, signal) => finish(code, signal, null));
  });
}

/* After a run: fastp's HTML report loads its plots' script (Plotly.js 1.2.0) from a file next to it, not from the web
   (Native Workbench's change to fastp's report, for use without a network): the runner puts the file there when it is
   not there yet – as Native Workbench did. */
const optionValue = (args, short, long) => {
  let v = null;
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a === short || a === long) v = args[++i];
    else if (a.startsWith(long + '=')) v = a.slice(long.length + 1);
  }
  return v;
};
const AFTER = {
  fastp(prog, args, cwd) {
    const html = path.resolve(cwd, optionValue(args, '-h', '--html') || 'fastp.html');
    const asset = path.join(path.dirname(prog.exe), 'plotly-1.2.0.min.js'), dest = path.join(path.dirname(html), 'plotly-1.2.0.min.js');
    if (fs.existsSync(html) && fs.existsSync(asset) && !fs.existsSync(dest)) fs.copyFileSync(asset, dest);
  }
};

const SIGNAL_TEXT = { SIGSEGV: 'Segmentation fault', SIGABRT: 'Aborted', SIGBUS: 'Bus error', SIGFPE: 'Floating point exception', SIGILL: 'Illegal instruction', SIGKILL: 'Killed', SIGTERM: 'Terminated' };

/** stop a native program by force – and whatever it started */
export function killNative(job) {
  const c = job.child;
  if (!c || !c.pid) return false;
  try {
    if (isWin) spawnSync('taskkill', ['/PID', String(c.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
    else process.kill(-c.pid, 'SIGKILL');
  } catch (e) {
    try {
      c.kill('SIGKILL');
    } catch (x) {
      /* (ended) */
    }
  }
  return true;
}

/** the messages of a program (a file of at most 1 MiB, UTF-8): the folders on disk get the page's names back */
function unmapFile(file, ctx, links) {
  if (!file) return;
  try {
    const st = fs.statSync(file);
    if (!st.size || st.size > 2 ** 20) return;
    const buf = fs.readFileSync(file);
    let text;
    try {
      text = new TextDecoder('utf-8', { fatal: true }).decode(buf);
    } catch (e) {
      return;
    }
    const t2 = unmapText(text, ctx, links);
    if (t2 !== text) fs.writeFileSync(file, t2);
  } catch (e) {
    /* (as it is) */
  }
}
export function unmapText(text, ctx, links) {
  const pairs = [];
  const fwd = (p) => (isWin ? p.replace(/\\/g, '/') : p);
  const linkFor = (v) => {
    for (const [target, link] of links) if (v === target || v.startsWith(target + '/')) return link + v.slice(target.length);
    return v.startsWith(ctx.ROOT + '/') ? v.slice(ctx.ROOT.length) : v;
  };
  if (ctx.examples) pairs.push([ctx.examples.copy, linkFor(ctx.examples.at)]);
  for (const m of ctx.mounts) pairs.push([m.dir, m.at === '/' ? '' : linkFor(m.at)]);
  pairs.sort((a, b) => b[0].length - a[0].length);
  // (a folder's path only where it ends: the folder /tmp/ws is not in /tmp/ws2)
  const esc = (x) => x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  for (const [dir, name] of pairs)
    for (const d of new Set([dir, fwd(dir)])) {
      if (!d || !text.includes(d)) continue;
      text = text.replace(new RegExp(esc(d) + '(?=$|[\\\\/\\s"\'`:,;)\\]])', 'g'), (x, at, all) => name || (/[\\\\/]/.test(all[at + x.length] || '') ? '' : '/'));
    }
  return text;
}
