/* =====================================================================
   Execution backends: where the programs of the terminal run, and where the bytes that they read and write are kept.

   The page keeps the names of the files (vfs.js): what is in each folder, sizes, times, permissions, and the text of
   small text files. The bytes of the files that programs write (BAM, .gz, anything large) are kept by the backend
   that ran the program; the page's entry for such a file says which backend holds it, and how to find it there.
   Everything else in the workbench that runs a program or touches those bytes goes through MG.exec – the terminal,
   the shell's pipes and redirections, the editor and the viewers (through vfs.js), the AI agent and the workflows.

   The backends:
     browser – the programs run in this page, compiled to WebAssembly (exec-browser.js). What the workbench has always
               done; right for teaching and for smaller analyses.
     local   – the programs run in a companion program on this computer, which keeps the files on disk
               (exec-local.js), for analyses larger than a browser tab can hold. Being built: this version has the
               connection only – see docs/execution-backends.md.

   One backend is active in a page. It is chosen as the page starts: ?backend=local in the address, or backend:
   'local' in config.js; the browser otherwise. A backend is an object with the members of CONTRACT below; what each
   must do is written in docs/execution-backends.md.
   ===================================================================== */
(function () {
  'use strict';
  const MG = (window.MG = window.MG || {});

  /** A handle to bytes that a backend keeps: what a program printed (the next command of a pipe reads it), the file
      of < FILE, the bytes of a pipe, a temporary file. Only the backend that made it knows what `handle` means:
      everyone else hands the object back to MG.exec (and MG.exec.argPath gives the name by which a program can be
      given the file). binary: not text for the screen (samtools view -b); fromFile, path: it is the file at path
      (< FILE: a program may go back in it); psub: … but it stands for a pipe (< <(COMMAND)) */
  class FileRef {
    constructor(handle, binary = false) {
      this.handle = handle;
      this.binary = binary;
    }
  }

  /* What a backend must have: 'fn' – a method; 'value' – a property (it may be a getter). See the documentation for
     what each one does. */
  const CONTRACT = {
    id: 'value', // 'browser', 'local' …
    label: 'value', // how the page names it to a person
    entryKind: 'value', // the kind of the page's file entries whose bytes it holds (vfs.js)
    versions: 'value', // program → version, of the programs it runs
    ready: 'value', // it has started (ensure) and has not been stopped since
    running: 'value', // the name of the program that is running, or null
    // programs
    ensure: 'fn', // (status) → start it, if it has not started
    run: 'fn', // (ctx, program, args, opts) → the result of one program (see RunResult in the documentation)
    kill: 'fn', // (fs) → stop the running program by force; → the paths of the files that were lost with it
    needsIsolation: 'fn', // (program) → the program cannot run in this page as it is (threads without cross-origin isolation)
    tidy: 'fn', // (text, name) → what a program printed, with paths as the person knows them
    // handles (FileRef)
    readText: 'fn',
    readBytes: 'fn',
    sizeOf: 'fn',
    tempBytes: 'fn', // (bytes, binary) → a FileRef to those bytes (the input of the next command of a pipe)
    tempFile: 'fn', // () → a FileRef to a file that a program can be told to write (see argPath); empty until written
    discard: 'fn', // (ref) → the bytes of a temporary file are not needed any more
    argPath: 'fn', // (ref) → the name to give a program for the file of a FileRef, as an argument
    hold: 'fn', // (ref) → the bytes of this handle stay until release (a pipe whose reader has not run yet)
    release: 'fn',
    inputRef: 'fn', // (fs, abs) → a FileRef to the file at abs, for < FILE
    // the bytes of the page's files
    holds: 'fn', // (entry) → the bytes of this file entry are held by this backend
    entryText: 'fn', // (entry) → its bytes, as text
    entryBytes: 'fn', // (entry) → its bytes
    writeBytes: 'fn', // (fs, abs, bytes) → bytes in hand become the file at abs
    writeOutput: 'fn', // (fs, abs, ref, {tail, append}) → what a program printed becomes the file at abs (> FILE)
    settle: 'fn' // (fs) → files that were copied or moved (cp, mv) get bytes of their own
  };
  /* What a backend may leave out: the page then does without (the AI agent can then not put back a file that a
     program it ran changed; there is nothing to tell after a forced stop). */
  const OPTIONAL = {
    gen: 0, // counts the forced stops that lost the backend's files
    lastKill: '', // what the last forced stop stopped: 'threads' (one program) or 'runner' (every program, and their files)
    lostTimes: null, // after a forced stop: path → the time of the file that was lost
    lostEntries: null, // after a forced stop: path → its entry
    capabilities: null,
    keep: async () => 0, // (list) → copies of these files, before a command of the AI agent
    putBack: async () => false, // (abs, entry, since) → the file is as it was before the agent's command
    dropKept: async () => {}
  };

  const backends = new Map();
  let active = null;
  // the choice of the backend, while it is being made (the local backend must answer first): every program waits for it
  let choosing = null;
  const wanted = (() => {
    let w = null;
    try {
      w = new URLSearchParams(location.search).get('backend');
    } catch (e) {
      /* (no address: a test) */
    }
    return String(w || (window.MG_CONFIG && window.MG_CONFIG.backend) || 'browser').toLowerCase();
  })();

  function check(b) {
    const missing = [];
    for (const [k, how] of Object.entries(CONTRACT)) {
      if (!(k in b)) missing.push(k);
      else if (how === 'fn' && typeof b[k] !== 'function') missing.push(k + ' (a method)');
    }
    for (const k of ['id', 'label', 'entryKind']) if (k in b && typeof b[k] !== 'string') missing.push(k + ' (a string)');
    if (missing.length) throw new Error(`execution backend ${b && b.id}: missing ${missing.join(', ')}`);
  }
  function current() {
    if (!active) throw new Error('No execution backend: the programs of this page are not loaded.');
    return active;
  }
  const opt = (k) => (active && k in active && active[k] != null ? active[k] : OPTIONAL[k]);
  // (the backend whose bytes an entry is: the active one, as a rule – any registered one that holds it)
  const owner = (e) => {
    if (!e) return null;
    if (active && active.holds(e)) return active;
    for (const b of backends.values()) if (b !== active && b.holds(e)) return b;
    return null;
  };

  const E = {
    FileRef,
    CONTRACT,
    /** the backend that was asked for: 'browser' unless the address or config.js says otherwise */
    wanted,
    /** after the page asked for another backend and got the browser's: { wanted, reason, message } */
    fallback: null,
    /** add a backend (exec-browser.js, exec-local.js). The browser's is active unless another is chosen. */
    register(b) {
      check(b);
      backends.set(b.id, b);
      if (!active && b.id === 'browser') active = b;
      return b;
    },
    /** make a registered backend the active one. Before any program has run: a page does not change backends with
        files in one of them. */
    use(id) {
      const b = backends.get(id);
      if (!b) throw new Error(`no execution backend "${id}"`);
      active = b;
      return b;
    },
    /** choose the backend that was asked for, if it answers: connect() → true, or a reason why not (a string). Until
        it has answered, every program waits. */
    choose(id, connect) {
      choosing = (async () => {
        let why;
        try {
          const r = await connect();
          if (r === true) {
            this.use(id);
            return;
          }
          why = String(r || 'it did not answer');
        } catch (e) {
          why = String((e && e.message) || e);
        }
        const b = backends.get(id), label = (b && b.label) || id;
        this.fallback = { wanted: id, reason: why, message: `The programs were to run in ${label}, but ${why}. They run in this browser tab instead.` };
        if (MG.bus) MG.bus.emit('exec:fallback', this.fallback);
      })().finally(() => {
        choosing = null;
      });
      return choosing;
    },
    /** a promise that is settled when the backend has been chosen */
    whenChosen() {
      return choosing ? choosing.then(() => this.id) : Promise.resolve(this.id);
    },
    get backend() {
      return active;
    },
    get id() {
      return active ? active.id : null;
    },
    get backends() {
      return Array.from(backends.values());
    },
    get label() {
      return active ? active.label : '';
    },

    // ---- programs
    get ready() {
      return !!active && !!active.ready;
    },
    get running() {
      return active ? active.running || null : null;
    },
    get versions() {
      return (active && active.versions) || {};
    },
    get gen() {
      return opt('gen');
    },
    get lastKill() {
      return opt('lastKill');
    },
    get lostTimes() {
      return opt('lostTimes') || new Map();
    },
    get lostEntries() {
      return opt('lostEntries') || new Map();
    },
    get capabilities() {
      return opt('capabilities') || {};
    },
    async ensure(status) {
      if (choosing) await choosing;
      return current().ensure(status);
    },
    async run(ctx, program, args, opts) {
      if (choosing) await choosing;
      return current().run(ctx, program, args, opts);
    },
    kill(fs) {
      return active ? active.kill(fs) : [];
    },
    needsIsolation(program) {
      return !!active && active.needsIsolation(program);
    },
    tidy(text, name) {
      return active ? active.tidy(text, name) : text;
    },

    // ---- handles
    async readText(ref) {
      if (choosing) await choosing;
      return current().readText(ref);
    },
    async readBytes(ref) {
      if (choosing) await choosing;
      return current().readBytes(ref);
    },
    async sizeOf(ref) {
      if (choosing) await choosing;
      return current().sizeOf(ref);
    },
    async tempBytes(bytes, binary) {
      if (choosing) await choosing;
      return current().tempBytes(bytes, binary);
    },
    async tempFile() {
      if (choosing) await choosing;
      return current().tempFile();
    },
    async discard(ref) {
      if (choosing) await choosing;
      return current().discard(ref);
    },
    argPath(ref) {
      return current().argPath(ref);
    },
    hold(ref) {
      if (active && ref) active.hold(ref);
    },
    release(ref) {
      if (active && ref) active.release(ref);
    },
    async inputRef(fs, abs) {
      if (choosing) await choosing;
      return current().inputRef(fs, abs);
    },

    // ---- the bytes of the page's files
    /** is this file entry one whose bytes a backend holds? */
    holds(e) {
      return !!owner(e);
    },
    /** the bytes of such an entry as text. path: for the message when they cannot be had yet */
    async entryText(e, path) {
      const b = owner(e);
      if (!b || !b.ready) throw new Error(`${path}: not available yet`);
      return b.entryText(e);
    },
    async entryBytes(e) {
      const b = owner(e);
      if (!b) throw new Error('these bytes are not held by any backend');
      return b.entryBytes(e);
    },
    async writeBytes(fs, abs, bytes) {
      if (choosing) await choosing;
      return current().writeBytes(fs, abs, bytes);
    },
    /** what a program printed (ref) becomes the file at abs, or is added to its end (append); tail: bytes after it.
        → false: nothing was printed, and the file stays as it was */
    async writeOutput(fs, abs, ref, opts) {
      if (choosing) await choosing;
      return current().writeOutput(fs, abs, ref, opts || {});
    },
    async settle(fs) {
      if (choosing) await choosing;
      return current().settle(fs);
    },

    // ---- for the AI agent: what a command changes outside the agent's folder is put back (assistant.js)
    async keep(list) {
      return active && active.keep ? active.keep(list) : OPTIONAL.keep(list);
    },
    async putBack(abs, e, since) {
      const b = owner(e);
      return b && b.putBack ? b.putBack(abs, e, since) : false;
    },
    async dropKept() {
      if (active && active.dropKept) return active.dropKept();
    }
  };

  MG.exec = E;
  MG.FileRef = FileRef;
})();
