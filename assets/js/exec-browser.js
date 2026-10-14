/* =====================================================================
   The browser backend: the programs of the terminal run in this page, compiled to WebAssembly – the Biowasm builds
   (one shared worker, Aioli, with one shared file system) and the genomics-wasm ports (featureCounts, Salmon, PLINK 2,
   Cutadapt, MACS3, LoFreq, SomaticSniper, Strelka2, Kraken2, Bracken, Prodigal, HMMER, bustools: each command in a
   worker of its own – threads-worker.mjs, python-worker.mjs). This file is its machine – what is particular to the
   browser – for the engine that both backends share (exec-engine.js, which keeps the page's files and the programs'
   the same); registered with MG.exec (exec.js), which is how the rest of the workbench reaches it.

   Aioli's local execIO patch binds real file descriptors and reports each exit status. A program of OWN_WORKER gets
   the files it needs, and what it writes comes back into the shared file system (see execWorker). lofreq somatic and
   Strelka's runWorkflow.py are workflows of several such commands (somatic.js), and so are Kraken2's and Bracken's
   commands, wrapper scripts upstream (metagenomics.js).
   ===================================================================== */
(function () {
  'use strict';
  const MG = window.MG;
  const FileRef = MG.FileRef;
  const { ROOT, TMP, real, stat, mkdirp, place, rmtree } = MG.execEngine;
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
  function loadScript(src){return new Promise((resolve,reject)=>{const s=document.createElement('script');s.src=src;s.onload=resolve;s.onerror=()=>reject(new Error('Could not load '+src));document.head.appendChild(s);});}
  const MACHINE = {
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
    /** Aioli: the Biowasm programs in one worker of this page, with one shared file system ('base') */
    async start(status, specs) {
      const base=new URL(MG.config.biowasmBase||'assets/vendor/biowasm',location.href).href.replace(/\/$/,'');
      if(!window.Aioli)await loadScript(base+'/aioli.js');
      status?.('Starting the local WebAssembly filesystem…');
      // 'base' holds the shared file system and never runs a program: a tool that aborts is replaced without losing the files
      const tools=specs.map(([tool,version,program])=>({tool,version,program:program||tool,urlPrefix:`${base}/${tool}/${version}`,loading:'lazy',features:{}}));
      return await new window.Aioli(tools,{printInterleaved:false,urlCDN:base,debug:false});
    },
    /** the programs that run in a worker of their own (see execWorker) */
    ownWorker(program) {
      return OWN_WORKER[program] || null;
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
  };
  MG.exec.register(MG.execEngine.create(MACHINE));
})();
