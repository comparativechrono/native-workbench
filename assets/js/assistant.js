/* =====================================================================
   The AI assistant of the workbench.

   Chat  – a real AI model answers questions about code, errors, programs
           and methods. With each question it gets – if the user leaves the
           boxes ticked – the code of the open notebook, the names of the
           user's files and the last terminal commands (never what is in the
           data files). Code in its answers goes into a notebook, the
           terminal or a file with one click. "Ask AI" on a notebook cell and
           "Ask the AI assistant about this error" under a failed command
           send them here.
   Agent – the same model as an agent: it carries out a task by running
           commands in the Terminal, one step at a time, in a folder of its
           own (~/ai-agent/run-N). It may read any file but write only there:
           what a step changes outside it is undone. Every command and its
           output is shown, and the run is kept as a notebook in its folder
           (agent-record.ipynb).
   The model is the user's: Google Gemini (free tier), Anthropic or an
   OpenAI-compatible service, called from the browser with a key that the
   user enters. The key is kept in memory – or, if the user asks, in this
   tab's sessionStorage until the tab is closed – never in localStorage and
   never in a file. Without a key: how to get one, a prompt to copy into
   another AI tool, and offline help for common error messages.
   ===================================================================== */
(function () {
  'use strict';
  const MG = window.MG;
  const { h, esc, bus, toast, store } = MG;
  const CFG = MG.config || {};
  const KEY_NAME = (CFG.storePrefix || 'biowb') + '-ai-key';
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const HOME = () => (MG.app && MG.app.HOME) || '/home/user';
  const pretty = (p) => (MG.app && MG.app.fs ? MG.app.fs.pretty(p) : p);
  const TAB_NAMES = { notebook: 'Notebook', terminal: 'Terminal', editor: 'Files', galaxy: 'Galaxy', apis: 'Databases', viewer: '3D viewer', igv: 'Genome browser', networks: 'Networks', assistant: 'AI assistant' };
  const stamp = () => {
    const d = new Date(), p = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}`;
  };
  const quote = (t) => String(t || '').trim().split('\n').map((l) => '> ' + l).join('\n');

  /* ------------------------------------------------------------------
     answers: Markdown → HTML (marked), cleaned (DOMPurify). A model's answer can contain anything, so no
     scripts, forms, styles or pictures get through (a picture would be fetched at once, from any address).
     Code blocks become boxes with buttons (codeBox).
     ------------------------------------------------------------------ */
  const CLEAN = { FORBID_TAGS: ['style', 'form', 'input', 'button', 'textarea', 'select', 'iframe', 'script', 'img', 'picture', 'video', 'audio', 'source', 'object', 'embed', 'svg', 'math', 'link', 'meta', 'base'], FORBID_ATTR: ['style', 'srcset'] };
  const clean = (html) => (window.DOMPurify ? window.DOMPurify.sanitize(html, CLEAN) : '<p>' + esc(html) + '</p>');
  /** a code fence's file name: ```python scripts/plot.py  (or title="plot.py") */
  function fenceFile(words) {
    return (
      words
        .map((x) => x.replace(/^(title|file|filename|path)=/i, '').replace(/^["']|["']$/g, ''))
        .find((x) => /^[\w.~/+-]+$/.test(x) && (/\.\w{1,8}$/.test(x) || x.includes('/')) && !/^\d/.test(x)) || null
    );
  }
  /** Markdown → [{html} | {code, lang, file}] */
  function mdBlocks(md) {
    const src = String(md || '');
    const M = window.marked;
    if (!M || !M.lexer || !M.parser) return [{ html: '<p>' + esc(src).replace(/\n/g, '<br>') + '</p>' }];
    let toks;
    try {
      toks = M.lexer(src, { gfm: true });
    } catch (e) {
      return [{ html: '<pre>' + esc(src) + '</pre>' }];
    }
    const out = [];
    let run = [];
    const flush = () => {
      if (!run.length) return;
      run.links = toks.links || {};
      let html;
      try {
        html = M.parser(run, { gfm: true });
      } catch (e) {
        html = '<p>' + esc(run.map((t) => t.raw || '').join('')) + '</p>';
      }
      out.push({ html: clean(html) });
      run = [];
    };
    for (const t of toks) {
      if (t.type === 'code') {
        flush();
        const info = String(t.lang || '').trim().split(/\s+/).filter(Boolean);
        out.push({ code: t.text, lang: (info[0] || '').toLowerCase(), file: fenceFile(info.slice(1)) });
      } else run.push(t);
    }
    flush();
    return out;
  }

  /* the languages of code blocks */
  const PY = /^(python|py|python3|ipython|ipython3|pycon|jupyter)$/;
  const RL = /^(r|rscript|splus|rconsole)$/;
  const SH = /^(bash|sh|shell|console|zsh|shell-session|sh-session|shellscript|terminal|cmd|command)$/;
  const PLAIN = /^(text|txt|plaintext|output|log|stdout|stderr|none)$/;
  const EXT = { python: '.py', r: '.R', bash: '.sh', yaml: '.yaml', yml: '.yaml', json: '.json', csv: '.csv', tsv: '.tsv', fasta: '.fasta', fa: '.fa', fastq: '.fastq', snakemake: 'Snakefile', smk: 'Snakefile', nextflow: '.nf', markdown: '.md', md: '.md', html: '.html', sql: '.sql', javascript: '.js', js: '.js', vcf: '.vcf', bed: '.bed', gff: '.gff3', gff3: '.gff3', gtf: '.gtf', newick: '.nwk', nwk: '.nwk', dot: '.dot', graphviz: '.dot', toml: '.toml', ini: '.ini', xml: '.xml', sam: '.sam', awk: '.awk', sed: '.sed' };
  /** commands typed after a prompt ("$ samtools …") – the rest of such a block is what they printed */
  function shellCode(code) {
    const lines = String(code).replace(/\r/g, '').split('\n');
    const prompted = lines.filter((l) => /^\s*\$\s/.test(l));
    return prompted.length ? prompted.map((l) => l.replace(/^\s*\$\s+/, '')).join('\n') : code;
  }
  /** the commands of a block, one by one (lines that belong together – a loop, a here-document – are one) */
  function shellCommands(code) {
    const SL = MG.shellLang;
    const cmds = [];
    let acc = null;
    for (const line of String(code).replace(/\r/g, '').replace(/\n+$/, '').split('\n')) {
      if (acc == null && (!line.trim() || /^\s*#/.test(line))) continue;
      acc = acc == null ? line : acc + '\n' + line;
      let more = false;
      try {
        more = !!(SL && SL.incomplete && SL.incomplete(acc));
      } catch (e) {
        more = false;
      }
      if (!more) {
        cmds.push(acc);
        acc = null;
      }
    }
    if (acc != null) cmds.push(acc);
    return cmds;
  }
  const knownCommand = (n) => !!((MG.shellTools && MG.shellTools[n]) || (MG.shellBuiltins && MG.shellBuiltins[n]) || (MG.shellLang && MG.shellLang.isShellWord && MG.shellLang.isShellWord(n)));
  /** an unlabelled code block that is terminal commands: its first word is a command of the terminal */
  function looksShell(code) {
    const first = String(code).split('\n').find((l) => l.trim() && !/^\s*#/.test(l)) || '';
    const w = first.trim().replace(/^\$\s+/, '').split(/\s+/)[0] || '';
    return knownCommand(w) && !/^(import|from|library|print|def|for|if|while)$/.test(w);
  }
  /* commands that delete or move files: asked about before they run */
  const RISKY = /(^|[\s;&|(`])(rm|rmdir|mv|shred|truncate)(\s|$)|\s-delete\b|>\s*\/home|>\s*~\//m;
  function confirmBox(title, html, ok) {
    return new Promise((resolve) => {
      let done = false;
      const end = (v) => {
        if (done) return;
        done = true;
        m.close();
        resolve(v);
      };
      const m = MG.modal(title, html + `<div class="prompt-actions"><button class="btn" data-x="no" type="button">Cancel</button><button class="btn primary" data-x="yes" type="button">${esc(ok || 'OK')}</button></div>`, { onClose: () => end(false) });
      m.box.querySelector('[data-x="no"]').addEventListener('click', () => end(false));
      m.box.querySelector('[data-x="yes"]').addEventListener('click', () => end(true));
    });
  }

  /* ------------------------------------------------------------------
     what the model is told about the workbench
     ------------------------------------------------------------------ */
  const EXAMPLES =
    'reads/NA12878_R1.fastq and reads/NA12878_R2.fastq (3,519 pairs of 76-base Illumina exome reads of the public sample NA12878, from two regions of chr10), reads/reference.fa and reference.fa.fai (two slices of GRCh37 chr10, named human_CYP2C19 and human_CYP2C9), variants/NA12878.calls.vcf.gz and .tbi (bcftools calls from those reads), annotation/cyp2c_slices.gff3 and cyp2c_exons.bed (genes and exons, in the coordinates of the slices), sequences/pBR322.fasta, sequences/myoglobins.fasta (myoglobin proteins of eight animals) and unknown_myoglobin.fasta, sequences/tRNA-Thr.afa (six aligned human tRNAs), tables/yeast_genes.csv (5,481 yeast genes; columns orf, gene, essential, protein_length, gc_content, codon_bias, protein_abundance, interaction_partners, transmembrane_helices, human_homolog, paralog_identity, plddt, disorder, conditional_mutant_phenotypes, location, chromosome, uniprot, alphafold_id, description), structures/1mbn.pdb (sperm whale myoglobin), rnaseq/yeast_chrI.fa and .fai (chromosome I of S. cerevisiae R64-1-1, sequence named I), rnaseq/yeast_chrI.gtf (its genes, Ensembl), rnaseq/yeast_chrI.splice_sites.tsv (5 annotated introns, for hisat2 --known-splicesite-infile), rnaseq/SRR6357070_1.fastq and _2.fastq (256 pairs of 101-base yeast RNA-seq reads), rnaseq/airway_counts.tsv (gene counts: gene_id then 8 samples, 63,677 Ensembl genes, airway smooth muscle cells with and without dexamethasone) and rnaseq/airway_samples.tsv (sample_id, cell, dex = untrt/trt …; design ~ cell + dex for DESeq2), trimming/SRR6357070_adapters_1.fastq and _2.fastq (384 pairs of the same yeast run, chosen for adapters: read 1 adapter AGATCGGAAGAGCACACGTCTGAACTCCAGTCA, read 2 AGATCGGAAGAGCGTCGTGTAGGGAAAGAGTGT), somatic/tumor.bam and somatic/normal.bam with .bai (real reads of the breast-cancer cell line HCC1395 and its matched normal HCC1395BL, SEQC2; two windows of GRCh38 chr21 renamed chr21_10572001_10582000 and chr21_21404501_21423500, so local position + 10572000 or + 21404500 gives the chr21 position), somatic/reference.fa and .fai (those two windows), somatic/regions.bed and regions.bed.gz with .tbi (the windows less 2 kb at each end), somatic/truth.vcf (the 4 SEQC2 high-confidence somatic variants there: 2 SNVs, 2 deletions; the SNV at chr21_21404501_21423500:14045 has no alternate reads in this replicate), metagenomics/reads_1.fastq.gz and reads_2.fastq.gz (4,096 pairs of 151-base Illumina reads of the ZymoBIOMICS mock community – 8 bacteria, 2 yeasts; ENA ERR2984773), metagenomics/db/ (a small Kraken2 database: hash.k2d, opts.k2d, taxo.k2d built from the first 1 Mb of E. coli, Salmonella enterica and Shigella flexneri chromosomes – library/reference.fna, seqid2taxid.map, taxonomy/ – and database151mers.kmer_distrib for Bracken with -r 151; about 94% of the reads stay unclassified, as most of the community is not in it), bacteria/ecoli.fna and salmonella.fna (the first 60,000 bases of the chromosomes of E. coli K-12 MG1655 and Salmonella Typhimurium LT2, for prodigal; combined.fna: both, for -p meta), hmmer/ (the tutorial data of the HMMER 3.4 User\'s Guide, unchanged: globins4.sto and globins4.hmm (four globins), fn3.sto/fn3.hmm and Pkinase.sto/Pkinase.hmm (Pfam\'s fibronectin type III and protein kinase domains), MADE1.sto/MADE1.hmm (a human DNA transposon, Dfam, for nhmmer), globins45.fa (45 globins), HBB_HUMAN (one, FASTA), 7LESS_DROME (the Drosophila Sevenless receptor, a UniProt text record: 9 fn3 domains and a kinase domain) and dna_target.fa (330 kb of human chromosome 1 with MADE1 copies); the tutorial makes minifam from globins4.hmm, fn3.hmm and Pkinase.hmm for hmmscan), singlecell/ (BUS records of a mouse 10x Chromium v2 experiment, SRR8599150, from kallisto bus: input.bus with matrix.ec, transcripts.txt, transcripts-to-genes.txt and whitelist.txt (the cell barcodes near the observed ones); R1.fastq and R2.fastq (2,500 of its read pairs: R1 holds the 16-base barcode and 10-base UMI); large/: 10,235 records of 358 barcodes, already corrected and sorted, with their own matrix.ec, transcripts.txt, transcripts-to-genes.txt and whitelist.txt).';
  /** the programs of the terminal, with their versions */
  function programs() {
    const T = MG.shellTools || {};
    const v = (n) => (T[n] && T[n].version) || '';
    const one = (n, label) => (T[n] ? `${label || n} ${v(n)}`.trim() : null);
    const W = MG.exec.versions;
    return [
      one('fastp'), one('seqtk'), one('minimap2'), T.bowtie2 ? `bowtie2 ${v('bowtie2')} (with bowtie2-build)` : null, T.bwa ? `bwa ${v('bwa')} (bwa index, bwa mem)` : null, T['bwa-mem2'] ? `bwa-mem2 ${v('bwa-mem2')} (its own index: bwa-mem2 index)` : null, T.hisat2 ? `hisat2 ${v('hisat2')} (spliced RNA-seq alignment; with hisat2-build and hisat2-inspect; reads .gz files)` : null, one('samtools'), one('bcftools'), one('freebayes'), T.bgzip ? `bgzip and tabix (htslib ${v('bgzip')})` : null, one('bedtools'),
      one('mosdepth'), T.featureCounts ? `featureCounts ${v('featureCounts')} (Subread; paired reads need -p --countReadPairs; up to 4 threads, -T)` : null, T.stringtie ? `stringtie ${v('stringtie')} (needs a sorted BAM; hisat2 --dta)` : null, T.kallisto ? `kallisto ${v('kallisto')} (index, quant; writes abundance.tsv, no .h5)` : null, T.salmon ? `salmon ${v('salmon')} (index, quant; the Rust Salmon)` : null,
      T.cutadapt ? `cutadapt ${v('cutadapt')} (adapter and quality trimming; one core; a few seconds to start)` : null, T.macs3 ? `macs3 ${v('macs3')} (MACS3: callpeak -t CHIP -c CONTROL -f BED|BAM|BAMPE|BEDPE -g hs|NUMBER -n NAME --outdir DIR [-B], hmmratac for ATAC-seq, bdgcmp and its other commands; one process; a few seconds to start)` : null, T.lofreq ? `lofreq ${v('lofreq')} (call, indelqual, filter, somatic – lofreq somatic runs its steps one after another, --threads 1; not call-parallel)` : null, T['bam-somaticsniper'] ? `bam-somaticsniper ${v('bam-somaticsniper')} (SomaticSniper: tumour BAM, normal BAM, output file; -F vcf)` : null, T['configureStrelkaSomaticWorkflow.py'] ? `Strelka2 ${v('configureStrelkaSomaticWorkflow.py')} somatic (configureStrelkaSomaticWorkflow.py --normalBam N --tumorBam T --referenceFasta REF --runDir DIR, then DIR/runWorkflow.py -m local -j 1; results in DIR/results/variants/)` : null, T.kraken2 ? `kraken2 ${v('kraken2')} (kraken2 --db DB --paired --report R.report --output R.kraken R1.fq.gz R2.fq.gz; kraken2-inspect, kraken2-build --build; one thread; the database must be small)` : null, T.bracken ? `bracken ${v('bracken')} (bracken -d DB -i R.report -o R.bracken -r READLEN -l S -t 10; bracken-build -d DB -l READLEN; a few seconds to start)` : null, T.prodigal ? `prodigal ${v('prodigal')} (prodigal -i genome.fna -o genes.gff -f gff -a proteins.faa -d genes.ffn; -p meta for metagenomes; plain FASTA, not .gz)` : null, T.hmmsearch ? `HMMER ${v('hmmsearch')} (hmmbuild, hmmsearch, hmmscan – after hmmpress –, hmmpress, hmmfetch, hmmalign, hmmconvert, hmmemit, hmmstat, phmmer, jackhmmer, nhmmer, nhmmscan; one thread, no --cpu; no .gz files; no esl- miniapps)` : null, T.bustools ? `bustools ${v('bustools')} (sort, correct -w LIST, count --genecounts -g T2G -e matrix.ec -t transcripts.txt -o DIR/PREFIX, inspect, text, capture, allowlist …; one thread, sort -m 1G at most)` : null, T.plink2 ? `plink2 ${v('plink2')} (PLINK 2: --vcf FILE, --pfile PREFIX, --bfile PREFIX; --make-pgen, --freq, --missing, --hardy, --het, --maf/--geno/--hwe filters, --indep-pairwise, --r2-unphased, --make-king-table, --glm, --score, --export vcf; files named --out PREFIX; the terminal adds --threads 1 --memory 640 require; no --pca or --pheno-svd in this build, no --script)` : null,
      one('wgsim'), one('gffread'), one('kalign'), one('muscle'), one('fasttree'), T.needleman_wunsch ? 'needleman_wunsch and smith_waterman (seq-align)' : null, one('lastz'), one('jq'),
      `GNU coreutils ${W.coreutils || ''}, grep ${W.grep || ''}, sed ${W.sed || ''}, gawk ${W.gawk || ''}, diff`.replace(/ ,/g, ','),
      'python, pip, Rscript, snakemake (Snakemake 9, a browser edition), dot (Graphviz), curl, wget, unzip, zip, tar, gzip'
    ]
      .filter(Boolean)
      .join(', ');
  }
  function versions() {
    const peek = (l) => (MG.kernels && MG.kernels.peek ? MG.kernels.peek(l) : null);
    const P = (peek('python') || {}).versions || {}, R = (peek('r') || {}).versions || {};
    return {
      python: P.python || '3.13',
      pyodide: P.pyodide || ((CFG.pyodideBase || '').match(/v(\d+\.\d+(\.\d+)?)/) || [])[1] || '0.29',
      r: R.r || '4.6',
      webr: R.webr || ((CFG.webrBase || '').match(/v(\d+\.\d+(\.\d+)?)/) || [])[1] || '0.6'
    };
  }
  /** the environment, for the chat (web: true) and for the agent (web: whether it may use the internet) */
  function envLines(opts = {}) {
    const v = versions();
    const web = opts.agent
      ? opts.web
        ? '- The internet: curl, wget and Python (requests) can reach web services that allow requests from web pages – Ensembl REST, UniProt, NCBI E-utilities, EBI (InterPro, ENA, Europe PMC, QuickGO), RCSB PDB, AlphaFold DB, STRING, Reactome – but not KEGG.'
        : '- No internet: curl and wget are not available to you, and your Python and R code must not use the network.'
      : '- The internet: Python (requests), R and the terminal (curl, wget) can reach web services that allow requests from web pages – Ensembl REST, UniProt, NCBI E-utilities, EBI (InterPro, ENA, Europe PMC, QuickGO, BLAST through Job Dispatcher), RCSB PDB, AlphaFold DB, STRING, Reactome – but not KEGG, or NCBI BLAST through its URL API.';
    return [
      `- Terminal: a bash-like shell (pipes, redirection, variables, $( ), loops, functions, here-documents; no background jobs, sudo, apt, conda installs or docker). Programs – the real ones, compiled to WebAssembly, each running on one thread (featureCounts, Salmon and PLINK 2 on several, in a cross-origin isolated page); there is no Python 2: ${programs()}.`,
      `- Python ${v.python} (Pyodide ${v.pyodide}) with numpy, pandas and matplotlib; more with %pip install NAME in a notebook (pip install NAME in the terminal): pure-Python packages from PyPI and the packages built for Pyodide – biopython (import Bio), scipy, scikit-learn, statsmodels, seaborn and others. No threads or subprocesses. In the terminal: python script.py, python -c "…".`,
      `- R ${v.r} (webR ${v.webr}): library(NAME) installs a package the first time it is used, if a build for webR exists (ggplot2, dplyr, tidyr, readr … from CRAN; Bioconductor packages of the current release from r-universe where they are built for webR – DESeq2, edgeR, limma, Biostrings, GenomicRanges among them). In the terminal: Rscript script.R, Rscript -e '…' (plots go to Rplots.pdf unless the script opens png()).`,
      `- Files: the user's own files are in ~ (= ${HOME()}), kept in the browser and shared by the notebooks, the terminal and the Files tab. A notebook's code runs in the notebook's folder (~/notebooks for most). Read-only example data is in /data/examples: ${EXAMPLES}`,
      web
    ];
  }

  /* ------------------------------------------------------------------
     offline help (no model connected): what common error messages mean
     ------------------------------------------------------------------ */
  const SHELL_HELP = [
    [/command not found/, 'The terminal has no program of that name. Check the spelling – `help` lists the programs that are here. A script runs with `bash script.sh`, a Python or R script with `python script.py` or `Rscript script.R`.'],
    [/No such file or directory|cannot open|[Cc]ould not open|[Ff]ailed to open|not found: /, 'A file or folder in the command is not where the command looked. Check the folder you are in (`pwd`) and what is there (`ls`); a path without a leading `/` or `~` starts from the current folder. The example data is in `/data/examples` (`ls -R /data/examples`).'],
    [/Read-only file system|read-only|Permission denied/i, 'That file cannot be changed: the example data in `/data/examples` is read-only. Copy what you need into your own folder first (`cp -r /data/examples/reads ~/example-reads`) and work on the copy.'],
    [/unrecognized option|unrecognised option|invalid option|unknown option|illegal option|unknown argument/i, 'The program does not have that option (in this version). Check its real options with `PROGRAM --help` or `man PROGRAM` – AI tools often invent options that sound right.'],
    [/syntax error|unexpected token|unexpected EOF|unexpected end of file/i, 'The shell could not read the command: look for an unmatched quote or bracket, a `do` without `done` or an `if` without `fi`. Characters such as `(`, `)`, `;`, `&`, `|`, `<` and `>` must be quoted when they are part of a name.'],
    [/Is a directory/, 'The command expected a file but got a folder. Give the path of a file in it, or use the option for folders (`cp -r`, `rm -r`).'],
    [/does not allow downloads from a web page|CORS|could not get /i, 'The web server did not answer, or does not allow requests from a web page (CORS). The workbench runs in your browser, so it can only reach services that allow that – Ensembl REST, UniProt, NCBI E-utilities, EBI, RCSB PDB and others (see the Databases tab). Check the address, or download the file with your browser and upload it in the Files tab.'],
    [/out of memory|Cannot enlarge memory|memory access out of bounds|Array buffer allocation failed|Invalid typed array length/i, 'The program ran out of memory: programs here run inside the browser, which gives each of them a few gigabytes at most. Work on a smaller file (`seqtk sample`, `head -n 400000 reads.fastq > small.fastq`) or on one region at a time.'],
    [/truncated file|EOF marker is absent|invalid BGZF|not compressed with bgzip|fail to read the header/i, 'The program could not read an input file: check that it is complete and in the format the program expects (`head FILE`, `file FILE`). A `.gz` file that is to be indexed must be compressed with `bgzip`, not `gzip`.'],
    [/stopped by force|Stop requested/i, 'The command was stopped before it finished, so its output files may be missing or incomplete: run it again – on a smaller input if it takes too long.']
  ];
  const R_HELP = [
    [/could not find function/, 'R does not know that function: load its package first (`library(dplyr)`), or check the spelling – names are case-sensitive.'],
    [/object '.*' not found/, 'R does not know that name: it is misspelt (names are case-sensitive), or it was made in a cell that has not been run since R started. A column name works on its own only inside functions such as `aes()` or `filter()`, with the data given.'],
    [/there is no package called/, 'That package is not available here: `library()` installs packages that are built for webR (R in the browser) the first time they are used, and this one has no such build. Look for another package that does the same, or do this step in Python.'],
    [/cannot open (file|the connection)|No such file or directory/, 'The file is not where R looked. A notebook\'s code runs in the notebook\'s folder (`getwd()` shows it): give the path from there, a path from your home folder (`"~/data/x.csv"`) or the full path (`"/data/examples/tables/yeast_genes.csv"`).'],
    [/unexpected (symbol|string constant|numeric constant|'\)'|'\}'|','|'='|input|end of input)/, 'R could not read the code: look for a missing or extra bracket, comma, quote or operator on that line, or on the line before.'],
    [/non-numeric argument to (binary operator|mathematical function)/, 'A calculation got text instead of numbers – often a column that was read as text. Look at it with `str(df)`, and convert it with `as.numeric()`.'],
    [/arguments imply differing number of rows|replacement has \d+ rows?, data has/, 'The vectors or columns have different lengths, so they cannot form one table.'],
    [/subscript out of bounds|undefined columns selected/, 'A row, column or list element that does not exist was asked for. Check the names with `names(df)` and the size with `dim(df)`.']
  ];
  const PY_HELP = {
    NameError: 'Python does not know that name: it is misspelt (names are case-sensitive), or it was made in a cell that has not been run since Python started. After a restart, run the cells again from the top (Run all).',
    SyntaxError: 'Python could not read the code: look for a missing bracket, quote, comma or colon on the line shown – or just above it.',
    IndentationError: 'Python groups lines by their indentation: the lines inside `for`, `if`, `def` or `with` must all be indented the same (4 spaces).',
    KeyError: 'That key is not in the dictionary – or that column is not in the table. Keys are case-sensitive: print the dictionary, or `df.columns`, to see what is there.',
    IndexError: 'An index is out of range: a list of 3 items has positions 0, 1 and 2.',
    TypeError: 'A value of the wrong type was used – for example a number added to a string (`"NA" + 1`), or something called that is not a function.',
    FileNotFoundError: 'The file is not where Python looked. A notebook\'s code runs in the notebook\'s folder (`import os; os.getcwd()` shows it): give the path from there, or the full path (`/data/examples/tables/yeast_genes.csv`, `/home/user/…`).',
    ModuleNotFoundError: 'That package is not installed yet. Install it with `%pip install NAME` in a cell – for Biopython `%pip install biopython`, then `import Bio`. Packages that need compiled code that was not built for the browser cannot be installed.',
    ImportError: 'The package is there, but that name is not in it (or not in this version): check the spelling and the package\'s documentation.',
    AttributeError: 'The object has no attribute or method of that name – often a typo, or a method of another kind of object (`type(x)` shows what it is).',
    ValueError: 'The value has the right type but cannot be used – for example `int("NA12878")`, or two lists of different lengths.',
    ZeroDivisionError: 'Something was divided by zero.',
    PermissionError: 'That file cannot be written: the example data in /data/examples is read-only. Save results in your own folders.',
    MemoryError: 'Python ran out of memory: the browser gives it a few gigabytes at most. Work on part of the data.'
  };
  function offlineHelp(text, lang) {
    const rules = lang === 'r' ? R_HELP.concat(SHELL_HELP) : SHELL_HELP;
    const hits = rules.filter(([re]) => re.test(text)).map(([, t]) => t);
    return hits.length ? hits.slice(0, 2).map((t) => '- ' + t).join('\n') : null;
  }

  /* ------------------------------------------------------------------
     the services and their models
     ------------------------------------------------------------------ */
  const LIVE_DEFAULTS = {
    provider: CFG.liveProvider || 'gemini',
    model: CFG.anthropicModel || 'claude-sonnet-5-5',
    geminiModel: CFG.geminiModel || 'gemini-3.8-flash',
    baseURL: 'https://api.openai.com/v1',
    openaiModel: '',
    agentWeb: false
  };
  /* the model of each service; an empty model in the saved settings means the site's default
     from config.js, so a model changed there (e.g. when one is retired) reaches every user
     who has not chosen a model of their own */
  const geminiModelOf = (s) => (s.geminiModel || LIVE_DEFAULTS.geminiModel).trim().replace(/^models\//, '');
  const anthropicModelOf = (s) => (s.model || LIVE_DEFAULTS.model).trim();
  const modelOf = (s) => (s.provider === 'gemini' ? geminiModelOf(s) : s.provider === 'anthropic' ? anthropicModelOf(s) : s.openaiModel || 'model');
  /** Gemini and Anthropic always need a key; an OpenAI-compatible server (e.g. a local one) may not */
  const needsKey = (s) => s.provider !== 'openai';
  /* A Gemini model can be busy (HTTP 503 "high demand"), give no answer at all, or be over one
     of its limits (429) – on the free tier each model has limits of its own, per minute and per
     day. Then the next model of this list is asked; the answer says which one replied.
     The page remembers what a model said, and does not ask it again before that can have
     changed: a busy model after two minutes (then four, eight … if it is busy again), a silent
     one after one minute, a model over a limit when the service says the limit is over (a limit
     per day: not before tomorrow), a model that was not found not at all. That saves time –
     "busy" can take twenty seconds to arrive – and requests, of which the free tier allows few.
     The memory belongs to one key – another key is another project, with limits of its own –
     and lasts until the page is loaded again. */
  const FALLBACK_DEFAULT = ['gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-flash-lite'];
  const FALLBACKS = (Array.isArray(CFG.geminiFallbackModels) ? CFG.geminiFallbackModels : FALLBACK_DEFAULT).map((m) => String(m).trim().replace(/^models\//, '')).filter(Boolean);
  const BUSY = [500, 502, 503, 504, 529];
  const BUSY_REST = 120, SILENT_REST = 60; // seconds
  const RETRY = 20; // seconds after which it is worth asking busy or silent models again
  /* how long a Gemini model may say nothing – before its answer begins, or in the middle of it – until the request is given up */
  const WAIT = () => (+CFG.aiWaitSeconds > 0 ? Math.max(1, +CFG.aiWaitSeconds) : 60);
  const REST = new Map(); // model → { model, why: 'busy' | 'noanswer' | 'limit' | 'notfound', at, until (ms), daily, limit, n, status, text }
  let restKey = null;
  const resting = (model) => {
    const r = REST.get(model);
    return r && r.until > Date.now() ? r : null;
  };
  const hhmm = (ms) => new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  /** what kept a model from answering: in a word or two (under an answer, in the bar) … */
  const skipWord = (x) => (x.why === 'notfound' ? 'not found' : x.why === 'limit' ? (x.daily ? 'over its limit for today' : 'over its limit') : x.why === 'noanswer' ? 'gave no answer' : x.why === 'broke' ? 'broke off' : 'busy');
  /** … and as part of a sentence – with the numbers that the service gave, unless short */
  const told = (x, short) =>
    x.why === 'notfound'
      ? 'was not found'
      : x.why === 'limit'
        ? x.daily
          ? 'is over its limit for today' + (short ? '' : (x.limit != null ? `: ${x.limit} requests a day` : '') + (isFinite(x.until) ? `, again after ${hhmm(x.until)}` : ''))
          : 'is over its limit per minute'
        : x.why === 'noanswer'
          ? 'gave no answer'
          : 'is busy';
  /** the error when no Gemini model answered: what each one said. .status: 429 (limits), 503 (busy), 404, or not set
      (no answer came); .retryIn: after how many seconds asking again can help – 0 when it cannot today */
  function noAnswer(all, connection) {
    const some = (f) => all.some(f);
    const waits = all.filter((x) => x.why === 'limit' && !x.daily).map((x) => Math.min(90, Math.max(1, Math.ceil((x.until - Date.now()) / 1000))));
    if (some((x) => x.why === 'busy' || x.why === 'noanswer')) waits.push(RETRY);
    const retryIn = waits.length ? Math.min(...waits) : 0;
    // one model only (no fallback models): its own words
    if (all.length === 1) return Object.assign(new Error(all[0].text), { status: all[0].status, network: all[0].why === 'noanswer', retryIn });
    let status, lead;
    // (a model that answered within the last two minutes, if only with "busy" or "over its limit": the service can be reached)
    const heard = some((x) => x.status && Date.now() - x.at < 120000);
    if (connection || (some((x) => x.why === 'noanswer') && !some((x) => x.why === 'busy'))) lead = heard ? 'No answer came from the Gemini API, though it can be reached: try again in a moment.' : 'Could not reach the Gemini API: no answer came. Check the internet connection, and try again.';
    else if (some((x) => x.why === 'busy')) (status = 503), (lead = 'HTTP 503. Google’s servers are busy (“high demand”). That is on Google’s side, not a problem with your key: wait a minute and try again.');
    else if (waits.length) (status = 429), (lead = 'HTTP 429. Too many requests: the free tier allows only a few requests per minute – wait a minute and try again.');
    else if (some((x) => x.why === 'limit')) (status = 429), (lead = 'HTTP 429. No requests are left for today: every model that this page asks is over its limit for this key. The free tier allows each model a number of requests per day, counted per project. Go on when the service takes requests again, or use a key from another person or project.');
    else (status = 404), (lead = 'HTTP 404. None of the models was found – check the model in the AI settings (⚙).');
    return Object.assign(new Error(`${lead} (${all.map((x) => x.model + ' ' + told(x)).join('; ')}.)`), { status, network: !status, retryIn });
  }
  const stopped = () => new DOMException('Stopped', 'AbortError');

  /* ------------------------------------------------------------------
     the agent: what it may run, and where
     ------------------------------------------------------------------ */
  const AGENT_MAX = Math.max(5, +CFG.agentMaxSteps || 20); // steps per task
  const AGENT_OUT = 3000; // characters of each step's output that the model sees
  // a step of the agent that has not ended after this many seconds is stopped (config.js: agentCommandSeconds)
  const AGENT_SECONDS = Math.max(5, +CFG.agentCommandSeconds || 150);
  /* What the agent may not run: cd (each step starts in its folder, where programs put the files they make), and
     what would change the user's set-up or the shell itself. Commands that act on the user's screen refuse the
     agent themselves (open, nano, igv, network, download, export-session), and so do curl and wget unless it may use the
     internet (shell-wb.js). Everything else of the terminal is the agent's to use. */
  const AGENT_DENY = new Set(['cd', 'pushd', 'popd', 'exec', 'conda', 'mamba', 'micromamba']);
  const AGENT_ALLOW = { has: (n) => !AGENT_DENY.has(n) };
  /** why the agent may not run this text ('' if it may): a command in it that the agent has not got. The names are
      those that the shell itself reads in the text – also inside $( ), loops and pipes. Nothing of such a text is
      run. (A name that is only known when the text runs – "$tool", what xargs or find -exec starts – is checked
      when it runs: see dispatch in shell-wb.js.) */
  function agentRefusal(text) {
    let names;
    try {
      names = MG.shellLang.commandNames(text);
    } catch (e) {
      return ''; // (not readable as shell: nothing of it runs, and the terminal says why)
    }
    const bad = names.filter((c) => AGENT_DENY.has(c)).filter((c, i, a) => a.indexOf(c) === i);
    if (!bad.length) return '';
    if (bad.some((c) => /^(cd|pushd|popd)$/.test(c))) return 'cd is not available: every step starts in your folder. Use paths instead – relative to your folder, or ~/…, or /data/examples/….';
    return `${bad.map((b) => '`' + b + '`').join(', ')} ${bad.length > 1 ? 'are' : 'is'} not available to you.`;
  }
  const SHELL_FENCE = ['', 'bash', 'sh', 'shell', 'console', 'zsh', 'shell-session', 'shellscript', 'terminal', 'cmd', 'command'];
  /** The command in an agent's reply: its first shell code block, as it was written ('' = empty block, null = none).
      A model sometimes begins its command on the line of the fence itself (```bcftools view -H x.vcf | wc -l), also
      after the name of a shell (```bash samtools index x.bam) – a known command followed by more words; one word alone
      is the name of a language (```diff, ```awk). And sometimes the whole command stands between two fences on one line. */
  function agentStep(reply) {
    const re = /```([^\n`]*)(?:\n([\s\S]*?)```|```)/g;
    let m;
    while ((m = re.exec(reply))) {
      const info = m[1].trim(), words = info.split(/\s+/).filter(Boolean);
      const shell = SHELL_FENCE.includes((words[0] || '').toLowerCase());
      let first = '';
      if (m[2] === undefined) {
        // (one line between two fences: a command if it begins with one – after the name of a shell, or not)
        if (shell && words.length > 1 && knownCommand(words[1])) first = info.slice(words[0].length).trim();
        else if (words.length && knownCommand(words[0])) first = info;
        else continue;
        return { cmd: first, before: withoutCode(reply.slice(0, m.index)), after: withoutCode(reply.slice(re.lastIndex)) };
      }
      if (shell) {
        if (words.length > 1 && knownCommand(words[1])) first = info.slice(words[0].length).trim();
      } else if (words.length > 1 && knownCommand(words[0])) first = info;
      else continue;
      const body = m[2]
        .replace(/\r/g, '')
        .split('\n')
        .map((l) => l.replace(/^\s*\$\s+/, ''))
        .join('\n')
        .trim();
      // (before, after: what the reply says in front of the block of its command, and behind it)
      return { cmd: first ? first + (body ? '\n' + body : '') : body, before: withoutCode(reply.slice(0, m.index)), after: withoutCode(reply.slice(re.lastIndex)) };
    }
    return { cmd: null, before: '', after: '' };
  }
  /* A model sometimes goes on writing after the block of its command – its report, with what the command "showed",
     before the command has run. The reply is a step all the same; but what stands behind the block, when it is more
     than a remark, is not shown as the description of the step: the card says so, and the agent is told. */
  const AGENT_AHEAD = 120; // characters behind the block from which this holds
  const AGENT_AHEAD_TOLD = 'What you wrote after the code block was written before the command had run; it was not shown to the user. Send your report when you have read the output – without a code block.';
  // (what the agent is told, once in a task, when a reply has a code block that is no command)
  const AGENT_REMIND = 'Nothing was run: your reply had a code block, but not a ```bash block with a command. If you meant to run a command, send it again in a ```bash block. If that was your report, send it again without any code block.';
  /** the commands of a block, one by one (a loop or an if … fi is one command) */
  function agentParts(cmd) {
    try {
      const parts = MG.shellLang.statements(cmd, { extglob: MG.shellLang.extglobOn(MG.app.term.shell._top()) });
      return parts.length ? parts : [cmd];
    } catch (e) {
      return [cmd];
    }
  }
  const withoutCode = (reply) => reply.replace(/```[\s\S]*?(```|$)/g, '').trim();
  // (for the tests)
  MG.agentRules = { deny: AGENT_DENY, refusal: agentRefusal, step: agentStep, command: (r) => agentStep(r).cmd, parts: agentParts, seconds: AGENT_SECONDS, max: AGENT_MAX };
  const insideDir = (k, root) => k === root || k.startsWith(root + '/');
  // the agent's own folder, and /tmp, where the programs keep temporary files
  const agentMay = (k, root) => insideDir(k, root) || insideDir(k, '/tmp');
  /** every file entry outside the agent's folder, to put back what a command changed there */
  function outsideSnapshot(fs, root) {
    const m = new Map();
    for (const [k, v] of fs.entries) if (!agentMay(k, root)) m.set(k, v);
    return m;
  }
  /* A file that a program wrote (BAM, .gz …) has its bytes in the programs' memory only. Two copies are taken before
     a step of the agent runs:
     - of the files outside the agent's folder, the execution backend keeps one in that memory (keep) and writes it back after the
       step, where the step changed or removed the file (putBack);
     - of all such files – in the user's folders and in the agent's – the page holds one itself (holdBytes). If the
       programs have to be stopped by force (a command that does not end: the time limit, or Stop pressed twice),
       their memory is gone, and with it every file that a program wrote. Those that were there before the step are
       then written again from the page's copies: a forced stop costs the work of that step, and nothing else. */
  const AGENT_HOLD = 300 * 1024 * 1024; // bytes that the page holds at most (more than that: lost in a forced stop, and named)
  async function holdBytes(fs, held) {
    // (copies of files that are not there any more are let go)
    const live = new Set(fs.entries.values());
    for (const e of Array.from(held.keys())) if (!live.has(e)) held.delete(e);
    let total = 0;
    for (const b of held.values()) total += b.length;
    for (const [k, v] of Array.from(fs.entries)) {
      if (!MG.exec.holds(v) || held.has(v) || insideDir(k, '/tmp')) continue;
      if (total + (v.size || 0) > AGENT_HOLD) continue;
      try {
        const bytes = await fs.readBytes(k);
        held.set(v, bytes);
        total += bytes.length;
      } catch (e) {
        console.error(e);
      }
    }
  }
  /** After a step: what it changed outside the agent's folder is put back; after a forced stop of the programs, the
      files that programs had written before the step are written again.
      snap: the entries outside the folder before the step; keep: paths the user changed meanwhile (theirs);
      since, gen: when the step started, and MG.exec.gen then; held: see holdBytes; before: every program-written
      file before the step (path → entry).
      → { changed: paths outside that were put back or removed again, lost: paths whose bytes could not be had, killed } */
  async function undoOutside(fs, root, snap, keep, since, gen, held, before) {
    const W = MG.exec, changed = [], lost = [], back = [];
    const killed = !!W && W.gen !== gen;
    // 1. what the step made outside the folder goes
    for (const k of Array.from(fs.entries.keys())) {
      if (!agentMay(k, root) && !snap.has(k) && !keep.has(k)) {
        fs.entries.delete(k);
        changed.push(k);
      }
    }
    // 2. files that the step copied or moved, and that stay, get bytes of their own first
    if (W && W.ready && W.settle && !killed) {
      try {
        await W.settle(fs);
      } catch (e) {
        console.error(e);
      }
    }
    // 3. what was there before is put back
    for (const [k, v] of snap) {
      if (keep.has(k)) continue;
      const now = fs.entries.get(k);
      if (W.holds(v) && killed) {
        // (whatever is there now is not the user's file: it goes, and the file comes back below)
        if (now) {
          fs.entries.delete(k);
          changed.push(k);
        }
        continue;
      }
      if (now === v) continue;
      fs.entries.set(k, v);
      changed.push(k);
      if (!W.holds(v) || !W.putBack) continue;
      let ok = false;
      try {
        ok = await W.putBack(k, v, since);
      } catch (e) {
        console.error(e);
      }
      if (!ok) {
        fs.entries.delete(k);
        back.push([k, v]);
      }
    }
    // 4. After a forced stop: the files that programs had written before the step. Outside the folder: all of them.
    //    Inside it: those that were still there, unchanged, when the programs were stopped – a file that the step
    //    itself had removed or written anew stays gone.
    if (killed && before) {
      const atStop = W.lostEntries || new Map();
      for (const [k, v] of before) {
        if (keep.has(k) || fs.entries.has(k)) continue;
        if (agentMay(k, root) && atStop.get(k) !== v) continue;
        back.push([k, v]);
      }
    }
    for (const [k, v] of back) {
      const bytes = held ? held.get(v) : null;
      let ok = false;
      if (bytes && W && W.writeBytes) {
        try {
          fs.mkdirp(MG.path.dirname(k));
          await W.writeBytes(fs, k, bytes);
          fs.touch(k, v.mtime); // (the file has the time it had: Snakemake compares the times of files)
          ok = true;
        } catch (e) {
          console.error(e);
        }
      }
      if (!ok) lost.push(k);
    }
    changed.concat(lost).forEach((k) => fs._changed(k, !fs.entries.has(k) ? 'remove' : fs.entries.get(k).kind === 'dir' ? 'mkdir' : 'write'));
    return { changed, lost, killed };
  }
  /** a pause that the Stop button can cut short */
  const pause = (ms, signal) =>
    new Promise((resolve, reject) => {
      const t = setTimeout(resolve, ms);
      const stop = () => {
        clearTimeout(t);
        reject(new DOMException('Stopped', 'AbortError'));
      };
      if (signal && signal.aborted) stop();
      else if (signal) signal.addEventListener('abort', stop, { once: true });
    });

  /* ------------------------------------------------------------------
     the panel
     ------------------------------------------------------------------ */
  const CHAT_HELLO =
    'Ask me about your code, an error message, a program or a method. With your question I get the code of the open notebook, the names of your files and your last terminal commands – as you choose under the box – but never what is in your data files. Code in my answers goes into a notebook or the terminal with one click.\n\n**Check what I give you**: run it and look at the result – AI models make mistakes, and sound sure when they do. Never paste personal or patient data here.';
  const AGENT_HELLO =
    'Give me a whole task – for example *“Map the example reads to the reference, call the variants and tell me how many there are”* – and I will carry it out in the Terminal, one command at a time, in a folder of my own (`~/ai-agent/run-…`). You see every command and its output; **Stop** ends the task.\n\nI may read your files, but what I change outside my folder is undone. Further tasks continue in the same folder until you press **New**. Each run is kept as a notebook in its folder (`agent-record.ipynb`) – check my results there, not only my report.';
  const CHAT_STARTERS = ['How do I count the sequences in a FASTA file with Biopython?', 'What does the output of samtools flagstat tell me?', 'Plot protein length against abundance from /data/examples/tables/yeast_genes.csv with ggplot2', 'Which programs can I use in the terminal here?'];
  const agentTasks = () =>
    [
      'Map the reads in /data/examples/reads to reference.fa with minimap2, sort and index the BAM file, and report how many reads mapped',
      'Call the variants from those reads with bcftools and tell me how many SNPs and indels there are',
      MG.shellTools && MG.shellTools.kalign && MG.shellTools.fasttree ? 'Align the proteins in /data/examples/sequences/myoglobins.fasta and make a tree from the alignment' : null,
      'Which essential yeast genes in /data/examples/tables/yeast_genes.csv code for proteins longer than 1,500 amino acids? Write them to a CSV file'
    ].filter(Boolean);

  class Assistant {
    constructor(root, opts) {
      this.root = root;
      this.opts = opts || {};
      this.nb = this.opts.notebook || (MG.app && MG.app.nbApp);
      this.threads = {};
      this.msgs = { chat: [], agent: [] };
      this.busy = false;
      this.tab = 'chat';
      this.settings = Object.assign({}, LIVE_DEFAULTS, store.get('ai:settings', {}));
      this.ctxOpts = Object.assign({ nb: true, files: true, term: true, net: true }, store.get('ai:context', {}));
      try {
        this.key = window.sessionStorage.getItem(KEY_NAME) || '';
      } catch (e) {
        this.key = '';
      }
      this.agentCtx = null; // the agent's folder and record while the conversation goes on (New starts another)
      this._step = null; // while a step of the agent runs: what the user changes meanwhile (see _onFsChange)
      this._build();
      this.welcome('chat');
      this.welcome('agent');
      bus.on('nb:ask', (d) => this.askAboutCell(d));
      bus.on('term:ask', (d) => this.askAboutError(d));
      if (MG.app && MG.app.fs) MG.app.fs.onChange((p, what) => this._onFsChange(p, what));
    }
    /** may the agent use the internet (curl, wget)? – asked by shell-wb.js */
    get allowWeb() {
      return !!this.settings.agentWeb;
    }
    connected() {
      return !!this.key || !needsKey(this.settings);
    }
    /** the tab the user was in before the assistant's */
    lastBench() {
      const cur = MG.app && MG.app.currentBench;
      return (cur && cur !== 'assistant' ? cur : MG.app && MG.app.prevBench) || 'notebook';
    }

    _build() {
      const R = this.root;
      R.classList.add('ai');
      const tabs = h('div.ai-tabs', { role: 'tablist', 'aria-label': 'Chat or agent' });
      this.tabBtns = {};
      [
        ['chat', 'Chat', 'sparkle', 'Ask questions; code in the answers goes into a notebook or the terminal'],
        ['agent', 'Agent', 'robot', 'Give a task; the agent runs commands in the terminal, in a folder of its own']
      ].forEach(([k, label, ic, tip]) => {
        const b = h('button.ai-tab', { type: 'button', role: 'tab', title: tip, html: MG.icon(ic) + '<span>' + label + '</span>' });
        b.addEventListener('click', () => this.showTab(k));
        tabs.appendChild(b);
        this.tabBtns[k] = b;
      });
      this.modeEl = h('button.ai-mode', { type: 'button', title: 'The AI model – click to change it, or to add a key' });
      this.modeEl.addEventListener('click', () => this.settingsDialog());
      const newBtn = h('button.tbtn', { type: 'button', title: 'Start a new conversation (Agent: the next task works in a new folder)', html: MG.icon('reset') + '<span>New</span>' });
      newBtn.addEventListener('click', () => this.newConversation());
      const moreBtn = h('button.tbtn', { type: 'button', title: 'More', 'aria-label': 'More', html: MG.icon('dots') });
      moreBtn.addEventListener('click', () => this.moreMenu(moreBtn));
      const setBtn = h('button.tbtn', { type: 'button', title: 'AI settings: the service, the model and your key', 'aria-label': 'AI settings', html: MG.icon('gear') });
      setBtn.addEventListener('click', () => this.settingsDialog());
      const body = h('div.ai-threads');
      ['chat', 'agent'].forEach((k) => {
        const t = h('div.ai-thread', { role: 'log', 'aria-live': 'polite', dataset: { tab: k } });
        this.threads[k] = t;
        body.appendChild(t);
      });
      this.sugg = h('div.ai-sugg');
      this.ctxRow = h('div.ai-ctx');
      this.input = h('textarea.ai-input', { rows: 2, 'aria-label': 'Message to the AI assistant' });
      this.sendBtn = h('button.btn.primary.ai-send', { type: 'button', title: 'Send (Enter; Shift+Enter for a new line)', html: MG.icon('send') + '<span>Send</span>' });
      this.sendBtn.addEventListener('click', () => (this._abort ? this.stopNow() : this.send()));
      this.input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
          e.preventDefault();
          if (!this._abort) this.send();
        }
      });
      R.append(h('div.ai-bar', tabs, this.modeEl, h('span.grow'), newBtn, moreBtn, setBtn), body, h('div.ai-foot', this.sugg, h('div.ai-inrow', this.input, this.sendBtn), this.ctxRow));
      this.renderMode();
      this.showTab('chat', true);
    }
    showTab(k, quiet) {
      this.tab = k;
      Object.entries(this.tabBtns).forEach(([n, b]) => {
        b.classList.toggle('on', n === k);
        b.setAttribute('aria-selected', String(n === k));
      });
      Object.entries(this.threads).forEach(([n, t]) => (t.hidden = n !== k));
      this.root.classList.toggle('agent', k === 'agent');
      this.input.placeholder = k === 'agent' ? 'A task for the agent – e.g. “Map the example reads to the reference and call the variants”' : 'Ask about code, an error, a program or a method…';
      this.renderSuggestions();
      this.renderCtx();
      if (!quiet) bus.emit('ai:tab', { tab: k });
    }
    renderMode() {
      const on = this.connected();
      this.modeEl.classList.toggle('live', on);
      this.modeEl.innerHTML = on ? `<span class="kdot ok"></span> ${esc(modelOf(this.settings))}` : '<span class="kdot"></span> Not connected';
    }
    showStatus() {
      this.renderMode();
    }
    welcome(tab) {
      if (!this.connected()) return this.setupCard(tab);
      return this.addBubble('assistant', tab === 'agent' ? AGENT_HELLO : CHAT_HELLO, { intro: true, tab });
    }
    /** the buttons under a message when no model is connected */
    setupActs(prompt) {
      const go = h('button.btn.small.primary', { type: 'button', html: MG.icon('key') + '<span>Connect a model</span>' });
      go.addEventListener('click', () => this.settingsDialog());
      const cp = h('button.btn.small', { type: 'button', title: 'A prompt with your question and its context, to paste into an AI tool you are allowed to use', html: MG.icon('copy') + '<span>Copy a prompt for another AI tool</span>' });
      cp.addEventListener('click', () => this.copyPrompt(prompt && prompt.question, prompt && prompt.extra));
      return h('div.ai-setup-acts', go, cp);
    }
    setupCard(tab) {
      const b = this.addBubble(
        'assistant',
        [
          '**Connect an AI model to use the assistant.** It needs a key for an AI service – the workbench has none of its own.',
          '',
          '- **Google Gemini** has a free tier: make a key with a Google account at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) (you must be 18 or over). On the free tier Google may use what you send to improve its products.',
          '- Or a key for **Anthropic (Claude)**, or an **OpenAI-compatible** service – your own, or one you have been given.',
          '',
          'The key stays in this browser tab: it is never saved in a file, and it is sent only to the service you choose. Never paste personal or patient data into an AI tool.'
        ].join('\n'),
        { intro: true, tab }
      );
      b.classList.add('ai-setup');
      b.appendChild(this.setupActs());
      return b;
    }
    /** after the settings changed: the cards that ask for a key go, or come */
    refreshIntro() {
      ['chat', 'agent'].forEach((tab) => {
        const t = this.threads[tab];
        const on = this.connected();
        t.querySelectorAll('.ai-msg.ai-setup').forEach((x) => on && x.remove());
        if (on && !t.querySelector('.ai-msg.intro')) {
          if (!this.msgs[tab].length) t.innerHTML = '';
          this.welcome(tab);
        } else if (!on && !t.querySelector('.ai-setup')) this.setupCard(tab);
      });
    }
    renderSuggestions() {
      this.sugg.innerHTML = '';
      if (this.msgs[this.tab].length) return; // (only before the first question)
      const list = this.tab === 'agent' ? agentTasks() : CHAT_STARTERS;
      this.sugg.appendChild(h('span.muted.small', this.tab === 'agent' ? 'Try a task:' : 'Try:'));
      list.forEach((p) => {
        const b = h('button.chip', { type: 'button', title: 'Put this in the box – change it if you like, then press Enter' }, p);
        b.addEventListener('click', () => {
          this.input.value = p;
          this.input.focus();
        });
        this.sugg.appendChild(b);
      });
    }
    renderCtx() {
      const R = this.ctxRow;
      R.innerHTML = '';
      if (this.tab === 'agent') {
        const c = this.agentCtx;
        const fs = MG.app.fs;
        R.appendChild(
          h('span', {
            html:
              c && fs.isDir(c.run)
                ? `The next task continues in <code>${esc(pretty(c.run))}</code> – <b>New</b> starts a new folder.`
                : 'The agent works in a new folder, <code>~/ai-agent/run-…</code>. It sends what it reads and what its commands print to the AI service.' + (this.allowWeb ? ' It may use the internet.' : '')
          })
        );
        return;
      }
      R.appendChild(h('span', 'With your question, send:'));
      const cb = (k, label, tip) => {
        const i = h('input', { type: 'checkbox' });
        i.checked = !!this.ctxOpts[k];
        i.addEventListener('change', () => {
          this.ctxOpts[k] = i.checked;
          store.set('ai:context', this.ctxOpts);
        });
        return h('label', { title: tip }, i, ' ' + label);
      };
      R.append(
        cb('nb', 'the open notebook’s code', 'The code cells of the notebook that is open in the Notebook tab – not their outputs, and not your data'),
        cb('files', 'your file names', 'The names and sizes of the files in your home folder – not what is in them'),
        cb('term', 'your last commands', 'When you come from the Terminal: your last three commands and the end of what they printed'),
        cb('net', 'the open network', 'When you come from the Networks tab: the name, size and columns of the network that is open, its best-connected nodes, what is selected and the latest results')
      );
    }
    newConversation() {
      if (this.busy) return toast('The assistant is busy – press Stop first.', 'warn');
      const tab = this.tab;
      this.msgs[tab] = [];
      this.threads[tab].innerHTML = '';
      if (tab === 'agent') this.agentCtx = null;
      this.welcome(tab);
      this.renderSuggestions();
      this.renderCtx();
    }
    moreMenu(anchor) {
      MG.popmenu(
        anchor,
        [
          ['copy', 'Copy a prompt for another AI tool', () => this.copyPrompt()],
          ['download', 'Download this conversation (Markdown)', () => this.downloadConversation()],
          this.agentCtx && MG.app.fs.isDir(this.agentCtx.run) ? ['folder', 'Show the agent’s folder in Files', () => MG.app.revealFile(this.agentCtx.run)] : null,
          ['gear', 'AI settings', () => this.settingsDialog()]
        ].filter(Boolean)
      );
    }
    downloadConversation() {
      const tab = this.tab;
      const list = this.msgs[tab];
      if (!list.length) return toast('Nothing to save yet.', 'warn');
      const lines = [`# AI assistant – ${tab === 'agent' ? 'agent tasks' : 'chat'}`, '', `Bioinformatics workbench · ${new Date().toLocaleString('en-GB')} · ${modelOf(this.settings)}`, ''];
      if (tab === 'agent' && this.agentCtx) lines.push(`The agent's commands and their output are in \`${pretty(this.agentCtx.run)}/agent-record.ipynb\`.`, '');
      for (const m of list) lines.push(m.role === 'user' ? '## You' : '## AI', '', m.content, '');
      MG.downloadText(lines.join('\n'), `ai-${tab}-${stamp()}.md`, 'text/markdown');
    }

    /* ---------------- messages ---------------- */
    addBubble(role, md, meta = {}) {
      const tab = meta.tab || this.tab;
      const b = h('div.ai-msg.' + role + (meta.intro ? '.intro' : ''));
      const body = h('div.ai-body');
      if (role === 'user') body.textContent = md;
      else this.fill(body, md);
      b.appendChild(body);
      if (meta.badge) b.appendChild(h('div.ai-badge', { html: meta.badge }));
      this.threads[tab].appendChild(b);
      this.scroll(tab, true);
      return b;
    }
    /** to the end of the conversation – while an answer streams in, only if the user has not scrolled up to read */
    scroll(tab, force) {
      const t = this.threads[tab || this.tab];
      if (force || t.scrollHeight - t.scrollTop - t.clientHeight < 140) t.scrollTop = t.scrollHeight;
    }
    fill(body, md) {
      body.innerHTML = '';
      for (const blk of mdBlocks(md)) {
        if (blk.html != null) body.insertAdjacentHTML('beforeend', blk.html);
        else body.appendChild(this.codeBox(blk));
      }
      body.querySelectorAll('a[href]').forEach((a) => {
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
      });
      body.querySelectorAll('table').forEach((t) => {
        t.classList.add('ai-table');
        if (!t.parentElement.classList.contains('ai-tablewrap')) {
          const w = h('div.ai-tablewrap');
          t.replaceWith(w);
          w.appendChild(t);
        }
      });
    }
    /** an answer that streams in: drawn at most once a frame */
    painter(body, tab) {
      let pending = null, raf = 0;
      return (text) => {
        pending = text;
        if (raf) return;
        raf = requestAnimationFrame(() => {
          raf = 0;
          if (pending == null) return;
          this.fill(body, pending + ' ▍');
          this.scroll(tab);
        });
      };
    }
    codeBox(blk) {
      const lang = blk.lang || '';
      const kind = PY.test(lang) ? 'python' : RL.test(lang) ? 'r' : SH.test(lang) || (!lang && looksShell(blk.code)) ? 'bash' : null;
      const pre = h('pre.ai-code', h('code', blk.code));
      const label = blk.file || (kind === 'r' ? 'R' : lang) || '';
      const head = label ? h('div.ai-code-head', label) : null;
      const acts = h('div.ai-code-acts');
      const btn = (icon, text, fn, primary, tip) => {
        const b = h('button.btn.small' + (primary ? '.primary' : ''), { type: 'button', title: tip || '', html: (icon ? MG.icon(icon) : '') + '<span>' + esc(text) + '</span>' });
        b.addEventListener('click', async () => {
          b.disabled = true;
          try {
            await fn();
          } catch (e) {
            console.error(e);
            toast(esc(e.message || String(e)), 'error');
          } finally {
            b.disabled = false;
          }
        });
        return b;
      };
      if (blk.file) acts.appendChild(btn('save', 'Save as ' + blk.file, () => this.saveAs(blk.file, blk.code), true, 'Save this as a file in your home folder, and open it in Files'));
      if (kind === 'python' || kind === 'r') {
        const L = kind === 'r' ? 'an R' : 'a Python';
        acts.append(btn('notebook', 'Add to notebook', () => this.toNotebook(blk.code, kind, false), !blk.file, `Add this code as a new cell of ${L} notebook (the open one, if it is ${L} notebook)`), btn('play', 'Add and run', () => this.toNotebook(blk.code, kind, true), false, `Add this code to ${L} notebook and run it`));
      } else if (kind === 'bash') {
        const code = shellCode(blk.code);
        const cmds = shellCommands(code);
        if (cmds.length) {
          acts.appendChild(btn('terminal', cmds.length > 1 ? `Run in the terminal (${cmds.length} commands)` : 'Run in the terminal', () => this.toTerminal(code, true), !blk.file, 'Run these commands in the Terminal'));
          if (cmds.length === 1 && !cmds[0].includes('\n')) acts.appendChild(btn('keyboard', 'Type in the terminal', () => this.toTerminal(cmds[0], false), false, 'Type the command at the prompt without running it: check it, then press Enter'));
          acts.appendChild(btn('notebook', 'Add to notebook', () => this.toNotebook('%%bash\n' + code, (this.nb && this.nb.view && this.nb.view.lang) || 'python', false), false, 'Add these commands to the open notebook as a %%bash cell'));
        }
      } else if (!blk.file && !PLAIN.test(lang)) {
        acts.appendChild(btn('save', 'Save as…', () => this.saveAsAsk(blk), false, 'Save this as a file in your home folder'));
      }
      acts.appendChild(btn('copy', 'Copy', async () => ((await MG.copyText(blk.code)) ? toast('Copied.') : toast('Could not copy.', 'error'))));
      return h('div.ai-codebox', head, pre, acts);
    }

    /* ---------------- code into the workbench ---------------- */
    async toNotebook(code, lang, run) {
      await MG.app.toNotebook(code, lang === 'r' ? 'r' : 'python', run);
      bus.emit('ai:insert', { target: 'notebook', lang, run: !!run });
    }
    async toTerminal(code, run) {
      if (MG.app.term && MG.app.term.locked) return toast('The agent is using the terminal – wait until it has finished, or press Stop.', 'warn');
      if (run && RISKY.test(code) && !(await confirmBox('Run these commands?', `<p>They delete, move or overwrite files – check the names first. What is deleted cannot be brought back.</p><pre class="ai-code">${esc(code)}</pre>`, 'Run them'))) return;
      await MG.app.runInTerminal(code, run);
      bus.emit('ai:insert', { target: 'terminal', run: !!run });
    }
    resolvePath(file) {
      const rel = file.replace(/^\.\//, '');
      return rel.startsWith('/') ? rel : rel.startsWith('~/') ? HOME() + rel.slice(1) : HOME() + '/' + rel;
    }
    async saveAs(file, code) {
      const fs = MG.app.fs;
      const path = this.resolvePath(file);
      const e = fs.get(path);
      if (e && (e.readonly || e.protected)) return toast(esc(pretty(path)) + ' is read-only: save it under another name.', 'error');
      if (e && e.kind === 'dir') return toast(esc(pretty(path)) + ' is a folder.', 'error');
      if (e) {
        const old = await fs.readText(path);
        if (old.trim() !== code.trim() && !(await confirmBox('Replace the file?', `<p><b>${esc(pretty(path))}</b> is there already. Replace what is in it with the assistant’s version?</p>`, 'Replace'))) return;
      }
      fs.mkdirp(MG.path.dirname(path));
      fs.writeText(path, code.replace(/\s+$/, '') + '\n', /\.(sh|bash|py|R)$/i.test(path) && /^#!/.test(code) ? { mode: 'x' } : undefined);
      await MG.app.editFile(path, { line: 1 });
      toast(`Saved <b>${esc(pretty(path))}</b>.`, 'ok', 3000);
      bus.emit('ai:insert', { target: 'file', path });
    }
    async saveAsAsk(blk) {
      const ext = EXT[blk.lang] || '.txt';
      const def = ext.startsWith('.') ? 'ai-' + stamp().slice(11) + ext : ext;
      const name = await MG.promptText('Save as', 'A file name, or a path – it is saved in your home folder (~).', def, 'Save');
      if (name && name.trim()) await this.saveAs(name.trim(), blk.code);
    }

    /* ---------------- sending ---------------- */
    async send(text) {
      const q = (text != null ? text : this.input.value).trim();
      if (!q) return;
      if (this.busy) {
        toast('The assistant is still busy – wait for it, or press Stop.', 'warn');
        return;
      }
      if (!this.connected()) return this.noModel();
      if (text == null) this.input.value = '';
      const tab = this.tab;
      this.addBubble('user', q, { tab });
      this.msgs[tab].push({ role: 'user', content: q });
      this.renderSuggestions();
      bus.emit('ai:ask', { tab, source: text == null ? 'typed' : 'button' });
      if (tab === 'agent') return this.liveAgent(q);
      return this.live(q);
    }
    noModel() {
      toast('Connect an AI model first (⚙ AI settings).', 'warn', 4000);
      const card = this.threads[this.tab].querySelector('.ai-setup');
      if (!card) return this.setupCard(this.tab);
      card.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      card.classList.add('flash');
      setTimeout(() => card.classList.remove('flash'), 1400);
    }
    /** Stop. While the agent runs a command in the terminal, the first press lets the program that is running finish
        and skips the rest; a second press stops that program by force (what programs had written is then lost). */
    stopNow() {
      if (this._abort) this._abort.abort();
      const T = MG.app.term;
      if (this._agentLive && T && T.busy) T.stop();
    }

    /* ---------------- asked from the terminal or a notebook ---------------- */
    async askAboutError(d) {
      if (this.tab !== 'chat') this.showTab('chat');
      if (this.busy) return toast('The assistant is still answering – try again in a moment.', 'warn');
      const err = (d.error || d.output || '').trim();
      const short = err.split('\n').slice(-12).join('\n');
      const q = `My command failed:\n$ ${d.line}\n${short}`;
      this.addBubble('user', q);
      if (!this.connected()) {
        const help = offlineHelp(d.line + '\n' + (d.output || ''), 'shell');
        const reply = (help ? `What that message usually means:\n\n${help}` : 'Read the **last lines** of the message first – they usually name the problem – and check the names of the files and the folder you are in (`pwd`, `ls`).') + '\n\n*Offline help – no AI model is connected.*';
        const b = this.addBubble('assistant', reply, { badge: 'offline help' });
        b.appendChild(this.setupActs({ question: 'Why did this command fail, and how do I fix it?', extra: { error: d } }));
        return;
      }
      this.msgs.chat.push({ role: 'user', content: q });
      this.renderSuggestions();
      return this.live(q, { error: d });
    }
    async askAboutCell(d) {
      if (this.tab !== 'chat') this.showTab('chat');
      if (this.busy) return toast('The assistant is still answering – try again in a moment.', 'warn');
      const c = d.cell;
      const what = d.kind === 'fix' ? 'Explain this error and how to fix it.' : d.kind === 'improve' ? 'How could this code be improved or extended?' : 'Explain what this code does.';
      const shortCode = c.code.length > 600 ? c.code.slice(0, 600) + '\n…' : c.code;
      const q = `${what}\n\n${shortCode}${d.kind === 'fix' && c.error ? `\n\n${c.error.ename}: ${c.error.evalue}` : ''}`;
      this.addBubble('user', q);
      if (!this.connected()) {
        let reply;
        const e = c.error;
        if (d.kind === 'fix' && e) {
          const text = `${e.ename}: ${e.evalue}\n${e.traceback || ''}`;
          const help = c.lang === 'r' ? offlineHelp(text, 'r') : PY_HELP[e.ename] ? '- ' + PY_HELP[e.ename] : offlineHelp(text, 'python');
          reply = `**${e.ename}**${e.evalue ? ': ' + e.evalue : ''}\n\n${help || '- Read the last line of the error first: it names the problem. The line it points to is where it was noticed – the mistake can be just above it.'}`;
        } else reply = 'Explaining or improving code needs an AI model. Connect one (Google Gemini has a free tier), or copy a prompt with this cell into an AI tool you are allowed to use.';
        const b = this.addBubble('assistant', reply + '\n\n*Offline help – no AI model is connected.*', { badge: 'offline help' });
        b.appendChild(this.setupActs({ question: what, extra: { cell: c } }));
        return;
      }
      this.msgs.chat.push({ role: 'user', content: q });
      this.renderSuggestions();
      return this.live(q, { cell: c });
    }

    /* ---------------- the chat ---------------- */
    systemPrompt() {
      return [
        'You are the AI assistant of a bioinformatics workbench: a website where people – researchers, staff and students in the life sciences, many of them new to programming – analyse biological data. Everything runs in their web browser; nothing is installed.',
        '',
        'The workbench:',
        ...envLines(),
        '- Its tabs: Notebook (Jupyter-style notebooks in Python or R, saved as .ipynb files; in a Python cell !command runs a terminal command, and a cell that begins with %%bash runs terminal commands – in R notebooks too), Terminal, Files (a file browser and editor), Galaxy (a small Galaxy with the same programs), Databases (search forms for UniProt, PDB, Ensembl, NCBI, EBI BLAST and others, each with code to repeat the search), 3D viewer (NGL, for PDB and AlphaFold structures), Genome browser (igv.js: BAM, VCF, BED and GFF files), Networks (networks of genes, proteins or anything else, drawn with Cytoscape.js: SIF, GraphML, GML, XGMML, Cytoscape JSON and CX2 files, networks from STRING, IntAct and NDEx; styles mapped from table columns, e.g. DESeq2 results on a STRING network; statistics as in Cytoscape\'s Analyzer, hubs as in cytoHubba, clusters with MCODE, MCL and Louvain, enrichment with STRING or g:Profiler; the terminal command  network FILE  opens a file there), and AI assistant (you).',
        '',
        'How to answer:',
        '- Be brief, clear and friendly. Explain in plain words what code does and why – many users are learning.',
        '- Put Python code in ```python blocks, R code in ```r blocks and terminal commands in ```bash blocks: each block gets a button that puts it into a notebook or runs it in the terminal. Give complete code that runs in this environment, with real paths (/data/examples/…, ~/…). To offer a file, put its path after the language: ```python scripts/count_genes.py',
        '- Never invent program options, functions, results or file contents. If you are not sure, say so, and say how to check (PROGRAM --help, help(name) in Python, ?name in R).',
        '- Do not claim to have run code or seen results that the user has not shown you.',
        '- If the user seems to be working with personal or patient data, remind them not to share it with AI tools.'
      ].join('\n');
    }
    /** what the model gets with a question, besides the conversation */
    async contextFor(extra = {}) {
      const parts = [];
      const fs = MG.app.fs;
      const last = this.lastBench();
      parts.push(`(The user was last in the ${TAB_NAMES[last] || last} tab.)`);
      try {
        if (extra.error) {
          const e = extra.error;
          parts.push(`The command that failed, run in ${pretty(e.cwd || fs.cwd)}: \`${e.line}\`. The end of what it printed:\n\`\`\`text\n${String(e.output || '').slice(-3000)}\n\`\`\``);
        }
        if (extra.cell) {
          const c = extra.cell, L = c.lang === 'r' ? 'r' : 'python';
          parts.push(`The user asks about this cell of the ${L === 'r' ? 'R' : 'Python'} notebook ${pretty(c.path)}:\n\`\`\`${L}\n${c.code}\n\`\`\``);
          if (c.error) parts.push(`It raised:\n\`\`\`text\n${String(c.error.traceback || c.error.ename + ': ' + c.error.evalue).slice(-2500)}\n\`\`\``);
          else if (c.output) parts.push(`What it printed (the beginning):\n\`\`\`text\n${c.output.slice(0, 1200)}\n\`\`\``);
        }
        const v = this.nb && this.nb.view;
        if (this.ctxOpts.nb && v) {
          const code = v.codeContext(4000);
          if (code) parts.push(`The notebook open in the Notebook tab: ${pretty(v.path)} (${v.lang === 'r' ? 'R' : 'Python'}; its code runs in ${pretty(MG.path.dirname(v.path))}). Its code cells:\n\`\`\`${v.lang === 'r' ? 'r' : 'python'}\n${code}\n\`\`\``);
        }
        if (this.ctxOpts.files) {
          const list = this.fileList(60);
          if (list) parts.push(`The user's files (names and sizes only):\n${list}`);
        }
        if (this.ctxOpts.net !== false && last === 'networks' && MG.app.networks && MG.app.networks.contextText) parts.push(MG.app.networks.contextText());
        if (this.ctxOpts.term && last === 'terminal' && !extra.error && !extra.cell) {
          const T = MG.app.term;
          const recent = ((T && T.transcript) || []).slice(-3);
          if (recent.length) parts.push('The last commands in the terminal, and the end of what they printed:\n```text\n' + recent.map((e) => `${pretty(e.cwd)}$ ${e.line}${e.code ? `   (exit status ${e.code})` : ''}\n${String(e.stderr || e.stdout || '').slice(-600).replace(/\s+$/, '')}`).join('\n') + '\n```');
        }
      } catch (e) {
        console.error(e);
      }
      // (the name the person gave the workbench stays in the browser: "user" where it names the user – ls -l, whoami …)
      return MG.user.mask(parts.join('\n\n')) + '\n\n';
    }
    /** the user's files: names and sizes, two folders deep */
    fileList(max = 60) {
      const fs = MG.app.fs, out = [];
      let more = 0;
      const walk = (dir, depth) => {
        for (const c of fs.list(dir)) {
          if (c.name.startsWith('.') || (c.entry && c.entry.hidden)) continue;
          const isDir = c.entry.kind === 'dir';
          if (out.length >= max) {
            more++;
            continue;
          }
          out.push(`${'  '.repeat(depth + 1)}${c.name}${isDir ? '/' : ` (${MG.humanSize(fs.size(c.entry))}B)`}`);
          if (isDir && depth < 1) walk(c.path, depth + 1);
        }
      };
      try {
        walk(HOME(), 0);
      } catch (e) {
        return '';
      }
      return out.length ? `~/\n${out.join('\n')}${more ? `\n  … and ${more} more` : ''}` : '';
    }
    async live(q, extra) {
      this.busy = true;
      this._abort = new AbortController();
      this.sendBtn.innerHTML = MG.icon('stop') + '<span>Stop</span>';
      const b = this.addBubble('assistant', '', { tab: 'chat' });
      const body = b.querySelector('.ai-body');
      body.innerHTML = '<span class="ai-typing"><i></i><i></i><i></i></span>';
      const hist = this.msgs.chat.slice(-12).map((m) => ({ role: m.role, content: m.content }));
      while (hist.length && hist[0].role !== 'user') hist.shift();
      if (hist.length) hist[hist.length - 1] = { role: 'user', content: (await this.contextFor(extra || {})) + 'Question: ' + hist[hist.length - 1].content };
      let text = '';
      const paint = this.painter(body, 'chat');
      const t0 = performance.now();
      try {
        const res = await this.streamLive(
          hist,
          (delta) => {
            text += delta;
            paint(text);
          },
          this._abort.signal,
          {
            onReset: () => {
              text = '';
              paint('');
            }
          },
          (note) => {
            if (!text) body.innerHTML = `<div class="muted small" style="margin-bottom:0.35em">${esc(note)}</div><span class="ai-typing"><i></i><i></i><i></i></span>`;
          }
        );
        // a reply with nothing in it is not kept as a turn of the conversation: it is reported, and the question can be asked again
        if (!text.trim()) throw Object.assign(new Error(`${res.model} sent an empty reply. Ask again – a second try usually gets an answer.`), { empty: true });
        paint(null);
        this.fill(body, text);
        const via = res.skipped.length ? ` (${res.skipped.map((x) => x.model + ' ' + skipWord(x)).join(', ')})` : '';
        b.appendChild(h('div.ai-badge', { html: `${esc(res.model + via)} · ${((performance.now() - t0) / 1000).toFixed(1)} s` }));
        this.msgs.chat.push({ role: 'assistant', content: text });
        bus.emit('ai:answer', { model: res.model });
      } catch (e) {
        paint(null);
        if (e.name === 'AbortError') {
          this.fill(body, (text || '') + '\n\n*(stopped)*');
          if (text) this.msgs.chat.push({ role: 'assistant', content: text });
        } else {
          this.fill(body, (e.empty ? '' : '**The AI service returned an error.**\n\n') + e.message);
          b.classList.add('err');
        }
      } finally {
        this.busy = false;
        this._abort = null;
        this.sendBtn.innerHTML = MG.icon('send') + '<span>Send</span>';
        this.scroll('chat');
      }
    }

    /* ---------------- the agent ---------------- */
    agentPrompt(run) {
      return [
        "You are an AI agent in a bioinformatics workbench that runs entirely in the user's web browser. You carry out the user's task by running shell commands, one step at a time, in its terminal.",
        '',
        'How to work:',
        '- In each reply, say in one or two short sentences what you will do next and why, then give ONE step in a ```bash code block – a command, or a few that belong together, one per line – and stop. You then get the exit status and the output. If a command of the block fails, the ones after it are not run.',
        '- Base each next step on the output you got. If a command fails, read the error and change your approach. Check what you make (head, wc -l, samtools quickcheck …) before you report it.',
        '- Do not ask the user questions – nobody can answer during the task. Make sensible choices, say which, and carry on.',
        `- You can take at most ${AGENT_MAX} steps for a task.`,
        '- When the task is done, or cannot be done, reply WITHOUT a code block: the commands you ran (in short), the files you made (with their paths) and what the results show. Report only what the outputs showed – never invent results, numbers, versions or files.',
        '',
        'Your environment:',
        `- Your folder is ${pretty(run)} (= ${run}). Every step starts there, and cd is not available: use paths. Write files only inside your folder – changes anywhere else are undone after each step. You may read files anywhere: the user's files in ~ and the example data in /data/examples. agent-record.ipynb in your folder is the record of your work: leave it alone.`,
        ...envLines({ agent: true, web: this.allowWeb }),
        `- Each step's output is shortened to its last ${AGENT_OUT} characters. A step that has not ended after ${AGENT_SECONDS} seconds is stopped. For Python or R code of more than a line or two, write a script with a here-document (cat > count.py << 'EOF' … EOF) and run it (python count.py); save plots as files (plt.savefig("plot.png"), png("plot.png") … dev.off()).`,
        "- Commands that act on the user's screen (open, nano, igv, network, download) are not available to you."
      ].join('\n');
    }
    /** one turn of the agent: the model's reply (free-tier limits: wait and ask again, up to 3 times) */
    async agentAsk(hist, run, signal, note, onText) {
      for (let waited = 0; ; waited++) {
        let text = '';
        try {
          const res = await this.streamLive(
            hist,
            (d) => {
              text += d;
              onText(text);
            },
            signal,
            {
              settings: this.settings,
              key: this.key,
              system: this.agentPrompt(run),
              onReset: () => {
                text = '';
                onText('');
              }
            },
            note
          );
          return { text, model: res.model };
        } catch (e) {
          // no model answered. Waiting helps when a limit per minute is reached, the servers are busy or the connection
          // gave no answer (the error says after how many seconds: retryIn) – up to three times for one reply. It does
          // not help when every model is over its limit for today, or the key is not accepted: the task ends at once.
          const wait = e.name !== 'AbortError' && e.retryIn > 0 ? Math.round(Math.min(90, Math.max(5, e.retryIn))) : 0;
          if (wait && waited >= 3) e.message += (e.status === 429 ? ' The page waited three times and the limit is still reached – a key that many people are using at once, perhaps.' : e.status ? ' The page waited three times and asked again: the service is still busy.' : ' The page waited three times and asked again: still no answer.') + ' Go on later' + (e.status ? ', or use a key from another person or project (limits are counted per project, not per key).' : '.');
          if (!wait || waited >= 3) throw e;
          for (let t = wait; t > 0; t--) {
            note(`${e.status === 429 ? 'The service allows only a few requests per minute' : e.status ? 'The service is busy' : 'No answer came from the service'} – waiting ${t} s, then asking again (Stop ends the task)…`);
            await pause(1000, signal);
          }
          note('');
        }
      }
    }
    agentCard(title) {
      const card = h('div.ai-msg.assistant.ag');
      const head = h('div.ag-head', { html: MG.icon('robot') + '<b>' + esc(title) + '</b>' });
      const steps = h('ol.ag-steps');
      card.append(head, steps);
      this.threads.agent.appendChild(card);
      this.scroll('agent', true);
      return { card, steps };
    }
    /** run a command in the terminal (as the agent) and capture what it printed */
    async termRun(cmd, opts) {
      const T = MG.app.term;
      for (let i = 0; i < 600 && T.busy; i++) await sleep(100);
      const before = T.outEl.children.length;
      const code = await T.exec(cmd, opts);
      const els = Array.from(T.outEl.children).slice(before + 1);
      const text = els.filter((x) => !x.classList.contains('ask')).map((x) => x.textContent + (x.classList.contains('note') ? '\n' : '')).join('');
      // (what goes to the AI service: the agent runs as "user" – and where the person's name still names the user in
      // what it printed, a log of the person's with the output of whoami or ls -l in it, "user" takes its place)
      return { code, text: opts && opts.agent ? MG.user.mask(text) : text };
    }
    /** While a step of the agent runs, a change to a file that its command did not reach – a notebook saved, a file
        edited in Files, a cell that wrote a file – is the user's: it is not undone after the step. (The terminal
        notes every path that the agent's command works out: T.touched. Programs, Python and R write through it.) */
    _onFsChange(path, what) {
      const s = this._step;
      if (!s || insideDir(path, s.run)) return;
      const T = MG.app.term;
      const touched = T && T.touched;
      if (touched && touched.has(path)) return;
      if (touched && what === 'mkdir') for (const t of touched) if (t.startsWith(path + '/')) return;
      s.saved.add(path);
    }
    /** the record of the agent's work in a folder, as a notebook: each step a %%bash cell with its output */
    saveRecord(ctx) {
      const fs = MG.app.fs;
      if (!fs.isDir(ctx.run)) return null;
      const path = ctx.run + '/agent-record.ipynb';
      const where = pretty(ctx.run);
      const cells = [
        {
          type: 'markdown',
          source: `# AI agent – ${where}\n\nThe tasks given to the AI agent of the Bioinformatics workbench, and the steps it ran in the terminal, with their output as the agent saw it (shortened). Every step ran in \`${where}\` – the folder of this notebook. **Check the results yourself**: an agent can be wrong, and its report can claim more than the outputs show.\n\nEach code cell starts with \`%%bash\` and runs in the notebook's folder: again in the workbench's Notebook tab, or in Jupyter on a computer with the same programs. To keep the agent's files as they are, copy the folder (with this notebook) and run the copy.`
        }
      ];
      ctx.tasks.forEach((t, i) => {
        cells.push({ type: 'markdown', source: `## Task ${i + 1}\n\n${quote(t.task)}\n\n*${new Date(t.t).toLocaleString('en-GB')} · ${t.models.join(', ') || modelOf(this.settings)} · ${t.steps.length} step${t.steps.length === 1 ? '' : 's'}*` });
        for (const s of t.steps) {
          if (s.say) cells.push({ type: 'markdown', source: quote(s.say) });
          if (s.refused) {
            cells.push({ type: 'markdown', source: `*Not run – ${s.refused}*\n\n\`\`\`bash\n${s.cmd}\n\`\`\`` });
            continue;
          }
          const outputs = s.out ? [{ type: 'stream', name: 'stdout', text: s.out.length > 20000 ? s.out.slice(0, 8000) + '\n… (shortened) …\n' + s.out.slice(-8000) : s.out }] : [];
          // (no cd: a %%bash cell runs in the notebook's folder, which is the agent's – so a copy of the folder runs in the copy)
          cells.push({ type: 'code', source: `%%bash\n${s.cmd}`, outputs, meta: { workbench: { exit_status: s.code, agent_step: true } } });
          if (s.note) cells.push({ type: 'markdown', source: `*${s.note}*` });
        }
        cells.push({ type: 'markdown', source: `### The agent's report\n\n${t.report || '*(' + (t.outcome || 'no report') + ')*'}` });
      });
      try {
        fs.writeText(path, JSON.stringify(MG.nbformat.make('python', cells, { workbench: { kind: 'ai-agent-run' } }), null, 1));
      } catch (e) {
        console.error(e);
        return null;
      }
      return path;
    }
    async liveAgent(task) {
      const fs = MG.app.fs;
      const T = MG.app.term;
      if (!T) {
        this.addBubble('assistant', 'The terminal is not ready yet – try again in a moment.', { tab: 'agent' });
        return;
      }
      this.busy = true;
      this._abort = new AbortController();
      const signal = this._abort.signal;
      this.sendBtn.innerHTML = MG.icon('stop') + '<span>Stop</span>';
      // the folder: the conversation's, or a new one
      let ctx = this.agentCtx;
      if (!ctx || !fs.isDir(ctx.run)) {
        let n = 1;
        while (fs.exists(HOME() + '/ai-agent/run-' + n)) n++;
        ctx = this.agentCtx = { n, run: HOME() + '/ai-agent/run-' + n, tasks: [] };
        fs.mkdirp(ctx.run);
      }
      const run = ctx.run;
      const earlier = ctx.tasks.slice();
      const rec = { task, steps: [], report: '', outcome: '', t: Date.now(), models: [] };
      ctx.tasks.push(rec);
      this.renderCtx();
      const back = fs.cwd;
      const { card, steps } = this.agentCard(`Agent · working in ${pretty(run)}`);
      const noteEl = h('div.muted.small.ag-note');
      card.appendChild(noteEl);
      const note = (t) => {
        noteEl.textContent = t || '';
        this.scroll('agent');
      };
      const t0 = performance.now();
      // (a task after others in the same folder: what they were, what was run, and what was found)
      const intro = earlier.length
        ? 'Earlier tasks in this folder – you did them, and their files are still there:\n' +
          earlier
            .map((t, i) => `${i + 1}. Task: ${t.task}\n   Commands: ${t.steps.filter((s) => s.cmd && !s.refused).map((s) => s.cmd.split('\n')[0]).slice(-12).join(' ; ').slice(0, 1500) || '(none)'}\n   Your report: ${(t.report || '(none)').slice(0, 1500)}`)
            .join('\n') +
          '\n\nThe new task:\n'
        : '';
      const hist = [{ role: 'user', content: intro + task }];
      let cmds = 0, final = '', outcome = 'done';
      // The agent works in a new shell – the user's variables, functions and options are not its own, and it leaves
      // none behind – and nobody else can type into the terminal meanwhile.
      for (let i = 0; i < 600 && T.busy; i++) await sleep(100);
      const shellState = T.shell.saveState ? T.shell.saveState() : null;
      if (T.shell.freshState) T.shell.freshState();
      const held = new Map(); // the page's copies of program-written files, for a forced stop: see holdBytes
      if (T.lock) T.lock('The AI agent is using the terminal – Stop it in the AI assistant tab.');
      this._agentLive = true;
      MG.app.agentBusy = true;
      let reminded = false;
      try {
        await this.termRun('cd ' + run, { agent: true });
        for (;;) {
          const li = h('li.ag-step.run', h('span.ag-ic', { html: '<span class="spinner small"></span>' }), h('span.ag-say.muted', 'thinking…'));
          steps.appendChild(li);
          this.scroll('agent');
          const say = li.querySelector('.ag-say');
          const { text, model } = await this.agentAsk(hist, run, signal, note, (t) => {
            say.textContent = withoutCode(t) || 'thinking…';
            this.scroll('agent');
          });
          note('');
          if (!rec.models.includes(model)) rec.models.push(model);
          const step = agentStep(text), cmd = step.cmd;
          // A reply with a code block that is no command (```text, ```python …). The rule the agent was given is that
          // a report has no code block: once in a task it is told that nothing was run, and asked which it meant.
          if (cmd == null && /```/.test(text) && !reminded && cmds < AGENT_MAX) {
            reminded = true;
            li.remove();
            hist.push({ role: 'assistant', content: text }, { role: 'user', content: AGENT_REMIND });
            continue;
          }
          if (cmd == null || cmds >= AGENT_MAX) {
            // no command: this is the agent's report
            li.remove();
            final = cmd == null ? text : withoutCode(text) + `\n\n*(Stopped at the limit of ${AGENT_MAX} steps.)*`;
            break;
          }
          // (the description of the step: what stands in front of its block – see AGENT_AHEAD)
          const ahead = step.before && step.after.length > AGENT_AHEAD;
          const said = ahead ? step.before : withoutCode(text);
          say.textContent = said;
          say.classList.remove('muted');
          cmds++;
          const srec = { say: said, cmd: cmd || '', code: null, out: '', refused: '', note: '' };
          rec.steps.push(srec);
          const refused = cmd ? agentRefusal(cmd) : 'the code block was empty: give one command.';
          let result;
          li.appendChild(h('div', h('code.ag-cmd', cmd || '(empty)')));
          if (refused) {
            li.classList.add('bad');
            li.querySelector('.ag-ic').textContent = '⛔';
            li.appendChild(h('small.muted', 'not run: ' + refused));
            srec.refused = refused;
            result = 'Not run: ' + refused;
          } else {
            // run it in the terminal; what it changes outside the agent's folder is put back
            const W = MG.exec;
            const snap = outsideSnapshot(fs, run);
            if (W && W.keep) {
              try {
                await W.keep(Array.from(snap));
              } catch (e) {
                console.error(e); // without the copies, only files that the command leaves alone can be put back
              }
            }
            const before = new Map();
            for (const [p, e] of fs.entries) if (W.holds(e) && !insideDir(p, '/tmp')) before.set(p, e);
            try {
              await holdBytes(fs, held);
            } catch (e) {
              console.error(e);
            }
            const since = Date.now(), gen = W ? W.gen : 0;
            const saved = new Set(); // what the user changes meanwhile: theirs
            this._step = { run, saved };
            // a command that has not ended after AGENT_SECONDS is stopped by force. (The Stop button: see stopNow.)
            let timedOut = false, again = null;
            const timer = setTimeout(() => {
              timedOut = true;
              T.stop();
              T.stop(true);
              // (a program that was only just being started is not "running" yet at that moment: again, until the command has ended)
              again = setInterval(() => T.stop(true), 500);
            }, AGENT_SECONDS * 1000);
            const r = { code: 0, text: '' };
            const notRun = [], refusedNow = [];
            let ended = null;
            try {
              // the commands of the block, one after the other: what follows a command that failed is not run
              const parts = agentParts(cmd);
              for (let k = 0; k < parts.length; k++) {
                T.shell.endedBy = null;
                T.shell.exitTyped = false;
                // (while a command of the agent runs, the shell refuses the programs the agent has not got)
                T.shell._agentOnly = AGENT_ALLOW;
                T.shell._agentRefused = refusedNow;
                let one;
                try {
                  one = await this.termRun(parts[k], { agent: true });
                } finally {
                  T.shell._agentOnly = null;
                  T.shell._agentRefused = null;
                }
                r.text += one.text;
                r.code = one.code;
                // (exit, or the agent's own set -e / set -u, ended the command where a script would have ended: so does the block)
                ended = T.shell.exitTyped ? 'exit' : T.shell.endedBy || null;
                T.shell.exitTyped = false;
                if (one.code !== 0 || ended || timedOut || signal.aborted) {
                  notRun.push(...parts.slice(k + 1));
                  break;
                }
              }
            } finally {
              clearTimeout(timer);
              clearInterval(again);
              this._step = null;
            }
            // (files that a forced stop of the programs removed are not the user's doing)
            if (W && W.gen !== gen && W.lostEntries) for (const k of W.lostEntries.keys()) saved.delete(k);
            const u = await undoOutside(fs, run, snap, saved, since, gen, held, before);
            const undone = u.changed, killed = u.killed;
            // (after a forced stop: the program-written files of this folder that are not there any more – the step's own)
            const gone = killed ? Array.from(before.keys()).filter((p) => insideDir(p, run) && !fs.entries.has(p)).map((p) => p.slice(run.length + 1)) : [];
            const lostOut = u.lost.filter((p) => !insideDir(p, run));
            if (fs.cwd !== run && fs.isDir(run)) await this.termRun('cd ' + run, { agent: true });
            li.classList.toggle('bad', r.code !== 0 || undone.length > 0 || timedOut);
            li.querySelector('.ag-ic').innerHTML = r.code === 0 && !undone.length && !timedOut ? '✓' : '✗';
            const lines = r.text.replace(/\s+$/, '').split('\n');
            const excerpt = (lines.length > 14 ? ['…'].concat(lines.slice(-14)) : lines).join('\n');
            li.appendChild(h('details.ag-out', h('summary', `output (exit status ${r.code})`), h('pre', excerpt || '(no output)')));
            const notes = [];
            if (undone.length) notes.push('Changes outside its folder were undone: ' + undone.slice(0, 4).map((k) => pretty(k)).join(', ') + (undone.length > 4 ? ' …' : ''));
            if (refusedNow.length) notes.push('not available to the agent: ' + refusedNow.join(', '));
            if (timedOut) notes.push(`Stopped by the page: it ran for more than ${AGENT_SECONDS} seconds.`);
            if (killed) notes.push('The programs had to be stopped by force, and were started again. What programs wrote in this step is gone; the files they had written before are back as they were.' + (lostOut.length ? ' Lost from your folders (too large to hold a copy of): ' + lostOut.slice(0, 4).map((k) => pretty(k)).join(', ') + (lostOut.length > 4 ? ` and ${lostOut.length - 4} more` : '') + '.' : ''));
            notes.forEach((t) => li.appendChild(h('small.muted', t)));
            srec.code = r.code;
            srec.out = r.text;
            srec.note = notes.join(' ');
            const out = r.text.trim();
            result =
              `Exit status ${r.code}.` +
              (timedOut ? ` The command was stopped: it ran for more than ${AGENT_SECONDS} seconds.` : '') +
              (killed ? ' The programs had to be stopped by force: what programs wrote in this step is gone; the files from earlier steps are as they were.' + (gone.length ? ` Not there any more: ${gone.slice(0, 6).join(', ')}.` : '') : '') +
              (refusedNow.length ? ` ${refusedNow.map((b) => '`' + b + '`').join(', ')} ${refusedNow.length > 1 ? 'are' : 'is'} not available to you.` : '') +
              (notRun.length ? ` Not run, because the command before ${r.code !== 0 ? 'failed' : ended === 'exit' ? 'was exit' : 'ended the block'}: ${notRun.join(' ; ').slice(0, 300)}.` : '') +
              (undone.length ? ` Your changes outside your folder were undone: ${undone.slice(0, 6).map((k) => pretty(k)).join(', ')}.` : '') +
              '\nOutput' +
              (out.length > AGENT_OUT ? ' (last ' + AGENT_OUT + ' characters)' : '') +
              ':\n```text\n' +
              (out.slice(-AGENT_OUT) || '(no output)') +
              '\n```';
          }
          li.classList.remove('run');
          if (ahead) {
            li.appendChild(h('small.muted', 'The model wrote more after this step – before the step had run. That text is not shown here: a report can only come after the result.'));
            result += '\n\n' + AGENT_AHEAD_TOLD;
          }
          if (cmds >= AGENT_MAX) result += `\n\nYou have used all ${AGENT_MAX} steps. Reply now without a code block: what you did, which files you made and what the results show.`;
          hist.push({ role: 'assistant', content: text }, { role: 'user', content: result });
          if (signal.aborted) throw new DOMException('Stopped', 'AbortError');
        }
      } catch (e) {
        outcome = e.name === 'AbortError' ? 'stopped' : 'error';
        steps.querySelectorAll('li.run').forEach((li) => {
          li.classList.remove('run');
          li.querySelector('.ag-ic').textContent = '–';
          if (/thinking/.test(li.textContent)) li.remove();
        });
        final = outcome === 'stopped' ? '*(Stopped.)*' : '**The AI service returned an error.**\n\n' + e.message;
        if (outcome === 'error') card.classList.add('err');
      } finally {
        this._step = null;
        note('');
        if (fs.cwd !== back && fs.isDir(back)) await this.termRun('cd ' + back, { agent: true });
        this._agentLive = false;
        MG.app.agentBusy = false;
        if (T.unlock) T.unlock();
        if (shellState && T.shell.restoreState) T.shell.restoreState(shellState);
        held.clear();
        MG.exec.dropKept().catch(() => {});
        T._renderPrompt();
        rec.report = outcome === 'done' ? final : '';
        rec.outcome = outcome === 'done' ? 'done' : outcome === 'stopped' ? 'stopped by the user' : 'the AI service returned an error';
        card.querySelector('.ag-head b').textContent = (outcome === 'done' ? 'Agent · finished' : outcome === 'stopped' ? 'Agent · stopped' : 'Agent · error') + ` · ${pretty(run)}`;
        const body = h('div.ai-body');
        card.appendChild(body);
        this.fill(body, final || '(no reply)');
        const recPath = this.saveRecord(ctx);
        if (recPath) card.appendChild(this.recordRow(recPath, run));
        const secs = Math.round((performance.now() - t0) / 1000);
        card.appendChild(h('div.ai-badge', `agent · ${rec.models.join(', ') || modelOf(this.settings)} · ${cmds} step${cmds === 1 ? '' : 's'} · ${secs >= 60 ? Math.floor(secs / 60) + ' min ' : ''}${secs % 60} s`));
        this.msgs.agent.push({ role: 'assistant', content: final || '(no reply)' });
        this.busy = false;
        this._abort = null;
        this.sendBtn.innerHTML = MG.icon('send') + '<span>Send</span>';
        this.scroll('agent');
        this.renderCtx();
        bus.emit('agent:live', { ok: outcome === 'done', run: ctx.n, commands: cmds, folder: pretty(run) });
      }
    }
    /** under an agent's card: its record (a notebook) and its folder */
    recordRow(path, run) {
      const fs = MG.app.fs;
      const b = (icon, text, fn, tip) => {
        const x = h('button.btn.small', { type: 'button', title: tip, html: MG.icon(icon) + '<span>' + esc(text) + '</span>' });
        x.addEventListener('click', () => Promise.resolve(fn()).catch((e) => toast(esc(e.message || String(e)), 'error')));
        return x;
      };
      return h(
        'div.ag-file',
        h('span.ag-fname', { html: MG.icon('notebook') + ' ' + esc(pretty(path)) }),
        h('span.grow'),
        b('notebook', 'Open the record', () => MG.app.openFile(path), 'The steps and their output as a notebook, in the Notebook tab'),
        b('download', '.ipynb', async () => MG.downloadText(await fs.readText(path), `agent-run-${MG.path.basename(run).replace(/^run-/, '')}.ipynb`, 'application/x-ipynb+json'), 'Download the record as a Jupyter notebook'),
        b('folder', 'Folder', () => MG.app.revealFile(run), 'Show the agent’s folder in Files')
      );
    }

    /* ---------------- talking to the service ---------------- */
    /* Stream an answer.
       Gemini: the chosen model is asked first, then the fallback models in their order – but not a model that the
       page knows to be busy, silent or over a limit (the memory above). A model that is busy (HTTP 5xx), over a
       limit (429), not found (404) or gives no answer (the connection fails, or nothing comes for a minute) is
       noted, and the next one is asked. An answer that breaks off part-way is taken back (cfg.onReset) and the
       question goes to the next model. When no model is left that is not at rest, the two that have rested longest
       of those that were only busy or silent get another chance. Two models in a row that give no answer end the
       request: that is the connection, not the models.
       Other services: one model; if it is busy, a second try after a short pause.
       → { model, skipped }: the model that answered, and what kept others from it.
       When nothing answers, the error says what each model said. Its .status is 429 (limits), 503 (busy) or not set
       (no answer came); .retryIn is the number of seconds after which asking again can help. */
    async streamLive(messages, onDelta, signal, cfg, onNote) {
      const s = (cfg && cfg.settings) || this.settings;
      const key = cfg && cfg.key != null ? cfg.key : this.key;
      const system = (cfg && cfg.system) || this.systemPrompt();
      const note = onNote || (() => {});
      const reset = cfg && cfg.onReset;
      // turns must alternate between user and assistant: join neighbours of the same role
      messages = messages.reduce((out, m) => {
        const last = out[out.length - 1];
        if (last && last.role === m.role) last.content += '\n\n' + m.content;
        else out.push({ role: m.role, content: m.content });
        return out;
      }, []);
      if (s.provider !== 'gemini') {
        const model = modelOf(s);
        for (let attempt = 1; ; attempt++) {
          let started = false;
          try {
            await this.streamOnce(s, key, model, messages, (d) => {
              started = true;
              onDelta(d);
            }, signal, system);
            return { model, skipped: [] };
          } catch (e) {
            if (e.name !== 'AbortError' && !started && BUSY.includes(e.status) && attempt === 1) {
              note(`${model} is busy – trying again…`);
              await pause(1500 + Math.random() * 1500, signal);
              continue;
            }
            if (e.status === 429 && !started) e.retryIn = Math.round(Math.min(90, Math.max(5, e.retryAfter || 30)));
            throw e;
          }
        }
      }
      const chosen = geminiModelOf(s);
      const chain = [chosen].concat(FALLBACKS.filter((m, i, a) => a.indexOf(m) === i && m !== chosen));
      if (restKey !== key) {
        // another key is another project, with limits of its own
        REST.clear();
        restKey = key;
      }
      try {
        if (navigator.onLine === false) throw Object.assign(new Error('This browser is offline. Connect it to the internet, and try again.'), { network: true, retryIn: RETRY });
        const said = new Map(); // what each model said: in this request, or when it was last asked and is still at rest
        chain.forEach((m) => resting(m) && said.set(m, REST.get(m)));
        const failed = [];
        let queue = chain.filter((m) => !said.has(m));
        let again = false, silent = 0;
        for (;;) {
          if (!queue.length && !again) {
            again = true;
            queue = chain.filter((m) => said.has(m) && !failed.includes(said.get(m)) && (said.get(m).why === 'busy' || said.get(m).why === 'noanswer')).sort((a, b) => said.get(a).until - said.get(b).until).slice(0, 2);
          }
          if (!queue.length) break;
          const model = queue.shift();
          const before = failed[failed.length - 1];
          if (before) note(`${before.model} ${before.broke ? 'broke off' : told(before, true)} – asking ${model} instead…`);
          let started = false;
          try {
            await this.streamOnce(s, key, model, messages, (d) => {
              started = true;
              onDelta(d);
            }, signal, system);
            REST.delete(model);
            const first = model !== chosen && said.get(chosen);
            return { model, skipped: (first && !failed.includes(first) ? [first] : []).concat(failed).map((x) => ({ model: x.model, why: x.broke ? 'broke' : x.why, daily: x.daily })) };
          } catch (e) {
            if (e.name === 'AbortError') throw e;
            const why = e.network ? 'noanswer' : e.status === 404 ? 'notfound' : e.status === 429 ? 'limit' : BUSY.includes(e.status) ? 'busy' : '';
            // an error of another kind (the key, the request itself) – or an answer that broke off and cannot be taken back
            if (!why || (started && !reset)) throw e;
            if (started) reset();
            const was = REST.get(model);
            const x = { model, why, broke: started, status: e.status, text: e.message, at: Date.now(), until: Infinity };
            if (why === 'limit') {
              const wait = e.retryAfter > 0 ? Math.min(86400, e.retryAfter) : e.daily ? 3600 : 60;
              x.daily = !!e.daily || wait > 900;
              x.limit = e.limit;
              x.until = Date.now() + (wait + 1) * 1000;
            } else if (why === 'busy') {
              // busy again soon after its rest: the rest is twice as long (2, 4, 8, at most 15 minutes)
              x.n = was && was.why === 'busy' && Date.now() - was.until < 600000 ? was.n + 1 : 1;
              x.until = Date.now() + Math.min(900, BUSY_REST * 2 ** (x.n - 1)) * 1000;
            } else if (why === 'noanswer') x.until = Date.now() + SILENT_REST * 1000;
            REST.set(model, x);
            said.set(model, x);
            failed.push(x);
            silent = why === 'noanswer' ? silent + 1 : 0;
            if (silent >= 2) break;
          }
        }
        throw noAnswer(chain.map((m) => said.get(m)).filter(Boolean), silent >= 2);
      } finally {
        this.showStatus();
      }
    }
    /** one request; the answer is passed to onDelta as it arrives.
        An error that the service reports carries .status – and for "too many requests" (429) .retryAfter (seconds)
        and, when the service names a limit per day, .daily and .limit. An answer that does not come – the connection
        fails or breaks off, or (Gemini) nothing arrives for a minute (aiWaitSeconds) – carries .network. */
    async streamOnce(s, key, model, messages, onDelta, signal, system) {
      const gem = s.provider === 'gemini';
      const base = (s.baseURL || '').replace(/\/+$/, '');
      if (signal && signal.aborted) throw stopped();
      // the request ends when the user presses Stop – or when the service has said nothing for too long
      const ac = new AbortController();
      const onStop = () => ac.abort();
      if (signal) signal.addEventListener('abort', onStop, { once: true });
      const quiet = gem ? WAIT() * 1000 : 0;
      let timer = null, silent = false, bytes = 0;
      const arm = () => {
        clearTimeout(timer);
        if (quiet)
          timer = setTimeout(() => {
            silent = true;
            ac.abort();
          }, quiet);
      };
      /* why the answer did not come: the user's Stop, the service's silence, or the connection */
      const lost = (e) => {
        if (signal && signal.aborted) return stopped();
        if (silent) return Object.assign(new Error(`${model} ${bytes ? 'stopped in the middle of its reply and said nothing more' : 'gave no answer'} for ${Math.round(quiet / 1000)} seconds.`), { network: true, silent: true });
        if (e.name === 'AbortError') return e;
        const where = gem ? 'the Gemini API' : s.provider === 'anthropic' ? 'the Anthropic API' : base;
        return Object.assign(new Error(bytes ? `The connection to ${where} broke off in the middle of the reply (${e.message}).` : `Could not reach ${where} (${e.message}). ${s.provider === 'openai' ? 'Check the address; the service must allow requests from web pages (CORS).' : 'Check the internet connection.'}`), { network: true });
      };
      /* an error that the service reports: as the status of its answer, or (Gemini) inside an answer that had begun */
      const refused = (status, j, statusText, retryHeader) => {
        const err = (j && j.error) || null;
        const det = err && Array.isArray(err.details) ? err.details.filter(Boolean) : [];
        const detail = j ? (err && (err.message || err.type)) || JSON.stringify(j).slice(0, 300) : statusText || '';
        const reason = err ? det.map((d) => d.reason).filter(Boolean)[0] || err.status || '' : '';
        const ri = det.find((d) => /RetryInfo$/.test(d['@type'] || ''));
        const retryAfter = (ri && parseFloat(ri.retryDelay)) || parseFloat(retryHeader) || 0;
        // a limit per day is named in the answer: quotaId "GenerateRequestsPerDayPerProjectPerModel-FreeTier", with its value
        const qf = det.find((d) => /QuotaFailure$/.test(d['@type'] || ''));
        const day = ((qf && qf.violations) || []).find((v) => v && /PerDay/i.test(v.quotaId || ''));
        const limit = day && /^\d+$/.test(String(day.quotaValue)) ? +day.quotaValue : undefined;
        const badKey = status === 401 || status === 403 || reason === 'API_KEY_INVALID';
        const why = badKey
          ? 'The API key was not accepted.'
          : status === 404
            ? `The model name (${model}) may be wrong, or the model has been retired – check it in the AI settings (⚙).`
            : status === 429
              ? gem
                ? day
                  ? `${model} is over its limit for today${limit != null ? ` (${limit} requests a day)` : ''}. The free tier allows each model a number of requests per day, counted per project: go on when the service takes requests again, use a key from another person or project, or choose another model in the AI settings (⚙).`
                  : 'Too many requests: the free tier allows only a few requests per minute and per day – wait a minute and try again.'
                : 'Too many requests, or no credit left – try again in a minute.'
              : BUSY.includes(status)
                ? gem
                  ? `Google’s servers are busy for ${model} (“high demand”). That is on Google’s side, not a problem with your key: wait a minute and try again, or choose another model in the AI settings (⚙).`
                  : 'The service is busy or had a temporary problem – try again in a minute.'
                : '';
        return Object.assign(new Error(`HTTP ${status}. ${why} ${detail}`.trim()), { status, retryAfter, daily: !!day, limit });
      };
      try {
        arm();
        let r;
        if (s.provider === 'anthropic') {
          r = await fetch('https://api.anthropic.com/v1/messages', {
            method: 'POST',
            headers: { 'content-type': 'application/json', 'x-api-key': key, 'anthropic-version': '2023-06-01', 'anthropic-dangerous-direct-browser-access': 'true' },
            body: JSON.stringify({ model, max_tokens: 8000, system, messages, stream: true }),
            signal: ac.signal
          }).catch((e) => {
            throw lost(e);
          });
        } else if (gem) {
          // Google's Gemini API (generateContent, streamed as server-sent events); the whole conversation is sent each time
          r = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:streamGenerateContent?alt=sse`, {
            method: 'POST',
            headers: { 'content-type': 'application/json', 'x-goog-api-key': key },
            body: JSON.stringify({ system_instruction: { parts: [{ text: system }] }, contents: messages.map((m) => ({ role: m.role === 'assistant' ? 'model' : 'user', parts: [{ text: m.content }] })) }),
            signal: ac.signal
          }).catch((e) => {
            throw lost(e);
          });
        } else {
          r = await fetch(base + '/chat/completions', {
            method: 'POST',
            headers: Object.assign({ 'content-type': 'application/json' }, key ? { authorization: 'Bearer ' + key } : {}),
            body: JSON.stringify({ model, stream: true, messages: [{ role: 'system', content: system }].concat(messages) }),
            signal: ac.signal
          }).catch((e) => {
            throw lost(e);
          });
        }
        arm();
        if (!r.ok) {
          let j = null;
          try {
            j = await r.json();
          } catch (e) {
            if (signal && signal.aborted) throw stopped();
          }
          throw refused(r.status, j, r.statusText, r.headers.get('retry-after'));
        }
        const reader = r.body.getReader();
        const dec = new TextDecoder();
        let buf = '';
        for (;;) {
          const { value, done } = await reader.read().catch((e) => {
            throw lost(e);
          });
          if (done) break;
          arm();
          bytes += value.length;
          buf += dec.decode(value, { stream: true });
          let k;
          while ((k = buf.indexOf('\n')) >= 0) {
            const line = buf.slice(0, k).trim();
            buf = buf.slice(k + 1);
            if (!line.startsWith('data:')) continue;
            const data = line.slice(5).trim();
            if (!data || data === '[DONE]') continue;
            let j;
            try {
              j = JSON.parse(data);
            } catch (e) {
              continue;
            }
            if (s.provider === 'anthropic') {
              if (j.type === 'content_block_delta' && j.delta && j.delta.type === 'text_delta') onDelta(j.delta.text);
              else if (j.type === 'error') throw Object.assign(new Error((j.error && j.error.message) || 'stream error'), { status: j.error && j.error.type === 'overloaded_error' ? 529 : undefined });
            } else if (gem) {
              if (j.error) {
                // an error in an answer that began with "200 OK": the same kinds as the errors that come instead of an answer
                const code = +j.error.code || { UNAVAILABLE: 503, RESOURCE_EXHAUSTED: 429, INTERNAL: 500, DEADLINE_EXCEEDED: 504, NOT_FOUND: 404 }[j.error.status];
                throw code ? refused(code, j) : new Error(j.error.message || 'stream error');
              }
              if (j.promptFeedback && j.promptFeedback.blockReason) throw new Error('Gemini did not answer (' + j.promptFeedback.blockReason + ').');
              const cand = (j.candidates && j.candidates[0]) || {};
              ((cand.content && cand.content.parts) || []).forEach((p) => {
                if (p.text && !p.thought) onDelta(p.text);
              });
              // A reply that the service cut off as a "malformed function call": the model had begun its ```bash block,
              // and the service took the fence for the call of a tool named bash. What it took away is in finishMessage
              // ("Malformed function call: call:bash ```", the commands, "```") – the block goes back into the reply.
              if (cand.finishReason === 'MALFORMED_FUNCTION_CALL' && typeof cand.finishMessage === 'string') {
                const m = /call:\s*(?:bash|sh|shell)\s*```[^\n]*\n([\s\S]*?)\n?```\s*$/.exec(cand.finishMessage);
                if (m && m[1].trim()) onDelta('\n\n```bash\n' + m[1] + '\n```\n');
              }
            } else {
              const dd = j.choices && j.choices[0] && j.choices[0].delta;
              if (dd && dd.content) onDelta(dd.content);
            }
          }
        }
      } finally {
        clearTimeout(timer);
        if (signal) signal.removeEventListener('abort', onStop);
        ac.abort(); // (nothing is left to end when the answer came whole)
      }
    }

    /* ---------------- a prompt for another AI tool ---------------- */
    async buildPrompt(question, extra) {
      const q = question || this.input.value.trim() || '[write your question here]';
      const ctx = await this.contextFor(extra || {});
      return [
        'I am using a bioinformatics workbench that runs in the web browser: Jupyter-style notebooks in Python (Pyodide) and R (webR), and a bash-like terminal with bioinformatics programs compiled to WebAssembly.',
        ...envLines(),
        '',
        ctx.trim(),
        '',
        'My question: ' + q,
        '',
        'Please answer briefly, explain the code you give, and use only options and functions that really exist.'
      ].join('\n');
    }
    async copyPrompt(question, extra) {
      const text = await this.buildPrompt(question, extra);
      const ok = await MG.copyText(text);
      const m = MG.modal(
        'A prompt for another AI tool',
        `<p class="small">${ok ? '<b>Copied to the clipboard.</b> ' : ''}Paste it into an AI tool you are allowed to use, and check what it gives you. It describes the workbench and contains what is ticked under the assistant's box (the open notebook's code, your file names, your last commands) and your question – not your data. Read it before you paste it, and never paste personal or patient data into an AI tool.</p><textarea class="prompt-text" readonly aria-label="Prompt">${esc(text)}</textarea><div class="prompt-actions"><button class="btn" data-x="copy" type="button">${MG.icon('copy')}<span>Copy</span></button><button class="btn primary" data-x="ok" type="button">Done</button></div>`
      );
      m.box.querySelector('[data-x="copy"]').addEventListener('click', async () => toast((await MG.copyText(text)) ? 'Prompt copied.' : 'Could not copy – select the text and copy it yourself.', null, 2500));
      m.box.querySelector('[data-x="ok"]').addEventListener('click', () => m.close());
      bus.emit('ai:copyprompt', {});
    }

    /* ---------------- settings ---------------- */
    settingsDialog() {
      const s = this.settings;
      let remembered = false;
      try {
        remembered = !!window.sessionStorage.getItem(KEY_NAME);
      } catch (e) {
        remembered = false;
      }
      const html = `
<div class="ai-set">
  <p class="muted small">The assistant uses an AI service of your choice, with a key of your own (or one you have been given). Your messages – with what you tick under the box – go from your browser straight to that service.</p>
  <label>Service <select data-k="provider"><option value="gemini" ${s.provider === 'gemini' ? 'selected' : ''}>Google Gemini (free tier available)</option><option value="anthropic" ${s.provider === 'anthropic' ? 'selected' : ''}>Anthropic (Claude)</option><option value="openai" ${s.provider === 'openai' ? 'selected' : ''}>OpenAI-compatible service</option></select></label>
  <label data-show="gemini">Model <input data-k="geminiModel" value="${esc(geminiModelOf(s))}" spellcheck="false"></label>
  <p data-show="gemini" class="muted small">Make a free key with a Google account at <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">aistudio.google.com/apikey</a> (you must be 18 or over). On the free tier Google may use what you send to improve its products, and human reviewers may read it. Each model allows only a few requests per minute and a limited number per day; when a model is busy or over its limit, the page asks another one, and each answer says which model replied.</p>
  <label data-show="anthropic">Model <input data-k="model" value="${esc(anthropicModelOf(s))}" spellcheck="false"></label>
  <p data-show="anthropic" class="muted small">A key from the Claude Console, <a href="https://platform.claude.com/settings/keys" target="_blank" rel="noopener">platform.claude.com</a> (paid use).</p>
  <label data-show="openai">Base URL <input data-k="baseURL" value="${esc(s.baseURL)}" spellcheck="false"></label>
  <label data-show="openai">Model <input data-k="openaiModel" value="${esc(s.openaiModel)}" placeholder="the model name your service uses" spellcheck="false"></label>
  <p data-show="openai" class="muted small">Any service with an OpenAI-style <code>/chat/completions</code> API that allows requests from web pages (CORS) – a university service, or one on your own computer – with or without a key.</p>
  <label>API key <input data-k="key" type="password" value="${esc(this.key)}" autocomplete="off" spellcheck="false" placeholder="paste the key here"></label>
  <label class="ai-cb"><input type="checkbox" data-k="remember" ${remembered ? 'checked' : ''}> Keep the key until I close this browser tab (otherwise it is forgotten when the page is reloaded)</label>
  <label class="ai-cb"><input type="checkbox" data-k="agentWeb" ${s.agentWeb ? 'checked' : ''}> Let the agent use the internet (curl and wget in its commands)</label>
  <p class="muted small">The key is kept only in this browser tab – never in a file, and never in the browser's long-term storage. Never paste personal or patient data into an AI tool.</p>
  <div class="prompt-actions"><span class="ai-test-out muted small"></span><button class="btn" data-x="forget" type="button">Forget the key</button><button class="btn" data-x="test" type="button">Test</button><button class="btn primary" data-x="save" type="button">Save</button></div>
</div>`;
      const m = MG.modal('AI settings', html);
      const B = m.box;
      const val = (k) => B.querySelector(`[data-k="${k}"]`);
      const sync = () => {
        const p = val('provider').value;
        B.querySelectorAll('[data-show]').forEach((el) => (el.hidden = el.dataset.show !== p));
      };
      val('provider').addEventListener('change', sync);
      sync();
      // a model left at the site's default is saved as '' (= follow config.js)
      const own = (k, dflt) => {
        const v = val(k).value.trim().replace(/^models\//, '');
        return v && v !== dflt ? v : '';
      };
      const read = () => ({
        settings: { provider: val('provider').value, model: own('model', LIVE_DEFAULTS.model), geminiModel: own('geminiModel', LIVE_DEFAULTS.geminiModel), baseURL: val('baseURL').value.trim(), openaiModel: val('openaiModel').value.trim(), agentWeb: val('agentWeb').checked },
        key: val('key').value.trim()
      });
      B.querySelector('[data-x="test"]').addEventListener('click', async () => {
        const out = B.querySelector('.ai-test-out');
        const r = read();
        if (!r.key && needsKey(r.settings)) {
          out.textContent = 'Paste a key first.';
          return;
        }
        out.textContent = 'Testing…';
        let got = '';
        try {
          const res = await this.streamLive([{ role: 'user', content: 'Reply with the single word: ready' }], (d) => (got += d), undefined, Object.assign(r, { onReset: () => (got = '') }), (note) => (out.textContent = note));
          out.textContent = '✓ Connected: “' + got.trim().slice(0, 40) + '”' + (res.skipped.length ? ` – from ${res.model} (${res.skipped.map((x) => x.model + ' ' + skipWord(x)).join(', ')})` : '');
        } catch (e) {
          out.textContent = '✗ ' + e.message;
        }
      });
      B.querySelector('[data-x="forget"]').addEventListener('click', () => {
        val('key').value = '';
        val('remember').checked = false;
        this.key = '';
        try {
          window.sessionStorage.removeItem(KEY_NAME);
        } catch (e) {
          /* storage may be blocked */
        }
        this.renderMode();
        this.refreshIntro();
        B.querySelector('.ai-test-out').textContent = 'The key is forgotten.';
      });
      B.querySelector('[data-x="save"]').addEventListener('click', () => {
        const r = read();
        this.settings = r.settings;
        this.key = r.key;
        store.set('ai:settings', this.settings);
        try {
          if (val('remember').checked && this.key) window.sessionStorage.setItem(KEY_NAME, this.key);
          else window.sessionStorage.removeItem(KEY_NAME);
        } catch (e) {
          /* storage may be blocked */
        }
        this.renderMode();
        this.refreshIntro();
        this.renderCtx();
        m.close();
        if (!this.connected()) toast('Saved – add a key to use the assistant.', 'warn');
        else toast(`The assistant uses ${esc(modelOf(this.settings))}.`, 'ok', 2500);
        bus.emit('ai:settings', { provider: this.settings.provider });
      });
    }
  }

  MG.Assistant = Assistant;
  MG.aiModelMemory = REST;
  MG.aiUtil = { mdBlocks, shellCommands, shellCode, offlineHelp, envLines, programs };
})();
