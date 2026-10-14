#!/usr/bin/env python3
"""Freeze the 0.16.1 UI patch, matching source and core-only 0.16.0 update.

No network fetch, compiler invocation, publication or Windows execution occurs
here. The workflow supplies hash-verified published inputs and compiled native
executables. All four published pack trees remain byte-for-byte unchanged.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import zipfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_update_090 import extract, read_json, require, sha256, verify, verify_inventory
import make_core_update
import package_split

VERSION = '0.16.1'
BASELINE_VERSION = '0.16.0'
BASELINE_SHA = 'f96e03e43cac92ba8ca9a0a3807eb671f9924d5e624cadbba94d1a5ca1309073'
BASELINE_BYTES = 17846873
SOURCE_SHA = 'f746f00a82675c2cf52364a3b4d040721c6d06ac5605488efbdc0376ef5b7e44'
SOURCE_BYTES = 47848425
COMPILER_SHA = 'bb7bb7654b33d5aa8712acb837c963b2e0c56352560c76105270a3268c665c21'
PACKS = {'align-0.4.0', 'align-0.4.1', 'bam-0.4.0', 'variants-0.4.0'}
SOURCE_ROOT = Path(__file__).resolve().parents[1]


def hashes(root, prefix):
    return {path.relative_to(root).as_posix(): sha256(path)
            for path in package_split.files(root / prefix)}


def verify_preserved(base, target, old, new):
    require(old['version'] == BASELINE_VERSION and new['version'] == VERSION, 'Unexpected patch version range.')
    for field in ('starter_packs', 'additional_packs'):
        require(old.get(field) == new.get(field), 'Published pack pins or inventories changed: ' + field)
    require({path.name for path in (base / 'packs').iterdir()} == PACKS, 'Unexpected published pack set.')
    counts = {}
    for prefix in ('packs', 'runtime'):
        original, candidate = hashes(base, prefix), hashes(target, prefix)
        require(original == candidate, 'Published ' + prefix + ' bytes changed.')
        counts[prefix] = len(original)
    for name in ('workspace/setup-profile.json', 'workspace/catalog-sources.json'):
        require((base / name).read_bytes() == (target / name).read_bytes(), 'Published selection/trust changed: ' + name)
    require(not any(row['path'].startswith('packs/') for row in new['files']), 'Core update cannot own packs.')
    return counts


def source_correspondence(source, starter, commit):
    """Compare every current source member with its named Git blob."""
    with zipfile.ZipFile(source) as zipped, zipfile.ZipFile(starter) as packaged:
        require(zipped.testzip() is None and packaged.testzip() is None, 'Candidate ZIP CRC failure.')
        inventory = json.loads(zipped.read('SOURCE-RECOVERY.json'))['current_source_files']
        paths = [row['path'].removeprefix('current/') for row in inventory]
        require(all(row['path'].startswith('current/') for row in inventory), 'Invalid source inventory prefix.')
        request = ''.join(commit + ':' + path + '\n' for path in paths).encode()
        objects = subprocess.run(['git', 'cat-file', '--batch'], cwd=SOURCE_ROOT, input=request,
                                 stdout=subprocess.PIPE, check=True).stdout
        position = 0
        for row, path in zip(inventory, paths):
            end = objects.index(b'\n', position)
            header = objects[position:end].decode().split()
            require(len(header) == 3 and header[1] == 'blob', 'Missing committed source: ' + path)
            size = int(header[2])
            committed = objects[end + 1:end + 1 + size]
            position = end + 1 + size + 1
            raw = zipped.read(row['path'])
            require(raw == committed and len(raw) == row['bytes'] and
                    hashlib.sha256(raw).hexdigest() == row['sha256'], 'Source mismatch: ' + path)
        require(position == len(objects), 'Unexpected source-object response.')
        modules = []
        for name in packaged.namelist():
            if name.startswith('native-workbench/workspace/') and name.endswith('.py'):
                relative = name.removeprefix('native-workbench/')
                require(packaged.read(name) == zipped.read('current/' + relative), 'Runtime/source mismatch: ' + relative)
                modules.append(relative)
        source_pin = json.loads(packaged.read('native-workbench/SOURCE-AVAILABILITY.json'))['sourceArtifact']
        require(source_pin['sha256'] == sha256(source) and source_pin['bytes'] == source.stat().st_size,
                'Source companion identity differs.')
    return {'sourceCommit': commit, 'currentFilesMatchCommit': len(inventory),
            'runtimeModulesMatchSource': len(modules), 'zipCrc': 'passed'}


def build(baseline, source_input, output, work, commit):
    require(re.fullmatch('[0-9a-f]{40}', commit), 'Exact source commit required.')
    require(subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=SOURCE_ROOT, text=True).strip() == commit,
            'Source commit must be the checked-out HEAD.')
    require(package_split.VERSION == VERSION, 'Application version differs from patch identity.')
    require(not output.exists() and not work.exists(), 'Use new output and work directories.')
    require(output != work and not output.is_relative_to(work) and not work.is_relative_to(output),
            'Output and work directories must not overlap.')
    inputs = [verify(baseline, BASELINE_SHA, BASELINE_BYTES), verify(source_input, SOURCE_SHA, SOURCE_BYTES)]
    launcher = SOURCE_ROOT / 'build/desktop/UpdateWorkbench.exe'
    require(launcher.is_file(), 'Compile the patch updater launcher first.')
    work.mkdir(parents=True)
    extract(baseline, work / 'baseline')
    base, target = work / 'baseline/native-workbench', work / 'target/native-workbench'
    old = read_json(base / 'manifest.json')
    verify_inventory(base, old['files'])
    output.mkdir(parents=True)
    source = output / ('native-workbench-' + VERSION + '-source.zip')
    source_metadata = package_split.build_sources(base, source, source_input)
    (output / 'source-metadata.json').write_text(json.dumps(source_metadata, indent=2) + '\n')
    package_split.stage(base, target, source_metadata, [base / 'packs/align-0.4.1'])
    new = read_json(target / 'manifest.json')
    preserved = verify_preserved(base, target, old, new)
    starter = output / ('native-workbench-' + VERSION + '-starter-windows.zip')
    package_split.starter_archive(target, starter)
    correspondence = source_correspondence(source, starter, commit)
    updater = work / 'updater'
    update_result = make_core_update.make(base, target, updater, launcher)
    update = output / ('native-workbench-' + VERSION + '-update-from-' + BASELINE_VERSION + '.zip')
    make_core_update.archive(updater, update)
    recipe = read_json(updater / 'update/update-manifest.json')
    verify_inventory(updater, read_json(updater / 'update-inventory.json')['files'])
    require(recipe['base_version'] == BASELINE_VERSION and recipe['target_version'] == VERSION, 'Unexpected updater range.')
    for operation in recipe['operations']:
        require((updater / 'update/blobs' / operation['blob']).read_bytes() == (target / operation['path']).read_bytes(),
                'Updater payload differs from frozen Starter.')
    rows = [{'file': path.name, 'bytes': path.stat().st_size, 'sha256': sha256(path)}
            for path in (source, starter, update)]
    record = {'schema': 1, 'status': 'unpublished review candidate; exact native Windows validation pending',
              'createdUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': commit,
              'appVersion': VERSION, 'baseVersion': BASELINE_VERSION, 'platform': platform.platform(),
              'published': False, 'nativeWindowsExecutedByBuilder': False, 'inputs': inputs,
              'compiler': 'LLVM-MinGW 20260922 UCRT', 'compilerArchiveSha256': COMPILER_SHA,
              'sourceCorrespondence': correspondence, 'preservedPublishedFiles': preserved,
              'starterPacks': new['starter_packs'], 'additionalPacks': new['additional_packs'],
              'preservedSetupProfileSha256': sha256(target / 'workspace/setup-profile.json'),
              'preservedCatalogueSourcesSha256': sha256(target / 'workspace/catalog-sources.json'),
              'nativeExecutables': {name: sha256(SOURCE_ROOT / 'build/desktop' / name) for name in
                                    ('DesktopWorkbench.exe', 'WorkbenchBridge.exe', 'UpdateWorkbench.exe')},
              'archives': rows, 'updater': {'applicationRebuilt': False, 'result': update_result,
                  'baseManifestSha256': sha256(base / 'manifest.json'), 'targetManifestSha256': sha256(target / 'manifest.json'),
                  'coreFilesVerified': len(new['files']), 'packsChanged': False,
                  'additionalPacksInstalledByUpdater': False, 'launcherSourceCommit': commit}}
    (output / 'BUILD-PROVENANCE.json').write_text(json.dumps(record, indent=2) + '\n')
    (output / 'SHA256SUMS.txt').write_text(''.join(row['sha256'] + '  ' + row['file'] + '\n' for row in rows))
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 'baseline-source', 'output', 'work'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    args = parser.parse_args()
    report = build(args.baseline.resolve(), args.baseline_source.resolve(), args.output.resolve(),
                   args.work.resolve(), args.source_commit)
    print(json.dumps(report, indent=2))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            for kind, suffix in (('starter', '-starter-windows.zip'), ('update', '-update-from-0.16.0.zip')):
                row = next(row for row in report['archives'] if row['file'].endswith(suffix))
                stream.write(kind + '_sha256=' + row['sha256'] + '\n')
                stream.write(kind + '_name=' + row['file'] + '\n')


if __name__ == '__main__':
    main()
