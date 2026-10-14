#!/usr/bin/env python3
"""Derive a 0.10.0-to-0.10.1 core update from an exact candidate starter.

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

BASELINE_SHA = '659a08911cec65b8dc1ce0dd9f47fea25350a39b619c7f0aea663bae71a871ae'
BASELINE_BYTES = 17028340
BASELINE_URL = ('https://github.com/comparativechrono/workbench/releases/download/app-v0.10.0/'
                'native-workbench-0.10.0-starter-windows.zip')
UPDATE_NAME = 'native-workbench-0.10.1-update-from-0.10.0.zip'


def pack_hashes(root):
    return {path.relative_to(root).as_posix(): sha256(path)
            for path in sorted((root / 'packs').rglob('*')) if path.is_file()}


def build(starter, starter_sha, baseline, launcher, launcher_sha, source_commit, output, work):
    require(re.fullmatch(r'[0-9a-f]{40}', source_commit) is not None, 'Expected exact source commit SHA.')
    require(all(re.fullmatch(r'[0-9a-f]{64}', value) for value in (starter_sha, launcher_sha)),
            'Expected exact candidate input SHA-256 values.')
    require(not output.exists() and not work.exists(), 'Choose new output and work directories.')
    require(output != work and not output.is_relative_to(work) and not work.is_relative_to(output),
            'Output and work directories must not overlap.')
    inputs = [verify(starter, starter_sha), verify(baseline, BASELINE_SHA, BASELINE_BYTES),
              verify(launcher, launcher_sha)]
    work.mkdir(parents=True)
    extract(baseline, work / 'baseline')
    extract(starter, work / 'target')
    base, target = work / 'baseline/native-workbench', work / 'target/native-workbench'
    old, new = read_json(base / 'manifest.json'), read_json(target / 'manifest.json')
    require(old['version'] == '0.10.0' and new['version'] == '0.10.1', 'Unexpected app version.')
    verify_inventory(base, old['files'])
    verify_inventory(target, new['files'])
    require(pack_hashes(base) == pack_hashes(target), 'Starter pack bytes changed; updater scope is core only.')
    require({'workspace/setup_manager.py', 'workspace/setup-profile.json', 'workspace/catalog-sources.json'} <=
            {entry['path'] for entry in new['files']}, 'Target lacks inventoried tool setup components.')
    for name in ('workspace/catalog-sources.json', 'workspace/setup-profile.json'):
        require((base / name).read_bytes() == (target / name).read_bytes(),
                'Patch must preserve the published production trust and pack selection: ' + name)
    output.mkdir(parents=True)
    result = make(base, target, work / 'new-updater', launcher)
    artifact = archive(work / 'new-updater', output / UPDATE_NAME)
    recipe = read_json(work / 'new-updater/update/update-manifest.json')
    verify_inventory(work / 'new-updater', read_json(work / 'new-updater/update-inventory.json')['files'])
    require(recipe['base_version'] == '0.10.0' and recipe['target_version'] == '0.10.1',
            'Unexpected update range.')
    for operation in recipe['operations']:
        require((work / 'new-updater/update/blobs' / operation['blob']).read_bytes() ==
                (target / operation['path']).read_bytes(), 'Update payload differs from candidate starter.')
    artifact = {'file': UPDATE_NAME, 'bytes': artifact['bytes'], 'sha256': artifact['sha256']}
    report = {'schema': 1, 'createdUtc': datetime.now(timezone.utc).isoformat(),
              'sourceCommit': source_commit, 'workflowRun': os.environ.get('GITHUB_RUN_ID'),
              'platform': platform.platform(), 'applicationRebuilt': False,
              'nativeWindowsExecutedByBuilder': False, 'baseVersion': '0.10.0',
              'targetVersion': '0.10.1', 'inputs': inputs, 'baselineUrl': BASELINE_URL,
              'baselineSha256': BASELINE_SHA, 'starterSha256': starter_sha,
              'updateSha256': artifact['sha256'], 'archive': artifact,
              'baseManifestSha256': sha256(base / 'manifest.json'),
              'targetManifestSha256': sha256(target / 'manifest.json'),
              'launcherSha256': launcher_sha, 'coreFilesVerified': len(new['files']),
              'unchangedPackFiles': len(pack_hashes(base)),
              'productionTrustUnchanged': True, 'setupSelectionUnchanged': True, 'result': result,
              'scope': 'Core update derived from the hash-pinned candidate; application and pack payloads are unchanged. Requires separate native Windows validation.'}
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
