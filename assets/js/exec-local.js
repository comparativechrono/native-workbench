/* =====================================================================
   The local backend: the programs of the terminal run on this computer, in the local runner (runner/runner.mjs) – a
   companion program that serves the workbench at http://127.0.0.1:PORT/ and keeps the files of an analysis in a
   folder on disk, so that neither the size of the input nor the memory of a browser tab limits an analysis. The
   programs are the same WebAssembly builds as in the browser; the runner runs them under Node.js, with a file system
   that is the folder on disk.

   This file is the backend's machine (see exec-engine.js): the engine keeps the page's files and the folder the same,
   as it keeps the page's files and the browser's programs' the same; here every call of the programs' file system is
   a request to the runner, and copies, moves and what a program printed into a file stay on the runner's side –
   the bytes of a large file never come to the page. The folder is where the work is kept: the page starts with what
   is in it (restore), and what the page changes goes to it soon after (watch).

   Where the runner has a program built for this computer (native/bin: SAMtools, BCFtools, minimap2, BWA …), it runs
   that one instead (runner/native.mjs); it tells the page which (GET /api/v1/hello: programs), and the page takes
   their versions and whether they use threads from there (capabilities.native).

   The page asks for this backend with ?backend=local (or backend: 'local' in config.js), and asks the runner who it
   is (GET /api/v1/hello) at the page's own address. Every request carries the key of the session (Authorization:
   Bearer KEY): the runner puts it in the address it prints (#runner-token=KEY); the page keeps it for this tab only and
   takes it out of the address. Where no runner answers, the page says so once and uses the browser backend.

   Not yet here: the programs that run in a worker of their own in the browser (featureCounts, Salmon, PLINK 2,
   Cutadapt, MACS3, LoFreq, SomaticSniper, Strelka2, Kraken2, Bracken, Prodigal, HMMER, bustools) – the terminal says
   so; the AI agent's undo of what its commands change (keep, putBack) works as in the browser. The protocol: see
   docs/execution-backends.md.
   ===================================================================== */
