#!/usr/bin/env python3
"""Validate the exact 0.11.0-to-0.16.0 update on disposable native Windows roots.

The shared 0.9 gate helpers supply the same reference/provenance oracles. This
new gate pins the published 0.11.0 starter, accepts one exact 0.16.0 candidate hash,
and checks preservation plus actual offline native scientific/CWL execution.
It does not claim updater folder-picker interaction or live reference retrieval.
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
from build_update_0160 import (ALIGN_SHA, BASELINE_SHA, SOURCE_COMMIT, STARTER_SHA,
                               pack_hashes, verify_inventory)
from check_update_090_windows import (PACK_SHA, read_json, preserved_files,
                                      synthetic_reference)
from check_references_windows import PrivateHost, require, sha256, write_json
from check_results_windows import scientific_checks



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
                ('provider', 'release', 'species', 'assembly', 'assembly_accession',
                 'receipt_path', 'receipt_sha256', 'downloaded_at')),
            'Frozen run changed the preserved reference identity or receipt.')
    # 0.11 methods used the provider ID. The independently tested 0.15/0.16
    # provenance contract additionally retains and displays its human name.
    # Keep the original ID assertions above, and check the actual frozen name
    # instead of requiring old presentation text from a newer application.
    if cwl:
        require(frozen.get('provider_name') == record['provider_name'],
                'Updated run lost the preserved provider display name.')
    provider_text = frozen.get('provider_name') or frozen['provider']
    methods = (folder / 'methods-completed.txt').read_text(encoding='utf-8')
    for token in (provider_text, 'release ' + record['release'], record['species']['name'],
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



def import_pack(host, archive):
    host.call('packs/import', {'path': str(archive.resolve())})
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        operation = host.call('packs/status')['operation']
        if not operation.get('active'):
            require(operation.get('status') == 'completed' and operation.get('success'),
                    'Explicit optional pack import failed: ' + json.dumps(operation))
            return
        time.sleep(.05)
    raise TimeoutError('Explicit optional pack import did not finish.')


def missing_index_guidance(base, target, evidence, report):
    # Obtain an ordinary user-created index graph from the exact accepted app,
    # then ask the upgraded installation to review that same explicit pin.
    target_host = PrivateHost(target, evidence, 'accepted-index-definition', offline=True)
    try:
        target_host.call('init')
        graph = target_host.call('workspace/tool', {'toolId': 'align/build-sr-index'})['graph']
        source = graph['sources'][0]
        files = {field['id']: str(base / 'examples/starter/reference.fa') for field in source['fields']}
        graph = target_host.call('model', {'action': 'apply_fields', 'payload': {
            'sourceId': source['id'], 'files': {source['id']: files}}})['graph']
    finally:
        target_host.close()
    host = PrivateHost(base, evidence, 'missing-index-pack-review', offline=True)
    try:
        state = host.call('init')
        require('align/build-sr-index' not in state['catalog']['tools'],
                'Application update implicitly installed the optional index operation.')
        review = host.call('review', {'graph': graph, 'output_folder': str(evidence)})
        detail = json.dumps(review)
        require(not review['valid'] and 'align/build-sr-index' in detail and '0.4.1' in detail and
                'Install the original pack or explicitly select another version' in detail,
                'Missing exact index pack does not provide actionable installation/version guidance: ' + detail)
        require(host.call('state')['graph'] == state['graph'], 'Dependency review mutated the current graph.')
        write_json(evidence / 'missing-index-pack-review.json', review)
    finally:
        host.close()
    report['checks'].append('Reviewing an explicitly pinned reusable-index operation without align 0.4.1 blocks execution, names the exact version and advises explicit pack installation without changing the draft.')
    return graph


def migration(args, report):
    base, target, update = args.base_app_root.resolve(), args.app_root.resolve(), args.update_root.resolve()
    evidence = args.report.resolve().parent
    external = base.parent / 'external references'
    require(os.name == 'nt', 'This release gate requires native Windows; unavailable is not a pass.')
    require(args.source_commit == SOURCE_COMMIT and args.starter_sha256 == STARTER_SHA,
            'This gate requires the exact accepted 0.16.0 source and starter.')
    require(base != target and not base.is_relative_to(target) and not update.is_relative_to(base),
            'Baseline, accepted starter and updater must be separate disposable roots.')
    require(sha256(args.baseline_archive) == BASELINE_SHA and sha256(args.starter_archive) == args.starter_sha256 and
            sha256(args.update_archive) == args.update_sha256 and sha256(args.optional_pack_archive) == PACK_SHA and
            sha256(args.align_pack_archive) == ALIGN_SHA,
            'The native gate input archive does not match its frozen identity.')
    baseline_manifest, target_manifest = read_json(base / 'manifest.json'), read_json(target / 'manifest.json')
    require(baseline_manifest['version'] == '0.11.0' and target_manifest['version'] == '0.16.0', 'Unexpected app versions.')
    verify_inventory(base, baseline_manifest['files'])
    verify_inventory(target, target_manifest['files'])
    for name in ('workspace/catalog-sources.json', 'workspace/setup-profile.json'):
        require((base / name).read_bytes() == (target / name).read_bytes(),
                'The patch changed published production trust or pack selection: ' + name)
    inventory = read_json(update / 'update-inventory.json')['files']
    verify_inventory(update, inventory)
    recipe = read_json(update / 'update/update-manifest.json')
    require(recipe['base_manifest_sha256'] == sha256(base / 'manifest.json') and
            recipe['target_manifest_sha256'] == sha256(target / 'manifest.json'), 'Updater targets different core manifests.')
    report['checks'].append('Frozen baseline, accepted target and updater inventories match the exact archives and manifest identities.')
    record = synthetic_reference(base, external)
    host = PrivateHost(base, evidence, 'baseline-offline-host', offline=True)
    try:
        require(host.call('init')['app_version'] == '0.11.0', 'Published baseline private host is not 0.11.0.')
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
        report['baselineRunId'] = host.call('history')['runs'][0]['run_id']
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
        host.call('setup/start', {'profile': 'starter'})
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            setup = host.call('setup/status')
            if not setup['operation']['active']:
                require(setup['operation']['status'] == 'completed', 'Baseline Starter setup did not complete offline.')
                break
            time.sleep(.05)
        else:
            raise TimeoutError('Baseline Starter setup did not finish.')
        require(setup['selection']['profile'] == 'starter', 'Baseline did not persist the Starter selection.')
    finally:
        host.close()
    saved = read_json(base / 'user-data/saved.json')
    require(len(saved['presets']) == len(saved['pipelines']) == 1 and saved['presets'][0]['pin'] == optional_pin,
            'Baseline did not save separate settings and exact pipeline/optional-pack pins.')
    persisted_setup = read_json(base / 'user-data/tool-setup.json')
    require(persisted_setup['queue'] and all(row['status'] == 'completed' for row in persisted_setup['queue']),
            'Baseline setup queue did not persist its exact completed pins.')
    preserved = preserved_files(base, external)
    write_json(evidence / 'preservation-before.json', preserved)
    report['checks'].append('Published 0.11.0 imports the exact optional reads pack, executes a real reference run, and saves independent settings and pipeline pins offline.')
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
    report['checks'].append('Native updater installs 0.16.0 and returns already-installed on repeat; every installed core file equals the accepted starter.')
    after = preserved_files(base, external)
    write_json(evidence / 'preservation-after.json', after)
    changes = {name: {'before': value, 'after': after.get(name)} for name, value in preserved.items() if after.get(name) != value}
    additions = {name: value for name, value in after.items() if name not in preserved}
    report['preservation'] = {'files': len(preserved), 'changes': changes, 'additions': additions,
                              'fixtureNotice': record['fixtureNotice']}
    require(not changes and all(name == 'user-data/session.lock' and value == hashlib.sha256(b'\0').hexdigest()
                                for name, value in additions.items()), 'Update changed existing user files or added unexpected user data.')
    report['checks'].append('Starter and optional packs, saved settings/pins, completed setup selection/queue, existing real results, local registry/receipt and external reference bytes survive unchanged.')
    host = PrivateHost(base, evidence, 'updated-offline-host', offline=True)
    try:
        require(host.call('init')['app_version'] == '0.16.0', 'Updated private host did not start 0.16.0.')
        resumed_setup = host.call('setup/status')
        require(resumed_setup['selection'] == persisted_setup['selection']
                and resumed_setup['operation']['status'] == 'completed',
                'Updated host changed persisted setup selection or completion.')
        require(read_json(base / 'user-data/tool-setup.json') == persisted_setup,
                'Updated host changed the persisted setup queue or publisher identity.')
        state = host.call('workspace/tool', {'toolId': saved['presets'][0]['tool']})
        require(state['graph']['nodes'][0]['pin'] == optional_pin,
                'Updated tool selection did not resolve the preserved exact optional pack.')
        host.call('load', {'kind': 'preset', 'id': saved['presets'][0]['id'], 'node_id': state['graph']['nodes'][0]['id']})
        require(host.call('state')['graph']['nodes'][0]['pin'] == optional_pin, 'Updated host changed saved optional pack pin.')
        state = host.call('load', {'kind': 'pipeline', 'id': saved['pipelines'][0]['id']})
        require([node['pin'] for node in state['graph']['nodes']] ==
                [node['pin'] for node in saved['pipelines'][0]['graph']['nodes']], 'Updated host changed saved workflow pins.')
        legacy = host.call('results/search', {'query': 'SAMtools'})
        require(any(item['run_id'] == report['baselineRunId'] for item in legacy['runs']),
                'Upgraded result search lost the actual 0.11 reference analysis.')
        summary = host.call('results/summary', {'id': report['baselineRunId']})
        require(summary['status'] == 'completed' and not summary['metrics'] and not summary['failures'] and
                summary['details'] and 'not a QC pass/fail' in summary['interpretation'],
                'Legacy reference-only result invented measurements or lost its successful recorded state.')
        write_json(evidence / 'legacy-reference-summary.json', summary)
        report['legacyResultSummary'] = {'id': report['baselineRunId'], 'status': summary['status'], 'metrics': len(summary['metrics'])}
        report['updatedReferenceRun'] = local_reference_run(host, base, evidence, record, 'updated-reference-run', cwl=True)
    finally:
        host.close()
    report['checks'].append('Updated host reloads exact saved pins, searches and honestly summarizes the actual 0.11 result, selects its preserved compatible reference, and executes offline with provenance in CWL and completed methods.')
    # The exact target manifest describes the separately bundled align 0.4.1
    # pack, but the application-only updater must not inject it into old installs.
    require(not (base / 'packs/align-0.4.1').exists(), 'Core update silently installed an optional pack.')
    packs_before_import = pack_hashes(base)
    core_check = subprocess.run([str(base / 'runtime/python/python.exe'), '-I',
                                 str(base / 'workspace/verify_installation.py'), '--app-root', str(base)],
                                capture_output=True, timeout=120, cwd=base)
    (evidence / 'without-index-pack-installation.stdout.txt').write_bytes(core_check.stdout)
    (evidence / 'without-index-pack-installation.stderr.txt').write_bytes(core_check.stderr)
    require(core_check.returncode == 0, 'Additional pack absence incorrectly fails upgraded installation checks: ' +
            core_check.stderr.decode('utf-8', 'replace'))
    reports = list((base / 'results').glob('installation-*/installation-checks.json'))
    require(len(reports) == 1, 'Expected one independent post-update installation report.')
    integrity = read_json(reports[0])
    require(integrity['success'] and integrity['passed'] == 7 and integrity['failed'] == 0,
            'Upgraded core or existing installed packs fail integrity without optional align 0.4.1.')
    write_json(evidence / 'without-index-pack-installation.json', integrity)
    report['withoutAdditionalPack'] = {'present': False, 'installationChecks': integrity['passed'],
                                        'packFiles': len(packs_before_import)}
    report['checks'].append('The upgraded app passes all seven real installation checks with align 0.4.1 absent; additional pack declarations do not change core ownership.')
    index_graph = missing_index_guidance(base, target, evidence, report)
    host = PrivateHost(base, evidence, 'manual-index-pack-import', offline=True)
    try:
        host.call('init')
        before_graph = host.call('state')['graph']
        import_pack(host, args.align_pack_archive)
        require(host.call('state')['graph'] == before_graph,
                'Explicit independent pack import changed the current saved-pin graph.')
        ready = host.call('review', {'graph': index_graph, 'output_folder': str(evidence)})
        require(ready['valid'], 'Explicitly imported exact index pack did not resolve its operation: ' + json.dumps(ready))
        write_json(evidence / 'explicit-index-pack-ready.json', ready)
    finally:
        host.close()
    after_import = pack_hashes(base)
    require(all(after_import.get(name) == digest for name, digest in packs_before_import.items()),
            'Explicit index pack import changed an existing pack.')
    expected_added = {name: digest for name, digest in pack_hashes(target).items()
                      if name.startswith('packs/align-0.4.1/')}
    actual_added = {name: digest for name, digest in after_import.items() if name not in packs_before_import}
    # The installer writes a compatibility receipt outside immutable pack folders.
    require(actual_added == expected_added, 'Explicit imported pack differs from the accepted Starter pack.')
    report['manualAdditionalPackImport'] = {'sha256': ALIGN_SHA, 'addedFiles': len(actual_added),
                                           'existingPackFilesPreserved': len(packs_before_import)}
    report['checks'].append('Explicit separate align 0.4.1 import installs its exact 43 files alongside preserved versions and resolves the reviewed index operation without changing a graph pin.')
    curated_dir = evidence / 'curated'
    curated_dir.mkdir()
    curated_path = curated_dir / 'native-curated.json'
    command = [str(base / 'runtime/python/python.exe'), '-I', str(Path(__file__).with_name('check_curated_windows.py')),
               '--app-root', str(base), '--report', str(curated_path), '--source-commit', SOURCE_COMMIT,
               '--asset-sha256', args.update_sha256, '--asset-name', args.update_archive.name,
               '--app-version', '0.16.0']
    with (curated_dir / 'gate.stdout.txt').open('wb') as stdout, (curated_dir / 'gate.stderr.txt').open('wb') as stderr:
        completed = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=600, cwd=base)
    require(curated_path.is_file(), 'Upgraded curated/results gate did not retain its report.')
    curated = read_json(curated_path)
    report['curated'] = curated
    require(completed.returncode == 0 and curated['success'] and curated['passed'] == 11 and
            curated['failed'] == curated['skipped'] == 0 and curated['nativeGUIValidated'],
            'The actual upgraded installation failed curated workflows or recorded-results GUI checks: ' + str(curated.get('error')))
    report['checks'].append('The same upgraded installation passes the unchanged 11-check curated gate, both known-answer native workflows, result search/reopen/failure diagnosis and six real GUI captures.')
    stable = preserved_files(base, external)
    legacy_files = {name: digest for name, digest in preserved.items() if name.startswith(('results/', 'external/'))}
    require(all(stable.get(name) == digest for name, digest in legacy_files.items()),
            'Using new features changed historical 0.11 scientific results or external reference bytes.')
    report['legacyResultAndReferenceFilesPreservedAfterNewFeatures'] = len(legacy_files)
    report['checks'].append('New curated runs and result interpretation leave every previous 0.11 scientific result and external reference file unchanged.')
    science = evidence / 'post-update-science'
    science.mkdir()
    scientific_checks(base, science, report)
    verify_inventory(update, inventory)
    report['checks'].append('Updater inventories remain intact after execution with its own private runtime.')
    report['nativeWindowsExecuted'] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('base-app-root', 'app-root', 'update-root', 'baseline-archive', 'starter-archive', 'update-archive', 'optional-pack-archive', 'align-pack-archive', 'report'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--update-sha256', required=True)
    parser.add_argument('--starter-sha256', required=True)
    parser.add_argument('--source-commit', required=True)
    args = parser.parse_args()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    report = {'schema': 1, 'sourceCommit': args.source_commit, 'validationCommit': os.environ.get('GITHUB_SHA'),
              'workflowRun': os.environ.get('GITHUB_RUN_ID'),
              'gateSha256': sha256(Path(__file__)), 'startedUtc': datetime.now(timezone.utc).isoformat(),
              'platform': platform.platform(), 'pythonVersion': platform.python_version(),
              'nativeWindowsHost': os.name == 'nt', 'nativeWindowsExecuted': False, 'success': False,
              'baseVersion': '0.11.0', 'appVersion': '0.16.0', 'starterSha256': args.starter_sha256,
              'baselineSha256': BASELINE_SHA, 'updateSha256': args.update_sha256,
              'scope': 'Native updater CLI/private runtime, 0.11 data preservation, legacy result interpretation, optional pack absence and explicit import, curated native science/results GUI, and scientific/CWL checks; no updater picker UI or live reference download.',
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
