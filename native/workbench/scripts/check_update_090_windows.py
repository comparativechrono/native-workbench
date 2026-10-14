#!/usr/bin/env python3
"""Validate the exact 0.8.0-to-0.9.0 update on disposable native Windows roots.

Uses the updater's private runtime, not the installation's interpreter. Reuses
the accepted scientific/CWL oracle after updating. No reference network fetches
or native updater folder-picker interaction are claimed by this focused gate.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import traceback

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_update_090 import SOURCE_COMMIT, STARTER_SHA, BASELINE_SHA, verify_inventory
from check_references_windows import PrivateHost, require, sha256, write_json
from check_results_windows import scientific_checks

PACK_SHA = '2dd05fece8deb2b0178d8b1bc2b6830f175b3fbc2f5a4d48f9c9023cbfe6775b'


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def preserved_files(base, external):
    result = {}
    for prefix, folder in [(name, base / name) for name in ('packs', 'user-data', 'results')] + [('external', external)]:
        for path in sorted(folder.rglob('*')):
            if path.is_file():
                result[prefix + '/' + path.relative_to(folder).as_posix()] = sha256(path)
    return result


def synthetic_reference(base, external):
    """A transparent synthetic receipt fixture, not evidence of a live download."""
    external.mkdir(parents=True)
    genome = external / 'synthetic-reference.fa'
    shutil.copyfile(base / 'examples/starter/reference.fa', genome)
    record = {'schema': 1, 'id': '09000800000000000000000000000001',
              'label': 'Synthetic updater preservation reference',
              'provider': 'synthetic-validation-fixture', 'provider_name': 'Synthetic update fixture',
              'release': '1', 'species': {'id': 'starter', 'name': 'Synthetic starter'},
              'assembly': 'starter-fixture', 'assembly_accession': '',
              'folder': str(external), 'receipt_path': str(external / 'reference.json'),
              'downloaded_at': '2026-10-06T00:00:00Z',
              'fixtureNotice': 'Created by this gate from the packaged synthetic FASTA; not downloaded.',
              'files': [{'id': 'genome', 'kind': 'genome', 'label': 'Genome FASTA',
                         'filename': genome.name, 'path': str(genome),
                         'bytes': genome.stat().st_size, 'sha256': sha256(genome)}]}
    write_json(external / 'reference.json', record)
    record['receipt_sha256'] = sha256(external / 'reference.json')
    data = base / 'user-data/references'
    data.mkdir(parents=True, exist_ok=True)
    write_json(data / 'library.json', {'schema': 1, 'records': [record]})
    return record


def local_reference_run(host, base, evidence, record, label, *, cwl=False):
    listed = host.call('references/list')['local']
    require(any(item['id'] == record['id'] and item['available'] and
                item['receipt_sha256'] == record['receipt_sha256'] for item in listed),
            'Preserved local reference was not available offline.')
    host.call('workspace/tool', {'toolId': 'bam/reference-index'})
    targets = host.call('references/targets', {'record_id': record['id'], 'file_id': 'genome'})['targets']
    require(len(targets) == 1 and targets[0]['type'] == 'reference', 'Local reference lacks compatible input.')
    target = targets[0]
    host.call('references/use', {'record_id': record['id'], 'file_id': 'genome',
                                'source_id': target['source_id'], 'field_id': target['field_id']})
    review = host.call('review')
    require(review['valid'], 'Preserved reference failed review: ' + json.dumps(review.get('issues')))
    output = base / 'results' / label
    output.mkdir(parents=True)
    started = host.call('run', {'output_folder': str(output)})
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        result = host.call('run/get', {'run_id': started['run_id']})
        if result['status'] not in ('preparing', 'running', 'cancelling'):
            break
        time.sleep(.1)
    else:
        raise TimeoutError('Offline native reference indexing did not finish.')
    require(result['status'] == 'completed' and result.get('success'), 'Offline reference analysis failed.')
    folder = Path(result['folder'])
    # Keep the actual run/receipt evidence even if a later oracle assertion
    # fails; a display-name mismatch must remain diagnosable without rerunning.
    write_json(evidence / (label + '-result.json'), result)
    for name in ('plan.json', 'run.json', 'methods-completed.txt', 'reference-provenance.json', 'workflow.cwl'):
        if (folder / name).is_file():
            shutil.copyfile(folder / name, evidence / (label + '-' + name))
    indexes = list(folder.rglob('*.fai'))
    require(len(indexes) == 1, 'Native SAMtools failed to create one private reference index.')
    actual = [(row[0], int(row[1])) for line in indexes[0].read_text(encoding='utf-8').splitlines()
              if (row := line.split('\t'))]
    expected = []
    for line in Path(record['files'][0]['path']).read_text(encoding='utf-8').splitlines():
        if line.startswith('>'):
            expected.append([line[1:].split()[0], 0])
        elif line.strip():
            expected[-1][1] += len(line.strip())
    require(actual == [tuple(row) for row in expected], 'Native reference index differs from FASTA truth.')
    require(not Path(record['files'][0]['path'] + '.fai').exists(), 'Analysis modified external reference directory.')
    plan, run = read_json(folder / 'plan.json'), read_json(folder / 'run.json')
    genome = record['files'][0]
    frozen = plan['references'][genome['path']]
    require(frozen['file']['sha256'] == genome['sha256'] and
            sha256(genome['path']) == genome['sha256'], 'Run lost or changed the preserved reference.')
    require(all(frozen[key] == record[key] for key in
                ('provider', 'release', 'species', 'assembly', 'receipt_path', 'receipt_sha256')),
            'Frozen run changed the preserved reference identity or receipt.')
    # The public provenance contract carries provider ID; provider_name is not
    # copied from the local registry into frozen run evidence in either release.
    methods = (folder / 'methods-completed.txt').read_text(encoding='utf-8')
    for token in (record['provider'], 'release ' + record['release'], record['species']['name'],
                  'assembly ' + record['assembly'], genome['filename']):
        require(token in methods, 'Completed methods lost reference provenance: ' + token)
    if cwl:
        exported = read_json(folder / 'workflow.cwl')
        main = exported['$graph'][0]
        require(exported['cwlVersion'] == 'v1.2' and json.loads(main['nw:references']) == plan['references'] and
                main['nw:execution']['success'] is True and main['nw:planSha256'] == run['planSha256'] and
                run['workflowExport']['sha256'] == sha256(folder / 'workflow.cwl'),
                'Updated reference analysis did not export preserved provenance in successful CWL.')
        shutil.copyfile(folder / 'workflow.cwl', evidence / 'updated-reference-workflow.cwl')
    return {'folder': str(folder), 'nativeWindowsExecuted': True, 'contigs': len(expected),
            'referenceSha256': genome['sha256'], 'runSha256': sha256(folder / 'run.json'), 'cwlChecked': cwl}


def migration(args, report):
    base, target, update = args.base_app_root.resolve(), args.app_root.resolve(), args.update_root.resolve()
    evidence = args.report.resolve().parent
    external = base.parent / 'external references'
    require(os.name == 'nt', 'This release gate requires native Windows; unavailable is not a pass.')
    require(base != target and not base.is_relative_to(target) and not update.is_relative_to(base),
            'Baseline, accepted starter and updater must be separate disposable roots.')
    require(sha256(args.baseline_archive) == BASELINE_SHA and sha256(args.starter_archive) == STARTER_SHA and
            sha256(args.update_archive) == args.update_sha256 and sha256(args.optional_pack_archive) == PACK_SHA,
            'The native gate input archive does not match its frozen identity.')
    baseline_manifest, target_manifest = read_json(base / 'manifest.json'), read_json(target / 'manifest.json')
    require(baseline_manifest['version'] == '0.8.0' and target_manifest['version'] == '0.9.0', 'Unexpected app versions.')
    verify_inventory(base, baseline_manifest['files'])
    verify_inventory(target, target_manifest['files'])
    inventory = read_json(update / 'update-inventory.json')['files']
    verify_inventory(update, inventory)
    recipe = read_json(update / 'update/update-manifest.json')
    require(recipe['base_manifest_sha256'] == sha256(base / 'manifest.json') and
            recipe['target_manifest_sha256'] == sha256(target / 'manifest.json'), 'Updater targets different core manifests.')
    report['checks'].append('Frozen baseline, accepted target and updater inventories match the exact archives and manifest identities.')
    record = synthetic_reference(base, external)
    host = PrivateHost(base, evidence, 'baseline-offline-host', offline=True)
    try:
        require(host.call('init')['app_version'] == '0.8.0', 'Published baseline private host is not 0.8.0.')
        host.call('packs/import', {'path': str(args.optional_pack_archive.resolve())})
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            operation = host.call('packs/status')['operation']
            if not operation.get('active'):
                require(operation.get('status') == 'completed' and operation.get('success'), 'Baseline optional pack import failed.')
                break
            time.sleep(.05)
        else:
            raise TimeoutError('Optional pack import did not finish.')
        report['baselineReferenceRun'] = local_reference_run(host, base, evidence, record, 'existing-reference-run')
        tools = host.call('state')['catalog']['tools'].values()
        reads = next(tool for tool in tools if tool.get('packId') == 'reads')
        state = host.call('workspace/tool', {'toolId': reads['id']})
        node = state['graph']['nodes'][0]
        optional_pin = node['pin']
        host.call('save', {'kind': 'preset', 'name': 'Preserve optional reads settings', 'nodeId': node['id']})
        host.call('workspace/mode', {'mode': 'workflow'})
        first = host.call('model', {'action': 'add_tool', 'payload': {'toolId': 'bam/reference-index'}})['selected']
        second = host.call('model', {'action': 'add_tool', 'payload': {'toolId': 'bam/reference-index'}})['selected']
        source = host.call('model', {'action': 'add_input', 'payload': {'inputType': 'reference'}})['selected']
        host.call('model', {'action': 'connect', 'payload': {'nodeId': first, 'portId': 'reference', 'refs': [source]}})
        host.call('model', {'action': 'connect', 'payload': {'nodeId': second, 'portId': 'reference', 'refs': [first + '::reference']}})
        host.call('save', {'kind': 'pipeline', 'name': 'Preserve connected pinned pipeline'})
    finally:
        host.close()
    saved = read_json(base / 'user-data/saved.json')
    require(len(saved['presets']) == len(saved['pipelines']) == 1 and saved['presets'][0]['pin'] == optional_pin,
            'Baseline did not save separate settings and exact pipeline/optional-pack pins.')
    preserved = preserved_files(base, external)
    write_json(evidence / 'preservation-before.json', preserved)
    report['checks'].append('Published 0.8.0 imports the exact optional reads pack, executes a real reference run, and saves independent settings and pipeline pins offline.')
    report['updateAttempts'] = {}
    command = [str(update / 'runtime/python/python.exe'), '-I',
               str(update / 'update/apply_workspace_update.py'), '--app-root', str(base)]
    for name, expected in [('install', 'installed'), ('repeat', 'already-installed')]:
        result = subprocess.run(command, cwd=update, capture_output=True, timeout=180)
        (evidence / ('update-' + name + '.stdout.txt')).write_bytes(result.stdout)
        (evidence / ('update-' + name + '.stderr.txt')).write_bytes(result.stderr)
        require(result.returncode == 0, 'Native private-runtime updater failed: ' + result.stderr.decode('utf-8', 'replace'))
        value, _ = json.JSONDecoder().raw_decode(result.stdout.decode('utf-8').lstrip())
        require(value['status'] == expected, 'Unexpected native updater transaction status.')
        report['updateAttempts'][name] = value
    require((base / 'manifest.json').read_bytes() == (target / 'manifest.json').read_bytes(),
            'Updated manifest differs from the accepted starter.')
    verify_inventory(base, target_manifest['files'])
    report['coreFilesVerified'] = len(target_manifest['files'])
    report['checks'].append('Native updater installs 0.9.0 and returns already-installed on repeat; every installed core file equals the accepted starter.')
    after = preserved_files(base, external)
    write_json(evidence / 'preservation-after.json', after)
    changes = {name: {'before': value, 'after': after.get(name)} for name, value in preserved.items() if after.get(name) != value}
    additions = {name: value for name, value in after.items() if name not in preserved}
    report['preservation'] = {'files': len(preserved), 'changes': changes, 'additions': additions,
                              'fixtureNotice': record['fixtureNotice']}
    require(not changes and all(name == 'user-data/session.lock' and value == hashlib.sha256(b'\0').hexdigest()
                                for name, value in additions.items()), 'Update changed existing user files or added unexpected user data.')
    report['checks'].append('Starter and optional packs, saved settings/pins, existing real results, local registry/receipt and external reference bytes survive unchanged.')
    host = PrivateHost(base, evidence, 'updated-offline-host', offline=True)
    try:
        require(host.call('init')['app_version'] == '0.9.0', 'Updated private host did not start 0.9.0.')
        state = host.call('workspace/tool', {'toolId': saved['presets'][0]['tool']})
        require(state['graph']['nodes'][0]['pin'] == optional_pin,
                'Updated tool selection did not resolve the preserved exact optional pack.')
        host.call('load', {'kind': 'preset', 'id': saved['presets'][0]['id'], 'node_id': state['graph']['nodes'][0]['id']})
        require(host.call('state')['graph']['nodes'][0]['pin'] == optional_pin, 'Updated host changed saved optional pack pin.')
        state = host.call('load', {'kind': 'pipeline', 'id': saved['pipelines'][0]['id']})
        require([node['pin'] for node in state['graph']['nodes']] ==
                [node['pin'] for node in saved['pipelines'][0]['graph']['nodes']], 'Updated host changed saved workflow pins.')
        report['updatedReferenceRun'] = local_reference_run(host, base, evidence, record, 'updated-reference-run', cwl=True)
    finally:
        host.close()
    report['checks'].append('Updated host reloads exact saved pins, selects the preserved compatible reference, and executes offline with its provenance in CWL and completed methods.')
    science = evidence / 'post-update-science'
    science.mkdir()
    scientific_checks(base, science, report)
    verify_inventory(update, inventory)
    report['checks'].append('Updater inventories remain intact after execution with its own private runtime.')
    report['nativeWindowsExecuted'] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('base-app-root', 'app-root', 'update-root', 'baseline-archive', 'starter-archive', 'update-archive', 'optional-pack-archive', 'report'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--update-sha256', required=True)
    args = parser.parse_args()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    report = {'schema': 1, 'sourceCommit': SOURCE_COMMIT, 'validationCommit': os.environ.get('GITHUB_SHA'),
              'workflowRun': os.environ.get('GITHUB_RUN_ID'), 'startedUtc': datetime.now(timezone.utc).isoformat(),
              'platform': platform.platform(), 'pythonVersion': platform.python_version(),
              'nativeWindowsHost': os.name == 'nt', 'nativeWindowsExecuted': False, 'success': False,
              'baseVersion': '0.8.0', 'appVersion': '0.9.0', 'starterSha256': STARTER_SHA,
              'baselineSha256': BASELINE_SHA, 'updateSha256': args.update_sha256,
              'scope': 'Native updater CLI/private runtime, preservation and offline native scientific/CWL checks; no updater picker UI or live reference download.',
              'networkScope': 'Private-host Python socket operations denied by audit hook; native subprocesses are not OS-firewalled.',
              'checks': [], 'failures': [], 'skips': []}
    try:
        migration(args, report)
        report['success'] = True
    except Exception as error:
        report['failures'].append({'error': str(error), 'traceback': traceback.format_exc()})
    finally:
        report['passed'] = len(report['checks'])
        report['finishedUtc'] = datetime.now(timezone.utc).isoformat()
        write_json(args.report, report)
        print(json.dumps(report, indent=2))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
