"""Independent application checks and optional, pinned starter science checks.

Application integrity is useful even when no packs are installed. Scientific
evidence is separately attributed to the exact pack versions and test fixture;
static PE inspection is never reported as native Windows tool execution.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import threading
import uuid

from catalog import load_catalog, resolve_tool
from engine import Engine, NativeBackend, digest_file, write_json, _io_path, _resolved_path
from example import make_example
from pack_checks import _assert_sam, _assert_vcf, _read_check_text
from verify_installation import inside, require, run_checks, strict_json


def _profile(root):
    path = inside(root, 'workspace/starter-check-profile.json')
    value = strict_json(path, limit=256*1024)
    require(isinstance(value,dict) and value.get('schema') == 1 and value.get('id') == 'starter-1',
            'Unsupported starter check profile')
    require(isinstance(value.get('packs'),list) and len(value['packs']) == 3, 'Starter check must identify three exact packs')
    require({p.get('id') for p in value['packs']} == {'align','bam','variants'}, 'Unexpected starter pack identities')
    require(set(value.get('fixtures',{})) == {'reference.fa','reads1.fastq','reads2.fastq','truth.json'},
            'Unexpected starter fixture inventory')
    return value


def run_starter_checks(root, catalog, output_parent, event=None, cancel=None, backend=None):
    """Run only the externally pinned starter profile; do not require its packs.

Installed packs with newer manifests retain their own independent self-checks.
The legacy starter packs predate that format, so this profile supplies a check
without modifying an already distributed pack or invalidating saved pipelines.
"""
    root = Path(root).resolve()
    event = event or (lambda value: None)
    cancel = cancel or threading.Event()
    report = {'schema':1, 'scope':'starter-packs', 'checks':[], 'passed':0, 'failed':0,
              'skipped':0, 'nativeWindowsExecuted':False, 'analysisExecuted':False}
    if not (root/'workspace/starter-check-profile.json').is_file():
        report.update(success=True, skipped=1, message='No starter scientific check profile is installed.')
        report['checks'].append({'id':'starter/profile','status':'skipped','message':report['message']})
        return report
    entry = {'id':'starter/align-prepare-call-report', 'status':'failed'}
    try:
        profile = _profile(root)
        report['profile'] = profile['id']
        report['packs'] = profile['packs']
        selected = {}
        operations = {'align':'align/paired-end','bam':'bam/prepare','variants':'variants/call'}
        unavailable = []
        for pin in profile['packs']:
            identity = operations[pin['id']]
            try:
                selected[identity] = resolve_tool(catalog, identity,
                    {'packId':pin['id'],'packVersion':pin['version'],'manifestSha256':pin['manifestSha256']})
            except ValueError:
                unavailable.append(pin['id']+' '+pin['version'])
        if unavailable:
            entry.update(status='skipped', message='Optional starter check skipped: install its exact packs in Manage tools: '+', '.join(unavailable)+'. Other installed packs are checked separately.')
        else:
            for name, expected in profile['fixtures'].items():
                require(digest_file(inside(root,'examples/starter/'+name),cancel) == expected,
                        'Starter check fixture differs: '+name)
            if cancel.is_set():
                raise InterruptedError('Cancelled before starter scientific checks')
            # Build with exact selected versions, independently of newer installed
            # defaults. Graph pins remain authoritative throughout execution.
            import copy
            profile_catalog = copy.deepcopy(catalog)
            for pin in profile['packs']:
                for identity in ('align/paired-end','bam/prepare','variants/call','variants/statistics'):
                    if identity.split('/')[0] == pin['id']:
                        profile_catalog['tools'][identity] = resolve_tool(catalog,identity,
                            {'packId':pin['id'],'packVersion':pin['version'],'manifestSha256':pin['manifestSha256']})
            graph = make_example(root,profile_catalog)
            graph['name'] = 'Starter scientific installation check'
            engine = Engine(root,catalog,backend=backend) if backend is not None else Engine(root,catalog)
            event({'type':'phase','message':'Checking minimap2, SAMtools and BCFtools on synthetic reads'})
            plan = engine.prepare(graph,output_parent,cancel=cancel)
            # Running on a reference adapter is explicitly different evidence.
            report['analysisExecuted'] = True
            report['nativeWindowsExecuted'] = os.name == 'nt' and isinstance(engine.backend,NativeBackend)
            record = engine.execute(plan,event=event,cancel=cancel)
            entry['folder'] = record.get('folder',plan['folder'])
            require(record.get('success') is True, 'Starter pipeline did not complete: '+str(record.get('message',record.get('status'))))
            def output(reference, field):
                return _io_path(record['outputs'][reference]['files'][field])
            _assert_sam(profile['expect']['alignment'],_read_check_text(output('step-1::sam','sam')))
            _assert_vcf(profile['expect']['variants'],_read_check_text(output('step-3::variants','variants')))
            require(output('step-2::bam','bam').stat().st_size > 0, 'Prepared BAM is empty')
            require(output('step-5::report','report').stat().st_size > 0, 'Combined report is empty')
            entry['status'] = 'passed'
            entry['evidence'] = 'native-windows' if report['nativeWindowsExecuted'] else 'reference-backend'
    except Exception as exc:
        entry['message'] = str(exc) or type(exc).__name__
    report['checks'].append(entry)
    report['passed'] = int(entry['status'] == 'passed')
    report['failed'] = int(entry['status'] == 'failed')
    report['skipped'] = int(entry['status'] == 'skipped')
    report['cancelled'] = cancel.is_set()
    report['success'] = report['failed'] == 0 and not report['cancelled']
    report['message'] = entry.get('message') or 'Starter scientific check passed.'
    event({'type':'log','message':entry['status'].upper()+': '+entry['id']+' — '+report['message']})
    return report


def run_core_checks(root, catalog, output_parent, event=None, cancel=None, backend=None):
    """Return an application report plus separately labelled starter evidence."""
    root = Path(root).resolve()
    event = event or (lambda value: None)
    cancel = cancel or threading.Event()
    parent = _resolved_path(output_parent)
    require(_io_path(parent).is_dir(), 'Choose an existing output folder for installation checks')
    folder = parent/('installation-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
    _io_path(folder).mkdir()
    event({'type':'run','folder':str(folder)})
    event({'type':'phase','message':'Checking application and installed pack integrity'})
    core = run_checks(root,event=event,cancel=cancel,catalog=catalog)
    write_json(folder/'core-checks.json',core)
    starter = {'success':True,'passed':0,'failed':0,'skipped':1,'checks':[],
               'analysisExecuted':False,'nativeWindowsExecuted':False,
               'message':'Scientific checks were not run because application checks did not pass.'}
    if core['success'] and not cancel.is_set():
        starter = run_starter_checks(root,catalog,folder,event=event,cancel=cancel,backend=backend)
    write_json(folder/'starter-checks.json',starter)
    report = {'schema':1,'folder':str(folder),'core_checks':core,'starter_checks':starter,
              'success':core['success'] and starter['success'] and not cancel.is_set(),
              'cancelled':cancel.is_set(), 'passed':core['passed']+starter['passed'],
              'failed':core['failed']+starter['failed'], 'skipped':starter.get('skipped',0),
              'nativeWindowsExecuted':starter['nativeWindowsExecuted'],
              'analysisExecuted':starter['analysisExecuted']}
    report['message'] = str(core['passed'])+' of '+str(len(core['checks']))+' application/integrity checks passed. '+starter['message']
    write_json(folder/'installation-checks.json',report)
    return report
