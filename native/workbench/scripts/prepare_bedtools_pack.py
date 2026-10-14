#!/usr/bin/env python3
"""Package local BEDTools interval operations for Native Workbench 0.6.0."""
import argparse, hashlib, json, shutil, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from prepare_modular_packs import field, number, artifact, execute, workflow
from build_bedtools_native import DEFAULT_CACHE, DEFAULT_TC, SOURCES, VERSION, sha
PACK_VERSION='1.0.0'
CITATION={'text':'Quinlan AR, Hall IM (2010). BEDTools: a flexible suite of utilities for comparing genomic features.', 'url':'https://doi.org/10.1093/bioinformatics/btq033'}
BED='Uncompressed BED intervals|*.bed|All files|*.*'
FASTA='Uncompressed reference FASTA|*.fa;*.fasta;*.fna|All files|*.*'

def definitions():
    workflows=[];schemas={}
    for identity,title,description in [
        ('intersect','Overlapping intervals','Retain each A interval once if it overlaps any B interval by at least one base.'),
        ('intersect-stranded','Overlapping intervals on the same strand','Retain each BED6 A interval once when any B interval overlaps on the same + or - strand.'),
        ('nonoverlap','Intervals without an overlap','Retain each A interval only when it has no overlap with B; adjacent intervals do not overlap.'),
        ('subtract','Subtract intervals','Remove B-covered bases from A and emit the remaining interval pieces, retaining A metadata.'),
        ('coverage','Interval coverage','For each A interval, append the number of overlapping B features, covered bases, A length and covered fraction.'),
        ('sort','Sort genomic intervals','Sort intervals by chromosome name and start coordinate using BEDTools sort.'),
        ('merge','Merge genomic intervals','Sort and merge overlapping or book-ended intervals; optionally bridge gaps up to the specified distance. Output is BED3.'),
        ('getfasta','Extract interval sequences','Extract genomic reference sequence for each BED interval, ignoring strand. Coordinates are zero-based and half-open.'),
        ('getfasta-stranded','Extract sequences by strand','Extract genomic reference sequences and reverse-complement minus-strand BED6 intervals.')]:
        strand=identity.endswith('-stranded');extract=identity.startswith('getfasta');two=identity in ('intersect','intersect-stranded','nonoverlap','subtract','coverage')
        inputs=[field('a','Intervals A' if two else 'Intervals',filter=BED,help='Plain tab-separated BED3–BED6, zero-based half-open; use positive-length intervals and one consistent column count. Workbench 0.6 validates at most 1,000,000 intervals per input.'+(' BED6 with explicit + or - required.' if strand else ' BED12 blocks are not supported.'))]
        ports=[dict(id='a',type='bed',manifestInputs=['a'],min=1,max=1,validation={'minColumns':6 if strand else 3,**({'referenceBounds':True} if extract else {})})]
        outputs=[artifact('validation-a','Input interval validation','validation-a.json',False)]
        products=[dict(id='validation-a',type='metrics',manifestOutputs=['validation-a'],state={})]
        steps=[execute('validate-a','Validate BED columns and strands','bedcheck',['strand' if strand else 'plain','{input:a}'],stdout='validation-a')]
        if two:
            inputs.append(field('b','Intervals B',filter=BED,help='Intervals from the same reference assembly and contig naming convention as A. No assembly conversion is inferred.'))
            ports.append(dict(id='b',type='bed',manifestInputs=['b'],min=1,max=1,validation={'minColumns':6 if strand else 3}))
            outputs.append(artifact('validation-b','Comparison interval validation','validation-b.json',False));products.append(dict(id='validation-b',type='metrics',manifestOutputs=['validation-b'],state={}))
            steps.append(execute('validate-b','Validate comparison BED','bedcheck',['strand' if strand else 'plain','{input:b}'],stdout='validation-b'))
        outtype='metrics' if identity=='coverage' else 'fasta-nucleotide' if extract else 'bed'
        outputs.append(artifact('result',title+' result','coverage.tsv' if identity=='coverage' else 'sequences.fasta' if extract else 'result.bed',nonempty=extract or identity=='coverage'))
        products.append(dict(id='result',type=outtype,manifestOutputs=['result'],state={'compression':'none',**({'sort':'coordinate'} if identity in ('sort','merge') else {})}))
        if extract:
            inputs.append(field('reference','Reference genome',filter=FASTA,help='Matching uncompressed genomic DNA FASTA; copied into the run directory before indexing. Contigs over 2,147,483,647 bases exceed the bundled faidx interface.'))
            ports.append(dict(id='reference',type='reference',manifestInputs=['reference'],min=1,max=1,requiredState={'compression':'none'}))
            outputs.append(artifact('validation-reference','Reference validation','validation-reference.json',False));products.append(dict(id='validation-reference',type='metrics',manifestOutputs=['validation-reference'],state={}))
            steps.append(execute('validate-reference','Validate reference alphabet and contig lengths','bedcheck',['reference','{input:reference}'],stdout='validation-reference'))
            outputs.extend([artifact('reference-copy','Private reference copy','reference.fa',False),artifact('reference-index','Private FASTA index','reference.fa.fai',False)])
            products.extend([dict(id='reference-copy',type='reference',manifestOutputs=['reference-copy'],state={'compression':'none'}),dict(id='reference-index',type='index',manifestOutputs=['reference-index'],state={})])
            steps.append(dict(id='copy-reference',label='Stage a private reference copy',kind='copy',source='{input:reference}',destination='reference-copy'))
            args=['getfasta','-fi','{output:reference-copy}','-bed','{input:a}','-fo','{output:result}']+(['-s'] if strand else [])
            steps.append(execute('run',title,'bedtools',args,produces=['result','reference-index']))
        elif identity=='merge':
            inputs.append(number('distance','Maximum gap to merge (bases)',0,0,1000000,help='Zero merges overlapping or adjacent intervals. A positive value also merges intervals separated by up to that many bases; strand is ignored.'))
            outputs.append(artifact('sorted','Private sorted intervals','sorted.bed',False));products.append(dict(id='sorted',type='bed',manifestOutputs=['sorted'],state={'compression':'none','sort':'coordinate'}))
            steps.extend([execute('sort','Sort intervals before merging','bedtools',['sort','-i','{input:a}'],stdout='sorted'),execute('run',title,'bedtools',['merge','-i','{output:sorted}','-d','{input:distance}'],stdout='result')])
        else:
            args=['sort','-i','{input:a}'] if identity=='sort' else ([identity if identity in ('subtract','coverage') else 'intersect','-a','{input:a}','-b','{input:b}']+(['-u'] if identity.startswith('intersect') else ['-v'] if identity=='nonoverlap' else [])+(['-s'] if strand else []))
            steps.append(execute('run',title,'bedtools',args,stdout='result'))
        if outtype=='bed':
            outputs.append(artifact('summary','Output interval count','interval-summary.json'));products.append(dict(id='summary',type='metrics',manifestOutputs=['summary'],state={}))
            steps.append(execute('summarize','Count output intervals','bedcheck',['summary','{output:result}'],stdout='summary'))
        workflows.append(workflow(identity,title,description,inputs,outputs,steps))
        schemas[identity]={'ports':ports,'outputs':products,'methods':'Genomic intervals were processed using BEDTools '+VERSION+'. '+description+' Input coordinates used the BED zero-based half-open convention. '+('Both input interval sets were required to refer to the same assembly; this cannot be inferred from coordinate overlap. ' if two else '')+('The original reference was preserved and a private FASTA copy was indexed in the run directory. ' if extract else '')+'The selected parameters and exact inputs are recorded with the run.', 'pathPolicy':{'asciiOnly':True}}
    return workflows,{'schema':1,'category':'Genomic intervals','citations':[CITATION],'workflows':schemas}

