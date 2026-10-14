#!/usr/bin/env python3
"""Validate the exact 0.10.1-to-0.11.0 update on disposable native Windows roots.

The shared 0.9 gate helpers supply the same reference/provenance oracles. This
new gate pins the published 0.10.1 starter, accepts one exact 0.11.0 candidate hash,
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
import subprocess
import sys
import time
import traceback

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_update_0110 import BASELINE_SHA, SOURCE_COMMIT, STARTER_SHA, verify_inventory
from check_update_090_windows import (PACK_SHA, read_json, preserved_files,
                                      synthetic_reference, local_reference_run)
from check_references_windows import PrivateHost, require, sha256, write_json
from check_results_windows import scientific_checks


def migration(args, report):
    base, target, update = args.base_app_root.resolve(), args.app_root.resolve(), args.update_root.resolve()
    evidence = args.report.resolve().parent
    external = base.parent / 'external references'
    require(os.name == 'nt', 'This release gate requires native Windows; unavailable is not a pass.')
    require(args.source_commit == SOURCE_COMMIT and args.starter_sha256 == STARTER_SHA,
            'This gate requires the exact accepted 0.11.0 source and starter.')
    require(base != target and not base.is_relative_to(target) and not update.is_relative_to(base),
            'Baseline, accepted starter and updater must be separate disposable roots.')
    require(sha256(args.baseline_archive) == BASELINE_SHA and sha256(args.starter_archive) == args.starter_sha256 and
            sha256(args.update_archive) == args.update_sha256 and sha256(args.optional_pack_archive) == PACK_SHA,
            'The native gate input archive does not match its frozen identity.')
    baseline_manifest, target_manifest = read_json(base / 'manifest.json'), read_json(target / 'manifest.json')
    require(baseline_manifest['version'] == '0.10.1' and target_manifest['version'] == '0.11.0', 'Unexpected app versions.')
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
        require(host.call('init')['app_version'] == '0.10.1', 'Published baseline private host is not 0.10.1.')
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
    report['checks'].append('Published 0.10.1 imports the exact optional reads pack, executes a real reference run, and saves independent settings and pipeline pins offline.')
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
    report['checks'].append('Native updater installs 0.11.0 and returns already-installed on repeat; every installed core file equals the accepted starter.')
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
        require(host.call('init')['app_version'] == '0.11.0', 'Updated private host did not start 0.11.0.')
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
    parser.add_argument('--starter-sha256', required=True)
    parser.add_argument('--source-commit', required=True)
    args = parser.parse_args()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    report = {'schema': 1, 'sourceCommit': args.source_commit, 'validationCommit': os.environ.get('GITHUB_SHA'),
              'workflowRun': os.environ.get('GITHUB_RUN_ID'),
              'gateSha256': sha256(Path(__file__)), 'startedUtc': datetime.now(timezone.utc).isoformat(),
              'platform': platform.platform(), 'pythonVersion': platform.python_version(),
              'nativeWindowsHost': os.name == 'nt', 'nativeWindowsExecuted': False, 'success': False,
              'baseVersion': '0.10.1', 'appVersion': '0.11.0', 'starterSha256': args.starter_sha256,
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
