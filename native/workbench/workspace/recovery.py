"""Verified completed-step restart into a new result folder.

This is local integrity evidence, not publisher authentication or a checkpoint
inside a scientific executable. Earlier result folders are always read-only.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


def _engine():
    try:
        from . import engine
    except ImportError:
        import engine
    return engine


def _load(path, maximum):
    engine = _engine()
    ordinary = engine._ordinary(path)
    if engine._io_path(ordinary).stat().st_size > maximum:
        raise ValueError('The selected restart record exceeds its size limit.')
    raw = engine._io_path(ordinary).read_bytes()
    value = json.loads(raw.decode('utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Invalid restart record.')
    return value, hashlib.sha256(raw).hexdigest()


def _source(folder):
    engine = _engine()
    folder = Path(folder).absolute()
    plan, _ = _load(folder / 'plan.json', 16 * 1024 * 1024)
    run, run_hash = _load(folder / 'run.json', 64 * 1024 * 1024)
    claimed = plan.get('sha256')
    unhashed = {key: value for key, value in plan.items() if key != 'sha256'}
    if (claimed != hashlib.sha256(engine.canonical(unhashed).encode('utf-8')).hexdigest()
            or run.get('planSha256') != claimed or run.get('id') != plan.get('id')
            or engine._resolved_path(plan.get('folder', '')) != engine._resolved_path(folder)
            or not isinstance(run.get('nodes'), list) or not isinstance(plan.get('nodes'), list)):
        raise ValueError('The earlier result does not match its frozen plan.')
    ids = [entry.get('id') for entry in run['nodes'] if isinstance(entry, dict)]
    if len(ids) != len(run['nodes']) or len(ids) != len(set(ids)):
        raise ValueError('The earlier result has invalid or repeated step records.')
    return plan, run, run_hash


def _contract(plan, node):
    """Include exact source bytes/provenance and dependency identities, not labels."""
    sources = {source['id']: source for source in plan['graph']['sources']}
    inputs = {}
    for refs in node['inputs'].values():
        for ref in refs:
            if ref in sources:
                source = sources[ref]
                files = {}
                for role, path in source.get('files', {}).items():
                    evidence = plan['inputs'][path]
                    files[role] = {key: evidence.get(key) for key in ('path', 'bytes', 'sha256', 'reference')}
                inputs[ref] = {'type': source['type'], 'state': source.get('state', {}), 'files': files}
    return {'tool': node['tool'], 'params': node['params'], 'inputs': node['inputs'],
            'dependencies': node['dependencies'], 'validationTools': node.get('validationTools', {}),
            'sources': inputs, 'batch': plan.get('batch'), 'project': plan.get('project')}


def unsupported_reason(tool):
    # These published adapters consume descriptor-named database files, sibling
    # reports/distributions, or return a descriptor for an undeclared directory
    # product. Hashing the JSON itself cannot close that dependency inventory.
    if tool.get('packId') in {'kraken2', 'bracken'}:
        return ('This operation uses external resource descriptors without a complete restart dependency inventory; '
                'run it again so its adapter verifies the actual resources.')
    if any(port.get('type') == 'directory' for port in [*tool.get('ports', []), *tool.get('outputs', [])]):
        return 'Directory-valued resources do not yet have a complete restart inventory; run this step again.'
    return None


def verify_tool_bytes(owner, node, cancel=None):
    """A reused operation bypasses the bridge, so verify declared code/assets here."""
    engine = _engine()
    tool = node['tool']
    owner._verify_manifest(tool)
    if tool.get('builtin'):
        return
    try:
        from .catalog import parse_pack
    except ImportError:
        from catalog import parse_pack
    folder = owner.app_root / tool['packFolder']
    manifest = parse_pack(engine._io_path(folder / 'pack.ini').read_text(encoding='utf-8'))
    for item in [*manifest['tools'].values(), *manifest['assets'].values()]:
        path = engine._ordinary(engine._safe_relative(folder, item['path']))
        if engine.digest_file(path, cancel) != item['sha256']:
            raise ValueError('Installed tool or asset integrity changed: ' + item['path'])
    if node.get('validationTools', {}).get('samtools'):
        owner._samtools(node)
        selection = node['validationTools']['samtools']
        helper = owner._tool({'tool': selection['operation'], 'pin': selection['pin']})
        if engine.pin_for(helper) != engine.pin_for(tool):
            verify_tool_bytes(owner, {'tool': helper}, cancel)


def _inventory(plan, node, entry, cancel):
    engine = _engine()
    if (entry.get('tool') != node['tool']['id'] or entry.get('pin') != engine.pin_for(node['tool'])
            or entry.get('inputs') != node['inputs']):
        raise ValueError('The completed step does not match its exact tool pin.')
    old_root = engine._resolved_path(plan['folder'])
    step_root = old_root / engine.display_id(node['id'])
    actual = engine._resolved_path(entry.get('folder', step_root))
    if not actual.is_relative_to(step_root):
        raise ValueError('A completed output is outside its original step folder.')
    expected_refs = {node['id'] + '::' + output['id'] for output in node['tool'].get('outputs', [])}
    if not expected_refs or set(entry.get('outputs', {})) != expected_refs:
        raise ValueError('The completed step output inventory is incomplete.')
    inventory = {}
    for output in node['tool']['outputs']:
        ref = node['id'] + '::' + output['id']
        item = entry['outputs'][ref]
        if (set(item.get('files', {})) != set(output['files']) or set(item.get('sha256', {})) != set(output['files'])
                or item.get('type') != output['type'] or item.get('state', {}) != output.get('state', {})
                or item.get('id') != ref or item.get('producer') != node['id']
                or item.get('manifestOutputs') != output.get('manifestOutputs', list(output['files']))):
            raise ValueError('A completed output no longer matches its declaration.')
        files = {}
        for key, relative in output['files'].items():
            path = engine._ordinary(item['files'][key])
            if path != engine._resolved_path(engine._safe_relative(actual, relative)):
                raise ValueError('A completed output path does not match its declaration.')
            checksum = engine.digest_file(path, cancel)
            if checksum != item['sha256'][key]:
                raise ValueError('A completed output changed: ' + ref)
            files[key] = {'path': str(path), 'relative': relative, 'sha256': checksum,
                          'bytes': engine._io_path(path).stat().st_size}
        inventory[ref] = {'descriptor': copy.deepcopy(item), 'files': files}
    return inventory


def review(owner, candidate, source, cancel=None):
    engine = _engine()
    expected = source if isinstance(source, dict) else None
    folder = expected.get('sourceFolder') if expected else source
    old_plan, old_run, run_hash = _source(folder)
    old_nodes = {node['id']: node for node in old_plan['nodes']}
    old_entries = {entry['id']: entry for entry in old_run['nodes']}
    result = {'schema': 1, 'sourceFolder': str(engine._resolved_path(folder)),
              'sourceRunId': old_run['id'], 'sourcePlanSha256': old_plan['sha256'],
              'sourceRunSha256': run_hash, 'nodes': [],
              'scope': 'Verified complete-step output copies; no within-tool checkpoint resume.'}
    reused = set()
    for node in candidate['nodes']:
        identity = node['id']
        decision = {'id': identity, 'action': 'run', 'reason': 'No verified completed step is available.'}
        old, entry = old_nodes.get(identity), old_entries.get(identity)
        if any(dependency not in reused for dependency in node['dependencies']):
            decision['reason'] = 'An upstream step must run again.'
        elif unsupported_reason(node['tool']):
            decision['reason'] = unsupported_reason(node['tool'])
        elif old is None or entry is None or entry.get('status') != 'success':
            pass
        elif engine.canonical(_contract(old_plan, old)) != engine.canonical(_contract(candidate, node)):
            decision['reason'] = 'Inputs, reference evidence, exact tool, parameters or dependencies changed.'
        elif node['tool'].get('builtin'):
            # Built-in reports embed original result paths; reconstruct them for
            # this new result even when their scientific source bytes match.
            decision['reason'] = 'Rebuild the report with this result folder’s output paths.'
        else:
            try:
                verify_tool_bytes(owner, node, cancel)
                inventory = _inventory(old_plan, old, entry, cancel)
            except InterruptedError:
                raise
            except (ValueError, OSError) as exc:
                decision['reason'] = str(exc)
            else:
                decision.update(action='reuse', reason='Exact completed output bytes and dependencies verified.',
                                outputs=inventory)
                if entry.get('referenceIndex'):
                    decision['referenceIndex'] = copy.deepcopy(entry['referenceIndex'])
                reused.add(identity)
        result['nodes'].append(decision)
    if expected and engine.canonical(expected) != engine.canonical(result):
        raise ValueError('The reviewed restart evidence changed. Review the earlier result again.')
    return result


def verify_source(evidence):
    plan, _, run_hash = _source(evidence['sourceFolder'])
    if plan['sha256'] != evidence['sourcePlanSha256'] or run_hash != evidence['sourceRunSha256']:
        raise ValueError('The earlier restart record changed after this plan was frozen.')


def copy_outputs(decision, step_folder, cancel):
    """Copy into the new private result, verifying the same stream and destination."""
    engine = _engine()
    result = {}
    for ref, item in decision['outputs'].items():
        descriptor = copy.deepcopy(item['descriptor'])
        descriptor['files'] = {}
        for key, evidence in item['files'].items():
            source = engine._ordinary(evidence['path'])
            target = engine._safe_relative(step_folder, evidence['relative'])
            engine._io_path(target.parent).mkdir(parents=True, exist_ok=True)
            checksum, size = hashlib.sha256(), 0
            with open(engine._io_path(source), 'rb') as reader, open(engine._io_path(target), 'xb') as writer:
                for part in iter(lambda: reader.read(1024 * 1024), b''):
                    if cancel.is_set():
                        raise InterruptedError('Cancelled while copying a verified completed step.')
                    writer.write(part); checksum.update(part); size += len(part)
            if (checksum.hexdigest() != evidence['sha256'] or size != evidence['bytes']
                    or engine.digest_file(target, cancel) != evidence['sha256']):
                raise ValueError('A restart output changed before its verified copy completed: ' + ref)
            descriptor['files'][key] = str(target)
        result[ref] = descriptor
    return result
