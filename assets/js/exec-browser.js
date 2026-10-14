/* =====================================================================
   The browser backend: the programs of the terminal run in this page, compiled to WebAssembly – the Biowasm builds
   (one shared worker, Aioli, with one shared file system) and the genomics-wasm ports (featureCounts, Salmon, PLINK 2,
   Cutadapt, MACS3, LoFreq, SomaticSniper, Strelka2, Kraken2, Bracken, Prodigal, HMMER, bustools: each command in a
   worker of its own – threads-worker.mjs, python-worker.mjs). Registered with MG.exec (exec.js), which is how the rest
   of the workbench reaches it; the contract it fulfils is described in docs/execution-backends.md.

   One shared file system backs the terminal and the AI agent: before a program runs, the programs' file system is made
   the same as the page's (syncAll); afterwards what the program changed becomes part of the page's (importChanges).
   Pipes use byte-preserving temporary files (run one after another, not as concurrent processes). Aioli's local execIO
   patch binds real file descriptors and reports each exit status. A program of OWN_WORKER gets the files it needs, and
   what it writes comes back into the shared file system (see execWorker). lofreq somatic and Strelka's runWorkflow.py are
   workflows of several such commands (somatic.js), and so are Kraken2's and Bracken's commands, wrapper scripts
   upstream (metagenomics.js).
   ===================================================================== */
