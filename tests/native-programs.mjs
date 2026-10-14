#!/usr/bin/env node
/* The native programs of the local runner (runner/native.mjs, native/bin), command by command, three ways:
     page       typed into the workbench's terminal, with the local runner (the native programs);
     direct     the same command line in bash, with the same executables, started by hand (the loader, as the runner
                does) – in a folder of its own;
     reference  the same in bash with the Linux builds of the same sources (native/build.py leaves them in the build
                tree: baselines/bin/NAME-linux).
   page = direct, byte for byte: the runner runs a program as it runs when started by hand – its arguments, working
   folder, input, output and messages (where the page names the folders as it knows them, /data/examples …), exit
   status, and every file it writes. Only what carries the time of the run is compared with the time masked (bcftools'
   Date=, fastp's report, the programs' timings).
   direct = reference: the Cosmopolitan builds compute what the Linux builds of the same source compute. Compressed
   files are compared by what they hold: the two builds' zlib compress differently (Cosmopolitan's is Chromium's), so
   their bytes – and the index files that point into them – may differ.

     node native-programs.mjs [--refs BUILD-TREE/baselines/bin] [--only id,id] [--keep]

   Linux (the loader for Linux starts the programs by hand). Without --refs (or NATIVE_REFS) the reference column is
   left out. Exit status 1 when anything differs. */
import { openWorkbench, runStep } from './lib/harness.mjs';
import { unmapText } from '../runner/native.mjs';
import { look, maskText } from './lib/content.mjs';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const argv = process.argv.slice(2);
const opt = (name, dflt) => {
  const i = argv.indexOf('--' + name);
  return i >= 0 ? argv[i + 1] : dflt;
};
const REFS = opt('refs', process.env.NATIVE_REFS || '');
const ONLY = opt('only', '') ? new Set(opt('only').split(',')) : null;
const BIN = path.join(ROOT, 'native', 'bin');
const manifest = JSON.parse(fs.readFileSync(path.join(BIN, 'programs.json'), 'utf8'));
const LOADER = path.join(BIN, manifest.loaders['linux-x64'].file);

/* The commands, in order (later ones use what earlier ones made). $EX is the example data: /data/examples in the page,
   and the same folder on disk (the runner's copy of it) in bash – so that both give the programs the same paths. */