FIXTURES={
 'a.bed':'chr1\t0\t4\ta\t0\t+\nchr1\t4\t8\tb\t0\t-\nchr1\t10\t12\tc\t0\t+\n',
 'crlf.bed':'chr1\t0\t4\ta\t0\t+\r\nchr1\t4\t8\tb\t0\t-\r\nchr1\t10\t12\tc\t0\t+\r\n',
 'b.bed':'chr1\t2\t6\tx\t0\t+\nchr1\t7\t9\ty\t0\t-\n',
 'strand.bed':'chr1\t2\t6\tx\t0\t+\nchr1\t10\t11\tz\t0\t-\n',
 'far.bed':'chr1\t20\t24\tfar\t0\t+\n',
 'unsorted.bed':'chr1\t10\t12\tc\t0\t+\nchr1\t4\t8\tb\t0\t-\nchr1\t0\t4\ta\t0\t+\n',
 'large-a.bed':'chrLarge\t3000000000\t3000000100\nchrLarge\t4000000000\t4000000100\n',
 'large-b.bed':'chrLarge\t3000000050\t3000000200\n',
 'reference.fa':'>chr1\nAACCGTTAACGTTTGGCCAATGCA\n',
}
def checks():
    result=[]
    def add(identity,wf,bindings,expect,params=None):
        row={'id':identity,'workflow':wf,'inputs':{key:[{key:'fixture-'+name}] for key,name in bindings.items()},'expect':expect}
        if params:row['params']=params
        result.append(row)
    def bedexpect(count,text=None):
        out=[{'output':'summary','kind':'text','contains':['"records":'+str(count)+',']}]
        if text:out.append({'output':'result','kind':'text','contains':[text]})
        return out
    add('unique-overlaps','intersect',{'a':'a','b':'b'},bedexpect(2,'chr1\t0\t4\ta\t0\t+\nchr1\t4\t8\tb\t0\t-'))
    add('windows-crlf-bed','intersect',{'a':'crlf','b':'b'},bedexpect(2,'chr1\t0\t4\ta\t0\t+\nchr1\t4\t8\tb\t0\t-'))
    add('same-strand','intersect-stranded',{'a':'a','b':'strand'},bedexpect(1,'chr1\t0\t4\ta\t0\t+'))
    add('legitimate-empty-overlap','intersect',{'a':'a','b':'far'},bedexpect(0))
    add('large-64bit-coordinates','intersect',{'a':'large-a','b':'large-b'},bedexpect(1,'chrLarge\t3000000000\t3000000100'))
    add('large-coordinate-coverage','coverage',{'a':'large-a','b':'large-b'},[{'output':'result','kind':'text','contains':['chrLarge\t3000000000\t3000000100\t1\t50\t100\t0.5000000\nchrLarge\t4000000000\t4000000100\t0\t0\t100\t0.0000000']}])
    add('large-coordinate-sort-merge','merge',{'a':'large-a'},bedexpect(2,'chrLarge\t3000000000\t3000000100\nchrLarge\t4000000000\t4000000100'))
    add('no-overlap','nonoverlap',{'a':'a','b':'b'},bedexpect(1,'chr1\t10\t12\tc\t0\t+'))
    add('subtract-pieces','subtract',{'a':'a','b':'b'},bedexpect(3,'chr1\t0\t2\ta\t0\t+\nchr1\t6\t7\tb\t0\t-\nchr1\t10\t12\tc\t0\t+'))
    add('exact-coverage','coverage',{'a':'a','b':'b'},[{'output':'result','kind':'text','contains':['chr1\t0\t4\ta\t0\t+\t1\t2\t4\t0.5000000\nchr1\t4\t8\tb\t0\t-\t2\t3\t4\t0.7500000\nchr1\t10\t12\tc\t0\t+\t0\t0\t2\t0.0000000'] }])
    add('sort','sort',{'a':'unsorted'},bedexpect(3,FIXTURES['a.bed'].rstrip()))
    add('merge-adjacent','merge',{'a':'unsorted'},bedexpect(2,'chr1\t0\t8\nchr1\t10\t12'))
    add('merge-gap','merge',{'a':'unsorted'},bedexpect(1,'chr1\t0\t12'),{'distance':'2'})
    add('extract-forward','getfasta',{'a':'a','reference':'reference'},[{'output':'result','kind':'fasta','records':3,'sequences':{'chr1:0-4':'AACC','chr1:4-8':'GTTA','chr1:10-12':'GT'}}])
    add('extract-strands','getfasta-stranded',{'a':'a','reference':'reference'},[{'output':'result','kind':'fasta','records':3,'sequences':{'chr1:0-4(+)':'AACC','chr1:4-8(-)':'TAAC','chr1:10-12(+)':'GT'}}])
    return {'schema':1,'checks':result}

