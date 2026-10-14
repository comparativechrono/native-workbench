#!/usr/bin/env node
/* The SAMtools prototype of the memory review (see docs/execution-backends.md): from the page, with the local runner,
   sort a BAM file several times larger than the memory a program may have (2 GiB: the WebAssembly builds are 32-bit),
   with the sort's memory bounded and its temporary files on disk – and measure what it takes.

     node prototype/sort-big-bam.mjs --bam unsorted.bam --workspace FOLDER [--mem 256M] [--native PATH/samtools]
                                     [--out results/prototype-sort.json] [--keep]

   --bam        an unsorted BAM file (make-unsorted-sam.mjs makes one); it is linked into the workspace as unsorted.bam
   --workspace  a new folder on the same disk: the runner's folder (~)
   --mem        samtools sort -m (the memory of the sort)
   --native     a native samtools of the same version (1.17): it sorts the same file with the same options, and the
                result is compared with the page's
   --keep       leave the workspace as it is at the end (otherwise what the run made is removed again)

   It checks that the sort ends with status 0; that sorted.bam is a valid BAM, sorted by coordinate, whose header (but
   for its @PG lines, which name the command) and records (all of them, in order) are those of the native sort; that
   samtools can index it and read a region of it, as the native one does; that the page never held its bytes; and that
   a reload of the page finds the files again. It measures the wall time, the program's WebAssembly memory, the peak
   resident memory of the runner, the browser's memory (its JavaScript heap; the resident memory of its processes),
   the peak size of the temporary files on disk, and what passed between the page and the runner.
   Linux only (the memory of the processes is read in /proc). Exit status 1 when a check fails. */
