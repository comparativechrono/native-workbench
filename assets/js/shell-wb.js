/* =====================================================================
   What the workbench's terminal has beyond the shared shell (shell.js,
   shell-lang.js, shell-extra.js, tools-wasm.js):

     python, pip            Python (Pyodide) – the notebook's Python; pip
                            installs packages for this visit (micropip)
     Rscript, R             R (webR) – the notebook's R
     snakemake              Snakemake (the browser edition), see smk.py
     conda, mamba           a model of conda environments (every program
                            is always there: nothing is gated by them)
     dot                    Graphviz, compiled to WebAssembly
     curl, wget             downloads from web services that allow it
     unzip, zip, tar        archives
     igv                    show files in the Genome browser tab
     network                open networks in the Networks tab
     help, man              the programs of the workbench
   ===================================================================== */
(function () {
  'use strict';
  const MG = window.MG;
  const B = MG.shellBuiltins;
  const T = MG.shellTools;
  const { userErr, linesOf } = MG.shellUtil;
  const enc = new TextEncoder();
  const unsavedNote = (ctx) => MG.unsavedNote && MG.unsavedNote(ctx);

  /** the bytes that are piped into a command */
  async function stdinBytes(ctx) {
    const s = ctx.stdin;
    if (s == null) {
      const rest = MG.shellUtil.inherited ? MG.shellUtil.inherited(ctx) : null;
      return rest == null ? new Uint8Array(0) : enc.encode(rest);
    }
    if (MG.FileRef && s instanceof MG.FileRef) return await MG.exec.readBytes(s);
    return typeof s === 'string' ? enc.encode(s) : s instanceof Uint8Array ? s : enc.encode(String(s));
  }

  /* ------------------------------------------------------------------ the examples of the manual pages */
  const EX = '/data/examples/reads';
  const MAN = {
    minimap2: `minimap2 -ax sr ${EX}/reference.fa ${EX}/NA12878_R1.fastq ${EX}/NA12878_R2.fastq > mapped.sam`,
    samtools: 'samtools sort -o mapped.bam mapped.sam\nsamtools index mapped.bam\nsamtools flagstat mapped.bam\nsamtools view mapped.bam human_CYP2C19:11600-11620 | head',
    bcftools: `bcftools mpileup -f ${EX}/reference.fa mapped.bam -Ou | bcftools call -mv -Oz -o calls.vcf.gz\nbcftools view -H calls.vcf.gz | head\nUse bcftools COMMAND --help for the options of a command.`,
    bgzip: 'bgzip -c INPUT > OUTPUT.gz',
    tabix: 'tabix -p vcf calls.vcf.gz',
    fastp: `fastp -i ${EX}/NA12878_R1.fastq -I ${EX}/NA12878_R2.fastq -o trimmed_R1.fastq -O trimmed_R2.fastq -h fastp.html -j fastp.json\nopen fastp.html`,
    bowtie2: `bowtie2-build ${EX}/reference.fa reference\nbowtie2 -x reference -1 ${EX}/NA12878_R1.fastq -2 ${EX}/NA12878_R2.fastq -S mapped.sam`,
    'bowtie2-build': `bowtie2-build ${EX}/reference.fa reference`,
    'bowtie2-align-s': `bowtie2-align-s -x reference -1 ${EX}/NA12878_R1.fastq -2 ${EX}/NA12878_R2.fastq -S mapped.sam`,
    'bowtie2-build-s': `bowtie2-build-s ${EX}/reference.fa reference`,
    seqtk: `seqtk fqchk ${EX}/NA12878_R1.fastq | head\nseqtk seq -a ${EX}/NA12878_R1.fastq > reads.fasta\nseqtk sample -s 11 ${EX}/NA12878_R1.fastq 1000 > sample.fastq`,
    bedtools: 'bedtools genomecov -ibam mapped.bam -bg | head\nbedtools intersect -a regions.bed -b genes.bed',
    jq: 'jq . fastp.json | head\njq .summary fastp.json'
  };
  for (const [name, example] of Object.entries(MAN)) if (T[name]) T[name].man = `${name} ${T[name].version} · compiled program, running in your browser\n\n${example}`;
  // md5sum is the GNU program; the tasks of the practical hear of a check (md5sum -c) and of new checksums as before
  if (T.md5sum) {
    const run = T.md5sum.run;
    T.md5sum.run = async (ctx) => {
      const check = ctx.args.some((a) => a === '--check' || /^-[a-z]*c/.test(a));
      const code = (await run(ctx)) || 0;
      if (check) MG.bus.emit('hash:check', { name: 'md5sum', ok: code === 0 });
      else if (!code) MG.bus.emit('hash:made', { name: 'md5sum', files: ctx.args.filter((a) => !a.startsWith('-')) });
      return code;
    };
  }

  /* ------------------------------------------------------------------ Python, pip */
  const pyVersion = () => (MG.py && MG.py.versions && MG.py.versions.python) || '3.13';
  async function runPython(ctx) {
    const a = ctx.args;
    if (a[0] === '--version' || a[0] === '-V') {
      if (!(MG.py && MG.py.versions)) ctx.io.note('(Python has not started yet; this is the version it will be.)');
      ctx.out(`Python ${pyVersion()}\n`);
      return 0;
    }
    if (a[0] === '--help' || a[0] === '-h') {
      ctx.out('usage: python [option] ... [-c cmd | -m mod | file] [arg] ...\n  -c cmd : a program passed in as a string\n  -m mod : run a module as a script (python -m pip … is pip)\n  file   : a program read from a script file\n  -V     : print the Python version number and exit (also --version)\nFor interactive Python use the Notebook tab (a Python notebook).\n');
      return 0;
    }
    if (a[0] === '-m' && (a[1] === 'pip' || a[1] === 'venv')) {
      if (a[1] === 'pip') return B.pip(Object.assign({}, ctx, { args: a.slice(2) }));
      ctx.err('The venv module cannot make environments in this browser: there is one Python here. Install packages with  pip install NAME.\n');
      return 1;
    }
    if (!MG.py) throw userErr('python: Python is not available on this page');
    if (a.length) unsavedNote(ctx);
    return MG.py.term('python', a, ctx);
  }
  B.python = runPython;
  B.python3 = runPython;
  B.pip = async (ctx) => {
    const [sub] = ctx.args;
    if (sub === '--version' || sub === '-V') {
      ctx.out(`pip (micropip, Pyodide) for Python ${pyVersion()}\n`);
      return 0;
    }
    if (sub === 'uninstall') {
      ctx.err('pip uninstall: not needed here – what pip installs lasts until the page is reloaded (or Python restarted).\n');
      return 1;
    }
    if (!MG.py) throw userErr('pip: Python is not available on this page');
    return MG.py.term('pip', ctx.args, ctx);
  };
  B.pip3 = B.pip;

  /* ------------------------------------------------------------------ R */
  const rVersion = () => {
    const K = MG.kernels && MG.kernels.peek('r');
    return (K && K.versions && K.versions.r) || '4.6';
  };
  async function startR(ctx) {
    const K = MG.kernels.get('r');
    if (K.state !== 'ready') {
      ctx.io.note('Starting R in your browser (the first time this downloads about 25 MB and takes 10–30 seconds)…');
      if (ctx.term && ctx.term.statusEl) ctx.term.statusEl.innerHTML = '<span class="spinner small"></span> starting R…';
    }
    try {
      await K.ensure();
    } catch (e) {
      throw userErr('R could not start: ' + e.message);
    }
    if (ctx.term && ctx.term.statusEl) ctx.term.statusEl.innerHTML = '<span class="spinner small"></span> R is running…';
    return K;
  }
  B.Rscript = async (ctx) => {
    const a = ctx.args.slice();
    if (!a.length || a[0] === '--help') {
      ctx.out('Usage: Rscript [options] file [args]\n   or: Rscript [options] -e expr [-e expr2 ...] [args]\n  --version   print the version of R\n  -e EXPR     run the R expression(s)\nPlots made by a script go to Rplots.pdf (or use png("file.png") … dev.off()).\nFor interactive R use the Notebook tab (an R notebook).\n');
      return a.length ? 0 : 1;
    }
    if (a[0] === '--version') {
      ctx.out(`Rscript (R) version ${rVersion()} (webR, in your browser)\n`);
      return 0;
    }
    while (a.length && /^--(vanilla|no-save|no-restore|no-environ|no-site-file|no-init-file|quiet|silent|slave|no-echo|verbose|default-packages=.*)$/.test(a[0])) a.shift();
    const exprs = [];
    while (a[0] === '-e' && a.length > 1) {
      a.shift();
      exprs.push(a.shift());
    }
    let file = null;
    if (!exprs.length) {
      file = a.shift();
      if (!file) throw userErr('Rscript: give a file (Rscript script.R) or an expression (Rscript -e "1 + 1")');
      if (!ctx.fs.exists(file)) {
        ctx.err(`Fatal error: cannot open file '${file}': No such file or directory\n`);
        return 2;
      }
    }
    unsavedNote(ctx);
    const io = { out: (t) => ctx.out(t), err: (t) => ctx.err(t) };
    const run = async () => {
      const K = await startR(ctx);
      // (Ctrl+C while R was starting: the script does not run)
      if (ctx.term && ctx.term.cancelled) return 130;
      return K.script({ file: file ? ctx.fs.resolve(file) : null, code: exprs.join('\n'), args: a, cwd: ctx.fs.cwd, fs: ctx.fs }, io);
    };
    // (in the terminal a second Ctrl+C – while R starts, or while the script runs – ends the command and restarts R:
    // see inKernel in terminal.js)
    const code = ctx.term && ctx.term.inKernel ? await ctx.term.inKernel(MG.kernels.get('r'), run()) : await run();
    MG.bus.emit('r:script', { file, code });
    return code;
  };
  B.R = async (ctx) => {
    const a = ctx.args;
    if (a[0] === '--version' || a[0] === '-V') {
      ctx.out(`R version ${rVersion()} – webR, R compiled to WebAssembly, running in your browser\n`);
      return 0;
    }
    if (a[0] === 'CMD') throw userErr('R CMD is not available here (it builds and checks packages with a compiler). Packages for the browser come ready-made:  Rscript -e \'install.packages("NAME")\'');
    const ei = a.indexOf('-e');
    if (ei >= 0) return B.Rscript(Object.assign({}, ctx, { args: a.slice(ei) }));
    const fi = a.findIndex((x) => /^--file=/.test(x) || x === '-f');
    if (fi >= 0) return B.Rscript(Object.assign({}, ctx, { args: [a[fi] === '-f' ? a[fi + 1] : a[fi].slice(7)] }));
    ctx.err('R\'s interactive console is not available in this terminal. Use an R notebook (Notebook tab → Notebooks → New R notebook), or run R code with  Rscript script.R  or  Rscript -e \'summary(cars)\'.\n');
    return 1;
  };

  /* ------------------------------------------------------------------ conda / mamba */
  const C = () => MG.conda;
  function envTable() {
    const names = Object.keys(C().envs).sort((a, b) => (a === 'base' ? -1 : b === 'base' ? 1 : a.localeCompare(b)));
    const w = Math.max(24, ...names.map((n) => n.length + 2));
    return '# conda environments:\n#\n' + names.map((n) => `${n.padEnd(w)} ${n === C().active ? '*' : ' '}  ${C().prefix(n)}`).join('\n') + '\n\n';
  }
  function listTable(name) {
    const pk = C().packages(name);
    const rows = pk.map((p) => {
      const c = C().CATALOGUE[p];
      const vb = C().version(name, p);
      return `${p.padEnd(25)} ${vb.v.padEnd(15)} ${vb.build.padStart(15)}    ${c.ch}`;
    });
    return `# packages in environment at ${C().prefix(name)}:\n#\n# Name                    Version                   Build  Channel\n` + rows.join('\n') + '\n';
  }
  function exportYaml(name, fromHistory) {
    const env = C().envs[name];
    const deps = fromHistory ? env.specs.filter((s) => s !== 'conda') : C().packages(name).map((p) => {
      const vb = C().version(name, p);
      return `${p}=${vb.v}=${vb.build}`;
    });
    return `name: ${name}\nchannels:\n${env.channels.map((c) => '  - ' + c).join('\n')}\ndependencies:\n${deps.map((d) => '  - ' + d).join('\n')}\nprefix: ${C().prefix(name)}\n`;
  }
  function planText(name, specs, channels, pkgs, pins) {
    const lines = [];
    lines.push('Channels:');
    (channels.length ? channels : ['conda-forge', 'bioconda']).forEach((c) => lines.push(' - ' + c));
    lines.push('Platform: linux-64 (in your web browser)');
    lines.push('Collecting package metadata (repodata.json): done');
    lines.push('Solving environment: done');
    lines.push('');
    lines.push('## Package Plan ##');
    lines.push('');
    lines.push(`  environment location: ${C().prefix(name)}`);
    lines.push('');
    lines.push('  added / updated specs:');
    specs.forEach((s) => lines.push('    - ' + s));
    lines.push('');
    lines.push('');
    lines.push('The following NEW packages will be INSTALLED:');
    lines.push('');
    const all = new Set();
    const add = (p) => {
      const c = C().CATALOGUE[p];
      if (!c || all.has(p)) return;
      all.add(p);
      (c.deps || []).forEach(add);
    };
    pkgs.forEach(add);
    Array.from(all).sort().forEach((p) => {
      const c = C().CATALOGUE[p];
      const v = (pins && pins[p]) || c.v;
      const build = v === c.v ? c.build : (c.alt || {})[v] || c.build;
      lines.push(`  ${p.padEnd(18)} ${c.ch}/linux-64::${p}-${v}-${build}`);
    });
    lines.push('');
    return lines.join('\n') + '\n';
  }
  /* conda's message when two packages need different versions of the same library */
  function conflictText(all, channels) {
    const conflicts = all.filter((c) => c.lib === all[0].lib); // conda reports one problem at a time
    const lines = ['Channels:'].concat((channels && channels.length ? channels : ['conda-forge', 'bioconda']).map((c) => ' - ' + c));
    lines.push('Platform: linux-64', 'Collecting package metadata (repodata.json): done', 'Solving environment: failed', '');
    lines.push('LibMambaUnsatisfiableError: Encountered problems while solving:');
    const tools = conflicts.filter((c) => c.pkg !== c.lib);
    const pin = conflicts.find((c) => c.pkg === c.lib);
    const loser = tools[tools.length - 1];
    lines.push(`  - package ${loser.text}, but none of the providers can be installed`, '', 'Could not solve for environment specs', 'The following packages are incompatible');
    const rows = [];
    if (pin) rows.push([pin.spec, 'is requested and can be installed;']);
    tools.forEach((c, i) => {
      const last = i === tools.length - 1;
      rows.push([c.spec, last ? 'is not installable because it requires' : 'is installable and it requires', `${c.lib} >=${c.range[0]},<${c.range[1]}.0a0 *, ${last ? 'which conflicts with any installable versions previously reported.' : 'which can be installed;'}`]);
    });
    rows.forEach((r, i) => {
      const end = i === rows.length - 1;
      lines.push(`${end ? '└─' : '├─'} ${r[0]} ${r[1]}`);
      if (r[2]) lines.push(`${end ? '   ' : '│  '}└─ ${r[2]}`);
    });
    return lines.join('\n') + '\n\n';
  }
  function notFound(problems) {
    return `\nPackagesNotFoundError: The following packages are not available from current channels:\n\n${problems.join('\n')}\n\nCurrent channels:\n\n  - https://conda.anaconda.org/conda-forge\n  - https://conda.anaconda.org/bioconda\n\n`;
  }
  async function condaCmd(ctx) {
    const args = ctx.args.slice();
    const sub = args.shift();
    const cmdName = ctx.name || 'conda';
    const opt = (names) => {
      for (const n of names) {
        const i = args.indexOf(n);
        if (i >= 0) {
          const v = args[i + 1];
          args.splice(i, 2);
          return v;
        }
        const j = args.findIndex((a) => a.startsWith(n + '='));
        if (j >= 0) {
          const v = args[j].split('=').slice(1).join('=');
          args.splice(j, 1);
          return v;
        }
      }
      return null;
    };
    const flag = (names) => {
      let hit = false;
      names.forEach((n) => {
        const i = args.indexOf(n);
        if (i >= 0) {
          args.splice(i, 1);
          hit = true;
        }
      });
      return hit;
    };
    if (!sub || sub === '-h' || sub === '--help') {
      ctx.out(`usage: ${cmdName} [-h] [-v] [--version] COMMAND ...\n\ncommands:\n  activate     Activate a conda environment.\n  deactivate   Deactivate the current active conda environment.\n  create       Create a new conda environment from a list of specified packages.\n  env          See \`conda env --help\` (create -f, export, list, remove).\n  info         Display information about current conda install.\n  install      Install a list of packages into a specified conda environment.\n  list         List installed packages in a conda environment.\n  remove       Remove a list of packages from a specified conda environment.\n  search       Search for packages and display associated information.\n`);
      return 0;
    }
    if (sub === '--version' || sub === '-V') {
      ctx.out(`${cmdName === 'mamba' ? 'mamba 2.3.2\nconda' : 'conda'} ${C().VERSION}\n`);
      return 0;
    }
    if (sub === 'activate') {
      const name = args.filter((a) => !a.startsWith('-'))[0] || 'base';
      const n = C().envs[name] ? name : Object.keys(C().envs).find((k) => C().prefix(k) === name);
      if (!n) {
        ctx.err(`\nEnvironmentNameNotFound: Could not find conda environment: ${name}\nYou can list all discoverable environments with \`conda info --envs\`.\n\n`);
        return 1;
      }
      if (C().active !== n) C().stack.push(n);
      if (C().stack.length > 6) C().stack.splice(1, C().stack.length - 6);
      C().save();
      MG.bus.emit('conda:activate', { name: n });
      return 0;
    }
    if (sub === 'deactivate') {
      if (C().stack.length > 1) C().stack.pop();
      C().save();
      MG.bus.emit('conda:deactivate', { name: C().active });
      return 0;
    }
    if (sub === 'info') {
      if (flag(['--envs', '-e'])) {
        ctx.out(envTable());
        return 0;
      }
      ctx.out(`\n     active environment : ${C().active}\n    active env location : ${C().prefix(C().active)}\n       user config file : ${HOME()}/.condarc\n          conda version : ${C().VERSION}\n       python version : ${pyVersion()}\n       base environment : ${C().ROOT}  (writable)\n           channel URLs : https://conda.anaconda.org/conda-forge/linux-64\n                          https://conda.anaconda.org/bioconda/linux-64\n               platform : linux-64 (WebAssembly in your browser)\n\n`);
      return 0;
    }
    if (sub === 'list') {
      const name = opt(['-n', '--name']) || C().active;
      if (!C().envs[name]) {
        ctx.err(`\nEnvironmentLocationNotFound: Not a conda environment: ${C().prefix(name)}\n\n`);
        return 1;
      }
      if (flag(['--export', '-e'])) {
        ctx.out(`# This file may be used to create an environment using:\n# $ conda create --name <env> --file <this file>\n# platform: linux-64\n` + C().packages(name).map((p) => {
          const vb = C().version(name, p);
          return `${p}=${vb.v}=${vb.build}`;
        }).join('\n') + '\n');
        return 0;
      }
      const pat = args.filter((a) => !a.startsWith('-'))[0];
      let text = listTable(name);
      if (pat) text = text.split('\n').filter((l) => l.startsWith('#') || l.includes(pat)).join('\n') + '\n';
      ctx.out(text);
      return 0;
    }
    if (sub === 'search') {
      const q = args.filter((a) => !a.startsWith('-'))[0] || '';
      const name = q.split(/[=<>]/)[0];
      const hits = Object.keys(C().CATALOGUE).filter((k) => !C().CATALOGUE[k].dep && k.includes(name));
      if (!hits.length) {
        ctx.err(notFound([`  - ${q}`]));
        return 1;
      }
      ctx.out('Loading channels: done\n# Name                       Version           Build  Channel\n' + hits.map((k) => `${k.padEnd(28)} ${C().CATALOGUE[k].v.padEnd(17)} ${C().CATALOGUE[k].build.padEnd(6)} ${C().CATALOGUE[k].ch}`).join('\n') + '\n');
      ctx.io.note('A real conda search lists every published version; this browser has exactly one version of each program.');
      return 0;
    }
    if (sub === 'env') {
      const sub2 = args.shift();
      if (sub2 === 'list') {
        ctx.out(envTable());
        return 0;
      }
      if (sub2 === 'export') {
        const name = opt(['-n', '--name']) || C().active;
        const hist = flag(['--from-history']);
        const file = opt(['-f', '--file']);
        if (!C().envs[name]) {
          ctx.err(`\nEnvironmentLocationNotFound: Not a conda environment: ${C().prefix(name)}\n\n`);
          return 1;
        }
        const y = exportYaml(name, hist);
        if (file) ctx.fs.writeText(file, y);
        else ctx.out(y);
        MG.bus.emit('conda:export', { name, fromHistory: hist });
        return 0;
      }
      if (sub2 === 'remove') {
        const name = opt(['-n', '--name']);
        flag(['-y', '--yes']);
        return removeEnv(ctx, name);
      }
      if (sub2 === 'create') {
        const file = opt(['-f', '--file']) || 'environment.yml';
        let name = opt(['-n', '--name']);
        flag(['-y', '--yes']);
        let text;
        try {
          text = await ctx.fs.readText(file);
        } catch (e) {
          ctx.err(`\nEnvironmentFileNotFound: '${ctx.fs.resolve(file)}' file not found\n\n`);
          return 1;
        }
        const y = parseEnvYaml(text);
        if (!y) {
          ctx.err(`\nEnvironmentFileNotFound or invalid YAML: ${file} needs  name:,  channels:  and  dependencies:\n\n`);
          return 1;
        }
        name = name || y.name;
        if (!name) {
          ctx.err('\nCondaValueError: the environment file has no name: – give one with  -n NAME\n\n');
          return 1;
        }
        return createEnv(ctx, name, y.deps, y.channels, true);
      }
      ctx.err(`usage: conda env [-h] {create,export,list,remove} ...\n`);
      return 2;
    }
    if (sub === 'create') {
      const name = opt(['-n', '--name']);
      const channels = [];
      let ch;
      while ((ch = opt(['-c', '--channel']))) channels.push(ch);
      const file = opt(['--file']);
      flag(['-y', '--yes', '--quiet', '-q']);
      if (!name) {
        ctx.err('\nCondaValueError: one of the arguments -n/--name -p/--prefix is required\n\n');
        return 2;
      }
      let specs = args.filter((a) => !a.startsWith('-'));
      if (file) specs = specs.concat(linesOf(await ctx.fs.readText(file)).filter((l) => l.trim() && !l.startsWith('#')));
      return createEnv(ctx, name, specs, channels, false);
    }
    if (sub === 'install') {
      const name = opt(['-n', '--name']) || C().active;
      const channels = [];
      let ch;
      while ((ch = opt(['-c', '--channel']))) channels.push(ch);
      flag(['-y', '--yes', '--quiet', '-q']);
      const specs = args.filter((a) => !a.startsWith('-'));
      if (!C().envs[name]) {
        ctx.err(`\nEnvironmentLocationNotFound: Not a conda environment: ${C().prefix(name)}\n\n`);
        return 1;
      }
      const env0 = C().envs[name];
      const r = C().solve(env0.specs.filter((x) => x !== 'conda').concat(specs));
      if (r.problems.length) {
        ctx.err(notFound(r.problems));
        ctx.io.note('On a real computer conda would download these from the internet. This browser has exactly one version of each program: see  conda search NAME');
        return 1;
      }
      if (r.conflicts.length && name !== 'pipelines') {
        ctx.err(conflictText(r.conflicts, channels));
        ctx.io.note(conflictNote(r.conflicts));
        return 1;
      }
      ctx.out(planText(name, specs, channels, r.pkgs, r.pins) + '\nProceed ([y]/n)? y\n\nDownloading and Extracting Packages: done\nPreparing transaction: done\nVerifying transaction: done\nExecuting transaction: done\n');
      const env = C().envs[name];
      env.specs = Array.from(new Set(env.specs.concat(specs)));
      env.pkgs = Array.from(new Set(env.pkgs.concat(r.pkgs)));
      env.pins = Object.assign({}, env.pins || {}, r.pins);
      C().save();
      r.notes.forEach((n) => ctx.io.note(n));
      return 0;
    }
    if (sub === 'remove' || sub === 'uninstall') {
      const name = opt(['-n', '--name']) || C().active;
      flag(['-y', '--yes']);
      if (flag(['--all'])) return removeEnv(ctx, name);
      const env = C().envs[name];
      if (!env) {
        ctx.err(`\nEnvironmentLocationNotFound: Not a conda environment: ${C().prefix(name)}\n\n`);
        return 1;
      }
      const names = args.filter((a) => !a.startsWith('-'));
      env.pkgs = env.pkgs.filter((p) => !names.includes(p));
      env.specs = env.specs.filter((s) => !names.includes(s.split(/[=<>]/)[0]));
      C().save();
      ctx.out(`\n## Package Plan ##\n\n  environment location: ${C().prefix(name)}\n\n  removed specs:\n${names.map((n) => '    - ' + n).join('\n')}\n\nPreparing transaction: done\nVerifying transaction: done\nExecuting transaction: done\n`);
      return 0;
    }
    if (sub === 'config' || sub === 'init' || sub === 'update' || sub === 'clean') {
      ctx.io.note(`conda ${sub} is not needed in the browser.`);
      return 0;
    }
    ctx.err(`${cmdName}: error: argument COMMAND: invalid choice: '${sub}'\n`);
    return 2;
  }
  function conflictNote(all) {
    const lib = all[0].lib;
    const conflicts = all.filter((c) => c.lib === lib);
    const pin = conflicts.find((c) => c.pkg === c.lib);
    const tools = conflicts.filter((c) => c.pkg !== c.lib);
    const C = MG.conda.CATALOGUE;
    const cmp = (a, b) => (MG.conda.versionOk(a, '>', b) ? 1 : MG.conda.versionOk(a, '==', b) ? 0 : -1);
    const libName = lib === 'libzlib' ? 'zlib' : lib;
    const nice = (p) => (p === 'python' ? 'Python ' + C[p].v.split('.').slice(0, 2).join('.') : `${p} ${C[p].v}`);
    const join = (xs) => (xs.length < 2 ? xs.join('') : xs.slice(0, -1).join(', ') + ' and ' + xs[xs.length - 1]);
    // which bound decides: the lowest upper bound, or the highest lower bound
    const minHi = tools.map((c) => c.range[1]).reduce((a, b) => (cmp(a, b) <= 0 ? a : b));
    const older = tools.filter((c) => !pin && c.range[1] === minHi && tools.some((o) => cmp(o.range[0], minHi) >= 0));
    const newer = tools.filter((c) => !older.includes(c));
    const parts = [];
    if (older.length) parts.push(`${join(older.map((c) => nice(c.pkg)))} ${older.length > 1 ? 'need' : 'needs'} ${libName} older than ${minHi}${lib === 'libzlib' ? ' (these builds were made with zlib 1.2)' : ''}`);
    newer.forEach((c) => parts.push(`${nice(c.pkg)} needs ${libName} ${c.range[0]} or newer`));
    const why = parts.join(older.length ? ', but ' : '; ');
    return `An environment holds ONE version of each library. ${why}${pin ? `, but you asked for exactly ${libName} ${pin.v}` : ''}. Put them in separate environments (in a Snakefile: a different conda: file for each rule).`;
  }
  function createEnv(ctx, name, specs, channels, fromFile) {
    if (!/^[\w.\-]+$/.test(name)) {
      ctx.err(`\nCondaValueError: Invalid environment name: '${name}'\n\n`);
      return 1;
    }
    if (C().envs[name]) {
      ctx.err(`\nCondaValueError: prefix already exists: ${C().prefix(name)}\n\n`);
      ctx.io.note(`Remove it first with  conda env remove -n ${name}  – or choose another name.`);
      return 1;
    }
    const r = C().solve(specs);
    if (r.problems.length) {
      ctx.err('Channels:\n' + (channels.length ? channels : ['conda-forge', 'bioconda']).map((c) => ' - ' + c).join('\n') + '\nPlatform: linux-64\nCollecting package metadata (repodata.json): done\nSolving environment: failed\n' + notFound(r.problems));
      ctx.io.note('On a real computer conda downloads the versions you ask for. This browser has exactly one version of each program (see  conda search samtools) – so pin the versions that are here.');
      MG.bus.emit('conda:create', { name, ok: false });
      return 1;
    }
    if (r.conflicts.length) {
      ctx.err(conflictText(r.conflicts, channels));
      ctx.io.note(conflictNote(r.conflicts));
      MG.bus.emit('conda:create', { name, ok: false, conflict: true });
      return 1;
    }
    ctx.out(planText(name, specs, channels, r.pkgs, r.pins) + (fromFile ? '' : '\nProceed ([y]/n)? y\n') + '\nDownloading and Extracting Packages: done\nPreparing transaction: done\nVerifying transaction: done\nExecuting transaction: done\n#\n# To activate this environment, use\n#\n#     $ conda activate ' + name + '\n#\n# To deactivate an active environment, use\n#\n#     $ conda deactivate\n\n');
    C().create(name, specs, channels);
    r.notes.forEach((n) => ctx.io.note(n));
    MG.bus.emit('conda:create', { name, ok: true, specs });
    return 0;
  }
  function removeEnv(ctx, name) {
    if (!name) {
      ctx.err('\nCondaValueError: no environment specified – use  -n NAME\n\n');
      return 2;
    }
    if (name === 'base' || name === 'pipelines') {
      ctx.err(`\nCondaEnvironmentError: cannot remove the environment '${name}' here.\n\n`);
      return 1;
    }
    if (!C().envs[name]) {
      ctx.err(`\nEnvironmentLocationNotFound: Not a conda environment: ${C().prefix(name)}\n\n`);
      return 1;
    }
    if (C().stack.includes(name)) {
      ctx.err(`\nCondaEnvironmentError: cannot remove current environment. Deactivate and run conda remove again\n\n`);
      return 1;
    }
    delete C().envs[name];
    C().save();
    ctx.out(`\nRemove all packages in environment ${C().prefix(name)}:\n\nPreparing transaction: done\nVerifying transaction: done\nExecuting transaction: done\n`);
    return 0;
  }
  /* a small reader for environment.yml files: name, channels, dependencies (and pip:) */
  function parseEnvYaml(text) {
    const out = { name: null, channels: [], deps: [] };
    let section = null;
    let ok = false;
    for (const raw of linesOf(text)) {
      const line = raw.replace(/\s+#.*$/, '');
      if (!line.trim() || line.trim().startsWith('#')) continue;
      const top = /^([A-Za-z_]+):\s*(.*)$/.exec(line);
      if (top) {
        section = top[1];
        if (section === 'name') out.name = top[2].trim();
        ok = true;
        continue;
      }
      const item = /^\s*-\s*(.+)$/.exec(line);
      if (item && section === 'channels') out.channels.push(item[1].trim());
      else if (item && section === 'dependencies' && !/^pip\s*:/.test(item[1])) out.deps.push(item[1].trim());
    }
    return ok ? out : null;
  }
  MG.parseEnvYaml = parseEnvYaml;
  B.conda = condaCmd;
  B.mamba = condaCmd;
  B.micromamba = condaCmd;

  /* ------------------------------------------------------------------ snakemake */
  B.snakemake = async (ctx) => {
    if (!MG.py) throw userErr('snakemake: Python is not available on this page');
    unsavedNote(ctx);
    return MG.py.term('smk', ctx.args, ctx);
  };

  /* ------------------------------------------------------------------ dot (Graphviz, via viz.js) */
  let vizP = null;
  MG.viz = () => {
    if (!vizP) {
      vizP = new Promise((resolve, reject) => {
        const go = () => window.Viz.instance().then(resolve, reject);
        if (window.Viz) return go();
        const s = document.createElement('script');
        s.src = 'assets/vendor/viz/viz-global.js';
        s.onload = go;
        s.onerror = () => reject(new Error('could not load Graphviz'));
        document.head.appendChild(s);
      });
      vizP.catch(() => (vizP = null));
    }
    return vizP;
  };
  MG.svgToPng = (svg, scale = 2) =>
    new Promise((resolve, reject) => {
      const img = new Image();
      const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }));
      img.onload = () => {
        const c = document.createElement('canvas');
        c.width = Math.max(1, Math.round(img.width * scale));
        c.height = Math.max(1, Math.round(img.height * scale));
        const g = c.getContext('2d');
        g.fillStyle = '#fff';
        g.fillRect(0, 0, c.width, c.height);
        g.drawImage(img, 0, 0, c.width, c.height);
        URL.revokeObjectURL(url);
        c.toBlob((b) => (b ? resolve(b) : reject(new Error('PNG failed'))), 'image/png');
      };
      img.onerror = () => reject(new Error('could not draw the SVG'));
      img.src = url;
    });
  B.dot = async (ctx) => {
    let fmt = 'dot', outFile = null, engine = 'dot';
    const files = [];
    const a = ctx.args;
    for (let i = 0; i < a.length; i++) {
      const x = a[i];
      if (/^-T/.test(x)) fmt = x.length > 2 ? x.slice(2) : a[++i];
      else if (/^-o/.test(x)) outFile = x.length > 2 ? x.slice(2) : a[++i];
      else if (/^-K/.test(x)) engine = x.length > 2 ? x.slice(2) : a[++i];
      else if (x === '-V' || x === '--version') {
        const v = await MG.viz();
        ctx.err(`dot - graphviz version ${v.graphvizVersion} (viz.js, WebAssembly)\n`);
        return 0;
      } else if (x.startsWith('-')) throw userErr(`dot: option ${x} is not available in this terminal (use -Tsvg, -Tpng and -o FILE)`);
      else files.push(x);
    }
    fmt = (fmt || 'dot').split(':')[0];
    let src = '';
    if (files.length) {
      for (const f of files) src += await ctx.fs.readText(f).catch(() => {
        throw userErr(`Error: dot: can't open ${f}`);
      });
    } else if (ctx.stdin != null) src = new TextDecoder().decode(await stdinBytes(ctx));
    else throw userErr('dot: reading from the keyboard is not available here – give a file, or pipe:  snakemake --dag | dot -Tsvg > dag.svg');
    if (!src.trim()) throw userErr('Error: <stdin>: syntax error in line 1 near \'\' (the input is empty)');
    const viz = await MG.viz();
    const textFormats = ['svg', 'dot', 'gv', 'plain', 'plain-ext', 'json', 'json0', 'xdot', 'canon', 'ps', 'eps'];
    if (!textFormats.includes(fmt) && fmt !== 'png') {
      ctx.err(`Format: "${fmt}" not recognized. Use one of: canon dot eps gv json json0 plain plain-ext png ps svg xdot\n`);
      if (fmt === 'pdf') ctx.io.note('PDF output needs a Graphviz with Cairo, which this browser does not have. Use -Tsvg (or -Tpng); SVG opens in any web browser and prints to PDF.');
      return 1;
    }
    const r = viz.render(src, { format: fmt === 'png' ? 'svg' : fmt, engine });
    if (r.status !== 'success') {
      const msgs = (r.errors || []).map((e) => (e.level ? e.level[0].toUpperCase() + e.level.slice(1) + ': ' : '') + e.message.trim());
      ctx.err((msgs.join('\n') || 'Error: could not draw the graph') + '\n');
      return 1;
    }
    const target = outFile || ctx.redirectTarget;
    if (fmt === 'png') {
      if (!target) {
        ctx.io.note('PNG is a binary format – save it to a file:  ... | dot -Tpng > dag.png');
        return 1;
      }
      const blob = await MG.svgToPng(r.output, 2);
      if (target !== '/dev/null') ctx.fs.put(target, { kind: 'blob', blob, size: blob.size, fresh: true });
      if (!outFile) ctx.wroteRedirect = true;
    } else if (outFile) ctx.fs.writeText(outFile, r.output);
    else ctx.out(r.output);
    MG.bus.emit('dot:render', { format: fmt, file: target ? ctx.fs.resolve(target) : null });
    return 0;
  };

  /* ------------------------------------------------------------------ the shell's hooks */
  // (Snakemake jobs pass the programs of a rule's conda environment as opts.tools; here every program is always
  // there, so they are only remembered.)
  const Shell = MG.Shell;
  const exec0 = Shell.prototype.exec;
  Shell.prototype.exec = async function (text, io, opts = {}) {
    if (!opts.tools) return exec0.call(this, text, io, opts);
    const before = this._jobTools;
    this._jobTools = opts.tools;
    try {
      return await exec0.call(this, text, io, opts);
    } finally {
      this._jobTools = before;
    }
  };
  const dispatch0 = Shell.prototype.dispatch;
  Shell.prototype.dispatch = function (name, ctx) {
    // a command of the AI agent runs only the programs the agent was told it has (assistant.js sets _agentOnly)
    const only = this._agentOnly;
    if (only && !only.has(name)) {
      ctx.err(`bash: ${name}: not available to the agent\n`);
      if (this._agentRefused && !this._agentRefused.includes(name)) this._agentRefused.push(name);
      return 126;
    }
    return dispatch0.call(this, name, ctx);
  };
  MG.shellHooks = MG.shellHooks || {};
  MG.shellHooks.promptPrefix = () => (MG.conda && MG.conda.active && MG.conda.active !== 'base' && MG.conda.stack && MG.conda.stack.length > 1 ? `<span class="penv">(${MG.esc(MG.conda.active)})</span> ` : '');
  MG.bus.on('conda:changed', () => {
    const t = MG.app && MG.app.term;
    if (t) t._renderPrompt();
  });

  /* ------------------------------------------------------------------ programs that are not here */
  if (MG.shellUtil.ABSENT)
    MG.shellUtil.ABSENT.splice(
      0,
      MG.shellUtil.ABSENT.length,
      [/^(bowtie|STAR|bbmap|ngmlr|novoalign|subread-align|subjunc|rsem-calculate-expression|htseq-count)$/, 'is not installed in this terminal. For mapping reads there are bwa, bwa-mem2, bowtie2 and minimap2 – and hisat2 for RNA-seq reads; for counting featureCounts, for abundances stringtie, kallisto and salmon.'],
      [/^(featurecounts|featureCount|FeatureCounts)$/, 'is not a command here: the program is called featureCounts (with a capital C).'],
      [/^(fastqc|multiqc|trimmomatic|trim_galore|bbduk\.sh|seqkit|NanoPlot|prinseq)$/, 'is not installed in this terminal. For quality control and trimming there are fastp (fastp -i R1.fastq -I R2.fastq … -h report.html) and cutadapt (adapters, primers, quality: cutadapt -a ADAPTER -o out.fastq reads.fastq); seqtk does many small jobs on FASTQ files.'],
      [/^(strelka|strelka2|configureStrelkaWorkflow\.pl|runWorkflow\.py)$/, 'is not a command here: Strelka2 starts with  configureStrelkaSomaticWorkflow.py --normalBam N.bam --tumorBam T.bam --referenceFasta REF.fa --runDir DIR, which writes DIR/runWorkflow.py; then run  DIR/runWorkflow.py -m local -j 1  (see man configureStrelkaSomaticWorkflow.py).'],
      [/^(kraken|krakenuniq|centrifuge|kaiju|metaphlan|metaphlan4|mpa_config|humann|humann3|motus|mash|sourmash|kma|gtdbtk|ktImportTaxonomy|ktImportText|kreport2krona\.py|kreport2mpa\.py|extract_kraken_reads\.py|combine_kreports\.py|combine_bracken_outputs\.py)$/, 'is not installed in this terminal. For classifying the reads of a sample by taxon there are kraken2 (kraken2 --db DB --report sample.report READS) and bracken (species abundances from that report) – see the help page Metagenomics.'],
      [/^(Mutect2|mutect2|varscan|varscan2|VarScan|vardict|VarDict|muse|MuSE|somaticseq)$/, 'is not installed in this terminal. For somatic variants (a tumour and its normal) there are lofreq somatic, bam-somaticsniper and Strelka2 (configureStrelkaSomaticWorkflow.py); for germline variants bcftools and freebayes.'],
      [/^(gatk|picard|deepvariant|octopus|snpEff|SnpSift|vep|annovar|vcftools|qualimap|sambamba|bamtools)$/, 'is not installed in this terminal. For variants there are bcftools (mpileup, call, filter, view, query, stats, norm) and freebayes – and, for a tumour and its normal, lofreq somatic, bam-somaticsniper and Strelka2; for alignments samtools; for depth mosdepth; for regions bedtools.'],
      [/^(blastn|blastp|blastx|tblastn|makeblastdb|diamond|interproscan\.sh)$/, 'is not installed in this terminal. BLAST searches run at EBI from the Databases tab (BLAST card). Here, phmmer and jackhmmer (HMMER) search proteins with a protein, hmmsearch and hmmscan with profile HMMs; for pairwise alignments there are needleman_wunsch and smith_waterman.'],
      [/^(prokka|bakta|pgap|glimmer3|long-orfs|gmhmmp|gmsn\.pl|getorf|orfipy|transeq|augustus)$/, 'is not installed in this terminal. For the genes of bacteria and archaea there is prodigal:  prodigal -i genome.fna -o genes.gff -f gff -a proteins.faa  – and HMMER (hmmscan, hmmsearch) finds the domains of the proteins.'],
      [/^(esl-[A-Za-z0-9_-]+|hmmpgmd|hmmpgmd_shard|hmmsim|hmmlogo|hmmc2|alimask|makehmmerdb|hmmerfm-exactmatch|pfam_scan\.pl)$/, 'is not installed in this terminal: of HMMER there are hmmbuild, hmmsearch, hmmscan, hmmpress, hmmfetch, hmmalign, hmmconvert, hmmemit, hmmstat, phmmer, jackhmmer, nhmmer and nhmmscan – not its Easel miniapps (esl-…) or its servers.'],
      [/^(macs2|macs|macs14|HMMRATAC|homer|findPeaks|makeTagDirectory|Genrich|genrich|epic2|sicer|SICER2|seacr|SEACR_1\.3\.sh|idr|bamCoverage|bamCompare|computeMatrix|plotHeatmap|plotProfile|bedGraphToBigWig|ChIPseeker)$/, 'is not installed in this terminal. For peaks – ChIP-seq, ATAC-seq, CUT&RUN – there is MACS3:  macs3 callpeak -t chip.bam -c input.bam -g hs -n NAME  (man macs3); macs3 hmmratac calls the open chromatin of ATAC-seq, macs3 bdgcmp compares two bedGraph tracks (fold enrichment), macs3 pileup or bedtools genomecov -bg make coverage tracks, and igv shows peaks and tracks in the Genome browser.'],
      [/^(kb|cellranger|alevin-fry|velocyto|umi_tools|dropseq|scanpy|seurat)$/, 'is not installed in this terminal. For single-cell RNA-seq there is bustools: it sorts, corrects and counts the BUS records that kallisto bus writes (man bustools). The matrix it writes opens in Python with scipy.io.mmread.'],
      [/^(plink|plink1|plink1\.9|plink19|gcta|gcta64|regenie|bolt|saige|admixture|smartpca|king|beagle|shapeit|shapeit4|shapeit5|impute2|impute5|bgenix|qctool)$/, 'is not installed in this terminal. For the genotypes of many people – quality control, allele frequencies, LD, kinship, association (GWAS), scores – there is PLINK 2:  plink2 --vcf FILE.vcf.gz --freq --out NAME  (man plink2). Many options of PLINK 1.9 are the same in PLINK 2 (--bfile, --maf, --geno, --hwe, --make-bed); --assoc, --linear and --logistic are --glm there, and --recode is --export.'],
      [/^(cytoscape|Cytoscape|cytoscape\.sh|gephi|graphviz-gui)$/, 'is a desktop program and is not installed in this terminal. The Networks tab draws and analyses networks here – SIF, GraphML, GML, XGMML and Cytoscape JSON files, STRING and IntAct networks:  network FILE  (man network); dot draws graphs written in the DOT language.'],
      [/^(clustalo|clustalw|mafft|t_coffee|prank)$/, 'is not installed in this terminal. For multiple alignments there are kalign and muscle:  kalign -i seqs.fasta -o aligned.fasta'],
      [/^(raxml|raxml-ng|iqtree|iqtree2|phyml|mrbayes)$/, 'is not installed in this terminal. For trees there is FastTree:  fasttree aligned.fasta > tree.nwk  (open tree.nwk in the Files tab to see it).'],
      [/^(perl|ruby|java|julia|node|ipython|jupyter|conda-build)$/, 'is not installed in this terminal. There are Python (python script.py; the Notebook tab), R (Rscript script.R; R notebooks) and the shell with awk, sed, grep, sort, cut …'],
      [/^(apt|apt-get|yum|dnf|brew|docker|singularity|apptainer|nextflow|git|make|module|cmake|gcc|cc|g\+\+)$/, 'is not available in this terminal: programs cannot be installed or compiled in a web page. Python packages: pip install NAME; R packages: install.packages("NAME") in R.'],
      [/^(ssh|scp|rsync|ping|ftp|sftp|nc|telnet)$/, 'is not available: a web page cannot open network connections of its own. Downloads from web services that allow it: curl or wget (see  man curl).'],
      [/^(top|htop|ps|kill|free|lscpu|df|mount|su|chown|screen|tmux|nohup|watch|crontab|pkill|pgrep|uptime|stty|getconf|lsblk|dmesg|who|w|last|service|systemctl|chgrp|mknod)$/, 'is not available in this terminal: it is a web page, not a whole computer.'],
      [/^(mkfifo|flock)$/, 'is not available in this terminal: the commands here run one after the other, so there are no named pipes and nothing to lock. Use a file between two commands, or  COMMAND <(OTHER COMMAND)'],
      [/^install$/, 'is not available in this terminal. For a folder:  mkdir -p FOLDER   For a file with permissions:  cp FILE DESTINATION && chmod 755 DESTINATION'],
      [/^(iconv|recode)$/, 'is not installed in this terminal: text here is UTF-8, and the programs pass other bytes through as they are.'],
      [/^(dos2unix|unix2dos)$/, "is not installed in this terminal. To take the carriage returns of a Windows file away:  sed -i 's/\\r$//' FILE   or   tr -d '\\r' < FILE > NEWFILE"],
      [/^(cal|ncal|banner|figlet|cowsay|fortune)$/, 'is not installed in this terminal. Type  help  to see what is here.'],
      [/^ln$/, 'is not available in this terminal: there are no links here. Copy the file instead:  cp FILE NEWNAME'],
      [/^(7z|bzip2|bunzip2|xz|unxz|pigz|rar|unrar)$/, 'is not installed in this terminal. There are gzip, gunzip, zcat and bgzip, zip and unzip, and tar (with z for .tar.gz).'],
      [/^dc$/, 'is not installed in this terminal. For sums there are bc, $(( 2 + 3 )) and awk.'],
      [/^(sdiff|diff3)$/, 'is not available in this terminal: it works by starting diff as a second program, which a web page cannot do. Two files side by side:  diff -y A B'],
      [/^(patch|colordiff|vimdiff|wdiff)$/, 'is not installed in this terminal. To compare files there are diff and cmp.'],
      [/^strings$/, 'is not installed in this terminal. To look at the bytes of a file there are od -c, hexdump -C and xxd; to look into a compressed file,  zcat FILE | head'],
      [/^yes$/, "is not available in this terminal: the commands of a pipeline run one after the other, and yes never ends. For N lines:  seq N | sed \"s/.*/y/\""],
      [/^(csplit|numfmt|cksum|sum|dd|tsort|fmt|pr)$/, 'is not among the programs of this terminal. Type  help  to see what is here.'],
      [/^(alias|unalias)$/, 'is not available in this terminal. Write a function instead:  ll() { ls -l "$@"; }']
    );

  /* ------------------------------------------------------------------ man pages of the workbench's own commands */
  const OWN_MAN = {
    snakemake: 'snakemake – Snakemake 9 (the browser edition): runs the rules of a Snakefile.\n\n  snakemake -n                       what would run, and why (a dry run)\n  snakemake --cores 1                run the pipeline\n  snakemake --dag | dot -Tsvg > dag.svg\n  snakemake --summary                what made each output, and when\n\nAll its options:  snakemake --help',
    conda: 'conda – a model of conda environments (with the real versions of the programs here).\nIn the workbench every program is always available; environments only record what a pipeline needs.\n\n  conda env list     conda list     conda env export     conda create -n NAME PACKAGE=VERSION …\n\nAll its commands:  conda --help',
    python: 'python – Python (Pyodide) in your browser: the same Python as the Python notebooks.\n\n  python script.py [ARGUMENTS]\n  python -c "print(1 + 1)"\n  python -m MODULE\n  python --version\n\nPackages: pandas, NumPy, matplotlib, SciPy, Biopython, scikit-learn … load when imported; others:  pip install NAME\nFor interactive Python use the Notebook tab.',
    pip: 'pip – installs Python packages for this visit of the page (micropip): pure-Python packages from PyPI, and those Pyodide has built.\n\n  pip install NAME …\n  pip list\n  pip show NAME',
    Rscript: 'Rscript – R (webR) in your browser: the same R as the R notebooks.\n\n  Rscript script.R [ARGUMENTS]          (commandArgs(trailingOnly = TRUE) gives the arguments)\n  Rscript -e \'summary(cars)\'\n  Rscript -e \'install.packages("ggplot2")\'\n\nPlots go to Rplots.pdf, or to a file you open with png("plot.png") / pdf("plot.pdf") … dev.off().',
    R: 'R – see  man Rscript. The interactive R console is not available in the terminal: use an R notebook.',
    dot: 'dot – Graphviz, compiled to WebAssembly: draws a graph described in the DOT language.\n\n  dot -Tsvg graph.dot -o graph.svg\n  dot -Tpng graph.dot -o graph.png\n  snakemake --dag | dot -Tsvg > dag.svg',
    curl: 'curl – download from the web (through the browser). Only web services that allow pages to read them (CORS) can be reached: EBI, UniProt, Ensembl, NCBI E-utilities, RCSB PDB, AlphaFold DB, GitHub raw files …\n\n  curl -s "https://rest.uniprot.org/uniprotkb/P69905.fasta"\n  curl -o hb.fasta "https://rest.uniprot.org/uniprotkb/P69905.fasta"\n  curl -O https://files.rcsb.org/download/1A3N.pdb\n  curl -H "Content-Type: application/json" "https://rest.ensembl.org/lookup/symbol/homo_sapiens/BRCA2"\n  curl -X POST -H "Content-Type: application/json" -d \'{"ids":["ENSG00000139618"]}\' https://rest.ensembl.org/lookup/id\n\nOptions: -o FILE, -O, -s, -S, -f, -L, -H HEADER, -X METHOD, -d DATA, --data-binary @FILE, -I, -w \'%{http_code}\', --compressed (ignored).',
    wget: 'wget – download from the web (through the browser); the same reach as curl.\n\n  wget https://files.rcsb.org/download/1A3N.pdb\n  wget -O hb.fasta "https://rest.uniprot.org/uniprotkb/P69905.fasta"\n  wget -q -O - "https://rest.ensembl.org/info/ping?content-type=application/json"\n\nOptions: -O FILE (- for the screen), -q, -P FOLDER, -nc.',
    unzip: 'unzip – unpack a .zip archive.\n\n  unzip data.zip                 into the folder you are in\n  unzip data.zip -d data         into a folder\n  unzip -l data.zip              list what is in it\n  unzip -o data.zip              overwrite without asking (the default here)',
    zip: 'zip – make a .zip archive.\n\n  zip -r results.zip results/\n  zip notes.zip a.txt b.txt\n\n(To save a folder on your computer as a .zip in one step:  download FOLDER)',
    tar: 'tar – .tar and .tar.gz archives.\n\n  tar -xzf data.tar.gz            unpack (x) a gzipped (z) archive file (f)\n  tar -tzf data.tar.gz            list (t) what is in it\n  tar -xf data.tar -C folder      unpack into a folder\n  tar -czf results.tar.gz results/   make (c) one',
    igv: 'igv – show files in the Genome browser tab.\n\n  igv mapped.bam                    (needs mapped.bam.bai: samtools index mapped.bam)\n  igv calls.vcf.gz regions.bed\n  igv --genome reference.fa mapped.bam      use a FASTA file of yours as the genome (it needs reference.fa.fai: samtools faidx)\n  igv --genome hg19 peaks.narrowPeak        a genome hosted by the IGV team, with its genes (it needs the internet):\n                                            hg38, hg19, mm39, mm10, danRer11, dm6, ce11, sacCer3\n  igv --locus chr17:7,661,779-7,687,538',
    network: 'network – open networks in the Networks tab.\n\n  network graph.graphml                  a network file: SIF, GraphML, XGMML, GML, Cytoscape JSON (.cyjs), CX2 – or a table of edges (.csv, .tsv: the Networks tab asks which columns)\n  network --table deseq2_results.csv     add a table of values to the nodes of the network that is open (it asks which columns match)\n  network --string TP53 MDM2 CDKN1A      the STRING network of these genes or proteins (string-db.org)\n          [--species 10090] [--score 700] [--add 10]      species (NCBI taxon: 9606 human), minimum confidence (0–1000), interactors to add\n  network --example airway               an example: airway (genes changed by dexamethasone, on STRING) or karate\n\nFrom a Python notebook:  !network ~/networks/graph.graphml  (networkx writes it: nx.write_graphml(G, "graph.graphml"))',
    'export-session': 'export-session – save the commands of this terminal session, with their output.\n\n  export-session session.ipynb    a Jupyter notebook: one %%bash cell per command (it opens in the Notebook tab, and in Jupyter)\n  export-session session.sh       a shell script of the commands\n  export-session --clear          forget the commands so far\n\nThe "Save session" button above the terminal does the same.',
    'needleman_wunsch': 'needleman_wunsch – global pairwise alignment (seq-align).\n\n  needleman_wunsch ACGTTGCA ACGTGCA\n  needleman_wunsch --file seqs.fasta            (aligns the sequences of the file in pairs)\n  needleman_wunsch --match 1 --mismatch -1 --gapopen -2 --gapextend -1 SEQ1 SEQ2\n\nIts options:  needleman_wunsch --help',
    'smith_waterman': 'smith_waterman – local pairwise alignment (seq-align).\n\n  smith_waterman GATTACAGATTACA TTACAG\n  smith_waterman --file seqs.fasta\n\nIts options:  smith_waterman --help'
  };
  const man0 = B.man;
  B.man = (ctx) => {
    const name = ctx.args.filter((a) => !a.startsWith('-'))[0];
    const key = { mamba: 'conda', micromamba: 'conda', python3: 'python', pip3: 'pip' }[name] || name;
    if (OWN_MAN[key]) return ctx.out(OWN_MAN[key] + '\n');
    return man0(ctx);
  };

  /* ------------------------------------------------------------------ curl, wget: the web, through the browser */
  const CORS_NOTE = 'A web page can only download from servers that allow it (CORS). Services that do: EBI (ebi.ac.uk), UniProt, Ensembl, NCBI E-utilities, RCSB PDB, AlphaFold DB, raw.githubusercontent.com, Zenodo … For other files: download them with your browser, then add them with Files → Upload.';
  function webErr(ctx, prog, url, e) {
    const msg = String((e && e.message) || e);
    if (/Failed to fetch|NetworkError|Load failed|CORS/i.test(msg)) {
      ctx.err(`${prog}: (7) could not get ${url}: the server did not answer, or does not allow downloads from a web page\n`);
      ctx.io.note(CORS_NOTE);
    } else ctx.err(`${prog}: ${msg}\n`);
  }
  async function fetchFor(ctx, url, init) {
    if (MG.app && MG.app.term && MG.app.term.agentCmd && !(MG.app.ai && MG.app.ai.allowWeb)) throw userErr('the network is not available to the agent');
    const ctrl = new AbortController();
    const timer = setInterval(() => {
      if (ctx.term && ctx.term.cancelled) ctrl.abort();
    }, 200);
    try {
      return await fetch(url, Object.assign({}, init, { signal: ctrl.signal, credentials: 'omit', redirect: 'follow' }));
    } finally {
      clearInterval(timer);
    }
  }
  const nameOfUrl = (url) => {
    try {
      const u = new URL(url);
      return decodeURIComponent(u.pathname.split('/').filter(Boolean).pop() || '') || 'index.html';
    } catch (e) {
      return 'download';
    }
  };
  async function saveBytes(ctx, path, bytes) {
    const abs = ctx.fs.resolve(path);
    const text = MG.looksText(abs, bytes);
    if (text != null) ctx.fs.writeText(abs, text);
    else ctx.fs.put(abs, { kind: 'blob', blob: new Blob([bytes]), size: bytes.length, fresh: true });
    MG.bus.emit('vfs:created', { path: abs, program: ctx.name });
    return abs;
  }
  B.curl = async (ctx) => {
    const a = ctx.args.slice();
    let out = null, remoteName = false, silent = false, showErr = false, fail = false, head = false, method = null, data = null, writeOut = null, include = false;
    const headers = {};
    const urls = [];
    for (let i = 0; i < a.length; i++) {
      const x = a[i];
      const val = () => {
        if (i + 1 >= a.length) throw userErr(`curl: option ${x}: requires parameter`);
        return a[++i];
      };
      if (x === '-o' || x === '--output') out = val();
      else if (x === '-O' || x === '--remote-name') remoteName = true;
      else if (x === '-s' || x === '--silent') silent = true;
      else if (x === '-S' || x === '--show-error') showErr = true;
      else if (x === '-f' || x === '--fail') fail = true;
      else if (x === '-L' || x === '--location' || x === '--compressed' || x === '-k' || x === '--insecure' || x === '-g' || x === '--globoff') continue;
      else if (x === '-I' || x === '--head') head = true;
      else if (x === '-i' || x === '--include') include = true;
      else if (x === '-X' || x === '--request') method = val().toUpperCase();
      else if (x === '-H' || x === '--header') {
        const hv = val(), k = hv.indexOf(':');
        if (k > 0) headers[hv.slice(0, k).trim()] = hv.slice(k + 1).trim();
      } else if (x === '-d' || x === '--data' || x === '--data-raw' || x === '--data-binary' || x === '--data-ascii') {
        let d = val();
        if (d.startsWith('@')) d = d === '@-' ? (ctx.stdin == null ? '' : typeof ctx.stdin === 'string' ? ctx.stdin : new TextDecoder().decode(await stdinBytes(ctx))) : await ctx.fs.readText(d.slice(1));
        data = data == null ? d : data + '&' + d;
      } else if (x === '-w' || x === '--write-out') writeOut = val();
      else if (x === '-A' || x === '--user-agent' || x === '-e' || x === '--referer' || x === '--retry' || x === '-m' || x === '--max-time' || x === '--connect-timeout') val();
      else if (/^-[sSfLkOI]+$/.test(x)) {
        for (const c of x.slice(1)) {
          if (c === 's') silent = true;
          else if (c === 'S') showErr = true;
          else if (c === 'f') fail = true;
          else if (c === 'O') remoteName = true;
          else if (c === 'I') head = true;
        }
      } else if (x === '--help' || x === '-h') {
        ctx.out(OWN_MAN.curl + '\n');
        return 0;
      } else if (x === '--version' || x === '-V') {
        ctx.out('curl (the workbench\'s: downloads through the web browser)\n');
        return 0;
      } else if (x.startsWith('-')) throw userErr(`curl: option ${x}: is not available here (see  man curl)`);
      else urls.push(x);
    }
    if (!urls.length) throw userErr('curl: no URL specified!\ncurl: try \'curl --help\' or \'man curl\' for more information');
    let code = 0;
    for (const url0 of urls) {
      const url = /^[a-z]+:\/\//i.test(url0) ? url0 : 'https://' + url0;
      if (!/^https?:/i.test(url)) throw userErr(`curl: (1) Protocol "${url.split(':')[0]}" not supported`);
      const m = method || (head ? 'HEAD' : data != null ? 'POST' : 'GET');
      const init = { method: m, headers: Object.assign({}, headers) };
      if (data != null && m !== 'GET' && m !== 'HEAD') {
        init.body = data;
        if (!Object.keys(headers).some((k) => k.toLowerCase() === 'content-type')) init.headers['Content-Type'] = 'application/x-www-form-urlencoded';
      }
      let r;
      try {
        r = await fetchFor(ctx, url, init);
      } catch (e) {
        if (!silent || showErr) webErr(ctx, 'curl', url, e);
        else if (silent) ctx.io.note(CORS_NOTE);
        code = 7;
        continue;
      }
      if (fail && !r.ok) {
        if (!silent || showErr) ctx.err(`curl: (22) The requested URL returned error: ${r.status}\n`);
        code = 22;
        continue;
      }
      const hdrText = () => `HTTP/${'1.1'} ${r.status} ${r.statusText || ''}\n` + Array.from(r.headers.entries()).map(([k, v]) => `${k}: ${v}`).join('\n') + '\n\n';
      if (head) {
        ctx.out(hdrText());
        continue;
      }
      const bytes = new Uint8Array(await r.arrayBuffer());
      const dest = out || (remoteName ? nameOfUrl(r.url || url) : null);
      if (dest) {
        if (dest === '-') ctx.out(MG.looksText('x', bytes) != null ? new TextDecoder().decode(bytes) : bytes);
        else {
          await saveBytes(ctx, dest, bytes);
          if (!silent) ctx.err(`  % Total: ${MG.humanSize(bytes.length)}B received → ${dest}\n`);
        }
      } else {
        if (include) ctx.out(hdrText());
        const t = MG.looksText('x', bytes);
        if (t != null) ctx.out(t);
        else if (ctx.isPipedOut || ctx.redirectTarget) ctx.out(bytes);
        else ctx.io.note(`Binary output (${MG.humanSize(bytes.length)}B): save it with  -o FILE  or  > FILE`);
      }
      if (writeOut) ctx.out(writeOut.replace(/%\{http_code\}/g, String(r.status)).replace(/%\{size_download\}/g, String(bytes.length)).replace(/%\{url_effective\}/g, r.url || url).replace(/\\n/g, '\n'));
      MG.bus.emit('web:download', { url, status: r.status, bytes: bytes.length, file: dest || null });
    }
    return code;
  };
  B.wget = async (ctx) => {
    const a = ctx.args.slice();
    let out = null, quiet = false, prefix = null, noClobber = false;
    const urls = [];
    for (let i = 0; i < a.length; i++) {
      const x = a[i];
      if (x === '-O' || x === '--output-document') out = a[++i];
      else if (/^-O./.test(x)) out = x.slice(2);
      else if (/^--output-document=/.test(x)) out = x.split('=').slice(1).join('=');
      else if (x === '-q' || x === '--quiet' || x === '-nv' || x === '--no-verbose') quiet = true;
      else if (x === '-P' || x === '--directory-prefix') prefix = a[++i];
      else if (x === '-nc' || x === '--no-clobber') noClobber = true;
      else if (x === '-c' || x === '--continue' || x === '--no-check-certificate' || x === '-N') continue;
      else if (x === '--help' || x === '-h') {
        ctx.out(OWN_MAN.wget + '\n');
        return 0;
      } else if (x.startsWith('-')) throw userErr(`wget: option ${x} is not available here (see  man wget)`);
      else urls.push(x);
    }
    if (!urls.length) throw userErr('wget: missing URL\nUsage: wget [OPTION]... [URL]...');
    let code = 0;
    for (const url0 of urls) {
      const url = /^[a-z]+:\/\//i.test(url0) ? url0 : 'https://' + url0;
      if (!quiet) ctx.err(`--${new Date().toISOString().slice(0, 19).replace('T', ' ')}--  ${url}\n`);
      let r;
      try {
        r = await fetchFor(ctx, url, {});
      } catch (e) {
        webErr(ctx, 'wget', url, e);
        code = 4;
        continue;
      }
      if (!r.ok) {
        ctx.err(`ERROR ${r.status}: ${r.statusText || 'error'}.\n`);
        code = 8;
        continue;
      }
      const bytes = new Uint8Array(await r.arrayBuffer());
      if (out === '-') {
        const t = MG.looksText('x', bytes);
        ctx.out(t != null ? t : bytes);
        continue;
      }
      let dest = out || nameOfUrl(r.url || url);
      if (prefix && !out) dest = prefix.replace(/\/+$/, '') + '/' + dest;
      if (noClobber && ctx.fs.exists(dest)) {
        ctx.err(`File '${dest}' already there; not retrieving.\n`);
        continue;
      }
      if (!out && ctx.fs.exists(dest)) {
        let k = 1;
        while (ctx.fs.exists(`${dest}.${k}`)) k++;
        dest = `${dest}.${k}`;
      }
      await saveBytes(ctx, dest, bytes);
      if (!quiet) ctx.err(`Length: ${bytes.length} (${MG.humanSize(bytes.length)}B)\nSaving to: '${dest}'\n\n'${dest}' saved [${bytes.length}]\n`);
      MG.bus.emit('web:download', { url, status: r.status, bytes: bytes.length, file: dest });
    }
    return code;
  };

  /* ------------------------------------------------------------------ unzip, zip, tar */
  const loadZip = async () => {
    if (!window.JSZip) await MG.loadScript('assets/vendor/jszip/jszip.min.js');
    return window.JSZip;
  };
  B.unzip = async (ctx) => {
    const a = ctx.args.slice();
    let dir = null, list = false, quiet = false;
    const files = [];
    for (let i = 0; i < a.length; i++) {
      const x = a[i];
      if (x === '-d') dir = a[++i];
      else if (x === '-l') list = true;
      else if (x === '-q' || x === '-qq') quiet = true;
      else if (x === '-o' || x === '-n' || x === '-u') continue;
      else if (x === '--help' || x === '-h') {
        ctx.out(OWN_MAN.unzip + '\n');
        return 0;
      } else if (x.startsWith('-')) throw userErr(`unzip: option ${x} is not available here (see  man unzip)`);
      else files.push(x);
    }
    if (!files.length) throw userErr('usage: unzip [-l] [-q] FILE.zip [-d FOLDER]');
    const JSZip = await loadZip();
    const zipPath = files[0];
    if (!ctx.fs.exists(zipPath)) throw userErr(`unzip:  cannot find or open ${zipPath}, ${zipPath}.zip or ${zipPath}.ZIP.`);
    let zip;
    try {
      zip = await JSZip.loadAsync(await ctx.fs.readBytes(zipPath));
    } catch (e) {
      throw userErr(`unzip: ${zipPath} is not a zip archive (or it is damaged): ${e.message}`);
    }
    const names = Object.keys(zip.files).filter((n) => !/(^|\/)__MACOSX\//.test(n));
    if (list) {
      let total = 0;
      const rows = names.map((n) => {
        const z = zip.files[n];
        const size = (z._data && z._data.uncompressedSize) || 0;
        total += size;
        const d = z.date || new Date();
        return `${String(size).padStart(9)}  ${d.toISOString().slice(0, 10)} ${d.toTimeString().slice(0, 5)}   ${n}`;
      });
      ctx.out(`Archive:  ${zipPath}\n  Length      Date    Time    Name\n---------  ---------- -----   ----\n${rows.join('\n')}\n---------                     -------\n${String(total).padStart(9)}                     ${names.length} files\n`);
      return 0;
    }
    if (!quiet) ctx.out(`Archive:  ${zipPath}\n`);
    const base = ctx.fs.resolve(dir || '.');
    let n = 0;
    for (const name of names) {
      const z = zip.files[name];
      const dest = ctx.fs.resolve(base + '/' + name.replace(/\/+$/, ''));
      if (!dest.startsWith(base + '/') && dest !== base) continue; // no ../ out of the folder
      if (z.dir) {
        ctx.fs.mkdirp(dest);
        if (!quiet) ctx.out(`   creating: ${ctx.fs.pretty(dest)}/\n`);
        continue;
      }
      const bytes = await z.async('uint8array');
      const text = MG.looksText(name, bytes);
      const when = z.date ? z.date.getTime() : Date.now();
      if (text != null) ctx.fs.put(dest, { kind: 'text', text, mtime: when, fresh: true });
      else ctx.fs.put(dest, { kind: 'blob', blob: new Blob([bytes]), size: bytes.length, mtime: when, fresh: true });
      if (!quiet) ctx.out(`  inflating: ${dir ? MG.path.basename(base) + '/' : ''}${name}\n`);
      n++;
    }
    MG.bus.emit('files:unzipped', { folder: base, n });
    return 0;
  };
  B.zip = async (ctx) => {
    const a = ctx.args.slice();
    let recursive = false, quiet = false;
    const rest = [];
    for (const x of a) {
      if (/^-[rq9]+$/.test(x)) {
        if (x.includes('r')) recursive = true;
        if (x.includes('q')) quiet = true;
      } else if (x === '--help' || x === '-h') {
        ctx.out(OWN_MAN.zip + '\n');
        return 0;
      } else if (x.startsWith('-')) throw userErr(`zip: option ${x} is not available here (see  man zip)`);
      else rest.push(x);
    }
    const [out, ...items] = rest;
    if (!out || !items.length) throw userErr('usage: zip [-r] ARCHIVE.zip FILE|FOLDER …');
    const JSZip = await loadZip();
    const zip = new JSZip();
    let n = 0;
    const addFile = async (abs, name) => {
      const e = ctx.fs.get(abs);
      zip.file(name, await ctx.fs.readBytes(abs), { date: new Date(e.mtime || Date.now()) });
      n++;
      if (!quiet) ctx.out(`  adding: ${name}\n`);
    };
    for (const it of items) {
      const abs = ctx.fs.resolve(it);
      const e = ctx.fs.get(abs);
      if (!e) {
        ctx.err(`zip warning: name not matched: ${it}\n`);
        continue;
      }
      if (e.kind === 'dir') {
        // (zip stores names without a leading /, as the real one does)
        if (!recursive) {
          ctx.out(`  adding: ${it.replace(/\/+$/, '').replace(/^\/+/, '')}/ (stored 0%)\n`);
          zip.folder(it.replace(/\/+$/, '').replace(/^\/+/, ''));
          continue;
        }
        const pre = it.replace(/\/+$/, '').replace(/^\/+/, '');
        for (const [p, x] of Array.from(ctx.fs.entries)) {
          if (!p.startsWith(abs + '/')) continue;
          const name = pre + p.slice(abs.length);
          if (x.kind === 'dir') zip.folder(name);
          else if (x.kind !== 'virtual') await addFile(p, name);
        }
      } else await addFile(abs, it.replace(/^\/+/, ''));
    }
    const blob = await zip.generateAsync({ type: 'blob', compression: 'DEFLATE', compressionOptions: { level: 6 } });
    const dest = /\.zip$/i.test(out) ? out : out + '.zip';
    ctx.fs.put(dest, { kind: 'blob', blob, size: blob.size, fresh: true });
    if (!n && !quiet) ctx.err('zip error: Nothing to do!\n');
    return n ? 0 : 12;
  };

  /* tar: read and write ustar archives (with gzip through the browser's own (de)compression) */
  async function gunzipBytes(bytes) {
    const ds = new DecompressionStream('gzip');
    const buf = await new Response(new Blob([bytes]).stream().pipeThrough(ds)).arrayBuffer();
    return new Uint8Array(buf);
  }
  async function gzipBytes(bytes) {
    const cs = new CompressionStream('gzip');
    const buf = await new Response(new Blob([bytes]).stream().pipeThrough(cs)).arrayBuffer();
    return new Uint8Array(buf);
  }
  function tarEntries(buf) {
    const out = [];
    const dec = new TextDecoder();
    const str = (o, n) => dec.decode(buf.subarray(o, o + n)).replace(/\0.*$/s, '');
    let off = 0, longName = null;
    while (off + 512 <= buf.length) {
      if (buf.subarray(off, off + 512).every((b) => b === 0)) break;
      let name = str(off, 100);
      const size = parseInt(str(off + 124, 12).trim() || '0', 8) || 0;
      const mtime = parseInt(str(off + 136, 12).trim() || '0', 8) * 1000;
      const mode = parseInt(str(off + 100, 8).trim() || '644', 8);
      const type = String.fromCharCode(buf[off + 156] || 48);
      // (the owner and the group, by name – the ustar fields; an old archive without them: by number)
      const owner = str(off + 265, 32) || String(parseInt(str(off + 108, 8).trim() || '0', 8) || 0);
      const group = str(off + 297, 32) || String(parseInt(str(off + 116, 8).trim() || '0', 8) || 0);
      const prefix = str(off + 345, 155);
      if (prefix && dec.decode(buf.subarray(off + 257, off + 262)) === 'ustar') name = prefix + '/' + name;
      const data = buf.subarray(off + 512, off + 512 + size);
      off += 512 + Math.ceil(size / 512) * 512;
      if (type === 'L') {
        longName = dec.decode(data).replace(/\0.*$/s, '');
        continue;
      }
      if (type === 'x' || type === 'g') {
        const m = /\d+ path=([^\n]*)\n/.exec(dec.decode(data));
        if (m) longName = m[1];
        continue;
      }
      if (longName) {
        name = longName;
        longName = null;
      }
      out.push({ name, type: type === '5' ? 'dir' : type === '0' || type === '\0' || type === '7' ? 'file' : 'other', data, mtime, mode, owner, group });
    }
    return out;
  }
  function tarBuild(files) {
    const enc = new TextEncoder();
    const parts = [];
    const field = (h, off, len, s) => h.set(enc.encode(s).subarray(0, len), off);
    for (const f of files) {
      let name = f.name;
      const hdr = new Uint8Array(512);
      if (enc.encode(name).length > 99) {
        const lh = new Uint8Array(512), body = enc.encode(name + '\0');
        field(lh, 0, 100, '././@LongLink');
        field(lh, 100, 8, '0000644\0');
        field(lh, 124, 12, body.length.toString(8).padStart(11, '0') + '\0');
        field(lh, 136, 12, '00000000000\0');
        lh[156] = 'L'.charCodeAt(0);
        field(lh, 257, 6, 'ustar ');
        field(lh, 263, 2, ' \0');
        let sum = 0;
        for (let i = 0; i < 512; i++) sum += i >= 148 && i < 156 ? 32 : lh[i];
        field(lh, 148, 8, sum.toString(8).padStart(6, '0') + '\0 ');
        parts.push(lh, body, new Uint8Array((512 - (body.length % 512)) % 512));
        name = name.slice(0, 99);
      }
      field(hdr, 0, 100, name);
      field(hdr, 100, 8, (f.dir ? '0000755' : f.mode === 'x' ? '0000755' : '0000644') + '\0');
      field(hdr, 108, 8, '0001750\0');
      field(hdr, 116, 8, '0001750\0');
      field(hdr, 124, 12, (f.dir ? 0 : f.data.length).toString(8).padStart(11, '0') + '\0');
      field(hdr, 136, 12, Math.floor((f.mtime || Date.now()) / 1000).toString(8).padStart(11, '0') + '\0');
      hdr[156] = (f.dir ? '5' : '0').charCodeAt(0);
      field(hdr, 257, 6, 'ustar ');
      field(hdr, 263, 2, ' \0');
      field(hdr, 265, 32, MG.user.login());
      field(hdr, 297, 32, MG.user.login());
      let sum = 0;
      for (let i = 0; i < 512; i++) sum += i >= 148 && i < 156 ? 32 : hdr[i];
      field(hdr, 148, 8, sum.toString(8).padStart(6, '0') + '\0 ');
      parts.push(hdr);
      if (!f.dir) {
        parts.push(f.data);
        parts.push(new Uint8Array((512 - (f.data.length % 512)) % 512));
      }
    }
    parts.push(new Uint8Array(1024));
    const total = parts.reduce((n, p) => n + p.length, 0);
    const out = new Uint8Array(total);
    let o = 0;
    for (const p of parts) {
      out.set(p, o);
      o += p.length;
    }
    return out;
  }
  B.tar = async (ctx) => {
    const a = ctx.args.slice();
    let mode = null, gz = false, file = null, verbose = false, dir = null;
    const items = [];
    const flags = (str) => {
      for (const c of str) {
        if ('xct'.includes(c)) mode = c;
        else if (c === 'z') gz = true;
        else if (c === 'v') verbose = true;
        else if (c === 'f') file = '__next__';
        else if (c === 'j' || c === 'J') throw userErr('tar: bzip2 and xz archives (j, J) are not available here – only .tar and .tar.gz');
        else throw userErr(`tar: option -${c} is not available here (see  man tar)`);
      }
    };
    for (let i = 0; i < a.length; i++) {
      const x = a[i];
      if (i === 0 && /^[xctzvf]+$/.test(x)) flags(x);
      else if (/^-[xctzvfjJ]+$/.test(x)) flags(x.slice(1));
      else if (x === '-C' || x === '--directory') dir = a[++i];
      else if (x === '--help') {
        ctx.out(OWN_MAN.tar + '\n');
        return 0;
      } else if (x.startsWith('--')) {
        if (x === '--gzip') gz = true;
        else if (x === '--extract') mode = 'x';
        else if (x === '--create') mode = 'c';
        else if (x === '--list') mode = 't';
        else if (/^--file=/.test(x)) file = x.slice(7);
        else throw userErr(`tar: option ${x} is not available here (see  man tar)`);
      } else if (file === '__next__') file = x;
      else items.push(x);
      if (file === '__next__' && i + 1 < a.length && !/^-/.test(a[i + 1])) file = a[++i];
    }
    if (!mode) throw userErr('tar: You must specify one of the \'-ctx\' options\nTry \'tar --help\' or \'man tar\' for more information.');
    if (!file || file === '__next__') throw userErr('tar: give the archive with f (tar -xzf FILE.tar.gz); reading from the keyboard is not available');
    if (mode === 'c') {
      const files = [];
      // (-C DIR: the names that follow are read in DIR – the archive itself is written where tar was started)
      const from = dir ? ctx.fs.resolve(dir) : null;
      if (from && !ctx.fs.isDir(from)) throw userErr(`tar: ${dir}: Cannot open: No such file or directory`);
      let failed = false, toldSlash = false;
      for (const it of items) {
        const abs = from && !it.startsWith('/') ? ctx.fs.resolve(from + '/' + it) : ctx.fs.resolve(it);
        const e = ctx.fs.get(abs);
        if (!e) {
          ctx.err(`tar: ${it}: Cannot stat: No such file or directory\n`);
          failed = true;
          continue;
        }
        let pre = it.replace(/\/+$/, '');
        if (pre.startsWith('/')) {
          if (!toldSlash) ctx.err("tar: Removing leading `/' from member names\n");
          toldSlash = true;
          pre = pre.replace(/^\/+/, '');
        }
        if (e.kind === 'dir') {
          files.push({ name: pre + '/', dir: true, mtime: e.mtime });
          for (const [p, x] of Array.from(ctx.fs.entries)) {
            if (!p.startsWith(abs + '/')) continue;
            const name = pre + p.slice(abs.length);
            if (x.kind === 'dir') files.push({ name: name + '/', dir: true, mtime: x.mtime });
            else if (x.kind !== 'virtual') files.push({ name, data: await ctx.fs.readBytes(p), mtime: x.mtime, mode: x.mode });
            if (verbose) ctx.out(name + (x.kind === 'dir' ? '/' : '') + '\n');
          }
        } else {
          files.push({ name: pre, data: await ctx.fs.readBytes(abs), mtime: e.mtime, mode: e.mode });
          if (verbose) ctx.out(pre + '\n');
        }
      }
      let bytes = tarBuild(files);
      if (gz || /\.(tgz|tar\.gz)$/i.test(file)) bytes = await gzipBytes(bytes);
      ctx.fs.put(file, { kind: 'blob', blob: new Blob([bytes]), size: bytes.length, fresh: true });
      if (failed) {
        ctx.err('tar: Exiting with failure status due to previous errors\n');
        return 2;
      }
      return 0;
    }
    if (!ctx.fs.exists(file)) throw userErr(`tar: ${file}: Cannot open: No such file or directory`);
    let bytes = await ctx.fs.readBytes(file);
    if (bytes[0] === 0x1f && bytes[1] === 0x8b) bytes = await gunzipBytes(bytes);
    const entries = tarEntries(bytes);
    if (mode === 't') {
      // (as GNU tar: owner/group and the size take at least 18 characters together – and as many as the widest so far)
      let ugsw = 18;
      const ugs = (e) => {
        const ug = `${e.owner}/${e.group}`, size = String(e.data.length), pad = ug.length + size.length;
        if (pad > ugsw) ugsw = pad;
        return ug + ' ' + size.padStart(ugsw - pad + size.length);
      };
      ctx.out(entries.map((e) => (verbose ? `${e.type === 'dir' ? 'd' : '-'}rw-r--r-- ${ugs(e)} ${new Date(e.mtime).toISOString().slice(0, 16).replace('T', ' ')} ` : '') + e.name).join('\n') + (entries.length ? '\n' : ''));
      return 0;
    }
    const base = ctx.fs.resolve(dir || '.');
    for (const e of entries) {
      const dest = ctx.fs.resolve(base + '/' + e.name.replace(/\/+$/, ''));
      if (!dest.startsWith(base + '/') && dest !== base) continue;
      if (e.type === 'dir') ctx.fs.mkdirp(dest);
      else if (e.type === 'file') {
        const data = e.data.slice();
        const text = MG.looksText(e.name, data);
        const extra = { mtime: e.mtime || Date.now(), mode: e.mode & 0o111 ? 'x' : undefined, fresh: true };
        if (text != null) ctx.fs.put(dest, Object.assign({ kind: 'text', text }, extra));
        else ctx.fs.put(dest, Object.assign({ kind: 'blob', blob: new Blob([data]), size: data.length }, extra));
      }
      if (verbose) ctx.out(e.name + '\n');
    }
    return 0;
  };

  /* ------------------------------------------------------------------ igv: files → the Genome browser tab */
  B.igv = async (ctx) => {
    if (MG.shellUtil.forPerson && MG.shellUtil.forPerson(ctx)) return 1;
    const a = ctx.args.slice();
    let genome = null, locus = null;
    const files = [];
    for (let i = 0; i < a.length; i++) {
      if (a[i] === '--genome' || a[i] === '-g') genome = a[++i];
      else if (a[i] === '--locus' || a[i] === '-l') locus = a[++i];
      else if (a[i] === '--help' || a[i] === '-h') {
        ctx.out(OWN_MAN.igv + '\n');
        return 0;
      } else if (a[i].startsWith('-')) throw userErr(`igv: unknown option ${a[i]} (see  man igv)`);
      else if (/^[\w.]+:[\d,]+(-[\d,]+)?$/.test(a[i]) && !ctx.fs.exists(a[i])) locus = a[i];
      else files.push(a[i]);
    }
    // (--genome hg19: a genome that the IGV team hosts – hg38, hg19, mm39, mm10, danRer11, dm6, ce11, sacCer3 – unless a
    // file of that name is here)
    const hosted = genome && !ctx.fs.exists(genome) ? (MG.igvHosted || []).find((g) => g.id.toLowerCase() === String(genome).toLowerCase()) : null;
    for (const f of files.concat(genome && !hosted ? [genome] : [])) if (!ctx.fs.exists(f)) throw userErr(`igv: ${f}: No such file or directory${f === genome ? ` (a hosted genome: ${(MG.igvHosted || []).map((g) => g.id).join(', ')})` : ''}`);
    await MG.app.showWorkbench('igv');
    for (let t = 0; t < 300 && !MG.app.igv; t++) await new Promise((r) => setTimeout(r, 50));
    const I = MG.app.igv;
    if (!I) throw userErr('igv: the genome browser could not start');
    if (hosted) {
      if (!(await I.setGenome(hosted.id))) throw userErr(`igv: the genome ${hosted.id} could not be loaded – the hosted genomes need the internet`);
    } else if (genome) await I.loadGenomeFromFiles(ctx.fs, ctx.fs.resolve(genome));
    if (files.length) await I.loadPaths(ctx.fs, files.map((f) => ctx.fs.resolve(f)));
    if (locus) await I.goto(locus);
    ctx.io.note('Shown in the Genome browser tab.');
    return 0;
  };

  /* ------------------------------------------------------------------ network: files → the Networks tab */
  B.network = async (ctx) => {
    if (MG.shellUtil.forPerson && MG.shellUtil.forPerson(ctx)) return 1;
    const a = ctx.args.slice();
    const files = [], genes = [];
    let table = null, example = null, string = false, species = '9606', score = 400, add = 0;
    for (let i = 0; i < a.length; i++) {
      const x = a[i];
      const val = () => {
        if (i + 1 >= a.length) throw userErr(`network: ${x} needs a value (see  man network)`);
        return a[++i];
      };
      if (x === '--help' || x === '-h') {
        ctx.out(OWN_MAN.network + '\n');
        return 0;
      } else if (x === '--table' || x === '-t') table = val();
      else if (x === '--example') example = val();
      else if (x === '--string' || x === '-s') string = true;
      else if (x === '--species') species = val();
      else if (x === '--score') score = Number(val());
      else if (x === '--add') add = Number(val());
      else if (x.startsWith('-')) throw userErr(`network: unknown option ${x} (see  man network)`);
      else if (string) genes.push(...x.split(/[,;]+/).filter(Boolean));
      else files.push(x);
    }
    if (example && !/^(airway|karate)$/.test(example)) throw userErr(`network: there is no example ${example} (airway, karate)`);
    if (!/^\d+$/.test(species)) throw userErr('network: --species takes an NCBI taxon number (9606 human, 10090 mouse, 4932 yeast …)');
    if (!(score >= 0 && score <= 1000)) throw userErr('network: --score takes a number from 0 to 1000 (400 medium confidence, 700 high)');
    if (string && !genes.length) throw userErr('network: --string needs genes or proteins:  network --string TP53 MDM2');
    for (const f of files.concat(table ? [table] : [])) {
      if (!ctx.fs.exists(f)) throw userErr(`network: ${f}: No such file or directory`);
      if (ctx.fs.isDir(f)) throw userErr(`network: ${f}: Is a directory`);
    }
    if (!files.length && !table && !string && !example) throw userErr('usage: network FILE…   |  network --table FILE  |  network --string GENE…  |  network --example airway   (man network)');
    const N = await MG.app.networksReady();
    if (example) await N.example(example);
    if (files.length) await N.openPaths(files.map((f) => ctx.fs.resolve(f)));
    if (string) await N.stringNetwork({ ids: genes, species, score, add });
    if (table) {
      if (!N.cur) throw userErr('network: --table adds a table to the network that is open – open one first');
      await N.importTableDialog({ path: ctx.fs.resolve(table) });
    }
    ctx.io.note('Shown in the Networks tab.');
    return 0;
  };

  /* ------------------------------------------------------------------ the session as a notebook or a script */
  const HOME = () => (MG.app && MG.app.HOME) || '/home/user';
  const tilde = (p) => (p === HOME() ? '~' : p.startsWith(HOME() + '/') ? '~' + p.slice(HOME().length) : p);
  const qpath = (p) => (/^[\w~/.\-+]+$/.test(p) ? p : "'" + p.replace(/'/g, "'\\''") + "'");
  MG.termSession = {
    entries(T) {
      return ((T || MG.app.term).transcript || []).filter((e) => e.line.trim() && !/^\s*(export-session|clear|history)\b/.test(e.line));
    },
    toIpynb(T, title) {
      const list = this.entries(T);
      const when = list.length ? new Date(list[0].t) : new Date();
      const cells = [
        {
          type: 'markdown',
          source: `# ${title || 'Terminal session'}\n\nCommands run in the terminal of the Bioinformatics workbench on ${when.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })}, in the order they were run, with what they printed.\n\nEach cell starts with \`%%bash\`: it runs in the workbench's Notebook tab, and in Jupyter on a computer that has the same programs (samtools, bcftools … – see the README of the workbench). \`~\` is the home folder; files from \`/data/examples\` come with the workbench.`
        }
      ];
      for (const e of list) {
        const outputs = [];
        if (e.stdout) outputs.push({ type: 'stream', name: 'stdout', text: e.stdout });
        if (e.stderr) outputs.push({ type: 'stream', name: 'stderr', text: e.stderr });
        cells.push({ type: 'code', source: `%%bash\ncd ${qpath(tilde(e.cwd))}\n${e.line}`, outputs, meta: e.code ? { workbench: { exit_status: e.code } } : {} });
      }
      return MG.nbformat.make('python', cells, { workbench: { kind: 'terminal-session' } });
    },
    toSh(T) {
      const list = this.entries(T);
      let cwd = null;
      const lines = ['#!/usr/bin/env bash', `# Commands from the terminal of the Bioinformatics workbench (${new Date().toLocaleString('en-GB')}).`, '# Run with:  bash THIS_FILE   (each command ran in the folder named by the cd line before it)', ''];
      for (const e of list) {
        if (e.cwd !== cwd) {
          lines.push(`cd ${qpath(tilde(e.cwd))}`);
          cwd = e.cwd;
        }
        lines.push(e.line + (e.code ? `    # exit status ${e.code}` : ''));
        if (/^\s*cd(\s|$)/.test(e.line)) cwd = null;
      }
      return lines.join('\n') + '\n';
    },
    stamp() {
      const d = new Date();
      const p = (n) => String(n).padStart(2, '0');
      return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}`;
    },
    async saveNotebook(T, path, open) {
      const fs = MG.app.fs;
      const nb = this.toIpynb(T);
      fs.writeText(path, JSON.stringify(nb, null, 1));
      if (open) {
        await MG.app.showWorkbench('notebook');
        await MG.app.nbApp.open(path);
      }
      return path;
    },
    menu(anchor, T) {
      const n = this.entries(T).length;
      if (!n) {
        MG.toast('Nothing to save yet: run some commands first.', 'warn');
        return;
      }
      const name = `terminal-session-${this.stamp()}`;
      MG.popmenu(anchor, [
        ['notebook', `Open as a notebook here (${n} command${n === 1 ? '' : 's'})`, async () => {
          const p = `${HOME()}/notebooks/${name}.ipynb`;
          MG.app.fs.mkdirp(`${HOME()}/notebooks`);
          await this.saveNotebook(T, p, true);
          MG.toast(`Saved as <b>${MG.esc(MG.app.fs.pretty(p))}</b>.`, 'ok');
        }],
        ['download', 'Download as a Jupyter notebook (.ipynb)', () => MG.downloadText(JSON.stringify(this.toIpynb(T), null, 1), name + '.ipynb', 'application/x-ipynb+json')],
        ['code', 'Download as a shell script (.sh)', () => MG.downloadText(this.toSh(T), name + '.sh', 'text/x-shellscript')],
        ['trash', 'Start a new session record (forget these commands)', () => {
          (T || MG.app.term).transcript = [];
          MG.toast('The session record is empty now; the commands you run from now on are recorded.');
        }]
      ]);
    }
  };
  B['export-session'] = async (ctx) => {
    if (MG.shellUtil.forPerson && MG.shellUtil.forPerson(ctx)) return 1;
    const T = MG.app.term;
    const a = ctx.args;
    if (a[0] === '--clear') {
      T.transcript = [];
      ctx.out('The session record is empty now.\n');
      return 0;
    }
    if (!a.length || a[0] === '--help') {
      ctx.out(OWN_MAN['export-session'] + '\n');
      return a.length ? 0 : 1;
    }
    const f = a[0];
    if (/\.ipynb$/i.test(f)) {
      const p = ctx.fs.resolve(f);
      ctx.fs.writeText(p, JSON.stringify(MG.termSession.toIpynb(T), null, 1));
      ctx.out(`Saved ${MG.termSession.entries(T).length} commands to ${f}  (open it in the Notebook tab:  open ${f})\n`);
    } else {
      ctx.fs.writeText(f, MG.termSession.toSh(T), { mode: 'x' });
      ctx.out(`Saved ${MG.termSession.entries(T).length} commands to ${f}\n`);
    }
    return 0;
  };

  /* ------------------------------------------------------------------ help */
  B.help = (ctx) => {
    const v = MG.exec.versions;
    const has = (n) => !!(MG.shellTools && MG.shellTools[n]);
    // a program, its version, and what it is for – the descriptions start in one column
    const row = (name, text) => '  ' + name.padEnd(34) + text;
    const opt = (n, name, text) => (has(n) ? row(name, text) : null);
    ctx.out(
      [
        'Programs in this terminal – every one runs here, in your browser. (man NAME: examples; NAME --help: options)',
        '',
        'Reads, alignments and variants (the real programs, compiled to WebAssembly):',
        row(`fastp ${v.fastp}`, 'quality control and trimming of FASTQ files (HTML + JSON report)'),
        opt('cutadapt', `cutadapt ${v.cutadapt || ''}`, 'remove adapters, primers, poly-A; trim by quality:  cutadapt -a ADAPTER -o out.fastq reads.fastq'),
        row(`seqtk ${v.seqtk}`, 'FASTQ/FASTA: convert, subsample, trim, statistics'),
        row(`minimap2 ${v.minimap2}`, 'map reads:  minimap2 -ax sr REF.fa R1.fastq R2.fastq > out.sam'),
        row(`bowtie2 ${v.bowtie2}`, 'map short reads (bowtie2-build makes the index)'),
        opt('bwa', `bwa ${v.bwa || ''}`, 'map short reads:  bwa index REF.fa   then   bwa mem REF.fa R1.fastq R2.fastq > out.sam'),
        opt('bwa-mem2', `bwa-mem2 ${v['bwa-mem2'] || ''}`, 'bwa mem, rewritten for speed:  bwa-mem2 index REF.fa   then   bwa-mem2 mem REF.fa R1 R2 > out.sam'),
        opt('hisat2', `hisat2 ${v.hisat2 || ''}`, 'map RNA-seq reads across splice junctions (hisat2-build makes the index)'),
        row(`samtools ${v.samtools}`, 'sort, index, view, flagstat, stats, depth, faidx, mpileup …'),
        opt('mosdepth', `mosdepth ${v.mosdepth || ''}`, 'read depth per base, window or region:  mosdepth PREFIX sorted.bam'),
        row(`bcftools ${v.bcftools}`, 'mpileup, call, view, filter, query, stats, norm, index …'),
        opt('freebayes', `freebayes ${v.freebayes || ''}`, 'call variants:  freebayes -f REF.fa sorted.bam > calls.vcf'),
        opt('lofreq', `lofreq ${v.lofreq || ''}`, 'low-frequency variants (lofreq call) and somatic variants (lofreq somatic -n N.bam -t T.bam …)'),
        opt('bam-somaticsniper', `bam-somaticsniper ${v.somaticsniper || ''}`, 'somatic SNVs:  bam-somaticsniper -F vcf -f REF.fa tumor.bam normal.bam out.vcf'),
        opt('configureStrelkaSomaticWorkflow.py', `Strelka2 ${v.strelka2 || ''}`, 'somatic SNVs and indels:  configureStrelkaSomaticWorkflow.py …, then RUNDIR/runWorkflow.py -m local'),
        row(`bgzip, tabix (htslib ${v.htslib})`, 'compress and index'),
        row(`bedtools ${v.bedtools}`, 'genome arithmetic: intersect, merge, genomecov, getfasta …'),
        opt('wgsim', `wgsim ${v.wgsim || ''}`, 'simulate reads from a reference'),
        opt('gffread', `gffread ${v.gffread || ''}`, 'GFF/GTF files: convert; write transcript, CDS or protein sequences'),
        '',
        'RNA-seq: counts and abundances',
        opt('featureCounts', `featureCounts ${v.featurecounts || ''}`, 'reads per gene:  featureCounts -p --countReadPairs -a genes.gtf -o counts.txt sorted.bam'),
        opt('stringtie', `stringtie ${v.stringtie || ''}`, 'assemble transcripts and their abundance:  stringtie sorted.bam -G genes.gtf -o out.gtf'),
        opt('kallisto', `kallisto ${v.kallisto || ''}`, 'transcript abundances by pseudoalignment:  kallisto index, kallisto quant'),
        opt('salmon', `salmon ${v.salmon || ''}`, 'transcript abundances by selective alignment:  salmon index, salmon quant  (several threads)'),
        opt('bustools', `bustools ${v.bustools || ''}`, 'single-cell RNA-seq: sort, correct and count the BUS records of kallisto bus:  bustools count …'),
        '',
        'ChIP-seq and ATAC-seq: peaks',
        opt('macs3', `macs3 ${v.macs3 || ''}`, 'peaks over a control:  macs3 callpeak -t chip.bam -c input.bam -g hs -n NAME   (macs3 hmmratac: ATAC-seq)'),
        '',
        'Genes and proteins: gene finding, profile HMMs',
        opt('prodigal', `prodigal ${v.prodigal || ''}`, 'genes of bacteria and archaea:  prodigal -i genome.fna -o genes.gff -f gff -a proteins.faa'),
        opt('hmmsearch', `HMMER ${v.hmmer || ''}`, 'hmmbuild, hmmsearch, hmmscan, hmmpress, phmmer, jackhmmer, nhmmer, hmmalign, hmmfetch, hmmemit …'),
        '',
        'Metagenomics: who is in the sample',
        opt('kraken2', `kraken2 ${v.kraken2 || ''}`, 'reads to taxa:  kraken2 --db DB --paired --report sample.report R1.fq.gz R2.fq.gz  (kraken2-inspect, kraken2-build)'),
        opt('bracken', `bracken ${v.bracken || ''}`, 'species abundances from a Kraken2 report:  bracken -d DB -i sample.report -o sample.bracken -r 151  (bracken-build)'),
        '',
        'Genotypes of many people: quality control, LD, kinship, association (GWAS)',
        opt('plink2', `plink2 ${v.plink2 || ''}`, 'PLINK 2:  plink2 --vcf cohort.vcf.gz --freq --missing --hardy --out cohort  (several threads)'),
        '',
        'Sequences, alignments and trees:',
        opt('kalign', `kalign ${v.kalign || ''}`, 'multiple alignment:  kalign -i seqs.fasta -o aligned.afa'),
        opt('muscle', `muscle ${v.muscle || ''}`, 'multiple alignment:  muscle -in seqs.fasta -out aligned.afa'),
        opt('fasttree', `fasttree ${v.fasttree || ''}`, 'trees from alignments:  fasttree aligned.afa > tree.nwk'),
        opt('needleman_wunsch', 'needleman_wunsch, smith_waterman', 'pairwise global / local alignment (seq-align)'),
        opt('lastz', `lastz ${v.lastz || ''}`, 'align long DNA sequences'),
        '',
        'Languages and pipelines:',
        row('python, pip', 'Python (the notebooks\' Python): python script.py, python -c "…", pip install NAME'),
        row('Rscript, R', 'R (the notebooks\' R): Rscript script.R, Rscript -e \'…\''),
        row('snakemake', 'Snakemake 9 (browser edition): snakemake -n, snakemake --cores 1, --dag'),
        row('dot', 'Graphviz: dot -Tsvg graph.dot -o graph.svg'),
        row(`jq ${v.jq}`, 'JSON:  curl -s URL | jq .'),
        '',
        'GNU text tools (WebAssembly):',
        `  cat head tail wc sort uniq cut tr tee paste join comm seq fold shuf md5sum date (coreutils ${v.coreutils})`,
        `  grep egrep fgrep (grep ${v.grep})   sed (sed ${v.sed})   awk gawk (gawk ${v.gawk})   diff cmp (diffutils ${v.diffutils})`,
        '  gzip gunzip zcat zgrep (done by bgzip)',
        '',
        'Files, archives and the web:',
        '  ls cd pwd mkdir cp mv rm rmdir touch tree find du stat file chmod basename dirname realpath',
        '  unzip, zip, tar (-xzf, -czf)   curl, wget (web services that allow it: EBI, UniProt, Ensembl, NCBI, PDB …)',
        '  open FILE   show a file in its tab (notebook, picture, table, structure, tree)    nano FILE   edit it in Files',
        '  igv FILE…   show BAM/VCF/BED files in the Genome browser     download FILE|FOLDER   save to your computer',
        '  network FILE…   open networks (SIF, GraphML, GML, Cytoscape JSON …) in the Networks tab;  network --string TP53 MDM2',
        '  export-session FILE.ipynb   this session\'s commands as a notebook (or FILE.sh as a script)',
        '',
        'The shell is bash: | && || ; > >> < 2> 2>&1, quotes, $VAR, $( ), $(( )), globs, if/for/while/case, functions,',
        '  [[ ]], here-documents, <( ), xargs, printf, read. Scripts: bash script.sh. Not there: background jobs (&), sudo, apt.',
        'Keys: ↑/↓ earlier commands · Tab completes · Ctrl+C stops · Ctrl+L clears.  Full guide: the Help pane (Terminal).',
        ''
      ]
        .filter((l) => l !== null)
        .join('\n')
    );
  };
})();
