#!/usr/bin/env python3
"""Prepare the independent STAR 1.0.0 pack for Native Workbench 0.6.0+."""
import argparse, hashlib, json, random, shutil, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT.parent/'rna-build/star'
PACK=ROOT/'packs/star-1.0.0'
TC=ROOT.parent/'toolchains/llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64'
VERSION='2.7.11b-workbench1'
CITATION={'text':'Dobin A et al. (2013). STAR: ultrafast universal RNA-seq aligner. Bioinformatics 29:15-21.','url':'https://doi.org/10.1093/bioinformatics/bts635'}
PINNED={'samtools':('samtools-cosmo.exe','1.24','49c2f16425d464e4ad1c1439d7a9e32a3b1c1bf8e5d54403778de610d2f440b3'),'paircheck':('paircheck-cosmo.exe','1.0.1','4f2dda7e26b5c115a7edee936a8a059eb55ece244931b2799a62cebfcd44ecd4')}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,value):p.write_text(json.dumps(value,indent=2)+'\n')
def fixtures(path):
    path.mkdir(parents=True,exist_ok=True);rng=random.Random(20261004)
    seq=''.join(rng.choice('ACGT') for _ in range(10000));seq=seq[:700]+'GT'+seq[702:1498]+'AG'+seq[1500:]
    (path/'reference.fa').write_text('>chrSynthetic\n'+seq+'\n')
    (path/'annotation.gtf').write_text(''.join('chrSynthetic\tWorkbench\texon\t%d\t%d\t.\t+\t.\tgene_id "gene1"; transcript_id "tx1"; gene_name "SyntheticGene";\n'%(a,b) for a,b in [(301,700),(1501,1900)]))
    rc=lambda s:s.translate(str.maketrans('ACGT','TGCA'))[::-1]
    junction=seq[650:700]+seq[1500:1550]
    def fq(name,rows):(path/name).write_text(''.join('@'+label+'\n'+s+'\n+\n'+'I'*len(s)+'\n' for label,s in rows))
    fq('rna-unmapped.fastq',[('rna_unmapped','N'*100)])
    fq('rna-single.fastq',[('rna_junction',junction),('rna_exon',seq[1600:1700])])
    fq('rna-r1.fastq',[('rna_pair/1',junction)]);fq('rna-r2.fastq',[('rna_pair/2',rc(seq[1700:1800]))])

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--build',action='store_true');parser.add_argument('--fetch',action='store_true');args=parser.parse_args()
    if args.build:subprocess.run([sys.executable,str(ROOT/'scripts/build_star_native.py'),*(['--fetch'] if args.fetch else [])],check=True)
    for d in ('bin','licenses','fixtures'):(PACK/d).mkdir(parents=True,exist_ok=True)
    sections=[('pack',{'format':'2','id':'star','version':'1.0.0','name':'STAR RNA-seq alignment','platform':'windows-x86_64','description':'Build a genome index and align single or paired RNA reads, optionally using GTF annotations and producing gene counts. Native Workbench 0.6.0+.','color':'#427C84'})]
    shutil.copy2(CACHE/'build-windows/STAR.exe',PACK/'bin/STAR.exe')
    sections.append(('tool:star',{'path':'bin/STAR.exe','version':VERSION,'sha256':sha(PACK/'bin/STAR.exe')}))
    shutil.copy2(CACHE/'build-windows/libomp.dll',PACK/'bin/libomp.dll')
    sections.append(('asset:openmp-runtime',{'path':'bin/libomp.dll','sha256':sha(PACK/'bin/libomp.dll')}))
    for name,(filename,version,digest) in PINNED.items():
        candidates=[ROOT/'baselines/bin'/filename,ROOT.parent/'integration-source/native-workbench/baselines/bin'/filename]
        source=next((p for p in candidates if p.is_file()),PACK/'bin'/(name+'.exe'))
        if sha(source)!=digest:raise ValueError('Helper hash mismatch: '+name)
        if source!=PACK/'bin'/(name+'.exe'):shutil.copy2(source,PACK/'bin'/(name+'.exe'))
        sections.append(('tool:'+name,{'path':'bin/'+name+'.exe','version':version,'sha256':digest}))
    fixtures(PACK/'fixtures')
    schema={'schema':1,'category':'RNA-seq','citations':[CITATION],'workflows':{}}
    checks={'schema':1,'checks':[]}
    for annotated in (False,True):
      for paired in (False,True):
        identity='rna-'+('paired' if paired else 'single')+('-counts' if annotated else '')
        title='STAR '+('paired-end' if paired else 'single-end')+(' + gene counts' if annotated else ' alignment')
        inputs=(['reads1','reads2'] if paired else ['reads'])+['reference']+(['annotation','overhang'] if annotated else [])+['sample','read-group','platform','threads','two-pass','min-intron','max-intron','multimap','sort-memory-mb']
        outputs=(['pair-check'] if paired else [])+['aligned-sam','aligned','bam-index','junctions','summary','log']+(['gene-counts'] if annotated else [])
        steps=(['check-pairs'] if paired else [])+['index','align','sort','bam-index']
        sections.append(('workflow:'+identity,{'name':title,'description':'Build a private STAR genome index, align uncompressed Phred+33 RNA FASTQ reads, and return coordinate-sorted BAM/CSI plus SAM, splice junctions and logs.'+(' GTF annotation supplies known junctions and STAR GeneCounts.' if annotated else ' No gene annotation is required; splice sites are discovered from the reads.'),'inputs':','.join(inputs),'outputs':','.join(outputs),'steps':','.join(steps)}))
        def inp(key,fields):sections.append(('input:'+identity+':'+key,fields))
        for key in (['reads1','reads2'] if paired else ['reads']):
            value={'label':{'reads':'RNA reads FASTQ','reads1':'RNA read 1 FASTQ','reads2':'RNA read 2 FASTQ'}[key],'type':'file','required':'true','filter':'Uncompressed FASTQ|*.fastq;*.fq|All files|*.*','help':'Uncompressed Phred+33 short RNA reads. Gzip is not accepted. '+('Mates must match in name, count and order. ' if paired else '')+'Use ASCII paths without commas; spaces are supported.'}
            if key=='reads2':value['different-from']='reads1'
            inp(key,value)
        inp('reference',{'label':'Reference genome FASTA','type':'file','required':'true','filter':'Uncompressed FASTA|*.fa;*.fasta;*.fna|All files|*.*','help':'Genomic reference, not transcript sequences. STAR rebuilds its index for every run. Human alignment typically needs tens of GB of RAM; this pack does not reduce STAR memory requirements. Use the assembly matching your GTF.'})
        if annotated:
            inp('annotation',{'label':'Gene annotation GTF','type':'file','required':'true','filter':'GTF annotation|*.gtf|All files|*.*','help':'GTF with exon features and gene_id/transcript_id attributes; chromosome names and assembly must match the FASTA. GFF3 is not interchangeable. Counts contain unstranded, forward and reverse columns; select the correct column for your library.'})
        for key,label,default in [('sample','Sample ID','sample1'),('read-group','Read-group ID','rg1')]:inp(key,{'label':label,'type':'text','required':'true','default':default,'constraint':'identifier','help':'Recorded in the alignment read group and methods.'})
        inp('platform',{'label':'Sequencing platform','type':'choice','required':'true','default':'ILLUMINA','choices':'ILLUMINA:Illumina|DNBSEQ:DNBSEQ (MGI/BGI)','help':'Recorded as the alignment read-group PL value; choose the actual sequencing platform.'})
        def integer(key,label,default,lo,hi,helptext):inp(key,{'label':label,'type':'integer','required':'true','default':str(default),'min':str(lo),'max':str(hi),'help':helptext})
        integer('threads','STAR CPU threads',2,1,64,'Used for indexing and alignment. More threads can increase memory use; SAMtools sorting uses one worker.')
        if annotated:integer('overhang','Splice-junction overhang',100,1,649,'Normally maximum read length minus one; 100 is an upstream-recommended generic value. Used when building the annotation index.')
        inp('two-pass',{'label':'Splice discovery passes','type':'choice','required':'true','default':'Basic','choices':'Basic:Two passes (discover then realign)|None:One pass','help':'Two-pass mode discovers sample splice junctions then repeats alignment. This improves novel-junction sensitivity and takes longer.'})
        integer('min-intron','Minimum intron length',21,1,1000000,'Shortest allowed intron. Must not exceed maximum intron length.')
        integer('max-intron','Maximum intron length',1000000,1,10000000,'Longest allowed intron. Choose for the organism; this also bounds the paired-end mate gap.')
        integer('multimap','Maximum mapping loci',10,1,10000,'Reads with more mapping loci are reported as unmapped. All accepted primary/secondary alignments are retained; duplicates are not removed.')
        integer('sort-memory-mb','BAM sorting memory (MiB)',256,64,8192,'Memory for the single SAMtools sorting worker; this is not a cap on STAR indexing or alignment RAM.')
        def output(key,label,path,nonempty=True):sections.append(('output:'+identity+':'+key,{'label':label,'path':path,'final':'true','nonempty':str(nonempty).lower()}))
        if paired:output('pair-check','Read-pair validation','read-pairs.json')
        output('aligned-sam','Unsorted RNA SAM','Aligned.out.sam')
        output('aligned','Coordinate-sorted RNA BAM','alignment.sorted.bam')
        output('bam-index','RNA BAM CSI index','alignment.sorted.bam.csi')
        output('junctions','Splice junctions','SJ.out.tab',False)
        output('summary','STAR alignment summary','Log.final.out')
        output('log','STAR detailed log','Log.out')
        if annotated:output('gene-counts','STAR gene counts (three strand conventions)','ReadsPerGene.out.tab')
        def step(key,label,tool,argv,produces=None,stdout=None):
            value={'label':label,'kind':'exec','tool':tool}
            if produces:value['produces']=','.join(produces)
            if stdout:value['stdout']=stdout
            value.update({'arg.'+str(i):arg for i,arg in enumerate(argv)})
            sections.append(('step:'+identity+':'+key,value))
        if paired:step('check-pairs','Validate mate names, count and order','paircheck',['--reads1','{input:reads1}','--reads2','{input:reads2}'],stdout='pair-check')
        index=['--runMode','genomeGenerate','--genomeDir','{run}/index/','--genomeFastaFiles','{input:reference}','--genomeSAindexNbases','0','--runThreadN','{input:threads}','--outFileNamePrefix','{run}/index-build.','--genomeLoad','NoSharedMemory']
        if annotated:index+=['--sjdbGTFfile','{input:annotation}','--sjdbOverhang','{input:overhang}']
        step('index','Build a private STAR genome index','star',index)
        align=['--genomeDir','{run}/index/','--runThreadN','{input:threads}','--genomeLoad','NoSharedMemory','--outFileNamePrefix','{run}/','--readFilesIn']+(['{input:reads1}','{input:reads2}'] if paired else ['{input:reads}'])+['--outSAMtype','SAM','--outSAMunmapped','Within','--outSAMattributes','NH','HI','AS','nM','NM','MD','XS','--outSAMattrRGline','ID:{input:read-group}','SM:{input:sample}','PL:{input:platform}','--twopassMode','{input:two-pass}','--alignIntronMin','{input:min-intron}','--alignIntronMax','{input:max-intron}','--alignMatesGapMax','{input:max-intron}','--outFilterMultimapNmax','{input:multimap}','--runRNGseed','777']
        if annotated:align+=['--quantMode','GeneCounts']
        step('align','Align RNA reads'+(' and count genes' if annotated else ''),'star',align,['aligned-sam','junctions','summary','log']+(['gene-counts'] if annotated else []))
        step('sort','Sort RNA alignments by coordinate','samtools',['sort','-m','{input:sort-memory-mb}M','-o','{output:aligned}','{output:aligned-sam}'],['aligned'])
        step('bam-index','Index coordinate-sorted RNA BAM','samtools',['index','-c','{output:aligned}','{output:bam-index}'],['bam-index'])
        ports=[{'id':'reads','label':'Paired RNA reads' if paired else 'RNA reads','type':'pair' if paired else 'reads','accepts':['pair' if paired else 'reads'],'manifestInputs':['reads1','reads2'] if paired else ['reads'],'min':1,'max':1,'requiredState':{'compression':'none'}},{'id':'reference','label':'Reference genome','type':'reference','accepts':['reference'],'manifestInputs':['reference'],'min':1,'max':1,'requiredState':{'compression':'none'}}]
        if annotated:ports.append({'id':'annotation','label':'GTF annotation','type':'text','accepts':['text'],'manifestInputs':['annotation'],'min':1,'max':1})
        products=[]
        for key,kind,label in [('aligned','bam-rna','Coordinate-sorted RNA BAM'),('aligned-sam','sam-rna','Unsorted RNA SAM'),('bam-index','index','BAM CSI index'),('junctions','metrics','Splice junctions'),('summary','metrics','Alignment summary'),('log','metrics','Detailed alignment log')]+([('gene-counts','metrics','Gene counts')] if annotated else [])+([('pair-check','metrics','Read-pair validation')] if paired else []):
            product={'id':key,'label':label,'type':kind,'manifestOutputs':[key]}
            if key in ('aligned','aligned-sam'):product['state']={'sort':'coordinate' if key=='aligned' else 'unsorted','pairing':'paired' if paired else 'single','duplicates':'retained'}
            products.append(product)
        schema['workflows'][identity]={'category':'RNA-seq','ports':ports,'outputs':products,'pathPolicy':{'asciiOnly':True,'forbiddenCharacters':[',']},'parameterConstraints':[{'left':'min-intron','operator':'<=','right':'max-intron'}],'methods':'RNA reads were aligned to the supplied genomic reference with STAR '+VERSION+'. A private index was built for each run; the suffix-array prefix length was selected as max(1, min(14, floor(log2(genome length)/2 - 1))). '+('Known splice junctions and gene models were supplied from the matching GTF, and STAR GeneCounts reported unstranded, forward and reverse counts. ' if annotated else 'Splice junctions were discovered without a supplied annotation. ')+'Alignments retained duplicates and accepted multimappers. Read groups recorded the sample and sequencing platform. Alignments were sorted by coordinate and CSI-indexed using SAMtools 1.24. All displayed parameters and exact input/tool hashes are recorded in the results.','citations':[{'text':'Danecek P et al. (2021). Twelve years of SAMtools and BCFtools. GigaScience 10:giab008.','url':'https://doi.org/10.1093/gigascience/giab008'}]}
        bindings={'reference':[{'reference':'fixture-reference'}],'reads':[{'reads1':'fixture-rna-r1','reads2':'fixture-rna-r2'} if paired else {'reads':'fixture-rna-single'}]}
        if annotated:bindings['annotation']=[{'annotation':'fixture-annotation'}]
        truth={'output':'aligned-sam','kind':'sam','records':2,'mapped':2,'paired':2 if paired else 0,'properPairs':2 if paired else 0,'spliced':1,'references':{'chrSynthetic':10000},'samples':['validation'],'allReadGroups':True,'alignments':[{'name':'rna_pair' if paired else 'rna_junction','reference':'chrSynthetic','position':651,'cigar':'50M800N50M','flag':99 if paired else 0,'tags':{'RG':'validation'}},{'name':'rna_pair' if paired else 'rna_exon','reference':'chrSynthetic','position':1701 if paired else 1601,'cigar':'100M','flag':147 if paired else 0,'tags':{'RG':'validation'}}]}
        expected=[truth,{'output':'summary','kind':'text','contains':['Uniquely mapped reads number |\t'+('1' if paired else '2')]}]
        if annotated:expected.append({'output':'gene-counts','kind':'text','contains':['gene1\t'+('1\t1\t0' if paired else '2\t2\t0')]})
        checks['checks'].append({'id':identity,'workflow':identity,'params':{'sample':'validation','read-group':'validation','threads':'2' if paired and annotated else '1'},'inputs':bindings,'expect':expected})
    checks['checks'].append({'id':'rna-unmapped-counts','workflow':'rna-single-counts','params':{'sample':'validation','read-group':'validation','threads':'1'},'inputs':{'reference':[{'reference':'fixture-reference'}],'reads':[{'reads':'fixture-rna-unmapped'}],'annotation':[{'annotation':'fixture-annotation'}]},'expect':[{'output':'aligned-sam','kind':'sam','records':1,'mapped':0,'paired':0,'properPairs':0,'spliced':0,'references':{'chrSynthetic':10000},'samples':['validation'],'allReadGroups':True,'alignments':[{'name':'rna_unmapped','reference':'*','position':0,'cigar':'*','flag':4,'tags':{'RG':'validation'}}]},{'output':'gene-counts','kind':'text','contains':['N_unmapped\t1\t1\t1','gene1\t0\t0\t0']}]})
    dump(PACK/'workbench-schema.json',schema);dump(PACK/'workbench-checks.json',checks)
    for identity,path in [('workbench-schema','workbench-schema.json'),('workbench-checks','workbench-checks.json')]+[('fixture-'+p.stem,'fixtures/'+p.name) for p in sorted((PACK/'fixtures').iterdir())]:sections.insert(5,('asset:'+identity,{'path':path,'sha256':sha(PACK/path)}))
    (PACK/'pack.ini').write_text('\n\n'.join('['+name+']\n'+'\n'.join(k+'='+v for k,v in fields.items()) for name,fields in sections)+'\n')
    licenses=PACK/'licenses'
    for source,name in [(CACHE/'STAR-2.7.11b.tar.gz','STAR-2.7.11b.tar.gz'),(CACHE/'zlib-1.3.2.tar.gz','zlib-1.3.2.tar.gz'),(CACHE/'STAR-2.7.11b/LICENSE','STAR-LICENSE.txt'),(CACHE/'workbench1.patch','workbench1.patch'),(CACHE/'build-windows/build.json','windows-build.json'),(ROOT/'scripts/build_star_native.py','build_star_native.py'),(ROOT/'scripts/prepare_star_pack.py','prepare_star_pack.py'),(TC/'LICENSE.TXT','LLVM-LICENSE.txt')]:shutil.copy2(source,licenses/name)
    shutil.copytree(ROOT/'tools/star',licenses/'star-port',dirs_exist_ok=True)
    for source in (TC/'x86_64-w64-mingw32/share/mingw32').glob('COPYING*'):shutil.copy2(source,licenses/source.name)
    original=ROOT.parent/'integration-source/native-workbench'
    for folder,name in [('baselines/licenses','portable-runtime'),('vendor-variant/licenses','samtools-runtime')]:
        source=ROOT/folder
        if not source.is_dir():source=original/folder
        if source.is_dir():shutil.copytree(source,licenses/name,dirs_exist_ok=True)
    provenance=json.loads((CACHE/'build-windows/build.json').read_text());provenance.update({'tool':'STAR','version':VERSION,'packVersion':'1.0.0','minimumWorkbenchVersion':'0.6.0','executionTestsPerformedByBuild':False,'citation':CITATION,'limitations':['Native Windows execution is tested separately; see release evidence for recorded Windows results. Source-matched Linux regressions do not prove Windows execution.','Uncompressed FASTQ and FASTA only; ASCII paths without commas.','Bulk short-read RNA alignment only; STARsolo, shared memory, shell read commands and arbitrary input streaming are outside the supported pack interface.','Indexes are rebuilt each run; human-scale workloads require tens of GB of RAM.','Reference and annotation must use the same assembly and chromosome names. Gene counts are raw counts, not TPM or differential expression.']});dump(licenses/'provenance.json',provenance)
    (licenses/'MODIFICATIONS.txt').write_text('STAR 2.7.11b-workbench1 for Native Workbench, 2026-10-03. The upstream RNA alignment, splice discovery and gene-counting algorithms are retained. Port changes replace unavailable Windows directory/disk/memory primitives, use binary I/O, provide explicit failures for unsupported Unix FIFO/shared-memory operations, and adapt compiler/library includes. Parameter logging requires an opened stream, preventing a libc++ null dereference when formatted default values would otherwise be written before the log file is opened. Explicit bounded external-buffer streams replace implementation-defined stringbuf pubsetbuf for FASTQ/SAM chunks, with exact populated input lengths and checked output capacity; this prevents empty reads and detached output under libc++. GTF inputs fail on missing contigs, invalid exon coordinates/strands or missing gene/transcript IDs instead of silently skipping records. genomeSAindexNbases=0 automatically selects the upstream documented recommendation after scanning genome length. HTSlib remote access and unused SAM/CRAM parsing/indexing functions are excluded; original local BGZF/BAM header, record and auxiliary-tag functions used by STAR are retained. The exact source archive, patch, support code and build recipe are supplied here.\n')
    (PACK/'PACK-README.md').write_text('''# STAR RNA-seq pack 1.0.0\n\nRequires Native Workbench 0.6.0 or newer on Windows x86-64. Four operations provide single-end or paired-end bulk RNA-seq alignment, with optional matching GTF annotation and gene counts. Each builds its own STAR reference index, performs one- or two-pass alignment, and returns unsorted RNA SAM, coordinate-sorted BAM, CSI index, splice junctions, summary and detailed log. Annotated modes add ReadsPerGene.out.tab.\n\nSelect genomic FASTA (not transcript FASTA) and uncompressed Phred+33 FASTQ. Gzip inputs are not accepted. Paired files must have matching names, record order and counts. Use ASCII paths without commas; spaces are supported. GTF must contain exon, gene_id and transcript_id records and match the exact genome assembly/chromosome names; GFF3 is not interchangeable. Counts are raw and retain STAR's three strand conventions: column 2 unstranded, column 3 forward, column 4 reverse. Pick the correct library column; do not add the three columns. No normalization or differential-expression analysis is performed. RNA outputs are intentionally typed separately from DNA caller inputs.\n\nSTAR indexes are rebuilt for each run. This pack does not reduce upstream RAM requirements: human-scale STAR work generally requires tens of GB of RAM and substantial index storage. The sorting memory setting caps only the SAMtools sorting worker. Small genomes use an automatically selected suffix-array prefix according to STAR's published sizing recommendation, recorded in the index log. No reusable-index archive, STARsolo, shared-memory index, external decompression shell, CRAM, or network input is exposed. The upstream short-read size limit applies (650 bases).\n\nThis is a native LLVM-MinGW Windows source build, with the matching OpenMP runtime included. No Docker, WSL, Python, browser or Unix shell is needed to run the pack. STAR 2.7.11b-workbench1 preserves the upstream scientific algorithms; the bounded OS portability patch and exact source/build metadata are in licenses/. Native Windows execution is tested separately; see release evidence for recorded Windows results. The bundled installation checks run real single/paired spliced alignments and count tests on your machine. Linux regression results must not be mistaken for native Windows validation.\n\nCite Dobin et al. (2013), Bioinformatics 29:15-21, doi:10.1093/bioinformatics/bts635; and Danecek et al. (2021) for SAMtools.\n''')
    from prepare_rnaseq_licenses import retain_rna_notices
    retain_rna_notices(ROOT, PACK, 'star')
    sys.path.insert(0,str(ROOT/'workspace'));from catalog import load_pack
    pack=load_pack(PACK/'pack.ini');print(json.dumps({'pack':str(PACK),'workflows':list(pack['workflows']),'manifestSha256':sha(PACK/'pack.ini')}))
if __name__=='__main__':main()
