"""Strict pack-manifest catalogue for the local graph workspace.

The manifest remains the execution authority. This module adds conservative port
semantics and presents every declared workflow without creating command strings.
New steps use the highest compatible installed pack. Saved steps resolve their
exact pack version and manifest hash from the complete installed registry.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

try:
    from .app_version import APP_VERSION, PACK_API
except ImportError:
    from app_version import APP_VERSION, PACK_API

SCHEMA = 1
TYPES = {
    'pair': 'Paired FASTQ reads', 'reads': 'FASTQ reads',
    'reference': 'Reference FASTA', 'sam': 'SAM alignments', 'bam': 'BAM alignments',
    'sam-rna': 'RNA alignments (SAM)', 'bam-rna': 'RNA alignments (BAM)',
    'bed': 'Genomic intervals (BED)',
    'vcf': 'Variant calls (VCF)', 'vcf-pass': 'PASS variant calls (VCF)',
    'bcf': 'Variant calls (BCF)', 'bcf-likelihoods': 'Genotype likelihoods (BCF)',
    'metrics': 'Statistics or quality metrics', 'report': 'HTML report',
    'index': 'Index file', 'minimap2-sr-index': 'Verified minimap2 short-read index',
    'text': 'Text file', 'file': 'Other file',
    'directory': 'Folder', 'script': 'Report supporting asset',
    'fasta-nucleotide': 'Nucleotide sequences (FASTA)',
    'fasta-protein': 'Protein sequences (FASTA)',
    'msa-nucleotide': 'Aligned nucleotide sequences (FASTA)',
    'msa-protein': 'Aligned protein sequences (FASTA)',
    'fasta-nucleotide-abundance': 'Nucleotide FASTA with abundance counts',
    'id-list': 'Sequence identifiers (one per line)',
    'cluster-membership': 'Sequence cluster membership (UC)',
}
CATEGORIES = {
    'reads': 'Read quality', 'align': 'Alignment', 'bwa': 'Alignment',
    'bam': 'Alignment processing', 'trimming': 'Trimming', 'fastp': 'Trimming',
    'variants': 'Variant calling', 'freebayes': 'Variant calling',
    'variant-pipeline': 'Complete pipelines', 'research-variants': 'Complete pipelines',
}
ID = re.compile(r'[a-z](?:[a-z0-9-]{0,46}[a-z0-9])?\Z')
VERSION = re.compile(r'(?:0|[1-9][0-9]{0,8})\.(?:0|[1-9][0-9]{0,8})\.(?:0|[1-9][0-9]{0,8})\Z')
SHA = re.compile(r'[0-9a-f]{64}\Z')
PARAM_TYPES = {'integer', 'choice', 'text', 'boolean'}
FILE_TYPES = {'file', 'files', 'directory'}
RESERVED = {'con', 'prn', 'aux', 'nul', 'conin$', 'conout$'} | {f'{p}{n}' for p in ('com','lpt') for n in '123456789¹²³'}


class CatalogError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise CatalogError(message)


def _keys(fields, allowed, context, arguments=False):
    for key in fields:
        require(key in allowed or (arguments and re.fullmatch(r'(?:sink-)?arg\.(?:0|[1-9][0-9]{0,2})', key)),
                f'{context}: unknown key {key!r}')


def _clean(value, length, empty=False):
    return isinstance(value, str) and (empty or bool(value)) and len(value) <= length and all(ord(c) >= 32 and ord(c) != 127 for c in value)


def _bool(value):
    require(value in ('true','false'), 'Boolean must be true or false')
    return value == 'true'


def _integer(value):
    require(re.fullmatch(r'-?[0-9]{1,19}', value) is not None, 'Invalid integer')
    n = int(value)
    require(-(2**63) <= n < 2**63, 'Integer outside signed 64-bit range')
    return n


def _ids(value, maximum, empty=False):
    ids = [x.strip() for x in value.split(',')] if value else []
    require((empty or ids) and len(ids) <= maximum and len(set(ids)) == len(ids), 'Missing, duplicate, or too many IDs')
    require(all(ID.fullmatch(x) for x in ids), 'Invalid manifest identifier')
    return ids


def _relative(value):
    value = value.replace('\\','/')
    require(0 < len(value) <= 240, 'Empty or overlong relative path')
    parts = value.split('/')
    require(len(parts) <= 12, 'Relative path nested too deeply')
    for part in parts:
        require(_clean(part,180) and part not in ('.','..') and part[-1] not in '. ' and not any(c in part for c in '\\/:<>"|?*{}'), 'Unsafe relative path')
        require(part.split('.')[0].lower() not in RESERVED, 'Reserved Windows path')
    return value


def _sections(text):
    require(len(text) <= 2*1024*1024 and '\0' not in text, 'Manifest is overlong or contains NUL')
    sections, current = {}, None
    for line in text.lstrip('\ufeff').split('\n'):
        if line.endswith('\r'): line = line[:-1]
        require(len(line) <= 8192 and all(ord(c) >= 32 or c == '\t' for c in line), 'Overlong manifest line or control character')
        line = line.strip(' \t')
        if not line or line.startswith(('#',';')):
            continue
        if line.startswith('[') and line.endswith(']'):
            name = line[1:-1]
            require(name and name not in sections and len(sections) < 10000, 'Duplicate, empty, or excessive section')
            current = sections[name] = {}
        else:
            require(current is not None and '=' in line, 'Expected a section and key=value')
            key, value = (s.strip(' \t') for s in line.split('=',1))
            require(key and key not in current and len(current) < 288, 'Duplicate, empty, or excessive key')
            current[key] = value
    return sections


def _input(identifier, fields):
    _keys(fields, {'label','type','help','filter','default','required','min','max','choices','constraint','different-from'}, 'input')
    kind = fields.get('type','file')
    require(kind in PARAM_TYPES | FILE_TYPES, 'Unknown input type')
    item = {'id':identifier, 'label':fields['label'], 'type':kind,
            'role':{'reads1':'read1','reads2':'read2'}.get(identifier,'file' if kind in FILE_TYPES else 'parameter'),
            'binding':identifier in {'sample','library','read-group','platform-unit'},
            'preset':identifier not in {'sample','library','read-group','platform-unit'},
            'required':_bool(fields.get('required','true')), 'default':fields.get('default',''),
            'help':fields.get('help',''), 'filter':fields.get('filter','All files|*.*'),
            'constraint':fields.get('constraint',''), 'differentFrom':fields.get('different-from','')}
    require(_clean(item['label'],100) and _clean(item['help'],2048,True) and _clean(item['default'],4096,True), 'Invalid input text')
    filters = item['filter'].split('|')
    require(0 < len(filters) <= 32 and len(filters)%2 == 0 and all(filters), 'Invalid file filter pairs')
    require('filter' not in fields or kind in ('file','files'), 'Only file inputs support filters')
    if kind == 'integer':
        item['min'], item['max'] = _integer(fields.get('min','0')), _integer(fields.get('max','2147483647'))
        require(item['min'] <= item['max'], 'Invalid integer range')
        if item['default']:
            require(item['min'] <= _integer(item['default']) <= item['max'], 'Integer default outside range')
    else:
        require('min' not in fields and 'max' not in fields, 'Range on noninteger input')
    if kind == 'choice':
        values = []
        for choice in fields['choices'].split('|'):
            require(':' in choice, 'Choice requires value:Label')
            value,label = choice.split(':',1)
            require(_clean(value,128) and _clean(label,100) and not any(c in value for c in '{}') and value not in values, 'Invalid choice')
            values.append(value)
            item.setdefault('choices',[]).append({'value':value,'label':label})
        require(len(values) <= 64 and (not item['default'] or item['default'] in values), 'Invalid choice default')
    else:
        require('choices' not in fields, 'Choices on nonchoice input')
    if kind == 'boolean':
        item['default'] = item['default'] or 'false'
        _bool(item['default'])
    if 'constraint' in fields:
        require(kind == 'text' and item['constraint'] in ('identifier','dna'), 'Invalid text constraint')
        if item['default'] or (item['constraint']=='dna' and 'default' in fields):
            _validate_text(item['constraint'], item['default'])
    if 'different-from' in fields:
        require(kind == 'file' and ID.fullmatch(item['differentFrom']), 'Invalid different-from')
    return item


def _validate_text(constraint, value):
    if constraint == 'identifier':
        require(re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',value), 'Identifier requires 1–64 ASCII letters, digits, dots, underscores, or hyphens')
    elif constraint == 'dna':
        require(re.fullmatch(r'[ACGTRYSWKMBDHVNacgtryswkmbdhvn]{1,4096}',value), 'DNA requires 1–4096 IUPAC letters')


def validate_parameter(param, value):
    """Return a manifest-safe scalar string, preserving actual user choices."""
    require(isinstance(value,(str,int,bool)) and not isinstance(value,float), f'{param["label"]}: invalid value')
    value = ('true' if value else 'false') if isinstance(value,bool) else str(value)
    require(_clean(value,4096,not param['required']), f'{param["label"]}: missing or invalid text')
    if not value and not param['required']:
        return value
    if param['type'] == 'integer':
        require(param['min'] <= _integer(value) <= param['max'], f'{param["label"]}: outside allowed range')
    elif param['type'] == 'choice':
        require(value in [x['value'] for x in param['choices']], f'{param["label"]}: unknown choice')
    elif param['type'] == 'boolean':
        _bool(value)
    _validate_text(param.get('constraint',''),value)
    return value


def _args(fields, prefix):
    found = {int(k[len(prefix):]):v for k,v in fields.items() if k.startswith(prefix)}
    require(len(found) <= 128 and set(found) == set(range(len(found))), 'Argument numbering contains a gap')
    require(all(_clean(v,4096,True) for v in found.values()), 'Invalid argument')
    return [found[i] for i in range(len(found))]


def _placeholders(value):
    result, pos = [], 0
    while True:
        opens = [i for i in (value.find('{',pos),value.find('}',pos)) if i >= 0]
        if not opens:
            return result
        start = min(opens)
        require(value[start]=='{', 'Unmatched placeholder brace')
        end = value.find('}',start+1)
        require(end >= 0, 'Unclosed placeholder')
        body = value[start+1:end]
        if body == 'run':
            kind,identifier = 'run',''
        else:
            require(':' in body, 'Unknown placeholder')
            kind,identifier = body.split(':',1)
            require(kind in ('input','inputs','output','asset') and ID.fullmatch(identifier), 'Unknown or malformed placeholder')
            require(kind != 'inputs' or (start==0 and end+1==len(value)), 'A file-list placeholder must occupy its argument')
        result.append((kind,identifier))
        pos = end+1


def _validate_workflow(workflow, executables, assets):
    inputs = {x['id']:x for x in workflow['inputs']}
    outputs = {x['id']:x for x in workflow['outputs']}
    paths = set()
    for item in inputs.values():
        other = item.get('differentFrom')
        if other:
            require(other in inputs and other != item['id'] and inputs[other]['type']=='file', 'Unknown different-from file')
    for item in outputs.values():
        path = item['path'].lower()
        require(all(32<=ord(c)<=126 for c in path), 'Output paths must use printable ASCII')
        require(path.split('/')[0] not in {'run.json','run.json.pending','workbench.log','workbench.log.pending','logs'}, 'Output collides with workbench metadata')
        require(not any(path == old or path.startswith(old+'/') or old.startswith(path+'/') for old in paths), 'Output paths collide')
        paths.add(path)
    available = set()
    for step in workflow['steps']:
        produced = ([step['destination']] if step['kind']=='copy' else ([step['stdout']] if step.get('stdout') else [])+step['produces'])
        require(len(produced)==len(set(produced)) and all(x in outputs and x not in available for x in produced), 'Unknown or duplicate output producer')
        if step['kind'] != 'copy':
            require(step['tool'] in executables and (step['kind'] != 'pipe' or step['sinkTool'] in executables), 'Unknown executable')
        for value in ([step['source']] if step['kind']=='copy' else step['args']+step.get('sinkArgs',[])):
            refs = _placeholders(value)
            if step['kind']=='copy':
                require(len(refs)==1 and refs[0][0] in ('input','output','asset') and value=='{'+':'.join(refs[0])+'}', 'Copy must use one input, output or asset placeholder')
            for kind,identifier in refs:
                if kind in ('input','inputs'):
                    require(identifier in inputs and (kind=='inputs')==(inputs[identifier]['type']=='files'), 'Unknown input or incorrect file-list placeholder')
                    require(step['kind'] != 'copy' or inputs[identifier]['type']=='file','Copy input must be a file')
                elif kind=='asset':
                    require(identifier in assets, 'Unknown asset')
                elif kind=='output':
                    require(identifier in available or (step['kind']!='copy' and identifier in produced),'Output used before produced')
        available.update(produced)
    require(available == set(outputs),'Every output needs exactly one producer')


def parse_pack(text):
    sections = _sections(text)
    require('pack' in sections,'Missing pack section')
    meta = sections['pack']
    _keys(meta,{'format','id','version','name','platform','description','color'},'pack')
    require(meta['format']=='2','Graph workspace requires modular format-2 packs')
    require(meta['platform']=='windows-x86_64','Unsupported pack platform')
    require(ID.fullmatch(meta['id']) and VERSION.fullmatch(meta['version']),'Invalid pack ID or version')
    require(_clean(meta['name'],100) and _clean(meta.get('description',''),2048,True),'Invalid pack text')
    require(re.fullmatch(r'#[0-9A-Fa-f]{6}',meta.get('color','#347E88')),'Invalid pack colour')
    result = {'id':meta['id'],'version':meta['version'],'name':meta['name'],'description':meta.get('description',''),'tools':{},'assets':{},'workflows':{}}
    used, paths = {'pack'}, set()
    for name, fields in sections.items():
        if not name.startswith(('tool:','asset:')):
            continue
        kind,identifier = name.split(':',1)
        require(ID.fullmatch(identifier),'Invalid declared file ID')
        _keys(fields,{'path','sha256','version'} if kind=='tool' else {'path','sha256'},kind)
        path = _relative(fields['path'])
        sha = fields['sha256'].lower()
        require(SHA.fullmatch(sha),'Invalid SHA-256')
        folded = path.lower()
        require(all(32 <= ord(c) <= 126 for c in path),'Declared pack paths must use printable ASCII')
        require(folded.split('/')[0] not in {'pack.ini','licenses','pack-readme.md','pack-readme.txt','readme.txt'},'Declared pack path collides with metadata')
        require(not any(folded == old or folded.startswith(old+'/') or old.startswith(folded+'/') for old in paths),'Declared file paths collide')
        paths.add(folded)
        item = {'id':identifier,'path':path,'sha256':sha}
        if kind=='tool':
            require(path.lower().endswith('.exe') and re.fullmatch(r'[A-Za-z0-9.+_-]{1,64}',fields['version']),'Invalid executable path or version')
            item['version']=fields['version']
        result['tools' if kind=='tool' else 'assets'][identifier]=item
        used.add(name)
    require(1 <= len(result['tools']) <= 64 and len(result['assets']) <= 8192,'Invalid declared tool/asset count')
    for name, fields in sections.items():
        if not name.startswith('workflow:'):
            continue
        identifier = name[9:]
        require(ID.fullmatch(identifier),'Invalid workflow ID')
        _keys(fields,{'name','description','inputs','outputs','steps'},'workflow')
        require(_clean(fields['name'],100) and _clean(fields.get('description',''),2048,True),'Invalid workflow text')
        workflow = {'id':identifier,'name':fields['name'],'description':fields.get('description',''),'inputs':[],'outputs':[],'steps':[]}
        used.add(name)
        for kind, maximum in (('input',32),('output',64),('step',64)):
            for child_id in _ids(fields[kind+'s'],maximum,kind!='step'):
                key=f'{kind}:{identifier}:{child_id}'
                require(key in sections and key not in used, 'Missing or duplicate workflow child')
                used.add(key)
                item = sections[key]
                if kind=='input':
                    parsed = _input(child_id,item)
                elif kind=='output':
                    _keys(item,{'label','path','final','nonempty'},'output')
                    require(_clean(item['label'],100),'Invalid output label')
                    parsed={'id':child_id,'label':item['label'],'path':_relative(item['path']), 'final':_bool(item.get('final','true')),'nonempty':_bool(item.get('nonempty','true'))}
                else:
                    _keys(item,{'label','kind','tool','sink-tool','stdout','source','destination','produces'},'step',True)
                    require(_clean(item['label'],100),'Invalid step label')
                    step_kind=item.get('kind','exec')
                    require(step_kind in ('copy','exec','pipe'),'Unknown step kind')
                    parsed={'id':child_id,'label':item['label'],'kind':step_kind,'args':_args(item,'arg.'),'sinkArgs':_args(item,'sink-arg.')}
                    require(step_kind=='pipe' or ('sink-tool' not in item and not parsed['sinkArgs']),'Sink on nonpipe step')
                    if step_kind=='copy':
                        require(not any(x in item for x in ('tool','stdout','produces')) and not parsed['args'],'Invalid copy step')
                        parsed.update(source=item['source'],destination=item['destination'])
                    else:
                        require('source' not in item and 'destination' not in item,'Invalid executable step')
                        parsed.update(tool=item['tool'],stdout=item.get('stdout',''),produces=_ids(item.get('produces',''),64,True))
                        if step_kind=='pipe':
                            parsed['sinkTool']=item['sink-tool']
                workflow[kind+'s'].append(parsed)
        _validate_workflow(workflow,result['tools'],result['assets'])
        result['workflows'][identifier]=workflow
    require(1 <= len(result['workflows']) <= 64,'Invalid workflow count')
    require(used == set(sections),'Unknown or unreferenced manifest section')
    return result


def _input_type(item):
    identifier, filt = item['id'],item.get('filter','').lower()
    if item['type']=='directory': return 'directory',['directory']
    if identifier == 'reference': return 'reference',['reference']
    if identifier.startswith('reads'): return 'reads',['reads']
    if identifier == 'likelihoods': return 'bcf-likelihoods',['bcf-likelihoods']
    if identifier in ('alignment','alignments'):
        return 'bam',['sam','bam'] if '*.sam' in filt else ['bam']
    if identifier == 'variants':
        return 'vcf',['vcf','vcf-pass','bcf'] if '*.bcf' in filt else ['vcf','vcf-pass']
    # Unknown new pack inputs deliberately do not infer biological compatibility.
    return 'file',['file']


def _output_type(item):
    identifier,path = item['id'],item['path'].lower()
    if identifier == 'pileup': return 'bcf-likelihoods'
    if path.endswith(('.fastq','.fq','.fastq.gz','.fq.gz')): return 'reads'
    if path.endswith(('.fa','.fasta','.fna')):
        # A FASTA extension alone does not establish a genomic reference, a
        # nucleotide/protein alphabet, or an alignment. New packs declare that
        # explicitly in their integrity-checked workbench-schema asset.
        return 'reference' if identifier == 'reference' else 'file'
    if path.endswith('.sam'): return 'sam'
    if path.endswith('.bam'): return 'bam'
    if path.endswith('.bcf'): return 'bcf'
    if path.endswith(('.vcf','.vcf.gz')): return 'vcf-pass' if identifier=='pass-variants' else 'vcf'
    if path.endswith(('.bai','.csi','.fai','.amb','.ann','.bwt','.pac','.sa')): return 'index'
    if path.endswith('.html'): return 'report'
    if path.endswith('.js'): return 'script'
    if path.endswith(('.txt','.tsv','.json')): return 'metrics'
    return 'file'


def _state(pack_id, workflow_id, output):
    identifier, path = output['id'],output['path'].lower()
    state = {}
    if _output_type(output)=='reads':
        state['compression']='gzip' if path.endswith('.gz') else 'none'
    if _output_type(output) in ('sam','bam'):
        if identifier in ('sam','aligned'): state['sort']='unsorted'
        if identifier=='names' or (pack_id=='bam' and workflow_id=='name-sort'): state['sort']='queryname'
        if identifier=='fixed': state.update(sort='queryname',mateFixed=True)
        if identifier in ('coordinates','bam','marked','merged') or (pack_id=='bam' and workflow_id in ('sort','index')):
            state['sort']='coordinate'
        if identifier=='coordinates': state['mateFixed']=True
        if identifier=='merged': state['duplicates']='requires-remarking'
        if identifier in ('bam','marked'): state.update(mateFixed=True,duplicates='marked')
    if identifier in ('variants','filtered') and _output_type(output)=='vcf': state['selection']='all-calls-with-filter-labels'
    if identifier=='pass-variants': state['selection']='PASS-only'
    return state


def _workflow_presentation(data):
    """Add discoverable labels without changing an operation's saved contract.

    Foreground the executables that actually produce the scientific products,
    not the first alphabetically sorted executable (often a validation helper).
    These strings never select a command, a port type or a saved tool identity.
    """
    steps = [step for step in data.get('steps', []) if step['kind'] != 'copy']
    executables = {item['id']: item for item in data.get('executables', [])}
    products = [item for item in data.get('outputs', []) if item.get('final')]
    scientific = [item for item in products if item['type'] not in ('metrics', 'index', 'text', 'script')]
    product_ids = {member for item in scientific or products for member in item['manifestOutputs']}
    producers = [step for step in steps if product_ids.intersection(
        step.get('produces', []) + ([step['stdout']] if step.get('stdout') else []))]
    program_ids = []
    for step in producers or steps:
        for key in ('tool', 'sinkTool'):
            identity = step.get(key)
            if identity in executables and identity not in program_ids:
                program_ids.append(identity)
    # Known executable spellings are presentation only; unknown pack programs
    # retain their declared identity. No pack IDs are renamed or special-cased.
    spellings = {'samtools': 'SAMtools', 'bcftools': 'BCFtools', 'bwa': 'BWA',
                 'star': 'STAR', 'fastqc': 'FastQC', 'multiqc': 'MultiQC'}
    programs = [spellings.get(identity.casefold(), identity) for identity in program_ids]
    name, description = data['name'], data['description']
    extra_terms = []
    # Recognize the precise declared SAMtools commands, not an operation ID or
    # a filename alone. A larger operation containing faidx is not an index tool.
    only = steps[0] if len(steps) == 1 and steps[0]['kind'] == 'exec' else None
    samtools_command = (only.get('args', [])[0] if only and only.get('tool') == 'samtools'
                        and only.get('args') else None)
    if samtools_command == 'faidx' and any(
            path.lower().endswith('.fai') for item in products for path in item['files'].values()):
        name = 'FASTA lookup index (.fai)'
        description += (' Creates a SAMtools FASTA lookup index for sequence access, not an aligner index. '
                        'Starter alignment and variant-calling operations prepare their required indexes '
                        'themselves; this separate export step is not a prerequisite.')
        extra_terms.extend(['faidx', 'FASTA lookup index', '.fai'])
    elif samtools_command == 'sort' and any(item['type'] == 'bam' for item in products):
        accepts = {kind for port in data.get('ports', []) for kind in port.get('accepts', [])}
        if {'sam', 'bam'} <= accepts:
            name += ' to BAM (SAM/BAM input)'
            description += (' Converts SAM input to BAM while sorting, and also accepts BAM. '
                            'Sorting does not repair mates or mark duplicates.')
            extra_terms.extend(['SAM to BAM', 'SAM -> BAM', 'convert SAM', 'BAM conversion'])
    # Existing names that already identify their program need no redundant
    # prefix. Adapter wrappers can be recognized by their operation's own name.
    missing = [program for program in programs if re.search(
        r'(?<![a-z0-9])' + re.escape(program.removesuffix('-adapter').casefold()) + r'(?![a-z0-9])',
        name.casefold()) is None]
    if missing:
        name = ' + '.join(missing) + ' — ' + name
    if any(item['type'] == 'sam' for item in products) and not re.search(r'\bsam\b', name, re.I):
        name += ' (SAM)'
    data['displayName'] = name
    data['displayDescription'] = description
    # Search uses both friendly labels and exact command/format vocabulary.
    data['searchTerms'] = ' '.join(dict.fromkeys(
        [data['name'], name, description, data.get('category', '')] + program_ids + programs + extra_terms +
        [step['args'][0] for step in steps if step.get('args')] +
        [kind for port in data.get('ports', []) for kind in port.get('accepts', [])] +
        [item['type'] for item in data.get('outputs', [])]))


def describe_workflow(pack, workflow, pack_folder, manifest_sha):
    key = pack['id']+'/'+workflow['id']
    data={'id':key,'packId':pack['id'],'packVersion':pack['version'],'packFolder':pack_folder,
          'manifestSha256':manifest_sha,'workflowId':workflow['id'],'name':workflow['name'],
          'description':workflow['description'],'category':CATEGORIES.get(pack['id'],'Other tools'),
          'ports':[],'params':[],'outputs':[],'executables':[],'steps':workflow['steps']}
    inputs={i['id']:i for i in workflow['inputs']}
    consumed=set()
    if all(i in inputs and inputs[i]['type']=='file' for i in ('reads1','reads2')):
        data['ports'].append({'id':'reads','label':'Paired reads','type':'pair','accepts':['pair'],
            'manifestInputs':['reads1','reads2'],'min':1,'max':1,'required':True,
            'fields':[inputs['reads1'],inputs['reads2']],'help':'Read 1 and Read 2 remain an atomic pair; both files must contain matching mates.'})
        consumed.update(('reads1','reads2'))
    for item in workflow['inputs']:
        if item['id'] in consumed: continue
        if item['type'] in PARAM_TYPES:
            data['params'].append(item)
            continue
        kind,accepts = _input_type(item)
        port={'id':item['id'],'label':item['label'],'type':kind,'accepts':accepts,
            'manifestInputs':[item['id']],'min':1 if item['required'] else 0,
            'max':64 if item['type']=='files' else 1,'required':item['required'],'fields':[item],'help':item['help']}
        if key=='bam/merge': port.update(min=2,help=item['help']+' Inputs must be disjoint lanes from one sample and reference; metadata and headers are checked before merging.')
        if key in ('bam/index','bam/merge','bam/mark-duplicates','variants/call','variants/pileup','freebayes/call') and kind=='bam':
            port['requiredState']={'sort':'coordinate'}
        if key=='bam/fixmate': port['requiredState']={'sort':'queryname'}
        if key=='bam/mark-duplicates': port['requiredState']['mateFixed']=True
        if key=='reads/statistics': port['requiredState']={'compression':'none'}
        if key=='variants/index': port['requiredState']={'compression':'bgzf'}
        data['ports'].append(port)
    outputs={i['id']:i for i in workflow['outputs']}
    consumed=set()
    for first,second,identifier,label in (('trimmed1','trimmed2','trimmed','Trimmed paired reads'),('rejected1','rejected2','rejected','Rejected short pairs')):
        if first in outputs and second in outputs:
            members=[outputs[first],outputs[second]]
            data['outputs'].append({'id':identifier,'label':label,'type':'pair','manifestOutputs':[first,second],
                'files':{m['id']:m['path'] for m in members},'fields':members,'final':all(m['final'] for m in members),
                'state':{'compression':'gzip' if all(m['path'].endswith('.gz') for m in members) else 'none'},'propagateStateFrom':'reads'})
            consumed.update((first,second))
    for output in workflow['outputs']:
        if output['id'] in consumed: continue
        kind=_output_type(output)
        descriptor={'id':output['id'],'label':output['label'],'type':kind,'manifestOutputs':[output['id']],
            'files':{output['id']:output['path']},'fields':[output],'state':_state(pack['id'],workflow['id'],output),'final':output['final']}
        if kind in ('vcf','vcf-pass') and output['path'].endswith('.gz'): descriptor['state']['compression']='bgzf'
        if kind in ('sam','bam') and 'alignment' in inputs: descriptor['propagateStateFrom']='alignment'
        if kind=='bam' and key=='bam/merge': descriptor['propagateStateFrom']='alignments'
        if kind in ('vcf','vcf-pass','bcf') and 'variants' in inputs: descriptor['propagateStateFrom']='variants'
        if kind=='reference' and 'reference' in inputs: descriptor['propagateStateFrom']='reference'
        if kind=='reads' and output['id']=='reversed': descriptor['propagateStateFrom']='reads'
        data['outputs'].append(descriptor)
    # Promote scientific products while keeping every declared output addressable.
    priority={'pair':0,'bam':1,'sam':1,'vcf':2,'vcf-pass':3,'bcf':4,'bcf-likelihoods':4,'reads':5,'reference':6,'metrics':7,'report':8,'index':10,'script':11}
    data['outputs'].sort(key=lambda o:(not o['final'],priority.get(o['type'],9)))
    tool_ids={step[k] for step in workflow['steps'] for k in ('tool','sinkTool') if k in step}
    data['executables']=[pack['tools'][i] for i in sorted(tool_ids)]
    data.update(task=data['name'],cat=data['category'],desc=data['description'],version=data['packVersion'],
                defaults={p['id']:p['default'] for p in data['params']},output=data['outputs'][0] if data['outputs'] else None)
    if key=='bam/merge':
        data['requirements']=['same-reference','same-sample','disjoint-readsets','coordinate-sorted']
        data['merge']=True
    if key in ('variants/call','variants/pileup','freebayes/call'):
        data['requirements']=['same-reference','coordinate-sorted']
    if key=='variants/call' or key.startswith('variant-pipeline/'):
        for out in data['outputs']:
            if out['id']=='variants': out['label']='All normalized calls with filter labels'
    _apply_workbench_schema(pack,workflow,data)
    _workflow_presentation(data)
    return data



SEQUENCE_TYPES = {'reads','reference','fasta-nucleotide','fasta-protein','msa-nucleotide','msa-protein','fasta-nucleotide-abundance'}
STATE_VALUES = {
    'compression': {'none','gzip','bgzf'},
    'alphabet': {'nucleotide','protein'},
    'alignment': {'unaligned','aligned'},
    'sort': {'coordinate','queryname','unsorted','lexicographic','abundance'},
    'pairing': {'single','paired'},
    'duplicates': {'marked','retained','removed','requires-remarking'},
    'selection': {'all-calls-with-filter-labels','PASS-only'},
}
STATE_BOOLEANS = {'abundance','mateFixed'}


def _schema_object(value, allowed, label):
    require(isinstance(value,dict),label+': expected an object')
    require(all(isinstance(key,str) and key in allowed for key in value),label+': unknown field')
    return value


def _schema_state(value):
    _schema_object(value,set(STATE_VALUES)|STATE_BOOLEANS,'Scientific state')
    for key,item in value.items():
        if key in STATE_BOOLEANS:
            require(type(item) is bool,'Scientific state '+key+' must be a boolean')
        else:
            require(isinstance(item,str) and item in STATE_VALUES[key],'Unknown scientific state value: '+key)
    return dict(value)


def _schema_citations(value):
    from urllib.parse import urlsplit
    require(isinstance(value,list) and len(value)<=8,'Citations must be a list with at most eight entries')
    result=[]
    for item in value:
        _schema_object(item,{'text','url'},'Citation')
        require(_clean(item.get('text'),2048),'Citation needs short plain text')
        url=item.get('url','')
        if url:
            require(_clean(url,2048),'Citation URL is invalid')
            try:
                parsed=urlsplit(url)
                require(parsed.scheme in ('https','http') and parsed.hostname and not parsed.username and not parsed.password,'Citation URL must be an ordinary HTTP(S) address')
            except ValueError as exc:
                raise CatalogError('Citation URL is invalid') from exc
        result.append({'text':item['text'],'url':url})
    return result


def _schema_ids(value, known, label):
    require(isinstance(value,list) and 1<=len(value)<=64 and all(isinstance(x,str) and x in known for x in value),label+': unknown or missing manifest member')
    require(len(value)==len(set(value)),label+': repeated manifest member')
    return list(value)


def _schema_path_policy(value):
    _schema_object(value,{'asciiOnly','forbiddenCharacters'},'Path policy')
    require('asciiOnly' not in value or type(value['asciiOnly']) is bool,'asciiOnly must be boolean')
    characters=value.get('forbiddenCharacters',[])
    require(isinstance(characters,list) and len(characters)<=16 and all(isinstance(c,str) for c in characters) and len(set(characters))==len(characters),
            'Path policy needs distinct forbidden characters')
    require(all(isinstance(c,str) and len(c)==1 and 32<=ord(c)<127 and c not in '/\\:' for c in characters),
            'Path policy characters must be individual printable characters, not path separators')
    return {'asciiOnly':value.get('asciiOnly',False),'forbiddenCharacters':list(characters)}


def _validate_workbench_schema(document,pack):
    _schema_object(document,{'schema','category','citations','workflows'},'Workbench schema')
    require(type(document.get('schema')) is int and document['schema']==1,'Unsupported workbench schema version')
    require(_clean(document.get('category'),100),'Workbench schema needs a category')
    citations=_schema_citations(document.get('citations',[]))
    definitions=document.get('workflows')
    require(isinstance(definitions,dict) and set(definitions)==set(pack['workflows']),'Workbench schema must cover every pack workflow exactly once')
    normalized={}
    for identity,definition in definitions.items():
        _schema_object(definition,{'category','ports','outputs','methods','citations','pathPolicy','parameterConstraints','parameterRanges','referenceIndex','requiresReferenceIndex'},'Workflow metadata')
        category=definition.get('category',document['category'])
        require(_clean(category,100),'Invalid workflow category')
        methods=definition.get('methods','')
        require(_clean(methods,4096,True),'Methods must be short plain text')
        workflow=pack['workflows'][identity]
        inputs={item['id']:item for item in workflow['inputs'] if item['type'] in FILE_TYPES}
        outputs={item['id']:item for item in workflow['outputs']}
        ports=definition.get('ports')
        products=definition.get('outputs')
        require(isinstance(ports,list) and len(ports)<=64 and isinstance(products,list) and 1<=len(products)<=128,'Invalid metadata port/output count')
        seen_inputs=set(); seen_outputs=set(); port_ids=set(); output_ids=set()
        parsed_ports=[]; parsed_outputs=[]
        for port in ports:
            _schema_object(port,{'id','label','type','accepts','manifestInputs','min','max','requiredState','help','validation'},'Input port')
            port_id=port.get('id')
            require(isinstance(port_id,str) and ID.fullmatch(port_id) and port_id not in port_ids,'Invalid or repeated input port ID')
            port_ids.add(port_id)
            members=_schema_ids(port.get('manifestInputs'),inputs,'Input port')
            require(not seen_inputs.intersection(members),'A manifest input appears in more than one port')
            seen_inputs.update(members)
            kind=port.get('type'); accepts=port.get('accepts',[kind])
            require(kind in TYPES and isinstance(accepts,list) and 1<=len(accepts)<=len(TYPES) and all(isinstance(t,str) and t in TYPES for t in accepts) and len(accepts)==len(set(accepts)) and kind in accepts,'Input port declares an unknown or incompatible type')
            fields=[inputs[m] for m in members]
            multiple=len(fields)==1 and fields[0]['type']=='files'
            require(len(fields)==1 or all(f['type']=='file' for f in fields),'Grouped ports must contain ordinary file fields')
            if kind=='pair':
                require(len(fields)==2 and all(f['type']=='file' for f in fields),'A paired-read port requires exactly two file fields')
                require(accepts==['pair'],'A paired-read port cannot accept unpaired sequences')
            elif kind in SEQUENCE_TYPES or kind in {'id-list','cluster-membership'}:
                require(len(fields)==1,'A sequence or identifier port must contain one manifest input')
            required=any(f['required'] for f in fields)
            minimum=port.get('min',1 if required else 0); maximum=port.get('max',64 if multiple else 1)
            require(type(minimum) is int and type(maximum) is int and (1 if required else 0)<=minimum<=maximum<=64,'Invalid input cardinality')
            require(multiple or maximum==1,'Only a manifest files input accepts multiple sources')
            label=port.get('label',fields[0]['label']); help_text=port.get('help',' '.join(f.get('help','') for f in fields).strip())
            require(_clean(label,150) and _clean(help_text,4096,True),'Invalid input label/help')
            result={'id':port_id,'label':label,'type':kind,'accepts':list(accepts),'manifestInputs':members,'min':minimum,'max':maximum,'required':required,'fields':fields,'help':help_text}
            if 'requiredState' in port: result['requiredState']=_schema_state(port['requiredState'])
            if 'validation' in port:
                rules=port['validation']
                if kind in ('sam','bam','sam-rna','bam-rna'):
                    _schema_object(rules,{'singleSample','sampleParameter'},'Alignment validation')
                    require('singleSample' not in rules or type(rules['singleSample']) is bool,'singleSample must be boolean')
                    if 'sampleParameter' in rules:
                        params={item['id'] for item in workflow['inputs'] if item['type']=='text'}
                        require(rules.get('singleSample') is True and rules['sampleParameter'] in params,'sampleParameter requires singleSample and a declared text parameter')
                elif kind in ('vcf','vcf-pass'):
                    _schema_object(rules,{'requiredInfoFields'},'VCF validation')
                    declarations=rules.get('requiredInfoFields')
                    require(isinstance(declarations,list) and 1<=len(declarations)<=16 and set(accepts)<={'vcf','vcf-pass'},
                            'VCF validation requires 1 to 16 INFO fields and VCF-only inputs')
                    info_ids=set()
                    for declaration in declarations:
                        _schema_object(declaration,{'id','number','type'},'Required VCF INFO field')
                        require(set(declaration)=={'id','number','type'} and
                                isinstance(declaration['id'],str) and re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}',declaration['id']) and
                                declaration['id'] not in info_ids,'Required VCF INFO fields need distinct valid IDs')
                        require(isinstance(declaration['number'],str) and re.fullmatch(r'(?:[ARG.]|0|[1-9][0-9]{0,5})',declaration['number']) and
                                isinstance(declaration['type'],str) and declaration['type'] in ('Integer','Float','Flag','Character','String'),
                                'Required VCF INFO fields need valid Number and Type declarations')
                        require(declaration['type']!='Flag' or declaration['number']=='0','A VCF INFO Flag must declare Number=0')
                        info_ids.add(declaration['id'])
                elif kind=='bed':
                    _schema_object(rules,{'minColumns','nonOverlapping','referenceBounds'},'BED validation')
                    require(type(rules.get('minColumns',3)) is int and 3<=rules.get('minColumns',3)<=12,'BED minimum columns must be 3 to 12')
                    require(all(type(rules[key]) is bool for key in ('nonOverlapping','referenceBounds') if key in rules),'BED validation switches must be boolean')
                else:
                    _schema_object(rules,{'minRecords','maxRecords','minLength','maxLength','uniqueIds','rejectAbundance'},'Sequence validation')
                    require(kind in SEQUENCE_TYPES-{'reads','reference'},'Sequence validation requires an explicit FASTA sequence type')
                    for rule,value in rules.items():
                        if rule in ('uniqueIds','rejectAbundance'): require(type(value) is bool,rule+' must be boolean')
                        else: require(type(value) is int and 0<=value<=1000000000,'Sequence validation bounds must be nonnegative integers')
                    require(rules.get('minRecords',0)<=rules.get('maxRecords',1000000000) and rules.get('minLength',0)<=rules.get('maxLength',1000000000),'Sequence validation minimum exceeds maximum')
                result['validation']=dict(rules)
            parsed_ports.append(result)
        require(seen_inputs==set(inputs),'Workbench metadata omits manifest file inputs')
        for output in products:
            _schema_object(output,{'id','label','type','manifestOutputs','state','propagateStateFrom'},'Output port')
            output_id=output.get('id')
            require(isinstance(output_id,str) and ID.fullmatch(output_id) and output_id not in output_ids,'Invalid or repeated output ID')
            output_ids.add(output_id)
            members=_schema_ids(output.get('manifestOutputs'),outputs,'Output port')
            require(not seen_outputs.intersection(members),'A manifest output appears in more than one output port')
            seen_outputs.update(members)
            kind=output.get('type')
            require(isinstance(kind,str) and kind in TYPES,'Unknown output data type')
            fields=[outputs[m] for m in members]
            require(kind!='pair' or len(fields)==2,'Paired output requires exactly two declared files')
            if kind in SEQUENCE_TYPES or kind in {'id-list','cluster-membership'}:
                require(len(fields)==1,'A sequence/identifier output contains one file')
            state=_schema_state(output.get('state',{}))
            if kind in SEQUENCE_TYPES or kind=='pair':
                require('compression' in state,'Sequence output must explicitly declare compression')
                gz=[f['path'].lower().endswith('.gz') for f in fields]
                require((all(gz) and state['compression'] in ('gzip','bgzf')) or (not any(gz) and state['compression']=='none'),'Output compression declaration differs from its filename')
            if kind=='fasta-nucleotide-abundance':
                require(state.get('abundance') is True,'Abundance FASTA output must declare abundance=true')
            label=output.get('label',fields[0]['label'])
            require(_clean(label,150),'Invalid output label')
            result={'id':output_id,'label':label,'type':kind,'manifestOutputs':members,'files':{f['id']:f['path'] for f in fields},'fields':fields,'state':state,'final':all(f['final'] for f in fields)}
            if 'propagateStateFrom' in output:
                require(output['propagateStateFrom'] in port_ids,'Output state refers to unknown input port')
                result['propagateStateFrom']=output['propagateStateFrom']
            parsed_outputs.append(result)
        require(seen_outputs==set(outputs),'Workbench metadata omits manifest outputs')
        normalized[identity]={'category':category,'ports':parsed_ports,'outputs':parsed_outputs,'methods':methods,'citations':citations+_schema_citations(definition.get('citations',[]))}
        for key in ('referenceIndex','requiresReferenceIndex'):
            if key not in definition:
                continue
            require(not all(k in definition for k in ('referenceIndex','requiresReferenceIndex')),
                    'An index builder cannot also consume an index')
            index=definition[key]
            allowed={'format','tool','referencePort','outputPort'} if key=='referenceIndex' else {'format','tool','port'}
            _schema_object(index,allowed,'Reference index contract')
            require(set(index)==allowed and index.get('format')=='minimap2-sr-v1' and index.get('tool') in pack['tools'],
                    'Unsupported or incomplete reference index contract')
            used_tools={step.get(k) for step in workflow['steps'] for k in ('tool','sinkTool')}
            require(index['tool'] in used_tools,'Reference index tool must execute in this operation')
            if key=='referenceIndex':
                require(len(parsed_ports)==1 and parsed_ports[0]['id']==index['referencePort'] and
                        parsed_ports[0]['type']=='reference' and len(parsed_ports[0]['fields'])==1 and
                        parsed_ports[0]['fields'][0]['type']=='file' and parsed_ports[0]['min']==1 and
                        len(parsed_outputs)==1 and parsed_outputs[0]['id']==index['outputPort'] and
                        parsed_outputs[0]['type']=='minimap2-sr-index' and len(parsed_outputs[0]['fields'])==1,
                        'Reference index builder needs one reference file and one minimap2 index output')
                require(all(field['nonempty'] for output in parsed_outputs for field in output['fields']),
                        'Reference index outputs must be nonempty')
            else:
                matches=[p for p in parsed_ports if p['id']==index['port']]
                require(len(matches)==1 and matches[0]['type']=='minimap2-sr-index' and
                        len(matches[0]['fields'])==1 and matches[0]['min']==matches[0]['max']==1,
                        'Index consumer needs one required minimap2 index file')
            normalized[identity][key]=dict(index)
        if 'pathPolicy' in definition:
            normalized[identity]['pathPolicy']=_schema_path_policy(definition['pathPolicy'])
        if 'parameterConstraints' in definition:
            constraints=definition['parameterConstraints']
            require(isinstance(constraints,list) and 1<=len(constraints)<=16,'Expected 1 to 16 parameter constraints')
            integers={item['id'] for item in workflow['inputs'] if item['type']=='integer'}
            text_parameters={item['id'] for item in workflow['inputs'] if item['type']=='text'}
            for constraint in constraints:
                _schema_object(constraint,{'left','operator','right'},'Parameter constraint')
                require(set(constraint)=={'left','operator','right'} and
                        all(isinstance(constraint[key],str) for key in ('left','operator','right')) and
                        constraint['left']!=constraint['right'],
                        'Parameter constraints require two distinct declared parameters')
                known=integers if constraint['operator']=='<=' else text_parameters if constraint['operator']=='!=' else set()
                require(constraint['left'] in known and constraint['right'] in known,
                        'Parameter constraints support <= between integers or != between text parameters')
            normalized[identity]['parameterConstraints']=[dict(c) for c in constraints]
        if 'parameterRanges' in definition:
            ranges=definition['parameterRanges']
            require(isinstance(ranges,list) and 1<=len(ranges)<=16,'Expected 1 to 16 decimal parameter ranges')
            parameters={item['id'] for item in workflow['inputs'] if item['type']=='text'}
            seen=set()
            for bounds in ranges:
                _schema_object(bounds,{'parameter','min','max'},'Decimal parameter range')
                require(set(bounds)=={'parameter','min','max'} and isinstance(bounds['parameter'],str) and
                        bounds['parameter'] in parameters and bounds['parameter'] not in seen,
                        'Decimal ranges require distinct declared text parameters')
                require(all(type(bounds[key]) in (int,float) and -1e100<=bounds[key]<=1e100 and math.isfinite(bounds[key]) for key in ('min','max')) and
                        bounds['min']<=bounds['max'],'Decimal parameter range bounds must be finite ordered numbers within +/-1e100')
                seen.add(bounds['parameter'])
            normalized[identity]['parameterRanges']=[dict(bounds) for bounds in ranges]
    return normalized


def _load_workbench_schema(manifest,pack):
    asset=pack['assets'].get('workbench-schema')
    if asset is None:
        return
    root=Path(manifest).parent.resolve()
    path=root/asset['path']
    require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root),'Workbench schema must be an ordinary pack asset')
    for parent in path.parents:
        if parent==root: break
        require(not parent.is_symlink() and not (hasattr(parent,'is_junction') and parent.is_junction()),'Workbench schema folders must not be links')
    require(path.stat().st_size<=1024*1024,'Workbench schema exceeds 1 MiB')
    with path.open('rb') as stream:
        raw=stream.read(1024*1024+1)
    require(len(raw)<=1024*1024,'Workbench schema exceeds 1 MiB')
    require(hashlib.sha256(raw).hexdigest()==asset['sha256'],'Workbench schema asset hash mismatch')
    def pairs(items):
        result={}
        for key,value in items:
            require(key not in result,'Duplicate JSON field in workbench schema')
            result[key]=value
        return result
    def constant(value):
        raise CatalogError('Non-finite JSON value in workbench schema')
    try:
        document=json.loads(raw.decode('utf-8-sig'),object_pairs_hook=pairs,parse_constant=constant)
        normalized=_validate_workbench_schema(document,pack)
    except (UnicodeError,ValueError,TypeError,KeyError,RecursionError) as exc:
        if isinstance(exc,CatalogError): raise
        raise CatalogError('Malformed workbench schema: '+str(exc)) from exc
    pack['workbenchSchema']=normalized
    pack['workbenchSchemaAsset']={'id':'workbench-schema','path':asset['path'],'sha256':asset['sha256']}


def _apply_workbench_schema(pack,workflow,data):
    metadata=pack.get('workbenchSchema',{}).get(workflow['id'])
    if metadata is None:
        return
    data['category']=data['cat']=metadata['category']
    data['ports']=metadata['ports']
    data['outputs']=metadata['outputs']
    data['output']=data['outputs'][0] if data['outputs'] else None
    data['methodsDescription']=metadata['methods']
    data['citations']=metadata['citations']
    data['schemaAsset']=dict(pack['workbenchSchemaAsset'])
    for key in ('referenceIndex','requiresReferenceIndex'):
        if key in metadata:
            data[key]=dict(metadata[key])
    if 'pathPolicy' in metadata:
        data['pathPolicy']=dict(metadata['pathPolicy'])
    if 'parameterConstraints' in metadata:
        data['parameterConstraints']=[dict(c) for c in metadata['parameterConstraints']]
    if 'parameterRanges' in metadata:
        data['parameterRanges']=[dict(bounds) for bounds in metadata['parameterRanges']]

def load_pack(manifest):
    path=Path(manifest)
    raw=path.read_bytes()
    require(len(raw)<=8*1024*1024,'Manifest exceeds byte limit')
    try:
        pack=parse_pack(raw.decode('utf-8-sig'))
    except (UnicodeError,KeyError) as exc:
        raise CatalogError(f'{path.name}: malformed manifest ({exc})') from exc
    pack['manifestSha256']=hashlib.sha256(raw).hexdigest()
    _load_workbench_schema(path,pack)
    return pack


def builtin_report():
    """A local HTML collection with separately attributed metric sections."""
    desc='Collect selected statistics into a local HTML report with a separate, attributed section for each input. Counts are not pooled and variant files are not merged.'
    title={'id':'title','label':'Report title','type':'text','default':'Pipeline report','required':True,'help':'Heading for the combined report.','constraint':'','binding':False,'preset':True}
    output={'id':'report','label':'Combined report','type':'report','manifestOutputs':['report'],'files':{'report':'report.html'},'fields':[{'id':'report','label':'Combined report','path':'report.html','final':True,'nonempty':True}],'state':{},'final':True}
    return {'id':'builtin/report','packId':'builtin','packVersion':'0.5.0','packFolder':'','manifestSha256':hashlib.sha256(b'native-workbench-report-v1').hexdigest(),'workflowId':'report',
        'name':'Combine statistics reports','task':'Combine statistics reports','description':desc,'desc':desc,'category':'Reporting','cat':'Reporting','version':'0.5.0',
        'ports':[{'id':'metrics','label':'Statistics to include','type':'metrics','accepts':['metrics','text'],'manifestInputs':['metrics'],'min':2,'max':64,'required':True,
                  'fields':[{'id':'metrics','label':'Statistics files','type':'files','required':True,'default':'','role':'file','filter':'Metrics|*.json;*.txt;*.tsv|All files|*.*','help':'Each file becomes a separately labelled section.'}]}],
        'params':[title],'defaults':{'title':'Pipeline report'},'outputs':[output],'output':output,'executables':[],'steps':[],'builtin':'report'}


def resolve_tool(catalog, identity, pin=None):
    """Resolve a new operation or an exact saved operation, never upgrade a pin.

    Historical saved graphs omit packId but always carry version and manifest
    hash. A catalogue supplied by older callers may contain only ``tools``.
    """
    require(isinstance(identity,str), 'Invalid operation identity')
    if pin is None:
        tool=catalog.get('tools',{}).get(identity)
        require(tool is not None,'This tool is not installed: '+identity)
        return tool
    require(isinstance(pin,dict) and isinstance(pin.get('packVersion'),str) and
            VERSION.fullmatch(pin['packVersion']) and isinstance(pin.get('manifestSha256'),str) and
            SHA.fullmatch(pin['manifestSha256']), 'The saved tool pin is incomplete or malformed: '+identity)
    require('packId' not in pin or isinstance(pin['packId'],str), 'Invalid saved pack identity')
    candidates=catalog.get('toolVersions',{}).get(identity)
    if candidates is None:
        latest=catalog.get('tools',{}).get(identity)
        candidates=[latest] if latest is not None else []
    matches=[tool for tool in candidates if tool.get('packVersion')==pin['packVersion'] and
             tool.get('manifestSha256')==pin['manifestSha256'] and
             ('packId' not in pin or tool.get('packId')==pin['packId'])]
    require(len(matches)==1,'The exact saved tool version is not installed or its manifest differs: '+identity+
            ' '+pin['packVersion']+'. Install the original pack or explicitly select another version.')
    return matches[0]


def _installed_compatibility(app_root, pack):
    """Check optional distribution receipts without changing legacy manifests."""
    path=app_root/'user-data'/'pack-receipts'/(pack['id']+'-'+pack['version']+'.json')
    if not path.exists() and not path.is_symlink():
        return
    for member in (path,*path.parents):
        if member==app_root: break
        require(not member.is_symlink() and not (hasattr(member,'is_junction') and member.is_junction()),
                'Pack compatibility receipt must not use links')
    require(path.is_file() and path.stat().st_size<=65536,'Invalid or oversized pack compatibility receipt')
    def unique(items):
        values={}
        for key,value in items:
            require(key not in values,'Duplicate pack compatibility receipt field')
            values[key]=value
        return values
    def invalid(value):
        raise CatalogError('Non-finite pack compatibility receipt value')
    document=json.loads(path.read_text(encoding='utf-8'),object_pairs_hook=unique,parse_constant=invalid)
    require(isinstance(document,dict) and set(document)=={'schema','id','version','packApi','minAppVersion','platform','manifestSha256'},
            'Malformed pack compatibility receipt')
    require(type(document['schema']) is int and document['schema']==1,'Unsupported pack receipt schema')
    require(document['id']==pack['id'] and document['version']==pack['version'] and
            document['manifestSha256']==pack['manifestSha256'],'Pack compatibility receipt does not match the installed manifest')
    require(type(document['packApi']) is int and document['packApi']==PACK_API,'This pack requires an unsupported pack API')
    require(document['platform']=='windows-x86_64','This pack requires an unsupported platform')
    minimum=document['minAppVersion']
    require(isinstance(minimum,str) and VERSION.fullmatch(minimum),'Invalid minimum application version in pack receipt')
    require(tuple(map(int,minimum.split('.')))<=tuple(map(int,APP_VERSION.split('.'))),
            'This pack requires Native Workbench '+minimum+' or newer')


def load_catalog(app_root):
    """Discover installed format-2 packs and return a JSON-serializable catalogue."""
    app_root=Path(app_root).resolve()
    packs_root=app_root/'packs'
    if not packs_root.exists():
        report=builtin_report()
        return {'schema':SCHEMA,'types':TYPES,'tools':{report['id']:report},'toolVersions':{report['id']:[report]},
                'packs':[],'errors':[],'execution':'local-sequential-dag'}
    require(packs_root.is_dir(),'The packs path is not a folder')
    require(not packs_root.is_symlink() and not (hasattr(packs_root,'is_junction') and packs_root.is_junction()),'The packs folder must not be a link')
    versions={}
    seen_versions=set()
    installed=[]
    errors=[]
    for folder in sorted(packs_root.iterdir()):
        if folder.name.startswith(('_','.')) or not folder.is_dir(): continue
        rel=folder.relative_to(app_root).as_posix()
        try:
            require(not folder.is_symlink() and not (hasattr(folder,'is_junction') and folder.is_junction()) and
                    folder.resolve().parent == packs_root.resolve(),'Pack folders must not be links outside packs')
            manifest=folder/'pack.ini'
            if not manifest.is_file(): continue
            require(not manifest.is_symlink(),'Pack manifest must not be a symbolic link')
            pack=load_pack(manifest)
            require(folder.name==pack['id']+'-'+pack['version'],'Pack folder name must match its ID and version')
            _installed_compatibility(app_root,pack)
            version=tuple(map(int,pack['version'].split('.')))
            identity=(pack['id'],version)
            require(identity not in seen_versions,'Duplicate installed pack version')
            descriptors=[describe_workflow(pack,w,rel,pack['manifestSha256']) for w in pack['workflows'].values()]
            seen_versions.add(identity)
            installed.append({'id':pack['id'],'version':pack['version'],'name':pack['name'],
                              'description':pack.get('description',''),'folder':rel,'manifestSha256':pack['manifestSha256']})
            for tool in descriptors:
                versions.setdefault(tool['id'],[]).append(tool)
        except (OSError,ValueError,KeyError,TypeError,UnicodeError,RecursionError) as exc:
            errors.append({'folder':rel,'message':str(exc)})
    for candidates in versions.values():
        candidates.sort(key=lambda tool:tuple(map(int,tool['packVersion'].split('.'))),reverse=True)
    report=builtin_report()
    versions[report['id']]=[report]
    newest={}
    for pack in installed:
        version=tuple(map(int,pack['version'].split('.')))
        newest[pack['id']]=max(version,newest.get(pack['id'],version))
    tools={identity:candidates[0] for identity,candidates in versions.items()
           if candidates[0].get('builtin') or tuple(map(int,candidates[0]['packVersion'].split('.')))==newest[candidates[0]['packId']]}
    return {'schema':SCHEMA,'types':TYPES,'tools':tools,'toolVersions':versions,'packs':installed,'errors':errors,
            'execution':'local-sequential-dag'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app_root',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    catalog=load_catalog(args.app_root)
    text=json.dumps(catalog,ensure_ascii=False,indent=2)+'\n'
    if args.output:
        args.output.write_text(text,encoding='utf-8')
    else:
        print(text,end='')


if __name__=='__main__':
    main()
