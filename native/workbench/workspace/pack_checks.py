"""Execute optional, hash-pinned pack self-checks using the ordinary graph engine.

Checks contain data and assertions, never shell commands or Python expressions.
They run only when the user requests installation checks.
"""
from __future__ import annotations

from datetime import datetime, timezone
import gzip
import json
import os
from pathlib import Path
import re
import threading
import uuid

from catalog import load_pack, _relative, resolve_tool
from engine import Engine, digest_file, pin_for, write_json, _io_path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _asset(root, pack, identity, cancel):
    require(identity in pack['assets'], 'Check refers to an undeclared fixture asset: '+str(identity))
    item = pack['assets'][identity]
    path = root.joinpath(*_relative(item['path']).split('/'))
    require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root.resolve()), 'Invalid check asset path')
    require(not any(p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()) for p in (path,*path.parents)), 'Fixture cannot use symbolic links or junctions')
    require(digest_file(path, cancel) == item['sha256'], 'Pack check asset hash differs: '+identity)
    return path


def _json(path):
    require(path.stat().st_size <= 256*1024, 'Pack check specification is too large')
    def unique(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate check field: '+key)
            result[key] = value
        return result
    def bad(value):
        raise ValueError('Invalid nonfinite check value')
    value = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique, parse_constant=bad)
    require(isinstance(value, dict) and set(value) == {'schema','checks'} and type(value['schema']) is int and value['schema'] == 1, 'Unsupported pack check specification')
    require(isinstance(value['checks'], list) and 1 <= len(value['checks']) <= 32, 'Expected 1 to 32 pack checks')
    return value


def _sequence_records(text, kind):
    result = {}
    if kind == 'fasta':
        identity = None
        for line in text.splitlines():
            if line.startswith('>'):
                identity = line[1:].split()[0] if line[1:].split() else ''
                require(identity and identity not in result, 'Missing or duplicate FASTA ID in check output')
                result[identity] = ''
            elif line.strip():
                require(identity is not None, 'FASTA sequence before header')
                result[identity] += line.strip()
    else:
        lines = text.splitlines()
        require(len(lines) % 4 == 0, 'Expected four-line FASTQ check output')
        for at in range(0, len(lines), 4):
            header, sequence, plus, quality = lines[at:at+4]
            require(header.startswith('@') and plus.startswith('+') and len(sequence) == len(quality), 'Malformed FASTQ check output')
            identity = header[1:].split()[0] if header[1:].split() else ''
            require(identity and identity not in result, 'Missing or duplicate FASTQ ID in check output')
            result[identity] = sequence
    return result


def _read_check_text(path):
    path = _io_path(path)
    limit = 4*1024*1024
    require(path.stat().st_size <= limit, 'Check output is unexpectedly large')
    with path.open('rb') as stream:
        compressed = stream.read(2) == b'\x1f\x8b'
    with (gzip.open(path,'rb') if compressed else path.open('rb')) as stream:
        data = stream.read(limit+1)
    require(len(data) <= limit, 'Decompressed check output is unexpectedly large')
    return data.decode('utf-8')


def _expected_count(expectation, key, actual, required=False):
    if key not in expectation:
        require(not required, 'Output assertion requires an expected '+key+' count')
        return
    value = expectation[key]
    require(type(value) is int and value >= 0, 'Expected '+key+' count must be a nonnegative integer')
    require(value == actual, 'Unexpected '+key+' count: expected '+str(value)+', found '+str(actual))


def _row_matches(actual, expected):
    return all((all(actual.get(key,{}).get(k) == v for k,v in value.items()) if isinstance(value,dict)
                else actual.get(key) == value) for key,value in expected.items())


def _assert_rows(expected, rows, allowed, label, absent=False):
    require(isinstance(expected,list) and len(expected)<=128, 'Invalid '+label+' assertions')
    remaining = list(rows)
    for row in expected:
        require(isinstance(row,dict) and row and set(row)<=allowed, 'Invalid '+label+' assertion fields')
        for key,value in row.items():
            if key in ('position','pos','flag'):
                require(type(value) is int and value>=0, 'Invalid '+label+' integer assertion')
            elif key in ('tags','info','genotypes'):
                require(isinstance(value,dict) and len(value)<=64 and all(isinstance(k,str) and k and isinstance(v,(str,bool)) for k,v in value.items()), 'Invalid '+label+' annotation assertions')
            else:
                require(isinstance(value,str) and 0<len(value)<=4096, 'Invalid '+label+' text assertion')
        matched = next((i for i,actual in enumerate(remaining) if _row_matches(actual,row)),None)
        if absent:
            require(matched is None, 'Unexpected '+label+' found: '+repr(row))
        else:
            require(matched is not None, 'Expected '+label+' missing: '+repr(row))
            remaining.pop(matched)


