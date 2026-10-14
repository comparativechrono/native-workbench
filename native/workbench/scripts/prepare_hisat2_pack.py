#!/usr/bin/env python3
"""Prepare the local HISAT2 2.2.3-workbench1 pack (Workbench >=0.5.3)."""
import argparse, hashlib, json, random, shutil, subprocess, sys, urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'vendor-expanded/hisat2'
PACK=ROOT/'packs/hisat2-0.5.3'
TC=ROOT.parents[1]/'toolchains/llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64'
SOURCE_URL='https://codeload.github.com/DaehwanKimLab/hisat2/tar.gz/refs/tags/v2.2.3'
SOURCE_SHA='b53107422e5b44ebea4b20b1a77bb9e240d6b92d654fcd7e6a6ab5d1aae86c45'
SOURCE_COMMIT='0d244324f98de541bce04d45c75e83bc3522f7f4'
PINNED={'samtools':('samtools-cosmo.exe','1.24','49c2f16425d464e4ad1c1439d7a9e32a3b1c1bf8e5d54403778de610d2f440b3'),'paircheck':('paircheck-cosmo.exe','1.0.1','4f2dda7e26b5c115a7edee936a8a059eb55ece244931b2799a62cebfcd44ecd4')}
CITATION={'text':'Kim D, Paggi JM, Park C, Bennett C and Salzberg SL (2019). Graph-based genome alignment and genotyping with HISAT2 and HISAT-genotype. Nature Biotechnology 37:907-915.','url':'https://doi.org/10.1038/s41587-019-0201-4'}

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def dump(path,value):path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
def fixtures(path):
    path.mkdir(parents=True,exist_ok=True);rng=random.Random(20261003)
    sequence=''.join(rng.choice('ACGT') for _ in range(1100));sequence=sequence[:500]+'GT'+sequence[502:598]+'AG'+sequence[600:]
    (path/'reference.fa').write_text('>chrSynthetic\n'+sequence+'\n')
    def rc(s):return s.translate(str.maketrans('ACGT','TGCA'))[::-1]
    def fastq(name,rows):(path/name).write_text(''.join('@'+label+'\n'+s+'\n+\n'+'I'*len(s)+'\n' for label,s in rows))
    junction=sequence[470:500]+sequence[600:630]
    fastq('rna-single.fastq',[('rna_junction',junction),('rna_exon',sequence[650:710])])
    fastq('rna-r1.fastq',[('rna_pair/1',junction)]);fastq('rna-r2.fastq',[('rna_pair/2',rc(sequence[690:750]))])
    fastq('dna-single.fastq',[('dna_exon_a',sequence[210:270]),('dna_exon_b',sequence[350:410])])
    fastq('dna-r1.fastq',[('dna_pair/1',sequence[210:270])]);fastq('dna-r2.fastq',[('dna_pair/2',rc(sequence[350:410]))])


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--fetch',action='store_true');parser.add_argument('--build',action='store_true');args=parser.parse_args()
    CACHE.mkdir(parents=True,exist_ok=True);archive=CACHE/'hisat2-v2.2.3.tar.gz'
    if not archive.exists() and (PACK/'licenses'/archive.name).is_file():shutil.copy2(PACK/'licenses'/archive.name,archive)
    if not archive.exists() and args.fetch:archive.write_bytes(urllib.request.urlopen(SOURCE_URL,timeout=120).read())
    if not archive.exists() or sha(archive)!=SOURCE_SHA:raise ValueError('Missing/changed HISAT2 source; use --fetch')
    if args.build:subprocess.run([sys.executable,str(ROOT/'scripts/build_hisat2_native.py')],check=True)
    for d in ('bin','licenses','fixtures'):(PACK/d).mkdir(parents=True,exist_ok=True)
    sections=[('pack',{'format':'2','id':'hisat2','version':'0.5.3','name':'HISAT2 DNA and RNA alignment','platform':'windows-x86_64','description':'Index a reference and align single or paired DNA/RNA reads locally. RNA includes coordinate-sorted BAM and CSI. Workbench 0.5.3 or newer.','color':'#507FA5'})]
    for name in ('hisat2-align-l','hisat2-build-l'):
        shutil.copy2(CACHE/'build-windows'/(name+'.exe'),PACK/'bin'/(name+'.exe'))
        sections.append(('tool:'+name,{'path':'bin/'+name+'.exe','version':'2.2.3-workbench1','sha256':sha(PACK/'bin'/(name+'.exe'))}))
    for name,(filename,version,digest) in PINNED.items():
        source=ROOT/'baselines/bin'/filename
        if not source.exists():source=PACK/'bin'/(name+'.exe')
        if sha(source)!=digest:raise ValueError('Portable helper hash differs: '+name)
        if source!=(PACK/'bin'/(name+'.exe')):shutil.copy2(source,PACK/'bin'/(name+'.exe'))
        sections.append(('tool:'+name,{'path':'bin/'+name+'.exe','version':version,'sha256':digest}))
    fixtures(PACK/'fixtures')
    schema={'schema':1,'category':'Read alignment','citations':[CITATION],'workflows':{}}
    checks={'schema':1,'checks':[]}
    for family in ('rna','dna'):
      for paired in (False,True):
        identity=family+('-paired' if paired else '-single');rna=family=='rna';prefix='HISAT2 '+family.upper()+' '+('paired reads' if paired else 'single reads')
        inputs=['reads1','reads2'] if paired else ['reads']
        inputs+=['reference','sample','read-group','library','platform-unit','platform','threads','seed']
        if rna:inputs+=['strandness','min-intron','max-intron','sort-memory-mb']
        elif paired:inputs+=['min-insert','max-insert']
        outputs=(['pair-check'] if paired else [])+['reference']+['index-'+str(n) for n in range(1,9)]+(['aligned-sam','aligned','bam-index'] if rna else ['aligned'])+['summary']
        steps=(['check-pairs'] if paired else [])+['copy-reference','index','align']+(['sort','bam-index'] if rna else [])
        desc=('Discover spliced RNA alignments and produce coordinate-sorted BAM/CSI, with an auxiliary SAM.' if rna else 'Align DNA reads with splicing explicitly disabled; produce unsorted SAM for downstream DNA tools.')+' Builds a private 64-bit HISAT2 reference index. Uncompressed Phred+33 FASTQ required.'
        sections.append(('workflow:'+identity,{'name':prefix,'description':desc,'inputs':','.join(inputs),'outputs':','.join(outputs),'steps':','.join(steps)}))
        def inp(key,fields):sections.append(('input:'+identity+':'+key,fields))
        for key in (['reads1','reads2'] if paired else ['reads']):
            fields={'label':{'reads1':'Read 1 FASTQ','reads2':'Read 2 FASTQ','reads':'Reads FASTQ'}[key],'type':'file','required':'true','filter':'Uncompressed FASTQ|*.fastq;*.fq|All files|*.*','help':'Uncompressed Phred+33 FASTQ. '+('Both files must have matching mate names and record order. ' if paired else '')+'ASCII paths only; spaces are supported, commas are not.'}
            if key=='reads2':fields['different-from']='reads1'
            inp(key,fields)
        inp('reference',{'label':'Reference genome FASTA','type':'file','required':'true','filter':'Uncompressed FASTA|*.fa;*.fasta;*.fna|All files|*.*','help':'Genomic DNA reference, not a transcriptome. A private copy and large-format index are created in the results. Index building for large genomes needs substantial RAM, disk space and time.'})
        for key,label,default in [('sample','Sample ID','sample1'),('read-group','Read-group ID','rg1'),('library','Library ID','lib1'),('platform-unit','Platform unit / lane','unit1')]:
            inp(key,{'label':label,'type':'text','required':'true','default':default,'constraint':'identifier','help':'Recorded in the SAM/BAM read group. Use the correct sample/library and a unique read-group ID for each lane.'})
        inp('platform',{'label':'Sequencing platform','type':'choice','required':'true','default':'ILLUMINA','choices':'ILLUMINA:Illumina|DNBSEQ:DNBSEQ (MGI/BGI)','help':'Recorded as the read-group PL value.'})
        def integer(key,label,default,minimum,maximum,helptext):inp(key,{'label':label,'type':'integer','required':'true','default':str(default),'min':str(minimum),'max':str(maximum),'help':helptext})
        integer('threads','HISAT2 CPU threads',2,1,64,'Workers for HISAT2 indexing and alignment. More workers may use more RAM. SAMtools remains single-threaded in this portable build.')
        integer('seed','Alignment seed',0,0,2147483647,'Seed for HISAT2 deterministic tie breaking. Input names/sequences/qualities also affect tie breaking; all settings are recorded.')
        if rna:
            choices='unstranded:Unstranded|FR:Read 1 follows transcript (FR)|RF:Read 1 opposes transcript (RF)' if paired else 'unstranded:Unstranded|F:Read follows transcript (F)|R:Read opposes transcript (R)'
            inp('strandness',{'label':'RNA library strandedness','type':'choice','required':'true','default':'unstranded','choices':choices,'help':'Select the actual library preparation. FR/RF are transcript-strand conventions and are separate from the paired reads physical orientation. The workbench build makes the ordinary unstranded default explicit.'})
            integer('min-intron','Minimum intron length',20,20,500000,'Shortest splice gap, in bases. Must not exceed maximum intron length.')
            integer('max-intron','Maximum intron length',500000,20,10000000,'Longest splice gap, in bases. Must be at least the minimum intron length. Choose a range appropriate to the organism.')
            integer('sort-memory-mb','BAM sorting memory (MiB)',256,64,8192,'SAMtools sorting memory for its one worker; this does not cap HISAT2 indexing/alignment memory.')
        elif paired:
            integer('min-insert','Minimum DNA fragment length',0,0,1000000,'Concordant paired DNA fragment bounds, only used because splicing is disabled. Must not exceed the maximum.')
            integer('max-insert','Maximum DNA fragment length',500,1,1000000,'Maximum DNA fragment length for the ordinary inward-facing FR read-pair geometry.')
        def output(key,label,path,final=True,nonempty=True):sections.append(('output:'+identity+':'+key,{'label':label,'path':path,'final':str(final).lower(),'nonempty':str(nonempty).lower()}))
        if paired:output('pair-check','Read-pair validation','read-pairs.json')
        output('reference','Private indexed reference','reference.fa',False)
        for n in range(1,9):output('index-'+str(n),'HISAT2 large index '+str(n),'reference.'+str(n)+'.ht2l',False)
        output('aligned-sam' if rna else 'aligned','Unsorted '+family.upper()+' alignment SAM','alignment.unsorted.sam',not rna)
        if rna:
            output('aligned','Coordinate-sorted RNA BAM','alignment.sorted.bam')
            output('bam-index','RNA BAM CSI index','alignment.sorted.bam.csi')
        output('summary','HISAT2 alignment summary','alignment-summary.txt')
        def step(key,label,tool,args,produces=None,stdout=None):
            fields={'label':label,'kind':'exec','tool':tool}
            if produces:fields['produces']=','.join(produces)
            if stdout:fields['stdout']=stdout
            fields.update({'arg.'+str(n):arg for n,arg in enumerate(args)})
            sections.append(('step:'+identity+':'+key,fields))
        if paired:step('check-pairs','Validate paired FASTQ names, count and order','paircheck',['--reads1','{input:reads1}','--reads2','{input:reads2}'],stdout='pair-check')
        sections.append(('step:'+identity+':copy-reference',{'label':'Stage a private reference copy','kind':'copy','source':'{input:reference}','destination':'reference'}))
        step('index','Build the 64-bit HISAT2 reference index','hisat2-build-l',['-p','{input:threads}','{output:reference}','{run}/reference'],['index-'+str(n) for n in range(1,9)])
        args=['--wrapper','basic-0','-x','{run}/reference','-S','{output:aligned-sam}' if rna else '{output:aligned}','-p','{input:threads}','--seed','{input:seed}','--reorder','--phred33','--rg-id','{input:read-group}','--rg','SM:{input:sample}','--rg','LB:{input:library}','--rg','PL:{input:platform}','--rg','PU:{input:platform-unit}','--summary-file','{output:summary}','--new-summary']
        if rna:args+=['--dta','--rna-strandness','{input:strandness}','--min-intronlen','{input:min-intron}','--max-intronlen','{input:max-intron}']
        else:
            args+=['--no-spliced-alignment']
            if paired:args+=['-I','{input:min-insert}','-X','{input:max-insert}']
        args+=['--fr','-1','{input:reads1}','-2','{input:reads2}'] if paired else ['-U','{input:reads}']
        step('align',prefix,'hisat2-align-l',args,['aligned-sam' if rna else 'aligned','summary'])
        if rna:
            step('sort','Sort RNA alignments by coordinate','samtools',['sort','-m','{input:sort-memory-mb}M','-o','{output:aligned}','{output:aligned-sam}'],['aligned'])
            step('bam-index','Index the coordinate-sorted RNA BAM','samtools',['index','-c','{output:aligned}','{output:bam-index}'],['bam-index'])
        ports=[{'id':'reads','label':'Paired FASTQ reads' if paired else 'FASTQ reads','type':'pair' if paired else 'reads','accepts':['pair' if paired else 'reads'],'manifestInputs':['reads1','reads2'] if paired else ['reads'],'min':1,'max':1,'requiredState':{'compression':'none'}},{'id':'reference','label':'Reference genome','type':'reference','accepts':['reference'],'manifestInputs':['reference'],'min':1,'max':1,'requiredState':{'compression':'none'}}]
        products=[]
        def product(key,label,kind,members,state=None):
            value={'id':key,'label':label,'type':kind,'manifestOutputs':members}
            if state:value['state']=state
            products.append(value)
        if paired:product('pair-check','Read-pair validation','metrics',['pair-check'])
        product('reference','Private indexed reference','reference',['reference'],{'compression':'none'})
        product('hisat-index','HISAT2 64-bit reference index','index',['index-'+str(n) for n in range(1,9)])
        state={'sort':'unsorted','pairing':'paired' if paired else 'single','duplicates':'retained'}
        product('aligned-sam' if rna else 'aligned','Unsorted '+family.upper()+' alignments','sam-rna' if rna else 'sam',['aligned-sam' if rna else 'aligned'],state)
        if rna:
            product('aligned','Coordinate-sorted RNA alignments','bam-rna',['aligned'],dict(state,sort='coordinate'))
            product('bam-index','RNA BAM CSI index','index',['bam-index'])
        product('summary','HISAT2 alignment summary','metrics',['summary'])
        products.sort(key=lambda value: {'aligned':0,'summary':1,'bam-index':2,'pair-check':3,'aligned-sam':4,'reference':5,'hisat-index':6}[value['id']])
        methods='Reads were aligned to a privately indexed genomic reference using HISAT2 2.2.3-workbench1 and its 64-bit linear index. '+('Spliced alignment and transcript-assembly-oriented reporting (--dta) were enabled with the recorded library strandedness and intron limits. SAMtools 1.24 coordinate-sorted the RNA alignments and generated a CSI index. No annotation-derived splice sites were supplied.' if rna else 'Spliced alignment was disabled (--no-spliced-alignment), producing unsorted DNA SAM.')+' Phred+33 input, read-group metadata, CPU count and alignment seed were explicit; duplicates were retained.'
        schema['workflows'][identity]={'ports':ports,'outputs':products,'methods':methods,'pathPolicy':{'asciiOnly':True,'forbiddenCharacters':[',']}}
        if rna:
            schema['workflows'][identity]['citations']=[{'text':'Danecek P et al. (2021). Twelve years of SAMtools and BCFtools. GigaScience 10(2):giab008.','url':'https://doi.org/10.1093/gigascience/giab008'}]
        if rna or paired:
            schema['workflows'][identity]['parameterConstraints']=[{'left':'min-intron' if rna else 'min-insert','operator':'<=','right':'max-intron' if rna else 'max-insert'}]
        params={'sample':'validation','read-group':'validation','library':'lib1','platform-unit':'unit1','threads':'1','seed':'0'}
        bindings={'reference':[{'reference':'fixture-reference'}],'reads':[{'reads1':'fixture-'+family+'-r1','reads2':'fixture-'+family+'-r2'} if paired else {'reads':'fixture-'+family+'-single'}]}
        expected={'output':'aligned-sam' if rna else 'aligned','kind':'sam','records':2,'mapped':2,'paired':2 if paired else 0,'properPairs':2 if paired else 0,'spliced':1 if rna else 0,'references':{'chrSynthetic':1100},'samples':['validation'],'allReadGroups':True,'alignments':[]}
        if rna:expected['alignments']=[{'name':'rna_pair' if paired else 'rna_junction','reference':'chrSynthetic','position':471,'cigar':'30M100N30M','flag':99 if paired else 0,'tags':{'RG':'validation','XS':'+'}},{'name':'rna_pair' if paired else 'rna_exon','reference':'chrSynthetic','position':691 if paired else 651,'cigar':'60M','flag':147 if paired else 0,'tags':{'RG':'validation'}}]
        else:expected['alignments']=[{'name':'dna_pair' if paired else 'dna_exon_'+('a' if at==0 else 'b'),'reference':'chrSynthetic','position':position,'cigar':'60M','flag':(99 if at==0 else 147) if paired else 0,'tags':{'RG':'validation'}} for at,position in enumerate((211,351))]
        checks['checks'].append({'id':identity,'workflow':identity,'params':params,'inputs':bindings,'expect':[expected,{'output':'summary','kind':'text','contains':['Overall alignment rate: 100.00%']}]})
    dump(PACK/'workbench-schema.json',schema);dump(PACK/'workbench-checks.json',checks)
    for identity,relative in [('workbench-schema','workbench-schema.json'),('workbench-checks','workbench-checks.json')]+[('fixture-'+path.stem,'fixtures/'+path.name) for path in sorted((PACK/'fixtures').iterdir())]:sections.insert(5,('asset:'+identity,{'path':relative,'sha256':sha(PACK/relative)}))
    (PACK/'pack.ini').write_text('\n\n'.join('['+section+']\n'+'\n'.join(k+'='+v for k,v in values.items()) for section,values in sections)+'\n')
    licenses=PACK/'licenses'
    for source,name in [(archive,archive.name),(CACHE/'source/hisat2-2.2.3/LICENSE','HISAT2-GPL-3.0.txt'),(CACHE/'workbench1.patch','workbench1.patch'),(ROOT/'scripts/build_hisat2_native.py','build_hisat2_native.py'),(CACHE/'build-windows/build.json','windows-build.json'),(TC/'LICENSE.TXT','LLVM-LICENSE.txt'),(ROOT/'tools/paircheck.c','paircheck.c')]:shutil.copy2(source,licenses/name)
    extra=CACHE/'GCC-RUNTIME-EXCEPTION-3.1.txt'
    retained=licenses/extra.name
    if not extra.exists() and retained.exists():shutil.copy2(retained,extra)
    if not extra.exists() and args.fetch:extra.write_bytes(urllib.request.urlopen('https://raw.githubusercontent.com/gcc-mirror/gcc/releases/gcc-14.2.0/COPYING.RUNTIME',timeout=60).read())
    if not extra.exists() or sha(extra)!='9d6b43ce4d8de0c878bf16b54d8e7a10d9bd42b75178153e3af6a815bdc90f74':raise ValueError('Missing/changed GCC runtime exception notice; use --fetch')
    shutil.copy2(extra,retained)
    shutil.copy2(CACHE/'source/hisat2-2.2.3/third_party/cpuid.h',licenses/'cpuid-GPL-runtime-exception.h')
    for source in (TC/'x86_64-w64-mingw32/share/mingw32').glob('COPYING*'):shutil.copy2(source,licenses/source.name)
    for source,name in [(ROOT/'baselines/licenses','portable-runtime'),(ROOT/'vendor-variant/licenses','samtools-runtime')]:
        if source.is_dir():shutil.copytree(source,licenses/name,dirs_exist_ok=True)
    (licenses/'MODIFICATIONS.txt').write_text('HISAT2 2.2.3-workbench1, modified 2026-10-03 for Native Workbench. GNU GPL version 3 or later applies as in upstream source. The sole CLI change accepts --rna-strandness unstranded, explicitly selecting the existing upstream RNA_STRANDNESS_UNKNOWN default. Alignment/scoring algorithms are unchanged. Native static Windows and matching Linux source builds use deterministic build/version metadata. Source archive and exact patch are retained.\n')
    provenance={'schema':1,'tool':'HISAT2','version':'2.2.3-workbench1','upstreamTag':'v2.2.3','sourceCommit':SOURCE_COMMIT,'sourceUrl':SOURCE_URL,'sourceSha256':SOURCE_SHA,'patchSha256':sha(CACHE/'workbench1.patch'),'windowsExecuted':False,'windowsBuild':json.loads((CACHE/'build-windows/build.json').read_text()),'portableHelpers':{name:{'version':record[1],'sha256':record[2]} for name,record in PINNED.items()},'manual':'https://daehwankimlab.github.io/hisat2/manual/','citation':CITATION,'limitations':['Only uncompressed Phred+33 FASTQ inputs are exposed; no wrapper decompression or SRA network access.','ASCII installation/input/results paths; commas rejected because HISAT2 uses comma-separated file arguments.','Indexes are rebuilt privately for each operation; no annotation-derived splice sites or population-variant graph inputs in this pack.','RNA BAMs are specifically typed and cannot enter DNA-only calling workflows.','Indexing large genomes needs substantial memory and disk space; the sorting memory setting does not cap HISAT2 memory.']}
    dump(licenses/'provenance.json',provenance)
    (PACK/'PACK-README.md').write_text('''# HISAT2 2.2.3-workbench1\n\nRequires Native Workbench 0.5.3 or newer. Four operations accept uncompressed Phred+33 FASTQ: single/paired RNA alignment and single/paired DNA alignment. Each builds a private 64-bit HISAT2 index from a genomic reference. Paired modes validate mate names, counts and order before indexing.\n\nRNA alignment enables splicing and --dta, exposes real library strandedness and intron bounds, and returns coordinate-sorted BAM with CSI plus an auxiliary unsorted SAM and alignment summary. It discovers splice sites without a supplied gene annotation. RNA alignments have their own data type and cannot be connected to DNA-only calling or duplicate-processing steps. DNA modes explicitly disable splicing and return unsorted SAM suitable for the existing DNA pipeline tools. Paired geometry is ordinary inward-facing FR; RNA strandness means transcript strand, not mate geometry.\n\nRead groups, sample/library/platform/lane, thread count and seed are recorded. Duplicates are retained. RNA sorting uses the stated SAMtools memory amount for one worker. HISAT2 indexing/alignment has no hard memory cap; large genomes require substantial RAM, disk space and time. The 64-bit index avoids the small-index genome-size limit, but does not make large analyses lightweight. Indexes are built anew per operation. No annotation-derived splice database, graph variants, compressed FASTQ, SRA download or reusable prebuilt-index input is exposed by these four operations.\n\nPaths must be ASCII and contain no commas. Spaces are supported. Native Windows binaries were cross-compiled and their DLL imports inspected; Windows execution was not available in the build environment. Four installation self-checks run real synthetic alignments, including a known 100-base splice junction, exact positions/CIGARs and mate flags.\n\nThis is a static LLVM-MinGW source build, not an upstream Windows binary. The small documented CLI patch accepts explicit --rna-strandness unstranded and selects precisely the existing upstream default. Alignment/scoring algorithms remain upstream. Exact GPL source, patch and build recipe are in licenses/. Build with scripts/prepare_hisat2_pack.py --fetch --build; matching Linux reference: scripts/build_hisat2_native.py --linux. The pinned LLVM-MinGW toolchain and existing SHA-pinned portable SAMtools/paircheck helpers are required. GNU GPL v3-or-later covers HISAT2; helper/runtime licenses are retained separately.\n\nCite Kim et al. (2019), Nature Biotechnology 37:907-915, doi:10.1038/s41587-019-0201-4.\n''')
    sys.path.insert(0,str(ROOT/'workspace'));from catalog import load_pack
    pack=load_pack(PACK/'pack.ini');print(json.dumps({'pack':str(PACK),'manifestSha256':sha(PACK/'pack.ini'),'workflows':list(pack['workflows'])}))
if __name__=='__main__':main()
