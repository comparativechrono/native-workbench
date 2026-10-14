/* =====================================================================
   The workbench's set-up: the file system (your files, kept in the
   browser, and the read-only examples), the terminal, the notebooks,
   and the other tabs – each built the first time it is shown.
   Also: opening a file in the right tab (a notebook in the Notebook
   tab, a structure in the 3D viewer, the rest in Files).
   ===================================================================== */
(function () {
  'use strict';
  const MG = window.MG;
  const { h, esc, bus, toast, store } = MG;
  const CFG = MG.config;
  MG.app = MG.app || {};
  MG.page = MG.page || {};
  MG.actions = MG.actions || {};

  const HOME = '/home/user';
  MG.app.HOME = HOME;
  /* The home folder was /home/student until October 2026. What the browser kept with that name moves to /home/user:
     the files (project.restore), and the paths in what the page remembers – the files that were open, the folders
     that were unfolded, the terminal's history, Galaxy's history, the conda environments. (A path written with the
     old name still leads home: see vfs.js.) */
  const OLD_HOME = '/home/student';
  function moveOldHome() {
    try {
      const pfx = (CFG.storePrefix || 'genomics') + ':';
      for (const k of Object.keys(localStorage)) {
        if (!k.startsWith(pfx)) continue;
        const v = localStorage.getItem(k);
        if (v && v.includes(OLD_HOME)) localStorage.setItem(k, v.replace(/\/home\/student(?![A-Za-z0-9_.-])/g, HOME));
      }
    } catch (e) {
      /* (the browser keeps nothing for the page) */
    }
  }
  MG.app.PROJECT = HOME; // (Galaxy and the assistant save things relative to this)
  const abs = (u) => new URL(u, location.href).href;
  const EX_TIME = Date.parse('2026-10-01T09:00:00Z');

  /* the example data: the list is written into the page by build/make_page.py (window.WB_EXAMPLES) */
  const EXAMPLES = (window.WB_EXAMPLES || []).map((f) => ({ path: '/data/examples/' + f.p, url: abs('data/examples/' + f.p), size: f.s, mtime: EX_TIME }));
  MG.app.exampleFiles = EXAMPLES;
  /* the notebooks a new user finds in ~/notebooks (data/starter/*.ipynb) */
  const STARTERS = window.WB_STARTERS || [];

  async function setupFs() {
    const fs = new MG.VFS(HOME);
    fs.mkdirp('/data/examples');
    for (const f of EXAMPLES) {
      fs.mkdirp(MG.path.dirname(f.path));
      fs.put(f.path, { kind: 'url', url: f.url, size: f.size, protected: true, readonly: true, mtime: f.mtime });
    }
    for (const [p, e] of fs.entries) if (e.kind === 'dir' && (p === '/data' || p.startsWith('/data/'))) e.protected = true;
    moveOldHome();
    // (where the programs run on this computer – the local runner –, the files are those of its folder on disk, and what
    // the page changes goes there: the browser keeps no copy of them – see exec-local.js)
    await MG.exec.whenChosen();
    let onDisk = !!MG.exec.capabilities.persistentFiles;
    if (onDisk)
      try {
        await MG.exec.restore(fs, [HOME, '/galaxy']);
      } catch (e) {
        // (the runner answered, but its files cannot be had: the page runs the programs itself, and says why)
        console.error(e);
        for (const p of Array.from(fs.entries.keys())) if (p.startsWith(HOME + '/') || p.startsWith('/galaxy')) fs.entries.delete(p);
        MG.exec.use('browser');
        MG.exec.notices.length = 0;
        MG.exec.fallback = { wanted: 'local', reason: String((e && e.message) || e), message: `The local runner answered, but the files of its folder could not be read (${(e && e.message) || e}). The programs run in this browser tab instead, with the files this browser keeps.` };
        onDisk = false;
      }
    if (!onDisk) await MG.project.restore(fs, [HOME, '/galaxy'], [[OLD_HOME, HOME]]);
    fs.cwd = HOME;
    // (with the runner, what the page writes from here on goes to the folder – the starter notebooks too)
    if (onDisk) MG.exec.watch(fs);
    // the first visit: a folder of notebooks to start from (a file that is there already is left alone). With the local
    // runner: a new, empty folder – the files of an analysis that is there already get nothing added to them.
    const first = onDisk ? !Array.from(fs.entries.keys()).some((p) => p.startsWith(HOME + '/')) : !store.get('seeded', false);
    if (first) {
      for (const s of STARTERS) {
        const path = HOME + '/' + s.p;
        if (fs.exists(path)) continue;
        try {
          const r = await fetch(abs('data/starter/' + s.p.split('/').pop()));
          if (r.ok) fs.writeText(path, await r.text());
        } catch (e) {
          /* offline: no starter */
        }
      }
      fs.mkdirp(HOME + '/notebooks');
      if (!onDisk) store.set('seeded', true);
    }
    if (!onDisk) MG.project.watch(fs);
    return fs;
  }

  MG.page.firstBench = 'notebook';
  MG.page.init = async function () {
    const fs = (MG.app.fs = await setupFs());
    MG.app.term = new MG.TerminalUI(document.getElementById('termRoot'), {
      fs,
      hostname: CFG.hostname || 'workbench',
      env: {},
      welcome:
        `This is a Linux terminal (bash) with real bioinformatics programs, running ${MG.exec.capabilities.where === 'local' ? 'on this computer' : 'in your browser'}. Your files: ~ (${HOME}). Examples (read-only): /data/examples. Type  help  for the programs,  man NAME  for one of them.` +
        (MG.user.name() === MG.user.DEFAULT ? ' To see your name in place of user, click “user” at the top of the page.' : '')
    });
    MG.app.nbApp = new MG.NotebookApp(document.getElementById('nbRoot'), { fs, dir: HOME + '/notebooks' });
    const last = store.get('nbOpen', null);
    const welcome = HOME + '/notebooks/welcome-python.ipynb';
    const start = (last && fs.exists(last) && last) || (fs.exists(welcome) && welcome) || (MG.app.nbApp.list()[0] || {}).path;
    if (start) await MG.app.nbApp.open(start, { delay: 2500 });
    else await MG.app.nbApp.newNotebook('python');
    MG.project.persist();
  };

  /* ------------------------------------------------------------------
     the tabs that are built when first shown
     ------------------------------------------------------------------ */
  MG.app.createViewer = function (root) {
    try {
      new MG.ViewerUI(root);
    } catch (e) {
      console.error(e);
      root.innerHTML = '<div class="ex-empty"><h3>The 3D viewer could not start</h3><p>This browser or computer may have 3D graphics (WebGL) switched off. Try Chrome, Edge, Firefox or Safari, and turn on “hardware acceleration” in the browser\'s settings.</p></div>';
      const noop = () => toast('The 3D viewer is not available in this browser.', 'error');
      MG.app.vui = { run: noop, log() {}, showTab() {}, showHelp() { noop(); }, tabs: {}, views: [] };
      MG.app.viewer = { structures: [], stage: { handleResize() {} } };
      MG.commands.run = async () => noop();
    }
  };
  const once = {};
  const loadOnce = (src) => (once[src] = once[src] || MG.loadScript(src));

  MG.page.lazy = {
    terminal: () => {},
    notebook: () => {},
    editor: (pane) => {
      MG.app.editor = new MG.Editor(pane.querySelector('#edRoot'), { fs: MG.app.fs });
    },
    galaxy: (pane) => {
      MG.app.galaxy = new MG.GalaxyApp(pane.querySelector('#gxRoot'), { fs: MG.app.fs });
    },
    apis: (pane) => {
      MG.app.apis = new MG.ApiExplorer(pane.querySelector('#apiRoot'));
    },
    viewer: async (pane) => {
      const root = pane.querySelector('#viewerRoot');
      root.innerHTML = '<div class="wb-loading"><span class="spinner"></span> Loading the 3D viewer…</div>';
      await loadOnce('assets/vendor/ngl/ngl.js');
      root.innerHTML = '';
      MG.app.createViewer(root);
    },
    igv: async (pane) => {
      const root = pane.querySelector('#igvRoot');
      root.innerHTML = '<div class="wb-loading"><span class="spinner"></span> Loading the genome browser…</div>';
      await loadOnce('assets/vendor/igv/igv.min.js');
      root.innerHTML = '';
      MG.app.igv = new MG.IGVPanel(root, {});
    },
    networks: async (pane) => {
      const root = pane.querySelector('#netRoot');
      root.innerHTML = '<div class="wb-loading"><span class="spinner"></span> Loading the network viewer…</div>';
      // Cytoscape.js and its layouts (fCoSE needs layout-base and cose-base before it), then the tab's own scripts
      for (const src of ['assets/vendor/cytoscape/cytoscape.min.js', 'assets/vendor/cytoscape/layout-base.js', 'assets/vendor/cytoscape/cose-base.js', 'assets/vendor/cytoscape/cytoscape-fcose.js', 'assets/vendor/cytoscape/cytoscape-dagre.min.js', 'assets/js/net-io.js', 'assets/js/net-algo.js', 'assets/js/networks.js']) await loadOnce(src);
      if (!MG.netLayoutsRegistered) {
        window.cytoscape.use(window.cytoscapeFcose);
        window.cytoscape.use(window.cytoscapeDagre);
        MG.netLayoutsRegistered = true;
      }
      root.innerHTML = '';
      MG.app.networks = new MG.NetworksPanel(root);
      await MG.app.networks.ready;
    },
    assistant: (pane) => {
      MG.app.ai = new MG.Assistant(pane.querySelector('#aiRoot'), { notebook: MG.app.nbApp });
    }
  };
  /* each time a tab is shown */
  MG.page.shown = {
    notebook: () => MG.app.nbApp && MG.app.nbApp.shown(),
    terminal: (pane, opts) => {
      if (MG.app.term && !(opts && opts.resize) && !window.matchMedia('(max-width: 900px)').matches) MG.app.term.focus();
    },
    editor: () => MG.app.editor && MG.app.editor.shown && MG.app.editor.shown(),
    galaxy: () => MG.app.galaxy && MG.app.galaxy.shown && MG.app.galaxy.shown(),
    viewer: () => MG.app.viewer && MG.app.viewer.stage && MG.app.viewer.stage.handleResize(),
    igv: () => MG.app.igv && MG.app.igv.shown && MG.app.igv.shown(),
    networks: () => MG.app.networks && MG.app.networks.shown && MG.app.networks.shown()
  };

  /* ------------------------------------------------------------------
     opening files: the right tab for each kind
     ------------------------------------------------------------------ */
  const STRUCTURE = /\.(pdb|ent|cif|mmcif|bcif|mol2|sdf|pqr|gro|mmtf)(\.gz)?$/i;
  const NETWORK = /\.(sif|graphml|xgmml|gml|cyjs|cx2)$/i;
  MG.app.isNetwork = (p) => NETWORK.test(p);
  const GENOMIC = /\.(bam|cram|vcf|vcf\.gz|bcf|bed|bed\.gz|gff3?|gtf|bedgraph|bdg|narrowpeak|broadpeak|gappedpeak|bw|bigwig|wig|seg)$/i;
  MG.app.isStructure = (p) => STRUCTURE.test(p);
  MG.app.isGenomic = (p) => GENOMIC.test(p);

  async function waitFor(get, ms = 4000) {
    for (let t = 0; t < ms && !get(); t += 50) await new Promise((r) => setTimeout(r, 50));
    return get();
  }
  /** edit or look at a file in the Files tab */
  MG.app.editFile = async (path, opts = {}) => {
    await MG.app.showWorkbench('editor');
    const ed = await waitFor(() => MG.app.editor);
    if (ed) await ed.openFile(path, opts);
  };
  /** open a file where it belongs: a notebook in Notebook, a structure in the 3D viewer, the rest in Files */
  MG.app.openFile = async (path, opts = {}) => {
    const fs = MG.app.fs;
    const p = fs.resolve(path);
    if (!opts.edit && /\.ipynb$/i.test(p)) {
      await MG.app.showWorkbench('notebook');
      return MG.app.nbApp.open(p);
    }
    if (!opts.edit && STRUCTURE.test(p)) return MG.app.viewStructure(p);
    if (!opts.edit && NETWORK.test(p)) return MG.app.netOpen([p]);
    return MG.app.editFile(p, opts);
  };
  /** show a folder or file in the Files tab */
  MG.app.revealFile = async (path) => {
    await MG.app.showWorkbench('editor');
    const ed = await waitFor(() => MG.app.editor);
    if (ed && ed.reveal) ed.reveal(MG.app.fs.resolve(path));
  };
  /** a structure file → the 3D viewer */
  MG.app.viewStructure = async (path) => {
    const fs = MG.app.fs;
    const p = fs.resolve(path);
    await MG.app.showWorkbench('viewer');
    const V = await waitFor(() => MG.app.viewer && MG.app.viewer.loadFile && MG.app.viewer, 15000);
    if (!V) return;
    const bytes = await fs.readBytes(p);
    await V.loadFile(new File([bytes], MG.path.basename(p)));
    bus.emit('viewer:fromfile', { path: p });
  };
  /** the 3D viewer, built and ready → the Viewer */
  MG.app.ensureViewer = async () => {
    await MG.app.showWorkbench('viewer');
    return waitFor(() => MG.app.vui && MG.app.viewer && MG.app.viewer.loadPDB && MG.app.viewer, 20000);
  };
  /** run a command of the 3D viewer (load 1MBN, color rainbow …), building the viewer first if need be */
  MG.app.viewerRun = async (cmd) => {
    await MG.app.ensureViewer();
    return MG.app.vui.run(cmd);
  };
  /* Files edited in the Files tab are saved with Save / Ctrl+S: before the page is left or reloaded with unsaved
     edits, the browser asks (it shows its own message). */
  window.addEventListener('beforeunload', (e) => {
    const ed = MG.app.editor;
    if (ed && ed.dirtyPaths && ed.dirtyPaths().length) {
      e.preventDefault();
      e.returnValue = '';
    }
  });

  /** keep something among your files (asks where; ~/data unless opts.folder says otherwise) → the path */
  MG.app.saveToFiles = (name, content, opts) => MG.apiTools.saveFile(name, content, opts);
  /** files → the genome browser */
  MG.app.igvLoad = async (paths) => {
    await MG.app.showWorkbench('igv');
    const I = await waitFor(() => MG.app.igv, 15000);
    if (I) await I.loadPaths(MG.app.fs, [].concat(paths));
  };
  /** the Networks tab, built and ready → its NetworksPanel */
  MG.app.networksReady = async () => {
    await MG.app.showWorkbench('networks');
    const N = await waitFor(() => MG.app.networks, 30000);
    if (!N) throw new Error('The Networks tab could not start.');
    await N.ready;
    return N;
  };
  /** network files (SIF, GraphML, XGMML, GML, Cytoscape JSON, CX2 – or tables of edges) → the Networks tab */
  MG.app.netOpen = async (paths, opts) => (await MG.app.networksReady()).openPaths([].concat(paths), opts || {});
  /** a table of values (DESeq2 results …) → the nodes of the network that is open */
  MG.app.netTable = async (path) => (await MG.app.networksReady()).importTableDialog({ path: MG.app.fs.resolve(path) });
  /** a network of net-io.js's form (nodes, edges) → a new network */
  MG.app.netFrom = async (obj, opts) => (await MG.app.networksReady()).addNetwork(obj, opts || {});
  /** STRING: {ids, species, score, type, add} → a network */
  MG.app.netString = async (opts) => (await MG.app.networksReady()).stringNetwork(opts);
  /* ▶ buttons of the help: data-net="example:airway", "analyse:mcode" … (see NetworksPanel.action) */
  MG.actions.net = async (spec) => (await MG.app.networksReady()).action(spec);

  /** a file → Galaxy's history */
  MG.app.toGalaxy = async (paths) => {
    await MG.app.showWorkbench('galaxy');
    const G = await waitFor(() => MG.app.galaxy, 8000);
    if (G && G.uploadPaths) await G.uploadPaths([].concat(paths));
  };

  /* ------------------------------------------------------------------
     ▶ buttons of the help pages
     data-example="reads/NA12878_R1.fastq"  copy an example into ~/examples
     data-new-nb="python|r"                  a new notebook
     data-open-nb="path"                     open a notebook
     ------------------------------------------------------------------ */
  MG.actions.example = async (rel) => {
    const fs = MG.app.fs;
    const src = '/data/examples/' + rel.replace(/^\/+/, '');
    if (!fs.exists(src)) throw new Error('There is no example ' + rel);
    const dest = HOME + '/examples/' + rel.replace(/^\/+/, '');
    if (fs.isDir(src)) {
      for (const [p, e] of Array.from(fs.entries)) if (p.startsWith(src + '/') && e.kind !== 'dir') fs.copy(p, dest + p.slice(src.length));
    } else fs.copy(src, dest);
    toast(`Copied to <b>${esc(fs.pretty(dest))}</b> – your own copy, which you can change.`, 'ok');
  };
  MG.actions.newNb = async (lang) => {
    await MG.app.showWorkbench('notebook');
    await MG.app.nbApp.newNotebook(lang === 'r' ? 'r' : 'python');
  };
  MG.actions.openNb = async (path) => {
    await MG.app.showWorkbench('notebook');
    const p = path.startsWith('~/') ? HOME + path.slice(1) : path;
    if (!MG.app.fs.exists(p)) throw new Error(`There is no notebook ${path} (was it renamed or deleted?)`);
    await MG.app.nbApp.open(p);
  };

  /* data-recipe="python|r": a page of the help as a notebook – its headings and text as text cells, its code
     (that of the language, and the terminal's as %%bash cells) as code cells – in ~/notebooks */
  function inlineMd(node) {
    let out = '';
    node.childNodes.forEach((n) => {
      if (n.nodeType === 3) out += n.textContent.replace(/\s+/g, ' ');
      else if (n.nodeType !== 1) return;
      else {
        const t = n.tagName.toLowerCase();
        const inner = () => inlineMd(n).trim();
        if (t === 'svg' || t === 'button' || t === 'script') return;
        if (t === 'b' || t === 'strong') out += '**' + inner() + '**';
        else if (t === 'i' || t === 'em') out += '*' + inner() + '*';
        else if (t === 'code' || t === 'kbd') out += '`' + n.textContent + '`';
        else if (t === 'br') out += '\n';
        else if (t === 'a') {
          const href = n.getAttribute('href') || '';
          out += /^https?:/.test(href) ? `[${inner()}](${href})` : inner();
        } else out += inlineMd(n);
      }
    });
    return out;
  }
  function blockMd(el) {
    const t = el.tagName.toLowerCase();
    const line = (s) => s.replace(/[ \t]+\n/g, '\n').trim();
    if (/^h[1-4]$/.test(t)) return '#'.repeat(+t[1]) + ' ' + line(inlineMd(el));
    if (t === 'p') return line(inlineMd(el));
    if (t === 'ul' || t === 'ol') return Array.from(el.children).map((li, i) => (t === 'ol' ? `${i + 1}. ` : '- ') + line(inlineMd(li))).join('\n');
    if (t === 'dl') return Array.from(el.children).map((x) => (x.tagName === 'DT' ? '**' + line(inlineMd(x)) + '**' : line(inlineMd(x)))).join('\n\n');
    if (t === 'table') {
      const rows = Array.from(el.querySelectorAll('tr')).map((tr) => Array.from(tr.children).map((c) => line(inlineMd(c)).replace(/\|/g, '\\|')));
      if (!rows.length) return '';
      const w = rows[0].length;
      return ['| ' + rows[0].join(' | ') + ' |', '|' + ' --- |'.repeat(w)].concat(rows.slice(1).map((r) => '| ' + r.join(' | ') + ' |')).join('\n');
    }
    if (el.classList.contains('callout')) return Array.from(el.children).map((c) => (c.classList.contains('co-t') ? '**' + line(inlineMd(c)) + '**' : blockMd(c))).filter(Boolean).join('\n\n').split('\n').map((l) => '> ' + l).join('\n');
    return '';
  }
  MG.actions.recipe = async (lang, btn) => {
    const art = btn && btn.closest('article.help-page');
    if (!art) return;
    const L = lang === 'r' ? 'r' : 'python';
    const want = L === 'r' ? 'r' : 'py';
    const cells = [];
    const md = (text) => {
      text = (text || '').trim();
      if (!text) return;
      const last = cells[cells.length - 1];
      if (last && last.type === 'markdown') last.source += '\n\n' + text;
      else cells.push({ type: 'markdown', source: text });
    };
    const title = art.dataset.title || 'Recipe';
    const day = new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });
    for (const el of Array.from(art.children)) {
      if (el.matches('.tryrow, .help-crumbs, .help-nav, nav')) continue;
      const pre = el.matches('pre') ? el : el.matches('.code-box') ? el.querySelector('pre') : null;
      if (pre) {
        const kind = pre.dataset.run || '';
        const code = (pre.querySelector('code') || pre).textContent.replace(/\n+$/, '');
        if (kind === want) cells.push({ type: 'code', source: code });
        else if (kind === 'term') cells.push({ type: 'code', source: '%%bash\n' + code });
        else if (!kind) md('```\n' + code + '\n```');
        continue;
      }
      if (el.matches('h1')) {
        md('# ' + title + '\n\n*A recipe from the help of the Bioinformatics workbench, as a notebook (' + day + '). Run the cells from the top, in order.*');
        continue;
      }
      md(blockMd(el));
    }
    const fs = MG.app.fs;
    const stem = 'recipe-' + art.id.replace(/^h-recipe-/, '').replace(/^h-/, '') + (L === 'r' ? '-R' : '');
    let path = `${HOME}/notebooks/${stem}.ipynb`;
    for (let i = 2; fs.exists(path); i++) path = `${HOME}/notebooks/${stem}-${i}.ipynb`;
    fs.mkdirp(MG.path.dirname(path));
    fs.writeText(path, JSON.stringify(MG.nbformat.make(L, cells), null, 1));
    await MG.app.showWorkbench('notebook');
    await MG.app.nbApp.open(path);
    toast(`The recipe is now the notebook <b>${esc(fs.pretty(path))}</b> – run its cells from the top.`, 'ok', 5000);
  };

  /* Start afresh: forget the open notebooks first */
  MG.page.beforeReset = async () => {
    store.remove('nbOpen');
    store.remove('seeded');
    store.remove('termHistory');
  };
})();