def _assert_sam(expectation, text):
    references, groups, rows = {}, {}, []
    for line in text.splitlines():
        if not line:
            continue
        fields = line.split('\t')
        if line.startswith('@'):
            tags = dict(item.split(':',1) for item in fields[1:] if ':' in item)
            if fields[0] == '@SQ':
                name = tags.get('SN','')
                require(name and name not in references and int(tags.get('LN','0'))>0, 'Invalid SAM reference dictionary')
                references[name] = int(tags['LN'])
            elif fields[0] == '@RG':
                require(tags.get('ID') and tags['ID'] not in groups, 'Missing or duplicate SAM read-group ID')
                groups[tags['ID']] = tags
            continue
        require(len(fields)>=11 and fields[0], 'Malformed SAM alignment record')
        flag, position = int(fields[1]), int(fields[3])
        require(0<=flag<=65535 and position>=0, 'Invalid SAM alignment flag/position')
        require(fields[5]=='*' or re.fullmatch(r'(?:[1-9][0-9]*[MIDNSHP=X])+',fields[5]), 'Invalid SAM CIGAR')
        tags = {}
        for field in fields[11:]:
            parts = field.split(':',2)
            require(len(parts)==3 and len(parts[0])==2 and parts[0] not in tags, 'Malformed or duplicate SAM optional tag')
            tags[parts[0]] = parts[2]
        rows.append({'name':fields[0],'flag':flag,'reference':fields[2],'position':position,'cigar':fields[5],'tags':tags})
    _expected_count(expectation,'records',len(rows),required=True)
    for key, mask, on in (('mapped',4,False),('paired',1,True),('properPairs',2,True),('secondary',256,True),('supplementary',2048,True)):
        _expected_count(expectation,key,sum(bool(row['flag'] & mask)==on for row in rows))
    _expected_count(expectation,'spliced',sum(bool(re.search(r'[0-9]+N',row['cigar'])) for row in rows))
    if 'references' in expectation:
        require(isinstance(expectation['references'],dict) and all(isinstance(k,str) and k and type(v)is int and v>0 for k,v in expectation['references'].items()), 'Invalid expected SAM references')
        require(references==expectation['references'], 'SAM reference dictionary differs')
    if 'samples' in expectation:
        require(isinstance(expectation['samples'],list) and all(isinstance(x,str) and x for x in expectation['samples']), 'Invalid expected SAM sample list')
        require(sorted(set(group.get('SM','') for group in groups.values()))==sorted(expectation['samples']), 'SAM sample metadata differs')
    if 'allReadGroups' in expectation:
        require(expectation['allReadGroups'] is True, 'allReadGroups assertion must be true')
        require(all(row['tags'].get('RG') in groups for row in rows), 'SAM records lack declared read-group tags')
    if 'alignments' in expectation:
        _assert_rows(expectation['alignments'],rows,{'name','reference','position','cigar','flag','tags'},'SAM alignment')


def _assert_vcf(expectation, text):
    require(text.startswith('##fileformat=VCF'), 'VCF file-format header is missing')
    header, samples, rows = None, [], []
    for line in text.splitlines():
        if line.startswith('##') or not line:
            continue
        fields = line.split('\t')
        if line.startswith('#CHROM'):
            require(header is None and fields[:8]==['#CHROM','POS','ID','REF','ALT','QUAL','FILTER','INFO'], 'Malformed or duplicate VCF column header')
            require(len(fields)==8 or (len(fields)>=10 and fields[8]=='FORMAT'), 'VCF sample columns are malformed')
            header, samples = fields, fields[9:]
            require(len(set(samples))==len(samples) and all(samples), 'VCF sample names are missing or repeated')
            continue
        require(header is not None and len(fields)==len(header), 'VCF record columns differ from the header')
        position = int(fields[1])
        require(position>0 and fields[0] and fields[3] and fields[4], 'Malformed VCF locus or alleles')
        info = {}
        for entry in ([] if fields[7]=='.' else fields[7].split(';')):
            pair = entry.split('=',1)
            require(pair[0] and pair[0] not in info, 'Malformed or duplicate VCF INFO field')
            info[pair[0]] = pair[1] if len(pair)==2 else True
        genotypes = {}
        if samples:
            formats = fields[8].split(':')
            if 'GT' in formats:
                at = formats.index('GT')
                for sample, value in zip(samples,fields[9:]):
                    parts = value.split(':')
                    genotypes[sample] = parts[at] if at<len(parts) else '.'
        rows.append({'chrom':fields[0],'pos':position,'ref':fields[3],'alt':fields[4],'filter':fields[6],'info':info,'genotypes':genotypes})
    require(header is not None, 'VCF column header is missing')
    _expected_count(expectation,'records',len(rows),required=True)
    if 'samples' in expectation:
        require(isinstance(expectation['samples'],list) and all(isinstance(x,str) and x for x in expectation['samples']), 'Invalid expected VCF sample list')
        require(samples==expectation['samples'], 'VCF sample columns differ')
    allowed = {'chrom','pos','ref','alt','filter','info','genotypes'}
    if 'variants' in expectation:
        _assert_rows(expectation['variants'],rows,allowed,'VCF variant')
    if 'absentVariants' in expectation:
        _assert_rows(expectation['absentVariants'],rows,allowed,'VCF variant',absent=True)


