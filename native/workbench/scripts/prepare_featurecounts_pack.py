#!/usr/bin/env python3
"""Prepare the featureCounts 2.1.1 pack for Native Workbench 0.6.0."""
import argparse, json, shutil, struct, sys, zlib
from pathlib import Path
from build_featurecounts_native import ROOT, VERSION, SOURCES, TC_NAME, sha
sys.path.insert(0,str(ROOT/'desktop'))
from prepare_modular_packs import field, number, artifact, execute, workflow
PACK_VERSION='1.0.0'
CITATION={'text':'Liao Y, Smyth GK, Shi W (2014). featureCounts: an efficient general purpose program for assigning sequence reads to genomic features. Bioinformatics 30:923–930.','url':'https://doi.org/10.1093/bioinformatics/btt656'}
def dump(path,value): path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
def bam_bytes(rows):
    header=b'@HD\tVN:1.6\tSO:unsorted\n@SQ\tSN:chr1\tLN:2000\n'
    body=b'BAM\1'+struct.pack('<i',len(header))+header+struct.pack('<i',1)+struct.pack('<i',5)+b'chr1\0'+struct.pack('<i',2000)
    for row in rows:
        name,flag,pos,cigar,mpos,tlen,nh,mapq=row;name=name.encode()+b'\0'
        seq=sum(length for length,op in cigar if op in 'MIS=X')
        ops=b''.join(struct.pack('<I',(length<<4)+'MIDNSHP=XB'.index(op)) for length,op in cigar)
        block=struct.pack('<iiIIiiii',0,pos-1,(4681<<16)|(mapq<<8)|len(name),(flag<<16)|len(cigar),seq,0 if flag&1 else -1,mpos-1 if mpos else -1,tlen)+name+ops+b'\x11'*((seq+1)//2)+bytes([40])*seq+b'NHi'+struct.pack('<i',nh)
        body+=struct.pack('<i',len(block))+block
    def bgzf(data):
        c=zlib.compressobj(6,zlib.DEFLATED,-15);payload=c.compress(data)+c.flush()
        return b'\x1f\x8b\x08\x04'+bytes(4)+b'\x00\xff\x06\x00BC\x02\x00'+struct.pack('<H',len(payload)+25)+payload+struct.pack('<II',zlib.crc32(data),len(data))
    return b''.join(bgzf(body[n:n+60000]) for n in range(0,len(body),60000))+bgzf(b'')
def fixtures(path):
    path.mkdir(parents=True,exist_ok=True)
    annotation=''.join(f'chr1\tWorkbench\texon\t{start}\t{end}\t.\t{strand}\t.\tgene_id "{gene}"; transcript_id "{gene}.1";\n' for gene,start,end,strand in [('geneA',100,199,'+'),('geneB',300,399,'-'),('geneC',500,549,'+'),('geneC',600,649,'+'),('geneD',700,799,'+'),('geneE',750,849,'+')])
    (path/'genes.gtf').write_text(annotation)
    single=[]
    def one(name,pos,flag=0,nh=1,mapq=60,cigar=None):single.append((name,flag,pos,cigar or [(20,'M')],0,0,nh,mapq))
    one('a_forward',120);one('a_reverse',160,16);one('b_reverse',340,16);one('c_spliced',530,cigar=[(20,'M'),(50,'N'),(20,'M')]);one('overlapping_genes',760);one('multimapping',125,nh=2);one('secondary',130,256);one('duplicate',135,1024);one('low_mapq',140,mapq=10);one('intergenic',1000)
    paired=[]
    def pair(name,left,right,reverse=False,extra=0,nh=1,firstcigar=None,secondflag=None):
        p1,p2=(right,left) if reverse else (left,right);length=right-left+20
        f1=(83 if reverse else 99)|extra;f2=(163 if reverse else 147)|extra
        if secondflag is not None:f2=secondflag
        paired.extend([(name,f1,p1,firstcigar or [(20,'M')],p2,-length if reverse else length,nh,60),(name,f2,p2,[(20,'M')],p1,length if reverse else -length,nh,60)])
    pair('a_forward1',110,170);pair('a_forward2',120,160);pair('a_reverse',115,165,True);pair('b_reverse',310,370,True);pair('c_spliced',530,625,firstcigar=[(20,'M'),(50,'N'),(20,'M')]);pair('overlapping_genes',760,775);pair('multimapping',120,160,nh=2);pair('secondary',120,160,extra=256);pair('duplicate',120,160,extra=1024)
    # A single aligned mate is deliberately not assigned under fixed -B policy.
    paired.extend([('orphan',73,120,[(20,'M')],0,0,1,60),('orphan',133,120,[(20,'M')],120,0,1,0)])
    # Same-strand mates are rejected by the upstream -C chimera filter.
    paired.extend([('chimera',67,120,[(20,'M')],160,60,1,60),('chimera',131,160,[(20,'M')],120,-60,1,60)])
    for name,rows in [('single',single),('paired',paired)]: (path/(name+'.bam')).write_bytes(bam_bytes(rows))
    dump(path/'truth.json',{'description':'Synthetic annotated gene overlaps. Expected raw counts derived from explicit alignment coordinates/flags, not from tool output. Duplicate flags are retained, NH>1/secondary/ambiguous genes excluded. Paired fragments require both mates and opposing strands.','single':{'0':[4,1,1,0,0],'1':[3,1,1,0,0],'2':[1,0,0,0,0]},'paired':{'0':[4,1,1,0,0],'1':[3,1,1,0,0],'2':[1,0,0,0,0]},'genes':['geneA','geneB','geneC','geneD','geneE'],'singleRecords':len(single),'pairedRecords':len(paired)})
def definitions():
    workflows=[]; schemas={}
    for paired in (False,True):
        mode='paired' if paired else 'single';identity='count-'+mode
        inputs=[field('alignment','Paired RNA BAM' if paired else 'Single-end RNA BAM',filter='RNA alignments|*.bam|All files|*.*',help='Binary BAM from a genomic RNA aligner, such as STAR or HISAT2. One sample per run. Coordinate- or name-sorted accepted; no index required. Mixed pairing modes and supplementary alignments are rejected.'),field('annotation','Matching gene annotation GTF',filter='Uncompressed GTF|*.gtf|All files|*.*',help='Same assembly and exact contig names as the BAM. Exon rows require quoted gene_id, valid coordinates and + or - strand. GFF3, gzip GTF and transcript FASTA are not accepted.'),field('strandness','Library strandedness (required)','choice',choices='0:Unstranded|1:Read 1 follows transcript|2:Read 1 opposes transcript',help='Select from the library preparation; no value is inferred. For single-end input this refers to the sequenced read. For paired input it refers to read 1.'),number('threads','CPU threads',2,1,64),number('mapq','Minimum mapping quality',0,0,255,help='Paired fragments pass if at least one mate meets this threshold. NH-tagged multimappers remain excluded. Set consistently across samples.')]
        outputs=[artifact('counts','Raw gene counts','gene-counts.tsv'),artifact('summary','Assignment summary','gene-counts.tsv.summary'),artifact('input-check','BAM and annotation validation','input-validation.json')]
        args=['-T','{input:threads}','-a','{input:annotation}','-o','{output:counts}','-F','GTF','-t','exon','-g','gene_id','-s','{input:strandness}','-Q','{input:mapq}','--primary','--tmpDir','{run}']
        if paired:args+=['-p','--countReadPairs','-B','-C']
        args+=['{input:alignment}']
        steps=[execute('validate','Validate RNA BAM mode and annotation compatibility','featurecounts-guard',[mode,'{input:alignment}','{input:annotation}'],stdout='input-check'),execute('count','Assign fragments to genes' if paired else 'Assign reads to genes','featureCounts',args,produces=['counts','summary'])]
        policy='Paired fragments are counted once with both ends mapped; chimeric/same-strand pairs are excluded (-p --countReadPairs -B -C). No fragment-length filter is applied.' if paired else 'Single-end reads are counted individually.'
        workflows.append(workflow(identity,'Count '+('paired RNA fragments' if paired else 'single-end RNA reads'),policy+' Returns integer raw gene counts and assignment reasons; no normalization or differential expression.',inputs,outputs,steps))
        schemas[identity]={'ports':[dict(id='alignment',label='RNA BAM',type='bam-rna',accepts=['bam-rna'],manifestInputs=['alignment'],min=1,max=1,requiredState={'pairing':mode}),dict(id='annotation',label='Matching GTF annotation',type='text',manifestInputs=['annotation'],min=1,max=1)],'outputs':[dict(id=x['id'],label=x['label'],type='metrics',manifestOutputs=[x['id']]) for x in outputs],'pathPolicy':{'asciiOnly':True},'methods':'RNA alignments were summarized with featureCounts 2.1.1 using GTF exon features grouped by gene_id. '+policy+' Library strandedness and minimum mapping quality were explicitly recorded. Secondary alignments were excluded with --primary, NH-tagged multimappers and reads ambiguous between genes were not assigned, and duplicate-marked reads were retained. Supplementary alignments and mismatched BAM pairing modes were rejected by the Workbench guard, which also checked GTF exon bounds and exact BAM reference names. Counts are unnormalized integers; no differential-expression test was performed.'}
    return workflows,{'schema':1,'category':'RNA-seq','citations':[CITATION],'workflows':schemas}
def checks():
    # The unmodified Windows binary writes text-mode CRLF. Released Workbench
    # checks decode raw UTF-8 bytes, preserving CR; retain exact count boundaries.
    newline='\r\n'
    values=[]
    tails=['chr1\t100\t199\t+\t100','chr1\t300\t399\t-\t100','chr1;chr1\t500;600\t549;649\t+;+\t100','chr1\t700\t799\t+\t100','chr1\t750\t849\t+\t100']
    for mode in ('single','paired'):
        for strand,counts in [('0',[4,1,1,0,0]),('1',[3,1,1,0,0]),('2',[1,0,0,0,0])]:
            values.append({'id':mode+'-strand-'+strand,'workflow':'count-'+mode,'params':{'threads':2,'strandness':strand,'mapq':0},'inputs':{'alignment':[{'alignment':'fixture-'+mode}],'annotation':[{'annotation':'fixture-annotation'}]},'expect':[{'output':'counts','kind':'text','contains':['Geneid\tChr\tStart\tEnd\tStrand\tLength',*[gene+'\t'+tail+'\t'+str(count)+newline for gene,tail,count in zip(['geneA','geneB','geneC','geneD','geneE'],tails,counts)]]},{'output':'summary','kind':'text','contains':['Assigned\t'+str(sum(counts))+newline,'Unassigned_MultiMapping\t1'+newline,'Unassigned_Secondary\t1'+newline]},{'output':'input-check','kind':'text','contains':['"valid":true','"gtf_exons":6']}]})
    return {'schema':1,'checks':values}
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cache',type=Path,default=ROOT.parent/'popular-build/featurecounts');p.add_argument('--destination',type=Path,default=ROOT/'packs/featurecounts-1.0.0');p.add_argument('--toolchain',type=Path,default=ROOT.parent/'toolchains'/TC_NAME);a=p.parse_args()
    cache=a.cache.resolve();dest=a.destination.resolve();build=json.loads((cache/'build-windows/build.json').read_text())
    if build['version']!=VERSION or build['guardSourceSha256']!=sha(ROOT/'tools/featurecounts/guard.cpp'):raise ValueError('Build identity mismatch')
    if dest.exists() and any(dest.iterdir()):raise ValueError('Destination must be new/empty')
    for directory in ('bin','fixtures','licenses'):(dest/directory).mkdir(parents=True,exist_ok=True)
    sections=[]
    def section(name,values):sections.append('['+name+']\n'+'\n'.join(k+'='+str(v) for k,v in values.items() if k!='id' or name=='pack')+'\n')
    section('pack',dict(format=2,id='featurecounts',version=PACK_VERSION,name='featureCounts gene counts',platform='windows-x86_64',description='Count aligned bulk RNA reads or fragments by gene with explicit strandedness and paired-fragment policy. Workbench 0.6.0 or newer.',color='#3D8A82'))
    for name in ('featureCounts','featurecounts-guard'):
        source=cache/'build-windows'/(name+'.exe')
        if sha(source)!=build['files'][source.name]['sha256']:raise ValueError('Changed executable')
        shutil.copy2(source,dest/'bin'/source.name);section('tool:'+name.lower(),dict(path='bin/'+source.name,version=VERSION if name=='featureCounts' else '1.0.0',sha256=sha(source)))
    workflows,schema=definitions()
    # Tool IDs are case-normalized by this pack, filenames retain upstream spelling.
    for wf in workflows:
        for step in wf['steps']:step['tool']=step['tool'].lower()
    dump(dest/'workbench-schema.json',schema);dump(dest/'workbench-checks.json',checks());fixtures(dest/'fixtures')
    for name,path in {'workbench-schema':'workbench-schema.json','workbench-checks':'workbench-checks.json','fixture-annotation':'fixtures/genes.gtf','fixture-single':'fixtures/single.bam','fixture-paired':'fixtures/paired.bam','fixture-truth':'fixtures/truth.json'}.items():section('asset:'+name,dict(path=path,sha256=sha(dest/path)))
    for wf in workflows:
        section('workflow:'+wf['id'],dict(name=wf['name'],description=wf['description'],inputs=','.join(x['id'] for x in wf['inputs']),outputs=','.join(x['id'] for x in wf['outputs']),steps=','.join(x['id'] for x in wf['steps'])))
        for kind in ('input','output','step'):
            for item in wf[kind+'s']:section(kind+':'+wf['id']+':'+item['id'],item)
    (dest/'pack.ini').write_text('\n'.join(sections),encoding='utf-8');lic=dest/'licenses'
    for name,(_,digest) in SOURCES.items():
        if sha(cache/name)!=digest:raise ValueError('Changed upstream artifact')
        if name.endswith('.tar.gz'):shutil.copy2(cache/name,lic/name)
    for source,name in [(cache/'subread-2.1.1-source/LICENSE','Subread-GPL-3.0.txt'),(cache/'zlib-1.3.2/LICENSE','zlib-LICENSE.txt'),(a.toolchain/'LICENSE.TXT','LLVM-LICENSE.txt'),(ROOT/'LICENSE','Workbench-MIT-LICENSE.txt'),(ROOT/'tools/featurecounts/guard.cpp','guard.cpp'),(ROOT/'scripts/build_featurecounts_native.py','build_featurecounts_native.py')]:shutil.copy2(source,lic/name)
    for source in (a.toolchain/'x86_64-w64-mingw32/share/mingw32').glob('COPYING*'):shutil.copy2(source,lic/source.name)
    dump(lic/'provenance.json',build)
    (lic/'MODIFICATIONS.txt').write_text('featureCounts 2.1.1 is the unmodified official Windows x86-64 executable from the pinned Subread release archive. The complete matching GPL source archive is retained. Workbench adds a separate MIT input guard with statically linked unmodified zlib 1.3.2; guard sources, build recipe, compiler notices and exact source archive are retained. The guard checks format, pairing, supplementary flags, annotation names/coordinates/attributes; it does not assign or count reads. No upstream counting code is modified. Native Windows scientific checks are a separate release gate; build provenance does not claim execution.\n')
    shutil.copy2(ROOT/'docs/FEATURECOUNTS-PACK.md',dest/'PACK-README.md')
    sys.path.insert(0,str(ROOT/'workspace'));from catalog import load_pack
    pack=load_pack(dest/'pack.ini');print(json.dumps({'pack':str(dest),'manifestSha256':sha(dest/'pack.ini'),'workflows':list(pack['workflows'])},indent=2))
if __name__=='__main__':main()
