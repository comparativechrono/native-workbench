/* =====================================================================
   The local backend: the programs of the terminal run on this computer, in the local runner – a companion program
   that serves the workbench at http://127.0.0.1:PORT/ and keeps the files of an analysis on disk, so that neither the
   size of the input nor the memory of a browser tab limits an analysis. The programs stay the same WebAssembly
   builds; the runner runs them under Node.js.

   This version has the page's side of the connection only (step 1 in docs/execution-backends.md). The page asks for
   this backend with ?backend=local (or backend: 'local' in config.js) and asks the runner who it is; the runner
   serves the page, so it is asked at the page's own address. Running programs, the files on disk and reading large
   results in pieces come with the runner itself (the next steps). Until a runner answers, the page says so once and
   uses the browser backend; a runner that answers but cannot yet be used for something is told so, in words.

   The protocol, version 1 (a draft – docs/execution-backends.md):
     GET /api/v1/hello  →  { protocol: 1, runner: NAME, version: V, programs: { name: version }, workspace: { root } }
   Every request carries the token of the session (Authorization: Bearer TOKEN). The runner hands it to the page in the
   address it opens (#runner-token=TOKEN); the page keeps it for this tab only and takes it out of the address.
   ===================================================================== */
(function () {
  'use strict';
  const MG = window.MG;
  const PROTOCOL = 1;
  const KEY = ((window.MG_CONFIG && window.MG_CONFIG.storePrefix) || 'biowb') + '.runnerToken';
  const HELLO_MS = 4000;

  /** the token of this session: from the address the runner opened (#runner-token=…), then from this tab's storage */
  function token() {
    let t = null;
    try {
      const m = /(?:^#|&)runner-token=([^&]+)/.exec(location.hash || '');
      if (m) {
        t = decodeURIComponent(m[1]);
        sessionStorage.setItem(KEY, t);
        // (not left in the address: it would be copied with it)
        const rest = location.hash.replace(/(^#|&)runner-token=[^&]+/, '$1').replace(/^#&/, '#').replace(/^#$/, '');
        history.replaceState(null, '', location.pathname + location.search + rest);
      } else t = sessionStorage.getItem(KEY);
    } catch (e) {
      /* (no storage in this tab: only the address) */
    }
    return t;
  }

  const userErr = (msg) => (MG.shellUtil && MG.shellUtil.userErr ? MG.shellUtil.userErr(msg) : Object.assign(new Error(msg), { userMessage: msg }));

  const L = {
    id: 'local',
    label: 'the local runner',
    // the page's file entries whose bytes are on the runner's disk: { kind: 'local', handle, size }
    entryKind: 'local',
    ready: false,
    running: null,
    versions: {},
    capabilities: { where: 'local', persistentFiles: true, threads: false },
    /** what the runner said about itself (GET /api/v1/hello) */
    info: null,
    base: '',

    /** ask the runner who it is. → true, or why it cannot be used (a sentence) */
    async connect() {
      this.base = location.origin;
      const where = this.base || 'this address';
      const t = token();
      const ac = typeof AbortController === 'function' ? new AbortController() : null;
      const timer = ac ? setTimeout(() => ac.abort(), HELLO_MS) : null;
      let r;
      try {
        r = await fetch(this.base + '/api/v1/hello', { headers: t ? { Authorization: 'Bearer ' + t } : {}, cache: 'no-store', signal: ac ? ac.signal : undefined });
      } catch (e) {
        return `no local runner answered at ${where}`;
      } finally {
        if (timer) clearTimeout(timer);
      }
      if (r.status === 401 || r.status === 403) return 'the local runner did not accept this page: open the workbench with the link the runner gives, which carries the key of the session';
      if (!r.ok) return `no local runner answered at ${where} (this page comes from an ordinary web server)`;
      let j;
      try {
        j = await r.json();
      } catch (e) {
        return `what answered at ${where} is not a local runner`;
      }
      if (!j || typeof j !== 'object' || j.protocol == null) return `what answered at ${where} is not a local runner`;
      if (j.protocol !== PROTOCOL) return `the local runner speaks version ${j.protocol} of the protocol, and this page version ${PROTOCOL}: use a runner and a workbench of the same release`;
      this.info = j;
      this.versions = Object.assign({}, j.programs || {});
      this.label = `the local runner${j.runner ? ' (' + j.runner + (j.version ? ' ' + j.version : '') + ')' : ''}`;
      this.ready = true;
      return true;
    },

    /* ---- what the runner does not do yet: said in words ---- */
    notYet(what) {
      return userErr(`${what}: the local runner answered, but this version of the workbench cannot use it for that yet. Open the workbench without ?backend=local to run it in this browser tab.`);
    },
    async ensure() {
      if (!this.ready) throw userErr('The local runner is not connected.');
    },
    async run(ctx, program) {
      throw this.notYet((ctx && ctx.name) || program);
    },
    kill() {
      return [];
    },
    needsIsolation() {
      return false;
    },
    tidy(text) {
      return text;
    },
    async readText() {
      throw this.notYet('reading what a program printed');
    },
    async readBytes() {
      throw this.notYet('reading what a program printed');
    },
    async sizeOf() {
      throw this.notYet('reading what a program printed');
    },
    async tempBytes() {
      throw this.notYet('a pipe into a program');
    },
    async tempFile() {
      throw this.notYet('a temporary file');
    },
    async discard() {},
    argPath(ref) {
      return ref.handle;
    },
    hold() {},
    release() {},
    async inputRef() {
      throw this.notYet('< FILE');
    },
    holds(e) {
      return !!e && e.kind === 'local';
    },
    async entryText() {
      throw this.notYet('reading a file on the runner');
    },
    async entryBytes() {
      throw this.notYet('reading a file on the runner');
    },
    async writeBytes() {
      throw this.notYet('writing a file on the runner');
    },
    async writeOutput() {
      throw this.notYet('> FILE');
    },
    async settle() {}
  };

  MG.exec.register(L);
  if (MG.exec.wanted === 'local') MG.exec.choose('local', () => L.connect());
})();
