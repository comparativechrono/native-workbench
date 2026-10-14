/* Somatic variant calling in the terminal: the workflows that call several programs.

   lofreq somatic          LoFreq's somatic workflow is a Python script that runs lofreq call, filter, vcfset and uniq.
                           Here genomics-wasm's translation of it (lofreq-somatic.mjs, unchanged) runs those commands,
                           each in a worker of its own, with LoFreq compiled to WebAssembly.
   configureStrelkaSomaticWorkflow.py, then RUNDIR/runWorkflow.py
                           Strelka2 is used in two steps. The first checks the input as upstream's configure script does
                           (with its messages) and writes RUNDIR/runWorkflow.py; that script runs the workflow:
                           genomics-wasm's translation of it (strelka2-somatic.mjs, unchanged) runs Strelka's programs –
                           GetChromDepth, strelka2, bgzip, bgzf_cat, tabix, MergeRunStats – one after another.
   python2                 runWorkflow.py begins with #!/usr/bin/env python2. There is no Python 2 here: python2 runs
                           Strelka's workflow scripts, and says so for anything else.

   Each workflow runs inside the terminal's program runner (tools-wasm.js: OWN_WORKER, execWorker), which hands it the
   files its arguments name and takes back what it made. In a workflow the files have the paths of the terminal
   (/home/user/…, /data/…): the programs write the paths they are given into their output (Strelka's VCF header names
   the reference file). The two translations run with the workspacePath of index.mjs next to them (see there).

   Licence: the help texts and messages of configureStrelkaSomaticWorkflow.py and runWorkflow.py in this file are
   Strelka2's (Strelka - Small Variant Caller, Copyright (c) 2009-2018 Illumina, Inc.; GNU General Public License
   version 3 or later – assets/vendor/genomics-wasm/strelka2/2.9.10/LICENSE.txt, COPYRIGHT.txt; the source is in
   assets/vendor/licenses/sources/), so this file is distributed under the GNU GPL version 3 or later.
   SPDX-License-Identifier: GPL-3.0-or-later */