def build(destination,cache=DEFAULT_CACHE,toolchain=DEFAULT_TC):
    destination=Path(destination).resolve();cache=Path(cache).resolve();toolchain=Path(toolchain).resolve()
    if destination.exists() and any(destination.iterdir()):raise ValueError('Use a new or empty pack destination')
    for part in ('bin','fixtures','licenses'):(destination/part).mkdir(parents=True,exist_ok=True)
    record=json.loads((cache/'build-windows/build.json').read_text())
    if record['version']!=VERSION or record['platform']!='windows-x86_64':raise ValueError('Build identity differs')
    sections=[]
    def section(name,values):sections.append('['+name+']\n'+'\n'.join(str(k)+'='+str(v) for k,v in values.items() if k!='id')+'\n')
    sections.append('[pack]\nformat=2\nid=bedtools\nversion='+PACK_VERSION+'\nname=BEDTools genomic intervals\nplatform=windows-x86_64\ndescription=Local interval overlap, subtraction, coverage, sorting, merging and reference sequence extraction.\ncolor=#477F9E\n')
    for tool in ('bedtools','bedcheck'):
        src=cache/'build-windows'/(tool+'.exe')
        if sha(src)!=record['files'][src.name]['sha256']:raise ValueError('Binary changed since build')
        shutil.copy2(src,destination/'bin'/src.name);section('tool:'+tool,{'path':'bin/'+src.name,'version':VERSION if tool=='bedtools' else '1.0.0','sha256':sha(src)})
    for name,text in FIXTURES.items():(destination/'fixtures'/name).write_bytes(text.encode('utf-8'))
    workflows,schema=definitions()
    for name,value in [('workbench-schema.json',schema),('workbench-checks.json',checks())]:(destination/name).write_text(json.dumps(value,indent=2)+'\n')
    assets={'workbench-schema':'workbench-schema.json','workbench-checks':'workbench-checks.json'}
    assets.update({'fixture-'+name.split('.')[0]:'fixtures/'+name for name in FIXTURES})
    for identity,path in assets.items():section('asset:'+identity,{'path':path,'sha256':sha(destination/path)})
    for wf in workflows:
        section('workflow:'+wf['id'],{'name':wf['name'],'description':wf['description'],**{part:','.join(x['id'] for x in wf[part]) for part in ('inputs','outputs','steps')}})
        for part in ('input','output','step'):
            for item in wf[part+'s']:section(part+':'+wf['id']+':'+item['id'],item)
    (destination/'pack.ini').write_text('\n'.join(sections))
    for name,(url,checksum) in SOURCES.items():
        if sha(cache/name)!=checksum:raise ValueError('Source changed: '+name)
        shutil.copy2(cache/name,destination/'licenses'/name)
    for src,name in [(cache/'source-windows/LICENSE','BEDTools-LICENSE.txt'),(cache/'source-windows/src/utils/htslib/LICENSE','HTSlib-LICENSE.txt'),(cache/'zlib-1.3.2/README','zlib-README.txt'),(cache/'workbench1-windows.patch','workbench1.patch'),(ROOT/'scripts/build_bedtools_native.py','build_bedtools_native.py'),(ROOT/'scripts/prepare_bedtools_pack.py','prepare_bedtools_pack.py'),(ROOT/'tools/bedtools/windows_compat.h','windows_compat.h'),(ROOT/'tools/bedtools/bedcheck.cpp','bedcheck.cpp'),(toolchain/'LICENSE.TXT','LLVM-LICENSE.txt'),(ROOT/'LICENSE','Workbench-LICENSE.txt')]:shutil.copy2(src,destination/'licenses'/name)
    for src in (toolchain/'x86_64-w64-mingw32/share/mingw32').glob('COPYING*'):shutil.copy2(src,destination/'licenses'/src.name)
    (destination/'licenses/provenance.json').write_text(json.dumps({'schema':1,'pack':'bedtools','packVersion':PACK_VERSION,'minAppVersion':'0.6.0','nativeBuild':record,'windowsExecuted':False,'citation':CITATION,'supportedOperations':[x['id'] for x in workflows],'sourceNotes':'Complete pinned BEDTools source preserves embedded third-party notices and legacy file licence headers. Build omits optional bzip2/lzma codecs; supported pack inputs are BED and plain genomic FASTA only.','portNotes':['Upstream interval algorithms unchanged; bounded C library compatibility, binary I/O and integer-width fixes.','Initialize upstream flags and match new[] with delete[] to remove undefined behaviour.','BED validator restricts to consistent BED3 through BED6; stranded operations require explicit +/-.','Windows executable has no external private runtime DLL dependencies; analysis stays local.']},indent=2)+'\n')
    shutil.copy2(ROOT/'docs/BEDTOOLS-PACK.md',destination/'PACK-README.md')
    sys.path.insert(0,str(ROOT/'workspace'));from catalog import load_pack
    pack=load_pack(destination/'pack.ini');print(json.dumps({'pack':str(destination),'manifestSha256':sha(destination/'pack.ini'),'workflows':list(pack['workflows'])},indent=2));return destination
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--destination',type=Path,default=ROOT/'packs'/('bedtools-'+PACK_VERSION));p.add_argument('--cache',type=Path,default=DEFAULT_CACHE);p.add_argument('--toolchain',type=Path,default=DEFAULT_TC);a=p.parse_args();build(a.destination,a.cache,a.toolchain)