def _assert_output(expectation, result):
    common = {'output','field','kind','contains','records'}
    by_kind = {'text':set(), 'fasta':{'sequences','ungapped','aligned'}, 'fastq':{'sequences'},
               'sam':{'mapped','paired','properPairs','secondary','supplementary','spliced','references','samples','allReadGroups','alignments'},
               'vcf':{'samples','variants','absentVariants'}}
    require(isinstance(expectation,dict) and expectation.get('kind') in by_kind, 'Unknown output assertion kind')
    require(set(expectation) <= common | by_kind[expectation['kind']], 'Unsupported output assertion')
    item = result['outputs'].get('step-1::'+expectation.get('output',''))
    require(item is not None, 'Expected output was not produced')
    files = item['files']
    field = expectation.get('field')
    require(field in files if field else len(files) == 1, 'Select one manifest field for a grouped output assertion')
    path = Path(files[field] if field else next(iter(files.values())))
    text = _read_check_text(path)
    kind = expectation.get('kind')
    contains = expectation.get('contains', [])
    require(isinstance(contains,list) and len(contains)<=64 and all(isinstance(x,str) and x and len(x)<=4096 for x in contains), 'Invalid text assertions')
    for fragment in contains:
        require(fragment in text, 'Expected text missing from '+path.name+': '+repr(fragment))
    if kind == 'text':
        require(contains and not set(expectation) & {'records','sequences','ungapped','aligned'}, 'Text assertion requires expected content')
        return
    if kind == 'sam':
        _assert_sam(expectation,text)
        return
    if kind == 'vcf':
        _assert_vcf(expectation,text)
        return
    records = _sequence_records(text, kind)
    require(type(expectation.get('records')) is int and expectation['records'] >= 0, 'Sequence assertion requires an expected record count')
    require(len(records) == expectation['records'], 'Unexpected sequence count in '+path.name)
    if 'sequences' in expectation:
        require(records == expectation['sequences'], 'Output sequences differ in '+path.name)
    if 'ungapped' in expectation:
        require({k:v.replace('-','').replace('.','') for k,v in records.items()} == expectation['ungapped'], 'Alignment changed sequence identities or residues')
    if 'aligned' in expectation:
        require(type(expectation['aligned']) is bool and expectation['aligned'], 'aligned assertion must be true')
        require(bool(records) and len({len(v) for v in records.values()}) == 1, 'Alignment rows have different lengths')