const STEPS = [
  // (cp: the page gives a copy its bytes when a program next runs – samtools quickcheck, here)
  { id: 'inputs', cmd: 'cp $EX/reads/reference.fa ref.fa && cp $EX/reads/NA12878_R1.fastq r1.fq && cp $EX/reads/NA12878_R2.fastq r2.fq && cp $EX/somatic/tumor.bam tumor.bam && samtools quickcheck tumor.bam && echo copied' },
  // seqtk
  { id: 'seqtk-fqchk', cmd: 'seqtk fqchk r1.fq | head -5' },
  { id: 'seqtk-seq', cmd: 'seqtk seq -a r1.fq | head -4; seqtk comp ref.fa' },
  { id: 'seqtk-sample', cmd: 'seqtk sample -s 11 r1.fq 100 > s.fq && seqtk trimfq -q 0.05 r1.fq | seqtk seq -A - | grep -c "^>"' },
  // minimap2
  { id: 'minimap2', cmd: 'minimap2 -ax sr ref.fa r1.fq r2.fq > mm.sam 2> mm.log; echo code=$?; grep -c . mm.sam' },
  { id: 'minimap2-threads', cmd: 'minimap2 -t 2 -ax sr ref.fa r1.fq r2.fq 2>/dev/null | grep -v "^@PG" | md5sum; grep -v "^@PG" mm.sam | md5sum' },
  { id: 'minimap2-index', cmd: 'minimap2 -d ref.mmi ref.fa 2>/dev/null && minimap2 -ax sr ref.mmi r1.fq r2.fq 2>/dev/null | grep -v "^@PG" | md5sum' },
  // SAMtools
  { id: 'faidx', cmd: 'samtools faidx ref.fa && cat ref.fa.fai && samtools faidx ref.fa human_CYP2C19:100-160' },
  { id: 'sort-index', cmd: 'samtools sort -o mm.bam mm.sam && samtools index mm.bam && samtools flagstat mm.bam' },
  { id: 'view', cmd: 'samtools view -H mm.bam | grep -v "^@PG"; samtools view mm.bam | head -5 | cut -f1-9' },
  { id: 'idxstats-region', cmd: 'samtools idxstats mm.bam; samtools view -c mm.bam human_CYP2C19:1000-20000' },
  { id: 'stats', cmd: 'samtools stats mm.bam | grep ^SN | cut -f2-' },
  { id: 'depth-coverage', cmd: 'samtools depth -a -r human_CYP2C19:1-20 mm.bam; samtools coverage mm.bam' },
  { id: 'markdup', cmd: 'samtools sort -n -o byname.bam mm.bam && samtools fixmate -m byname.bam fix.bam && samtools sort -o pos.bam fix.bam && samtools markdup pos.bam md.bam 2> md.log; echo code=$?; samtools flagstat md.bam | head -5' },
  { id: 'fastq', cmd: 'samtools fastq -1 o1.fq -2 o2.fq -0 /dev/null -s /dev/null -n mm.bam 2>/dev/null; head -4 o1.fq' },
  { id: 'mpileup', cmd: 'samtools mpileup -f ref.fa -r human_CYP2C19:2540-2550 mm.bam 2>/dev/null' },
  { id: 'merge-quickcheck', cmd: 'samtools view -b -o copy.bam mm.bam && samtools quickcheck -v copy.bam && echo ok; samtools merge -f -c -p merged.bam mm.bam copy.bam && samtools view -c merged.bam' },
  { id: 'dict', cmd: 'samtools dict ref.fa | cut -f1-3' },
  { id: 'subsample', cmd: 'samtools view -s 0.25 -b mm.bam | samtools view -c -' },
  { id: 'stdin-bam', cmd: 'samtools view -c - < mm.bam; cat mm.bam | samtools view -c -' },
  { id: 'bam-in-block', cmd: '{ samtools view -H mm.bam | head -1; samtools view -c tumor.bam; } > block.txt; cat block.txt' },
  { id: 'no-such-file', cmd: 'samtools view -c nosuch.bam; echo code=$?; samtools faidx $EX/reads/nosuch.fa; echo code=$?' },
  // BCFtools
  { id: 'call', cmd: 'bcftools mpileup -f ref.fa mm.bam 2>/dev/null | bcftools call -mv -Oz -o calls.vcf.gz && bcftools index calls.vcf.gz && bcftools view -H calls.vcf.gz | cut -f1-6' },
  { id: 'vcf-stats', cmd: 'bcftools stats calls.vcf.gz | grep ^SN' },
  { id: 'norm-query', cmd: 'bcftools norm -f ref.fa -m -any calls.vcf.gz -Ov -o norm.vcf 2>&1; grep -vc "^#" norm.vcf; bcftools query -f "%CHROM\\t%POS\\t%REF\\t%ALT\\t%QUAL\\n" calls.vcf.gz | head -4' },
  { id: 'filter-region', cmd: 'bcftools filter -s LowQual -e "QUAL<20" calls.vcf.gz -Oz -o filt.vcf.gz && bcftools view -H filt.vcf.gz | cut -f1,2,7 | head -4; bcftools view -H -r human_CYP2C19:1-10000 calls.vcf.gz | wc -l' },
  { id: 'consensus', cmd: 'bcftools consensus -f ref.fa calls.vcf.gz 2>/dev/null > cons.fa; head -c 200 cons.fa' },
  // bgzip and tabix
  { id: 'bgzip', cmd: 'bgzip -c ref.fa > ref.fa.gz && bgzip -t ref.fa.gz && echo ok && bgzip -dc ref.fa.gz | cmp - ref.fa && echo same; bgzip -i -c r1.fq > r1.fq.gz && ls r1.fq.gz*' },
  { id: 'tabix', cmd: 'tabix -f -p vcf calls.vcf.gz && tabix calls.vcf.gz human_CYP2C19:1-5000 | cut -f1-5; tabix -l calls.vcf.gz' },
  // BWA
  { id: 'bwa-index', cmd: 'bwa index ref.fa 2> bwaidx.log; echo code=$?; ls ref.fa.*' },
  { id: 'bwa-mem', cmd: 'bwa mem ref.fa r1.fq r2.fq > bwa.sam 2> bwa.log; echo code=$?; grep -vc "^@" bwa.sam' },
  { id: 'bwa-threads', cmd: 'bwa mem -t 2 -K 10000000 ref.fa r1.fq r2.fq 2>/dev/null | grep -v "^@PG" | md5sum; bwa mem -K 10000000 ref.fa r1.fq r2.fq 2>/dev/null | grep -v "^@PG" | md5sum' },
  { id: 'bwa-readgroup', cmd: "bwa mem -R '@RG\\tID:x\\tSM:x' ref.fa r1.fq r2.fq 2>/dev/null | samtools view -H - | grep '^@RG'" },
  // FreeBayes
  { id: 'freebayes', cmd: 'freebayes -f ref.fa mm.bam > fb.vcf; echo code=$?; grep -vc "^#" fb.vcf' },
  { id: 'freebayes-region', cmd: 'freebayes -f ref.fa -r human_CYP2C19:1000-20000 mm.bam | grep -v "^##" | head -3 | cut -f1-6' },
  // fastp
  { id: 'fastp', cmd: 'fastp -i r1.fq -I r2.fq -o t1.fq -O t2.fq -h fp.html -j fp.json 2> fp.log; echo code=$?; head -4 t1.fq' },
  { id: 'fastp-threads', cmd: 'fastp -i r1.fq -o single.fq -w 2 -j s.json -h s.html 2>/dev/null; grep -c "^@" single.fq' }
];

