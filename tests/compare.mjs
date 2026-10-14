#!/usr/bin/env node
/* Compare a run of the parity suite with two runs of the reference version.
     node compare.mjs reference-1.json reference-2.json candidate.json
   What differs between the two reference runs is not determined by the workbench (times, durations, the moment a
   forced stop came): there the candidate is compared with digits masked, and a file only by its kind and
   permissions – and so are the files that suite.mjs names as carrying the time of the run (timeStamped), which the
   steps that make them check in another way. Everything else must be identical: exit status, output, messages, and
   every file in the home folder – its kind, size, permissions and bytes. Exit status 1 when anything differs.
     --content   a file whose bytes differ, but whose content is the same (c: unpacked, times masked – recorded for the
                 local runner's files, see harness.mjs), counts as the same, with a note; so does the index of such a
                 file (.bai, .csi, .tbi, .gzi: it points into other bytes). For two builds of a program that compress
                 differently: the native programs against the WebAssembly ones. */
import fs from 'node:fs';
import { timeStamped } from './suite.mjs';

const CONTENT = process.argv.includes('--content');
const [fa, fb, fc] = process.argv.slice(2).filter((a) => !a.startsWith('--'));
if (!fc) {
  console.error('usage: node compare.mjs reference-1.json reference-2.json candidate.json');
  process.exit(2);
}
// (a file whose bytes a backend holds: 'aioli' in the browser, 'local' in the local runner – the same, for this)
const held = (s) => s.replace(/"(k|kind)":(\s*)"(aioli|local)"/g, '"$1":$2"held"');
const load = (f) => {
  const j = JSON.parse(held(fs.readFileSync(f, 'utf8')));
  return new Map(j.results.map((r) => [r.id, r.result]));
};
const A = load(fa), B = load(fb), C = load(fc);
const mask = (s) => (s == null ? s : String(s).replace(/\d+(\.\d+)?/g, '#'));
const problems = [], notes = [];
let checked = 0, volatile = 0;

function field(id, name, a, b, c) {
  checked++;
  const sa = JSON.stringify(a), sb = JSON.stringify(b), sc = JSON.stringify(c);
  if (sa === sb) {
    if (sc !== sa) problems.push({ id, name, reference: a, candidate: c });
    return;
  }
  volatile++;
  if (JSON.stringify(mask(sa)) !== JSON.stringify(mask(sc)) && JSON.stringify(mask(sb)) !== JSON.stringify(mask(sc)))
    problems.push({ id, name, reference: a, reference2: b, candidate: c, note: 'differs between the reference runs too; compared with digits masked' });
}

function files(id, a, b, c) {
  const map = (xs) => new Map((xs || []).map((f) => [f.p, f]));
  const ma = map(a), mb = map(b), mc = map(c);
  for (const p of new Set([...ma.keys(), ...mc.keys()])) {
    const fa = ma.get(p), fb = mb.get(p), fc = mc.get(p);
    checked++;
    if (!fa || !fc) {
      // (there in one reference run only: a file whose existence depends on timing)
      if (!fa && fb && fc) continue;
      if (fa && !fb && !fc) continue;
      problems.push({ id, name: 'file ' + p, reference: fa || null, candidate: fc || null });
      continue;
    }
    const stamped = timeStamped.find(([re]) => re.test(p));
    const same = !stamped && JSON.stringify(fa) === JSON.stringify(fb);
    if (same) {
      if (JSON.stringify(fa) !== JSON.stringify(fc)) {
        // (--content: the same content, compressed differently – or an index into such bytes)
        const keys = ['p', 'k', 'mode', 'ro', 'perm', 'prot'];
        const meta = JSON.stringify(keys.map((k) => fa[k])) === JSON.stringify(keys.map((k) => fc[k]));
        const base = p.replace(/\.(bai|csi|tbi|gzi)$/, ''), ba = base !== p ? ma.get(base) : null, bc = base !== p ? mc.get(base) : null;
        if (CONTENT && meta && fa.c && fa.c === fc.c) notes.push(`${id}: ${p} – the same content, compressed differently`);
        else if (CONTENT && meta && ba && bc && ba.c && ba.c === bc.c && ba.h !== bc.h) notes.push(`${id}: ${p} – an index of differently compressed bytes`);
        else problems.push({ id, name: 'file ' + p, reference: fa, candidate: fc });
      }
      continue;
    }
    volatile++;
    // (bytes that differ from run to run – a time in a header, compressed – need not keep their size either; and the
    // files that suite.mjs names as carrying the time of the run are compared so, whether or not the two runs differ)
    const keys = ['p', 'k', 'mode', 'ro', 'perm', 'prot'];
    const pick = (f) => JSON.stringify(keys.map((k) => f[k]));
    if (pick(fa) !== pick(fc)) problems.push({ id, name: 'file ' + p, reference: fa, reference2: fb, candidate: fc, note: 'its bytes differ between the reference runs; compared by ' + keys.join(', ') });
  }
}

for (const [id, a] of A) {
  const b = B.get(id), c = C.get(id);
  if (!b) continue;
  if (!c) {
    problems.push({ id, name: 'step', reference: 'ran', candidate: 'missing' });
    continue;
  }
  for (const k of ['failure', 'code', 'stdout', 'stderr', 'cwd', 'value', 'lost', 'screen']) if (k in a || k in c) field(id, k, a[k], b[k], c[k]);
  field(id, 'page errors', a.errors, b.errors, c.errors);
  files(id, a.files, b.files, c.files);
}
const short = (v) => {
  const s = typeof v === 'string' ? v : JSON.stringify(v);
  return s && s.length > 600 ? s.slice(0, 600) + ' …' : s;
};
for (const p of problems) {
  console.log(`✗ ${p.id} · ${p.name}${p.note ? '  (' + p.note + ')' : ''}`);
  console.log('    reference: ' + short(p.reference));
  if ('reference2' in p) console.log('    reference2: ' + short(p.reference2));
  console.log('    candidate: ' + short(p.candidate));
}
if (notes.length) console.log(`(${notes.length} files with the same content, compressed differently, or indexes of them – e.g. ${notes.slice(0, 3).join('; ')})`);
console.log(`${A.size} steps, ${checked} comparisons (${volatile} vary between the reference runs and were masked): ${problems.length ? problems.length + ' DIFFERENCES' : 'identical'}`);
process.exit(problems.length ? 1 : 0);
