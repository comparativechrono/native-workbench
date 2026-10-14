#!/usr/bin/env python3
"""Prepare the local BLAST+ pack from the pinned, static-runtime Windows build.

Build with scripts/build_blast_windows.ps1 first. This preparation never downloads
data, changes global configuration, or bundles the unmodified upstream DLL build.
"""
import argparse
import hashlib
import json
from pathlib import Path
import random
import shutil
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))
from prepare_modular_packs import field, number, artifact, execute, workflow

PACK_VERSION = '1.0.0'
TOOL_VERSION = '2.17.0'
SOURCE_SHA = '502057a88e9990e34e62758be21ea474cc0ad68d6a63a2e37b2372af1e5ea147'
SQLITE_SHA = '1d3049dd0f830a025a53105fc79fd2ab9431aea99e137809d064d8ee8356b032'
LINUX_SHA = '3888112d8207831aa47371d93583c601f058f88b5db22dc782438b039a3a411b'
PROGRAMS = ('blastn', 'blastp', 'blastx', 'tblastn', 'makeblastdb', 'blast_formatter')
FIELDS = 'qseqid sseqid pident length mismatch gapopen qstart qend sstart send evalue bitscore qlen slen qframe sframe'
KINDS = {'nucl': 'fasta-nucleotide', 'prot': 'fasta-protein'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def choose(identity, label, default, values, help=''):
    return field(identity, label, 'choice', default=default, choices='|'.join(a+':'+b for a,b in values), help=help)


def definitions():
    workflows, metadata = [], {}
    for program, query, subject, description in (
        ('blastn','nucl','nucl','Search nucleotide queries against a local nucleotide FASTA database.'),
        ('blastp','prot','prot','Search protein queries against a local protein FASTA database.'),
        ('blastx','nucl','prot','Translate nucleotide queries in six frames and search a local protein FASTA database.'),
        ('tblastn','prot','nucl','Search protein queries against a local nucleotide database translated in six frames.'),
    ):
        inputs=[]; ports=[]
        for identity,kind,label in [('query',query,'Query sequences'),('subjects',subject,'Database sequences')]:
            inputs.append(field(identity,label+(' (nucleotide FASTA)' if kind=='nucl' else ' (protein FASTA)'),
                filter='Uncompressed FASTA|*.fa;*.fasta;*.fna;*.faa|All files|*.*',
                help='Local, uncompressed and unaligned FASTA. Unique IDs: ASCII letters, digits, underscore, dot, colon or hyphen (up to 200 characters); no pipes. No database is downloaded.'))
            ports.append(dict(id=identity,type=KINDS[kind],accepts=[KINDS[kind]]+(['reference'] if kind=='nucl' else []),
                manifestInputs=[identity],min=1,max=1,requiredState={'compression':'none'}))
        inputs.extend([
            choose('evalue','Maximum E-value','1e-5',[(v,v) for v in ('1e-50','1e-20','1e-10','1e-5','1e-3','0.01','0.1','1','10')],
                   'Expected chance matches depend on the supplied database size; similarity alone is not functional annotation.'),
            number('targets','Maximum target sequences',500,1,50000,help='BLAST retention cap, not an exhaustive best-hit guarantee. Tied hits can depend on database order.'),
            number('threads','Threads',2,1,64,help='Worker limit; indexing and formatting are separate steps.')])
        search_args=['run',program,'-query','{input:query}','-db','blast-database','-evalue','{input:evalue}',
                     '-max_target_seqs','{input:targets}','-num_threads','{input:threads}','-outfmt','11','-out','{output:archive}']
        if program=='blastn':
            inputs.append(choose('task','Nucleotide search task','blastn',
                [('blastn','BLASTN: general nucleotide similarity'),('megablast','Megablast: closely related sequences'),('blastn-short','BLASTN short: queries under 50 bases')],
                'Task controls upstream word/scoring defaults. Both strands are searched; DUST masking remains enabled.'))
            search_args.extend(['-task','{input:task}','-strand','both','-dust','yes'])
        else:
            search_args.extend(['-seg','yes'])
            if program=='blastp': search_args.extend(['-task','blastp'])
        if program in ('blastx','tblastn'):
            inputs.append(choose('genetic-code','Genetic code','1',[(v,t) for v,t in [('1','Standard (1)'),('2','Vertebrate mitochondrial (2)'),('4','Mold / Mycoplasma (4)'),('5','Invertebrate mitochondrial (5)'),('11','Bacterial / archaeal / plastid (11)')]],
                'Select from the biology of the nucleotide sequences. This is not inferred.'))
            search_args.extend(['-query_gencode' if program=='blastx' else '-db_gencode','{input:genetic-code}'])
        outputs=[artifact('query-validation','Query FASTA validation','query-validation.json'),
                 artifact('database-validation','Database FASTA validation','database-validation.json'),
                 artifact('index-log','Database build log','database-build.log'),
                 artifact('archive','BLAST ASN.1 archive','search.asn'),
                 artifact('hits','BLAST hits (16 columns)','hits.tsv',nonempty=False),
                 artifact('report','BLAST search report with column headings','search-report.txt')]
        steps=[execute('validate-query','Validate every query FASTA record','guard',['validate',query,'{input:query}','{output:query-validation}'],produces=['query-validation']),
               execute('validate-database','Validate every database FASTA record','guard',['validate',subject,'{input:subjects}','{output:database-validation}'],produces=['database-validation']),
               execute('index','Build a private local BLAST database','guard',['run','makeblastdb','-in','{input:subjects}','-input_type','fasta','-dbtype',subject,'-parse_seqids','-blastdb_version','4','-title','Workbench local FASTA database','-out','blast-database','-logfile','{output:index-log}'],produces=['index-log']),
               execute('search','Search the local database','guard',search_args,produces=['archive']),
               execute('tabulate','Export tab-separated hits','guard',['run','blast_formatter','-archive','{output:archive}','-outfmt','6 '+FIELDS,'-out','{output:hits}'],produces=['hits']),
               execute('report','Export labelled BLAST report','guard',['run','blast_formatter','-archive','{output:archive}','-outfmt','7 '+FIELDS,'-out','{output:report}'],produces=['report'])]
        workflows.append(workflow(program,'BLAST+: '+program,description+' A new private database is built for each run; inputs remain unchanged.',inputs,outputs,steps))
        metadata[program]=dict(ports=ports,outputs=[dict(id=o['id'],type='file' if o['id']=='archive' else 'metrics' if o['id']!='report' else 'text',manifestOutputs=[o['id']],state={}) for o in outputs],
            methods=f'FASTA record structure, unique identifiers and {query}/{subject} alphabets were checked, and a private version-4 BLAST database was built from the supplied local database sequences with makeblastdb and parsed sequence identifiers. NCBI BLAST+ {program} searched that database with the recorded E-value, target cap, task/genetic-code choices and thread setting. '+
                ('Both nucleotide strands were searched with DUST masking.' if program=='blastn' else 'SEG low-complexity masking was enabled; upstream BLOSUM62, composition-based statistics and gap defaults were retained.')+
                ' Results were retained as ASN.1 search archives and 16-column tabular hits, including one-based inclusive alignment coordinates and query/subject frames. No hits is a valid result. BLAST usage reporting and user/global NCBI configuration were disabled; no remote search or automatic database download was used.')
    return workflows,dict(schema=1,category='Sequence similarity',citations=[dict(text='Camacho C et al. (2009). BLAST+: architecture and applications. BMC Bioinformatics 10:421.',url='https://doi.org/10.1186/1471-2105-10-421')],workflows=metadata)


def fixtures():
    rng=random.Random(471923)
    dna=''.join(rng.choice('ACGT') for _ in range(240))
    protein=''.join(rng.choice('ACDEFGHIKLMNPQRSTVWY') for _ in range(80))
    codons=dict(zip('ACDEFGHIKLMNPQRSTVWY',['GCT','TGT','GAT','GAA','TTT','GGT','CAT','ATT','AAA','CTG','ATG','AAT','CCT','CAA','CGT','TCT','ACT','GTT','TGG','TAT']))
    coding=''.join(codons[a] for a in protein)
    return {'nucl-query.fa':'>nq\n'+dna[80:200]+'\n','nucl-db.fa':'>ns\n'+dna+'\n',
            'protein-query.fa':'>pq\n'+protein[10:60]+'\n','protein-db.fa':'>ps\n'+protein+'\n',
            'translated-query.fa':'>xq\n'+coding[30:180]+'\n','translated-db.fa':'>xs\n'+coding+'\n',
            'no-hit.fa':'>absent\n'+'N'*120+'\n'}


def checks():
    cases=[]
    for name,q,s,needle in [('blastn','nucl-query.fa','nucl-db.fa','nq\tns\t100.000\t120\t0\t0\t1\t120\t81\t200\t'),
                          ('blastp','protein-query.fa','protein-db.fa','pq\tps\t100.000\t50\t0\t0\t1\t50\t11\t60\t'),
                          ('blastx','translated-query.fa','protein-db.fa','xq\tps\t100.000\t50\t0\t0\t1\t150\t11\t60\t'),
                          ('tblastn','protein-query.fa','translated-db.fa','pq\txs\t100.000\t50\t0\t0\t1\t50\t31\t180\t')]:
        cases.append(dict(id=name+'-known-coordinates',workflow=name,params={},
            inputs={'query':[{'query':'fixture-'+q.replace('.','-')}],'subjects':[{'subjects':'fixture-'+s.replace('.','-')}]},
            expect=[dict(output='hits',kind='text',contains=[needle]),dict(output='report',kind='text',contains=['# Fields:','# BLAST processed 1 queries'])]))
    cases.append(dict(id='no-hit-is-valid',workflow='blastn',params={},inputs={'query':[{'query':'fixture-no-hit-fa'}],'subjects':[{'subjects':'fixture-nucl-db-fa'}]},
        expect=[dict(output='report',kind='text',contains=['# 0 hits found','# BLAST processed 1 queries'])]))
    return dict(schema=1,checks=cases)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-build',type=Path,required=True)
    parser.add_argument('--destination',type=Path,default=ROOT/'packs'/('blast-'+PACK_VERSION))
    args=parser.parse_args(); vendor=args.native_build.resolve(); destination=args.destination.resolve()
    record=json.loads((vendor/'build-provenance.json').read_text(encoding='utf-8-sig'))
    if record['sourceSha256']!=SOURCE_SHA or record['sqliteSha256']!=SQLITE_SHA or record.get('sourcePatched') is not True:
        raise ValueError('Native build does not match the reviewed source inputs')
    if record.get('patchSha256')!=sha(ROOT/'tools/blast/makeblastdb-space-path.patch'):
        raise ValueError('Native build does not have the reviewed path compatibility patch')
    if (record.get('patchedSourceBeforeSha256'),record.get('patchedSourceAfterSha256'))!=('b555dc444f7da23b4ee2566908e7cf9922644e8f8bac87a1f6a0c5a298e78ab4','c65d73d28f92eda26d20efd658e409990d23531e719284ef3dce60688231d4a4'):
        raise ValueError('Native build source patch hashes differ')
    offline=record.get('offlinePatches',{})
    if offline.get('patchSha256')!=sha(ROOT/'tools/blast/local-only.patch') or offline.get('files')!=[
        dict(path='c++/src/app/blast/blast_formatter.cpp',beforeSha256='17c2e8f4b2fc0813ac4d8ea4a6589d46f42b44b5e607de49b0be77d2d9be518f',afterSha256='00256274213373cd8f27616c21cd04d6313a6aec646ecb63cbd3b4347424cfac'),
        dict(path='c++/src/algo/blast/blastinput/blast_scope_src.cpp',beforeSha256='b040a3dc5e7fa8be0236f5e0598d50d24db9cd28508affb1a3d2e1a778b79c1e',afterSha256='7036efe9edbff9a306b20b7a560c099cc8eae686d03d71899a9ae3a0778db5aa')]:
        raise ValueError('Native build must include the exact reviewed offline boundary changes')
    adapter_record=None
    if (vendor/'adapter-provenance.json').is_file():
        adapter_record=json.loads((vendor/'adapter-provenance.json').read_text(encoding='utf-8-sig'))
        if (adapter_record.get('kind')!='adapter-only-rebuild' or
            adapter_record.get('parentBuildRecordSha256')!=sha(vendor/'build-provenance.json') or
            adapter_record.get('originalAdapterSha256')!=record['adapterSha256'] or
            adapter_record.get('unchangedScientificExecutables')!=record['binaries']):
            raise ValueError('Adapter-only rebuild is not bound to the unchanged scientific build')
    adapter_source_sha=adapter_record['sourceSha256'] if adapter_record else record['adapterSourceSha256']
    adapter_binary_sha=adapter_record['sha256'] if adapter_record else record['adapterSha256']
    if adapter_source_sha!=sha(ROOT/'tools/blast/guard.cpp'):
        raise ValueError('Adapter source has changed since the native build')
    for source,digest in [('source.tar.gz',SOURCE_SHA),('sqlite.zip',SQLITE_SHA)]:
        if sha(vendor/source)!=digest: raise ValueError('Source hash mismatch: '+source)
    expected={x['name']:x['sha256'] for x in record['binaries']}
    expected['blast-guard.exe']=adapter_binary_sha
    for name,digest in expected.items():
        if sha(vendor/'bin'/name)!=digest: raise ValueError('Native binary hash mismatch: '+name)
    if set(expected)!=set(p+'.exe' for p in PROGRAMS)|{'blast-guard.exe'}: raise ValueError('Incorrect native program set')
    if destination.exists() and any(destination.iterdir()): raise ValueError('Destination must be new or empty')
    (destination/'bin').mkdir(parents=True,exist_ok=True)
    for name in expected: shutil.copy2(vendor/'bin'/name,destination/'bin'/name)
    licenses=destination/'licenses';licenses.mkdir()
    shutil.copy2(vendor/'source.tar.gz',licenses/'ncbi-blast-2.17.0-source.tar.gz')
    shutil.copy2(vendor/'sqlite.zip',licenses/'sqlite-3.50.4-source.zip')
    shutil.copy2(ROOT/'tools/blast/guard.cpp',licenses/'workbench-blast-guard.cpp')
    shutil.copy2(ROOT/'tools/blast/makeblastdb-space-path.patch',licenses/'makeblastdb-space-path.patch')
    shutil.copy2(ROOT/'tools/blast/local-only.patch',licenses/'local-only.patch')
    shutil.copy2(ROOT/'tools/blast/apply_local_only_patch.py',licenses/'apply_local_only_patch.py')
    shutil.copy2(ROOT/'scripts/build_blast_windows.ps1',licenses/'build_blast_windows.ps1')
    shutil.copy2(ROOT/'LICENSE',licenses/'WORKBENCH-LICENSE.txt')
    shutil.copy2(vendor/'build-provenance.json',licenses/'build-provenance.json')
    if adapter_record:
        shutil.copy2(vendor/'adapter-provenance.json',licenses/'adapter-provenance.json')
        shutil.copy2(ROOT/'.github/workflows/blast-adapter-rebuild.yml',licenses/'blast-adapter-rebuild.yml')
    # Retain shallow copies of source licences, with immutable source archives
    # for full context and notices in source-file headers.
    with tarfile.open(vendor/'source.tar.gz','r:gz') as archive:
        for identity,path in [('NCBI-LICENSE.txt','c++/scripts/projects/blast/LICENSE'),('LMDB-LICENSE.txt','c++/src/util/lmdb/LICENSE'),('LMDB-COPYRIGHT.txt','c++/src/util/lmdb/COPYRIGHT'),('BZIP2-LICENSE.txt','c++/src/util/compress/bzip2/LICENSE'),('ZLIB-LICENSE.txt','c++/src/util/compress/zlib_cloudflare/LICENSE'),('PCRE-LICENSE.txt','c++/src/util/regexp/COPYING')]:
            member=next((x for x in archive.getmembers() if x.name.endswith('/'+path)),None)
            if member: (licenses/identity).write_bytes(archive.extractfile(member).read())
        for identity,path in [('ZLIB-HEADER-NOTICE.txt','c++/include/util/compress/zlib/zlib.h'),('PCRE2-HEADER-NOTICE.txt','c++/src/util/regexp/pcre2_compile.c'),('PCRE2-JIT-HEADER-NOTICE.txt','c++/src/util/regexp/pcre2_jit_compile.c')]:
            member=next(x for x in archive.getmembers() if x.name.endswith('/'+path))
            # The leading comment may be a short title; retain all leading
            # comment blocks until the first source preprocessor directive.
            content=archive.extractfile(member).read().decode('utf-8')
            (licenses/identity).write_text(content.split('\n#',1)[0]+'\n',encoding='utf-8')
    with zipfile.ZipFile(vendor/'sqlite.zip') as archive:
        source=archive.read('sqlite-amalgamation-3500400/sqlite3.c').decode('utf-8')
        (licenses/'SQLITE-NOTICE.txt').write_text(source.split('*/',1)[0]+'*/\n',encoding='utf-8')
    (licenses/'WORKBENCH-GUARD-NOTICE.txt').write_text('Workbench BLAST boundary adapter source is distributed with this repository under its project licence. It validates input and launches unchanged upstream scientific programs. Microsoft runtime code is statically linked by a licensed Visual Studio build environment; no separately sourced MSVC runtime DLLs are redistributed.\n',encoding='utf-8')
    workflows,schema=definitions()
    (destination/'workbench-schema.json').write_text(json.dumps(schema,indent=2)+'\n',encoding='utf-8')
    (destination/'workbench-checks.json').write_text(json.dumps(checks(),indent=2)+'\n',encoding='utf-8')
    (destination/'fixtures').mkdir()
    for name,data in fixtures().items(): (destination/'fixtures'/name).write_text(data,encoding='ascii')
    sections=[]
    def section(name,data): sections.append('['+name+']\n'+'\n'.join(k+'='+str(v) for k,v in data.items() if k!='id')+'\n')
    section('pack',dict(format=2,id='blast',version=PACK_VERSION,name='NCBI BLAST+ local similarity',platform='windows-x86_64',description='Local nucleotide, protein and translated similarity search with private databases.',color='#256F86'))
    # id is excluded for ordinary records, but required in the pack envelope.
    sections[0]=sections[0].replace('format=2\n','format=2\nid=blast\n')
    for program in PROGRAMS: section('tool:'+program.replace('_','-'),dict(path='bin/'+program+'.exe',version=TOOL_VERSION,sha256=expected[program+'.exe']))
    section('tool:guard',dict(path='bin/blast-guard.exe',version='1.0.0',sha256=expected['blast-guard.exe']))
    for identity,path in [('workbench-schema','workbench-schema.json'),('workbench-checks','workbench-checks.json')]+[('fixture-'+name.replace('.','-'),'fixtures/'+name) for name in fixtures()]:
        section('asset:'+identity,dict(path=path,sha256=sha(destination/path)))
    for item in workflows:
        section('workflow:'+item['id'],dict(name=item['name'],description=item['description'],inputs=','.join(x['id'] for x in item['inputs']),outputs=','.join(x['id'] for x in item['outputs']),steps=','.join(x['id'] for x in item['steps'])))
        for singular,plural in [('input','inputs'),('output','outputs'),('step','steps')]:
            for value in item[plural]:section(f'{singular}:{item["id"]}:{value["id"]}',value)
    (destination/'pack.ini').write_text('\n'.join(sections),encoding='utf-8')
    shutil.copy2(ROOT/'docs/BLAST-PACK.md',destination/'PACK-README.md')
    print(json.dumps(dict(pack=str(destination),workflows=len(workflows),checks=len(checks()['checks']),manifestSha256=sha(destination/'pack.ini'))))


if __name__=='__main__': main()