const INDEX = /\.(bai|csi|tbi|gzi)$/;
/** every file below a folder → { rel: look() } */
function files(dir) {
  const out = {};
  const walk = (d, rel) => {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, e.name), r = rel ? rel + '/' + e.name : e.name;
      if (e.isDirectory()) walk(p, r);
      else if (e.isFile()) out[r] = look(p);
    }
  };
  if (fs.existsSync(dir)) walk(dir, '');
  return out;
}

// ---------------------------------------------------------------- the page
const ws = fs.mkdtempSync(path.join(os.tmpdir(), 'wb-native-'));
const wb = await openWorkbench(ROOT, { runner: true, workspace: ws });
const id = await wb.page.evaluate(async () => (await MG.exec.whenChosen(), MG.exec.id));
if (id !== 'local') throw new Error('the local runner was not used: ' + id);
const native = await wb.page.evaluate(() => MG.exec.capabilities.native || {});
const EXCOPY = path.join(ws, '.workbench', 'examples');
await runStep(wb, { cmd: 'mkdir -p ~/n && cd ~/n && EX=/data/examples', noSnapshot: true });
const page = [];
for (const s of STEPS) {
  if (ONLY && !ONLY.has(s.id)) continue;
  const r = await runStep(wb, { cmd: s.cmd, noSnapshot: true }, { timeoutMs: 180000 });
  // (what the page writes itself – a redirection of messages, 2> FILE – reaches the folder a moment later: now)
  await wb.page.evaluate(() => MG.exec.backend.flush(MG.app.term.fs));
  page.push({ id: s.id, code: r.code, stdout: r.stdout, stderr: r.stderr, failure: r.failure || null, files: files(path.join(ws, 'n')) });
  console.log(`page       ${s.id.padEnd(18)} ${r.failure ? 'FAILED ' + r.failure : 'code ' + r.code}`);
}
const pageErrors = wb.errors.slice();
await wb.close();

// ---------------------------------------------------------------- by hand, in bash
function wrappers(dir, how) {
  fs.mkdirSync(dir, { recursive: true });
  for (const p of manifest.programs) {
    const line = how === 'direct' ? `exec ${JSON.stringify(LOADER)} - ${JSON.stringify(path.join(BIN, p.file))} ${p.name} "$@"` : `exec -a ${p.name} ${JSON.stringify(path.join(REFS, p.name + '-linux'))} "$@"`;
    fs.writeFileSync(path.join(dir, p.name), `#!/bin/bash\n${line}\n`, { mode: 0o755 });
  }
}
function byHand(how) {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), `wb-${how}-`)), work = path.join(base, 'n'), bin = path.join(base, 'bin');
  fs.mkdirSync(work);
  wrappers(bin, how);
  const out = [];
  for (const s of STEPS) {
    if (ONLY && !ONLY.has(s.id)) continue;
    const r = spawnSync('bash', ['-c', `EX=${JSON.stringify(EXCOPY)}; ${s.cmd}`], { cwd: work, env: { PATH: `${bin}:/usr/bin:/bin`, LC_ALL: 'C', HOME: base, TMPDIR: path.join(base) }, encoding: 'utf8', maxBuffer: 64 * 2 ** 20 });
    out.push({ id: s.id, code: r.status, stdout: r.stdout, stderr: r.stderr, files: files(work) });
    console.log(`${how.padEnd(10)} ${s.id.padEnd(18)} code ${r.status}`);
  }
  return { out, base };
}
const direct = byHand('direct');
const reference = REFS && fs.existsSync(REFS) ? byHand('reference') : null;