def run_pack_checks(root, catalog, output_parent, event=None, cancel=None, backend=None):
    """Run declared self-checks; return a separate truthful native tool report."""
    root = Path(root).resolve()
    event = event or (lambda value: None)
    cancel = cancel or threading.Event()
    installed, discovery_failures = [], []
    # Retained versions are executable reproducibility dependencies and need
    # their own checks. Older integration catalogues contain only ``tools``.
    registry = catalog.get('toolVersions')
    tools = [tool for versions in registry.values() for tool in versions] if registry is not None else list(catalog['tools'].values())
    folders = {tool['packFolder']:pin_for(tool) for tool in tools if tool.get('packFolder')}
    for relative, pin in sorted(folders.items()):
        try:
            pack_root = root/relative
            pack = load_pack(pack_root/'pack.ini')
            require(pack['id']==pin['packId'] and pack['version']==pin['packVersion'] and
                    pack['manifestSha256']==pin['manifestSha256'], 'Pack manifest changed after catalogue discovery')
            if 'workbench-checks' in pack['assets']:
                installed.append((pack_root, pack))
        except Exception as exc:
            discovery_failures.append({'id':pin['packId']+'/check-discovery@'+pin['packVersion'],
                                       'pin':pin, 'status':'failed', 'message':str(exc)})
    if not installed and not discovery_failures:
        return {'success':True, 'passed':0, 'failed':0, 'checks':[], 'message':'No additional pack self-checks are declared.'}
    folder = Path(output_parent)/('pack-checks-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
    _io_path(folder).mkdir()
    engine = Engine(root, catalog, backend=backend) if backend is not None else Engine(root, catalog)
    report = {'schema':1, 'folder':str(folder), 'checks':discovery_failures, 'nativeWindowsExecuted':os.name == 'nt'}
    def tool_event(value):
        if value.get('type') in ('phase','log','error'):
            event(value)
    for pack_root, pack in installed:
        pin = {'packId':pack['id'], 'packVersion':pack['version'], 'manifestSha256':pack['manifestSha256']}
        try:
            specification = _json(_asset(pack_root,pack,'workbench-checks',cancel))
            seen = set()
            for case in specification['checks']:
                if cancel.is_set():
                    raise InterruptedError('Cancelled during pack validation')
                require(isinstance(case,dict) and set(case) <= {'id','workflow','params','inputs','expect'}, 'Unsupported pack check fields')
                identity = case.get('id')
                require(isinstance(identity,str) and 0<len(identity)<=80 and identity not in seen, 'Missing or duplicate pack check ID')
                seen.add(identity)
                name = pack['id']+'/'+identity+'@'+pack['version']
                event({'type':'phase','message':'Checking '+name})
                entry = {'id':name, 'pin':dict(pin), 'status':'failed'}
                try:
                    tool = resolve_tool(catalog, pack['id']+'/'+case['workflow'], pin)
                    inputs, sources = {}, []
                    require(isinstance(case['inputs'],dict), 'Check inputs must name ports')
                    ports = {p['id']:p for p in tool['ports']}
                    for port_id, members in case['inputs'].items():
                        require(port_id in ports and isinstance(members,list) and len(members)<=64, 'Unknown or invalid check input port')
                        port = ports[port_id]
                        inputs[port_id] = []
                        for member in members:
                            require(isinstance(member,dict) and set(member)==set(port['manifestInputs']), 'Fixture fields do not match the port')
                            source_id = 'input-'+str(len(sources)+1)
                            files = {key:str(_asset(pack_root,pack,value,cancel)) for key,value in member.items()}
                            sources.append({'id':source_id,'label':port['label'],'type':port['type'],'files':files})
                            inputs[port_id].append(source_id)
                    graph = {'schema':1,'name':'Pack self-check: '+name,'nodes':[{'id':'step-1','tool':tool['id'],'pin':pin_for(tool),'params':case.get('params',{}),'inputs':inputs}], 'sources':sources,'nextNode':2,'nextSource':len(sources)+1}
                    # Keep graph runs beside this report, as starter checks do.
                    # Nesting them below pack-checks adds an unnecessary path
                    # component to native working directories. Engine.prepare
                    # still allocates each run exclusively, and the report
                    # retains its exact result-folder/provenance references.
                    plan = engine.prepare(graph,output_parent,cancel=cancel)
                    result = engine.execute(plan,event=tool_event,cancel=cancel)
                    entry['folder'] = result.get('folder',plan['folder'])
                    require(result.get('success') is True and result['status']=='success', 'Tool did not complete: '+str(result.get('message',result.get('status'))))
                    expected = case.get('expect')
                    require(isinstance(expected,list) and 1<=len(expected)<=32, 'A check must assert expected outputs')
                    for expectation in expected:
                        _assert_output(expectation,result)
                    entry['status'] = 'passed'
                except Exception as exc:
                    entry['message'] = str(exc)
                report['checks'].append(entry)
                event({'type':'log','message':entry['status'].upper()+': '+name+(' — '+entry['message'] if 'message' in entry else '')})
        except Exception as exc:
            report['checks'].append({'id':pack['id']+'/check-specification@'+pack['version'],
                                     'pin':dict(pin),'status':'failed','message':str(exc)})
    report['passed'] = sum(c['status']=='passed' for c in report['checks'])
    report['failed'] = len(report['checks'])-report['passed']
    report['cancelled'] = cancel.is_set()
    report['success'] = report['failed']==0 and not report['cancelled']
    report['message'] = str(report['passed'])+' of '+str(len(report['checks']))+' additional pack checks passed.'
    write_json(folder/'pack-checks.json',report)
    return report
