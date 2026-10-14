/* A page script for run-suite.mjs (--init): puts a backend in front of the browser's that gives the rest of the page
   handles that mean nothing – "opaque-1", "opaque-2" … – and translates them back on the way in. Every program still
   runs in the browser backend. If anything outside a backend still took a handle for a path of the programs' file
   system (passed it to a program, compared it with a path, read from it), the parity suite gives other results with
   this backend than without it. It also counts which members of the contract the suite used (window.__testReport). */
const inner = MG.exec.backend;
const toInner = new Map();
let n = 0;
const calls = {};
const count = (k) => (calls[k] = (calls[k] || 0) + 1);
const KEEP = ['fromFile', 'path', 'psub'];
const outer = (ref) => {
  if (!(ref instanceof MG.FileRef)) return ref;
  const h = 'opaque-' + ++n;
  toInner.set(h, ref.handle);
  const w = new MG.FileRef(h, ref.binary);
  for (const k of KEEP) if (k in ref) w[k] = ref[k];
  return w;
};
const innerRef = (w) => {
  if (!(w instanceof MG.FileRef)) return w;
  if (!toInner.has(w.handle)) throw new Error('opaque backend: a handle it did not give out: ' + w.handle);
  const r = new MG.FileRef(toInner.get(w.handle), w.binary);
  for (const k of KEEP) if (k in w) r[k] = w[k];
  return r;
};
const B = {
  id: 'opaque',
  label: 'the browser (opaque handles)',
  entryKind: inner.entryKind,
  get ready() { return inner.ready; },
  get running() { return inner.running; },
  get versions() { return inner.versions; },
  get gen() { return inner.gen; },
  get lastKill() { return inner.lastKill; },
  get lostTimes() { return inner.lostTimes; },
  get lostEntries() { return inner.lostEntries; },
  get capabilities() { return inner.capabilities; },
  ensure: (s) => (count('ensure'), inner.ensure(s)),
  async run(ctx, program, args, opts) {
    count('run');
    // (the program's input: the handle of a pipe or of < FILE, or that of a block's input stream – which the run
    // moves along, and so is the same object, with the handle swapped while the program runs)
    const view = Object.create(ctx);
    if (ctx.stdin instanceof MG.FileRef) Object.defineProperty(view, 'stdin', { value: innerRef(ctx.stdin), enumerable: true });
    const s = ctx.inherit, had = s && s.handle;
    if (had) s.handle = toInner.get(had);
    try {
      const r = await inner.run(view, program, args, opts);
      if (r && r.out) r.out = outer(r.out);
      return r;
    } finally {
      if (had) s.handle = had;
    }
  },
  kill: (fs) => (count('kill'), inner.kill(fs)),
  needsIsolation: (p) => inner.needsIsolation(p),
  tidy: (t, name) => inner.tidy(t, name),
  readText: (r) => (count('readText'), inner.readText(innerRef(r))),
  readBytes: (r) => (count('readBytes'), inner.readBytes(innerRef(r))),
  sizeOf: (r) => (count('sizeOf'), inner.sizeOf(innerRef(r))),
  tempBytes: async (b, bin) => (count('tempBytes'), outer(await inner.tempBytes(b, bin))),
  tempFile: async () => (count('tempFile'), outer(await inner.tempFile())),
  discard: (r) => (count('discard'), inner.discard(innerRef(r))),
  argPath: (r) => (count('argPath'), inner.argPath(innerRef(r))),
  hold: (r) => (count('hold'), inner.hold(innerRef(r))),
  release: (r) => (count('release'), inner.release(innerRef(r))),
  inputRef: async (fs, abs) => (count('inputRef'), outer(await inner.inputRef(fs, abs))),
  holds: (e) => inner.holds(e),
  entryText: (e) => (count('entryText'), inner.entryText(e)),
  entryBytes: (e) => (count('entryBytes'), inner.entryBytes(e)),
  writeBytes: (fs, abs, b) => (count('writeBytes'), inner.writeBytes(fs, abs, b)),
  writeOutput: (fs, abs, r, o) => (count('writeOutput'), inner.writeOutput(fs, abs, innerRef(r), o)),
  settle: (fs, between) => (count('settle'), inner.settle(fs, between)),
  keep: (l) => (count('keep'), inner.keep(l)),
  putBack: (a, e, s) => (count('putBack'), inner.putBack(a, e, s)),
  dropKept: () => (count('dropKept'), inner.dropKept())
};
MG.exec.register(B);
MG.exec.use('opaque');
window.__testReport = () => ({ backend: MG.exec.id, handles: n, calls });
return { backend: MG.exec.id };