(function () {
  'use strict';
  const MG = window.MG;
  const E = MG.execEngine;
  const PROTOCOL = 1;
  const KEY = ((window.MG_CONFIG && window.MG_CONFIG.storePrefix) || 'biowb') + '.runnerToken';
  const HELLO_MS = 4000;
  const ROOT = E.ROOT;

  /** the key of this session: from the address the runner opened (#runner-token=…), then from this tab's storage */
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
  const b64 = (bytes) => {
    let s = '';
    for (let i = 0; i < bytes.length; i += 32768) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 32768));
    return btoa(s);
  };

  /* The programs' file system of the runner, with the calls of Aioli's (cli.fs.readFile …, mkdir, cd, statTree,
     execIO) and those that keep large files on the runner's side (copyFile, rename, redirect, readTextBounded,
     readSmall, siteFile). Paths are the programs' paths (/shared/vfs/…): the runner knows which folder each is. */
  class RemoteCli {
    constructor(base, key, specs) {
      this.base = base;
      this.key = key;
      this.cwd = ROOT;
      // program → [tool, version, program]: the files the runner loads ('base' is Aioli's, and runs nothing)
      this.specs = new Map(specs.filter((s) => s[0] !== 'base').map(([tool, version, program]) => [program || tool, [tool, version, program || tool]]));
      const op = (name, args) => this.call(name, args);
      this.fs = {
        readFile: (p) => this.get(p),
        writeFile: (p, data) => this.put(p, data),
        // (a file that is not there: an error, as Aioli's lstat gives – the runner answers null)
        lstat: async (p) => {
          const s = await op('lstat', { path: p });
          if (!s) throw Object.assign(new Error(`${p}: No such file or directory`), { code: 'ENOENT' });
          return s;
        },
        readdir: (p) => op('readdir', { path: p }),
        unlink: (p) => op('unlink', { path: p }),
        rmdir: (p) => op('rmdir', { path: p }),
        chmod: (p, mode) => op('chmod', { path: p, mode }),
        utime: (p, atime, mtime) => op('utime', { path: p, atime, mtime }),
        copyFile: (from, to) => op('copy', { from, to }),
        rename: (from, to) => op('rename', { from, to }),
        redirect: async (from, to, { tail, append } = {}) => (await op('redirect', { from, to, append: !!append, tail: tail && tail.length ? b64(tail) : null })).size,
        readTextBounded: async (p, head, tail) => (await op('peek', { path: p, head, tail })).text,
        readSmall: (paths) => op('readSmall', { paths, max: E.TEXT_MAX })
      };
    }
    async request(method, path, { query, json, body } = {}) {
      const url = new URL(path, this.base);
      if (query) for (const [k, v] of Object.entries(query)) url.searchParams.set(k, v);
      const headers = { Authorization: 'Bearer ' + this.key };
      if (json !== undefined) headers['Content-Type'] = 'application/json';
      let r;
      try {
        r = await fetch(url, { method, headers, body: json !== undefined ? JSON.stringify(json) : body, cache: 'no-store' });
      } catch (e) {
        throw userErr('The local runner is not answering: is it still running? (Start it again, and open the address it prints.)');
      }
      if (r.ok) return r;
      let j = {};
      try {
        j = await r.json();
      } catch (e) {
        /* (no message) */
      }
      throw Object.assign(new Error(j.error || `the local runner answered ${r.status}`), { code: j.code || null, status: r.status });
    }
    async call(op, args) {
      return (await (await this.request('POST', '/api/v1/fs', { json: Object.assign({ op }, args) })).json()).ok;
    }
    async get(p) {
      return new Uint8Array(await (await this.request('GET', '/api/v1/file', { query: { path: p } })).arrayBuffer());
    }
    async put(p, data) {
      await this.request('PUT', '/api/v1/file', { query: { path: p }, body: typeof data === 'string' ? new TextEncoder().encode(data) : data });
    }
    mkdir(p) {
      return this.call('mkdir', { path: p });
    }
    cd(p) {
      this.cwd = p;
    }
    statTree(root, skip) {
      return this.call('tree', { root, skip });
    }
    async execIO(program, args, io) {
      const spec = this.specs.get(program);
      if (!spec) throw userErr(`${program}: the local runner has no such program`);
      return (await (await this.request('POST', '/api/v1/exec', { json: { spec, args, io, cwd: this.cwd } })).json()).ok;
    }
    cancel() {
      this.request('POST', '/api/v1/kill', { json: {} }).catch(() => {});
    }
    /** a file of the site (an example file, or a copy of one: kind 'url') → its path in the programs' file system: the
        runner has the site's example data at /data/examples */
    siteFile(url) {
      try {
        const u = new URL(url, location.href);
        if (u.origin !== location.origin || !u.pathname.startsWith('/data/examples/')) return null;
        return ROOT + decodeURIComponent(u.pathname);
      } catch (e) {
        return null;
      }
    }
  }

  const SPEC = new Set(E.SPECS.filter((s) => s[0] !== 'base').map((s) => s[2] || s[0]));
  const MACHINE = {
    id: 'local',
    label: 'the local runner',
    // the page's file entries whose bytes are in the runner's folder: { kind: 'local', apath, size }
    entryKind: 'local',
    keepsBytes: true,
    capabilities: { where: 'local', persistentFiles: true, threads: false },
    /** (no page isolation is needed: the programs' threads, where they have them, are the runner's) */
    needsIsolation() {
      return false;
    },
    /** what the runner said about itself (GET /api/v1/hello) */
    info: null,
    base: '',
    key: null,

    /** ask the runner who it is. → true, or why it cannot be used (a sentence) */
    async connect() {
      this.base = location.origin;
      const where = this.base || 'this address';
      const t = (this.key = token());
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
      this.label = `the local runner${j.runner ? ' (' + j.runner + (j.version ? ' ' + j.version : '') + ')' : ''}`;
      const folder = j.workspace && j.workspace.root;
      // the programs the runner has built for this computer: their versions, and whether they can use threads
      const native = j.programs && typeof j.programs === 'object' ? j.programs : {};
      const names = Object.keys(native).sort();
      if (names.length) {
        this.capabilities = Object.assign({}, this.capabilities, { native });
        const v = Object.assign({}, this.versions);
        for (const n of names) {
          v[n] = native[n].version;
          if (native[n].tool) v[native[n].tool] = native[n].version;
        }
        this.versions = v;
      }
      const which = names.length ? ` ${names.map((n) => n + ' ' + native[n].version).join(', ')} are native programs, built for this computer; the others are the browser's WebAssembly builds, run by the runner.` : j.native && j.native.why ? ` The runner has no native programs (${j.native.why}): it runs the browser's WebAssembly builds.` : '';
      MG.exec.notices.push(`The programs run on this computer, in the local runner${folder ? `; your files (~) are the folder ${folder}` : ''}.${which} featureCounts, Salmon, Kraken2 and the other programs that run in a worker of their own in the browser are not in the runner yet (open the workbench without ?backend=local to use them).`);
      if (j.busy) this.whileBusy(j.busy);
      return true;
    },

    /** the folder on disk, through the runner */
    async start(status, specs) {
      if (!this.info) throw userErr('The local runner is not connected.');
      status?.('Connecting to the local runner…');
      return new RemoteCli(this.base + '/', this.key, specs);
    },
    /** the programs that run in a worker of their own in the browser: not (yet) in the runner */
    ownWorker(program) {
      return SPEC.has(program) ? null : { name: program };
    },
    async execWorker(program, args, { name }) {
      throw userErr(`${name || program}: this program does not run in the local runner yet – it runs in the browser. Open the workbench without ?backend=local to use it.`);
    },
    /** a program stopped by force: only that run ends – the files are on disk, and nothing is lost */
    lastKill: '',
    kill(fs) {
      if (!this.running) return [];
      const program = this.running, err = Object.assign(new Error('Killed'), { userMessage: `${program}: Killed`, code: 137 });
      this.lastKill = 'threads';
      if (this.cli) this.cli.cancel();
      if (this._killed) this._killed(err);
      MG.bus.emit('wasm:killed', { program, lost: 0 });
      return [];
    },
    /** A program that a page started is still running (the page was closed or reloaded while it ran): the runner lets
        it finish. Its files join the page's when it has. */
    whileBusy(busy) {
      const started = new Date(busy.started || Date.now());
      const t = String(started.getHours()).padStart(2, '0') + ':' + String(started.getMinutes()).padStart(2, '0');
      MG.exec.notices.push(`${busy.program} is still running in the local runner (started at ${t}): what it writes appears in your folder when it has finished. The next command waits for it.`);
      const poll = async () => {
        try {
          // (the folder as it was when the page took its files from it: what the run has written since joins them)
          const before = this.restored;
          if (!before || !this.cli) return setTimeout(poll, 1000);
          const r = await (await this.cli.request('GET', '/api/v1/run')).json();
          if (r.busy) return setTimeout(poll, 3000);
          await this.locked(() => this.importChanges(this._fs, before));
          const last = r.last || {};
          if (MG.app && MG.app.term) MG.app.term.note(`${last.program || busy.program}, which was still running, has finished${last.code != null ? ` (exit status ${last.code})` : ''}: its files are in your folder now.`);
        } catch (e) {
          setTimeout(poll, 5000);
        }
      };
      setTimeout(poll, 1000);
    }
  };

  const L = E.create(MACHINE);
  MG.exec.register(L);
  if (MG.exec.wanted === 'local') MG.exec.choose('local', () => L.connect());
})();
