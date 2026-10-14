#!/usr/bin/env python3
"""Package the 0.8.0 update from the immutable, accepted 0.9.0 app bytes.

This deliberately does not build the application or change its accepted starter
and source archives. Its native launcher and runtime come from that candidate.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import stat
import sys
import zipfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_core_update import make, archive

SOURCE_COMMIT = 'beea34ab29f3e7cb9a7e79dbcfa11c89f40ee59d'
STARTER_NAME = 'native-workbench-0.9.0-starter-windows.zip'
STARTER_SHA = 'c2661c144e073c4efdd190ffd186bacd9398b6413b81770d7a057c3947eecf02'
BASELINE_SHA = 'df001a80033ff8e834045ec683c79672e0efdbd4880fb89fca8bf8c36d830fdc'
OLD_UPDATE_NAME = 'native-workbench-0.9.0-update-from-0.6.0.zip'
OLD_UPDATE_SHA = 'eed778882bed560e765c1f2c03d6473b2ea07f2b219e4bd81bff7297e67b177d'
UPDATE_NAME = 'native-workbench-0.9.0-update-from-0.8.0.zip'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def verify(path, expected, size=None):
    require(Path(path).is_file() and sha256(path) == expected and
            (size is None or Path(path).stat().st_size == size), 'Frozen input differs: ' + str(path))
    return {'file': Path(path).name, 'bytes': Path(path).stat().st_size, 'sha256': expected}


def extract(path, destination):
    require(not destination.exists(), 'Extraction must use a new directory.')
    with zipfile.ZipFile(path) as zipped:
        seen = set()
        for item in zipped.infolist():
            name = item.filename.rstrip('/')
            parts = PurePosixPath(name).parts
            require(name and not name.startswith('/') and '\\' not in name and ':' not in name and
                    all(part not in ('', '.', '..') for part in parts) and
                    name.casefold() not in seen and not stat.S_ISLNK(item.external_attr >> 16),
                    'Unsafe or duplicate archive member: ' + name)
            seen.add(name.casefold())
        require(zipped.testzip() is None, 'Archive CRC failure: ' + str(path))
        zipped.extractall(destination)


def verify_inventory(root, items):
    for item in items:
        verify(root / item['path'], item['sha256'], item['bytes'])


def build(candidate, baseline, output, work, validation_commit):
    require(not output.exists() and not work.exists(), 'Choose new output and work directories.')
    starter, old_update = candidate / STARTER_NAME, candidate / OLD_UPDATE_NAME
    inputs = [verify(starter, STARTER_SHA, 17002821),
              verify(baseline, BASELINE_SHA, 16948940),
              verify(old_update, OLD_UPDATE_SHA, 12951447)]
    require(read_json(candidate / 'BUILD-PROVENANCE.json')['sourceCommit'] == SOURCE_COMMIT,
            'Accepted candidate source identity changed.')
    work.mkdir(parents=True)
    extract(baseline, work / 'baseline')
    extract(starter, work / 'target')
    extract(old_update, work / 'old-updater')
    base, target = work / 'baseline/native-workbench', work / 'target/native-workbench'
    old, new = read_json(base / 'manifest.json'), read_json(target / 'manifest.json')
    require(old['version'] == '0.8.0' and new['version'] == '0.9.0', 'Unexpected app version.')
    verify_inventory(base, old['files'])
    verify_inventory(target, new['files'])
    verify_inventory(work / 'old-updater', read_json(work / 'old-updater/update-inventory.json')['files'])
    # Updating the baseline must not quietly introduce new updater code either.
    source = Path(__file__).resolve().parents[1]
    for source_name, frozen_name in [('apply_core_update.py', 'apply_workspace_update.py'),
                                     ('apply_desktop_update.py', 'apply_desktop_update.py')]:
        require((source / 'scripts' / source_name).read_bytes() ==
                (work / 'old-updater/update' / frozen_name).read_bytes(),
                'Updater implementation differs from the accepted candidate: ' + source_name)
    def packs(root):
        return {path.relative_to(root).as_posix(): sha256(path)
                for path in sorted((root / 'packs').rglob('*')) if path.is_file()}
    require(packs(base) == packs(target), 'Starter pack bytes changed; updater scope is core only.')
    output.mkdir(parents=True)
    result = make(base, target, work / 'new-updater', work / 'old-updater/UpdateWorkbench.exe')
    artifact = archive(work / 'new-updater', output / UPDATE_NAME)
    recipe = read_json(work / 'new-updater/update/update-manifest.json')
    verify_inventory(work / 'new-updater', read_json(work / 'new-updater/update-inventory.json')['files'])
    require(recipe['base_version'] == '0.8.0' and recipe['target_version'] == '0.9.0',
            'Unexpected update range.')
    for operation in recipe['operations']:
        require((work / 'new-updater/update/blobs' / operation['blob']).read_bytes() ==
                (target / operation['path']).read_bytes(), 'Update payload differs from accepted starter.')
    artifact = {'file': UPDATE_NAME, 'bytes': artifact['bytes'], 'sha256': artifact['sha256']}
    report = {'schema': 1, 'createdUtc': datetime.now(timezone.utc).isoformat(),
              'sourceCommit': SOURCE_COMMIT, 'packagingCommit': validation_commit,
              'workflowRun': os.environ.get('GITHUB_RUN_ID'), 'platform': platform.platform(),
              'applicationRebuilt': False, 'nativeWindowsExecutedByBuilder': False,
              'baseVersion': '0.8.0', 'targetVersion': '0.9.0', 'inputs': inputs,
              'baselineSha256': BASELINE_SHA, 'starterSha256': STARTER_SHA,
              'updateSha256': artifact['sha256'], 'archive': artifact,
              'baseManifestSha256': sha256(base / 'manifest.json'),
              'targetManifestSha256': sha256(target / 'manifest.json'),
              'launcherSha256': sha256(work / 'new-updater/UpdateWorkbench.exe'),
              'coreFilesVerified': len(new['files']), 'unchangedPackFiles': len(packs(base)),
              'result': result,
              'scope': 'App-only update derived from accepted starter; target files, launcher and updater code are unchanged.'}
    (output / 'BUILD-UPDATE-PROVENANCE.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    (output / 'SHA256SUMS.txt').write_text(artifact['sha256'] + '  ' + UPDATE_NAME + '\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--validation-commit', required=True)
    args = parser.parse_args()
    report = build(args.candidate.resolve(), args.baseline.resolve(), args.output.resolve(),
                   args.work.resolve(), args.validation_commit)
    print(json.dumps(report, indent=2))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
            stream.write('update_sha256=' + report['updateSha256'] + '\n')


if __name__ == '__main__':
    main()
