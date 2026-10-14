#!/usr/bin/env python3
"""Build Bowtie 2's self-contained Windows pack from a verified offline cache."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from prepare_modular_packs import field,number,artifact,execute,workflow
from fetch_bowtie2_vendor import VERSION,COMMIT,GALAXY_COMMIT,ARTIFACTS,WINDOWS

PACK_VERSION='0.5.3'
PAIR_SHA='4f2dda7e26b5c115a7edee936a8a059eb55ece244931b2799a62cebfcd44ecd4'
FASTQ='FASTQ reads|*.fastq;*.fq;*.fastq.gz;*.fq.gz|All files|*.*'
FASTA='Uncompressed reference FASTA|*.fa;*.fasta;*.fna|All files|*.*'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def definitions():
    workflows=[];schemas={}
    for large in (False,True):
        suffix='l' if large else 's';extension='bt2l' if large else 'bt2'
        for paired in (False,True):
            identity=('paired-end' if paired else 'single-end')+('-large' if large else '')
            title=('Paired-end' if paired else 'Single-end')+' DNA alignment'+(' (large index)' if large else '')
            description=('Index a private reference copy and align '+('validated paired' if paired else 'single')+' Phred+33 reads with Bowtie 2. '
                         +('Use a 64-bit index, including references at or above 4 billion bases.' if large else 'Use a compact 32-bit index for references below 4 billion bases.')
                         +' Produce unsorted SAM with read groups; no duplicate marking or variant calling is performed.')
            reads=[field('reads1','Read 1' if paired else 'Reads',filter=FASTQ,help='Plain or gzip FASTQ with Phred+33 qualities. File paths must use ASCII characters and must not contain commas.')]
            if paired:
                reads.append(field('reads2','Read 2',filter=FASTQ,help='Matching mate file in the same record order; validated before indexing.',**{'different-from':'reads1'}))
            inputs=reads+[
                field('reference','Reference genome',filter=FASTA,help='Uncompressed nucleotide FASTA. A private copy is indexed in this run; the original file is unchanged.'),
                field('sample','Sample name','text',default='sample',constraint='identifier',help='SAM SM tag. Use the same sample identity across lanes from this sample.'),
                field('read-group','Read-group ID','text',default='lane1',constraint='identifier',help='SAM RG ID. Use a distinct identifier for each sequencing lane that will be merged.'),
                field('library','Library ID','text',default='library1',constraint='identifier',help='SAM LB tag; distinct preparations should have distinct library names.'),
                field('platform','Sequencing platform','choice',default='ILLUMINA',choices='ILLUMINA:Illumina|DNBSEQ:DNBSEQ|IONTORRENT:Ion Torrent',help='SAM PL tag. Choose from the sequencing metadata.'),
                field('preset','End-to-end search effort','choice',default='sensitive',choices='very-fast:Very fast|fast:Fast|sensitive:Sensitive|very-sensitive:Very sensitive',help='Bowtie 2 end-to-end presets. Higher sensitivity can require more compute. This is an unspliced DNA aligner.'),
                number('threads','Threads',2,1,64),number('seed','Random seed',42,0,2147483647,help='Deterministic tie-breaking seed. Input records and names also affect the pseudo-random choices.'),
            ]
            if paired:
                inputs += [field('orientation','Expected mate orientation','choice',default='fr',choices='fr:Forward-reverse|rf:Reverse-forward|ff:Forward-forward'),
                           number('min-insert','Minimum fragment length',0,0,1000000),
                           number('max-insert','Maximum fragment length',500,1,1000000,help='Must be at least the minimum. Bowtie 2 also permits discordant and single-mate fallback alignments when concordant alignment fails.')]
            outputs=[artifact('reference','Private reference copy','reference.fa',final=False)]
            index_ids=[]
            for number_text in ('1','2','3','4','rev.1','rev.2'):
                index_id='index-'+number_text.replace('.','-');index_ids.append(index_id)
                outputs.append(artifact(index_id,'Bowtie 2 index '+number_text,'reference-index.'+number_text+'.'+extension,final=False))
            outputs.append(artifact('sam','Read alignments (unsorted SAM)','alignment.sam'))
            steps=[]
            if paired:
                outputs.append(artifact('pair-check','Read-pair validation','read-pairs.json'))
                steps.append(execute('check-pairs','Validate paired FASTQ records','paircheck',['--reads1','{input:reads1}','--reads2','{input:reads2}'],stdout='pair-check'))
            steps += [dict(id='copy-reference',label='Copy reference into this run',kind='copy',source='{input:reference}',destination='reference'),
                      execute('index','Build '+('large' if large else 'small')+' Bowtie 2 index','build-'+suffix,
                              ['--wrapper','basic-0','--threads','{input:threads}','{output:reference}','{run}/reference-index'],produces=index_ids)]
            argv=['--wrapper','basic-0','--end-to-end','--{input:preset}','--phred33','--seed','{input:seed}','--reorder',
                  '-p','{input:threads}','--rg-id','{input:read-group}','--rg','SM:{input:sample}','--rg','LB:{input:library}',
                  '--rg','PL:{input:platform}','-x','{run}/reference-index']
            if paired:
                argv += ['-1','{input:reads1}','-2','{input:reads2}','-I','{input:min-insert}','-X','{input:max-insert}','--{input:orientation}']
            else: argv += ['-U','{input:reads1}']
            steps.append(execute('align','Align reads with Bowtie 2','align-'+suffix,argv,stdout='sam'))
            workflows.append(workflow(identity,title,description,inputs,outputs,steps))
            ports=[dict(id='reads',type='pair' if paired else 'reads',manifestInputs=['reads1','reads2'] if paired else ['reads1'],min=1,max=1),
                   dict(id='reference',type='reference',manifestInputs=['reference'],min=1,max=1,requiredState={'compression':'none'})]
            products=[dict(id='sam',type='sam',manifestOutputs=['sam'],state={'sort':'unsorted','pairing':'paired' if paired else 'single'}),
                      dict(id='reference',type='reference',manifestOutputs=['reference'],state={'compression':'none'}),
                      dict(id='index',label='Bowtie 2 '+('large' if large else 'small')+' index (six files)',type='index',manifestOutputs=index_ids,state={})]
            if paired: products.append(dict(id='pair-check',type='metrics',manifestOutputs=['pair-check'],state={}))
            methods=('A private copy of the reference was indexed with Bowtie 2 using '+('64-bit large' if large else '32-bit small')+' index files. '
                     +('Mate identifiers, counts and FASTQ structure were validated with paircheck. ' if paired else '')
                     +'Reads were aligned end to end with Bowtie 2, interpreting quality scores as Phred+33 and using the selected sensitivity preset and deterministic seed. '
                     +('The specified fragment bounds and orientation governed concordant pairing; Bowtie 2 discordant-pair and single-mate fallback were enabled. ' if paired else '')
                     +'At most one primary alignment was reported per read, with unmapped reads retained. SAM records include the selected sample, read group, library and sequencing-platform tags. Output order follows input order and is not coordinate sorted.')
            schemas[identity]=dict(ports=ports,outputs=products,methods=methods,pathPolicy={'asciiOnly':True,'forbiddenCharacters':[',']})
            if paired:
                schemas[identity]['parameterConstraints']=[{'left':'min-insert','operator':'<=','right':'max-insert'}]
    return workflows,dict(schema=1,category='Alignment',citations=[dict(text='Langmead B, Salzberg SL. Fast gapped-read alignment with Bowtie 2. Nature Methods 9, 357–359 (2012).',url='https://doi.org/10.1038/nmeth.1923')],workflows=schemas)


def write_fixtures(folder):
    folder.mkdir()
    rng=random.Random(853)
    reference=''.join(rng.choice('ACGT') for _ in range(900))
    rc=lambda value:value.translate(str.maketrans('ACGT','TGCA'))[::-1]
    (folder/'reference.fa').write_text('>chrTest\n'+reference+'\n')
    def fastq(name,seq): return '@'+name+'\n'+seq+'\n+\n'+'I'*len(seq)+'\n'
    (folder/'single.fastq').write_text(fastq('single1',reference[300:375])+fastq('single2',rc(reference[650:725]))+fastq('unmapped','C'*75))
    for mate in (1,2):
        records=[]
        for i,start in enumerate((100,400),1):
            seq=reference[start:start+75] if mate==1 else rc(reference[start+125:start+200])
            records.append(fastq('pair'+str(i)+'/'+str(mate),seq))
        (folder/('reads'+str(mate)+'.fastq')).write_text(''.join(records))


def checks():
    cases=[]
    for large in (False,True):
        for paired in (False,True):
            identity=('paired-end' if paired else 'single-end')+('-large' if large else '')
            inputs={'reads':[{'reads1':'check-read1','reads2':'check-read2'}] if paired else [{'reads1':'check-single'}],
                    'reference':[{'reference':'check-reference'}]}
            alignments=([{'name':'pair1','reference':'chrTest','position':101,'cigar':'75M','flag':99,'tags':{'RG':'validation'}},
                         {'name':'pair1','reference':'chrTest','position':226,'cigar':'75M','flag':147,'tags':{'RG':'validation'}}]
                        if paired else [{'name':'single1','reference':'chrTest','position':301,'cigar':'75M','flag':0,'tags':{'RG':'validation'}},
                                        {'name':'single2','reference':'chrTest','position':651,'cigar':'75M','flag':16,'tags':{'RG':'validation'}}])
            expected=dict(output='sam',kind='sam',records=4 if paired else 3,mapped=4 if paired else 2,paired=4 if paired else 0,
                          properPairs=4 if paired else 0,spliced=0,references={'chrTest':900},samples=['validation'],allReadGroups=True,alignments=alignments)
            cases.append(dict(id=identity,workflow=identity,params={'sample':'validation','read-group':'validation','library':'fixture','threads':1},inputs=inputs,expect=[expected]))
    return dict(schema=1,checks=cases)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor',type=Path,required=True)
    parser.add_argument('--destination',type=Path,default=ROOT/'packs'/('bowtie2-'+PACK_VERSION))
    args=parser.parse_args();vendor=args.vendor.resolve();destination=args.destination.resolve()
    for name,digest in WINDOWS.items():
        if sha(vendor/'windows-bin'/name)!=digest: raise ValueError('Executable checksum differs: '+name)
    for name,_,digest in ARTIFACTS:
        if name.endswith('.zip'):continue
        if sha(vendor/'licenses'/name)!=digest:raise ValueError('Source/license artifact checksum differs: '+name)
    if sha(ROOT/'baselines/bin/paircheck-cosmo.exe')!=PAIR_SHA:raise ValueError('Pair validator checksum differs')
    if destination.exists():
        if destination.name!='bowtie2-'+PACK_VERSION or not (destination/'pack.ini').is_file():raise ValueError('Refusing to replace an unrelated directory')
        shutil.rmtree(destination)
    (destination/'bin').mkdir(parents=True)
    shutil.copytree(vendor/'licenses',destination/'licenses')
    for name in WINDOWS:shutil.copy2(vendor/'windows-bin'/name,destination/'bin'/name)
    shutil.copy2(ROOT/'baselines/bin/paircheck-cosmo.exe',destination/'bin/paircheck.exe')
    shutil.copy2(ROOT/'tools/paircheck.c',destination/'licenses/paircheck.c')
    shutil.copy2(ROOT/'tools/build_paircheck.py',destination/'licenses/build_paircheck.py')
    shutil.copytree(ROOT/'packs/core-bio-0.2.0/licenses',destination/'licenses/paircheck-runtime')
    workflows,schema=definitions()
    (destination/'workbench-schema.json').write_text(json.dumps(schema,indent=2)+'\n')
    (destination/'workbench-checks.json').write_text(json.dumps(checks(),indent=2)+'\n')
    write_fixtures(destination/'fixtures')
    sections=['[pack]\nformat=2\nid=bowtie2\nversion='+PACK_VERSION+'\nname=Bowtie 2 DNA alignment\nplatform=windows-x86_64\ndescription=Reference indexing and short-read DNA alignment with explicit small/large index workflows.\ncolor=#4D78C7\n']
    def section(name,values):sections.append('['+name+']\n'+'\n'.join(k+'='+str(v) for k,v in values.items() if k!='id')+'\n')
    for name,digest in WINDOWS.items():section('tool:'+name.removeprefix('bowtie2-').removesuffix('.exe'),dict(path='bin/'+name,version=VERSION,sha256=digest))
    section('tool:paircheck',dict(path='bin/paircheck.exe',version='1.0.1',sha256=PAIR_SHA))
    assets={'workbench-schema':'workbench-schema.json','workbench-checks':'workbench-checks.json','check-reference':'fixtures/reference.fa',
            'check-single':'fixtures/single.fastq','check-read1':'fixtures/reads1.fastq','check-read2':'fixtures/reads2.fastq'}
    for key,path in assets.items():section('asset:'+key,dict(path=path,sha256=sha(destination/path)))
    for wf in workflows:
        section('workflow:'+wf['id'],dict(name=wf['name'],description=wf['description'],inputs=','.join(x['id'] for x in wf['inputs']),outputs=','.join(x['id'] for x in wf['outputs']),steps=','.join(x['id'] for x in wf['steps'])))
        for kind,plural in [('input','inputs'),('output','outputs'),('step','steps')]:
            for entry in wf[plural]:section(f'{kind}:{wf["id"]}:{entry["id"]}',entry)
    (destination/'pack.ini').write_text('\n'.join(sections),encoding='utf-8')
    (destination/'PACK-README.txt').write_text('Bowtie 2 DNA alignment — pack '+PACK_VERSION+' / upstream '+VERSION+'\n\n'
        'Requires Native Workbench 0.5.3 or newer. Four local workflows combine reference indexing with single-end or paired-end short-read DNA alignment. Small indexes support references below 4 billion bases; the separate large-index workflows use 64-bit indexes and can require more memory. Indexing occurs for every run. Existing indexes are not silently reused. This is not a splice-aware RNA aligner.\n\n'
        'The pack invokes official native Windows build/align executables directly; it does not run upstream Python wrappers, shell scripts, Docker, WSL or network clients. Executables import only Windows KERNEL32.dll and msvcrt.dll. Pack/input/output paths must contain ASCII characters and no commas because the native CLI uses comma-separated file lists and its Windows Unicode paths have not been verified. Spaces are supported through argument vectors.\n\n'
        'References must be uncompressed FASTA. Reads may be plain or gzip FASTQ, with Phred+33 qualities. Paired inputs must have matching names, counts and order; paircheck validates them before indexing. All inputs are unchanged. End-to-end alignment, input-order output, one primary alignment per read, unmapped records and Bowtie 2 default discordant/single-mate fallback are retained. Select the library orientation and fragment bounds from the experiment.\n\n'
        'SAM includes sample (SM), read-group (ID), library (LB) and platform (PL) tags. Use unique read-group IDs across lanes. SAM is unsorted and no duplicate marking is performed. Connect the SAM output to BAM preparation/sorting workflows before downstream steps that require prepared BAM. The copied reference and all six index files remain recorded as intermediate outputs.\n\n'
        'License: GPLv3 or later for Bowtie 2. Complete Bowtie 2 source, linked compression sources, upstream build instructions, GCC runtime exception, MinGW/winpthreads notices and existing paircheck/Cosmopolitan notices accompany the pack under licenses. Official binaries are unmodified. Their published archive SHA256 digests were verified. The upstream compiler/runtime details do not establish byte-reproducible builds; see licenses/provenance.json.\n\n'
        'Validation uses the exact manifest commands with the matching pinned Linux release binaries. Four included installation checks assert mapped positions, pair flags, reference dictionary and sample/read-group metadata on the user Windows computer. Windows execution has not been performed in this development environment.\n\n'
        'Upstream: https://github.com/BenLangmead/bowtie2/releases/tag/v2.5.5\n'
        'Galaxy guidance: https://github.com/galaxyproject/tools-iuc/tree/'+GALAXY_COMMIT+'/tools/bowtie2\n'
        'Citation: Langmead B, Salzberg SL (2012). Fast gapped-read alignment with Bowtie 2. Nature Methods 9:357–359. https://doi.org/10.1038/nmeth.1923\n',encoding='utf-8')
    entries=list(destination.rglob('*'));size=sum(p.stat().st_size for p in entries if p.is_file())
    if len(entries)>2000 or size>256*1024*1024:raise ValueError('Pack exceeds native import limits')
    print(json.dumps(dict(pack=str(destination),workflows=len(workflows),entries=len(entries),bytes=size,manifestSha256=sha(destination/'pack.ini'))))


if __name__=='__main__':main()
