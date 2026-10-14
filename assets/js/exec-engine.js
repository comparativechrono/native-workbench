/* =====================================================================
   What the execution backends share (exec.js): a backend that runs programs in a file system of its own and keeps it
   the same as the page's (vfs.js). Before a program runs, the programs' file system is made the same as the page's
   (syncAll); afterwards what the program changed becomes part of the page's (importChanges). Pipes use byte-preserving
   temporary files (run one after another, not as concurrent processes). The bytes of a file that a program wrote stay
   in the programs' file system: the page's entry for it ({ kind: entryKind, apath, size }) says where.

   A backend is this engine and a machine (create(machine)): what starts the programs' file system (start), stops a
   program by force (kill), runs the programs of a worker of their own (ownWorker, execWorker), and names the backend
   (id, label, entryKind, capabilities). The browser's machine is Aioli, in this page (exec-browser.js); the local
   runner's is a folder on disk, through the runner (exec-local.js). A machine's file system (cli) has the calls of
   Aioli's: fs.{readFile, writeFile, lstat, readdir, unlink, rmdir, chmod, utime}, mkdir, cd, statTree and execIO. A
   machine whose files can be larger than a page should hold says so (keepsBytes: true) and also has fs.copyFile,
   fs.rename, fs.redirect, fs.readTextBounded, fs.readSmall and siteFile: with them, copies, moves, the agent's copies
   and what a program printed into a file stay on its side, and only the beginning and the end of a long output come to
   the page. (A flag, not a look at the cli: Aioli's is a proxy of its worker, on which every name seems to be there.)
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
  /* The programs of the Biowasm builds, as [tool, version, program]: what the machine starts ('base' holds Aioli's
     shared file system and runs no program) */
  const SPECS=[['base','1.0.0'],['samtools','1.17'],['bcftools','1.10'],['htslib','1.17','bgzip'],['htslib','1.17','tabix'],['minimap2','2.22'],['bowtie2','2.4.2','bowtie2-align-s'],['bowtie2','2.4.2','bowtie2-build-s'],['bwa','0.7.19'],['bwa-mem2','2.2.1'],['hisat2','2.2.2'],['freebayes','1.3.6'],['stringtie','3.0.3'],['kallisto','0.52.0'],['mosdepth','0.3.14'],['fastp','0.20.1'],['seqtk','1.4'],['bedtools','2.31.0'],['jq','1.7'],['gawk','5.1.0'],['grep','3.7'],['grep','3.11','grep-perl'],['sed','4.8'],['diffutils','3.10','diff'],['diffutils','3.10','cmp'],['kalign','3.3.1'],['muscle','3.8.1551'],['fasttree','2.1.11'],['seq-align','2017.10.18','needleman_wunsch'],['seq-align','2017.10.18','smith_waterman'],['seq-align','2017.10.18','lcs'],['wgsim','2011.10.17'],['gffread','0.12.7'],['lastz','1.04.52'],...CORE.map(p=>['coreutils','8.32',p])];
  // (of what a program printed for the screen, at most this much from its beginning and from its end: OUT_HEAD, OUT_TAIL)
  const OUT_HEAD=8*2**20,OUT_TAIL=2*2**20;
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
  const ENGINE = {
    ready:false, loading:null, cli:null, pipeN:0, mountN:0,
    synced:new Map(), placed:new Map(), managed:new Set(), dirs:new Set(), gone:[], denied:[], refused:[],
    gen:0, kept:new Map(), keepN:0,
    versions:{fastp:'0.20.1',minimap2:'2.22',bowtie2:'2.4.2',bwa:'0.7.19','bwa-mem2':'2.2.1',hisat2:'2.2.2',freebayes:'1.3.6',stringtie:'3.0.3',kallisto:'0.52.0',mosdepth:'0.3.14',featurecounts:'2.1.1',salmon:'2.8.0',cutadapt:'5.2',macs3:'3.0.5',lofreq:'2.1.5',somaticsniper:'1.0.5.0',strelka2:'2.9.10',kraken2:'2.17.2',bracken:'3.1',prodigal:'2.6.3',hmmer:'3.4',bustools:'0.45.1',plink2:'2.0.0-b.1-dev',samtools:'1.17',bcftools:'1.10',htslib:'1.17',seqtk:'1.4',bedtools:'2.31.0',jq:'1.7',gawk:'5.1.0',grep:'3.7',sed:'4.8',coreutils:'8.32',diffutils:'3.10',kalign:'3.3.1',muscle:'3.8.1551',fasttree:'2.1.11','seq-align':'2017.10.18',wgsim:'0.3.1-r13',gffread:'0.12.7',lastz:'1.04.52'},
    apath(abs) { return ROOT+abs; },
    /** start the programs' file system, if it has not started: the machine's start – Aioli in this page, or the local
        runner's folder on disk */
    ensure(status) {
      if(this.ready)return Promise.resolve(this.cli);
      if(this.loading)return this.loading;
      this.loading=(async()=>{
        this.cli=await this.start(status,SPECS);
        await mkdirp(this.cli,TMP); await mkdirp(this.cli,KEEP); this.ready=true; MG.bus.emit('wasm:ready',{}); return this.cli;
      })().catch(e=>{this.loading=null;throw e;});
      return this.loading;
    },
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
      // (a machine that copies files itself: the bytes do not come through the page)
      const copy=async src=>{if(await stat(cli,dest))await cli.fs.chmod(dest,0o644);await cli.fs.copyFile(src,dest);if(locked)await cli.fs.chmod(dest,0o444);await stamp();};
      if(e.kind==='text'){
        if(prior!==e||e.dirty||!(await look(dest))){await write(e.text);e.dirty=false;}
      }else if(e.kind===this.entryKind){
        if(prior!==e||e.apath!==dest){
          if(!(await look(e.apath))){
            // its bytes are gone: a name without contents must not stay behind (every later program would stop)
            fs.entries.delete(abs);fs._changed(abs,'remove');this.synced.delete(abs);this.managed.delete(abs);this.gone.push(abs);return;
          }
          if(e.apath!==dest){if(this.keepsBytes)await copy(e.apath);else await write(await cli.fs.readFile(e.apath));e.apath=dest;}
          else{await cli.fs.chmod(dest,locked?0o444:0o644);await stamp();}
        }
      }else if(e.kind==='url'||e.kind==='blob'){
        // the course data is copied in as real bytes – by a machine that has the site's files (the local runner) from
        // there, and not at all where its file is the site's file itself (/data/examples)
        const site=e.kind==='url'&&this.keepsBytes?cli.siteFile(e.url):null;
        if(site&&site===dest){/* the file itself */}
        else if(prior!==e||!(await look(dest)))await (site?copy(site):write(await fs.readBytes(abs)));
      }else throw MG.shellUtil.userErr(`Unsupported file entry: ${e.kind}`);
      this.synced.set(abs,e);this.managed.add(abs);
    },
    /* A file that was copied or moved (cp, mv) still has its bytes at the old place, until a program
       needs it. settle gives every such file its own bytes: all of them are read first, then written –
       so that it does not matter in which order they are, or what else is written to the old places.
       between() runs after the reading and before the writing. */
    async settle(fs,between){
      fs=real(fs);
      const cli=this.cli,moved=[],held=this.entryKind;
      // (A machine that copies and renames files itself – the local runner – keeps the bytes on its side: each such file
      // is put in a place of its own first – moved there when nothing else needs its old place, copied when the file it
      // was copied from is still there – and then given its name.)
      const refs=new Map();
      if(this.keepsBytes)for(const e of fs.entries.values())if(e.kind===held)refs.set(e.apath,(refs.get(e.apath)||0)+1);
      for(const [abs,e] of Array.from(fs.entries))if(e.kind===held&&e.apath!==this.apath(abs)){
        if(await stat(cli,e.apath))moved.push([abs,e,this.keepsBytes?await this.stash(e.apath,refs.get(e.apath)>1):await cli.fs.readFile(e.apath)]);
        else{fs.entries.delete(abs);fs._changed(abs,'remove');this.gone.push(abs);}
      }
      if(between)await between();
      for(const [abs,e,bytes] of moved){
        if(fs.entries.get(abs)!==e)continue;
        const dest=this.apath(abs);
        await (this.keepsBytes?placeFrom(cli,dest,bytes,'move'):place(cli,dest,bytes));e.apath=dest;this.noteDirs(abs);
        if(e.readonly||e.protected)await cli.fs.chmod(dest,0o444);
        this.synced.set(abs,e);this.managed.add(abs);
      }
    },
    /** a file of the machine's, moved (or copied) to a place of its own on the machine's side → that place. (Numbered
        apart from the files of pipes: their names reach what programs write – hisat2's @PG line names its input.) */
    async stash(src,copyIt){
      const p=`${TMP}/stash-${++this.stashN}`;
      await (copyIt?this.cli.fs.copyFile(src,p):this.cli.fs.rename(src,p));
      return p;
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
       A file of the machine's kind (entryKind) has its bytes only here, in the programs' file system. Before a command of the
       agent runs, each such file outside the agent's folder is copied (once per run of the agent);
       putBack writes the copy back where a command changed or removed the file. */
    async keep(list){
      if(!this.ready)return 0;
      const cli=this.cli;let n=0;
      for(const [,e] of list){
        if(e.kind!==this.entryKind)continue;
        const had=this.kept.get(e);
        if(had&&had.gen===this.gen)continue;
        const s=await stat(cli,e.apath);
        if(!s||s.isDir)continue;
        const path=`${KEEP}/${++this.keepN}`;
        if(this.keepsBytes)await cli.fs.copyFile(e.apath,path);else await cli.fs.writeFile(path,await cli.fs.readFile(e.apath));
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
      if(moved){const src=same?e.apath:k.path;await (this.keepsBytes?placeFrom(cli,dest,src,'copy'):place(cli,dest,await cli.fs.readFile(src)));e.apath=dest;this.noteDirs(abs);}
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
      else fs.put(abs,Object.assign({kind:this.entryKind,apath,size,fresh:true},keep));
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
      const guarded=abs=>{const e=fs.get(abs);return !!e&&e.kind!==this.entryKind&&e.kind!=='dir'&&!!e.protected;};
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
    /* one program at a time – and the backend's own work on the files (flush) between two programs, never during one */
    lock:Promise.resolve(),
    async locked(f){
      let release;const prev=this.lock;this.lock=new Promise(r=>(release=r));
      await prev;
      try{return await f();}finally{release();}
    },
    async run(ctx,program,args,opts={}){
      return this.locked(()=>this._run(ctx,program,args,opts));
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
      const own=this.ownWorker(program);
      this.running=own?(ctx.name||own.name):program;
      const job=own?this.execWorker(program,a,{stdin,stdout:stdoutPath,stderr:stderrPath,merge:!!ctx.mergeStderr,fs,before,name:ctx.name,io:ctx.io,flowOpts:opts.flow,devUsed,piped})
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
      // (a machine whose files can be larger than a page should hold – the local runner – gives the beginning and the end)
      const textOf=p=>this.keepsBytes?cli.fs.readTextBounded(p,OUT_HEAD,OUT_TAIL):this.textAt(p);
      const stderr=ctx.mergeStderr?'':named(await textOf(stderrPath)),outStat=await stat(cli,stdoutPath);
      // exit(-1) in C gives status 255 on Linux (bcftools' error() does this)
      const raw=result.code==null?(result.error?1:0):result.code,code=((raw%256)+256)%256;
      // (as text: for the screen, or for whoever takes the output as text – not when it goes into a file or a pipe, where
      // runReal hands on the bytes: opts.textOut false)
      const stdout=opts.binaryOut||opts.textOut===false?'':tidy(await textOf(stdoutPath),ctx.name||program);
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
      if(!ctx.mergeStderr&&!opts.binaryOut&&opts.textOut!==false&&!devUsed.size&&ord.length>2&&!(this.keepsBytes&&(outStat?.size||0)>OUT_HEAD)){
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
  /* … or with bytes that the machine has at src: moved there ('move') or copied ('copy') on the machine's side */
  async function placeFrom(cli,dest,src,how){
    const parts=dest.split('/').filter(Boolean);let cur='';
    for(let i=0;i<parts.length-1;i++){
      cur+='/'+parts[i];const s=await stat(cli,cur);
      if(s&&!s.isDir)await cli.fs.unlink(cur);
      if(!s||!s.isDir)await cli.mkdir(cur);
    }
    const s=await stat(cli,dest);
    if(s&&s.isDir)await rmtree(cli,dest);else if(s)await cli.fs.chmod(dest,0o644);
    await (how==='move'?cli.fs.rename(src,dest):cli.fs.copyFile(src,dest));
  }
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
  const CONTRACT = {
    running: null,
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
      return !!e && e.kind === this.entryKind;
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
      const cli = this.cli;
      if (this.keepsBytes) {
        // (a machine that does it itself – the local runner: the output is moved to the file, or added to its end, on
        // the machine's side, and does not come through the page)
        const size = await this.sizeAt(ref.handle);
        if (!size && !(tail && tail.length) && fs.exists(target) && !fs.isDir(target)) return false;
        const dest = this.apath(target);
        await mkdirp(cli, MG.path.dirname(dest));
        const n = await cli.fs.redirect(ref.handle, dest, { tail, append: append && fs.exists(target) });
        await this.adopt(fs, target, dest, n, null);
        return true;
      }
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
  };

  /* ---- a machine whose files stay where they are (the local runner's folder on disk: capabilities.persistentFiles) ---- */
  Object.assign(CONTRACT, {
    /** at the start: the page's files are what is in the machine's folders – in place of what the browser kept for the
        page (project.js). Small text files become text in the page (fetched together); the rest stays where it is. */
    async restore(fs, roots) {
      await this.ensure();
      fs = real(fs);
      const cli = this.cli;
      // (one look at the whole tree: kept as this.restored – what the folder was when the page took its files from it)
      const snap = (this.restored = await this.snapshot());
      this._fs = fs;
      const under = (abs) => roots.some((r) => abs === r || abs.startsWith(r + '/'));
      const list = Array.from(snap).filter(([p]) => p !== this.apath('/') && under(p.slice(ROOT.length))).map(([p, s]) => [p, s.size, s.mtime, s.isDir]);
      {
        const small = list.filter(([, size, , dir]) => !dir && size <= TEXT_MAX).map(([p]) => p);
        const texts = small.length && this.keepsBytes ? await cli.fs.readSmall(small) : {};
        for (const [p, size, mtime, dir] of list) {
          const abs = p.slice(ROOT.length);
          if (roots.includes(abs) && dir) continue;
          if (dir) {
            if (!fs.exists(abs)) fs.mkdirp(abs);
            const d = fs.entries.get(abs);
            if (d && d.kind === 'dir' && mtime) d.mtime = mtime;
            this.dirs.add(abs);
            continue;
          }
          if (typeof texts[p] === 'string') fs.put(abs, { kind: 'text', text: texts[p], fresh: true, mtime });
          else fs.put(abs, { kind: this.entryKind, apath: p, size, fresh: true, mtime });
          const e = fs.get(abs);
          if (e.kind === 'text') e.dirty = false;
          this.synced.set(abs, e);
          this.managed.add(abs);
        }
      }
    },
    /** what the page changes itself – a file written by echo or the editor, removed by rm, moved by mv – goes to the
        machine's files soon after, not only before the next program: they are where the work is kept */
    watch(fs) {
      fs = real(fs);
      fs.onChange(() => this.flushSoon(fs));
    },
    flushSoon(fs) {
      clearTimeout(this._flushT);
      this._flushT = setTimeout(() => this.flush(fs).catch((e) => console.error(e)), 300);
    },
    flush(fs) {
      if (!this.ready) return Promise.resolve();
      return this.locked(() => this.syncAll(fs));
    }
  });
  /** a backend: the engine with a machine (its members are the backend's too: start, kill, ownWorker, execWorker, id …).
      Each backend has state of its own. */
  function create(machine) {
    return Object.assign({}, ENGINE, CONTRACT, {
      ready: false, loading: null, cli: null, pipeN: 0, mountN: 0,
      synced: new Map(), placed: new Map(), managed: new Set(), dirs: new Set(), gone: [], denied: [], refused: [],
      gen: 0, kept: new Map(), keepN: 0, stashN: 0, held: new Map(), lock: Promise.resolve(), running: null
    }, machine);
  }
  MG.execEngine = { create, ROOT, TMP, KEEP, TEXT_MAX, SPECS, real, stat, readdir, mkdirp, place, placeFrom, rmtree };
})();
