#!/usr/bin/env node
/* The boundary, checked in the source: outside the files of the execution backends, nothing reaches the programs or
   their bytes except through MG.exec (assets/js/exec.js). Each rule names what only a backend may use.
     node boundary-lint.mjs   → exit status 1 when a rule is broken */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const js = path.join(here, '..', 'assets', 'js');
// the backends, and the workers that only the browser backend starts
const BACKEND = new Set(['exec-engine.js', 'exec-browser.js', 'exec-local.js', 'threads-worker.mjs', 'python-worker.mjs']);
const rules = [
  [/\bMG\.wasm\b/, 'the old global of the browser runner (MG.wasm): use MG.exec'],
  [/\bAioli\b/, "the browser backend's program runner (Aioli)"],
  [/\/shared\/vfs/, "a path of the browser backend's file system"],
  [/\.apath\b/, "a handle's or an entry's place in the browser backend (apath)"],
  [/['"]aioli['"]/, "the browser backend's kind of file entry: ask MG.exec.holds(entry)"],
  [/\bexecIO\b|\bstatTree\b/, "the browser backend's calls into its runner"],
  [/threads-worker\.mjs|python-worker\.mjs/, "the browser backend's workers"],
  [/\.handle\b/, 'the inside of a handle: hand the FileRef to MG.exec (only exec.js and the shell\'s input streams look at it)']
];
// (where a rule may be broken, and why: a file, the rule's text, a test the line must pass)
const allowed = [
  // the shell's input stream of a block remembers the handle of the file it came from, and gives it to the backend
  ['shell-lang.js', '.handle', (l) => /handle: s\.handle|!s\.handle/.test(l)],
  // the contract itself
  ['exec.js', '.handle', () => true],
  // config.js describes where the browser backend's programs are
  ['config.js', 'threads-worker', () => true],
  // Bracken's workflow (run by the backend through h.spawn) says which of its programs are Python programs: in the
  // browser they run in python-worker.mjs, and that is the name the descriptor gives
  ['metagenomics.js', 'python-worker', () => true]
];
let bad = 0, files = 0;
for (const f of fs.readdirSync(js).filter((f) => /\.(m?js)$/.test(f)).sort()) {
  if (BACKEND.has(f)) continue;
  files++;
  const lines = fs.readFileSync(path.join(js, f), 'utf8').split('\n');
  lines.forEach((line, i) => {
    for (const [re, what] of rules) {
      if (!re.test(line)) continue;
      if (allowed.some(([af, key, ok]) => af === f && re.source.includes(key.replace('.', '\\.')) && ok(line))) continue;
      bad++;
      console.log(`${f}:${i + 1}: ${what}\n    ${line.trim().slice(0, 160)}`);
    }
  });
}
// (the page loads the contract before the backends, and the backends before the commands that use them)
const page = fs.readFileSync(path.join(here, '..', 'index.html'), 'utf8');
const order = ['vfs.js', 'exec.js', 'shell.js', 'exec-engine.js', 'exec-browser.js', 'exec-local.js', 'tools-wasm.js'].map((f) => page.indexOf(`src="assets/js/${f}"`));
if (order.some((x) => x < 0) || order.some((x, i) => i && x < order[i - 1])) {
  bad++;
  console.log('index.html: the scripts must load in this order: vfs.js, exec.js, shell.js, exec-engine.js, exec-browser.js, exec-local.js, tools-wasm.js');
}
console.log(`${files} files checked: ${bad ? bad + ' PROBLEMS' : 'the boundary holds'}`);
process.exit(bad ? 1 : 0);
