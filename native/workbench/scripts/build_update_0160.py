#!/usr/bin/env python3
"""Derive a 0.11.0-to-0.16.0 core update from an exact candidate starter.

The published baseline has a fixed identity. Candidate inputs must be supplied
with their build-record hashes. This packages an update without rebuilding the
application, changing pack bytes, fetching network inputs or running Windows.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_update_090 import extract, read_json, require, sha256, verify, verify_inventory
from make_core_update import make, archive

BASELINE_SHA = 'e816e2f7cd5efe98af752fbf072fab00344ebaa2b6963795c2fbf4a86b5fa81c'
BASELINE_BYTES = 17044022
BASELINE_URL = ('https://github.com/comparativechrono/workbench/releases/download/app-v0.11.0/'
                'native-workbench-0.11.0-starter-windows.zip')
SOURCE_COMMIT = 'e855dc4396e0c16ae35f4e840eb9cc734adb4441'
STARTER_SHA = 'f96e03e43cac92ba8ca9a0a3807eb671f9924d5e624cadbba94d1a5ca1309073'
STARTER_BYTES = 17846873
ALIGN_SHA = '3a08cf061f0b62c5502d1420115db3fcae2b04bf695ad3cfd1c3063de0fafa02'
ALIGN_MANIFEST_SHA = '7f8f36efbfd6a8255a98eabb06746fbcc5bbdb872f392a65ca3e79a586d04939'
UPDATE_NAME = 'native-workbench-0.16.0-update-from-0.11.0.zip'


def pack_hashes(root):
    return {path.relative_to(root).as_posix(): sha256(path)
            for path in sorted((root / 'packs').rglob('*')) if path.is_file()}



def verify_pack_scope(base, target, old, new):
    """Permit only the exact separately inventoried addition, never replace packs."""
    before, after = pack_hashes(base), pack_hashes(target)
    require(old['starter_packs'] == new['starter_packs'], 'Published Starter pins changed.')
    require(not old.get('additional_packs'), 'Unexpected baseline additional packs.')
    require(all(after.get(name) == digest for name, digest in before.items()),
            'Published Starter pack bytes changed; updater scope is core only.')
    additional = new.get('additional_packs', [])
    require(len(additional) == 1 and additional[0].get('id') == 'align' and
            additional[0].get('version') == '0.4.1' and additional[0].get('folder') == 'packs/align-0.4.1' and
            additional[0].get('manifestSha256') == ALIGN_MANIFEST_SHA,
            'Unexpected independently owned target pack.')
    declared = {additional[0]['folder'] + '/' + item['path']: item['sha256']
                for item in additional[0]['files']}
    require(len(declared) == len(additional[0]['files']) and declared,
            'Additional pack inventory is empty or duplicated.')
    require(declared.get('packs/align-0.4.1/pack.ini') == ALIGN_MANIFEST_SHA,
            'Additional pack manifest does not match its pinned identity.')
    excluded = {name: digest for name, digest in after.items() if name not in before}
    require(excluded == declared, 'Additional pack bytes differ from its exact independent inventory.')
    require(not any(item['path'].startswith('packs/') for item in new['files']),
            'An independently owned pack cannot be a core update destination.')
    return before, excluded


def build(starter, starter_sha, baseline, launcher, launcher_sha, source_commit, output, work):
    require(source_commit == SOURCE_COMMIT, 'Expected the accepted application source commit.')
    require(starter_sha == STARTER_SHA, 'Expected the accepted starter identity.')
    require(all(re.fullmatch(r'[0-9a-f]{64}', value) for value in (starter_sha, launcher_sha)),
            'Expected exact candidate input SHA-256 values.')
    require(not output.exists() and not work.exists(), 'Choose new output and work directories.')
    require(output != work and not output.is_relative_to(work) and not work.is_relative_to(output),
            'Output and work directories must not overlap.')
    inputs = [verify(starter, starter_sha, STARTER_BYTES), verify(baseline, BASELINE_SHA, BASELINE_BYTES),
              verify(launcher, launcher_sha)]
    work.mkdir(parents=True)
    extract(baseline, work / 'baseline')
    extract(starter, work / 'target')
    base, target = work / 'baseline/native-workbench', work / 'target/native-workbench'
    old, new = read_json(base / 'manifest.json'), read_json(target / 'manifest.json')
    require(old['version'] == '0.11.0' and new['version'] == '0.16.0', 'Unexpected app version.')
    verify_inventory(base, old['files'])
    verify_inventory(target, new['files'])
    preserved_packs, excluded_packs = verify_pack_scope(base, target, old, new)
    require({'workspace/setup_manager.py', 'workspace/setup-profile.json', 'workspace/catalog-sources.json'} <=
            {entry['path'] for entry in new['files']}, 'Target lacks inventoried tool setup components.')
    for name in ('workspace/catalog-sources.json', 'workspace/setup-profile.json'):
        require((base / name).read_bytes() == (target / name).read_bytes(),
                'Update must preserve the published production trust and pack selection: ' + name)
    output.mkdir(parents=True)
    result = make(base, target, work / 'new-updater', launcher)
    artifact = archive(work / 'new-updater', output / UPDATE_NAME)
    recipe = read_json(work / 'new-updater/update/update-manifest.json')
    verify_inventory(work / 'new-updater', read_json(work / 'new-updater/update-inventory.json')['files'])
    require(recipe['base_version'] == '0.11.0' and recipe['target_version'] == '0.16.0',
            'Unexpected update range.')
    for operation in recipe['operations']:
        require((work / 'new-updater/update/blobs' / operation['blob']).read_bytes() ==
                (target / operation['path']).read_bytes(), 'Update payload differs from candidate starter.')
    artifact = {'file': UPDATE_NAME, 'bytes': artifact['bytes'], 'sha256': artifact['sha256']}
    report = {'schema': 1, 'createdUtc': datetime.now(timezone.utc).isoformat(),
              'sourceCommit': source_commit, 'packagingCommit': os.environ.get('GITHUB_SHA'),
              'workflowRun': os.environ.get('GITHUB_RUN_ID'),
              'platform': platform.platform(), 'applicationRebuilt': False,
              'nativeWindowsExecutedByBuilder': False, 'baseVersion': '0.11.0',
              'targetVersion': '0.16.0', 'inputs': inputs, 'baselineUrl': BASELINE_URL,
              'baselineSha256': BASELINE_SHA, 'starterSha256': starter_sha,
              'updateSha256': artifact['sha256'], 'archive': artifact,
              'baseManifestSha256': sha256(base / 'manifest.json'),
              'targetManifestSha256': sha256(target / 'manifest.json'),
              'launcherSha256': launcher_sha,
              'launcherSourceCommit': SOURCE_COMMIT,
              'updaterImplementationSha256': {name: sha256(Path(__file__).resolve().parent / name)
                                               for name in ('apply_core_update.py', 'apply_desktop_update.py', 'make_core_update.py')}, 'coreFilesVerified': len(new['files']),
              'unchangedPackFiles': len(preserved_packs),
              'excludedAdditionalPackFiles': excluded_packs,
              'additionalPacksInstalledByUpdater': False,
              'productionTrustUnchanged': True, 'setupSelectionUnchanged': True, 'result': result,
              'scope': 'Core update derived from the hash-pinned candidate without rebuilding the app. Existing packs and user files remain independent; align 0.4.1 is not installed by this updater and requires explicit separate import. Requires native Windows validation.'}
    (output / 'BUILD-UPDATE-PROVENANCE.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    (output / 'SHA256SUMS.txt').write_text(artifact['sha256'] + '  ' + UPDATE_NAME + '\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('starter', 'baseline', 'launcher', 'output', 'work'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('starter-sha256', 'launcher-sha256', 'source-commit'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    report = build(args.starter.resolve(), args.starter_sha256, args.baseline.resolve(),
                   args.launcher.resolve(), args.launcher_sha256, args.source_commit,
                   args.output.resolve(), args.work.resolve())
    print(json.dumps(report, indent=2))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
            stream.write('update_sha256=' + report['updateSha256'] + '\n')


if __name__ == '__main__':
    main()