// ---------------------------------------------------------------- compare
const problems = [], notes = [];
const ctx = { ROOT: '/shared/vfs', STATE: path.join(ws, '.workbench'), examples: { at: '/shared/vfs/data/examples', copy: EXCOPY }, mounts: [{ at: '/shared/vfs/home/user', dir: ws }, { at: '/shared/vfs/tmp', dir: path.join(ws, '.workbench', 'tmp') }] };
const links = [['/shared/vfs/home/user', '/home/user'], ['/shared/vfs/data', '/data']];
// (the page's terminal ends what it shows with a newline, as a terminal shows it; bash's capture is as printed)
const norm = (t) => (t || '').replace(/\n?$/, '\n');
let compared = 0;
function compare(a, b, nameA, nameB, { content }) {
  for (let i = 0; i < a.length; i++) {
    const x = a[i], y = b[i];
    if (!y) continue;
    const where = `${x.id}: ${nameA} / ${nameB}`;
    for (const k of ['code', 'stdout', 'stderr']) {
      compared++;
      let u = x[k], v = y[k];
      // (the page names the folders as it knows them: what was started by hand prints the paths on disk)
      if (k === 'stderr') {
        if (nameA !== 'page') u = unmapText(String(u || ''), ctx, links);
        v = unmapText(String(v || ''), ctx, links);
      }
      if (k !== 'code') {
        u = maskText(norm(u));
        v = maskText(norm(v));
      }
      if (String(u) !== String(v)) problems.push({ where, what: k, a: u, b: v });
    }
    if (x.failure) problems.push({ where, what: 'failure', a: x.failure });
    const names = new Set([...Object.keys(x.files), ...Object.keys(y.files)]);
    for (const n of names) {
      // (fastp's report needs its plots' script next to it: the runner puts it there; by hand nobody does)
      if (n === 'plotly-1.2.0.min.js') continue;
      compared++;
      const f = x.files[n], g = y.files[n];
      if (!f || !g) {
        problems.push({ where, what: 'file ' + n, a: f ? 'there' : 'missing', b: g ? 'there' : 'missing' });
        continue;
      }
      if (f.raw === g.raw) continue;
      if (f.content === g.content && (content || f.kind === 'raw' || f.kind === 'gz')) {
        if (content && f.kind === 'gz') notes.push(`${where}: ${n} – compressed differently, the same content`);
        continue;
      }
      // an index of a compressed file whose bytes differ (compressed differently, or a time in its header): it points
      // into other bytes – compared by its use (the steps that read regions through it)
      const base = n.replace(INDEX, ''), fb = x.files[base], gb = y.files[base];
      if (INDEX.test(n) && fb && gb && fb.raw !== gb.raw && fb.content === gb.content) {
        notes.push(`${where}: ${n} – an index of differently compressed bytes: compared by its use (the steps that read regions)`);
        continue;
      }
      problems.push({ where, what: 'file ' + n, a: f, b: g });
    }
  }
}
// page and direct: the same executables – every byte (but for times, masked in text and in what compressed files hold)
compare(page, direct.out, 'page', 'direct', { content: false });
if (reference) compare(direct.out, reference.out, 'direct', 'reference', { content: true });
const short = (v) => {
  const s = typeof v === 'string' ? v : JSON.stringify(v);
  return s && s.length > 700 ? s.slice(0, 700) + ' …' : s;
};
for (const p of problems) console.log(`✗ ${p.where} · ${p.what}\n    ${short(p.a)}\n    ${short(p.b)}`);
for (const n of notes) console.log(`  (${n})`);
if (pageErrors.length) problems.push({ where: 'page', what: 'errors', a: pageErrors }), console.log('✗ page errors: ' + JSON.stringify(pageErrors));
const programs = Object.entries(native).map(([k, v]) => `${k} ${v.version}`).join(', ');
console.log(`native programs: ${programs}`);
console.log(`${page.length} steps, ${compared} comparisons${reference ? '' : ' (no reference builds: --refs)'}: ${problems.length ? problems.length + ' DIFFERENCES' : 'the same'}`);
if (!argv.includes('--keep')) for (const d of [ws, direct.base, reference && reference.base]) if (d) fs.rmSync(d, { recursive: true, force: true });
process.exit(problems.length ? 1 : 0);
