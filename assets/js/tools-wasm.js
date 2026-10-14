/* Real, pinned programs compiled to WebAssembly (Biowasm builds; Bowtie 2, diff and cmp built for
 * this practical; BWA, BWA-MEM2, HISAT2, FreeBayes, StringTie, kallisto, mosdepth, featureCounts, Salmon, Cutadapt,
 * MACS3, LoFreq, SomaticSniper, Strelka2, Kraken2, Bracken, Prodigal, HMMER, bustools and PLINK 2 from the genomics-wasm
 * ports), as commands of the terminal: what each command does before and after its program runs – the wrappers
 * (bowtie2, hisat2), the options that these builds cannot take (threads, memory), gzip and its relatives, grep -P – and
 * where the output of a program goes (runReal). The programs themselves run in the execution backend (exec.js): this
 * file reaches them through MG.exec only – in the browser backend (exec-browser.js), or in a local one.
 */
(function () {
  'use strict';
  const MG = window.MG;
  // (the same programs as the browser backend's coreutils – exec-browser.js)
  const CORE = ['cat','head','tail','wc','sort','uniq','cut','tr','tee','comm','join','paste','seq','fold','shuf','md5sum','date'];
  const FileRef = MG.FileRef;
  // While a command of the AI agent runs, the shell's file system notes every path that is worked out through it
  // (terminal.js: watched). What is done here looks at all files, whatever the command names: it uses the file system itself.
  const real=fs=>(fs&&fs.__real)||fs;
  // HMMER 3.4: thirteen programs, a module each (the SIMD of WebAssembly stands in for SSE2: every browser of the last
  // years has it). Their options that name a file they write:
  const HMMER=['hmmbuild','hmmsearch','hmmscan','hmmpress','hmmfetch','hmmalign','hmmconvert','hmmemit','hmmstat','phmmer','jackhmmer','nhmmer','nhmmscan'];
  const HMMER_OUTS=['-o','-A','-O','--tblout','--domtblout','--pfamtblout','--dfamtblout','--aliscoresout','--chkhmm','--chkali','--hmmout'];
  // (an argument of PLINK 2 is an option when it starts with - and goes on with neither a digit nor a dot: -1 is a number)
  const plinkFlag=a=>a.length>1&&a[0]==='-'&&!/[\d.]/.test(a[1])?a.replace(/^--?/,''):null;
  /* PLINK 2's threads and working memory. In the browser it computes on one or two threads, in 640 to 1024 MiB (640 is
     the least PLINK 2 takes): without --threads and --memory the terminal adds  --threads 1 --memory 640 require , as
     genomics-wasm's runner does; more threads become 2, more memory 1024 – with a note. --script and --rerun (options
     read from a file) are not available: the terminal must see those two options – and in this development version of
     PLINK 2, --script stops even the native program (a buffer overflow). --help, -h, --version and --zst-decompress need
     no memory; plink2 alone prints its summary. → the arguments, or {refuse: message} */
  function plink2Args(args,io){
    const names=args.map(plinkFlag);
    const bad=args.find((a,i)=>names[i]==='script'||names[i]==='rerun');
    if(bad)return {refuse:`plink2: ${bad} is not available here – the terminal must see every option of PLINK 2 (it sets its threads and its memory). Give the options on the command line, or read them from the file:  plink2 $(cat FILE)`};
    if(!args.length||['zst-decompress','zd'].includes(names[0])||names.some(n=>['help','h','version'].includes(n)))return args;
    const out=[];let threads=false,memory=false;
    for(let i=0;i<args.length;i++){
      const a=args[i],n=names[i];
      // (the values of an option: the arguments up to the next option)
      let j=i+1;while(j<args.length&&names[j]==null)j++;
      const vals=args.slice(i+1,j);
      if(['threads','thread-num','num_threads'].includes(n)){
        threads=true;
        if(vals.length===1&&/^\d+$/.test(vals[0])&&+vals[0]>2){
          out.push(a,'2');
          if(io&&io.note)io.note(`plink2: ${a} ${vals[0]} is ${a} 2 here – in the browser PLINK 2 computes on two threads at most.`);
        }else out.push(a,...vals);
        i=j-1;continue;
      }
      if(n==='memory'){
        memory=true;
        const k=vals.findIndex(v=>/^\d+$/.test(v));
        if(vals.length<=2&&k>=0&&+vals[k]>1024){
          const was=vals.join(' ');vals[k]='1024';
          if(io&&io.note)io.note(`plink2: ${a} ${was} is ${a} ${vals.join(' ')} here – in the browser PLINK 2 works in 1024 MiB of memory at most.`);
        }
        out.push(a,...vals);
        i=j-1;continue;
      }
      out.push(a);
    }
    if(!threads)out.push('--threads','1');
    if(!memory)out.push('--memory','640','require');
    return out;
  }
  /* date -r FILE: the time of the last change of a file. The page knows it; the programs' copy of the file is newer. */
  function dateArgs(ctx){
    const a=ctx.args,out=[];
    for(let i=0;i<a.length;i++){
      const v=a[i],m=/^--reference=(.*)$/.exec(v),c=/^-([uR]*)r(.*)$/.exec(v);
      let f=null;
      if(m)f=m[1];
      else if(v==='--reference')f=a[++i];
      else if(c){if(c[1])out.push('-'+c[1]);f=c[2]!==''?c[2]:a[++i];}
      else{out.push(v);if(/^-[uR]*[dfs]$/.test(v)&&i+1<a.length)out.push(a[++i]);continue;}
      const e=f!=null?ctx.fs.get(f):null;
      if(!e)throw MG.shellUtil.userErr(`date: ${f==null?'option requires an argument -- \'r\'':f+': No such file or directory'}`);
      out.push('-d','@'+Math.floor((e.mtime||Date.now())/1000));
    }
    return out;
  }
  /* cat FILE >> FILE, cat A FILE > FILE: GNU cat does not read a file that it is itself writing to once something is
     in it ("input file is output file") – it names the file, leaves it out, and ends with status 1. (After > the file
     is empty at first: cat FILE > FILE reads nothing, and nothing is said.) */
  async function catRun(ctx){
    const out=ctx.redirectTarget?ctx.fs.resolve(ctx.redirectTarget):ctx.toCaller&&ctx.io.outFile?ctx.io.outFile.path:null;
    const e=out&&ctx.redirectTarget!=='/dev/null'?ctx.fs.get(out):null;
    if(!e||e.kind==='dir')return runReal(ctx,'cat');
    const fromIt=ctx.stdin instanceof FileRef&&ctx.stdin.fromFile&&ctx.stdin.path===out;
    const names=[];let opts=true;
    for(const a of ctx.args){if(opts&&a==='--')opts=false;else if(!(opts&&a.startsWith('-')&&a!=='-'))names.push(a);}
    if(!fromIt&&!names.some(a=>a!=='-'&&ctx.fs.resolve(a)===out))return runReal(ctx,'cat');
    // how much is in the output file when cat comes to each of its inputs: with >> what was there, with > what cat
    // itself has written by then
    const sizeOf=async a=>{
      if(a!=='-'){const f=ctx.fs.get(a);return f&&f.kind!=='dir'?ctx.fs.size(f):0;}
      const s=ctx.stdin;
      return s==null?(ctx.inherit?1:0):s instanceof FileRef?(await MG.exec.readBytes(s)).length:String(s).length;
    };
    // (the file of a block – { echo start; cat FILE; } > FILE –: what the block has written into it so far counts)
    let written=ctx.redirectTarget?(ctx.redirectAppend?ctx.fs.size(e):0):ctx.fs.size(e);
    const args=[];let files=0,bad=0;opts=true;
    for(const a of ctx.args){
      if(opts&&a==='--'){opts=false;args.push(a);continue;}
      if(opts&&a.startsWith('-')&&a!=='-'){args.push(a);continue;}
      files++;
      const same=a==='-'?fromIt:ctx.fs.resolve(a)===out;
      if(same&&written>0){ctx.err(`cat: ${a}: input file is output file\n`);bad++;}
      else{args.push(a);if(!same)written+=await sizeOf(a);}
    }
    if(!files&&fromIt&&written>0){ctx.err('cat: -: input file is output file\n');return 1;}
    if(!bad)return runReal(ctx,'cat');
    if(bad===files)return 1;
    await withArgs(ctx,args,'cat');
    return 1;
  }
  /* tee /dev/stdout, tee /dev/stderr: one more copy of the input on the output (or among the messages). The page
     makes the copy: tee writes its input into a file of its own, too, and that file is printed once more. */
  async function teeRun(ctx){
    const isOut=a=>a==='/dev/stdout'||a==='/dev/fd/1',isErr=a=>a==='/dev/stderr'||a==='/dev/fd/2'||a==='/dev/tty';
    let opts=true,outs=0,errs=0;const args=[];
    for(const a of ctx.args){
      if(opts&&a==='--'){opts=false;args.push(a);}
      else if(opts&&a.startsWith('-')&&a!=='-')args.push(a);
      else if(isOut(a))outs++;
      else if(isErr(a))errs++;
      else args.push(a);
    }
    if(!outs&&!errs)return runReal(ctx,'tee');
    const copy=await MG.exec.tempFile();
    const code=await withArgs(ctx,[...args,MG.exec.argPath(copy)],'tee');
    let bytes;
    try{bytes=await MG.exec.readBytes(copy);}catch(e){return code;}
    try{await MG.exec.discard(copy);}catch(e){}
    // (tee /dev/stdout > FILE: on Linux both copies are written to the same place in FILE – it holds the input once)
    if(!ctx.redirectTarget)for(let k=0;k<outs;k++)if(bytes.length)ctx.out(bytes);
    for(let k=0;k<errs;k++)if(bytes.length)ctx.err(MG.shellUtil.bytesText(bytes));
    return code;
  }
  function binaryOutput(program,a){
    if(program==='samtools')return ['sort','merge','markdup','fixmate','collate'].includes(a[0])&&!a.some(x=>x==='SAM'||x==='sam'||/^(-O|--output-fmt=)sam(,|$)/i.test(x))||a[0]==='view'&&a.some(x=>/^-[A-Za-z]*[bu]/.test(x))&&!a.some(x=>x==='-c'||x==='--count');
    if(program==='bcftools')return a.some((x,i)=>/^-[A-Za-z]*O[buz]/.test(x)||x==='-O'&&/^[buz]/.test(a[i+1]||'')||/^--output-type=[buz]/.test(x));
    // lofreq indelqual and viterbi write BAM to the standard output unless -o names a file; alnqual with -b or -u
    if(program==='lofreq'){
      if(a[0]==='alnqual')return a.slice(1).some(x=>/^-[A-Za-z]*[bu]/.test(x));
      if(a[0]!=='indelqual'&&a[0]!=='viterbi')return false;
      let o=null;
      for(let i=1;i<a.length;i++){if(a[i]==='-o'||a[i]==='--out')o=a[++i];else if(/^--out=/.test(a[i]))o=a[i].slice(6);else if(/^-o./.test(a[i]))o=a[i].slice(2);}
      return o==null||o==='-';
    }
    return program==='bgzip'&&!a.some(x=>/^-\w*d/.test(x)||x==='--decompress');
  }
  /* Messages of the programs: paths as the person sees them (the backend knows where its files are) */
  const tidy=(text,name)=>MG.exec.tidy(text,name);
  async function runReal(ctx,program,opts={}){
    // this build of jq does not know its own version number
    if(program==='jq'&&ctx.args.length===1&&(ctx.args[0]==='--version'||ctx.args[0]==='-V')){ctx.out('jq-'+MG.exec.versions.jq+'\n');return 0;}
    const binary=binaryOutput(program,ctx.args),r=await MG.exec.run(ctx,program,ctx.args,{...opts,binaryOut:binary});
    if(r.stdinUsed!=null)ctx.stdinUsed=r.stdinUsed;
    // Messages and output that go the same way – to the terminal, or to whoever takes the output of the block or
    // the script this command stands in – are passed on in the order in which the program wrote them. (To the
    // terminal as text; to a block's file or pipe the output goes as bytes, as it is.)
    const inTurn=!!r.parts&&!ctx.redirectTarget&&!!ctx.toCaller;
    // (> FILE 2>&1: the program's messages are in its output already; what the page adds – "… is read-only: the
    // change to it was undone" – follows them into the file)
    const tailBytes=ctx.mergeStderr&&ctx.redirectTarget&&r.tail?new TextEncoder().encode(tidy(r.tail,ctx.name||program).replace(/^\n/,'')):null;
    if(inTurn){
      const name=ctx.name||program,od=new TextDecoder('utf-8',{ignoreBOM:true}),ed=new TextDecoder('utf-8',{ignoreBOM:true});
      for(const [fd,bytes] of r.parts){
        if(!bytes.length)continue;
        if(fd===2)ctx.err(tidy(ed.decode(bytes,{stream:true}),name));
        else if(ctx.isPipedOut)ctx.out(bytes);
        else ctx.out(tidy(od.decode(bytes,{stream:true}),name));
      }
      if(r.tail)ctx.err(tidy(r.tail,name));
    }else if(r.stderr&&!tailBytes)ctx.err(tidy(r.stderr,ctx.name||program));
    if(inTurn){/* (passed on above) */}
    else if(ctx.redirectTarget){
      if(ctx.redirectTarget!=='/dev/null'){
        const target=ctx.fs.resolve(ctx.redirectTarget);
        // (The program printed nothing: the file stays as it was opened – made, or emptied, before the program ran –
        // or as the program itself wrote it by name:  samtools sort x.bam -o s.bam > s.bam 2>&1,  sort -o F a > F.)
        await MG.exec.writeOutput(ctx.fs,target,r.out,{tail:tailBytes,append:ctx.redirectAppend});
        r.created.push(target);MG.bus.emit('vfs:created',{path:target,program,sub:ctx.args[0]});
      }
      ctx.wroteRedirect=true;
    }else if(ctx.isPipedOut){r.out.binary=binary;ctx.out(r.out);}
    else if(binary&&r.stdoutSize){
      // (what the options promise is not always what was written: samtools view -b -c prints a count, and so text)
      let text=null;
      if(r.stdoutSize<=4194304)try{const t=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(await MG.exec.readBytes(r.out));if(t.indexOf('\u0000')<0)text=t;}catch(e){}
      if(text!=null)ctx.out(tidy(text,ctx.name||program));
      else ctx.io.note(`Binary output: ${MG.humanSize(r.stdoutSize)} bytes. Save with > FILE, or inspect using samtools/bcftools view.`);
    }
    // (… and the other way round: BAM where the options did not say so – samtools view --bam, -1 – is not text for the screen)
    else if(r.stdout&&r.stdout.slice(0,4096).indexOf('\u0000')>=0&&/^(samtools|bcftools|bgzip)$/.test(program))ctx.io.note(`Binary output: ${MG.humanSize(r.stdoutSize)} bytes. Save with > FILE, or inspect using samtools/bcftools view.`);
    else if(r.stdout)ctx.out(r.stdout);
    MG.bus.emit('tool:run',{program,sub:ctx.args[0]||'',args:ctx.args,code:r.code,secs:r.secs,created:r.created,real:true,line:ctx.rawLine,statusKnown:r.statusKnown});
    return r.code;
  }
  MG.runReal=runReal;
  /* A browser tab runs these programs on one thread. Asked for more, these builds stop (minimap2, BWA, HISAT2) or
     abort (samtools, bcftools), so the option is left out – and the terminal says so.
     short/long: the options that ask for threads; one: the values that ask for no more than there is (the option then
     stays as it was written); when: only for these subcommands (bwa index has no -t); why: the reason the note gives;
     cap: instead of leaving the option out, ask for this many (featureCounts counts on up to four threads here). */
  const THREADS={
    samtools:{short:'-@',long:'--threads',one:v=>v==='0'},
    bcftools:{long:'--threads',one:v=>v==='0'},
    minimap2:{short:'-t',one:v=>v==='1'},
    bgzip:{short:'-@',long:'--threads',one:v=>v==='0'||v==='1'},
    bwa:{short:'-t',one:v=>v==='1',when:a=>/^(mem|aln|bwasw)$/.test(a[0]||'')},
    'bwa-mem2':{short:'-t',one:v=>v==='1',when:a=>a[0]==='mem'},
    hisat2:{short:'-p',long:'--threads',one:v=>v==='1'},
    'hisat2-build':{short:'-p',long:'--threads',one:v=>v==='1'},
    stringtie:{short:'-p',one:v=>v==='1'},
    kallisto:{short:'-t',long:'--threads',one:v=>v==='1',when:a=>/^(index|quant)$/.test(a[0]||'')},
    // (mosdepth's -t: threads that unpack the BAM file besides the main one – 0, its default, is the only value here)
    mosdepth:{short:'-t',long:'--threads',one:v=>v==='0'},
    featureCounts:{short:'-T',one:v=>/^[1-4]$/.test(v),cap:'4',why:'in the browser featureCounts counts on four threads at most'},
    salmon:{short:'-p',long:'--threads',one:v=>v==='1',when:a=>/^(index|quant)$/.test(a[0]||''),why:'in the browser Salmon runs one worker thread'},
    cutadapt:{short:'-j',long:'--cores',one:v=>v==='1',why:'in the browser Cutadapt runs on one core'},
    lofreq:{long:'--threads',one:v=>v==='1',when:a=>a[0]==='somatic',why:'in the browser lofreq somatic runs its steps one after another'},
    // (bustools sort -t: threads; bustools count -t is a file of transcript names)
    bustools:{short:'-t',long:'--threads',one:v=>v==='1',when:a=>a[0]==='sort',why:'in the browser bustools sorts on one thread'},
    // (HMMER without threads has no --cpu at all: the option goes, whatever its value)
    ...Object.fromEntries(HMMER.map(p=>[p,{long:'--cpu',one:()=>false,why:'in the browser HMMER runs on one thread'}]))
  };
  function oneThread(name,args,io){
    const t=THREADS[name];
    if(!t||(t.when&&!t.when(args)))return args;
    const glued=a=>t.short&&a.length>t.short.length&&a.startsWith(t.short)&&/^\d+$/.test(a.slice(t.short.length))?a.slice(t.short.length):t.long&&a.startsWith(t.long+'=')&&/^\d+$/.test(a.slice(t.long.length+1))?a.slice(t.long.length+1):null;
    const out=[];let dropped='';
    for(let i=0;i<args.length;i++){
      const a=args[i];
      if(a==='--'){out.push(...args.slice(i));break;}
      const sep=a===t.short||a===t.long,g=sep?null:glued(a);
      if(sep){if(t.one(args[i+1])){out.push(a,args[++i]);}else{dropped=a+' '+(args[i+1]||'');if(t.cap&&/^\d+$/.test(args[i+1]||''))out.push(a,t.cap);i++;}continue;}
      if(g!=null){if(t.one(g))out.push(a);else{dropped=a;if(t.cap)out.push(t.short,t.cap);}continue;}
      out.push(a);
    }
    if(dropped&&io&&io.note)io.note(t.cap?`${name}: ${dropped.trim()} is ${t.short} ${t.cap} here – ${t.why}.`:`${name}: ${dropped.trim()} left out – ${t.why||'in the browser every program runs on one thread'}.`);
    return out;
  }
  /* Run with other arguments on the same context object: the shell reads what a program did
     (a redirect already written, for one) from that object afterwards. */
  async function withArgs(ctx,args,program){
    const given=ctx.args;ctx.args=args;
    try{return await runReal(ctx,program);}finally{ctx.args=given;}
  }
  const T=MG.shellTools=MG.shellTools||{};
  // [program, version, summary, example] – the name typed in the terminal can differ from the program file
  const definitions={
    fastp:['fastp','0.20.1','Quality control, adapter and quality trimming of FASTQ files; writes an HTML and a JSON report','fastp -i /data/examples/reads/NA12878_R1.fastq -I /data/examples/reads/NA12878_R2.fastq -o trimmed_R1.fastq -O trimmed_R2.fastq -h fastp.html -j fastp.json\nopen fastp.html'],
    minimap2:['minimap2','2.22','Minimizer-based alignment; use -ax sr for short paired reads','minimap2 -ax sr /data/examples/reads/reference.fa /data/examples/reads/NA12878_R1.fastq /data/examples/reads/NA12878_R2.fastq > mapped.sam'],
    bowtie2:['bowtie2-align-s','2.4.2','Bowtie 2 short-read aligner (needs an index from bowtie2-build)','bowtie2-build /data/examples/reads/reference.fa reference\nbowtie2 -x reference -1 /data/examples/reads/NA12878_R1.fastq -2 /data/examples/reads/NA12878_R2.fastq -S mapped.sam'],
    'bowtie2-align-s':['bowtie2-align-s','2.4.2','Bowtie 2 aligner (the program behind the bowtie2 command)','bowtie2-align-s -x reference -1 /data/examples/reads/NA12878_R1.fastq -2 /data/examples/reads/NA12878_R2.fastq -S mapped.sam'],
    'bowtie2-build':['bowtie2-build-s','2.4.2','Builds a Bowtie 2 index from a FASTA file (six .bt2 files)','bowtie2-build /data/examples/reads/reference.fa reference'],
    'bowtie2-build-s':['bowtie2-build-s','2.4.2','Builds a Bowtie 2 index (the program behind bowtie2-build)','bowtie2-build-s /data/examples/reads/reference.fa reference'],
    samtools:['samtools','1.17','Inspect, sort, index and transform SAM/BAM/CRAM','samtools sort -o mapped.bam mapped.sam\nsamtools index mapped.bam\nsamtools flagstat mapped.bam'],
    bcftools:['bcftools','1.10','Genotype likelihoods, calling models, normalisation and VCF operations','bcftools mpileup -f /data/examples/reads/reference.fa mapped.bam | bcftools call -mv -Oz -o calls.vcf.gz\nbcftools view -H calls.vcf.gz | head\nUse bcftools COMMAND --help for the options of a command.'],
    bgzip:['bgzip','1.17','Block gzip compression / decompression (BGZF files are valid gzip files)','bgzip -c INPUT > OUTPUT.gz'],
    tabix:['tabix','1.17','Index and query sorted tabular BGZF data','tabix -p vcf calls.vcf.gz'],
    seqtk:['seqtk','1.4','Toolkit for FASTA/FASTQ files: subsample, convert, trim, statistics','seqtk fqchk /data/examples/reads/NA12878_R1.fastq | head\nseqtk sample -s 11 /data/examples/reads/NA12878_R1.fastq 1000 > sample.fastq'],
    bedtools:['bedtools','2.31.0','Genome arithmetic on BED, VCF, SAM/BAM files','bedtools genomecov -ibam mapped.bam -bg | head'],
    jq:['jq','1.7','Command-line JSON processor','jq .summary fastp.json'],
    kalign:['kalign','3.3.1','Multiple sequence alignment of DNA, RNA or protein sequences (fast and accurate)','kalign -i /data/examples/sequences/myoglobins.fasta -o myoglobins.afa\nkalign -i seqs.fasta -f clu -o aligned.aln      (Clustal format; also msf)\n\nAlways give the output file with -o: this version of kalign prints its banner on the standard output\ntoo, so  kalign -i seqs.fasta > aligned.afa  would put the banner into the file.\n(The warning about AVX2 means only that this build does not use the processor\'s vector instructions.)'],
    muscle:['muscle','3.8.1551','Multiple sequence alignment (MUSCLE version 3)','muscle -in /data/examples/sequences/myoglobins.fasta -out myoglobins.afa\nmuscle -in seqs.fasta -clw -out aligned.aln      (Clustal format)\nmuscle -in seqs.fasta -maxiters 2 -out quick.afa  (faster, for many sequences)'],
    fasttree:['fasttree','2.1.11','Approximately-maximum-likelihood phylogenetic trees from a multiple alignment','fasttree myoglobins.afa > myoglobins.nwk          (protein: JTT+CAT)\nfasttree -nt -gtr dna_aligned.fasta > tree.nwk   (DNA: GTR+CAT)\nopen myoglobins.nwk                              (draws the tree)'],
    FastTree:['fasttree','2.1.11','FastTree (the same program as fasttree)','FastTree aligned.fasta > tree.nwk'],
    needleman_wunsch:['needleman_wunsch','2017.10.18','Global pairwise alignment (Needleman–Wunsch), from seq-align','needleman_wunsch GATTACA GCATGCT\nneedleman_wunsch --match 1 --mismatch -1 --gapopen 0 --gapextend -1 GATTACA GCATGCT\nneedleman_wunsch --printscores --file two_sequences.fasta\nneedleman_wunsch --help'],
    smith_waterman:['smith_waterman','2017.10.18','Local pairwise alignment (Smith–Waterman), from seq-align','smith_waterman ACACACTA AGCACACA\nsmith_waterman --printscores --file two_sequences.fasta\nsmith_waterman --help'],
    lcs:['lcs','2017.10.18','Repeated substrings of a sequence, longest first (from seq-align)','lcs GATTACAGATTACA\n(each line: a substring that occurs twice, and the two positions where it starts, counted from 0)'],
    wgsim:['wgsim','0.3.1-r13','Simulates paired-end reads from a reference, with sequencing errors and mutations','wgsim -N 1000 -1 100 -2 100 -S 11 /data/examples/reads/reference.fa sim_R1.fastq sim_R2.fastq\n(-e error rate, -r mutation rate, -d/-s fragment length and its spread, -S seed: the same seed gives the same reads)'],
    gffread:['gffread','0.12.7','GFF/GTF files: check, convert, and write transcript, CDS or protein sequences','gffread /data/examples/annotation/cyp2c_slices.gff3 -T -o cyp2c.gtf          (GFF3 to GTF)\ngffread /data/examples/annotation/cyp2c_slices.gff3 -g /data/examples/reads/reference.fa -w transcripts.fa -y proteins.fa'],
    lastz:['lastz','1.04.52','Pairwise alignment of long DNA sequences (regions, chromosomes, small genomes)',"lastz '/data/examples/reads/reference.fa[multiple]' query.fa --format=general > hits.tsv\nlastz target.fa query.fa --format=maf > aln.maf\n([multiple]: the target file holds more than one sequence)"],
    bwa:['bwa','0.7.19','BWA: indexes a reference and maps short reads to it (bwa index, bwa mem)',"cp /data/examples/reads/reference.fa .        (bwa index writes five files next to the FASTA file)\nbwa index reference.fa\nbwa mem reference.fa /data/examples/reads/NA12878_R1.fastq /data/examples/reads/NA12878_R2.fastq > bwa.sam\nbwa mem -R '@RG\\tID:NA12878\\tSM:NA12878' reference.fa R1.fastq R2.fastq > bwa.sam    (with a read group)\n\nbwa mem reads .fastq.gz files too. bwa mem -t N: one thread in the browser."],
    hisat2:['hisat2','2.2.2','HISAT2: maps RNA-seq reads, across splice junctions (needs an index from hisat2-build)',"hisat2-build /data/examples/rnaseq/yeast_chrI.fa yeast_chrI\nhisat2 -x yeast_chrI -1 /data/examples/rnaseq/SRR6357070_1.fastq -2 /data/examples/rnaseq/SRR6357070_2.fastq -S rnaseq.sam\nhisat2 -x yeast_chrI -U reads.fastq -S out.sam --no-unal                (single reads; leave out the reads that do not map)\nhisat2 ... --known-splicesite-infile /data/examples/rnaseq/yeast_chrI.splice_sites.tsv    (known junctions)\n\n.gz files are unpacked first, as hisat2's wrapper script does. hisat2 -p N: one thread in the browser."],
    'hisat2-build':['hisat2','2.2.2','Builds a HISAT2 index from a FASTA file (eight .ht2 files)','hisat2-build /data/examples/rnaseq/yeast_chrI.fa yeast_chrI\n(writes yeast_chrI.1.ht2 … yeast_chrI.8.ht2; hisat2 -x yeast_chrI uses them)'],
    'hisat2-inspect':['hisat2','2.2.2','Shows what is in a HISAT2 index','hisat2-inspect -s yeast_chrI       (a summary: the sequences and their lengths)\nhisat2-inspect -n yeast_chrI       (the names of the sequences)'],
    'bwa-mem2':['bwa-mem2','2.2.1','BWA-MEM2: bwa mem\'s algorithm, rewritten for speed – indexes a reference and maps short reads (bwa-mem2 index, bwa-mem2 mem)',"cp /data/examples/reads/reference.fa .        (bwa-mem2 index writes five files next to the FASTA file)\nbwa-mem2 index reference.fa\nbwa-mem2 mem reference.fa /data/examples/reads/NA12878_R1.fastq /data/examples/reads/NA12878_R2.fastq > bwamem2.sam\nbwa-mem2 mem -R '@RG\\tID:NA12878\\tSM:NA12878' reference.fa R1.fastq R2.fastq > bwamem2.sam    (with a read group)\n\nbwa-mem2 needs an index of its own (.0123, .amb, .ann, .bwt.2bit.64, .pac): one made by bwa index does not do.\nIt takes a few hundred MB of memory even for a small reference, and in the browser it is not faster than bwa.\nbwa-mem2 mem -t N: one thread in the browser."],
    stringtie:['stringtie','3.0.3','StringTie: assembles transcripts from RNA-seq alignments and estimates their abundance (BAM sorted by position)',"stringtie rnaseq.bam -G /data/examples/rnaseq/yeast_chrI.gtf -o transcripts.gtf -A gene_abundance.tsv\nstringtie -e -B rnaseq.bam -G /data/examples/rnaseq/yeast_chrI.gtf -o ballgown/rnaseq/rnaseq.gtf   (-e: the annotated transcripts only; -B: the tables of Ballgown)\nstringtie --merge -G /data/examples/rnaseq/yeast_chrI.gtf -o merged.gtf sample1.gtf sample2.gtf\n\nMap the reads with hisat2 --dta (alignments made for transcript assembly) and sort them (samtools sort).\nstringtie -p N: one thread in the browser."],
    kallisto:['kallisto','0.52.0','kallisto: transcript abundances from RNA-seq reads by pseudoalignment – no alignments, no BAM file',"gffread -w transcripts.fa -g /data/examples/rnaseq/yeast_chrI.fa /data/examples/rnaseq/yeast_chrI.gtf   (the transcript sequences)\nkallisto index -i transcripts.idx transcripts.fa\nkallisto quant -i transcripts.idx -o kallisto_out /data/examples/rnaseq/SRR6357070_1.fastq /data/examples/rnaseq/SRR6357070_2.fastq\nhead kallisto_out/abundance.tsv      (est_counts and tpm of every transcript)\nkallisto quant -i transcripts.idx -o single --single -l 200 -s 20 reads.fastq    (single reads: give the fragment length and its spread)\n\nThe results are abundance.tsv and run_info.json: this build writes no .h5 file and no BAM file (bootstraps: -b N --plaintext).\nkallisto -t N: one thread in the browser."],
    mosdepth:['mosdepth','0.3.14','mosdepth: read depth (coverage) of a BAM file – per base, in windows or in regions, with a summary',"samtools index rnaseq.bam                    (mosdepth needs the index of the BAM file, .bai)\nmosdepth yeast rnaseq.bam                    (yeast.mosdepth.summary.txt, yeast.mosdepth.global.dist.txt, yeast.per-base.bed.gz)\ncat yeast.mosdepth.summary.txt               (the length, the bases and the mean depth of each sequence)\nmosdepth -n --by 1000 windows rnaseq.bam     (the mean depth in windows of 1000 bp; -n: no per-base file)\nmosdepth --by /data/examples/annotation/cyp2c_exons.bed --thresholds 1,10,20 exons mapped.bam   (the regions of a BED file)\nzcat yeast.per-base.bed.gz | head\n\nmosdepth keeps an array as long as the longest sequence of the BAM file: fine for yeast chromosomes and the example\nslices, too big for a whole human chromosome in a browser. mosdepth -t N: not in the browser."],
    featureCounts:['featurecounts','2.1.1','featureCounts (Subread): counts the reads in each gene of an annotation – the count table for DESeq2 or edgeR',"featureCounts -p --countReadPairs -a /data/examples/rnaseq/yeast_chrI.gtf -o counts.txt rnaseq.bam   (paired reads: a count per fragment)\ntail -n +3 counts.txt | sort -k7,7nr | head        (the genes with the most reads)\ncat counts.txt.summary      (why reads were not counted: Unassigned_NoFeatures, _Ambiguity, _MultiMapping …)\nfeatureCounts -a genes.gtf -o counts.txt single.bam                       (single reads)\nfeatureCounts -s 2 -p --countReadPairs -a genes.gtf -o counts.txt s1.bam s2.bam s3.bam   (a reverse-stranded library; a column per file)\n\nPaired reads need -p: without it featureCounts 2.1 stops (\"Paired-end reads were detected in single-end read library\").\nfeatureCounts counts on several threads (-T 1 to 4; one unless asked for more). That needs a page that is\ncross-origin isolated, which the workbench makes its page as it starts – see Limits in the help."],
    salmon:['salmon','2.8.0','Salmon: transcript abundances from RNA-seq reads, by selective alignment to the transcript sequences',"gffread -w transcripts.fa -g /data/examples/rnaseq/yeast_chrI.fa /data/examples/rnaseq/yeast_chrI.gtf   (the transcript sequences)\nsalmon index -t transcripts.fa -i salmon_index\nsalmon quant -i salmon_index -l A -1 /data/examples/rnaseq/SRR6357070_1.fastq -2 /data/examples/rnaseq/SRR6357070_2.fastq -o salmon_out\nhead salmon_out/quant.sf        (NumReads and TPM of every transcript)\nsalmon quant -i salmon_index -l U -r reads.fastq --fldMean 200 --fldSD 20 -o single    (single reads)\n\n-l A: Salmon works out the library type (salmon_out/lib_format_counts.json says which).\nAn index made by Salmon on a 64-bit computer cannot be read here, nor one made here there: make it where you use it.\nsalmon -p N: one worker thread in the browser. Like featureCounts, Salmon needs a cross-origin isolated page."],
    cutadapt:['cutadapt','5.2','Cutadapt: removes adapters, primers and poly-A tails from reads, trims low-quality ends and filters reads by length',"cutadapt -a AGATCGGAAGAGCACACGTCTGAACTCCAGTCA -A AGATCGGAAGAGCGTCGTGTAGGGAAAGAGTGT -o trimmed_1.fastq -p trimmed_2.fastq /data/examples/trimming/SRR6357070_adapters_1.fastq /data/examples/trimming/SRR6357070_adapters_2.fastq\ncutadapt -q 20 -m 50 -a AGATCGGAAGAGC -o trimmed.fastq reads.fastq      (also trim 3' ends below quality 20; keep reads of 50 bases or more)\ncutadapt -g ^ACGTACGT -o out.fastq.gz reads.fastq.gz                    (a 5' adapter anchored at the start; .gz in and out)\ncutadapt --discard-untrimmed -a ADAPTER -o with_adapter.fastq reads.fastq   (keep only the reads that had the adapter)\ncutadapt ... --json report.json                                         (the report as JSON too, for MultiQC)\n\n-a/-A: the 3' adapter of read 1/read 2 (-g/-G: 5'); -e: error rate (0.1); -O: shortest overlap that counts (3).\nThe report (on the screen, or > report.txt) says how many reads had the adapter and how many bases were removed.\nCutadapt runs on one core here (-j N is left out, with a note). It is a Python program: each command starts the Python\nthat comes with it, which takes a few seconds."],
    lofreq:['lofreq','2.1.5','LoFreq: calls variants, also those at low frequencies (lofreq call), and somatic variants from a tumour and its normal (lofreq somatic)',"lofreq call -f /data/examples/somatic/reference.fa -o tumor_calls.vcf /data/examples/somatic/tumor.bam     (SNVs, at any allele frequency)\n\nSomatic variants – first give the reads indel qualities (needed for --call-indels), then index:\nlofreq indelqual --dindel -f /data/examples/somatic/reference.fa -o tumor.iq.bam /data/examples/somatic/tumor.bam\nlofreq indelqual --dindel -f /data/examples/somatic/reference.fa -o normal.iq.bam /data/examples/somatic/normal.bam\nsamtools index tumor.iq.bam && samtools index normal.iq.bam\nlofreq somatic -n normal.iq.bam -t tumor.iq.bam -f /data/examples/somatic/reference.fa --call-indels -o lofreq_\nzcat lofreq_somatic_final.snvs.vcf.gz | grep -v '^##'       (the somatic SNVs; lofreq_somatic_final.indels.vcf.gz: the indels)\n\nlofreq somatic runs lofreq call, filter, vcfset and uniq one after another, as upstream's script does; its options\nare upstream's (lofreq somatic -h), with --threads 1. LoFreq's authors call this workflow experimental.\nNot here: lofreq call-parallel and lofreq vcfplot (Python scripts that start other programs)."],
    'bam-somaticsniper':['somaticsniper','1.0.5.0','SomaticSniper: somatic SNVs from a tumour BAM and its matched normal BAM',"bam-somaticsniper -F vcf -f /data/examples/somatic/reference.fa /data/examples/somatic/tumor.bam /data/examples/somatic/normal.bam somaticsniper.vcf\ngrep -v '^##' somaticsniper.vcf | head      (the columns NORMAL and TUMOR; SS=2 in FORMAT: somatic)\nbam-somaticsniper -F vcf -Q 40 -L -G -f ref.fa tumor.bam normal.bam strict.vcf    (somatic score 40 or more; no LOH, no gain of reference)\n\nThe tumour BAM comes first, then the normal BAM, then the output file. Both BAM files must be sorted by position and\nmust name the same chromosomes, in the same order; the reference needs its .fai index (samtools faidx).\n-F vcf|classic|bed: output format (classic by default); -q: minimum mapping quality; -Q: minimum somatic score (15);\n-n/-t: the sample names in the VCF. -t is the name of the tumour sample, not a number of threads."],
    somaticsniper:['somaticsniper','1.0.5.0','SomaticSniper (the program behind bam-somaticsniper)',"somaticsniper -F vcf -f ref.fa tumor.bam normal.bam calls.vcf     (the same as bam-somaticsniper)"],
    prodigal:['prodigal','2.6.3',"Prodigal: finds the protein-coding genes of bacteria and archaea in a genome (GFF, GenBank, proteins)","prodigal -i /data/examples/bacteria/ecoli.fna -o ecoli.gff -f gff -a ecoli.faa -d ecoli.ffn\nhead -4 ecoli.gff        (each gene: where it starts and ends, its strand and Prodigal's scores)\ngrep -c '>' ecoli.faa    (the proteins, one per gene)\nprodigal -p meta -i /data/examples/bacteria/combined.fna -o meta.gff -f gff     (contigs of several genomes)\n\n-p single (the default): Prodigal learns the genome's own model first – it needs 20,000 bases at least, and 100,000\nare better; -p meta: preset models, for metagenomes and short sequences. -f gbk|gff|sco (gbk by default); -o FILE (else\nthe standard output); -a FILE: the proteins; -d FILE: the genes' DNA; -s FILE: every possible start, with its scores;\n-c: no genes running off the ends of a sequence; -g 4: another genetic code (11, bacteria and archaea, by default);\n-t FILE: save the training (or use it, when FILE is there); -q: no messages. Prodigal reads plain FASTA, GenBank or\nEMBL – not .gz files."],
    hmmbuild:['hmmbuild','3.4',"HMMER: builds a profile HMM from a multiple sequence alignment","hmmbuild globins4.hmm /data/examples/hmmer/globins4.sto      (a profile of the four globins of the alignment)\nhmmbuild -n kinase kinase.hmm /data/examples/hmmer/Pkinase.sto\n\nThe alignment: Stockholm (.sto), aligned FASTA or Clustal; the profile is written to the first file. --amino, --dna,\n--rna: the alphabet, when HMMER cannot tell; -n NAME: the profile's name; --seed N: the seed of the calibration (42).\n\nOne thread here: --cpu is left out, with a note. Files compressed with gzip (.gz) cannot be read here – HMMER would\nstart gzip for them: unpack them first (gunzip -k FILE.gz). -h lists every option; the HMMER User's Guide explains them."],
    hmmsearch:['hmmsearch','3.4',"HMMER: searches a sequence database with a profile HMM","hmmsearch globins4.hmm /data/examples/hmmer/globins45.fa > globins.out\nhmmsearch --tblout hits.tbl --domtblout domains.tbl -E 1e-5 globins4.hmm proteins.faa\n\nThe output ranks the sequences by E-value, then shows each one's domains and alignments; --tblout and --domtblout write\nthe hits as tables (one line per sequence, one per domain). -E, -T: the thresholds of what is reported; --cut_ga: the\nprofile's own (Pfam's gathering) thresholds; --noali: no alignments.\n\nOne thread here: --cpu is left out, with a note. Files compressed with gzip (.gz) cannot be read here – HMMER would\nstart gzip for them: unpack them first (gunzip -k FILE.gz). -h lists every option; the HMMER User's Guide explains them."],
    hmmscan:['hmmscan','3.4',"HMMER: searches a database of profile HMMs with sequences (which domains does a protein have?)","cat /data/examples/hmmer/globins4.hmm /data/examples/hmmer/fn3.hmm /data/examples/hmmer/Pkinase.hmm > minifam.hmm\nhmmpress minifam.hmm            (hmmscan needs the four files of hmmpress next to the profiles)\nhmmscan minifam.hmm /data/examples/hmmer/7LESS_DROME\nhmmscan --domtblout domains.tbl minifam.hmm proteins.faa\n\nFor a few sequences against many profiles (Pfam): hmmscan; for profiles against many sequences: hmmsearch.\n\nOne thread here: --cpu is left out, with a note. Files compressed with gzip (.gz) cannot be read here – HMMER would\nstart gzip for them: unpack them first (gunzip -k FILE.gz). -h lists every option; the HMMER User's Guide explains them."],
    hmmpress:['hmmpress','3.4',"HMMER: prepares a file of profile HMMs for hmmscan (writes .h3m, .h3i, .h3f and .h3p)","cat /data/examples/hmmer/globins4.hmm /data/examples/hmmer/fn3.hmm /data/examples/hmmer/Pkinase.hmm > minifam.hmm\nhmmpress minifam.hmm\n\nThe four files are written next to the profiles (not in /data: copy the profiles first). -f writes them again.\n\nOne thread here: --cpu is left out, with a note. Files compressed with gzip (.gz) cannot be read here – HMMER would\nstart gzip for them: unpack them first (gunzip -k FILE.gz). -h lists every option; the HMMER User's Guide explains them."],
    hmmfetch:['hmmfetch','3.4',"HMMER: takes one profile (or several) out of a file of profiles","hmmfetch minifam.hmm fn3 > fn3.hmm\nhmmfetch --index minifam.hmm         (an SSI index, minifam.hmm.ssi: quicker for large files)\nhmmfetch -f minifam.hmm names.txt > some.hmm   (the profiles named in a file)\n\nOne thread here: --cpu is left out, with a note. Files compressed with gzip (.gz) cannot be read here – HMMER would\nstart gzip for them: unpack them first (gunzip -k FILE.gz). -h lists every option; the HMMER User's Guide explains them."],
    hmmalign:['hmmalign','3.4',"HMMER: aligns sequences to a profile HMM","hmmalign globins4.hmm /data/examples/hmmer/globins45.fa > globins45.sto\nhmmalign --outformat afa -o globins45.afa globins4.hmm /data/examples/hmmer/globins45.fa      (aligned FASTA)\n\nThe alignment is Stockholm by default: columns of the profile in upper case, insertions in lower case; the #=GR … PP\nlines are the confidence of each residue (0-9, * for the most).\n\nOne thread here: --cpu is left out, with a note. Files compressed with gzip (.gz) cannot be read here – HMMER would\nstart gzip for them: unpack them first (gunzip -k FILE.gz). -h lists every option; the HMMER User's Guide explains them."],
    hmmconvert:['hmmconvert','3.4',"HMMER: converts profile HMMs between file formats","hmmconvert globins4.hmm > globins4.v3.hmm       (HMMER3's own format, written again)\nhmmconvert -2 globins4.hmm > globins4.hmm2      (HMMER2 format)\nhmmconvert -b globins4.hmm > globins4.bin       (binary)\n\nOne thread here: --cpu is left out, with a note. Files compressed with gzip (.gz) cannot be read here – HMMER would\nstart gzip for them: unpack them first (gunzip -k FILE.gz). -h lists every option; the HMMER User's Guide explains them."],
    hmmemit:['hmmemit','3.4',"HMMER: writes sequences that a profile HMM would produce – or its consensus","hmmemit -N 5 --seed 42 globins4.hmm       (five sampled sequences)\nhmmemit -c globins4.hmm                   (the consensus sequence)\n\nOne thread here: --cpu is left out, with a note. Files compressed with gzip (.gz) cannot be read here – HMMER would\nstart gzip for them: unpack them first (gunzip -k FILE.gz). -h lists every option; the HMMER User's Guide explains them."],
    hmmstat:['hmmstat','3.4',"HMMER: one line about each profile in a file (its length, the sequences it was built from …)","hmmstat minifam.hmm\n\nOne thread here: --cpu is left out, with a note. Files compressed with gzip (.gz) cannot be read here – HMMER would\nstart gzip for them: unpack them first (gunzip -k FILE.gz). -h lists every option; the HMMER User's Guide explains them."],
    phmmer:['phmmer','3.4',"HMMER: searches a sequence database with one protein sequence (like BLASTP, with HMMER's statistics)","phmmer /data/examples/hmmer/HBB_HUMAN /data/examples/hmmer/globins45.fa\nphmmer --tblout hits.tbl -E 1e-10 query.faa proteins.faa\n\nOne thread here: --cpu is left out, with a note. Files compressed with gzip (.gz) cannot be read here – HMMER would\nstart gzip for them: unpack them first (gunzip -k FILE.gz). -h lists every option; the HMMER User's Guide explains them."],
    jackhmmer:['jackhmmer','3.4',"HMMER: searches a sequence database again and again with a profile it builds from what it finds","jackhmmer -N 3 /data/examples/hmmer/HBB_HUMAN /data/examples/hmmer/globins45.fa      (at most three rounds; it stops when nothing new comes)\njackhmmer --chkhmm round -N 3 query.faa proteins.faa   (the profile of each round: round-1.hmm …)\n\nOne thread here: --cpu is left out, with a note. Files compressed with gzip (.gz) cannot be read here – HMMER would\nstart gzip for them: unpack them first (gunzip -k FILE.gz). -h lists every option; the HMMER User's Guide explains them."],
    nhmmer:['nhmmer','3.4',"HMMER: searches DNA sequences with a DNA profile HMM (or a sequence, or an alignment) – on both strands","nhmmer /data/examples/hmmer/MADE1.hmm /data/examples/hmmer/dna_target.fa\nnhmmer --tblout made1.tbl /data/examples/hmmer/MADE1.hmm /data/examples/hmmer/dna_target.fa\n\nOne thread here: --cpu is left out, with a note. Files compressed with gzip (.gz) cannot be read here – HMMER would\nstart gzip for them: unpack them first (gunzip -k FILE.gz). -h lists every option; the HMMER User's Guide explains them."],
    nhmmscan:['nhmmscan','3.4',"HMMER: searches DNA sequences against a database of DNA profile HMMs","cp /data/examples/hmmer/MADE1.hmm . && hmmpress MADE1.hmm\nnhmmscan MADE1.hmm /data/examples/hmmer/dna_target.fa\n\nOne thread here: --cpu is left out, with a note. Files compressed with gzip (.gz) cannot be read here – HMMER would\nstart gzip for them: unpack them first (gunzip -k FILE.gz). -h lists every option; the HMMER User's Guide explains them."],
    bustools:['bustools','0.45.1',"bustools: single-cell RNA-seq – sorts, corrects and counts the BUS records of kallisto bus (cells × genes)","bustools sort -o sorted.bus /data/examples/singlecell/input.bus\nbustools correct -w /data/examples/singlecell/whitelist.txt -o corrected.bus sorted.bus\nbustools sort -o corrected.sorted.bus corrected.bus\nmkdir -p counts\nbustools count --genecounts -g /data/examples/singlecell/transcripts-to-genes.txt -e /data/examples/singlecell/matrix.ec \\\n    -t /data/examples/singlecell/transcripts.txt -o counts/cells_x_genes corrected.sorted.bus\nbustools inspect corrected.sorted.bus        bustools text -p corrected.sorted.bus | head\n\nA BUS file has a record for each molecule seen: the cell's barcode, the UMI, the equivalence class (the transcripts the\nread fits) and how often it was seen – kallisto bus writes it from single-cell reads. sort; correct (cell barcodes, against\nthe technology's list); count (cells × genes, in Matrix Market format, with .barcodes.txt and .genes.txt); inspect, text,\ncapture, allowlist, umicorrect, compress … – bustools COMMAND without arguments lists its options.\nOne thread here: sort -t N becomes -t 1, with a note; sort keeps 64 MB in memory by default, 1 GB at most (-m 4G becomes\n-m 64M)."],
    macs3:['macs3','3.0.5',"MACS3: finds peaks – where reads pile up more than chance and the control would put them – in ChIP-seq, ATAC-seq, CUT&RUN …","macs3 callpeak -t /data/examples/chipseq/CTCF_SE_ChIP_chr22_50k.bed.gz -c /data/examples/chipseq/CTCF_SE_CTRL_chr22_50k.bed.gz \\\n    -f BED -g 52000000 -n ctcf -B --outdir ctcf\nhead -3 ctcf/ctcf_peaks.narrowPeak     (the peaks: chromosome, start, end, name, score, strand, fold enrichment, -log10 p, -log10 q, summit)\nmacs3 bdgcmp -t ctcf/ctcf_treat_pileup.bdg -c ctcf/ctcf_control_lambda.bdg -m FE -o ctcf/ctcf_FE.bdg   (fold enrichment along the genome)\nigv --genome hg19 ctcf/ctcf_peaks.narrowPeak ctcf/ctcf_FE.bdg\nmacs3 callpeak -t chip.bam -c input.bam -f BAMPE -g hs -n sample      (paired reads: the fragments themselves, no model)\nmacs3 callpeak -t chip.bam -c input.bam -g hs --broad -n mark          (broad regions: histone marks)\nmacs3 hmmratac -i /data/examples/atacseq/yeast_SRR1822137_chrI.bedpe.gz -f BEDPE --randomSeed 12345 -n atac --outdir atac   (ATAC-seq)\n\n-t: the ChIP (treatment); -c: the control (input); -f: BED, BAM, BAMPE, BEDPE, FRAG … (AUTO, the default, does not find the\npaired formats); -g: the effective genome size – hs (human), mm (mouse), ce (worm), dm (fly) or a number; -n: the name of the\nfiles; --outdir: their folder; -B: the pile-ups as bedGraph files too; -q 0.05: the q-value of a peak (-p: a p-value instead);\n--nomodel --extsize 200: no model, every read extended to 200 bases. callpeak writes NAME_peaks.narrowPeak, NAME_peaks.xls\n(a tab-separated table), NAME_summits.bed and NAME_model.r (an R script: Rscript NAME_model.r draws NAME_model.pdf).\n\nThe commands: callpeak, hmmratac, bdgcmp, bdgpeakcall, bdgbroadcall, bdgopt, cmbreps, bdgdiff, filterdup, predictd, pileup,\nrandsample, refinepeak, callvar. macs3 COMMAND -h lists the options of a command.\nMACS3 is a Python program: each command starts the Python that comes with it, with NumPy, SciPy, scikit-learn and pandas,\nwhich takes a few seconds (the first time about 45 MB are loaded). It runs as one process (callvar -m N works through its N\nparts one after another) and keeps the reads in memory: a chromosome or a small genome, not a whole human experiment."],
    plink2:['plink2','2.0.0-b.1-dev',"PLINK 2: the genotypes of many people – quality control, allele frequencies, LD, kinship, association (GWAS) and scores","plink2 --vcf /data/examples/plink2/1kg-phase3-chr21.vcf.gz --make-pgen --out chr21   (PLINK's own files: chr21.pgen, .pvar, .psam)\nplink2 --pfile chr21 --freq --out chr21                    (allele frequencies: chr21.afreq)\nplink2 --pfile chr21 --missing --hardy --het --out qc      (missing calls, Hardy-Weinberg, heterozygosity)\nplink2 --pfile chr21 --maf 0.05 --indep-pairwise 50 5 0.2 --out ld      (LD pruning: ld.prune.in, ld.prune.out)\nplink2 --pfile chr21 --keep /data/examples/plink2/keep48.samples.txt --make-king-table --out king   (kinship)\nplink2 --vcf /data/examples/plink2/synthetic_glm.vcf --pheno /data/examples/plink2/synthetic_phenotypes.tsv \\\n    --pheno-name BINARY --covar /data/examples/plink2/synthetic_covariates.tsv --glm hide-covar --out assoc   (association)\nplink2 --help --glm                                         (what an option does)\n\nEach command writes NAME.log and the files of what it was asked for, named by --out NAME (plink2.* without --out).\n--pfile NAME reads NAME.pgen, NAME.pvar and NAME.psam; --bfile NAME the PLINK 1 files NAME.bed, NAME.bim and NAME.fam.\nPLINK 2 computes here on one thread, in 640 MiB of working memory: the terminal adds  --threads 1 --memory 640 require\nunless you give them (--threads 2 at most; --memory 640 to 1024). It needs a cross-origin isolated page, as featureCounts.\nNot in this build of PLINK 2, which has no LAPACK: --pca and --pheno-svd. Not here: --script and --rerun."],
    freebayes:['freebayes','1.3.6','FreeBayes: haplotype-based variant caller – SNPs, indels and MNPs from aligned reads (BAM)','freebayes -f /data/examples/reads/reference.fa mapped.bam > freebayes.vcf\nfreebayes -f /data/examples/reads/reference.fa -r human_CYP2C19:11000-12500 mapped.bam    (one region: needs mapped.bam.bai – samtools index mapped.bam)\nfreebayes -f /data/examples/reads/reference.fa --min-alternate-count 3 --min-mapping-quality 20 mapped.bam > strict.vcf\n\nThe reads must be sorted by position (samtools sort); the reference needs its .fai index (samtools faidx).']
  };
  for(const [name,[program,version,summary,man]] of Object.entries(definitions))T[name]={version,summary,man:`${name} ${version} · compiled program, running in your browser\n\n${man}`,run:ctx=>{
    const here=(what,err)=>{if(MG.shellUtil.notHere)MG.shellUtil.notHere(what);return err;};
    // (tview draws on a terminal; with -d T or -d H it prints text or HTML and needs none)
    if(name==='samtools'&&ctx.args[0]==='tview'&&!ctx.args.some((x,i)=>/^-d[TH]$/.test(x)||(x==='-d'&&/^[TH]$/.test(ctx.args[i+1]||''))))throw here('samtools tview without -d',MG.shellUtil.userErr('samtools tview requires a terminal device; use samtools view instead – or samtools tview -d T -p CHR:POS FILE.bam REF.fa, which prints text.'));
    // samtools reheader -c CMD hands the header to another program – which a program cannot start here
    if(name==='samtools'&&ctx.args[0]==='reheader'&&ctx.args.some(x=>x==='-c'||x==='--command'||/^--command=/.test(x)))throw here('samtools reheader -c',MG.shellUtil.userErr("samtools reheader: -c (--command) runs another program on the header, and a program cannot start a program in this terminal. Do it in two steps:  samtools view -H in.bam | sed 's/old/new/' > header.sam  and then  samtools reheader header.sam in.bam > out.bam"));
    // bcftools +NAME loads a plugin from a shared library, which a WebAssembly program in a web page cannot do
    if(name==='bcftools'&&(/^\+/.test(ctx.args[0]||'')||(ctx.args[0]==='plugin'&&ctx.args.length>1&&ctx.args[1]!=='-l'&&ctx.args[1]!=='--list-plugins')))throw here('the plugins of bcftools',MG.shellUtil.userErr(`bcftools: plugins (${ctx.args[0]==='plugin'?'bcftools plugin NAME':ctx.args[0]}) are not available in this build. The built-in commands are: view, query, filter, norm, stats, annotate, call, mpileup, index, sort, concat, merge, isec, consensus, reheader.`));
    // bowtie2 and bowtie2-build are wrapper scripts around these programs; like them, say that a wrapper made the call
    if(name==='bowtie2'){
      // these options are carried out by the wrapper script itself (it reads the aligner's output), which is not here
      const w=ctx.args.find(a=>/^--(un|al)(-conc|-mates)?(-gz|-bz2|-lz4)?(=|$)/.test(a));
      if(w)throw here('bowtie2 '+w.split('=')[0],MG.shellUtil.userErr(`bowtie2: ${w.split('=')[0]} is not available here: it is done by bowtie2's wrapper script (perl), and this terminal runs the aligner itself. To get the reads that did not align:  samtools fastq -f 4 mapped.bam > unaligned.fastq`));
    }
    if(name==='bowtie2')return bowtie2Run(ctx,program);
    if(name==='bowtie2-build')return withArgs(ctx,['--wrapper','basic-0',...ctx.args],program);
    if(name==='hisat2')return hisat2Run(ctx,here);
    if(name==='hisat2-build'||name==='hisat2-inspect')return hisat2Tool(ctx,name,here);
    if(name==='samtools')seedNote(ctx);
    // lofreq call-parallel and vcfplot are Python scripts that start other programs – which a web page cannot do
    if(name==='lofreq'&&(ctx.args[0]==='call-parallel'||ctx.args[0]==='vcfplot')){
      here('lofreq '+ctx.args[0]);
      ctx.err(ctx.args[0]==='call-parallel'?'lofreq call-parallel: not available here – it is a Python script that runs several lofreq call processes at once, and a browser page cannot start processes. Use lofreq call: one process, the same calls (but for rare differences where call-parallel splits the genome).\n':'lofreq vcfplot: not available here – it is a Python script that plots with matplotlib. For the numbers use bcftools stats; to plot, read the VCF into a notebook.\n');
      return 2;
    }
    if(MG.exec.needsIsolation(program))return notIsolated(ctx,name);
    // PLINK 2: its threads and memory (--threads 1 --memory 640 require unless given; at most 2 and 1024), not --script
    if(name==='plink2'){
      const a=plink2Args(ctx.args,ctx.io);
      if(a.refuse){here('plink2 '+(ctx.args.find(x=>/^--?(script|rerun)$/.test(x))||'--script'));ctx.err(a.refuse+'\n');return 1;}
      return withArgs(ctx,a,program);
    }
    // bustools sort -m: the memory for sorting (bustools' own default, 4 GB, is more than a browser tab has: here the
    // default is 64 MB, and 1 GB the most). A larger value becomes 64M, with a note
    if(name==='bustools'&&ctx.args[0]==='sort')return withArgs(ctx,bustoolsMemory(oneThread(name,ctx.args,ctx.io),ctx.io),program);
    // HMMER reads a file ending in .gz through gzip, a program it starts – which a web page cannot do
    if(HMMER.includes(name)){
      const gz=ctx.args.find((a,i)=>/\.gz$/.test(a)&&!(i&&HMMER_OUTS.includes(ctx.args[i-1]))&&ctx.fs.exists(ctx.fs.resolve(a))&&!ctx.fs.isDir(ctx.fs.resolve(a)));
      if(gz){here(name+' with a .gz file');ctx.err(`${name}: ${gz}: files compressed with gzip cannot be read here – HMMER starts gzip to read them, and a web page cannot start programs. Unpack it first:  gunzip -k ${gz}\n`);return 1;}
    }
    return withArgs(ctx,oneThread(name,ctx.args,ctx.io),program);
  }};
  // bustools sort -m SIZE (M or G at the end; a number below 128 without them is gigabytes, as bustools reads it)
  function bustoolsMemory(args,io){
    const bytes=v=>{const m=/^(\d+)([mMgG]?)$/.exec(v||'');if(!m)return null;const n=+m[1];return /[gG]/.test(m[2])?n*2**30:/[mM]/.test(m[2])?n*2**20:n<128?n*2**30:n;};
    const out=[];let dropped=null;
    for(let i=0;i<args.length;i++){
      const a=args[i],g=/^(-m|--memory=)(.+)$/.exec(a);
      if((a==='-m'||a==='--memory')&&i+1<args.length&&bytes(args[i+1])>2**30){dropped=`${a} ${args[i+1]}`;out.push(a,'64M');i++;continue;}
      if(g&&bytes(g[2])>2**30){dropped=a;out.push(g[1]+'64M');continue;}
      out.push(a);
    }
    if(dropped&&io&&io.note)io.note(`bustools: ${dropped} becomes ${dropped.replace(/(\s|=|^-m)\S+$/,'$164M')} here – in the browser bustools sorts in 1 GB of memory at most.`);
    return out;
  }
  /* featureCounts, Salmon and PLINK 2 outside a cross-origin isolated page: why they cannot run here, and what to do */
  let isolationNoted=false;
  function notIsolated(ctx,name){
    const why=(window.WB_ISOLATION||{}).reason||'';
    const how=why==='insecure'?'Only a page opened over https, or from localhost, can be isolated – this one was not.'
      :why==='no-service-worker'?'The workbench isolates its page with a service worker, which this browser does not allow here (a private window can be the reason).'
      :why==='off'?'Isolation is turned off: the address of the page has ?isolation=off. Open the workbench without it.'
      :'The workbench isolates its page as it starts: reload the page.';
    ctx.err(`${name}: this program counts on several threads that share their memory, and a browser allows that only in a page that is cross-origin isolated – this page is not. ${how} (See Limits in the help.)\n`);
    // (once, also as a note – which is seen where the program's messages go into a file: 2> log.txt)
    if(!isolationNoted&&ctx.io&&ctx.io.note){isolationNoted=true;ctx.io.note(`featureCounts, salmon and plink2 cannot run in this page: it is not cross-origin isolated. ${how}`);}
    return 1;
  }
  /* bowtie2 is a wrapper script (perl) around the aligner, bowtie2-align-s. This terminal runs the aligner itself –
     and does here the two things of the wrapper that a script or a person meets:
     - before anything else it looks for the index (-x NAME: any file NAME*.bt2 or NAME*.bt2l, also below
       $BOWTIE2_INDEXES): if there is none it says so in its own words and ends with status 255;
     - when the aligner fails, it adds its line "(ERR): bowtie2-align exited with value N" and ends with N. */
  async function bowtie2Run(ctx,program){
    const a=ctx.args,xi=a.indexOf('-x');
    if(xi>=0&&a[xi+1]!=null){
      const fs=ctx.fs,there=base=>{
        const abs=fs.resolve(base),dir=/\/$/.test(base)?abs:MG.path.dirname(abs),stem=/\/$/.test(base)?'':abs.slice(dir.length).replace(/^\//,'');
        return fs.isDir(dir)&&fs.list(dir).some(c=>c.entry.kind!=='dir'&&c.name.startsWith(stem)&&/\.bt2l?$/.test(c.name.slice(stem.length)));
      };
      const env=(ctx.env&&ctx.env.BOWTIE2_INDEXES)||'';
      if(!there(a[xi+1])&&!(env&&there(env.replace(/\/+$/,'')+'/'+a[xi+1]))){
        ctx.err(`(ERR): "${env?env+'/':''}${a[xi+1]}" does not exist or is not a Bowtie 2 index\nExiting now ...\n`);
        return 255;
      }
    }
    const code=await withArgs(ctx,['--wrapper','basic-0',...a],program);
    if(code)ctx.err(`(ERR): bowtie2-align exited with value ${code}\n`);
    return code;
  }
  /* HISAT2. hisat2 is a wrapper script (perl) around the aligner, hisat2-build and hisat2-inspect are wrapper scripts
     (python) around theirs. Here the three programs are one module: "hisat2 build|inspect ARGS", and the aligner when
     the first argument is an option (see its NOTICE.txt). The terminal does what the wrappers do that a person meets:
     - the programs are told --wrapper basic-0, as the wrappers tell them (their messages then name hisat2 and hisat2-build);
     - hisat2 first looks for the read files ("(ERR): Read file 'X' doesn't exist"), then for the index (-x NAME: any
       file NAME*.ht2): if it is not there it says so in its own words and ends with status 255;
     - read files packed with gzip (.gz) are unpacked first: the aligner reads only plain FASTQ/FASTA files;
     - when the aligner fails it adds "(ERR): hisat2-align exited with value N" and ends with N.
     Done by the wrapper itself, and so not here: --un, --al, --un-conc, --al-conc (it reads the aligner's output). */
  const hisat2Fail=(ctx,msg)=>{ctx.err(`(ERR): ${msg}\nExiting now ...\n`);return 255;};
  async function hisat2Run(ctx,here){
    const a=ctx.args,fs=ctx.fs,u=MG.shellUtil;
    const w=a.find(x=>/^--(un|al|un-conc|al-conc|al-conc-disc)(-gz|-bz2|-lz4)?(=|$)/.test(x));
    if(w)throw here('hisat2 '+w.split('=')[0],u.userErr(`hisat2: ${w.split('=')[0]} is not available here: it is done by hisat2's wrapper script (perl), and this terminal runs the aligner itself. To get the reads that did not align:  samtools fastq -f 4 mapped.bam > unaligned.fastq  (or leave them out of the SAM file with --no-unal)`));
    if(a.includes('--large-index'))throw here('hisat2 --large-index',u.userErr('hisat2: --large-index is not available here: indexes are the small kind (.ht2), enough for anything that fits into a browser.'));
    // the read files: -U, --unpaired, -1, -2 (also -1FILE), each a list separated by commas
    const groups={U:[],1:[],2:[]},at={U:[],1:[],2:[]};
    let inline=false;
    for(let i=0;i<a.length;i++){
      const x=a[i];
      if(x==='--')break;
      if(x==='-c')inline=true;
      let k=null,v=null;
      if(x==='-U'||x==='--unpaired'){k='U';v=a[i+1];}
      else{const m=/^--?([12])(.*)$/.exec(x);if(m&&!/^--?12/.test(x)){k=m[1];if(m[2])v=m[2];else v=a[i+1];}}
      if(k==null||v==null)continue;
      const glued=!(x==='-U'||x==='--unpaired'||/^--?[12]$/.test(x));
      at[k].push(glued?[i,x.slice(0,x.length-v.length)]:[i+1,'']);
      groups[k].push(...v.split(',').filter(Boolean));
      if(!glued)i++;
    }
    const files=[...groups.U,...groups[1],...groups[2]];
    if(!inline)for(const f of files)if(f!=='-'&&!(fs.exists(f)&&!fs.isDir(f)))return hisat2Fail(ctx,`Read file '${f}' doesn't exist`);
    const args=a.slice(),held=[];
    try{
      // packed read files: each group (-U, -1, -2) becomes one plain file, as the wrapper makes one pipe of each
      if(!inline&&files.some(f=>/\.(gz|bz2)$/.test(f))){
        const bz=files.find(f=>/\.bz2$/.test(f));
        if(bz)throw here('hisat2 with .bz2 reads',u.userErr(`hisat2: ${bz}: bzip2 files cannot be unpacked in this terminal. Unpack it elsewhere, or pack it with gzip.`));
        for(const k of ['U','1','2']){
          if(!groups[k].length)continue;
          const parts=[];
          for(const f of groups[k]){
            if(/\.gz$/.test(f)){
              const r=await MG.exec.run({...ctx,stdin:null,inherit:null,redirectTarget:null,mergeStderr:false},'bgzip',['-dc',f],{binaryOut:true});
              if(r.code){ctx.err(tidy(r.stderr,'hisat2'));return hisat2Fail(ctx,`Could not open gzipped read file: ${f} `);}
              parts.push(await MG.exec.readBytes(r.out));
            }else parts.push(await fs.readBytes(f));
          }
          let n=0;for(const b of parts)n+=b.length;
          const all=new Uint8Array(n);let o=0;for(const b of parts){all.set(b,o);o+=b.length;}
          const ref=await MG.exec.tempBytes(all,false);MG.exec.hold(ref);held.push(ref);
          // (the first place of the group gets the plain file; the others go)
          at[k].forEach(([idx,prefix],j)=>{args[idx]=j?null:prefix+MG.exec.argPath(ref);if(j&&!prefix)args[idx-1]=null;});
        }
      }
      // the index: -x NAME
      const xi=args.indexOf('-x');
      if(xi>=0&&args[xi+1]!=null){
        const base=args[xi+1],abs=fs.resolve(base),dir=/\/$/.test(base)?abs:MG.path.dirname(abs),stem=/\/$/.test(base)?'':abs.slice(dir.length).replace(/^\//,'');
        if(!(fs.isDir(dir)&&fs.list(dir).some(c=>c.entry.kind!=='dir'&&c.name.startsWith(stem)&&/\.ht2l?$/.test(c.name.slice(stem.length)))))return hisat2Fail(ctx,`"${base}" does not exist`);
      }
      const code=await withArgs(ctx,['--wrapper','basic-0',...oneThread('hisat2',args.filter(x=>x!=null),ctx.io)],'hisat2');
      if(code)ctx.err(`(ERR): hisat2-align exited with value ${code}\n`);
      return code;
    }finally{for(const p of held)MG.exec.release(p);}
  }
  /* hisat2-build and hisat2-inspect: their wrappers take away --verbose, --debug and --large-index (the last two
     choose another program) and tell the program --wrapper basic-0. */
  function hisat2Tool(ctx,name,here){
    const a=ctx.args.filter(x=>x!=='--verbose'&&x!=='--debug');
    if(a.includes('--large-index'))throw here(name+' --large-index',MG.shellUtil.userErr(`${name}: --large-index is not available here: indexes are the small kind (.ht2), enough for anything that fits into a browser.`));
    const args=name==='hisat2-build'?oneThread('hisat2-build',a,ctx.io):a;
    return withArgs(ctx,[name==='hisat2-build'?'build':'inspect','--wrapper','basic-0',...args],'hisat2');
  }
  /* samtools view -s SEED.FRACTION (and --subsample-seed): samtools turns the seed into a pseudo-random number with
     the C library's rand(), and the C library of these WebAssembly programs (musl) gives other numbers than the
     one on Linux (glibc). So with a seed other than 0 the same command keeps other reads on Linux – about as many,
     not the same. With seed 0 samtools does not call rand(): -s 0.25 gives the same reads everywhere. */
  function seedNote(ctx){
    const a=ctx.args;
    if(a[0]!=='view'||!ctx.io||!ctx.io.note)return;
    let seed=null;
    for(let i=1;i<a.length;i++){
      let m;
      if(a[i]==='-s'&&(m=/^(\d+)\.\d+$/.exec(a[i+1]||'')))seed=m[1];
      else if((m=/^-s(\d+)\.\d+$/.exec(a[i])))seed=m[1];
      else if(a[i]==='--subsample-seed'&&/^\d+$/.test(a[i+1]||''))seed=a[i+1];
      else if((m=/^--subsample-seed=(\d+)$/.exec(a[i])))seed=m[1];
    }
    if(seed!=null&&+seed!==0)ctx.io.note(`samtools view: with the seed ${seed} this program keeps other reads than samtools on Linux does (about as many, but not the same ones): samtools feeds the seed through the C library's random numbers, and the library of this terminal's programs is another one. With seed 0 (-s 0.25, or --subsample 0.25 alone) the reads are the same everywhere; so are those of seqtk sample -s.`);
  }
  /* gzip, gunzip, zcat: bgzip does the work (what it writes, BGZF, is a valid gzip file). gzip takes any number of
     files, bgzip one: each file is done by itself –  gzip a.txt b.txt  makes two .gz files,  zcat x.gz y.gz  prints
     both, one after the other. */
  const gzLong={'--recursive':'r','--stdout':'c','--to-stdout':'c','--decompress':'d','--uncompress':'d','--keep':'k','--force':'f','--best':'9','--fast':'1','--quiet':'q','--verbose':'v','--test':'t','--no-name':'n','--name':'N'};
  async function gzRun(ctx,name){
    const u=MG.shellUtil;
    let toStdout=name==='zcat'||name==='gzcat',decompress=name!=='gzip',keep=false,force=false,test=false,level=null,noMore=false,quiet=false,recursive=false;
    const files=[];
    for(const a of ctx.args){
      if(noMore||a==='-'||!a.startsWith('-')){files.push(a);continue;}
      if(a==='--'){noMore=true;continue;}
      if(a==='--help'||a==='--version'){ctx.out(`${name}: ${name==='gzip'?'compress':'decompress'} gzip files – in this terminal bgzip ${MG.exec.versions.htslib} does the work.\nUsage: ${name} [-c] [-d] [-k] [-f] [-r] [-t] [-q] [-1 … -9] [FILE …]\n`);return 0;}
      const letters=a.startsWith('--')?(gzLong[a]||''):a.slice(1);
      if(!letters)throw u.userErr(`${name}: unrecognized option '${a}'\nTry \`${name} --help' for more information.`);
      for(const c of letters){
        if(c==='c')toStdout=true;else if(c==='d')decompress=true;else if(c==='k')keep=true;else if(c==='f')force=true;else if(c==='t')test=true;
        else if(/[1-9]/.test(c))level=c;else if(c==='q')quiet=true;else if(c==='r')recursive=true;else if('vnN'.includes(c))continue;
        else if(c==='l'||c==='S')throw u.userErr(`${name}: -${c} is not available in this terminal (the work is done by bgzip). The size of what is in a .gz file:  zcat FILE.gz | wc -c`);
        else throw u.userErr(`${name}: invalid option -- '${c}'\nTry \`${name} --help' for more information.`);
      }
    }
    // (gzip -t looks at compressed files, as gzip -d does: NAME stands for NAME.gz where there is no NAME)
    if(test)decompress=true;
    // -r: a folder stands for every file in it and below it (and gzip then says nothing about the files it leaves alone)
    if(recursive){
      const all=[];
      for(const f of files){
        if(f==='-'||f===''||!ctx.fs.isDir(f)){all.push(f);continue;}
        const abs=ctx.fs.resolve(f),pre=abs==='/'?'/':abs+'/',lead=f.endsWith('/')?f:f+'/';
        all.push(...Array.from(real(ctx.fs).entries).filter(([k,e])=>k.startsWith(pre)&&e.kind!=='dir').map(([k])=>lead+k.slice(pre.length)).sort());
      }
      // (folders without a file in them: there is nothing to do – and nothing is read from the input)
      if(files.length&&!all.length)return 0;
      files.length=0;files.push(...all);
    }
    const one=f=>[...(test?['-t']:[]),...(decompress&&!test?['-d']:[]),...(toStdout&&!test?['-c']:[]),...(keep?['-k']:[]),...(force&&!toStdout?['-f']:[]),...(level&&!decompress?['-l',level]:[]),...(f==null||f==='-'?[]:[f])];
    // zcat -f, gunzip -cf: a file that is not compressed is given as it is
    const plain=async f=>{
      if(!(force&&decompress&&toStdout)||f==null||f==='-'||!ctx.fs.exists(f)||ctx.fs.isDir(f))return null;
      const bytes=await ctx.fs.readBytes(f);
      return bytes.length>=2&&bytes[0]===0x1f&&bytes[1]===0x8b?null:bytes;
    };
    // The suffixes that gzip knows (in any case of the letters): a file that has one is compressed already – gzip leaves
    // it alone –, and only a file that has one is decompressed (.tgz and .taz give .tar, the others are cut off).
    const sfx=f=>{const b=String(f).split('/').pop(),m=/(\.gz|\.tgz|\.taz|\.z|-gz|-z|_z)$/i.exec(b);return m&&m[1].length<b.length?m[1]:null;};
    const result=f=>{const s=sfx(f);return f.slice(0,f.length-s.length)+(/^\.t[ag]z$/i.test(s)?'.tar':'');};
    // What gzip refuses before it reads anything, in gzip's words and with its statuses (1: an error, 2: a warning;
    // an error counts more): a folder ("-- ignored" – bgzip would make DIR.gz), a file that is not there, a file that
    // has the suffix already (gzip *  in a folder where some files are compressed: bgzip would compress them again), a
    // file without the suffix that is to be decompressed, and a result that is there already.
    const refused=f=>{
      if(f==null||f==='-')return null;
      const e=f===''?null:ctx.fs.get(f),s=sfx(f);
      if(!e&&!(decompress&&!s&&f!==''&&ctx.fs.exists(f+'.gz')))return [`gzip: ${decompress&&!s?f+'.gz':f}: ${(ctx.fs.pathError&&ctx.fs.pathError(f))||'No such file or directory'}\n`,1];
      if(e&&e.kind==='dir')return [quiet?'':`gzip: ${f} is a directory -- ignored\n`,2];
      // (gzip -rt: of what is in a folder only the files with the suffix are looked at)
      if(e&&recursive&&test&&!s)return ['',0];
      if(!e||toStdout||test)return null;
      if(!decompress){
        if(s&&!force)return [quiet||recursive?'':`gzip: ${f} already has ${s} suffix -- unchanged\n`,0];
        if(!force&&ctx.fs.exists(f+'.gz'))return [`gzip: ${f}.gz already exists;\tnot overwritten\n`,2];
        return null;
      }
      if(!s)return [quiet||recursive?'':`gzip: ${f}: unknown suffix -- ignored\n`,quiet||recursive?0:2];
      if(!force&&ctx.fs.exists(result(f)))return [`gzip: ${result(f)} already exists;\tnot overwritten\n`,2,'result'];
      return null;
    };
    // How a file that is to be unpacked begins: 'short' – it ends before its second byte –, 'other' – not as a
    // compressed file does (gzip, and the older formats that gzip reads) –, or null.
    const begins=async f=>{
      if(f==null||f==='-'||f==='')return null;
      const n=ctx.fs.exists(f)?f:f+'.gz';
      if(!ctx.fs.exists(n)||ctx.fs.isDir(n))return null;
      const b=await ctx.fs.readBytes(n);
      if(b.length<2)return ['short',n];
      const two=(b[0]<<8)|b[1];
      return two===0x1f8b||two===0x1f9e||two===0x1f1e||two===0x1f9d||two===0x1fa0||two===0x504b?null:['other',n];
    };
    let said=0;
    const count=c=>{if(c===1||said===1)said=1;else if(c)said=Math.max(said,c);};
    // gzip gives the file it makes the permissions and the time of the file it was made from: a script is still
    // executable after gzip and gunzip, and "is the .gz older than the file?" (make-like checks) is answered as on Linux
    const carry=(src,name)=>{
      const fs=real(ctx.fs),abs=ctx.fs.resolve(name),out=fs.entries.get(abs);
      if(!src||!out||out.kind==='dir'||out===src)return;
      const n=Object.assign({},out);
      if(src.mode)n.mode=src.mode;else delete n.mode;
      if(src.perm!=null)n.perm=src.perm;else delete n.perm;
      // (a read-only file of one's own gives a read-only .gz, and the other way round; the course data's protection is not handed on)
      if(src.readonly&&!src.protected)n.readonly=true;else delete n.readonly;
      if(src.mtime)n.mtime=src.mtime;
      fs.entries.set(abs,n);
    };
    if(files.length&&(!toStdout||test)){
      // each file is replaced by its .gz (or the .gz by the file) – one after the other, each looked at when its turn comes
      for(let f of files){
        const r=refused(f);
        // gzip looks into a file before it looks at the name of the result. A file that ends before its second byte
        // ends gzip itself ("unexpected end of file", status 1: the files after it are not looked at); one that does
        // not begin as a compressed file is an error (status 1) – whether or not the result is there already.
        if(decompress&&!test&&(!r||r[2]==='result')){
          const g=await begins(f);
          if(g&&g[0]==='short'){ctx.err(`\ngzip: ${g[1]}: unexpected end of file\n`);return 1;}
          if(g){ctx.err(`\ngzip: ${g[1]}: not in gzip format\n`);count(1);continue;}
        }
        if(r){if(r[0])ctx.err(r[0]);count(r[1]);continue;}
        // (gunzip NAME: NAME.gz is meant where there is no NAME)
        if(f!=='-'&&decompress&&!ctx.fs.exists(f))f+='.gz';
        if(f!=='-'&&decompress&&!test&&!/\.gz$/.test(f)){
          // a suffix that bgzip does not know (.tgz, .GZ, .z, -gz …): its output is written under the name gzip gives the result
          const run=await MG.exec.run({...ctx,redirectTarget:null,mergeStderr:false},'bgzip',['-dc',f],{binaryOut:true});
          if(run.stderr)ctx.err(tidy(run.stderr,name));
          if(run.code){count(1);continue;}
          const from=ctx.fs.get(f);
          await MG.exec.writeBytes(ctx.fs,ctx.fs.resolve(result(f)),await MG.exec.readBytes(run.out));
          carry(from,result(f));
          if(!keep)ctx.fs.remove(f);
          continue;
        }
        const from=f==='-'?null:ctx.fs.get(f);
        // (-f: a result that is there already is removed first, as gzip does – so a read-only one is no obstacle)
        if(force&&from&&!test){const old=ctx.fs.get(decompress?result(f):f+'.gz');if(old&&old.kind!=='dir'&&old.readonly&&!old.protected)ctx.fs.remove(decompress?result(f):f+'.gz');}
        if(await withArgs(ctx,one(f),'bgzip'))count(1);
        else if(from&&!test)carry(from,decompress?result(f):f+'.gz');
      }
      return said;
    }
    const todo=[];
    for(const f of files){const r=refused(f);if(r){if(r[0])ctx.err(r[0]);count(r[1]);}else todo.push(f!=='-'&&decompress&&!ctx.fs.exists(f)?f+'.gz':f);}
    if(files.length&&!todo.length)return said;
    if(todo.length<=1&&!(await plain(todo[0]))){const c=await withArgs(ctx,one(todo[0]),'bgzip');return c?(said===1?1:c):said;}
    // to the output: what each file gives, one after the other
    const sink=new u.Sink();let code=said;
    for(const f of todo){
      const raw=await plain(f);
      if(raw){sink.add(raw);continue;}
      const r=await MG.exec.run({...ctx,redirectTarget:null,mergeStderr:false},'bgzip',one(f),{binaryOut:true});
      if(r.stderr)ctx.err(tidy(r.stderr,name));
      if(r.code)code=r.code;
      sink.add(await MG.exec.readBytes(r.out));
      MG.bus.emit('tool:run',{program:'bgzip',sub:'',args:one(f),code:r.code,secs:r.secs,created:r.created,real:true,line:ctx.rawLine,statusKnown:r.statusKnown});
    }
    if(ctx.takesBytes)ctx.out(sink.bytes());
    else if(!decompress){if(!sink.empty)ctx.io.note(`Binary output: ${MG.humanSize(sink.bytes().length)} bytes. Save with > FILE, or inspect using samtools/bcftools view.`);}
    else ctx.out(sink.text());
    return code;
  }
  for(const name of ['gzip','gunzip','zcat','gzcat'])T[name]={hidden:true,summary:'gzip files (done by bgzip)',man:`${name}: ${name==='gzip'?'compress':'decompress'} gzip files. In this terminal bgzip ${MG.exec.versions.htslib} does the work.`,run:ctx=>gzRun(ctx,name)};
  /* zgrep PATTERN FILE… = for each file: zcat -f FILE | grep --label=FILE PATTERN. A file that is not compressed is
     searched as it is; with several files each line is given with the name of its file (not with -h), as grep
     does; the status is 0 if something was found in any file, 2 after an error, else 1. */
  T.zgrep={hidden:true,summary:'grep in gzip files',man:'zgrep [OPTIONS] PATTERN FILE…: search gzip files (for each: zcat -f FILE | grep PATTERN).',run:async ctx=>{
    const opts=[],rest=[];
    for(let i=0;i<ctx.args.length;i++){const a=ctx.args[i];if(a==='-e'||a==='-m'||a==='-A'||a==='-B'||a==='-C')opts.push(a,ctx.args[++i]);else if(a.startsWith('-')&&a.length>1)opts.push(a);else rest.push(a);}
    if(!rest.length&&!opts.includes('-e'))throw MG.shellUtil.userErr('usage: zgrep [OPTIONS] PATTERN FILE.gz',2);
    const pattern=opts.includes('-e')?[]:[rest.shift()];
    const io=MG.shellUtil.innerIO(ctx);
    if(!rest.length){
      // (what comes in is searched as it is when it is not compressed: zgrep PATTERN < plain.txt)
      let packed=true;
      try{const s=ctx.stdin;if(typeof s==='string')packed=s.charCodeAt(0)===0x1f&&s.charCodeAt(1)===0x8b;else if(s instanceof FileRef){const b=await MG.exec.readBytes(s);packed=b.length>=2&&b[0]===0x1f&&b[1]===0x8b;}}catch(e){}
      const parts=packed?[{argv:['gzip','-dcfq'],redirs:[]},{argv:['grep',...opts,...pattern],redirs:[]}]:[{argv:['grep',...opts,...pattern],redirs:[]}];
      return ctx.shell.runPipeline(parts,io,ctx.rawLine,Object.assign({},ctx.opts,{stdin:ctx.stdin}));
    }
    const named=rest.length>1&&!opts.some(a=>a==='--no-filename'||(/^-[A-Za-z]+$/.test(a)&&a.includes('h')));
    let found=false,failed=false;
    for(const f of rest){
      const o=Object.assign({},ctx.opts,{stdin:undefined});
      const c=await ctx.shell.runPipeline([{argv:['gzip','-dcfq',f],redirs:[]},{argv:['grep',...opts,...(named?['-H']:[]),'--label='+f,...pattern],redirs:[]}],io,ctx.rawLine,o);
      if((o.codes&&o.codes[0])||c>1)failed=true;else if(c===0)found=true;
    }
    return failed?2:found?0:1;
  }};
  /* grep -P. The Biowasm build of grep 3.7 has no PCRE ("Perl matching not supported in a --disable-perl-regexp
     build"), so a command line that asks for Perl patterns is carried out by a second program: GNU grep 3.11 with
     PCRE2 10.42, built for this practical (grep-perl; see its NOTICE.txt). Whether a command line asks for them is
     decided as grep's getopt decides it: -P alone or in a group of letters (-oP, -oPm1 – but not behind a letter that
     takes a value: -eP is the pattern "P"), --perl-regexp or a beginning of that word, anywhere before "--". */
  const GREP_VALUE='ABCDXdefm',GREP_LONG={'after-context':1,'before-context':1,'binary-files':1,'context':1,'devices':1,'directories':1,'exclude':1,'exclude-from':1,'exclude-dir':1,'file':1,'group-separator':1,'include':1,'label':1,'max-count':1,'regexp':1,
    'basic-regexp':0,'extended-regexp':0,'fixed-regexp':0,'fixed-strings':0,'perl-regexp':0,'byte-offset':0,'color':0,'colour':0,'count':0,'files-with-matches':0,'files-without-match':0,'help':0,'ignore-case':0,'no-ignore-case':0,'initial-tab':0,'line-buffered':0,'line-number':0,'line-regexp':0,'no-filename':0,'no-group-separator':0,'no-messages':0,'null':0,'null-data':0,'only-matching':0,'quiet':0,'recursive':0,'dereference-recursive':0,'invert-match':0,'silent':0,'text':0,'binary':0,'unix-byte-offsets':0,'version':0,'with-filename':0,'word-regexp':0};
  function wantsPerl(args){
    let perl=false;
    for(let i=0;i<args.length;i++){
      const a=String(args[i]);
      if(a==='--')break;
      if(a.startsWith('--')){
        const word=a.slice(2).split('=')[0];
        // (the whole word, or a beginning that only one word has)
        const hits=word in GREP_LONG?[word]:Object.keys(GREP_LONG).filter(k=>k.startsWith(word));
        if(hits.length!==1)continue;
        if(hits[0]==='perl-regexp')perl=true;
        else if(GREP_LONG[hits[0]]&&!a.includes('='))i++;
      }else if(a.length>1&&a[0]==='-'){
        for(let k=1;k<a.length;k++){
          if(a[k]==='P')perl=true;
          else if(GREP_VALUE.includes(a[k])){if(k===a.length-1)i++;break;}
        }
      }
    }
    return perl;
  }
  MG.wantsPerl=wantsPerl;
  const grepRun=(ctx,name)=>{
    const first=name==='egrep'?['-E']:name==='fgrep'?['-F']:[],program=wantsPerl(ctx.args)?'grep-perl':'grep';
    return first.length?withArgs(ctx,[...first,...ctx.args],program):runReal(ctx,program);
  };
  for(const name of ['awk','gawk','grep','egrep','fgrep','sed','diff','cmp',...CORE]){
    const program=name==='awk'?'gawk':name==='egrep'||name==='fgrep'?'grep':name;
    T[name]={summary:'GNU '+name+' (real WebAssembly executable)',man:`GNU ${name}: use ${name} --help for its supported options. Shell constructs are documented in help.`,run:ctx=>program==='grep'?grepRun(ctx,name):name==='date'?withArgs(ctx,dateArgs(ctx),program):name==='cat'?catRun(ctx):name==='tee'?teeRun(ctx):runReal(ctx,program)};
    delete MG.shellBuiltins[name];
  }
})();
