#!/usr/bin/env python3
"""Read-only audit of downloaded first-batch packs against an exact Git commit.

This verifies bytes and corresponding source, not native execution or publisher
trust. Run it on the downloaded Actions candidate, not a local preparation tree.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import struct
import subprocess
import tarfile
import zipfile

from validate_pack_release import inspect_release

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_PINS = {
    'prodigal': {'prodigal-2.6.3.tar.gz': '9caafa079a29ff8f02b5ea84729fec4ecf03975c9ccf4acade4909368b69f317'},
    'fasttree': {'FastTree.c': '975202a6b74c9996af871404ff043bb2152edcbda539035662514bc12d1f3431',
                 'FastTree-LICENSE.txt': '3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986'},
}


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_hash(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def members(archive):
    names = archive.namelist()
    require(len(names) == len({name.casefold() for name in names}), 'Duplicate ZIP members')
    for name in names:
        path = PurePosixPath(name)
        require(name and not path.is_absolute() and '\\' not in name and ':' not in name
                and all(part not in ('', '.', '..') for part in name.split('/')),
                'Unsafe ZIP member: ' + name)
    require(archive.testzip() is None, 'ZIP CRC failed')
    return set(names)


def verify_file(root, record):
    name = record['file']
    require(Path(name).name == name, 'Artifact must be an immediate filename')
    path = root / name
    require(path.is_file() and not path.is_symlink(), 'Missing regular artifact: ' + name)
    require(path.stat().st_size == record['bytes'] and file_hash(path) == record['sha256'],
            'Artifact identity mismatch: ' + name)
    return path


def git_files(commit):
    require(re.fullmatch(r'[a-f0-9]{40}', commit), 'Expected full Git commit')
    data = subprocess.check_output(['git', 'archive', '--format=tar', commit], cwd=ROOT)
    result = {}
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for member in archive:
            if member.isdir():
                continue
            require(member.isfile(), 'Unexpected nonregular Git source: ' + member.name)
            result[member.name] = archive.extractfile(member).read()
    return result


def pe_x64(data):
    require(len(data) > 64 and data[:2] == b'MZ', 'Tool is not a PE executable')
    offset = struct.unpack_from('<I', data, 60)[0]
    require(offset + 6 <= len(data) and data[offset:offset + 4] == b'PE\0\0'
            and struct.unpack_from('<H', data, offset + 4)[0] == 0x8664,
            'Tool is not a Windows x86-64 PE')


def source_correspondence(identity, pack, originals):
    """Connect the runtime payload to retained recipes, guard and build records."""
    paths = {
        'pack/licenses/guard.cpp': 'tools/' + identity + '/guard.cpp',
        'pack/licenses/fixtures.py': 'tools/' + identity + '/fixtures.py',
        'pack/licenses/build_' + identity + '_native.py': 'scripts/build_' + identity + '_native.py',
        'pack/licenses/prepare_' + identity + '_pack.py': 'scripts/prepare_' + identity + '_pack.py',
        'pack/PACK-README.md': 'docs/' + identity.upper() + '-PACK.md',
        'pack/licenses/' + ('Workbench-MIT.txt' if identity == 'prodigal' else 'Workbench-LICENSE.txt'): 'LICENSE',
    }
    for retained, original in paths.items():
        require(pack.read(retained) == originals[original], 'Pack retained source differs from Git: ' + original)
    provenance_name = 'provenance.json' if identity == 'prodigal' else 'build-provenance.json'
    build = json.loads(pack.read('pack/licenses/' + provenance_name))
    guard_key = 'guardSourceSha256' if identity == 'prodigal' else 'guardSha256'
    require(build['platform'] == 'windows-x86_64' and build['executionTestsPerformedByBuild'] is False,
            'Unexpected binary build platform or execution claim')
    require(build[guard_key] == digest(originals['tools/' + identity + '/guard.cpp']),
            'Compiled guard provenance differs from committed source')
    require(build['builderSha256'] == digest(originals['scripts/build_' + identity + '_native.py']),
            'Compiled recipe provenance differs from committed source')
    require(set(build['files']) == {identity + '.exe', identity + '-guard.exe'}, 'Unexpected build binary set')
    for name, record in build['files'].items():
        data = pack.read('pack/bin/' + name)
        require(len(data) == record['bytes'] and digest(data) == record['sha256'],
                'Pack executable differs from retained build record: ' + name)
    for name, checksum in UPSTREAM_PINS[identity].items():
        require(digest(pack.read('pack/licenses/' + name)) == checksum, 'Pinned corresponding source changed: ' + name)
    if identity == 'prodigal':
        require(build['sourceCommit'] == '004218fbeb2cf54fe12d88ec2eede6a27d70ebf7'
                and build['version'] == '2.6.3-workbench1', 'Unexpected Prodigal source/version')
        require(build['patchSha256'] == digest(pack.read('pack/licenses/workbench1.patch')),
                'Prodigal build patch identity differs')
    else:
        require(build['upstreamCommit'] == 'a780aa4f6a18791ea76c04afaf37aafe43e51d59'
                and build['upstreamVersion'] == '2.2.0' and build['serial'] is True
                and build['precision'] == 'double' and build['upstreamSourceUnmodified'] is True,
                'Unexpected FastTree source/version/build scope')
        for name in ('nucleotide.afa', 'protein.afa', 'truth.json', 'reference.json'):
            require(pack.read('pack/fixtures/' + name) == originals['tools/fasttree/fixtures/' + name],
                    'Pack scientific fixture differs from Git: ' + name)
    return {'retainedRecipeFilesMatchedToGit': len(paths), 'guardSourceBoundToBuild': True,
            'builderSourceBoundToBuild': True, 'binaryHashesMatchedToBuild': len(build['files']),
            'upstreamSourceHashesVerified': UPSTREAM_PINS[identity],
            'scope': 'Byte and provenance correspondence; not independent bit-identical recompilation.'}


def audit(candidate, commit):
    record = json.loads((candidate / 'BUILD-PROVENANCE.json').read_text(encoding='utf-8'))
    require(record['sourceCommit'] == commit, 'Build record refers to another commit')
    tree = subprocess.check_output(['git', 'rev-parse', commit + '^{tree}'], cwd=ROOT, text=True).strip()
    require(record['sourceTree'] == tree, 'Build tree differs from Git')
    require(record['published'] is False and record['nativeWindowsExecuted'] is False,
            'Freeze must remain unpublished build-time evidence')
    require(set(record['packs']) == {'prodigal', 'fasttree'}, 'Unexpected pack set')
    companion = verify_file(candidate, record['sourceCompanion'])
    originals = git_files(commit)
    result = {'schema': 1, 'kind': 'downloaded-pack-source-audit', 'sourceCommit': commit,
              'sourceTree': tree, 'nativeWindowsExecuted': False, 'published': False,
              'success': False, 'packs': {}, 'sourceCompanion': record['sourceCompanion']}
    with zipfile.ZipFile(companion) as source:
        names = members(source)
        inventory = json.loads(source.read('SOURCE-INVENTORY.json'))
        require(inventory['sourceCommit'] == commit and inventory['schema'] == 1,
                'Source inventory identity differs')
        indexed = {item['path']: item for item in inventory['files']}
        require(len(indexed) == len(inventory['files']), 'Duplicate source inventory entries')
        require(names == set(indexed) | {'SOURCE-INVENTORY.json', 'BUILD-PROVENANCE.json'},
                'Source companion contains missing or undeclared files')
        for name, item in indexed.items():
            data = source.read(name)
            require(len(data) == item['bytes'] and digest(data) == item['sha256'],
                    'Source inventory mismatch: ' + name)
        embedded = json.loads(source.read('BUILD-PROVENANCE.json'))
        require(embedded == {key: value for key, value in record.items() if key != 'sourceCompanion'},
                'Embedded and external build records differ')
        require({name[7:] for name in names if name.startswith('source/')} == set(originals),
                'Git and companion source file sets differ')
        for name, data in originals.items():
            require(source.read('source/' + name) == data, 'Source differs from committed Git bytes: ' + name)
        result['gitSourceFilesVerified'] = len(originals)
        result['companionInventoryFilesVerified'] = len(indexed)
        for identity, pack_record in record['packs'].items():
            pack_path = verify_file(candidate, pack_record)
            inspected = inspect_release(pack_path)
            require(inspected == pack_record['staticValidation'], 'Static pack audit differs')
            require((inspected['id'], inspected['version']) == (identity, '1.0.0'), 'Wrong pack identity')
            with zipfile.ZipFile(pack_path) as pack:
                pack_names = members(pack)
                licence_names = {name for name in pack_names if name.startswith('pack/licenses/')}
                prefix = 'corresponding-sources/' + identity + '/'
                require({prefix + name[len('pack/licenses/'):] for name in licence_names}
                        == {name for name in names if name.startswith(prefix)},
                        'Pack and companion corresponding-source inventories differ')
                for name in licence_names:
                    require(pack.read(name) == source.read(prefix + name[len('pack/licenses/'):]),
                            'Corresponding source differs from pack: ' + name)
                executables = [name for name in pack_names if name.startswith('pack/bin/') and name.endswith('.exe')]
                require(len(executables) == 2, 'Expected upstream tool and native guard')
                for name in executables:
                    pe_x64(pack.read(name))
                correspondence = source_correspondence(identity, pack, originals)
                result['packs'][identity] = {**pack_record, 'licenceSourceFilesMatched': len(licence_names),
                                             'x64ExecutablesVerified': executables,
                                             'sourceCorrespondence': correspondence}
    expected_sums = {item['file']: item['sha256'] for item in [*record['packs'].values(), record['sourceCompanion']]}
    lines = (candidate / 'SHA256SUMS.txt').read_text(encoding='ascii').splitlines()
    pairs = [line.split('  ', 1) for line in lines]
    require(len(pairs) == len(expected_sums) and all(len(pair) == 2 for pair in pairs)
            and {name: checksum for checksum, name in pairs} == expected_sums,
            'Checksum manifest differs from frozen artifacts')
    result['success'] = True
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = audit(args.candidate.resolve(), args.source_commit)
    except Exception as exc:
        result = {'schema': 1, 'success': False, 'sourceCommit': args.source_commit, 'error': str(exc),
                  'nativeWindowsExecuted': False}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'success': result['success'], 'report': str(args.report)}))
    return 0 if result['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
