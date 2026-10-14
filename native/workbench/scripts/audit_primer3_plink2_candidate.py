#!/usr/bin/env python3
"""Read-only audit of downloaded Primer3/PLINK2 packs against an exact Git commit.

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


UPSTREAM_PINS = {
    'primer3': {'primer3-2.6.1.tar.gz': 'c981e42765ceb525f56607c6a7cf989ac5068483731c6e083b1e9fb22816463b'},
    'plink2': {
        'plink-ng-2.00a7.12.tar.gz': 'bcfa30a7cfca2e117bacb94c94a2248ab190396ff8d2711f600ef42ebf5f9198',
        'zlib-1.3.2.tar.gz': 'bb329a0a2cd0274d05519d61c667c062e06990d72e125ee2dfa8de64f0119d16',
    },
}
UPSTREAM_IDENTITIES = {
    'primer3': ('2.6.1', '7f9f17d6012f404e83bbf0f931a4d06eb4af465b'),
    'plink2': ('2.0.0-a.7.12', '5c1f185d4144e62fa23087d68760162f712cd2a8'),
}


def source_correspondence(identity, pack, originals):
    """Bind runtime bytes to retained recipes, guards and pinned corresponding source."""
    require(identity in UPSTREAM_PINS and UPSTREAM_PINS[identity], 'Upstream pins not established')
    paths = {
        'pack/licenses/guard.cpp': 'tools/' + identity + '/guard.cpp',
        'pack/licenses/fixtures.py': 'tools/' + identity + '/fixtures.py',
        'pack/licenses/build_' + identity + '_native.py': 'scripts/build_' + identity + '_native.py',
        'pack/licenses/prepare_' + identity + '_pack.py': 'scripts/prepare_' + identity + '_pack.py',
        'pack/PACK-README.md': 'docs/' + identity.upper() + '-PACK.md',
        'pack/licenses/Workbench-LICENSE.txt': 'LICENSE',
    }
    recorder = 'tools/' + identity + '/record_reference.py'
    if recorder in originals:
        paths['pack/licenses/record_reference.py'] = recorder
    for retained, original in paths.items():
        require(pack.read(retained) == originals[original], 'Pack retained source differs from Git: ' + original)
    build = json.loads(pack.read('pack/licenses/build-provenance.json'))
    require(build['platform'] == 'windows-x86_64' and build['executionTestsPerformedByBuild'] is False,
            'Unexpected binary build platform or execution claim')
    require(build['upstreamScientificAlgorithmsUnmodified'] is True, 'Scientific source modification not reviewed')
    version, commit = UPSTREAM_IDENTITIES[identity]
    require(build['version'] == version and build['upstreamVersion'] == version and
            build['sourceCommit'] == commit and build['upstreamCommit'] == commit and
            build['upstreamSourceUnmodified'] is True, 'Unexpected upstream identity or modification')
    require(build['builderSha256'] == digest(originals['scripts/build_' + identity + '_native.py']),
            'Compiled recipe provenance differs from committed source')
    require(build['guardSourceSha256'] == digest(originals['tools/' + identity + '/guard.cpp']),
            'Compiled guard provenance differs from committed source')
    science = 'primer3_core.exe' if identity == 'primer3' else 'plink2.exe'
    require(set(build['files']) == {science, identity + '-guard.exe'}, 'Unexpected build binary set')
    for name, record in build['files'].items():
        data = pack.read('pack/bin/' + name)
        require(len(data) == record['bytes'] and digest(data) == record['sha256'], 'Pack executable differs from build: ' + name)
        pe_x64(data)
        optional = struct.unpack_from('<I', data, 60)[0] + 24
        require(struct.unpack_from('<H', data, optional)[0] == 0x20b and
                struct.unpack_from('<QQ', data, optional + 72) == (8388608, 65536),
                'Unexpected PE stack reserve/commit: ' + name)
    for name, checksum in UPSTREAM_PINS[identity].items():
        require(digest(pack.read('pack/licenses/' + name)) == checksum and build['sources'][name]['sha256'] == checksum,
                'Pinned corresponding source changed: ' + name)
    require(set(build['sources']) == set(UPSTREAM_PINS[identity]), 'Unreviewed upstream dependency')
    for name, checksum in build['compilerNotices'].items():
        require(digest(pack.read('pack/licenses/compiler-' + name)) == checksum, 'Compiler/runtime notice differs')
    configuration_count = 0
    if identity == 'primer3':
        require(build['serial'] is True and build['openmp'] is False, 'Unexpected Primer3 execution scope')
        source_bytes = pack.read('pack/licenses/primer3-2.6.1.tar.gz')
        with tarfile.open(fileobj=io.BytesIO(source_bytes)) as source:
            prefix = 'primer3-' + commit + '/src/primer3_config/'
            tables = {m.name.removeprefix(prefix): source.extractfile(m).read()
                      for m in source.getmembers() if m.isfile() and m.name.startswith(prefix)}
            require({name: digest(data) for name, data in tables.items()} == build['configurationFiles'],
                    'Thermodynamic configuration does not match pinned source')
            require({name.removeprefix('pack/bin/primer3_config/') for name in pack.namelist()
                     if name.startswith('pack/bin/primer3_config/')} == set(tables),
                    'Thermodynamic runtime file set differs')
            for name, data in tables.items():
                require(pack.read('pack/bin/primer3_config/' + name) == data, 'Changed thermodynamic table: ' + name)
            configuration_count = len(tables)
            for name, target in [('LICENSE', 'Primer3-GPL-2.0.txt'),
                                 ('src/LICENSE_GPL3_for_Amplicon3', 'Amplicon3-GPL-3.0.txt'),
                                 ('src/amplicontm.c', 'Amplicon3-source-notices.c')]:
                require(pack.read('pack/licenses/' + target) ==
                        source.extractfile('primer3-' + commit + '/' + name).read(),
                        'Upstream component notice differs: ' + target)
    else:
        require(build['lapack'] is False, 'Unexpected PLINK2 LAPACK build scope')
        with tarfile.open(fileobj=io.BytesIO(pack.read('pack/licenses/plink-ng-2.00a7.12.tar.gz'))) as source:
            for relative, name in [('COPYING', 'PLINK2-GPLv3.txt'), ('COPYING.LESSER', 'PLINK2-LGPLv3.txt'),
                                   ('include/LICENSE.QD', 'QD-LICENSE.txt'), ('simde/COPYING', 'SIMDe-MIT.txt'),
                                   ('include/SFMT.c', 'SFMT-source-notices.c'),
                                   ('libdeflate/COPYING', 'libdeflate-MIT.txt'), ('zstd/COPYING', 'zstd-GPLv2.txt'),
                                   ('zstd/LICENSE', 'zstd-BSD.txt')]:
                require(pack.read('pack/licenses/' + name) ==
                        source.extractfile('plink-ng-' + commit + '/2.0/' + relative).read(),
                        'Upstream component notice differs: ' + name)
        with tarfile.open(fileobj=io.BytesIO(pack.read('pack/licenses/zlib-1.3.2.tar.gz'))) as source:
            require(pack.read('pack/licenses/zlib-LICENSE.txt') == source.extractfile('zlib-1.3.2/LICENSE').read(),
                    'Zlib notice differs')
    prefix = 'tools/' + identity + '/fixtures/'
    fixtures = {name.removeprefix(prefix): data for name, data in originals.items() if name.startswith(prefix)}
    require({name.removeprefix('pack/fixtures/') for name in pack.namelist() if name.startswith('pack/fixtures/')} == set(fixtures),
            'Fixture file sets differ')
    for name, data in fixtures.items():
        require(pack.read('pack/fixtures/' + name) == data, 'Fixture differs from Git: ' + name)
    return {'retainedRecipeFilesMatchedToGit': len(paths), 'guardSourceBoundToBuild': True,
            'builderSourceBoundToBuild': True, 'binaryHashesMatchedToBuild': len(build['files']),
            'upstreamSourceHashesVerified': UPSTREAM_PINS[identity], 'fixturesMatchedToGit': len(fixtures),
            'runtimeConfigurationFilesMatchedToUpstream': configuration_count,
            'scope': 'Byte and provenance correspondence; not independent bit-identical recompilation.'}


def audit(candidate, commit):
    record = json.loads((candidate / 'BUILD-PROVENANCE.json').read_text(encoding='utf-8'))
    require(record['sourceCommit'] == commit, 'Build record refers to another commit')
    tree = subprocess.check_output(['git', 'rev-parse', commit + '^{tree}'], cwd=ROOT, text=True).strip()
    require(record['sourceTree'] == tree, 'Build tree differs from Git')
    require(record['published'] is False and record['nativeWindowsExecuted'] is False,
            'Freeze must remain unpublished build-time evidence')
    require(set(record['packs']) == {'primer3', 'plink2'}, 'Unexpected pack set')
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