(function () {
  'use strict';
  const MG = window.MG;
  const T = (MG.shellTools = MG.shellTools || {});
  const enc = new TextEncoder();
  const dec = new TextDecoder('utf-8');
  const vendor = (rel) => new URL(String(MG.config.threadsBase || 'assets/vendor/genomics-wasm').replace(/\/?$/, '/') + rel, location.href);
  const dirname = (p) => p.slice(0, p.lastIndexOf('/')) || '/';
  const STRELKA = 'strelka2/2.9.10/';
  const MARK = 'WORKBENCH_STRELKA_SOMATIC = ';

  /* One command of a workflow, in a worker of its own. → what genomics-wasm's ToolRunner returns: {exitCode, stdout,
     stderr, files} – the files: of `outputs`, and below `outputDirectories`, those the command made or changed (a
     workflow keeps the others as they were). A program that stops on an error of WebAssembly rejects, as there. */
  function stageRunner(h, module, program, log) {
    return async (command, { files = [], outputs = [], outputDirectories = [] } = {}) => {
      const want = new Set(outputs), under = outputDirectories;
      const roots = [...new Set([...outputs.map(dirname), ...under])];
      h.stage(program === 'lofreq' ? 'lofreq ' + command[0] : program);
      const r = await h.spawn({ name: program, module }, { args: command, thisProgram: program, files: files.map((f) => ({ path: f.path, data: f.data })), roots });
      if (log) log(program, command, r.exitCode);
      if (r.error) throw new Error(`${program}: ${r.error}`);
      return { exitCode: r.exitCode, stdout: r.stdout, stderr: r.stderr, files: r.files.filter((f) => want.has(f.path) || under.some((d) => f.path.startsWith(d + '/'))) };
    };
  }

  /* ------------------------------------------------------------------ lofreq somatic */
  // the value of an option of lofreq somatic (argparse: -o X, -oX, --outprefix X, --outprefix=X, --outp X)
  function argValue(a, short, long) {
    let v = null;
    for (let i = 0; i < a.length; i++) {
      const x = a[i];
      if (x === short || (x.startsWith('--') && x.length > 2 && long.startsWith(x) && !x.includes('='))) v = a[++i];
      else if (x.startsWith(short) && x.length > 2 && !x.startsWith('--')) v = x.slice(2).replace(/^=/, '');
      else if (x.startsWith('--') && x.includes('=') && long.startsWith(x.slice(0, x.indexOf('=')))) v = x.slice(x.indexOf('=') + 1);
    }
    return v;
  }
  // the files that lofreq somatic writes, after its prefix (lofreq2_somatic.py, as in lofreq-somatic.mjs)
  const LOFREQ_OUTPUTS = ['normal_relaxed.vcf.gz', 'normal_relaxed.log', 'normal_stringent.snvs.vcf.gz', 'normal_stringent.indels.vcf.gz',
    'tumor_relaxed.vcf.gz', 'tumor_relaxed.log', 'tumor_stringent.snvs.vcf.gz', 'tumor_stringent.indels.vcf.gz',
    'somatic_raw.snvs.vcf.gz', 'somatic_raw.indels.vcf.gz', 'somatic_final.snvs.vcf.gz', 'somatic_final.indels.vcf.gz',
    'somatic_final_minus-dbsnp.snvs.vcf.gz', 'somatic_final_minus-dbsnp.indels.vcf.gz', 'germline.snvs.vcf.gz', 'germline.indels.vcf.gz'];
  // bytes without the parts that were added to them, in their order (the messages of the commands of a workflow)
  function without(all, parts) {
    const out = [];
    let at = 0;
    for (const part of parts) {
      if (!part || !part.length) continue;
      const i = indexOf(all, part, at);
      if (i < 0) continue;
      out.push(all.subarray(at, i));
      at = i + part.length;
    }
    out.push(all.subarray(at));
    const n = out.reduce((k, b) => k + b.length, 0), joined = new Uint8Array(n);
    let o = 0;
    for (const b of out) { joined.set(b, o); o += b.length; }
    return joined;
  }
  function indexOf(hay, needle, from) {
    outer: for (let i = from; i + needle.length <= hay.length; i++) {
      for (let j = 0; j < needle.length; j++) if (hay[i + j] !== needle[j]) continue outer;
      return i;
    }
    return -1;
  }
  async function lofreq(args, h) {
    const [flow, ws] = await Promise.all([import(vendor('lofreq/2.1.5/lofreq-somatic.mjs').href), import(vendor('lofreq/2.1.5/index.mjs').href)]);
    ws.setWorkspace(h.cwd);
    const a = args.slice(1);
    const files = await h.inputsOf(a, ['-o', '--outprefix']);
    // The workflow checks that the folder of the output prefix is there, as upstream does; it knows of a folder by the
    // files in it – a folder that holds none of the input files is shown by an empty file of its own.
    const prefix = argValue(a, '-o', '--outprefix');
    let outdir = null;
    if (prefix) {
      try { outdir = dirname(ws.workspacePath(prefix + 'normal_relaxed.vcf.gz')); } catch (e) { outdir = null; }
      if (outdir && h.isDir(outdir) && !files.some((f) => f.path.startsWith(outdir + '/'))) files.push({ path: outdir + '/.lofreq-somatic-folder', data: new Uint8Array(0) });
    }
    // Upstream refuses to write over the files of an earlier run with the same prefix; the workflow looks for them among
    // its files – it is shown those that are there (their contents are not needed)
    if (prefix) for (const suffix of LOFREQ_OUTPUTS) {
      let p = null;
      try { p = ws.workspacePath(prefix + suffix); } catch (e) { p = null; }
      if (p && h.isFile(p) && !files.some((f) => f.path === p)) files.push({ path: p, data: new Uint8Array(0) });
    }
    // (what each command printed: upstream keeps it out of sight – the log files have the calls' messages – and so does
    // the terminal, unless the workflow fails)
    const printed = [];
    const core = stageRunner(h, 'lofreq/2.1.5/lofreq.mjs', 'lofreq');
    const r = await flow.runSomatic(a, { files, outputDirectories: outdir ? [outdir] : [] }, async (command, o) => {
      const res = await core(command, o);
      printed.push(res.stderr);
      return res;
    });
    if (r.exitCode === 0) r.stderr = without(r.stderr, printed);
    // (the warnings in upstream's words – the translation says "upstream recommends")
    r.stderr = enc.encode(dec.decode(r.stderr)
      .replace('WARNING: No dbsnp file given. Upstream recommends dbsnp when dealing with human data.', 'WARNING: No dbsnp file given. Using dbsnp is highly recommended when dealing with human data.')
      .replace('WARNING: dbsnp has no .tbi index; upstream recommends bgzip and tabix.', 'WARNING: the dbsnp file has no .tbi index: compress it with bgzip and index it with tabix.'));
    const made = new Set(r.workflow.generatedFiles);
    // (lofreq somatic -h: the last lines of the help are about genomics-wasm's own use of it)
    let stdout = r.stdout;
    const help = dec.decode(stdout);
    if (help.includes('All file paths are inside the /work workspace.')) stdout = enc.encode(help.replace(/--continue is not implemented\. All file paths are inside the \/work workspace\.\nSee runtime\/LOFREQ\.md[^\n]*\n/, '--continue is not available here. The steps run one after another, in this browser.\n'));
    return { exitCode: r.exitCode, stdout, stderr: r.stderr, files: r.files.filter((f) => made.has(f.path)), order: [] };
  }

  /* ------------------------------------------------------------------ Strelka2: configure */
  const CONFIGURE = 'configureStrelkaSomaticWorkflow.py';
  const HELP = `Usage: ${CONFIGURE} [options]

Version: 2.9.10

This script configures Strelka somatic small variant calling.
You must specify an alignment file (BAM or CRAM) for each sample of a matched tumor-normal pair.

Configuration will produce a workflow run script which
can execute the workflow on a single node or through
sge and resume any interrupted execution.

Options:
  --version             show program's version number and exit
  -h, --help            show this help message and exit
  --config=FILE         provide a configuration file to override defaults in
                        global config file
                        (/usr/bin/configureStrelkaSomaticWorkflow.py.ini)
  --allHelp             show all extended/hidden options

  Workflow options:
    --normalBam=FILE    Normal sample BAM or CRAM file. (no default)
    --tumorBam=FILE, --tumourBam=FILE
                        Tumor sample BAM or CRAM file. [required] (no default)
    --outputCallableRegions
                        Output a bed file describing somatic callable regions
                        of the genome
    --referenceFasta=FILE
                        samtools-indexed reference fasta file [required]
    --indelCandidates=FILE
                        Specify a VCF of candidate indel alleles. These
                        alleles are always evaluated but only reported in the
                        output when they are inferred to exist in the sample.
                        The VCF must be tabix indexed. All indel alleles must
                        be left-shifted/normalized, any unnormalized alleles
                        will be ignored. This option may be specified more
                        than once, multiple input VCFs will be merged.
                        (default: None)
    --forcedGT=FILE     Specify a VCF of candidate alleles. These alleles are
                        always evaluated and reported even if they are
                        unlikely to exist in the sample. The VCF must be tabix
                        indexed. All indel alleles must be left-
                        shifted/normalized, any unnormalized allele will
                        trigger a runtime error. This option may be specified
                        more than once, multiple input VCFs will be merged.
                        Note that for any SNVs provided in the VCF, the SNV
                        site will be reported (and for gVCF, excluded from
                        block compression), but the specific SNV alleles are
                        ignored. (default: None)
    --exome, --targeted
                        Set options for exome or other targeted input: note in
                        particular that this flag turns off high-depth filters
    --callRegions=FILE  Optionally provide a bgzip-compressed/tabix-indexed
                        BED file containing the set of regions to call. No VCF
                        output will be provided outside of these regions. The
                        full genome will still be used to estimate statistics
                        from the input (such as expected depth per
                        chromosome). Only one BED file may be specified.
                        (default: call the entire genome)
    --runDir=DIR        Name of directory to be created where all workflow
                        scripts and output will be written. Each analysis
                        requires a separate directory. (default:
                        StrelkaSomaticWorkflow)

`;
  const EXTENDED = `  Extended options:
    These options are either unlikely to be reset after initial site
    configuration or only of interest for workflow development/debugging.
    They will not be printed here if a default exists unless --allHelp is
    specified

    --noiseVcf=FILE     Noise vcf file (submit argument multiple times for
                        more than one file)
    --scanSizeMb=INT    Maximum sequence region size (in megabases) scanned by
                        each task during genome variant calling. (default: 12)
    --region=REGION     Limit the analysis to one or more genome region(s) for
                        debugging purposes. If this argument is provided
                        multiple times the union of all specified regions will
                        be analyzed. All regions must be non-overlapping to
                        get a meaningful result. Examples: '--region chr20'
                        (whole chromosome), '--region chr2:100-2000 --region
                        chr3:2500-3000' (two regions)'. If this option is
                        specified (one or more times) together with the
                        --callRegions BED file, then all region arguments will
                        be intersected with the callRegions BED track.
    --callMemMb=INT     Set variant calling task memory limit (in megabytes).
                        It is not recommended to change the default in most
                        cases, but this might be required for a sample of
                        unusual depth.
    --retainTempFiles   Keep all temporary files (for workflow debugging)
    --disableEVS        Disable empirical variant scoring (EVS).
    --reportEVSFeatures
                        Report all empirical variant scoring features in VCF
                        output.
    --snvScoringModelFile=FILE
                        Provide a custom empirical scoring model file for SNVs
                        (default: /usr/share/strelka/config/somaticSNVScoringM
                        odels.json)
    --indelScoringModelFile=FILE
                        Provide a custom empirical scoring model file for
                        indels (default: /usr/share/strelka/config/somaticInde
                        lScoringModels.json)
`;
  // optparse's options of the configure script: name → [takes a value, repeatable, integer]
  const C_OPTS = {
    '--version': [0], '--help': [0], '--config': [1], '--allHelp': [0],
    '--normalBam': [1, 1], '--tumorBam': [1, 1], '--tumourBam': [1, 1], '--outputCallableRegions': [0],
    '--referenceFasta': [1], '--indelCandidates': [1, 1], '--forcedGT': [1, 1], '--exome': [0], '--targeted': [0],
    '--callRegions': [1], '--runDir': [1], '--noiseVcf': [1, 1], '--scanSizeMb': [1, 0, 1], '--region': [1, 1],
    '--callMemMb': [1, 0, 1], '--retainTempFiles': [0], '--disableEVS': [0], '--reportEVSFeatures': [0],
    '--snvScoringModelFile': [1], '--indelScoringModelFile': [1]
  };
  class Usage extends Error {}
  /* optparse: --opt value, --opt=value, a unique beginning of a long option; -h. → {o: name → [values], rest} */
  function optparse(args, table, shorts) {
    const o = {}, rest = [];
    for (let i = 0; i < args.length; i++) {
      let x = args[i], v;
      if (x === '--') { rest.push(...args.slice(i + 1)); break; }
      if (!x.startsWith('-') || x === '-') { rest.push(x); continue; }
      if (!x.startsWith('--')) {
        const s = shorts[x.slice(0, 2)];
        if (!s) throw new Usage(`no such option: ${x.slice(0, 2)}`);
        if (table[s][0]) {
          v = x.length > 2 ? x.slice(2) : args[++i];
          if (v === undefined) throw new Usage(`${x.slice(0, 2)} option requires an argument`);
        } else if (x.length > 2) throw new Usage(`no such option: -${x[2]}`);
        (o[s] = o[s] || []).push(v);
        continue;
      }
      const eq = x.indexOf('=');
      let name = eq < 0 ? x : x.slice(0, eq);
      if (eq >= 0) v = x.slice(eq + 1);
      if (!table[name]) {
        const m = Object.keys(table).filter((k) => k.startsWith(name));
        if (m.length === 1) name = m[0];
        else if (m.length > 1) throw new Usage(`ambiguous option: ${name} (${m.join(', ')}?)`);
        else throw new Usage(`no such option: ${name}`);
      }
      const [takes, , integer] = table[name];
      if (takes) {
        if (v === undefined) { v = args[++i]; if (v === undefined) throw new Usage(`${name} option requires an argument`); }
        if (integer && !/^[-+]?\d+$/.test(v.trim())) throw new Usage(`option ${name}: invalid integer value: '${v}'`);
      } else if (eq >= 0) throw new Usage(`${name} option does not take a value`);
      (o[name] = o[name] || []).push(v);
    }
    return { o, rest };
  }
  const norm = (p) => MG.path.norm(p);
  async function configure(ctx) {
    const fs = ctx.fs, a = ctx.args;
    const usage = (msg) => { ctx.err(`Usage: ${CONFIGURE} [options]\n\n${CONFIGURE}: error: ${msg}\n`); return 2; };
    if (!a.length) { ctx.out(HELP + '  Extended options (hidden):\n'); return 2; }
    let p;
    try { p = optparse(a, C_OPTS, { '-h': '--help' }); } catch (e) { if (e instanceof Usage) return usage(e.message); throw e; }
    const o = p.o, one = (k) => (o[k] ? o[k][o[k].length - 1] : null), many = (...ks) => ks.flatMap((k) => o[k] || []);
    if (o['--help'] || o['--allHelp']) { ctx.out(HELP + (o['--allHelp'] ? EXTENDED : '  Extended options (hidden):\n')); return 0; }
    if (o['--version']) { ctx.out('2.9.10\n'); return 0; }
    if (p.rest.length) return usage(`${p.rest.length} unrecognized argument${p.rest.length > 1 ? 's' : ''}:\n${p.rest.map((x) => `'${x}'`).join('\n')}`);
    const abs = (f) => norm(fs.resolve(f));
    const isFile = (f) => fs.exists(f) && !fs.isDir(f);
    // the checks of upstream's configure script, in its order, with its messages
    if (one('--config') != null && !isFile(one('--config'))) return usage(`Can't find config file: '${abs(one('--config'))}'`);
    const runDir = abs(one('--runDir') || 'StrelkaSomaticWorkflow');
    const script = runDir + '/runWorkflow.py';
    if (fs.exists(script)) return usage(`Run directory already contains workflow script file '${script}'. Each analysis must be configured in a separate directory.`);
    const ref = one('--referenceFasta');
    if (ref == null) return usage('No reference fasta file specified');
    if (!isFile(ref)) return usage(`Can't find reference fasta file: '${abs(ref)}'`);
    if (!isFile(abs(ref) + '.fai')) return usage(`Can't find expected fasta index file: '${abs(ref)}.fai'`);
    const tabixed = (list, label) => {
      for (const f of list) {
        if (!isFile(f)) return `Can't find expected ${label} file: '${f}'`;
        if (!isFile(f + '.tbi')) return `Can't find expected ${label} index file: '${f}.tbi'`;
      }
      return null;
    };
    let m = tabixed(many('--indelCandidates'), 'candidate indel vcf') || tabixed(many('--forcedGT'), 'forced genotype vcf') || tabixed(one('--callRegions') != null ? [one('--callRegions')] : [], 'call-regions bed');
    if (m) return usage(m);
    const fai = parseFai(await fs.readText(abs(ref) + '.fai'));
    for (const r of many('--region')) for (const rr of r.split('+')) {
      const chrom = rr.includes(':') ? rr.slice(0, rr.lastIndexOf(':')) : rr;
      if (!fai.has(chrom) && !fai.has(rr)) return usage(`Chromosome label '${chrom}', parsed from region argument '${rr}', not found in reference genome.`);
    }
    for (const [k, label] of [['--snvScoringModelFile', 'SNV empirical scoring model file'], ['--indelScoringModelFile', 'Indel empirical scoring model file']]) {
      if (one(k) != null && !isFile(one(k))) return usage(`Can't find ${label}: '${abs(one(k))}'`);
    }
    m = tabixed(many('--noiseVcf'), 'noise vcf');
    if (m) return usage(m);
    const bams = [];
    for (const [list, label] of [[many('--normalBam'), 'normal'], [many('--tumorBam', '--tumourBam'), 'tumor']]) {
      for (const b of list) {
        if (!isFile(b)) return usage(`Can't find ${label} sample BAM/CRAM file: '${abs(b)}'`);
        if (!/\.(bam|cram)$/.test(abs(b))) return usage(`Input alignment files should be in BAM/CRAM format and with extension .bam/.cram: '${abs(b)}'`);
        const x = abs(b);
        if (!['.bai', '.csi', '.crai'].some((s) => isFile(x + s)) && !(x.endsWith('.bam') && isFile(x.slice(0, -4) + '.bai'))) return usage(`Can't find any expected BAM/CRAM index files for: '${x}'`);
      }
    }
    if (!many('--tumorBam', '--tumourBam').length) return usage('No tumor sample BAM/CRAM files specified');
    for (const [list, label] of [[many('--normalBam'), 'normal'], [many('--tumorBam', '--tumourBam'), 'tumor']]) {
      if (list.length > 1) return usage(`More than one ${label} sample BAM/CRAM files specified`);
      for (const b of list) bams.push([abs(b), label]);
    }
    // the chromosomes of the reference and of the alignments (upstream's checkChromSet, which reads the headers with htsfile)
    const fail = (msg) => { ctx.err(`\nCONFIGURATION ERROR:\n${msg}\n\n`); return 1; };
    const sq = [];
    for (const [b] of bams) {
      const r = await MG.exec.run({ ...ctx, stdin: null, inherit: null, redirectTarget: null, mergeStderr: false }, 'samtools', ['view', '-H', b]);
      if (r.code) { ctx.err(r.stderr); return fail(`Can't read the header of the BAM/CRAM file: '${b}'`); }
      const info = new Map();
      for (const line of r.stdout.split('\n')) if (line.startsWith('@SQ\t')) {
        const f = Object.fromEntries(line.split('\t').slice(1).map((x) => [x.slice(0, 2), x.slice(3)]));
        if (f.SN != null) info.set(f.SN, [Number(f.LN), info.size]);
      }
      sq.push(info);
    }
    if (sq.length) {
      const [first, label0] = [sq[0], bams[0][1]];
      for (const [chrom, [len]] of first) {
        if (!fai.has(chrom)) return fail(`Reference genome mismatch: Reference fasta file is missing a chromosome found in the ${label0} BAM/CRAM file: '${chrom}'`);
        if (fai.get(chrom) !== len) return fail(`Reference genome mismatch: The length of chromosome '${chrom}' is ${fai.get(chrom)} in the reference fasta file but ${len} in the ${label0} BAM/CRAM file`);
      }
      for (const chrom of fai.keys()) if (!first.has(chrom)) return fail(`Reference genome mismatch: ${label0} BAM/CRAM file is missing a chromosome found in the reference fasta file: '${chrom}'`);
      for (let i = 1; i < sq.length; i++) {
        const other = new Map(sq[i]), label = bams[i][1];
        for (const [chrom, [len, ord]] of first) {
          if (!other.has(chrom)) return fail(`Reference genome mismatch: ${label} BAM/CRAM file is missing a chromosome found in the ${label0} BAM/CRAM file: '${chrom}'`);
          const [len2, ord2] = other.get(chrom);
          if (len !== len2) return fail(`Reference genome mismatch: The length of chromosome '${chrom}' is ${len} in the ${label0} BAM/CRAM file, but ${len2} in the ${label} BAM/CRAM file`);
          if (ord !== ord2) return fail(`Reference genome mismatch: Chromosome '${chrom}' is ordered ${ordinal(ord + 1)} in the ${label0} BAM/CRAM file, but ${ordinal(ord2 + 1)} in the ${label} BAM/CRAM file`);
          other.delete(chrom);
        }
        for (const chrom of other.keys()) return fail(`Reference genome mismatch: ${label0} BAM/CRAM file is missing a chromosome found in the ${label} BAM/CRAM file: '${chrom}'`);
      }
      const seen = new Set();
      for (const [b] of bams) { if (seen.has(b)) return usage(`Repeated input BAM/CRAM file: ${b}`); seen.add(b); }
    }
    // the run folder, as upstream leaves it: the run script, and the folders the workflow writes into
    for (const d of [runDir, runDir + '/results/variants', runDir + '/results/stats', runDir + '/workspace']) fs.mkdirp(d);
    if (o['--outputCallableRegions']) fs.mkdirp(runDir + '/results/regions');
    const config = { version: '2.9.10', cwd: fs.cwd, args: a.slice(), runDir };
    const line = `${CONFIGURE} ${a.join(' ')}`;
    fs.writeText(script, `#!/usr/bin/env python2
# Workflow run script auto-generated by command: '${line.replace(/'/g, "\\'")}'
#
# In this workbench the terminal runs this script itself:  ./runWorkflow.py -m local -j 1  (or: python2 runWorkflow.py -m local)
# It reads the configuration below and runs Strelka2 2.9.10's somatic workflow in the browser: Strelka's programs
# (GetChromDepth, strelka2, bgzip, bgzf_cat, tabix, MergeRunStats), compiled to WebAssembly, one after another.
# Edit nothing in it: configure a new run folder instead.

import os, sys

if sys.version_info >= (3,0):
    import platform
    raise Exception("Strelka does not currently support python3 (version %s detected)" % (platform.python_version()))

${MARK}${JSON.stringify(config)}
`, { mode: 'x' });
    ctx.out(`\nSuccessfully created workflow run script.\nTo execute the workflow, run the following script and set appropriate options:\n\n${script}\n`);
    return 0;
  }
  function parseFai(text) {
    const m = new Map();
    for (const line of text.split('\n')) { const c = line.split('\t'); if (c.length >= 2 && c[0]) m.set(c[0], Number(c[1])); }
    return m;
  }
  function ordinal(n) { const s = n % 100 >= 11 && n % 100 <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' })[n % 10] || 'th'; return n + s; }

  /* ------------------------------------------------------------------ Strelka2: runWorkflow.py */
  const RUN_HELP = `Usage: runWorkflow.py [options]

Version: 2.9.10

Options:
  --version             show program's version number and exit
  -h, --help            show this help message and exit
  -m MODE, --mode=MODE  select run mode (local|sge)
  -q QUEUE, --queue=QUEUE
                        specify scheduler queue name
  -j JOBS, --jobs=JOBS  number of jobs, must be an integer or 'unlimited'
                        (default: Estimate total cores on this node for local
                        mode, 128 for sge mode)
  -g MEMGB, --memGb=MEMGB
                        gigabytes of memory available to run workflow -- only
                        meaningful in local mode, must be an integer (default:
                        Estimate the total memory for this node for local
                        mode, 'unlimited' for sge mode)
  -d, --dryRun          dryRun workflow code without actually running command-
                        tasks
  --quiet               Don't write any log output to stderr (but still write
                        to workspace/pyflow.data/logs/pyflow_log.txt)

  development debug options:
    --rescore           Reset task list to re-run hypothesis generation and
                        scoring without resetting graph generation.

  extended portability options (should not be needed by most users):
    --maxTaskRuntime=hh:mm:ss
                        Specify scheduler max runtime per task, argument is
                        provided to the 'h_rt' resource limit if using SGE (no
                        default)

Note this script can be re-run to continue the workflow run in case of
interruption. Also note that dryRun option has limited utility when
task definition depends on upstream task results -- in this case the
dry run will not cover the full 'live' run task set.
`;
  const R_OPTS = { '--version': [0], '--help': [0], '--mode': [1], '--queue': [1], '--jobs': [1], '--memGb': [1], '--dryRun': [0], '--quiet': [0], '--mailTo': [1, 1], '--rescore': [0], '--maxTaskRuntime': [1] };
  const R_SHORT = { '-h': '--help', '-m': '--mode', '-q': '--queue', '-j': '--jobs', '-g': '--memGb', '-d': '--dryRun', '-e': '--mailTo' };
  const isRunScript = (text) => text.includes('\n' + MARK);
  function readConfig(text) {
    const line = text.split('\n').find((l) => l.startsWith(MARK));
    const c = line ? JSON.parse(line.slice(MARK.length)) : null;
    if (!c || !Array.isArray(c.args) || typeof c.cwd !== 'string' || typeof c.runDir !== 'string') throw new Error('the configuration in the run script cannot be read');
    return c;
  }
  async function runWorkflow(ctx, script, opts) {
    const name = 'runWorkflow.py';
    const usage = (msg) => { ctx.err(`Usage: ${name} [options]\n\n${name}: error: ${msg}\n`); return 2; };
    let p;
    try { p = optparse(opts, R_OPTS, R_SHORT); } catch (e) { if (e instanceof Usage) return usage(e.message); throw e; }
    const o = p.o, one = (k) => (o[k] ? o[k][o[k].length - 1] : null);
    if (o['--help']) { ctx.out(RUN_HELP); return 0; }
    if (o['--version']) { ctx.out('2.9.10\n'); return 0; }
    if (p.rest.length || one('--mode') == null) { ctx.out(RUN_HELP); return 2; }
    const mode = one('--mode');
    if (mode !== 'local' && mode !== 'sge') return usage('Invalid mode. Available modes are: local, sge');
    if (mode === 'sge') return usage('sge mode sends the tasks to a Sun Grid Engine cluster, which a browser does not have: use -m local');
    for (const [k, what] of [['--jobs', 'Jobs'], ['--memGb', 'memGb']]) {
      const v = one(k);
      if (v != null && v !== 'unlimited' && !(/^[-+]?\d+$/.test(v.trim()) && +v > 0)) return usage(`${what} must be 'unlimited' or an integer greater than 1`);
    }
    if (o['--dryRun']) return usage('-d (--dryRun) is not available in this terminal: the workflow is not run by pyflow here, and so it has no list of tasks to show without running them');
    if (one('--jobs') && one('--jobs') !== '1' && ctx.io && ctx.io.note) ctx.io.note(`${name}: -j ${one('--jobs')} – in the browser Strelka's tasks run one after another`);
    const given = { args: ctx.args, name: ctx.name };
    const cmdline = [ctx.name === 'python2' ? script : ctx.name, ...opts].join(' ');
    ctx.args = [script];
    ctx.name = name;
    try { return await MG.runReal(ctx, 'strelka2', { flow: { quiet: !!o['--quiet'], cmdline } }); } finally { ctx.args = given.args; ctx.name = given.name; }
  }
  // the workflow itself (see OWN_WORKER.strelka2 in tools-wasm.js): args = [the run script]; h.opts: {quiet, cmdline}
  async function strelka(args, h) {
    const script = h.abs(args[0]);
    const quiet = !!h.opts.quiet, cmdline = h.opts.cmdline || args[0];
    const c = readConfig(await h.readText(script));
    const [flow, ws] = await Promise.all([import(vendor(STRELKA + 'strelka2-somatic.mjs').href), import(vendor(STRELKA + 'index.mjs').href)]);
    ws.setWorkspace(c.cwd);
    const runDir = c.runDir, start = Date.now(), log = [];
    const say = (who, text) => log.push(`[${new Date().toISOString()}] [workbench] [${who}] ${text}`);
    say('WorkflowRunner', 'Initiating the Strelka somatic workflow (Strelka 2.9.10: its tasks run one after another, in this browser)');
    say('WorkflowRunner', `WorkingDir: '${h.cwd}'`);
    say('WorkflowRunner', `ProcessCmdLine: '${cmdline}'`);
    say('WorkflowRunner', '[RunParameters] mode: local');
    const files = await h.inputsOf(c.args, ['--runDir'], c.cwd);
    const execute = (tool, command, o) => stageRunner(h, STRELKA + tool + '.mjs', tool)(command, o);
    let r, error = null;
    try {
      r = await flow.runSomatic(c.args, { files, outputDirectories: [runDir] }, execute, vendor(STRELKA));
    } catch (e) { error = e; }
    if (r) for (const s of r.workflow.stages) say('TaskManager', `${s.exitCode === 0 && !(s.missingOutputs || []).length ? 'Completed' : '[ERROR] Failed to complete'} command task: '${s.id}' (${s.kind === 'native' ? s.tool : 'done by the workflow script: ' + s.tool})`);
    const code = error ? 1 : r.exitCode;
    let stderr = r ? dec.decode(r.stderr) : '';
    const why = stderr.split('\n').filter((l) => l.startsWith('strelka2 somatic: ')).map((l) => l.slice(18));
    stderr = stderr.split('\n').filter((l) => !l.startsWith('strelka2 somatic: ')).join('\n');
    if (error) why.push(error.message || String(error));
    if (code === 0) {
      say('WorkflowRunner', 'Strelka somatic workflow successfully completed.');
      say('WorkflowRunner', '\tworkflow version: 2.9.10');
      say('WorkflowRunner', 'Workflow successfully completed all tasks');
    } else for (const w of why) say('WorkflowRunner', `[ERROR] ${w}`);
    say('WorkflowRunner', `Elapsed time for full workflow: ${Math.round((Date.now() - start) / 1000)} sec`);
    const text = log.join('\n') + '\n';
    const out = r ? r.files.filter((f) => f.path.startsWith(runDir + '/')) : [];
    out.push({ path: runDir + '/workflow.exitcode.txt', data: enc.encode(code + '\n') });
    out.push({ path: runDir + '/workflow.error.log.txt', data: enc.encode(code ? why.join('\n') + '\n' : '') });
    out.push({ path: runDir + '/workflow.warning.log.txt', data: new Uint8Array(0) });
    out.push({ path: runDir + '/workspace/pyflow.data/logs/pyflow_log.txt', data: enc.encode(text) });
    if (code === 0 && h.io && h.io.note) h.io.note(`The calls are in ${h.pretty(runDir)}/results/variants/: somatic.snvs.vcf.gz and somatic.indels.vcf.gz (with their .tbi indexes); look at them with  bcftools view -f PASS ${h.pretty(runDir)}/results/variants/somatic.snvs.vcf.gz`);
    return { exitCode: code, stdout: r ? r.stdout : new Uint8Array(0), stderr: enc.encode(stderr + (quiet ? '' : text)), files: out, order: [] };
  }

  /* ------------------------------------------------------------------ python2 */
  async function python2(ctx) {
    const a = ctx.args, fs = ctx.fs;
    let i = 0;
    while (i < a.length && /^-[A-Za-z]+$/.test(a[i])) i++;
    const script = a[i];
    if (script != null && fs.exists(script) && !fs.isDir(script)) {
      let text = '';
      try { text = await fs.readText(script); } catch (e) { text = ''; }
      if (isRunScript(text)) return runWorkflow(ctx, script, a.slice(i + 1));
    }
    ctx.err('python2: there is no Python 2 in this terminal. It runs only the workflow script of Strelka2 (runWorkflow.py, made by configureStrelkaSomaticWorkflow.py) – for anything else use python3.\n');
    return 127;
  }

  const MAN_CONFIGURE = `configureStrelkaSomaticWorkflow.py 2.9.10 · Strelka2's somatic workflow, running in your browser

Strelka2 calls somatic SNVs and small indels from a tumour BAM and its matched normal BAM. As upstream, in two steps:

configureStrelkaSomaticWorkflow.py --normalBam /data/examples/somatic/normal.bam --tumorBam /data/examples/somatic/tumor.bam \\
    --referenceFasta /data/examples/somatic/reference.fa --callRegions /data/examples/somatic/regions.bed.gz --runDir strelka_run
strelka_run/runWorkflow.py -m local -j 1
bcftools view -H -f PASS strelka_run/results/variants/somatic.snvs.vcf.gz      (the calls that passed the filters)

The first step checks the input as upstream does (the reference needs its .fai, the BAM files their .bai, and BAM headers
and reference must name the same chromosomes, of the same lengths) and writes RUNDIR/runWorkflow.py. That script runs the
workflow: chromosome depth (GetChromDepth), calling and scoring (strelka2, with the bundled empirical scoring models),
then bgzip, tabix and MergeRunStats. Results: RUNDIR/results/variants/somatic.snvs.vcf.gz and somatic.indels.vcf.gz
(.tbi indexes too) and RUNDIR/results/stats/runStats.tsv.

--exome (--targeted): no depth filter; --region CHR:START-END; --callRegions FILE.bed.gz (bgzip + tabix -p bed);
--outputCallableRegions; --indelCandidates / --forcedGT / --noiseVcf FILE.vcf.gz; --config FILE ([StrelkaSomatic]
values). --allHelp lists all options. runWorkflow.py: -m local only (no sge); the tasks run one after another, whatever
-j says. The germline workflow (configureStrelkaGermlineWorkflow.py) is not here.`;
  T[CONFIGURE] = { version: '2.9.10', summary: 'Strelka2: configures the somatic small-variant workflow for a tumour and a normal BAM (then run RUNDIR/runWorkflow.py)', man: MAN_CONFIGURE, run: configure };
  T['configureStrelkaGermlineWorkflow.py'] = {
    version: '2.9.10', summary: 'Strelka2 germline workflow – not available here (only the somatic one)', hidden: true,
    man: 'configureStrelkaGermlineWorkflow.py · not in this terminal: only Strelka2\'s somatic workflow is (configureStrelkaSomaticWorkflow.py). For germline variants use freebayes or bcftools mpileup + call.',
    run: (ctx) => { ctx.err('configureStrelkaGermlineWorkflow.py: only the somatic workflow of Strelka2 is in this terminal (configureStrelkaSomaticWorkflow.py). For germline variants use freebayes, or bcftools mpileup | bcftools call.\n'); return 127; }
  };
  T.python2 = {
    version: '', summary: 'Runs Strelka2\'s workflow script (runWorkflow.py) – there is no Python 2 here otherwise', hidden: true,
    man: 'python2 · There is no Python 2 in this terminal. python2 RUNDIR/runWorkflow.py (or RUNDIR/runWorkflow.py itself, whose first line is #!/usr/bin/env python2) runs the workflow script that configureStrelkaSomaticWorkflow.py writes. For Python, use python3.',
    run: python2
  };
  MG.somatic = { lofreq, strelka, isRunScript, readConfig };
})();