(function () {
  'use strict';
  const MG = window.MG;
  const FileRef = MG.FileRef;
  const ROOT = '/shared/vfs', TMP = ROOT + '/tmp/.pipes';
  // copies of files the AI agent could change (see keep): in the file system of the page, where no program looks
  const KEEP = '/keep';
  const TEXT_MAX = 262144;
  const CORE = ['cat','head','tail','wc','sort','uniq','cut','tr','tee','comm','join','paste','seq','fold','shuf','md5sum','date'];
  // While a command of the AI agent runs, the shell's file system notes every path that is worked out through it
  // (terminal.js: watched). What is done here looks at all files, whatever the command names: it uses the file system itself.
  const real=fs=>(fs&&fs.__real)||fs;
  /** The environment of a program, as NAME=value: the variables that the shell exports (export NAME, declare -x,
      NAME=value COMMAND, env NAME=value COMMAND) – awk's ENVIRON, jq's env and getenv() in every program see them,
      and LC_ALL=C means bytes to sort, grep, sed, wc and awk as it does on Linux. PWD and _ are there as bash sets
      them. Left out: TMPDIR when it names a folder outside the home folder (a program's own /tmp is not the /tmp of
      this terminal: sort would look for a folder that it cannot see). */
  function envOf(ctx,program,fs){
    const st=ctx.opts&&ctx.opts.st,vars=ctx.env||{},out=[],home=fs.home;
    const names=st&&st.exported?Array.from(st.exported):Object.keys(vars);
    let pwd=false;
    for(const k of names){
      let v=vars[k];
      // (a variable that a function declared local and gave no value: the program still gets the value from outside)
      if(v===undefined&&st&&st.locals&&st.locals.has(k))v=st.locals.get(k);
      if(typeof v!=='string'||k==='_'||!/^[A-Za-z_]\w*$/.test(k)||v.includes('\0'))continue;
      if(k==='TMPDIR'&&!(v===home||v.startsWith(home+'/')))continue;
      if(k==='PWD')pwd=true;
      // (cmp says "differ: byte 7" – and "char 7" where the language of the messages is C or POSIX; diff -c dates
      // its files "2024-03-05 12:34:56.000000000 +0000" – and "Tue Mar  5 12:34:56 2024" where the language of
      // times is C or POSIX. The C library of these builds takes C.UTF-8 for C in these respects, Linux's does
      // not: the two programs get the name of a language instead.)
      out.push(k+'='+((program==='cmp'||program==='diff')&&/^(LANG|LC_ALL|LC_MESSAGES|LC_TIME)$/.test(k)&&/^C\.utf-?8$/i.test(v)?'en_US.UTF-8':v));
    }
    if(!pwd&&(!st||!st.exported||st.exported.has('PWD')))out.push('PWD='+fs.cwd);
    if(ctx.shell&&ctx.shell.oldpwd&&(!st||!st.exported||st.exported.has('OLDPWD'))&&typeof vars.OLDPWD!=='string')out.push('OLDPWD='+ctx.shell.oldpwd);
    const name=String(ctx.name||program);
    if(!(st&&st.envEmptied))out.push('_='+(name.includes('/')?name:'/usr/bin/'+name));
    return out;
  }
  /* Programs that run as genomics-wasm built them, each command in a worker of its own: their modules are in
     assets/vendor/genomics-wasm/. threads: the program counts on several threads (Emscripten pthreads,
     SharedArrayBuffer), which needs a cross-origin isolated page. worker: the worker that runs it (Cutadapt is a
     Python program: its own worker starts the Python that comes with it). outputs: the options whose value the program
     writes (a file, or a folder) – it is not handed over (salmon quant -o OUT: OUT may hold the results of an earlier
     run). flow: a workflow of several commands, in place of one (lofreq somatic; Strelka's runWorkflow.py – somatic.js). */
  const OWN_WORKER={
    featurecounts:{name:'featureCounts',module:'featurecounts/2.1.1/featurecounts.mjs',threads:true,outputs:()=>['-o','--tmpDir']},
    salmon:{name:'salmon',module:'salmon/2.8.0/salmon.mjs',threads:true,outputs:a=>a[0]==='index'?['-i','--index','-o','--output','--tmpdir']:['-o','--output','--auxDir','--tmpdir']},
    cutadapt:{name:'cutadapt',module:'cutadapt/5.2/manifest.json',worker:'assets/js/python-worker.mjs',pyodide:'pyodide/314.0.7/',outputs:()=>['-o','--output','-p','--paired-output','--info-file','--rest-file','--wildcard-file','--too-short-output','--too-short-paired-output','--too-long-output','--too-long-paired-output','--untrimmed-output','--untrimmed-paired-output','--json']},
    lofreq:{name:'lofreq',module:'lofreq/2.1.5/lofreq.mjs',outputs:()=>['-o','--out','--outprefix'],flow:a=>a[0]==='somatic'&&MG.somatic?MG.somatic.lofreq:null},
    somaticsniper:{name:'bam-somaticsniper',module:'somaticsniper/1.0.5.0/somaticsniper.mjs',outputs:()=>[]},
    // Strelka's workflow script: python2 RUNDIR/runWorkflow.py (made by configureStrelkaSomaticWorkflow.py)
    strelka2:{name:'runWorkflow.py',module:'strelka2/2.9.10/strelka2.mjs',outputs:()=>[],flow:()=>MG.somatic&&MG.somatic.strelka},
    // Kraken2's commands (kraken2, kraken2-inspect, kraken2-build) and Bracken's (bracken, bracken-build and its three
    // programs): wrapper scripts upstream, run by the terminal – each program of theirs in a worker of its own
    // (metagenomics.js); Bracken's Python programs in the Python that comes with them, as Cutadapt's
    kraken2:{name:'kraken2',module:'kraken2/2.17.2/classify.mjs',outputs:()=>[],flow:()=>MG.metagenomics&&MG.metagenomics.kraken2},
    bracken:{name:'bracken',module:'bracken/3.1/manifest.json',worker:'assets/js/python-worker.mjs',pyodide:'pyodide/314.0.7/',outputs:()=>[],flow:()=>MG.metagenomics&&MG.metagenomics.bracken},
    // MACS3 (the peaks of ChIP-seq, ATAC-seq …): a Python program too, in the same Python – with NumPy, SciPy,
    // scikit-learn, pandas, h5py and AnnData (Pyodide's own packages, next to the shared Python) and the two wheels
    // compiled for it (hmmlearn, MACS3). Its options that name what it writes: --outdir, -o (one file; three for
    // bdgdiff, several for bdgcmp), --o-prefix, -n (the prefix of callpeak's and hmmratac's files) and --rfile
    // (prewarm: after a command, the next one's worker gets its Python ready in the background – see W.prewarm)
    macs3:{name:'macs3',module:'macs3/3.0.5/manifest.json',worker:'assets/js/python-worker.mjs',pyodide:'pyodide/314.0.7/',prewarm:true,outputs:()=>['--outdir','-o','--ofile','--o-prefix','-n','--name','--rfile']},
    // Prodigal (the genes of bacteria and archaea) and bustools (single-cell BUS files): one thread each, in any page.
    // Prodigal reads a genome from its standard input twice (it learns the genome's model first): see prodigalFlow
    prodigal:{name:'prodigal',module:'prodigal/2.6.3/prodigal.mjs',outputs:()=>PRODIGAL_OUTS,flow:()=>prodigalFlow},
    bustools:{name:'bustools',module:'bustools/0.45.1/bustools.mjs',outputs:()=>['-o','--output','-T','--temp']},
    // PLINK 2: threads even with --threads 1 (it reads its files on threads of their own), so a cross-origin isolated
    // page, as featureCounts and Salmon. Its inputs are often filesets named by a prefix: see plink2Flow
    plink2:{name:'plink2',module:'plink2/2.0.0-b.1-dev/plink2.mjs',threads:true,outputs:()=>['--out','-out'],flow:()=>plink2Flow}
  };
  // HMMER 3.4: thirteen programs, a module each (the SIMD of WebAssembly stands in for SSE2: every browser of the last
  // years has it). Their options that name a file they write:
  const HMMER=['hmmbuild','hmmsearch','hmmscan','hmmpress','hmmfetch','hmmalign','hmmconvert','hmmemit','hmmstat','phmmer','jackhmmer','nhmmer','nhmmscan'];
  const HMMER_OUTS=['-o','-A','-O','--tblout','--domtblout','--pfamtblout','--dfamtblout','--aliscoresout','--chkhmm','--chkali','--hmmout'];
  for(const p of HMMER)OWN_WORKER[p]={name:p,module:`hmmer/3.4/${p}.mjs`,outputs:()=>HMMER_OUTS};
  // Prodigal's options with a file it writes (-t: the training file is written when it is not there, and read when it is)
  const PRODIGAL_OUTS=['-o','-O','-a','-A','-d','-s','-S'];
  /* Prodigal and its standard input. In single-genome mode (no -p meta, no -t) Prodigal reads the genome twice – to learn
     its model, then to find the genes – so it rewinds its input: a file given with < it reads as it is, and a pipe it
     first copies into a file of the working folder (tmp.prodigal.stdin.PID; "Piped input detected, copying stdin to a
     tmp file...done!"), which it removes at the end. Its WebAssembly build sees a character device there (as a terminal
     is), and would print its help. So the terminal hands the input over as a file – outside the folders of the terminal
     – and says what Prodigal says for a pipe. (-i, -I: a file given; without input, Prodigal prints its help, as here.) */
  async function prodigalFlow(args,h){
    const T={name:'prodigal',module:'prodigal/2.6.3/prodigal.mjs'};
    const has=(...o)=>args.some(a=>o.includes(a)),val=(...o)=>{let v=null;args.forEach((a,i)=>{if(o.includes(a)&&i+1<args.length)v=args[i+1];});return v;};
    const mode=val('-p','-P'),train=val('-t','-T');
    const copy=!!(h.stdin&&!has('-i','-I')&&!(mode&&mode!=='single')&&train==null&&!has('-h','-H','-v','-V'));
    const STDIN='/.prodigal/stdin';
    const files=await h.inputsOf(args,PRODIGAL_OUTS);
    if(copy)files.push({path:STDIN,data:h.stdin});
    // (what Prodigal writes: below the working folder, and the folders of the files it is asked to write)
    const outs=[];args.forEach((a,i)=>{if(i+1<args.length&&(PRODIGAL_OUTS.includes(a)||((a==='-t'||a==='-T')&&!h.isFile(h.abs(args[i+1])))))outs.push(h.abs(args[i+1]));});
    const roots=[...new Set([h.cwd,...outs.map(p=>p.slice(0,p.lastIndexOf('/'))||'/')])];
    const r=await h.spawn(T,{args:copy?[...args,'-i',STDIN]:args,thisProgram:'prodigal',files,roots,dirs:roots.filter(d=>d==='/'||h.isDir(d)),stdin:copy?null:h.stdin});
    if(r.error)throw new Error(r.error);
    let stderr=r.stderr,order=r.order||[];
    if(copy&&h.stdinPipe&&!has('-q','-Q')){
      // after Prodigal's header (its first five lines): the lines of the copy, as on Linux
      const text=new TextDecoder().decode(stderr),head=text.split('\n').slice(0,5).join('\n')+'\n';
      if(text.startsWith(head)&&/^-+\nPRODIGAL v/.test(head)){
        const add=new TextEncoder().encode('Piped input detected, copying stdin to a tmp file...done!\n-------------------------------------\n');
        const at=new TextEncoder().encode(head).length,all=new Uint8Array(stderr.length+add.length);
        all.set(stderr.subarray(0,at));all.set(add,at);all.set(stderr.subarray(at),at+add.length);stderr=all;
        // (the header is in the first stretch of messages)
        if(order[0]===2&&order[1]>=at)order=[2,order[1]+add.length,...order.slice(2)];
      }
    }
    return {exitCode:r.exitCode,stdout:r.stdout,stderr,order,files:r.files,stdinPos:copy?h.stdin.length:r.stdinPos};
  }
  /* PLINK 2 and its files. Its inputs are often filesets named by a prefix: --pfile NAME reads NAME.pgen, NAME.pvar (or
     NAME.pvar.zst) and NAME.psam, --bfile NAME the PLINK 1 files NAME.bed, .bim and .fam – and so do --bpfile, --pmerge,
     --pgen-diff …; --pmerge-list FILE names filesets in a file (in the folder of --pmerge-list-dir, if given). The
     program is given every file that an argument names and, for an argument NAME, every file NAME.EXT of a fileset
     (PLINK_EXTS). It writes its files with the prefix of --out (plink2 without it) – PREFIX.log, PREFIX.afreq … – in the
     folder of the prefix; temporary files (PREFIX-temporary.pgen …) it removes itself. The paths are the terminal's: the
     log names the files and the working folder as they were typed. */
  const PLINK_EXTS=['pgen','pgen.pgi','pvar','pvar.zst','psam','bed','bim','bim.zst','fam','gen','gen.zst','sample','bgen','bgen.bgi'];
  // (an argument of PLINK 2 is an option when it starts with - and goes on with neither a digit nor a dot: -1 is a number)
  const plinkFlag=a=>a.length>1&&a[0]==='-'&&!/[\d.]/.test(a[1])?a.replace(/^--?/,''):null;
  async function plink2Flow(args,h){
    const T={name:'plink2',module:OWN_WORKER.plink2.module};
    let out='plink2',list=null,listDir='';
    args.forEach((a,i)=>{
      const f=plinkFlag(a),v=args[i+1];
      if(v==null||plinkFlag(v)!=null)return;
      if(f==='out')out=v;else if(f==='pmerge-list')list=v;else if(f==='pmerge-list-dir')listDir=v.replace(/\/?$/,'/');
    });
    // (and the files of modifiers: --glm local-covar=FILE, --freq refbins-file=FILE …)
    const words=[];
    args.forEach((a,i)=>{
      if(plinkFlag(a)!=null||(i&&plinkFlag(args[i-1])==='out'))return;
      words.push(a);
      if(a.indexOf('=')>0)words.push(a.slice(a.indexOf('=')+1));
    });
    // (the filesets that --pmerge-list names: a prefix, or the files of a fileset, on each line)
    if(list&&h.isFile(h.abs(list)))for(const w of (await h.readText(h.abs(list))).split(/\s+/).filter(Boolean))words.push(w.startsWith('/')?w:listDir+w);
    const files=await h.inputsOf([...words,...words.flatMap(w=>PLINK_EXTS.map(e=>`${w}.${e}`))],[]);
    const outDir=(p=>p.slice(0,p.lastIndexOf('/'))||'/')(h.abs(out));
    const roots=[...new Set([h.cwd,outDir])];
    const r=await h.spawn(T,{args,thisProgram:'plink2',files,roots,dirs:roots.filter(d=>d==='/'||h.isDir(d)),stdin:h.stdin});
    if(r.error)throw new Error(r.error);
    return {exitCode:r.exitCode,stdout:r.stdout,stderr:r.stderr,order:r.order||[],files:r.files,stdinPos:r.stdinPos};
  }
  // the index files that a program finds next to a file it is given (NAME.bam: NAME.bam.bai or NAME.bai; a FASTA file:
  // its .fai, and the .gzi of a compressed one; a compressed VCF or BED: its .tbi or .csi; HMMER's profiles: the four
  // files of hmmpress, and the SSI index of hmmfetch --index – of the pressed file, .h3m.ssi, when it is pressed) – handed
  // over with it
  const INDEX_SUFFIXES=['.bai','.csi','.crai','.fai','.gzi','.tbi','.h3m','.h3i','.h3f','.h3p','.ssi','.h3m.ssi'];
  // how long a worker made ready in advance (W.prewarm) waits for its command before it is stopped
  const SPARE_MS=15*60*1000;
  const W = {
    ready:false, loading:null, cli:null, pipeN:0, mountN:0,
    synced:new Map(), placed:new Map(), managed:new Set(), dirs:new Set(), gone:[], denied:[], refused:[],
    gen:0, kept:new Map(), keepN:0,
    versions:{fastp:'0.20.1',minimap2:'2.22',bowtie2:'2.4.2',bwa:'0.7.19','bwa-mem2':'2.2.1',hisat2:'2.2.2',freebayes:'1.3.6',stringtie:'3.0.3',kallisto:'0.52.0',mosdepth:'0.3.14',featurecounts:'2.1.1',salmon:'2.8.0',cutadapt:'5.2',macs3:'3.0.5',lofreq:'2.1.5',somaticsniper:'1.0.5.0',strelka2:'2.9.10',kraken2:'2.17.2',bracken:'3.1',prodigal:'2.6.3',hmmer:'3.4',bustools:'0.45.1',plink2:'2.0.0-b.1-dev',samtools:'1.17',bcftools:'1.10',htslib:'1.17',seqtk:'1.4',bedtools:'2.31.0',jq:'1.7',gawk:'5.1.0',grep:'3.7',sed:'4.8',coreutils:'8.32',diffutils:'3.10',kalign:'3.3.1',muscle:'3.8.1551',fasttree:'2.1.11','seq-align':'2017.10.18',wgsim:'0.3.1-r13',gffread:'0.12.7',lastz:'1.04.52'},
    apath(abs) { return ROOT+abs; },
    ensure(status) {
      if(this.ready)return Promise.resolve(this.cli);
      if(this.loading)return this.loading;
      const base=new URL(MG.config.biowasmBase||'assets/vendor/biowasm',location.href).href.replace(/\/$/,'');
      this.loading=(async()=>{
        if(!window.Aioli)await loadScript(base+'/aioli.js');
        status?.('Starting the local WebAssembly filesystem…');
        // 'base' holds the shared file system and never runs a program: a tool that aborts is replaced without losing the files
        const specs=[['base','1.0.0'],['samtools','1.17'],['bcftools','1.10'],['htslib','1.17','bgzip'],['htslib','1.17','tabix'],['minimap2','2.22'],['bowtie2','2.4.2','bowtie2-align-s'],['bowtie2','2.4.2','bowtie2-build-s'],['bwa','0.7.19'],['bwa-mem2','2.2.1'],['hisat2','2.2.2'],['freebayes','1.3.6'],['stringtie','3.0.3'],['kallisto','0.52.0'],['mosdepth','0.3.14'],['fastp','0.20.1'],['seqtk','1.4'],['bedtools','2.31.0'],['jq','1.7'],['gawk','5.1.0'],['grep','3.7'],['grep','3.11','grep-perl'],['sed','4.8'],['diffutils','3.10','diff'],['diffutils','3.10','cmp'],['kalign','3.3.1'],['muscle','3.8.1551'],['fasttree','2.1.11'],['seq-align','2017.10.18','needleman_wunsch'],['seq-align','2017.10.18','smith_waterman'],['seq-align','2017.10.18','lcs'],['wgsim','2011.10.17'],['gffread','0.12.7'],['lastz','1.04.52'],...CORE.map(p=>['coreutils','8.32',p])];
        const tools=specs.map(([tool,version,program])=>({tool,version,program:program||tool,urlPrefix:`${base}/${tool}/${version}`,loading:'lazy',features:{}}));
        this.cli=await new window.Aioli(tools,{printInterleaved:false,urlCDN:base,debug:false});
        await mkdirp(this.cli,TMP); await mkdirp(this.cli,KEEP); this.ready=true; MG.bus.emit('wasm:ready',{}); return this.cli;
      })().catch(e=>{this.loading=null;throw e;});
      return this.loading;
    },
    // (decoded here, not by the programs' file system: that one stops at the first NUL byte – find -print0 | sort -z)
    async textAt(p){return new TextDecoder('utf-8',{ignoreBOM:true}).decode(await (await this.ensure()).fs.readFile(p));},
    async bytesAt(p){return (await this.ensure()).fs.readFile(p);},
    /* how many bytes a file of the programs holds (what one program wrote for the next) */
    async sizeAt(p){const s=await stat(await this.ensure(),p);return s?s.size:0;},
    async readTextSmart(p){return this.textAt(p);},
    async stat(p){return stat(await this.ensure(),p);},
    /* known: what is in the programs' file system (see snapshot) – asked once for all files, not once per file. */
    async syncIn(fs,abs,known){
      fs=real(fs);
      const e=fs.entries.get(abs), cli=this.cli, dest=this.apath(abs);
      if(!e)return;
      // (what is under ROOT, and no file of a pipe, is in the list – or is not there)
      const look=p=>known&&p.startsWith(ROOT+'/')&&!p.startsWith(TMP)?Promise.resolve(known.get(p)||null):stat(cli,p);
      const folder=async d=>{
        if(known&&(d===ROOT||(known.get(d)||{}).isDir))return;
        await mkdirp(cli,d);
        if(known)for(let q=d;q.length>ROOT.length;q=MG.path.dirname(q))known.set(q,{size:0,mtime:0,isDir:true,sig:''});
      };
      if(e.kind==='dir'){await folder(dest);this.dirs.add(abs);return;}
      await folder(MG.path.dirname(dest));
      // a folder of that name that is still there (it could not be removed) must not stop every later program
      const there=await look(dest);
      if(there&&there.isDir){await rmtree(cli,dest);if(known)known.delete(dest);}
      if(e.kind==='virtual')throw MG.shellUtil.userErr('This lab requires actual file bytes; simulated files cannot be processed.');
      const prior=this.synced.get(abs);
      // a read-only file is read-only for the programs too (they get "Permission denied")
      const locked=!!(e.readonly||e.protected);
      // (the file keeps the time of its last change: diff -u and diff -c print it. Last of all: in this file system
      // a change of the permissions sets the time, too)
      const stamp=async()=>{if(e.mtime)try{await cli.fs.utime(dest,e.mtime,e.mtime);}catch(x){}};
      const write=async data=>{if(await stat(cli,dest))await cli.fs.chmod(dest,0o644);await cli.fs.writeFile(dest,data);if(locked)await cli.fs.chmod(dest,0o444);await stamp();};
      if(e.kind==='text'){
        if(prior!==e||e.dirty||!(await look(dest))){await write(e.text);e.dirty=false;}
      }else if(e.kind==='aioli'){
        if(prior!==e||e.apath!==dest){
          if(!(await look(e.apath))){
            // its bytes are gone: a name without contents must not stay behind (every later program would stop)
            fs.entries.delete(abs);fs._changed(abs,'remove');this.synced.delete(abs);this.managed.delete(abs);this.gone.push(abs);return;
          }
          if(e.apath!==dest){await write(await cli.fs.readFile(e.apath));e.apath=dest;}
          else{await cli.fs.chmod(dest,locked?0o444:0o644);await stamp();}
        }
      }else if(e.kind==='url'||e.kind==='blob'){
        // the course data is copied in as real bytes
        if(prior!==e||!(await look(dest)))await write(await fs.readBytes(abs));
      }else throw MG.shellUtil.userErr(`Unsupported file entry: ${e.kind}`);
      this.synced.set(abs,e);this.managed.add(abs);
    },
    /* A file that was copied or moved (cp, mv) still has its bytes at the old place, until a program
       needs it. settle gives every such file its own bytes: all of them are read first, then written –
       so that it does not matter in which order they are, or what else is written to the old places.
       between() runs after the reading and before the writing. */
    async settle(fs,between){
      fs=real(fs);
      const cli=this.cli,moved=[];
      for(const [abs,e] of Array.from(fs.entries))if(e.kind==='aioli'&&e.apath!==this.apath(abs)){
        if(await stat(cli,e.apath))moved.push([abs,e,await cli.fs.readFile(e.apath)]);
        else{fs.entries.delete(abs);fs._changed(abs,'remove');this.gone.push(abs);}
      }
      if(between)await between();
      for(const [abs,e,bytes] of moved){
        if(fs.entries.get(abs)!==e)continue;
        const dest=this.apath(abs);
        await place(cli,dest,bytes);e.apath=dest;this.noteDirs(abs);
        if(e.readonly||e.protected)await cli.fs.chmod(dest,0o444);
        this.synced.set(abs,e);this.managed.add(abs);
      }
    },
    /** the folders above abs exist in the programs' file system: remember them (syncAll removes those the page no longer has) */
    noteDirs(abs){for(let d=MG.path.dirname(abs);d&&d!=='/';d=MG.path.dirname(d))this.dirs.add(d);},
    /* Make the programs' file system the same as the page's.
       1. Copied and moved files get their own bytes (settle).
       2. In between: files that are no longer there are removed – and folders too, deepest first.
          (Left there, a folder that was removed with rm -r would come back, empty, after the next
          program.) The programs first leave the folder they were in: a folder cannot be removed while
          it is somebody's working directory.
       3. Everything else is brought up to date. */
    async syncAll(fs){
      fs=real(fs);
      const cli=this.cli;
      await this.settle(fs,async()=>{
        await cli.cd(ROOT);
        for(const abs of Array.from(this.managed)){
          const e=fs.entries.get(abs);
          if(!e||e.kind==='dir'){
            try{await cli.fs.unlink(this.apath(abs));}catch(x){}
            this.managed.delete(abs);this.synced.delete(abs);
          }
        }
        for(const abs of Array.from(this.dirs).sort((a,b)=>b.length-a.length))if(!fs.isDir(abs)){
          try{await cli.fs.rmdir(this.apath(abs));}catch(x){}
          this.dirs.delete(abs);
        }
      });
      // (what is there now: one answer for the whole tree)
      const known=await this.snapshot();
      for(const [abs] of Array.from(fs.entries))await this.syncIn(fs,abs,known);
    },
    /* ---- for the AI agent: what it changes outside its own folder is put back (assistant.js) ----
       A file of kind 'aioli' has its bytes only here, in the programs' memory. Before a command of the
       agent runs, each such file outside the agent's folder is copied (once per run of the agent);
       putBack writes the copy back where a command changed or removed the file. */
    async keep(list){
      if(!this.ready)return 0;
      const cli=this.cli;let n=0;
      for(const [,e] of list){
        if(e.kind!=='aioli')continue;
        const had=this.kept.get(e);
        if(had&&had.gen===this.gen)continue;
        const s=await stat(cli,e.apath);
        if(!s||s.isDir)continue;
        const path=`${KEEP}/${++this.keepN}`;
        await cli.fs.writeFile(path,await cli.fs.readFile(e.apath));
        this.kept.set(e,{path,sig:s.size+':'+s.mtime,gen:this.gen});n++;
      }
      return n;
    },
    /** the entry e is at abs in the page's file system again: make sure its bytes are there too.
        since: when the command started (ms). → false: the bytes are lost */
    async putBack(abs,e,since){
      if(!this.ready)return false;
      const cli=this.cli,dest=this.apath(abs),now=await stat(cli,e.apath);
      let k=this.kept.get(e);if(k&&k.gen!==this.gen)k=null;
      // untouched: the file is as it was when the copy was made. (Without a copy: there, of the size the
      // entry records, and not written since the command started.)
      const same=!!now&&!now.isDir&&(k?now.size+':'+now.mtime===k.sig:now.size===e.size&&(!since||now.mtime<since));
      if(!same&&!k)return false;
      const moved=!same||e.apath!==dest;
      if(moved){await place(cli,dest,await cli.fs.readFile(same?e.apath:k.path));e.apath=dest;this.noteDirs(abs);}
      await cli.fs.chmod(dest,e.readonly||e.protected?0o444:0o644);
      // (the time of the file changes with chmod: the mark of "untouched" is taken afterwards)
      if(k){const s=await stat(cli,dest);k.sig=s.size+':'+s.mtime;}
      this.synced.set(abs,e);this.managed.add(abs);
      return true;
    },
    async dropKept(){
      const all=Array.from(this.kept.values());this.kept.clear();
      if(!this.ready)return;
      for(const k of all)if(k.gen===this.gen)try{await this.cli.fs.unlink(k.path);}catch(x){}
    },
    /* everything in the programs' file system (but the files of pipes): path → {size, mtime, isDir, sig}. The
       worker answers for the whole tree at once (statTree, a local addition to aioli.js): asked file by file,
       a folder of a thousand files made every program take a second longer. */
    async snapshot(){
      const out=new Map();
      for(const [p,size,mtime,isDir] of await this.cli.statTree(ROOT,'.pipes'))out.set(p,{size,mtime,isDir,sig:size+':'+mtime});
      return out;
    },
    /* A file that a program wrote joins the page's file system. A small text file (a table, a log,
       a JSON report, an edited script) becomes an ordinary text file: it can be edited and is saved
       with the student's work. Anything else (BAM, .gz, large files) stays in the programs' memory. */
    async adopt(fs,abs,apath,size,bytes,like){
      fs=real(fs);
      const there=fs.get(abs),was=there&&there.kind!=='dir'?there:(like||null),keep={};
      // (a file that took the place of a read-only one is read-only, too: sed -i gives the new file the old one's permissions.
      // like: the file that a program renamed to this name – it keeps its permissions under the new name, see importChanges)
      if(was&&was.kind!=='dir'){if(was.mode)keep.mode=was.mode;if(was.perm!=null)keep.perm=was.perm;if(was.readonly&&!was.protected)keep.readonly=true;}
      let text=null;
      if(size<=TEXT_MAX){
        try{
          if(!bytes)bytes=await this.cli.fs.readFile(apath);
          const t=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(bytes);
          if(t.indexOf('\u0000')<0)text=t;
        }catch(e){text=null;}
      }
      // (its time is the time at which the program wrote it)
      const made=await stat(this.cli,apath);if(made&&made.mtime)keep.mtime=made.mtime;
      if(text!=null){fs.put(abs,Object.assign({kind:'text',text,fresh:true},keep));fs.get(abs).dirty=false;}
      else fs.put(abs,Object.assign({kind:'aioli',apath,size,fresh:true},keep));
      this.synced.set(abs,fs.get(abs));this.managed.add(abs);
    },
    /* what a program changed in the WebAssembly file system becomes part of the page's file system.
       A file of the course data that a program changed or removed is put back (the folder is not the student's).
       A read-only file of the student's own is another matter: the programs cannot write into it (it has mode 444
       in their file system: "Permission denied"), but a program may put a new file in its place or remove it
       – sed -i, gzip, bgzip do: that takes a folder one may write to, as on Linux.
       The inputs of an agent's run (~/runs/N-…/data/NAME: read-only copies of the course data) are such files:
       an agent can replace its own copies, and the script made from the run does the same – which is why the
       practical tests a script on a fresh copy of the course data. */
    async importChanges(fs,before){
      fs=real(fs);
      const after=await this.snapshot(),created=[];this.denied=[];this.refused=[];
      const guarded=abs=>{const e=fs.get(abs);return !!e&&e.kind!=='aioli'&&e.kind!=='dir'&&!!e.protected;};
      // A new name in a folder of the example data (samtools faidx /data/examples/…/x.fasta writes x.fasta.fai next to
      // it): those folders take nothing new – see refusesNew in vfs.js. It is removed again, and the run says so
      // (refused). (What was there before the program ran and is unchanged is a leftover: removed without a word.)
      const out=[],underOut=abs=>out.some(r=>abs.startsWith(r+'/'));
      // A file that a program renamed – sed -i.bak: FILE becomes FILE.bak, and a new FILE is written – keeps its
      // permissions under the new name, as on Linux. The programs' file system does not hold them (the page does), so
      // a renamed file is told by what a rename leaves as it was, its size and its time: a name that is new and has the
      // size and time that another file had before the program ran – a file that is gone now, or has changed. Where
      // several files had that size and time (three files written by one loop), the names decide: FILE.bak begins with
      // FILE, and a backup in a folder of its own (sed -i'bak/*') has the name of its file.
      const moved=new Map();
      for(const [p,s] of before){if(s.isDir)continue;const now=after.get(p);if(!now||now.isDir||now.sig!==s.sig){if(!moved.has(s.sig))moved.set(s.sig,[]);moved.get(s.sig).push(p.slice(ROOT.length));}}
      const last=x=>x.slice(x.lastIndexOf('/')+1);
      const renamedFrom=(old,s,abs)=>{
        const c=old?null:moved.get(s.sig);
        if(!c)return null;
        const from=c.filter(q=>abs.length>q.length&&abs.startsWith(q)).sort((a,b)=>b.length-a.length)[0]||c.find(q=>last(q)===last(abs))||(c.length===1?c[0]:null);
        const e=from?fs.get(from):null;
        return e&&e.kind!=='dir'&&!e.protected?e:null;
      };
      for(const [p,s] of after){
        const abs=p.slice(ROOT.length), old=before.get(p);
        if(underOut(abs))continue;
        if(fs.refusesNew(abs)){out.push(abs);if(!old||(!s.isDir&&old.sig!==s.sig))this.refused.push(abs);continue;}
        if(s.isDir){
          this.dirs.add(abs);
          if(!fs.exists(abs))fs.mkdirp(abs);
          // (a program that made, renamed or removed a name in a folder – sed -i does all three – has changed the folder:
          // its time moves on, as on Linux; see _dirTouched in vfs.js)
          else if(old&&s.mtime>old.mtime){const d=fs.entries.get(abs);if(d&&d.kind==='dir'&&s.mtime>(d.mtime||0))d.mtime=s.mtime;}
          continue;
        }
        if(old&&old.sig===s.sig)continue;
        if(guarded(abs)){this.denied.push(abs);this.synced.delete(abs);continue;}
        await this.adopt(fs,abs,p,s.size,undefined,renamedFrom(old,s,abs));created.push(abs);
      }
      for(const [p,s] of before)if(!s.isDir&&!after.has(p)){
        const abs=p.slice(ROOT.length);
        if(guarded(abs)){this.denied.push(abs);this.synced.delete(abs);continue;}
        fs.remove(abs);this.managed.delete(abs);
      }
      for(const abs of out){
        const p=ROOT+abs;
        try{const st=await stat(this.cli,p);if(st&&st.isDir)await rmtree(this.cli,p);else if(st)await this.cli.fs.unlink(p);}catch(x){}
      }
      return created;
    },
    /* Bytes that the shell has in hand (what a block printed: { samtools view -b …; } > x.bam, f | samtools …):
       writeBytes makes them a file of the page; tempBytes a file for the next command of a pipe to read. */
    async writeBytes(fs,abs,bytes){
      fs=real(fs);
      // (nothing new in a folder of the example data – refused before anything is written)
      if(fs.refusesNew(abs))fs._refuseNew(abs);
      const cli=await this.ensure(),dest=this.apath(abs);
      // (a file that was copied or moved – cp, mv – may still have its bytes at this very place: see settle.
      // Each such file gets its own bytes before anything is written here.)
      await this.settle(fs);
      await mkdirp(cli,MG.path.dirname(dest));
      const there=await stat(cli,dest);
      if(there&&there.isDir)await rmtree(cli,dest);else if(there)await cli.fs.chmod(dest,0o644);
      await cli.fs.writeFile(dest,bytes);
      await this.adopt(fs,abs,dest,bytes.length,bytes);
      this.noteDirs(abs);
    },
    async tempBytes(bytes,binary){
      const cli=await this.ensure(),path=`${TMP}/i${++this.pipeN}`;
      await cli.fs.writeFile(path,bytes);
      return new FileRef(path,!!binary);
    },
    /* a file of a pipe that is still needed (the input of a block or a script that runs several programs) is not
       tidied away: see cleanupPipes */
    held:new Map(),
    hold(ref){const p=ref.handle;this.held.set(p,(this.held.get(p)||0)+1);},
    release(ref){const p=ref.handle,n=(this.held.get(p)||0)-1;if(n>0)this.held.set(p,n);else this.held.delete(p);},
    /* one WebAssembly program at a time */
    lock:Promise.resolve(),
    async run(ctx,program,args,opts={}){
      let release;const prev=this.lock;this.lock=new Promise(r=>(release=r));
      await prev;
      try{return await this._run(ctx,program,args,opts);}finally{release();}
    },
    async _run(ctx,program,args,opts={}){
      const start=performance.now(),fs=real(ctx.fs);
      // … but the arguments that name a file or a folder that is there are paths the command uses: they are noted.
      // (A pattern or a program – /^#/d, /human_CYP2C19/ – names none. A file that the command makes is seen
      // afterwards, when the page looks at what has changed.)
      if(ctx.fs!==fs){
        const kinds=MG.shellLang&&MG.shellLang.argKinds?MG.shellLang.argKinds(ctx.name||program,args):[];
        args.forEach((v,i)=>{
          const m=/^--[^=]+=(.+)$/.exec(v),w=m?m[1]:v;
          if(kinds[i]!=='skip'&&w&&!w.startsWith('-')&&fs.exists(w))ctx.fs.resolve(w);
        });
      }
      const status=s=>{if(ctx.term?.statusEl)ctx.term.statusEl.textContent=s;};
      await this.ensure(status);this.gone=[];await this.syncAll(fs);
      const cli=this.cli;let stdin=null,inherit=null;
      if(ctx.stdin instanceof FileRef)stdin=ctx.stdin.handle;
      else if(ctx.stdin!=null){
        if(typeof ctx.stdin!=='string')throw MG.shellUtil.userErr('Only real byte streams can enter a tool.');
        stdin=`${TMP}/i${++this.pipeN}`;await cli.fs.writeFile(stdin,ctx.stdin);
      }else if(ctx.inherit&&ctx.inherit.pos<ctx.inherit.text.length){
        // No input of its own: the program stands in a block, a function or a script that has one
        // ({ head -n 1; sort; } < FILE,  f() { wc -l; }; f < FILE,  while read x; do PROGRAM; done < FILE).
        // It gets what is left of that input, and afterwards the page looks at how much of it the program read:
        // a program that does not read leaves it to the commands after it. From the start of a file the program
        // gets the file itself (byte for byte); otherwise the rest of the text.
        inherit=ctx.inherit;
        const own=inherit.pos===0?(inherit.handle||(inherit.path&&fs.exists(inherit.path)&&!fs.isDir(inherit.path)?this.apath(inherit.path):null)):null;
        if(own&&await stat(cli,own))stdin=own;
        else{stdin=`${TMP}/i${++this.pipeN}`;await cli.fs.writeFile(stdin,inherit.text.slice(inherit.pos));}
        inherit.size=((await stat(cli,stdin))||{}).size||0;
      }
      await this.cleanupPipes(fs,stdin);
      // Paths in the student's home and in the example data are given to the programs as typed: each program has the
      // links /home/user (the home folder) and /data -> the shared folder (see links below), and prints the names it was given (in the
      // @PG lines of SAM files, the headers of VCF files). Other absolute paths (/tmp/…) are in the shared folder under ROOT.
      const home=fs.home,inHome=p=>p===home||p.startsWith(home+'/'),inData=p=>p==='/data'||p.startsWith('/data/');
      // (a path below /home/student – the home folder until October 2026 – is one below the home folder: see vfs.js)
      const pathToken=p=>(p=MG.VFS.unalias(fs,p),p.startsWith(ROOT)||p.startsWith('/dev/')||inHome(p)||(inData(p)&&p===MG.path.norm(p))?p:(p.startsWith('/')?this.apath(MG.path.norm(p)):p));
      // What is no path goes to the program as it was typed: a pattern (grep /tmp, awk '/chr1/'), a set of characters
      // (tr / _), a delimiter (cut -d /). Of the rest, absolute paths and absolute output destinations are rewritten.
      const kinds=MG.shellLang&&MG.shellLang.argKinds?MG.shellLang.argKinds(ctx.name||program,args):args.map(()=>'path');
      const stdoutPath=`${TMP}/o${++this.pipeN}`,stderrPath=`${TMP}/e${this.pipeN}`;
      // /dev/stdin, /dev/stdout and /dev/stderr as arguments (sort /dev/stdin, samtools sort -o /dev/stdout): the files
      // that are the program's input and output here. (In what the program prints they get their names back.)
      const dev={'/dev/stdin':()=>stdin||'/dev/null','/dev/fd/0':()=>stdin||'/dev/null','/dev/stdout':()=>stdoutPath,'/dev/fd/1':()=>stdoutPath,'/dev/stderr':()=>ctx.mergeStderr?stdoutPath:stderrPath,'/dev/fd/2':()=>ctx.mergeStderr?stdoutPath:stderrPath};
      const devUsed=new Map();
      // An operand that names nothing because of the way it is written – "FILE/", "nosuch/../x" (see VFS.forShell):
      // the programs' file system would take the dots and the slash away and find the file. So the program is given a
      // name in a folder that is not there (it can neither read nor make anything under it), and in what it prints the
      // name that was typed is put back (the same way as for /dev/stdin, see named below).
      let nowhere=0;const notDir=[];
      // (the shell is in a folder that was removed – a script after  rm -rf "$PWD" : the program cannot be started
      // there. An operand that names something that is there – ../a.txt – is handed over with its whole path.)
      const adrift=!fs.isDir(fs.cwd);
      const a=args.map((v,i)=>{
        if(kinds[i]==='skip')return v;
        if(adrift&&v&&!v.startsWith('-')&&!v.startsWith('/')&&v.includes('/')){const abs=ctx.fs.resolve(v);if(fs.entries.has(abs)){const full=pathToken(abs);devUsed.set(full,v);return full;}}
        if(v.includes('/')&&!v.startsWith('-')&&ctx.fs.pathError&&ctx.fs.pathError(v)){const fake=`.no-such-folder-${++nowhere}/x`;devUsed.set(fake,v);if(ctx.fs.pathError(v)==='Not a directory')notDir.push(v);return fake;}
        const d=/^(-[A-Za-z]|--[^=]+=)?(\/dev\/(?:stdin|stdout|stderr|fd\/[012]))$/.exec(v);
        if(d&&!(d[1]&&/^-[A-Za-z]$/.test(d[1])&&MG.shellLang&&MG.shellLang.optionSkips&&MG.shellLang.optionSkips(ctx.name||program,d[1]))){const real=dev[d[2]]();if(real!=='/dev/null')devUsed.set(real,d[2].replace('/dev/fd/0','/dev/stdin').replace('/dev/fd/1','/dev/stdout').replace('/dev/fd/2','/dev/stderr'));return (d[1]||'')+real;}
        if(v.startsWith('/')&&(fs.exists(v)||fs.isDir(MG.path.dirname(v))))return pathToken(v);
        // -o/tmp/x.bam, -f/tmp/patterns.txt: a path glued to its option (not the value of an option that takes a
        // pattern or a delimiter: -F/, -d/, -e/x/d)
        const o=/^(-[A-Za-z])(\/[^/]+\/.*)$/.exec(v);
        if(o&&!(MG.shellLang&&MG.shellLang.optionSkips&&MG.shellLang.optionSkips(ctx.name||program,o[1]))&&(fs.exists(o[2])||fs.isDir(MG.path.dirname(o[2]))))return o[1]+pathToken(o[2]);
        const m=/^(--[^=]+=)(\/.*)$/.exec(v);return m?m[1]+pathToken(m[2]):v;
      });
      if(ctx.mergeStderr)await cli.fs.writeFile(stdoutPath,'');
      // date -u, TZ=UTC date, TZ=America/New_York date: the clock of that zone (the programs take the time zone from the
      // browser, and no notice of TZ); and the short name of the time zone (BST), as date prints it on Linux.
      // The same for awk's strftime and mktime, and for the times of the files in the headers of diff -u and diff -c.
      let clock={};
      if(program==='date'||program==='gawk'||program==='diff'){
        const tz=ctx.env&&typeof ctx.env.TZ==='string'&&(!(ctx.opts&&ctx.opts.st&&ctx.opts.st.exported)||ctx.opts.st.exported.has('TZ'))?ctx.env.TZ:null;
        let zone=MG.time.zoneOf(ctx);
        if(program==='date'&&dateUTC(args))zone='UTC';
        if(tz&&!zone)ctx.io.note(`${ctx.name||program}: the time zone ${tz} (TZ) is not known in this browser – the time is that of this computer's zone`);
        clock={zoneName:true,zone:zone||null};
      }
      // sed in a block whose input is a file ({ sed 1q; cat; } < FILE): what sed did not use is left for the next command.
      // On Linux the C library puts the rest back when sed ends; here sed is handed its input a line at a time.
      const lines=program==='sed'&&!!inherit&&!inherit.pipe;
      // wc sets the width of its columns by what its input is: 7 for a pipe ("cat f | wc" →  "      3       3      17"),
      // the digits of the size for a file ("wc < f" → " 3  3 17"). Here a pipe is a file too – so wc is told. (bash
      // hands a here-document over as a pipe when it has 64 KiB at most, as a file when it has more.)
      // (… and Prodigal, which copies a pipe into a file before it reads it: see prodigalFlow)
      const piped=stdin!=null&&(ctx.stdin instanceof FileRef?(!ctx.stdin.fromFile||!!ctx.stdin.psub):ctx.stdin!=null?!(ctx.hereInput&&new Blob([ctx.stdin]).size>65536):!!(inherit&&inherit.pipe));
      const fifo=program==='wc'&&piped;
      const before=await this.snapshot();await cli.cd(this.apath(fs.isDir(fs.cwd)?fs.cwd:fs.home));
      status(`${program} is running locally…`);
      // (a workflow says which of its programs runs: lofreq somatic – lofreq call · 12 s)
      const timer=setInterval(()=>status(`${this.running||program}${this.stage?' – '+this.stage:''} · ${((performance.now()-start)/1000).toFixed(0)} s`),1000);
      let result;
      const killed=new Promise((_,reject)=>{this._killed=reject;});
      this.running=OWN_WORKER[program]?(ctx.name||OWN_WORKER[program].name):program;
      const job=OWN_WORKER[program]?this.execWorker(program,a,{stdin,stdout:stdoutPath,stderr:stderrPath,merge:!!ctx.mergeStderr,fs,before,name:ctx.name,io:ctx.io,flowOpts:opts.flow,devUsed,piped})
        :cli.execIO(program,a,{stdin,stdout:stdoutPath,stderr:ctx.mergeStderr?stdoutPath:stderrPath,merge:!!ctx.mergeStderr,links:[[this.apath(home),home],[this.apath('/data'),'/data']],lines,fifo,env:envOf(ctx,program,fs),...clock});
      try{result=await Promise.race([job,killed]);}
      catch(e){
        // not a forced stop (then there is nothing left to look at): the page's file system must still learn what was written.
        // No program is running any more: a forced stop that came now would end the worker under this very call.
        this._killed=null;this.running=null;
        if(this.ready&&this.cli===cli)try{await this.importChanges(fs,before);}catch(x){}
        throw e;
      }finally{clearInterval(timer);this._killed=null;this.running=null;}
      if(inherit){
        // how far the program read: in a file, where it left off (head -n 1 goes back behind the first line);
        // in what came through a pipe, the furthest byte it took
        const n=devUsed.has(stdin)?Infinity:inherit.pipe?Math.max(result.stdinMax||0,result.stdinPos||0):(result.stdinPos||0);
        if(n>0){
          // (n bytes of the file are so many characters of the text)
          const t=inherit.text;let k=inherit.pos,b=0;
          if(n>=inherit.size)k=t.length;
          else while(k<t.length&&b<n){const c=t.codePointAt(k);b+=c<0x80?1:c<0x800?2:c<0x10000?3:4;k+=c>0xffff?2:1;}
          inherit.pos=k;
        }
      }
      const created=await this.importChanges(fs,before);
      if(ctx.mergeStderr){
        // 2>&1: what the program wrote to stderr is in the output file – tidy it like stderr (see tidy)
        const st=await stat(cli,stdoutPath);
        if(st&&st.size&&st.size<=1048576)try{
          const t=new TextDecoder('utf-8',{fatal:true}).decode(await this.bytesAt(stdoutPath)),t2=tidy(t,ctx.name||program);
          if(t2!==t)await cli.fs.writeFile(stdoutPath,t2);
        }catch(e){}
      }
      // (a file that stood for /dev/stdin … is called that again in what the program printed – also as a workflow
      // names it, with the terminal's path: bracken -o /dev/stdout)
      // (… and of a name that asks for a folder where a file is – "a.txt/", "a.txt/../x" – the program is told, in
      // Linux's words, why it was not found)
      const named=t=>{for(const [real,name] of devUsed){t=t.split(real).join(name);if(real.startsWith(TMP+'/'))t=t.split(real.slice(ROOT.length)).join(name);}if(notDir.length)t=t.split('\n').map(l=>notDir.some(v=>l.includes(v))?l.replace('No such file or directory','Not a directory'):l).join('\n');return t;};
      if(devUsed.size){
        const st=await stat(cli,stdoutPath);
        if(st&&st.size&&st.size<=1048576)try{
          const t=new TextDecoder('utf-8',{fatal:true}).decode(await this.bytesAt(stdoutPath)),t2=named(t);
          if(t2!==t)await cli.fs.writeFile(stdoutPath,t2);
        }catch(e){}
      }
      const stderr=ctx.mergeStderr?'':named(await this.textAt(stderrPath)),outStat=await stat(cli,stdoutPath);
      // exit(-1) in C gives status 255 on Linux (bcftools' error() does this)
      const raw=result.code==null?(result.error?1:0):result.code,code=((raw%256)+256)%256;
      const stdout=opts.binaryOut?'':tidy(await this.textAt(stdoutPath),ctx.name||program);
      for(const path of created)MG.bus.emit('vfs:created',{path,program,sub:args[0]});
      // (how many changes were put back so far: the agent's run asks, see agentRun – the message may go to /dev/null)
      if(this.denied.length)this.deniedN=(this.deniedN||0)+this.denied.length;
      const undone=this.denied.map(abs=>`${program}: ${fs.pretty(abs)} is read-only (the example data): the change to it was undone\n`).join('')
        +this.refused.map(abs=>`${program}: ${fs.pretty(abs)} was not kept – nothing new can be written into the example data (/data/examples is read-only): write into your home folder instead\n`).join('');
      const gone=this.gone.map(abs=>`${fs.pretty(abs)}: the contents of this file were lost when the programs were stopped – make it again\n`).join('');this.gone=[];
      const failure=result.error?(/FS error/.test(result.error)?`${ctx.name||program}: stopped – it could not read or write a file. Check the file names in the command.`:result.error):'';
      // The two outputs in the order in which the program wrote to them (wc -l a nosuch b: the count of a, the
      // message, the count of b): the run reports that order, and where both go the same way – to the terminal, to
      // the file or the pipe of a block or a script – they are passed on in it (see runReal). parts: [1 or 2,
      // bytes] in turn; only when the list accounts for every byte of both files.
      let parts=null;const ord=result.order||[],tail=(failure?`\n${failure}\n`:'')+undone+gone;
      if(!ctx.mergeStderr&&!opts.binaryOut&&!devUsed.size&&ord.length>2){
        const ob=await this.bytesAt(stdoutPath),eb=await this.bytesAt(stderrPath);let no=0,ne=0;
        for(let k=0;k<ord.length;k+=2){if(ord[k]===1)no+=ord[k+1];else ne+=ord[k+1];}
        if(no===ob.length&&ne===eb.length){
          let oi=0,ei=0;parts=[];
          for(let k=0;k<ord.length;k+=2){
            const n=ord[k+1];
            if(ord[k]===1){parts.push([1,ob.subarray(oi,oi+n)]);oi+=n;}
            else{parts.push([2,eb.subarray(ei,ei+n)]);ei+=n;}
          }
        }
      }
      // how far the program read what was piped in (see "the reader left early" in runPipeline) – Infinity: it was
      // named as a file (cat - , sort /dev/stdin), and so read as one
      const stdinUsed=stdin&&!inherit?(devUsed.has(stdin)?Infinity:Math.max(result.stdinMax||0,result.stdinPos||0)):null;
      return {stdout,stderr:stderr+tail,parts,tail,out:new FileRef(stdoutPath),stdoutSize:outStat?.size||0,created,secs:(performance.now()-start)/1000,code:code||(undone?1:0),statusKnown:result.code!=null,stdinUsed};
    },
    /* A program of OWN_WORKER: the command runs in a worker of its own (threads-worker.mjs, or the program's own). It
       gets the files that its arguments name – of a folder, everything in it; not what it is told to write (-o) – with
       their index files (INDEX_SUFFIXES), at the paths they have in the programs' file system, the links of the home
       folder and /data, every folder (it may write into any of them), its working folder and its input. What it wrote
       is put into the programs' file system, and the run goes on as for any other program: importChanges finds the new
       files. A workflow (T.flow) runs its commands that way one after another, and hands back what they made. The
       answer has the form of execIO's. */
    threadedWorker:null,
    /** the files of the programs' file system that the arguments name (with their index files), read for a worker:
        [{path, data, readonly}]. cwd: the folder relative names are in (a path of the programs' file system). */
    async inputsOf(args,outs,{fs,before,cwd}){
      const cli=this.cli;
      const toProg=v=>{
        if(!v||v==='-')return null;
        if(v===ROOT||v.startsWith(ROOT+'/'))return MG.path.norm(v);
        // (an absolute path that is not one of the programs' file system – /dev/stdin – names no file there)
        if(v.startsWith('/'))return ROOT+MG.path.norm(v);
        return MG.path.norm(cwd+'/'+v);
      };
      const want=new Set();
      for(let i=0;i<args.length;i++){
        const v=args[i];
        if(i&&outs.includes(args[i-1]))continue;
        const m=/^(--?[^=]+)=(.*)$/.exec(v);
        if(m&&outs.includes(m[1]))continue;
        // (a list of files after an option: lofreq call -S a.vcf.gz,b.vcf.gz; Cutadapt's adapters from a file: -a file:adapters.fa)
        for(const w of (m?m[2]:v).split(',')){
          const p=toProg(w.replace(/^\^?file\$?:/,''));
          // (the files of pipes – /dev/stdin, <(COMMAND) – are not in the list of the programs' files: asked for one by one)
          const st=!p?null:p.startsWith(TMP+'/')?await stat(cli,p):before.get(p);
          if(!st)continue;
          if(!st.isDir){
            want.add(p);
            for(const x of [...INDEX_SUFFIXES.map(s=>p+s),...(/\.(bam|cram)$/.test(p)?[p.replace(/\.(bam|cram)$/,'.bai'),p.replace(/\.(bam|cram)$/,'.crai')]:[])]){const t=before.get(x);if(t&&!t.isDir)want.add(x);}
            continue;
          }
          for(const [q,t] of before)if(!t.isDir&&q.startsWith(p+'/'))want.add(q);
        }
      }
      const files=[];
      for(const p of want){
        const e=fs.entries.get(p.slice(ROOT.length));
        files.push({path:p,data:await cli.fs.readFile(p),readonly:!!(e&&(e.readonly||e.protected))});
      }
      return files;
    },
    /** one command in a worker of its own → {exitCode, error, stdout, stderr, order, dirs, files, removed, stdinPos}
        T: the program (OWN_WORKER, or {name, module, worker}); the rest as threads-worker.mjs takes it */
    async spawn(T,{args,thisProgram,cwd,dirs,files,links,stdin,roots}){
      // (stopped between two commands of a workflow: the next one does not start)
      if(this.ownRun&&this.ownRun.stopped)throw Object.assign(new Error('Killed'),{userMessage:`${this.running||'program'}: Killed`,code:137});
      const {moduleUrl,pyodideUrl}=this.workerUrls(T);
      // (a worker made ready after the last command of this program – see prewarm – or a new one)
      const worker=this.takeSpare(T)||new Worker(new URL(T.worker||'assets/js/threads-worker.mjs',location.href),{type:'module',name:thisProgram||T.name});
      this.threadedWorker=worker;
      try{
        return await new Promise((resolve,reject)=>{
          this._threadedStop=reject;
          worker.onmessage=e=>{const m=e.data||{};if(m.type==='ready'||m.type==='prepare-error')return;if(m.type==='result')resolve(m.result);else reject(new Error((m.error&&m.error.message)||'the program gave no answer'));};
          worker.onerror=e=>{if(e.preventDefault)e.preventDefault();reject(new Error(e.message||'the program could not be started'));};
          // (the files are copied, not moved: a workflow hands the same bytes to its next command)
          worker.postMessage({moduleUrl,pyodideUrl,args,thisProgram:thisProgram||T.name,cwd,dirs,files,links,stdin,roots});
        });
      }finally{this._threadedStop=null;if(this.threadedWorker===worker)this.threadedWorker=null;try{worker.terminate();}catch(e){}if(T.prewarm)this.prewarm(T);}
    },
    workerUrls(T){
      const base=new URL(String(MG.config.threadsBase||'assets/vendor/genomics-wasm').replace(/\/?$/,'/'),location.href);
      return {moduleUrl:new URL(T.module,base).href,pyodideUrl:T.pyodide?new URL(T.pyodide,base).href:undefined};
    },
    /* MACS3's Python takes many seconds to start with all its packages (NumPy, SciPy, scikit-learn, pandas …). After a
       command of it, a new worker starts its Python in the background (python-worker.mjs: the message 'prepare'), so
       that the next command finds it ready. Every command still has a worker and a Python of its own, as genomics-wasm
       runs MACS3. A worker that is not used within SPARE_MS is stopped: it holds a few hundred MB of memory. */
    spares:new Map(),
    prewarm(T){
      if(this.spares.has(T.module))return;
      let worker;
      try{worker=new Worker(new URL(T.worker||'assets/js/threads-worker.mjs',location.href),{type:'module',name:T.name});}catch(e){return;}
      const spare={worker,timer:null};
      const drop=()=>{if(this.spares.get(T.module)===spare)this.spares.delete(T.module);clearTimeout(spare.timer);try{worker.terminate();}catch(e){}};
      spare.timer=setTimeout(drop,SPARE_MS);
      // (a worker that could not get ready is not used: the next command starts afresh)
      worker.onmessage=e=>{if(e.data&&e.data.type==='prepare-error')drop();};
      worker.onerror=e=>{if(e.preventDefault)e.preventDefault();drop();};
      this.spares.set(T.module,spare);
      worker.postMessage(Object.assign({type:'prepare'},this.workerUrls(T)));
    },
    takeSpare(T){
      const spare=T.prewarm&&this.spares.get(T.module);
      if(!spare)return null;
      this.spares.delete(T.module);clearTimeout(spare.timer);
      return spare.worker;
    },
    async execWorker(program,args,{stdin,stdout,stderr,merge,fs,before,name,io,flowOpts,devUsed,piped}){
      const T=OWN_WORKER[program],cli=this.cli,home=fs.home,cwd=this.apath(fs.isDir(fs.cwd)?fs.cwd:fs.home);
      const links=[[ROOT+home,home],[ROOT+'/data','/data']];
      const dirs=[ROOT,TMP,...Array.from(before).filter(([p,t])=>t.isDir&&!p.startsWith(TMP)).map(([p])=>p),cwd];
      const input=stdin?await cli.fs.readFile(stdin):null;
      const flow=T.flow&&T.flow(args);
      let r;
      const run=this.ownRun={stopped:false};
      try{
      if(flow){
        // A workflow: its commands one after another, each in a worker of its own (see somatic.js). Its files have the
        // paths of the terminal (/home/user/…, /data/…, /tmp/…) – also in the workers, where they are folders of their
        // own: a program that writes a path into its output (Strelka's VCF header names the reference file) writes the
        // path the person knows. What the workflow made is put below ROOT here.
        const term=p=>p===ROOT?'/':p.startsWith(ROOT+'/')?p.slice(ROOT.length):p,tcwd=term(cwd);
        // (the arguments as they were typed: ROOT is in none of them – see pathToken in _run. /dev/stdin is given back its
        // name: the workflow has what came in as h.stdin – kraken2 … /dev/stdin)
        const ins=[...(devUsed||new Map())].filter(([,n])=>n==='/dev/stdin').map(([real])=>real);
        const typed=args.map(v=>{for(const real of ins)v=v.split(real).join('/dev/stdin');return v.split(ROOT+'/').join('/');});
        const h={cwd:tcwd,io,opts:flowOpts||{},name:name||T.name,stdin:input,stdinPipe:!!piped,
          abs:p=>MG.path.norm(p.startsWith('/')?p:tcwd+'/'+p),
          // (the folder of the files that stand for /dev/stdout and /dev/stderr is not in the snapshot – it is there)
          isDir:p=>{if(p===term(TMP))return true;const t=before.get(p==='/'?ROOT:ROOT+p);return !!(t&&t.isDir);},
          isFile:p=>{const t=before.get(ROOT+p);return !!(t&&!t.isDir);},
          readText:async p=>new TextDecoder('utf-8').decode(await cli.fs.readFile(ROOT+p)),
          pretty:p=>(fs.pretty?fs.pretty(p):p),
          stage:t=>{this.stage=t;},
          inputsOf:async(a,outs,at)=>(await this.inputsOf(a,outs||[],{fs,before,cwd:at?ROOT+at:cwd})).map(f=>({path:term(f.path),data:f.data,readonly:f.readonly})),
          spawn:(t,o)=>this.spawn(t,Object.assign({cwd:tcwd,dirs:[tcwd],links:[],stdin:null},o))};
        r=await flow(typed,h);
        r.files=(r.files||[]).map(f=>({path:ROOT+f.path,data:f.data}));
        // (what the workflow removes – kraken2-build --clean: in the programs' file system, and in the terminal's)
        r.removeTerm=r.remove||[];
        r.remove=r.removeTerm.map(p=>ROOT+p);
      }else{
        const files=await this.inputsOf(args,T.outputs(args),{fs,before,cwd});
        r=await this.spawn(T,{args,thisProgram:name||T.name,cwd,dirs,files,links,stdin:input,roots:[ROOT]});
        // (a file it was given that the program removed is removed here too – hmmpress on a pressed file removes three of
        // the four, as on Linux; not a file of the course data, nor a read-only one)
        const kept=p=>{const e=fs.get(p);return p==='/data'||p.startsWith('/data/')||!!(e&&(e.readonly||e.protected));};
        r.removeTerm=(r.removed||[]).filter(p=>p.startsWith(ROOT+'/')).map(p=>p.slice(ROOT.length)).filter(p=>!kept(p));
        r.remove=r.removeTerm.map(p=>ROOT+p);
      }
      }finally{if(this.ownRun===run)this.ownRun=null;this.stage=null;}
      if(run.stopped)throw Object.assign(new Error('Killed'),{userMessage:`${this.running||name||T.name}: Killed`,code:137});
      for(const d of r.dirs||[])if(!before.has(d))await mkdirp(cli,d);
      for(const p of r.remove||[]){const st=await stat(cli,p);if(st&&st.isDir)await rmtree(cli,p);else if(st)await cli.fs.unlink(p);}
      for(const p of r.removeTerm||[])fs.remove(p);
      // (-o /dev/stdout: the program wrote into the file that stands for its output – it joins what it printed)
      const join=(a,b)=>{const all=new Uint8Array(a.length+b.length);all.set(a);all.set(b,a.length);return all;};
      for(const f of r.files){
        if(f.path===stdout){r.stdout=join(r.stdout,f.data);if(r.order.length)r.order.push(1,f.data.length);continue;}
        if(f.path===stderr){r.stderr=join(r.stderr,f.data);if(r.order.length)r.order.push(2,f.data.length);continue;}
        await place(cli,f.path,f.data);
      }
      if(merge){
        // 2>&1: the two outputs in one file, in the order in which they were written
        const all=new Uint8Array(r.stdout.length+r.stderr.length);let o=0,i1=0,i2=0;
        // (a workflow that kept no order: what it printed, then its messages)
        const ord=r.order&&r.order.length?r.order:[1,r.stdout.length,2,r.stderr.length];
        for(let k=0;k<ord.length;k+=2){const n=ord[k+1];if(ord[k]===1){all.set(r.stdout.subarray(i1,i1+n),o);i1+=n;}else{all.set(r.stderr.subarray(i2,i2+n),o);i2+=n;}o+=n;}
        await cli.fs.writeFile(stdout,all);
      }else{await cli.fs.writeFile(stdout,r.stdout);await cli.fs.writeFile(stderr,r.stderr);}
      return {code:r.exitCode,error:r.error?`${name||T.name}: stopped – ${r.error}`:null,order:merge?[]:r.order||[],stdinPos:r.stdinPos||0,stdinMax:r.stdinPos||0};
    },
    /* A program that does not end blocks every later command. kill() stops the worker that runs the
       programs; the next command starts a new one. What programs had written lived in that worker's
       memory and is lost (returned as a list); the course data and text files are not.
       The programs of OWN_WORKER run in a worker of their own: stopping one loses nothing else (lastKill 'threads') – nor
       does stopping a workflow of them (lofreq somatic, runWorkflow.py) between two of its commands. */
    lastKill:'',
    ownRun:null,
    kill(fs){
      fs=real(fs);
      if(this.threadedWorker||this.ownRun){
        const program=this.running,err=Object.assign(new Error('Killed'),{userMessage:`${program||'program'}: Killed`,code:137});
        if(this.ownRun)this.ownRun.stopped=true;
        try{if(this.threadedWorker)this.threadedWorker.terminate();}catch(e){}
        this.threadedWorker=null;this.lastKill='threads';
        if(this._threadedStop)this._threadedStop(err);
        if(this._killed)this._killed(err);
        MG.bus.emit('wasm:killed',{program,lost:0});
        return [];
      }
      this.lastKill='runner';
      const w=window.Aioli&&window.Aioli.lastWorker;
      if(!this.cli||!w)return [];
      const program=this.running;
      try{w.terminate();}catch(e){}
      window.Aioli.lastWorker=null;
      this.ready=false;this.loading=null;this.cli=null;this.synced.clear();this.placed.clear();this.managed.clear();this.dirs.clear();this.gen++;
      const lost=[];this.lostTimes=new Map();this.lostEntries=new Map();
      for(const [abs,e] of Array.from(fs.entries))if(e.kind==='aioli'){this.lostTimes.set(abs,e.mtime||0);this.lostEntries.set(abs,e);fs.entries.delete(abs);fs._changed(abs,'remove');lost.push(abs);}
      if(this._killed)this._killed(Object.assign(new Error('Killed'),{userMessage:`${program||'program'}: Killed`,code:137}));
      MG.bus.emit('wasm:killed',{program,lost:lost.length});
      return lost;
    },
    async gunzipText(ctx,file){const r=await this.run({...ctx,stdin:null,inherit:null},'bgzip',['-dc',file]);if(r.code)throw MG.shellUtil.userErr(r.stderr||'Decompression failed');return r.stdout;},
    async cleanupPipes(fs,keep){
      fs=real(fs);
      if(!this.ready)return;
      const refs=new Set(keep?[keep]:[]);for(const e of fs.entries.values())if(e.apath)refs.add(e.apath);for(const p of this.held.keys())refs.add(p);
      for(const n of await readdir(this.cli,TMP)){const p=TMP+'/'+n;if(n!=='.'&&n!=='..'&&!refs.has(p))try{await this.cli.fs.unlink(p);}catch(e){}}
    }
  };
  async function stat(cli,p){try{const s=await cli.fs.lstat(p);return {size:s.size,mtime:+new Date(s.mtime),isDir:(s.mode&0o170000)===0o040000};}catch(e){return null;}}
  async function readdir(cli,p){try{return await cli.fs.readdir(p);}catch(e){return [];}}
  async function mkdirp(cli,p){let cur='';for(const part of p.split('/').filter(Boolean)){cur+='/'+part;const s=await stat(cli,cur);if(s&&!s.isDir)try{await cli.fs.unlink(cur);}catch(e){}if(!s||!s.isDir)try{await cli.mkdir(cur);}catch(e){}}}
  /* write a file at dest, whatever is in the way: a folder of that name, a file where a folder should be */
  async function place(cli,dest,data){
    const parts=dest.split('/').filter(Boolean);let cur='';
    for(let i=0;i<parts.length-1;i++){
      cur+='/'+parts[i];const s=await stat(cli,cur);
      if(s&&!s.isDir)await cli.fs.unlink(cur);
      if(!s||!s.isDir)await cli.mkdir(cur); // Aioli's mkdir: FS.mkdir returns a node, which cannot be sent to the page
    }
    const s=await stat(cli,dest);
    if(s&&s.isDir)await rmtree(cli,dest);else if(s)await cli.fs.chmod(dest,0o644);
    await cli.fs.writeFile(dest,data);
  }
  async function rmtree(cli,p){
    for(const n of await readdir(cli,p)){
      if(n==='.'||n==='..')continue;
      const q=p+'/'+n,s=await stat(cli,q);
      if(s&&s.isDir)await rmtree(cli,q);else if(s)await cli.fs.unlink(q);
    }
    await cli.fs.rmdir(p);
  }
  function loadScript(src){return new Promise((resolve,reject)=>{const s=document.createElement('script');s.src=src;s.onload=resolve;s.onerror=()=>reject(new Error('Could not load '+src));document.head.appendChild(s);});}
  /* date -u …: is the time asked for in UTC? (-u among the letters of an option – not in the value of -d or -I) */
  function dateUTC(args){
    for(let i=0;i<args.length;i++){
      const v=args[i];
      if(v==='--utc'||v==='--universal')return true;
      if(v==='--')break;
      if(!/^-[A-Za-z]/.test(v))continue;
      for(let j=1;j<v.length;j++){
        const c=v[j];
        if(c==='u')return true;
        if(c==='I')break;
        if('dfrs'.includes(c)){if(j===v.length-1)i++;break;}
      }
    }
    return false;
  }
  /* Messages of the programs: paths as the student sees them, and the program's name where the
     WebAssembly build has none ("(null): cannot open …"). */
  function tidy(text,name){
    text=text.replace(/\/shared\/vfs/g,'').replace(/^\(null\):/gm,name+':');
    // Salmon (Rust) adds the number of a system error to its message: "No such file or directory (os error 44)" – the
    // numbering of WebAssembly's C library (WASI). Linux's number is put in its place (ENOENT is 2 there).
    if(name==='salmon')text=text.replace(/\(os error (\d+)\)/g,(x,n)=>`(os error ${LINUX_ERRNO[n]||n})`);
    return text;
  }
  const LINUX_ERRNO={63:1,44:2,29:5,8:9,48:12,2:13,20:17,54:20,31:21,28:22,33:24,22:27,51:28,70:29,69:30,64:32,37:36,55:39};
  /* ---- the contract of an execution backend (exec.js; docs/execution-backends.md) ---- */
  Object.assign(W, {
    id: 'browser',
    label: 'this browser tab',
    // the page's file entries whose bytes are in the programs' file system: { kind: 'aioli', apath, size }
    entryKind: 'aioli',
    running: null,
    capabilities: { where: 'browser', persistentFiles: false, threads: !!window.crossOriginIsolated },
    /** featureCounts, Salmon and PLINK 2 count on several threads: only in a cross-origin isolated page */
    needsIsolation(program) {
      const T = OWN_WORKER[program];
      return !!(T && T.threads && !window.crossOriginIsolated);
    },
    tidy(text, name) {
      return tidy(text, name);
    },
    readText(ref) {
      return this.textAt(ref.handle);
    },
    readBytes(ref) {
      return this.bytesAt(ref.handle);
    },
    sizeOf(ref) {
      return this.sizeAt(ref.handle);
    },
    /** a file of the programs' file system that a program can be told to write (tee /dev/stdout: see teeRun) */
    tempFile() {
      return new FileRef(`${TMP}/t${++this.pipeN}`);
    },
    async discard(ref) {
      if (this.cli) await this.cli.fs.unlink(ref.handle);
    },
    /** (a path of the programs' file system: _run gives it to the program as it is) */
    argPath(ref) {
      return ref.handle;
    },
    /** < FILE: the program reads the file itself. Everything is brought up to date first, not this file alone: writing
        one file could destroy the bytes that a copy of it (cp, mv) still needs. */
    async inputRef(fs, abs) {
      await this.ensure();
      await this.syncAll(fs);
      const ref = new FileRef(this.apath(abs));
      ref.fromFile = true; // a file, not a pipe: see _stream in shell-lang.js
      ref.path = abs;
      return ref;
    },
    holds(e) {
      return !!e && e.kind === 'aioli';
    },
    entryText(e) {
      return this.textAt(e.apath);
    },
    entryBytes(e) {
      return this.bytesAt(e.apath);
    },
    /** what a program printed becomes the file at abs (COMMAND > FILE), or is added to it (>>); tail: what the page adds
        after it (> FILE 2>&1: "… is read-only: the change to it was undone"). → false: the program printed nothing, and
        the file stays as it was opened – made, or emptied, before the program ran – or as the program itself wrote it
        by name:  samtools sort x.bam -o s.bam > s.bam 2>&1,  sort -o F a > F. */
    async writeOutput(fs, target, ref, { tail = null, append = false } = {}) {
      let bytes = await this.bytesAt(ref.handle);
      if (tail) {
        const all = new Uint8Array(bytes.length + tail.length);
        all.set(bytes);
        all.set(tail, bytes.length);
        bytes = all;
      }
      if (!bytes.length && fs.exists(target) && !fs.isDir(target)) return false;
      if (append && fs.exists(target)) {
        const old = await fs.readBytes(target), joined = new Uint8Array(old.length + bytes.length);
        joined.set(old);
        joined.set(bytes, old.length);
        bytes = joined;
      }
      const dest = this.apath(target);
      await mkdirp(this.cli, MG.path.dirname(dest));
      await this.cli.fs.writeFile(dest, bytes);
      await this.adopt(fs, target, dest, bytes.length, bytes);
      return true;
    }
  });
  MG.exec.register(W);
})();
