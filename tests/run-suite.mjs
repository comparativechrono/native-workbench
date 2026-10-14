#!/usr/bin/env node
/* Run the parity suite against one checkout of the workbench and save what happened.
     node run-suite.mjs --root PATH/TO/CHECKOUT --out results.json [--query '?x=y'] [--init page-script.js] [--only a,b]
   --init: a script evaluated in the page after it has loaded and before the first step (to put a test backend in
   place, for instance). */
import { openWorkbench, runStep } from './lib/harness.mjs';
import { suite } from './suite.mjs';
import fs from 'node:fs';
import path from 'node:path';

const args = process.argv.slice(2);
const opt = (name, dflt) => {
  const i = args.indexOf('--' + name);
  return i >= 0 ? args[i + 1] : dflt;
};
const root = path.resolve(opt('root', '..'));
const out = opt('out', 'results.json');
const only = opt('only', '') ? new Set(opt('only').split(',')) : null;
const init = opt('init', '');

const wb = await openWorkbench(root, { query: opt('query', '') });
if (init) {
  const value = await wb.page.evaluate(`(async () => { ${fs.readFileSync(init, 'utf8')} })()`);
  if (value != null) console.log('init:', JSON.stringify(value));
}
const results = [];
const t0 = Date.now();
for (const step of suite) {
  if (only && !only.has(step.id)) continue;
  const r = await runStep(wb, step);
  results.push({ id: step.id, step, result: r });
  const tag = r.failure ? 'FAILED ' + r.failure : r.code != null ? 'code ' + r.code : 'ok';
  console.log(`${step.id.padEnd(24)} ${tag.padEnd(10)} ${String(r.ms).padStart(7)} ms${r.errors.length ? '  page errors: ' + r.errors.length : ''}`);
}
const meta = { root, query: opt('query', ''), init, when: new Date().toISOString(), secs: (Date.now() - t0) / 1000 };
if (init) meta.after = await wb.page.evaluate(() => (window.__testReport ? window.__testReport() : null)).catch(() => null);
fs.writeFileSync(out, JSON.stringify({ meta, results }, null, 1));
console.log(`${results.length} steps in ${meta.secs.toFixed(0)} s → ${out}`);
await wb.close();
process.exit(0);
