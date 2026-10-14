#!/usr/bin/env python3
"""Stage align 0.4.1 from immutable Starter binaries and explicit new contracts.

The candidate is separate from the published align 0.4.0 pack and the official
32-pack setup profile. No source build or upstream algorithm change is involved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'workspace'))
sys.path.insert(0,str(ROOT/'scripts'))
from catalog import parse_pack, describe_workflow, load_pack
from package_split import build_pack, copy_tree, pack_inventory
from apply_core_update import ordinary_root

BASE_MANIFEST_SHA256='81c962222c93356a4f7727b23193c71d7dcd515859e62a179574781f411824d3'
VERSION='0.4.1'
MIN_APP_VERSION='0.13.0'


def check_assets():
    """One declared installation check; indexed DAG behavior has its own gate."""
    profile=json.loads((ROOT/'workspace/starter-check-profile.json').read_text())
    assets={}
    for field,name in (('reads1','reads1.fastq'),('reads2','reads2.fastq'),('reference','reference.fa')):
        raw=(ROOT/'examples/starter'/name).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=profile['fixtures'][name]:
            raise ValueError('The Starter scientific fixture differs from its published pin.')
        assets['fixture-'+field]=('fixtures/'+name,raw)
    check={'schema':1,'checks':[{'id':'paired-mapping-known-answer','workflow':'paired-end',
        'params':{'sample':'starter','threads':'2'},
        'inputs':{'reads':[{'reads1':'fixture-reads1','reads2':'fixture-reads2'}],
                  'reference':[{'reference':'fixture-reference'}]},
        'expect':[dict(profile['expect']['alignment'],output='sam',kind='sam')]}]}
    assets['workbench-checks']=('workbench-checks.json',(json.dumps(check,indent=2)+'\n').encode('utf-8'))
    return assets


def contracts(base_text):
    """Return deterministic manifest/schema for the pinned legacy operation set."""
    pack=parse_pack(base_text)
    if (pack['id'],pack['version'],set(pack['workflows']))!=('align','0.4.0',{'single-end','paired-end'}):
        raise ValueError('Expected the published align 0.4.0 operation set.')
    schema={'schema':1,'category':'Alignment','citations':[{
        'text':'Li H. (2018). Minimap2: pairwise alignment for nucleotide sequences. Bioinformatics 34:3094–3100.',
        'url':'https://doi.org/10.1093/bioinformatics/bty191'}],'workflows':{}}
    for name,workflow in pack['workflows'].items():
        data=describe_workflow(pack,workflow,'packs/align-0.4.0',BASE_MANIFEST_SHA256)
        schema['workflows'][name]={
            'ports':[{k:v for k,v in port.items() if k in {'id','label','type','accepts','manifestInputs','min','max','help','requiredState'}} for port in data['ports']],
            'outputs':[{k:v for k,v in output.items() if k in {'id','label','type','manifestOutputs','state','propagateStateFrom'}} for output in data['outputs']],
            'methods':workflow['description']}
    sections=re.split(r'(?=\[workflow:)',base_text)
    indexed=[]
    for block in sections[1:]:
        name=re.match(r'\[workflow:([^]]+)\]',block)[1]
        new_name=name+'-indexed'
        text=block.replace(':'+name+']',':'+new_name+']').replace(':'+name+':',':'+new_name+':')
        text=text.replace('reads1,reference,','reads1,index,').replace('reads2,reference,','reads2,index,')
        text=text.replace(':reference]',':index]').replace('{input:reference}','{input:index}')
        text=text.replace('name=Single-end alignment','name=Single-end alignment with verified index').replace('name=Paired-end alignment','name=Paired-end alignment with verified index')
        text=text.replace('label=Reference genome','label=Verified short-read reference index')
        text=text.replace('filter=Uncompressed FASTA reference|*.fa;*.fasta;*.fna|All files|*.*','filter=Minimap2 short-read index|*.mmi')
        text=text.replace('help=Uncompressed FASTA. Workflows that build an index copy this file into the run folder first.',
                          'help=Use Workflow mode and connect the output of Build short-read reference index. This operation requires that graph producer and cannot run alone with an arbitrary .mmi file. Its exact minimap2 version and short-read settings must match.')
        indexed.append(text)
        metadata=json.loads(json.dumps(schema['workflows'][name]))
        for port in metadata['ports']:
            if port['id']=='reference':
                port.update(id='index',label='Verified short-read reference index',type='minimap2-sr-index',
                            accepts=['minimap2-sr-index'],manifestInputs=['index'],
                            help='Use Workflow mode and connect the output of Build short-read reference index. This operation requires that graph producer and cannot run alone with an arbitrary .mmi file.')
        metadata['methods']='Short reads are mapped with minimap2 -a -x sr against the verified, explicitly connected short-read minimizer index. The index format and exact indexing/mapping executable identity are checked before use.'
        metadata['requiresReferenceIndex']={'format':'minimap2-sr-v1','tool':'minimap2','port':'index'}
        schema['workflows'][new_name]=metadata
    schema['workflows']['build-sr-index']={
        'ports':[{'id':'reference','type':'reference','manifestInputs':['reference'],'min':1,'max':1}],
        'outputs':[{'id':'index','label':'Verified short-read reference index','type':'minimap2-sr-index','manifestOutputs':['index']}],
        'methods':'This operation explicitly requests a reusable minimap2 -x sr minimizer index. The reference bytes, exact pack and executable, indexing arguments and parameter values identify the index. An existing complete matching index is verified and copied into this run; otherwise the declared indexing command builds it. Reuse does not rerun indexing.',
        'referenceIndex':{'format':'minimap2-sr-v1','tool':'minimap2','referencePort':'reference','outputPort':'index'}}
    builder='''
[workflow:build-sr-index]
name=Build short-read reference index
description=Build once and reuse a verified minimap2 short-read index. A complete matching local index is reused automatically after all file hashes are checked. Connect its output to an indexed alignment operation.
inputs=reference,threads
outputs=index
steps=build
[input:build-sr-index:reference]
label=Reference genome
type=file
filter=Uncompressed FASTA reference|*.fa;*.fasta;*.fna|All files|*.*
help=Uncompressed genomic FASTA. Exact reference content, indexing settings and minimap2 version define the reusable index.
[input:build-sr-index:threads]
label=Indexing threads
type=integer
default=2
min=1
max=16
[output:build-sr-index:index]
label=Verified short-read reference index
path=reference.mmi
final=true
nonempty=true
[step:build-sr-index:build]
label=Build minimap2 short-read minimizer index
kind=exec
tool=minimap2
produces=index
arg.0=-x
arg.1=sr
arg.2=-t
arg.3={input:threads}
arg.4=-d
arg.5={output:index}
arg.6={input:reference}
'''
    schema_bytes=(json.dumps(schema,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    manifest=base_text.replace('version=0.4.0\n','version='+VERSION+'\n',1)
    manifest+='\n\n'.join(['',*indexed,builder])
    manifest+='\n[asset:workbench-schema]\npath=workbench-schema.json\nsha256='+hashlib.sha256(schema_bytes).hexdigest()+'\n'
    for identity,(path,raw) in check_assets().items():
        manifest+='\n[asset:'+identity+']\npath='+path+'\nsha256='+hashlib.sha256(raw).hexdigest()+'\n'
    parse_pack(manifest)
    return manifest,schema_bytes


def stage(base_root,output_root):
    base_root=ordinary_root(base_root);output_root=Path(os.path.abspath(output_root))
    if any(p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()) for p in (output_root,*output_root.parents)):
        raise ValueError('Candidate staging must not use symbolic links or junctions.')
    base,_,_=pack_inventory(base_root)
    if base['manifestSha256']!=BASE_MANIFEST_SHA256:
        raise ValueError('The reusable-index candidate requires the immutable published align 0.4.0 pack.')
    if output_root.exists():
        raise ValueError('Candidate pack staging directory already exists.')
    manifest,schema=contracts((base_root/'pack.ini').read_text(encoding='utf-8'))
    copy_tree(base_root,output_root)
    (output_root/'pack.ini').write_text(manifest,encoding='utf-8',newline='\n')
    (output_root/'workbench-schema.json').write_bytes(schema)
    for path,raw in check_assets().values():
        destination=output_root/path;destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes(raw)
    (output_root/'PACK-README.md').write_text('''# minimap2 reusable short-read index candidate

Pack align 0.4.1 requires Native Workbench 0.13.0. It preserves the published
single-end and paired-end FASTA operations and adds an explicit index builder
and indexed variants. Build short-read reference index uses `minimap2 -x sr -d`.
Connect its verified output to an indexed alignment. Selecting the builder
requests verified reuse on later runs. Ordinary alignment is unchanged.

The store binds the exact reference SHA-256, pack manifest, minimap2 binary and
version, all indexing options, and a complete hashed file inventory. Raw external
`.mmi` files are not accepted. Different references, tools or options do not
silently reuse an older index. Corrupted or incomplete entries fail closed.
No index, reference, read file or diagnostic is uploaded. Cache storage can be
large; indexes are copied into results for independent result retention.

The .mmi format is specific to minimap2 and this short-read preset. It is not a
SAMtools .fai, BWA index or STAR genome directory. Upstream v2.28 documentation:
https://github.com/lh3/minimap2/blob/v2.28/README.md#general

The minimap2 and paircheck executable bytes, sources and licenses are inherited
unchanged from the pinned align 0.4.0 pack. Matching source recovery instructions
remain in the application source companion; the new recipe and contracts are
scripts/package_reusable_index.py and workspace/reference_indexes.py.

Check installation also runs the candidate pack's ordinary paired mapping with
the pinned synthetic Starter fixture and requires all 202 records to map as
proper pairs. That check exercises these exact binaries and ordinary mapping;
it does not claim to test an indexed graph or cache reuse. The separate native
candidate release gate tests indexed mapping and cache equivalence explicitly.
''',encoding='utf-8')
    pack=load_pack(output_root/'pack.ini')
    if pack['version']!=VERSION or len(pack['workflows'])!=5:
        raise ValueError('Candidate index operations were not staged correctly.')
    pack_inventory(output_root)
    return pack


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-pack-root',type=Path,required=True)
    parser.add_argument('--output-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--metadata',type=Path,required=True)
    args=parser.parse_args()
    if args.metadata.exists():
        parser.error('Metadata destination already exists.')
    stage(args.base_pack_root,args.output_root)
    metadata=build_pack(args.output_root,args.output,min_app_version=MIN_APP_VERSION)
    metadata['derivedFrom']={'id':'align','version':'0.4.0','manifestSha256':BASE_MANIFEST_SHA256}
    args.metadata.parent.mkdir(parents=True,exist_ok=True)
    args.metadata.write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(metadata,indent=2))


if __name__=='__main__':
    main()
