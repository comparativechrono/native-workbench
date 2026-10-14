/* =====================================================================
   The user's files: kept in this browser between visits (IndexedDB),
   downloadable as a .zip, and filled from the user's computer
   (upload, drag and drop, .zip).

   Every file under the home folder (and Galaxy's datasets, /galaxy) is
   kept: text files as text, everything else – uploads, what programs
   wrote (BAM, compressed VCF …), pictures – as bytes. Nothing leaves the
   browser.
   ===================================================================== */
(function () {
  'use strict';
  const MG = window.MG;
  const { bus, toast, esc } = MG;
  const CFG = MG.config || {};
  const DB_NAME = (CFG.storePrefix || 'workbench') + '-files';
  const MAX_FILE = 1024 * 1024 * 1024; // one file: 1 GB
  const newId = () => Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 9);

  /* ---- IndexedDB: path -> { path, k: 'd'|'t'|'b'|'u', text, blob, url, size, mtime, mode, readonly, perm, id } ---- */
  const idb = {
    open() {
      if (!this.ready) {
        this.ready = new Promise((resolve, reject) => {
          let rq;
          try {
            rq = window.indexedDB.open(DB_NAME, 1);
          } catch (e) {
            return reject(e);
          }
          rq.onupgradeneeded = () => rq.result.createObjectStore('files', { keyPath: 'path' });
          rq.onsuccess = () => resolve(rq.result);
          rq.onerror = () => reject(rq.error);
          rq.onblocked = () => reject(new Error('blocked'));
        });
        this.ready.catch(() => {});
      }
      return this.ready;
    },
    async tx(mode, fn) {
      const db = await this.open();
      return new Promise((resolve, reject) => {
        const t = db.transaction('files', mode);
        const out = fn(t.objectStore('files'));
        t.oncomplete = () => resolve(out && out.result !== undefined ? out.result : undefined);
        t.onerror = t.onabort = () => reject(t.error || new Error('IndexedDB transaction failed'));
      });
    },
    all: () => idb.tx('readonly', (st) => st.getAll()),
    clear: () => idb.tx('readwrite', (st) => st.clear()),
    /** put some records and delete some paths (and, for folders, everything below them), in one transaction.
        drops: records to delete by themselves (not what is below them) */
    write: (puts, dels, drops = []) =>
      idb.tx('readwrite', (st) => {
        for (const p of dels) {
          st.delete(p);
          st.delete(IDBKeyRange.bound(p + '/', p + '/￿'));
        }
        for (const p of drops) st.delete(p);
        for (const r of puts) st.put(r);
      })
  };

  const project = {
    roots: [],
    saved: new Map(), // path -> the entry object whose state is in IndexedDB
    dirty: new Set(),
    removed: new Set(),
    drop: new Set(), // records kept under an old name, to be deleted one by one (see move)
    hold: new Set(), // paths whose records must not be deleted just now (a forced stop: they may come back)
    ok: true,

    under(p) {
      return this.roots.some((r) => p === r || p.startsWith(r + '/'));
    },

    /** put the kept files back into the file system (called once, before anything else uses it).
        moved: [[old folder, new folder]] – files kept under a folder that has a new name now (the home folder was
        /home/student until October 2026): they are put into the new folder, and kept there from now on */
    async restore(fs, roots, moved = []) {
      this.roots = roots;
      let recs = [];
      try {
        recs = await idb.all();
      } catch (e) {
        this.ok = false;
        console.warn('The workbench cannot keep files in this browser (IndexedDB): ' + (e && e.message));
        toast('This browser does not let the workbench keep your files (private window, or storage turned off). Your work is lost when the page closes: download what you want to keep.', 'warn', 12000);
        return 0;
      }
      const fresh = new Set();
      if (moved.length) recs = await this.move(recs, moved, fresh);
      recs = recs.filter((r) => r && r.path);
      recs.sort((a, b) => (a.path < b.path ? -1 : 1));
      let n = 0;
      for (const r of recs) {
        if (!r || !r.path || !this.under(r.path)) continue;
        try {
          let e;
          if (r.k === 'd') {
            fs.mkdirp(r.path);
            e = fs.entries.get(r.path);
            if (r.mtime) e.mtime = r.mtime;
            if (r.perm != null) e.perm = r.perm;
          } else {
            if (r.k === 't') e = { kind: 'text', text: r.text || '' };
            else if (r.k === 'b') e = { kind: 'blob', blob: r.blob, kid: r.id };
            else if (r.k === 'u') e = { kind: 'url', url: new URL(r.url, location.href).href, size: r.size };
            else continue;
            Object.assign(e, { mtime: r.mtime || Date.now() });
            if (r.mode) e.mode = r.mode;
            if (r.readonly) e.readonly = true;
            if (r.perm != null) e.perm = r.perm;
            fs.put(r.path, e);
            e = fs.entries.get(r.path);
            if (e.kind === 'text') e.dirty = true;
            n++;
          }
          // (moved, but not yet kept under the new name in the browser's storage: the next flush does it – see move)
          if (fresh.has(r.path)) this.dirty.add(r.path);
          else this.saved.set(r.path, e);
        } catch (err) {
          /* a record that does not fit (a file where a folder is): left out */
        }
      }
      return n;
    },

    /** Files kept under a folder that has a new name now (moved: [[old, new]]) are kept under the new name: in the
        browser's storage, fifty at a time (each in a transaction of its own: a large file is copied, and storage that
        is nearly full must not stop everything). A file kept under both names: the newer one stays. Closing the page
        half way loses nothing – the rest is moved the next time. What cannot be moved now is written under the new
        name by the next flush (unsaved collects those paths), and its old record deleted then (drop).
        → the records, with the new names */
    async move(recs, moved, unsaved) {
      const at = new Map(recs.filter((r) => r && r.path).map((r) => [r.path, r]));
      const jobs = [];
      for (const r of recs) {
        const m = r && r.path && moved.find(([a]) => r.path === a || r.path.startsWith(a + '/'));
        if (!m) continue;
        const to = m[1] + r.path.slice(m[0].length), there = at.get(to);
        jobs.push({ from: r.path, rec: !there || (r.mtime || 0) > (there.mtime || 0) ? Object.assign({}, r, { path: to }) : null });
      }
      if (!jobs.length) return recs;
      for (let i = 0; i < jobs.length; i += 50) {
        const part = jobs.slice(i, i + 50);
        try {
          await idb.tx('readwrite', (st) => {
            for (const j of part) {
              if (j.rec) st.put(j.rec);
              st.delete(j.from);
            }
          });
        } catch (e) {
          for (const j of jobs.slice(i)) {
            if (j.rec) unsaved.add(j.rec.path);
            this.drop.add(j.from);
          }
          break;
        }
      }
      for (const j of jobs) {
        at.delete(j.from);
        if (j.rec) at.set(j.rec.path, j.rec);
      }
      return Array.from(at.values());
    },

    /** keep every change: what changed is written to IndexedDB a moment later */
    watch(fs) {
      this.fs = fs;
      fs.onChange((path, what) => {
        if (!this.under(path)) return;
        if (what === 'remove') {
          this.removed.add(path);
          for (const p of Array.from(this.dirty)) if (p === path || p.startsWith(path + '/')) this.dirty.delete(p);
        } else {
          this.dirty.add(path);
          // a folder that was moved or made: everything in it
          const e = fs.entries.get(path);
          if (e && e.kind === 'dir' && what === 'rename') for (const [p] of fs.entries) if (p.startsWith(path + '/')) this.dirty.add(p);
        }
        this._soon();
      });
      window.addEventListener('pagehide', () => this.flush());
      document.addEventListener('visibilitychange', () => document.visibilityState === 'hidden' && this.flush());
      // (files that could not be moved to a new folder at once: written there now – see move)
      if (this.dirty.size || this.removed.size || this.drop.size) this._soon();
    },
    _soon() {
      clearTimeout(this._t);
      this._t = setTimeout(() => this.flush(), 700);
      if (!this._first) this._first = Date.now();
      if (Date.now() - this._first > 5000) this.flush();
    },

    /** write what changed. → a promise that resolves when it is written */
    async flush() {
      clearTimeout(this._t);
      this._first = 0;
      if (!this.ok || !this.fs) return;
      if (this._busy) {
        this._again = true;
        return this._busy;
      }
      const fs = this.fs;
      const dirty = Array.from(this.dirty), removed = Array.from(this.removed), drops = Array.from(this.drop);
      this.dirty.clear();
      this.removed.clear();
      this.drop.clear();
      if (!dirty.length && !removed.length && !drops.length) return;
      bus.emit('files:saving', {});
      this._busy = (async () => {
        const puts = [], dels = [];
        for (const p of removed) {
          if (fs.entries.has(p) || this.hold.has(p)) continue; // made again since (it is in dirty), or it may come back
          dels.push(p);
          for (const k of Array.from(this.saved.keys())) if (k === p || k.startsWith(p + '/')) this.saved.delete(k);
        }
        for (const p of dirty) {
          const e = fs.entries.get(p);
          if (!e) continue;
          if (this.saved.get(p) === e) continue;
          const rec = { path: p, mtime: e.mtime || Date.now() };
          if (e.mode) rec.mode = e.mode;
          if (e.readonly) rec.readonly = true;
          if (e.perm != null) rec.perm = e.perm;
          if (e.kind === 'dir') rec.k = 'd';
          else if (e.kind === 'text') {
            rec.k = 't';
            rec.text = e.text;
          } else if (e.kind === 'url') {
            rec.k = 'u';
            rec.url = siteRelative(e.url); // the site may move: kept relative to it
            rec.size = e.size;
          } else if (e.kind === 'blob' || (MG.exec && MG.exec.holds(e))) {
            const size = fs.size(e);
            if (size > MAX_FILE) {
              this._big = this._big || new Set();
              if (!this._big.has(p)) toast(`<b>${esc(fs.pretty(p))}</b> is larger than 1 GB: it is here while the page is open, but it is not kept in the browser. Download it if you need it.`, 'warn', 10000);
              this._big.add(p);
              continue;
            }
            rec.k = 'b';
            try {
              rec.blob = e.kind === 'blob' ? e.blob : new Blob([await fs.readBytes(p)]);
            } catch (err) {
              this.dirty.add(p); // not readable just now (the programs are being restarted): next time
              continue;
            }
            if (fs.entries.get(p) !== e) {
              this.dirty.add(p); // it changed while it was read
              continue;
            }
            rec.id = newId();
            e.kid = rec.id;
          } else continue; // virtual
          puts.push(rec);
          this.saved.set(p, e);
        }
        try {
          if (puts.length || dels.length || drops.length) await idb.write(puts, dels, drops);
          bus.emit('files:saved', { n: puts.length, removed: dels.length });
        } catch (err) {
          puts.forEach((r) => {
            this.saved.delete(r.path);
            this.dirty.add(r.path);
          });
          dels.forEach((p) => this.removed.add(p));
          drops.forEach((p) => this.drop.add(p));
          bus.emit('files:notsaved', { error: String((err && err.message) || err) });
          if (!this._warned) {
            this._warned = true;
            const full = err && /quota/i.test(String(err.name || err.message));
            toast(full ? 'The browser has no more room for the workbench\'s files. Delete files you no longer need (or download them), so that new work can be kept.' : 'Your files could not be kept in this browser just now: ' + esc((err && err.message) || String(err)), 'warn', 12000);
          }
        }
      })();
      try {
        await this._busy;
      } finally {
        this._busy = null;
        if (this._again) {
          this._again = false;
          this._soon();
        }
      }
    },

    /** The programs were stopped by force: the files in `lost` lived in their memory. Each comes back as it was
        last kept in the browser (if it was). → how many came back */
    async afterKill(fs, lost) {
      lost.forEach((p) => this.hold.add(p));
      let n = 0;
      try {
        const recs = await idb.all();
        const byPath = new Map(recs.map((r) => [r.path, r]));
        for (const p of lost) {
          const r = byPath.get(p);
          if (!r || r.k !== 'b' || fs.exists(p) || !fs.isDir(MG.path.dirname(p))) continue;
          fs.put(p, { kind: 'blob', blob: r.blob, mtime: r.mtime, mode: r.mode || undefined, readonly: r.readonly || undefined, kid: r.id });
          this.saved.set(p, fs.entries.get(p));
          n++;
        }
      } catch (e) {
        /* nothing kept */
      } finally {
        lost.forEach((p) => this.hold.delete(p));
        this._soon();
      }
      return n;
    },

    /** how much the browser keeps for this site: { usage, quota } in bytes, or null */
    async usage() {
      try {
        if (navigator.storage && navigator.storage.estimate) return await navigator.storage.estimate();
      } catch (e) {
        /* not available */
      }
      return null;
    },
    /** ask the browser not to clear the workbench's storage when space runs low (once) */
    async persist() {
      try {
        if (navigator.storage && navigator.storage.persist && !(await navigator.storage.persisted())) await navigator.storage.persist();
      } catch (e) {
        /* not available */
      }
    },
    /** forget every file (Start afresh): the database and the file system below the roots */
    async reset(fs) {
      try {
        await idb.clear();
      } catch (e) {
        /* nothing kept */
      }
      this.saved.clear();
      this.dirty.clear();
      this.removed.clear();
      this.drop.clear();
      if (fs) for (const r of this.roots) for (const [p] of Array.from(fs.entries)) if (p.startsWith(r + '/')) fs.entries.delete(p);
    },

    /* ---------------- files from the user's computer ---------------- */
    /** put File objects (from an <input type=file> or a drop) into a folder. relPath (webkitRelativePath) keeps the
        folders of an uploaded folder. → the paths written */
    async addFiles(fs, folder, files) {
      const out = [];
      let big = 0;
      for (const f of files) {
        const rel = (f.webkitRelativePath || f.relativePath || f.name).replace(/^\/+/, '');
        const dest = fs.resolve(folder + '/' + rel);
        if (!this.under(dest)) continue;
        if (/\.zip$/i.test(f.name) && files.length === 1 && f.size < 500e6 && (await this._askUnzip(f.name))) {
          out.push(...(await this.unzip(fs, f, folder)));
          continue;
        }
        if (f.size > MAX_FILE) big++;
        fs.put(dest, { kind: 'blob', blob: f, mtime: f.lastModified || Date.now(), fresh: true });
        out.push(dest);
      }
      if (out.length) {
        this.persist();
        bus.emit('files:uploaded', { paths: out });
      }
      if (big) toast('Files larger than 1 GB are here while the page is open, but are not kept in the browser.', 'warn', 9000);
      return out;
    },
    _askUnzip(name) {
      return new Promise((resolve) => {
        const m = MG.modal('A .zip file', `<p><b>${esc(name)}</b> is a zip archive. Unpack its files into the folder, or keep the .zip as it is?</p><div class="prompt-actions"><button class="btn" data-x="keep" type="button">Keep the .zip</button><button class="btn primary" data-x="unzip" type="button">Unpack it</button></div>`);
        m.box.querySelector('[data-x="keep"]').addEventListener('click', () => (m.close(), resolve(false)));
        m.box.querySelector('[data-x="unzip"]').addEventListener('click', () => (m.close(), resolve(true)));
      });
    },
    /** unpack a .zip (a Blob, or the path of a file in the file system) into a folder. → the paths written */
    async unzip(fs, src, folder) {
      if (!window.JSZip) await loadScript('assets/vendor/jszip/jszip.min.js');
      const data = typeof src === 'string' ? await fs.readBytes(src) : src;
      const zip = await window.JSZip.loadAsync(data);
      const out = [];
      const names = Object.keys(zip.files);
      for (const name of names) {
        const z = zip.files[name];
        if (/(^|\/)__MACOSX\//.test(name) || /(^|\/)\.DS_Store$/.test(name)) continue;
        const dest = fs.resolve(folder + '/' + name.replace(/\/+$/, ''));
        if (!this.under(dest) || !dest.startsWith(fs.resolve(folder) + '/')) continue; // no ../ out of the folder
        if (z.dir) {
          fs.mkdirp(dest);
          continue;
        }
        const bytes = await z.async('uint8array');
        const when = z.date ? z.date.getTime() : Date.now();
        const exec = z.unixPermissions != null && (z.unixPermissions & 0o111) ? 'x' : undefined;
        const text = looksText(name, bytes);
        if (text != null) fs.put(dest, { kind: 'text', text, mtime: when, mode: exec, fresh: true });
        else fs.put(dest, { kind: 'blob', blob: new Blob([bytes]), mtime: when, mode: exec, fresh: true });
        out.push(dest);
      }
      bus.emit('files:unzipped', { folder, n: out.length });
      return out;
    },

    /* ---------------- downloads ---------------- */
    /** a .zip of a folder */
    async zip(root, opts = {}) {
      const fs = MG.app.fs;
      if (!window.JSZip) await loadScript('assets/vendor/jszip/jszip.min.js');
      const zip = new window.JSZip();
      const top = opts.top || root.split('/').pop() || 'files';
      const skip = opts.skip || /(^|\/)(__pycache__)(\/|$)/;
      let n = 0;
      for (const [p, e] of fs.entries) {
        if (!p.startsWith(root + '/')) continue;
        const rel = p.slice(root.length + 1);
        if (skip.test(rel) || (opts.only && !opts.only.test(rel))) continue;
        if (e.kind === 'dir') {
          zip.folder(top + '/' + rel);
          continue;
        }
        if (e.kind === 'virtual') continue;
        const bytes = await fs.readBytes(p);
        zip.file(top + '/' + rel, bytes, { date: new Date(e.mtime || Date.now()), unixPermissions: 0o100000 | (e.mode === 'x' ? (e.readonly ? 0o555 : 0o755) : e.readonly ? 0o444 : 0o644) });
        n++;
      }
      for (const [name, text] of Object.entries(opts.extra || {})) zip.file(top + '/' + name, text);
      const blob = await zip.generateAsync({ type: 'blob', compression: 'DEFLATE', compressionOptions: { level: 6 }, platform: 'UNIX' });
      return { blob, n };
    },
    async download(root, filename, opts) {
      const fs = MG.app.fs;
      if (!fs.isDir(root)) {
        toast(`There is no folder ${esc(fs.pretty(root))}.`, 'warn');
        return null;
      }
      const { blob, n } = await this.zip(root, opts);
      MG.downloadBlob(blob, filename);
      toast(`Saved <b>${esc(filename)}</b> (${n} files, ${MG.humanSize(blob.size)}B).`);
      bus.emit('project:download', { root, filename, files: n, size: blob.size });
      return blob;
    }
  };

  /** a URL of a file of this site, relative to the page (so that kept files still work if the site moves) */
  function siteRelative(url) {
    try {
      const base = new URL('.', location.href).href;
      return url.startsWith(base) ? url.slice(base.length) : url;
    } catch (e) {
      return url;
    }
  }

  /** text if the bytes are text (UTF-8, no NUL) and not too large to edit; else null */
  const BINARY = /\.(gz|bgz|bam|bai|cram|crai|bcf|csi|tbi|bt2|zip|pdf|png|jpe?g|gif|webp|ico|pkl|npy|npz|xlsx?|docx?|pptx?|rds|rda|rdata|sqlite|db|h5|hdf5|parquet|feather|whl|wasm|so|o|mmi)$/i;
  function looksText(name, bytes) {
    if (BINARY.test(name) || bytes.length > 8e6) return null;
    const head = bytes.subarray(0, 8192);
    for (let i = 0; i < head.length; i++) if (head[i] === 0) return null;
    try {
      return new TextDecoder('utf-8', { fatal: true }).decode(bytes);
    } catch (e) {
      return null;
    }
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = src;
      s.onload = resolve;
      s.onerror = () => reject(new Error('Could not load ' + src));
      document.head.appendChild(s);
    });
  }
  MG.loadScript = loadScript;
  MG.looksText = looksText;
  MG.project = project;
})();