import { openWorkbench } from '../lib/harness.mjs';
import { spawn, spawnSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const argv = process.argv.slice(2);
const opt = (name, dflt) => {
  const i = argv.indexOf('--' + name);
  return i >= 0 ? argv[i + 1] : dflt;
};
const BAM = opt('bam') && path.resolve(opt('bam'));
const WS = opt('workspace') && path.resolve(opt('workspace'));
const MEM = opt('mem', '256M');
const NATIVE = opt('native');
const OUT = path.resolve(opt('out', path.join(ROOT, 'tests', 'results', 'prototype-sort.json')));
if (!BAM || !WS) {
  console.error('usage: node prototype/sort-big-bam.mjs --bam unsorted.bam --workspace FOLDER [--mem 256M] [--native samtools] [--out FILE] [--keep]');
  process.exit(2);
}

let failed = 0, passed = 0;
const check = (name, ok, detail) => {
  if (ok) passed++;
  else failed++;
  console.log(`${ok ? '✓' : '✗'} ${name}${!ok && detail !== undefined ? '\n    ' + JSON.stringify(detail).slice(0, 600) : ''}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const GiB = 2 ** 30, MiB = 2 ** 20;
const human = (n) => (n == null ? '–' : n >= GiB ? (n / GiB).toFixed(2) + ' GiB' : n >= MiB ? (n / MiB).toFixed(1) + ' MiB' : n >= 1024 ? (n / 1024).toFixed(1) + ' KiB' : n + ' bytes');
const secs = (t0) => Math.round((Date.now() - t0) / 100) / 10;

// ---------------------------------------------------------------- the folder
fs.mkdirSync(WS, { recursive: true });
const input = path.join(WS, 'unsorted.bam');
if (!fs.existsSync(input))
  try {
    fs.linkSync(BAM, input);
  } catch (e) {
    fs.symlinkSync(BAM, input);
  }
for (const f of ['sorted.bam', 'sorted.bam.bai', 'native.bam']) fs.rmSync(path.join(WS, f), { force: true });
const inputSize = fs.statSync(input).size;

// ---------------------------------------------------------------- what is measured while the page works
/** resident memory of a process (now, and its peak) */
function mem(pid) {
  try {
    const s = fs.readFileSync(`/proc/${pid}/status`, 'utf8');
    const kb = (k) => {
      const m = new RegExp('^' + k + ':\\s+(\\d+) kB', 'm').exec(s);
      return m ? Number(m[1]) * 1024 : 0;
    };
    return { rss: kb('VmRSS'), peak: kb('VmHWM') };
  } catch (e) {
    return null;
  }
}
/** the processes below this one, but for the runner: the browser's */
function browserPids(runnerPid) {
  const kids = new Map();
  for (const d of fs.readdirSync('/proc')) {
    if (!/^\d+$/.test(d)) continue;
    try {
      const stat = fs.readFileSync(`/proc/${d}/stat`, 'utf8');
      const ppid = Number(stat.slice(stat.lastIndexOf(')') + 2).split(' ')[1]);
      if (!kids.has(ppid)) kids.set(ppid, []);
      kids.get(ppid).push(Number(d));
    } catch (e) {
      /* (gone) */
    }
  }
  const out = [], todo = [...(kids.get(process.pid) || [])];
  while (todo.length) {
    const p = todo.pop();
    if (p === runnerPid) continue;
    let cmd = '';
    try {
      cmd = fs.readFileSync(`/proc/${p}/cmdline`, 'utf8');
    } catch (e) {
      continue;
    }
    if (/chrom|headless/i.test(cmd)) out.push({ pid: p, renderer: cmd.includes('--type=renderer') });
    todo.push(...(kids.get(p) || []));
  }
  return out;
}
/** the files of the folder: the temporary files of the sort (samtools' NAME.tmp.NNNN.bam, and the runner's own
    temporary folder), the output so far */
function diskUse() {
  let temp = 0, output = 0, n = 0;
  const walk = (d, inTmp) => {
    let names = [];
    try {
      names = fs.readdirSync(d, { withFileTypes: true });
    } catch (e) {
      return;
    }
    for (const e of names) {
      const p = path.join(d, e.name);
      if (e.isDirectory()) walk(p, inTmp || p === path.join(WS, '.workbench', 'tmp'));
      else if (e.isFile())
        try {
          const s = fs.statSync(p).size;
          if (inTmp || /\.tmp\.\d{4}\.bam$/.test(e.name)) (temp += s), n++;
          else if (e.name === 'sorted.bam') output += s;
        } catch (x) {
          /* (gone) */
        }
    }
  };
  walk(WS, false);
  return { temp, output, tempFiles: n, free: fs.statfsSync(WS).bavail * fs.statfsSync(WS).bsize };
}

const wb = await openWorkbench(ROOT, { runner: true, workspace: WS });
const runnerPid = wb.server.pid;
const cdp = await wb.page.context().newCDPSession(wb.page);
await cdp.send('Network.enable');
await cdp.send('Performance.enable');
// what passes between the page and the runner (the requests of the API; the page itself and the programs' files of
// the site are not counted)
const net = { requests: 0, sent: 0, received: 0, largest: 0, largestUrl: '' };
const pending = new Map();
cdp.on('Network.requestWillBeSent', (e) => {
  if (!/\/api\/v1\//.test(e.request.url)) return;
  pending.set(e.requestId, e.request.url);
  net.requests++;
  net.sent += e.request.postData ? Buffer.byteLength(e.request.postData) : 0;
});
cdp.on('Network.loadingFinished', (e) => {
  const u = pending.get(e.requestId);
  if (!u) return;
  pending.delete(e.requestId);
  net.received += e.encodedDataLength;
  if (e.encodedDataLength > net.largest) {
    net.largest = e.encodedDataLength;
    net.largestUrl = u.replace(/^https?:\/\/[^/]+/, '');
  }
});
const heap = async () => {
  try {
    const { metrics } = await cdp.send('Performance.getMetrics');
    const m = Object.fromEntries(metrics.map((x) => [x.name, x.value]));
    return { used: m.JSHeapUsedSize, total: m.JSHeapTotalSize };
  } catch (e) {
    return null;
  }
};

/** run a command line in the terminal, as if typed, and measure it */
async function phase(name, line) {
  const n0 = { ...net }, t0 = Date.now();
  const peak = { runner: 0, runnerPeak: 0, browser: 0, renderer: 0, jsHeap: 0, jsHeapTotal: 0, temp: 0, tempFiles: 0, output: 0, extra: 0, minFree: Infinity };
  let start = null; // (the first sample: what the browser and the runner had before the command)
  const series = [];
  let stop = false;
  const sampler = (async () => {
    while (!stop) {
      const r = mem(runnerPid) || { rss: 0, peak: 0 };
      let b = 0, rend = 0;
      for (const p of browserPids(runnerPid)) {
        const m = mem(p.pid);
        if (!m) continue;
        b += m.rss;
        if (p.renderer) rend = Math.max(rend, m.rss);
      }
      const h = (await heap()) || { used: 0, total: 0 };
      const d = diskUse();
      peak.runner = Math.max(peak.runner, r.rss);
      peak.runnerPeak = Math.max(peak.runnerPeak, r.peak);
      peak.browser = Math.max(peak.browser, b);
      peak.renderer = Math.max(peak.renderer, rend);
      peak.jsHeap = Math.max(peak.jsHeap, h.used);
      peak.jsHeapTotal = Math.max(peak.jsHeapTotal, h.total);
      peak.temp = Math.max(peak.temp, d.temp);
      peak.tempFiles = Math.max(peak.tempFiles, d.tempFiles);
      peak.output = Math.max(peak.output, d.output);
      peak.extra = Math.max(peak.extra, d.temp + d.output);
      peak.minFree = Math.min(peak.minFree, d.free);
      if (!start) start = { runner: r.rss, browser: b, renderer: rend, jsHeap: h.used };
      series.push({ t: secs(t0), runnerRSS: r.rss, browserRSS: b, jsHeap: h.used, temp: d.temp, output: d.output });
      await sleep(1000);
    }
  })();
  const res = await wb.page.evaluate(async (l) => {
    const T = MG.app.term, n = T.transcript.length;
    const code = await T.exec(l);
    const rec = T.transcript.length > n ? T.transcript[T.transcript.length - 1] : null;
    return { code, stdout: rec ? rec.stdout : null, stderr: rec ? rec.stderr : null };
  }, line);
  const wall = secs(t0);
  stop = true;
  await sampler;
  const traffic = { requests: net.requests - n0.requests, sent: net.sent - n0.sent, received: net.received - n0.received };
  const p = { name, line, ...res, wall, start, peak, traffic, series: series.filter((s, i) => i % 5 === 0 || i === series.length - 1) };
  console.log(`  ${name}: ${wall} s, exit ${res.code}; page↔runner ${traffic.requests} requests, ${human(traffic.sent)} sent, ${human(traffic.received)} received`);
  return p;
}
const lastRun = () => {
  const lines = fs.readFileSync(path.join(WS, '.workbench', 'runs.jsonl'), 'utf8').trim().split('\n');
  return JSON.parse(lines[lines.length - 1]);
};
/** a native program, and its peak resident memory (getrusage of the child: Python's resource module) */
function native(args) {
  const t0 = Date.now();
  const py = 'import resource,subprocess,sys\nr=subprocess.run(sys.argv[1:])\nsys.stderr.write("\\nMAXRSS %d\\n" % resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)\nsys.exit(r.returncode)';
  const r = spawnSync('python3', ['-c', py, NATIVE, ...args], { stdio: ['ignore', 'pipe', 'pipe'], maxBuffer: 256 * MiB });
  const m = /MAXRSS (\d+)/.exec(String(r.stderr));
  return { code: r.status, stdout: String(r.stdout), stderr: String(r.stderr).replace(/\nMAXRSS \d+\n/, ''), wall: secs(t0), maxRSS: m ? Number(m[1]) * 1024 : null };
}
/** a hash of what a native command prints (the records of a BAM file: samtools view) */
function nativeHash(args) {
  return new Promise((resolve, reject) => {
    const p = spawn(NATIVE, args, { stdio: ['ignore', 'pipe', 'inherit'] });
    const h = crypto.createHash('sha256');
    let n = 0;
    p.stdout.on('data', (c) => {
      h.update(c);
      n += c.length;
    });
    p.on('error', reject);
    p.on('close', (code) => resolve({ code, sha256: h.digest('hex'), bytes: n }));
  });
}
/** a hash of a file from an offset on */
function fileHash(file, start) {
  return new Promise((resolve, reject) => {
    const h = crypto.createHash('sha256');
    fs.createReadStream(file, { start })
      .on('data', (c) => h.update(c))
      .on('error', reject)
      .on('end', () => resolve(h.digest('hex')));
  });
}
/** where the records begin: htslib writes the header in BGZF blocks of its own (it flushes after it), so the records
    begin with the first block after it. The blocks are read until the header (magic, text, references) is complete;
    null if it ends inside a block. */
function afterHeader(file) {
  const fd = fs.openSync(file, 'r');
  let off = 0, data = Buffer.alloc(0);
  try {
    for (let k = 0; k < 64; k++) {
      const h = Buffer.alloc(18);
      if (fs.readSync(fd, h, 0, 18, off) < 18) return null;
      const bsize = h.readUInt16LE(16) + 1, block = Buffer.alloc(bsize);
      fs.readSync(fd, block, 0, bsize, off);
      data = Buffer.concat([data, zlib.inflateRawSync(block.subarray(18, bsize - 8))]);
      off += bsize;
      // magic, l_text, text, n_ref, then each reference: l_name, name, l_ref
      if (data.length < 8) continue;
      let p = 8 + data.readInt32LE(4);
      if (data.length < p + 4) continue;
      const nRef = data.readInt32LE(p);
      p += 4;
      let complete = true;
      for (let i = 0; i < nRef; i++) {
        if (data.length < p + 4) {
          complete = false;
          break;
        }
        p += 4 + data.readInt32LE(p) + 4;
      }
      if (!complete || data.length < p) continue;
      return data.length === p ? off : null;
    }
  } finally {
    fs.closeSync(fd);
  }
  return null;
}

// ---------------------------------------------------------------- the run
const report = {
  date: new Date().toISOString(),
  machine: { os: `${os.type()} ${os.release()}`, cpu: os.cpus()[0].model, cpus: os.cpus().length, memory: os.totalmem() },
  versions: { node: process.versions.node, browser: wb.browser.version(), playwright: JSON.parse(fs.readFileSync(path.join(ROOT, 'tests', 'node_modules', 'playwright', 'package.json'), 'utf8')).version },
  build: {
    samtools: 'samtools 1.17 with htslib 1.17, compiled by Biowasm (assets/vendor/biowasm/samtools/1.17)',
    emscripten: '2.0.25 (Biowasm Dockerfile-dev: emscripten/emsdk:2.0.25)',
    flags: '-O2 -s USE_ZLIB=1 -s USE_BZIP2=1, liblzma 5.2.5; -s MODULARIZE=1 -s ENVIRONMENT="web,worker" -s ALLOW_MEMORY_GROWTH=1 -s INVOKE_RUN=0 -s FORCE_FILESYSTEM=1 (biowasm-build/bin/shared.sh, tools/samtools/compile.sh)',
    memory: 'wasm32: INITIAL_MEMORY 16 MiB, growth to 2 GiB at most (the build default of Emscripten 2.0.25)',
    wasmSha256: crypto.createHash('sha256').update(fs.readFileSync(path.join(ROOT, 'assets', 'vendor', 'biowasm', 'samtools', '1.17', 'samtools.wasm'))).digest('hex')
  },
  dataset: { file: BAM, bytes: inputSize },
  command: `samtools sort -m ${MEM} -o sorted.bam unsorted.bam`,
  phases: {},
  checks: []
};
const keep = (name, p) => (report.phases[name] = p);
console.log(`input: ${human(inputSize)} (${BAM})`);

{
  const id = await wb.page.evaluate(async () => (await MG.exec.whenChosen(), MG.exec.id));
  check('the page runs its programs in the local runner', id === 'local', id);
  const e = await wb.page.evaluate(() => {
    const e = MG.app.term.fs.get(MG.app.term.fs.home + '/unsorted.bam');
    return e && { kind: e.kind, size: e.size };
  });
  check('the input is in the terminal, and its bytes stay on disk', e && e.kind === 'local' && e.size === inputSize, e);
  const v = await phase('version', 'samtools --version | head -2');
  report.versions.samtoolsInPage = (v.stdout || '').trim();
}

const sort = keep('sort', await phase('sort', `cd ~ && samtools sort -m ${MEM} -o sorted.bam unsorted.bam`));
sort.run = lastRun();
check('samtools sort ends with status 0', sort.code === 0 && sort.run.code === 0, { code: sort.code, stderr: sort.stderr, run: sort.run });
const outSize = fs.existsSync(path.join(WS, 'sorted.bam')) ? fs.statSync(path.join(WS, 'sorted.bam')).size : 0;
report.dataset.sortedBytes = outSize;
check(`an input larger than the 2 GiB a wasm32 program can have (${human(inputSize)}), sorted in ${human(sort.run.memory)} of WebAssembly memory`, sort.run.memory > 0 && sort.run.memory <= 2 * GiB && inputSize > 2 * GiB, sort.run);
check('its temporary files were on disk', sort.peak.temp > 0 && sort.peak.tempFiles > 0, sort.peak);
check('the page received none of the data (less than 1 MiB in all, for a sort of ' + human(inputSize) + ')', sort.traffic.received + sort.traffic.sent < MiB, sort.traffic);
{
  const e = await wb.page.evaluate(() => {
    const e = MG.app.term.fs.get(MG.app.term.fs.home + '/sorted.bam');
    return e && { kind: e.kind, size: e.size, hasBytes: !!(e.bytes || e.blob || e.data) };
  });
  check('sorted.bam is in the terminal, its bytes on disk', e && e.kind === 'local' && e.size === outSize && !e.hasBytes, e);
}

const index = keep('index', await phase('index', 'samtools index sorted.bam'));
index.run = lastRun();
check('samtools index sorted.bam', index.code === 0 && fs.existsSync(path.join(WS, 'sorted.bam.bai')), index);
const idx = keep('idxstats', await phase('idxstats', 'samtools idxstats sorted.bam'));
const region = keep('region', await phase('region', 'samtools view -c sorted.bam chr21:20000000-30000000'));
const head = keep('header', await phase('header', 'samtools view -H sorted.bam | head -1'));
check('the header says it is sorted by coordinate', /^@HD\t.*SO:coordinate/.test(head.stdout || ''), head.stdout);

// ---- a reload of the page
{
  const t0 = Date.now();
  await wb.page.reload();
  await wb.page.waitForFunction(() => !!(window.MG && MG.app && MG.app.term), null, { timeout: 120000 });
  const id = await wb.page.evaluate(async () => (await MG.exec.whenChosen(), MG.exec.id));
  const e = await wb.page.evaluate(() => {
    const f = MG.app.term.fs, out = {};
    for (const n of ['unsorted.bam', 'sorted.bam', 'sorted.bam.bai']) {
      const e = f.get(f.home + '/' + n);
      out[n] = e && { kind: e.kind, size: e.size };
    }
    return out;
  });
  report.reload = { secs: secs(t0), entries: e };
  check('after a reload of the page: the same files, still on disk', id === 'local' && e['sorted.bam'] && e['sorted.bam'].kind === 'local' && e['sorted.bam'].size === outSize && e['sorted.bam.bai'] && e['unsorted.bam'] && e['unsorted.bam'].size === inputSize, { id, e });
  const again = keep('afterReload', await phase('after reload', 'cd ~ && samtools view -c sorted.bam chrM && ls -l sorted.bam'));
  check('… and samtools reads them', again.code === 0 && /^\d+\n/.test(again.stdout || '') && (again.stdout || '').includes(String(outSize)), again);
  report.afterReloadCount = Number((again.stdout || '').split('\n')[0]);
}
report.browserErrors = wb.errors.slice();
check('no errors in the page', wb.errors.length === 0, wb.errors);
await wb.close();

// ---------------------------------------------------------------- the native samtools of the same version
if (NATIVE) {
  const v = native(['--version']);
  report.versions.native = v.stdout.split('\n').slice(0, 2).join('; ');
  report.versions.nativeBuild = 'built from samtools-1.17.tar.bz2 (with htslib 1.17): ./configure --without-curses --disable-libcurl CFLAGS=-O2; ' + spawnSync('gcc', ['--version']).stdout.toString().split('\n')[0];
  const sorted = path.join(WS, 'sorted.bam'), ref = path.join(WS, 'native.bam');
  const q = native(['quickcheck', '-v', sorted]);
  check('native samtools quickcheck: sorted.bam is a complete BAM file', q.code === 0 && q.stdout.trim() === '', q);
  // the same sort, with the same options, by the native program
  console.log('  native sort …');
  const ns = native(['sort', '-m', MEM, '-o', ref, input]);
  report.native = { sort: { wall: ns.wall, maxRSS: ns.maxRSS, code: ns.code } };
  console.log(`  native sort: ${ns.wall} s, peak RSS ${human(ns.maxRSS)}`);
  check('the native sort ends with status 0', ns.code === 0, ns);
  const pg = (t) => t.split('\n').filter((l) => !l.startsWith('@PG')).join('\n');
  const h1 = native(['view', '-H', sorted]).stdout, h2 = native(['view', '-H', ref]).stdout;
  check('the headers are the same, but for their @PG lines (which name the command)', pg(h1) === pg(h2) && h1 !== '', { page: h1.split('\n').filter((l) => l.startsWith('@PG')), native: h2.split('\n').filter((l) => l.startsWith('@PG')) });
  console.log('  comparing the records …');
  const [r1, r2] = await Promise.all([nativeHash(['view', sorted]), nativeHash(['view', ref])]);
  report.native.records = { page: r1, native: r2 };
  check(`the records are the same, in the same order (${human(r1.bytes)} of SAM)`, r1.code === 0 && r2.code === 0 && r1.sha256 === r2.sha256 && r1.bytes > 0, { r1, r2 });
  // (not a check – the compressed bytes depend on the version of zlib, which the rules of equivalence leave out)
  const o1 = afterHeader(sorted), o2 = afterHeader(ref);
  if (o1 != null && o2 != null) {
    const [b1, b2] = await Promise.all([fileHash(sorted, o1), fileHash(ref, o2)]);
    report.native.bytesAfterHeader = { identical: b1 === b2, page: b1, native: b2, sizes: [outSize - o1, fs.statSync(ref).size - o2] };
    console.log(`  the compressed bytes after the header: ${b1 === b2 ? 'identical' : 'different'}`);
  }
  const nIdx = native(['index', ref]), nStats = native(['idxstats', ref]), nRegion = native(['view', '-c', ref, 'chr21:20000000-30000000']), nM = native(['view', '-c', ref, 'chrM']);
  check('idxstats as the native samtools gives them', nIdx.code === 0 && idx.stdout === nStats.stdout && nStats.stdout.split('\n').length > 20, { page: idx.stdout && idx.stdout.slice(0, 200), native: nStats.stdout.slice(0, 200) });
  check('the reads of a region, as the native samtools counts them', region.stdout === nRegion.stdout && Number(region.stdout) > 0, { page: region.stdout, native: nRegion.stdout });
  check('… and after the reload', report.afterReloadCount === Number(nM.stdout), { page: report.afterReloadCount, native: nM.stdout });
  const total = native(['view', '-c', ref]);
  report.dataset.reads = Number(total.stdout);
  fs.rmSync(ref, { force: true });
  fs.rmSync(ref + '.bai', { force: true });
}

// ---------------------------------------------------------------- the report
report.checks = { passed, failed };
fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, JSON.stringify(report, null, 1));
const s = report.phases.sort;
console.log(`
SAMtools prototype – ${report.command}
  input ${human(inputSize)}${report.dataset.reads ? ` (${report.dataset.reads.toLocaleString('en')} reads)` : ''}; output ${human(outSize)}
  wall time ${s.wall} s (runner: ${s.run.secs} s)${report.native ? `; native samtools 1.17, same options: ${report.native.sort.wall} s` : ''}
  WebAssembly memory of samtools ${human(s.run.memory)} (at most 2 GiB); runner peak RSS ${human(Math.max(s.run.maxRSS || 0, s.peak.runnerPeak))}${report.native ? `; native peak RSS ${human(report.native.sort.maxRSS)}` : ''}
  browser: JS heap ${human(s.start.jsHeap)} before, ${human(s.peak.jsHeap)} at most; its processes ${human(s.start.browser)} resident before, ${human(s.peak.browser)} at most (renderer ${human(s.start.renderer)} → ${human(s.peak.renderer)})
  temporary files ${human(s.peak.temp)} at most (${s.peak.tempFiles} at once); input + temporary + output on disk ${human(inputSize + s.peak.extra)} at most
  page ↔ runner during the sort: ${s.traffic.requests} requests, ${human(s.traffic.sent)} sent, ${human(s.traffic.received)} received
  report: ${OUT}`);
if (!argv.includes('--keep')) for (const f of ['sorted.bam', 'sorted.bam.bai', 'unsorted.bam']) fs.rmSync(path.join(WS, f), { force: true });
console.log(`${passed + failed} checks: ${failed ? failed + ' FAILED' : 'all passed'}`);
process.exit(failed ? 1 : 0);
